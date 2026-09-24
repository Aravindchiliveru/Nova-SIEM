"""Transactional internal response workflows and linked audit history.
No network containment or arbitrary script execution is implemented here.
"""
import hashlib
import json
import time
import uuid
from contextlib import contextmanager
from .core import Problem,canonical,identifier

SCHEMA='''
CREATE TABLE IF NOT EXISTS nova_audit_chain (
 tenant TEXT NOT NULL,seq BIGINT NOT NULL,audit_id BIGINT NOT NULL,
 payload TEXT NOT NULL,previous TEXT NOT NULL,digest TEXT NOT NULL,
 PRIMARY KEY(tenant,seq),UNIQUE(tenant,audit_id));
CREATE TABLE IF NOT EXISTS nova_workflows (
 id TEXT PRIMARY KEY,tenant TEXT NOT NULL,request_key TEXT NOT NULL,
 request_digest TEXT NOT NULL,requester TEXT NOT NULL,approver TEXT,
 alert_id TEXT NOT NULL,definition TEXT NOT NULL,state TEXT NOT NULL,
 step INTEGER NOT NULL DEFAULT 0,revision INTEGER NOT NULL DEFAULT 0,
 attempts INTEGER NOT NULL DEFAULT 0,next_try DOUBLE PRECISION NOT NULL DEFAULT 0,
 result TEXT NOT NULL,last_error TEXT,created DOUBLE PRECISION NOT NULL,
 UNIQUE(tenant,request_key));
CREATE INDEX IF NOT EXISTS nova_workflows_queue ON nova_workflows(state,next_try,created);
CREATE INDEX IF NOT EXISTS nova_workflows_tenant ON nova_workflows(tenant,created);
'''
SCHEMA+='\nCREATE TABLE IF NOT EXISTS nova_rule_settings (\n tenant TEXT NOT NULL,rule_id TEXT NOT NULL,revision TEXT NOT NULL,enabled INTEGER NOT NULL,\n PRIMARY KEY(tenant,rule_id));\n'
PLAYBOOK={'id':'triage-auth.v1','title':'Create and annotate an investigation',
          'steps':[{'action':'case.create'},{'action':'case.status','status':'investigating'},
                   {'action':'case.note','note':'Approved triage workflow completed. Review source evidence before any containment.'}]}

def execute(c,sql,args=(),postgres=False):return c.execute(sql.replace('?', '%s') if postgres else sql,args)

def append_audit(c,tenant,audit_id,actor,action,detail,created,postgres=False):
    if postgres:execute(c,'SELECT pg_advisory_xact_lock(hashtextextended(?,4))',(tenant,),True)
    row=execute(c,'SELECT seq,digest FROM nova_audit_chain WHERE tenant=? ORDER BY seq DESC LIMIT 1',(tenant,),postgres).fetchone()
    seq=row['seq']+1 if row else 1;previous=row['digest'] if row else '0'*64
    payload=canonical(dict(tenant=tenant,audit_id=audit_id,actor=actor,action=action,detail=detail,created=created))
    digest=hashlib.sha256(canonical([tenant,seq,previous,payload]).encode()).hexdigest()
    execute(c,'INSERT INTO nova_audit_chain VALUES(?,?,?,?,?,?)',(tenant,seq,audit_id,payload,previous,digest),postgres)

def verify_audit(c,tenant,postgres=False,anchor=None,max_records=10000):
    if anchor is not None:
        if not isinstance(anchor,dict) or not {'tenant','count','root'}<=set(anchor) or type(anchor['count']) is not int or anchor['count']<0 or not isinstance(anchor['root'],str) or len(anchor['root'])!=64:raise Problem('invalid audit checkpoint')
    previous='0'*64;seq=0;anchor_ok=anchor is None
    table='nova_audit' if postgres else 'audit'
    rows=execute(c,'SELECT * FROM nova_audit_chain WHERE tenant=? ORDER BY seq',(tenant,),postgres)
    for r in rows:
        seq+=1
        if seq>max_records:raise Problem('online audit verification budget exceeded; use the offline checkpoint tool',429)
        digest=hashlib.sha256(canonical([tenant,seq,previous,r['payload']]).encode()).hexdigest()
        if r['seq']!=seq or r['previous']!=previous or r['digest']!=digest:raise Problem('audit chain integrity failed',409)
        p=json.loads(r['payload'])
        original=execute(c,'SELECT * FROM '+table+' WHERE tenant=? AND id=?',(tenant,r['audit_id']),postgres).fetchone()
        if not original:raise Problem('audited record is missing',409)
        expected=dict(tenant=tenant,audit_id=original['id'],actor=original['actor'],action=original['action'],detail=json.loads(original['detail']),created=original['created'])
        if canonical(expected)!=r['payload']:raise Problem('audit record differs from linked history',409)
        previous=digest
        if anchor and seq==anchor.get('count'):anchor_ok=anchor.get('tenant')==tenant and anchor.get('root')==digest
    if anchor and anchor.get('count')==0:anchor_ok=anchor.get('tenant')==tenant and anchor.get('root')=='0'*64
    if not anchor_ok:raise Problem('external audit checkpoint does not match',409)
    total=execute(c,'SELECT COUNT(*) AS n FROM '+table+' WHERE tenant=?',(tenant,),postgres).fetchone()['n']
    return dict(tenant=tenant,count=seq,root=previous,unlinked_records=total-seq,integrity='verified',external_anchor_checked=anchor is not None)

