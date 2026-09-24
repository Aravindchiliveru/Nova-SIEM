"""Send a synthetic authentication sequence through the actual HTTP API."""
import argparse
import json
import uuid
from datetime import datetime,timezone
from pathlib import Path
from urllib.request import Request,build_opener,ProxyHandler
p=argparse.ArgumentParser()
p.add_argument('--port',type=int,default=8787)
p.add_argument('--tokens',type=Path,default=Path(__file__).resolve().parents[1]/'data/local-tokens.json')
a=p.parse_args()
token=json.loads(a.tokens.read_text())['admin']
def post(path,body):
    req=Request(f'http://127.0.0.1:{a.port}'+path,data=json.dumps(body).encode(),headers={'Authorization':'Bearer '+token,'Content-Type':'application/json'})
    with build_opener(ProxyHandler({})).open(req,timeout=10) as r: return json.load(r)
post('/api/integrations/activate',{'package':'auth-json'})
batch=str(uuid.uuid4());now=datetime.now(timezone.utc).isoformat()
result=post('/api/events',{'source':'sample-cli','integration':'auth-json','events':[{'id':batch+'-'+str(i),'data':{'timestamp':now,'user':'sample-'+batch[:8],'src_ip':'192.0.2.10','status':'failure','message':'Synthetic authentication failure'}} for i in range(5)]})
print(json.dumps(result,indent=2))
