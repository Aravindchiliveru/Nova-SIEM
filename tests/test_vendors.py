import json,tempfile,unittest
from pathlib import Path
from nova.core import Engine,Problem
from nova.enterprise import Enterprise
from nova.soar import External,configuration
from nova.vendors import Router
from test_core import batch,event

class DefenderTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.e=Engine(Path(self.tmp.name)/'db');self.e.activate('a','admin','auth-json');self.e.ingest('a','c',batch([event(i) for i in range(5)]));self.e.drain()
        self.aid=self.e.listing('a','alerts')[0]['id'];self.now=1000.;self.calls=[];self.status='Pending';self.fail=False;self.wrong=False
        self.cfg={'mde':dict(kind='defender',url='https://api.security.microsoft.com',token_file='/run/secrets/mde',tenants=['a'],assets={'a':['a'*40]})};parent=self
        class HTTP:
            def request(self,cfg,method,path,body=None):
                parent.calls.append((method,path,body))
                if parent.fail:raise TimeoutError()
                return (201 if method=='POST' else 200),dict(id='12345678-1234-1234-1234-123456789012',machineId='b'*40 if parent.wrong else 'a'*40,type='Isolate',status=parent.status)
        en=Enterprise(self.e);self.x=External(en,self.cfg,Router(en,HTTP()),lambda:self.now)
    def tearDown(self):self.tmp.cleanup()
    def create(self,machine='a'*40):
        j=self.x.create('a','analyst',dict(request_key='r1',connector='mde',alert_id=self.aid,parameters=dict(action='isolate',machine_id=machine)))
        return self.x.transition('a','admin',dict(id=j['id'],revision=j['revision'],action='approve'))
    def state(self):return self.x.listing('a')[0]['state']
    def test_async_poll_completion_without_repost(self):
        self.create();self.x.tick();self.assertEqual(self.state(),'ready');self.assertEqual(self.x.tick(),0)
        self.now+=31;self.status='Succeeded';self.x.tick();self.assertEqual(self.state(),'completed')
        self.assertEqual([c[0] for c in self.calls],['POST','GET'])
    def test_ambiguous_submission_never_retries(self):
        self.create();self.fail=True;self.x.tick();self.assertEqual(self.state(),'uncertain')
        self.now+=1000;self.x.tick();self.assertEqual(len(self.calls),1)
    def test_crash_after_intent_stops_before_network(self):
        j=self.create()
        from nova.core import canonical
        import hashlib
        digest=hashlib.sha256(canonical([self.cfg['mde'],json.loads(j['payload'])]).encode()).hexdigest()
        with self.e.tx() as c:c.execute("INSERT INTO nova_vendor_operations VALUES(?,?,?,'submitting',NULL,'{}')",(j['id'],'a',digest))
        self.x.tick();self.assertEqual(self.state(),'uncertain');self.assertEqual(self.calls,[])
    def test_poll_timeout_does_not_repost(self):
        self.create();self.x.tick();self.now+=31;self.fail=True;self.x.tick();self.assertEqual(self.state(),'ready')
        self.now+=31;self.fail=False;self.status='Succeeded';self.x.tick();self.assertEqual(self.state(),'completed');self.assertEqual([c[0] for c in self.calls],['POST','GET','GET'])
    def test_machine_binding_enforced_before_approval(self):
        with self.assertRaises(Problem):self.create('b'*40)
        self.assertEqual(self.calls,[])
    def test_foreign_provider_receipt_not_success(self):
        self.create();self.wrong=True;self.status='Succeeded';self.x.tick();self.assertEqual(self.state(),'uncertain')
    def test_provider_failure_is_terminal(self):
        self.create();self.status='Failed';self.x.tick();self.assertEqual(self.state(),'failed')
    def test_url_cannot_redirect_credentials(self):
        self.cfg['mde']['url']='https://attacker.example'
        with self.assertRaises(Problem):configuration(self.cfg)
    def test_more_than_five_polls_supported(self):
        self.create()
        for _ in range(7):self.x.tick();self.now+=31
        self.status='Succeeded';self.x.tick();self.assertEqual(self.state(),'completed');self.assertEqual(sum(c[0]=='POST' for c in self.calls),1)

    def test_actual_sigkill_after_provider_effect_never_reposts(self):
        import subprocess,sys,signal
        self.create();root=Path(self.tmp.name)
        (root/'cfg.json').write_text(json.dumps(self.cfg))
        code="""
import json,os,signal,sys
from pathlib import Path
from nova.core import Engine
from nova.enterprise import Enterprise
from nova.soar import External
from nova.vendors import Router
root=Path(sys.argv[1]);en=Enterprise(Engine(root/'db'))
class HTTP:
    def request(self,*args):
        with open(root/'effect','ab') as f:f.write(b'1');f.flush();os.fsync(f.fileno())
        os.kill(os.getpid(),signal.SIGKILL)
External(en,json.loads((root/'cfg.json').read_text()),Router(en,HTTP()),lambda:1000).tick()
"""
        child=subprocess.run([sys.executable,'-c',code,str(root)],capture_output=True,timeout=20)
        self.assertEqual(child.returncode,-signal.SIGKILL,child.stderr)
        self.assertEqual(self.state(),'running');self.now=1061;self.x.tick()
        self.assertEqual(self.state(),'uncertain');self.assertEqual((root/'effect').read_bytes(),b'1');self.assertEqual(self.calls,[])
