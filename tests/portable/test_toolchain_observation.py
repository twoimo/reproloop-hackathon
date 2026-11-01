"""Local read-only report boundaries, no SDK binary/model/device execution."""
from pathlib import Path
from hashlib import sha256
import importlib.util,json,os,subprocess,sys,tempfile,unittest
ROOT=Path(__file__).resolve().parents[2]
SPEC=importlib.util.spec_from_file_location('toolchain_observation',ROOT/'android/scripts/verify-toolchain.py')
tool=importlib.util.module_from_spec(SPEC);SPEC.loader.exec_module(tool)

class ObservationTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name).resolve()
  self.homes={name:self.root/name for name in('ANDROID_SDK_ROOT','KOTLIN_HOME')}
  for p in self.homes.values():p.mkdir()
  self.env={name:str(path)for name,path in self.homes.items()};self.env['UNRELATED_SECRET']='DO_NOT_EXPORT_ENVIRONMENT_SENTINEL'
  pins={}
  for key,(variable,relative)in tool.TOOLS.items():
   p=self.homes[variable]/relative;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(('fixture-'+key).encode());pins[key]=sha256(p.read_bytes()).hexdigest()
  self.lock=self.root/'lock.json';self.lock.write_text(json.dumps({'observed_installed_sha256':pins}));self.before=self.lock.read_bytes()
 def test_match_is_observation_not_native_or_independent_admission(self):
  d=tool.observe(self.env,self.lock);self.assertTrue(d['original_six_pins_match']);self.assertEqual(d['native_authority'],'NOT_EVALUATED_OR_GRANTED');self.assertEqual(d['independent_machine'],'NOT_ESTABLISHED_BY_METADATA');self.assertEqual(self.lock.read_bytes(),self.before)
  serialized=json.dumps(d);self.assertNotIn(self.env['UNRELATED_SECRET'],serialized);self.assertNotIn(str(self.root),serialized)
 def test_mismatch_keeps_original_lock_and_records_negative_result(self):
  key='aapt2';variable,relative=tool.TOOLS[key];(self.homes[variable]/relative).write_bytes(b'new-host-bytes')
  d=tool.observe(self.env,self.lock);self.assertFalse(d['original_six_pins_match']);self.assertEqual(d['mismatches'],[key]);self.assertEqual(self.lock.read_bytes(),self.before)
  out=self.root/'observed.json';tool.save_observation(out,d);self.assertFalse(json.loads(out.read_text())['original_six_pins_match'])
 def test_missing_environment_and_missing_file_are_not_success(self):
  d=tool.observe({},self.lock);self.assertFalse(d['original_six_pins_match']);self.assertTrue(d['errors'])
  variable,relative=tool.TOOLS['d8_jar'];(self.homes[variable]/relative).unlink();d=tool.observe(self.env,self.lock);self.assertFalse(d['original_six_pins_match']);self.assertIn('d8_jar',d['errors'][0])
 def test_report_is_private_exclusive_and_never_overwrites(self):
  out=self.root/'report.json';d=tool.observe(self.env,self.lock);tool.save_observation(out,d)
  self.assertEqual(out.stat().st_mode&0o777,0o600);before=out.read_bytes()
  with self.assertRaises(FileExistsError):tool.save_observation(out,d)
  self.assertEqual(out.read_bytes(),before)
 def test_symlink_output_or_parent_cannot_change_target(self):
  target=self.root/'target';target.write_text('keep');link=self.root/'linked';link.symlink_to(target)
  with self.assertRaises(FileExistsError):tool.save_observation(link,{})
  self.assertEqual(target.read_text(),'keep');parent=self.root/'alias';parent.symlink_to(self.root,target_is_directory=True)
  with self.assertRaises(ValueError):tool.save_observation(parent/'new.json',{})
 def test_cli_missing_environment_report_and_existing_output_stay_negative(self):
  android=self.root/'missing-project/android';script=android/'scripts/verify-toolchain.py';script.parent.mkdir(parents=True);script.write_bytes((ROOT/'android/scripts/verify-toolchain.py').read_bytes());(android/'toolchain-lock.json').write_bytes(self.before)
  env={k:v for k,v in os.environ.items()if k in('HOME','PATH','TMPDIR','LANG','PYTHONHOME','PYTHONPATH')}
  report=self.root/'missing.json';cmd=[sys.executable,str(script),'--record-observed',str(report)]
  p=subprocess.run(cmd,env=env,capture_output=True,text=True);self.assertEqual(p.returncode,2);self.assertTrue(json.loads(report.read_text())['errors']);before=report.read_bytes()
  p=subprocess.run(cmd,env=env,capture_output=True,text=True);self.assertEqual(p.returncode,2);self.assertEqual(report.read_bytes(),before);self.assertEqual(self.lock.read_bytes(),self.before)
 def test_malformed_original_lock_cannot_be_reported_as_pin_match(self):
  for value in([],{'observed_installed_sha256':{}},{'observed_installed_sha256':dict.fromkeys(tool.TOOLS,True)}):
   with self.subTest(value=value):
    self.lock.write_text(json.dumps(value))
    with self.assertRaises(ValueError):tool.observe(self.env,self.lock)
 def test_cli_negative_exit_is_preserved_even_when_report_is_saved(self):
  # A relocated synthetic copy binds only its own test lock, never the real one.
  android=self.root/'project/android';script=android/'scripts/verify-toolchain.py';script.parent.mkdir(parents=True);script.write_bytes((ROOT/'android/scripts/verify-toolchain.py').read_bytes());(android/'toolchain-lock.json').write_bytes(self.before)
  env={k:v for k,v in os.environ.items()if k in('HOME','PATH','TMPDIR','LANG','PYTHONHOME','PYTHONPATH')};env.update(self.env)
  good=subprocess.run([sys.executable,str(script)],env=env,capture_output=True,text=True);self.assertEqual(good.returncode,0,good.stdout+good.stderr);self.assertIn('PASS six',good.stdout)
  variable,relative=tool.TOOLS['aapt2'];(self.homes[variable]/relative).write_bytes(b'different')
  report=self.root/'cli-negative.json';bad=subprocess.run([sys.executable,str(script),'--record-observed',str(report)],env=env,capture_output=True,text=True)
  self.assertEqual(bad.returncode,1);self.assertIn('Tool pin mismatch: aapt2',bad.stderr);self.assertFalse(json.loads(report.read_text())['original_six_pins_match']);self.assertEqual(self.lock.read_bytes(),self.before)

class OwnLicenseGate(unittest.TestCase):
 def test_missing_empty_and_symlink_license_fail_before_build_side_effects(self):
  for mode in('missing','empty','symlink'):
   with self.subTest(mode=mode),tempfile.TemporaryDirectory()as temp:
    root=Path(temp);android=root/'android';android.mkdir();(android/'build.sh').write_bytes((ROOT/'android/build.sh').read_bytes())
    if mode=='empty':(root/'LICENSE').write_bytes(b'')
    if mode=='symlink':(root/'real-license').write_text('MIT');(root/'LICENSE').symlink_to(root/'real-license')
    env={k:v for k,v in os.environ.items()if k in('HOME','PATH','TMPDIR','LANG','PYTHONHOME','PYTHONPATH')};env.update(ANDROID_SDK_ROOT=str(root),JAVA_HOME=str(root),KOTLIN_HOME=str(root))
    p=subprocess.run(['/bin/bash',str(android/'build.sh')],env=env,capture_output=True,text=True)
    self.assertEqual(p.returncode,3);self.assertIn('project LICENSE',p.stderr);self.assertFalse((android/'build').exists())

if __name__=='__main__':unittest.main()
