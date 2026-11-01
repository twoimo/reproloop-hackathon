"""Offline source-candidate tests. No devices, models or network."""
import importlib.util
from pathlib import Path
import json
import stat
import tempfile
import unittest
from unittest.mock import patch
import zipfile

SPEC = importlib.util.spec_from_file_location('release_candidate', Path(__file__).resolve().parents[2]/'tools/release_candidate.py')
rc = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(rc)
REAL_SOURCE_ALLOWLIST = tuple(rc.WHITELIST)


class CandidateTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.source = self.root/'source'
        self.source.mkdir()
        (self.source/'code.py').write_text('print("synthetic")\n')
        self.allowed = patch.object(rc, 'WHITELIST', ('code.py',))
        self.allowed.start()
        self.addCleanup(self.allowed.stop)
        self.archive = self.root/'candidate.zip'

    def build(self):
        rc.build(self.source, self.archive)

    def mutate(self, transform):
        self.build()
        with zipfile.ZipFile(self.archive) as archive:
            entries = [(i, archive.read(i)) for i in archive.infolist()]
        changed = self.root/'changed.zip'
        with zipfile.ZipFile(changed, 'w') as archive:
            for info, data in transform(entries):
                archive.writestr(info, data)
        return changed

    def test_deterministic_and_clean_full_set(self):
        self.build()
        other = self.root/'other.zip'
        rc.build(self.source, other)
        self.assertEqual(self.archive.read_bytes(), other.read_bytes())
        dest = self.root/'fresh'
        self.assertEqual(rc.verify(self.archive, dest), 2)
        manifest = json.loads((dest/rc.MANIFEST).read_bytes())
        actual = {p.relative_to(dest).as_posix() for p in dest.rglob('*') if p.is_file()}
        self.assertEqual(actual, {'code.py','README.md',rc.MANIFEST})
        self.assertEqual({f['path'] for f in manifest['files']}, actual-{rc.MANIFEST})
        self.assertFalse(manifest['execution_evidence'])

    def test_unlisted_private_file_never_read_or_copied(self):
        (self.source/'secret.db').write_bytes(b'not public')
        self.build()
        with zipfile.ZipFile(self.archive) as archive:
            self.assertNotIn('secret.db', archive.namelist())

    def test_missing_source_no_output(self):
        (self.source/'code.py').unlink()
        with self.assertRaises(OSError): self.build()
        self.assertFalse(self.archive.exists())

    def test_no_output_overwrite(self):
        self.archive.write_bytes(b'original')
        with self.assertRaises(ValueError): self.build()
        self.assertEqual(self.archive.read_bytes(), b'original')

    def test_no_existing_extraction_overwrite(self):
        self.build()
        dest=self.root/'existing';dest.mkdir()
        (dest/'keep').write_text('keep')
        with self.assertRaises(FileExistsError): rc.verify(self.archive,dest)
        self.assertEqual((dest/'keep').read_text(),'keep')

    def test_symlink_output_parent(self):
        alias=self.root/'alias';alias.symlink_to(self.source)
        with self.assertRaises(ValueError):rc.build(self.source,alias/'output.zip')
        self.assertFalse((self.source/'output.zip').exists())

    def test_nonregular_source(self):
        p=self.source/'code.py';p.unlink();p.mkdir()
        with self.assertRaises(ValueError):self.build()
        self.assertFalse(self.archive.exists())

    def test_symlink_source_file(self):
        p=self.source/'code.py';p.unlink();p.symlink_to(self.root/'absent')
        with self.assertRaises(ValueError): self.build()

    def test_symlink_source_root(self):
        alias=self.root/'alias';alias.symlink_to(self.source)
        with self.assertRaises(ValueError): rc.build(alias,self.archive)

    def test_symlink_extraction_parent(self):
        self.build()
        alias=self.root/'alias';alias.symlink_to(self.source)
        with self.assertRaises(ValueError): rc.verify(self.archive,alias/'fresh')
        self.assertFalse((self.source/'fresh').exists())

    def test_privacy_patterns_fail_closed(self):
        examples=['/'+'Users'+'/private/file', '/'+'home'+'/person/key',
                  'person'+'@'+'example.org', 'BEGIN '+'PRIVATE KEY',
                  'sk'+'-proj-'+'x'*30, 'AI'+'za'+'x'*35]
        for value in examples:
            with self.subTest(value=examples.index(value)):
                (self.source/'code.py').write_text(value)
                with self.assertRaises(ValueError): self.build()
                self.assertFalse(self.archive.exists())

    def test_dated_session_avd_rejected_without_copying_live_identity(self):
        # Generated SYNTHETIC fixture, not a hidden copy of any real session ID.
        for prefix in ('SyntheticRun', 'fixture_case', 'TEST'):
            name = '_'.join(('ReproLoop', prefix, '20990101'))
            (self.source/'code.py').write_text('avd_name = '+repr(name))
            with self.subTest(prefix=prefix), self.assertRaisesRegex(ValueError, 'privacy scan rejected'):
                self.build()
            self.assertFalse(self.archive.exists())

    def test_dated_session_rejected_even_with_rehashed_archive(self):
        # Integrity cannot launder structurally private identity into acceptance.
        def transform(rows):
            payload={i.filename:data for i,data in rows if i.filename!=rc.MANIFEST}
            payload['code.py']='_'.join(('ReproLoop', 'SyntheticRun', '20990101')).encode()
            payload[rc.MANIFEST]=rc.canonical(rc.manifest_for(payload))
            return [(i,payload[i.filename]) for i,_ in rows]
        changed=self.mutate(transform)
        with self.assertRaisesRegex(ValueError, 'privacy scan rejected'):
            rc.verify(changed, self.root/'fresh')
        self.assertFalse((self.root/'fresh').exists())

    def test_generic_synthetic_target_is_not_treated_as_a_secret(self):
        # Device serial alone is not authentication; these are synthetic fixtures.
        rc.scan('fixture.py', b"avd='ReproLoop_TEST_OWNED'; serial='emulator-5998'")

    def test_binary_and_size_rejection(self):
        for body in (b'\xff',b'a\x00b',b'x'*(rc.MAX_FILE+1)):
            (self.source/'code.py').write_bytes(body)
            with self.assertRaises(ValueError): self.build()
            self.assertFalse(self.archive.exists())

    def test_relative_path_aliases(self):
        for name in ('../x','/x','x/../y','./x','x//y','C:'+chr(92)+'x','x/',''):
            with self.subTest(name=name),self.assertRaises(ValueError):rc.member_name(name)

    def test_corrupt_payload_rejected_before_extraction(self):
        changed=self.mutate(lambda rows:[(i,b'changed' if i.filename=='code.py' else data) for i,data in rows])
        dest=self.root/'fresh'
        with self.assertRaisesRegex(ValueError,'manifest mismatch'):rc.verify(changed,dest)
        self.assertFalse(dest.exists())

    def test_extra_member(self):
        changed=self.mutate(lambda rows:rows+[('extra.txt',b'x')])
        with self.assertRaises(ValueError):rc.verify(changed)

    def test_duplicate_member(self):
        import warnings
        with warnings.catch_warnings():
            warnings.simplefilter('ignore',UserWarning)
            changed=self.mutate(lambda rows:rows+[rows[0]])
        with self.assertRaises(ValueError):rc.verify(changed)

    def test_missing_member(self):
        changed=self.mutate(lambda rows:rows[1:])
        with self.assertRaises(ValueError):rc.verify(changed)

    def test_traversal_member(self):
        changed=self.mutate(lambda rows:rows+[('../escape',b'x')])
        with self.assertRaises(ValueError):rc.verify(changed)
        self.assertFalse((self.root/'escape').exists())

    def test_archive_symlink(self):
        def transform(rows):
            for info,data in rows:
                if info.filename=='code.py': info.external_attr=(stat.S_IFLNK|0o777)<<16
            return rows
        changed=self.mutate(transform)
        with self.assertRaises(ValueError):rc.verify(changed)

    def test_compressed_member(self):
        def transform(rows):
            rows[0][0].compress_type=zipfile.ZIP_DEFLATED
            return rows
        changed=self.mutate(transform)
        with self.assertRaises(ValueError):rc.verify(changed)

    def test_malformed_manifest(self):
        changed=self.mutate(lambda rows:[(i,b'{}' if i.filename==rc.MANIFEST else data) for i,data in rows])
        with self.assertRaises(ValueError):rc.verify(changed)

    def test_generated_document_not_replaceable_even_with_rehashed_manifest(self):
        def transform(rows):
            payload={i.filename:data for i,data in rows if i.filename!=rc.MANIFEST}
            payload['README.md']=b'counterfeit clearance'
            payload[rc.MANIFEST]=rc.canonical(rc.manifest_for(payload))
            return [(i,payload[i.filename]) for i,_ in rows]
        changed=self.mutate(transform)
        with self.assertRaisesRegex(ValueError,'generated document mismatch'):rc.verify(changed)




