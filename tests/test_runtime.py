import hashlib
import http.client
import json
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import Mock
from nova.core import Engine,ROOT
from nova.server import Service,Server

class RuntimeTests(unittest.TestCase):
    def test_live_worker_cli_and_case_flow(self):
        with tempfile.TemporaryDirectory() as d:
            token='test-only-runtime-secret'
            tokens=Path(d)/'tokens.json';tokens.write_text(json.dumps({'admin':token}))
            svc=Service(Engine(Path(d)/'db'),[{'name':'test-admin','role':'admin','tenant':'alpha','token_sha256':hashlib.sha256(token.encode()).hexdigest()}])
            server=Server(('127.0.0.1',0),svc)
            threads=[threading.Thread(target=server.serve_forever,daemon=True),threading.Thread(target=svc.worker,daemon=True)]
            for t in threads:t.start()
            try:
                result=subprocess.run([sys.executable,str(ROOT/'tools/send_sample.py'),'--port',str(server.server_port),'--tokens',str(tokens)],capture_output=True,text=True,timeout=10)
                self.assertEqual(result.returncode,0,result.stderr)
                self.assertEqual(json.loads(result.stdout)['accepted'],5)
                deadline=time.monotonic()+5
                while time.monotonic()<deadline and not svc.engine.listing('alpha','alerts'):
                    time.sleep(.02)
                alerts=svc.engine.listing('alpha','alerts');self.assertEqual(len(alerts),1)
                conn=http.client.HTTPConnection('127.0.0.1',server.server_port)
                conn.request('POST','/api/cases',json.dumps({'alert_id':alerts[0]['id']}),{'Authorization':'Bearer '+token,'Content-Type':'application/json'})
                response=conn.getresponse();self.assertEqual(response.status,200)
                self.assertEqual(json.loads(response.read())['status'],'open');conn.close()
            finally:
                svc.stop.set();server.shutdown();server.server_close()
                for t in threads:t.join(timeout=5)
    def test_worker_retry_limit(self):
        engine=Mock();engine.drain.side_effect=RuntimeError('simulated storage outage')
        service=Service(engine,[])
        service.stop=Mock();service.stop.is_set.return_value=False
        with self.assertLogs(level='ERROR'):service.worker()
        self.assertEqual(engine.drain.call_count,5)
        self.assertTrue(service.worker_error)
        self.assertEqual(service.stop.wait.call_count,4)

if __name__=='__main__':unittest.main()
