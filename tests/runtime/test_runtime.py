import dataclasses
import json
import pathlib
import struct
import tempfile
import threading
import time
import unittest
from reproloop.runtime.owned import (OwnedTarget, OwnedAdbTransport, CommandResult, RuntimeStop, PACKAGE, parse_hierarchy)
from reproloop.runtime.driver import RuntimeJournal, RuntimeDriver, ActionRequest

import zlib

def chunk(kind,data):
    return struct.pack('>I',len(data))+kind+data+struct.pack('>I',zlib.crc32(kind+data))
PNG = b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR',struct.pack('>IIBBBBB',100,100,8,2,0,0,0))+chunk(b'IDAT',zlib.compress((b'\x00'+b'\x00'*300)*100))+chunk(b'IEND',b'')

XML = ('<hierarchy><node package="'+PACKAGE+'" resource-id="'+PACKAGE+':id/cancel" text="Cancel" clickable="true" bounds="[0,0][100,100]"/></hierarchy>').encode()

class Clock:
    def monotonic(self): return time.monotonic()
    def sleep(self, seconds): time.sleep(seconds)

class Runner:
    def __init__(self):
        self.calls=[]; self.taps=0; self.owner='parent-owned'; self.fail_tap=False
        self.entered=threading.Event(); self.release=threading.Event(); self.block=False
    def __call__(self,argv,timeout,max_output):
        assert 0 < timeout <= (5 if argv[5:] == ('shell','uiautomator','dump','/data/local/tmp/reproloop-window.xml') else 2) and max_output <= 8388608
        self.calls.append(argv)
        args=argv[5:]
        if args == ('get-state',): out=b'device\n'
        elif args == ('emu','avd','name'): out=b'Owned_AVD\nOK\n'
        elif args == ('shell','cat','/proc/sys/kernel/random/boot_id'): out=b'boot-1'
        elif args == ('shell','cat','/data/local/tmp/reproloop-owner'): out=self.owner.encode()
        elif args == ('shell','pm','path',PACKAGE): out=b'package:/data/app/abc/base.apk'
        elif args == ('shell','sha256sum','/data/app/abc/base.apk'): out=('a'*64+'  /data/app/abc/base.apk').encode()
        elif args == ('exec-out','screencap','-p'): out=PNG
        elif args == ('shell','uiautomator','dump','/data/local/tmp/reproloop-window.xml'): out=b'OK'
        elif args == ('exec-out','cat','/data/local/tmp/reproloop-window.xml'): out=XML
        elif args == ('shell','run-as',PACKAGE,'cat','files/state.json'): out=b'{}'
        elif args == ('shell','run-as',PACKAGE,'cat','files/events.jsonl'): out=b'{}\n'
        elif args[:3] == ('shell','input','tap'):
            self.taps+=1
            if self.block:
                self.entered.set(); self.release.wait(1)
            if self.fail_tap: raise TimeoutError('unknown external outcome')
            out=b''
        else: raise AssertionError(args)
        return CommandResult(0,out)

def contend(path, queue):
    journal=RuntimeJournal(path,'host-boot')
    with journal.locked(): queue.put('acquired')

class RuntimeTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.clock=Clock(); self.runner=Runner()
        self.target=OwnedTarget('emulator-5554','Owned_AVD','parent-owned','boot-1','a'*64,'run-1',1)
        self.transport=OwnedAdbTransport(self.target,self.runner,self.clock,'/fake/adb')
        self.journal=RuntimeJournal(str(pathlib.Path(self.tmp.name)/'journal.db'),'host-boot')
        self.driver=RuntimeDriver(self.transport,self.journal,self.clock,time.monotonic()+20)
        self.driver.start(); self.frame=self.driver.capture()
    def request(self, action='action-1', request='request-1', **kwargs):
        return ActionRequest(action,request,'tap',self.frame.evidence_sha256,PACKAGE+':id/cancel','Cancel',**kwargs)
    def test_acceptance_requires_readback_and_duplicate_is_not_replayed(self):
        req=self.request()
        receipt=self.driver.execute(req,self.frame,lambda _:False)
        self.assertEqual(receipt.state,'NOT_ACCEPTED')
        self.assertEqual(self.driver.execute(req,self.frame,lambda _:True),receipt)
        self.assertEqual(self.runner.taps,1)
        self.assertEqual(self.driver.execute(self.request('a2','r2'),self.frame,lambda _:True).state,'ACCEPTED')
    def test_unknown_blocks_new_id_and_reconciles_read_only(self):
        self.runner.fail_tap=True
        self.assertEqual(self.driver.execute(self.request(),self.frame,lambda _:True).state,'UNKNOWN')
        with self.assertRaises(RuntimeStop): self.driver.execute(self.request('a2','r2'),self.frame,lambda _:True)
        self.assertEqual(self.driver.reconcile('action-1',lambda _:False).state,'UNKNOWN')
        self.assertEqual(self.driver.reconcile('action-1',lambda _:True).state,'ACCEPTED')
        self.assertEqual(self.runner.taps,1)
    def test_same_name_unauthorized_owner_never_dispatches(self):
        self.runner.owner='intruder'
        with self.assertRaises(RuntimeStop): self.driver.execute(self.request(),self.frame,lambda _:True)
        self.assertEqual(self.runner.taps,0)
    def test_physical_targets_rejected(self):
        with self.assertRaises(ValueError): dataclasses.replace(self.target,serial='R58ABC')
    def test_stale_binding_and_generation(self):
        changed=dataclasses.replace(self.frame,binding='b'*64)
        with self.assertRaises(RuntimeStop): self.driver.execute(self.request(),changed,lambda _:True)
        self.driver.cancel()
        with self.assertRaises(RuntimeStop): self.driver.execute(self.request(),self.frame,lambda _:True)
    def test_xml_defenses(self):
        for xml in (b'<!DOCTYPE x [<!ENTITY e SYSTEM "file:///etc/passwd">]><hierarchy/>',XML.replace(PACKAGE.encode(),b'foreign'),XML.replace(b'100,100',b'99999,99999'),b'x'*1048577,b'<hierarchy>'*70):
            with self.subTest(xml=xml[:30]), self.assertRaises(RuntimeStop): parse_hierarchy(xml,100,100)
        self.assertEqual(len(parse_hierarchy(XML,100,100)),1)
    def test_nonfinite_bool_and_arbitrary_actions(self):
        for x in (float('nan'),True,1.5,-1):
            with self.assertRaises(ValueError): self.transport.tap(x,0,self.frame,time.monotonic()+1)
        with self.assertRaises(ValueError): dataclasses.replace(self.request(),kind='shell')
        self.assertEqual(self.runner.taps,0)
    def test_pending_is_committed_at_input_and_cancel_serialized(self):
        self.runner.block=True
        result=[]
        a=threading.Thread(target=lambda: result.append(self.driver.execute(self.request(),self.frame,lambda _:True)))
        a.start(); self.assertTrue(self.runner.entered.wait(1))
        # Ordinary SQLite reader sees committed intent while writer fence is held.
        import sqlite3
        with sqlite3.connect(self.journal.path) as db:
            self.assertEqual(db.execute('SELECT state FROM actions').fetchone()[0],'PENDING')
        cancelled=threading.Event()
        b=threading.Thread(target=lambda: (self.driver.cancel(),cancelled.set()))
        b.start(); time.sleep(.02); self.assertFalse(cancelled.is_set())
        self.runner.release.set(); a.join(2); b.join(2)
        self.assertEqual(result[0].state,'ACCEPTED'); self.assertTrue(cancelled.is_set())
        self.assertEqual(self.runner.taps,1)
    def test_two_threads_duplicate_dispatch_once(self):
        results=[]
        def run(): results.append(self.driver.execute(self.request(),self.frame,lambda _:True))
        threads=[threading.Thread(target=run) for _ in range(2)]
        for t in threads:t.start()
        for t in threads:t.join(2)
        self.assertEqual(len(results),2); self.assertEqual(self.runner.taps,1)
    def test_lease_owner_and_host_boot_fences(self):
        other=dataclasses.replace(self.target,owner_id='other')
        runner=Runner(); runner.owner='other'
        transport=OwnedAdbTransport(other,runner,self.clock,'/fake/adb')
        with self.assertRaises(RuntimeStop): RuntimeDriver(transport,self.journal,self.clock,time.monotonic()+10).start()
        rebooted=RuntimeJournal(self.journal.path,'new-host-boot')
        stale=RuntimeDriver(self.transport,rebooted,self.clock,time.monotonic()+10)
        with self.assertRaises(RuntimeStop): stale.capture()
    def test_deadline_and_wait_reservation(self):
        self.driver.deadline=time.monotonic()+.01
        with self.assertRaises(RuntimeStop): self.driver.execute(self.request(),self.frame,lambda _:True)
        self.assertEqual(self.runner.taps,0)
    def test_conflicting_duplicate_and_action_cap(self):
        self.driver.max_actions=1
        self.driver.execute(self.request(),self.frame,lambda _:True)
        with self.assertRaises(RuntimeStop): self.driver.execute(self.request('a2','r2'),self.frame,lambda _:True)
        with self.assertRaises(RuntimeStop): self.driver.execute(dataclasses.replace(self.request(),text='Other'),self.frame,lambda _:True)
    def test_frame_evidence_not_atomic_and_mismatch(self):
        self.assertFalse(self.frame.evidence()['atomic'])
        with self.assertRaises(RuntimeStop): self.driver.execute(dataclasses.replace(self.request(),preframe_hash='b'*64),self.frame,lambda _:True)
        with self.assertRaises(RuntimeStop): self.frame.resolve(PACKAGE+':id/absent','Cancel')
    def test_crash_pending_persists_unknown_on_restart(self):
        self.driver.execute(self.request(),self.frame,lambda _:True)
        with self.journal.locked() as db:
            db.execute("UPDATE actions SET state='PENDING'")
        with self.assertRaises(RuntimeStop): self.driver.start()
        self.assertEqual(self.journal.get('action-1').state,'UNKNOWN')
        self.assertEqual(self.runner.taps,1)
    def test_cross_process_lock_contention(self):
        import multiprocessing
        ctx=multiprocessing.get_context('spawn')
        queue=ctx.Queue()
        with self.journal.locked():
            process=ctx.Process(target=contend,args=(self.journal.path,queue)); process.start()
            time.sleep(.03); self.assertTrue(queue.empty())
        self.assertEqual(queue.get(timeout=2),'acquired')
        process.join(2); self.assertEqual(process.exitcode,0)
    def test_png_crc_and_decompression_bounds(self):
        from reproloop.runtime.owned import png_size
        with self.assertRaises(RuntimeStop): png_size(PNG[:-1]+b'x')
        self.assertEqual(png_size(PNG),(100,100))
    def test_explicit_server_port_and_clipped_timeouts(self):
        transport=OwnedAdbTransport(self.target,self.runner,self.clock,'/fake/adb',5041)
        transport.discover(time.monotonic()+.2)
        self.assertEqual(self.runner.calls[-1][1:3],('-P','5041'))
        with self.assertRaises(ValueError): OwnedAdbTransport(self.target,self.runner,self.clock,'/fake/adb',True)
    def test_negative_broken_ownership_variant_is_detectable(self):
        # Deliberate local mutant: skipping discover turns denied owner into input.
        # This checks the bad variant changes the safety observable, not just LOC.
        from unittest.mock import patch
        self.runner.owner='intruder'
        with patch.object(self.transport,'discover',lambda _:None):
            receipt=self.driver.execute(self.request(),self.frame,lambda _:True)
        self.assertEqual(receipt.state,'ACCEPTED')
        self.assertEqual(self.runner.taps,1)
    def test_fixture_reader_uses_fixed_allowlisted_paths(self):
        self.assertEqual(self.transport.read_app_state(self.driver.deadline),b'{}')
        self.assertEqual(self.transport.read_app_events(self.driver.deadline),b'{}\n')

if __name__=='__main__': unittest.main()
