import sys,unittest
from reproloop.host import BoundedRunner
class HostTests(unittest.TestCase):
 def test_normal(self):
  r=BoundedRunner()((sys.executable,'-c','print("owned")'),2,1024);self.assertEqual(r.code,0);self.assertEqual(r.stdout,b'owned\n')
 def test_timeout(self):
  with self.assertRaises(TimeoutError):BoundedRunner()((sys.executable,'-c','import time;time.sleep(5)'),.1,1024)
 def test_output_bound(self):
  with self.assertRaises(ValueError):BoundedRunner()((sys.executable,'-c','print("x"*100000)'),2,1024)
