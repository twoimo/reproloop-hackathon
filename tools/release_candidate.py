#!/usr/bin/env python3
"""Private source-only preparation. Never changes or packages execution receipts.

Integrity is not authorship, licensing clearance, native reproduction or release.
Use private, exclusively owned source/output parents (not adversarial concurrent writers).
"""
from pathlib import Path, PurePosixPath
import argparse
import hashlib
import json
import os
import re
import stat
import tempfile
import zipfile

WHITELIST = (
    'tools/public_release.py',
    'tests/portable/test_public_release.py',
    'docs/PUBLIC_RELEASE.md',
    'tests/portable/test_demo_render_safety.py',
    'tests/portable/test_toolchain_observation.py',
    'docs/NOVICE_DEMO_REVIEW.md',
    'docs/NOVICE_DEMO_OBSERVER_GUIDE.md',
    'LICENSE',
    'docs/evaluation/FRESH_SETUP_REFERENCE_v1.md',
    'docs/evaluation/FRESH_SETUP_REFERENCE_v2.md',
    'src/reproloop/reference.py',
    'tools/init_owned_journal.py',
    'tools/emit_reference_export.py',
    'tests/portable/test_fresh_setup.py',
    'docs/FRESH_REPRODUCTION.md',
    'docs/NOVICE_REVIEW.md',
    'third_party/kotlin-stdlib-notices/PROVENANCE.md',
    'third_party/kotlin-stdlib-notices/SHA256SUMS',
    'third_party/kotlin-stdlib-notices/license/COPYRIGHT.txt',
    'third_party/kotlin-stdlib-notices/license/COPYRIGHT_HEADER.txt',
    'third_party/kotlin-stdlib-notices/license/LICENSE.txt',
    'third_party/kotlin-stdlib-notices/license/NOTICE.txt',
    'third_party/kotlin-stdlib-notices/license/README.md',
    'third_party/kotlin-stdlib-notices/license/third_party/boost_LICENSE.txt',
    'third_party/kotlin-stdlib-notices/license/third_party/guava_license.txt',
    'third_party/kotlin-stdlib-notices/license/third_party/gwt_license.txt',
    'third_party/kotlin-stdlib-notices/license/third_party/threetenbp_license.txt',

    'NEW_WORK.md',
    'docs/CURRENT_STATUS.md',
    'docs/FAULT_COVERAGE.md',
    'tests/faults/test_fault_boundaries.py',
    'demo/README.md',
    'demo/REHEARSAL.md',
    'demo/ReproLoop_180s.srt',
    'demo/STORYBOARD.md',
    'demo/capture-manifest.json',
    'demo/ffprobe-validation.json',
    'demo/generation-manifest.json',
    'demo/render.py',
    'demo/safe-aggregates.json',
    'demo/safe-evidence.json',
    'demo/source-manifest.json',
    'demo/storyboard.json',
    'THIRD_PARTY_NOTICES.md',
    'android/AndroidManifest.xml',
    'android/build.sh',
    'android/event.schema.json',
    'android/res/values/ids.xml',
    'android/scripts/verify-toolchain.py',
    'android/src/com/tinyburn/reproloop/lab/Domain.kt',
    'android/src/com/tinyburn/reproloop/lab/MainActivity.kt',
    'android/state.schema.json',
    'android/test-domain.sh',
    'android/tests/DomainChecks.kt',
    'android/toolchain-lock.json',
    'docs/RELEASE_READINESS.md',
    'docs/REPRODUCTION.md',
    'evaluation/__init__.py',
    'evaluation/cli.py',
    'evaluation/complexity_bench.py',
    'evaluation/formal_model.py',
    'evaluation/improvement_loop.py',
    'evaluation/ledger.py',
    'evaluation/splits.py',
    'evaluation/stats.py',
    'examples/evaluation_metrics.py',
    'examples/meta_protocol.py',
    'examples/replay_contracts.py',
    'examples/repro_oracle.py',
    'examples/test_evaluation_metrics.py',
    'examples/test_meta_protocol.py',
    'examples/test_replay_contracts.py',
    'examples/test_repro_oracle.py',
    'pyproject.toml',
    'requirements-video.txt',
    'src/reproloop/__init__.py',
    'src/reproloop/explore.py',
    'src/reproloop/host.py',
    'src/reproloop/lab.py',
    'src/reproloop/meta/client.py',
    'src/reproloop/meta/gateway.py',
    'src/reproloop/meta/ledger.py',
    'src/reproloop/pair_binding.py',
    'src/reproloop/portable.py',
    'src/reproloop/replay.py',
    'src/reproloop/runtime/app_state.py',
    'src/reproloop/runtime/driver.py',
    'src/reproloop/runtime/owned.py',
    'src/reproloop/video.py',
    'src/reproloop/video_frames.py',
    'tests/explore/test_explore.py',
    'tests/explore/test_observation_turn.py',
    'tests/explore/test_video_goal.py',
    'tests/host/test_host.py',
    'tests/host/test_local_checks.py',
    'tests/lab/test_lab.py',
    'tests/meta/test_ipc.py',
    'tests/meta/test_meta.py',
    'tests/pair/test_pair_binding.py',
    'tests/portable/test_portable.py',
    'tests/portable/test_replay_owned_cli.py',
    'tests/portable/test_release_candidate.py',
    'tests/runtime/test_app_state.py',
    'tests/runtime/test_audit_regressions.py',
    'tests/runtime/test_capture_stability.py',
    'tests/runtime/test_repair.py',
    'tests/runtime/test_runtime.py',
    'tests/video/test_ocr_grounding.py',
    'tests/video/test_request_envelope.py',
    'tests/video/test_v4_contract.py',
    'tests/video_frames/test_context_grounding.py',
    'tests/video_frames/test_ocr_context.py',
    'tests/video_frames/test_video_frames.py',
    'third_party/hallmark/LICENSE',
    'third_party/hallmark/PROVENANCE.md',
    'third_party/hallmark/references/terminal.md',
    'third_party/hallmark/scripts/sloplint.mjs',
    'tools/bootstrap_owned_avd.py',
    'tools/check_local.py',
    'tools/package_workbench.py',
    'tests/portable/test_workbench_package.py',
    'docs/design/product-workbench.md',
    'tools/inspect_video.swift',
    'tools/meta_smoke.py',
    'tools/native_smoke.py',
    'tools/ocr_video_frames.swift',
    'tools/package_live_pair.py',
    'tools/replay_owned_case.py',
    'tools/release_candidate.py',
    'ui/README.md',
    'ui/recorded-demo.js',
    'ui/recorded-demo.test.mjs',
    'ui/fixtures/recorded-case.json',
    'ui/fixtures/recorded-assets.json',
    'ui/adapter.js',
    'ui/adapter.test.mjs',
    'ui/app.js',
    'ui/console.css',
    'ui/dom.test.mjs',
    'ui/fixtures/synthetic-illustration.json',
    'ui/index.html',
    'ui/package.json',
    'ui/scripts/build-host-bundle.py',
    'ui/scripts/test-build-host-bundle.py',
)

