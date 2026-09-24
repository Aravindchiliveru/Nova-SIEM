"""Direct journald and CloudTrail management-event acquisition into the durable spool."""
import argparse,hashlib,json,subprocess
from datetime import datetime,timezone
from .collector import Spool
from .core import Problem,canonical,timestamp
from .distributed.contracts import strict_json

class NativeSpool(Spool):
    def __init__(self,path,source,adapter):
        super().__init__(path,source,adapter)
        self.c.execute('CREATE TABLE IF NOT EXISTS native_cursor(kind TEXT PRIMARY KEY,value TEXT NOT NULL)')
        self.c.commit()
    def cursor(self,kind):
        r=self.c.execute('SELECT value FROM native_cursor WHERE kind=?',(kind,)).fetchone()
        return json.loads(r[0]) if r else None
    def commit_page(self,kind,cursor,records):
        # Cursor and records share one FULL-WAL transaction; never acknowledge upstream first.
        with self.c:
            self.c.execute('BEGIN IMMEDIATE')
            size=self.c.execute('SELECT COALESCE(SUM(bytes),0) FROM queue').fetchone()[0]
            for upstream,data in records:
                payload=canonical(data);n=len(payload.encode())
                if n>32768:raise Problem('native event exceeds 32 KiB; cursor retained',413)
                eid=hashlib.sha256(canonical([kind,upstream]).encode()).hexdigest()
                previous=self.c.execute('SELECT payload FROM queue WHERE id=?',(eid,)).fetchone()
                if previous:
                    if previous[0]!=payload:raise Problem('upstream identity changed payload',409)
                    continue
                size+=n
                if size>self.max_bytes:raise Problem('native spool full; cursor retained',429)
                self.c.execute("INSERT INTO queue(id,payload,bytes,state) VALUES(?,?,?,'pending')",(eid,payload,n))
            self.c.execute('INSERT INTO native_cursor VALUES(?,?) ON CONFLICT(kind) DO UPDATE SET value=excluded.value',(kind,canonical(cursor)))

def journal_record(r):
    if not isinstance(r,dict):raise Problem('journal record must be an object')
    cursor=r.get('__CURSOR');micros=r.get('__REALTIME_TIMESTAMP')
    if not isinstance(cursor,str) or not 1<=len(cursor)<=2048:raise Problem('journal cursor missing')
    try:
        if not isinstance(micros,str) or not micros.isdigit():raise ValueError()
        when=datetime.fromtimestamp(int(micros)/1000000,timezone.utc).isoformat()
    except (ValueError,OverflowError,OSError):raise Problem('invalid journal time')
    message=r.get('MESSAGE');host=r.get('_HOSTNAME','');exe=r.get('_EXE') or r.get('SYSLOG_IDENTIFIER')
    if not isinstance(message,str) or not isinstance(exe,str) or not exe:raise Problem('journal message or process identity missing')
    return cursor,dict(timestamp=when,action='log',target=exe,message=message,host=host,actor=str(r.get('_UID','')),original=r)

def collect_journal(spool,limit=1000,popen=subprocess.Popen):
    if spool.adapter!='process-json':raise Problem('journal requires process-json spool')
    args=['journalctl','--output=json','--no-pager','--all']
    cursor=spool.cursor('journald')
    if cursor:args+=['--after-cursor',cursor]
    proc=popen(args,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL)
    count=0
    try:
        while count<limit:
            line=proc.stdout.readline(65538)
            if not line:break
            if len(line)>65536:raise Problem('oversize journal record; cursor retained')
            key,data=journal_record(strict_json(line))
            spool.commit_page('journald',key,[(key,data)]);count+=1
        if count<limit and proc.wait(timeout=10)!=0:raise Problem('journalctl failed; inspect journal permissions/cursor')
    finally:
        if proc.poll() is None:proc.terminate()
        try:proc.wait(timeout=10)
        except subprocess.TimeoutExpired:proc.kill();proc.wait()
        proc.stdout.close()
    return count

def cloud_record(event):
    r=strict_json(event['CloudTrailEvent']);eid=r.get('eventID')
    if not isinstance(eid,str) or eid!=event.get('EventId'):raise Problem('CloudTrail event identity mismatch')
    timestamp(r.get('eventTime'))
    user=r.get('userIdentity',{});resources=r.get('resources',[])
    target=resources[0].get('ARN') if resources and isinstance(resources[0],dict) else None
    target=target or r.get('eventSource')
    if not isinstance(target,str) or not target:raise Problem('CloudTrail resource/service missing')
    data=dict(timestamp=r['eventTime'],action=r['eventName'],target=target,message=r['eventName'],actor=user.get('arn') or user.get('principalId',''),outcome='failure' if r.get('errorCode') else 'success',original=r)
    # AWS service-originated addresses may be names, not IP literals: preserve raw instead.
    import ipaddress
    try:data['src_ip']=str(ipaddress.ip_address(r.get('sourceIPAddress')))
    except ValueError:pass
    return eid,data

def collect_cloudtrail(spool,client,start,end,region):
    if spool.adapter!='cloud-json':raise Problem('CloudTrail requires cloud-json spool')
    lo,hi=timestamp(start),timestamp(end)
    if lo>=hi:raise Problem('start must precede end')
    scope=dict(start=start,end=end,region=region)
    old=spool.cursor('cloudtrail')
    if old and old['scope']!=scope:raise Problem('use a separate spool for a different CloudTrail interval/region')
    if old and old['done']:return 0
    args=dict(StartTime=datetime.fromtimestamp(lo,timezone.utc),EndTime=datetime.fromtimestamp(hi,timezone.utc),MaxResults=50)
    if old and old['token']:args['NextToken']=old['token']
    response=client.lookup_events(**args);events=response.get('Events',[])
    if len(events)>50:raise Problem('CloudTrail page exceeds bound')
    records=[]
    for event in events:
        eid,data=cloud_record(event)
        # Explicit half-open interval regardless of provider boundary semantics.
        if lo<=timestamp(data['timestamp'])<hi:records.append((eid,data))
    token=response.get('NextToken')
    if token is not None and (not isinstance(token,str) or not token):raise Problem('invalid CloudTrail continuation')
    if old and token and token==old['token']:raise Problem('CloudTrail continuation did not advance')
    spool.commit_page('cloudtrail',dict(scope=scope,token=token,done=not bool(token)),records)
    return len(records)

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('kind',choices=['journald','cloudtrail']);p.add_argument('--spool',required=True);p.add_argument('--source',required=True);p.add_argument('--start');p.add_argument('--end');p.add_argument('--region');a=p.parse_args()
    spool=NativeSpool(a.spool,a.source,'process-json' if a.kind=='journald' else 'cloud-json')
    try:
        if a.kind=='journald':print(collect_journal(spool))
        else:
            if not all([a.start,a.end,a.region]):p.error('CloudTrail requires --start, --end and --region')
            import boto3,time
            from botocore.config import Config
            client=boto3.client('cloudtrail',region_name=a.region,config=Config(connect_timeout=5,read_timeout=15,retries={'max_attempts':5,'mode':'standard'}))
            while not (spool.cursor('cloudtrail') or {}).get('done'):
                print(collect_cloudtrail(spool,client,a.start,a.end,a.region));time.sleep(.6)
    finally:spool.close()
if __name__=='__main__':main()
