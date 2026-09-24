"""Defender response adapter. Durable submission intent prevents ambiguous replay."""
import hashlib,re
from pathlib import Path
from urllib.request import Request,build_opener,ProxyHandler
from urllib.error import HTTPError
from .core import Problem,canonical
from .collector import NoRedirect
from .distributed.contracts import strict_json

SCHEMA='''CREATE TABLE IF NOT EXISTS nova_vendor_operations (
 job_id TEXT PRIMARY KEY, tenant TEXT NOT NULL, digest TEXT NOT NULL,
 state TEXT NOT NULL, operation_id TEXT, receipt TEXT NOT NULL);'''

class Pending(Exception):pass
class Uncertain(Exception):pass

def validate_config(cfg):
    if cfg.get('kind')!='defender':raise Problem('unsupported vendor connector')
    if cfg['url']!='https://api.security.microsoft.com':raise Problem('Defender requires its fixed public API origin')
    assets=cfg.get('assets')
    if not isinstance(assets,dict) or set(assets)!=set(cfg['tenants']):raise Problem('explicit per-tenant machine grants required')
    for ids in assets.values():
        if not isinstance(ids,list) or not 1<=len(ids)<=10000 or any(not isinstance(x,str) or not re.fullmatch('[a-fA-F0-9]{40}',x) for x in ids):raise Problem('invalid Defender machine grants')

def parameters(cfg,payload):
    p=payload['parameters']
    if set(p)!={'action','machine_id'} or p['action'] not in ('isolate','unisolate'):raise Problem('Defender requires action isolate/unisolate and machine_id')
    if p['machine_id'] not in cfg['assets'].get(payload['tenant'],[]):raise Problem('machine is not granted to tenant',403)
    return p

class HTTP:
    def request(self,cfg,method,path,body=None):
        from .soar import Permanent
        token=Path(cfg['token_file']).read_text().strip()
        if not token or len(token)>8192 or '\n' in token or '\r' in token:raise Permanent('invalid credential')
        req=Request(cfg['url']+path,method=method,data=None if body is None else canonical(body).encode(),headers={'Authorization':'Bearer '+token,'Content-Type':'application/json'})
        with build_opener(ProxyHandler({}),NoRedirect()).open(req,timeout=15) as response:
            raw=response.read(65537)
            if len(raw)>65536:raise ValueError('vendor response too large')
            return response.status,strict_json(raw)

class Router:
    def __init__(self,enterprise,http=None):self.e=enterprise;self.http=http or HTTP()
    def send(self,cfg,key,payload):
        if cfg.get('kind')!='defender':
            from .soar import Webhook
            return Webhook().send(cfg,key,payload)
        return self.defender(cfg,key,payload)
    def save(self,key,tenant,state,operation,receipt):
        e=self.e
        with e.tx() as c:
            e.sql(c,"UPDATE nova_vendor_operations SET state=?,operation_id=?,receipt=? WHERE job_id=? AND state NOT IN ('completed','failed')",(state,operation,canonical(receipt),key))
            e.audit(c,tenant,'worker','vendor.'+state,{'id':key,'operation_id':operation})
    def defender(self,cfg,key,payload):
        from .soar import Permanent
        p=parameters(cfg,payload);e=self.e
        digest=hashlib.sha256(canonical([cfg,payload]).encode()).hexdigest()
        with e.tx() as c:
            inserted=e.sql(c,"INSERT INTO nova_vendor_operations(job_id,tenant,digest,state,receipt) VALUES(?,?,?,'submitting','{}') ON CONFLICT(job_id) DO NOTHING RETURNING job_id",(key,payload['tenant'],digest)).fetchone()
            r=dict(e.sql(c,'SELECT * FROM nova_vendor_operations WHERE job_id=?',(key,)).fetchone())
            if inserted:e.audit(c,payload['tenant'],'worker','vendor.intent',{'id':key,'machine_id':p['machine_id'],'action':p['action']})
        if r['digest']!=digest:raise Permanent('vendor intent mismatch')
        if r['state']=='completed':return True
        if r['state']=='failed':raise Permanent('vendor action failed')
        if not inserted and r['state'] in ('submitting','uncertain'):
            # The process may have died after the provider accepted the POST.
            raise Uncertain('submission outcome unknown; inspect provider before a new request')
        operation=r['operation_id']
        try:
            if inserted:
                body={'Comment':'Nova job '+key}
                if p['action']=='isolate':body['IsolationType']='Full'
                status,result=self.http.request(cfg,'POST','/api/machines/'+p['machine_id']+'/'+p['action'],body)
                if status!=201:raise ValueError('unexpected submission status')
            else:
                status,result=self.http.request(cfg,'GET','/api/machineactions/'+operation)
                if status!=200:raise ValueError('unexpected polling status')
            if not isinstance(result,dict) or not isinstance(result.get('id'),str) or not re.fullmatch('[a-fA-F0-9-]{36}',result['id']):raise ValueError('invalid operation identity')
            if operation and operation!=result['id']:raise ValueError('operation changed')
            if result.get('machineId')!=p['machine_id'] or result.get('type')!=('Isolate' if p['action']=='isolate' else 'Unisolate'):raise ValueError('action identity mismatch')
            operation=result['id'];status=result.get('status')
            if status not in ('Pending','InProgress','Succeeded','Failed','TimeOut','Cancelled'):raise ValueError('unknown provider state')
        except Exception:
            if inserted:
                self.save(key,payload['tenant'],'uncertain',None,{'reason':'submission unconfirmed'})
                raise Uncertain('submission outcome unknown') from None
            raise Pending('poll unconfirmed') from None
        state='completed' if status=='Succeeded' else 'pending' if status in ('Pending','InProgress') else 'failed'
        self.save(key,payload['tenant'],state,operation,{'id':operation,'machineId':p['machine_id'],'type':result['type'],'status':status})
        if state=='pending':raise Pending('vendor operation pending')
        if state=='failed':raise Permanent('vendor action failed')
        return True
