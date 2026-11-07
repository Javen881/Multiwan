"""Evidence-only selection of per-WAN IPv4 SNAT pools.

Never changes host network. Decisions require measured independent targets and
sufficient samples; lack of source route is unknown, not a failed probe.
"""
import time
from .telemetry import log_decision

def ip_evidence(db, wan, ip, *, now=None, window=900):
    now = int(time.time() if now is None else now)
    row=db.execute('''SELECT COUNT(*), COUNT(DISTINCT target),
        SUM(CASE WHEN outcome IN ('timeout','network_error') THEN 1 ELSE 0 END),
        SUM(CASE WHEN outcome='success' THEN 1 ELSE 0 END)
        FROM samples WHERE origin='measured' AND kind='ip' AND wan=?
        AND source_ip=? AND at BETWEEN ? AND ? AND
        outcome IN ('success','timeout','network_error')''',
        (wan,ip,now-window,now)).fetchone()
    n, targets, failed, ok=row
    return {'samples':n,'targets':targets,'failures':failed or 0,'successes':ok or 0,
            'failure_rate':(failed or 0)/n if n else None}

def propose_pools(db, config, *, now=None, window=900, min_samples=12,
                  min_targets=2, threshold=.6, audit=False):
    """Propose same-WAN replacements. Never suspends an entire WAN from one window.

    A suspect IP is excluded only if an independent better IP in the same WAN
    has sufficient positive evidence. When uncertain, retain the original pool.
    """
    now=int(time.time() if now is None else now)
    proposals=[]
    for wan in config['wans']:
        name=wan['name']
        metrics={ip:ip_evidence(db,name,ip,now=now,window=window) for ip in wan['addresses']}
        good=[ip for ip,s in metrics.items() if s['samples']>=min_samples and s['targets']>=min_targets
              and s['failure_rate'] is not None and s['failure_rate']<=.2 and s['successes']>0]
        bad=[ip for ip,s in metrics.items() if s['samples']>=min_samples and s['targets']>=min_targets
             and s['failure_rate'] is not None and s['failure_rate']>=threshold]
        # Only quarantine confirmed bad IPs if there is a corroborated alternative.
        proposed=[ip for ip in wan['addresses'] if ip not in bad] if good else list(wan['addresses'])
        reason=('confirmed same-WAN alternate; exclude high-failure source IPs' if good and bad
                else 'insufficient independent evidence, retain pool')
        p={'wan':name,'interface':wan['interface'],'ips':proposed,'suspects':bad,
           'metrics':metrics,'reason':reason,'status':'advisory'}
        proposals.append(p)
        if audit and bad:
            log_decision(db,scope='ip',subject=name,action='propose_pool',reason=reason,
                         evidence={'bad':bad,'good':good,'metrics':metrics}, status='proposed',at=now)
    return proposals

def render_snat_pools(config, proposals):
    """Generate a complete separate preview table; inactive until explicitly deployed.

    numgen selects a source address on the first packet of a conntrack flow.
    We do not mutate established conntrack NAT mappings.
    """
    lan=config['lan']['subnet']
    chosen={p['wan']:p['ips'] for p in proposals}
    lines=['# PREVIEW ONLY: not installed by this command', 'table ip multiwan_v36_nat {',
           ' chain postrouting { type nat hook postrouting priority srcnat; policy accept;']
    for wan in config['wans']:
        ips=chosen[wan['name']]
        if not ips: raise ValueError('empty SNAT pool is prohibited')
        iface=wan['interface']
        if len(ips)==1:
            expression=ips[0]
        else:
            mapping=', '.join(f'{i} : {ip}' for i,ip in enumerate(ips))
            expression=f'numgen random mod {len(ips)} map {{ {mapping} }}'
        lines.append(f'  oifname "{iface}" ip saddr {lan} snat to {expression}')
    lines.extend([' }', '}'])
    return '\n'.join(lines)+'\n'
