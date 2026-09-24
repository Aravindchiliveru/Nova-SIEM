import concurrent.futures
import copy
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from nova.core import Engine,Problem,canonical
from nova.enterprise import Enterprise
from test_core import event,batch

class EnterpriseTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.path=Path(self.temp.name)/'db'
        self.e=Engine(self.path);self.e.activate('alpha','admin','auth-json')
        self.e.ingest('alpha','collector',batch([event(i) for i in range(5)]));self.e.drain()
        self.aid=self.e.listing('alpha','alerts')[0]['id'];self.x=Enterprise(self.e)
    def tearDown(self):self.temp.cleanup()
    def job(self,key='job-1'):return self.x.create('alpha','analyst',dict(request_key=key,playbook='triage-auth.v1',alert_id=self.aid))
    def approve(self,job):return self.x.transition('alpha','admin',dict(id=job['id'],revision=job['revision'],action='approve'))
    def test_no_work_before_approval(self):
        self.job();self.assertEqual(self.x.tick(),0);self.assertEqual(self.e.listing('alpha','cases'),[])
    def test_request_idempotency(self):self.assertEqual(self.job()['id'],self.job()['id'])
    def test_request_key_conflict(self):
        self.job()
        with self.assertRaises(Problem):self.x.create('alpha','analyst',dict(request_key='job-1',playbook='triage-auth.v1',alert_id='different'))
    def test_self_approval_denied(self):
        j=self.job()
        with self.assertRaises(Problem) as c:self.x.transition('alpha','analyst',dict(id=j['id'],revision=0,action='approve'))
        self.assertEqual(c.exception.status,403)
    def test_tenant_approval_denied(self):
        j=self.job()
        with self.assertRaises(Problem):self.x.transition('beta','admin',dict(id=j['id'],revision=0,action='approve'))
    def test_tenant_alert_binding(self):
        with self.assertRaises(Problem):self.x.create('beta','analyst',dict(request_key='x',playbook='triage-auth.v1',alert_id=self.aid))
    def test_stale_revision_denied(self):
        j=self.job();self.approve(j)
        with self.assertRaises(Problem):self.x.transition('alpha','admin',dict(id=j['id'],revision=0,action='cancel'))
    def test_workflow_survives_restart(self):
        self.approve(self.job());self.x.tick();self.x=Enterprise(Engine(self.path))
        self.x.tick();self.x.tick();self.assertEqual(self.x.tick(),0)
        j=self.x.listing('alpha')[0];self.assertEqual(j['state'],'completed')
        case=self.e.case_detail('alpha',json.loads(j['result'])['case_id'])
        self.assertEqual(case['case']['status'],'investigating');self.assertEqual(len(case['notes']),1)
    def test_two_workers_do_not_repeat_steps(self):
        self.approve(self.job())
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            list(pool.map(lambda _:self.x.tick(),range(10)))
        j=self.x.listing('alpha')[0];self.assertEqual(j['step'],3)
        self.assertEqual(len(self.e.case_detail('alpha',json.loads(j['result'])['case_id'])['notes']),1)
    def test_failure_rolls_back_action(self):
        self.approve(self.job());original=self.x.action
        def fault(*args):original(*args);raise RuntimeError('after case creation')
        with patch.object(self.x,'action',side_effect=fault):self.x.tick(now=1)
        self.assertEqual(self.e.listing('alpha','cases'),[])
        j=self.x.listing('alpha')[0];self.assertEqual(j['step'],0);self.assertEqual(j['attempts'],1)
        self.x.tick(now=100);self.assertEqual(len(self.e.listing('alpha','cases')),1)
    def test_retry_circuit_and_recovery(self):
        self.approve(self.job())
        with patch.object(self.x,'action',side_effect=RuntimeError('outage')):
            for now in (0,100,200):self.x.tick(now=now)
        j=self.x.listing('alpha')[0];self.assertEqual(j['state'],'failed');self.assertEqual(self.x.tick(now=300),0)
        self.x.transition('alpha','admin',dict(id=j['id'],revision=j['revision'],action='retry'))
        for _ in range(3):self.x.tick(now=400)
        self.assertEqual(self.x.listing('alpha')[0]['state'],'completed')
    def test_cancel_does_not_undo_committed_steps(self):
        j=self.approve(self.job());self.x.tick();j=self.x.listing('alpha')[0]
        self.x.transition('alpha','admin',dict(id=j['id'],revision=j['revision'],action='cancel'))
        self.assertEqual(self.x.tick(),0);self.assertEqual(len(self.e.listing('alpha','cases')),1)
    def test_audit_chain_and_checkpoint(self):
        anchor=self.x.integrity('alpha');self.job()
        result=self.x.integrity('alpha',anchor);self.assertTrue(result['external_anchor_checked']);self.assertEqual(result['unlinked_records'],0)
    def test_modified_audit_record_detected(self):
        with self.e.tx() as c:c.execute("UPDATE audit SET actor='tampered' WHERE tenant='alpha'")
        with self.assertRaises(Problem):self.x.integrity('alpha')
    def test_changed_chain_payload_detected(self):
        with self.e.tx() as c:c.execute("UPDATE nova_audit_chain SET payload='{}' WHERE tenant='alpha' AND seq=1")
        with self.assertRaises(Problem):self.x.integrity('alpha')
    def test_tail_truncation_requires_anchor(self):
        self.job();anchor=self.x.integrity('alpha')
        with self.e.tx() as c:
            row=c.execute('SELECT audit_id FROM nova_audit_chain WHERE tenant=? AND seq=?',('alpha',anchor['count'])).fetchone()
            c.execute('DELETE FROM audit WHERE id=?',(row['audit_id'],));c.execute('DELETE FROM nova_audit_chain WHERE tenant=? AND seq=?',('alpha',anchor['count']))
        with self.assertRaises(Problem):self.x.integrity('alpha',anchor)
    def test_online_audit_budget_fails_explicitly(self):
        from nova.enterprise import verify_audit
        with self.e.connect() as c:
            with self.assertRaises(Problem) as ctx:verify_audit(c,'alpha',max_records=1)
            self.assertEqual(ctx.exception.status,429)
    def test_foreign_anchor_rejected(self):
        anchor=self.x.integrity('alpha')
        with self.assertRaises(Problem):self.x.integrity('beta',anchor)

class CorrelationTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.e=Engine(Path(self.temp.name)/'db');self.e.activate('alpha','a','auth-json')
        self.rules={r['window_mode']:r for r in self.e.rules.rules if 'window_mode' in r}
        for r in self.e.rules.rules:r['enabled']=False
    def tearDown(self):self.temp.cleanup()
    def put(self,events,tenant='alpha'):
        self.e.ingest(tenant,'c',batch(events));self.e.drain()
    def alerts(self):return self.e.listing('alpha','alerts')
    def test_sliding_crosses_fixed_boundary(self):
        self.rules['sliding']['enabled']=True
        self.put([event(i,timestamp='2026-09-17T12:04:59Z') for i in range(4)]+[event(4,timestamp='2026-09-17T12:05:01Z')])
        self.assertEqual(len(self.alerts()),1)
    def test_sliding_excludes_lower_boundary(self):
        self.rules['sliding']['enabled']=True
        self.put([event(i,timestamp='2026-09-17T12:00:00Z') for i in range(4)]+[event(4,timestamp='2026-09-17T12:05:00Z')])
        self.assertEqual(self.alerts(),[])
    def test_sequence_requires_later_success(self):
        self.rules['sequence']['enabled']=True
        self.put([event(i) for i in range(5)]);self.assertEqual(self.alerts(),[])
        self.put([event(6,timestamp='2026-09-17T12:01:01Z',status='success')]);self.assertEqual(len(self.alerts()),1)
        self.assertEqual(len(json.loads(self.alerts()[0]['evidence'])),6)
    def test_equal_timestamp_is_not_ordered(self):
        self.rules['sequence']['enabled']=True
        self.put([event(i) for i in range(5)]+[event(6,status='success')]);self.assertEqual(self.alerts(),[])
    def test_late_failures_complete_stored_sequence(self):
        self.rules['sequence']['enabled']=True
        self.put([event(6,timestamp='2026-09-17T12:01:01Z',status='success')]);self.put([event(i) for i in range(5)])
        self.assertEqual(len(self.alerts()),1)
    def test_correlation_retry_idempotent(self):
        self.rules['sequence']['enabled']=True;events=[event(i) for i in range(5)]+[event(6,timestamp='2026-09-17T12:01:01Z',status='success')]
        self.put(events)
        with self.e.tx() as c:c.execute("DELETE FROM processed WHERE consumer='detector'")
        self.e.drain();self.assertEqual(len(self.alerts()),1)
    def test_correlation_group_capacity_is_atomic(self):
        self.rules['sliding']['enabled']=True
        self.e.ingest('alpha','c',batch([event(i) for i in range(5)]));self.e.normalize_batch()
        with patch('nova.correlation.MAX_GROUP_EVENTS',3):
            with self.assertRaises(Problem):self.e.detect_batch()
        self.assertEqual(self.e.health('alpha')['detector_pending'],5)
        with self.e.connect() as c:self.assertEqual(c.execute('SELECT COUNT(*) FROM nova_correlation_events').fetchone()[0],0)
    def test_distinct_correlation(self):
        r=self.rules['sliding'];r['enabled']=True;r['distinct']='actor';r['group_by']=['ip']
        self.put([event(i) for i in range(5)]);self.assertFalse(self.alerts())
    def test_correlation_tenant_isolation(self):
        self.rules['sequence']['enabled']=True;self.e.activate('beta','a','auth-json')
        self.put([event(i) for i in range(5)]);self.put([event(6,timestamp='2026-09-17T12:01:01Z',status='success')],'beta')
        self.assertFalse(self.alerts());self.assertFalse(self.e.listing('beta','alerts'))


