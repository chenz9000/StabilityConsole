import base64,json,tempfile,threading,unittest
from pathlib import Path
from core import connect,add_application,update_application
from mail_sync import sync_mail,DEFAULTS,SyncError,AppWorker,protect
from browser_lookup import structured_proposal,choose_proposal,public_url
from gmail_panel import apply_lookup
from integration_runtime import InstanceLock

def raw(mid='m1',subject='Application received: Systems Engineer',body='We received your application for Systems Engineer at Example Employer.',thread='t1'):
 return {'id':mid,'threadId':thread,'payload':{'mimeType':'text/plain','headers':[{'name':'Subject','value':subject},{'name':'From','value':'jobs@example.org'},{'name':'Date','value':'Wed, 11 Nov 2026 10:00:00 +0200'}],'body':{'data':base64.urlsafe_b64encode(body.encode()).decode()}}}
class FakeGmail:
 def __init__(self):self.calls=[];self.account='test@example.org';self.reply=False
 def get(self,path,params=None):
  self.calls.append((path,params))
  if path=='profile':return {'emailAddress':self.account}
  if path=='messages':return {'messages':[{'id':'m1'}],'nextPageToken':'page2'} if not params.get('pageToken') else {'messages':[{'id':'m1'},{'id':'m2'}]}
  if path=='messages/m1':return raw()
  if path=='messages/m2':return raw('m2',subject='Newsletter',body='A generic newsletter without a matching role.',thread='unrelated')
  if path=='messages/m3':return raw('m3',subject='Next steps',body='Choose a time.')
  if path=='threads/t1':return {'messages':[{'id':'m1'}]+([{'id':'m3'}] if self.reply else [])}
  raise AssertionError(path)
