import concurrent.futures
import json
import tempfile
import unittest
from pathlib import Path
from nova.core import Engine, Problem, timestamp


def event(i=1,**overrides):
    data=dict(timestamp='2026-09-17T12:01:00Z',user='alice',src_ip='192.0.2.1',status='failure',message='Login denied')
    data.update(overrides)
    return dict(id=str(i),data=data)

def batch(events=None,integration='auth-json',source='collector-1'):
    return dict(source=source,integration=integration,events=events if events is not None else [event()])

class CoreTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.path=Path(self.temp.name)/'db.sqlite'
        self.e=Engine(self.path)
        self.e.activate('alpha','admin','auth-json')
    def tearDown(self): self.temp.cleanup()
    def ingest(self,events=None,tenant='alpha',**kw):
        return self.e.ingest(tenant,'collector',batch(events,**kw))
    def test_durable_restart(self):
        self.ingest(); self.e=Engine(self.path); self.e.drain()
        self.assertEqual(len(self.e.search('alpha',{})),1)
    def test_retry_idempotent(self):
        self.ingest(); self.assertEqual(self.ingest()['duplicates'],1)
        self.e.drain(); self.assertEqual(self.e.health('alpha')['normalized'],1)
    def test_conflict_rolls_back_entire_batch(self):
        self.ingest()
        with self.assertRaises(Problem) as ctx: self.ingest([event(2),event(1,user='bob')])
        self.assertEqual(ctx.exception.status,409)
        self.assertEqual(self.e.health('alpha')['raw_events'],1)
    def test_tenant_cannot_be_payload_selected(self):
        b=batch(); b['tenant']='beta'
        with self.assertRaises(Problem): self.e.ingest('alpha','collector',b)
    def test_same_upstream_id_across_sources(self):
        self.ingest(); self.ingest(source='collector-2')
        self.assertEqual(self.e.health('alpha')['raw_events'],2)
    def test_same_id_across_tenants(self):
        self.ingest(); self.ingest(tenant='beta')
        self.assertEqual(self.e.health('beta')['raw_events'],1)
    def test_isolated_search(self):
        self.ingest(); self.e.drain()
        self.assertEqual(self.e.search('beta',{}),[])
    def test_inactive_goes_to_quarantine(self):
        self.ingest(tenant='beta'); self.e.drain()
        self.assertEqual(len(self.e.listing('beta','quarantine')),1)
        self.assertEqual(self.e.health('beta')['normalized'],0)
    def test_activate_then_replay(self):
        eid=self.ingest(tenant='beta')['event_ids'][0]; self.e.drain()
        self.e.activate('beta','admin','auth-json')
        self.e.replay('beta','admin',eid); self.e.drain()
        self.assertEqual(self.e.health('beta')['quarantine'],0)
        self.assertEqual(self.e.health('beta')['normalized'],1)
    def test_invalid_ip_preserved(self):
        self.ingest([event(src_ip='bad')]); self.e.drain()
        self.assertEqual(self.e.health('alpha')['raw_events'],1)
        self.assertEqual(self.e.health('alpha')['quarantine'],1)
    def test_replay_bounded(self):
        eid=self.ingest([event(src_ip='bad')])['event_ids'][0]; self.e.drain()
        for _ in range(3): self.e.replay('alpha','admin',eid); self.e.drain()
        with self.assertRaises(Problem): self.e.replay('alpha','admin',eid)
    def test_cross_tenant_replay_denied(self):
        eid=self.ingest([event(src_ip='bad')])['event_ids'][0]; self.e.drain()
        with self.assertRaises(Problem) as ctx: self.e.replay('beta','admin',eid)
        self.assertEqual(ctx.exception.status,404)
    def test_five_failures_alert_once(self):
        events=[event(i) for i in range(5)]
        self.ingest(events); self.e.drain(); self.ingest(events); self.e.drain()
        alerts=self.e.listing('alpha','alerts')
        self.assertEqual(len(alerts),1)
        self.assertEqual(len(json.loads(alerts[0]['evidence'])),5)
    def test_four_failures_do_not_alert(self):
        self.ingest([event(i) for i in range(4)]); self.e.drain()
        self.assertEqual(self.e.listing('alpha','alerts'),[])
    def test_successes_do_not_count(self):
        self.ingest([event(i,status='success') for i in range(6)]); self.e.drain()
        self.assertEqual(self.e.listing('alpha','alerts'),[])
    def test_detection_tenant_isolation(self):
        self.e.activate('beta','admin','auth-json')
        self.ingest([event(i) for i in range(3)])
        self.ingest([event(i) for i in range(3)],tenant='beta'); self.e.drain()
        self.assertEqual(self.e.listing('alpha','alerts'),[])
        self.assertEqual(self.e.listing('beta','alerts'),[])
    def test_buckets_do_not_cross(self):
        self.ingest([event(i) for i in range(3)]+[event(i+3,timestamp='2026-09-17T12:06:00Z') for i in range(3)])
        self.e.drain(); self.assertEqual(self.e.listing('alpha','alerts'),[])
    def test_late_event_completes_bucket(self):
        self.ingest([event(i,timestamp='2026-09-17T12:04:00Z') for i in range(4)]); self.e.drain()
        self.ingest([event(7,timestamp='2026-09-17T12:01:00Z')]); self.e.drain()
        self.assertEqual(len(self.e.listing('alpha','alerts')),1)
    def test_case_is_idempotent_and_scoped(self):
        self.ingest([event(i) for i in range(5)]); self.e.drain()
        aid=self.e.listing('alpha','alerts')[0]['id']
        a=self.e.create_case('alpha','analyst',aid); b=self.e.create_case('alpha','analyst',aid)
        self.assertEqual(a['id'],b['id'])
        with self.assertRaises(Problem): self.e.create_case('beta','analyst',aid)
    def test_literal_search_not_sql(self):
        self.ingest(); self.e.drain()
        self.assertEqual(self.e.search('alpha',{'q':"' OR 1=1 --"}),[])
    def test_half_open_time_range(self):
        self.ingest(); self.e.drain()
        self.assertEqual(len(self.e.search('alpha',{'after':'2026-09-17T12:01:00Z','before':'2026-09-17T12:02:00Z'})),1)
        self.assertEqual(self.e.search('alpha',{'before':'2026-09-17T12:01:00Z'}),[])
    def test_timezone_required(self):
        with self.assertRaises(Problem): timestamp('2026-09-17T12:01:00')
    def test_bad_batch_atomic(self):
        with self.assertRaises(Problem): self.ingest([event(1),{'id':'2','data':[]}])
        self.assertEqual(self.e.health('alpha')['raw_events'],0)
    def test_capacity_backpressure(self):
        self.e.max_events=1
        with self.assertRaises(Problem) as ctx: self.ingest([event(1),event(2)])
        self.assertEqual(ctx.exception.status,429)
        self.assertEqual(self.e.health('alpha')['raw_events'],0)
    def test_concurrent_retries(self):
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            results=list(pool.map(lambda _:self.ingest(),range(20)))
        self.assertEqual(sum(r['accepted'] for r in results),1)
    def test_detector_independent_of_normalizer_progress(self):
        self.ingest([event(i) for i in range(5)])
        while self.e.normalize_one(): pass
        self.assertEqual(self.e.health('alpha')['detector_pending'],5)
        while self.e.detect_one(): pass
        self.assertEqual(len(self.e.listing('alpha','alerts')),1)
    def test_event_journey_scoped(self):
        eid=self.ingest()['event_ids'][0]; self.e.drain()
        detail=self.e.event('alpha',eid)
        self.assertEqual(set(detail['completed_stages']),{'normalizer','detector'})
        self.assertEqual(json.loads(detail['raw']['payload'])['user'],'alice')
        with self.assertRaises(Problem): self.e.event('beta',eid)
    def test_second_declarative_package(self):
        self.e.activate('alpha','admin','identity-json')
        p=self.e.packages['identity-json']['fixtures'][0]['input']
        self.ingest([{'id':'1','data':p}],integration='identity-json'); self.e.drain()
        self.assertEqual(self.e.search('alpha',{})[0]['ip'],'2001:db8::1')
    def test_unsupported_query_rejected(self):
        with self.assertRaises(Problem): self.e.search('alpha',{'tenant':'beta'})
    def test_restart_does_not_repeat_alert(self):
        self.ingest([event(i) for i in range(5)]); self.e.drain()
        self.e=Engine(self.path); self.e.drain()
        self.assertEqual(len(self.e.listing('alpha','alerts')),1)

if __name__=='__main__': unittest.main()
