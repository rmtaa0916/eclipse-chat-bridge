
import unittest,tempfile,json,gzip
from pathlib import Path
from bridge_archive_compression import compress,restore,maintain_archives
class Tests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.d=Path(self.tmp.name);self.p=self.d/'bridge_old.json';self.raw=json.dumps({'text':'x'*10000}).encode();self.p.write_bytes(self.raw)
 def tearDown(self):self.tmp.cleanup()
 def test_roundtrip(self):
  a,b=compress(self.p,True);self.assertLess(b,a);self.assertFalse(self.p.exists());self.assertEqual(restore(self.p.with_suffix('.json.gz')).read_bytes(),self.raw)
 def test_retention(self):
  compress(self.p);self.assertTrue(self.p.exists())
 def test_mismatch(self):
  self.p.with_suffix('.json.gz').write_bytes(gzip.compress(b'wrong'));self.assertRaises(ValueError,compress,self.p,True);self.assertTrue(self.p.exists())
 def test_recent(self):
  self.assertEqual(maintain_archives(self.d,min_age=999999,keep=0),[])
 def test_keep(self):
  self.assertEqual(maintain_archives(self.d,min_age=0,keep=1),[])
 def test_bad_json(self):
  self.p.write_bytes(b'not json');self.assertRaises(ValueError,compress,self.p,True);self.assertTrue(self.p.exists())
 def test_restore_conflict(self):
  compress(self.p);self.p.write_bytes(b'{}');self.assertRaises(ValueError,restore,self.p.with_suffix('.json.gz'))
 def test_symlink(self):
  q=self.d/'bridge_link.json';q.symlink_to(self.p);self.assertRaises(ValueError,compress,q,True)
 def test_bounded(self):
  (self.d/'bridge_2.json').write_bytes(self.raw);self.assertEqual(len(maintain_archives(self.d,keep=0,min_age=0,limit=1)),1)
if __name__=='__main__':unittest.main()
