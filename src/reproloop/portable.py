"""Private, lossless saved-pair transport. Byte integrity is not attestation."""
from dataclasses import asdict
from hashlib import sha256
from pathlib import Path
import os
import re
import stat
import tempfile
import zipfile
from replay_contracts import SemanticExport, Locator
from repro_oracle import CaseSpec, validate_spec
from evaluation.splits import build_frozen_splits_v2, get_native_scenario
from .pair_binding import (Files, bind_saved_pair, canonical, equal, require,
                           strict_json, lexical_absolute)

MAX_FILE = 16_777_216
MAX_TOTAL = 268_435_456
LIMITS = ['PRIVATE: raw metadata retains original local host paths; NOT public sanitized',
          'byte integrity only; NOT producer/native attestation',
          'NOT video-to-intent evidence or a heldout pilot',
          'scope: two result JSONs plus referenced evidence union, not whole source folder']
FIXED = {'case.json', 'fixture.json', 'semantic-export.json',
         'faulty-replay.json', 'fixed-replay.json'}
SUFFIX = r'[0-9a-f]{64}\.(?:png|xml|state\.json|events\.jsonl|capture\.json|script\.json|trace\.json|reset\.json|proof\.json|journal\.json|stability\.json)'


def export_from_bytes(raw):
    value = strict_json(raw)
    value['steps'] = tuple(Locator(**s) for s in value['steps'])
    export = SemanticExport(**value)
    require(export.to_bytes() == raw, 'canonical semantic export required')
    return export


def real_directory(path):
    p = lexical_absolute(path)
    require(p == p.resolve() and p.is_dir(), 'real directory required')
    for q in (p, *p.parents):
        require(not q.is_symlink(), 'symlink directory forbidden')
    return p


