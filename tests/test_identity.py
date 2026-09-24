import base64
import hashlib
import json
import tempfile
import time
import unittest
from pathlib import Path
from cryptography.hazmat.primitives.asymmetric import rsa,padding
from cryptography.hazmat.primitives import hashes
from nova.core import Problem
from nova.identity import JWTVerifier
from nova.server import Service

def enc(value):
    if isinstance(value,int):value=value.to_bytes((value.bit_length()+7)//8,'big')
    if not isinstance(value,bytes):value=json.dumps(value,separators=(',',':')).encode()
    return base64.urlsafe_b64encode(value).rstrip(b'=').decode()

class IdentityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.key=rsa.generate_private_key(public_exponent=65537,key_size=2048)
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.dir=Path(self.temp.name)
        numbers=self.key.public_key().public_numbers()
        self.jwks={'keys':[{'kid':'test','kty':'RSA','alg':'RS256','use':'sig','n':enc(numbers.n),'e':enc(numbers.e)}]}
        (self.dir/'jwks.json').write_text(json.dumps(self.jwks))
        self.config=dict(issuer='https://identity.example/realm',audience='nova-api',jwks_file=str(self.dir/'jwks.json'),clock_skew_seconds=0)
        self.verifier=JWTVerifier(self.config)
    def tearDown(self):self.temp.cleanup()
    def token(self,claims=None,header=None,key=None):
        h=enc(header or dict(alg='RS256',typ='at+jwt',kid='test'))
        p=enc(claims if claims is not None else dict(iss=self.config['issuer'],aud='nova-api',sub='person-1',iat=0,exp=1000))
        s=enc((key or self.key).sign((h+'.'+p).encode(),padding.PKCS1v15(),hashes.SHA256()))
        return h+'.'+p+'.'+s
    def reject(self,**kw):
        with self.assertRaises(Problem):self.verifier.verify(self.token(**kw),now=100)
    def test_valid_token(self):self.assertEqual(self.verifier.verify(self.token(),now=100)['sub'],'person-1')
    def test_algorithm_confusion(self):self.reject(header=dict(alg='HS256',typ='at+jwt',kid='test'))
    def test_none_algorithm(self):self.reject(header=dict(alg='none',typ='at+jwt',kid='test'))
    def test_unknown_key(self):self.reject(header=dict(alg='RS256',typ='at+jwt',kid='other'))
    def test_remote_key_url_denied(self):self.reject(header=dict(alg='RS256',typ='at+jwt',kid='test',jku='https://evil.example'))
    def test_id_token_type_denied(self):self.reject(header=dict(alg='RS256',typ='JWT',kid='test'))
    def test_missing_expiry(self):self.reject(claims=dict(iss=self.config['issuer'],aud='nova-api',sub='person-1'))
    def test_expired(self):self.reject(claims=dict(iss=self.config['issuer'],aud='nova-api',sub='person-1',exp=100))
    def test_wrong_issuer(self):self.reject(claims=dict(iss='https://evil.example',aud='nova-api',sub='person-1',exp=1000))
    def test_wrong_audience(self):self.reject(claims=dict(iss=self.config['issuer'],aud='other',sub='person-1',exp=1000))
    def test_future_not_before(self):self.reject(claims=dict(iss=self.config['issuer'],aud='nova-api',sub='person-1',exp=1000,nbf=101))
    def test_future_issued(self):self.reject(claims=dict(iss=self.config['issuer'],aud='nova-api',sub='person-1',exp=1000,iat=101))
    def test_tampered_signature(self):
        token=self.token();h,p,s=token.split('.');raw=bytearray(base64.urlsafe_b64decode(s+'='*(-len(s)%4)));raw[0]^=1
        with self.assertRaises(Problem):self.verifier.verify(h+'.'+p+'.'+enc(bytes(raw)),now=100)
    def test_duplicate_json_claims(self):self.reject(claims=b'{"iss":"https://identity.example/realm","aud":"nova-api","sub":"person-1","exp":1000,"exp":2000}')
    def test_tenant_and_role_claims_ignored(self):
        service=Service(None,[dict(name='analyst',tenant='alpha',role='viewer',oidc_sub='person-1')],verifier=self.verifier)
        token=self.token(claims=dict(iss=self.config['issuer'],aud='nova-api',sub='person-1',exp=time.time()+100,tenant='beta',role='admin'))
        identity=service.authenticate('Bearer '+token,'read');self.assertEqual(identity['tenant'],'alpha')
        with self.assertRaises(Problem):service.authenticate('Bearer '+token,'manage')
    def test_unknown_subject_denied(self):
        service=Service(None,[],verifier=self.verifier)
        token=self.token(claims=dict(iss=self.config['issuer'],aud='nova-api',sub='person-1',exp=time.time()+100))
        with self.assertRaises(Problem):service.authenticate('Bearer '+token,'read')
    def test_duplicate_grants_denied(self):
        grant=dict(name='analyst',tenant='alpha',role='viewer',oidc_sub='person-1')
        with self.assertRaises(ValueError):Service(None,[grant,dict(grant,tenant='beta')],verifier=self.verifier)

if __name__=='__main__':unittest.main()
