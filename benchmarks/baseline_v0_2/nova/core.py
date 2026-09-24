"""Executable correctness reference. SQLite is a local journal, not the scale backend."""
from __future__ import annotations
import hashlib
import ipaddress
import json
import math
import re
import sqlite3
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
NAME = re.compile(r'^[a-zA-Z0-9][a-zA-Z0-9_.:@-]{0,127}$')

class Problem(Exception):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status

def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False)

def timestamp(value):
    if not isinstance(value, str) or len(value) > 64:
        raise Problem('timestamp must be an ISO 8601 string with a timezone')
    try:
        dt = datetime.fromisoformat(value.replace('Z', '+00:00'))
        if dt.tzinfo is None:
            raise ValueError()
        n = dt.timestamp()
        if not math.isfinite(n):
            raise ValueError()
        return n
    except (ValueError, OverflowError):
        raise Problem('timestamp must be an ISO 8601 string with a timezone')

def identifier(value, label):
    if not isinstance(value, str) or not NAME.fullmatch(value):
        raise Problem('invalid ' + label)
    return value

SCHEMA = '''
CREATE TABLE IF NOT EXISTS raw_events (
 seq INTEGER PRIMARY KEY AUTOINCREMENT, tenant TEXT NOT NULL, event_id TEXT NOT NULL,
 source TEXT NOT NULL, integration TEXT NOT NULL, payload TEXT NOT NULL,
 digest TEXT NOT NULL, received REAL NOT NULL, UNIQUE(tenant, event_id));
CREATE TABLE IF NOT EXISTS normalized (
 tenant TEXT NOT NULL, event_id TEXT NOT NULL, source TEXT NOT NULL,
 event_time REAL NOT NULL, received REAL NOT NULL, normalized_at REAL NOT NULL,
 actor TEXT NOT NULL, ip TEXT NOT NULL, outcome TEXT NOT NULL, message TEXT NOT NULL,
 parser TEXT NOT NULL, version TEXT NOT NULL, PRIMARY KEY(tenant,event_id));
CREATE INDEX IF NOT EXISTS normal_time ON normalized(tenant,event_time);
CREATE INDEX IF NOT EXISTS normal_detection ON normalized(tenant,source,actor,ip,outcome,event_time);
CREATE TABLE IF NOT EXISTS quarantine (
 tenant TEXT NOT NULL,event_id TEXT NOT NULL,reason TEXT NOT NULL,
 attempts INTEGER NOT NULL DEFAULT 0,PRIMARY KEY(tenant,event_id));
CREATE TABLE IF NOT EXISTS processed (
 consumer TEXT NOT NULL,tenant TEXT NOT NULL,event_id TEXT NOT NULL,
 PRIMARY KEY(consumer,tenant,event_id));
CREATE TABLE IF NOT EXISTS activations (
 tenant TEXT NOT NULL,package TEXT NOT NULL,version TEXT NOT NULL,
 PRIMARY KEY(tenant,package));
CREATE TABLE IF NOT EXISTS alerts (
 id TEXT PRIMARY KEY,tenant TEXT NOT NULL,rule TEXT NOT NULL,title TEXT NOT NULL,
 severity TEXT NOT NULL,created REAL NOT NULL,evidence TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS cases (
 id INTEGER PRIMARY KEY AUTOINCREMENT,tenant TEXT NOT NULL,alert_id TEXT NOT NULL,
 title TEXT NOT NULL,status TEXT NOT NULL DEFAULT 'open',created REAL NOT NULL,
 UNIQUE(tenant,alert_id));
CREATE TABLE IF NOT EXISTS audit (
 id INTEGER PRIMARY KEY AUTOINCREMENT,tenant TEXT NOT NULL,actor TEXT NOT NULL,
 action TEXT NOT NULL,detail TEXT NOT NULL,created REAL NOT NULL);
'''

class Connection(sqlite3.Connection):
    def __exit__(self, *args):
        try:
            return super().__exit__(*args)
        finally:
            self.close()