class MailTests(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.db=Path(self.temp.name)/'test.db';self.conn=connect(self.db)
  self.ident=add_application(self.conn,'Systems Engineer',notes='Keep note',cv_version='CV-actual.pdf',status='Applied')
  self.client=FakeGmail();self.stop=threading.Event()
 def tearDown(self):self.conn.close();self.temp.cleanup()
 def sync(self):return sync_mail(self.conn,self.client,DEFAULTS,self.stop)
 def proposal(self,**extra):
  app=dict(self.conn.execute('SELECT * FROM applications').fetchone())
  job={'title':'Systems Engineer','hiringOrganization':{'name':'Example Employer','url':'https://example.org'},'jobLocation':{'address':{'addressLocality':'Knysna','addressCountry':'ZA'}},'validThrough':'2099-01-01',**extra}
  return structured_proposal(job,'https://example.org/jobs/1',app,{'subject':'Systems Engineer','body':'Example Employer received your application','sender':'jobs@example.org'})
 def test_paginated_collection_dedup_restart_and_linked_replies(self):
  self.assertIn('1 new relevant messages',self.sync());self.assertTrue(any(p and p.get('pageToken')=='page2' for _,p in self.client.calls))
  self.assertEqual(self.conn.execute('SELECT confidence FROM mail_matches').fetchone()[0],'Tentative title only')
  self.conn.close();self.conn=connect(self.db);self.sync()
  self.assertEqual(self.conn.execute('SELECT count(*) FROM mail_messages').fetchone()[0],1)
  with self.conn:self.conn.execute('INSERT INTO mail_bindings VALUES (?,?,?)',('test@example.org','t1',self.ident))
  self.client.reply=True;self.sync();self.assertEqual(self.conn.execute('SELECT count(*) FROM mail_messages').fetchone()[0],2)
  row=self.conn.execute('SELECT * FROM applications').fetchone();self.assertEqual((row['status'],row['cv_version'],row['notes']),('Applied','CV-actual.pdf','Keep note'))
  self.assertTrue(all(' before:' in p['q'] for path,p in self.client.calls if path=='messages'))
 def test_failed_collection_and_cancellation_are_not_success(self):
  class Bad:
   def get(self,*a,**kw):raise SyncError('Gmail returned 403. Check API.')
  with self.assertRaises(SyncError):sync_mail(self.conn,Bad(),DEFAULTS,self.stop)
  self.assertEqual(self.conn.execute('SELECT outcome FROM mail_runs').fetchone()[0],'FAILED')
  self.stop.set()
  with self.assertRaises(SyncError):self.sync()
  self.assertEqual(self.conn.execute("SELECT count(*) FROM mail_runs WHERE outcome='CANCELLED'").fetchone()[0],1)
 def test_account_mismatch_and_isolation(self):
  with self.assertRaises(SyncError):sync_mail(self.conn,self.client,{**DEFAULTS,'account':'different@example.org'},self.stop)
  self.sync();self.client.account='other@example.org';self.sync();self.assertEqual(self.conn.execute('SELECT count(*) FROM mail_messages').fetchone()[0],2)
 def test_blank_autofill_keeps_status_cv_notes_and_source_evidence(self):
  self.sync();result=choose_proposal([self.proposal()]);self.assertEqual(result['state'],'CORROBORATED')
  fields=apply_lookup(self.conn,'test@example.org','m1',self.ident,result);self.assertEqual(set(fields),{'employer','area','url'})
  row=self.conn.execute('SELECT * FROM applications').fetchone();self.assertEqual((row['employer'],row['status'],row['cv_version'],row['notes']),('Example Employer','Applied','CV-actual.pdf','Keep note'))
  self.assertEqual(apply_lookup(self.conn,'test@example.org','m1',self.ident,result),[])
  self.assertIn('source',self.conn.execute('SELECT details FROM events ORDER BY id DESC').fetchone()[0])
 def test_concurrent_edit_blocks_auto_fill(self):
  self.sync();p=self.proposal();update_application(self.conn,self.ident,employer='Different Employer')
  self.assertEqual(apply_lookup(self.conn,'test@example.org','m1',self.ident,choose_proposal([p])),[])
 def test_ambiguous_and_expired_are_review_only(self):
  p=self.proposal();other=self.proposal(jobLocation={'address':{'addressLocality':'George'}})
  self.assertEqual(choose_proposal([p,other])['state'],'AMBIGUOUS')
  self.assertFalse(self.proposal(description='Closing dtae - 27 October 2020')['auto_eligible'])
  job={'title':'Systems Engineer','hiringOrganization':{'name':'Other'}}
  unconfirmed=structured_proposal(job,'https://example.org/jobs/1',{'title':'Systems Engineer','employer':'','area':''},{'body':'','sender':''})
  self.assertEqual(choose_proposal([unconfirmed])['state'],'REVIEW')
 def test_page_budget_is_partial_and_resumes_same_window(self):
  class Many(FakeGmail):
   more=True
   def get(self,path,params=None):
    if path=='messages':
     self.calls.append((path,dict(params)))
     return {'messages':[{'id':'m1'}],**({'nextPageToken':'more'} if self.more else {})}
    return super().get(path,params)
  c=Many();summary=sync_mail(self.conn,c,DEFAULTS,self.stop)
  self.assertTrue(summary.startswith('PARTIAL'))
  self.assertEqual(self.conn.execute('SELECT outcome FROM mail_runs').fetchone()[0],'PARTIAL')
  query=c.calls[1][1]['q'];c.more=False;sync_mail(self.conn,c,DEFAULTS,self.stop)
  last=[p for path,p in c.calls if path=='messages'][-1]
  self.assertEqual(last['q'],query)
  self.assertEqual(self.conn.execute('SELECT count(*) FROM mail_messages').fetchone()[0],1)
 def test_rejected_page_token_clears_checkpoint_for_next_cycle(self):
  from mail_sync import PageTokenError
  self.sync()
  with self.conn:self.conn.execute("UPDATE mail_cursors SET page_token='bad'")
  class Rejected(FakeGmail):
   def get(self,path,params=None):
    if path=='messages' and params.get('pageToken')=='bad':raise PageTokenError('checkpoint rejected')
    return super().get(path,params)
  with self.assertRaises(SyncError):sync_mail(self.conn,Rejected(),DEFAULTS,self.stop)
  self.assertEqual(self.conn.execute('SELECT page_token FROM mail_cursors').fetchone()[0],'')
  self.sync();self.assertEqual(self.conn.execute('SELECT count(*) FROM mail_messages').fetchone()[0],1)
 def test_public_advert_urls_exclude_actions_and_private_targets(self):
  for url in ['http://example.org/jobs/1','https://127.0.0.1/jobs/1','https://localhost/jobs/1','https://host.local/jobs/1','https://example.org/jobs/1?token=private','https://example.org/unsubscribe','https://example.org/apply/1']:
   self.assertEqual(public_url(url),'',url)
  self.assertEqual(public_url('https://example.org/jobs/1'),'https://example.org/jobs/1')
 def test_worker_overlap_and_cancellation(self):
  w=AppWorker();entered=threading.Event()
  def work(stop,progress):entered.set();stop.wait(2);return 'cancelled'
  self.assertTrue(w.start(work));self.assertTrue(entered.wait(1));self.assertFalse(w.start(work));w.close();w.thread.join(1);self.assertFalse(w.busy)
 def test_single_instance_lock_release(self):
  a=InstanceLock(self.temp.name);b=InstanceLock(self.temp.name);a.acquire()
  with self.assertRaises(SyncError):b.acquire()
  a.release();b.acquire();b.release()
 def test_encrypted_storage_has_no_plaintext_fallback(self):
  import os
  if os.name!='nt':
   with self.assertRaises(SyncError):protect(b'controlled-test-token')
if __name__=='__main__':unittest.main()
