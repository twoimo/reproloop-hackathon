"""Synthetic offline PUBLIC preparation tests. No real media or review decisions."""
import contextlib
import io
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import sys
import unittest
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location('public_release', Path(__file__).resolve().parents[2]/'tools/public_release.py')
m = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(m)


class PublicPreparationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name).resolve()
        self.source = self.base/'source'; self.source.mkdir()
        self.media = self.base/'media'; self.media.mkdir()
        self.output = self.base/'ready'
        self.review = self.base/'review.json'
        self.names = ('code.py', 'LICENSE', 'THIRD_PARTY_NOTICES.md',
                      'third_party/example/LICENSE', m.CATALOG)
        p = patch.object(m.rc, 'WHITELIST', self.names)
        p.start(); self.addCleanup(p.stop)
        for name in (*self.names, *m.EXTRA_SOURCE):
            path = self.source/name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text('synthetic source and original notice\n')
        self.raw = {}
        def asset(name):
            body = (b'\x89PNG\r\n\x1a\nsynthetic' if name.endswith('.png')
                    else b'\x00\x00\x00\x18ftypisom\x00\x00\x00\x00isommp42')
            self.raw[name] = body
            (self.media/name).write_bytes(body)
            return {'path': 'recorded/'+name, 'bytes': len(body), 'sha256': m.digest(body),
                    'type': 'image/png' if name.endswith('.png') else 'video/mp4'}
        self.catalog = {'TEST': {'one': asset('faulty.png'), 'two': asset('fixed.png'),
                                 'video': asset('source.mp4')}}
        raw = m.rc.canonical(self.catalog)
        (self.source/m.CATALOG).write_bytes(raw)
        self.pin = patch.object(m, 'CATALOG_SHA256', m.digest(raw))
        self.pin.start(); self.addCleanup(self.pin.stop)
        self.review_value = {'kind': m.REVIEW_KIND, 'files': [
            {'path': 'ui/recorded/'+n, 'sha256': m.digest(body), 'visual_reviewed': True,
             'metadata_reviewed': True, 'rights_basis': m.RIGHTS_BASIS}
            for n, body in self.raw.items()]}
        self.save_review()

    def save_review(self):
        self.review.write_bytes(m.rc.canonical(self.review_value))

    def save_catalog(self, repin=True):
        raw = m.rc.canonical(self.catalog)
        (self.source/m.CATALOG).write_bytes(raw)
        if repin: m.CATALOG_SHA256 = m.digest(raw)

    def build(self):
        return m.build(self.source, self.media, self.review, self.output)

    def reject(self):
        with self.assertRaises((ValueError, OSError, TypeError)):
            self.build()
        self.assertFalse(self.output.exists())
        self.assertEqual(list(self.base.glob('.public-preparation-*')), [])

    def test_complete_inventory_preserves_bytes_notices_and_roles(self):
        (self.source/'raw-receipt.json').write_text('excluded')
        (self.media/'extra.png').write_bytes(b'excluded')
        count = self.build()
        self.assertEqual(m.verify(self.output), count)
        expected = set(self.names) | set(m.EXTRA_SOURCE) | {
            'README.md', m.REVIEW, m.MANIFEST, m.INVENTORY} | {'ui/recorded/'+n for n in self.raw}
        actual = {p.relative_to(self.output).as_posix() for p in self.output.rglob('*') if p.is_file()}
        self.assertEqual(expected, actual)
        for n, body in self.raw.items():
            self.assertEqual((self.output/'ui/recorded'/n).read_bytes(), body)
            self.assertEqual((self.media/n).read_bytes(), body)
        self.assertEqual((self.output/'LICENSE').read_bytes(), (self.source/'LICENSE').read_bytes())
        inv = json.loads((self.output/m.INVENTORY).read_bytes())
        self.assertEqual({r['role'] for r in inv['files']}, {'source','media','license','derived-review','manifest'})
        for row in inv['files']:
            raw = (self.output/row['path']).read_bytes()
            self.assertEqual(row['bytes'], len(raw)); self.assertEqual(row['sha256'], m.digest(raw))
        declaration = json.loads((self.output/m.MANIFEST).read_bytes())
        self.assertFalse(declaration['public_release_approved'])
        self.assertFalse(declaration['final_rights_clearance'])
        self.assertEqual(declaration['evidence_trust'], 'UNVERIFIED')

    def test_deterministic_review_and_inventory(self):
        self.build()
        other = self.base/'other'
        self.review_value['files'].reverse(); self.save_review()
        m.build(self.source, self.media, self.review, other)
        for name in (m.REVIEW, m.MANIFEST, m.INVENTORY):
            self.assertEqual((self.output/name).read_bytes(), (other/name).read_bytes())

    def test_private_source_and_extra_test_are_scanned(self):
        for name in ('code.py', m.EXTRA_SOURCE[-1]):
            with self.subTest(name=name):
                p = self.source/name
                p.write_text('person'+'@'+'example.invalid')
                self.reject(); p.write_text('safe source')

    def test_cli_build_verify_and_sanitized_errors(self):
        output = io.StringIO()
        with patch.object(sys, 'argv', ['public_release.py', '--source', str(self.source),
                '--media-root', str(self.media), '--review', str(self.review), '--out', str(self.output)]), contextlib.redirect_stdout(output):
            m.main()
        self.assertIn('NOT published or legally cleared', output.getvalue())
        with patch.object(sys, 'argv', ['public_release.py', '--verify', str(self.output)]), contextlib.redirect_stdout(io.StringIO()):
            m.main()
        (self.output/'code.py').write_text('changed')
        error = io.StringIO()
        with patch.object(sys, 'argv', ['public_release.py', '--verify', str(self.output)]), contextlib.redirect_stderr(error):
            with self.assertRaises(SystemExit) as exc: m.main()
        self.assertEqual(exc.exception.code, 2)
        self.assertNotIn(str(self.base), error.getvalue())

    def test_unavailable_atomic_primitive_fails_closed(self):
        with patch.object(sys, 'platform', 'unsupported-local-fixture'):
            with self.assertRaises(OSError): self.build()
        self.assertFalse(self.output.exists())
        self.assertEqual(list(self.base.glob('.public-preparation-*')), [])

    def test_bounded_total_size(self):
        with patch.object(m, 'MAX_TOTAL', 1): self.reject()

    def test_missing_source(self):
        (self.source/'code.py').unlink(); self.reject()

    def test_missing_media(self):
        (self.media/'faulty.png').unlink(); self.reject()

    def test_missing_review(self):
        self.review.unlink(); self.reject()

    def test_incomplete_review(self):
        self.review_value['files'].pop(); self.save_review(); self.reject()

    def test_review_duplicate(self):
        self.review_value['files'].append(dict(self.review_value['files'][0]))
        self.save_review(); self.reject()

    def test_strict_review_fields_booleans_and_hashes(self):
        original = dict(self.review_value['files'][0])
        for field, value in (('visual_reviewed', 1), ('visual_reviewed', False),
                             ('metadata_reviewed', 'true'), ('sha256', '0'*64),
                             ('path', '../private'), ('rights_basis', 'LEGAL_CLEARANCE'),
                             ('notes', 'free text')):
            with self.subTest(field=field, value=value):
                self.review_value['files'][0] = {**original, field: value}
                self.save_review(); self.reject()

    def test_review_top_level_extra_and_pii_not_copied(self):
        self.review_value['owner'] = 'person'+'@'+'example.invalid'
        self.save_review(); self.reject()

    def test_duplicate_json_keys_rejected(self):
        self.review.write_text('{"kind":"x","kind":"y","files":[]}')
        self.reject()

    def test_unregistered_catalog_even_if_review_present(self):
        self.catalog['NEW'] = dict(self.catalog['TEST'])
        self.save_catalog(repin=False); self.reject()

    def test_catalog_conflicting_duplicate(self):
        self.catalog['TEST']['two'] = {**self.catalog['TEST']['one'], 'sha256': '0'*64}
        self.save_catalog(); self.reject()

    def test_identical_catalog_duplicate_is_deduplicated(self):
        self.catalog['TEST']['steps'] = [{'one': self.catalog['TEST']['one'], 'two': self.catalog['TEST']['two']}]
        self.save_catalog(); self.build(); m.verify(self.output)

    def test_bad_catalog_path_type_size_hash(self):
        original = dict(self.catalog['TEST']['one'])
        for field, value in (('path','recorded/../escape.png'), ('path','recorded/sub/a.png'),
                             ('bytes', True), ('bytes', 0), ('type','video/mp4'),
                             ('sha256','bad'), ('sha256','A'*64)):
            with self.subTest(field=field, value=value):
                self.catalog['TEST']['one'] = {**original, field: value}
                self.save_catalog(); self.reject()

    def test_changed_media_hash_or_size(self):
        for body in (b'bad', b'x'*len(self.raw['faulty.png'])):
            (self.media/'faulty.png').write_bytes(body); self.reject()

    def test_wrong_signature_even_when_hash_matches(self):
        body = b'not a PNG file'
        (self.media/'faulty.png').write_bytes(body)
        self.catalog['TEST']['one'].update(bytes=len(body), sha256=m.digest(body))
        self.save_catalog()
        self.review_value['files'][0]['sha256'] = m.digest(body)
        self.save_review(); self.reject()

    def test_media_root_symlink(self):
        alias = self.base/'alias'; alias.symlink_to(self.media, target_is_directory=True)
        with self.assertRaises(ValueError): m.build(self.source, alias, self.review, self.output)

    def test_media_symlink_and_nonregular(self):
        p = self.media/'faulty.png'; p.unlink(); p.symlink_to(self.media/'fixed.png')
        self.reject(); p.unlink(); p.mkdir(); self.reject()

    def test_fifo_rejected_without_blocking(self):
        p = self.media/'faulty.png'; p.unlink(); os.mkfifo(p); self.reject()

    def test_source_and_review_symlinks(self):
        p = self.source/'code.py'; p.unlink(); p.symlink_to(self.source/'LICENSE'); self.reject()
        p.unlink(); p.write_text('safe')
        self.review.unlink(); self.review.symlink_to(self.source/'LICENSE'); self.reject()

    def test_existing_output_file_directory_and_symlink_not_replaced(self):
        for kind in ('file', 'directory', 'symlink'):
            with self.subTest(kind=kind):
                if kind == 'file': self.output.write_bytes(b'keep')
                elif kind == 'directory': self.output.mkdir()
                else: self.output.symlink_to(self.base/'absent')
                with self.assertRaises(ValueError): self.build()
                if kind == 'directory': self.output.rmdir()
                else: self.output.unlink()

    def test_output_symlink_parent(self):
        alias = self.base/'alias'; alias.symlink_to(self.base, target_is_directory=True)
        with self.assertRaises(ValueError): m.build(self.source, self.media, self.review, alias/'ready')

    def test_atomic_collision_preserves_racing_directory(self):
        publish = m.publish_directory
        def race(stage, output):
            output.mkdir()
            (output/'keep').write_text('existing owner')
            publish(stage, output)
        with patch.object(m, 'publish_directory', side_effect=race):
            with self.assertRaises(OSError): self.build()
        self.assertEqual((self.output/'keep').read_text(), 'existing owner')
        self.assertEqual(list(self.base.glob('.public-preparation-*')), [])

    def test_failure_cleans_only_owned_stage(self):
        untouched = self.base/'.public-preparation-other'; untouched.mkdir()
        (untouched/'keep').write_text('keep')
        with patch.object(m, 'verify', side_effect=ValueError('synthetic rejection')):
            with self.assertRaises(ValueError): self.build()
        self.assertFalse(self.output.exists())
        self.assertEqual(list(untouched.iterdir()), [untouched/'keep'])
        self.assertEqual(list(self.base.glob('.public-preparation-*')), [untouched])

    def test_verify_missing_extra_modified_and_symlink_files(self):
        self.build()
        p = self.output/'code.py'; original = p.read_bytes()
        p.unlink()
        with self.assertRaises(ValueError): m.verify(self.output)
        p.write_bytes(original)
        extra = self.output/'extra'; extra.write_bytes(b'private')
        with self.assertRaises(ValueError): m.verify(self.output)
        extra.unlink(); extra.mkdir()
        with self.assertRaises(ValueError): m.verify(self.output)
        extra.rmdir(); p.write_bytes(b'changed')
        with self.assertRaises(ValueError): m.verify(self.output)
        p.unlink(); p.symlink_to(self.source/'code.py')
        with self.assertRaises(ValueError): m.verify(self.output)

    def test_verify_media_review_manifest_inventory_tampering(self):
        self.build()
        for name in ('ui/recorded/faulty.png', m.REVIEW, m.MANIFEST, m.INVENTORY, 'README.md'):
            p = self.output/name; original = p.read_bytes(); p.write_bytes(b'{}')
            with self.subTest(name=name), self.assertRaises(ValueError): m.verify(self.output)
            p.write_bytes(original)

    def test_integrity_does_not_launder_private_text(self):
        self.build()
        (self.output/'code.py').write_text('/'+'home'+'/synthetic/private')
        payload = {p.relative_to(self.output).as_posix():p.read_bytes()
                   for p in self.output.rglob('*') if p.is_file() and p.name != m.INVENTORY}
        (self.output/m.INVENTORY).write_bytes(m.inventory(payload))
        with self.assertRaises(ValueError): m.verify(self.output)


class StaticContractTests(unittest.TestCase):
    def test_real_catalog_pin_and_selection(self):
        root = Path(__file__).resolve().parents[2]
        assets = m.catalog_assets((root/m.CATALOG).read_bytes())
        self.assertEqual(len(assets), 17)
        self.assertIn('tests/portable/test_demo_render_safety.py', m.EXTRA_SOURCE)
        self.assertEqual(set(m.EXTRA_SOURCE)-{'tests/portable/test_demo_render_safety.py'},
                         {'tools/public_release.py','tests/portable/test_public_release.py','docs/PUBLIC_RELEASE.md'})
        for name in m.EXTRA_SOURCE:
            m.rc.read_source(root, name)


if __name__ == '__main__': unittest.main()
