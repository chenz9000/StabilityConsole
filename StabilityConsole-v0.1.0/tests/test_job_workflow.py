import hashlib
import json
import tempfile
import threading
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from core import connect, add_application, add_task, update_application, metrics
from job_workflow import (ensure_schema, validate_report, load_report, import_report,
    save_fact, link_document, approve_document, start_session, complete_session,
    due_check, recover_sessions, check_result, retry_check)
from mail_sync import DEFAULTS, SyncError, match_message
from gmail_panel import GmailPanel


def report():
    return {'schema_version':1,'namespace':'career-search','report_id':'session-1','account':'candidate@example.org',
        'applications':[{'external_id':'A-1','title':'Support Technician','employer':'Example Ltd',
            'area':'Example town','url':'https://example.org/jobs/1','status':'SENT','cv_version':'support.pdf',
            'evidence':[{'kind':'submission','message_id':'message-1','thread_id':'thread-1','url':'https://mail.google.com/mail/#all/message-1'}]}],
        'profile':[{'name':'Work authorization','value':'','state':'UNKNOWN','source':'Candidate has not confirmed'}],
        'documents':[{'document_key':'profile','filename':'profile.docx','sha256':'a'*64,'state':'APPROVED','application_external_id':'A-1','source':'Candidate reviewed source report'}]}


