"""Pure deterministic IP/WAN policy for simulation and unit tests.

This module never changes real network configuration. Only valid confirmed network
failures should be submitted. HTTP 403/429 or application denials are not input.
"""
from collections import deque
from dataclasses import dataclass, field
from typing import Dict, List

@dataclass
class IPRecord:
    observations: deque = field(default_factory=lambda: deque(maxlen=300))
    cooldown_until: float = 0.0
    last_reason: str = ''

class DecisionEngine:
    def __init__(self, wan_addresses: Dict[str,List[str]], window=60, min_samples=12,
                 threshold=.6, bad_windows=3, cooldown=300):
        self.wans=wan_addresses
        self.window=window; self.min_samples=min_samples
        self.threshold=threshold;self.bad_windows=bad_windows;self.cooldown=cooldown
        self.records={ip:IPRecord() for ips in wan_addresses.values() for ip in ips}
        self.bad_counts={w:0 for w in wan_addresses}
        self.wan_cooldown={w:0.0 for w in wan_addresses}
        self.rotation={w:0 for w in wan_addresses}

    def observe(self, source_ip, target, success, timestamp, *, confirmed=True):
        if source_ip not in self.records: raise ValueError('unknown IP')
        if not confirmed: return # incomplete/unknown cases are never counted as confirmed failures
        rec=self.records[source_ip]
        rec.observations.append((timestamp,str(target),bool(success)))
        while rec.observations and rec.observations[0][0]<timestamp-self.window:
            rec.observations.popleft()

    def stats(self,ip,now):
        obs=[o for o in self.records[ip].observations if o[0]>=now-self.window]
        n=len(obs); fail=sum(not v for _,_,v in obs)
        return {'samples':n,'failures':fail,'failure_rate':fail/n if n else None,
                'targets':len({t for _,t,_ in obs})}

    def next_ip(self,wan,now):
        """Prefer same-WAN IP. Return None only if whole pool cooling down."""
        ips=self.wans[wan]
        for i in range(len(ips)):
            idx=(self.rotation[wan]+i)%len(ips)
            ip=ips[idx]
            if self.records[ip].cooldown_until<=now:
                self.rotation[wan]=(idx+1)%len(ips)
                return ip
        return None

    def assess(self,wan,now):
        """Require all four IPs to have sufficient independent evidence before WAN ejection.
        Called once per completed measurement window (not once per sample).
        """
        ips=self.wans[wan]
        stats=[self.stats(ip,now) for ip in ips]
        qualified=all(s['samples']>=self.min_samples and s['targets']>=2 for s in stats)
        bad=qualified and all(s['failure_rate']>=self.threshold for s in stats)
        self.bad_counts[wan]=self.bad_counts[wan]+1 if bad else 0
        if self.bad_counts[wan]>=self.bad_windows:
            self.wan_cooldown[wan]=now+self.cooldown
        return {'wan':wan,'qualified':qualified,'bad_window':bad,
                'bad_windows':self.bad_counts[wan],
                'wan_paused':self.wan_cooldown[wan]>now,
                'ip_stats':dict(zip(ips,stats))}

    def flag_ip_suspect(self,wan,ip,now):
        """Caller must corroborate via a successful alternate source/target probe."""
        if ip not in self.wans[wan]: raise ValueError('IP not in WAN')
        self.records[ip].cooldown_until=now+self.cooldown
        return self.next_ip(wan,now)
