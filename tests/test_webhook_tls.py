import ipaddress,json,os,ssl,tempfile,threading,unittest
from datetime import datetime,timedelta,timezone
from http.server import BaseHTTPRequestHandler,HTTPServer
from pathlib import Path
from unittest.mock import patch
from nova.soar import Webhook,Permanent

class WebhookTLSTests(unittest.TestCase):
    def test_real_tls_verified_peer_and_ack_contract(self):
        from cryptography import x509
        from cryptography.x509.oid import NameOID
        from cryptography.hazmat.primitives import hashes,serialization
        from cryptography.hazmat.primitives.asymmetric import rsa
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);key=rsa.generate_private_key(public_exponent=65537,key_size=2048);name=x509.Name([x509.NameAttribute(NameOID.COMMON_NAME,'localhost')]);now=datetime.now(timezone.utc)
            cert=x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key()).serial_number(x509.random_serial_number()).not_valid_before(now-timedelta(minutes=1)).not_valid_after(now+timedelta(hours=1)).add_extension(x509.BasicConstraints(ca=True,path_length=None),critical=True).add_extension(x509.SubjectAlternativeName([x509.DNSName('localhost')]),critical=False).sign(key,hashes.SHA256())
            (root/'cert').write_bytes(cert.public_bytes(serialization.Encoding.PEM));(root/'key').write_bytes(key.private_bytes(serialization.Encoding.PEM,serialization.PrivateFormat.PKCS8,serialization.NoEncryption()));(root/'token').write_text('test-token')
            seen=[]
            class Handler(BaseHTTPRequestHandler):
                def log_message(self,*args):pass
                def do_POST(self):
                    seen.append((self.headers.get('Authorization'),self.headers.get('Idempotency-Key'),json.loads(self.rfile.read(int(self.headers['Content-Length'])))))
                    data=json.dumps({'idempotency_key':self.headers['Idempotency-Key'],'status':'completed'}).encode();self.send_response(200);self.send_header('Content-Length',str(len(data)));self.end_headers();self.wfile.write(data)
            server=HTTPServer(('127.0.0.1',0),Handler);ctx=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER);ctx.load_cert_chain(root/'cert',root/'key');server.socket=ctx.wrap_socket(server.socket,server_side=True);thread=threading.Thread(target=server.serve_forever);thread.start()
            try:
                cfg=dict(url=f'https://localhost:{server.server_port}/actions',token_file=str(root/'token'))
                with patch.dict(os.environ,{'SSL_CERT_FILE':str(root/'cert')}):self.assertTrue(Webhook().send(cfg,'idempotent-key',{'action':'test'}))
                self.assertEqual(seen,[('Bearer test-token','idempotent-key',{'action':'test'})])
            finally:server.shutdown();server.server_close();thread.join()
