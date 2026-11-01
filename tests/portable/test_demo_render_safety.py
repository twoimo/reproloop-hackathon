"""Offline renderer boundaries. Fake encoder/probe; no full 180s encoding."""
import hashlib
import importlib.util
import json
import io
import contextlib
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

# Assemble synthetic negative vectors at runtime, as in the release scanner tests.
FAKE_EMAIL = 'private' + '@' + 'example.invalid'
FAKE_HOST_HOME = '/' + 'Users' + '/private'

SPEC = importlib.util.spec_from_file_location('demo_render', Path(__file__).resolve().parents[2]/'demo/render.py')
r = importlib.util.module_from_spec(SPEC)
try:
    SPEC.loader.exec_module(r)
except ModuleNotFoundError as exc:
    if exc.name != 'PIL':raise
    r = None


@unittest.skipIf(r is None, 'Pillow is required for the optional local demo renderer')
class RenderSafetyTests(unittest.TestCase):
    def setUp(self):
        if not Path(r.FONT).is_file():
            fonts = patch.object(r,'font',side_effect=lambda n,b=False:r.ImageFont.load_default(size=n))
            fonts.start();self.addCleanup(fonts.stop)
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.out = self.base/'output'
        self.scratch = self.base/'scratch'
        self.image = self.base/'capture.png'
        r.Image.new('RGB', (240, 420), 'white').save(self.image)
        self.receipt = self.base/'receipt.json'
        self.data = {'kind':'PRIVATE_RECORDED_WORKBENCH_SOFTWARE_CAPTURE',
                     'capture_sha256':r.sha(self.image),
                     'not_a_new_native_or_Meta_run':True,'not_producer_attestation':True,
                     'owner_email':FAKE_EMAIL, 'extra':{'home':FAKE_HOST_HOME},
                     'source_revision':'a'*40,
                     'base_revision':'b'*40,
                     'committed_snapshot_matching_captured_bytes':'c'*40,
                     'source_files':[{'path':name,'sha256':str(i)*64}
                                     for i,name in enumerate(sorted(r.WORKBENCH_SOURCE_PATHS),1)],
                     'capture':FAKE_EMAIL + '.png',
                     'captured_at':'2026-11-01T07:40:31.822538+00:00'}
        r.js(self.receipt,self.data)

    def args(self, workbench=True):
        args = ['render.py','--session',str(self.base),'--out',str(self.out),'--scratch',str(self.scratch)]
        if workbench: args += ['--workbench-image',str(self.image),'--workbench-source-manifest',str(self.receipt)]
        return args

    def fixture(self):
        root = self.base/'tmp/final-native-v4obs1/FINAL-C-v4obs1'
        (root/'model').mkdir(parents=True)
        (root/'evidence').mkdir()
        pic = root/'evidence'/('b'*64+'.png')
        pic.write_bytes(self.image.read_bytes())
        step = {'receipt':{'evidence':{'png_sha256':'b'*64}}}
        r.js(root/'model/exploration-summary.json',{'attempts':[step]*4})
        r.js(root/'model/semantic-export.json',{'steps':['select','rename','today','cancel']})
        r.js(root/'summary.json',{'source_commit':'c'*40,'export_sha256':'d'*64,
             'fixture_sha256':'e'*64,'build_sha256':'f'*64,'model_calls':5,'read_only_observations':0})
        for kind in ('faulty','fixed'):
            r.js(root/(kind+'-replay.json'),{'trace_sha256':kind,'script_sha256':'d'*64,
                 'model_calls':0,'complete':True,'oracle_run':{'failure_observed':kind=='faulty'}})
            r.js(root/'evidence'/(kind+'.trace.json'),{'steps':[step]*4})
        view = self.base/'artifacts/ReproLoop_Final_Viewer'
        view.mkdir(parents=True)
        (view/'FINAL-C-recorded-source.mp4').write_bytes(b'original video')

    def fake_run(self, args):
        if '-version' in args:return SimpleNamespace(stdout=b'fake offline encoder\n')
        if args[0] == r.FP:
            if '-count_frames' not in args:return SimpleNamespace(stdout=json.dumps({'format':{'duration':'31.158'}}).encode())
            return SimpleNamespace(stdout=json.dumps({'format':{'format_name':'mov,mp4','duration':'180.000','size':'12'},
              'streams':[{'index':0,'codec_type':'video','codec_name':'h264','pix_fmt':'yuv420p',
              'width':1920,'height':1080,'r_frame_rate':'24/1','nb_read_frames':'4320','duration':'180.000'}]}).encode())
        dest=Path(args[-1])
        if dest.suffix=='.jpg':r.Image.new('RGB',(640,360),'white').save(dest)
        else:
            self.assertIn('-an',args)
            if '-c:v' in args:self.assertEqual(args[args.index('-c:v')+1],'libx264')
            dest.write_bytes(b'fake encoded output')
        return SimpleNamespace(stdout=b'')

    def invoke(self, workbench=True, runner=None):
        with contextlib.redirect_stdout(io.StringIO()), patch.object(sys,'argv',self.args(workbench)), patch.object(r,'run',side_effect=runner or self.fake_run):
            r.main()

    def test_text_block_shrinks_unbroken_word_to_fit_width(self):
        draw=r.ImageDraw.Draw(r.Image.new('RGB',(1600,240),'white'))
        word='W'*40
        width=int(draw.textlength(word,font=r.font(28)))+1
        self.assertLess(width,draw.textlength(word,font=r.font(29)))
        self.assertLess(width,draw.textlength(word,font=r.font(56)))
        box=(10,10,10+width,210)
        with patch.object(draw,'text',wraps=draw.text) as render_text:
            end=r.text_block(draw,[word],box,n=56)
        render_text.assert_called_once()
        self.assertEqual(render_text.call_args.args[1],word)
        fitted_font=render_text.call_args.kwargs['font']
        self.assertEqual(fitted_font.size,28)
        self.assertLessEqual(draw.textlength(word,font=fitted_font),width)
        self.assertLessEqual(end,box[3])

    def test_text_block_keeps_requested_size_when_both_dimensions_fit(self):
        draw=r.ImageDraw.Draw(r.Image.new('RGB',(800,240),'white'))
        with patch.object(draw,'text',wraps=draw.text) as render_text:
            end=r.text_block(draw,['Fits'],(10,10,790,210),n=56)
        render_text.assert_called_once()
        self.assertEqual(render_text.call_args.args[1],'Fits')
        self.assertEqual(render_text.call_args.kwargs['font'].size,56)
        self.assertEqual(end,10+round(56*1.28))

    def test_text_block_rejects_when_no_permitted_size_fits(self):
        draw=r.ImageDraw.Draw(r.Image.new('RGB',(800,240),'white'))
        word='W'*40
        too_narrow=int(draw.textlength(word,font=r.font(28)))-1
        for box in ((0,0,too_narrow,200),(0,0,2000,round(28*1.28)-1)):
            with self.subTest(box=box),patch.object(draw,'text') as render_text:
                with self.assertRaisesRegex(ValueError,'Text exceeds reserved presentation band'):
                    r.text_block(draw,[word],box,n=56)
                render_text.assert_not_called()

    def test_sanitized_receipt_no_arbitrary_fields_or_paths(self):
        original=self.receipt.read_bytes()
        safe=r.sanitized_receipt(self.data,original,r.sha(self.image))
        text=json.dumps(safe)
        self.assertNotIn('private@',text)
        self.assertNotIn('/' + 'Users' + '/',text)
        self.assertNotIn('owner_email',safe)
        self.assertEqual(safe['original_receipt']['sha256'],hashlib.sha256(original).hexdigest())
        self.assertEqual(safe['source_revision'],'a'*40)
        self.assertNotEqual(hashlib.sha256((json.dumps(safe,indent=2)+'\n').encode()).hexdigest(),r.sha(self.receipt))
        self.assertEqual(self.receipt.read_bytes(),original)

    def test_actual_contract_provenance_preserved_but_extras_dropped(self):
        self.data['source_files'][0]['owner']=FAKE_EMAIL
        self.data['source_files'][0]['metadata']={'home':FAKE_HOST_HOME}
        original=json.dumps(self.data).encode()
        safe=r.sanitized_receipt(self.data,original,r.sha(self.image))
        self.assertEqual(safe['base_revision'],self.data['base_revision'])
        self.assertEqual(safe['committed_snapshot_matching_captured_bytes'],self.data['committed_snapshot_matching_captured_bytes'])
        self.assertEqual(safe['source_files'],[{'path':item['path'],'sha256':item['sha256']}
                                             for item in self.data['source_files']])
        self.assertEqual(safe['source_hashes_verification'],'DECLARED_ONLY_NOT_INDEPENDENTLY_VERIFIED')
        self.assertNotIn('private@',json.dumps(safe));self.assertNotIn('/' + 'Users' + '/',json.dumps(safe))
        self.assertNotIn('capture',safe);self.assertNotIn('captured_at',safe)
        self.assertEqual(safe['original_receipt']['sha256'],hashlib.sha256(original).hexdigest())

    def test_bad_provenance_rejected_before_output(self):
        valid=json.loads(json.dumps(self.data))
        mutations=[
            lambda d:d.update(base_revision='A'*40),
            lambda d:d.update(committed_snapshot_matching_captured_bytes=FAKE_EMAIL),
            lambda d:d['source_files'][0].update(path=FAKE_HOST_HOME + '/secret'),
            lambda d:d['source_files'][0].update(path='ui/../secret'),
            lambda d:d['source_files'][0].update(sha256='f'*63),
            lambda d:d['source_files'][0].update(sha256='F'*64),
            lambda d:d['source_files'][0].update(sha256=FAKE_EMAIL),
            lambda d:d['source_files'].append(dict(d['source_files'][0])),
            lambda d:d['source_files'].append(dict(d['source_files'][0],sha256='0'*64)),
            lambda d:d['source_files'].pop(),
            lambda d:d.update(source_files={}),
            lambda d:d.update(source_files=[None]),
        ]
        for mutate in mutations:
            self.data=json.loads(json.dumps(valid));mutate(self.data);r.js(self.receipt,self.data)
            with self.subTest(receipt=self.data),contextlib.redirect_stderr(io.StringIO()),self.assertRaises(SystemExit):
                self.invoke()
            self.assertFalse(self.out.exists());self.assertFalse(self.scratch.exists())

    def test_optional_provenance_legacy_and_64hex_revisions(self):
        self.data['base_revision']='b'*64
        self.data['committed_snapshot_matching_captured_bytes']='c'*64
        safe=r.sanitized_receipt(self.data,json.dumps(self.data).encode(),r.sha(self.image))
        self.assertEqual(safe['base_revision'],'b'*64)
        self.assertEqual(safe['committed_snapshot_matching_captured_bytes'],'c'*64)
        for key in ('source_files','base_revision','committed_snapshot_matching_captured_bytes'):
            self.data.pop(key)
        safe=r.sanitized_receipt(self.data,json.dumps(self.data).encode(),r.sha(self.image))
        self.assertNotIn('source_files',safe)

    def test_existing_destinations_and_symlinks_preserved(self):
        for target in (self.out,self.scratch):
            target.mkdir()
            (target/'keep').write_bytes(b'keep')
            with self.assertRaises(FileExistsError):
                with r.render_workspace(self.out,self.scratch):self.fail('must reject')
            self.assertEqual((target/'keep').read_bytes(),b'keep')
            (target/'keep').unlink();target.rmdir()
            target.symlink_to(self.base/'missing')
            with self.assertRaises(FileExistsError):
                with r.render_workspace(self.out,self.scratch):self.fail('must reject symlink')
            self.assertTrue(target.is_symlink());target.unlink()

    def test_symlink_parent_rejected(self):
        alias=self.base/'alias';alias.symlink_to(self.base,target_is_directory=True)
        with self.assertRaises(ValueError):
            with r.render_workspace(alias/'output',self.scratch):self.fail('must reject')

    def test_concurrent_final_creation_not_replaced(self):
        with self.assertRaises(FileExistsError):
            with r.render_workspace(self.out,self.scratch) as (stage,tmp):
                (stage/'new').write_text('new')
                self.out.mkdir()
        self.assertEqual(list(self.out.iterdir()),[])
        self.assertFalse(self.scratch.exists())
        self.assertFalse(list(self.base.glob('.output-staging-*')))

    def test_atomic_publish_and_failure_cleanup(self):
        with r.render_workspace(self.out,self.scratch) as (stage,tmp):
            self.assertFalse(self.out.exists())
            (stage/'done').write_text('done')
            (tmp/'frame').write_text('not distributed')
        self.assertEqual((self.out/'done').read_text(),'done')
        self.assertFalse(self.scratch.exists())
        other=self.base/'other'
        with self.assertRaises(OSError):
            with r.render_workspace(other,self.scratch) as (stage,tmp):
                (stage/'partial').write_text('partial')
                raise OSError('write failed')
        self.assertFalse(other.exists());self.assertFalse(self.scratch.exists())
        self.assertFalse(list(self.base.glob('.*-staging-*')))

    def test_mismatched_input_rejected_without_output(self):
        self.data['capture_sha256']='0'*64;r.js(self.receipt,self.data)
        with self.assertRaises(SystemExit):self.invoke()
        self.assertFalse(self.out.exists());self.assertFalse(self.scratch.exists())

    def test_invalid_receipt_types_and_flags_fail_closed(self):
        for value in ([],None,{'kind':'PRIVATE_RECORDED_WORKBENCH_SOFTWARE_CAPTURE'},
                      dict(self.data,not_producer_attestation='true'),
                      dict(self.data,screenshot_sha256='f'*64)):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    r.sanitized_receipt(value,b'original',r.sha(self.image))

    def test_missing_optional_pair_rejected_without_output(self):
        args=self.args()[:-2]
        with patch.object(sys,'argv',args),self.assertRaises(SystemExit):r.main()
        self.assertFalse(self.out.exists());self.assertFalse(self.scratch.exists())

    def test_nested_paths_rejected_without_output(self):
        for output,scratch in ((self.out,self.out/'scratch'),(self.scratch/'out',self.scratch)):
            with self.assertRaises(ValueError):
                with r.render_workspace(output,scratch):self.fail('must reject')
        self.assertFalse(self.out.exists());self.assertFalse(self.scratch.exists())

    def test_intermediate_encoder_failure_cleans_partial_outputs(self):
        self.fixture()
        def fail(args):
            if args[0]==r.FF and Path(args[-1]).name=='part-03.mp4':
                raise subprocess.CalledProcessError(1,args)
            return self.fake_run(args)
        with self.assertRaises(subprocess.CalledProcessError):self.invoke(runner=fail)
        self.assertFalse(self.out.exists());self.assertFalse(self.scratch.exists())
        self.assertFalse(list(self.base.glob('.output-staging-*')))

    def test_late_manifest_write_failure_never_publishes(self):
        self.fixture();real_js=r.js
        def fail(path,data):
            if path.name=='distribution-manifest.json':raise OSError('disk full')
            real_js(path,data)
        with patch.object(r,'js',side_effect=fail),self.assertRaises(OSError):self.invoke()
        self.assertFalse(self.out.exists());self.assertFalse(self.scratch.exists())
        self.assertFalse(list(self.base.glob('.output-staging-*')))

    def test_normal_both_modes_inventory_and_source_preservation(self):
        self.fixture()
        before={p:p.read_bytes() for p in self.base.rglob('*') if p.is_file()}
        for workbench in (True,False):
            self.out=self.base/('with-ui' if workbench else 'without-ui')
            self.invoke(workbench)
            entries=json.loads((self.out/'storyboard.json').read_text())
            self.assertEqual(len(entries),23)
            self.assertEqual(entries[0]['start'],0);self.assertEqual(entries[-1]['end'],180)
            self.assertTrue(all(a['end']==b['start'] for a,b in zip(entries,entries[1:])))
            inventory=json.loads((self.out/'distribution-manifest.json').read_text())
            listed={x['file'] for x in inventory['files']}
            actual={p.relative_to(self.out).as_posix() for p in self.out.rglob('*') if p.is_file()}
            self.assertEqual(listed,actual-{'distribution-manifest.json'})
            self.assertTrue({'safe-evidence.json','STORYBOARD.md','storyboard.json','ReproLoop_180s.srt','REHEARSAL.md'}<=listed)
            self.assertFalse(any('part-' in name or 'slide-' in name for name in listed))
            for item in inventory['files']:
                p=self.out/item['file'];self.assertEqual(item['sha256'],r.sha(p));self.assertEqual(item['bytes'],p.stat().st_size)
            source=json.loads((self.out/'source-manifest.json').read_text())['sources']
            for item in source.values():self.assertEqual(item['sha256'],r.sha(self.out/item['file']))
            if workbench:
                receipt=source['workbench-source-receipt']
                self.assertNotEqual(receipt['sha256'],receipt['original_receipt']['sha256'])
                self.assertEqual((self.out/source['workbench-image']['file']).read_bytes(),self.image.read_bytes())
                self.assertNotIn('private@',(self.out/receipt['file']).read_text())
                derivative=json.loads((self.out/receipt['file']).read_text())
                self.assertEqual(derivative['source_files'],self.data['source_files'])
                self.assertEqual(derivative['base_revision'],self.data['base_revision'])
                self.assertEqual(derivative['committed_snapshot_matching_captured_bytes'],self.data['committed_snapshot_matching_captured_bytes'])
        for p,data in before.items():self.assertEqual(p.read_bytes(),data)


if __name__=='__main__':unittest.main()
