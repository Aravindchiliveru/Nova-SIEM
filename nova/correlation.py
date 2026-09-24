"""Bounded event-time correlation for sliding thresholds and ordered sequences."""
import bisect
import hashlib
import json
import time
from .core import Problem,canonical
from .enterprise import execute

SCHEMA='''
CREATE TABLE IF NOT EXISTS nova_correlation_events (
 tenant TEXT NOT NULL,revision TEXT NOT NULL,event_id TEXT NOT NULL,
 group_key TEXT NOT NULL,event_time DOUBLE PRECISION NOT NULL,
 first_match INTEGER NOT NULL,last_match INTEGER NOT NULL,distinct_value TEXT NOT NULL,
 PRIMARY KEY(tenant,revision,event_id));
CREATE INDEX IF NOT EXISTS nova_correlation_group ON nova_correlation_events(tenant,revision,group_key,event_time,event_id);
'''
MAX_GROUP_EVENTS=10000

def matches(selection,event):return all(event.get(k) in v for k,v in selection.items())

def evaluate(c,events,rules,postgres=False):
    def sql(q,a=()):return execute(c,q,a,postgres)
    for rule in rules:
        if not rule['enabled']:continue
        touched=set();changes={}
        prepared=[]
        for n in events:
            first=matches(rule['match'],n)
            last=matches(rule['after'],n) if rule['window_mode']=='sequence' else first
            if not (first or last):continue
            group=hashlib.sha256(canonical([n['tenant'],rule['revision'],[n[k] for k in rule['group_by']]]).encode()).hexdigest()
            prepared.append((n,group,first,last))
        if postgres:
            for group in sorted({x[1] for x in prepared}):sql('SELECT pg_advisory_xact_lock(hashtextextended(?,6))',(group,))
        for n,group,first,last in prepared:
            inserted=sql('INSERT INTO nova_correlation_events VALUES(?,?,?,?,?,?,?,?) ON CONFLICT DO NOTHING RETURNING event_id',(n['tenant'],rule['revision'],n['event_id'],group,n['event_time'],int(first),int(last),n[rule['distinct']] if rule.get('distinct') else n['event_id'])).fetchone()
            if inserted:
                touched.add((n['tenant'],group))
                changes.setdefault((n['tenant'],group),[]).append((n['event_id'],n['event_time'],first))
        for tenant,group in sorted(touched):
            rows=list(sql('SELECT * FROM nova_correlation_events WHERE tenant=? AND revision=? AND group_key=? ORDER BY event_time,event_id LIMIT ?',(tenant,rule['revision'],group,MAX_GROUP_EVENTS+1)))
            if len(rows)>MAX_GROUP_EVENTS:raise Problem('correlation group capacity exceeded; transaction retained for operator action',429)
            first=[r for r in rows if r['first_match']];times=[r['event_time'] for r in first]
            changed=changes[(tenant,group)];new_ids={x[0] for x in changed}
            first_times=[x[1] for x in changed if x[2]]
            for anchor in rows:
                if not anchor['last_match']:continue
                # Only a new anchor or a newly arrived predecessor can change an
                # alert. Re-evaluate affected historical anchors for late events.
                upper=anchor['event_time'];lower=upper-rule['window_seconds']
                if anchor['event_id'] not in new_ids and not any(lower<t and (t<upper if rule['window_mode']=='sequence' else t<=upper) for t in first_times):continue
                lo=bisect.bisect_right(times,anchor['event_time']-rule['window_seconds'])
                hi=(bisect.bisect_left if rule['window_mode']=='sequence' else bisect.bisect_right)(times,anchor['event_time'])
                candidates=first[lo:hi]
                if len({r['distinct_value'] for r in candidates})<rule['threshold']:continue
                ids=[r['event_id'] for r in candidates]
                if anchor['event_id'] not in ids:ids.append(anchor['event_id'])
                evidence=ids[:99]+([anchor['event_id']] if anchor['event_id'] not in ids[:99] else [])
                aid=hashlib.sha256(canonical([tenant,rule['revision'],group,anchor['event_id']]).encode()).hexdigest()
                if postgres:
                    sql('INSERT INTO nova_alerts VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET evidence=excluded.evidence,event_count=excluded.event_count',(aid,tenant,rule['id'],rule['title'],rule['severity'],time.time(),canonical(evidence),len(ids)))
                else:
                    sql('INSERT INTO alerts(id,tenant,rule,title,severity,created,evidence) VALUES(?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET evidence=excluded.evidence',(aid,tenant,rule['id'],rule['title'],rule['severity'],time.time(),canonical(evidence)))
