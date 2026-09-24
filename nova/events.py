"""Nova native typed events. This is not an OCSF compatibility claim."""
import ipaddress
from .core import Problem, timestamp

CATEGORIES={'authentication','process','network','dns','file','cloud'}
TEXT_FIELDS={'actor','ip','outcome','message','action','host','target'}

def validate_package(p):
    mapping=p.get('mapping')
    if p.get('category') not in CATEGORIES-{'authentication'}:
        raise ValueError('unsupported typed category')
    if not isinstance(mapping,dict) or set(mapping)-TEXT_FIELDS-{'time'} or not {'time','action','message','target'}<=set(mapping):
        raise ValueError('typed mapping requires time, action, message and target')
    optional=p.get('optional',[])
    if not isinstance(optional,list) or any(k not in {'actor','ip','host','outcome'} or k not in mapping for k in optional):
        raise ValueError('invalid optional mappings')
    if any(not isinstance(v,str) or not 1<=len(v)<=128 for v in mapping.values()):
        raise ValueError('invalid mapped field')

def validate_fields(n):
    if n.get('category') not in CATEGORIES:raise Problem('invalid event category')
    for key in TEXT_FIELDS:
        if not isinstance(n.get(key),str) or len(n[key])>8192:raise Problem('invalid '+key)
    if not n['action'] or len(n['action'])>128:raise Problem('action requires 1 to 128 characters')
    if len(n['actor'])>256 or len(n['host'])>256:raise Problem('actor or host exceeds 256 characters')
    if n['outcome'] not in ('success','failure','unknown'):raise Problem('invalid outcome')
    if n['ip']:
        try:ipaddress.ip_address(n['ip'])
        except ValueError:raise Problem('invalid source IP')
    if n['category']=='authentication' and (not n['actor'] or not n['ip'] or n['outcome']=='unknown'):
        raise Problem('authentication requires actor, IP and known outcome')
    if n['category']!='authentication' and not n['target']:raise Problem('typed event requires target')
    return n

def normalize(p,payload):
    validate_package(p)
    values={k:'' for k in TEXT_FIELDS};values['outcome']='unknown'
    for k,field in p['mapping'].items():
        if field not in payload:
            if k in p.get('optional',[]):continue
            raise Problem('missing field: '+field)
        values[k]=payload[field]
    values['event_time']=timestamp(values.pop('time'))
    values['category']=p['category']
    validate_fields(values)
    if values['ip']:values['ip']=str(ipaddress.ip_address(values['ip']))
    return values
