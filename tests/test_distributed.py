import hashlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock,patch
from urllib.parse import parse_qs,urlparse
from nova.core import ROOT,Problem,canonical
from nova.distributed.contracts import (prepare,transform,validate_raw,validate_normal,strict_json,
    offsets,Record,Processor,Packages,NormalizerSink,NORMAL_TOPIC,QUARANTINE_TOPIC)
from nova.distributed.clients import ClickHouse,compile_search
from nova.distributed.archive import Archive
from nova.distributed.main import ConfirmedSink,ConfirmedNormalizer
from nova.distributed.metadata import Metadata
from test_core import batch,event

class Consumer:
    def __init__(self,records):self.records=records;self.commits=[]
    def read(self,size):return self.records[:size]
    def commit(self,positions):self.commits.append(positions);self.records=[]

class Response:
    def __init__(self,body=b'',status=200):self.body,self.status=body,status
    def __enter__(self):return self
    def __exit__(self,*args):pass
    def read(self,n):return self.body[:n]

class DistributedTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.packages=Packages(ROOT/'integrations').packages
    def raw(self):
        r=prepare('alpha',batch(),now=10)[0]
        r['package_digest']=self.packages['auth-json']['sha256']
        return r
    def normal(self):return transform(self.raw(),self.packages,now=11)[1]
    def records(self):return [Record('raw',0,3,canonical(self.raw()).encode())]
    def test_stable_identity_and_digest(self):
        a,b=prepare('alpha',batch(),now=1)[0],prepare('alpha',batch(),now=2)[0]
        self.assertEqual(a['event_id'],b['event_id']);self.assertEqual(a['digest'],b['digest'])
    def test_changed_payload_changes_digest_not_id(self):
        a,b=self.raw(),prepare('alpha',batch([event(user='bob')]))[0]
        self.assertEqual(a['event_id'],b['event_id']);self.assertNotEqual(a['digest'],b['digest'])
    def test_valid_transform(self):
        topic,n=transform(self.raw(),self.packages,now=11)
        self.assertEqual(topic,NORMAL_TOPIC);self.assertEqual(n['actor'],'alice')
        self.assertEqual(n['received'],10);self.assertEqual(n['normalized_at'],11)
    def test_package_snapshot_mismatch_quarantines(self):
        r=self.raw();r['package_digest']='f'*64
        topic,q=transform(r,self.packages)
        self.assertEqual(topic,QUARANTINE_TOPIC);self.assertEqual(q['raw'],r)
    def test_malformed_payload_preserved_in_quarantine(self):
        r=prepare('alpha',batch([event(src_ip='invalid')]))[0];r['package_digest']=self.packages['auth-json']['sha256']
        topic,q=transform(r,self.packages)
        self.assertEqual(topic,QUARANTINE_TOPIC);self.assertEqual(q['raw']['payload']['src_ip'],'invalid')
    def test_raw_digest_integrity(self):
        r=self.raw();r['payload']['user']='altered'
        with self.assertRaises(ValueError):validate_raw(r)
    def test_replay_generation_limit(self):
        r=self.raw();r['replay_generation']=4
        with self.assertRaises(ValueError):validate_raw(r)
    def test_nonfinite_received_rejected(self):
        r=self.raw();r['received']=float('nan')
        with self.assertRaises(ValueError):validate_raw(r)
    def test_normalized_tenant_override_rejected(self):
        n=self.normal();n['tenant']='beta'
        with self.assertRaises(ValueError):validate_normal(n)
    def test_normalized_identity_override_rejected(self):
        n=self.normal();n['event_id']='a'*64
        with self.assertRaises(ValueError):validate_normal(n)
    def test_nonfinite_normalized_time_rejected(self):
        n=self.normal();n['event_time']=float('inf')
        with self.assertRaises(ValueError):validate_normal(n)
    def test_duplicate_wire_keys_rejected(self):
        with self.assertRaises(ValueError):strict_json(b'{"a":1,"a":2}')
    def test_nonfinite_wire_json_rejected(self):
        with self.assertRaises(ValueError):strict_json(b'{"a":NaN}')
    def test_offsets_use_exact_next_position(self):
        rows=[Record('t',0,2,b''),Record('t',0,8,b''),Record('t',1,3,b'')]
        self.assertEqual(offsets(rows),{('t',0):9,('t',1):4})
    def test_commit_after_sink_success(self):
        c=Consumer(self.records());sink=Mock()
        sink.write.side_effect=lambda _:self.assertEqual(c.commits,[])
        self.assertEqual(Processor(c,sink).step(),1);self.assertEqual(c.commits,[{('raw',0):4}])
    def test_sink_failure_never_commits(self):
        c=Consumer(self.records());sink=Mock();sink.write.side_effect=RuntimeError()
        with self.assertRaises(RuntimeError):Processor(c,sink).step()
        self.assertEqual(c.commits,[])
    def test_invalid_wire_record_never_commits(self):
        c=Consumer([Record('t',0,0,b'bad json')]);sink=Mock()
        with self.assertRaises(ValueError):Processor(c,sink).step()
        sink.write.assert_not_called();self.assertEqual(c.commits,[])
    def test_empty_poll_does_not_commit(self):
        c=Consumer([]);sink=Mock()
        self.assertEqual(Processor(c,sink).step(),0);self.assertEqual(c.commits,[])
    def test_commit_failure_can_redeliver(self):
        c=Consumer(self.records());real=c.commit;c.commit=Mock(side_effect=RuntimeError())
        sink=Mock()
        with self.assertRaises(RuntimeError):Processor(c,sink).step()
        c.commit=real;Processor(c,sink).step()
        self.assertEqual(sink.write.call_count,2)
    def test_bad_member_prevents_entire_publish(self):
        p=Mock();bad=self.raw();bad['digest']='f'*64
        with self.assertRaises(ValueError):NormalizerSink(p,self.packages).write([self.raw(),bad])
        p.publish.assert_not_called()
    def test_publish_failure_prevents_metadata_marker(self):
        p=Mock();p.publish.side_effect=RuntimeError();meta=Mock()
        with self.assertRaises(RuntimeError):ConfirmedNormalizer(p,self.packages,meta).write([self.raw()])
        meta.mark.assert_not_called()
    def test_clickhouse_success_metadata_failure_does_not_commit(self):
        c=Consumer([Record('normal',0,2,canonical(self.normal()).encode())]);meta=Mock();meta.mark.side_effect=RuntimeError()
        sink=Mock()
        with self.assertRaises(RuntimeError):Processor(c,ConfirmedSink(sink,meta,'indexed_at')).step()
        sink.write.assert_called_once();self.assertEqual(c.commits,[])
    def test_search_is_parameterized_and_tenant_bound(self):
        text="' OR tenant='beta' --"
        query,params=compile_search('alpha',{'q':text})
        self.assertNotIn(text,query);self.assertEqual(params['q'],text)
        self.assertIn('tenant={tenant:String}',query);self.assertIn(' FINAL ',query)
    def test_unknown_query_field_rejected(self):
        with self.assertRaises(Problem):compile_search('alpha',{'tenant':'beta'})
    def test_half_open_time_filter(self):
        q,p=compile_search('alpha',{'after':'2026-01-01T00:00:00Z','before':'2026-01-02T00:00:00Z'})
        self.assertIn('event_time>={after:Float64}',q);self.assertIn('event_time<{before:Float64}',q)
        self.assertEqual(p['before']-p['after'],86400)
    def test_search_limit_bounded(self):
        for value in ('0','501','oops'):
            with self.assertRaises(Problem):compile_search('alpha',{'limit':value})
    def test_embedded_database_credentials_rejected(self):
        with self.assertRaises(ValueError):ClickHouse('http://user:password@localhost:8123','u','p')
    def test_clickhouse_no_password_in_url(self):
        opener=Mock();opener.open.return_value=Response(b'{"data":[]}')
        ch=ClickHouse('http://localhost:8123','nova','private-test',opener)
        ch.search('alpha',{})
        req=opener.open.call_args.args[0]
        self.assertNotIn('private-test',req.full_url)
        self.assertEqual(parse_qs(urlparse(req.full_url).query)['param_tenant'],['alpha'])
    def test_clickhouse_200_execution_error_rejected(self):
        opener=Mock();opener.open.return_value=Response(b'Code: 241. DB::Exception: memory')
        with self.assertRaises(RuntimeError):ClickHouse('http://localhost:8123','u','p',opener).write([self.normal()])
    def test_clickhouse_transport_failure_rejected(self):
        opener=Mock();opener.open.side_effect=TimeoutError()
        with self.assertRaises(RuntimeError):ClickHouse('http://localhost:8123','u','p',opener).write([self.normal()])
    def test_clickhouse_invalid_query_response_rejected(self):
        opener=Mock();opener.open.return_value=Response(b'not json')
        with self.assertRaises(RuntimeError):ClickHouse('http://localhost:8123','u','p',opener).search('alpha',{})
    def test_clickhouse_batch_validate_before_network(self):
        opener=Mock();n=self.normal();n['tenant']='beta'
        with self.assertRaises(ValueError):ClickHouse('http://localhost:8123','u','p',opener).write([self.normal(),n])
        opener.open.assert_not_called()
    def test_clickhouse_write_uses_synchronous_response(self):
        opener=Mock();opener.open.return_value=Response()
        ClickHouse('http://localhost:8123','u','p',opener).write([self.normal()])
        req=opener.open.call_args.args[0]
        self.assertIn(b'INSERT INTO nova.events FORMAT JSONEachRow',req.data)
        self.assertIn('wait_end_of_query=1',req.full_url)
    def test_archive_redelivery_is_idempotent(self):
        with tempfile.TemporaryDirectory() as d:
            archive=Archive(d);archive.write([self.raw()]);archive.write([self.raw()])
            files=list(Path(d).rglob('*.json'));self.assertEqual(len(files),1)
            self.assertEqual(hashlib.sha256(files[0].read_bytes()).hexdigest(),files[0].stem)
    def test_archive_tampering_fails_closed(self):
        with tempfile.TemporaryDirectory() as d:
            archive=Archive(d);archive.write([self.raw()]);list(Path(d).rglob('*.json'))[0].write_text('corrupt')
            with self.assertRaises(RuntimeError):archive.write([self.raw()])
    def test_archive_replay_preserves_original(self):
        with tempfile.TemporaryDirectory() as d:
            a=Archive(d);r=self.raw();a.write([r]);r['replay_generation']=1;a.write([r])
            self.assertEqual(len(list(Path(d).rglob('*.json'))),2)

