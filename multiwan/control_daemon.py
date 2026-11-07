"""Root-owned, narrowly scoped Unix socket control service.

Neither network paths nor shell commands are accepted from HTTP or socket clients.
Network changes remain guarded by actuator's preflight + independent rollback.
"""
import json
import os
import socket
import socketserver
from pathlib import Path
from .actuator import apply, confirm, rollback, load_transaction, file_write
from .config_portal import validate_candidate

SOCKET = '/run/multiwan/control.sock'
ACTIVE = '/etc/multiwan/config.json'
STATE = '/var/lib/multiwan'


def safe_status(state):
    tx=load_transaction(state)
    return {k:v for k,v in (tx or {}).items() if k not in ('token','previous','candidate')}


def dispatch(request, *, active=ACTIVE, state=STATE):
    operation=request.get('action')
    if operation=='status': return {'ok':True,'transaction':safe_status(state)}
    if operation=='apply':
        active_path=Path(active)
        pending=active_path.with_name('config.pending.json')
        if not pending.is_file(): raise ValueError('No validated pending configuration')
        old=validate_candidate(json.loads(active_path.read_text()))
        candidate=validate_candidate(json.loads(pending.read_text()))
        pools={w['name']:list(w['addresses']) for w in candidate['wans']}
        tx=apply(old,candidate,pools,state,seconds=180)
        # Persist exact applied candidate, do not trust later edits of pending.
        transaction=load_transaction(state)
        transaction['candidate']=candidate
        file_write(Path(state)/'transaction.json',transaction)
        return {'ok':True,'transaction':{k:v for k,v in tx.items() if k!='token'},'confirm_token':tx['token']}
    if operation=='confirm':
        token=request.get('token','')
        if not isinstance(token,str) or len(token)>128:raise ValueError('Bad token')
        tx=load_transaction(state)
        if not tx or 'candidate' not in tx:raise ValueError('Missing pinned candidate')
        # Confirm first checks deadline and token; keep config pinned to the executed revision.
        confirm(state,token)
        from .core import atomic_json
        atomic_json(Path(active),tx['candidate'])
        os.chmod(active,0o640)
        return {'ok':True,'transaction':safe_status(state)}
    if operation=='rollback':
        return {'ok':True,'result':rollback(state),'transaction':safe_status(state)}
    raise ValueError('Unsupported action')

class Handler(socketserver.StreamRequestHandler):
    def handle(self):
        raw=self.rfile.readline(4097)
        if not raw or len(raw)>4096:
            return
        try:
            request=json.loads(raw)
            if not isinstance(request,dict):raise ValueError('Object expected')
            reply=dispatch(request,active=self.server.active,state=self.server.state)
        except Exception as exc:
            reply={'ok':False,'error':str(exc)[:500]}
        self.wfile.write((json.dumps(reply,ensure_ascii=False)+'\n').encode())

class Server(socketserver.ThreadingUnixStreamServer):
    daemon_threads=True

def main():
    if os.geteuid()!=0:raise PermissionError('Root control daemon required')
    p=Path(os.environ.get('MULTIWAN_CONTROL_SOCKET',SOCKET))
    p.parent.mkdir(mode=0o750,parents=True,exist_ok=True)
    if p.exists():p.unlink()
    with Server(str(p),Handler) as srv:
        srv.active=os.environ.get('MULTIWAN_CONFIG',ACTIVE)
        srv.state=os.environ.get('MULTIWAN_STATE_DIR',STATE)
        os.chmod(p,0o660)
        srv.serve_forever()


def request(action, **fields):
    path=os.environ.get('MULTIWAN_CONTROL_SOCKET',SOCKET)
    with socket.socket(socket.AF_UNIX,socket.SOCK_STREAM) as s:
        s.settimeout(12)
        s.connect(path)
        s.sendall((json.dumps({'action':action,**fields})+'\n').encode())
        response=b''
        while not response.endswith(b'\n') and len(response)<16384:
            piece=s.recv(16384-len(response))
            if not piece:break
            response+=piece
    if not response:raise RuntimeError('No response from root control daemon')
    return json.loads(response)

if __name__=='__main__':main()
