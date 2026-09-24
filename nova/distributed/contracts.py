"""Versioned wire contracts and dependency-free worker boundaries."""
import hashlib
import json
import math
import time
from dataclasses import dataclass
from pathlib import Path
from ..core import Engine, Problem, canonical, identifier

RAW_TOPIC='nova.raw.v1'
NORMAL_TOPIC='nova.normalized.v1'
QUARANTINE_TOPIC='nova.quarantine.v1'
TOPICS=(RAW_TOPIC,NORMAL_TOPIC,QUARANTINE_TOPIC)

def strict_json(raw):
    def pairs(items):
        d={}
        for k,v in items:
            if k in d: raise ValueError('duplicate JSON key')
            d[k]=v
        return d
    def reject(_): raise ValueError('nonfinite JSON number')
    return json.loads(raw,object_pairs_hook=pairs,parse_constant=reject)

class Packages:
    normalize=staticmethod(Engine.normalize)
    def __init__(self,path):
        self.package_dir=Path(path)
        self.packages=Engine._packages(self)

def prepare(tenant,body,now=None):
    identifier(tenant,'tenant')
    if not isinstance(body,dict) or set(body)-{'source','integration','events'}:
        raise Problem('allowed request fields: source, integration, events')
    source=identifier(body.get('source'),'source')
    package=identifier(body.get('integration'),'integration')
    events=body.get('events')
    if not isinstance(events,list) or not 1<=len(events)<=500:
        raise Problem('batch requires 1 to 500 events')
    now=time.time() if now is None else now
    results=[]
    for e in events:
        if not isinstance(e,dict) or set(e)!={'id','data'} or not isinstance(e['data'],dict):
            raise Problem('each event requires exactly id and data object')
        upstream=identifier(e['id'],'event id')
        try: text=canonical(e['data'])
        except (ValueError,TypeError,RecursionError):raise Problem('invalid JSON data')
        if len(text.encode())>32768:raise Problem('individual event exceeds 32 KiB',413)
        eid=hashlib.sha256(canonical([source,upstream]).encode()).hexdigest()
        digest=hashlib.sha256(canonical([package,e['data']]).encode()).hexdigest()
        results.append(dict(contract='nova.raw.v1',tenant=tenant,event_id=eid,source=source,
                            integration=package,digest=digest,received=now,payload=e['data'],
                            package_digest='',replay_generation=0))
    return results

def validate_raw(r):
    if not isinstance(r,dict) or r.get('contract')!='nova.raw.v1':raise ValueError('unsupported raw contract')
    for k in ('tenant','source','integration'):identifier(r.get(k),k)
    for k in ('event_id','digest'):
        v=r.get(k)
        if not isinstance(v,str) or len(v)!=64 or any(c not in '0123456789abcdef' for c in v):raise ValueError('invalid '+k)
    received=r.get('received')
    if type(received) not in (int,float) or not math.isfinite(received):raise ValueError('invalid received time')
    generation=r.get('replay_generation')
    if type(generation)!=int or not 0<=generation<=3:raise ValueError('invalid replay generation')
    digest=r.get('package_digest')
    if not isinstance(digest,str) or (digest and (len(digest)!=64 or any(c not in '0123456789abcdef' for c in digest))):raise ValueError('invalid package digest')
    if not isinstance(r.get('payload'),dict):raise ValueError('invalid payload')
    if len(canonical(r['payload']).encode())>32768:raise ValueError('payload exceeds maximum')
    expected=hashlib.sha256(canonical([r['integration'],r['payload']]).encode()).hexdigest()
    if expected!=r['digest']:raise ValueError('payload digest mismatch')
    return r

def transform(r,packages,now=None):
    validate_raw(r)
    try:
        p=packages.get(r['integration'])
        if not p or p['sha256']!=r['package_digest']:
            raise Problem('installed package does not match the ingestion snapshot; activate and replay')
        n=Engine.normalize(p,r['payload'])
    except Problem as e:
        return QUARANTINE_TOPIC,dict(contract='nova.quarantine.v1',raw=r,reason=str(e))
    n.update(contract='nova.normalized.v1',tenant=r['tenant'],event_id=r['event_id'],
             source=r['source'],received=r['received'],normalized_at=time.time() if now is None else now,
             parser=p['id'],version=p['version'],raw=r)
    return NORMAL_TOPIC,n

def validate_normal(n):
    if not isinstance(n,dict) or n.get('contract')!='nova.normalized.v1':raise ValueError('unsupported normalized contract')
    r=validate_raw(n.get('raw'))
    for k in ('tenant','event_id','source','received'):
        if n.get(k)!=r[k]:raise ValueError('normalized identity differs from raw record')
    for k in ('event_time','normalized_at'):
        if type(n.get(k)) not in (int,float) or not math.isfinite(n[k]):raise ValueError('invalid '+k)
    for k in ('actor','ip','outcome','message','parser','version'):
        if not isinstance(n.get(k),str) or len(n[k])>8192:raise ValueError('invalid '+k)
    # Legacy wire rows are authentication; producers now always emit explicit fields.
    n=dict(n)
    for key,value in [('category','authentication'),('action','login'),('host',''),('target','')]:
        n.setdefault(key,value)
    from ..events import validate_fields
    validate_fields(n)

    return n

@dataclass(frozen=True)
class Record:
    topic:str
    partition:int
    offset:int
    value:bytes

def offsets(records):
    result={}
    for r in records:
        key=(r.topic,r.partition)
        result[key]=max(result.get(key,0),r.offset+1)
    return result

class Processor:
    """All outputs finish before explicit offset commit; exceptions stop progress."""
    def __init__(self,consumer,sink,decode=True):
        self.consumer,self.sink,self.decode=consumer,sink,decode
    def step(self):
        records=self.consumer.read(200)
        if not records:return 0
        values=[strict_json(r.value) for r in records] if self.decode else records
        self.sink.write(values)
        self.consumer.commit(offsets(records))
        return len(records)

class NormalizerSink:
    def __init__(self,publisher,packages):self.publisher,self.packages=publisher,packages
    def write(self,rows):
        # Validate/transform the whole batch before publishing any of it.
        outputs=[transform(r,self.packages) for r in rows]
        self.publisher.publish(outputs)
