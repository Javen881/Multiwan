"""Read-only Linux interface discovery; no assumptions about eth/enp names."""
import json
from pathlib import Path
import subprocess


def _json_cmd(*cmd):
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=4, check=True)
        return json.loads(r.stdout)
    except (OSError, subprocess.SubprocessError, ValueError):
        return []


def discover_interfaces(sysfs=Path('/sys/class/net')):
    links = _json_cmd('ip', '-j', 'link', 'show')
    addresses = _json_cmd('ip', '-j', '-4', 'addr', 'show')
    routes = _json_cmd('ip', '-j', '-4', 'route', 'show', 'table', 'main')
    addr_by_if = {r['ifname']: [f"{a['local']}/{a['prefixlen']}" for a in r.get('addr_info', []) if a.get('family')=='inet'] for r in addresses}
    gateways = {}
    for r in routes:
        if r.get('dst') == 'default' and r.get('dev') and r.get('gateway'):
            gateways.setdefault(r['dev'], []).append(r['gateway'])
        for nh in r.get('nexthops', []):
            if nh.get('dev') and nh.get('gateway'):
                gateways.setdefault(nh['dev'], []).append(nh['gateway'])
    result=[]
    for item in links:
        name=item.get('ifname','')
        if name=='lo' or not name: continue
        path=sysfs/name
        # Only hardware-backed Ethernet interfaces are automatically selectable.
        # Virtual interfaces remain visible only if already configured elsewhere.
        if not (path/'device').exists():
            continue
        try: carrier=(path/'carrier').read_text().strip()=='1'
        except OSError: carrier=None
        try: speed=(path/'speed').read_text().strip()
        except OSError: speed=None
        try: mac=(path/'address').read_text().strip()
        except OSError: mac=item.get('address','')
        result.append({'name':name, 'mac':mac, 'link_up':carrier, 'speed_mbps':int(speed) if speed and speed.isdigit() else None,
                       'addresses':addr_by_if.get(name,[]), 'gateways':gateways.get(name,[]),
                       'kind':item.get('link_type',''), 'physical':True, 'operstate':item.get('operstate','UNKNOWN')})
    return sorted(result, key=lambda x:x['name'])
