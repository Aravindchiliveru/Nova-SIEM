import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from nova.core import Engine,Problem,SCHEMA
from nova.rules import Rules
from nova.distributed.contracts import prepare,transform,validate_normal,NORMAL_TOPIC
from nova.distributed.clients import compile_search
from nova.collector import Spool

class TypedEvents(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.path=Path(self.tmp.name)/'db';self.e=Engine(self.path)
    def tearDown(self):self.tmp.cleanup()
    def data(self,**kw):
        return dict(timestamp='2026-09-21T12:00:00Z',action='start',target='/bin/sh',message='activity',**kw)
    def ingest(self,category='process',data=None,count=1):
        package=category+'-json';self.e.activate('a','admin',package)
        self.e.ingest('a','collector',dict(source='host1',integration=package,events=[dict(id=str(i),data=data or self.data()) for i in range(count)]));self.e.drain()
    def test_all_categories_restart_and_tenant_search(self):
        for cat in ['process','network','dns','file','cloud']:
            with self.subTest(category=cat):
                self.e.activate('a','admin',cat+'-json')
                self.e.ingest('a','collector',dict(source=cat,integration=cat+'-json',events=[dict(id='1',data=self.data())]))
        self.e.drain();self.e=Engine(self.path)
        for cat in ['process','network','dns','file','cloud']:
            row=self.e.search('a',{'category':cat})[0]
            self.assertEqual((row['category'],row['ip'],row['outcome']),(cat,'','unknown'))
            self.assertEqual(self.e.search('b',{'category':cat}),[])
    def test_non_auth_failures_cannot_trigger_auth_rules(self):
        self.ingest(data=self.data(actor='root',src_ip='192.0.2.1',outcome='failure'),count=20)
        self.assertEqual(self.e.listing('a','alerts'),[])
    def test_optional_context_is_preserved_and_searchable(self):
        self.ingest(data=self.data(actor='alice',host='endpoint1',src_ip='2001:db8::1',outcome='success'))
        row=self.e.search('a',{'host':'endpoint1','action':'start','target':'/bin/sh'})[0]
        self.assertEqual(row['actor'],'alice');self.assertEqual(row['ip'],'2001:db8::1')
    def test_invalid_values_quarantined(self):
        for i,data in enumerate([self.data(src_ip='nonsense'),self.data(outcome='maybe'),self.data(host=None),dict(self.data(),target='')]):
            self.e.activate('a','admin','process-json');self.e.ingest('a','c',dict(source=str(i),integration='process-json',events=[dict(id='1',data=data)]))
        self.e.drain();self.assertEqual(len(self.e.listing('a','quarantine')),4)
    def test_legacy_database_migrates_with_auth_defaults(self):
        path=Path(self.tmp.name)/'old';c=sqlite3.connect(path);c.executescript(SCHEMA)
        c.execute('INSERT INTO normalized VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',('a','id','source',1,1,1,'user','192.0.2.1','failure','message','auth-json','0.1'));c.commit();c.close()
        old=Engine(path);row=old.search('a',{})[0]
        self.assertEqual((row['category'],row['action']),('authentication','login'))
        Engine(path);self.assertEqual(len(old.search('a',{})),1)
    def test_wire_round_trip_and_category_validation(self):
        p=self.e.packages['network-json'];r=prepare('a',dict(source='s',integration=p['id'],events=[dict(id='1',data=self.data())]))[0];r['package_digest']=p['sha256']
        topic,n=transform(r,self.e.packages);self.assertEqual(topic,NORMAL_TOPIC);self.assertEqual(validate_normal(n)['category'],'network')
        with self.assertRaises(Problem):validate_normal(dict(n,category='unsupported'))
    def test_exact_search_binding(self):
        query,bindings=compile_search('a',{'target':"x' OR 1=1 --",'category':'process'})
        self.assertNotIn("x' OR",query);self.assertIn("x' OR 1=1 --",bindings.values())
    def test_typed_rule_simulation(self):
        rule=dict(id='process.start',title='Process start',severity='low',enabled=True,window_seconds=60,threshold=1,group_by=['host','target'],match={'category':['process'],'action':['start']})
        event=dict(source='s',actor='',ip='',outcome='unknown',message='',category='process',action='start',host='h',target='/bin/sh',event_time=1)
        result=Rules.simulate(rule,[event]);self.assertTrue(result['groups'][0]['alert'])
        self.assertEqual(Rules.simulate(rule,[dict(event,category='file')])['groups'],[])
    def test_installed_typed_detection_governance_and_evidence(self):
        from nova.enterprise import Enterprise
        x=Enterprise(self.e);rule=next(r for r in x.rule_catalog('a') if r['id']=='cloud.logging-disabled.v1')
        self.assertFalse(rule['enabled']);x.set_rule('a','admin',{'id':rule['id'],'revision':rule['revision'],'enabled':True})
        self.ingest('cloud',dict(self.data(),action='StopLogging',target='trail1'))
        alerts=self.e.listing('a','alerts');self.assertEqual(len(alerts),1)
        self.assertEqual(alerts[0]['rule'],rule['id'])
        eid=json.loads(alerts[0]['evidence'])[0];self.assertEqual(self.e.event('a',eid)['normalized']['target'],'trail1')
        self.assertEqual(self.e.listing('b','alerts'),[])
    def test_spool_preserves_typed_integration_and_ack(self):
        import hashlib
        from nova.core import canonical
        source=Path(self.tmp.name)/'input';source.write_text(json.dumps(self.data())+'\n')
        spool=Spool(Path(self.tmp.name)/'spool','source','process-json')
        engine=self.e;engine.activate('a','admin','process-json')
        class Response:
            status=200
            def __enter__(self):return self
            def __exit__(self,*args):pass
            def read(self,n):return json.dumps(self.result).encode()
        class Opener:
            def open(self,request,timeout):
                body=json.loads(request.data)
                if body['integration']!='process-json':raise AssertionError('integration lost')
                response=Response();response.result=engine.ingest('a','collector',body);return response
        try:
            spool.import_file(source);self.assertEqual(spool.send('http://localhost:8787','token',opener=Opener()),1)
            self.assertEqual(spool.status(),[]);engine.drain();self.assertEqual(engine.search('a',{})[0]['category'],'process')
        finally:spool.close()
    def test_missing_required_mapping_is_quarantined(self):
        data=self.data();del data['action'];self.ingest(data=data)
        self.assertEqual(self.e.listing('a','quarantine')[0]['reason'],'missing field: action')
    def test_legacy_wire_defaults(self):
        p=self.e.packages['auth-json'];data=dict(timestamp='2026-09-21T12:00:00Z',user='alice',src_ip='192.0.2.1',status='failure',message='login')
        r=prepare('a',dict(source='s',integration=p['id'],events=[dict(id='1',data=data)]))[0];r['package_digest']=p['sha256']
        _,n=transform(r,self.e.packages)
        for k in ('category','action','host','target'):del n[k]
        self.assertEqual(validate_normal(n)['category'],'authentication');self.assertNotIn('category',n)
