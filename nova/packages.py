"""Opt-in Ed25519 package authenticity with operator-owned trust roots."""
import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
from .core import Problem,canonical,identifier

def message(path,raw):
    return canonical({'domain':'nova.package.v1','name':Path(path).name,'sha256':hashlib.sha256(raw).hexdigest()}).encode()

def verify(path,raw=None,trust_path=None,required=None):
    path=Path(path);raw=path.read_bytes() if raw is None else raw
    trust_path=trust_path or os.environ.get('NOVA_PACKAGE_TRUST')
    required=(os.environ.get('NOVA_REQUIRE_SIGNED_PACKAGES')=='1') if required is None else required
    signature_path=path.parent/'signatures'/(path.name+'.sig')
    if not signature_path.exists():
        if required:raise Problem('required package signature missing: '+path.name)
        return 'unsigned-development'
    if not trust_path:raise Problem('signed package needs an explicit trust file')
    try:
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
        signature=json.loads(signature_path.read_text())
        trust=json.loads(Path(trust_path).read_text())
        key=Ed25519PublicKey.from_public_bytes(base64.b64decode(trust[signature['key_id']],validate=True))
        key.verify(base64.b64decode(signature['signature'],validate=True),message(path,raw))
    except ImportError as e:raise Problem('install requirements-security.txt for package signature verification') from e
    except Exception as e:raise Problem('package signature verification failed: '+path.name) from e
    return 'verified'

def keygen(private_path,trust_path,key_id):
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from cryptography.hazmat.primitives.serialization import Encoding,PrivateFormat,PublicFormat,NoEncryption
    identifier(key_id,'key id')
    if Path(private_path).exists() or Path(trust_path).exists():raise Problem('key generation refuses to overwrite files')
    key=Ed25519PrivateKey.generate()
    private=key.private_bytes(Encoding.PEM,PrivateFormat.PKCS8,NoEncryption())
    trust={key_id:base64.b64encode(key.public_key().public_bytes(Encoding.Raw,PublicFormat.Raw)).decode()}
    for path,data in [(private_path,private),(trust_path,canonical(trust).encode())]:
        fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
        with os.fdopen(fd,'wb') as f:f.write(data)

def sign(path,private_path,key_id):
    from cryptography.hazmat.primitives.serialization import load_pem_private_key
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    identifier(key_id,'key id');path=Path(path)
    key=load_pem_private_key(Path(private_path).read_bytes(),password=None)
    if not isinstance(key,Ed25519PrivateKey):raise Problem('Ed25519 key required')
    target=path.parent/'signatures';target.mkdir(exist_ok=True)
    signature=base64.b64encode(key.sign(message(path,path.read_bytes()))).decode()
    target=target/(path.name+'.sig')
    # Fail closed until atomic replacement completes.
    import tempfile
    fd,temp=tempfile.mkstemp(dir=target.parent)
    try:
        with os.fdopen(fd,'w') as f:
            f.write(canonical({'key_id':key_id,'signature':signature}));f.flush();os.fsync(f.fileno())
        os.replace(temp,target)
    finally:
        if os.path.exists(temp):os.unlink(temp)

def main():
    p=argparse.ArgumentParser(description='Nova integration/rule package authenticity')
    p.add_argument('command',choices=['keygen','sign','verify'])
    p.add_argument('--private-key');p.add_argument('--trust');p.add_argument('--key-id',default='operator-1');p.add_argument('--package')
    a=p.parse_args()
    if a.command=='keygen':
        if not a.private_key or not a.trust:p.error('--private-key and --trust required')
        keygen(a.private_key,a.trust,a.key_id)
    elif a.command=='sign':
        if not a.private_key or not a.package:p.error('--private-key and --package required')
        sign(a.package,a.private_key,a.key_id)
    else:
        if not a.package or not a.trust:p.error('--package and --trust required')
        print(verify(a.package,trust_path=a.trust,required=True))

if __name__=='__main__':main()