README = b"""# ReproLoop source-only candidate (PRIVATE)

Not published. Owner-selected MIT covers ReproLoop-owned source: see LICENSE.
Third-party licenses, material rights and release holds: THIRD_PARTY_NOTICES.md.
Offline synthetic/boundary checks: python3 tools/check_local.py
Python 3.11+, Node and preinstalled Pillow 13.0.0 are needed for the full suite.
No package installation is performed by this builder or checker.
Read docs/CURRENT_STATUS.md, docs/REPRODUCTION.md, docs/FRESH_REPRODUCTION.md
and docs/RELEASE_READINESS.md
before any other action.
No APKs, media binaries, original receipts, raw provider output, databases or review votes
are included. Derived recorded-example metadata stays UNVERIFIED; media is separate.
This is NOT a complete saved-pair replay or Android reproduction.
"""
GENERATED = {"README.md": README}
MANIFEST = "source-manifest.json"
MAX_FILE = 2 * 1024 * 1024
MAX_TOTAL = 32 * 1024 * 1024
# Bounded classes, not an exhaustive secret detector. Session identities are
# rejected by structure; never insert actual owner/session/serial values here.
PATTERNS = (
    re.compile(r"/(?:" + "Users|home" + r")/[^\s\"']+"),
    re.compile(r"[A-Za-z]:\\(?:Users|Documents)\\"),
    re.compile(r"[A-Za-z0-9._%+-]+" + "@" + r"[A-Za-z0-9.-]+\.[A-Za-z]{2,}"),
    re.compile("BEGIN " + r"(?:RSA |EC |OPENSSH )?PRIVATE KEY"),
    re.compile("sk" + r"-(?:proj-)?[A-Za-z0-9_-]{20,}"),
    re.compile("AI" + r"za[A-Za-z0-9_-]{30,}"),
    re.compile(r"(?i)(?:bearer\s+|api_key\s*[:=]\s*['\"])[A-Za-z0-9_-]{20,}"),
    re.compile(r"(?i)\bReproLoop_[A-Za-z0-9][A-Za-z0-9_-]{0,59}_[0-9]{8}\b"),
)


def canonical(value):
    return (json.dumps(value, sort_keys=True, indent=2, ensure_ascii=True) + "\n").encode()


def member_name(name):
    if (not isinstance(name, str) or not name or "\\" in name or ":" in name
            or "\x00" in name or name.startswith("/")
            or any(p in ("", ".", "..") for p in name.split("/"))
            or str(PurePosixPath(name)) != name):
        raise ValueError("unsafe relative member")
    return name


def scan(name, data):
    member_name(name)
    if len(data) > MAX_FILE:
        raise ValueError("file size limit: " + name)
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        raise ValueError("non-text payload: " + name) from None
    if "\x00" in text or any(pattern.search(text) for pattern in PATTERNS):
        # Never echo matched private bytes or an absolute source path.
        raise ValueError("privacy scan rejected: " + name)


def read_source(root, name):
    current = root
    for part in member_name(name).split("/"):
        current = current / part
        if current.is_symlink():
            raise ValueError("source symlink: " + name)
    if not stat.S_ISREG(current.stat().st_mode):
        raise ValueError("source nonregular: " + name)
    if current.stat().st_size > MAX_FILE:
        raise ValueError("file size limit: " + name)
    data = current.read_bytes()
    scan(name, data)
    return data


