"""Bounded declarative rules; no eval, regex execution, or arbitrary code loading."""
import hashlib
import json
import math
import time
from pathlib import Path
from .core import Problem, canonical, identifier, ROOT

LEGACY_FIELDS = {'source', 'actor', 'ip', 'outcome', 'message'}
FIELDS = LEGACY_FIELDS | {'category','action','host','target'}
RULE_SCHEMA = """
CREATE TABLE IF NOT EXISTS rule_hits (
 tenant TEXT NOT NULL, revision TEXT NOT NULL, event_id TEXT NOT NULL,
 group_key TEXT NOT NULL, distinct_value TEXT NOT NULL,
 PRIMARY KEY(tenant,revision,event_id));
CREATE INDEX IF NOT EXISTS rule_hits_group ON rule_hits(tenant,revision,group_key,distinct_value,event_id);
"""

def validate(rule):
    required={'id','title','severity','enabled','window_seconds','threshold','group_by','match'}
    if not isinstance(rule,dict) or set(rule)-required-{'distinct','description','tags','window_mode','after','sigma'} or required-set(rule):
        raise Problem('invalid rule fields')
    identifier(rule['id'],'rule id')
    if not isinstance(rule['title'],str) or not 1<=len(rule['title'])<=200:raise Problem('invalid rule title')
    if rule['severity'] not in ('low','medium','high','critical') or type(rule['enabled']) is not bool:raise Problem('invalid rule severity or enabled flag')
    for key,maximum in [('window_seconds',86400),('threshold',100000)]:
        if type(rule[key]) is not int or not 1<=rule[key]<=maximum:raise Problem('invalid '+key)
    group=rule['group_by']
    if not isinstance(group,list) or not 1<=len(group)<=4 or any(not isinstance(x,str) or x not in FIELDS-{'message'} for x in group) or len(set(group))!=len(group):raise Problem('invalid grouping')
    if rule.get('distinct') is not None and (not isinstance(rule['distinct'],str) or rule['distinct'] not in FIELDS-{'message'}):raise Problem('invalid distinct field')
    match=rule['match']
    if not isinstance(match,dict) or not match or set(match)-FIELDS:raise Problem('invalid match fields')
    for value in match.values():
        if not isinstance(value,list) or not 1<=len(value)<=100 or any(not isinstance(v,str) or len(v)>256 for v in value):raise Problem('matches require bounded exact string lists')
    if 'description' in rule and (not isinstance(rule['description'],str) or len(rule['description'])>2000):raise Problem('invalid description')
    if 'tags' in rule and (not isinstance(rule['tags'],list) or len(rule['tags'])>20 or any(not isinstance(t,str) or len(t)>100 for t in rule['tags'])):raise Problem('invalid tags')
    mode=rule.get('window_mode','fixed')
    if mode not in ('fixed','sliding','sequence'):raise Problem('unsupported window mode')
    if mode=='sequence':
        after=rule.get('after')
        if not isinstance(after,dict) or not after or set(after)-FIELDS:raise Problem('sequence requires an after selection')
        for values in after.values():
            if not isinstance(values,list) or not 1<=len(values)<=100 or any(not isinstance(v,str) or len(v)>256 for v in values):raise Problem('invalid sequence selection')
    elif 'after' in rule:raise Problem('after requires sequence mode')
    if 'sigma' in rule:
        from .sigma import validate_node
        validate_node(rule['sigma'])
        if mode!='fixed':raise Problem('Sigma predicate requires fixed single-event rule')
    return dict(rule)

