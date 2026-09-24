"""Local correctness baseline only; not a distributed capacity benchmark."""
import argparse,json,platform,sys,tempfile,time
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from nova.core import Engine
p=argparse.ArgumentParser();p.add_argument('--events',type=int,default=1000);a=p.parse_args()
if not 1<=a.events<=100000: p.error('events must be 1..100000')
with tempfile.TemporaryDirectory() as d:
    e=Engine(Path(d)/'db');e.activate('bench','runner','auth-json')
    start=time.perf_counter()
    for first in range(0,a.events,500):
        e.ingest('bench','runner',{'source':'benchmark','integration':'auth-json','events':[{'id':str(i),'data':{'timestamp':'2026-09-17T12:00:00Z','user':'u'+str(i%100),'src_ip':'192.0.2.1','status':'success','message':'Synthetic success'}} for i in range(first,min(first+500,a.events))]})
    accepted=time.perf_counter();e.drain(a.events+1);finished=time.perf_counter()
    health=e.health('bench')
    assert health['raw_events']==health['normalized']==a.events
    assert health['normalizer_pending']==health['detector_pending']==0
    print(json.dumps({'mode':'local-reference-only','python':platform.python_version(),'events':a.events,'accept_seconds':accepted-start,'process_seconds':finished-accepted,'end_to_end_seconds':finished-start,'end_to_end_events_per_second':a.events/(finished-start),'workload':'small synthetic successes, zero query concurrency; not comparable to SIEM production EPS','health':health},indent=2))
