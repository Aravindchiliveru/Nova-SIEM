"""Loopback-only laboratory server. Production identity/TLS are release gates."""
import argparse
import hashlib
import hmac
import json
import logging
import math
import os
import secrets
import signal
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse
from .core import Engine, Problem, ROOT, identifier

PERMISSIONS={
 'viewer':{'read'},'analyst':{'read','case'},
 'collector':{'ingest'},'admin':{'read','ingest','case','manage'}
}

class Service:
    def __init__(self,engine,credentials,verifier=None):
        self.engine=engine
        from .enterprise import Enterprise
        self.enterprise=Enterprise(engine)
        from .soar import External
        self.external=External(self.enterprise,json.loads(Path(os.environ['NOVA_SOAR_CONFIG']).read_text()) if os.environ.get('NOVA_SOAR_CONFIG') else {})
        self.external_error=False
        self.credentials=credentials
        self.verifier=verifier
        if self.verifier is None and os.environ.get('NOVA_OIDC_CONFIG'):
            from .identity import JWTVerifier
            self.verifier=JWTVerifier.from_file(os.environ['NOVA_OIDC_CONFIG'])
        self.stop=threading.Event()
        self.worker_error=False
        self.rate_lock=threading.Lock()
        self.rate_state={}
        seen_grants=set()
        for item in credentials:
            opaque=isinstance(item.get('token_sha256'),str) and len(item['token_sha256'])==64
            federated=isinstance(item.get('oidc_sub'),str) and 1<=len(item['oidc_sub'])<=256 and self.verifier is not None
            if item.get('role') not in PERMISSIONS or not (opaque ^ federated) or not item.get('tenant'):
                raise ValueError('invalid credentials configuration')
            grant=('opaque',item.get('token_sha256')) if opaque else ('subject',item.get('oidc_sub'))
            if grant in seen_grants:raise ValueError('duplicate credential or subject grant')
            seen_grants.add(grant)
            identifier(item.get('tenant'),'tenant')
            identifier(item.get('name'),'credential name')
            if 'expires_at' in item and (type(item['expires_at']) not in (int,float) or not math.isfinite(item['expires_at'])):raise ValueError('invalid credential expiry')
            if 'revoked' in item and type(item['revoked']) is not bool:raise ValueError('invalid credential revocation flag')
            if 'sources' in item:
                if not isinstance(item['sources'],list):raise ValueError('sources must be a list')
                for source in item['sources']:identifier(source,'source grant')

    def authenticate(self,header,permission):
        if not header.startswith('Bearer ') or len(header)>16400:
            raise Problem('authentication required',401)
        token=header[7:];digest=hashlib.sha256(token.encode()).hexdigest()
        selected=None
        for identity in self.credentials:
            if 'token_sha256' in identity and hmac.compare_digest(digest,identity['token_sha256']):
                selected=identity;break
        if selected is None and self.verifier and token.count('.')==2:
            claims=self.verifier.verify(token)
            # Tenant and roles come exclusively from locally configured subject grants.
            selected=next((i for i in self.credentials if i.get('oidc_sub')==claims['sub']),None)
        if selected is None:raise Problem('invalid credential or missing subject grant',401)
        if selected.get('revoked') or time.time()>=selected.get('expires_at',float('inf')):raise Problem('credential expired or revoked',401)
        if permission not in PERMISSIONS[selected['role']]:raise Problem('permission denied',403)
        with self.rate_lock:
            key=self.credentials.index(selected)
            now=time.monotonic();tokens,previous=self.rate_state.get(key,(200.,now))
            tokens=min(200.,tokens+(now-previous)*100)
            if tokens<1:raise Problem('request rate limit reached',429)
            self.rate_state[key]=(tokens-1,now)
        return selected

    def worker(self):
        failures=0
        while not self.stop.is_set():
            try:
                worked=self.engine.drain(100)
                worked+=self.enterprise.tick()
                failures=0; self.worker_error=False
                if not worked: self.stop.wait(.15)
            except Exception:
                failures+=1; self.worker_error=True
                logging.exception('worker transaction failed; journal retained')
                if failures>=5:
                    logging.error('worker stopped after five failures; operator inspection required')
                    return
                self.stop.wait(min(2**failures,16))

    def external_worker(self):
        while not self.stop.is_set():
            try:
                worked=self.external.tick();self.external_error=False
                if not worked:self.stop.wait(.5)
            except Exception:
                self.external_error=True;self.stop.wait(5)

    def workflow_worker(self):
        failures=0
        while not self.stop.is_set():
            try:
                worked=self.enterprise.tick();failures=0;self.worker_error=False
                if not worked:self.stop.wait(.5)
            except Exception:
                failures+=1;self.worker_error=True
                if failures>=5:return
                self.stop.wait(min(2**failures,16))