class Engine:
    def __init__(self, db, package_dir=None, max_events=100000):
        self.db = str(db)
        self.package_dir = Path(package_dir or ROOT / 'integrations')
        self.max_events = max_events
        self.packages = self._packages()
        with self.connect() as c:
            c.executescript(SCHEMA)

    def connect(self):
        c = sqlite3.connect(self.db, timeout=10, isolation_level=None, factory=Connection)
        c.row_factory = sqlite3.Row
        c.execute('PRAGMA journal_mode=WAL')
        c.execute('PRAGMA synchronous=FULL')
        c.execute('PRAGMA foreign_keys=ON')
        return c

    @contextmanager
    def tx(self):
        c = self.connect()
        try:
            c.execute('BEGIN IMMEDIATE')
            yield c
            c.commit()
        except Exception:
            c.rollback()
            raise
        finally:
            c.close()

    def _packages(self):
        result = {}
        for path in sorted(self.package_dir.glob('*.json')):
            p = json.loads(path.read_text())
            identifier(p['id'], 'package')
            if p['id'] in result or p['format'] != 'nova.mapping.v1':
                raise ValueError('duplicate or unsupported package')
            if set(p['mapping']) != {'time','actor','ip','outcome','message'}:
                raise ValueError('invalid mapping')
            if any(not isinstance(v,str) or len(v)>128 for v in p['mapping'].values()):
                raise ValueError('invalid mapped field')
            for fixture in p['fixtures']:
                got = self.normalize(p, fixture['input'])
                for key, val in fixture['expected'].items():
                    if got[key] != val:
                        raise ValueError('package fixture failed: ' + p['id'])
            p['sha256'] = hashlib.sha256(path.read_bytes()).hexdigest()
            result[p['id']] = p
        if not result:
            raise ValueError('no integration packages')
        return result

    @staticmethod
    def normalize(p, payload):
        if not isinstance(payload, dict):
            raise Problem('event payload must be an object')
        m = p['mapping']
        try:
            values = {k: payload[v] for k,v in m.items()}
        except KeyError as e:
            raise Problem('missing field: ' + str(e.args[0]))
        event_time = timestamp(values['time'])
        for k in ('actor','ip','outcome','message'):
            if not isinstance(values[k],str) or len(values[k])>8192:
                raise Problem('invalid field: ' + k)
        if not values['actor'] or len(values['actor'])>256:
            raise Problem('actor must contain 1 to 256 characters')
        try:
            ip = str(ipaddress.ip_address(values['ip']))
        except ValueError:
            raise Problem('invalid source IP')
        outcome = p['outcomes'].get(values['outcome'])
        if outcome not in ('success','failure'):
            raise Problem('unrecognized authentication outcome')
        return dict(event_time=event_time,actor=values['actor'],ip=ip,
                    outcome=outcome,message=values['message'])

    def audit(self,c,tenant,actor,action,detail):
        c.execute('INSERT INTO audit(tenant,actor,action,detail,created) VALUES(?,?,?,?,?)',
                  (tenant,actor,action,canonical(detail),time.time()))

    def activate(self,tenant,actor,package):
        identifier(package, 'package')
        p = self.packages.get(package)
        if not p:
            raise Problem('unknown integration',404)
        with self.tx() as c:
            c.execute('INSERT INTO activations VALUES(?,?,?) ON CONFLICT(tenant,package) DO UPDATE SET version=excluded.version',
                      (tenant,package,p['version']))
            self.audit(c,tenant,actor,'integration.activate',{'package':package,'version':p['version'],'sha256':p['sha256']})
        return {'package':package,'version':p['version'],'state':'active'}

    def ingest(self,tenant,actor,body):
        if not isinstance(body,dict) or set(body)-{'source','integration','events'}:
            raise Problem('allowed request fields: source, integration, events')
        source = identifier(body.get('source'),'source')
        package = identifier(body.get('integration'),'integration')
        events = body.get('events')
        if not isinstance(events,list) or not 1<=len(events)<=500:
            raise Problem('batch requires 1 to 500 events')
        prepared = []
        for event in events:
            if not isinstance(event,dict) or set(event)!={'id','data'} or not isinstance(event['data'],dict):
                raise Problem('each event requires exactly id and data object')
            upstream = identifier(event['id'],'event id')
            payload = canonical(event['data'])
            if len(payload.encode())>32768:
                raise Problem('individual event exceeds 32 KiB',413)
            # Source scope prevents independent collectors from colliding.
            eid = hashlib.sha256(canonical([source,upstream]).encode()).hexdigest()
            digest = hashlib.sha256(canonical([package,event['data']]).encode()).hexdigest()
            prepared.append((eid,payload,digest))
        accepted, duplicates, ids = 0,0,[]
        with self.tx() as c:
            count = c.execute('SELECT COUNT(*) FROM raw_events WHERE tenant=?',(tenant,)).fetchone()[0]
            for eid,payload,digest in prepared:
                old = c.execute('SELECT digest FROM raw_events WHERE tenant=? AND event_id=?',(tenant,eid)).fetchone()
                if old:
                    if old['digest']!=digest:
                        raise Problem('event identity reused with a different payload or integration',409)
                    duplicates += 1
                else:
                    if count+accepted>=self.max_events:
                        raise Problem('local reference capacity reached; no records were accepted',429)
                    c.execute('INSERT INTO raw_events(tenant,event_id,source,integration,payload,digest,received) VALUES(?,?,?,?,?,?,?)',
                              (tenant,eid,source,package,payload,digest,time.time()))
                    accepted += 1
                ids.append(eid)
            self.audit(c,tenant,actor,'events.accept',{'accepted':accepted,'duplicates':duplicates,'source':source})
        return dict(accepted=accepted,duplicates=duplicates,event_ids=ids)

    def normalize_one(self):
        with self.tx() as c:
            r = c.execute("SELECT r.* FROM raw_events r LEFT JOIN processed p ON p.tenant=r.tenant AND p.event_id=r.event_id AND p.consumer='normalizer' WHERE p.event_id IS NULL ORDER BY r.seq LIMIT 1").fetchone()
            if not r:
                return False
            try:
                active = c.execute('SELECT version FROM activations WHERE tenant=? AND package=?',(r['tenant'],r['integration'])).fetchone()
                p = self.packages.get(r['integration'])
                if not p or not active or active['version']!=p['version']:
                    raise Problem('integration is not active at this installed version')
                n = self.normalize(p,json.loads(r['payload']))
                c.execute('INSERT OR IGNORE INTO normalized VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',
                          (r['tenant'],r['event_id'],r['source'],n['event_time'],r['received'],time.time(),n['actor'],n['ip'],n['outcome'],n['message'],p['id'],p['version']))
                c.execute('DELETE FROM quarantine WHERE tenant=? AND event_id=?',(r['tenant'],r['event_id']))
            except Problem as e:
                c.execute('INSERT INTO quarantine(tenant,event_id,reason) VALUES(?,?,?) ON CONFLICT(tenant,event_id) DO UPDATE SET reason=excluded.reason',
                          (r['tenant'],r['event_id'],str(e)))
            c.execute("INSERT INTO processed VALUES('normalizer',?,?)",(r['tenant'],r['event_id']))
        return True

    def detect_one(self):
        with self.tx() as c:
            r = c.execute("SELECT n.* FROM normalized n LEFT JOIN processed p ON p.tenant=n.tenant AND p.event_id=n.event_id AND p.consumer='detector' WHERE p.event_id IS NULL ORDER BY n.event_time,n.event_id LIMIT 1").fetchone()
            if not r:
                return False
            # Local reference: fixed 5-minute event-time buckets, not sliding windows.
            bucket = int(r['event_time']//300)*300
            if r['outcome']=='failure':
                rows = c.execute("SELECT event_id FROM normalized WHERE tenant=? AND source=? AND actor=? AND ip=? AND outcome='failure' AND event_time>=? AND event_time<? ORDER BY event_time,event_id",
                                 (r['tenant'],r['source'],r['actor'],r['ip'],bucket,bucket+300)).fetchall()
                if len(rows)>=5:
                    aid = hashlib.sha256(canonical([r['tenant'],r['source'],r['actor'],r['ip'],bucket,'auth.failures.v1']).encode()).hexdigest()
                    evidence = canonical([x['event_id'] for x in rows])
                    c.execute("INSERT INTO alerts VALUES(?,?,?,'Repeated authentication failures','medium',?,?) ON CONFLICT(id) DO UPDATE SET evidence=excluded.evidence",
                              (aid,r['tenant'],'auth.failures.v1',time.time(),evidence))
            c.execute("INSERT INTO processed VALUES('detector',?,?)",(r['tenant'],r['event_id']))
        return True

    def drain(self,limit=2000):
        steps=0
        while steps<limit:
            a=self.normalize_one()
            b=self.detect_one()
            if not a and not b:
                break
            steps+=1
        return steps

    def replay(self,tenant,actor,event_id):
        identifier(event_id, "event id")
        with self.tx() as c:
            q=c.execute('SELECT * FROM quarantine WHERE tenant=? AND event_id=?',(tenant,event_id)).fetchone()
            if not q:
                raise Problem('quarantined event not found',404)
            if q['attempts']>=3:
                raise Problem('replay attempt limit reached',409)
            c.execute('UPDATE quarantine SET attempts=attempts+1 WHERE tenant=? AND event_id=?',(tenant,event_id))
            c.execute("DELETE FROM processed WHERE tenant=? AND event_id=? AND consumer='normalizer'",(tenant,event_id))
            self.audit(c,tenant,actor,'quarantine.replay',{'event_id':event_id,'attempt':q['attempts']+1})
        return {'state':'queued'}

    def search(self,tenant,params):
        allowed={'q','outcome','after','before','limit','ip'}
        if set(params)-allowed:
            raise Problem('unsupported search parameter')
        try:
            limit=int(params.get('limit','100'))
            if not 1<=limit<=500: raise ValueError()
        except (ValueError,TypeError):
            raise Problem('limit must be between 1 and 500')
        where=['tenant=?']; args=[tenant]
        for field in ('outcome','ip'):
            if params.get(field):
                where.append(field+'=?'); args.append(params[field])
        for field,op in [('after','>='),('before','<')]:
            if params.get(field):
                where.append('event_time'+op+'?'); args.append(timestamp(params[field]))
        if params.get('q'):
            if len(params['q'])>256: raise Problem('query too long')
            where.append('(instr(message,?)>0 OR instr(actor,?)>0)')
            args.extend([params['q'],params['q']])
        with self.connect() as c:
            return [dict(r) for r in c.execute('SELECT * FROM normalized WHERE '+' AND '.join(where)+' ORDER BY event_time DESC,event_id LIMIT ?',args+[limit])]

    def listing(self,tenant,table):
        if table not in ('alerts','cases','audit','quarantine'):
            raise Problem('unknown collection',404)
        with self.connect() as c:
            return [dict(r) for r in c.execute('SELECT * FROM '+table+' WHERE tenant=? ORDER BY rowid DESC LIMIT 200',(tenant,))]

    def create_case(self,tenant,actor,alert_id):
        identifier(alert_id, "alert id")
        with self.tx() as c:
            a=c.execute('SELECT * FROM alerts WHERE tenant=? AND id=?',(tenant,alert_id)).fetchone()
            if not a: raise Problem('alert not found',404)
            c.execute('INSERT OR IGNORE INTO cases(tenant,alert_id,title,created) VALUES(?,?,?,?)',(tenant,alert_id,a['title'],time.time()))
            row=c.execute('SELECT * FROM cases WHERE tenant=? AND alert_id=?',(tenant,alert_id)).fetchone()
            self.audit(c,tenant,actor,'case.create',{'id':row['id'],'alert_id':alert_id})
        return dict(row)

    def health(self,tenant):
        with self.connect() as c:
            counts={k:c.execute('SELECT COUNT(*) FROM '+k+' WHERE tenant=?',(tenant,)).fetchone()[0] for k in ('raw_events','normalized','quarantine','alerts','cases')}
            for consumer,table in [('normalizer','raw_events'),('detector','normalized')]:
                pending=c.execute('SELECT COUNT(*),MIN(n.received) FROM '+table+' n WHERE tenant=? AND NOT EXISTS (SELECT 1 FROM processed p WHERE p.tenant=n.tenant AND p.event_id=n.event_id AND p.consumer=?)',(tenant,consumer)).fetchone()
                counts[consumer+'_pending']=pending[0]
                counts[consumer+'_oldest_seconds']=max(0,time.time()-pending[1]) if pending[1] else 0
            counts['local_capacity_events']=self.max_events
            counts['mode']='local-reference'
            counts['status']='attention' if counts['quarantine'] or counts['normalizer_pending'] or counts['detector_pending'] else 'healthy'
            return counts

    def integrations(self,tenant):
        with self.connect() as c:
            active={r['package']:r['version'] for r in c.execute('SELECT * FROM activations WHERE tenant=?',(tenant,))}
        return [dict(id=p['id'],name=p['name'],version=p['version'],description=p['description'],sha256=p['sha256'],fixture_count=len(p['fixtures']),active=active.get(p['id'])==p['version']) for p in self.packages.values()]

    def event(self,tenant,event_id):
        identifier(event_id,'event id')
        with self.connect() as c:
            r=c.execute('SELECT * FROM raw_events WHERE tenant=? AND event_id=?',(tenant,event_id)).fetchone()
            if not r: raise Problem('event not found',404)
            n=c.execute('SELECT * FROM normalized WHERE tenant=? AND event_id=?',(tenant,event_id)).fetchone()
            q=c.execute('SELECT * FROM quarantine WHERE tenant=? AND event_id=?',(tenant,event_id)).fetchone()
            stages=[x['consumer'] for x in c.execute('SELECT consumer FROM processed WHERE tenant=? AND event_id=?',(tenant,event_id))]
        return {'raw':dict(r),'normalized':dict(n) if n else None,'quarantine':dict(q) if q else None,'completed_stages':stages}