class RelayTests(unittest.TestCase):
    def test_outbox_not_deleted_without_broker_ack(self):
        c=Mock();c.__enter__=Mock(return_value=c);c.__exit__=Mock(return_value=False)
        c.execute.return_value.fetchall.return_value=[{'id':1,'topic':'t','payload':'{}'}]
        m=Metadata('unused');m.connect=Mock(return_value=c)
        publisher=Mock();publisher.publish.side_effect=RuntimeError()
        with self.assertRaises(RuntimeError):m.relay(publisher)
        self.assertFalse(any('DELETE' in call.args[0] for call in c.execute.call_args_list))
    def test_outbox_delete_follows_broker_ack(self):
        c=Mock();c.__enter__=Mock(return_value=c);c.__exit__=Mock(return_value=False)
        c.execute.return_value.fetchall.return_value=[{'id':1,'topic':'t','payload':'{}'}]
        m=Metadata('unused');m.connect=Mock(return_value=c)
        publisher=Mock()
        publisher.publish.side_effect=lambda _:self.assertFalse(any('DELETE' in call.args[0] for call in c.execute.call_args_list))
        self.assertEqual(m.relay(publisher),1)
        self.assertIn('DELETE',c.execute.call_args_list[-1].args[0])

class KafkaAdapterTests(unittest.TestCase):
    def test_producer_requires_all_acks_and_idempotence(self):
        import types
        from nova.distributed.clients import KafkaPublisher
        p=Mock();p.flush.return_value=0
        factory=Mock(return_value=p)
        with patch.dict('sys.modules',{'confluent_kafka':types.SimpleNamespace(Producer=factory)}):
            writer=KafkaPublisher({'bootstrap.servers':'example'})
            writer.publish([])
        config=factory.call_args.args[0]
        self.assertTrue(config['enable.idempotence']);self.assertEqual(config['acks'],'all')
    def test_unflushed_producer_queue_is_failure(self):
        import types
        from nova.distributed.clients import KafkaPublisher
        p=Mock();p.flush.return_value=1
        with patch.dict('sys.modules',{'confluent_kafka':types.SimpleNamespace(Producer=Mock(return_value=p))}):
            writer=KafkaPublisher({})
            with self.assertRaises(RuntimeError):writer.publish([])
    def test_delivery_callback_error_is_failure(self):
        import types
        from nova.distributed.clients import KafkaPublisher
        p=Mock()
        callbacks=[]
        p.produce.side_effect=lambda *a,**kw:callbacks.append(kw['on_delivery'])
        def flush(_):
            for cb in callbacks:cb(Mock(code=lambda:1),None)
            return 0
        p.flush.side_effect=flush
        with patch.dict('sys.modules',{'confluent_kafka':types.SimpleNamespace(Producer=Mock(return_value=p))}):
            writer=KafkaPublisher({})
            with self.assertRaises(RuntimeError):writer.publish([('t',{'tenant':'alpha','event_id':'1'})])
    def test_new_consumer_starts_without_silent_expired_offset_reset(self):
        import types
        from nova.distributed.clients import KafkaConsumer
        c=Mock();factory=Mock(return_value=c)
        module=types.SimpleNamespace(Consumer=factory,OFFSET_INVALID=-1001,OFFSET_BEGINNING=-2)
        with patch.dict('sys.modules',{'confluent_kafka':module}):
            KafkaConsumer({},'group','topic')
            assignment=c.subscribe.call_args.kwargs['on_assign']
            positions=[types.SimpleNamespace(offset=-1001),types.SimpleNamespace(offset=123)]
            c.committed.return_value=positions;assignment(c,[])
        self.assertEqual([p.offset for p in positions],[-2,123])
        config=factory.call_args.args[0]
        self.assertEqual(config['auto.offset.reset'],'error');self.assertFalse(config['enable.auto.commit'])
    def test_consumer_commit_checks_each_partition_result(self):
        import types
        from nova.distributed.clients import KafkaConsumer
        c=Mock();c.commit.return_value=[types.SimpleNamespace(error='failed')]
        module=types.SimpleNamespace(Consumer=Mock(return_value=c),TopicPartition=lambda *a:a)
        with patch.dict('sys.modules',{'confluent_kafka':module}):
            reader=KafkaConsumer({},'g','t')
            with self.assertRaises(RuntimeError):reader.commit({('t',0):12})
        self.assertFalse(c.commit.call_args.kwargs['asynchronous'])
    def test_consume_error_is_not_skipped(self):
        import types
        from nova.distributed.clients import KafkaConsumer
        c=Mock();m=Mock();m.error.return_value='bad';c.consume.return_value=[m]
        with patch.dict('sys.modules',{'confluent_kafka':types.SimpleNamespace(Consumer=Mock(return_value=c))}):
            reader=KafkaConsumer({},'g','t')
            with self.assertRaises(RuntimeError):reader.read(200)
        c.commit.assert_not_called()
