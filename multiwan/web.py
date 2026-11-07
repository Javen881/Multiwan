"""Loopback-only Web console. Discovers physical interfaces, saves reviewed drafts only."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit
import hmac
import html
import json
import os
import secrets
import datetime
from .core import load_config, current_state, STATE_DIR, CONFIG
from .discovery import discover_interfaces
from .config_portal import build_candidate_from_form, stage_config, validate_candidate
from .deployment import plan
from .telemetry import connect, get_dashboard, evaluate_wan

CSS='''
:root{--bg:#f4f7fc;--surface:#fff;--ink:#172c4a;--muted:#70829e;--border:#e5ebf5;--primary:#2563eb;--navy:#0d2654;--soft:#eff5ff;--ok:#079b7a;--warn:#ce8a24;--shadow:0 12px 38px rgba(24,47,86,.055)}
*{box-sizing:border-box}html{scroll-behavior:smooth}body{font:14px/1.6 Inter,system-ui,-apple-system,"Segoe UI","Microsoft YaHei",sans-serif;background:var(--bg);color:var(--ink);margin:0;padding:0}a{color:var(--primary);text-decoration:none}a:hover{text-decoration:underline}h1,h2,h3,p{margin-top:0}h1{font-size:25px;letter-spacing:-.7px;line-height:1.3}h2{font-size:17px;letter-spacing:-.2px}h3{font-size:15px}p{color:#657892}small,.muted{color:var(--muted)}.app-shell{display:grid;grid-template-columns:228px minmax(0,1fr);min-height:100vh}.sidebar{background:#102c5c;color:#dbe8fc;padding:26px 17px;position:sticky;top:0;height:100vh;display:flex;flex-direction:column;gap:25px}.side-brand{display:flex;gap:11px;align-items:center;padding:0 10px}.brand-mark{width:37px;height:37px;display:grid;place-items:center;border-radius:11px;background:#3979eb;color:white;font-size:23px;font-weight:900}.side-brand strong{font-size:18px;color:#fff;display:block;letter-spacing:-.4px}.side-brand small{font-size:10px;color:#9db7df;display:block;letter-spacing:1px}.nav-title{font-size:10px;font-weight:800;letter-spacing:1.6px;color:#829fcd;margin:0 12px 9px}.side-nav{display:grid;gap:6px}.side-nav a{padding:11px 12px;border-radius:10px;color:#c8d8f1;font-weight:600;display:flex;gap:11px;align-items:center}.side-nav a:hover,.side-nav a.active{background:#24477d;text-decoration:none;color:#fff}.nav-icon{font-size:16px;width:19px;text-align:center}.side-bottom{margin-top:auto;border:1px solid #35517c;border-radius:12px;padding:13px;font-size:12px;line-height:1.8;color:#b4c7e4}.side-bottom b{display:block;color:#fff}.status-dot{display:inline-block;background:#31d0a6;width:8px;height:8px;border-radius:100%;margin-right:8px}.main{padding:27px clamp(18px,3.2vw,48px) 65px;min-width:0;max-width:1700px;width:100%;margin:0 auto}.pagebar{display:flex;align-items:center;justify-content:space-between;gap:15px;margin-bottom:22px}.eyebrow{font-size:11px;font-weight:750;letter-spacing:1.1px;color:#5f7da8;text-transform:uppercase}.pagebar h1{margin:4px 0 0}.header-actions{display:flex;gap:9px;align-items:center;flex-wrap:wrap}.pill{display:inline-flex;align-items:center;gap:6px;background:#eef4ff;color:#235bac;border:1px solid #dce9ff;border-radius:100px;font-size:11px;font-weight:750;padding:5px 10px}.top{border-radius:18px;padding:24px 28px;margin-bottom:22px;color:white;background:radial-gradient(circle at 92% -12%,#4789ef 0,transparent 38%),linear-gradient(112deg,#113775,#1d5bc4);box-shadow:0 18px 40px rgba(26,76,154,.15);position:relative;overflow:hidden}.top:after{content:"";position:absolute;right:5%;bottom:-93px;border:1px solid rgba(255,255,255,.14);width:235px;height:235px;border-radius:50%;box-shadow:0 0 0 28px rgba(255,255,255,.045),0 0 0 57px rgba(255,255,255,.025);pointer-events:none}.top h1,.top p{color:#fff;position:relative;z-index:1}.top h1{font-size:24px;margin:4px 0}.top p{color:#d9e9ff;margin:4px 0 12px}.top .pill{background:rgba(255,255,255,.13);color:#fff;border-color:rgba(255,255,255,.23)}.top .brand{font-size:10px;letter-spacing:1.7px;font-weight:800;color:#bed9ff}.statrow{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:15px;margin-bottom:22px}.statcard{border:1px solid var(--border);border-radius:15px;background:white;box-shadow:var(--shadow);padding:18px 19px;position:relative;overflow:hidden}.statcard:before{content:"";position:absolute;left:0;top:0;bottom:0;width:3px;background:#367bec}.statcard small{font-weight:600;font-size:12px}.statcard b{font-size:29px;font-weight:760;display:block;line-height:1.4;letter-spacing:-1px;color:#163e88}.statcard:nth-child(3):before{background:#1ea58b}.statcard:nth-child(4):before{background:#d89a37}.sectionhead{display:flex;align-items:center;justify-content:space-between;gap:12px;flex-wrap:wrap;margin-bottom:15px}.sectionhead h2{margin:0}.panel,.wan{background:var(--surface);border:1px solid var(--border);border-radius:16px;padding:21px;margin:17px 0;box-shadow:var(--shadow)}.panel>h2{margin:0 0 14px}.panel>p{margin-bottom:17px}.overview-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(205px,1fr));gap:14px;margin-bottom:20px}.egress-card{border:1px solid #e1eafa;border-radius:14px;background:#fff;padding:17px;box-shadow:var(--shadow);position:relative}.egress-top{display:flex;justify-content:space-between;gap:10px;align-items:center}.egress-card strong{font-size:15px}.egress-card .iface{font-size:12px;color:#6d82a3;margin-top:1px}.egress-line{height:5px;background:#e8f0fb;border-radius:6px;margin:16px 0 12px;overflow:hidden}.egress-line span{display:block;height:100%;background:linear-gradient(90deg,#2467da,#62a4fa);border-radius:6px}.egress-foot{display:flex;justify-content:space-between;font-size:12px;color:#627b9a;gap:8px}.warning-band{padding:13px 16px;border-radius:12px;background:#eff6ff;border:1px solid #dceafe;color:#315f9c;font-size:12px;margin:15px 0}.notice{background:#ecf5ff;border:1px solid #cfe3ff;color:#205ea4;border-radius:11px;padding:13px 15px;margin:15px 0}.error{border-radius:11px;padding:13px 15px;background:#fff0f0;border:1px solid #fecaca;color:#a21d2c}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(205px,1fr));gap:14px}.wan-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(275px,1fr));gap:15px}.wan{margin:0;padding:19px}.wanhead{display:flex;justify-content:space-between;align-items:center;margin-bottom:15px;gap:10px}.wanhead h3{margin:0}.wan .grid{grid-template-columns:repeat(2,minmax(0,1fr));gap:10px}.wan .grid label:last-child{grid-column:1/-1}label{display:block;font-size:12px;color:#526b8f;font-weight:650;margin:0 0 8px}input,select,textarea{font:inherit;width:100%;border:1px solid #d8e3f3;border-radius:9px;padding:10px;background:#fbfdff;color:#213858;margin-top:5px;min-width:0}input:focus,select:focus,textarea:focus{outline:2px solid #a9ceff;border-color:#4285ee;background:#fff}.button{border:0;border-radius:10px;padding:11px 16px;color:#fff;background:#2468dc;font-weight:700;cursor:pointer}.button:hover{background:#1659c8}.button.secondary{background:#eef4ff;color:#2863bd}.button.secondary:hover{background:#e0edff}.wan .remove-wan{margin-top:9px;font-size:12px;padding:8px 12px}.form-actions{display:flex;align-items:end;gap:15px;flex-wrap:wrap}.form-actions label{flex:1;min-width:225px}.form-actions .button{margin-bottom:8px}.tablewrap{overflow-x:auto;border:1px solid var(--border);border-radius:12px}table{width:100%;border-collapse:collapse;background:white}th,td{padding:12px 14px;border-bottom:1px solid #eef2f8;text-align:left;vertical-align:middle;white-space:nowrap}th{background:#f7f9fd;color:#71829f;font-size:11px;font-weight:750;letter-spacing:.2px}tr:last-child td{border-bottom:0}tr:hover td{background:#f9fbff}.mono,.preview{font-family:ui-monospace,SFMono-Regular,Consolas,monospace;font-size:12px}.preview{max-height:390px;overflow:auto;white-space:pre-wrap;overflow-wrap:anywhere;background:#f8faff;padding:13px;border:1px solid #edf1f8;border-radius:10px}.good{color:#088565;font-weight:700}.risk{color:#c27d23;font-weight:700}.empty{text-align:center;color:#8190a7;padding:25px}.tiny{font-size:12px}.footer{color:#8a9bb5;font-size:11px;margin-top:25px}.toolbar{display:flex;gap:9px;margin:15px 0;flex-wrap:wrap}.toolbar a{background:#edf4ff;border-radius:10px;padding:9px 13px;color:#245fae;font-weight:700}.toolbar a:hover{background:#deebff;text-decoration:none}.metric-positive{color:#078968}.metric-negative{color:#cb7e29}.two-col{display:grid;grid-template-columns:1.3fr 1fr;gap:18px}.log-actions{display:flex;gap:7px;flex-wrap:wrap}.log-actions a{font-size:12px;background:#eff5ff;padding:7px 12px;border-radius:8px;font-weight:700}.log-actions a.active{background:#2468dc;color:white}.log-banner{border-left:3px solid #448aff;background:#f1f6ff;padding:12px 15px;font-size:12px;color:#496b9d;border-radius:9px;margin-bottom:20px}
@media(max-width:1080px){.app-shell{grid-template-columns:75px minmax(0,1fr)}.sidebar{padding:25px 10px}.side-brand{padding:0;justify-content:center}.side-brand>div:last-child,.nav-title,.side-nav a .nav-label,.side-bottom{display:none}.side-nav a{justify-content:center}.nav-icon{font-size:20px}.statrow{grid-template-columns:repeat(2,minmax(0,1fr))}.two-col{grid-template-columns:1fr}}@media(max-width:660px){.app-shell{display:block}.sidebar{position:relative;height:auto;padding:12px;gap:10px}.side-brand{justify-content:flex-start}.side-brand>div:last-child{display:block}.side-nav{display:flex;overflow:auto}.side-nav a{padding:8px 10px;gap:6px;white-space:nowrap}.side-nav a .nav-label{display:inline}.main{padding:18px 12px 44px}.statrow{gap:9px}.statcard{padding:12px}.statcard b{font-size:24px}.pagebar{align-items:start}.header-actions{display:none}.top{padding:20px}.panel{padding:15px}.wan .grid{grid-template-columns:1fr}.wan .grid label:last-child{grid-column:auto}.overview-grid{grid-template-columns:repeat(2,minmax(0,1fr))}.egress-card{padding:13px}}
'''

def shell(content,active='home',title='总览',subtitle='网关管理 · 安全预览'):
    nav=[('/', '◫','总览与配置','home'),('/logs','▤','日志与决策','logs'),('/plan','◇','规则预览','plan'),('/ip-pools','◉','IP 池诊断','ip-pools')]
    links=''.join(f'<a class="{"active" if active==slug else ""}" href="{href}"><span class="nav-icon">{icon}</span><span class="nav-label">{label}</span></a>' for href,icon,label,slug in nav)
    return (f'<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>MultiWAN · {e(title)}</title><style>{CSS}</style><script src="/app.js" defer></script></head><body><div class="app-shell"><aside class="sidebar"><div class="side-brand"><div class="brand-mark">M</div><div><strong>MultiWAN</strong><small>NETWORK CONTROL</small></div></div><div><div class="nav-title">工作台</div><nav class="side-nav">{links}</nav></div><div class="side-bottom"><span class="status-dot"></span><b>本机安全管理</b>127.0.0.1 only<br>WAN 变更需确认</div></aside><main class="main"><div class="pagebar"><div><div class="eyebrow">NETWORK OPERATIONS / V3.8</div><h1>{e(title)}</h1><small>{e(subtitle)}</small></div><div class="header-actions"><span class="pill">● Loopback only</span><span class="pill">受控变更模式</span></div></div>{content}</main></div></body></html>')


def time_label(timestamp):return datetime.datetime.fromtimestamp(timestamp,datetime.timezone.utc).strftime('%m-%d %H:%M:%S')
def e(v): return html.escape(str(v),quote=True)
def select(name, options, value):
    opts=''.join(f'<option value="{e(x)}" {"selected" if x==value else ""}>{e(x)}</option>' for x in options)
    return f'<select name="{e(name)}" required>{opts}</select>'
def field(name,value,label): return f'<label>{e(label)}<input name="{e(name)}" value="{e(value)}" required></label>'
def wan_row(w,i,names):
    return f'''<section class="wan" data-wan="{i}"><div class="wanhead"><h3>WAN <span class="wan-number">{i}</span></h3><span class="pill">出口配置</span></div><div class="grid">
    {field(f'wan{i}_name',w['name'],'名称')}
    <label>物理网卡{select(f'wan{i}_interface',names,w['interface'])}</label>
    {field(f'wan{i}_gateway',w['gateway'],'网关')}
    {field(f'wan{i}_prefix',w['prefix'],'CIDR 前缀')}
    {field(f'wan{i}_weight',w.get('weight',1),'ECMP 权重')}
    {field(f'wan{i}_ips',', '.join(w['addresses']),'IPv4 池（逗号分隔，数量可变）')}
    </div><button class="button secondary remove-wan" type="button">移除此 WAN</button></section>'''

def render_page(c, discovered, status, token, message='',err=False):
    names=[d['name'] for d in discovered]
    if not names:
        names=sorted({c['lan']['interface']}|{w['interface'] for w in c['wans']})
    active={c['lan']['interface']}|{w['interface'] for w in c['wans']}
    inventory=''.join(f'<tr><td>{e(d["name"])}</td><td>{e(d["mac"])}</td><td>{"UP" if d["link_up"] else "DOWN" if d["link_up"] is False else "未知"}</td><td>{e(d["speed_mbps"] or "-")}</td><td>{e(", ".join(d["addresses"]))}</td><td>{e(", ".join(d["gateways"]))}</td><td>{"已分配" if d["name"] in active else "未分配"}</td></tr>' for d in discovered)
    mgmt='\n'.join(f"{r['destination']} {r['via']}" for r in c.get('management',{}).get('routes',[]))
    warn=f'<div class="{"error" if err else "notice"}">{e(message)}</div>' if message else ''
    try:
        db=connect(Path(os.environ.get('MULTIWAN_STATE_DIR',str(STATE_DIR)))/'telemetry.sqlite3')
        telemetry=get_dashboard(db);db.close()
    except (OSError,ValueError): telemetry={'metrics':[],'samples':[],'decisions':[]}
    measured=sum(r['samples'] for r in telemetry['metrics'])
    failures=sum(r['failures'] for r in telemetry['metrics'])
    decisions=len(telemetry['decisions'])
    wan_cards=''.join(f'<article class="egress-card"><div class="egress-top"><div><strong>{e(w["name"])}</strong><div class="iface">{e(w["interface"])}</div></div><span class="pill">已配置</span></div><div class="egress-line"><span style="width:{min(100,max(10,round(100*int(w.get("weight",1))/max(1,sum(int(x.get("weight",1)) for x in c["wans"])))))}%"></span></div><div class="egress-foot"><span>{len(w["addresses"])} 个公网 IP</span><span>权重 {e(w.get("weight",1))}</span></div></article>' for w in c['wans'])
    stats=f'''<div class="statrow"><div class="statcard"><small>当前已配置 WAN</small><b>{len(c['wans'])}</b></div><div class="statcard"><small>已识别物理网卡</small><b>{len(discovered)}</b></div><div class="statcard"><small>近 15 分钟真实探测</small><b>{measured}</b></div><div class="statcard"><small>近 15 分钟网络探测失败</small><b>{failures}</b></div></div>'''
    content=f'''<section class="top"><div class="brand">NETWORK OVERVIEW</div><h1>每一条链路，都清晰可控。</h1><p>WAN 动态配置、源 IP 健康分析、决策审计与 LAN 管理保护</p><span class="pill">本机管理</span> <span class="pill">仅生成草稿 · 不应用现网</span></section>
    {stats}
    <div class="sectionhead"><h2>出口资源总览</h2><span class="pill">{len(c['wans'])} WAN · {sum(len(w['addresses']) for w in c['wans'])} IP</span></div><div class="overview-grid">{wan_cards or '<p class="empty">尚未添加 WAN</p>'}</div>
    <div class="warning-band">ⓘ 运行数据只显示真实已采集的探测结果。当前仍为配置预览版，不会自动禁用网卡或改变 NAT。</div>{warn}
    <section class="panel"><div class="sectionhead"><h2>物理接口发现</h2><span class="pill">扫描到 {len(discovered)} 个接口</span></div><div class="tablewrap"><table><tr><th>接口</th><th>MAC 地址</th><th>物理链路</th><th>速率 Mbps</th><th>IPv4</th><th>网关</th><th>角色</th></tr>{inventory or '<tr><td colspan="7" class="empty">未扫描到物理网卡</td></tr>'}</table></div></section>
    <form action="/config" method="post"><input type="hidden" name="csrf" value="{e(token)}"><input type="hidden" id="wan_count" name="wan_count" value="{len(c['wans'])}">
    <section class="panel"><div class="sectionhead"><h2>LAN · 管理链路保护</h2><span class="pill">强制校验</span></div><p>先锁定 LAN 接口、地址、回程网段；WAN 变更不能覆盖这些路由。</p><div class="grid"><label>LAN 物理接口{select('lan_interface',names,c['lan']['interface'])}</label>{field('lan_address',c['lan']['address'],'LAN IPv4 / CIDR')}{field('lan_subnet',c['lan']['subnet'],'受保护 LAN 网段')}</div><label>其他受保护管理路由（每行：网段CIDR 下一跳IPv4）<textarea name="management_routes" rows="3">{e(mgmt)}</textarea></label></section>
    <section class="panel"><div class="sectionhead"><div><h2>WAN 出口配置</h2><small>自由新增和移除物理 WAN，每个出口独立配置 IP 池与 ECMP 权重</small></div><button class="button secondary" id="add-wan" type="button">＋ 添加 WAN</button></div><div id="wan-list" class="wan-grid">{''.join(wan_row(w,i,names) for i,w in enumerate(c['wans'],1))}</div></section>
    <section class="panel"><div class="sectionhead"><h2>保存配置草稿</h2><span class="pill">不影响现网</span></div><div class="form-actions"><label>管理员配置口令<input name="admin_token" type="password" autocomplete="off" required placeholder="MULTIWAN_ADMIN_TOKEN"></label><button class="button" type="submit">校验并保存草稿</button></div><small>保存后通过 <a href="/plan">规则预览</a> 审核差异，当前不会执行应用。</small></section></form>
    <section class="panel"><details><summary style="cursor:pointer;font-weight:700">查看核心状态原始数据（诊断）</summary><pre class="preview">{e(json.dumps(status,ensure_ascii=False,indent=2)[:8000])}</pre></details></section><p class="footer">MultiWAN V3.6 · 操作记录保存在本地 · Web 仅监听 127.0.0.1</p>'''
    body=shell(content,active='home',title='网络控制台',subtitle='实时资源信息与动态接口配置')
    return body.encode()

JS=r'''(() => {
const container=document.getElementById('wan-list'); if(!container)return;
const count=document.getElementById('wan_count');
const ifaceOptions=[...document.querySelectorAll('select[name="lan_interface"] option')].map(o=>o.value);
function numbering(){const cards=[...container.querySelectorAll('[data-wan]')];cards.forEach((card,i)=>{const n=i+1; card.dataset.wan=n;card.querySelector('.wan-number').textContent=n;card.querySelectorAll('[name]').forEach(el=>{el.name=el.name.replace(/^wan\d+_/,`wan${n}_`);});});count.value=cards.length;}
function safeInput(name,value,label){const outer=document.createElement('label');outer.textContent=label;const input=document.createElement('input');input.name=name;input.value=value;input.required=true;outer.append(input);return outer;}
document.getElementById('add-wan').addEventListener('click',()=>{
 if(+count.value>=32)return;const n=+count.value+1;const section=document.createElement('section');section.className='wan';section.dataset.wan=n;
 const h=document.createElement('h3');h.innerHTML='WAN <span class="wan-number"></span>';section.append(h);const grid=document.createElement('div');grid.className='grid';
 grid.append(safeInput(`wan${n}_name`,`WAN${n}`,'名称'));
 const label=document.createElement('label');label.textContent='物理网卡';const select=document.createElement('select');select.name=`wan${n}_interface`;select.required=true;
 ifaceOptions.forEach(x=>{const o=document.createElement('option');o.value=x;o.textContent=x;select.append(o);});
 const used=[...container.querySelectorAll('select')].map(x=>x.value);select.value=ifaceOptions.find(x=>!used.includes(x)&&x!==document.querySelector('[name="lan_interface"]').value)||ifaceOptions[0]||'';
 label.append(select);grid.append(label);
 grid.append(safeInput(`wan${n}_gateway`,'','网关'),safeInput(`wan${n}_prefix`,'24','CIDR 前缀'),safeInput(`wan${n}_weight`,'1','ECMP 权重'),safeInput(`wan${n}_ips`,'','IPv4 池（逗号分隔）'));
 section.append(grid);const del=document.createElement('button');del.type='button';del.className='button secondary remove-wan';del.textContent='移除此 WAN';section.append(del);container.append(section);numbering();
});
container.addEventListener('click',(e)=>{if(e.target.closest('.remove-wan')){e.target.closest('[data-wan]').remove();numbering();}});
})();'''

class Handler(BaseHTTPRequestHandler):
    csrf_token=secrets.token_urlsafe(32)
    def _reply(self,code,data,ctype='text/html; charset=utf-8'):
        self.send_response(code)
        for k,v in [('Content-Type',ctype),('Content-Length',str(len(data))),('Cache-Control','no-store'),('X-Content-Type-Options','nosniff'),('X-Frame-Options','DENY'),('Referrer-Policy','no-referrer'),('Content-Security-Policy',"default-src 'none'; style-src 'unsafe-inline'; script-src 'self'; form-action 'self'; base-uri 'none'; frame-ancestors 'none'")]:self.send_header(k,v)
        self.end_headers();self.wfile.write(data)
    def _config(self):return load_config(os.environ.get('MULTIWAN_CONFIG',str(CONFIG)))
    def _state(self,c):
        path=Path(os.environ.get('MULTIWAN_STATE_DIR',str(STATE_DIR)))/'state.json'
        try:return json.loads(path.read_text()) if path.exists() else current_state(c)
        except (OSError,ValueError):return {'mode':'unknown','message':'state unavailable'}
    def _host_ok(self):return self.headers.get('Host','').split(':')[0].lower() in ('127.0.0.1','localhost')
    def do_GET(self):
        if not self._host_ok():return self._reply(403,b'Invalid Host','text/plain')
        if self.path=='/app.js':return self._reply(200,JS.encode(),'application/javascript')
        if urlsplit(self.path).path not in ('/','/health','/api/status','/api/interfaces','/plan','/api/plan','/logs','/api/logs','/api/ip-pools','/ip-pools','/api/transaction','/transaction','/apply'):return self._reply(404,b'Not Found','text/plain')
        if self.path=='/health':return self._reply(200,b'ok','text/plain')
        if self.path=='/apply':
            content=f"""<div class="top"><div class="brand">GUARDED APPLY</div><h1>应用与确认</h1><p>仅允许已配置 WAN 地址和接口；LAN 与管理路由不变。</p></div>
