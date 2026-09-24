"""Reproducible local typed-event ingest, normalize, detect and search benchmark."""
import hashlib,json,platform,resource,statistics,sys,tempfile,time
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from nova.core import Engine
from nova.enterprise import Enterprise
ROOT=Path(__file__).resolve().parents[1]

def measure(count=10000):
    with tempfile.TemporaryDirectory() as d:
        e=Engine(Path(d)/'db');x=Enterprise(e)
        categories=['process','network','dns','file','cloud']
        for category in categories:e.activate('bench','admin',category+'-json')
        rule=next(r for r in x.rule_catalog('bench') if r['id']=='cloud.logging-disabled.v1')
        x.set_rule('bench','admin',{'id':rule['id'],'revision':rule['revision'],'enabled':True})
        batches={c:[] for c in categories}
        for i in range(count):
            category=categories[i%5]
            data=dict(timestamp='2026-09-21T12:00:00Z',action='StopLogging' if i%100==4 else 'observe',target=f'resource-{i}',message='Synthetic typed-event benchmark',actor='user',host=f'host-{i%50}',outcome='unknown')
            batches[category].append(dict(id=str(i),data=data))
        cpu=time.process_time();start=time.perf_counter()
        for category,events in batches.items():
            for offset in range(0,len(events),500):e.ingest('bench','collector',dict(source='synthetic',integration=category+'-json',events=events[offset:offset+500]))
        e.drain(count*2);elapsed=time.perf_counter()-start;cpu=time.process_time()-cpu
        with e.connect() as c:
            counts={name:c.execute('SELECT COUNT(*) FROM '+name).fetchone()[0] for name in ('raw_events','normalized','quarantine','alerts')}
            assert counts==dict(raw_events=count,normalized=count,quarantine=0,alerts=count//100),counts
            assert c.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
        latency=[]
        for _ in range(100):
            start=time.perf_counter();rows=e.search('bench',{'category':'cloud','action':'StopLogging'});latency.append((time.perf_counter()-start)*1000)
            assert len(rows)==count//100
        return dict(events=count,counts=counts,completed_seconds=elapsed,completed_eps=count/elapsed,cpu_seconds=cpu,search_p95_ms=sorted(latency)[94],process_max_rss_kib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
if __name__=='__main__':
    runs=[measure() for _ in range(3)]
    result=dict(release='0.5',scope='Single-host SQLite FULL WAL; direct engine calls; five native categories; cloud rule enabled; synthetic data; not distributed or commercial comparison',python=platform.python_version(),code_sha256={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted((ROOT/'nova').rglob('*.py'))},runs=runs,median_completed_eps=statistics.median(r['completed_eps'] for r in runs))
    (ROOT/'benchmarks/typed-results.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result,indent=2))
