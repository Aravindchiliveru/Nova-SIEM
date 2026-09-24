"""Measure actual local advanced correlation and internal response workflow execution."""
import hashlib
import json
import resource
import statistics
import sys
import tempfile
import time
from datetime import datetime,timezone
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from nova.core import Engine
from nova.enterprise import Enterprise
ROOT=Path(__file__).resolve().parents[1]

def payload(i):
    # 50 entities, 100 records each, repeated failures followed by success.
    step=i//50
    return {'id':str(i),'data':dict(timestamp=datetime.fromtimestamp(1789646400+step,timezone.utc).isoformat(),user='user'+str(i%50),src_ip='192.0.2.1',status='success' if step%10==9 else 'failure',message='Synthetic advanced-correlation benchmark')}

def measure(advanced):
    with tempfile.TemporaryDirectory() as d:
        e=Engine(Path(d)/'db');e.activate('bench','admin','auth-json');x=Enterprise(e)
        if advanced:
            for r in x.rule_catalog('bench'):
                if r.get('window_mode') in ('sliding','sequence'):x.set_rule('bench','admin',{'id':r['id'],'revision':r['revision'],'enabled':True})
        rows=[payload(i) for i in range(5000)]
        cpu=time.process_time();start=time.perf_counter()
        for first in range(0,5000,500):e.ingest('bench','collector',{'source':'benchmark','integration':'auth-json','events':rows[first:first+500]})
        e.drain(6000);elapsed=time.perf_counter()-start;cpu=time.process_time()-cpu
        h=e.health('bench');assert h['normalized']==5000 and h['detector_pending']==0
        with e.connect() as c:counts={r['rule']:r['n'] for r in c.execute('SELECT rule,COUNT(*) AS n FROM alerts GROUP BY rule')}
        if advanced:
            assert counts.get('auth.failure-then-success.v1')==500,counts
            assert counts.get('auth.sliding-failures.v1')==4300,counts
        integrity=x.integrity('bench');assert integrity['unlinked_records']==0
        return dict(advanced_rules_enabled=advanced,events=5000,seconds=elapsed,eps=5000/elapsed,cpu_seconds=cpu,alerts_by_rule=counts,audit_records_verified=integrity['count'])

def workflows():
    with tempfile.TemporaryDirectory() as d:
        e=Engine(Path(d)/'db');e.activate('bench','admin','auth-json');x=Enterprise(e)
        rows=[payload(i*50) for i in range(5)]
        e.ingest('bench','collector',{'source':'benchmark','integration':'auth-json','events':rows});e.drain()
        aid=e.listing('bench','alerts')[0]['id']
        for i in range(50):
            j=x.create('bench','analyst',dict(request_key=str(i),playbook='triage-auth.v1',alert_id=aid))
            x.transition('bench','admin',dict(id=j['id'],revision=0,action='approve'))
        start=time.perf_counter();steps=0
        while x.tick():steps+=1
        elapsed=time.perf_counter()-start
        jobs=x.listing('bench');assert len(jobs)==50 and all(j['state']=='completed' for j in jobs)
        cid=json.loads(jobs[0]['result'])['case_id'];assert len(e.case_detail('bench',cid)['notes'])==50
        assert steps==150;x.integrity('bench')
        return dict(workflows=50,steps=steps,seconds=elapsed,steps_per_second=steps/elapsed,notes=50,scope='Internal transactional database actions, one shared case, no external API latency')

if __name__=='__main__':
    runs=[]
    for i in range(3):
        for enabled in (False,True):runs.append(measure(enabled))
    report={'scope':'Local Engine/SQLite FULL WAL; 5000 synthetic records, 50 entities, three runs each. Fixed rules versus fixed+sliding+sequence. Not a distributed or commercial-SIEM comparison.','runs':runs,'workflows':workflows(),'median_eps':{str(v):statistics.median(r['eps'] for r in runs if r['advanced_rules_enabled']==v) for v in (False,True)},'max_process_rss_kib':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,'code_sha256':{name:hashlib.sha256((ROOT/'nova'/name).read_bytes()).hexdigest() for name in ['enterprise.py','correlation.py','rules.py']}}
    (ROOT/'benchmarks/enterprise-results.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report,indent=2))
