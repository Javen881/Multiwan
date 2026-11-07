"""Guarded WAN-only change engine.

This engine NEVER assigns IP addresses, changes LAN or management routes, or edits
Netplan. WAN addresses must already exist and be validated. A detached watchdog
restores the prior ECMP and owned nft table unless explicitly confirmed.

Live apply is deliberately gated by root, explicit acknowledgement and a working
systemd-run executable. Independent management access is still required for production.
"""
import argparse
import fcntl
import ipaddress
import json
import os
from pathlib import Path
import re
import secrets
import shlex
import shutil
import subprocess
import sys
import tempfile
import time
from .config_portal import validate_candidate
from .core import check_lan_guard, check_environment, route_command, run
from .ip_policy import render_snat_pools

TABLE = 'multiwan_v36_nat'
DEFAULT_STATE = Path('/var/lib/multiwan')


def shell(cmd, *, input=None, check=True):
    return subprocess.run(cmd, text=True, capture_output=True, input=input, check=check)


def protected_config(active, proposed):
    a, b = validate_candidate(active), validate_candidate(proposed)
    if a['lan'] != b['lan'] or a.get('management', {}).get('routes') != b.get('management', {}).get('routes'):
        raise ValueError('LAN/management routes are immutable in WAN-only transaction')
    if not b['wans']:
        raise ValueError('Refusing zero WANs')
    # The safety engine cannot create or change WAN addresses: only already configured
    # interfaces are supported. Interface roles must not be reassigned while online.
    old = {w['name']:w for w in a['wans']}
    for w in b['wans']:
        if w['name'] in old and w['interface'] != old[w['name']]['interface']:
            raise ValueError('WAN interface reassignment requires maintenance window')
    return b


def public_addresses_are_real(c):
    for w in c['wans']:
        for raw in w['addresses']:
            ip = ipaddress.ip_address(raw)
            if not ip.is_global:
                raise ValueError(f'Not a globally routable public IPv4: {raw}')


def check_configured_network(c):
    problems = check_environment(c)
    if shutil.which('systemd-run') is None:
        problems.append('systemd-run missing: cannot guarantee independent timer')
    if shutil.which('systemctl') is None:
        problems.append('systemctl missing')
    if Path('/proc/sys/net/ipv4/ip_forward').read_text().strip() != '1':
        problems.append('IPv4 forwarding is disabled')
    check_lan_guard(c)
    # Refuse coexistence with the legacy preview NAT table; double SNAT creates
    # nondeterministic behavior when chains share the same hook priority.
    legacy=shell(['nft','list','table','ip','multiwan_v3'],check=False)
    if legacy.returncode==0:
        problems.append('Legacy multiwan_v3 NAT table exists; remove after audited migration')
    for w in c['wans']:
        if not Path('/sys/class/net',w['interface']).is_dir():
            problems.append('WAN missing: '+w['interface']);continue
        reply=shell(['ip','-j','-4','addr','show','dev',w['interface']])
        actual={a['local'] for n in json.loads(reply.stdout) for a in n.get('addr_info',[])}
        if not set(w['addresses']).issubset(actual):
            problems.append(f'{w["name"]} has missing IPs: {sorted(set(w["addresses"])-actual)}')
        # route to next-hop must resolve on the intended NIC.
        gw=shell(['ip','-4','route','get',w['gateway'],'oif',w['interface']],check=False)
        if gw.returncode or 'dev '+w['interface'] not in gw.stdout:
            problems.append(w['name']+' gateway not routed over its interface')
    if problems: raise RuntimeError('; '.join(problems))


def verified_pool(c, pools):
    expected={w['name'] for w in c['wans']}
    if set(pools)!=expected: raise ValueError('pool set differs from active WANs')
    for w in c['wans']:
        pool=pools[w['name']]
        if not pool or len(set(pool))!=len(pool) or not set(pool).issubset(w['addresses']):
            raise ValueError('Invalid/empty SNAT pool for '+w['name'])
    return pools


def render_owned_nat(c, pools):
    verified_pool(c,pools)
    props=[{'wan':w['name'],'ips':pools[w['name']]} for w in c['wans']]
    return render_snat_pools(c,props).replace('# PREVIEW ONLY: not installed by this command\n','')


def snapshot():
    # Only a single managed default route is allowed for reversible operations.
    routes=shell(['ip','-4','route','show','default']).stdout.strip().splitlines()
    if len(routes)!=1:
        raise RuntimeError('Expected exactly one IPv4 default route; refusing ambiguous rollback')
    old=shell(['nft','list','table','ip',TABLE],check=False)
    if old.returncode and 'No such file' not in old.stderr:
        raise RuntimeError('Cannot inspect existing NAT table: '+old.stderr)
    return {'route':routes[0], 'nat':old.stdout if old.returncode==0 else None}


def nft_swap(text):
    # Use a single nft batch to delete and replace just our owned table.
    old=shell(['nft','list','table','ip',TABLE],check=False)
    if old.returncode not in (0,1): raise RuntimeError(old.stderr)
    script=('delete table ip '+TABLE+'\n' if old.returncode==0 else '')+text
    # nf_tables supports atomic batch commit; validate same script before commit.
    shell(['nft','-c','-f','-'],input=script)
    shell(['nft','-f','-'],input=script)


