"""Regression witnesses for the independent 782783d runtime audit; no native I/O."""
import dataclasses
from contextlib import closing
import pathlib
import sqlite3
import tempfile
import unittest
import zlib
from unittest.mock import patch
import test_runtime as fixtures
from reproloop.runtime.owned import OwnedTarget, OwnedAdbTransport, RuntimeStop, PACKAGE, png_size, parse_hierarchy
from reproloop.runtime.driver import RuntimeJournal, RuntimeDriver, ActionRequest


class Clock:
    def __init__(self): self.now = 0.
    def monotonic(self): return self.now
    def sleep(self, seconds): self.now += seconds


class TimedRunner(fixtures.Runner):
    def __init__(self, clock):
        super().__init__(); self.clock = clock; self.step = 0.; self.dispatch_times = []
    def __call__(self, argv, timeout, max_output):
        self.dispatch_times.append(self.clock.now)
        if self.step >= timeout:
            self.clock.sleep(timeout)
            raise TimeoutError('bounded runner timeout')
        result = super().__call__(argv, timeout, max_output)
        self.clock.sleep(self.step)
        return result


class RepairTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.clock = Clock(); self.runner = TimedRunner(self.clock)
        self.target = OwnedTarget('emulator-5554','Owned_AVD','parent-owned','boot-1','a'*64,'run-1',1)
        self.path = str(pathlib.Path(self.tmp.name)/'journal.db')
        self.journal = RuntimeJournal(self.path,'host-boot')
        self.driver = self.make_driver(self.target)
        self.driver.start(.1)
    def make_driver(self, target, journal=None):
        transport = OwnedAdbTransport(target,self.runner,self.clock,'/fake/adb')
        return RuntimeDriver(transport,journal or self.journal,self.clock,100)
    def request(self, frame):
        return ActionRequest('a','r','tap',frame.evidence_sha256,PACKAGE+':id/cancel','Cancel')
    def test_cancelled_generation_stays_dead_after_replacement_expiry_and_reopen(self):
        self.driver.cancel(); self.clock.now = .2
        second = self.make_driver(dataclasses.replace(self.target,run_id='run-2',generation=2))
        second.start(.1); self.clock.now = .4
        reopened = RuntimeJournal(self.path,'host-boot')
        for target in (self.target,dataclasses.replace(self.target,run_id='other-old-run')):
            with self.subTest(target=target), self.assertRaises(RuntimeStop):
                self.make_driver(target,reopened).start(.1)
        self.assertEqual(self.runner.taps,0)
    def test_non_cancelled_old_generation_cannot_restart(self):
        self.clock.now = .2
        self.make_driver(dataclasses.replace(self.target,run_id='run-2',generation=2)).start(.1)
        self.clock.now = .4
        with self.assertRaisesRegex(RuntimeStop,'superseded generation'): self.driver.start(.1)
    def test_same_generation_new_run_allowed_but_retired_run_not_revived(self):
        self.clock.now = .2
        second = self.make_driver(dataclasses.replace(self.target,run_id='fresh-run'))
        second.start(.1); self.clock.now = .4
        with self.assertRaisesRegex(RuntimeStop,'retired'): self.driver.start(.1)
        second.start(.1)  # same active identity may renew expired lease
        self.assertIsNotNone(second.capture())
    def test_cancelled_run_cannot_evade_tombstone_by_changing_binding(self):
        self.driver.cancel(); self.clock.now = .2
        self.make_driver(dataclasses.replace(self.target,run_id='fresh-run')).start(.1)
        self.clock.now = .4
        changed = dataclasses.replace(self.target,apk_sha256='b'*64)
        driver = self.make_driver(changed)
        # Identity discovery remains trusted; isolate durable ledger behavior.
        with patch.object(driver.transport,'discover',lambda _:None):
            with self.assertRaisesRegex(RuntimeStop,'cancelled/retired'): driver.start(.1)
        with self.assertRaisesRegex(RuntimeStop,'cancelled/retired'): self.driver.start(.1)
    def test_legacy_cancelled_lease_is_imported_without_generation_off_by_one(self):
        self.driver.cancel()
        with closing(sqlite3.connect(self.path)) as db:
            db.execute('DROP TABLE run_history'); db.commit()
        legacy = RuntimeJournal(self.path,'host-boot')
        self.clock.now = .2
        with self.assertRaises(RuntimeStop): self.make_driver(self.target,legacy).start(.1)
        self.make_driver(dataclasses.replace(self.target,run_id='fresh-run'),legacy).start(.1)
    def test_unknown_still_blocks_new_generation(self):
        frame = self.driver.capture(); self.runner.fail_tap = True
        self.assertEqual(self.driver.execute(self.request(frame),frame,lambda _:True).state,'UNKNOWN')
        self.clock.now = .2
        with self.assertRaisesRegex(RuntimeStop,'unknown'):
            self.make_driver(dataclasses.replace(self.target,run_id='run-2',generation=2)).start(.1)
        self.assertEqual(self.runner.taps,1)
    def test_public_capture_is_clipped_to_lease(self):
        self.runner.step = .02
        with self.assertRaises((RuntimeStop,TimeoutError)): self.driver.capture()
        self.assertLessEqual(self.clock.now,.1)
        self.assertTrue(all(t < .1 for t in self.runner.dispatch_times))
    def test_execute_precapture_is_clipped_no_intent_or_tap(self):
        frame = self.driver.capture(); self.runner.step = .02
        with self.assertRaises((RuntimeStop,TimeoutError)):
            self.driver.execute(self.request(frame),frame,lambda _:True)
        self.assertEqual(self.runner.taps,0); self.assertIsNone(self.journal.get('a'))
        self.assertLessEqual(self.clock.now,.1)
    def test_cpu_overrun_after_capture_cannot_return_frame(self):
        frame = self.driver.capture()
        def late_capture(deadline): self.clock.sleep(.2); return frame
        with patch.object(self.driver.transport,'capture',late_capture):
            with self.assertRaisesRegex(RuntimeStop,'deadline/lease'): self.driver.capture()
    def test_late_predicate_is_unknown_and_never_replayed(self):
        frame = self.driver.capture()
        def late_predicate(_): self.clock.sleep(.2); return True
        request = self.request(frame)
        receipt = self.driver.execute(request,frame,late_predicate)
        self.assertEqual(receipt.state,'UNKNOWN')
        self.assertEqual(self.driver.execute(request,frame,lambda _:True),receipt)
        self.assertEqual(self.runner.taps,1)
    def test_capture_readback_overrun_does_not_call_predicate(self):
        frame = self.driver.capture(); original = self.driver.transport.capture; captures = 0; predicates = []
        def capture(deadline):
            nonlocal captures
            result = original(deadline); captures += 1
            if captures == 2: self.clock.sleep(.2)
            return result
        with patch.object(self.driver.transport,'capture',capture):
            receipt = self.driver.execute(self.request(frame),frame,lambda _:predicates.append(True) or True)
        self.assertEqual(receipt.state,'UNKNOWN'); self.assertEqual(predicates,[])
    def test_stale_tenant_capture_does_not_read_after_takeover(self):
        self.clock.now = .2
        self.make_driver(dataclasses.replace(self.target,run_id='run-2',generation=2)).start(.1)
        count = len(self.runner.calls)
        with self.assertRaises(RuntimeStop): self.driver.capture()
        self.assertEqual(len(self.runner.calls),count)
    def test_app_collection_cpu_overrun_is_rejected(self):
        from reproloop.runtime.app_state import AppStateReader
        def late_collect(*args): self.clock.sleep(.2); return object()
        with patch.object(AppStateReader,'collect',late_collect):
            with self.assertRaises(RuntimeStop): self.driver.collect_app_state(None)
    def test_readonly_reconcile_late_predicate_cannot_confirm(self):
        frame = self.driver.capture(); self.runner.fail_tap = True
        self.assertEqual(self.driver.execute(self.request(frame),frame,lambda _:True).state,'UNKNOWN')
        def late_predicate(_): self.clock.sleep(101); return True
        with self.assertRaisesRegex(RuntimeStop,'reconciliation deadline'):
            self.driver.reconcile('a',late_predicate)
        self.assertEqual(self.journal.get('a').state,'UNKNOWN'); self.assertEqual(self.runner.taps,1)
    def test_systemui_remains_fail_closed(self):
        xml = fixtures.XML.replace(b'</hierarchy>',b'<node package="com.android.systemui" resource-id="com.android.systemui:id/clock" text="12:00" clickable="false" bounds="[0,0][10,10]"/></hierarchy>')
        with self.assertRaises(RuntimeStop): parse_hierarchy(xml,100,100)


