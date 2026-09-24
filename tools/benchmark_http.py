"""Actual loopback HTTP + background worker load, with concurrent search clients."""
import concurrent.futures
import hashlib
import http.client
import json
import math
import os
import platform
import resource
import sys
import tempfile
import threading
import time
from datetime import datetime,timezone
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from nova.core import Engine
from nova.server import Service,Server

def pct(values,q):return sorted(values)[min(len(values)-1,math.ceil(len(values)*q)-1)]

def measure(events=10000):
    with tempfile.TemporaryDirectory() as d:
        engine=Engine(Path(d)/'db');engine.activate('benchmark','operator','auth-json')
        credentials=[dict(name='client'+str(i),tenant='benchmark',role='admin',token_sha256=hashlib.sha256(('synthetic-token-'+str(i)).encode()).hexdigest()) for i in range(6)]
        service=Service(engine,credentials);server=Server(('127.0.0.1',0),service)
        threads=[threading.Thread(target=server.serve_forever,daemon=True),threading.Thread(target=service.worker,daemon=True)]
        for t in threads:t.start()
        query_stop=threading.Event();query_times=[];query_errors=[];accepted_batches=[]
        def call(index,path,body=None):
            conn=http.client.HTTPConnection('127.0.0.1',server.server_port,timeout=15)
            try:
                conn.request('POST' if body else 'GET',path,json.dumps(body) if body else None,{'Authorization':'Bearer synthetic-token-'+str(index),'Content-Type':'application/json'})
                response=conn.getresponse();data=json.loads(response.read())
                if response.status!=200:raise RuntimeError(str((response.status,data)))
                return data
            finally:conn.close()
        def searcher(index):
            while not query_stop.is_set():
                start=time.perf_counter()
                try:call(index,'/api/search?q=Synthetic&limit=100');query_times.append(time.perf_counter()-start)
                except Exception as ex:query_errors.append(str(ex))
                query_stop.wait(.025)
        base=datetime.fromtimestamp(int(time.time()//300)*300+60,timezone.utc).isoformat()
        def producer(index):
            for first in range(index*100,events,400):
                rows=[dict(id=str(i),data=dict(timestamp=base,user='user'+str(i%100),src_ip='192.0.2.1',status='failure' if i%5==0 else 'success',message='Synthetic HTTP mixed workload '+('x'*128))) for i in range(first,min(first+100,events))]
                body=dict(source='http-benchmark',integration='auth-json',events=rows)
                start=time.perf_counter();result=call(index,'/api/events',body)
                assert result['accepted']==len(rows),result
                accepted_batches.append(time.perf_counter()-start)
        readers=[threading.Thread(target=searcher,args=(i,),daemon=True) for i in (4,5)]
        cpu=time.process_time();start=time.perf_counter()
        for reader in readers:reader.start()
        try:
            with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:list(pool.map(producer,range(4)))
            ingress_end=time.perf_counter()
            deadline=time.monotonic()+120
            while time.monotonic()<deadline:
                h=engine.health('benchmark')
                if h['raw_events']==h['normalized']==events and not h['normalizer_pending'] and not h['detector_pending']:break
                time.sleep(.02)
            else:raise AssertionError('processing deadline exceeded')
            end=time.perf_counter();cpu=time.process_time()-cpu
            query_stop.set()
            for reader in readers:reader.join(20)
            assert not query_errors,query_errors
            with engine.connect() as c:
                delays=[r[0]*1000 for r in c.execute('SELECT normalized_at-received FROM normalized')]
                counts={table:c.execute('SELECT COUNT(*) FROM '+table).fetchone()[0] for table in ['raw_events','normalized','quarantine','alerts']}
                assert c.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
            assert counts['raw_events']==counts['normalized']==events and counts['quarantine']==0
            return dict(scope='Single-host real loopback HTTP, SQLite FULL WAL, four producers, two concurrent search clients; not distributed sizing',events=events,producer_threads=4,search_threads=2,ingress_seconds=ingress_end-start,complete_seconds=end-start,completed_eps=events/(end-start),cpu_seconds=cpu,max_rss_kib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,ingest_batch_p95_ms=pct(accepted_batches,.95)*1000,search_requests=len(query_times),search_p50_ms=pct(query_times,.50)*1000,search_p95_ms=pct(query_times,.95)*1000,search_p99_ms=pct(query_times,.99)*1000,receive_to_normalize_p50_ms=pct(delays,.50),receive_to_normalize_p95_ms=pct(delays,.95),receive_to_normalize_p99_ms=pct(delays,.99),counts=counts,worker_error=service.worker_error,python=platform.python_version())
        finally:
            query_stop.set();service.stop.set();server.shutdown();server.server_close()
            for t in threads+readers:t.join(20)

if __name__=='__main__':
    runs=[measure() for _ in range(3)]
    output=Path(__file__).resolve().parents[1]/'benchmarks/http-results.json';output.write_text(json.dumps(runs,indent=2)+'\n');print(json.dumps(runs,indent=2))
