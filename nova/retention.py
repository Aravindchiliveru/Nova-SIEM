"""S3 Object Lock COMPLIANCE archive. Remote verification precedes acknowledgement."""
import base64,hashlib,time
from datetime import datetime,timezone,timedelta
from .core import Problem,canonical
from .distributed.contracts import validate_raw

class ObjectLockArchive:
    def __init__(self,client,bucket,owner,kms_key,days,clock=time.time):
        if not isinstance(owner,str) or len(owner)!=12 or not owner.isdigit():raise Problem('12-digit bucket owner required')
        if not isinstance(kms_key,str) or (not kms_key.startswith('arn:aws:kms:') or ':key/' not in kms_key):raise Problem('full AWS KMS key ARN required')
        if type(days) is not int or not 1<=days<=36500:raise Problem('retention days must be 1..36500')
        self.client,self.bucket,self.owner,self.kms,self.days,self.clock=client,bucket,owner,kms_key,days,clock
        cfg=dict(Bucket=bucket,ExpectedBucketOwner=owner)
        if client.get_bucket_versioning(**cfg).get('Status')!='Enabled':raise Problem('archive bucket must enable versioning')
        if client.get_object_lock_configuration(**cfg).get('ObjectLockConfiguration',{}).get('ObjectLockEnabled')!='Enabled':raise Problem('archive bucket must enable Object Lock')
    def args(self,key,version=None):
        out=dict(Bucket=self.bucket,Key=key,ExpectedBucketOwner=self.owner)
        if version:out['VersionId']=version
        return out
    def verify(self,key,version,data,until):
        if not isinstance(version,str) or not version or version=='null':raise Problem('archive object lacks a version')
        args=self.args(key,version)
        retention=self.client.get_object_retention(**args).get('Retention',{})
        if retention.get('Mode')!='COMPLIANCE' or retention.get('RetainUntilDate',datetime.min.replace(tzinfo=timezone.utc))<until:raise Problem('archive retention verification failed')
        obj=self.client.get_object(**args)
        if obj.get('ServerSideEncryption')!='aws:kms' or obj.get('SSEKMSKeyId')!=self.kms:raise Problem('archive encryption verification failed')
        body=obj['Body']
        try:actual=body.read(len(data)+1)
        finally:body.close()
        if actual!=data:raise Problem('archive content verification failed')
        return dict(key=key,version_id=version,sha256=hashlib.sha256(data).hexdigest(),retain_until=retention['RetainUntilDate'].isoformat())
    def put(self,raw):
        validate_raw(raw);data=canonical(raw).encode();digest=hashlib.sha256(data).digest()
        tenant=hashlib.sha256(raw['tenant'].encode()).hexdigest();key=f'nova/{tenant}/{raw["event_id"]}/{digest.hex()}.json'
        until=datetime.fromtimestamp(raw['received'],timezone.utc)+timedelta(days=self.days)
        if until<=datetime.fromtimestamp(self.clock(),timezone.utc):raise Problem('record is already beyond configured retention interval')
        args=self.args(key)
        try:
            result=self.client.put_object(**args,Body=data,ContentType='application/json',IfNoneMatch='*',ChecksumAlgorithm='SHA256',ChecksumSHA256=base64.b64encode(digest).decode(),ServerSideEncryption='aws:kms',SSEKMSKeyId=self.kms,ObjectLockMode='COMPLIANCE',ObjectLockRetainUntilDate=until)
            version=result.get('VersionId')
        except Exception as exc:
            # Only explicit conditional conflicts can reuse an existing object.
            if getattr(exc,'response',{}).get('ResponseMetadata',{}).get('HTTPStatusCode')!=412:raise
            version=self.client.head_object(**args).get('VersionId')
        return self.verify(key,version,data,until)
    def write(self,rows):
        for row in rows:self.put(row)
    def hold(self,key,version):
        if not isinstance(version,str) or not version or version=='null':raise Problem('explicit version required')
        args=self.args(key,version);self.client.put_object_legal_hold(**args,LegalHold={'Status':'ON'})
        if self.client.get_object_legal_hold(**args).get('LegalHold',{}).get('Status')!='ON':raise Problem('legal hold verification failed')
        return dict(key=key,version_id=version,legal_hold='ON')
    @classmethod
    def from_environment(cls):
        import boto3,os
        from botocore.config import Config
        client=boto3.client('s3',config=Config(connect_timeout=5,read_timeout=20,retries={'max_attempts':3,'mode':'standard'}))
        return cls(client,os.environ['NOVA_ARCHIVE_BUCKET'],os.environ['NOVA_ARCHIVE_OWNER'],os.environ['NOVA_ARCHIVE_KMS_ARN'],int(os.environ['NOVA_RETENTION_DAYS']))

def archive_local(engine,archive,limit=200):
    import json
    with engine.tx() as c:
        c.execute('CREATE TABLE IF NOT EXISTS nova_archive_receipts(tenant TEXT,event_id TEXT,receipt TEXT,PRIMARY KEY(tenant,event_id))')
        rows=[dict(r) for r in c.execute('SELECT r.* FROM raw_events r WHERE NOT EXISTS (SELECT 1 FROM nova_archive_receipts a WHERE a.tenant=r.tenant AND a.event_id=r.event_id) ORDER BY r.seq LIMIT ?',(limit,))]
    for r in rows:
        raw=dict(contract='nova.raw.v1',tenant=r['tenant'],event_id=r['event_id'],source=r['source'],integration=r['integration'],digest=r['digest'],received=r['received'],payload=json.loads(r['payload']),package_digest='',replay_generation=0)
        receipt=archive.put(raw)
        with engine.tx() as c:
            new=c.execute('INSERT OR IGNORE INTO nova_archive_receipts VALUES(?,?,?) RETURNING event_id',(r['tenant'],r['event_id'],canonical(receipt))).fetchone()
            if new:engine.audit(c,r['tenant'],'archive','archive.locked',receipt)
    return len(rows)

def main():
    import argparse
    from .core import Engine
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--db',required=True);a=p.parse_args()
    archive=ObjectLockArchive.from_environment();e=Engine(a.db)
    while archive_local(e,archive):pass
if __name__=='__main__':main()
