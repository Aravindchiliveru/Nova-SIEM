"""Black-box test of the actual local cluster. Never substitutes mocks for services."""
import argparse
import json
import subprocess
import sys
import time
import uuid
from datetime import datetime,timezone
from pathlib import Path
from urllib.error import HTTPError,URLError
from urllib.parse import urlencode
from urllib.request import Request,build_opener,ProxyHandler
from cluster import LAB,compose_args

OPEN=build_opener(ProxyHandler({}))

def call(path,token,body=None):
    req=Request('http://127.0.0.1:8787'+path,data=json.dumps(body).encode() if body is not None else None,
                headers={'Authorization':'Bearer '+token,'Content-Type':'application/json'})
    try:
        with OPEN.open(req,timeout=20) as r:return r.status,json.load(r)
    except HTTPError as e:return e.code,json.load(e)

def wait_for(fn,description,timeout=90):
    deadline=time.monotonic()+timeout
    while time.monotonic()<deadline:
        try:
            result=fn()
            if result:return result
        except (URLError,ConnectionError,TimeoutError):pass
        time.sleep(.5)
    raise AssertionError('Timed out: '+description)

def require(status,expected):
    if status!=expected:raise AssertionError(f'HTTP {status}; expected {expected}')

def run_sequence(token,label):
    run='cluster-test-'+label+'-'+uuid.uuid4().hex
    now=datetime.now(timezone.utc).isoformat()
    body={'source':'cluster-test','integration':'auth-json','events':[{'id':run+'-'+str(i),'data':{'timestamp':now,'user':run,'src_ip':'192.0.2.10','status':'failure','message':run}} for i in range(5)]}
    status,r=call('/api/events',token,body);require(status,200)
    assert r['accepted']==5
    return run,body,r['event_ids']

def alert_for(token,ids):
    status,rows=call('/api/alerts',token);require(status,200)
    return next((a for a in rows if set(ids)<=set(json.loads(a['evidence']))),None)

def visible(token,run):
    status,rows=call('/api/search?'+urlencode({'q':run}),token)
    return rows if status==200 and len(rows)==5 else None

def main():
    p=argparse.ArgumentParser();p.add_argument('--faults',action='store_true');args=p.parse_args()
    tokens=json.loads((LAB/'local-tokens.json').read_text());token=tokens['admin']
    wait_for(lambda:call('/healthz',token)[0]==200,'gateway readiness')
    require(call('/api/integrations/activate',token,{'package':'auth-json'})[0],200)
    run,body,ids=run_sequence(token,'baseline')
    status,retry=call('/api/events',token,body);require(status,200);assert retry['duplicates']==5
    conflict=json.loads(json.dumps(body));conflict['events'][0]['data']['user']='conflict'
    require(call('/api/events',token,conflict)[0],409)
    wait_for(lambda:visible(token,run),'ClickHouse search visibility')
    alert=wait_for(lambda:alert_for(token,ids),'independent detector')
    status,first_case=call('/api/cases',token,{'alert_id':alert['id']});require(status,200)
    status,retry_case=call('/api/cases',token,{'alert_id':alert['id']});require(status,200)
    assert first_case['id']==retry_case['id']
    require(call('/api/search',tokens['collector'])[0],403)
    malformed=json.loads(json.dumps(body));malformed['events']=malformed['events'][:1]
    malformed['events'][0]['id']=uuid.uuid4().hex;malformed['events'][0]['data']['src_ip']='not-an-ip'
    status,bad=call('/api/events',token,malformed);require(status,200)
    bad_id=bad['event_ids'][0]
    def quarantined():
        status,rows=call('/api/quarantine',token);require(status,200)
        return any(q['event_id']==bad_id for q in rows)
    wait_for(quarantined,'durable quarantine')
    results={'gateway_ingest':True,'retry_identity':True,'conflict_rejection':True,
             'clickhouse_search':True,'detection':True,'case_idempotency_request':True,
             'collector_permissions':True,'quarantine':True,'indexer_outage':None,'analytics_outage':None}
    if args.faults:
        # Only this named, localhost development project is affected.
        subprocess.run(compose_args()+['stop','indexer'],check=True)
        try:
            run,_,ids=run_sequence(token,'indexer-outage')
            wait_for(lambda:alert_for(token,ids),'detection with indexer stopped')
            assert not visible(token,run),'events unexpectedly indexed while indexer stopped'
        finally:subprocess.run(compose_args()+['start','indexer'],check=True)
        wait_for(lambda:visible(token,run),'indexer recovery')
        results['indexer_outage']=True
        subprocess.run(compose_args()+['stop','clickhouse'],check=True)
        try:
            run,_,ids=run_sequence(token,'analytics-outage')
            wait_for(lambda:alert_for(token,ids),'detection with analytics storage stopped')
        finally:
            subprocess.run(compose_args()+['start','clickhouse'],check=True)
            subprocess.run(compose_args()+['restart','indexer'],check=True)
        wait_for(lambda:visible(token,run),'analytics recovery')
        results['analytics_outage']=True
    print(json.dumps({'mode':'real-local-cluster','checks':results},indent=2))
if __name__=='__main__':main()
