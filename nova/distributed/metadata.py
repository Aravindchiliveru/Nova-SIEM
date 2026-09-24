"""PostgreSQL staging/control metadata. Bounded development profile, not a scale claim."""
import hashlib
import os
import time
from ..core import Problem,canonical,identifier
from .contracts import RAW_TOPIC,prepare,strict_json,validate_normal,validate_raw

class Metadata:
    def __init__(self,dsn):
        self.dsn=dsn
        from ..rules import Rules
        self.rules=Rules()
    def connect(self):
        import psycopg
        from psycopg.rows import dict_row
        return psycopg.connect(self.dsn,connect_timeout=5,row_factory=dict_row,
                              options='-c statement_timeout=30000 -c lock_timeout=5000')
    def audit(self,c,tenant,actor,action,detail):
        from ..enterprise import append_audit
        created=time.time()
        row=c.execute('INSERT INTO nova_audit(tenant,actor,action,detail,created) VALUES(%s,%s,%s,%s,%s) RETURNING id',(tenant,actor,action,canonical(detail),created)).fetchone()
        append_audit(c,tenant,row['id'],actor,action,detail,created,postgres=True)
    def heartbeat(self,worker_id,role,processed,failed=False):
        with self.connect() as c:
            c.execute('INSERT INTO nova_workers VALUES(%s,%s,%s,%s,%s) ON CONFLICT(worker_id) DO UPDATE SET updated=excluded.updated,failed=excluded.failed,processed=excluded.processed',(worker_id,role,time.time(),failed,processed))
    def relay(self,publisher):
        with self.connect() as c:
            rows=c.execute('SELECT * FROM nova_outbox ORDER BY id LIMIT 200 FOR UPDATE SKIP LOCKED').fetchall()
            if not rows:return 0
            publisher.publish([(r['topic'],strict_json(r['payload'])) for r in rows])
            # A crash between broker acceptance and commit can republish, never skip.
            c.execute('DELETE FROM nova_outbox WHERE id=ANY(%s)',([r['id'] for r in rows],))
        return len(rows)
    def mark(self,rows,field):
        if field not in ('normalized_at','indexed_at','archived_at'):raise ValueError('unknown stage')
        with self.connect() as c:
            for n in rows:
                r=n.get('raw',n)
                c.execute('UPDATE nova_receipts SET '+field+'=COALESCE('+field+',%s) WHERE tenant=%s AND event_id=%s',(time.time(),r['tenant'],r['event_id']))
                if field=='normalized_at':
                    c.execute('UPDATE nova_quarantine SET resolved=TRUE WHERE tenant=%s AND event_id=%s',(r['tenant'],r['event_id']))
    def locked(self,rows,receipts):
        if len(rows)!=len(receipts):raise ValueError('archive receipt count mismatch')
        with self.connect() as c:
            for raw,receipt in zip(rows,receipts):
                c.execute('INSERT INTO nova_archive_objects(tenant,event_id,object_key,version_id,receipt) VALUES(%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING',(raw['tenant'],raw['event_id'],receipt['key'],receipt['version_id'],canonical(receipt)))
                c.execute('UPDATE nova_receipts SET locked_at=COALESCE(locked_at,%s),archived_at=COALESCE(archived_at,%s) WHERE tenant=%s AND event_id=%s',(time.time(),time.time(),raw['tenant'],raw['event_id']))
    def quarantine(self,rows):
        with self.connect() as c:
            for q in rows:
                if q.get('contract')!='nova.quarantine.v1' or not isinstance(q.get('reason'),str):raise ValueError('invalid quarantine record')
                r=validate_raw(q.get('raw'))
                # Lock receipt against normalization marker to prevent late-error resurrection.
                receipt=c.execute('SELECT normalized_at FROM nova_receipts WHERE tenant=%s AND event_id=%s FOR UPDATE',(r['tenant'],r['event_id'])).fetchone()
                if not receipt:raise ValueError('quarantine event has no accepted receipt')
                if receipt['normalized_at'] is not None:continue
                c.execute('INSERT INTO nova_quarantine(tenant,event_id,reason,raw) VALUES(%s,%s,%s,%s) ON CONFLICT(tenant,event_id) DO UPDATE SET reason=excluded.reason',
                          (r['tenant'],r['event_id'],q['reason'],canonical(r)))
    def detect(self,rows):
        rows=[validate_normal(n) for n in rows]
        with self.connect() as c:
            # Lock once per batch in a stable order before checking the replay ledger.
            for tenant in sorted({n['tenant'] for n in rows}):
                c.execute('SELECT pg_advisory_xact_lock(hashtextextended(%s,3))',(tenant,))
            fresh=[]
            for n in rows:
                new=c.execute('INSERT INTO nova_detection_seen VALUES(%s,%s) ON CONFLICT DO NOTHING RETURNING event_id',(n['tenant'],n['event_id'])).fetchone()
                if new:fresh.append(n)
            self.rules.evaluate(c,fresh,postgres=True)
            for n in fresh:c.execute('UPDATE nova_receipts SET detected_at=%s WHERE tenant=%s AND event_id=%s',(time.time(),n['tenant'],n['event_id']))