class RealDependencyContract(unittest.TestCase):
    def test_own_mit_is_in_actual_package_without_public_release(self):
        self.assertIn('LICENSE',REAL_SOURCE_ALLOWLIST)
        root=Path(__file__).resolve().parents[2]
        license=(root/'LICENSE').read_text()
        self.assertTrue(license.startswith('MIT License\n'))
        self.assertIn('Copyright (c) 2026 Yeonwoo Choi',license)
        self.assertIn('THE SOFTWARE IS PROVIDED "AS IS"',license)
        value=rc.manifest_for({})
        self.assertEqual(value['project_license'],'MIT')
        self.assertFalse(value['public_release_approved'])

    def test_packaged_demo_safe_aggregate_dependency_is_in_real_allowlist(self):
        # Unlike the synthetic fixture tests, inspect the actual public selection.
        self.assertIn('demo/render.py', REAL_SOURCE_ALLOWLIST)
        self.assertIn('demo/safe-aggregates.json', REAL_SOURCE_ALLOWLIST)
        root=Path(__file__).resolve().parents[2]
        value=json.loads((root/'demo/safe-aggregates.json').read_bytes())
        self.assertEqual(value['schema'],1)
        self.assertEqual(value['budget']['upload_price'],'UNPRICED')


if __name__=='__main__':unittest.main()
