"""MultiWAN V3 controlled-preview core. No network changes without --apply.

Live mode implements baseline ECMP, static IP pool NAT and WAN failure handling.
Destination-specific diagnostics and IP switching are simulated/recorded only.
"""
import argparse
import collections
import ipaddress
import json
import os
from pathlib import Path
from .telemetry import connect, log_sample, log_decision
import shutil
import subprocess
import tempfile
import time
import datetime

STATE_DIR = Path(os.environ.get('MULTIWAN_STATE_DIR', '/var/lib/multiwan'))
CONFIG = Path(os.environ.get('MULTIWAN_CONFIG', '/etc/multiwan/config.json'))


def load_config(path=CONFIG):
    from .config_portal import validate_candidate
    return validate_candidate(json.loads(Path(path).read_text()))


def atomic_json(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile('w',dir=path.parent,delete=False) as f:
        json.dump(payload,f,ensure_ascii=False,indent=2)
        tmp=f.name
    os.replace(tmp,path)


def current_state(c):
    p=STATE_DIR/'state.json'
    if p.exists():
        try:
            s=json.loads(p.read_text())
            if set(s.get('wans',{})) == {w['name'] for w in c['wans']}: return s
        except (ValueError,OSError): pass
    return {'updated':None,'mode':'dry-run','wans':{w['name']:{'healthy':True,'fail':0,'success':0,'ip_index':0,'ip_health':{ip:'unknown' for ip in w['addresses']}} for w in c['wans']},'events':[]}


def event(s,message):
    s['events']=(s.get('events',[])+[{'at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'message':message}])[-200:]


def route_command(c, healthy):
    cmd=['ip','-4','route','replace','default']
    for w in c['wans']:
        if w['name'] in healthy:
            cmd+=['nexthop','via',w['gateway'],'dev',w['interface'],'weight',str(w.get('weight',1))]
    return cmd if any(w['name'] in healthy for w in c['wans']) else None


def nft_script(c, s):
    """Own table only; route selection is via ECMP. Fixed-range SNAT for first version.
    IP source failover is not claimed in live mode until verified per-target signals exist.
    """
    lan=c['lan']['interface']; subnet=c['lan']['subnet']
    lines=['table ip multiwan_v3 {',
           ' chain forward { type filter hook forward priority 0; policy accept;',
           f' iifname "{lan}" ip saddr {subnet} ct state new,established,related accept',
           f' oifname "{lan}" ct state established,related accept',
           ' }',
           ' chain postrouting { type nat hook postrouting priority srcnat; policy accept;']
    for w in c['wans']:
        # Stable SNAT one public address per WAN in live preview; other IPs are bound for future allocation.
        lines.append(f' oifname "{w["interface"]}" ip saddr {subnet} snat to {w["addresses"][0]}')
    lines+=[' }','}']
    return '\n'.join(lines)+'\n'


def run(cmd,check=True):
    return subprocess.run(cmd,text=True,capture_output=True,check=check)


def check_environment(c):
    issues=[]
    for tool in ('ip','nft','ping','sysctl'):
        if not shutil.which(tool): issues.append('missing executable: '+tool)
    for w in c['wans']:
        if not Path('/sys/class/net',w['interface']).exists():
            issues.append('missing interface '+w['interface'])
    if not Path('/sys/class/net',c['lan']['interface']).exists():
        issues.append('missing LAN '+c['lan']['interface'])
    if not Path('/proc/sys/net/ipv4/ip_forward').exists():
        issues.append('IPv4 forwarding unavailable')
    return issues


def check_lan_guard(c, *, route_output=None, address_output=None):
    """Fail closed unless protected LAN is configured and main table has a direct LAN route.

    This is a preflight, not a replacement for out-of-band access and automatic rollback.
    """
    lan = c['lan']
    iface = lan['interface']
    required = ipaddress.ip_network(lan['subnet'], strict=False)
    configured = ipaddress.ip_interface(lan['address'])
    if configured.network != required:
        raise RuntimeError('LAN guard: LAN address prefix differs from configured subnet')
    if address_output is None:
        address_output=run(['ip','-j','-4','addr','show','dev',iface]).stdout
    records=json.loads(address_output)
    addr_ok=any(item.get('local')==str(configured.ip) and item.get('prefixlen')==configured.network.prefixlen
                for rec in records for item in rec.get('addr_info',[]))
    if not addr_ok:
        raise RuntimeError('LAN guard: configured LAN address missing from '+iface)
    if route_output is None:
        route_output=run(['ip','-j','-4','route','show','table','main']).stdout
    routes=json.loads(route_output)
    route_ok=any(r.get('dst')==str(required) and r.get('dev')==iface and not r.get('gateway')
                 for r in routes)
    if not route_ok:
        raise RuntimeError('LAN guard: LAN connected route missing/wrong interface')
    for management_route in c.get('management', {}).get('routes', []):
        correct = any(r.get('dst') == management_route['destination'] and
                      r.get('dev') == iface and r.get('gateway') == management_route['via']
                      for r in routes)
        if not correct:
            raise RuntimeError('LAN guard: protected management route missing: ' + management_route['destination'])
    return True


def install_runtime(c,s):
    # Live apply deliberately requires preconfigured addresses, forwarding and verified routing.
    issues=check_environment(c)
    if not c['wans']:
        issues.append('WAN list empty: cannot activate routing')
    for w in c['wans']:
        configured=run(['ip','-j','-4','addr','show','dev',w['interface']]).stdout
        ips={item['local'] for rec in json.loads(configured) for item in rec.get('addr_info',[])}
        if not set(w['addresses']).issubset(ips): issues.append(w['name']+': missing preconfigured public addresses')
    if Path('/proc/sys/net/ipv4/ip_forward').read_text().strip()!='1':
        issues.append('ip_forward must be 1')
    if issues: raise RuntimeError('; '.join(issues))
    check_lan_guard(c)
    # Avoid competing NAT table rules if existing firewall is installed.
    old=run(['nft','list','table','ip','multiwan_v3'],check=False)
    if old.returncode==0:
        run(['nft','delete','table','ip','multiwan_v3'])
    with tempfile.NamedTemporaryFile('w',delete=False) as f:
        f.write(nft_script(c,s)); name=f.name
    try:
        run(['nft','-c','-f',name]); run(['nft','-f',name])
    finally: os.unlink(name)
    run(['sysctl','-w','net.ipv4.fib_multipath_hash_policy=1'])
    cmd=route_command(c,{n for n,x in s['wans'].items() if x['healthy']})
    if cmd: run(cmd)


def probe(w, target, timeout):
    # Bind to WAN interface; requires all interfaces & on-link routing configured.
    return run(['ping','-n','-I',w['interface'],'-c','1','-W',str(timeout),target],check=False).returncode==0


def update_healthy(c,s,observations):
    p=c['probe']
    for w in c['wans']:
        name=w['name']; a=s['wans'][name]; passed=observations.get(name,False)
        if passed:
            a['success']+=1;a['fail']=0
            if not a['healthy'] and a['success']>=p['recover_rounds']:
                a['healthy']=True;event(s,name+' recovered')
        else:
            a['fail']+=1;a['success']=0
            if a['healthy'] and a['fail']>=p['fail_rounds']:
                a['healthy']=False;event(s,name+' unavailable')
    s['updated']=datetime.datetime.now(datetime.timezone.utc).isoformat()
    return s


def run_loop(c,apply=False,once=False):
    STATE_DIR.mkdir(parents=True,exist_ok=True)
    s=current_state(c)
    telemetry=connect(STATE_DIR/"telemetry.sqlite3")
    s['mode']='live-basic' if apply else 'dry-run'
    # No live install before first probes, never replace route with empty set.
    while True:
        results={}
        for w in c['wans']:
            if not apply:
                results[w['name']]=True
                # A dry run must never manufacture measured success statistics.
            else:
                tested=[]
                for t in c['probe']['targets']:
                    start=time.monotonic()
                    success=probe(w,t,c['probe']['timeout_seconds'])
                    latency=round((time.monotonic()-start)*1000,1)
                    tested.append(success)
                    log_sample(telemetry,wan=w['name'],target=t,outcome='success' if success else 'timeout',
                               latency_ms=latency if success else None, kind='internet')
                results[w['name']]=any(tested)
        before={n:a['healthy'] for n,a in s['wans'].items()}
        update_healthy(c,s,results)
        for name,prev in before.items():
            if prev!=s['wans'][name]['healthy']:
                log_decision(telemetry,scope='wan',subject=name,action='recover' if s['wans'][name]['healthy'] else 'suspend',
                             reason='WAN probe threshold reached',evidence={'success':s['wans'][name]['success'],'fail':s['wans'][name]['fail']},
                             status='proposed' if not apply else 'applied')
        if apply:
            if not any(x['healthy'] for x in s['wans'].values()):
                event(s,'all WANs unhealthy; preserving last route; operator action needed')
            elif before!={n:a['healthy'] for n,a in s['wans'].items()}:
                cmd=route_command(c,{n for n,a in s['wans'].items() if a['healthy']})
                if cmd:
                    check_lan_guard(c)
                    run(cmd)
        atomic_json(STATE_DIR/'state.json',s)
        if once: break
        time.sleep(c['probe']['interval_seconds'])


def main():
    global STATE_DIR
    p=argparse.ArgumentParser();p.add_argument('--config',default=str(CONFIG));p.add_argument('--state-dir',default=str(STATE_DIR));p.add_argument('--apply',action='store_true');p.add_argument('--once',action='store_true');p.add_argument('--print',action='store_true');p.add_argument('--render-nft',action='store_true');p.add_argument('--install-runtime',action='store_true');p.add_argument('--ack-network-change',action='store_true'); a=p.parse_args()
    STATE_DIR=Path(a.state_dir)
    c=load_config(a.config);s=current_state(c)
    if a.print: print(json.dumps(s,ensure_ascii=False,indent=2));return
    if a.render_nft: print(nft_script(c,s));return
    if a.install_runtime:
        if not a.ack_network_change or os.geteuid()!=0: p.error('requires root and --ack-network-change')
        install_runtime(c,s);return
    if a.apply and (not a.ack_network_change or os.geteuid()!=0):
        p.error('live mode requires root and --ack-network-change')
    run_loop(c,apply=a.apply,once=a.once)

if __name__=='__main__':main()
