import unittest
from nova.distributed.readiness import check
from nova.distributed.contracts import TOPICS
from nova.core import Problem

class ReadinessTests(unittest.TestCase):
    def setUp(self):
        self.pg={'commit_mode':'on','standby':'ANY 1 (standby1,standby2)','recovery':False};self.sync=1
        self.replica=dict(engine='ReplicatedReplacingMergeTree',is_readonly=0,is_session_expired=0,active_replicas=2,total_replicas=2)
        self.topics={t:dict(min_insync_replicas=2,unclean_leader_election=False,partitions=[dict(replicas=3,isr=2)]) for t in TOPICS};parent=self
        class Meta:
            def connect(self):return self
            def __enter__(self):return self
            def __exit__(self,*a):pass
            def execute(self,q):self.value={'n':parent.sync} if 'COUNT' in q else parent.pg;return self
            def fetchone(self):return self.value
        class CH:
            def request(self,q):return [parent.replica]
        self.meta=Meta();self.ch=CH()
    def test_checks_do_not_claim_proven_ha(self):self.assertFalse(check(self.meta,self.ch,self.topics)['production_ha_dr_proven'])
    def test_async_metadata_refused(self):
        self.pg['commit_mode']='local'
        with self.assertRaises(Problem):check(self.meta,self.ch,self.topics)
    def test_no_sync_standby_refused(self):
        self.sync=0
        with self.assertRaises(Problem):check(self.meta,self.ch,self.topics)
    def test_underreplicated_broker_refused(self):
        self.topics[TOPICS[0]]['partitions'][0]['isr']=1
        with self.assertRaises(Problem):check(self.meta,self.ch,self.topics)
    def test_unreplicated_analytics_refused(self):
        self.replica['engine']='ReplacingMergeTree'
        with self.assertRaises(Problem):check(self.meta,self.ch,self.topics)