class GovernanceTests(unittest.TestCase):
    setUp=EnterpriseTests.setUp
    tearDown=EnterpriseTests.tearDown
    def test_tenant_rule_disable(self):
        rule=self.x.rule_catalog('alpha')[0]
        target=next(r for r in self.x.rule_catalog('alpha') if r['id']=='auth.failures.v1')
        self.x.set_rule('alpha','admin',dict(id=target['id'],revision=target['revision'],enabled=False))
        self.assertFalse(next(r for r in self.x.rule_catalog('alpha') if r['id']==target['id'])['enabled'])
        self.assertTrue(next(r for r in self.x.rule_catalog('beta') if r['id']==target['id'])['enabled'])
    def test_stale_rule_revision_cannot_activate(self):
        target=self.x.rule_catalog('alpha')[0]
        with self.assertRaises(Problem):self.x.set_rule('alpha','admin',dict(id=target['id'],revision='wrong',enabled=True))
    def test_changed_package_disables_override(self):
        target=self.x.rule_catalog('alpha')[0]
        self.x.set_rule('alpha','admin',dict(id=target['id'],revision=target['revision'],enabled=True))
        self.e.rules.rules[0]['revision']='f'*64
        row=self.x.rule_catalog('alpha')[0];self.assertFalse(row['enabled']);self.assertTrue(row['configuration_stale'])
    def test_rule_enable_changes_processing(self):
        target=next(r for r in self.x.rule_catalog('alpha') if r.get('window_mode')=='sequence')
        self.x.set_rule('alpha','admin',dict(id=target['id'],revision=target['revision'],enabled=True))
        self.e.ingest('alpha','c',batch([event(i+10) for i in range(5)]+[event(20,status='success',timestamp='2026-09-17T12:01:01Z')]))
        self.e.drain();self.assertIn(target['id'],[a['rule'] for a in self.e.listing('alpha','alerts')])
    def test_parser_preview_does_not_persist(self):
        before=self.e.health('alpha')['raw_events'];result=self.x.test_integration({'package':'auth-json','events':[event()['data'],event(src_ip='bad')['data']]})
        self.assertIsNone(result['results'][0]['error']);self.assertIsNotNone(result['results'][1]['error'])
        self.assertEqual(self.e.health('alpha')['raw_events'],before)
    def test_deactivated_package_quarantines_new_events(self):
        self.x.deactivate_integration('alpha','admin',{'package':'auth-json'})
        self.e.ingest('alpha','c',batch([event(100)]));self.e.drain()
        self.assertEqual(self.e.health('alpha')['quarantine'],1)
    def test_export_and_checksum(self):
        from nova.evidence import verify
        cid=self.e.create_case('alpha','analyst',self.aid)['id']
        bundle=self.x.export_case('alpha','analyst',{'case_id':cid});self.assertEqual(verify(bundle)['events'],5)
        self.assertFalse(bundle['payload']['point_in_time_snapshot']);self.assertEqual(self.x.integrity('alpha')['unlinked_records'],0)
        bundle['payload']['tenant']='tampered'
        with self.assertRaises(Problem):verify(bundle)
    def test_evidence_cannot_assert_its_own_authenticity(self):
        from nova.evidence import seal,verify
        bundle=seal({'events':[]});bundle['authenticity']='trusted signature'
        self.assertEqual(verify(bundle)['authenticity'],'checksum-only; signature not verified')
    def test_foreign_case_export_denied(self):
        cid=self.e.create_case('alpha','analyst',self.aid)['id']
        with self.assertRaises(Problem):self.x.export_case('beta','analyst',{'case_id':cid})

if __name__=='__main__':unittest.main()
