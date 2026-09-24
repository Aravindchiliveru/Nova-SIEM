"""Manage only the named local nova-lab Compose project; never removes volumes."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import secrets
import shutil
import subprocess
import sys
ROOT=Path(__file__).resolve().parents[1]
LAB=ROOT/'deploy/.lab'

def setup():
    LAB.mkdir(mode=0o700,parents=True,exist_ok=True)
    needed=[LAB/'env',LAB/'credentials.json',LAB/'local-tokens.json']
    if all(p.exists() for p in needed):return
    if any(p.exists() for p in needed):raise SystemExit('Incomplete lab credentials. Restore the missing files; credentials will not be overwritten.')
    tokens={role:secrets.token_urlsafe(32) for role in ('admin','collector','analyst')}
    credentials=[dict(name=role,tenant='demo',role=role,token_sha256=hashlib.sha256(token.encode()).hexdigest()) for role,token in tokens.items()]
    contents=[('env',f'POSTGRES_PASSWORD={secrets.token_hex(24)}\nCLICKHOUSE_PASSWORD={secrets.token_hex(24)}\n',0o600),
              ('credentials.json',json.dumps(credentials,indent=2),0o444),
              ('local-tokens.json',json.dumps(tokens,indent=2),0o600)]
    for name,content,mode in contents:
        fd=os.open(LAB/name,os.O_WRONLY|os.O_CREAT|os.O_EXCL,mode)
        with os.fdopen(fd,'w') as f:f.write(content)
        os.chmod(LAB/name,mode)

def compose_args():
    return ['docker','compose','--env-file',str(LAB/'env'),'-f',str(ROOT/'deploy/compose.lab.yaml')]

def main():
    p=argparse.ArgumentParser(description='Nova local distributed development cluster')
    p.add_argument('action',choices=['doctor','start','stop','status','verify','fault-test'])
    a=p.parse_args()
    if not shutil.which('docker'):
        print('Docker is not installed. Local mode still runs with: python3 run.py')
        return 2
    result=subprocess.run(['docker','compose','version'],capture_output=True)
    if result.returncode:
        print('Docker Compose v2 is required.');return 2
    if a.action=='doctor':
        result=subprocess.run(['docker','info'],capture_output=True)
        print('Docker and Compose are available.' if result.returncode==0 else 'Docker daemon is unavailable.')
        return result.returncode
    if a.action=='start':
        setup()
        return subprocess.call(compose_args()+['up','--build','-d'])
    if not (LAB/'env').exists():
        print('No initialized lab. Run: python3 tools/cluster.py start');return 2
    if a.action=='stop':return subprocess.call(compose_args()+['down'])
    if a.action=='status':return subprocess.call(compose_args()+['ps'])
    return subprocess.call([sys.executable,str(ROOT/'tools/check_cluster.py')]+(['--faults'] if a.action=='fault-test' else []))
if __name__=='__main__':raise SystemExit(main())