def ingest(conn,value):
    digest=hashlib.sha256(json.dumps(value,sort_keys=True).encode()).hexdigest()
    return import_report(conn,value,digest,'private-session.json')


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.conn=connect(self.root/'stability.db');ensure_schema(self.conn,self.root)
    def tearDown(self):
        self.conn.close();self.temp.cleanup()

    def test_backup_and_existing_records_survive_migration(self):
        other=connect(self.root/'old.db');ident=add_application(other,'Existing','Employer',notes='Keep this')
        add_task(other,'Keep task')
        folder=self.root/'migration';folder.mkdir();ensure_schema(other,folder)
        snapshot=connect(folder/'before-workflow-v0.3.0.db')
        self.assertEqual(snapshot.execute('SELECT notes FROM applications WHERE id=?',(ident,)).fetchone()[0],'Keep this')
        self.assertEqual(other.execute('SELECT count(*) FROM tasks').fetchone()[0],1)
        snapshot.close();other.close()

    def test_dedup_updates_and_failed_delivery_is_not_applied(self):
        value=report();self.assertEqual(ingest(self.conn,value)['created'],1)
        self.assertTrue(ingest(self.conn,value)['duplicate'])
        self.assertEqual(metrics(self.conn)['applied'],1)
        value['report_id']='session-2';value['applications'][0]['status']='FAILED'
        value['applications'][0]['evidence'].append({'kind':'bounce','message_id':'bounce-2','detail':'550 recipient rejected'})
        ingest(self.conn,value)
        self.assertEqual(self.conn.execute('SELECT count(*) FROM applications').fetchone()[0],1)
        self.assertEqual(self.conn.execute('SELECT count(*) FROM workflow_evidence').fetchone()[0],2)
        self.assertEqual(metrics(self.conn)['applied'],0)

    def test_local_edits_and_omitted_fields_are_preserved(self):
        value=report();ingest(self.conn,value)
        ident=self.conn.execute('SELECT id FROM applications').fetchone()[0]
        update_application(self.conn,ident,status='Interview scheduled',notes='Private local note')
        save_fact(self.conn,'Availability','By arrangement','CONFIRMED')
        value['report_id']='session-2';value['applications'][0]['status']='REJECTED'
        value['applications'][0].pop('cv_version')
        value['profile'].append({'name':'Availability','value':'','state':'UNKNOWN','source':'Report'})
        result=ingest(self.conn,value)
        row=self.conn.execute('SELECT * FROM applications').fetchone()
        self.assertEqual(row['status'],'Interview scheduled');self.assertEqual(row['notes'],'Private local note')
        self.assertEqual(row['cv_version'],'support.pdf');self.assertGreater(result['preserved'],0)
        self.assertEqual(self.conn.execute("SELECT value FROM workflow_facts WHERE name='Availability'").fetchone()[0],'By arrangement')
        self.assertEqual(self.conn.execute("SELECT state FROM workflow_facts WHERE name='Work authorization'").fetchone()[0],'UNKNOWN')

    def test_atomic_rollback_and_validation(self):
        self.conn.execute("CREATE TRIGGER fail_document BEFORE INSERT ON workflow_documents BEGIN SELECT RAISE(ABORT,'blocked fixture'); END")
        self.conn.commit()
        with self.assertRaises(Exception):ingest(self.conn,report())
        self.assertEqual(self.conn.execute('SELECT count(*) FROM applications').fetchone()[0],0)
        self.assertEqual(self.conn.execute('SELECT count(*) FROM mail_bindings').fetchone()[0],0)
        value=report();value['applications'][0]['evidence']=[{'kind':'advert','url':'https://example.org/jobs/1'}]
        with self.assertRaises(ValueError):validate_report(value)

    def test_thread_account_binding_and_existing_application_reuse(self):
        ident=add_application(self.conn,'Support Technician','Example Ltd',url='https://example.org/jobs/1')
        value=report();ingest(self.conn,value)
        self.assertEqual(self.conn.execute('SELECT count(*) FROM applications').fetchone()[0],1)
        row=self.conn.execute('SELECT * FROM mail_bindings').fetchone()
        self.assertEqual(row['account'],'candidate@example.org');self.assertEqual(row['application_id'],ident)
        self.assertEqual(self.conn.execute('SELECT status FROM applications').fetchone()[0],'Discovered')

    def test_document_approval_is_bound_to_bytes(self):
        path=self.root/'profile.txt';path.write_text('Reviewed contents')
        first=link_document(self.conn,'profile',path);approve_document(self.conn,'profile',first)
        path.write_text('Changed contents')
        with self.assertRaisesRegex(ValueError,'changed'):approve_document(self.conn,'profile',first)
        second=link_document(self.conn,'profile',path)
        self.assertNotEqual(first,second)
        self.assertEqual(self.conn.execute('SELECT state FROM workflow_documents WHERE sha256=?',(second,)).fetchone()[0],'REVIEW REQUIRED')

    def test_five_minute_deadline_restart_and_retry(self):
        at=datetime(2026,1,1,8,tzinfo=timezone.utc)
        ident=start_session(self.conn,at=at);complete_session(self.conn,ident,at=at)
        with self.assertRaises(ValueError):complete_session(self.conn,ident,at=at)
        self.assertIsNone(due_check(self.conn,at+timedelta(seconds=299)))
        recover_sessions(self.conn)
        self.assertEqual(due_check(self.conn,at+timedelta(seconds=300))['id'],ident)
        check_result(self.conn,ident,'RUNNING','Checking');recover_sessions(self.conn)
        self.assertEqual(self.conn.execute('SELECT check_state FROM workflow_sessions').fetchone()[0],'UNKNOWN')
        retry_check(self.conn,ident);self.assertIsNotNone(due_check(self.conn,at+timedelta(minutes=6)))

    def test_json_size_and_encoding_failures_are_visible(self):
        path=self.root/'invalid.json';path.write_bytes(b'not json')
        with self.assertRaises(ValueError):load_report(path)
        path.write_text(json.dumps(report()));value,digest=load_report(path)
        self.assertEqual(value['report_id'],'session-1');self.assertEqual(len(digest),64)

    def test_cancelled_import_rolls_back_completed_rows(self):
        value=report();stop=threading.Event()
        digest=hashlib.sha256(json.dumps(value).encode()).hexdigest()
        with self.assertRaisesRegex(ValueError,'CANCELLED'):
            import_report(self.conn,value,digest,stop=stop,progress=lambda _:stop.set())
        self.assertEqual(self.conn.execute('SELECT count(*) FROM applications').fetchone()[0],0)
        self.assertEqual(self.conn.execute('SELECT count(*) FROM workflow_reports').fetchone()[0],0)

    def test_cancelled_file_read_does_not_create_approval(self):
        path=self.root/'cancelled.txt';path.write_text('Review me')
        stop=threading.Event();stop.set()
        with self.assertRaisesRegex(ValueError,'CANCELLED'):link_document(self.conn,'file',path,stop=stop)
        self.assertEqual(self.conn.execute('SELECT count(*) FROM workflow_documents').fetchone()[0],0)

    def test_imported_session_is_historical_not_a_live_check(self):
        value=report();value['session']={'started_at':'2026-01-01T08:00:00+00:00','completed_at':'2026-01-01T08:15:00+00:00','check_detail':'Source reports a completed mail check.'}
        ingest(self.conn,value)
        row=self.conn.execute('SELECT * FROM workflow_sessions').fetchone()
        self.assertEqual(row['state'],'RECORDED');self.assertEqual(row['check_state'],'REPORTED')
        self.assertIsNone(due_check(self.conn))

    def test_partial_collection_does_not_become_pass(self):
        add_application(self.conn,'Support','Example')
        class Client:
            def get(self,resource,params=None):
                if resource=='profile':return {'emailAddress':'candidate@example.org'}
                return {'messages':[],'nextPageToken':'more-pages'}
        ident=start_session(self.conn);complete_session(self.conn,ident)
        panel=object.__new__(GmailPanel);panel.root_dir=self.root;panel.mail_settings={**DEFAULTS,'account':'candidate@example.org'}
        panel.mail_start=lambda work:work(threading.Event(),lambda _:None)
        with patch('gmail_panel.credentials',return_value=object()),patch('gmail_panel.GmailClient',return_value=Client()):
            panel.mail_sync_now(workflow_session_id=ident)
        self.assertEqual(self.conn.execute('SELECT check_state FROM workflow_sessions').fetchone()[0],'PARTIAL')

    def test_delayed_check_records_actual_collection_and_failure(self):
        class Client:
            def get(self,resource,params=None):return {'emailAddress':'candidate@example.org'} if resource=='profile' else {'messages':[]}
        ident=start_session(self.conn);complete_session(self.conn,ident)
        panel=object.__new__(GmailPanel);panel.root_dir=self.root;panel.mail_settings={**DEFAULTS,'account':'candidate@example.org','enrich':True}
        panel.mail_start=lambda work:work(threading.Event(),lambda _:None)
        with patch('gmail_panel.credentials',return_value=object()),patch('gmail_panel.GmailClient',return_value=Client()),patch('gmail_panel.browser_enrich') as lookup:
            panel.mail_sync_now(workflow_session_id=ident)
        row=self.conn.execute('SELECT * FROM workflow_sessions').fetchone()
        self.assertEqual(row['check_state'],'PASS');self.assertTrue(row['mail_run_id']);lookup.assert_not_called()
        with patch('gmail_panel.credentials',side_effect=SyncError('Reconnect required')):
            with self.assertRaises(SyncError):panel.mail_sync_now(workflow_session_id=ident)
        self.assertEqual(self.conn.execute('SELECT check_state FROM workflow_sessions').fetchone()[0],'FAILED')

    def test_bounce_and_role_withdrawal_are_distinct_suggestions(self):
        app={'title':'Support Technician','employer':'Example Ltd'}
        bounce={'subject':'Delivery Status Notification (Failure)','body':'Support Technician: recipient address rejected','sender':'mailer-daemon@example.org'}
        self.assertEqual(match_message(app,bounce)[2],'Failed')
        withdrawn={'subject':'Support Technician Application unsuccessful','body':'The role has been withdrawn due to changed requirements.','sender':'recruiter@example.org'}
        self.assertEqual(match_message(app,withdrawn)[2],'Withdrawn')


if __name__=='__main__':unittest.main()
