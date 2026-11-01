"""WO-10 local fault injection only. Temporary SQLite, fake ADB and fake HTTP.

No subprocess, socket, native device, provider, credential or operational DB I/O.
"""
import dataclasses
import errno
import pathlib
import sqlite3
import struct
import sys
import tempfile
import time
import unittest
import zlib
from unittest.mock import patch

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tests/runtime'))
from test_runtime import Runner, Clock, PNG, chunk
from reproloop.runtime.driver import RuntimeJournal, RuntimeDriver, ActionRequest
from reproloop.runtime.owned import OwnedTarget, OwnedAdbTransport, RuntimeStop, CommandResult, PACKAGE
from reproloop.meta.client import MetaClient, HttpResult, MODEL
from reproloop.meta.ledger import CostLedger, MetaBlocked


def rotated_png():
    return (b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB',200,100,8,2,0,0,0))
            + chunk(b'IDAT',zlib.compress((b'\0'+b'\0'*600)*100)) + chunk(b'IEND',b''))


class FaultRunner(Runner):
    def __init__(self):
        super().__init__(); self.boot='boot-1'; self.reboot_on_tap=False
        self.screenshot=PNG; self.bad_mime_after_input=False
    def __call__(self, argv, timeout, max_output):
        args=argv[5:]
        if args == ('shell','cat','/proc/sys/kernel/random/boot_id'):
            self.calls.append(argv); return CommandResult(0,self.boot.encode())
        if args == ('exec-out','screencap','-p'):
            self.calls.append(argv)
            raw=b'JPEG-not-PNG' if self.bad_mime_after_input and self.taps else self.screenshot
            return CommandResult(0,raw)
        result=super().__call__(argv,timeout,max_output)
        if args[:3] == ('shell','input','tap') and self.reboot_on_tap: self.boot='boot-2'
        return result


class DiskFaultConnection(sqlite3.Connection):
    """One deterministic SQLite failure; underlying DB is real, small and temporary."""
    fault=None
    def execute(self, sql, parameters=()):
        if sql.startswith('INSERT INTO actions '): self.intent_written=True
        if self.fault['phase']=='after-input' and sql.startswith('UPDATE actions SET state='):
            self.fault['fired']=True
            raise sqlite3.OperationalError('database or disk is full')
        return super().execute(sql,parameters)
    def commit(self):
        if self.fault['phase']=='before-intent-commit' and getattr(self,'intent_written',False):
            self.fault['fired']=True
            raise sqlite3.OperationalError('database or disk is full')
        return super().commit()


class DurableInputFaultTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.path=str(pathlib.Path(self.tmp.name)/'synthetic-actions.sqlite')
        self.clock=Clock();self.runner=FaultRunner()
        self.target=OwnedTarget('emulator-5554','Owned_AVD','parent-owned','boot-1','a'*64,'run-1',1)
        self.journal=RuntimeJournal(self.path,'synthetic-host')
        self.driver=self.make(self.journal);self.driver.start();self.frame=self.driver.capture()
    def make(self,journal):
        return RuntimeDriver(OwnedAdbTransport(self.target,self.runner,self.clock,'/fake/adb'),journal,self.clock,time.monotonic()+30)
    def req(self,suffix='1'):
        return ActionRequest('action-'+suffix,'request-'+suffix,'tap',self.frame.evidence_sha256,PACKAGE+':id/cancel','Cancel')
    def disk(self,phase):
        original=sqlite3.connect;fault={'phase':phase,'fired':False}
        def connect(*args,**kwargs):
            kwargs['factory']=DiskFaultConnection;db=original(*args,**kwargs);db.fault=fault;return db
        return fault,patch('reproloop.runtime.driver.sqlite3.connect',connect)
    def test_disk_full_before_durable_intent_prevents_input_and_rolls_back(self):
        fault,inject=self.disk('before-intent-commit')
        with inject,self.assertRaisesRegex(sqlite3.OperationalError,'disk is full'):
            self.driver.execute(self.req(),self.frame,lambda _:True)
        self.assertTrue(fault['fired']);self.assertEqual(self.runner.taps,0)
        reopened=RuntimeJournal(self.path,'synthetic-host');self.assertIsNone(reopened.get('action-1'))
        # Recovery is allowed because the original operation provably never reached input.
        recovered=self.make(reopened);recovered.start()
        self.assertEqual(recovered.execute(self.req('2'),self.frame,lambda _:True).state,'ACCEPTED')
        self.assertEqual(self.runner.taps,1)
    def test_disk_full_after_input_keeps_pending_then_unknown_across_reopen(self):
        fault,inject=self.disk('after-input')
        with inject,self.assertRaisesRegex(sqlite3.OperationalError,'disk is full'):
            self.driver.execute(self.req(),self.frame,lambda _:True)
        self.assertTrue(fault['fired']);self.assertEqual(self.runner.taps,1)
        self.assertEqual(self.journal.get('action-1').state,'PENDING')
        reopened=RuntimeJournal(self.path,'synthetic-host');recovered=self.make(reopened)
        with self.assertRaisesRegex(RuntimeStop,'unknown'):recovered.start()
        self.assertEqual(reopened.get('action-1').state,'UNKNOWN')
        self.assertEqual(recovered.execute(self.req(),self.frame,lambda _:True).state,'UNKNOWN')
        with self.assertRaisesRegex(RuntimeStop,'unresolved'):recovered.execute(self.req('2'),self.frame,lambda _:True)
        self.assertEqual(recovered.reconcile('action-1',lambda _:False).state,'UNKNOWN')
        self.assertEqual(recovered.reconcile('action-1',lambda _:True).state,'ACCEPTED')
        self.assertEqual(self.runner.taps,1)  # reconciliation issued no new input
    def test_capture_artifact_enospc_after_input_is_unknown_and_blocks_new_id(self):
        capture=self.driver.transport.capture
        def save_failure(deadline):
            if self.runner.taps:raise OSError(errno.ENOSPC,'synthetic capture artifact write')
            return capture(deadline)
        with patch.object(self.driver.transport,'capture',save_failure):
            result=self.driver.execute(self.req(),self.frame,lambda _:True)
        self.assertEqual(result.state,'UNKNOWN');self.assertEqual(result.reason,'OSError')
        reopened=RuntimeJournal(self.path,'synthetic-host');recovered=self.make(reopened)
        self.assertEqual(reopened.get('action-1').state,'UNKNOWN')
        with self.assertRaises(RuntimeStop):recovered.execute(self.req('2'),self.frame,lambda _:True)
        self.assertEqual(self.runner.taps,1)
    def test_boot_change_before_input_rejects_without_intent(self):
        self.runner.boot='boot-2'
        with self.assertRaisesRegex(RuntimeStop,'identity'):self.driver.execute(self.req(),self.frame,lambda _:True)
        self.assertEqual(self.runner.taps,0);self.assertIsNone(self.journal.get('action-1'))
    def test_boot_change_after_input_is_unknown_and_readonly_reconcile_stops(self):
        self.runner.reboot_on_tap=True
        self.assertEqual(self.driver.execute(self.req(),self.frame,lambda _:True).state,'UNKNOWN')
        with self.assertRaisesRegex(RuntimeStop,'identity'):self.driver.reconcile('action-1',lambda _:True)
        with self.assertRaises(RuntimeStop):self.driver.execute(self.req('2'),self.frame,lambda _:True)
        self.assertEqual(self.runner.taps,1);self.assertEqual(self.journal.get('action-1').state,'UNKNOWN')
    def test_rotation_before_input_rejects_stale_frame_without_intent(self):
        self.runner.screenshot=rotated_png()
        with self.assertRaisesRegex(RuntimeStop,'stale screen'):self.driver.execute(self.req(),self.frame,lambda _:True)
        self.assertEqual(self.runner.taps,0);self.assertIsNone(self.journal.get('action-1'))
    def test_bad_screenshot_mime_after_input_is_unknown_not_accepted(self):
        self.runner.bad_mime_after_input=True
        self.assertEqual(self.driver.execute(self.req(),self.frame,lambda _:True).state,'UNKNOWN')
        self.assertEqual(RuntimeJournal(self.path,'synthetic-host').get('action-1').state,'UNKNOWN')
        with self.assertRaises(RuntimeStop):self.driver.execute(self.req('2'),self.frame,lambda _:True)
        self.assertEqual(self.runner.taps,1)


class DurableProviderFaultTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.path=pathlib.Path(self.tmp.name)/'synthetic-provider.sqlite'
        self.payload={'model':MODEL,'store':False,'max_output_tokens':100,'input':'synthetic fault fixture'}
    def client(self,reply):
        class FakeHTTP:
            def __init__(self):self.calls=[]
            def request(self,*args):self.calls.append(args);return reply
        transport=FakeHTTP();return MetaClient(CostLedger(self.path),transport),transport
    def test_simulated_429_halt_survives_reopen_without_another_http_request(self):
        client,http=self.client(HttpResult(429,b''))
        self.assertEqual(client.responses('original',self.payload,'synthetic-not-a-credential')['state'],'REJECTED')
        reopened=CostLedger(self.path);self.assertEqual(reopened.status()['halt'],'HTTP_429')
        replacement=MetaClient(reopened,http)
        with self.assertRaises(MetaBlocked):replacement.responses('new-id',self.payload,'synthetic-not-a-credential')
        self.assertEqual(len(http.calls),1);self.assertEqual(reopened.get('original')['state'],'REJECTED')
    def test_malformed_or_duplicate_provider_json_stays_unknown_after_reopen(self):
        for index,raw in enumerate([b'{',b'{"id":"resp_a","id":"resp_b"}']):
            with self.subTest(raw=raw):
                self.path=pathlib.Path(self.tmp.name)/f'provider-{index}.sqlite'
                client,http=self.client(HttpResult(200,raw))
                self.assertEqual(client.responses('original',self.payload,'synthetic-not-a-credential')['state'],'UNKNOWN')
                reopened=CostLedger(self.path)
                with self.assertRaises(MetaBlocked):MetaClient(reopened,http).responses('new-id',self.payload,'synthetic-not-a-credential')
                self.assertEqual(reopened.get('original')['state'],'UNKNOWN');self.assertEqual(len(http.calls),1)

class ReplayFaultTests(unittest.TestCase):
    """Use the real replay/collector callers with existing synthetic lab fixtures."""
    def setUp(self):
        sys.path.insert(0,str(ROOT/'tests/lab'))
        import test_lab
        self.helper=test_lab.LabTests('test_pair_same_generation_and_persisted_post_frames')
        self.helper.setUp();self.addCleanup(self.helper.doCleanups)
    def test_real_capture_save_enospc_after_input_cannot_complete_or_start_new_run(self):
        from reproloop import lab as module
        from reproloop.replay import model_free_replay
        h=self.helper;original=module.save_blob
        def inject(root,raw,suffix):
            if h.runner.stage and suffix=='.png':
                raise OSError(errno.ENOSPC,'synthetic evidence write failure')
            return original(root,raw,suffix)
        with patch('reproloop.lab.save_blob',inject):
            result=model_free_replay(h.lab,h.export,h.spec,'faulty','disk-fault')
        self.assertFalse(result.complete);self.assertIsNone(result.oracle_run)
        self.assertIn('UNKNOWN',result.reason)
        before=len(h.runner.calls)
        with self.assertRaises(RuntimeStop):h.lab.prepare(h.fixture,'fixed','new-run',1)
        self.assertEqual(len(h.runner.calls),before)
        with h.lab.journal.locked() as db:
            self.assertEqual(db.execute('SELECT state FROM actions').fetchone()[0],'UNKNOWN')
    def test_missing_cancel_event_in_real_replay_cannot_be_negative_control_success(self):
        from reproloop.replay import model_free_replay
        h=self.helper;original=h.runner
        def missing(argv,timeout,max_output):
            result=original(argv,timeout,max_output)
            if argv[-1]=='files/events.jsonl' and h.runner.stage==4:
                return CommandResult(0,b'\n'.join(result.stdout.splitlines()[:-1])+b'\n')
            return result
        h.lab.runner=missing
        result=model_free_replay(h.lab,h.export,h.spec,'fixed','missing-event')
        self.assertFalse(result.complete)
        self.assertTrue(result.oracle_run is None or result.oracle_run.failure_observed is None)

if __name__=='__main__':unittest.main()
