
import runpy,unittest,tempfile,sqlite3
from pathlib import Path
from unittest.mock import patch
import types
ns=runpy.run_path(str(Path(__file__).with_name('BRIDGE-managed')),run_name='bridge_test')
g=ns['_lc_shutdown'].__globals__
class Tests(unittest.TestCase):
 def test_idle_stop(self):
  with patch.dict(g,{'_lc_idle':lambda:True,'_lc_status':iter([42,None]).__next__,'_lc_safe_service':lambda p:True,'_lc_watchers':lambda:[],'_lc_sv':lambda *a:None}):
   self.assertTrue(g['_lc_shutdown']())
 def test_foreign_watcher(self):
  with patch.dict(g,{'_lc_idle':lambda:True,'_lc_status':lambda:42,'_lc_safe_service':lambda p:True,'_lc_watchers':lambda:[43],'_lc_descendant':lambda *a:False,'_lc_sv':lambda *a:self.fail('must not stop')}):
   self.assertFalse(g['_lc_shutdown']())
 def test_active_work(self):
  clock=iter([0,21])
  with patch.dict(g,{'_lc_idle':lambda:False,'_lc_time':types.SimpleNamespace(monotonic=clock.__next__),'_lc_status':lambda:self.fail('must not stop')}):
   self.assertFalse(g['_lc_shutdown']())
 def test_unknown_state(self):
  def error():raise RuntimeError()
  with patch.dict(g,{'_lc_idle':error,'_lc_status':lambda:self.fail('must not stop')}):
   self.assertFalse(g['_lc_shutdown']())
 def test_already_down(self):
  with patch.dict(g,{'_lc_idle':lambda:True,'_lc_status':lambda:None,'_lc_watchers':lambda:[]}):
   self.assertTrue(g['_lc_shutdown']())
 def test_explicit_command_unchanged(self):
  with patch.dict(g,{'_LC_DEFAULT':False,'main':lambda:17,'_lc_shutdown':lambda:self.fail('must not stop')}):
   self.assertEqual(g['_lc_managed_main'](),17)
 def test_default_ctrl_c(self):
  def interrupted():raise KeyboardInterrupt()
  with tempfile.TemporaryDirectory() as d, patch('pathlib.Path.home',return_value=Path(d)),patch.dict(g,{'_LC_DEFAULT':True,'main':interrupted,'_lc_shutdown':lambda:True}):
   self.assertEqual(g['_lc_managed_main'](),0)
 def test_default_close(self):
  with tempfile.TemporaryDirectory() as d, patch('pathlib.Path.home',return_value=Path(d)),patch.dict(g,{'_LC_DEFAULT':True,'main':lambda:0,'_lc_shutdown':lambda:True}):
   self.assertEqual(g['_lc_managed_main'](),0)
 def test_fallback(self):
  states=iter([42,42,42,None]);watchers=iter([[43],[43],[],[]]);calls=[]
  with patch.dict(g,{'_lc_idle':lambda:True,'_lc_status':states.__next__,'_lc_safe_service':lambda p:True,'_lc_watchers':watchers.__next__,'_lc_descendant':lambda *a:True,'_lc_proc':lambda p:(42,[b'/root/projects/eclipse-chat-bridge/watch.py']),'_lc_sv':lambda *a:calls.append(a),'_lc_os':types.SimpleNamespace(kill=lambda *a:calls.append(a)),'_lc_time':types.SimpleNamespace(monotonic=lambda:0,sleep=lambda s:None)}):
   self.assertTrue(g['_lc_shutdown']());self.assertIn(('-w','8','force-stop'),calls)
if __name__=='__main__':unittest.main()
