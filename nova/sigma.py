"""Fail-closed Sigma subset compiler; exact configured logsource binding, no eval."""
import argparse,hashlib,json,re,ipaddress
from functools import lru_cache
from pathlib import Path
from .core import Problem,canonical
FIELDS={'source','actor','ip','outcome','message','category','action','host','target'}
MODES={'exact','contains','startswith','endswith','exists','present','null','cidr','fieldref'}

def validate_node(n,depth=0,budget=None):
    budget=[0] if budget is None else budget;budget[0]+=1
    if depth>16 or budget[0]>256 or not isinstance(n,dict):raise Problem('Sigma expression budget exceeded')
    op=n.get('op')
    if op in ('and','or'):
        if set(n)!={'op','args'} or not isinstance(n['args'],list) or not 1<=len(n['args'])<=100:raise Problem('invalid Sigma operands')
        for child in n['args']:validate_node(child,depth+1,budget)
    elif op=='not':
        if set(n)!={'op','arg'}:raise Problem('invalid Sigma not')
        validate_node(n['arg'],depth+1,budget)
    elif op=='field':
        if set(n)-{'op','field','mode','values','all','cased'} or not {'op','field','mode','values','all'}<=set(n) or n['field'] not in FIELDS or n['mode'] not in MODES or type(n['all']) is not bool:raise Problem('invalid Sigma field')
        if 'cased' in n and (type(n['cased']) is not bool or n['mode'] not in ('exact','contains','startswith','endswith','fieldref')):raise Problem('invalid cased modifier')
        values=n['values']
        if not isinstance(values,list) or not 1<=len(values)<=100:raise Problem('invalid Sigma values')
        if n['mode'] in ('exists','present'):
            if len(values)!=1 or type(values[0]) is not bool or n['all']:raise Problem('exists requires one boolean')
        elif n['mode']=='null':
            if values!=[None] or n['all']:raise Problem('null requires one null')
        elif any(not isinstance(x,str) or len(x)>256 for x in values):raise Problem('Sigma string exceeds bound')
        if n['mode']=='cidr':
            for value in values:
                try:network(value)
                except ValueError:raise Problem('invalid CIDR network') from None
        if n['mode']=='fieldref' and any(x not in FIELDS for x in values):raise Problem('unmapped field reference')
    else:raise Problem('unsupported Sigma expression')
    return n

@lru_cache(maxsize=4096)
def pattern_tokens(pattern,mode='exact',case_sensitive=False):
    # Tokenize Sigma escapes, preserving ordinary Windows path separators.
    if not case_sensitive:pattern=pattern.lower()
    tokens=[];i=0
    if mode in ('contains','endswith'):tokens.append(('*',None))
    while i<len(pattern):
        c=pattern[i];i+=1
        if c=='\\' and i<len(pattern) and pattern[i] in '*?\\':
            tokens.append(('literal',pattern[i]));i+=1
        elif c in '*?':tokens.append((c,None))
        else:tokens.append(('literal',c))
    if mode in ('contains','startswith'):tokens.append(('*',None))
    return tuple(tokens)

def wildcard(value,pattern,mode='exact',case_sensitive=False):
    # Greedy glob algorithm: no regex backtracking, bounded O(text * pattern).
    tokens=pattern_tokens(pattern,mode,case_sensitive);value=value if case_sensitive else value.lower();i=j=0;star=-1;restart=0
    while i<len(value):
        if j<len(tokens) and (tokens[j][0]=='?' or tokens[j]==('literal',value[i])):i+=1;j+=1
        elif j<len(tokens) and tokens[j][0]=='*':star=j;j+=1;restart=i
        elif star>=0:restart+=1;i=restart;j=star+1
        else:return False
    while j<len(tokens) and tokens[j][0]=='*':j+=1
    return j==len(tokens)

@lru_cache(maxsize=4096)
def network(value):
    if '/' not in value:raise ValueError('CIDR prefix required')
    return ipaddress.ip_network(value,strict=False)

