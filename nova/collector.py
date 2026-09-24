"""Disk-backed NDJSON collector. A source acknowledgement never precedes spool commit."""
import argparse
import hashlib
import ipaddress
import json
import os
import random
import re
import sqlite3
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, build_opener, ProxyHandler, HTTPRedirectHandler
from .core import Problem, canonical, identifier, timestamp
from .distributed.contracts import strict_json

TYPED_ADAPTERS=('ocsf-auth-json','process-json','network-json','dns-json','file-json','cloud-json')
ADAPTERS=TYPED_ADAPTERS+('auth-json','windows-security-json','cloudtrail-console-json','openssh-json')

def adapt(adapter,data):
    if not isinstance(data,dict):raise Problem('source record must be an object')
    if adapter=='auth-json' or adapter in TYPED_ADAPTERS:return data
    if adapter=='windows-security-json':
        # Explicit exported JSON contract, not native Windows EVTX/XML collection.
        event_id=str(data.get('event_id'))
        if event_id not in ('4624','4625'):raise Problem('only Windows authentication event IDs 4624 and 4625 are supported')
        out=dict(timestamp=data.get('timestamp'),user=data.get('TargetUserName'),src_ip=data.get('IpAddress'),status='success' if event_id=='4624' else 'failure',message='Windows security event '+event_id)
    elif adapter=='cloudtrail-console-json':
        if data.get('eventSource')!='signin.amazonaws.com' or data.get('eventName')!='ConsoleLogin':raise Problem('only CloudTrail ConsoleLogin is supported')
        identity=data.get('userIdentity',{});response=data.get('responseElements',{})
        if not isinstance(identity,dict) or not isinstance(response,dict):raise Problem('invalid CloudTrail identity or response')
        status={'Success':'success','Failure':'failure'}.get(response.get('ConsoleLogin'))
        out=dict(timestamp=data.get('eventTime'),user=identity.get('userName') or identity.get('arn') or identity.get('principalId'),src_ip=data.get('sourceIPAddress'),status=status,message='AWS ConsoleLogin')
    elif adapter=='openssh-json':
        message=data.get('message','')
        if not isinstance(message,str) or len(message)>8192:raise Problem('invalid SSH message')
        m=re.search(r'\b(Failed password|Accepted password|Accepted publickey) for (?:invalid user )?(\S+) from ([0-9a-fA-F:.]+) port [0-9]+(?:\s|$)',message)
        if not m:raise Problem('unsupported OpenSSH authentication message')
        out=dict(timestamp=data.get('timestamp'),user=m[2],src_ip=m[3],status='failure' if m[1]=='Failed password' else 'success',message=message)
    else:raise Problem('unknown adapter')
    timestamp(out['timestamp'])
    if not isinstance(out['user'],str) or not 1<=len(out['user'])<=256 or out['status'] not in ('success','failure'):raise Problem('missing authentication identity or outcome')
    try:out['src_ip']=str(ipaddress.ip_address(out['src_ip']))
    except ValueError:raise Problem('source address must be an IP literal')
    out['original']=data
    return out

class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs):raise Problem('collector refuses HTTP redirects')

