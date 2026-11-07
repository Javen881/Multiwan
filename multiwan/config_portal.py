"""Validate dynamically sized WAN configurations and stage edits; never apply networking."""
from copy import deepcopy
from ipaddress import ip_address, ip_interface, ip_network
from pathlib import Path
import json
import os
import re
from .core import atomic_json

NAME = re.compile(r'^[a-zA-Z0-9_.:-]{1,32}$')

def validate_candidate(candidate, discovered=None):
    if not isinstance(candidate, dict):
        raise ValueError('配置必须是对象')
    c = deepcopy(candidate)
    c.setdefault('web', {})['host'] = '127.0.0.1'
    c['web']['port'] = int(c['web'].get('port', 8765))
    if not 1024 <= c['web']['port'] <= 65535:
        raise ValueError('Web 端口无效')
    if not isinstance(c.get('lan'), dict):
        raise ValueError('必须指定 LAN')
    lan = c['lan']
    lan_name = lan.get('interface')
    if not isinstance(lan_name, str) or not NAME.fullmatch(lan_name):
        raise ValueError('LAN 网卡名不合法')
    lan_addr = ip_interface(lan['address'])
    lan_net = ip_network(lan['subnet'], strict=False)
    if lan_addr.version != 4 or lan_net.version != 4:
        raise ValueError('仅支持 IPv4')
    if lan_addr.network != lan_net:
        raise ValueError('LAN 地址前缀必须与 LAN 网段一致')
    if lan_addr.ip in (lan_net.network_address, lan_net.broadcast_address):
        raise ValueError('LAN 地址不可使用')

    # Remote operator may be beyond the connected LAN: protect explicit routes as well.
    management = c.setdefault('management', {})
    routes = management.setdefault('routes', [])
    if not isinstance(routes, list) or len(routes) > 32:
        raise ValueError('管理路由数量无效')
    managed_nets = []
    for r in routes:
        if not isinstance(r, dict):
            raise ValueError('管理路由格式错误')
        dest = ip_network(r['destination'], strict=True)
        gw = ip_address(r['via'])
        if dest.version != 4 or gw.version != 4 or gw not in lan_net or gw == lan_addr.ip:
            raise ValueError('管理路由必须通过 LAN 子网内的下一跳')
        if dest.overlaps(lan_net):
            raise ValueError('管理路由不能覆盖 LAN 直连网段')
        if any(dest.overlaps(old) for old in managed_nets):
            raise ValueError('管理路由互相重叠')
        managed_nets.append(dest)
        r['destination'] = str(dest)
        r['via'] = str(gw)

    wans = c.get('wans', [])
    if not isinstance(wans, list) or len(wans) > 32:
        raise ValueError('WAN 数量必须在 0～32（至少配置 1 个才能启用转发）')
    names = [lan_name]
    wan_ids = set()
    nets = [lan_net]
    for idx, wan in enumerate(wans, 1):
        if not isinstance(wan, dict):
            raise ValueError('WAN 配置必须是对象')
        iface = wan.get('interface')
        if not isinstance(iface, str) or not NAME.fullmatch(iface):
            raise ValueError(f'第 {idx} 组 WAN 网卡名不合法')
        names.append(iface)
        wid = wan.get('name') or f'WAN{idx}'
        if not isinstance(wid, str) or not NAME.fullmatch(wid) or wid in wan_ids:
            raise ValueError('WAN 名称重复或不合法')
        wan_ids.add(wid)
        wan['name'] = wid
        weight = int(wan.get('weight', 1))
        if not 1 <= weight <= 256:
            raise ValueError(f'{wid} 权重必须在 1～256')
        wan['weight'] = weight
        prefix = int(wan['prefix'])
        if not 1 <= prefix <= 30:
            raise ValueError(f'{wid} 前缀无效')
        wan['prefix'] = prefix
        ips = wan.get('addresses', [])
        if not isinstance(ips, list) or not 1 <= len(ips) <= 64 or len(ips) != len(set(ips)):
            raise ValueError(f'{wid} 需要 1～64 个不同 IPv4 地址')
        subnet = ip_interface(f'{ips[0]}/{prefix}').network
        gw = ip_address(wan['gateway'])
        if gw.version != 4 or gw not in subnet or gw in (subnet.network_address, subnet.broadcast_address):
            raise ValueError(f'{wid} 网关不在有效直连子网')
        if any(subnet.overlaps(n) for n in nets):
            raise ValueError('WAN 网段之间不能重叠，也不能与 LAN 重叠')
        if any(subnet.overlaps(n) for n in managed_nets):
            raise ValueError('WAN 子网不能覆盖受保护管理网段')
        nets.append(subnet)
        for ip in ips:
            addr = ip_address(ip)
            if addr.version != 4 or addr not in subnet or addr in (subnet.network_address, subnet.broadcast_address) or addr == gw:
                raise ValueError(f'{wid} IP {ip} 不可使用')
    if len(set(names)) != len(names):
        raise ValueError('LAN 与所有 WAN 必须使用不同网卡')
    if discovered is not None:
        known = {d['name'] for d in discovered}
        unknown = sorted(set(names) - known)
        if unknown:
            raise ValueError('设备不存在：' + ','.join(unknown))
    return c


def stage_config(candidate, config_path, discovered=None):
    c = validate_candidate(candidate, discovered)
    path = Path(config_path).with_name('config.pending.json')
    if path.exists():
        atomic_json(path.with_suffix('.json.previous'), json.loads(path.read_text()))
    atomic_json(path, c)
    os.chmod(path, 0o600)
    return c


def build_candidate_from_form(base, data):
    c = deepcopy(base)
    c['lan'] = {'interface': data['lan_interface'], 'address': data['lan_address'].strip(), 'subnet': data['lan_subnet'].strip()}
    # Explicit selection required. No implicit assignment based on interface order.
    count = int(data['wan_count'])
    if count < 0 or count > 32:
        raise ValueError('WAN 数量超出范围')
    wans = []
    for i in range(1, count+1):
        interface = data[f'wan{i}_interface']
        addresses = [x.strip() for x in data[f'wan{i}_ips'].split(',') if x.strip()]
        wans.append({'name': data.get(f'wan{i}_name', f'WAN{i}').strip(), 'interface': interface,
                     'gateway': data[f'wan{i}_gateway'].strip(), 'prefix': int(data[f'wan{i}_prefix']),
                     'weight': int(data.get(f'wan{i}_weight', '1')), 'addresses': addresses})
    c['wans'] = wans
    routes = []
    for line in data.get('management_routes', '').splitlines():
        if not line.strip():
            continue
        bits = line.strip().split()
        if len(bits) != 2:
            raise ValueError('管理路由每行格式：目标CIDR 下一跳IP')
        routes.append({'destination': bits[0], 'via': bits[1]})
    c['management'] = {'routes': routes}
    return c
