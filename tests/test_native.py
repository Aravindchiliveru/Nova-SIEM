import json,tempfile,unittest
from pathlib import Path
from nova.native import NativeSpool,journal_record,collect_cloudtrail,cloud_record
from nova.core import Problem

class NativeTests(unittest.TestCase):
    def setUp(self):self.tmp=tempfile.TemporaryDirectory();self.path=Path(self.tmp.name)/'spool'
    def tearDown(self):self.tmp.cleanup()
    def test_cursor_and_page_survive_restart(self):
        s=NativeSpool(self.path,'host','process-json');s.commit_page('journald','cursor1',[('c1',{'message':'x'})]);s.close()
        s=NativeSpool(self.path,'host','process-json')
        try:self.assertEqual(s.cursor('journald'),'cursor1');self.assertEqual(s.c.execute('SELECT COUNT(*) FROM queue').fetchone()[0],1)
        finally:s.close()
    def test_capacity_rolls_back_cursor_and_entire_page(self):
        s=NativeSpool(self.path,'host','process-json');s.max_bytes=30
        try:
            with self.assertRaises(Problem):s.commit_page('journald','cursor2',[('1',{'x':'a'}),('2',{'x':'z'*50})])
            self.assertIsNone(s.cursor('journald'));self.assertEqual(s.status(),[])
        finally:s.close()
    def test_replayed_native_id_deduplicates(self):
        s=NativeSpool(self.path,'host','process-json')
        try:
            s.commit_page('journald','1',[('1',{'x':1})]);s.commit_page('journald','1',[('1',{'x':1})]);self.assertEqual(s.status()[0]['records'],1)
            with self.assertRaises(Problem):s.commit_page('journald','2',[('1',{'x':2})])
            self.assertEqual(s.cursor('journald'),'1')
        finally:s.close()
    def test_journal_keeps_native_evidence_and_no_false_process_start(self):
        r={'__CURSOR':'c1','__REALTIME_TIMESTAMP':'1789992000123456','_EXE':'/usr/sbin/sshd','_HOSTNAME':'h','_UID':'0','MESSAGE':'session closed'}
        key,data=journal_record(r);self.assertEqual(data['action'],'log');self.assertEqual(data['original'],r);self.assertIn('.123456',data['timestamp'])
    def event(self):
        r=dict(eventID='event1',eventTime='2026-09-21T12:00:00Z',eventName='StopLogging',eventSource='cloudtrail.amazonaws.com',userIdentity={'arn':'arn:example'},sourceIPAddress='AWS Internal')
        return dict(EventId='event1',CloudTrailEvent=json.dumps(r))
    def test_cloudtrail_page_token_durable_and_scope_fixed(self):
        parent=self
        class Client:
            def __init__(self):self.calls=[]
            def lookup_events(self,**kw):
                self.calls.append(kw)
                return {'Events':[parent.event()],'NextToken':'next'} if len(self.calls)==1 else {'Events':[]}
        s=NativeSpool(self.path,'aws','cloud-json');client=Client()
        try:
            args=(s,client,'2026-09-21T11:00:00Z','2026-09-21T13:00:00Z','us-east-1')
            self.assertEqual(collect_cloudtrail(*args),1);self.assertEqual(s.cursor('cloudtrail')['token'],'next')
            self.assertEqual(collect_cloudtrail(*args),0);self.assertTrue(s.cursor('cloudtrail')['done']);self.assertEqual(client.calls[1]['NextToken'],'next')
            self.assertEqual(collect_cloudtrail(*args),0);self.assertEqual(len(client.calls),2)
            with self.assertRaises(Problem):collect_cloudtrail(s,client,args[2],args[3],'other-region')
        finally:s.close()
    def test_cloud_identity_mismatch_is_not_advanced(self):
        event=self.event();event['EventId']='bad'
        with self.assertRaises(Problem):cloud_record(event)
    def test_native_journal_command_resumes_committed_cursor(self):
        import io
        from nova.native import collect_journal
        s=NativeSpool(self.path,'host','process-json');s.commit_page('journald','old',[]);commands=[]
        record=dict(__CURSOR='new',__REALTIME_TIMESTAMP='1789992000000000',_EXE='/bin/app',MESSAGE='log')
        class Process:
            def __init__(self,args,**kw):commands.append(args);self.stdout=io.BytesIO((json.dumps(record)+'\n').encode())
            def wait(self,timeout=None):return 0
            def poll(self):return 0
        try:
            self.assertEqual(collect_journal(s,popen=Process),1);self.assertEqual(commands[0][-2:],['--after-cursor','old']);self.assertEqual(s.cursor('journald'),'new')
        finally:s.close()
    def test_journal_bad_record_does_not_advance(self):
        import io
        from nova.native import collect_journal
        s=NativeSpool(self.path,'host','process-json')
        class Process:
            def __init__(self,*args,**kw):self.stdout=io.BytesIO(b'{"MESSAGE":"missing identity"}\n')
            def wait(self,timeout=None):return 0
            def poll(self):return 0
        try:
            with self.assertRaises(Problem):collect_journal(s,popen=Process)
            self.assertIsNone(s.cursor('journald'));self.assertEqual(s.status(),[])
        finally:s.close()
