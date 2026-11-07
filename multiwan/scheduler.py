"""Evidence-gated dynamic IP/WAN controller. Default is observation-only.

The controller uses source-address TCP probe records, not packet drops or HTTP
403/429, and only acts on independent time windows. Automatic mode requires an
already confirmed baseline actuator transaction and explicit flag. It never
changes LAN, WAN addresses or Netplan.
"""
import argparse
import json
import os
from pathlib import Path
import time
from .telemetry import connect, log_decision
from .ip_policy import ip_evidence
from .core import check_lan_guard, route_command, load_config
from .actuator import verified_pool, nft_swap, render_owned_nat, shell, public_addresses_are_real, load_transaction


def window_result(db, wan, ip, start, end, min_samples, min_targets, threshold):
    metric=ip_evidence(db,wan,ip,now=end,window=end-start)
    adequate=metric['samples']>=min_samples and metric['targets']>=min_targets
    return {'enough':adequate, 'bad':adequate and metric['failure_rate']>=threshold,
            'good':adequate and metric['failure_rate']<=0.2,'metric':metric}


def propose(db,c,now=None,*, windows=3,window_seconds=60,min_samples=4,min_targets=2,threshold=.6):
    """Requires 3 consecutive disjoint windows and an independently good alternate.

    Individual targets cannot force an entire WAN down: at least 2 independent
    targets and ALL addresses must have sufficient repeated failure evidence.
    """
    now=int(time.time() if now is None else now)
    pools={};wan_healthy={};evidence={}
    for w in c['wans']:
        ip_results={}
        for ip in w['addresses']:
            slices=[]
            for index in reversed(range(windows)):
                hi=now-index*window_seconds
                lo=hi-window_seconds+1
                slices.append(window_result(db,w['name'],ip,lo,hi,min_samples,min_targets,threshold))
            ip_results[ip]={'bad':all(x['bad'] for x in slices),
                            'good':all(x['good'] for x in slices),
                            'windows':slices}
        healthy_alts=[ip for ip,item in ip_results.items() if item['good']]
        excluded=[ip for ip,item in ip_results.items() if item['bad'] and healthy_alts]
        selected=[ip for ip in w['addresses'] if ip not in excluded]
        # Whole WAN only eligible for suspension when every address has conclusive
        # persistent high failure; never suspend the final active WAN.
        fully_bad=bool(ip_results) and all(item['bad'] for item in ip_results.values())
        pools[w['name']]=selected or list(w['addresses'])
        wan_healthy[w['name']]=not fully_bad
        evidence[w['name']]={'ip_results':ip_results,'excluded':excluded,'fully_bad':fully_bad}
    if not any(wan_healthy.values()):
        wan_healthy={key:True for key in wan_healthy}  # preserve last WAN route
        for record in evidence.values():record['all_bad_guard']=True
    return {'pools':pools,'wan_healthy':wan_healthy,'evidence':evidence,'at':now}


def apply_recommendation(config,proposal,state,*,execute=False):
    """Apply evidence-gated source-IP pool only; never auto-alter WAN membership."""
    from .core import atomic_json
    pools=verified_pool(config,proposal['pools'])
    state=Path(state);state.mkdir(parents=True,exist_ok=True)
    previous_path=state/('applied_pool_state.json' if execute else 'proposed_pool_state.json')
    try:previous=json.loads(previous_path.read_text())
    except (ValueError,OSError):previous={}
    changed={name:ips for name,ips in pools.items() if previous.get(name)!=ips}
    # A scheduled probe cycle must not continually re-create the identical
    # nft table, nor flood the SQLite decision log when no health state changes.
    if execute and changed:
        if os.geteuid()!=0: raise PermissionError('Root required')
        tx=load_transaction(state)
        if not tx or tx['state']!='confirmed':
            raise RuntimeError('Baseline network transaction must be confirmed before automatic NAT updates')
        public_addresses_are_real(config)
        check_lan_guard(config)
        nft_swap(render_owned_nat(config,pools))
    if changed:
        atomic_json(previous_path,pools)
        db=connect(state/'telemetry.sqlite3')
        for wan in changed:
            record=proposal['evidence'][wan]
            log_decision(db,scope='ip',subject=wan,action='update_pool' if record['excluded'] else 'retain_pool',
                         reason='three disjoint measured windows and corroborated same-WAN healthy addresses',
                         evidence={'excluded':record['excluded'],'fully_bad':record['fully_bad'],'selected':pools[wan]},
                         status='applied' if execute else 'proposed')
            if record['fully_bad']:
                log_decision(db,scope='wan',subject=wan,action='review_suspension',
                             reason='all public source IPs persistently failed; manual ECMP review required',
                             evidence={'all_bad_guard':record.get('all_bad_guard',False)},status='proposed')
        db.close()
    return {'nat':('applied' if execute else 'proposed') if changed else 'unchanged',
            'changed_wans':list(changed),'wan_route':'review_only','pools':pools}


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--config',required=True);p.add_argument('--state-dir',default=os.environ.get('MULTIWAN_STATE_DIR','/var/lib/multiwan'))
    p.add_argument('--apply-nat',action='store_true');p.add_argument('--ack-network-change',action='store_true')
    args=p.parse_args();c=load_config(args.config)
    if args.apply_nat and not args.ack_network_change:p.error('explicit acknowledgement required')
    db=connect(Path(args.state_dir)/'telemetry.sqlite3')
    try:proposal=propose(db,c)
    finally:db.close()
    print(json.dumps(apply_recommendation(c,proposal,args.state_dir,execute=args.apply_nat),ensure_ascii=False,indent=2))

if __name__=='__main__':main()