def source_payload(root):
    root = Path(root)
    if root.is_symlink() or not root.is_dir():
        raise ValueError("source root must be a real directory")
    # Reject symlink ancestors before resolving, including the supplied root.
    if any(p.is_symlink() for p in (root, *root.parents)):
        raise ValueError("source root symlink ancestor")
    payload = {name: read_source(root, name) for name in WHITELIST}
    payload.update(GENERATED)
    return payload


def manifest_for(payload):
    return {"schema": 1, "kind": "PRIVATE_SOURCE_ONLY_CANDIDATE",
            "project_license": "MIT",
            "project_license_scope": "REPROLOOP_OWNED_SOURCE_ONLY",
            "public_release_approved": False,
            "execution_evidence": False,
            "files": [{"path": name, "size": len(data),
                       "sha256": hashlib.sha256(data).hexdigest()}
                      for name, data in sorted(payload.items())]}


def build(root, output):
    output = Path(output)
    if any(p.is_symlink() for p in (output.parent, *output.parent.parents)):
        raise ValueError("output symlink ancestor")
    if output.exists() or output.is_symlink():
        raise ValueError("output already exists")
    payload = source_payload(root)
    if sum(map(len, payload.values())) > MAX_TOTAL:
        raise ValueError("total size limit")
    payload[MANIFEST] = canonical(manifest_for(payload))
    # Stage privately; publish only complete locally verified bytes, no overwrite.
    fd, tmp = tempfile.mkstemp(prefix=".candidate-", suffix=".partial", dir=output.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            with zipfile.ZipFile(stream, "w", compression=zipfile.ZIP_STORED) as archive:
                for name, data in sorted(payload.items()):
                    info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
                    info.create_system = 3
                    info.external_attr = (stat.S_IFREG | 0o600) << 16
                    archive.writestr(info, data)
        verify(tmp)
        os.link(tmp, output)
    finally:
        os.unlink(tmp)
    return len(payload) - 1


def verify(archive_path, extract_to=None):
    expected = set(WHITELIST) | set(GENERATED) | {MANIFEST}
    if Path(archive_path).stat().st_size > MAX_TOTAL:
        raise ValueError("archive size limit")
    with zipfile.ZipFile(archive_path) as archive:
        entries = archive.infolist()
        names = [member_name(i.filename) for i in entries]
        if len(names) != len(set(names)) or set(names) != expected:
            raise ValueError("duplicate or unexpected/missing members")
        total = 0
        for info in entries:
            if (info.flag_bits & 1 or info.compress_type != zipfile.ZIP_STORED
                    or stat.S_IFMT(info.external_attr >> 16) != stat.S_IFREG
                    or info.file_size > MAX_FILE):
                raise ValueError("unsupported archive member")
            total += info.file_size
        if total > MAX_TOTAL:
            raise ValueError("total size limit")
        payload = {name: archive.read(name) for name in names}
    for name, data in payload.items():
        scan(name, data)
    raw_manifest = payload.pop(MANIFEST)
    # Canonical bytes enforce exact schema, unique paths, hashes and full closure.
    if raw_manifest != canonical(manifest_for(payload)):
        raise ValueError("manifest mismatch")
    for name, data in GENERATED.items():
        if payload[name] != data:
            raise ValueError("generated document mismatch")
    if extract_to is not None:
        dest = Path(extract_to)
        if any(p.is_symlink() for p in (dest, *dest.parents)):
            raise ValueError("extraction symlink ancestor")
        dest.mkdir(mode=0o700, parents=False, exist_ok=False)
        for name, data in sorted({**payload, MANIFEST: raw_manifest}.items()):
            target = dest / name
            target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            with target.open("xb") as stream:
                stream.write(data)
            target.chmod(0o600)
        actual = {p.relative_to(dest).as_posix() for p in dest.rglob("*") if p.is_file()}
        if actual != expected:
            raise ValueError("extraction set mismatch")
        for name, data in {**payload, MANIFEST: raw_manifest}.items():
            if read_source(dest, name) != data:
                raise ValueError("extraction bytes mismatch")
    return len(payload)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=Path(__file__).resolve().parents[1])
    choice = parser.add_mutually_exclusive_group(required=True)
    choice.add_argument("--out", type=Path)
    choice.add_argument("--verify", type=Path)
    parser.add_argument("--extract-to", type=Path)
    args = parser.parse_args()
    if args.extract_to and not args.verify:
        parser.error("--extract-to requires --verify")
    try:
        count = verify(args.verify, args.extract_to) if args.verify else build(args.source, args.out)
    except (ValueError, OSError, zipfile.BadZipFile) as exc:
        # OS errors can contain private host paths; expose only the error class.
        parser.exit(1, (str(exc) if isinstance(exc, ValueError) else type(exc).__name__) + "\n")
    print(f"PRIVATE source-only candidate: {count} payload files verified; NOT native reproduction or release")


if __name__ == "__main__":
    main()
