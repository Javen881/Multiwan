#!/usr/bin/env python3
"""On-device read-only acceptance evidence; never edits routes, links or firewall."""
import datetime
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys


def command(*args):
    try:
        x=subprocess.run(args,text=True,capture_output=True,timeout=12)
        return {'ok':x.returncode==0,'code':x.returncode,'stdout':x.stdout[:15000],'stderr':x.stderr[:2000]}
    except (OSError,subprocess.TimeoutExpired) as exc:
        return {'ok':False,'error':str(exc)}


def run(config_path):
    from multiwan.config_portal import validate_candidate
    from multiwan.core import check_lan_guard
    from multiwan.discovery import discover_interfaces
    data=json.loads(Path(config_path).read_text())
    config=validate_candidate(data,discover_interfaces())
    evidence={'timestamp_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),
              'host':os.uname().nodename,'configuration':{'lan':config['lan'],'wan_count':len(config['wans'])},
              'checks':{},'observations':{},'hardware_fault_injection':'NOT_PERFORMED'}
    tests=evidence['checks']
    tests['lan_configured']={'ok':bool(config['lan']['interface'] and config['lan']['subnet'])}
    tests['web_binding']={'ok':False,'observed':command('ss','-lntp')}
    ss=tests['web_binding']['observed'].get('stdout','')
    port=config['web']['port']
    listening=[line for line in ss.splitlines() if 'LISTEN' in line and f':{port}' in line]
    tests['web_binding']['ok']=bool(listening) and all(f'127.0.0.1:{port}' in x for x in listening)
    try:check_lan_guard(config);tests['lan_guard']={'ok':True}
    except Exception as exc:tests['lan_guard']={'ok':False,'error':str(exc)}
    for wan in config['wans']:
        iface=wan['interface']; name=wan['name']
        addr=command('ip','-j','-4','addr','show','dev',iface)
        present=set()
        if addr['ok']:
            for record in json.loads(addr['stdout']):
                for a in record.get('addr_info',[]):present.add(a['local'])
        tests[f'{name}_addresses']={'ok':all(a in present for a in wan['addresses']),
                                    'missing':sorted(set(wan['addresses'])-present)}
        tests[f'{name}_gateway_route']={'ok':False,'observed':command('ip','-4','route','get',wan['gateway'],'oif',iface)}
        got=tests[f'{name}_gateway_route']['observed']
        tests[f'{name}_gateway_route']['ok']=got['ok'] and 'dev '+iface in got.get('stdout','')
    for name,cmd in {'links':['ip','-br','link'], 'addresses':['ip','-4','-br','addr'],
                     'main_route':['ip','-4','route','show','table','main'],
                     'ip_rules':['ip','-4','rule','show'],
                     'ecmp_route':['ip','-4','route','show','default'],
                     'nft':['nft','list','ruleset'],
                     'forwarding':['sysctl','net.ipv4.ip_forward'],
                     'control_service':['systemctl','is-active','multiwan-control.service']}.items():
        evidence['observations'][name]=command(*cmd)
    evidence['all_preflight_passed']=all(v.get('ok',False) for v in tests.values())
    return evidence

if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser()
    parser.add_argument('--config',required=True)
    parser.add_argument('--out',default='multiwan-acceptance.json')
    args=parser.parse_args()
    result=run(args.config)
    Path(args.out).write_text(json.dumps(result,ensure_ascii=False,indent=2))
    print('Read-only acceptance evidence:',args.out)
    print('Preflight:', 'PASS' if result['all_preflight_passed'] else 'FAIL/INCOMPLETE')
    print('Physical link failures/recovery, real traffic and rollback require supervised on-device acceptance.')
    sys.exit(0 if result['all_preflight_passed'] else 2)