class Spool:
    def __init__(self,path,source,adapter='auth-json',max_bytes=256*1024*1024):
        identifier(source,'source')
        if adapter not in ADAPTERS:raise Problem('unknown adapter')
        self.source,self.adapter,self.max_bytes=source,adapter,max_bytes
        self.path=Path(path);self.path.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
        import fcntl
        self.lock=open(str(path)+'.lock','a')
        os.chmod(str(path)+'.lock',0o600)
        try:fcntl.flock(self.lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:
            self.lock.close();raise Problem('spool is already in use')
        self.c=sqlite3.connect(str(path),timeout=10)
        os.chmod(path,0o600)
        self.c.row_factory=sqlite3.Row
        self.c.execute('PRAGMA journal_mode=WAL');self.c.execute('PRAGMA synchronous=FULL')
        self.c.executescript('''CREATE TABLE IF NOT EXISTS config(source TEXT,adapter TEXT);
        CREATE TABLE IF NOT EXISTS files(path TEXT PRIMARY KEY,device INTEGER,inode INTEGER,offset INTEGER,prefix TEXT);
        CREATE TABLE IF NOT EXISTS queue(id TEXT PRIMARY KEY,payload TEXT NOT NULL,bytes INTEGER NOT NULL,state TEXT NOT NULL,reason TEXT,attempts INTEGER NOT NULL DEFAULT 0,next_try REAL NOT NULL DEFAULT 0);
        CREATE INDEX IF NOT EXISTS queue_ready ON queue(state,next_try);
        ''')
        try:
            with self.c:
                config=self.c.execute('SELECT * FROM config').fetchone()
                if config and (config['source']!=source or config['adapter']!=adapter):raise Problem('spool already belongs to another source or adapter')
                if not config:self.c.execute('INSERT INTO config VALUES(?,?)',(source,adapter))
        except Exception:
            self.close();raise
    def close(self):
        self.c.close();self.lock.close()
    def import_file(self,path,max_lines=10000):
        path=Path(path).resolve()
        imported=0
        with path.open('rb') as f:
            st=os.fstat(f.fileno())
            # Existing files cannot silently rotate or truncate: finish and register a new path/spool.
            old=self.c.execute('SELECT * FROM files WHERE path=?',(str(path),)).fetchone()
            offset=old['offset'] if old else 0
            if old and ((old['device'],old['inode'])!=(st.st_dev,st.st_ino) or st.st_size<offset):raise Problem('file rotated or truncated; preserve old file and use a new spool for the replacement')
            # Verify last committed record bytes via a bounded prefix fingerprint.
            prefix=hashlib.sha256(f.read(min(offset,4096))).hexdigest()
            if old and prefix!=old['prefix']:raise Problem('source file prefix changed; refusing to skip data')
            f.seek(offset)
            for _ in range(max_lines):
                start=f.tell();line=f.readline(65538)
                if not line:break
                if len(line)>65536:raise Problem('source line exceeds 64 KiB; cursor retained')
                if not line.endswith(b'\n'):break # Writer may still be appending.
                end=f.tell()
                eid=hashlib.sha256(canonical([str(path),st.st_dev,st.st_ino,start,hashlib.sha256(line).hexdigest()]).encode()).hexdigest()
                state,reason='pending',None
                try:
                    data=adapt(self.adapter,strict_json(line))
                    payload=canonical(data)
                    if len(payload.encode())>32768:raise Problem('normalized source record exceeds 32 KiB')
                except (Problem,ValueError,UnicodeDecodeError,TypeError,RecursionError) as error:
                    payload=canonical({'source_bytes_hex':line.hex()});state='quarantine';reason=str(error)[:500]
                size=len(payload.encode())
                pos=f.tell();f.seek(0);prefix=hashlib.sha256(f.read(min(end,4096))).hexdigest();f.seek(pos)
                with self.c:
                    self.c.execute('BEGIN IMMEDIATE')
                    usage=self.c.execute('SELECT COALESCE(SUM(bytes),0) FROM queue').fetchone()[0]
                    if usage+size>self.max_bytes:raise Problem('spool capacity reached; source cursor not advanced',429)
                    self.c.execute('INSERT INTO queue(id,payload,bytes,state,reason) VALUES(?,?,?,?,?)',(eid,payload,size,state,reason))
                    self.c.execute('INSERT INTO files VALUES(?,?,?,?,?) ON CONFLICT(path) DO UPDATE SET offset=excluded.offset,prefix=excluded.prefix',(str(path),st.st_dev,st.st_ino,end,prefix))
                imported+=1
        return imported
    def status(self):
        return [dict(r) for r in self.c.execute('SELECT state,COUNT(*) AS records,SUM(bytes) AS bytes,MAX(attempts) AS max_attempts FROM queue GROUP BY state')]
    def retry(self):
        with self.c:self.c.execute("UPDATE queue SET state='pending',attempts=0,next_try=0 WHERE state='failed'")
    def send(self,url,token,now=None,opener=None):
        now=time.time() if now is None else now
        parsed=urlsplit(url)
        if parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.path not in ('','/') or parsed.scheme not in ('http','https'):raise Problem('gateway URL must be an HTTP(S) origin')
        if parsed.scheme=='http' and parsed.hostname not in ('127.0.0.1','localhost','::1'):raise Problem('remote collection requires HTTPS')
        selected=[];size=0
        for r in self.c.execute("SELECT * FROM queue WHERE state='pending' AND next_try<=? ORDER BY rowid LIMIT 500",(now,)):
            size+=r['bytes']+150
            if size>900000:break
            selected.append(r)
        if not selected:return 0
        body={'source':self.source,'integration':self.adapter if self.adapter in TYPED_ADAPTERS else 'auth-json','events':[{'id':r['id'],'data':json.loads(r['payload'])} for r in selected]}
        request=Request(url.rstrip('/')+'/api/events',data=canonical(body).encode(),headers={'Authorization':'Bearer '+token,'Content-Type':'application/json'})
        try:
            client=opener or build_opener(ProxyHandler({}),NoRedirect())
            with client.open(request,timeout=15) as response:
                result=strict_json(response.read(262145))
                if response.status!=200 or not isinstance(result,dict):raise Problem('invalid gateway acknowledgement')
            expected=[hashlib.sha256(canonical([self.source,r['id']]).encode()).hexdigest() for r in selected]
            if result.get('event_ids')!=expected or type(result.get('accepted')) is not int or type(result.get('duplicates')) is not int or min(result['accepted'],result['duplicates'])<0 or result['accepted']+result['duplicates']!=len(selected):raise Problem('gateway acknowledgement does not match batch')
        except Exception:
            # No record deletion on timeout, auth, capacity, malformed ACK, or other delivery failure.
            with self.c:
                for r in selected:
                    attempts=r['attempts']+1
                    self.c.execute('UPDATE queue SET attempts=?,next_try=?,state=?,reason=? WHERE id=?',(attempts,now+min(300,2**attempts)+random.random(), 'failed' if attempts>=8 else 'pending','Delivery unconfirmed; inspect gateway and credentials',r['id']))
            raise
        with self.c:self.c.executemany('DELETE FROM queue WHERE id=?',[(r['id'],) for r in selected])
        return len(selected)

def main():
    os.umask(0o077)
    p=argparse.ArgumentParser(description='Nova durable NDJSON collector')
    p.add_argument('command',choices=['import','send','status','retry','run'])
    p.add_argument('--spool',required=True);p.add_argument('--source',required=True)
    p.add_argument('--adapter',choices=ADAPTERS,default='auth-json');p.add_argument('--file')
    p.add_argument('--url',default='http://127.0.0.1:8787');p.add_argument('--token-file');p.add_argument('--tokens-json')
    a=p.parse_args()
    if a.command in ('import','run') and not a.file:p.error('--file is required')
    if a.command in ('send','run') and not (bool(a.token_file)^bool(a.tokens_json)):p.error('provide either --token-file (plain token) or --tokens-json (Nova local-tokens.json)')
    def token():return json.loads(Path(a.tokens_json).read_text())['collector'] if a.tokens_json else Path(a.token_file).read_text().strip()
    spool=Spool(a.spool,a.source,a.adapter)
    try:
        if a.command=='import':print(json.dumps({'imported':spool.import_file(a.file)}))
        elif a.command=='status':print(json.dumps(spool.status()))
        elif a.command=='retry':spool.retry();print('Failed deliveries queued for retry; malformed source records remain quarantined.')
        elif a.command=='send':print(json.dumps({'confirmed':spool.send(a.url,token())}))
        else:
            while True:
                spool.import_file(a.file)
                try:spool.send(a.url,token())
                except Exception:print('Delivery unconfirmed; records retained for bounded retry.',flush=True)
                time.sleep(1)
    except KeyboardInterrupt:pass
    finally:spool.close()

if __name__=='__main__':main()
