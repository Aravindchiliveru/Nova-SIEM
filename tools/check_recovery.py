"""Real process-kill recovery checks against temporary local databases only."""
import json
import os
import signal
import subprocess
import sys
import tempfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from nova.core import Engine

def run():
    with tempfile.TemporaryDirectory() as d:
        db=Path(d)/'db'
        code='''import os,signal,sys
from nova.core import Engine
engine=Engine(sys.argv[1]);engine.activate('recovery','admin','auth-json')
rows=[{'id':str(i),'data':{'timestamp':'2026-09-17T12:01:00Z','user':'alice','src_ip':'192.0.2.1','status':'failure','message':'Synthetic recovery'}} for i in range(500)]
result=engine.ingest('recovery','collector',{'source':'test','integration':'auth-json','events':rows})
print(result['accepted'],flush=True)
os.kill(os.getpid(),signal.SIGKILL)
'''
        child=subprocess.run([sys.executable,'-c',code,str(db)],cwd=ROOT,capture_output=True,text=True,timeout=20)
        assert child.returncode==-signal.SIGKILL and child.stdout.strip()=='500',(child.returncode,child.stderr)
        e=Engine(db);e.drain(1000)
        assert e.health('recovery')['normalized']==500
        assert len(e.listing('recovery','alerts'))==1
        code='''import os,signal,sys
from nova.core import Engine
engine=Engine(sys.argv[1])
with engine.tx() as c:
 c.execute('DELETE FROM normalized')
 os.kill(os.getpid(),signal.SIGKILL)
'''
        child=subprocess.run([sys.executable,'-c',code,str(db)],cwd=ROOT,capture_output=True,text=True,timeout=20)
        assert child.returncode==-signal.SIGKILL,(child.returncode,child.stderr)
        e=Engine(db);assert e.health('recovery')['normalized']==500
        with e.connect() as c:assert c.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
        return {'accepted_before_kill':500,'normalized_after_restart':500,'alerts':1,'uncommitted_transaction_rolled_back':True,'integrity':'ok','scope':'process SIGKILL only; not power loss, disk failure, or distributed broker recovery'}

if __name__=='__main__':print(json.dumps(run(),indent=2))