def evaluate(n,event):
    op=n['op']
    if op=='and':return all(evaluate(x,event) for x in n['args'])
    if op=='or':return any(evaluate(x,event) for x in n['args'])
    if op=='not':return not evaluate(n['arg'],event)
    value=event.get(n['field']);mode=n['mode']
    if mode=='exists':return (n['field'] in event and value is not None)==n['values'][0]
    if mode=='present':return (n['field'] in event)==n['values'][0]
    if mode=='null':return value is None
    if not isinstance(value,str):return False
    if mode=='cidr':
        try:address=ipaddress.ip_address(value)
        except ValueError:return False
        checks=(address in network(x) for x in n['values'])
    elif mode=='fieldref':
        checks=((isinstance(event.get(x),str) and (value==event[x] if n.get('cased') else value.lower()==event[x].lower())) for x in n['values'])
    else:checks=(wildcard(value,x,mode,case_sensitive=n.get('cased',False)) for x in n['values'])
    return all(checks) if n['all'] else any(checks)

def selection(s,fieldmap):
    if isinstance(s,list):
        if not s or len(s)>100 or any(not isinstance(x,dict) for x in s):raise Problem('only map-list Sigma selections supported')
        return {'op':'or','args':[selection(x,fieldmap) for x in s]}
    if not isinstance(s,dict) or not s:raise Problem('Sigma selection must be a map')
    nodes=[]
    for key,values in s.items():
        parts=key.split('|');field=fieldmap.get(parts[0]);mods=parts[1:]
        if field not in FIELDS or len(set(mods))!=len(mods) or set(mods)-{'contains','startswith','endswith','all','exists','cidr','fieldref','cased'}:raise Problem('unmapped field or unsupported Sigma modifier')
        modes=[x for x in mods if x not in ('all','cased')]
        if 'all' in mods and (not isinstance(values,list) or len(values)<2):raise Problem('all requires multiple values')
        if len(modes)>1:raise Problem('stacked transform modifiers not supported')
        if isinstance(values,list) and any(x is None for x in values):raise Problem('null cannot occur in a value list')
        if values is None:
            if mods:raise Problem('null cannot have modifiers')
            modes=['null']
        values=values if isinstance(values,list) else [values]
        if modes!=['exists']:values=[str(x) if type(x) is int else x for x in values]
        mode=modes[0] if modes else 'exact'
        if mode=='fieldref':
            if any(not isinstance(x,str) or x not in fieldmap for x in values):raise Problem('unmapped field reference')
            values=[fieldmap[x] for x in values]
        node=dict(op='field',field=field,mode='present' if mode=='exists' else mode,values=values,all='all' in mods)
        if 'cased' in mods:node['cased']=True
        nodes.append(node)
    return {'op':'and','args':nodes}

def condition(text,selections):
    if isinstance(text,list):
        if not 1<=len(text)<=32 or any(not isinstance(x,str) for x in text):raise Problem('invalid Sigma conditions')
        return validate_node(dict(op='or',args=[condition(x,selections) for x in text]))
    if not isinstance(text,str) or len(text)>2000:raise Problem('invalid Sigma condition')
    tokens=re.findall(r'[A-Za-z_*][A-Za-z_0-9*]*|[()]|\S',text);pos=0
    def term(depth=0):
        nonlocal pos
        if depth>16 or pos>=len(tokens):raise Problem('invalid Sigma condition')
        token=tokens[pos];pos+=1
        if token in ('1','all'):
            if pos+1>=len(tokens) or tokens[pos]!='of':raise Problem('invalid Sigma quantifier')
            pattern=tokens[pos+1];pos+=2
            names=[name for name in selections if (not name.startswith('_') if pattern=='them' else wildcard(name,pattern,case_sensitive=True))]
            if not names:raise Problem('Sigma quantifier matches no selections')
            return dict(op='or' if token=='1' else 'and',args=[selections[name] for name in names])
        if token=='not':return dict(op='not',arg=term(depth+1))
        if token=='(':
            n=expr(depth+1)
            if pos>=len(tokens) or tokens[pos]!=')':raise Problem('unclosed Sigma condition')
            pos+=1;return n
        if token not in selections:raise Problem('unknown selection or unsupported Sigma condition')
        return selections[token]
    def conjunction(depth):
        nonlocal pos
        nodes=[term(depth)]
        while pos<len(tokens) and tokens[pos]=='and':pos+=1;nodes.append(term(depth))
        return nodes[0] if len(nodes)==1 else dict(op='and',args=nodes)
    def expr(depth):
        nonlocal pos
        nodes=[conjunction(depth)]
        while pos<len(tokens) and tokens[pos]=='or':pos+=1;nodes.append(conjunction(depth))
        return nodes[0] if len(nodes)==1 else dict(op='or',args=nodes)
    n=expr(0)
    if pos!=len(tokens):raise Problem('unsupported Sigma condition')
    return validate_node(n)

