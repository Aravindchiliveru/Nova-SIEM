import hashlib
import http.client
import json
import tempfile
import threading
import unittest
from pathlib import Path
from nova.core import Engine
from nova.server import Service,Server
from test_core import batch

class APITests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.e=Engine(Path(self.temp.name)/'db')
        creds=[dict(name=role,tenant=tenant,role=role,token_sha256=hashlib.sha256(token.encode()).hexdigest()) for token,tenant,role in [('alpha-admin','alpha','admin'),('beta-admin','beta','admin'),('collector','alpha','collector'),('viewer','alpha','viewer')]]
        self.s=Server(('127.0.0.1',0),Service(self.e,creds))
        self.thread=threading.Thread(target=self.s.serve_forever,daemon=True);self.thread.start()
    def tearDown(self):
        self.s.shutdown();self.s.server_close();self.thread.join();self.temp.cleanup()
    def call(self,path,token='alpha-admin',body=None,raw=None,headers=None):
        c=http.client.HTTPConnection('127.0.0.1',self.s.server_port)
        h={'Authorization':'Bearer '+token,'Content-Type':'application/json'}
        h.update(headers or {})
        data=raw if raw is not None else json.dumps(body) if body is not None else None
        c.request('POST' if data is not None else 'GET',path,body=data,headers=h)
        r=c.getresponse();status=r.status;data=r.read();c.close();return status,data
    def test_source_bound_collector(self):
        for credential in self.s.service.credentials:
            if credential['role']=='collector':credential['sources']=['allowed-source']
        self.assertEqual(self.call('/api/events',token='collector',body=batch())[0],403)
    def test_distributed_worker_error_reaches_metrics(self):
        original=self.e.health
        self.e.health=lambda tenant:dict(original(tenant),worker_error=True)
        status,data=self.call('/metrics')
        self.assertEqual(status,200);self.assertIn(b'nova_worker_error 1',data)
    def test_auth_required(self):
        self.assertEqual(self.call('/api/health',token='wrong')[0],401)
    def test_collector_cannot_search(self):
        self.assertEqual(self.call('/api/search',token='collector')[0],403)
    def test_viewer_cannot_activate(self):
        self.assertEqual(self.call('/api/integrations/activate',token='viewer',body={'package':'auth-json'})[0],403)
    def test_payload_cannot_override_tenant(self):
        b=batch();b['tenant']='beta'
        self.assertEqual(self.call('/api/events',body=b)[0],400)
    def test_api_flow_and_isolation(self):
        self.assertEqual(self.call('/api/integrations/activate',body={'package':'auth-json'})[0],200)
        self.assertEqual(self.call('/api/events',token='collector',body=batch())[0],200)
        self.e.drain()
        self.assertEqual(len(json.loads(self.call('/api/search')[1])),1)
        self.assertEqual(json.loads(self.call('/api/search',token='beta-admin')[1]),[])
    def test_typed_http_ingestion_search_and_isolation(self):
        self.assertEqual(self.call('/api/integrations/activate',body={'package':'file-json'})[0],200)
        data=dict(timestamp='2026-09-21T12:00:00Z',action='read',target='/etc/passwd',message='read',host='endpoint')
        body=dict(source='endpoint',integration='file-json',events=[dict(id='file1',data=data)])
        self.assertEqual(self.call('/api/events',token='collector',body=body)[0],200)
        self.e.drain()
        status,data=self.call('/api/search?category=file&action=read&host=endpoint&target=%2Fetc%2Fpasswd')
        self.assertEqual(status,200);self.assertEqual(json.loads(data)[0]['outcome'],'unknown')
        self.assertEqual(json.loads(self.call('/api/search?category=file',token='beta-admin')[1]),[])
    def test_duplicate_json_keys_rejected(self):
        self.assertEqual(self.call('/api/events',raw='{"source":"a","source":"b"}')[0],400)
    def test_nonfinite_json_rejected(self):
        self.assertEqual(self.call('/api/events',raw='{"source":NaN}')[0],400)
    def test_duplicate_query_parameters_rejected(self):
        self.assertEqual(self.call('/api/search?limit=1&limit=2')[0],400)
    def test_cross_origin_denied(self):
        self.assertEqual(self.call('/api/health',headers={'Origin':'https://evil.example'})[0],403)
    def test_dns_rebinding_host_denied(self):
        self.assertEqual(self.call('/api/health',headers={'Host':'evil.example'})[0],403)
    def test_invalid_action_input(self):
        self.assertEqual(self.call('/api/integrations/activate',body={'package':[]})[0],400)
    def test_metrics_require_identity(self):
        self.assertEqual(self.call('/metrics',token='invalid')[0],401)
        status,data=self.call('/metrics')
        self.assertEqual(status,200);self.assertIn(b'nova_raw_events 0',data)
    def test_traversal_not_served(self):
        self.assertEqual(self.call('/../nova/core.py')[0],404)
    def test_wrong_content_type(self):
        self.assertEqual(self.call('/api/events',body=batch(),headers={'Content-Type':'text/plain'})[0],415)
    def test_oversized_request(self):
        # Server can reject headers before the client finishes transmitting a large body.
        c=http.client.HTTPConnection('127.0.0.1',self.s.server_port)
        try:
            c.putrequest('POST','/api/events')
            c.putheader('Authorization','Bearer alpha-admin')
            c.putheader('Content-Type','application/json')
            c.putheader('Content-Length','1048577')
            c.endheaders()
            response=c.getresponse();self.assertEqual(response.status,413);response.read()
        finally:c.close()

    def test_rule_catalog_and_simulation_permissions(self):
        status,data=self.call('/api/rules',token='viewer');self.assertEqual(status,200);self.assertEqual(len(json.loads(data)),9)
        self.assertEqual(self.call('/api/rules/simulate',token='viewer',body={'rule':{},'events':[]})[0],403)
    def test_invalid_rule_input_is_client_error(self):
        self.assertEqual(self.call('/api/rules/simulate',body={'rule':{},'events':[]})[0],400)
    def test_case_update_permissions(self):
        self.assertEqual(self.call('/api/cases/update',token='viewer',body={'id':1,'status':'closed'})[0],403)
    def test_server_connection_limit(self):
        for _ in range(32):self.s.slots.acquire()
        try:self.assertEqual(self.call('/api/health')[0],503)
        finally:
            for _ in range(32):self.s.slots.release()

if __name__=='__main__': unittest.main()
