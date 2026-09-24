"""OCSF 1.4.0 Authentication: Logon projection. Not a full schema validator."""
import math,ipaddress
from .core import Problem
from .events import validate_fields
VERSION='1.4.0'

def normalize(event):
    if not isinstance(event,dict):raise Problem('OCSF object required')
    for key,value in [('class_uid',3002),('category_uid',3),('activity_id',1),('type_uid',300201)]:
        if type(event.get(key)) is not int or event[key]!=value:raise Problem('supported OCSF class/activity: 3002/1 only')
    metadata=event.get('metadata')
    if not isinstance(metadata,dict) or metadata.get('version')!=VERSION:raise Problem('OCSF metadata.version must be 1.4.0')
    product=metadata.get('product')
    if not isinstance(product,dict) or any(not isinstance(product.get(k),str) or not product[k] for k in ('name','vendor_name')):raise Problem('OCSF product name/vendor_name required')
    when=event.get('time');severity=event.get('severity_id');status=event.get('status_id')
    if type(when) is not int or not 0<=when<=253402300799999:raise Problem('OCSF time requires bounded integer epoch milliseconds')
    if type(severity) is not int or severity not in range(7) and severity!=99:raise Problem('invalid OCSF severity')
    if type(status) is not int or status not in (1,2):raise Problem('OCSF logon requires success/failure status')
    user=event.get('user');endpoint=event.get('src_endpoint');device=event.get('device',{})
    if not isinstance(user,dict) or not isinstance(endpoint,dict) or not isinstance(device,dict):raise Problem('OCSF user/src_endpoint/device must be objects')
    n=dict(category='authentication',action='login',event_time=when/1000,actor=user.get('name') or user.get('uid'),ip=endpoint.get('ip'),host=device.get('hostname',''),target='',outcome='success' if status==1 else 'failure',message=event.get('message',''))
    validate_fields(n)
    n['ip']=str(ipaddress.ip_address(n['ip']))
    return n

def export(event):
    document=event.get('document')
    if document is not None and event.get('parser') in ('ocsf-auth-json','ocsf-process-json','ocsf-file-json'):
        normalize(document) if document.get('class_uid')==3002 else normalize_system(document)
        import copy
        return copy.deepcopy(document)
    n=dict(event);validate_fields(n)
    if n['category']!='authentication' or n['action']!='login':raise Problem('only authentication/login OCSF export supported')
    if type(n.get('event_time')) not in (int,float) or not math.isfinite(n['event_time']):raise Problem('invalid event time')
    out=dict(class_uid=3002,category_uid=3,activity_id=1,type_uid=300201,time=round(n['event_time']*1000),severity_id=0,status_id=1 if n['outcome']=='success' else 2,user={'name':n['actor']},src_endpoint={'ip':n['ip']},message=n['message'],metadata={'version':VERSION,'product':{'name':'Nova SIEM','vendor_name':'Nova'},'uid':n.get('event_id','')})
    if not out['metadata']['uid']:del out['metadata']['uid']
    if n['host']:out['device']={'hostname':n['host'],'type_id':0}
    normalize(out)
    return out

# Explicit Nova projection profiles. These are not full upstream OCSF schemas.
def normalize_system(event,expected_class=None):
    if not isinstance(event,dict):raise Problem('OCSF object required')
    cls=event.get('class_uid')
    if expected_class is not None and cls!=expected_class:raise Problem('OCSF class differs from package binding')
    if type(cls) is not int or cls not in (1001,1007):raise Problem('supported system classes: 1001 and 1007')
    for key,value in [('category_uid',1),('activity_id',1),('type_uid',cls*100+1)]:
        if type(event.get(key)) is not int or event[key]!=value:raise Problem('system profile requires create/launch activity 1')
    metadata=event.get('metadata',{});product=metadata.get('product',{}) if isinstance(metadata,dict) else {}
    if not isinstance(metadata,dict) or metadata.get('version')!=VERSION or not isinstance(product,dict) or any(not isinstance(product.get(k),str) or not product[k] for k in ('name','vendor_name')):raise Problem('OCSF 1.4.0 product metadata required')
    when=event.get('time');severity=event.get('severity_id');status=event.get('status_id',0)
    if type(when) is not int or not 0<=when<=253402300799999:raise Problem('bounded epoch milliseconds required')
    if type(severity) is not int or severity not in (*range(7),99):raise Problem('invalid severity')
    if type(status) is not int or status not in (0,1,2,99):raise Problem('invalid status')
    actor=event.get('actor',{});device=event.get('device',{})
    if not isinstance(actor,dict) or not isinstance(device,dict):raise Problem('actor/device objects required')
    user=actor.get('user',{})
    if not isinstance(user,dict):raise Problem('actor.user object required')
    obj=event.get('process',{}) if cls==1007 else event
    if not isinstance(obj,dict) or not isinstance(obj.get('file'),dict):raise Problem('file object required')
    file=obj['file']
    if type(file.get('type_id')) is not int or file['type_id']!=1:raise Problem('file.type_id required')
    n=dict(category='process' if cls==1007 else 'file',action='start' if cls==1007 else 'create',event_time=when/1000,actor=user.get('name',user.get('uid','')),ip='',host=device.get('hostname',''),target=file.get('path'),outcome={1:'success',2:'failure'}.get(status,'unknown'),message=event.get('message',''))
    return validate_fields(n)
