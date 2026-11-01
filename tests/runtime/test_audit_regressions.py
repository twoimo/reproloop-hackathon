import dataclasses,pathlib,tempfile,unittest
from test_runtime import Runner, PNG, chunk
from reproloop.runtime.owned import OwnedTarget,OwnedAdbTransport,RuntimeStop,png_size,PACKAGE
from reproloop.runtime.driver import RuntimeJournal,RuntimeDriver,ActionRequest
class Clock:
 def __init__(self):self.now=0.
 def monotonic(self):return self.now
 def sleep(self,s):self.now+=s
class TimedRunner(Runner):
 def __init__(self,clock):super().__init__();self.clock=clock;self.step=0.
 def __call__(self,args,timeout,max_output):
  if self.step>=timeout:raise TimeoutError('bounded deadline')
  result=super().__call__(args,timeout,max_output);self.clock.now+=self.step;return result
class AuditRegressions(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.c=Clock();self.r=TimedRunner(self.c)
  self.t=OwnedTarget('emulator-5554','Owned_AVD','parent-owned','boot-1','a'*64,'run-1',1)
  self.j=RuntimeJournal(str(pathlib.Path(self.tmp.name)/'journal.db'),'host-boot');self.d=self.make(self.t);self.d.start(.1)
 def make(self,t):return RuntimeDriver(OwnedAdbTransport(t,self.r,self.c,'/fake/adb'),self.j,self.c,100)
 def test_cancel_tombstone_survives_new_lease_and_expiry(self):
  self.d.cancel();self.c.now=.2;other=self.make(dataclasses.replace(self.t,run_id='run-2',generation=2));other.start(.1);self.c.now=.4
  with self.assertRaises(RuntimeStop):self.d.start(.1)
  self.assertEqual(self.r.taps,0)
 def test_cancel_tombstone_survives_new_driver_and_journal(self):
  self.d.cancel();self.c.now=.3;self.j=RuntimeJournal(self.j.path,'host-boot')
  with self.assertRaises(RuntimeStop):self.make(self.t).start(.1)
 def test_capture_clips_total_lease(self):
  self.r.step=.02
  with self.assertRaises((RuntimeStop,TimeoutError)):self.d.capture()
  self.assertEqual(self.r.taps,0)
 def test_slow_predicate_makes_already_dispatched_action_unknown(self):
  f=self.d.capture()
  def slow(_):self.c.sleep(.2);return True
  rec=self.d.execute(ActionRequest('a','r','tap',f.evidence_sha256,PACKAGE+':id/cancel','Cancel'),f,slow)
  self.assertEqual(rec.state,'UNKNOWN');self.assertEqual(self.r.taps,1)
 def test_unknown_critical_chunk_rejected_and_good_png_accepted(self):
  self.assertEqual(png_size(PNG),(100,100))
  with self.assertRaises(RuntimeStop):png_size(PNG[:-12]+chunk(b'ABCD',b'bad')+PNG[-12:])

class NativeProtocolControls(unittest.TestCase):
 def test_sdk_console_crlf_preserves_exact_identity(self):
  clock=Clock()
  class CRLFRunner(Runner):
   def __call__(self,args,timeout,max_output):
    value=super().__call__(args,timeout,max_output)
    if args[5:]==('emu','avd','name'):
     from reproloop.runtime.owned import CommandResult
     return CommandResult(value.code,value.stdout.replace(b'\n',b'\r\n'),value.stderr)
    return value
  t=OwnedTarget('emulator-5554','Owned_AVD','parent-owned','boot-1','a'*64,'run-1',1)
  OwnedAdbTransport(t,CRLFRunner(),clock,'/fake/adb').discover(100)

class NativeHierarchyControls(unittest.TestCase):
 def test_framework_content_is_structural_only(self):
  from reproloop.runtime.owned import parse_hierarchy
  from test_runtime import XML
  extra=b'<node package="com.tinyburn.reproloop.lab" class="android.widget.FrameLayout" resource-id="android:id/content" text="" clickable="false" bounds="[0,0][100,100]"/>'
  nodes=parse_hierarchy(XML.replace(b'</hierarchy>',extra+b'</hierarchy>'),100,100)
  self.assertEqual(sum(n.resource_id=='android:id/content' for n in nodes),0)
  with self.assertRaises(RuntimeStop):parse_hierarchy(XML.replace(b'</hierarchy>',extra.replace(b'clickable="false"',b'clickable="true"')+b'</hierarchy>'),100,100)
