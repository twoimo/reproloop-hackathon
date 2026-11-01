#!/usr/bin/env python3
"""Offline PUBLIC preparation gate, not publication or legal clearance.

Only explicitly selected text and hash-pinned catalog media are copied. Use
exclusively owned input/output parents, not adversarial concurrent writers.
"""
from pathlib import Path
import argparse
import ctypes
import hashlib
import importlib.util
import json
import os
import re
import shutil
import stat
import sys
import tempfile

_SPEC = importlib.util.spec_from_file_location('public_source_gate', Path(__file__).with_name('release_candidate.py'))
rc = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(rc)
EXTRA_SOURCE = ('tools/public_release.py', 'tests/portable/test_public_release.py',
                'docs/PUBLIC_RELEASE.md', 'tests/portable/test_demo_render_safety.py')
CATALOG = 'ui/fixtures/recorded-assets.json'
# Reviewed static catalog identity, not a media discovery/registration mechanism.
CATALOG_SHA256 = '20f6368b83058d4cb887fad514c4d69211bb3279d914f4ccb55989a7a01113b7'
REVIEW = 'public-asset-review.json'
MANIFEST = 'public-preparation.json'
INVENTORY = 'public-inventory.json'
REVIEW_KIND = 'REPROLOOP_PUBLIC_ASSET_REVIEW_V1'
RIGHTS_BASIS = 'PROJECT_AUTHORED_SELF_CAPTURED'
MAX_MEDIA = 16 * 1024 * 1024
MAX_TOTAL = 64 * 1024 * 1024
README = b'''# ReproLoop

From bug video to a replay you can verify.

Recorded-evidence prototype for one self-owned Android Cancel-persistence
fixture. The browser workbench inspects saved controls; it does not trigger
a device, replay or Meta inference. Imported claims remain UNVERIFIED and
backend scores remain null, including matching local media hashes.

## Open the workbench

From this directory, with Python already installed:

```sh
python3 -m http.server 8000 --bind 127.0.0.1 --directory ui
```

Open the displayed loopback address and choose **Explore recorded run**.
The bundled import is `ui/fixtures/recorded-case.json`. FINAL-C has four saved
post-action frames; A/B have terminal states only. Source video starts paused
and muted. Media requests are trusted static same-origin reads, not fresh runs.
See [the console guide](ui/README.md).

## What the evidence means

Original PILOT **2/5** missed its target. Separate FINAL **3/3** used different
sampled-context conditions; never pool them. Both cover one correlated bug
family with three variants, not general video-to-test accuracy. Extra frames,
pointer pixels, temporal OCR and supplied fixture labels were needed. The
fixed control is developer supplied with AI assistance, not autonomous repair.
No model superiority or human-time saving is claimed. Independent-host Android
reproduction and real novice review remain not done.

## Check the source

```sh
python3 tools/check_local.py
```

Python 3.11+, Node and preinstalled Pillow are required as documented in
[reproduction](docs/REPRODUCTION.md). These are local synthetic/boundary/UI
checks, not Android or Meta evaluation. The public subset is not the whole
private checkout. [Demo roles and exact hashes](demo/README.md) distinguish
the 180-second master, re-encoded upload derivative and historical manifests.

## Integrity and rights

This payload combines selected source and the fixed 17-path / 11-hash media
catalog. Its preparation inventory proves byte binding, not publication,
remote acceptance, native success, producer authenticity or legal clearance.
The tool does not perform the declared visual/metadata/rights review itself.
MIT covers project-owned source: [LICENSE](LICENSE). Third-party and media
rights remain separate: [notices](THIRD_PARTY_NOTICES.md) and retained notices
under third_party/. Original private Git history and prototype files are not
part of this new sanitized tree. See [preparation limits](docs/PUBLIC_RELEASE.md).
'''


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def no_duplicate_keys(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('duplicate JSON key')
        result[key] = value
    return result


def parse(raw):
    try:
        return json.loads(raw, object_pairs_hook=no_duplicate_keys)
    except (UnicodeError, json.JSONDecodeError):
        raise ValueError('invalid JSON') from None


def real_directory(value):
    p = Path(os.path.abspath(value))
    if any(q.is_symlink() for q in (p, *p.parents)) or not p.is_dir():
        raise ValueError('real nonsymlink directory required')
    return p


def regular(root, name, limit):
    rc.member_name(name)
    p = root
    for part in name.split('/'):
        p = p / part
        if p.is_symlink():
            raise ValueError('symlink input rejected')
    # NONBLOCK prevents FIFO opens from hanging; fstat rejects nonregular inputs.
    fd = os.open(p, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW)
    with os.fdopen(fd, 'rb') as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_size > limit:
            raise ValueError('nonregular or oversized input')
        raw = stream.read(limit + 1)
    if len(raw) > limit:
        raise ValueError('input size limit')
    return raw


def catalog_assets(raw):
    if digest(raw) != CATALOG_SHA256:
        raise ValueError('static catalog identity mismatch')
    value = parse(raw)
    if not isinstance(value, dict) or not value:
        raise ValueError('invalid catalog')
    result = {}

    def add(asset, media_type):
        if not isinstance(asset, dict) or set(asset) != {'path', 'bytes', 'sha256', 'type'}:
            raise ValueError('invalid catalog asset schema')
        name = rc.member_name(asset['path'])
        if not re.fullmatch(r'recorded/[A-Za-z0-9][A-Za-z0-9._-]*\.(png|mp4)', name):
            raise ValueError('invalid catalog media path')
        suffix_type = 'image/png' if name.endswith('.png') else 'video/mp4'
        if (asset['type'] != media_type or suffix_type != media_type
                or type(asset['bytes']) is not int or not 0 < asset['bytes'] <= MAX_MEDIA
                or not isinstance(asset['sha256'], str)
                or re.fullmatch(r'[0-9a-f]{64}', asset['sha256']) is None):
            raise ValueError('invalid catalog type, size or hash')
        name = 'ui/' + name
        if name in result and result[name] != asset:
            raise ValueError('conflicting duplicate catalog asset')
        result[name] = dict(asset)

    for case in value.values():
        if not isinstance(case, dict) or set(case) not in ({'one', 'two', 'video'}, {'one', 'two', 'video', 'steps'}):
            raise ValueError('invalid catalog case schema')
        add(case['one'], 'image/png'); add(case['two'], 'image/png'); add(case['video'], 'video/mp4')
        steps = case.get('steps', [])
        if not isinstance(steps, list):
            raise ValueError('invalid catalog steps')
        for step in steps:
            if not isinstance(step, dict) or set(step) != {'one', 'two'}:
                raise ValueError('invalid catalog step')
            add(step['one'], 'image/png'); add(step['two'], 'image/png')
    return result


def check_media(raw, asset):
    if len(raw) != asset['bytes'] or digest(raw) != asset['sha256']:
        raise ValueError('catalog media bytes/hash mismatch')
    if asset['type'] == 'image/png':
        good = raw.startswith(b'\x89PNG\r\n\x1a\n')
    else:
        good = (len(raw) >= 16 and raw[4:8] == b'ftyp'
                and 16 <= int.from_bytes(raw[:4], 'big') <= len(raw))
    if not good:
        raise ValueError('catalog media signature/type mismatch')


def safe_review(raw, assets):
    rc.scan(REVIEW, raw)
    value = parse(raw)
    if not isinstance(value, dict) or set(value) != {'kind', 'files'} or value['kind'] != REVIEW_KIND or not isinstance(value['files'], list):
        raise ValueError('invalid review schema')
    rows = {}
    fields = {'path', 'sha256', 'visual_reviewed', 'metadata_reviewed', 'rights_basis'}
    for row in value['files']:
        if not isinstance(row, dict) or set(row) != fields:
            raise ValueError('invalid review file schema')
        name = rc.member_name(row['path'])
        if (name not in assets or name in rows or row['sha256'] != assets[name]['sha256']
                or row['visual_reviewed'] is not True or row['metadata_reviewed'] is not True
                or row['rights_basis'] != RIGHTS_BASIS):
            raise ValueError('missing, duplicate, unreviewed or mismatched asset review')
        rows[name] = {'path': name, 'sha256': assets[name]['sha256'],
                      'visual_reviewed': True, 'metadata_reviewed': True, 'rights_basis': RIGHTS_BASIS}
    if set(rows) != set(assets):
        raise ValueError('review does not cover all catalog media')
    return rc.canonical({'kind': REVIEW_KIND, 'files': [rows[n] for n in sorted(rows)]})


def source_names():
    return set(rc.WHITELIST) | set(EXTRA_SOURCE)


def role(name):
    if name == REVIEW: return 'derived-review'
    if name == MANIFEST: return 'manifest'
    if name.startswith('ui/recorded/'): return 'media'
    notice = Path(name).name.upper()
    if (name in {'LICENSE', 'THIRD_PARTY_NOTICES.md'} or (name.startswith('third_party/')
            and ('/license/' in name or notice.startswith(('LICENSE', 'NOTICE', 'COPYRIGHT', 'PROVENANCE', 'SHA256SUMS'))))):
        return 'license'
    return 'source'


def metadata():
    return rc.canonical({'kind': 'REPROLOOP_PUBLIC_PREPARATION_V1',
                         'public_release_approved': False, 'final_rights_clearance': False,
                         'review_status': 'SUPPLIED_DECLARATIONS_ONLY', 'evidence_trust': 'UNVERIFIED',
                         'new_native_or_model_calls': 0, 'ci_completed': False,
                         'project_license_scope': 'MIT_REPROLOOP_OWNED_SOURCE_ONLY',
                         'pilot': '2/5', 'final': '3/3_CORRELATED_SEPARATE',
                         'catalog_sha256': CATALOG_SHA256})


def inventory(payload):
    # The inventory cannot contain its own hash. Its exact canonical form is
    # verified separately; every other file including the manifest is inventoried.
    return rc.canonical({'kind': 'REPROLOOP_PUBLIC_INVENTORY_V1',
                         'self_excluded': INVENTORY,
                         'files': [{'path': n, 'role': role(n), 'bytes': len(raw), 'sha256': digest(raw)}
                                   for n, raw in sorted(payload.items())]})


def expected_payload(root, media, review):
    payload = rc.source_payload(root)
    for name in EXTRA_SOURCE:
        payload[name] = rc.read_source(root, name)
    payload['README.md'] = README
    assets = catalog_assets(payload[CATALOG])
    for name, asset in assets.items():
        raw = regular(media, Path(name).name, MAX_MEDIA)
        check_media(raw, asset)
        payload[name] = raw
    payload[REVIEW] = safe_review(review, assets)
    payload[MANIFEST] = metadata()
    for name, raw in payload.items():
        if role(name) != 'media': rc.scan(name, raw)
    if sum(map(len, payload.values())) > MAX_TOTAL:
        raise ValueError('total size limit')
    payload[INVENTORY] = inventory(payload)
    return payload


def verify(directory):
    root = real_directory(directory)
    catalog = rc.read_source(root, CATALOG)
    assets = catalog_assets(catalog)
    expected = source_names() | {'README.md', REVIEW, MANIFEST, INVENTORY} | set(assets)
    parents = {p.as_posix() for n in expected for p in Path(n).parents if p.as_posix() != '.'}
    actual = set()
    # Directory traversal is ONLY for output closure verification, never copying.
    for base, dirs, files in os.walk(root, followlinks=False):
        for child in dirs + files:
            p = Path(base) / child
            n = p.relative_to(root).as_posix()
            if p.is_symlink() or (n not in parents and n not in expected):
                raise ValueError('unexpected or symlink output member')
            if p.is_dir():
                if n not in parents: raise ValueError('unexpected output directory')
            elif stat.S_ISREG(p.stat().st_mode): actual.add(n)
            else: raise ValueError('nonregular output member')
    if actual != expected:
        raise ValueError('missing or extra output files')
    payload = {}
    for name in sorted(expected):
        raw = regular(root, name, MAX_MEDIA if name in assets else rc.MAX_FILE)
        if name in assets: check_media(raw, assets[name])
        else: rc.scan(name, raw)
        payload[name] = raw
    if sum(map(len, payload.values())) > MAX_TOTAL: raise ValueError('total size limit')
    if payload[REVIEW] != safe_review(payload[REVIEW], assets): raise ValueError('noncanonical review')
    if payload['README.md'] != README or payload[MANIFEST] != metadata(): raise ValueError('generated declaration mismatch')
    raw_inventory = payload.pop(INVENTORY)
    if raw_inventory != inventory(payload): raise ValueError('final inventory mismatch')
    return len(payload) + 1


def publish_directory(stage, output):
    # Native no-replace rename, no fallback to overwrite-prone os.rename.
    libc = ctypes.CDLL(None, use_errno=True)
    if sys.platform == 'darwin' and hasattr(libc, 'renamex_np'):
        result = libc.renamex_np(os.fsencode(stage), os.fsencode(output), ctypes.c_uint(4))
    elif sys.platform.startswith('linux') and hasattr(libc, 'renameat2'):
        result = libc.renameat2(-100, os.fsencode(stage), -100, os.fsencode(output), 1)
    else: raise OSError('atomic no-replace directory rename unavailable')
    if result: raise OSError(ctypes.get_errno(), 'no-replace directory rename refused')


def build(source, media_root, review_file, output):
    source, media_root = real_directory(source), real_directory(media_root)
    output = Path(os.path.abspath(output))
    parent = real_directory(output.parent)
    if output.exists() or output.is_symlink(): raise ValueError('output already exists')
    if output == source or source in output.parents or output == media_root or media_root in output.parents:
        raise ValueError('output must be outside source and media roots')
    review_file = Path(os.path.abspath(review_file))
    review_parent = real_directory(review_file.parent)
    raw_review = regular(review_parent, review_file.name, rc.MAX_FILE)
    payload = expected_payload(source, media_root, raw_review)
    stage = Path(tempfile.mkdtemp(prefix='.public-preparation-', dir=parent))
    try:
        for name, raw in sorted(payload.items()):
            target = stage / name
            target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            with target.open('xb') as stream: stream.write(raw)
            target.chmod(0o600)
        count = verify(stage)
        publish_directory(stage, output)
        return count
    finally:
        if stage.exists(): shutil.rmtree(stage)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path)
    parser.add_argument('--media-root', type=Path, help='flat directory of exact catalog basenames')
    parser.add_argument('--review', type=Path)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--out', type=Path); group.add_argument('--verify', type=Path)
    args = parser.parse_args()
    if args.out and not all((args.source, args.media_root, args.review)):
        parser.error('--out requires --source, --media-root and --review')
    if args.verify and any((args.source, args.media_root, args.review)):
        parser.error('--verify accepts only the prepared directory')
    try:
        count = verify(args.verify) if args.verify else build(args.source, args.media_root, args.review, args.out)
    except (ValueError, OSError, KeyError, TypeError, RecursionError):
        parser.exit(2, 'PUBLIC preparation refused; inspect selected inputs or output integrity locally\n')
    print(f'PUBLIC preparation: {count} files verified; NOT published or legally cleared; no new execution')


if __name__ == '__main__': main()