class PngRepairTests(unittest.TestCase):
    def test_unknown_critical_rejected_ancillary_allowed(self):
        chunk = fixtures.chunk
        self.assertEqual(png_size(fixtures.PNG),(100,100))
        with self.assertRaisesRegex(RuntimeStop,'critical'):
            png_size(fixtures.PNG[:-12]+chunk(b'ABCD',b'unknown')+fixtures.PNG[-12:])
        self.assertEqual(png_size(fixtures.PNG[:-12]+chunk(b'tEXt',b'Comment\x00ok')+fixtures.PNG[-12:]),(100,100))
    def test_idat_contiguity_positive_and_negative(self):
        chunk = fixtures.chunk; data = zlib.compress((b'\x00'+b'\x00'*300)*100); split = len(data)//2
        prefix = fixtures.PNG[:33]; suffix = fixtures.PNG[-12:]
        left,right = chunk(b'IDAT',data[:split]),chunk(b'IDAT',data[split:])
        self.assertEqual(png_size(prefix+left+right+suffix),(100,100))
        with self.assertRaisesRegex(RuntimeStop,'noncontiguous'):
            png_size(prefix+left+chunk(b'tEXt',b'Comment\x00gap')+right+suffix)
    def test_palette_and_chunk_type_controls(self):
        chunk = fixtures.chunk
        self.assertEqual(png_size(fixtures.PNG[:33]+chunk(b'PLTE',b'\x00\x00\x00')+fixtures.PNG[33:]),(100,100))
        for kind,data in ((b'PLTE',b'badsize'),(b'AB1D',b''),(b'abcd',b'')):
            with self.subTest(kind=kind), self.assertRaises(RuntimeStop):
                png_size(fixtures.PNG[:33]+chunk(kind,data)+fixtures.PNG[33:])
        with self.assertRaisesRegex(RuntimeStop,'palette'):
            png_size(fixtures.PNG[:-12]+chunk(b'PLTE',b'\x00'*3)+fixtures.PNG[-12:])
