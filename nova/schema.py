"""Nova schema v1: bounded typed object validation, not a JSON Schema implementation."""
import math
from .core import Problem,canonical
TYPES={'object','array','string','integer','number','boolean','null'}

def check(schema,depth=0,budget=None):
    budget=[0] if budget is None else budget;budget[0]+=1
    if depth>16 or budget[0]>512 or not isinstance(schema,dict):raise Problem('schema exceeds bounds')
    if set(schema)-{'type','properties','required','additional','items','enum','min','max','max_length','max_items'} or schema.get('type') not in TYPES:raise Problem('unsupported schema keyword/type')
    kind=schema['type'];allowed={'type','enum'}|({'properties','required','additional'} if kind=='object' else {'items','max_items'} if kind=='array' else {'max_length'} if kind=='string' else {'min','max'} if kind in ('integer','number') else set())
    if set(schema)-allowed:raise Problem('schema keyword incompatible with type')
    if 'enum' in schema and (not isinstance(schema['enum'],list) or not 1<=len(schema['enum'])<=100):raise Problem('bounded enum required')
    for k in ('min','max'):
        if k in schema and (type(schema[k]) not in (int,float) or (type(schema[k]) is float and not math.isfinite(schema[k]))):raise Problem('finite schema limit required')
    if 'min' in schema and 'max' in schema and schema['min']>schema['max']:raise Problem('inverted schema range')
    for k,maximum in [('max_length',32768),('max_items',1000)]:
        if k in schema and (type(schema[k]) is not int or not 0<=schema[k]<=maximum):raise Problem('invalid schema bound')
    if kind=='object':
        props=schema.get('properties',{});required=schema.get('required',[])
        if not isinstance(props,dict) or len(props)>128 or any(not isinstance(k,str) or len(k)>128 for k in props):raise Problem('invalid properties')
        if not isinstance(required,list) or any(not isinstance(k,str) or k not in props for k in required):raise Problem('required must reference properties')
        if 'additional' in schema and type(schema['additional']) is not bool:raise Problem('additional requires boolean')
        for child in props.values():check(child,depth+1,budget)
    if kind=='array':
        if 'items' not in schema:raise Problem('array items schema required')
        check(schema['items'],depth+1,budget)
    return schema

def validate(schema,value,location='$',depth=0):
    if depth>16:raise Problem('document schema depth exceeded')
    kind=schema['type'];valid={'object':isinstance(value,dict),'array':isinstance(value,list),'string':isinstance(value,str),'integer':type(value) is int,'number':type(value) in (int,float),'boolean':type(value) is bool,'null':value is None}[kind]
    if not valid:raise Problem('schema type mismatch at '+location)
    if 'enum' in schema and canonical(value) not in [canonical(v) for v in schema['enum']]:raise Problem('schema enum mismatch at '+location)
    if kind in ('number','integer'):
        if (type(value) is float and not math.isfinite(value)) or 'min' in schema and value<schema['min'] or 'max' in schema and value>schema['max']:raise Problem('schema numeric range at '+location)
    if kind=='string' and len(value)>schema.get('max_length',32768):raise Problem('schema string length at '+location)
    if kind=='array':
        if len(value)>schema.get('max_items',1000):raise Problem('schema array length at '+location)
        for i,item in enumerate(value):validate(schema['items'],item,location+'.'+str(i),depth+1)
    if kind=='object':
        props=schema.get('properties',{})
        if any(k not in value for k in schema.get('required',[])):raise Problem('schema required field at '+location)
        if schema.get('additional',True) is False and set(value)-set(props):raise Problem('schema additional field at '+location)
        for key,child in props.items():
            if key in value:validate(child,value[key],location+'.'+key,depth+1)
    return value

def normalize(package,payload):
    from .structured import path,get
    from .events import normalize as native
    validate(package['schema'],payload)
    flat={};mapping=package['mapping']
    for key,name in mapping.items():
        try:flat[key]=get(payload,path(name))
        except KeyError:
            if key not in package.get('optional',[]):raise Problem('missing mapped field: '+name) from None
    projected=dict(package,format='nova.mapping.v2',mapping={k:k for k in mapping})
    return native(projected,flat)

def validate_package(package):
    from .structured import path
    from .events import validate_package as native
    native(package);check(package.get('schema'))
    if package['schema']['type']!='object':raise Problem('root schema must be object')
    for value in package['mapping'].values():path(value)
