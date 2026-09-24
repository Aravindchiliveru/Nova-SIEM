"""Reproducible local engine comparison. No distributed/vendor performance claims."""
import argparse
import hashlib
import importlib.util
import json
import math
import os
import platform
import resource
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))

def percentile(xs,p):return sorted(xs)[min(len(xs)-1,math.ceil(len(xs)*p)-1)]

def one(root,n,workload):
    if Path(root).resolve()==ROOT:
        from nova.core import Engine
    else:
        spec=importlib.util.spec_from_file_location('baseline_core',Path(root)/'nova/core.py')
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);Engine=module.Engine
    ingest_times=[];queries=[]
    with tempfile.TemporaryDirectory() as d:
        db=Path(d)/'bench.db';e=Engine(db);e.activate('bench','runner','auth-json')
        rows=[]
        for i in range(n):
            outcome='failure' if workload=='hot-failures' or (workload=='mixed' and i%5==0) else 'success'
            actor='target' if workload=='hot-failures' else 'u'+str(i%100)
            rows.append({'id':str(i),'data':{'timestamp':'2026-09-17T12:01:00Z','user':actor,'src_ip':'192.0.2.1','status':outcome,'message':'Synthetic '+outcome+' '+('x'*128)}})
        cpu=time.process_time();start=time.perf_counter()
        for first in range(0,n,500):
            t=time.perf_counter();e.ingest('bench','runner',{'source':'benchmark','integration':'auth-json','events':rows[first:first+500]});ingest_times.append(time.perf_counter()-t)
        accepted=time.perf_counter();e.drain(n+1);end=time.perf_counter();cpu=time.process_time()-cpu
        h=e.health('bench')
        assert h['raw_events']==h['normalized']==n and h['normalizer_pending']==h['detector_pending']==0,h
        # Duplicate retry must not create new records.
        retry=e.ingest('bench','runner',{'source':'benchmark','integration':'auth-json','events':rows[:min(500,n)]})
        assert retry['accepted']==0 and retry['duplicates']==min(500,n)
        assert e.search('other-tenant',{})==[]
        for i in range(100):
            t=time.perf_counter();e.search('bench',{'q':'Synthetic','limit':'100'});queries.append(time.perf_counter()-t)
        with e.connect() as c:
            assert c.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
            assert c.execute('PRAGMA synchronous').fetchone()[0]==2
        sizes=sum(f.stat().st_size for f in Path(d).glob('bench.db*'))
        alerts=e.listing('bench','alerts')
        if workload=='hot-failures':assert any(a['rule']=='auth.failures.v1' for a in alerts)
        return {'events':n,'workload':workload,'wall_seconds':end-start,'eps':n/(end-start),'ingest_seconds':accepted-start,'processing_seconds':end-accepted,'cpu_seconds':cpu,'cpu_seconds_per_1000':cpu*1000/n,'max_rss_kib':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,'database_bytes':sizes,'ingest_batch_p95_ms':percentile(ingest_times,.95)*1000,'search_p50_ms':percentile(queries,.5)*1000,'search_p95_ms':percentile(queries,.95)*1000,'search_p99_ms':percentile(queries,.99)*1000,'alerts':len(alerts),'correctness':'counts, retries, tenant isolation, SQLite integrity, FULL durability passed'}

def main():
    p=argparse.ArgumentParser();p.add_argument('--baseline',default=str(ROOT/'benchmarks/baseline_v0_2'));p.add_argument('--output',default='benchmarks/engine-v0.4-results.json');p.add_argument('--repeats',type=int,default=3);p.add_argument('--events',type=int,default=5000);p.add_argument('--one');p.add_argument('--workload',default='mixed');a=p.parse_args()
    if a.one:print(json.dumps(one(a.one,a.events,a.workload)));return
    if not a.baseline:p.error('--baseline requires extracted v0.2 project directory')
    if not 1<=a.events<=100000 or not 1<=a.repeats<=10:p.error('invalid bounds')
    results=[]
    for workload in ['success','mixed','hot-failures']:
        # Alternate versions to reduce ordering bias; isolated subprocess for RSS.
        for repeat in range(a.repeats):
            order=[('v0.2',a.baseline),('v0.4',str(ROOT))]
            if repeat%2:order.reverse()
            for version,root in order:
                result=subprocess.run([sys.executable,__file__,'--one',str(Path(root).resolve()),'--events',str(a.events),'--workload',workload],capture_output=True,text=True,check=True,timeout=300)
                row=json.loads(result.stdout);row.update(version=version,repeat=repeat+1);results.append(row)
                print(version,workload,repeat+1,round(row['eps'],1),'EPS',flush=True)
    summary=[]
    for workload in ['success','mixed','hot-failures']:
        med={v:statistics.median(r['eps'] for r in results if r['version']==v and r['workload']==workload) for v in ('v0.2','v0.4')}
        summary.append({'workload':workload,'baseline_median_eps':med['v0.2'],'upgraded_median_eps':med['v0.4'],'ratio':med['v0.4']/med['v0.2']})
    report={'scope':'Local Engine API; synthetic data; single process; no network or concurrent query load; not a production sizing recommendation or vendor comparison. v0.4 executes four rules vs one in v0.2. Evidence cap differs (100 in v0.4).','environment':{'python':platform.python_version(),'platform':platform.platform(),'logical_cpus':os.cpu_count(),'cpu_affinity_count':len(os.sched_getaffinity(0)) if hasattr(os,'sched_getaffinity') else None,'sqlite':__import__('sqlite3').sqlite_version,'source_sha256':hashlib.sha256((ROOT/'nova/core.py').read_bytes()).hexdigest(),'baseline_sha256':hashlib.sha256((Path(a.baseline)/'nova/core.py').read_bytes()).hexdigest(),'durability':'SQLite WAL + synchronous FULL both versions','timestamp_utc':time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime())},'summary':summary,'runs':results}
    Path(a.output).parent.mkdir(parents=True,exist_ok=True);Path(a.output).write_text(json.dumps(report,indent=2)+'\n')

if __name__=='__main__':main()
