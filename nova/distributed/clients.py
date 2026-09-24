"""Real Kafka and ClickHouse adapters, loaded only for the optional profile."""
import json
import os
from urllib.parse import urlencode,urlparse
from urllib.request import Request,build_opener,ProxyHandler,HTTPRedirectHandler
from .contracts import Record,validate_normal,validate_raw,strict_json
from ..core import Problem,canonical,timestamp,identifier

class KafkaPublisher:
    def __init__(self,config):
        from confluent_kafka import Producer
        self.producer=Producer({**config,'enable.idempotence':True,'acks':'all',
                                'delivery.timeout.ms':15000,'request.timeout.ms':10000})
    def publish(self,outputs):
        errors=[]
        def delivered(error,message):
            if error:errors.append(str(error.code()))
        for topic,value in outputs:
            r=value.get('raw',value)
            key=canonical([r['tenant'],r['event_id']]).encode()
            self.producer.produce(topic,key=key,value=canonical(value).encode(),on_delivery=delivered)
        pending=self.producer.flush(20)
        if errors or pending:raise RuntimeError('Kafka delivery was not confirmed; input remains uncommitted')

class KafkaConsumer:
    def __init__(self,config,group,topic):
        from confluent_kafka import Consumer
        self.consumer=Consumer({**config,'group.id':group,'enable.auto.commit':False,
            'enable.auto.offset.store':False,'auto.offset.reset':'error','partition.assignment.strategy':'range',
            'isolation.level':'read_committed','max.poll.interval.ms':300000})
        def assigned(consumer,partitions):
            from confluent_kafka import OFFSET_INVALID,OFFSET_BEGINNING
            positions=consumer.committed(partitions,timeout=10)
            for p in positions:
                if p.offset==OFFSET_INVALID:p.offset=OFFSET_BEGINNING
            consumer.assign(positions)
        self.consumer.subscribe([topic],on_assign=assigned)
    def read(self,size):
        messages=self.consumer.consume(num_messages=size,timeout=1)
        records=[]
        for m in messages:
            if m.error():raise RuntimeError('Kafka consume failed; worker will stop without advancing offsets')
            if m.value() is None:raise ValueError('unexpected tombstone in immutable event stream')
            records.append(Record(m.topic(),m.partition(),m.offset(),m.value()))
        return records
    def commit(self,positions):
        from confluent_kafka import TopicPartition
        result=self.consumer.commit(offsets=[TopicPartition(t,p,o) for (t,p),o in positions.items()],asynchronous=False)
        if any(r.error for r in (result or [])):raise RuntimeError('Kafka offset commit failed')
    def close(self):self.consumer.close()

class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs):raise RuntimeError('database HTTP redirect rejected')

class ClickHouse:
    def __init__(self,url,user,password,opener=None):
        u=urlparse(url)
        if u.scheme not in ('http','https') or not u.hostname or u.username or u.password or u.query or u.fragment or u.path not in ('','/'):
            raise ValueError('ClickHouse URL must be an HTTP(S) origin without embedded credentials')
        self.url=url.rstrip('/')+'/'
        self.user,self.password=user,password
        self.opener=opener or build_opener(ProxyHandler({}),NoRedirect())
    def request(self,query,params=None,data=None,json_result=True):
        settings={'async_insert':'0','wait_end_of_query':'1','max_execution_time':'15','max_result_bytes':str(32*1024*1024),
                  'result_overflow_mode':'throw','max_rows_to_read':'1000000','read_overflow_mode':'throw',
                  'output_format_json_quote_64bit_integers':'0'}
        if os.environ.get('NOVA_REQUIRE_HA')=='1':
            settings.update(insert_quorum='2',insert_quorum_parallel='1',insert_quorum_timeout='15000')
        if params:settings.update({'param_'+k:str(v) for k,v in params.items()})
        body=query.encode()
        if data is not None:body+=b'\n'+data
        req=Request(self.url+'?'+urlencode(settings),data=body,headers={
            'X-ClickHouse-User':self.user,'X-ClickHouse-Key':self.password,'Content-Type':'text/plain'})
        try:
            with self.opener.open(req,timeout=20) as response:
                result=response.read(32*1024*1024+1)
                if response.status!=200 or len(result)>32*1024*1024:raise RuntimeError('invalid database response')
        except Exception as e:
            raise RuntimeError('ClickHouse request failed; no delivery acknowledgement') from e
        if result.lstrip().startswith(b'Code:'):raise RuntimeError('ClickHouse returned an execution error')
        if json_result:
            try:
                decoded=json.loads(result)
                if not isinstance(decoded.get('data'),list):raise ValueError()
                return decoded['data']
            except (ValueError,AttributeError):raise RuntimeError('invalid ClickHouse JSON response')
        return result
    def write(self,rows):
        payload=[]
        for n in rows:
            n=validate_normal(n)
            payload.append({k:n[k] for k in ('tenant','event_id','source','event_time','received','normalized_at','actor','ip','outcome','message','parser','version','category','action','host','target')}|{'raw':canonical(n['raw'])})
        if payload:
            self.request('INSERT INTO nova.events FORMAT JSONEachRow',
                         data=('\n'.join(canonical(r) for r in payload)+'\n').encode(),json_result=False)
    def search(self,tenant,params):
        query,bindings=compile_search(tenant,params)
        from ..structured import decode
        return [decode(row) for row in self.request(query,bindings)]
    def event(self,tenant,event_id):
        identifier(event_id,'event id')
        rows=self.request('SELECT * FROM nova.events FINAL WHERE tenant={tenant:String} AND event_id={id:String} LIMIT 1 FORMAT JSON',{'tenant':tenant,'id':event_id})
        if not rows:return None
        from ..structured import decode
        row=dict(rows[0]);row['document']=strict_json(row['raw'])['payload']
        return decode(row)
    def count(self,tenant):
        return self.request('SELECT count() AS n FROM nova.events FINAL WHERE tenant={tenant:String} FORMAT JSON',{'tenant':tenant})[0]['n']

def compile_search(tenant,params):
    identifier(tenant,'tenant')
    if set(params)-{'q','outcome','after','before','limit','ip','category','action','host','target','field','value','exists','include_document'}:raise Problem('unsupported search parameter')
    try:
        limit=int(params.get('limit','100'))
        if not 1<=limit<=500:raise ValueError()
    except (ValueError,TypeError):raise Problem('limit must be between 1 and 500')
    where=['tenant={tenant:String}'];bindings={'tenant':tenant,'limit':limit}
    for k in ('outcome','ip','category','action','host','target'):
        if params.get(k):where.append(k+'={'+k+':String}');bindings[k]=params[k]
    for k,op in [('after','>='),('before','<')]:
        if params.get(k):where.append('event_time'+op+'{'+k+':Float64}');bindings[k]=timestamp(params[k])
    if params.get('q'):
        if len(params['q'])>256:raise Problem('query too long')
        where.append('(position(message,{q:String})>0 OR position(actor,{q:String})>0)');bindings['q']=params['q']
    from ..structured import clickhouse_clause
    extra,values=clickhouse_clause(params);where.extend(extra);bindings.update(values)
    return ('SELECT tenant,event_id,source,event_time,received,normalized_at,actor,ip,outcome,message,parser,version,category,action,host,target'+(',JSONExtractRaw(raw,\'payload\') AS document' if params.get('include_document')=='true' else '')+' FROM nova.events FINAL WHERE '
            +' AND '.join(where)+' ORDER BY event_time DESC,event_id LIMIT {limit:UInt32} FORMAT JSON',bindings)