class Gateway:
    mode='distributed-lab'
    def __init__(self,metadata,analytics,packages,max_events=100000):
        self.meta,self.analytics,self.packages=metadata,analytics,packages
        self.max_events=max_events
    def activate(self,tenant,actor,package):
        identifier(package,'package')
        p=self.packages.get(package)
        if not p:raise Problem('unknown integration',404)
        with self.meta.connect() as c:
            c.execute('INSERT INTO nova_activations VALUES(%s,%s,%s,%s) ON CONFLICT(tenant,package) DO UPDATE SET version=excluded.version,digest=excluded.digest',(tenant,package,p['version'],p['sha256']))
            self.meta.audit(c,tenant,actor,'integration.activate',{'package':package,'version':p['version'],'digest':p['sha256']})
        return dict(package=package,version=p['version'],state='active')
    def ingest(self,tenant,actor,body):
        rows=prepare(tenant,body)
        accepted=duplicates=0
        with self.meta.connect() as c:
            # Serialize same-tenant capacity/identity checks; cross-tenant writers proceed independently.
            c.execute('SELECT pg_advisory_xact_lock(hashtextextended(%s,0))',(tenant,))
            count=c.execute('SELECT count(*) AS n FROM nova_receipts WHERE tenant=%s',(tenant,)).fetchone()['n']
            activation=c.execute('SELECT digest FROM nova_activations WHERE tenant=%s AND package=%s',(tenant,body['integration'])).fetchone()
            for r in rows:
                old=c.execute('SELECT digest FROM nova_receipts WHERE tenant=%s AND event_id=%s',(tenant,r['event_id'])).fetchone()
                if old:
                    if old['digest']!=r['digest']:raise Problem('event identity reused with a different payload or integration',409)
                    duplicates+=1;continue
                if count+accepted>=self.max_events:raise Problem('development tenant event capacity reached; batch rejected',429)
                r['package_digest']=activation['digest'] if activation else ''
                c.execute('INSERT INTO nova_receipts(tenant,event_id,digest,source,integration,received) VALUES(%s,%s,%s,%s,%s,%s)',(tenant,r['event_id'],r['digest'],r['source'],r['integration'],r['received']))
                c.execute('INSERT INTO nova_outbox(tenant,event_id,topic,payload,created) VALUES(%s,%s,%s,%s,%s)',(tenant,r['event_id'],RAW_TOPIC,canonical(r),time.time()))
                accepted+=1
            self.meta.audit(c,tenant,actor,'events.accept',{'accepted':accepted,'duplicates':duplicates,'source':body['source']})
        return dict(accepted=accepted,duplicates=duplicates,event_ids=[r['event_id'] for r in rows],durability='postgres-staging',mode=self.mode)
    def search(self,tenant,params):return self.analytics.search(tenant,params)
    def integrations(self,tenant):
        with self.meta.connect() as c:active={r['package']:r['digest'] for r in c.execute('SELECT * FROM nova_activations WHERE tenant=%s',(tenant,))}
        return [dict(id=p['id'],name=p['name'],description=p['description'],version=p['version'],sha256=p['sha256'],signature_status=p.get('signature_status','unsigned-development'),fixture_count=len(p['fixtures']),active=active.get(p['id'])==p['sha256']) for p in self.packages.values()]
    def listing(self,tenant,table):
        if table not in ('alerts','cases','audit','quarantine'):raise Problem('unknown collection',404)
        suffix=' AND resolved=FALSE' if table=='quarantine' else ''
        order='event_id' if table=='quarantine' else 'created DESC'
        fields='tenant,event_id,reason,attempts' if table=='quarantine' else '*'
        with self.meta.connect() as c:return list(c.execute('SELECT '+fields+' FROM nova_'+table+' WHERE tenant=%s'+suffix+' ORDER BY '+order+' LIMIT 200',(tenant,)))
    def create_case(self,tenant,actor,alert_id):
        identifier(alert_id,'alert id')
        with self.meta.connect() as c:
            a=c.execute('SELECT * FROM nova_alerts WHERE tenant=%s AND id=%s',(tenant,alert_id)).fetchone()
            if not a:raise Problem('alert not found',404)
            c.execute('INSERT INTO nova_cases(tenant,alert_id,title,created) VALUES(%s,%s,%s,%s) ON CONFLICT(tenant,alert_id) DO NOTHING',(tenant,alert_id,a['title'],time.time()))
            row=c.execute('SELECT * FROM nova_cases WHERE tenant=%s AND alert_id=%s',(tenant,alert_id)).fetchone()
            self.meta.audit(c,tenant,actor,'case.create',{'id':row['id']})
        return row
    def replay(self,tenant,actor,event_id):
        identifier(event_id,'event id')
        with self.meta.connect() as c:
            q=c.execute('SELECT * FROM nova_quarantine WHERE tenant=%s AND event_id=%s AND resolved=FALSE FOR UPDATE',(tenant,event_id)).fetchone()
            if not q:raise Problem('quarantined event not found',404)
            if q['attempts']>=3:raise Problem('replay attempt limit reached',409)
            raw=strict_json(q['raw'])
            activation=c.execute('SELECT digest FROM nova_activations WHERE tenant=%s AND package=%s',(tenant,raw['integration'])).fetchone()
            if not activation:raise Problem('activate the matching integration before replay',409)
            raw['package_digest']=activation['digest'];raw['replay_generation']=q['attempts']+1
            c.execute('UPDATE nova_quarantine SET attempts=attempts+1 WHERE tenant=%s AND event_id=%s',(tenant,event_id))
            c.execute('INSERT INTO nova_outbox(tenant,event_id,topic,payload,created) VALUES(%s,%s,%s,%s,%s)',(tenant,event_id,RAW_TOPIC,canonical(raw),time.time()))
            self.meta.audit(c,tenant,actor,'quarantine.replay',{'event_id':event_id,'attempt':raw['replay_generation']})
        return {'state':'queued'}
    def event(self,tenant,event_id):
        identifier(event_id,'event id')
        with self.meta.connect() as c:
            receipt=c.execute('SELECT * FROM nova_receipts WHERE tenant=%s AND event_id=%s',(tenant,event_id)).fetchone()
            q=c.execute('SELECT * FROM nova_quarantine WHERE tenant=%s AND event_id=%s AND resolved=FALSE',(tenant,event_id)).fetchone()
        if not receipt:raise Problem('event not found',404)
        n=self.analytics.event(tenant,event_id)
        return {'receipt':receipt,'raw':strict_json(n['raw']) if n else (strict_json(q['raw']) if q else None),'normalized':n,'quarantine':q}
    def health(self,tenant):
        with self.meta.connect() as c:
            h={'raw_events':c.execute('SELECT count(*) AS n FROM nova_receipts WHERE tenant=%s',(tenant,)).fetchone()['n']}
            for table in ('alerts','cases','quarantine'):
                suffix=' AND resolved=FALSE' if table=='quarantine' else ''
                h[table]=c.execute('SELECT count(*) AS n FROM nova_'+table+' WHERE tenant=%s'+suffix,(tenant,)).fetchone()['n']
            h['outbox_pending']=c.execute('SELECT count(*) AS n FROM nova_outbox WHERE tenant=%s',(tenant,)).fetchone()['n']
            for stage,condition in [('normalizer','normalized_at IS NULL'),('detector','normalized_at IS NOT NULL AND detected_at IS NULL'),('archive','archived_at IS NULL'),('immutable_archive','locked_at IS NULL')]:
                row=c.execute('SELECT count(*) AS n,min(received) AS oldest FROM nova_receipts WHERE tenant=%s AND '+condition,(tenant,)).fetchone()
                h[stage+'_pending']=row['n'];h[stage+'_oldest_seconds']=max(0,time.time()-row['oldest']) if row['oldest'] else 0
            workers=list(c.execute('SELECT role,max(updated) AS last_update,bool_and(failed) AS failed FROM nova_workers WHERE updated>%s GROUP BY role', (time.time()-60,)))
        h['analytics_available']=True
        try:h['normalized']=int(self.analytics.count(tenant))
        except Exception:h['normalized']=None;h['analytics_available']=False
        h['local_capacity_events']=self.max_events;h['mode']=self.mode
        expected={'relay','normalizer','indexer','detector','quarantine','archive'}
        healthy={r['role'] for r in workers if time.time()-r['last_update']<60 and not r['failed']}
        h['worker_error']=healthy!=expected
        h['immutable_archive_required']=os.environ.get('NOVA_ARCHIVE_MODE')=='s3-object-lock'
        h['status']='attention' if h['worker_error'] or not h['analytics_available'] or h['quarantine'] or h['normalizer_pending'] or h['detector_pending'] or (h['immutable_archive_required'] and h['immutable_archive_pending']) else 'healthy'
        return h

    def rule_catalog(self,tenant):return self.meta.rules.rules
    def update_case(self,tenant,actor,body):
        from ..cases import validate_update
        case_id,status,note=validate_update(body)
        with self.meta.connect() as c:
            row=c.execute('SELECT * FROM nova_cases WHERE tenant=%s AND id=%s FOR UPDATE',(tenant,case_id)).fetchone()
            if not row:raise Problem('case not found',404)
            if status:c.execute('UPDATE nova_cases SET status=%s WHERE tenant=%s AND id=%s',(status,tenant,case_id))
            if note:c.execute('INSERT INTO nova_case_notes(tenant,case_id,actor,note,created) VALUES(%s,%s,%s,%s,%s)',(tenant,case_id,actor,note,time.time()))
            self.meta.audit(c,tenant,actor,'case.update',{'id':case_id,'status':status,'note_added':bool(note)})
            return c.execute('SELECT * FROM nova_cases WHERE tenant=%s AND id=%s',(tenant,case_id)).fetchone()
    def case_detail(self,tenant,case_id):
        from ..cases import valid_id
        case_id=valid_id(case_id)
        with self.meta.connect() as c:
            row=c.execute('SELECT * FROM nova_cases WHERE tenant=%s AND id=%s',(tenant,case_id)).fetchone()
            if not row:raise Problem('case not found',404)
            notes=list(c.execute('SELECT * FROM nova_case_notes WHERE tenant=%s AND case_id=%s ORDER BY id DESC LIMIT 200',(tenant,case_id)))
        return {'case':row,'notes':notes}
