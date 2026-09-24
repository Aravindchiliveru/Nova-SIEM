import unittest
import test_vendors
from nova.core import Problem

class ReconcileTests(unittest.TestCase):
    setUp=test_vendors.DefenderTests.setUp
    tearDown=test_vendors.DefenderTests.tearDown
    create=test_vendors.DefenderTests.create
    state=test_vendors.DefenderTests.state
    def uncertain(self):
        self.create();self.fail=True;self.x.tick();self.fail=False
        return self.x.listing('a')[0]
    def request(self,j):return dict(id=j['id'],revision=j['revision'],action='reconcile',operation_id='12345678-1234-1234-1234-123456789012')
    def receipt(self,j,state='Succeeded',comment=None):
        parent=self
        def read(cfg,method,path,body=None):
            parent.assertEqual(method,'GET');parent.assertIsNone(body)
            return 200,dict(id=self.request(j)['operation_id'],machineId='a'*40,type='Isolate',status=state,requestorComment=comment or 'Nova job '+j['id'])
        self.x.transport.http.request=read
    def test_verified_completed(self):
        j=self.uncertain();self.receipt(j)
        self.assertEqual(self.x.transition('a','admin',self.request(j))['state'],'completed')
        self.assertEqual(len(self.calls),1)
        with self.assertRaises(Problem):self.x.transition('a','admin',self.request(j))
    def test_wrong_job_comment_rejected(self):
        j=self.uncertain();self.receipt(j,comment='Nova job someone-else')
        with self.assertRaises(Problem):self.x.transition('a','admin',self.request(j))
        self.assertEqual(self.state(),'uncertain')
    def test_pending_resumes_poll_only(self):
        j=self.uncertain();self.receipt(j,'Pending')
        self.assertEqual(self.x.transition('a','admin',self.request(j))['state'],'ready')
        self.now+=31;self.receipt(j);self.x.tick();self.assertEqual(self.state(),'completed');self.assertEqual(len(self.calls),1)
    def test_same_requester_and_cross_tenant_rejected(self):
        j=self.uncertain();self.receipt(j)
        for tenant,actor in [('a','analyst'),('other','admin')]:
            with self.assertRaises(Problem):self.x.transition(tenant,actor,self.request(j))
    def test_provider_failure_preserves_uncertain(self):
        j=self.uncertain()
        def fail(*args):raise TimeoutError()
        self.x.transport.http.request=fail
        with self.assertRaises(Problem):self.x.transition('a','admin',self.request(j))
        self.assertEqual(self.state(),'uncertain')
    def test_stale_revision_during_provider_read_cannot_commit(self):
        j=self.uncertain();self.receipt(j);read=self.x.transport.http.request
        def race(*args):
            result=read(*args)
            with self.e.tx() as c:c.execute('UPDATE nova_external_jobs SET revision=revision+1 WHERE id=?',(j['id'],))
            return result
        self.x.transport.http.request=race
        with self.assertRaises(Problem):self.x.transition('a','admin',self.request(j))
        self.assertEqual(self.state(),'uncertain')
    def test_missing_intent_rolls_back_job_update(self):
        j=self.uncertain();self.receipt(j)
        with self.e.tx() as c:c.execute('DELETE FROM nova_vendor_operations WHERE job_id=?',(j['id'],))
        with self.assertRaises(Problem):self.x.transition('a','admin',self.request(j))
        row=self.x.listing('a')[0];self.assertEqual(row['state'],'uncertain');self.assertEqual(row['revision'],j['revision'])
