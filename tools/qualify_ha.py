"""Operator-controlled live fault qualification. Default mode performs no mutations."""
import argparse,hashlib,json,subprocess,sys,time,uuid
from datetime import datetime,timezone
from pathlib import Path
from urllib.request import Request,build_opener,ProxyHandler
from urllib.parse import urlsplit
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from nova.collector import NoRedirect
REQUIRED={'gateway_loss','broker_loss','metadata_primary_loss','analytics_replica_loss','isolated_restore'}

def validate(config):
    if not isinstance(config,dict) or set(config)!={'gateway','admin_token_file','collector_token_file','rto_seconds','scenarios'}:raise ValueError('invalid qualification configuration')
    if type(config['rto_seconds']) is not int or not 1<=config['rto_seconds']<=3600:raise ValueError('rto_seconds must be 1..3600')
    for url in [config['gateway']]+[s.get('verify_gateway','') for s in config['scenarios']]:
        u=urlsplit(url)
        if u.scheme!='https' or not u.hostname or u.username or u.password or u.query or u.fragment or u.path not in ('','/'):raise ValueError('HTTPS gateway origins required')
    if len(config['scenarios'])!=5 or {s.get('name') for s in config['scenarios']}!=REQUIRED:raise ValueError('all five distinct scenarios required')
    for s in config['scenarios']:
        if set(s)!={'name','inject_argv','verify_fault_argv','recover_argv','verify_gateway'}:raise ValueError('invalid scenario')
        for key in ('inject_argv','verify_fault_argv','recover_argv'):
            if not isinstance(s[key],list) or not s[key] or any(not isinstance(x,str) or not x for x in s[key]):raise ValueError('command argv required')
    return config

def call(origin,path,token,body=None):
    req=Request(origin.rstrip('/')+path,data=json.dumps(body).encode() if body is not None else None,headers={'Authorization':'Bearer '+token,'Content-Type':'application/json'})
    with build_opener(ProxyHandler({}),NoRedirect()).open(req,timeout=5) as response:
        raw=response.read(1048577)
        if response.status!=200 or len(raw)>1048576:raise RuntimeError('invalid gateway response')
        return json.loads(raw)

def execute(config):
    # Use a dedicated synthetic-data qualification tenant and operator-reviewed fault commands.
    admin=Path(config['admin_token_file']).read_text().strip();collector=Path(config['collector_token_file']).read_text().strip();results=[]
    for scenario in config['scenarios']:
        call(config['gateway'],'/api/integrations/activate',admin,{'package':'auth-json'})
        source='ha-'+uuid.uuid4().hex;when=datetime.now(timezone.utc).isoformat()
        body=dict(source=source,integration='auth-json',events=[dict(id=str(i),data=dict(timestamp=when,user='qualification-user',src_ip='192.0.2.1',status='failure',message='Synthetic HA qualification event')) for i in range(10)])
        accepted=call(config['gateway'],'/api/events',collector,body)
        expected=[hashlib.sha256(json.dumps([source,str(i)],separators=(',',':')).encode()).hexdigest() for i in range(10)]
        if accepted.get('event_ids')!=expected or accepted.get('accepted')!=10:raise RuntimeError('acceptance mismatch')
        during=dict(body,events=[dict(item,id=str(i+10)) for i,item in enumerate(body['events'])])
        during_ids=[hashlib.sha256(json.dumps([source,str(i)],separators=(',',':')).encode()).hexdigest() for i in range(10,20)]
        expected+=during_ids
        accepted_during=False;fault_verified=False;available_at=None
        started=time.monotonic();passed=False;failure=None;missing=expected[:];recovered=False
        try:
            subprocess.run(scenario['inject_argv'],check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=config['rto_seconds'])
            subprocess.run(scenario['verify_fault_argv'],check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=config['rto_seconds'])
            fault_verified=True
            # Injection command must leave the component unavailable, or restore into the isolated target.
            # We test service availability BEFORE running the recover command.
            while time.monotonic()-started<config['rto_seconds']:
                try:
                    if not accepted_during:
                        ack=call(scenario['verify_gateway'],'/api/events',collector,during)
                        if ack.get('event_ids')!=during_ids or ack.get('accepted',-100)+ack.get('duplicates',-100)!=10:raise RuntimeError('during-fault acceptance mismatch')
                        accepted_during=True
                    missing=[]
                    for eid in expected:
                        event=call(scenario['verify_gateway'],'/api/event?id='+eid,admin)
                        if not event.get('normalized') or event.get('quarantine') or not all(event.get('receipt',{}).get(k) is not None for k in ('normalized_at','indexed_at','detected_at','archived_at','locked_at')):missing.append(eid)
                    alerts=call(scenario['verify_gateway'],'/api/alerts',admin)
                    evidence=set().union(*(set(json.loads(a['evidence'])) for a in alerts))
                    covered=set(expected)<=evidence
                    if not missing and covered:
                        retry=call(scenario['verify_gateway'],'/api/events',collector,body)
                        if retry.get('duplicates')!=10 or retry.get('accepted')!=0 or retry.get('event_ids')!=expected[:10]:raise RuntimeError('duplicate replay mismatch')
                        subprocess.run(scenario['verify_fault_argv'],check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=max(1,config['rto_seconds']-(time.monotonic()-started)))
                        available_at=time.monotonic()-started
                        passed=available_at<=config['rto_seconds'];break
                except Exception:missing=expected[:]
                time.sleep(.5)
            if not passed:failure='RTO expired or evidence/duplicate checks failed'
        except Exception as exc:failure=type(exc).__name__
        finally:
            try:subprocess.run(scenario['recover_argv'],check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=config['rto_seconds']);recovered=True
            except Exception:failure='recovery command failed';passed=False
        results.append(dict(scenario=scenario['name'],passed=passed,recovery_command_succeeded=recovered,acknowledged_before_fault=10,acknowledged_during_fault=10 if accepted_during else 0,fault_verified=fault_verified,service_recovery_seconds=available_at,missing_after_check=len(missing),elapsed_seconds=time.monotonic()-started,error=failure))
        if not recovered:break
    return dict(scope='Short synthetic fault scenarios, not full production certification',configuration_sha256=hashlib.sha256(json.dumps(config,sort_keys=True).encode()).hexdigest(),scenarios=results,all_scenarios_passed=len(results)==5 and all(x['passed'] for x in results),production_ha_dr_proven=False)

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--config',required=True);p.add_argument('--execute-faults',action='store_true');p.add_argument('--output',required=True);a=p.parse_args();config=validate(json.loads(Path(a.config).read_text()))
    result=execute(config) if a.execute_faults else {'status':'not_run','reason':'Fault execution requires explicit --execute-faults and operator-reviewed isolated test deployment','production_ha_dr_proven':False}
    with open(a.output,'x') as f:json.dump(result,f,indent=2)
    print(json.dumps(result,indent=2));return 0 if result.get('all_scenarios_passed') else 2
if __name__=='__main__':raise SystemExit(main())
