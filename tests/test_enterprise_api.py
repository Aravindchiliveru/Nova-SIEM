import hashlib
import http.client
import json
import tempfile
import threading
import unittest
from pathlib import Path
from nova.core import Engine
from nova.server import Service,Server
from test_core import event,batch

class EnterpriseAPITests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.e=Engine(Path(self.temp.name)/'db')
        self.e.activate('alpha','admin','auth-json');self.e.ingest('alpha','collector',batch([event(i) for i in range(5)]));self.e.drain()
        self.aid=self.e.listing('alpha','alerts')[0]['id']
        roles=[('admin','alpha','admin'),('analyst','alpha','analyst'),('viewer','alpha','viewer'),('other','beta','admin')]
        svc=Service(self.e,[dict(name=n,tenant=t,role=r,token_sha256=hashlib.sha256(n.encode()).hexdigest()) for n,t,r in roles])
        self.s=Server(('127.0.0.1',0),svc);self.thread=threading.Thread(target=self.s.serve_forever,daemon=True);self.thread.start()
    def tearDown(self):self.s.shutdown();self.s.server_close();self.thread.join();self.temp.cleanup()
    def call(self,path,body=None,token='admin'):
        c=http.client.HTTPConnection('127.0.0.1',self.s.server_port,timeout=10)
        try:
            c.request('POST' if body is not None else 'GET',path,json.dumps(body) if body is not None else None,{'Authorization':'Bearer '+token,'Content-Type':'application/json'})
            r=c.getresponse();return r.status,json.loads(r.read())
        finally:c.close()
    def create(self):return self.call('/api/workflows',dict(request_key='test',playbook='triage-auth.v1',alert_id=self.aid),'analyst')
    def test_real_http_approval_run_export(self):
        status,j=self.create();self.assertEqual(status,200)
        status,j=self.call('/api/workflows/transition',dict(id=j['id'],revision=j['revision'],action='approve'));self.assertEqual(status,200)
        for _ in range(3):self.s.service.enterprise.tick()
        status,jobs=self.call('/api/workflows');self.assertEqual(jobs[0]['state'],'completed')
        cid=json.loads(jobs[0]['result'])['case_id'];status,bundle=self.call('/api/evidence/export',{'case_id':cid},'analyst')
        self.assertEqual(status,200);self.assertEqual(len(bundle['payload']['events']),5)
    def test_analyst_cannot_approve(self):
        _,j=self.create();self.assertEqual(self.call('/api/workflows/transition',dict(id=j['id'],revision=0,action='approve'),'analyst')[0],403)
    def test_viewer_cannot_request_workflow(self):self.assertEqual(self.call('/api/workflows',dict(request_key='test',playbook='triage-auth.v1',alert_id=self.aid),'viewer')[0],403)
    def test_workflow_tenant_isolation(self):
        self.create();self.assertEqual(self.call('/api/workflows',token='other')[1],[])
    def test_checkpoint_round_trip(self):
        status,anchor=self.call('/api/audit/checkpoint');self.assertEqual(status,200)
        self.create();status,result=self.call('/api/audit/verify',{'anchor':anchor});self.assertEqual(status,200);self.assertTrue(result['external_anchor_checked'])
    def test_metrics_include_workflows(self):
        self.create();_,h=self.call('/api/health');self.assertEqual(h['workflow_awaiting_approval'],1)
    def test_viewer_cannot_configure_rule(self):
        _,rules=self.call('/api/rules');r=rules[0]
        self.assertEqual(self.call('/api/rules/configure',dict(id=r['id'],enabled=False,revision=r['revision']),'viewer')[0],403)
    def test_integration_preview_api(self):
        status,result=self.call('/api/integrations/test',{'package':'auth-json','events':[event()['data']]})
        self.assertEqual(status,200);self.assertFalse(result['persisted'])

    def test_external_api_approval_and_permissions(self):
        self.s.service.external.connectors={'response':dict(url='https://example.invalid/actions',token_file='/unused',tenants=['alpha'])}
        status,j=self.call('/api/external',dict(request_key='api-test',connector='response',alert_id=self.aid,parameters={}),token='analyst')
        self.assertEqual(status,200)
        self.assertEqual(self.call('/api/external/transition',dict(id=j['id'],revision=0,action='approve'),token='analyst')[0],403)
        self.assertEqual(self.call('/api/external/transition',dict(id=j['id'],revision=0,action='approve'))[0],200)
        self.assertEqual(self.call('/api/external',token='other')[1],[])
        self.assertEqual(self.call('/api/connectors',token='other')[1],[])
    def test_ocsf_export_api(self):
        row=self.e.search('alpha',{})[0]
        status,out=self.call('/api/event/ocsf?id='+row['event_id'])
        self.assertEqual(status,200);self.assertEqual(out['type_uid'],300201)
        self.assertEqual(self.call('/api/event/ocsf?id='+row['event_id'],token='other')[0],404)

if __name__=='__main__':unittest.main()
