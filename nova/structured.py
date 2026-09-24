"""Lossless JSON documents and bounded, typed nested-field search."""
import json,re,math
from .core import Problem

def path(value):
    if not isinstance(value,str) or len(value)>512:raise Problem('invalid field path')
    parts=value.split('.')
    if not 1<=len(parts)<=16 or any(not re.fullmatch(r'[A-Za-z_][A-Za-z_0-9-]{0,127}|0|[1-9][0-9]{0,3}',p) for p in parts):raise Problem('field path requires identifiers or array indexes')
    return parts

def get(document,parts):
    value=document
    for p in parts:
        if isinstance(value,list) and p.isdigit():
            i=int(p)
            if i>=len(value):raise KeyError(p)
            value=value[i]
        elif isinstance(value,dict) and not p.isdigit():value=value[p]
        else:raise KeyError(p)
    return value

def predicate(params):
    if params.get('include_document','false') not in ('true','false'):raise Problem('include_document requires true/false')
    if 'field' not in params:
        if 'value' in params or 'exists' in params:raise Problem('field required')
        return None
    parts=path(params['field'])
    if ('value' in params)==('exists' in params):raise Problem('provide value or exists, exclusively')
    if 'exists' in params:
        if params['exists'] not in ('true','false'):raise Problem('exists requires true/false')
        return parts,'exists',params['exists']=='true'
    raw=params['value']
    if not isinstance(raw,str) or len(raw)>8192:raise Problem('invalid field value')
    try:value=json.loads(raw,parse_constant=lambda x:(_ for _ in ()).throw(ValueError()))
    except (ValueError,RecursionError):raise Problem('value requires a JSON scalar') from None
    if isinstance(value,(dict,list)) or isinstance(value,float) and not math.isfinite(value):raise Problem('value requires a finite JSON scalar')
    if type(value) is int and not -(2**63)<=value<2**63:raise Problem('search integer must fit signed 64 bits')
    return parts,'equal',value

def sqlite_clause(params):
    pred=predicate(params)
    if pred is None:return [],[]
    parts,op,value=pred;jpath='$'+''.join('['+p+']' if p.isdigit() else '."'+p+'"' for p in parts)
    if op=='exists':return ['json_type(r.payload,?) IS '+('NOT NULL' if value else 'NULL')],[jpath]
    kind='null' if value is None else 'true' if value is True else 'false' if value is False else 'integer' if type(value) is int else 'real' if type(value) is float else 'text'
    clauses=['json_type(r.payload,?)=?'];args=[jpath,kind]
    if value is not None:clauses.append('json_extract(r.payload,?)=?');args.extend([jpath,value])
    return clauses,args

def decode(row):
    result=dict(row)
    if 'document' in result and isinstance(result['document'],str):result['document']=json.loads(result['document'])
    return result

def clickhouse_clause(params):
    pred=predicate(params)
    if pred is None:return [],{}
    parts,op,value=pred;bindings={};items=["'payload'"]
    for i,p in enumerate(parts):
        key='field_path_'+str(i);items.append('{'+key+(':UInt32}' if p.isdigit() else ':String}'));bindings[key]=int(p)+1 if p.isdigit() else p
    args=','.join(items)
    if op=='exists':return ['JSONHas(raw,'+args+')='+('1' if value else '0')],bindings
    # Raw scalar encoding keeps false distinct from zero and null from absence.
    bindings['field_value']=json.dumps(value,ensure_ascii=False,separators=(',',':'),allow_nan=False)
    return ['JSONHas(raw,'+args+')=1','JSONExtractRaw(raw,'+args+')={field_value:String}'],bindings