class Server(ThreadingHTTPServer):
    daemon_threads=True
    def __init__(self,address,service):
        self.service=service
        self.slots=threading.BoundedSemaphore(32)
        super().__init__(address,Handler)

    def process_request(self,request,client_address):
        if not self.slots.acquire(blocking=False):
            try:
                request.settimeout(.1)
                request.sendall(b'HTTP/1.1 503 Service Unavailable\r\nContent-Length: 0\r\nConnection: close\r\nRetry-After: 1\r\n\r\n')
            except OSError:pass
            finally:self.shutdown_request(request)
            return
        try:super().process_request(request,client_address)
        except Exception:
            self.slots.release();raise
    def process_request_thread(self,request,client_address):
        try:super().process_request_thread(request,client_address)
        finally:self.slots.release()

class Handler(BaseHTTPRequestHandler):
    server_version='NovaLab/0.6'
    def setup(self):
        super().setup()
        self.connection.settimeout(10)
    def log_message(self,*args):
        pass
    def reply(self,status,data,ctype='application/json'):
        if ctype=='application/json':
            data=json.dumps(data,allow_nan=False).encode()
        elif isinstance(data,str): data=data.encode()
        self.send_response(status)
        self.send_header('Content-Type',ctype)
        self.send_header('Content-Length',str(len(data)))
        self.send_header('Cache-Control','no-store')
        self.send_header('X-Content-Type-Options','nosniff')
        self.send_header('Referrer-Policy','no-referrer')
        self.send_header('Content-Security-Policy',"default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'")
        self.send_header('Connection','close')
        if status in (429,503):self.send_header('Retry-After','1')
        self.end_headers()
        self.wfile.write(data)
        self.close_connection=True
    def body(self):
        if self.headers.get('Transfer-Encoding'):
            raise Problem('chunked requests are not supported',400)
        if self.headers.get('Content-Type','').split(';')[0]!='application/json':
            raise Problem('Content-Type must be application/json',415)
        if len(self.headers.get_all('Content-Length',[]))!=1:raise Problem('exactly one Content-Length required')
        try:
            n=int(self.headers.get('Content-Length','-1'))
        except ValueError: raise Problem('invalid Content-Length')
        if not 0<n<=1048576: raise Problem('request must contain 1 byte to 1 MiB',413)
        try:
            def no_duplicates(pairs):
                obj={}
                for key,value in pairs:
                    if key in obj: raise ValueError('duplicate JSON key')
                    obj[key]=value
                return obj
            def reject_constant(v): raise ValueError('invalid JSON number')
            raw=self.rfile.read(n)
            if len(raw)!=n: raise ValueError('incomplete body')
            body=json.loads(raw,object_pairs_hook=no_duplicates,parse_constant=reject_constant)
            if not isinstance(body,dict): raise ValueError('object required')
            return body
        except (ValueError,UnicodeDecodeError,RecursionError): raise Problem('invalid JSON object')
    def do_GET(self): self.dispatch('GET')
    def do_POST(self): self.dispatch('POST')
    def dispatch(self,method):
        try:
            # Bind loopback and reject unexpected host/origin for browser access.
            port=self.server.server_port
            hosts={f'localhost:{port}',f'127.0.0.1:{port}'}
            if len(self.headers.get_all('Host',[]))!=1 or self.headers.get('Host') not in hosts:
                raise Problem('unrecognized host',403)
            origin=self.headers.get('Origin')
            if origin and origin not in {'http://'+h for h in hosts}:
                raise Problem('cross-origin access denied',403)
            u=urlparse(self.path); path=u.path
            assets={'/':('index.html','text/html; charset=utf-8'),'/app.js':('app.js','text/javascript; charset=utf-8'),'/style.css':('style.css','text/css; charset=utf-8')}
            if method=='GET' and path in assets:
                name,ctype=assets[path]
                return self.reply(200,(ROOT/'web'/name).read_bytes(),ctype)
            if method=='GET' and path=='/healthz':
                return self.reply(200,{'status':'running','mode':getattr(self.server.service.engine,'mode','local-reference')})
            permissions={
                ('POST','/api/external'):'case',('POST','/api/external/transition'):'manage',('POST','/api/evidence/export'):'case',('POST','/api/rules/configure'):'manage',('POST','/api/integrations/test'):'manage',('POST','/api/integrations/deactivate'):'manage',('POST','/api/workflows'):'case',('POST','/api/workflows/transition'):'manage',('POST','/api/audit/verify'):'read',('POST','/api/events'):'ingest',('POST','/api/integrations/activate'):'manage',
                ('POST','/api/quarantine/replay'):'manage',('POST','/api/cases'):'case',('POST','/api/cases/update'):'case',('POST','/api/rules/simulate'):'manage'}
            reads={'/api/external','/api/connectors','/api/event/ocsf','/api/workflows','/api/playbooks','/api/audit/checkpoint','/api/rules','/api/case','/api/event','/api/search','/api/alerts','/api/cases','/api/audit','/api/quarantine','/api/integrations','/api/health','/metrics'}
            permission=permissions.get((method,path)) or ('read' if method=='GET' and path in reads else None)
            if not permission: raise Problem('route not found',404)
            svc=self.server.service
            who=svc.authenticate(self.headers.get('Authorization',''),permission)
            tenant,actor=who['tenant'],who['name']; e=svc.engine
            if method=='POST':
                b=self.body()
                if path=='/api/external':result=svc.external.create(tenant,actor,b)
                elif path=='/api/external/transition':result=svc.external.transition(tenant,actor,b)
                elif path=='/api/evidence/export':result=svc.enterprise.export_case(tenant,actor,b)
                elif path=='/api/rules/configure':result=svc.enterprise.set_rule(tenant,actor,b)
                elif path=='/api/integrations/test':result=svc.enterprise.test_integration(b)
                elif path=='/api/integrations/deactivate':result=svc.enterprise.deactivate_integration(tenant,actor,b)
                elif path=='/api/workflows':result=svc.enterprise.create(tenant,actor,b)
                elif path=='/api/workflows/transition':result=svc.enterprise.transition(tenant,actor,b)
                elif path=='/api/audit/verify':
                    if set(b)!={'anchor'} or not isinstance(b['anchor'],dict):raise Problem('anchor object required')
                    result=svc.enterprise.integrity(tenant,b['anchor'])
                elif path=='/api/events':
                    if who.get('sources') is not None and b.get('source') not in who['sources']:
                        raise Problem('source is not authorized for this credential',403)
                    result=e.ingest(tenant,actor,b)
                elif path=='/api/integrations/activate': result=e.activate(tenant,actor,b.get('package'))
                elif path=='/api/cases/update': result=e.update_case(tenant,actor,b)
                elif path=='/api/rules/simulate':
                    from .rules import Rules
                    result=Rules.simulate(b.get('rule'),b.get('events'))
                elif path=='/api/quarantine/replay': result=e.replay(tenant,actor,b.get('event_id'))
                else: result=e.create_case(tenant,actor,b.get('alert_id'))
                return self.reply(200,result)
            if path=='/api/external':result=svc.external.listing(tenant)
            elif path=='/api/connectors':result=svc.external.catalog(tenant)
            elif path=='/api/event/ocsf':
                params=parse_qs(u.query)
                if set(params)!={'id'} or len(params['id'])!=1:raise Problem('event id required')
                event=e.event(tenant,params['id'][0])
                if not event or not event.get('normalized'):raise Problem('normalized event not found',404)
                from .ocsf import export
                result=export(event['normalized'])
            elif path=='/api/workflows':result=svc.enterprise.listing(tenant)
            elif path=='/api/playbooks':result=svc.enterprise.catalog()
            elif path=='/api/audit/checkpoint':result=svc.enterprise.integrity(tenant)
            elif path=='/api/rules':result=svc.enterprise.rule_catalog(tenant)
            elif path=='/api/case':
                params=parse_qs(u.query)
                if set(params)!={'id'} or len(params['id'])!=1:raise Problem('case id required')
                result=e.case_detail(tenant,params['id'][0])
            elif path=='/api/event':
                params=parse_qs(u.query)
                if set(params)!={'id'} or len(params['id'])!=1: raise Problem('event id required')
                result=e.event(tenant,params['id'][0])
            elif path=='/api/search':
                raw=parse_qs(u.query,keep_blank_values=True)
                if any(len(v)!=1 for v in raw.values()): raise Problem('duplicate query parameter')
                result=e.search(tenant,{k:v[0] for k,v in raw.items()})
            elif path=='/api/integrations': result=e.integrations(tenant)
            elif path in ('/api/health','/metrics'):
                result=e.health(tenant); result['external_worker_error']=svc.external_error; result.update(svc.enterprise.health(tenant)); result.update(svc.external.health(tenant)); result['worker_error']=result.get('worker_error',False) or svc.worker_error
                if svc.worker_error or svc.external_error or result.get('workflow_failed') or result.get('external_failed'): result['status']='attention'
                if path=='/metrics':
                    lines=[]
                    for k,v in result.items():
                        if type(v) in (int,float):
                            lines.extend([f'# TYPE nova_{k} gauge',f'nova_{k} {v}'])
                    lines.extend(['# TYPE nova_worker_error gauge',f"nova_worker_error {int(result.get('worker_error',False))}"])
                    return self.reply(200,'\n'.join(lines)+'\n','text/plain; version=0.0.4')
            else: result=e.listing(tenant,path.split('/')[-1])
            return self.reply(200,result)
        except Problem as e:
            self.reply(e.status,{'error':str(e)})
        except (BrokenPipeError,ConnectionResetError,TimeoutError):
            self.close_connection=True
        except Exception:
            logging.exception('request failed')
            self.reply(500,{'error':'internal error; request was not acknowledged'})

