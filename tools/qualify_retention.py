"""Live S3 retention probe. Writes only a unique synthetic object; never cleans it up."""
import argparse,json,sys,time,uuid
from datetime import datetime,timezone,timedelta
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from nova.core import canonical
from nova.retention import ObjectLockArchive
from nova.distributed.contracts import prepare

def denied(operation):
    try:operation()
    except Exception as exc:
        response=getattr(exc,'response',{});code=response.get('Error',{}).get('Code');status=response.get('ResponseMetadata',{}).get('HTTPStatusCode')
        return {'denied':status==403 and code=='AccessDenied','http_status':status,'aws_code':code,'request_id':response.get('ResponseMetadata',{}).get('RequestId')}
    return {'denied':False,'error':'mutation succeeded'}

def execute(archive):
    run=uuid.uuid4().hex
    body=dict(source='retention-qualification',integration='auth-json',events=[dict(id=run,data=dict(timestamp=datetime.now(timezone.utc).isoformat(),user='synthetic',src_ip='192.0.2.1',status='failure',message='Synthetic retention qualification'))])
    raw=prepare('retention-qualification',body)[0]
    receipt=archive.put(raw);again=archive.put(raw)
    if receipt!=again:raise RuntimeError('conditional retry did not reuse verified object version')
    args=archive.args(receipt['key'],receipt['version_id'])
    deletion=denied(lambda:archive.client.delete_object(**args))
    shortening=denied(lambda:archive.client.put_object_retention(**args,Retention={'Mode':'COMPLIANCE','RetainUntilDate':datetime.now(timezone.utc)+timedelta(seconds=60)}))
    intact=False
    try:
        archive.verify(receipt['key'],receipt['version_id'],canonical(raw).encode(),datetime.fromisoformat(receipt['retain_until']));intact=True
    except Exception:pass
    # Denial may result from IAM alone. Do not mistake it for an independently isolated Object Lock test.
    return dict(scope='writer-principal observation, not IAM-independent proof',run_id=run,receipt=receipt,delete_version=deletion,shorten_retention=shortening,content_intact=intact,writer_checks_passed=deletion['denied'] and shortening['denied'] and intact,remote_enforcement_independently_proven=False)

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--execute-isolated-probe',action='store_true');p.add_argument('--output',required=True);a=p.parse_args()
    # Refuse overwriting reports before making any external changes.
    with open(a.output,'x') as f:
        if a.execute_isolated_probe:
            try:result=execute(ObjectLockArchive.from_environment())
            except Exception as exc:result={'status':'failed','error_type':type(exc).__name__,'remote_enforcement_independently_proven':False}
        else:result={'status':'not_run','reason':'Use a dedicated test bucket; --execute-isolated-probe writes a COMPLIANCE object that persists until expiry','remote_enforcement_independently_proven':False}
        json.dump(result,f,indent=2)
    print(json.dumps(result,indent=2));return 0 if result.get('writer_checks_passed') else 2
if __name__=='__main__':raise SystemExit(main())
