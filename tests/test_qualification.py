import copy,importlib.util,json,unittest
from pathlib import Path
from unittest.mock import patch
from test_retention import S3,KMS
from nova.retention import ObjectLockArchive

def module(name):
    spec=importlib.util.spec_from_file_location(name,Path('tools')/(name+'.py'));mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod);return mod
ret=module('qualify_retention');ha=module('qualify_ha')
class Denied(Exception):
    response={'Error':{'Code':'AccessDenied'},'ResponseMetadata':{'HTTPStatusCode':403,'RequestId':'test-request'}}
class QualificationTests(unittest.TestCase):
    def test_network_failure_is_not_retention_proof(self):
        def timeout():raise TimeoutError()
        self.assertFalse(ret.denied(timeout)['denied']);self.assertFalse(ret.denied(lambda:None)['denied'])
    def test_retention_probe_uses_exact_version_and_rechecks_content(self):
        s3=S3();seen=[]
        def deny(**args):seen.append(args);raise Denied()
        s3.delete_object=deny;s3.put_object_retention=deny
        result=ret.execute(ObjectLockArchive(s3,'b','123456789012',KMS,30))
        self.assertTrue(result['writer_checks_passed']);self.assertFalse(result['remote_enforcement_independently_proven'])
        self.assertEqual(len(s3.objects),1);self.assertTrue(all(x['VersionId']=='v1' for x in seen))
    def test_ha_requires_independent_fault_verifier(self):
        cfg=json.loads(Path('deploy/ha/qualification.example.json').read_text());ha.validate(cfg)
        del cfg['scenarios'][0]['verify_fault_argv']
        with self.assertRaises(ValueError):ha.validate(cfg)
    def test_ha_writes_and_checks_during_fault_before_cleanup(self):
        cfg=json.loads(Path('deploy/ha/qualification.example.json').read_text());seen={};commands=[];fault=False
        def run(args,**kw):
            nonlocal fault
            commands.append(args)
            if 'verify-fault' in args[0]:self.assertTrue(fault)
            elif 'recover' in args[0]:fault=False
            else:fault=True
        def call(origin,path,token,body=None):
            if path.endswith('/activate'):return {}
            if path=='/api/events':
                import hashlib
                ids=[hashlib.sha256(json.dumps([body['source'],e['id']],separators=(',',':')).encode()).hexdigest() for e in body['events']]
                duplicate=sum(e in seen for e in ids)
                if body['events'][0]['id']=='10':self.assertTrue(fault)
                seen.update({e:True for e in ids});return dict(event_ids=ids,accepted=len(ids)-duplicate,duplicates=duplicate)
            if path.startswith('/api/event?'):return dict(normalized={'x':1},receipt={k:1 for k in ('normalized_at','indexed_at','detected_at','archived_at','locked_at')})
            if path=='/api/alerts':return [dict(evidence=json.dumps(list(seen)))]
            raise AssertionError(path)
        with patch.object(ha.Path,'read_text',return_value='token'),patch.object(ha.subprocess,'run',side_effect=run),patch.object(ha,'call',side_effect=call):result=ha.execute(cfg)
        self.assertTrue(result['all_scenarios_passed']);self.assertFalse(result['production_ha_dr_proven'])
        self.assertTrue(all(x['acknowledged_during_fault']==10 for x in result['scenarios']))