def restore_snapshot(previous):
    # nft and route are separate kernel APIs and cannot be atomically committed together.
    # Best-effort both even if the first restoration fails.
    errors=[]
    try:
        old=shell(['nft','list','table','ip',TABLE],check=False)
        script=('delete table ip '+TABLE+'\n' if old.returncode==0 else '')+(previous['nat'] or '')
        if script.strip(): shell(['nft','-f','-'],input=script)
    except Exception as exc: errors.append('nft: '+str(exc))
    try:
        shell(['ip','-4','route','replace']+shlex.split(previous['route']))
    except Exception as exc: errors.append('route: '+str(exc))
    if errors: raise RuntimeError('; '.join(errors))


def file_write(path, data):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.NamedTemporaryFile('w',dir=path.parent,delete=False) as f:
        json.dump(data,f,indent=2);temp=f.name
    os.chmod(temp,0o600);os.replace(temp,path)


def load_transaction(state):
    p=Path(state)/'transaction.json'
    return json.loads(p.read_text()) if p.exists() else None


def rollback(state):
    state=Path(state);trans=load_transaction(state)
    if not trans or trans['state']!='pending': return 'no pending change'
    restore_snapshot(trans['previous'])
    trans['state']='rolled_back';trans['completed_at']=int(time.time())
    file_write(state/'transaction.json',trans)
    return 'rolled back'


def confirm(state, token):
    state=Path(state);trans=load_transaction(state)
    if not trans or trans['state']!='pending': raise RuntimeError('No pending change')
    if not secrets.compare_digest(trans['token'],token): raise RuntimeError('Invalid confirmation token')
    if int(time.time()) >= trans['deadline']: raise RuntimeError('Deadline elapsed')
    trans['state']='confirmed';trans['completed_at']=int(time.time())
    file_write(state/'transaction.json',trans)
    return 'confirmed'


def schedule_rollback(state, seconds, txid):
    # Explicit independent systemd transient timer: survives a killed web/core process.
    cmd=['systemd-run','--quiet','--unit','multiwan-rollback-'+txid,
         '--on-active='+str(int(seconds))+'s',
         '--working-directory='+str(Path(__file__).resolve().parent.parent),
         sys.executable,'-m','multiwan.actuator','rollback','--state-dir',str(state)]
    shell(cmd)


def apply(active, candidate, pools, state, seconds=120):
    if os.geteuid()!=0: raise PermissionError('Root required')
    if not 60<=seconds<=900: raise ValueError('Confirmation timeout must be 60-900 seconds')
    c=protected_config(active,candidate)
    public_addresses_are_real(c)
    check_configured_network(c)
    verified_pool(c,pools)
    state=Path(state);state.mkdir(parents=True,exist_ok=True)
    # Lock prevents concurrent instances from applying on top of each other.
    with open(state/'network.lock','a+') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX)
        existing=load_transaction(state)
        if existing and existing['state']=='pending': raise RuntimeError('Pending transaction must be confirmed or rolled back first')
        prev=snapshot()
        token=secrets.token_urlsafe(32)
        txid=secrets.token_hex(6)
        trans={'id':txid,'state':'pending','token':token,'deadline':int(time.time())+seconds,'previous':prev}
        file_write(state/'transaction.json',trans)
        # Schedule rollback BEFORE any network modification; on failure cancel by changing state.
        try: schedule_rollback(state,seconds,txid)
        except Exception:
            trans['state']='aborted';file_write(state/'transaction.json',trans);raise
        try:
            nft_swap(render_owned_nat(c,pools))
            route=route_command(c,{w['name'] for w in c['wans']})
            if not route: raise RuntimeError('No WAN route')
            shell(route)
            check_lan_guard(c)
        except Exception:
            try: restore_snapshot(prev)
            finally:
                trans['state']='failed';file_write(state/'transaction.json',trans)
            raise
        return {'id':txid,'deadline':trans['deadline'],'token':token,'state':'pending'}


def main():
    p=argparse.ArgumentParser();sub=p.add_subparsers(dest='action',required=True)
    a=sub.add_parser('apply');a.add_argument('--active',required=True);a.add_argument('--pending',required=True);a.add_argument('--pools',required=True);a.add_argument('--timeout',type=int,default=120);a.add_argument('--state-dir',default=str(DEFAULT_STATE));a.add_argument('--ack-network-change',action='store_true')
    for name in ('confirm','rollback','status'):
        x=sub.add_parser(name);x.add_argument('--state-dir',default=str(DEFAULT_STATE))
        if name=='confirm': x.add_argument('--token',required=True)
    args=p.parse_args()
    if args.action=='status':
        t=load_transaction(args.state_dir)
        if t: t={k:v for k,v in t.items() if k not in ('previous','token')}
        print(json.dumps(t));return
    if os.geteuid()!=0: p.error('Root required for network transactions')
    if args.action=='rollback':print(rollback(args.state_dir));return
    if args.action=='confirm':print(confirm(args.state_dir,args.token));return
    if not args.ack_network_change:p.error('--ack-network-change required')
    active=json.loads(Path(args.active).read_text());pending=json.loads(Path(args.pending).read_text());pools=json.loads(Path(args.pools).read_text())
    result=apply(active,pending,pools,args.state_dir,args.timeout)
    print(json.dumps(result))

if __name__=='__main__':main()
