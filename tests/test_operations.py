import hashlib
import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch
from nova.core import Engine,Problem
from nova.operations import backup,restore,doctor
from nova.server import Service,Server
from nova.collector import Spool
from test_core import event,batch

class OperationsTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.dir=Path(self.temp.name)
        self.e=Engine(self.dir/'db');self.e.activate('alpha','admin','auth-json');self.e.ingest('alpha','collector',batch())
    def tearDown(self):self.temp.cleanup()
    def test_online_backup_and_restore_replays_pending(self):
        backup(self.dir/'db',self.dir/'snapshot');restore(self.dir/'snapshot',self.dir/'restored')
        recovered=Engine(self.dir/'restored');recovered.drain()
        self.assertEqual(recovered.health('alpha')['normalized'],1)
        self.assertEqual(self.e.health('alpha')['normalizer_pending'],1)
    def test_corrupt_snapshot_rejected(self):
        backup(self.dir/'db',self.dir/'snapshot')
        with (self.dir/'snapshot/nova.db').open('ab') as f:f.write(b'corrupt')
        with self.assertRaises(Problem):restore(self.dir/'snapshot',self.dir/'restored')
        self.assertFalse((self.dir/'restored').exists())
    def test_restore_does_not_overwrite(self):
        backup(self.dir/'db',self.dir/'snapshot')
        with self.assertRaises(Problem):restore(self.dir/'snapshot',self.dir/'db')
        self.assertEqual(self.e.health('alpha')['raw_events'],1)
    def test_doctor_explains_pending(self):
        report=doctor(self.dir/'db');self.assertEqual(report['normalizer_pending'],1);self.assertTrue(report['guidance'])
    def test_doctor_never_creates_db(self):
        with self.assertRaises(Problem):doctor(self.dir/'missing')
        self.assertFalse((self.dir/'missing').exists())
    def test_expired_token_denied(self):
        credentials=[dict(name='a',role='admin',tenant='alpha',token_sha256=hashlib.sha256(b'token').hexdigest(),expires_at=0)]
        with self.assertRaises(Problem):Service(self.e,credentials).authenticate('Bearer token','read')
    def test_revoked_token_denied(self):
        credentials=[dict(name='a',role='admin',tenant='alpha',token_sha256=hashlib.sha256(b'token').hexdigest(),revoked=True)]
        with self.assertRaises(Problem):Service(self.e,credentials).authenticate('Bearer token','read')
    def test_rate_limit_is_bounded_and_recovers(self):
        credentials=[dict(name='a',role='admin',tenant='alpha',token_sha256=hashlib.sha256(b'token').hexdigest())];s=Service(self.e,credentials)
        with patch('nova.server.time.monotonic',return_value=0):
            for i in range(200):s.authenticate('Bearer token','read')
            with self.assertRaises(Problem) as ctx:s.authenticate('Bearer token','read')
            self.assertEqual(ctx.exception.status,429)
        with patch('nova.server.time.monotonic',return_value=1):self.assertEqual(s.authenticate('Bearer token','read')['tenant'],'alpha')
    def test_collector_real_http_duplicate_ack_recovery(self):
        credentials=[dict(name='a',role='admin',tenant='alpha',token_sha256=hashlib.sha256(b'token').hexdigest())]
        service=Service(self.e,credentials);server=Server(('127.0.0.1',0),service)
        t=threading.Thread(target=server.serve_forever,daemon=True);t.start()
        spool=Spool(self.dir/'spool','collector-real');file=self.dir/'input';file.write_text(json.dumps(event()['data'])+'\n');spool.import_file(file)
        try:
            row=spool.c.execute('SELECT * FROM queue').fetchone()
            # Gateway has committed but the collector lost the acknowledgement.
            self.e.ingest('alpha','collector',batch([{'id':row['id'],'data':json.loads(row['payload'])}],source='collector-real'))
            self.assertEqual(spool.send('http://127.0.0.1:'+str(server.server_port),'token'),1)
            self.assertFalse(spool.status());self.assertEqual(self.e.health('alpha')['raw_events'],2)
        finally:spool.close();server.shutdown();server.server_close();t.join()

if __name__=='__main__':unittest.main()
