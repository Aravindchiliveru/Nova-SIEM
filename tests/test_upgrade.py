import base64
import copy
import hashlib
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock,patch
from nova.core import Engine,Problem,ROOT
from nova.rules import Rules,validate
from nova.collector import Spool,adapt
from nova.packages import keygen,sign,verify
from test_core import event,batch

class UpgradeTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.dir=Path(self.temp.name)
        self.e=Engine(self.dir/'db');self.e.activate('alpha','admin','auth-json')
    def tearDown(self):self.temp.cleanup()
    def put(self,events,tenant='alpha'):
        self.e.ingest(tenant,'collector',batch(events));self.e.drain(2000)
    def test_password_spray(self):
        self.put([event(i,user='person'+str(i)) for i in range(10)])
        self.assertEqual([r['rule'] for r in self.e.listing('alpha','alerts')],['auth.password-spray.v1'])
    def test_spray_counts_distinct_people(self):
        self.put([event(i,user='one') for i in range(10)])
        self.assertNotIn('auth.password-spray.v1',[r['rule'] for r in self.e.listing('alpha','alerts')])
    def test_distributed_guessing(self):
        self.put([event(i,src_ip='192.0.2.'+str(i+1)) for i in range(5)])
        self.assertEqual(self.e.listing('alpha','alerts')[0]['rule'],'auth.distributed-guessing.v1')
    def test_privileged_success(self):
        self.put([event(user='root',status='success')])
        self.assertEqual(self.e.listing('alpha','alerts')[0]['rule'],'auth.privileged-login.v1')
    def test_rule_hits_are_idempotent(self):
        self.put([event(i) for i in range(10)])
        with self.e.tx() as c:c.execute("DELETE FROM processed WHERE consumer='detector'")
        self.e.drain()
        with self.e.connect() as c:
            self.assertEqual(c.execute('SELECT COUNT(*) FROM rule_hits').fetchone()[0],30)
        self.assertEqual(len(json.loads(self.e.listing('alpha','alerts')[0]['evidence'])),10)
    def test_evidence_is_bounded(self):
        self.put([event(i) for i in range(500)])
        self.assertEqual(len(json.loads(self.e.listing('alpha','alerts')[0]['evidence'])),100)
    def test_invalid_record_does_not_block_batch(self):
        self.put([event(1),event(2,src_ip='bad'),event(3)])
        h=self.e.health('alpha');self.assertEqual(h['normalized'],2);self.assertEqual(h['quarantine'],1)
    def test_batch_respects_limit(self):
        self.e.ingest('alpha','collector',batch([event(i) for i in range(9)]))
        self.assertEqual(self.e.normalize_batch(3),3)
        self.assertEqual(self.e.detect_batch(2),2)
        self.assertEqual(self.e.health('alpha')['normalizer_pending'],6)
    def test_failed_rule_transaction_rolls_back_progress(self):
        self.e.ingest('alpha','collector',batch([event(i) for i in range(5)]));self.e.normalize_batch()
        original=self.e.rules.evaluate
        def fail(c,events):original(c,events);raise RuntimeError('fault after alert write')
        with patch.object(self.e.rules,'evaluate',side_effect=fail):
            with self.assertRaises(RuntimeError):self.e.detect_batch()
        self.assertEqual(self.e.health('alpha')['detector_pending'],5)
        self.assertEqual(self.e.listing('alpha','alerts'),[])
        self.e.drain();self.assertEqual(len(self.e.listing('alpha','alerts')),1)
    def test_rule_tenant_isolation(self):
        self.e.activate('beta','admin','auth-json')
        self.put([event(i,user='u'+str(i)) for i in range(5)])
        self.put([event(i,user='u'+str(i+5)) for i in range(5)],'beta')
        self.assertFalse(self.e.listing('alpha','alerts'));self.assertFalse(self.e.listing('beta','alerts'))
    def test_rule_invalid_operator_rejected(self):
        r=copy.deepcopy(self.e.rules.rules[0]);r.pop('revision');r.pop('signature_status');r['match']={'actor':{'regex':'.*'}}
        with self.assertRaises(Problem):validate(r)
    def test_simulation_does_not_write(self):
        r=json.loads((ROOT/'rules/auth.failures.v1.json').read_text())
        records=[dict(source='s',actor='a',ip='192.0.2.1',outcome='failure',message='x',event_time=0) for _ in range(5)]
        self.assertTrue(Rules.simulate(r,records)['groups'][0]['alert'])
        self.assertEqual(self.e.health('alpha')['raw_events'],0)
    def test_simulation_nan_rejected(self):
        r=json.loads((ROOT/'rules/auth.failures.v1.json').read_text())
        with self.assertRaises(Problem):Rules.simulate(r,[dict(source='s',actor='a',ip='i',outcome='failure',message='x',event_time=float('nan'))])
    def make_case(self):
        self.put([event(i) for i in range(5)]);aid=self.e.listing('alpha','alerts')[0]['id']
        return self.e.create_case('alpha','analyst',aid)['id']
    def test_case_status_and_notes(self):
        cid=self.make_case();self.e.update_case('alpha','analyst',{'id':cid,'status':'investigating','note':'Evidence reviewed'})
        detail=self.e.case_detail('alpha',cid)
        self.assertEqual(detail['case']['status'],'investigating');self.assertEqual(detail['notes'][0]['note'],'Evidence reviewed')
    def test_cross_tenant_case_update(self):
        cid=self.make_case()
        with self.assertRaises(Problem):self.e.update_case('beta','analyst',{'id':cid,'status':'closed'})
        with self.assertRaises(Problem):self.e.case_detail('beta',cid)
    def test_invalid_case_status_is_atomic(self):
        cid=self.make_case()
        with self.assertRaises(Problem):self.e.update_case('alpha','analyst',{'id':cid,'status':'bad','note':'should not persist'})
        self.assertEqual(self.e.case_detail('alpha',cid)['notes'],[])

class CollectorTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.dir=Path(self.temp.name)
        self.file=self.dir/'input.ndjson';self.file.write_text(json.dumps(event()['data'])+'\n')
        self.s=Spool(self.dir/'spool','collector-1')
    def tearDown(self):self.s.close();self.temp.cleanup()
    def test_import_restart_keeps_cursor(self):
        self.assertEqual(self.s.import_file(self.file),1);self.s.close();self.s=Spool(self.dir/'spool','collector-1')
        self.assertEqual(self.s.import_file(self.file),0);self.assertEqual(self.s.status()[0]['records'],1)
    def test_append_is_detected(self):
        self.s.import_file(self.file)
        with self.file.open('a') as f:f.write(json.dumps(event(2)['data'])+'\n')
        self.assertEqual(self.s.import_file(self.file),1)
    def test_incomplete_line_waits(self):
        self.file.write_text('{"timestamp":');self.assertEqual(self.s.import_file(self.file),0)
    def test_invalid_json_is_retained(self):
        self.file.write_text('not json\n');self.s.import_file(self.file)
        self.assertEqual(self.s.status()[0]['state'],'quarantine')
        row=self.s.c.execute('SELECT payload FROM queue').fetchone()
        self.assertEqual(bytes.fromhex(json.loads(row['payload'])['source_bytes_hex']),b'not json\n')
    def test_capacity_does_not_advance_cursor(self):
        self.s.max_bytes=1
        with self.assertRaises(Problem):self.s.import_file(self.file)
        self.s.max_bytes=10000;self.assertEqual(self.s.import_file(self.file),1)
    def test_truncation_rejected(self):
        self.s.import_file(self.file);self.file.write_text('')
        with self.assertRaises(Problem):self.s.import_file(self.file)
    def test_prefix_mutation_rejected(self):
        self.s.import_file(self.file);self.file.write_text(self.file.read_text().replace('alice','bobby'))
        with self.assertRaises(Problem):self.s.import_file(self.file)
    def test_wrong_source_does_not_leave_spool_locked(self):
        self.s.close()
        with self.assertRaises(Problem):Spool(self.dir/'spool','wrong-source')
        self.s=Spool(self.dir/'spool','collector-1')
        self.assertEqual(self.s.import_file(self.file),1)
    def test_second_process_lock(self):
        with self.assertRaises(Problem):Spool(self.dir/'spool','collector-1')
    def test_http_failure_retains_records(self):
        self.s.import_file(self.file);opener=Mock();opener.open.side_effect=TimeoutError()
        with self.assertRaises(TimeoutError):self.s.send('http://127.0.0.1:8787','test',now=0,opener=opener)
        self.assertEqual(self.s.status()[0]['records'],1)
        self.assertEqual(self.s.send('http://127.0.0.1:8787','test',now=0,opener=opener),0)
    def test_failure_circuit_and_manual_retry(self):
        self.s.import_file(self.file);opener=Mock();opener.open.side_effect=TimeoutError()
        for i in range(8):
            with self.assertRaises(TimeoutError):self.s.send('http://127.0.0.1:8787','test',now=1000*i,opener=opener)
        self.assertEqual(self.s.status()[0]['state'],'failed');self.s.retry();self.assertEqual(self.s.status()[0]['state'],'pending')
    def test_wrong_ack_never_deletes(self):
        self.s.import_file(self.file);opener=Mock();response=opener.open.return_value.__enter__.return_value if hasattr(opener.open.return_value,'__enter__') else None
        from unittest.mock import MagicMock
        opener=MagicMock();response=opener.open.return_value.__enter__.return_value;response.status=200;response.read.return_value=b'{"accepted":1,"duplicates":0,"event_ids":["wrong"]}'
        with self.assertRaises(Problem):self.s.send('http://localhost','test',now=0,opener=opener)
        self.assertEqual(self.s.status()[0]['records'],1)
    def test_remote_plaintext_denied(self):
        with self.assertRaises(Problem):self.s.send('http://example.com','test')
    def test_valid_ack_deletes_only_confirmed(self):
        from unittest.mock import MagicMock
        self.s.import_file(self.file);row=self.s.c.execute('SELECT id FROM queue').fetchone()
        eid=hashlib.sha256(json.dumps(['collector-1',row['id']],separators=(',',':')).encode()).hexdigest()
        opener=MagicMock();response=opener.open.return_value.__enter__.return_value;response.status=200
        response.read.return_value=json.dumps({'accepted':1,'duplicates':0,'event_ids':[eid]}).encode()
        self.assertEqual(self.s.send('http://localhost','test',opener=opener),1);self.assertEqual(self.s.status(),[])
    def test_windows_adapter(self):
        n=adapt('windows-security-json',dict(event_id=4625,timestamp='2026-09-17T12:00:00Z',TargetUserName='alice',IpAddress='192.0.2.1'))
        self.assertEqual(n['status'],'failure');self.assertIn('original',n)
    def test_unsupported_windows_event(self):
        with self.assertRaises(Problem):adapt('windows-security-json',{'event_id':4688})
    def test_cloudtrail_adapter(self):
        n=adapt('cloudtrail-console-json',dict(eventTime='2026-09-17T12:00:00Z',eventSource='signin.amazonaws.com',eventName='ConsoleLogin',userIdentity={'userName':'alice'},sourceIPAddress='192.0.2.1',responseElements={'ConsoleLogin':'Failure'}))
        self.assertEqual(n['status'],'failure')
    def test_openssh_adapter(self):
        n=adapt('openssh-json',dict(timestamp='2026-09-17T12:00:00Z',message='sshd[123]: Failed password for invalid user alice from 2001:db8::1 port 2222 ssh2'))
        self.assertEqual(n['src_ip'],'2001:db8::1');self.assertEqual(n['user'],'alice')
    def test_ssh_timestamp_required(self):
        with self.assertRaises(Problem):adapt('openssh-json',dict(message='Failed password for alice from 192.0.2.1 port 22 ssh2'))

class SignatureTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.dir=Path(self.temp.name)
        self.key=self.dir/'private.pem';self.trust=self.dir/'trust.json';self.package=self.dir/'demo.json';self.package.write_text('{"a":1}')
        keygen(self.key,self.trust,'test')
    def tearDown(self):self.temp.cleanup()
    def test_valid_signature(self):
        sign(self.package,self.key,'test');self.assertEqual(verify(self.package,trust_path=self.trust,required=True),'verified')
    def test_tamper_rejected(self):
        sign(self.package,self.key,'test');self.package.write_text('{"a":2}')
        with self.assertRaises(Problem):verify(self.package,trust_path=self.trust,required=True)
    def test_missing_required_signature(self):
        with self.assertRaises(Problem):verify(self.package,trust_path=self.trust,required=True)
    def test_unknown_key_rejected(self):
        sign(self.package,self.key,'other')
        with self.assertRaises(Problem):verify(self.package,trust_path=self.trust,required=True)
    def test_unsigned_development_explicit(self):self.assertEqual(verify(self.package,required=False),'unsigned-development')
    def test_keys_not_overwritten(self):
        with self.assertRaises(Problem):keygen(self.key,self.trust,'test')
    def test_unsigned_startup_fails_in_required_mode(self):
        with patch.dict(os.environ,{'NOVA_REQUIRE_SIGNED_PACKAGES':'1','NOVA_PACKAGE_TRUST':str(self.trust)}):
            with self.assertRaises(Problem):Engine(self.dir/'db')

if __name__=='__main__':unittest.main()
