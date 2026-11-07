"""Periodic bounded probes + advisory decision. Live NAT opt-in only."""
import argparse
import json
import os
from pathlib import Path
from .core import load_config
from .ip_probe import scan_parallel,DEFAULT_TARGETS
from .scheduler import propose,apply_recommendation
from .telemetry import connect


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--config',required=True)
    p.add_argument('--state-dir',default=os.environ.get('MULTIWAN_STATE_DIR','/var/lib/multiwan'))
    p.add_argument('--tcp-timeout',type=float,default=2)
    p.add_argument('--workers',type=int,default=8)
    p.add_argument('--apply-nat',action='store_true')
    p.add_argument('--ack-network-change',action='store_true')
    a=p.parse_args()
    if not 0.2<=a.tcp_timeout<=8 or not 1<=a.workers<=16:p.error('Probe limits exceeded')
    if a.apply_nat and not a.ack_network_change:p.error('Explicit acknowledgement required')
    c=load_config(a.config);db=connect(Path(a.state_dir)/'telemetry.sqlite3')
    try:
        measurements=scan_parallel(c,db,targets=DEFAULT_TARGETS,timeout=a.tcp_timeout,max_workers=a.workers)
        decision=propose(db,c)
    finally:db.close()
    result=apply_recommendation(c,decision,a.state_dir,execute=a.apply_nat)
    print(json.dumps({'probes':len(measurements),'unknown':sum(x['outcome']=='unknown' for x in measurements),
                      'decision':result},ensure_ascii=False))
if __name__=='__main__':main()