def initialize(directory):
    directory=Path(directory)
    directory.mkdir(parents=True,exist_ok=True,mode=0o700)
    target=directory/'credentials.json'
    if target.exists(): raise SystemExit('Credentials already exist; initialization will not overwrite them.')
    credentials=[]; tokens={}
    for name,role in [('admin','admin'),('collector','collector'),('analyst','analyst')]:
        token=secrets.token_urlsafe(32)
        tokens[name]=token
        credentials.append(dict(name=name,role=role,tenant='demo',token_sha256=hashlib.sha256(token.encode()).hexdigest()))
    for filename,data in [('credentials.json',credentials),('local-tokens.json',tokens)]:
        fd=os.open(directory/filename,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
        with os.fdopen(fd,'w') as f: json.dump(data,f,indent=2)
    print('Created local credentials. Open data/local-tokens.json to copy the admin token. Keep this file private.')

def main():
    os.umask(0o077)
    p=argparse.ArgumentParser(description='Nova SIEM local development reference')
    p.add_argument('command',choices=['init','serve'])
    p.add_argument('--data',default='data')
    p.add_argument('--port',type=int,default=8787)
    args=p.parse_args()
    if args.command=='init': return initialize(args.data)
    if os.environ.get('NOVA_REQUIRE_HA')=='1':raise SystemExit('SQLite local mode cannot satisfy HA preflight')
    directory=Path(args.data)
    credentials=json.loads((directory/'credentials.json').read_text())
    service=Service(Engine(directory/'nova.db'),credentials)
    server=Server(('127.0.0.1',args.port),service)
    worker=threading.Thread(target=service.worker,daemon=True); worker.start()
    external=threading.Thread(target=service.external_worker,daemon=True);external.start()
    print(f'Nova local reference: http://127.0.0.1:{args.port} — Ctrl+C to stop',flush=True)
    try: server.serve_forever()
    except KeyboardInterrupt: pass
    finally:
        service.stop.set(); worker.join(timeout=20); external.join(timeout=20); server.server_close()

if __name__=='__main__': main()
