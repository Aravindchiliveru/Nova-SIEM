"""Opt-in JWT resource-server validation, with pinned issuer/audience/JWKS and local grants.
This is not a browser OIDC authorization-code client or a discovery service.
"""
import base64
import json
import math
import time
from pathlib import Path
from urllib.parse import urlsplit
from .core import Problem

def decode(segment):
    if not isinstance(segment,str) or not segment or len(segment)>16384:raise ValueError('invalid JWT segment')
    import re
    if not re.fullmatch('[A-Za-z0-9_-]+',segment):raise ValueError('invalid base64url')
    return base64.b64decode(segment+'='*(-len(segment)%4),altchars=b'-_',validate=True)

def strict(raw):
    def pairs(items):
        result={}
        for k,v in items:
            if k in result:raise ValueError('duplicate JWT field')
            result[k]=v
        return result
    def reject(value):raise ValueError('nonfinite JSON')
    result=json.loads(raw.decode('utf-8') if isinstance(raw,bytes) else raw,object_pairs_hook=pairs,parse_constant=reject)
    if not isinstance(result,dict):raise ValueError('JSON object required')
    return result

class JWTVerifier:
    def __init__(self,config):
        self.issuer=config['issuer'];self.audience=config['audience'];self.leeway=config.get('clock_skew_seconds',30)
        u=urlsplit(self.issuer)
        if u.scheme!='https' or not u.hostname or u.username or u.password or u.query or u.fragment:raise ValueError('issuer must be a fixed HTTPS URL')
        if not isinstance(self.audience,str) or not 1<=len(self.audience)<=256:raise ValueError('audience required')
        if type(self.leeway) is not int or not 0<=self.leeway<=60:raise ValueError('clock skew must be 0..60 seconds')
        from cryptography.hazmat.primitives.asymmetric.rsa import RSAPublicNumbers
        jwks=strict(Path(config['jwks_file']).read_bytes())
        keys=jwks.get('keys')
        if not isinstance(keys,list) or not 1<=len(keys)<=20:raise ValueError('JWKS must contain 1..20 keys')
        self.keys={}
        for key in keys:
            if key.get('kty')!='RSA' or key.get('use','sig')!='sig' or key.get('alg','RS256')!='RS256':continue
            if 'key_ops' in key and key['key_ops']!=['verify']:continue
            kid=key.get('kid')
            if not isinstance(kid,str) or not 1<=len(kid)<=128 or kid in self.keys:raise ValueError('unique key identifiers required')
            n=int.from_bytes(decode(key['n']),'big');e=int.from_bytes(decode(key['e']),'big')
            if not 2048<=n.bit_length()<=8192 or e<3 or e>2**32 or e%2==0:raise ValueError('unsupported RSA key size/exponent')
            self.keys[kid]=RSAPublicNumbers(e,n).public_key()
        if not self.keys:raise ValueError('no eligible RS256 signing keys')
    @classmethod
    def from_file(cls,path):
        config=strict(Path(path).read_bytes())
        jwks=Path(config['jwks_file'])
        if not jwks.is_absolute():config['jwks_file']=str(Path(path).resolve().parent/jwks)
        return cls(config)
    def verify(self,token,now=None):
        try:
            if not isinstance(token,str) or len(token)>16384:raise ValueError()
            h,p,s=token.split('.')
            header=strict(decode(h))
            if set(header)-{'alg','kid','typ'} or header.get('alg')!='RS256' or header.get('typ')!='at+jwt':raise ValueError()
            key=self.keys[header['kid']]
            from cryptography.hazmat.primitives import hashes
            from cryptography.hazmat.primitives.asymmetric import padding
            key.verify(decode(s),(h+'.'+p).encode('ascii'),padding.PKCS1v15(),hashes.SHA256())
            claims=strict(decode(p));now=time.time() if now is None else now
            if claims.get('iss')!=self.issuer:raise ValueError()
            aud=claims.get('aud')
            if isinstance(aud,str):aud=[aud]
            if not isinstance(aud,list) or not 1<=len(aud)<=10 or any(not isinstance(a,str) for a in aud) or self.audience not in aud:raise ValueError()
            if not isinstance(claims.get('sub'),str) or not 1<=len(claims['sub'])<=256:raise ValueError()
            for field in ('exp','nbf','iat'):
                if field=='exp' or field in claims:
                    if type(claims.get(field)) not in (int,float) or not math.isfinite(claims[field]):raise ValueError()
            if now>=claims['exp']+self.leeway or claims.get('nbf',now)>now+self.leeway or claims.get('iat',now)>now+self.leeway:raise ValueError()
            return claims
        except Exception as error:raise Problem('invalid or expired access token',401) from error
