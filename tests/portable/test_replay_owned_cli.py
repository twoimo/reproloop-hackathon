import importlib.util
import json
from pathlib import Path
from contextlib import closing
import sqlite3
import tempfile
from types import SimpleNamespace
import unittest
import zipfile
from hashlib import sha256
from reproloop.lab import LAB_SETUP_SCHEMA
from reproloop.runtime.driver import RuntimeJournal
from evaluation.splits import get_native_scenario
from replay_contracts import SemanticExport,Locator

SPEC=importlib.util.spec_from_file_location('owned_replay_cli',Path(__file__).resolve().parents[2]/'tools/replay_owned_case.py')
cli=importlib.util.module_from_spec(SPEC);SPEC.loader.exec_module(cli)

class StandaloneReplayPlan(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name).resolve()
  self.runtime=self.root/'owned';self.runtime.mkdir();self.apk=self.root/'apk';self.apk.mkdir()
  (self.runtime/'config.ini').write_text('owned=true\n')
  (self.runtime/'bootstrap.json').write_text(json.dumps(dict(phase='READY',avd_name='ReproLoop_TEST_OWNED',serial='emulator-5998',owner_id='owner',avd_boot_id='guest',pid=99,adb_server_port=5037,avd_dir=str(self.runtime),config_sha256=sha256((self.runtime/'config.ini').read_bytes()).hexdigest())))
  journal=RuntimeJournal(str(self.runtime/'runtime.sqlite'),'host')
  with journal.locked()as db:
   db.execute(LAB_SETUP_SCHEMA)
   db.execute('INSERT INTO run_history VALUES(?,?,?,?,?)',('historical','old-run',16,0,1))
  for mode in('faulty','fixed'):
   with zipfile.ZipFile(self.apk/('pockettasks-'+mode+'-debug.apk'),'w')as z:
    z.writestr('AndroidManifest.xml',mode);z.writestr('classes.dex',mode)
  pins=[sha256((self.apk/('pockettasks-'+mode+'-debug.apk')).read_bytes()).hexdigest()for mode in('faulty','fixed')]
  scenario=get_native_scenario('FINAL-C');spec=scenario.to_case_spec('a'*64,'b'*64)
  export=SemanticExport(scenario.package_name,spec.task_sha256,spec.fixture_sha256,tuple(Locator(scenario.package_name+':id/'+rid,text,screen)for rid,text,screen in [('task_target','Target task: Release','tasks'),('rename_open','Rename','selected'),('preset_today','Today','rename'),('cancel_edit','Cancel','rename')]))
  self.export=self.root/'export.json';self.export.write_bytes(export.to_bytes())
  self.args=SimpleNamespace(runtime_root=self.runtime,apk_root=self.apk,export=self.export,case_id='FINAL-C',run_id='REPRO-C-v1',expected_avd='ReproLoop_TEST_OWNED',expected_serial='emulator-5998',source_revision='c'*40,admit_local_build=pins)
 def test_plan_no_provider_files_or_output_created(self):
  plan,*_=cli.prepare(self.args)
  self.assertEqual(plan['generation'],17);self.assertEqual(plan['model_calls'],0)
  self.assertEqual(sorted(p.name for p in self.root.iterdir()),['apk','export.json','owned'])
 def test_wrong_explicit_target_rejects(self):
  self.args.expected_serial='emulator-5996'
  with self.assertRaisesRegex(ValueError,'target mismatch'):cli.prepare(self.args)
 def test_unknown_action_blocks(self):
  with closing(sqlite3.connect(self.runtime/'runtime.sqlite'))as db, db:db.execute("INSERT INTO actions(action_id,request_id,payload,owner,binding,generation,preframe,planned_args,state,reason) VALUES(?,?,?,?,?,?,?,?,?,?)",('a','request','{}','owner','binding',16,'frame','[]','UNKNOWN','fixture'))
  with self.assertRaisesRegex(ValueError,'reconciliation'):cli.prepare(self.args)
 def test_missing_journal_never_created(self):
  (self.runtime/'runtime.sqlite').unlink()
  with self.assertRaisesRegex(ValueError,'existing owned journal'):cli.prepare(self.args)
  self.assertFalse((self.runtime/'runtime.sqlite').exists())
 def test_wrong_case_export_rejects(self):
  self.args.case_id='FINAL-B'
  with self.assertRaisesRegex(ValueError,'export case'):cli.prepare(self.args)
 def test_export_symlink_rejects(self):
  link=self.root/'linked.json';link.symlink_to(self.export);self.args.export=link
  with self.assertRaises((ValueError,OSError)):cli.prepare(self.args)
 def test_unsafe_run_id_rejects(self):
  self.args.run_id='retry; input'
  with self.assertRaisesRegex(ValueError,'run id'):cli.prepare(self.args)

 def test_missing_source_revision_rejects(self):
  self.args.source_revision='UNTRACKED'
  with self.assertRaisesRegex(ValueError,'source revision'):cli.prepare(self.args)
 def test_incomplete_semantic_flow_rejects_before_input(self):
  value=json.loads(self.export.read_bytes());value['steps']=value['steps'][:1]
  from reproloop.portable import export_from_bytes
  from replay_contracts import SemanticExport,Locator
  value['steps']=tuple(Locator(**step)for step in value['steps'])
  self.export.write_bytes(SemanticExport(**value).to_bytes())
  with self.assertRaisesRegex(ValueError,'four-step'):cli.prepare(self.args)
