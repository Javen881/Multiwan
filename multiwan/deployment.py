"""V3.2 read-only renderer: generates reviewed artifacts; never changes host networking."""
import argparse
import difflib
import hashlib
import json
from pathlib import Path
from .config_portal import validate_candidate
from .core import load_config, route_command, nft_script, current_state


def render_netplan(c):
    """Netplan YAML subset with static interfaces. ECMP is managed separately."""
    c=validate_candidate(c)
    lines=['# Generated preview. CHECK PHYSICAL PORTS before installation.',
           '# Does NOT configure main default route; ECMP is managed by separate core.',
           'network:', '  version: 2', '  renderer: networkd', '  ethernets:']
    lan=c['lan']; lines += [f"    {lan['interface']}:", '      dhcp4: false',
                           '      dhcp6: false', '      addresses:', f"        - {lan['address']}",
                           '      # The LAN connected route is created automatically in main by this address.',
                           '      # Mirror the explicit LAN subnet route in each WAN policy routing table.',
                           '      routes:']
    for table in range(101, 101 + len(c['wans'])):
        lines += [f"        - to: {lan['subnet']}", '          scope: link', f'          table: {table}']
    for route in c.get('management',{}).get('routes',[]):
        lines += [f"        - to: {route['destination']}",f"          via: {route['via']}"]
    for w in c['wans']:
        lines += [f"    {w['interface']}:", '      dhcp4: false','      dhcp6: false',
                  '      addresses:']
        lines += [f"        - {addr}/{w['prefix']}" for addr in w['addresses']]
    return '\n'.join(lines)+'\n'


def config_diff(active,pending):
    a=json.dumps(active,ensure_ascii=False,sort_keys=True,indent=2).splitlines(keepends=True)
    b=json.dumps(pending,ensure_ascii=False,sort_keys=True,indent=2).splitlines(keepends=True)
    return ''.join(difflib.unified_diff(a,b,fromfile='active',tofile='pending')) or 'No changes.\n'


def plan(active,pending):
    checked=validate_candidate(pending)
    warnings=[
        '示例 198.51.* 地址不能作为真实公网部署数据。',
        'LAN 为受保护的管理生命线：必须保持指定 LAN 接口、地址和网段的直连路由。',
        '变更 LAN 网口、LAN IP 或 LAN 网段必须走独立维护流程；自动应用仅允许修改 WAN。',
        '应用前检查当前 LAN 接口地址及内网回程路由；检查不通过拒绝修改 ECMP。',
        '已有防火墙/NAT、其他默认路由与 NetworkManager 必须先评估冲突。',
        '多 WAN ECMP 路由变化无法保证已有 TCP 会话保持。',
        '本生成器的 NAT 仍只使用每个 WAN 的第一个 IP；20-IP 动态调度尚未接入实机。',
        '生成物不应直接替换生产配置，应在独立管理链路下人工复核。',
    ]
    example = any(x.startswith(('198.51.100.','203.0.113.','192.0.2.')) for w in checked['wans'] for x in w['addresses'])
    if example: warnings.insert(0,'检测到文档保留 IP：禁止真实网络应用。')
    lan_changed=(any(active.get('lan',{}).get(k)!=checked['lan'].get(k) for k in ('interface','address','subnet')) or active.get('management',{}).get('routes',[])!=checked.get('management',{}).get('routes',[]))
    if lan_changed: warnings.insert(0,'检测到 LAN 或管理回程路由变更：禁止通过 WAN 自动应用流程提交，需控制台操作。')
    all_wans={w['name'] for w in checked['wans']}
    return {'changed':active!=checked,'lan_protected':True,'lan_changed':lan_changed,
            'sha256':hashlib.sha256(json.dumps(checked,sort_keys=True).encode()).hexdigest(),
            'diff':config_diff(active,checked),
            'netplan':render_netplan(checked),
            'ecmp_command':' '.join(route_command(checked, all_wans)),
            'nft':nft_script(checked,current_state(checked)),
            'warnings':warnings}


def main():
    p=argparse.ArgumentParser(description='V3.2 safety-first read-only deployment preview')
    p.add_argument('--active',required=True);p.add_argument('--pending',required=True)
    p.add_argument('--output-dir',required=True)
    args=p.parse_args()
    active=load_config(args.active)
    pending=validate_candidate(json.loads(Path(args.pending).read_text()))
    result=plan(active,pending)
    out=Path(args.output_dir);out.mkdir(parents=True,exist_ok=True)
    (out/'50-multiwan.preview.yaml').write_text(result['netplan'])
    (out/'multiwan.preview.nft').write_text(result['nft'])
    (out/'ecmp.preview.txt').write_text(result['ecmp_command']+'\n')
    (out/'config.diff').write_text(result['diff'])
    (out/'report.json').write_text(json.dumps({k:v for k,v in result.items() if k not in ('netplan','nft','diff')},ensure_ascii=False,indent=2))
    print('Review-only files generated in',out,'; NO system network changes made.')

if __name__=='__main__':main()
