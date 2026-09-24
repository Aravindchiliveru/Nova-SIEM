"""Portable incident evidence with content checksums; optional operator signature verification."""
import argparse
import hashlib
import json
from pathlib import Path
from .core import Problem,canonical

def seal(payload):
    return {'format':'nova.evidence.v1','payload':payload,'sha256':hashlib.sha256(canonical(payload).encode()).hexdigest(),'authenticity':'unsigned; a checksum alone does not prove provenance'}

def verify(bundle):
    if not isinstance(bundle,dict) or set(bundle)!={'format','payload','sha256','authenticity'} or bundle['format']!='nova.evidence.v1':raise Problem('invalid evidence bundle')
    if hashlib.sha256(canonical(bundle['payload']).encode()).hexdigest()!=bundle['sha256']:raise Problem('evidence checksum mismatch',409)
    payload=bundle['payload']
    if not isinstance(payload,dict) or not isinstance(payload.get('events'),list):raise Problem('invalid evidence payload')
    return {'integrity':'verified','sha256':bundle['sha256'],'events':len(payload['events']),'authenticity':'checksum-only; signature not verified'}

def main():
    p=argparse.ArgumentParser(description='Verify exported Nova evidence')
    p.add_argument('file');p.add_argument('--trust',help='Require an Ed25519 operator signature using this trust file')
    a=p.parse_args();path=Path(a.file)
    result=verify(json.loads(path.read_text()))
    if a.trust:
        from .packages import verify as verify_signature
        result['authenticity']=verify_signature(path,trust_path=a.trust,required=True)
    print(json.dumps(result,indent=2))

if __name__=='__main__':main()
