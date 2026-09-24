import copy,json,tempfile,unittest
from pathlib import Path
from nova.core import Engine,Problem
from nova import schema,ocsf
from nova.distributed.clients import compile_search
class StructuredTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.e=Engine(Path(self.tmp.name)/'db');self.e.activate('a','admin','nested-process-json');self.doc=json.loads(Path('examples/nested-process.ndjson').read_text());self.doc['extra']={'null':None,'boolean':True,'number':1,'text':'1','array':[{'value':'nested'}]}
    def tearDown(self):self.tmp.cleanup()
    def ingest(self,document=None):
        ack=self.e.ingest('a','c',dict(source='nested',integration='nested-process-json',events=[{'id':'1','data':self.doc if document is None else document}]));self.e.drain();return ack['event_ids'][0]
    def test_document_preserved_without_database_migration(self):
        eid=self.ingest();event=self.e.event('a',eid);self.assertEqual(event['normalized']['document'],self.doc)
        self.assertNotIn('document',self.e.search('a',{})[0]);self.assertEqual(self.e.search('a',{'include_document':'true'})[0]['document'],self.doc)
        self.assertEqual(self.e.search('b',{'include_document':'true'}),[])
    def test_nested_and_array_search(self):
        self.ingest()
        for field,value in [('process.executable','"/bin/sh"'),('extra.array.0.value','"nested"'),('extra.null','null'),('extra.boolean','true'),('extra.number','1'),('extra.text','"1"')]:
            with self.subTest(field=field):self.assertEqual(len(self.e.search('a',{'field':field,'value':value})),1)
        self.assertEqual(self.e.search('a',{'field':'extra.boolean','value':'1'}),[])
        self.assertEqual(self.e.search('a',{'field':'extra.number','value':'"1"'}),[])
    def test_null_and_missing_distinct(self):
        self.ingest()
        self.assertEqual(len(self.e.search('a',{'field':'extra.null','exists':'true'})),1)
        self.assertEqual(self.e.search('a',{'field':'extra.absent','value':'null'}),[])
        self.assertEqual(len(self.e.search('a',{'field':'extra.absent','exists':'false'})),1)
    def test_bad_paths_values_fail_closed(self):
        for params in [{'field':'x") OR 1=1--','value':'1'},{'field':'a','value':'NaN'},{'field':'a','value':'{}'},{'field':'a','exists':'yes'},{'value':'1'},{'field':'a','exists':'true','value':'1'}]:
            with self.subTest(params=params),self.assertRaises(Problem):self.e.search('a',params)
    def test_invalid_nested_schema_quarantined(self):
        self.doc['process']['arguments']=[False];eid=self.ingest();event=self.e.event('a',eid);self.assertIsNone(event['normalized']);self.assertIsNotNone(event['quarantine']);self.assertEqual(json.loads(event['raw']['payload']),self.doc)
    def test_unknown_schema_keywords_rejected(self):
        for value in [{'type':'object','$ref':'https://example.invalid'},{'type':'object','required':['missing']},{'type':'integer','min':True}]:
            with self.assertRaises(Problem):schema.check(value)
    def test_distributed_query_bound_and_array_translation(self):
        query,params=compile_search('a',{'field':'extra.array.0.value','value':'"nested"','include_document':'true'})
        self.assertIn('JSONExtractRaw',query);self.assertNotIn('nested',query);self.assertEqual(params['field_path_2'],1);self.assertEqual(params['tenant'],'a')
    def test_system_profiles_preserve_original_export(self):
        for name in ('process','file'):
            doc=json.loads(Path('examples/ocsf-'+name+'-json.ndjson').read_text());doc['custom']={'nested':[1,True,None]};package='ocsf-'+name+'-json';self.e.activate('a','admin',package)
            ack=self.e.ingest('a','c',dict(source=name,integration=package,events=[{'id':'1','data':doc}]));self.e.drain();n=self.e.event('a',ack['event_ids'][0])['normalized'];self.assertEqual(ocsf.export(n),doc)
            wrong=copy.deepcopy(doc);wrong['type_uid']+=1
            with self.assertRaises(Problem):ocsf.normalize_system(wrong)
    def test_schema_types_bounds_and_additional_properties(self):
        s=schema.check({'type':'object','additional':False,'required':['x'],'properties':{'x':{'type':'integer','min':0,'max':5}}})
        for value in [{'x':True},{'x':6},{'x':1,'extra':0},{}]:
            with self.assertRaises(Problem):schema.validate(s,value)
        self.assertEqual(schema.validate(s,{'x':5}),{'x':5})
    def test_class_binding_and_integer_search_bounds(self):
        doc=json.loads(Path('examples/ocsf-file-json.ndjson').read_text())
        with self.assertRaises(Problem):Engine.normalize(self.e.packages['ocsf-process-json'],doc)
        with self.assertRaises(Problem):self.e.search('a',{'field':'extra.number','value':str(2**100)})
    def test_distributed_lossless_event_read(self):
        from nova.distributed.clients import ClickHouse
        client=object.__new__(ClickHouse)
        client.request=lambda *args,**kwargs:[{'raw':json.dumps({'payload':self.doc}),'event_id':'id'}]
        self.assertEqual(client.event('a','id')['document'],self.doc)
