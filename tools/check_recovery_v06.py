"""Actual local SIGKILL, activity redelivery and isolated snapshot restore drill."""
import hashlib,json,signal,sqlite3,subprocess,sys,tempfile,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from nova.core import Engine
from nova.enterprise import Enterprise
from nova.soar import External
from nova.operations import backup,restore
from check_recovery import run as ingress_recovery

def run():
    ingress=ingress_recovery()
    with tempfile.TemporaryDirectory() as d:
        path=Path(d);db=path/'db';remote=path/'provider';e=Engine(db)
        e.activate('a','admin','auth-json')
        e.ingest('a','c',dict(source='test',integration='auth-json',events=[dict(id=str(i),data=dict(timestamp='2026-09-21T12:00:00Z',user='alice',src_ip='192.0.2.1',status='failure',message='test')) for i in range(5)]));e.drain()
        cfg={'response':dict(url='https://example.invalid/action',token_file='/unused',tenants=['a'])};x=External(Enterprise(e),cfg)
        j=x.create('a','analyst',dict(request_key='drill',connector='response',alert_id=e.listing('a','alerts')[0]['id'],parameters={'action':'local-drill'}));x.transition('a','admin',dict(id=j['id'],revision=0,action='approve'))
        code='''import json,os,signal,sqlite3,sys,time
from nova.core import Engine
from nova.enterprise import Enterprise
from nova.soar import External
class Endpoint:
 def send(self,cfg,key,payload):
  c=sqlite3.connect(sys.argv[2]);c.execute('PRAGMA synchronous=FULL');c.execute('CREATE TABLE IF NOT EXISTS effects(id TEXT PRIMARY KEY)');c.execute('INSERT OR IGNORE INTO effects VALUES(?)',(key,));c.commit();c.close()
  if sys.argv[3]=='kill':os.kill(os.getpid(),signal.SIGKILL)
x=External(Enterprise(Engine(sys.argv[1])),json.loads(sys.argv[4]),Endpoint(),lambda:time.time()+(61 if sys.argv[3]=='recover' else 0))
x.tick()
'''
        args=[sys.executable,'-c',code,str(db),str(remote)]
        killed=subprocess.run(args+['kill',json.dumps(cfg)],cwd=ROOT,capture_output=True,text=True,timeout=20)
        assert killed.returncode==-signal.SIGKILL,killed.stderr
        assert x.listing('a')[0]['state']=='running'
        started=time.perf_counter();resumed=subprocess.run(args+['recover',json.dumps(cfg)],cwd=ROOT,capture_output=True,text=True,timeout=20);assert resumed.returncode==0,resumed.stderr
        assert x.listing('a')[0]['state']=='completed'
        with sqlite3.connect(remote) as c:assert c.execute('SELECT COUNT(*) FROM effects').fetchone()[0]==1
        checkpoint=x.e.integrity('a');backup(db,path/'snapshot');restore(path/'snapshot',path/'restored');restored=Engine(path/'restored')
        assert Enterprise(restored).integrity('a',checkpoint)['external_anchor_checked']
        assert restored.health('a')['normalized']==5
        with restored.connect() as c:assert c.execute("SELECT COUNT(*) FROM nova_external_jobs WHERE state='completed'").fetchone()[0]==1
        return dict(ingress=ingress,external_action=dict(real_sigkill=True,provider_effects=1,attempts=x.listing('a')[0]['attempts'],recovered_state='completed',lease_clock_advanced_seconds=61,scope='Local durable provider simulator; idempotency honored. No real containment vendor.'),restore=dict(normalized=5,completed_external_jobs=1,audit_checkpoint_verified=True,scope='SQLite-only isolated snapshot restore'),recovery_and_restore_seconds=time.perf_counter()-started,production_ha_dr_proven=False)
if __name__=='__main__':
    result=run();(ROOT/'benchmarks/recovery-v0.6.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result,indent=2))
