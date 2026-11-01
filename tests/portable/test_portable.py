"""Offline synthetic boundary tests. No real device/model/network calls."""
import dataclasses
from hashlib import sha256
import json
import os
from pathlib import Path
import shutil
import stat
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile
sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'pair'))
import test_pair_binding
from reproloop.pair_binding import Files, bind_saved_pair
from reproloop.portable import verify, member_name, export_from_bytes, package


class PortableTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()

    def test_legacy_and_current_intent_manifest_keys(self):
        from evaluation.splits import build_frozen_splits_v2
        digest=build_frozen_splits_v2().manifest_sha256
        for index,keys in enumerate(({'live_manifest_sha256':digest},{'manifest_sha256':digest},{'live_manifest_sha256':digest,'manifest_sha256':digest})):
            root=self.root/str(index);root.mkdir()
            (root/'intent.json').write_text(json.dumps(dict(case_id='DEV-01',source_commit='a'*40,**keys)))
            with self.assertRaises(FileNotFoundError) as error: package(root,self.root/(str(index)+'.zip'))
            self.assertEqual(Path(error.exception.filename).name,'faulty-replay.json')
            self.assertFalse((self.root/(str(index)+'.zip')).exists())

    def test_missing_or_conflicting_manifest_never_packages(self):
        from evaluation.splits import build_frozen_splits_v2
        digest=build_frozen_splits_v2().manifest_sha256
        for index,keys in enumerate(({}, {'live_manifest_sha256':digest,'manifest_sha256':'f'*64})):
            root=self.root/str(index);root.mkdir()
            (root/'intent.json').write_text(json.dumps(dict(case_id='DEV-01',source_commit='a'*40,**keys)))
            with self.assertRaisesRegex(ValueError,'frozen manifest mismatch'): package(root,self.root/(str(index)+'.zip'))

    def test_cache_result_cannot_bypass_hash(self):
        p = self.root/('a'*64+'.png'); p.write_bytes(b'bad')
        files = Files(self.root)
        self.assertEqual(files.read(p, result=True), b'bad')
        with self.assertRaisesRegex(ValueError, 'content hash'): files.read(p)

    def test_cache_result_cannot_bypass_filename(self):
        p = self.root/'ordinary'; p.write_bytes(b'bad')
        files = Files(self.root); files.read(p, result=True)
        with self.assertRaisesRegex(ValueError, 'content address'): files.read(p)

    def test_rebase_cache_single_actual_file(self):
        raw = b'hello'; p = self.root/(sha256(raw).hexdigest()+'.png'); p.write_bytes(raw)
        files = Files(self.root, '/never-present-old-root')
        self.assertEqual(files.read('/never-present-old-root/'+p.name), raw)
        self.assertEqual(files.addressed(sha256(raw).hexdigest(), '.png'), raw)
        self.assertEqual((len(files.cache), files.total), (1, 5))

    def test_alias_url_outside_rejected(self):
        files = Files(self.root, '/never-present-old-root')
        for path in ['/never-present-old-root/../a', '/never-present-old-root/./a',
                     '/never-present-old-root//a', 'https://host/a',
                     '/never-present-old-root-untrusted/a', '/different/a']:
            with self.subTest(path=path), self.assertRaises(ValueError): files.read(path)

    def test_symlink_rejected(self):
        p = self.root/('a'*64+'.png'); p.symlink_to(self.root/'missing')
        with self.assertRaisesRegex(ValueError, 'symlink'): Files(self.root).read(p)

    def test_original_root_never_inspected(self):
        old = '/nonexistent-historical-host/evidence'
        raw = b'hello'; name = sha256(raw).hexdigest()+'.png'
        (self.root/name).write_bytes(raw)
        original_open, original_lstat = os.open, os.lstat
        def guard_open(path, *a, **kw):
            self.assertFalse(str(path).startswith(old)); return original_open(path, *a, **kw)
        def guard_lstat(path, *a, **kw):
            self.assertFalse(str(path).startswith(old)); return original_lstat(path, *a, **kw)
        with patch('os.open', guard_open), patch('os.lstat', guard_lstat):
            self.assertEqual(Files(self.root, old).read(old+'/'+name), raw)

    def test_relocated_pair_unchanged_and_corruption(self):
        helper = test_pair_binding.PairTests('test_normal_raw_pair'); helper.setUp()
        self.addCleanup(helper.doCleanups)
        baseline = helper.bind(); self.assertTrue(baseline.valid)
        dest = self.root/'relocated'; dest.mkdir()
        shutil.copytree(helper.evidence, dest/'evidence')
        paths = []
        for p in helper.paths:
            shutil.copyfile(p, dest/p.name); paths.append(dest/p.name)
        original = str(helper.evidence)
        # Historical path no longer exists. No JSON or content address changes.
        helper.evidence.rename(helper.evidence.with_name('retired-evidence'))
        args = dict(spec=helper.h.spec, export=helper.h.export, fixture=helper.h.fixture,
                    faulty_result_path=paths[0], fixed_result_path=paths[1],
                    evidence_root=dest/'evidence', original_evidence_root=original)
        report = bind_saved_pair(**args)
        self.assertTrue(report.valid, report.reason)
        for field in ('files_checked', 'bytes_checked'):
            self.assertEqual(report.proof[field], baseline.proof[field])
        self.assertFalse(bind_saved_pair(**{**args, 'original_evidence_root': None}).valid)
        victim = next((dest/'evidence').glob('*.png')); victim.write_bytes(b'corrupt')
        self.assertFalse(bind_saved_pair(**args).valid)

    def archive(self, name, body=b'x', mode=stat.S_IFREG|0o600, compression=zipfile.ZIP_STORED):
        p = self.root/'test.zip'
        with zipfile.ZipFile(p, 'w', compression=compression) as z:
            i = zipfile.ZipInfo(name); i.external_attr = mode << 16; i.compress_type = compression
            z.writestr(i, body)
        return p

    def test_archive_traversal(self):
        for name in ('../x', '/x', 'evidence/../x', './case.json', 'evidence//x', 'C:\\x'):
            with self.subTest(name=name), self.assertRaises(ValueError): member_name(name)

    def test_archive_symlink(self):
        archive = self.archive('case.json', mode=stat.S_IFLNK|0o777)
        with self.assertRaisesRegex(ValueError, 'nonregular'): verify(archive, self.root/'extract')
        self.assertFalse((self.root/'extract').exists())

    def test_archive_bomb(self):
        archive = self.archive('case.json', b'0'*1000000, compression=zipfile.ZIP_DEFLATED)
        with self.assertRaisesRegex(ValueError, 'bomb'): verify(archive, self.root/'extract')

    def test_archive_hash_corrupt(self):
        archive = self.root/'hash.zip'
        from reproloop.portable import LIMITS
        from evaluation.splits import build_frozen_splits_v2
        manifest = dict(version=1, limits=LIMITS, sourceRevision='a'*40,
                        frozenManifestSha256=build_frozen_splits_v2().manifest_sha256,
                        files={'case.json':'0'*64})
        with zipfile.ZipFile(archive, 'w') as z:
            z.writestr('portable-manifest.json', json.dumps(manifest))
            z.writestr('case.json', '{}')
        with self.assertRaisesRegex(ValueError, 'hashes'): verify(archive, self.root/'extract')

    def test_archive_duplicate(self):
        p = self.root/'duplicate.zip'
        with zipfile.ZipFile(p, 'w') as z:
            z.writestr('case.json', '{}')
            import warnings
            with warnings.catch_warnings():
                warnings.simplefilter('ignore'); z.writestr('case.json', '{}')
        with self.assertRaisesRegex(ValueError, 'duplicate'): verify(p, self.root/'extract')

    def test_extract_refuses_existing(self):
        p = self.archive('case.json')
        with self.assertRaisesRegex(ValueError, 'fresh'): verify(p, self.root)

    def test_export_rejects_noncanonical(self):
        with self.assertRaises((ValueError, KeyError)): export_from_bytes(b'{"steps":[],"steps":[]}')


if __name__ == '__main__': unittest.main()
