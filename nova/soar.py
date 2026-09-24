"""Approved external JSON webhook activities with durable leases and idempotency keys."""
import hashlib,json,time,uuid
from pathlib import Path
from urllib.request import Request,build_opener,ProxyHandler
from urllib.parse import urlsplit
from urllib.error import HTTPError
from .core import Problem,canonical,identifier
from .collector import NoRedirect
from .distributed.contracts import strict_json
from .vendors import SCHEMA as VENDOR_SCHEMA,Router,Pending,Uncertain,validate_config,parameters

SCHEMA='''
CREATE TABLE IF NOT EXISTS nova_external_jobs (
 id TEXT PRIMARY KEY,tenant TEXT NOT NULL,request_key TEXT NOT NULL,digest TEXT NOT NULL,
 requester TEXT NOT NULL,approver TEXT,connector TEXT NOT NULL,config_digest TEXT NOT NULL,
 payload TEXT NOT NULL,state TEXT NOT NULL,revision INTEGER NOT NULL DEFAULT 0,
 attempts INTEGER NOT NULL DEFAULT 0,lease TEXT,lease_until DOUBLE PRECISION NOT NULL DEFAULT 0,
 next_try DOUBLE PRECISION NOT NULL DEFAULT 0,last_error TEXT,created DOUBLE PRECISION NOT NULL,
 UNIQUE(tenant,request_key));
CREATE INDEX IF NOT EXISTS nova_external_ready ON nova_external_jobs(state,next_try,lease_until);
CREATE INDEX IF NOT EXISTS nova_external_tenant ON nova_external_jobs(tenant,created);
'''

SCHEMA+=VENDOR_SCHEMA

def configuration(items):
    if not isinstance(items,dict) or len(items)>100:raise Problem('connector configuration must be a bounded object')
    for name,cfg in items.items():
        identifier(name,'connector')
        if not isinstance(cfg,dict) or set(cfg) not in ({'url','token_file','tenants'},{'url','token_file','tenants','kind','assets'}):raise Problem('connector requires url, token_file, tenants')
        url=urlsplit(cfg['url'])
        if url.scheme!='https' or not url.hostname or url.username or url.password or url.fragment or url.query:raise Problem('connector URL must be a fixed HTTPS endpoint')
        if not isinstance(cfg['token_file'],str) or not Path(cfg['token_file']).is_absolute():raise Problem('connector requires absolute token_file')
        if not isinstance(cfg['tenants'],list) or not cfg['tenants']:raise Problem('connector requires explicit tenant grants')
        for tenant in cfg['tenants']:identifier(tenant,'tenant')
        if 'kind' in cfg:validate_config(cfg)
    return items

class Retryable(Exception):pass
class Permanent(Exception):pass

class Webhook:
    def send(self,cfg,key,payload):
        token=Path(cfg['token_file']).read_text().strip()
        if not token or len(token)>8192 or '\n' in token or '\r' in token:raise Permanent('invalid connector credential')
        req=Request(cfg['url'],data=canonical(payload).encode(),headers={'Authorization':'Bearer '+token,'Content-Type':'application/json','Idempotency-Key':key})
        try:
            with build_opener(ProxyHandler({}),NoRedirect()).open(req,timeout=15) as response:
                data=response.read(65537)
                if len(data)>65536:raise Permanent('response exceeds limit')
                body=strict_json(data)
                if response.status!=200 or not isinstance(body,dict) or body.get('idempotency_key')!=key or body.get('status')!='completed':raise Retryable('completion unconfirmed')
        except HTTPError as e:
            if e.code in (408,429) or e.code>=500:raise Retryable('provider temporarily unavailable') from None
            raise Permanent('provider rejected action') from None
        return True

