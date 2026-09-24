import copy,json,tempfile,unittest
from pathlib import Path
from nova.core import Engine,Problem
from nova import sigma,ocsf
from nova.rules import Rules

class InteropTests(unittest.TestCase):
    def binding(self):return dict(logsource={'category':'process_creation','product':'linux'},match={'category':['process'],'action':['start'],'source':['linux-agent']},fields={'Image':'target','User':'actor'})
    def rule(self):return dict(title='Shell by service account',logsource=self.binding()['logsource'],detection={'image':{'Image|endswith':'/SH'},'user':{'User':'root'},'condition':'image and not user'},level='high')
    def event(self,**kw):
        e=dict(source='linux-agent',category='process',action='start',actor='alice',host='h',target='/bin/sh',ip='',outcome='unknown',message='',event_time=1);e.update(kw);return e
    def test_case_insensitive_boolean_semantics(self):
        rule=sigma.compile_rule(self.rule(),self.binding());rule['enabled']=True
        self.assertTrue(Rules.matches(rule,self.event()));self.assertFalse(Rules.matches(rule,self.event(actor='ROOT')))
        self.assertFalse(Rules.matches(rule,self.event(source='unbound')))
    def test_or_parentheses_precedence(self):
        r=self.rule();r['detection']['condition']='(image or user) and not user'
        compiled=sigma.compile_rule(r,self.binding());compiled['enabled']=True
        self.assertTrue(Rules.matches(compiled,self.event()));self.assertFalse(Rules.matches(compiled,self.event(actor='root')))
    def test_unsupported_syntax_fails_closed(self):
        for selection in [{'Image|re':'.*'},{'Missing':'x'},{'Image|contains|endswith':'sh'}]:
            r=self.rule();r['detection']['image']=selection
            with self.subTest(selection=selection),self.assertRaises(Problem):sigma.compile_rule(r,self.binding())
        for text in ['2 of them','image | count() > 1','missing','image and','image)']:
            r=self.rule();r['detection']['condition']=text
            with self.subTest(text=text),self.assertRaises(Problem):sigma.compile_rule(r,self.binding())
    def test_requires_exact_logsource_binding(self):
        r=self.rule();r['logsource']['product']='windows'
        with self.assertRaises(Problem):sigma.compile_rule(r,self.binding())
    def test_import_disabled_and_executes_installed_rule(self):
        with tempfile.TemporaryDirectory() as d:
            r=sigma.compile_rule(self.rule(),self.binding());self.assertFalse(r['enabled']);r['enabled']=True
            rules=Path(d)/'rules';rules.mkdir();(rules/'sigma.json').write_text(json.dumps(r))
            e=Engine(Path(d)/'db',rule_dir=rules);e.activate('a','admin','process-json')
            e.ingest('a','collector',dict(source='linux-agent',integration='process-json',events=[dict(id='1',data=dict(timestamp='2026-09-21T12:00:00Z',action='start',target='/bin/sh',message='start',actor='alice'))]));e.drain()
            self.assertEqual(e.listing('a','alerts')[0]['rule'],r['id'])
    def test_yaml_duplicates_and_aliases_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'rule.yml'
            for text in ['title: a\ntitle: b\n','a: &x hi\nb: *x\n','!!python/object/apply:os.system [echo forbidden]']:
                p.write_text(text)
                with self.assertRaises(Exception):sigma.load_yaml(p)
    def ocsf(self):return json.loads(Path('examples/ocsf-auth.ndjson').read_text())
    def test_ocsf_roundtrip_and_exact_time(self):
        n=ocsf.normalize(self.ocsf());out=ocsf.export(n);self.assertEqual(out['time'],self.ocsf()['time']);self.assertEqual(ocsf.normalize(out),n)
    def test_ocsf_semantic_mismatch_rejected(self):
        for change in [dict(type_uid=300202),dict(activity_id=2),dict(class_uid=4001),dict(time=True),dict(status_id=0),dict(metadata={'version':'9.0'})]:
            with self.subTest(change=change),self.assertRaises(Problem):ocsf.normalize(self.ocsf()|change)
    def test_ocsf_ingestion_retains_original(self):
        with tempfile.TemporaryDirectory() as d:
            e=Engine(Path(d)/'db');e.activate('a','admin','ocsf-auth-json')
            result=e.ingest('a','c',dict(source='ocsf',integration='ocsf-auth-json',events=[dict(id='1',data=self.ocsf())]));e.drain()
            row=e.event('a',result['event_ids'][0]);self.assertEqual(json.loads(row['raw']['payload']),self.ocsf());self.assertEqual(row['normalized']['category'],'authentication')
