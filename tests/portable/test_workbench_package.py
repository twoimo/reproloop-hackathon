from pathlib import Path
from hashlib import sha256
import importlib.util
import json
import tempfile
import unittest
import zipfile

SPEC=importlib.util.spec_from_file_location('package_workbench',Path(__file__).resolve().parents[2]/'tools/package_workbench.py')
m=importlib.util.module_from_spec(SPEC);SPEC.loader.exec_module(m)

class PrivateWorkbenchPackage(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.base=Path(self.tmp.name).resolve();self.root=self.base/'source';self.media=self.base/'media';self.media.mkdir();self.out=self.base/'viewer.zip'
  for name in (*m.FILES,'LICENSE','third_party/hallmark/LICENSE'):
   p=self.root/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_text('synthetic source fixture')
  self.assets={}
  def asset(name):
   raw=('synthetic '+name).encode();self.assets[name]=raw;self.media.joinpath(name).write_bytes(raw)
   return {'path':'recorded/'+name,'bytes':len(raw),'sha256':sha256(raw).hexdigest(),'type':'video/mp4'if name.endswith('.mp4')else'image/png'}
  case=dict(one=asset('test.png'),two=asset('fixed.png'),video=asset('source.mp4'))
  case['steps']=[dict(one=asset('faulty-step'+str(i)+'.png'),two=asset('fixed-step'+str(i)+'.png'))for i in range(4)]
  self.media.joinpath('unrelated-not-packaged.bin').write_bytes(b'excluded')
  self.root.joinpath('ui/fixtures/recorded-assets.json').write_text(json.dumps({'TEST':case}))
 def tearDown(self):self.tmp.cleanup()
 def test_exact_private_payload_retains_notices_and_false_release(self):
  result=m.build(self.root,self.media,self.out)
  self.assertFalse(result['public_release_approved']);self.assertEqual(self.out.stat().st_mode&0o777,0o600)
  with zipfile.ZipFile(self.out)as z:
   expected={n.removeprefix('ui/')for n in m.FILES}|{'LICENSE','licenses/Hallmark-LICENSE','PRIVATE_VIEWER_README.txt','viewer-manifest.json'}|{'recorded/'+n for n in self.assets}
   self.assertEqual(set(z.namelist()),expected)
   self.assertEqual({r['path']for r in result['files']},expected-{'viewer-manifest.json'})
   for name,raw in self.assets.items():self.assertEqual(z.read('recorded/'+name),raw)
   for row in result['files']:self.assertEqual(sha256(z.read(row['path'])).hexdigest(),row['sha256'])
 def test_changed_media_is_rejected_before_output(self):
  (self.media/'test.png').write_bytes(b'changed')
  with self.assertRaises(ValueError):m.build(self.root,self.media,self.out)
  self.assertFalse(self.out.exists())
 def test_asset_symlink_is_rejected_without_touching_target(self):
  p=self.media/'test.png';raw=p.read_bytes();p.unlink();victim=self.base/'original';victim.write_bytes(raw);p.symlink_to(victim)
  with self.assertRaises(ValueError):m.build(self.root,self.media,self.out)
  self.assertEqual(victim.read_bytes(),raw);self.assertFalse(self.out.exists())
 def test_existing_output_is_not_replaced(self):
  self.out.write_bytes(b'keep')
  with self.assertRaises(ValueError):m.build(self.root,self.media,self.out)
  self.assertEqual(self.out.read_bytes(),b'keep')
 def test_missing_media_does_not_emit_partial_package(self):
  (self.media/'test.png').unlink()
  with self.assertRaises(ValueError):m.build(self.root,self.media,self.out)
  self.assertFalse(self.out.exists());self.assertEqual(list(self.base.glob('.workbench-*')),[])

if __name__=='__main__':unittest.main()