class Rules:
    def __init__(self,directory=None):
        self.rules=[]
        seen=set()
        for path in sorted(Path(directory or ROOT/'rules').glob('*.json')):
            if path.stat().st_size>65536:raise Problem('rule package too large')
            from .packages import verify
            raw=path.read_bytes();signature_status=verify(path,raw)
            r=validate(json.loads(raw))
            if r['id'] in seen:raise Problem('duplicate rule id')
            seen.add(r['id'])
            r['revision']=hashlib.sha256(canonical(r).encode()).hexdigest()
            r['signature_status']=signature_status
            self.rules.append(r)
        if not self.rules or len(self.rules)>100:raise Problem('install between 1 and 100 rules')
    @staticmethod
    def matches(rule,event):
        if not rule['enabled'] or not all(event.get(field) in values for field,values in rule['match'].items()):return False
        if 'sigma' in rule:
            from .sigma import evaluate
            return evaluate(rule['sigma'],event)
        return True
    @staticmethod
    def group(rule,event):
        bucket=math.floor(event['event_time']/rule['window_seconds'])
        return hashlib.sha256(canonical([event['tenant'],rule['revision'],bucket,[event[f] for f in rule['group_by']]]).encode()).hexdigest()
    def effective(self,c,tenant,postgres=False):
        from .enterprise import execute
        settings={r['rule_id']:r for r in execute(c,'SELECT * FROM nova_rule_settings WHERE tenant=?',(tenant,),postgres)}
        rules=[]
        for original in self.rules:
            r=dict(original);setting=settings.get(r['id'])
            if setting:
                r['enabled']=bool(setting['enabled']) and setting['revision']==r['revision']
                r['configuration_stale']=setting['revision']!=r['revision']
            r['configuration_source']='tenant' if setting else 'package-default'
            rules.append(r)
        return rules
    def evaluate(self,c,events,postgres=False):
        for tenant in sorted({e['tenant'] for e in events}):
            self.evaluate_set(c,[e for e in events if e['tenant']==tenant],self.effective(c,tenant,postgres),postgres)
    def evaluate_set(self,c,events,rules,postgres=False):
        def execute(sql,args=()):return c.execute(sql.replace('?', '%s') if postgres else sql,args)
        advanced=[r for r in rules if r.get('window_mode','fixed')!='fixed']
        fixed=[r for r in rules if r.get('window_mode','fixed')=='fixed']
        from .correlation import evaluate
        evaluate(c,events,advanced,postgres)
        touched={}
        for event in events:
            for rule in fixed:
                if not self.matches(rule,event):continue
                key=self.group(rule,event)
                touched[(event['tenant'],rule['revision'],key)]=rule
        # Consistent lock order avoids multi-group deadlocks between detector workers.
        if postgres:
            for tenant,rev,key in sorted(touched):execute('SELECT pg_advisory_xact_lock(hashtextextended(?,2))',(key,))
        for event in events:
            for rule in fixed:
                if self.matches(rule,event):
                    execute('INSERT INTO rule_hits VALUES(?,?,?,?,?) ON CONFLICT DO NOTHING',
                            (event['tenant'],rule['revision'],event['event_id'],self.group(rule,event),event[rule['distinct']] if rule.get('distinct') else event['event_id']))
        for (tenant,revision,key),rule in touched.items():
            args=(tenant,revision,key)
            row=execute('SELECT COUNT(*) AS event_count,COUNT(DISTINCT distinct_value) AS match_count FROM rule_hits WHERE tenant=? AND revision=? AND group_key=?',args).fetchone()
            if row['match_count']<rule['threshold']:continue
            evidence=[r['event_id'] for r in execute('SELECT event_id FROM rule_hits WHERE tenant=? AND revision=? AND group_key=? ORDER BY event_id LIMIT 100',args)]
            if postgres:
                execute('INSERT INTO nova_alerts VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET evidence=excluded.evidence,event_count=excluded.event_count',
                        (key,tenant,rule['id'],rule['title'],rule['severity'],time.time(),canonical(evidence),row['event_count']))
            else:
                execute('INSERT INTO alerts(id,tenant,rule,title,severity,created,evidence) VALUES(?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET evidence=excluded.evidence',
                        (key,tenant,rule['id'],rule['title'],rule['severity'],time.time(),canonical(evidence)))
    @staticmethod
    def simulate(rule,events):
        rule=validate(rule)
        rule['revision']=hashlib.sha256(canonical(rule).encode()).hexdigest()
        if not isinstance(events,list) or len(events)>500:raise Problem('simulation accepts at most 500 normalized events')
        groups={};prepared=[]
        for i,event in enumerate(events):
            if not isinstance(event,dict) or any(not isinstance(event.get(k),str) or len(event[k])>8192 for k in LEGACY_FIELDS):raise Problem('simulation needs normalized string fields')
            if type(event.get('event_time')) not in (int,float) or not math.isfinite(event['event_time']):raise Problem('invalid event time')
            # Tenant cannot be selected by supplied simulation data.
            e=dict(category='authentication',action='login',host='',target='')
            e.update(event,tenant='simulation',event_id=str(i))
            if any(not isinstance(e[k],str) or len(e[k])>8192 for k in FIELDS):raise Problem('invalid normalized field')
            prepared.append(e)
            if Rules.matches(rule,e):
                key=Rules.group(rule,e); g=groups.setdefault(key,{'events':0,'values':set()})
                g['events']+=1;g['values'].add(e[rule['distinct']] if rule.get('distinct') else str(i))
        if rule.get('window_mode','fixed')!='fixed':
            import sqlite3
            from .core import SCHEMA
            from .correlation import SCHEMA as CS,evaluate
            c=sqlite3.connect(':memory:');c.row_factory=sqlite3.Row
            try:
                c.executescript(SCHEMA+CS);evaluate(c,prepared,[rule])
                return {'alerts':[dict(r) for r in c.execute('SELECT * FROM alerts')],'window_semantics':rule['window_mode']+' event-time; supplied sample only'}
            finally:c.close()
        return {'groups':[{'event_count':g['events'],'match_count':len(g['values']),'alert':len(g['values'])>=rule['threshold']} for g in groups.values()], 'window_semantics':'fixed UTC event-time buckets; supplied sample only'}
