import tempfile,unittest
from pathlib import Path
from nova.core import Engine,Problem
from nova.enterprise import Enterprise
from nova.soar import External,Permanent,configuration
from test_core import batch,event

class SoarTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.e=Engine(Path(self.tmp.name)/'db');self.e.activate('a','admin','auth-json');self.e.ingest('a','c',batch([event(i) for i in range(5)]));self.e.drain()
        self.aid=self.e.listing('a','alerts')[0]['id'];self.now=1000.;self.sent=[];parent=self
        class Transport:
            def send(self,cfg,key,payload):parent.sent.append((key,payload))
        self.cfg={'response':dict(url='https://response.example/actions',token_file='/run/secrets/token',tenants=['a'])}
        self.x=External(Enterprise(self.e),self.cfg,Transport(),lambda:self.now)
    def tearDown(self):self.tmp.cleanup()
    def create(self):return self.x.create('a','analyst',dict(request_key='request1',connector='response',alert_id=self.aid,parameters={'action':'isolate','asset':'endpoint1'}))
    def approve(self,j):return self.x.transition('a','admin',dict(id=j['id'],revision=j['revision'],action='approve'))
    def test_approval_and_tenant_boundaries(self):
        j=self.create();self.assertEqual(self.x.tick(),0)
        with self.assertRaises(Problem):self.x.transition('a','analyst',dict(id=j['id'],revision=0,action='approve'))
        self.assertEqual(self.x.listing('b'),[]);self.assertEqual(self.x.catalog('b'),[])
        self.approve(j);self.x.tick();self.assertEqual(self.x.listing('a')[0]['state'],'completed');self.assertEqual(self.sent[0][1]['tenant'],'a')
    def test_request_idempotency_and_stale_approval(self):
        j=self.create();self.assertEqual(self.create()['id'],j['id']);self.approve(j)
        with self.assertRaises(Problem):self.approve(j)
    def test_retry_preserves_key_and_backoff(self):
        class Fail:
            def send(self,*args):raise TimeoutError()
        self.approve(self.create());original=self.x.transport;self.x.transport=Fail();self.x.tick()
        j=self.x.listing('a')[0];self.assertEqual(j['state'],'ready');self.assertEqual(self.x.tick(),0)
        self.now+=3;self.x.transport=original;self.x.tick();self.assertEqual(self.sent[0][0],j['id'])
    def test_crash_lease_reclaim_and_attempt_limit(self):
        j=self.approve(self.create())
        with self.e.tx() as c:c.execute("UPDATE nova_external_jobs SET state='running',lease='dead',lease_until=1010,attempts=1")
        self.assertEqual(self.x.tick(),0);self.now=1011;self.x.tick();self.assertEqual(self.x.listing('a')[0]['state'],'completed')
    def test_configuration_change_cannot_redirect_approved_action(self):
        self.approve(self.create());self.cfg['response']['url']='https://other.example/actions';self.x.tick()
        self.assertEqual(self.x.listing('a')[0]['state'],'failed');self.assertEqual(self.sent,[])
    def test_lease_fences_stale_completion(self):
        parent=self
        class Reclaim:
            def send(self,*args):
                with parent.e.tx() as c:c.execute("UPDATE nova_external_jobs SET lease='new-worker'")
        self.approve(self.create());self.x.transport=Reclaim();self.x.tick();self.assertEqual(self.x.listing('a')[0]['state'],'running')
    def test_retry_budget_exhausted(self):
        self.approve(self.create())
        with self.e.tx() as c:c.execute('UPDATE nova_external_jobs SET attempts=5')
        self.x.tick();self.assertEqual(self.x.listing('a')[0]['state'],'failed');self.assertEqual(self.sent,[])
    def test_fixed_https_configuration(self):
        for url in ['http://response.example','https://user:password@response.example','https://response.example/?token=secret']:
            cfg={'x':dict(url=url,token_file='/token',tenants=['a'])}
            with self.assertRaises(Problem):configuration(cfg)