class Enterprise:
    def __init__(self,engine):
        self.engine=engine;self.pg=hasattr(engine,'meta');self.owner=engine.meta if self.pg else engine
        self.prefix='nova_' if self.pg else ''
    @contextmanager
    def tx(self):
        with (self.owner.connect() if self.pg else self.owner.tx()) as c:yield c
    @contextmanager
    def read(self):
        with self.owner.connect() as c:
            c.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY' if self.pg else 'BEGIN')
            yield c
    def sql(self,c,sql,args=()):return execute(c,sql,args,self.pg)
    def audit(self,c,tenant,actor,action,detail):self.owner.audit(c,tenant,actor,action,detail)
    def catalog(self):return [PLAYBOOK]
    def listing(self,tenant):
        with self.read() as c:return [dict(r) for r in self.sql(c,'SELECT * FROM nova_workflows WHERE tenant=? ORDER BY created DESC LIMIT 200',(tenant,))]
    def integrity(self,tenant,anchor=None):
        with self.read() as c:return verify_audit(c,tenant,self.pg,anchor)
    def create(self,tenant,actor,body):
        if not isinstance(body,dict) or set(body)!={'request_key','playbook','alert_id'}:raise Problem('request_key, playbook and alert_id required')
        key=identifier(body['request_key'],'request key');aid=identifier(body['alert_id'],'alert id')
        if body['playbook']!=PLAYBOOK['id']:raise Problem('unknown playbook')
        digest=hashlib.sha256(canonical(body).encode()).hexdigest()
        with self.tx() as c:
            if self.pg:self.sql(c,'SELECT pg_advisory_xact_lock(hashtextextended(?,5))',(tenant,))
            old=self.sql(c,'SELECT * FROM nova_workflows WHERE tenant=? AND request_key=?',(tenant,key)).fetchone()
            if old:
                if old['request_digest']!=digest:raise Problem('request key reused with different input',409)
                return dict(old)
            alert=self.sql(c,'SELECT * FROM '+self.prefix+'alerts WHERE tenant=? AND id=?',(tenant,aid)).fetchone()
            if not alert:raise Problem('alert not found',404)
            wid=uuid.uuid4().hex
            self.sql(c,'INSERT INTO nova_workflows(id,tenant,request_key,request_digest,requester,alert_id,definition,state,result,created) VALUES(?,?,?,?,?,?,?,?,?,?)',(wid,tenant,key,digest,actor,aid,canonical(PLAYBOOK),'pending_approval','{}',time.time()))
            self.audit(c,tenant,actor,'workflow.request',{'id':wid,'playbook':PLAYBOOK['id'],'alert_id':aid})
            return dict(self.sql(c,'SELECT * FROM nova_workflows WHERE id=?',(wid,)).fetchone())
    def transition(self,tenant,actor,body):
        if not isinstance(body,dict) or set(body)!={'id','revision','action'}:raise Problem('id, revision and action required')
        wid=identifier(body['id'],'workflow id');revision=body['revision'];action=body['action']
        if type(revision) is not int or action not in ('approve','cancel','retry'):raise Problem('invalid workflow transition')
        with self.tx() as c:
            job=self.sql(c,'SELECT * FROM nova_workflows WHERE tenant=? AND id=?'+(' FOR UPDATE' if self.pg else ''),(tenant,wid)).fetchone()
            if not job:raise Problem('workflow not found',404)
            if job['revision']!=revision:raise Problem('workflow changed; refresh before applying action',409)
            if action=='approve':
                if job['state']!='pending_approval':raise Problem('workflow is not awaiting approval',409)
                if actor==job['requester']:raise Problem('a different named operator must approve',403)
                state='queued'
            elif action=='cancel':
                if job['state'] not in ('pending_approval','queued','failed'):raise Problem('workflow cannot be cancelled',409)
                state='cancelled'
            else:
                if job['state']!='failed' or not job['approver']:raise Problem('only failed approved workflows can be retried',409)
                state='queued'
            self.sql(c,'UPDATE nova_workflows SET state=?,revision=revision+1,approver=?,attempts=0,next_try=0,last_error=NULL WHERE tenant=? AND id=?',(state,actor if action=='approve' else job['approver'],tenant,wid))
            self.audit(c,tenant,actor,'workflow.'+action,{'id':wid,'revision':revision+1})
            return dict(self.sql(c,'SELECT * FROM nova_workflows WHERE tenant=? AND id=?',(tenant,wid)).fetchone())
    def action(self,c,job,step,result):
        tenant=job['tenant'];kind=step['action']
        if kind=='case.create':
            alert=self.sql(c,'SELECT * FROM '+self.prefix+'alerts WHERE tenant=? AND id=?',(tenant,job['alert_id'])).fetchone()
            if not alert:raise Problem('workflow alert no longer exists')
            self.sql(c,'INSERT INTO '+self.prefix+'cases(tenant,alert_id,title,created) VALUES(?,?,?,?) ON CONFLICT(tenant,alert_id) DO NOTHING',(tenant,job['alert_id'],alert['title'],time.time()))
            result['case_id']=self.sql(c,'SELECT id FROM '+self.prefix+'cases WHERE tenant=? AND alert_id=?',(tenant,job['alert_id'])).fetchone()['id']
        elif kind in ('case.status','case.note'):
            row=self.sql(c,'SELECT * FROM '+self.prefix+'cases WHERE tenant=? AND id=?',(tenant,result.get('case_id'))).fetchone()
            if not row or row['alert_id']!=job['alert_id']:raise Problem('workflow case binding is invalid')
            if kind=='case.status':
                if step['status']!='investigating':raise Problem('unsupported workflow status')
                self.sql(c,'UPDATE '+self.prefix+'cases SET status=? WHERE tenant=? AND id=?',(step['status'],tenant,row['id']))
            else:
                note=step['note']
                if not isinstance(note,str) or not 1<=len(note)<=8192:raise Problem('invalid workflow note')
                self.sql(c,'INSERT INTO '+self.prefix+'case_notes(tenant,case_id,actor,note,created) VALUES(?,?,?,?,?)',(tenant,row['id'],'workflow:'+job['id'],note,time.time()))
        else:raise Problem('unsupported workflow action')
        return result
    def tick(self,now=None):
        now=time.time() if now is None else now
        with self.tx() as c:
            job=self.sql(c,"SELECT * FROM nova_workflows WHERE state='queued' AND next_try<=? ORDER BY created LIMIT 1"+(' FOR UPDATE SKIP LOCKED' if self.pg else ''),(now,)).fetchone()
            if not job:return 0
            definition=json.loads(job['definition']);result=json.loads(job['result'])
            # Internal actions and cursor advancement share one transaction. Savepoint
            # rollback prevents partial effects; a process crash releases the DB lock.
            self.sql(c,'SAVEPOINT workflow_step')
            try:
                result=self.action(c,job,definition['steps'][job['step']],result)
                step=job['step']+1;state='completed' if step==len(definition['steps']) else 'queued'
                self.sql(c,'UPDATE nova_workflows SET result=?,step=?,state=?,revision=revision+1,attempts=0,last_error=NULL WHERE id=?',(canonical(result),step,state,job['id']))
                self.audit(c,job['tenant'],'workflow:'+job['id'],'workflow.step',{'id':job['id'],'step':step,'state':state})
                self.sql(c,'RELEASE SAVEPOINT workflow_step')
            except Exception:
                self.sql(c,'ROLLBACK TO SAVEPOINT workflow_step');self.sql(c,'RELEASE SAVEPOINT workflow_step')
                attempts=job['attempts']+1
                self.sql(c,'UPDATE nova_workflows SET attempts=?,next_try=?,state=?,last_error=?,revision=revision+1 WHERE id=?',(attempts,now+min(300,2**attempts),'failed' if attempts>=3 else 'queued','Internal action failed; inspect dependencies before retry',job['id']))
                self.audit(c,job['tenant'],'workflow:'+job['id'],'workflow.step_failed',{'id':job['id'],'attempt':attempts})
            return 1

    def rule_catalog(self,tenant):
        rules=self.owner.rules
        with self.read() as c:return rules.effective(c,tenant,self.pg)
    def set_rule(self,tenant,actor,body):
        if not isinstance(body,dict) or set(body)!={'id','enabled','revision'} or type(body['enabled']) is not bool:raise Problem('id, enabled and installed revision required')
        identifier(body['id'],'rule id')
        rule=next((r for r in self.owner.rules.rules if r['id']==body['id']),None)
        if not rule:raise Problem('rule not found',404)
        if body['revision']!=rule['revision']:raise Problem('installed rule revision changed; review before activation',409)
        with self.tx() as c:
            if self.pg:self.sql(c,'SELECT pg_advisory_xact_lock(hashtextextended(?,3))',(tenant,))
            self.sql(c,'INSERT INTO nova_rule_settings VALUES(?,?,?,?) ON CONFLICT(tenant,rule_id) DO UPDATE SET revision=excluded.revision,enabled=excluded.enabled',(tenant,rule['id'],rule['revision'],int(body['enabled'])))
            self.audit(c,tenant,actor,'rule.configure',body)
        return dict(id=rule['id'],enabled=body['enabled'],revision=rule['revision'])
    def test_integration(self,body):
        if not isinstance(body,dict) or set(body)!={'package','events'} or not isinstance(body['events'],list) or len(body['events'])>100:raise Problem('package and up to 100 sample event objects required')
        identifier(body['package'],'package id');package=self.engine.packages.get(body['package'])
        if not package:raise Problem('package not found',404)
        from .core import Engine
        result=[]
        for i,data in enumerate(body['events']):
            try:result.append({'index':i,'normalized':Engine.normalize(package,data),'error':None})
            except Problem as error:result.append({'index':i,'normalized':None,'error':str(error)})
        return {'results':result,'persisted':False,'package_revision':package['sha256']}
    def deactivate_integration(self,tenant,actor,body):
        if not isinstance(body,dict) or set(body)!={'package'}:raise Problem('package required')
        package=identifier(body['package'],'package')
        with self.tx() as c:
            self.sql(c,'DELETE FROM '+self.prefix+'activations WHERE tenant=? AND package=?',(tenant,package))
            self.audit(c,tenant,actor,'integration.deactivate',{'package':package})
        return {'package':package,'state':'inactive'}

    def health(self,tenant):
        with self.read() as c:
            rows=self.sql(c,'SELECT state,COUNT(*) AS n FROM nova_workflows WHERE tenant=? GROUP BY state',(tenant,))
            counts={r['state']:r['n'] for r in rows}
        return {'workflow_awaiting_approval':counts.get('pending_approval',0),'workflow_pending':counts.get('queued',0),'workflow_failed':counts.get('failed',0),'workflow_completed':counts.get('completed',0)}
    def export_case(self,tenant,actor,body):
        if not isinstance(body,dict) or set(body)!={'case_id'}:raise Problem('case_id required')
        case=self.engine.case_detail(tenant,body['case_id'])
        with self.read() as c:
            alert=self.sql(c,'SELECT * FROM '+self.prefix+'alerts WHERE tenant=? AND id=?',(tenant,case['case']['alert_id'])).fetchone()
            if not alert:raise Problem('case alert no longer exists',409)
            alert=dict(alert)
        evidence=json.loads(alert['evidence']);events=[]
        for eid in evidence[:100]:events.append(self.engine.event(tenant,eid))
        payload={'tenant':tenant,'exported_by':actor,'exported_at':time.time(),'case':case,'alert':alert,'events':events,'scope':'Stored alert evidence references, at most 100 events; not a full incident search or original-wire archive','may_be_truncated':len(evidence)>=100,'point_in_time_snapshot':False}
        from .evidence import seal
        bundle=seal(payload)
        with self.tx() as c:self.audit(c,tenant,actor,'evidence.export',{'case_id':case['case']['id'],'events':len(events),'sha256':bundle['sha256']})
        return bundle
