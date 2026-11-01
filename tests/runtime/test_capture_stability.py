import struct,zlib,unittest
from test_runtime import Runner,Clock,PNG,chunk
from reproloop.runtime.owned import OwnedTarget,OwnedAdbTransport,RuntimeStop,CommandResult

RED=b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR',struct.pack('>IIBBBBB',100,100,8,2,0,0,0))+chunk(b'IDAT',zlib.compress((b'\x00'+b'\xff\x00\x00'*100)*100))+chunk(b'IEND',b'')
class ChangingScreens(Runner):
    def __init__(self,screens):super().__init__();self.screens=iter(screens);self.reads=0
    def __call__(self,argv,timeout,max_output):
        if argv[5:]==('exec-out','screencap','-p'):
            self.reads+=1;return CommandResult(0,next(self.screens))
        return super().__call__(argv,timeout,max_output)

class CaptureStabilityTests(unittest.TestCase):
    def transport(self,runner):
        target=OwnedTarget('emulator-5554','Owned_AVD','parent-owned','boot-1','a'*64,'run-1',1)
        return OwnedAdbTransport(target,runner,Clock(),'/fake/adb')

    def test_stable_bracket_uses_two_screenshots_and_no_input(self):
        runner=ChangingScreens([PNG,PNG]);transport=self.transport(runner)
        frame=transport.capture(transport.clock.monotonic()+20)
        self.assertEqual(frame.png,PNG);self.assertEqual(runner.reads,2);self.assertEqual(runner.taps,0)
        self.assertTrue(transport.capture_probes[-1]['stable'])

    def test_transition_is_resampled_read_only_before_model(self):
        runner=ChangingScreens([PNG,RED,RED,RED]);transport=self.transport(runner)
        frame=transport.capture(transport.clock.monotonic()+20)
        self.assertEqual(frame.png,RED);self.assertEqual(frame.sequence,1)
        self.assertEqual([p['stable'] for p in transport.capture_probes],[False,True]);self.assertEqual(runner.taps,0)

    def test_persistent_animation_fails_closed_without_input(self):
        runner=ChangingScreens([PNG,RED,PNG,RED]);transport=self.transport(runner)
        with self.assertRaises(RuntimeStop):transport.capture(transport.clock.monotonic()+20)
        self.assertEqual(runner.reads,4);self.assertEqual(runner.taps,0);self.assertEqual(transport.sequence,0)