class External:
    def __init__(self,enterprise,connectors=None,transport=None,clock=time.time):
        self.e=enterprise;self.connectors=configuration(connectors or {});self.transport=transport or Router(enterprise);self.clock=clock
    def catalog(self,tenant):return [{'id':k,'kind':v.get('kind','webhook'),'approval':'different operator required','actions':['isolate','unisolate'] if v.get('kind')=='defender' else [],'assets':v.get('assets',{}).get(tenant,[])} for k,v in self.connectors.items() if tenant in v['tenants']]
    def cfg(self,tenant,name):
        c=self.connectors.get(name)
        if c is None or tenant not in c['tenants']:raise Problem('connector not available to tenant',403)
        return c,hashlib.sha256(canonical(c).encode()).hexdigest()
    def listing(self,tenant):
        with self.e.read() as c:return [dict(r) for r in self.e.sql(c,'SELECT j.*,v.state AS vendor_state,v.operation_id,v.receipt AS vendor_receipt FROM nova_external_jobs j LEFT JOIN nova_vendor_operations v ON j.id=v.job_id AND j.tenant=v.tenant WHERE j.tenant=? ORDER BY j.created DESC LIMIT 200',(tenant,))]
    def health(self,tenant):
        with self.e.read() as c:
            counts={r['state']:r['n'] for r in self.e.sql(c,'SELECT state,COUNT(*) AS n FROM nova_external_jobs WHERE tenant=? GROUP BY state',(tenant,))}
        return {'external_'+state:counts.get(state,0) for state in ('awaiting_approval','ready','running','failed','completed','uncertain')}
    def create(self,tenant,actor,b):
        if not isinstance(b,dict) or set(b)!={'request_key','connector','alert_id','parameters'}:raise Problem('request_key, connector, alert_id, parameters required')
        key=identifier(b['request_key'],'request key');aid=identifier(b['alert_id'],'alert id');name=identifier(b['connector'],'connector')
        if not isinstance(b['parameters'],dict) or len(canonical(b['parameters']).encode())>8192:raise Problem('parameters exceed bound')
        cfg,cfg_digest=self.cfg(tenant,name)
        if cfg.get('kind'):parameters(cfg,{'tenant':tenant,'parameters':b['parameters']})
        digest=hashlib.sha256(canonical([b,cfg_digest]).encode()).hexdigest()
        e=self.e
        with e.tx() as c:
            if e.pg:e.sql(c,'SELECT pg_advisory_xact_lock(hashtextextended(?,7))',(tenant+':'+key,))
            previous=e.sql(c,'SELECT * FROM nova_external_jobs WHERE tenant=? AND request_key=?',(tenant,key)).fetchone()
            if previous:
                if previous['digest']!=digest:raise Problem('request key conflicts with original action',409)
                return dict(previous)
            alert=e.sql(c,'SELECT * FROM '+e.prefix+'alerts WHERE tenant=? AND id=?',(tenant,aid)).fetchone()
            if not alert:raise Problem('alert not found',404)
            jid=uuid.uuid4().hex
            payload=canonical(dict(tenant=tenant,alert=dict(alert),parameters=b['parameters']))
            e.sql(c,'INSERT INTO nova_external_jobs(id,tenant,request_key,digest,requester,connector,config_digest,payload,state,created) VALUES(?,?,?,?,?,?,?,?,?,?)',(jid,tenant,key,digest,actor,name,cfg_digest,payload,'awaiting_approval',self.clock()))
            e.audit(c,tenant,actor,'external.request',{'id':jid,'connector':name,'digest':digest})
            return dict(e.sql(c,'SELECT * FROM nova_external_jobs WHERE id=?',(jid,)).fetchone())
    def transition(self,tenant,actor,b):
        if isinstance(b,dict) and b.get('action')=='reconcile':return self.reconcile(tenant,actor,b)
        if not isinstance(b,dict) or set(b)!={'id','revision','action'} or type(b['revision']) is not int or b['action'] not in ('approve','cancel'):raise Problem('id, revision and approve/cancel required')
        e=self.e
        with e.tx() as c:
            r=e.sql(c,'SELECT * FROM nova_external_jobs WHERE tenant=? AND id=?'+(' FOR UPDATE' if e.pg else ''),(tenant,b['id'])).fetchone()
            if not r:raise Problem('external job not found',404)
            if r['revision']!=b['revision']:raise Problem('stale action revision',409)
            if r['state']!='awaiting_approval':raise Problem('only pending approval can transition',409)
            if b['action']=='approve':
                if actor==r['requester']:raise Problem('a different operator must approve',403)
                _,digest=self.cfg(tenant,r['connector'])
                if digest!=r['config_digest']:raise Problem('connector configuration changed; request anew',409)
            state='ready' if b['action']=='approve' else 'cancelled'
            e.sql(c,'UPDATE nova_external_jobs SET state=?,approver=?,revision=revision+1 WHERE id=?',(state,actor,r['id']))
            e.audit(c,tenant,actor,'external.'+b['action'],{'id':r['id']})
            return dict(e.sql(c,'SELECT * FROM nova_external_jobs WHERE id=?',(r['id'],)).fetchone())
    def reconcile(self,tenant,actor,b):
        if set(b)!={'id','revision','action','operation_id'} or type(b['revision']) is not int:raise Problem('reconciliation requires id, revision and operation_id')
        import re
        if not isinstance(b['operation_id'],str) or not re.fullmatch('[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}',b['operation_id']):raise Problem('invalid operation ID')
        e=self.e
        with e.read() as c:
            row=e.sql(c,'SELECT * FROM nova_external_jobs WHERE tenant=? AND id=?',(tenant,b['id'])).fetchone()
            if not row:raise Problem('external job not found',404)
            r=dict(row)
        if r['state']!='uncertain' or r['revision']!=b['revision']:raise Problem('uncertain job with current revision required',409)
        if actor==r['requester'] or not r['approver']:raise Problem('a different administrator must reconcile an approved request',403)
        cfg,digest=self.cfg(tenant,r['connector'])
        if cfg.get('kind')!='defender' or digest!=r['config_digest']:raise Problem('unchanged Defender configuration required',409)
        payload=json.loads(r['payload']);p=parameters(cfg,payload)
        # Read-only provider request outside the metadata transaction. Never POST.
        try:status,result=self.transport.http.request(cfg,'GET','/api/machineactions/'+b['operation_id'])
        except Exception:raise Problem('provider verification unavailable',502) from None
        if status!=200 or not isinstance(result,dict) or result.get('id')!=b['operation_id'] or result.get('machineId')!=p['machine_id'] or result.get('type')!=('Isolate' if p['action']=='isolate' else 'Unisolate') or result.get('requestorComment')!='Nova job '+r['id']:raise Problem('provider action does not match approved job',409)
        state=result.get('status')
        if state not in ('Pending','InProgress','Succeeded','Failed','TimeOut','Cancelled'):raise Problem('unknown provider state',502)
        vendor_state='completed' if state=='Succeeded' else 'pending' if state in ('Pending','InProgress') else 'failed'
        job_state='ready' if vendor_state=='pending' else vendor_state
        receipt={k:result[k] for k in ('id','machineId','type','status','requestorComment')}
        with e.tx() as c:
            # CAS makes stale or competing administrator results harmless.
            _,current=self.cfg(tenant,r['connector'])
            if current!=digest:raise Problem('configuration changed during verification',409)
            updated=e.sql(c,"UPDATE nova_external_jobs SET state=?,attempts=0,next_try=?,lease=NULL,lease_until=0,last_error=NULL,revision=revision+1 WHERE tenant=? AND id=? AND state='uncertain' AND revision=? RETURNING id",(job_state,self.clock()+30,tenant,r['id'],b['revision'])).fetchone()
            if not updated:raise Problem('job changed during verification',409)
            intent=e.sql(c,'SELECT digest FROM nova_vendor_operations WHERE tenant=? AND job_id=?',(tenant,r['id'])).fetchone()
            expected=hashlib.sha256(canonical([cfg,payload]).encode()).hexdigest()
            if not intent or intent['digest']!=expected:raise Problem('matching durable vendor intent required',409)
            e.sql(c,'UPDATE nova_vendor_operations SET state=?,operation_id=?,receipt=? WHERE tenant=? AND job_id=?',(vendor_state,b['operation_id'],canonical(receipt),tenant,r['id']))
            e.audit(c,tenant,actor,'external.reconciled',{'id':r['id'],'operation_id':b['operation_id'],'state':job_state})
            return dict(e.sql(c,'SELECT * FROM nova_external_jobs WHERE tenant=? AND id=?',(tenant,r['id'])).fetchone())

    def tick(self):
        e=self.e;now=self.clock()
        with e.tx() as c:
            r=e.sql(c,"SELECT * FROM nova_external_jobs WHERE (state='ready' AND next_try<=?) OR (state='running' AND lease_until<=?) ORDER BY created LIMIT 1"+(' FOR UPDATE SKIP LOCKED' if e.pg else ''),(now,now)).fetchone()
            if not r:return 0
            r=dict(r)
            budget=960 if self.connectors.get(r['connector'],{}).get('kind') else 5
            if r['attempts']>=budget:
                terminal='uncertain' if budget==960 else 'failed'
                e.sql(c,"UPDATE nova_external_jobs SET state=?,last_error='attempt budget exhausted; inspect provider status',revision=revision+1 WHERE id=?",(terminal,r['id']));e.audit(c,r['tenant'],'worker','external.'+terminal,{'id':r['id']});return 1
            lease=uuid.uuid4().hex
            e.sql(c,"UPDATE nova_external_jobs SET state='running',lease=?,lease_until=?,attempts=attempts+1,revision=revision+1 WHERE id=?",(lease,now+60,r['id']))
            e.audit(c,r['tenant'],'worker','external.attempt',{'id':r['id'],'attempt':r['attempts']+1})
        # No database transaction is held during network I/O.
        state='completed';error=None;cfg={}
        try:
            cfg,digest=self.cfg(r['tenant'],r['connector'])
            if digest!=r['config_digest']:raise Permanent('connector configuration changed')
            self.transport.send(cfg,r['id'],json.loads(r['payload']))
        except Uncertain:state='uncertain';error='submission outcome unknown; inspect provider before any new request'
        except Pending:state='ready';error='provider operation pending; polling only'
        except (Permanent,Problem):state='failed';error='connector rejected or configuration changed'
        except Exception:
            state='failed' if r['attempts']+1>=5 else 'ready';error='completion unconfirmed; same idempotency key retained'
        with e.tx() as c:
            updated=e.sql(c,'UPDATE nova_external_jobs SET state=?,last_error=?,next_try=?,lease=NULL,lease_until=0,revision=revision+1 WHERE id=? AND state=\'running\' AND lease=? RETURNING id',(state,error,self.clock()+(30 if cfg.get('kind') else min(300,2**min(9,r['attempts']+1))),r['id'],lease)).fetchone()
            if updated:e.audit(c,r['tenant'],'worker','external.'+state,{'id':r['id'],'attempt':r['attempts']+1})
        return 1