def bounded_read(path):
    p = lexical_absolute(path)
    real_directory(p.parent)
    fd = os.open(p, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        before = os.fstat(fd)
        require(stat.S_ISREG(before.st_mode) and 0 < before.st_size <= MAX_FILE,
                'regular bounded file required')
        with os.fdopen(fd, 'rb', closefd=False) as f:
            raw = f.read(MAX_FILE + 1)
        after = os.fstat(fd)
        require(len(raw) == before.st_size and
                (before.st_size, before.st_mtime_ns, before.st_ctime_ns) ==
                (after.st_size, after.st_mtime_ns, after.st_ctime_ns), 'changed source file')
        return raw
    finally:
        os.close(fd)


def validated_case(case):
    spec = CaseSpec(**case)
    validate_spec(spec)
    scenario = get_native_scenario(spec.case_id)
    expected = scenario.to_case_spec(spec.faulty_build_sha256, spec.repaired_build_sha256)
    equal(asdict(spec), asdict(expected), 'frozen v2 case mismatch')
    return spec, scenario.to_fixture_spec()


def bind(root, spec, export, fixture, generation, original=None):
    report = bind_saved_pair(spec, export, fixture, root/'faulty-replay.json',
                             root/'fixed-replay.json', root/'evidence', generation,
                             original_evidence_root=original)
    require(report.valid, report.reason)
    return report


def package(case_root, out):
    root = real_directory(case_root)
    out = lexical_absolute(out)
    real_directory(out.parent)
    require(out.suffix == '.zip' and not out.exists() and not out.is_symlink(),
            'new absolute .zip output required')
    intent = strict_json(bounded_read(root/'intent.json'))
    frozen = build_frozen_splits_v2()
    claims = [intent[k] for k in ('live_manifest_sha256', 'manifest_sha256') if k in intent]
    require(bool(claims) and all(v == frozen.manifest_sha256 for v in claims), 'frozen manifest mismatch')
    scenario = get_native_scenario(intent['case_id'], frozen)
    results = {m: bounded_read(root/(m+'-replay.json')) for m in ('faulty', 'fixed')}
    saved = {m: strict_json(raw) for m, raw in results.items()}
    spec, fixture = validated_case(asdict(scenario.to_case_spec(
        saved['faulty']['oracle_run']['build_sha256'], saved['fixed']['oracle_run']['build_sha256'])))
    generation = saved['faulty']['oracle_run']['generation']
    export = export_from_bytes(bounded_read(root/'model'/'semantic-export.json'))
    before = bind(root, spec, export, fixture, generation)
    files = Files(root/'evidence')
    payload = {m+'-replay.json': raw for m, raw in results.items()}
    payload.update({'case.json': canonical(asdict(spec)), 'fixture.json': canonical(asdict(fixture)),
                    'semantic-export.json': export.to_bytes()})
    for result in saved.values():
        for path in result['evidencepaths'] + [str(files.root/(result['reset_receipt_sha256']+'.reset.json'))]:
            p = lexical_absolute(path)
            require(p.parent == files.root and re.fullmatch(SUFFIX, p.name), 'flat evidence allowlist')
            payload['evidence/'+p.name] = files.read(path)
    revision = intent['source_commit']
    require(type(revision) is str and re.fullmatch(r'[0-9a-f]{40}', revision), 'source revision required')
    manifest = dict(version=1, sourceRevision=revision, originalRoot=str(files.root),
                    generation=generation, frozenManifestSha256=frozen.manifest_sha256,
                    limits=LIMITS, files={n: sha256(b).hexdigest() for n,b in payload.items()})
    payload['portable-manifest.json'] = canonical(manifest)
    require(len(payload) <= 256 and all(0 < len(b) <= MAX_FILE for b in payload.values())
            and sum(map(len, payload.values())) <= MAX_TOTAL, 'archive budget')
    # Staging stays private and is intentionally retained: no deletion is performed.
    fd, staging = tempfile.mkstemp(prefix='.portable-', suffix='.partial', dir=out.parent)
    with os.fdopen(fd, 'w+b') as stream:
        with zipfile.ZipFile(stream, 'w', compression=zipfile.ZIP_STORED) as archive:
            for n,b in sorted(payload.items()):
                info = zipfile.ZipInfo(n)
                info.create_system = 3
                info.external_attr = (stat.S_IFREG | 0o600) << 16
                archive.writestr(info, b)
        stream.flush(); os.fsync(stream.fileno())
    # Revalidate packaged bytes before atomic no-overwrite publication.
    check = verify(Path(staging), out.parent/('.verify-'+Path(staging).name))
    equal(check.proof['files_checked'], before.proof['files_checked'], 'scope changed')
    equal(check.proof['bytes_checked'], before.proof['bytes_checked'], 'byte scope changed')
    os.link(staging, out, follow_symlinks=False)
    return check


def member_name(name):
    require(type(name) is str and '\\' not in name and ':' not in name and
            not name.startswith('/') and all(p not in ('', '.', '..') for p in name.split('/')),
            'unsafe archive path')
    require(name in FIXED | {'portable-manifest.json'} or
            re.fullmatch('evidence/'+SUFFIX, name), 'archive member outside allowlist')


def verify(archive_path, destination):
    archive_path = lexical_absolute(archive_path)
    real_directory(archive_path.parent)
    dest = lexical_absolute(destination)
    real_directory(dest.parent)
    require(not dest.exists() and not dest.is_symlink(), 'fresh extraction directory required')
    fd = os.open(archive_path, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(fd, 'rb') as stream:
        st = os.fstat(stream.fileno())
        require(stat.S_ISREG(st.st_mode) and 0 < st.st_size <= MAX_TOTAL, 'compressed archive budget')
        with zipfile.ZipFile(stream) as archive:
            infos = archive.infolist()
            require(1 <= len(infos) <= 256, 'archive file count')
            names = [i.filename for i in infos]
            require(len(set(names)) == len(names), 'duplicate member')
            require(sum(i.file_size for i in infos) <= MAX_TOTAL and
                    sum(i.compress_size for i in infos) <= MAX_TOTAL, 'archive byte budget')
            for info in infos:
                member_name(info.filename)
                kind = stat.S_IFMT(info.external_attr >> 16)
                require(kind in (0, stat.S_IFREG) and not info.is_dir(), 'nonregular archive member')
                require(not info.flag_bits & 1 and info.compress_type in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED),
                        'unsupported/encrypted member')
                require(0 < info.file_size <= MAX_FILE and info.compress_size > 0 and
                        info.file_size <= info.compress_size * 200, 'compressed bomb/member bound')
            payload = {}
            for info in infos:
                with archive.open(info) as f:
                    raw = f.read(MAX_FILE+1)
                require(len(raw) == info.file_size, 'member byte bound')
                payload[info.filename] = raw
    manifest = strict_json(payload.pop('portable-manifest.json'))
    require(type(manifest['version']) is int and manifest['version'] == 1, 'manifest version')
    equal(manifest['limits'], LIMITS, 'limits mismatch')
    require(re.fullmatch(r'[0-9a-f]{40}', manifest['sourceRevision']), 'source revision')
    equal(manifest['frozenManifestSha256'], build_frozen_splits_v2().manifest_sha256, 'frozen manifest mismatch')
    equal(manifest['files'], {n:sha256(b).hexdigest() for n,b in payload.items()}, 'manifest hashes mismatch')
    require(FIXED <= payload.keys(), 'missing case metadata')
    original = lexical_absolute(manifest['originalRoot'])
    spec, fixture = validated_case(strict_json(payload['case.json']))
    equal(strict_json(payload['fixture.json']), asdict(fixture), 'fixture mismatch')
    export = export_from_bytes(payload['semantic-export.json'])
    # Ensure ONLY the two declared replay evidence unions are carried.
    expected = set(FIXED)
    for mode in ('faulty', 'fixed'):
        saved = strict_json(payload[mode+'-replay.json'])
        for path in saved['evidencepaths'] + [str(original/(saved['reset_receipt_sha256']+'.reset.json'))]:
            p = lexical_absolute(path)
            require(p.parent == original, 'original flat evidence anchor required')
            expected.add('evidence/'+p.name)
    equal(sorted(payload), sorted(expected), 'unreferenced or missing archive payload')
    dest.mkdir(mode=0o700)
    (dest/'evidence').mkdir(mode=0o700)
    for n,b in {**payload, 'portable-manifest.json': canonical(manifest)}.items():
        fd = os.open(dest/n, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, 'wb') as f: f.write(b)
    return bind(dest, spec, export, fixture, manifest['generation'], original)
