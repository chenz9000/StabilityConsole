import json
from pathlib import Path
import tempfile
import threading
import unittest
from gmail_setup import checkpoint, save_checkpoint, setup_phase, GOOGLE_STEPS, wait_for_restart_unlock, restart_command
from integration_runtime import InstanceLock
from mail_sync import SyncError

class SetupTests(unittest.TestCase):
 def setUp(self):self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
 def tearDown(self):self.temp.cleanup()
 def phase(self,**kw):return setup_phase(self.root,platform='nt',ready=True,active=True,**kw)
 def test_ordered_prerequisites_and_no_fake_google_success(self):
  self.assertEqual(setup_phase(self.root,platform='posix'),'unsupported')
  self.assertEqual(setup_phase(self.root,platform='nt',ready=False,active=False),'support')
  self.assertEqual(setup_phase(self.root,platform='nt',ready=True,active=False),'restart')
  self.assertEqual(self.phase(verified=True),'registration')
  (self.root/'gmail-client.dpapi').write_bytes(b'controlled file-presence fixture, not a real credential')
  self.assertEqual(self.phase(),'signin')
  (self.root/'gmail-token.dpapi').write_bytes(b'controlled fixture, not a real token')
  self.assertEqual(self.phase(),'verify')
  self.assertEqual(self.phase(verified=True),'ready')
 def test_resume_progress_and_explicit_finish(self):
  self.assertFalse(checkpoint(self.root)['active'])
  save_checkpoint(self.root,True,3)
  self.assertEqual(checkpoint(self.root),{'active':True,'google_step':3})
  save_checkpoint(self.root,False,3)
  self.assertEqual(checkpoint(self.root),{'active':False,'google_step':3})
  raw=json.loads((self.root/'gmail-setup-progress.json').read_text())
  self.assertEqual(set(raw),{'active','google_step','updated_at','version'})
 def test_bad_progress_does_not_autorun(self):
  (self.root/'gmail-setup-progress.json').write_text('{broken')
  self.assertFalse(checkpoint(self.root)['active']);self.assertIn('warning',checkpoint(self.root))
  (self.root/'gmail-setup-progress.json').write_text(json.dumps({'active':'yes','google_step':999}))
  self.assertFalse(checkpoint(self.root)['active']);self.assertEqual(checkpoint(self.root)['google_step'],len(GOOGLE_STEPS)-1)
 def test_invalid_step_does_not_replace_good_checkpoint(self):
  save_checkpoint(self.root,True,1)
  with self.assertRaises(ValueError):save_checkpoint(self.root,True,999)
  self.assertEqual(checkpoint(self.root)['google_step'],1)
 def test_restart_waits_for_old_instance_without_force_unlock(self):
  lock=InstanceLock(self.root);lock.acquire()
  with self.assertRaises(SyncError):wait_for_restart_unlock(self.root,timeout=0)
  timer=threading.Timer(.15,lock.release);timer.start()
  wait_for_restart_unlock(self.root,timeout=2);timer.join()
  again=InstanceLock(self.root);again.acquire();again.release()
 def test_restart_command_contains_no_account_or_credentials(self):
  args=restart_command()
  self.assertTrue(Path(args[1]).name=='launch.py')
  self.assertEqual(args[2:],['--resume-gmail-setup','--wait-for-lock'])
 def test_google_links_are_fixed_official_pages(self):
  from urllib.parse import urlparse
  for title,body,url,value in GOOGLE_STEPS:
   self.assertEqual(urlparse(url).scheme,'https')
   self.assertIn(urlparse(url).hostname,('console.cloud.google.com','console.developers.google.com'))
if __name__=='__main__':unittest.main()