<section class="panel"><h2>申请应用</h2><p>执行前先设定 180 秒独立回滚计时器，离线后依旧能恢复。请先保持控制台访问。</p>
<form method="post" action="/control"><input type="hidden" name="action" value="apply"><input type="hidden" name="csrf" value="{self.csrf_token}"><label>管理员口令<input type="password" name="admin_token" required></label><label>确认文字：APPLY WAN ONLY<input name="ack" required></label><button class="button" type="submit">一键应用 WAN 配置</button></form></section>
<section class="panel"><h2>确认或回滚</h2><p>重新连入管理通道后，使用上一步获得的确认码确认。</p>
<form method="post" action="/control"><input type="hidden" name="action" value="confirm"><input type="hidden" name="csrf" value="{self.csrf_token}"><label>管理员口令<input type="password" name="admin_token" required></label><label>确认码<input name="confirm_token" required></label><button class="button" type="submit">确认新配置</button></form>
<form method="post" action="/control"><input type="hidden" name="action" value="rollback"><input type="hidden" name="csrf" value="{self.csrf_token}"><label>管理员口令<input type="password" name="admin_token" required></label><button class="button secondary" type="submit">立即回滚</button></form></section>"""
            return self._reply(200,shell(content,active='plan',title='安全应用与确认').encode())
        if urlsplit(self.path).path in ('/api/transaction','/transaction','/apply'):
            from .actuator import load_transaction
            state_dir=Path(os.environ.get('MULTIWAN_STATE_DIR',str(STATE_DIR)))
            try:
                tx=load_transaction(state_dir)
                report={k:v for k,v in (tx or {}).items() if k not in ('token','previous','candidate')}
            except (OSError,ValueError):report={'state':'unavailable'}
            if urlsplit(self.path).path=='/api/transaction':
                return self._reply(200,json.dumps(report,ensure_ascii=False).encode(),'application/json')
            content='<div class="top"><h1>网络变更与回滚状态</h1><p>严格受保护的运行事务 · Web 只读 · 127.0.0.1</p></div>' + \
                '<section class="panel"><h2>事务状态</h2><pre>'+e(json.dumps(report,ensure_ascii=False,indent=2))+'</pre></section>' + \
                '<section class="panel"><h2>安全操作方式</h2><p>为了防止本机 Web 进程获得 root 权限，真实应用与确认操作必须通过 sudo multiwan.actuator CLI 完成。未确认的事务由独立 systemd 计时服务执行回滚。</p></section>'
            return self._reply(200,shell(content,active='plan',title='变更事务',subtitle='确认、状态与回滚').encode())

        if urlsplit(self.path).path in ('/api/ip-pools','/ip-pools'):
            from .ip_policy import propose_pools, render_snat_pools
            try:
                c=self._config()
                db=connect(Path(os.environ.get('MULTIWAN_STATE_DIR',str(STATE_DIR)))/'telemetry.sqlite3')
                proposals=propose_pools(db,c)
                db.close()
                preview=render_snat_pools(c,proposals)
            except (OSError,ValueError,KeyError) as ex:
                return self._reply(503,e(ex).encode(),'text/plain')
            if urlsplit(self.path).path=='/api/ip-pools':
                return self._reply(200,json.dumps({'proposals':proposals,'nft_preview':preview,'applied':False},ensure_ascii=False).encode(),'application/json')
            cards=''
            for p in proposals:
                rows=''.join('<tr><td>'+e(ip)+'</td><td>'+str(s['samples'])+'</td><td>'+str(s['targets'])+'</td><td>'+('—' if s['failure_rate'] is None else f"{100*s['failure_rate']:.1f}%")+'</td><td>'+('暂缓推荐' if ip in p['suspects'] and ip not in p['ips'] else '观察')+'</td></tr>' for ip,s in p['metrics'].items())
                cards += f'<section class="panel"><div class="sectionhead"><h2>{e(p["wan"])} · {e(p["interface"])}</h2><span class="pill">可选地址 {len(p["ips"])} / {len(p["metrics"])}</span></div><p>{e(p["reason"])}</p><div class="tablewrap"><table><tr><th>公网 IP</th><th>有效样本</th><th>目标数</th><th>失败率</th><th>建议</th></tr>{rows}</table></div></section>'
            content='<div class="top"><div class="brand">SOURCE IP EVIDENCE</div><h1>公网 IP 池与切换依据</h1><p>源 IP TCP 真实探测 · 同组候选 IP · NAT 规则草案</p></div><div class="notice">这是诊断及 NAT 预览。未修改内核规则，未自动禁用 WAN；样本不足时不会排除 IP。</div>'+cards+'<section class="panel"><h2>NAT 地址池规则预览</h2><pre class="preview">'+e(preview)+'</pre></section>'
            return self._reply(200,shell(content,active='ip-pools',title='公网 IP 质量',subtitle='源地址探测 · 故障证据 · 切换建议').encode())
        if urlsplit(self.path).path in ('/logs','/api/logs','/api/ip-pools','/ip-pools'):
            params=parse_qs(urlsplit(self.path).query)
            try:window=min(86400,max(60,int(params.get('window',[900])[0])))
            except ValueError:window=900
            try:
                db=connect(Path(os.environ.get('MULTIWAN_STATE_DIR',str(STATE_DIR)))/'telemetry.sqlite3')
                report=get_dashboard(db,window=window,limit=100)
                recommendations=[evaluate_wan(db,w['name'],window=min(window,3600)) for w in self._config()['wans']]
                db.close()
            except (OSError,ValueError,KeyError) as ex:
                return self._reply(503,e(ex).encode(),'text/plain')
            if urlsplit(self.path).path=='/api/logs':
                return self._reply(200,json.dumps({'report':report,'recommendations':recommendations},ensure_ascii=False).encode(),'application/json')
            metrics=''.join(f'<tr><td>{e(m["wan"])}</td><td>{e(m["source_ip"] or "未绑定源IP")}</td><td>{m["samples"]}</td><td>{m["targets"]}</td><td>{m["successes"]}</td><td>{m["failures"]}</td><td>{m["failure_rate"]*100:.1f}%</td><td>{e(m["avg_latency_ms"] or "—")}</td></tr>' for m in report['metrics'])
            decisions=''.join(f'<tr><td class="mono">{e(time_label(x["at"]))}</td><td>{e(x["subject"])}</td><td>{e(x["action"])}</td><td>{e(x["reason"])}</td><td class="mono">{e(x["evidence"][:240])}</td><td>{e(x["status"])}</td></tr>' for x in report['decisions'])
            samples=''.join(f'<tr><td class="mono">{e(time_label(x["at"]))}</td><td>{e(x["wan"])}</td><td>{e(x["source_ip"] or "—")}</td><td>{e(x["target"])}</td><td>{e(x["kind"])}</td><td class="{("good" if x["outcome"]=="success" else "risk")}">{e(x["outcome"])}</td><td>{e(x["origin"])}</td></tr>' for x in report['samples'])
            notes=''.join(f'<tr><td>{e(a["wan"])}</td><td>{a["samples"]}</td><td>{a["targets"]}</td><td>{"—" if a["failure_rate"] is None else str(round(a["failure_rate"]*100,1))+"%"}</td><td>{"需人工核实" if a["recommendation"]=="investigate" else "继续观察"}</td></tr>' for a in recommendations)
            total=sum(m['samples'] for m in report['metrics'])
            total_fail=sum(m['failures'] for m in report['metrics'])
            fail_percent=(total_fail*100/total) if total else 0
            logstats=f'''<div class="statrow"><div class="statcard"><small>真实探测样本</small><b>{total}</b></div><div class="statcard"><small>网络失败次数</small><b>{total_fail}</b></div><div class="statcard"><small>有效失败率</small><b>{fail_percent:.1f}%</b></div><div class="statcard"><small>切换决策记录</small><b>{len(report['decisions'])}</b></div></div>'''
            content=f'''<div class="top"><div class="brand">OBSERVABILITY & AUDIT</div><h1>每一次切换，都有证据。</h1><p>网络异常 · 公网 IP 质量 · 失败率 · 决策追溯</p><span class="pill">SQLite 日志</span> <span class="pill">仅统计真实探测</span></div>
            {logstats}<div class="sectionhead"><h2>观察窗口</h2><div class="log-actions"><a href="/logs?window=300" class="{'active' if window==300 else ''}">5 分钟</a><a href="/logs?window=900" class="{'active' if window==900 else ''}">15 分钟</a><a href="/logs?window=3600" class="{'active' if window==3600 else ''}">1 小时</a><a href="/logs?window=86400" class="{'active' if window==86400 else ''}">24 小时</a></div></div>
            <div class="log-banner">统计只使用真实探测样本。普通 Ping 超时、目标返回 403/429 均不足以判定公网源 IP 故障，当前界面不执行自动封禁。</div>
            <section class="panel"><div class="sectionhead"><h2>公网出口可达性</h2><span class="pill">{window} 秒窗口</span></div><div class="tablewrap"><table><tr><th>WAN</th><th>源 IP</th><th>有效样本</th><th>目标</th><th>成功</th><th>网络失败</th><th>失败率</th><th>平均延迟</th></tr>{metrics or '<tr><td colspan="8" class="empty">暂无真实探测样本，无法生成可靠失败率。</td></tr>'}</table></div></section>
            <section class="panel"><h2>WAN 故障证据与建议</h2><div class="tablewrap"><table><tr><th>WAN</th><th>样本量</th><th>独立目标</th><th>失败率</th><th>建议</th></tr>{notes}</table></div></section>
            <section class="panel"><h2>切换 / 禁用 / 恢复审计</h2><div class="tablewrap"><table><tr><th>UTC 时间</th><th>对象</th><th>动作</th><th>原因</th><th>证据快照</th><th>状态</th></tr>{decisions or '<tr><td colspan="6" class="empty">尚无切换决策记录</td></tr>'}</table></div></section>
            <section class="panel"><h2>最新探测明细</h2><div class="tablewrap"><table><tr><th>UTC 时间</th><th>WAN</th><th>源 IP</th><th>探测目标</th><th>类型</th><th>结果</th><th>来源</th></tr>{samples or '<tr><td colspan="7" class="empty">暂无探测明细</td></tr>'}</table></div></section><p class="footer">数据库：MULTIWAN_STATE_DIR/telemetry.sqlite3 · 当前决策仅供审核，不自动应用。</p>'''
            page=shell(content,active='logs',title='日志与健康分析',subtitle='可观测性、故障证据与动作审计')
            return self._reply(200,page.encode())
        try:c=self._config();inventory=discover_interfaces();s=self._state(c)
        except (OSError,ValueError,KeyError) as ex:return self._reply(503,e(ex).encode(),'text/plain')
        if self.path=='/api/status':return self._reply(200,json.dumps(s).encode(),'application/json')
        if self.path=='/api/interfaces':return self._reply(200,json.dumps(inventory).encode(),'application/json')
        if self.path in ('/plan','/api/plan'):
            pending=Path(os.environ.get('MULTIWAN_CONFIG',str(CONFIG))).with_name('config.pending.json')
            if not pending.exists():return self._reply(404,b'No pending configuration','text/plain')
            try:result=plan(c,validate_candidate(json.loads(pending.read_text()),inventory))
            except (ValueError,KeyError,OSError) as ex:return self._reply(400,str(ex).encode(),'text/plain')
            if self.path=='/api/plan':return self._reply(200,json.dumps(result,ensure_ascii=False).encode(),'application/json')
            warnings=''.join('<li>'+e(x)+'</li>' for x in result['warnings'])
            sections=''.join(f'<details class="panel" {"open" if key=="diff" else ""}><summary>{e(label)}</summary><pre class="preview">{e(result[key])}</pre></details>' for key,label in [('diff','配置差异'),('netplan','Netplan 与 LAN 管理路由'),('ecmp_command','ECMP 命令'),('nft','NAT 规则')])
            content=f'<div class="top"><div class="brand">CHANGE REVIEW</div><h1>变更先审查，再执行。</h1><p>默认只读预览；明确确认后可通过受控服务应用已配置的 WAN 路由及 NAT。</p></div><div class="notice">LAN/管理路由变化属于高风险，必须控制台审核。</div><section class="panel"><h2>变更风险与摘要</h2><ul>{warnings}</ul><small class="mono">SHA-256: {e(result["sha256"])}</small></section>{sections}'
            page=shell(content,active='plan',title='规则变更预览',subtitle='Netplan · ECMP · nftables')
            return self._reply(200,page.encode())
        self._reply(200,render_page(c,inventory,s,self.csrf_token))
    def _control_post(self):
        if not self._host_ok():return self._reply(403,b'Invalid Host','text/plain')
        origin=self.headers.get('Origin')
        allowed=(f'http://127.0.0.1:{self.server.server_port}',f'http://localhost:{self.server.server_port}')
        if origin and origin not in allowed:return self._reply(403,b'Invalid Origin','text/plain')
        try:
            length=int(self.headers.get('Content-Length','0'))
            if not 1<=length<=4096:return self._reply(413,b'Invalid body size','text/plain')
            fields=parse_qs(self.rfile.read(length).decode(),strict_parsing=True)
            form={k:v[0] for k,v in fields.items() if len(v)==1}
            expected=os.environ.get('MULTIWAN_ADMIN_TOKEN','')
            if len(expected)<24 or not hmac.compare_digest(expected,form.get('admin_token','')) or not hmac.compare_digest(self.csrf_token,form.get('csrf','')):
                return self._reply(403,b'Authentication or CSRF failed','text/plain')
            action=form.get('action')
            if action not in ('apply','confirm','rollback'):raise ValueError('Invalid operation')
            if action=='apply' and form.get('ack')!='APPLY WAN ONLY':raise ValueError('Explicit acknowledgement required')
            from .control_daemon import request
            result=request(action,**({'token':form.get('confirm_token','')} if action=='confirm' else {}))
            if not result.get('ok'):raise RuntimeError(result.get('error','Control daemon rejected change'))
            note=html.escape(json.dumps(result,ensure_ascii=False))
            content='<div class="top"><h1>操作结果</h1></div><section class="panel"><pre class="preview">'+note+'</pre><p>确认码只在应用响应中显示；重新连接管理页面后请完成确认。</p><a href="/apply">返回应用与确认</a></section>'
            return self._reply(200,shell(content,title='变更结果').encode())
        except (ValueError,OSError,RuntimeError,UnicodeError) as exc:
            return self._reply(400,('Operation rejected: '+str(exc)).encode(),'text/plain')

    def do_POST(self):
        if not self._host_ok():return self._reply(403,b'Invalid Host','text/plain')
        if self.path=='/control':return self._control_post()
        if self.path!='/config':return self._reply(404,b'Not Found','text/plain')
        origin=self.headers.get('Origin')
        if origin and origin not in (f'http://127.0.0.1:{self.server.server_port}',f'http://localhost:{self.server.server_port}'):
            return self._reply(403,b'Invalid Origin','text/plain')
        try:
            length=int(self.headers.get('Content-Length','0'))
            if length<1 or length>65536:return self._reply(413,b'Body too large','text/plain')
            values=parse_qs(self.rfile.read(length).decode(),keep_blank_values=True,strict_parsing=True)
            form={k:v[0] for k,v in values.items() if len(v)==1}
            expected=os.environ.get('MULTIWAN_ADMIN_TOKEN','')
            if len(expected)<24 or not hmac.compare_digest(expected,form.pop('admin_token','')) or not hmac.compare_digest(self.csrf_token,form.pop('csrf','')):
                return self._reply(403,b'Authentication or CSRF failed','text/plain')
            c=self._config();inventory=discover_interfaces();candidate=build_candidate_from_form(c,form)
            checked=stage_config(candidate,os.environ.get('MULTIWAN_CONFIG',str(CONFIG)),inventory)
            self._reply(200,render_page(checked,inventory,self._state(c),self.csrf_token,'草稿已保存；未修改正在运行的网络。'))
        except (ValueError,KeyError,TypeError,OSError,UnicodeError) as ex:
            try:
                c=self._config();self._reply(400,render_page(c,discover_interfaces(),self._state(c),self.csrf_token,'配置未保存：'+str(ex),True))
            except Exception:self._reply(400,b'Invalid configuration','text/plain')

def main():
    c=load_config(os.environ.get('MULTIWAN_CONFIG',str(CONFIG)))
    server=ThreadingHTTPServer(('127.0.0.1',int(c['web']['port'])),Handler)
    print('Web bound to 127.0.0.1:',c['web']['port'],flush=True)
    server.serve_forever()
if __name__=='__main__':main()
