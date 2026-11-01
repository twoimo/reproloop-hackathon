import dataclasses
import json
from pathlib import Path
import sys
import tempfile
import unittest
import zipfile
from hashlib import sha256
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'runtime'))
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'examples'))
from test_runtime import PNG
from test_app_state import sample, encode, raw_events
from reproloop.lab import LabConfig, OwnedLab
from reproloop.replay import model_free_replay
from reproloop.runtime.owned import CommandResult, PACKAGE, RuntimeStop, OwnedTarget
from replay_contracts import SemanticExport, Locator
from repro_oracle import CaseSpec

class Clock:
    def monotonic(self): return 100.
    def sleep(self,seconds): pass

class FakeRunner:
    """Only injected byte fixtures. No subprocess, network or model facility."""
    def __init__(self): self.calls=[]; self.stage=0; self.mode='faulty'; self.owner='owner'; self.fail=False
    def __call__(self,argv,timeout,max_output):
        self.calls.append(argv); a=argv[5:]; out=b''
        if a==('get-state',): out=b'device'
        elif a==('emu','avd','name'): out=b'ReproLoop_TEST\r\nOK\r\n'
        elif a==('shell','cat','/proc/sys/kernel/random/boot_id'): out=b'guest'
        elif a==('shell','cat','/data/local/tmp/reproloop-owner'): out=self.owner.encode()
        elif a[0]=='install':
            self.mode='fixed' if 'fixed' in a[-1] else 'faulty'; self.apkhash=sha256(Path(a[-1]).read_bytes()).hexdigest(); out=b'Success'
        elif a[:3]==('shell','pm','clear'): out=b'Success'
        elif a[:3]==('shell','am','start'):
            self.run=a[a.index('run_id')+1]; self.gen=int(a[a.index('generation')+1]); self.stage=0; out=b'Status: ok'
        elif a[:3]==('shell','pm','path'): out=b'package:/data/app/test/base.apk'
        elif a[:2]==('shell','sha256sum'): out=(self.apkhash+'  /data/app/test/base.apk').encode()
        elif a==('exec-out','screencap','-p'): out=PNG
        elif a[:2]==('shell','uiautomator'): out=b'OK'
        elif a==('exec-out','cat','/data/local/tmp/reproloop-window.xml'):
            nodes=[('task_target','Target task: Inbox',True),('task_other','Other task: Archive',True)] if self.stage==0 else [('rename_open','Rename',True)] if self.stage in (1,4) else [('preset_today','Today',True),('cancel_edit','Cancel',True),('','Draft: '+('Today' if self.stage==3 else 'Inbox'),False)]
            out=('<hierarchy>'+''.join('<node package="'+PACKAGE+'" resource-id="'+(PACKAGE+':id/'+rid if rid else '')+'" text="'+text+'" clickable="'+str(click).lower()+'" bounds="[0,0][100,100]"/>' for rid,text,click in nodes)+'</hierarchy>').encode()
        elif a[:3]==('shell','input','tap'):
            if self.fail: raise TimeoutError('unknown')
            self.stage+=1
        elif a[:3]==('shell','run-as',PACKAGE):
            target=OwnedTarget('emulator-5554','ReproLoop_TEST','owner','guest',self.apkhash,self.run,self.gen)
            exp,state,events=sample(self.mode,self.stage==4,target)
            out=encode(state) if a[-1]=='files/state.json' else raw_events(events)
        else: raise AssertionError(a)
        return CommandResult(0,out)

class LabTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup); self.root=Path(self.tmp.name)
        (self.root/'config.ini').write_text('owned=true\n')
        b=dict(phase='READY',avd_name='ReproLoop_TEST',serial='emulator-5554',owner_id='owner',avd_boot_id='guest',pid=99,adb_server_port=5037,avd_dir=str(self.root),config_sha256=sha256((self.root/'config.ini').read_bytes()).hexdigest())
        (self.root/'bootstrap.json').write_text(json.dumps(b))
        for mode in ('faulty','fixed'):
            with zipfile.ZipFile(self.root/f'pockettasks-{mode}-debug.apk','w') as z:
                z.writestr('AndroidManifest.xml',mode); z.writestr('classes.dex',mode)
        self.cfg=LabConfig(self.root/'bootstrap.json','/fake/adb',self.root/'pockettasks-faulty-debug.apk',self.root/'pockettasks-fixed-debug.apk',self.root/'journal.db',self.root/'evidence')
        pins={mode:sha256((self.root/f'pockettasks-{mode}-debug.apk').read_bytes()).hexdigest() for mode in ('faulty','fixed')}
        pin_patch=patch('reproloop.lab.KNOWN_APK_SHA256',pins); pin_patch.start(); self.addCleanup(pin_patch.stop)
        self.runner=FakeRunner(); self.lab=OwnedLab(self.cfg,self.runner,Clock(),host_boot_id='host')
        self.fixture=self.lab.fixtures[next(iter(self.lab.fixtures))]
        self.spec=CaseSpec('case','c'*64,self.fixture.sha256,self.lab.apk_sha256('faulty'),self.lab.apk_sha256('fixed'),'cancel')
        self.export=SemanticExport(PACKAGE,self.spec.task_sha256,self.fixture.sha256,tuple(Locator(PACKAGE+':id/'+rid,text,screen) for rid,text,screen in [('task_target','Target task: Inbox','tasks'),('rename_open','Rename','selected'),('preset_today','Today','rename'),('cancel_edit','Cancel','rename')]))
    def test_pair_same_generation_and_persisted_post_frames(self):
        for mode in ('faulty','fixed'):
            result=model_free_replay(self.lab,self.export,self.spec,mode,'run-'+mode)
            self.assertTrue(result.complete,result.reason); self.assertEqual(result.model_calls,0)
            self.assertEqual(result.oracle_run.failure_observed,mode=='faulty')
            self.assertEqual(result.script_sha256,self.export.digest())
            self.assertTrue(any(x.endswith('.png') for x in result.evidencepaths))
    def test_foreign_bootstrap_before_writes(self):
        self.runner.owner='foreign'
        with self.assertRaises(RuntimeStop): self.lab.prepare(self.fixture,'faulty','run',1)
        self.assertFalse(any(c[5]=='install' for c in self.runner.calls))
    def test_wrong_script_and_build_before_setup(self):
        for export,spec in [(dataclasses.replace(self.export,steps=self.export.steps[:-1]),self.spec),(self.export,dataclasses.replace(self.spec,faulty_build_sha256='d'*64))]:
            r=model_free_replay(self.lab,export,spec,'faulty','bad')
            self.assertFalse(r.complete); self.assertEqual(self.runner.calls,[])
    def test_shell_metacharacters_rejected(self):
        for title in ('hello world','Inbox;id','$(id)','A&B'):
            with self.assertRaises(ValueError): self.lab.prepare(dataclasses.replace(self.fixture,target_title=title),'faulty','run',1)
        self.assertEqual(self.runner.calls,[])
    def test_unknown_preserves_fence(self):
        self.runner.fail=True
        result=model_free_replay(self.lab,self.export,self.spec,'faulty','unknown')
        self.assertFalse(result.complete)
        before=len(self.runner.calls)
        with self.assertRaises(RuntimeStop): self.lab.prepare(self.fixture,'fixed','next',1)
        self.assertEqual(len(self.runner.calls),before)
    def test_cancel_finish_handoff_and_reuse_rejection(self):
        run=self.lab.prepare(self.fixture,'faulty','first',1); run.driver.cancel(); self.lab.finish(run)
        other=self.lab.prepare(self.fixture,'fixed','second',1); self.lab.finish(other)
        with self.assertRaises(RuntimeStop): self.lab.prepare(self.fixture,'faulty','first',1)
    def test_missing_fresh_reset_rejected(self):
        from reproloop.runtime.app_state import AppObservation
        with patch('reproloop.lab.AppStateReader.collect',return_value=AppObservation('BAD',None,(),False)):
            with self.assertRaises(RuntimeStop): self.lab.prepare(self.fixture,'faulty','first',1)
    def test_hash_collision_fails_closed(self):
        from reproloop.lab import save_blob
        p=Path(save_blob(self.root,b'original','.png')); p.write_bytes(b'corrupt')
        with self.assertRaises(RuntimeStop): save_blob(self.root,b'original','.png')
    def test_no_model_import_or_call(self):
        import reproloop.replay as replay
        import ast
        tree=ast.parse(Path(replay.__file__).read_text())
        imports=[n.module or '' for n in ast.walk(tree) if isinstance(n,ast.ImportFrom)]
        self.assertFalse(any('meta' in n or 'http' in n or 'browser' in n for n in imports))
        with patch('urllib.request.urlopen',side_effect=AssertionError('network forbidden')):
            self.assertTrue(model_free_replay(self.lab,self.export,self.spec,'fixed','nomodel').complete)

if __name__=='__main__': unittest.main()
