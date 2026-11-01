"""Offline fresh-setup boundaries. No real AVD, adb, model or network calls."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from hashlib import sha256
import json
from pathlib import Path
import shutil
import subprocess
import sqlite3
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import zipfile

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'tests/lab'))
from test_lab import FakeRunner,Clock
from reproloop.lab import (KNOWN_APK_SHA256,LabConfig,OwnedLab,checked_apk_sha256,
                           local_build_pins,LAB_SETUP_SCHEMA)
from reproloop.replay import model_free_replay
from reproloop.runtime.driver import RuntimeJournal
from reproloop.runtime.owned import PACKAGE,RuntimeStop
from replay_contracts import SemanticExport,Locator
from repro_oracle import CaseSpec
from reproloop.reference import reference_export
from tools import replay_owned_case as cli,init_owned_journal as init,emit_reference_export as emitter

ORIGINAL={'faulty':'5b7e27d291bf39e10b255c11b32abf6a2f56df89784c0136e5850277764233df',
          'fixed':'4bcd23747d32429c2c21fd4527bd9a481e6d11376b6b3b1fd27d424378cb3cb6'}


class FreshFixture(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.base=Path(self.tmp.name).resolve();self.root=self.base/'owned';self.root.mkdir(mode=0o700)
        for d in('avds','emulator-home','android-user'):(self.root/d).mkdir()
        self.avd=self.root/'avds/ReproLoop_TEST.avd';self.avd.mkdir();(self.avd/'config.ini').write_text('owned=true\n')
        self.boot=dict(phase='READY',avd_name='ReproLoop_TEST',serial='emulator-5554',owner_id='owner',avd_boot_id='guest',pid=99,adb_server_port=5037,avd_dir=str(self.avd),config_sha256=sha256((self.avd/'config.ini').read_bytes()).hexdigest())
        (self.root/'bootstrap.json').write_text(json.dumps(self.boot));(self.root/'owner-marker.txt').write_text('owner\n')
        self.apks=self.base/'apk';self.apks.mkdir()
        for mode in('faulty','fixed'):
            with zipfile.ZipFile(self.apks/('pockettasks-'+mode+'-debug.apk'),'w')as z:
                z.writestr('AndroidManifest.xml',mode);z.writestr('classes.dex',mode)
        self.pins={m:sha256((self.apks/('pockettasks-'+m+'-debug.apk')).read_bytes()).hexdigest()for m in('faulty','fixed')}
        self.cfg=LabConfig(self.root/'bootstrap.json','/fake/adb',self.apks/'pockettasks-faulty-debug.apk',self.apks/'pockettasks-fixed-debug.apk',self.root/'runtime.sqlite',self.base/'evidence')

    def fresh_init(self):return init.initialize(self.root,'ReproLoop_TEST','emulator-5554',True)
    def replay_args(self):
        export=self.base/'export.json';export.write_bytes(reference_export('FINAL-C',*self.pins.values()).to_bytes())
        return SimpleNamespace(runtime_root=self.root,apk_root=self.apks,export=export,case_id='FINAL-C',run_id='FRESH-C',expected_avd='ReproLoop_TEST',expected_serial='emulator-5554',source_revision='c'*40,admit_local_build=list(self.pins.values()))


class LocalApkAdmission(FreshFixture):
    def test_original_pins_unchanged_and_fresh_default_rejected(self):
        self.assertEqual(KNOWN_APK_SHA256,ORIGINAL)
        for mode in('faulty','fixed'):
            with self.assertRaisesRegex(RuntimeStop,'documented verified'):checked_apk_sha256(self.apks/('pockettasks-'+mode+'-debug.apk'),mode)
    def test_mapping_is_frozen_and_copied(self):
        pins=local_build_pins(self.pins);old=pins['faulty'];self.pins['faulty']='c'*64
        self.assertEqual(pins['faulty'],old)
        with self.assertRaises(TypeError):pins['faulty']='d'*64
    def test_invalid_admission_never_creates_journal(self):
        for pins in({},dict(self.pins,other='d'*64),{'faulty':'a'*64,'fixed':'a'*64},{'faulty':'A'*64,'fixed':'b'*64}):
            with self.subTest(pins=pins):
                with self.assertRaises(ValueError):OwnedLab(self.cfg,host_boot_id='host',admitted_apk_sha256=pins)
                self.assertFalse(self.cfg.journal_path.exists())
    def test_swapped_mismatched_symlink_and_bad_zip_reject(self):
        apk=self.apks/'pockettasks-faulty-debug.apk'
        for pins in({'faulty':self.pins['fixed'],'fixed':self.pins['faulty']},{'faulty':'c'*64,'fixed':self.pins['fixed']}):
            with self.assertRaisesRegex(RuntimeStop,'owner-admitted'):checked_apk_sha256(apk,'faulty',pins)
        apk.write_bytes(b'not-zip')
        with self.assertRaisesRegex(RuntimeStop,'ZIP'):checked_apk_sha256(apk,'faulty',self.pins)
        apk.unlink();apk.symlink_to(self.apks/'pockettasks-fixed-debug.apk')
        with self.assertRaisesRegex(RuntimeStop,'regular'):checked_apk_sha256(apk,'faulty',self.pins)
    def test_fake_full_pair_explicit_acceptance_without_patching_global_pins(self):
        runner=FakeRunner();lab=OwnedLab(self.cfg,runner,Clock(),host_boot_id='host',admitted_apk_sha256=self.pins)
        fixture=next(iter(lab.fixtures.values()));spec=CaseSpec('case','c'*64,fixture.sha256,self.pins['faulty'],self.pins['fixed'],'cancel')
        steps=(('task_target','Target task: Inbox','tasks'),('rename_open','Rename','selected'),('preset_today','Today','rename'),('cancel_edit','Cancel','rename'))
        export=SemanticExport(PACKAGE,spec.task_sha256,fixture.sha256,tuple(Locator(PACKAGE+':id/'+rid,text,screen)for rid,text,screen in steps))
        for mode in('faulty','fixed'):
            result=model_free_replay(lab,export,spec,mode,'fresh-'+mode)
            self.assertTrue(result.complete,result.reason);self.assertEqual(result.model_calls,0)
            self.assertEqual(result.oracle_run.failure_observed,mode=='faulty')
        self.assertEqual(KNOWN_APK_SHA256,ORIGINAL)
    def test_live_default_rejects_before_any_runner_command(self):
        runner=FakeRunner();lab=OwnedLab(self.cfg,runner,Clock(),host_boot_id='host')
        fixture=next(iter(lab.fixtures.values()));spec=CaseSpec('case','c'*64,fixture.sha256,self.pins['faulty'],self.pins['fixed'],'cancel')
        export=SemanticExport(PACKAGE,spec.task_sha256,fixture.sha256,tuple(Locator(PACKAGE+':id/'+rid,text,screen)for rid,text,screen in [('task_target','Target task: Inbox','tasks'),('rename_open','Rename','selected'),('preset_today','Today','rename'),('cancel_edit','Cancel','rename')]))
        result=model_free_replay(lab,export,spec,'faulty','default-reject')
        self.assertFalse(result.complete);self.assertIn('documented verified',result.reason);self.assertEqual(runner.calls,[])
    def test_preflight_explicit_pass_default_fail_no_output(self):
        self.fresh_init();args=self.replay_args();plan,*_=cli.prepare(args)
        self.assertEqual(plan['apk_admission'],'LOCAL_BUILD_OWNER_ADMITTED');self.assertEqual(plan['build_sha256'],self.pins)
        self.assertRegex(plan['lab_sha256'],r'^[0-9a-f]{64}$');self.assertEqual(plan['generation'],1)
        args.admit_local_build=None
        with self.assertRaisesRegex(RuntimeStop,'documented verified'):cli.prepare(args)
        self.assertFalse((self.base/'out').exists())


class FreshJournalInitialization(FreshFixture):
    def test_preview_no_writes_and_execute_once(self):
        before=sorted(p.name for p in self.root.iterdir())
        preview=init.initialize(self.root,'ReproLoop_TEST','emulator-5554')
        self.assertEqual(preview['phase'],'PREVIEW');self.assertEqual(sorted(p.name for p in self.root.iterdir()),before)
        done=self.fresh_init();self.assertEqual(done['phase'],'COMPLETED');self.assertEqual(cli.runtime_state(self.root),1)
        digest=sha256((self.root/'runtime.sqlite').read_bytes()).hexdigest()
        with self.assertRaisesRegex(ValueError,'existing journal'):self.fresh_init()
        self.assertEqual(sha256((self.root/'runtime.sqlite').read_bytes()).hexdigest(),digest)
    def test_existing_empty_journal_or_sidecars_or_unknown_files_rejected(self):
        for name in('runtime.sqlite','runtime.sqlite-wal','runtime.sqlite.lock','journal-init.lock','unexpected'):
            p=self.root/name;p.write_bytes(b'')
            with self.assertRaises(ValueError):self.fresh_init()
            self.assertEqual(p.read_bytes(),b'');p.unlink()
    def test_incomplete_and_empty_unmarked_journal_rejected_cleanly(self):
        journal=RuntimeJournal(str(self.root/'runtime.sqlite'),'host')
        with self.assertRaisesRegex(ValueError,'schema'):cli.runtime_state(self.root)
        with journal.locked()as db:db.execute(LAB_SETUP_SCHEMA)
        with self.assertRaisesRegex(ValueError,'empty unmarked'):cli.runtime_state(self.root)
    def test_bad_target_outside_root_stale_config_and_symlink_reject(self):
        with self.assertRaisesRegex(ValueError,'target mismatch'):init.initialize(self.root,'ReproLoop_OTHER','emulator-5554',True)
        b=dict(self.boot,avd_dir=str(self.avd.parent));(self.avd.parent/'config.ini').write_text('owned=true\n')
        (self.root/'bootstrap.json').write_text(json.dumps(b))
        with self.assertRaisesRegex(ValueError,'this exact runtime'):self.fresh_init()
        (self.root/'bootstrap.json').write_text(json.dumps(self.boot));(self.avd/'config.ini').write_text('changed')
        with self.assertRaisesRegex(RuntimeStop,'configuration changed'):self.fresh_init()
        (self.avd/'config.ini').write_text('owned=true\n');link=self.base/'link';link.symlink_to(self.root,target_is_directory=True)
        with self.assertRaises(ValueError):init.initialize(link,'ReproLoop_TEST','emulator-5554',True)
        self.assertFalse((self.root/'runtime.sqlite').exists())
    def test_copy_relocated_completed_receipts_reject(self):
        self.fresh_init();copy=self.base/'copied';shutil.copytree(self.root,copy)
        with self.assertRaisesRegex(ValueError,'changed journal initialization'):cli.runtime_state(copy)
    def test_every_partial_init_boundary_retains_a_replay_blocker(self):
        real_save=init.save
        for stage in('started','schema','verify','complete'):
            with self.subTest(stage=stage):
                self.setUp()
                def failing_save(path,value):
                    if path.name==('journal-init.intent.json'if stage=='started'else'journal-init.complete.json'):raise OSError('injected write failure')
                    return real_save(path,value)
                def after_schema(*args,**kwargs):
                    RuntimeJournal(*args,**kwargs);raise OSError('injected after schema')
                context=patch.object(init,'save',side_effect=failing_save)if stage in('started','complete')else patch.object(init,'RuntimeJournal',side_effect=after_schema)if stage=='schema'else patch.object(init,'validate_journal_schema',side_effect=ValueError('injected after full schema'))
                with context:
                    with self.assertRaises((OSError,ValueError)):self.fresh_init()
                self.assertTrue((self.root/'journal-init.lock').exists())
                with self.assertRaisesRegex(ValueError,'initialization'):cli.runtime_state(self.root)
                with self.assertRaises(ValueError):self.fresh_init()
    def test_concurrent_initializers_single_winner(self):
        def attempt():
            try:return self.fresh_init()['phase']
            except(ValueError,FileExistsError):return'REJECTED'
        with ThreadPoolExecutor(max_workers=2)as pool:results=list(pool.map(lambda _:attempt(),range(2)))
        self.assertEqual(sorted(results),['COMPLETED','REJECTED']);self.assertEqual(cli.runtime_state(self.root),1)
    def test_documented_exclusive_private_root_under_umask_022(self):
        root=self.base/'documented-private-root'
        result=subprocess.run(['/bin/sh','-c','umask 022; /bin/mkdir -m 700 "$1"','sh',str(root)],capture_output=True)
        self.assertEqual(result.returncode,0);self.assertEqual(root.stat().st_mode&0o777,0o700)
        again=subprocess.run(['/bin/mkdir','-m','700',str(root)],capture_output=True)
        self.assertNotEqual(again.returncode,0)
    def test_same_columns_with_wrong_constraints_rejected(self):
        import re
        for mutation in('composite-pk','missing-unique','wrong-type','nullable-payload'):
            with self.subTest(mutation=mutation):
                self.setUp();self.fresh_init()
                with closing(sqlite3.connect(self.root/'runtime.sqlite'))as db,db:
                    ddl=db.execute("SELECT sql FROM sqlite_master WHERE name='actions'").fetchone()[0]
                    if mutation=='composite-pk':
                        ddl=ddl.replace('action_id TEXT PRIMARY KEY','action_id TEXT').rstrip()[:-1]+', PRIMARY KEY(action_id,request_id))'
                    elif mutation=='missing-unique':ddl=ddl.replace('request_id TEXT UNIQUE','request_id TEXT')
                    elif mutation=='wrong-type':ddl=ddl.replace('generation INTEGER NOT NULL','generation TEXT NOT NULL')
                    else:ddl=ddl.replace('payload TEXT NOT NULL','payload TEXT')
                    db.execute('DROP TABLE actions');db.execute(ddl)
                with self.assertRaisesRegex(ValueError,'schema'):cli.runtime_state(self.root)

    def test_corrupt_database_is_clean_error(self):
        self.fresh_init();(self.root/'runtime.sqlite').write_bytes(b'corrupt')
        with self.assertRaisesRegex(ValueError,'corrupt'):cli.runtime_state(self.root)


class BootstrapFinalization(FreshFixture):
    def test_post_boot_normalization_keeps_created_and_final_pins(self):
        from tools.bootstrap_owned_avd import finalized_config_pins
        cfg=self.avd/'config.ini';created=sha256(cfg.read_bytes()).hexdigest()
        cfg.write_text('owned = true\ndisk.dataPartition.size = 6442450944\n')
        pins=finalized_config_pins(cfg,created)
        self.assertEqual(pins['created_config_sha256'],created)
        self.assertEqual(pins['config_sha256'],sha256(cfg.read_bytes()).hexdigest())
        self.assertNotEqual(pins['config_sha256'],created)
    def test_bad_created_pin_or_symlink_rejects(self):
        from tools.bootstrap_owned_avd import finalized_config_pins
        cfg=self.avd/'config.ini'
        with self.assertRaises(ValueError):finalized_config_pins(cfg,'bad')
        link=self.base/'linked-config';link.symlink_to(cfg)
        with self.assertRaises(ValueError):finalized_config_pins(link,'a'*64)


class SystemUiReadiness(unittest.TestCase):
    def test_first_use_fullscreen_system_overlay_is_not_app_hierarchy(self):
        from reproloop.runtime.owned import parse_hierarchy
        xml=b'<hierarchy rotation="0"><node package="android" class="android.widget.FrameLayout" resource-id="" text="" clickable="false" bounds="[0,0][720,1280]"><node package="android" class="android.widget.Button" resource-id="android:id/ok" text="Got it" clickable="true" bounds="[464,353][640,449]"/></node></hierarchy>'
        with self.assertRaises(RuntimeStop):parse_hierarchy(xml,720,1280)


class PureReferenceExport(FreshFixture):
    def test_frozen_final_digests(self):
        expected={'FINAL-A': '3bbbd8cb455637bdc9f3b16124d79bf1f37b9ce47503c3d62e5d8e1d543b460f', 'FINAL-B': '86963eb6402d49c006db59bee4aa8f38d98437e80d1d22edb622593dd92706b7', 'FINAL-C': '0f2185d91acb8e96ca33339e8dc517a0458aedb674c522bf458a935dae7d565d'}
        for case,digest in expected.items():
            result=reference_export(case,*self.pins.values())
            self.assertEqual(result.digest(),digest)
    def test_emit_exclusive_canonical_output(self):
        path=self.base/'reference.json';result=emitter.emit('FINAL-C',*self.pins.values(),path)
        self.assertEqual(sha256(path.read_bytes()).hexdigest(),result['export_sha256']);self.assertTrue(result['not_video_inference'])
        with self.assertRaises(ValueError):emitter.emit('FINAL-C',*self.pins.values(),path)
        link=self.base/'link';link.symlink_to(path)
        with self.assertRaises(ValueError):emitter.emit('FINAL-C',*self.pins.values(),link)
        with self.assertRaises(ValueError):emitter.emit('FINAL-C','bad',self.pins['fixed'],self.base/'bad.json')
        self.assertFalse((self.base/'bad.json').exists())


if __name__=='__main__':unittest.main()
