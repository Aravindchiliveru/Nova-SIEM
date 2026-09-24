"""Local structured mapping/search microbenchmark; no distributed sizing claim."""
import json,sys,time,tempfile,statistics,resource
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from nova.core import Engine

def run(count=3000):
    with tempfile.TemporaryDirectory() as d:
        e=Engine(Path(d)/'db');e.activate('bench','admin','nested-process-json')
        doc=json.loads(Path('examples/nested-process.ndjson').read_text());started=time.perf_counter();cpu=time.process_time()
        for start in range(0,count,200):
            e.ingest('bench','collector',dict(source='nested-bench',integration='nested-process-json',events=[{'id':str(i),'data':dict(doc,context={'bucket':i%10,'details':[{'label':'sample'}]})} for i in range(start,min(count,start+200))]))
        e.drain(count+200);elapsed=time.perf_counter()-started;cpu=time.process_time()-cpu
        latencies=[]
        for _ in range(100):
            start=time.perf_counter();rows=e.search('bench',{'field':'context.bucket','value':'3','limit':'500','include_document':'true'});latencies.append(1000*(time.perf_counter()-start));assert len(rows)==count//10
            assert all(r['document']['context']['bucket']==3 for r in rows)
        assert e.health('bench')['normalized']==count
        return dict(scope='Single local SQLite process; no HTTP, concurrent clients, remote storage or cluster',events=count,ingest_and_drain_seconds=elapsed,completed_eps=count/elapsed,cpu_seconds=cpu,max_rss_kib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,queries=100,returned_per_query=count//10,search_p50_ms=statistics.median(latencies),search_p95_ms=sorted(latencies)[94],lossless_document_checks_passed=True)
if __name__=='__main__':
    result=run();Path('benchmarks/structured-v0.8.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result,indent=2))
