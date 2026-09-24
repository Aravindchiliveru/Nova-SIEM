import io,tempfile,unittest
from datetime import datetime,timezone
from pathlib import Path
from nova.retention import ObjectLockArchive,archive_local
from nova.distributed.contracts import prepare
from nova.core import Engine,Problem
from test_core import batch

KMS='arn:aws:kms:us-east-1:123456789012:key/example'
class Conditional(Exception):
    response={'ResponseMetadata':{'HTTPStatusCode':412}}
class S3:
    def __init__(self):self.objects={};self.mode='COMPLIANCE';self.corrupt=False;self.holds={}
    def get_bucket_versioning(self,**kw):return {'Status':'Enabled'}
    def get_object_lock_configuration(self,**kw):return {'ObjectLockConfiguration':{'ObjectLockEnabled':'Enabled'}}
    def put_object(self,**kw):
        if kw['Key'] in self.objects:raise Conditional()
        self.objects[kw['Key']]=kw;return {'VersionId':'v1'}
    def head_object(self,**kw):return {'VersionId':'v1'}
    def get_object_retention(self,**kw):return {'Retention':{'Mode':self.mode,'RetainUntilDate':self.objects[kw['Key']]['ObjectLockRetainUntilDate']}}
    def get_object(self,**kw):return dict(Body=io.BytesIO(b'corrupt' if self.corrupt else self.objects[kw['Key']]['Body']),ServerSideEncryption='aws:kms',SSEKMSKeyId=KMS)
    def put_object_legal_hold(self,**kw):self.holds[(kw['Key'],kw['VersionId'])]=kw['LegalHold']
    def get_object_legal_hold(self,**kw):return {'LegalHold':self.holds[(kw['Key'],kw['VersionId'])]}

class RetentionTests(unittest.TestCase):
    def setUp(self):self.s3=S3();self.archive=ObjectLockArchive(self.s3,'bucket','123456789012',KMS,30,lambda:1000);self.raw=prepare('a',batch(),now=1000)[0]
    def test_compliance_checksum_version_and_conditional_retry(self):
        one=self.archive.put(self.raw);two=self.archive.put(self.raw);self.assertEqual(one,two);self.assertEqual(len(self.s3.objects),1)
        request=next(iter(self.s3.objects.values()));self.assertEqual(request['IfNoneMatch'],'*');self.assertEqual(request['ObjectLockMode'],'COMPLIANCE');self.assertIn('ChecksumSHA256',request)
    def test_governance_mode_not_acknowledged(self):
        self.s3.mode='GOVERNANCE'
        with self.assertRaises(Problem):self.archive.put(self.raw)
    def test_wrong_content_not_acknowledged(self):
        self.s3.corrupt=True
        with self.assertRaises(Problem):self.archive.put(self.raw)
    def test_versioning_required(self):
        self.s3.get_bucket_versioning=lambda **kw:{'Status':'Suspended'}
        with self.assertRaises(Problem):ObjectLockArchive(self.s3,'b','123456789012',KMS,30)
    def test_retention_expired_rejected(self):
        self.archive.clock=lambda:1000+31*86400
        with self.assertRaises(Problem):self.archive.put(self.raw)
        self.assertEqual(self.s3.objects,{})
    def test_hold_is_explicit_version_and_verified(self):
        result=self.archive.put(self.raw);self.assertEqual(self.archive.hold(result['key'],result['version_id'])['legal_hold'],'ON')
        with self.assertRaises(Problem):self.archive.hold(result['key'],'null')
    def test_local_receipt_written_only_after_verification(self):
        with tempfile.TemporaryDirectory() as d:
            e=Engine(Path(d)/'db');e.ingest('a','collector',batch());self.s3.corrupt=True
            with self.assertRaises(Problem):archive_local(e,self.archive)
            with e.connect() as c:self.assertEqual(c.execute('SELECT COUNT(*) FROM nova_archive_receipts').fetchone()[0],0)
            self.s3.corrupt=False;self.assertEqual(archive_local(e,self.archive),1);self.assertEqual(archive_local(e,self.archive),0)
    def test_remote_archive_batch_failure_does_not_mark_metadata(self):
        from nova.distributed.main import LockedSink
        class Archive:
            def put(self,row):raise RuntimeError('remote unavailable')
        class Meta:
            called=False
            def locked(self,*args):self.called=True
        meta=Meta()
        with self.assertRaises(RuntimeError):LockedSink(Archive(),meta).write([self.raw])
        self.assertFalse(meta.called)
    def test_remote_archive_pins_version_receipts(self):
        from nova.distributed.main import LockedSink
        parent=self
        class Meta:
            rows=None
            def locked(self,rows,receipts):self.rows=rows;self.receipts=receipts
        meta=Meta();LockedSink(self.archive,meta).write([self.raw]);self.assertEqual(meta.receipts[0]['version_id'],'v1');self.assertEqual(meta.rows,[self.raw])
