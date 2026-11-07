"""Read-only, source-address TCP connectivity measurements.

Never changes network configuration. A valid route check is mandatory before a
probe is classified as measured; otherwise record unknown, not a failure.
"""
import argparse
import ipaddress
import json
import os
from pathlib import Path
import socket
import subprocess
import time
from .core import load_config
from .telemetry import connect, log_sample

DEFAULT_TARGETS = [('1.1.1.1', 443), ('8.8.8.8', 443)]

def route_uses_interface(source_ip, target, interface, runner=subprocess.run):
    proc = runner(['ip', '-j', '-4', 'route', 'get', target, 'from', source_ip],
                  text=True, capture_output=True, timeout=5, check=False)
    if proc.returncode != 0:
        return False
    try:
        return any(x.get('dev') == interface and x.get('src', source_ip) == source_ip
                   for x in json.loads(proc.stdout))
    except (ValueError, TypeError):
        return False

def tcp_probe(source_ip, host, port, timeout=3, connector=socket.socket):
    """Probe IPv4 TCP handshake using explicit source address, not HTTP status.

    'refused' means remote TCP refusal, not an unreachable WAN.
    """
    start = time.monotonic()
    sock = connector(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.settimeout(timeout)
        sock.bind((source_ip, 0))
        sock.connect((host, port))
        return 'success', round((time.monotonic()-start)*1000, 1)
    except ConnectionRefusedError:
        return 'refused', None
    except (socket.timeout, TimeoutError):
        return 'timeout', None
    except OSError:
        return 'network_error', None
    finally:
        sock.close()

def scan(c, db, *, targets=DEFAULT_TARGETS, timeout=3, route_checker=route_uses_interface,
         probe=tcp_probe):
    results = []
    for wan in c['wans']:
        for ip in wan['addresses']:
            for host, port in targets:
                target = f'{host}:{port}'
                if not route_checker(ip, host, wan['interface']):
                    outcome, latency, detail = 'unknown', None, 'source route does not match WAN; no failure counted'
                else:
                    outcome, latency = probe(ip, host, port, timeout=timeout)
                    detail = 'source-bound IPv4 TCP handshake'
                log_sample(db, wan=wan['name'], source_ip=ip, target=target,
                           outcome=outcome, kind='ip', latency_ms=latency, detail=detail)
                results.append({'wan':wan['name'], 'ip':ip, 'target':target,
                                'outcome':outcome, 'latency_ms':latency, 'detail':detail})
    return results

def main():
    parser = argparse.ArgumentParser(description='Source-IP probes; never edits routes/NAT')
    parser.add_argument('--config', required=True)
    parser.add_argument('--state-dir', default=os.environ.get('MULTIWAN_STATE_DIR', '/tmp/multiwan-preview'))
    parser.add_argument('--timeout', type=float, default=3)
    args=parser.parse_args()
    if not 0.2 <= args.timeout <= 15: parser.error('timeout range: 0.2..15 seconds')
    c=load_config(args.config)
    db=connect(Path(args.state_dir)/'telemetry.sqlite3')
    try:
        print(json.dumps(scan(c, db, timeout=args.timeout), ensure_ascii=False, indent=2))
    finally:
        db.close()

if __name__=='__main__': main()


def scan_parallel(c,db,*,targets=DEFAULT_TARGETS,timeout=2,max_workers=8):
    """Bounded concurrent source-IP probes; all SQLite writes on calling thread."""
    from concurrent.futures import ThreadPoolExecutor, as_completed
    work=[(w['name'],w['interface'],ip,host,int(port))
          for w in c['wans'] for ip in w['addresses'] for host,port in targets]
    def measure(item):
        name,iface,ip,host,port=item
        if not route_uses_interface(ip,host,iface):
            return name,ip,f'{host}:{port}','unknown',None,'route mismatch'
        outcome,latency=tcp_probe(ip,host,port,timeout=timeout)
        return name,ip,f'{host}:{port}',outcome,latency,'source-bound TCP handshake'
    results=[]
    with ThreadPoolExecutor(max_workers=min(max_workers,16)) as executor:
        for future in as_completed([executor.submit(measure,item) for item in work]):
            name,ip,target,outcome,latency,detail=future.result()
            log_sample(db,wan=name,source_ip=ip,target=target,kind='ip',
                       outcome=outcome,latency_ms=latency,detail=detail)
            results.append({'wan':name,'ip':ip,'target':target,'outcome':outcome})
    return results