def compile_rule(rule,binding):
    if not isinstance(rule,dict) or not isinstance(binding,dict):raise Problem('rule and binding objects required')
    if any(k in rule for k in ('correlation','action','scope')):raise Problem('correlation, collection actions and scope are not supported')
    if rule.get('taxonomy','sigma')!='sigma':raise Problem('unsupported Sigma taxonomy')
    if rule.get('logsource')!=binding.get('logsource'):raise Problem('logsource must match operator binding exactly')
    match=binding.get('match');fields=binding.get('fields')
    if not isinstance(match,dict) or not match.get('category') or not match.get('source') or not isinstance(fields,dict):raise Problem('binding requires category, explicit sources and field mapping')
    detection=rule.get('detection',{})
    if not isinstance(detection,dict) or not 2<=len(detection)<=33:raise Problem('invalid Sigma detection')
    selections={}
    for key,value in detection.items():
        if key=='condition':continue
        if not re.fullmatch('[A-Za-z_][A-Za-z_0-9]*',key) or key in ('and','or','not','all','of','them','timeframe'):raise Problem('invalid Sigma selection name')
        selections[key]=selection(value,fields)
    node=condition(detection.get('condition'),selections)
    from .rules import validate
    out=dict(id='sigma.'+hashlib.sha256(canonical(rule).encode()).hexdigest()[:32],title=rule.get('title'),severity=rule.get('level','medium'),enabled=False,window_seconds=1,threshold=1,group_by=['source','host','target','actor'],match=match,sigma=node)
    if out['severity']=='informational':out['severity']='low'
    result=validate(out)
    if len(canonical(result).encode())>65536:raise Problem('compiled rule exceeds package size limit')
    return result

def load_yaml(path):
    import yaml
    from yaml.tokens import AliasToken,AnchorToken
    raw=Path(path).read_text()
    if len(raw)>65536:raise Problem('Sigma YAML exceeds 64 KiB')
    if any(isinstance(t,(AliasToken,AnchorToken)) for t in yaml.scan(raw)):raise Problem('YAML anchors and aliases not supported')
    class Loader(yaml.SafeLoader):pass
    def mapping(loader,node):
        result={}
        for k,v in node.value:
            key=loader.construct_object(k)
            if not isinstance(key,str) or key in result:raise Problem('duplicate/non-string YAML key')
            result[key]=loader.construct_object(v)
        return result
    Loader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG,mapping)
    # Prevent automatic datetime conversion; Sigma date metadata is text.
    Loader.yaml_implicit_resolvers={k:[x for x in v if x[0]!='tag:yaml.org,2002:timestamp'] for k,v in Loader.yaml_implicit_resolvers.items()}
    return yaml.load(raw,Loader=Loader)

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('rule');p.add_argument('--binding',required=True);p.add_argument('--output',required=True);a=p.parse_args()
    result=compile_rule(load_yaml(a.rule),json.loads(Path(a.binding).read_text()))
    with open(a.output,'x') as f:f.write(json.dumps(result,indent=2)+'\n')
if __name__=='__main__':main()
