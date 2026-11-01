# Offline reproduction and source-package boundaries

The source-only candidate and media-complete PUBLIC preparation are separate
outputs. This guide retains the source-only workflow below; the PUBLIC copy
also ships the fixed recorded catalog, not raw private runs or Git history.
A package is not evidence of publication or submission. The packaged v2 import
is `ui/fixtures/recorded-case.json`; excluded historical evidence paths are
private archive identifiers, not required public inputs.

## Supported offline check

Use Python 3.11+, Node and Pillow 13.0.0 already installed on a trusted local
machine for the FULL suite. No package installation, network, credentials,
model or device is performed by the following command:

```sh
python3 tools/check_local.py
```

This entry point discovers each non-package Python test directory, then runs
73 Node DOM/adapter/recorded-media tests in the current workbench candidate. The post-submission R-UI-01 correction adds six same-case retry regressions: two hash outcomes in each of three slots. A missing Node is a failure, not a silent UI skip.
Pillow is optional for some runtime paths, but tests/video_frames/test_video_frames.py
imports it unconditionally: absent Pillow FAILS full checks, not a skip. The one
optional skip requires an explicitly supplied owned MP4 and is separate. Report
actual output rather than importing the private repository's historical count.
Never execute untrusted source archives; hashes are integrity, not authorship.

## Build and verify the separate source candidate

From a trusted checkout containing all whitelisted source files:

```sh
python3 tools/release_candidate.py --out candidate.zip
python3 tools/release_candidate.py --verify candidate.zip --extract-to clean-source
cd clean-source
python3 tools/check_local.py
```

Output/extraction destinations must not exist; use exclusively owned private
parents. Output is deterministic stored ZIP with fixed timestamps/modes and
sorted relative-path SHA-256/size manifest. No overwrite, symlinks, traversal,
unknown members, binary payloads, credential patterns or personal host paths
are accepted. Scan failure stops packaging rather than mutating source. The
manifest covers every emitted payload; it cannot cover its own bytes and is
not a signature. Do not run the full checker on an extracted source directory
before verification. Builder/verifier trust depends on trusted local code.

Source coverage deliberately excludes review_tools, internal evidence/reviews,
original documentation, actual media/raw model output, APKs, operational data,
UI host-bundling scripts and the evaluation test module containing a private
host-path dependency. Runtime/evaluation source and remaining synthetic tests
are unchanged, not broadly redacted. Package tests exercise only synthetic data.
The candidate is a subset: a green subset is NOT a green full private checkout.

### Session-identity privacy correction

The source allowlist additionally EXCLUDES these unchanged private files:

* tools/run_live_case.py and tools/run_matched_baseline.py: orchestration bound
  to the original task's actual target/session.
* tools/run_dev_baseline.py and tools/run_dev_cua.py: task-specific DEV launchers,
  not needed by the generic explicit-target replay interface.
* tests/live_pipeline/test_run_live_case.py (19 tests) and
  tests/evaluation/test_matched_baseline.py (5 tests): import excluded launchers.
* tests/video/test_video.py (33 tests, including the optional owned-MP4 skip):
  contains a serial also used by the original live target; source is not redacted.

Thus 57 tests present in the prior allowlist are omitted; their behavior is NOT
claimed validated by the new subset. This is in addition to the older full
private evaluation/review and UI-host-bundler exclusions. The allowlist adds
unchanged tools/replay_owned_case.py and tests/portable/test_replay_owned_cli.py
(9 synthetic planning tests), plus three new candidate privacy regressions.

The generic CLI requires trusted caller-provided --expected-avd/--expected-serial,
canonical export/case binding, an EXISTING owned journal and a fresh generation.
It does not discover the original target or depend on API/key/MetaLedger. Its
planning tests use only temporary synthetic journals, not operational data.
Do not invoke --execute-owned without separately verified target/action authority.

The scanner rejects a bounded ASCII dated-session AVD class: the project prefix,
a 1-60 character alphanumeric/underscore/hyphen component, underscore, and eight
digits. Tests generate an explicitly synthetic distant-date identity, rather
than inserting or hiding an actual session name in released source. Rehashing
a contaminated archive does not bypass the rejection. No live owner/serial is
embedded as a scanner denylist. Generic synthetic emulator serial fixtures remain;
a serial alone is not an authentication secret. The previous split owner-specific
name rule was replaced by the structural class, not a claim to identify arbitrary
bare usernames. The separate private post-build check searches every emitted
member for the known live identity literals; it is not included in public source.

Coverage is bounded: regex/literal checks cannot prove absence of all PII,
encoded identifiers, arbitrary session naming schemes or secrets. Selected UTF-8
source bytes remain EXACT, not broad-redaction derivatives. Original private
receipts, source pins and native artifact hashes are neither rewritten nor
presented as sanitized proof. The parent's later integrated/frozen build must
repeat manifest closure, privacy checks and the actual subset checker.

A source-only archive does not sanitize Git history. Making the existing private
repository public would expose historical identifiers/host paths even if the
current tree is clean. Any future public repository requires fresh sanitized
history, explicit owner release authorization and outstanding license decisions;
this builder does not flip repository visibility or rewrite history.

## Android build and fresh reproduction are external prerequisites

No Android/toolchain build, ADB, emulator, native runner or provider call is
performed by candidate generation, verification or the offline checker.
Installations and external execution require separate authority/setup.

For a future owner-controlled build, obtain the exact toolchain described in
android/toolchain-lock.json, set ANDROID_SDK_ROOT, JAVA_HOME and KOTLIN_HOME to
local installed directories, then inspect/run:

```sh
python3 android/scripts/verify-toolchain.py
bash android/test-domain.sh
bash android/build.sh
```

The lock lists observed installed byte hashes, not publisher signatures or
portable download instructions. Debug keys are generated locally; APK hashes
need not match another build. They are NOT silently admitted: the default
retains the original pins. Explicit owner-admitted local build, one-time fresh
journal initialization and pure B1 reference export commands are documented in
`docs/FRESH_REPRODUCTION.md`. These source paths have offline tests, not a new
independent-host/native acceptance. Compiler/D8 compatibility and runtime behavior
must be checked on an actually dedicated owned AVD. No such action ran here.

Actual fresh faulty/fixed reproduction additionally needs fresh owned target
admission, distinct verified APK installs, fixed case/fixture and same semantic
export, independent persisted-state/event oracle, zero-model replay and full
original private evidence closure. This source-only archive has none of those
execution artifacts. It cannot replay the original pair by itself. Existing
private portable pair ZIPs retain original absolute paths and raw identities;
do NOT relabel or publish them as sanitized. Never rewrite frozen receipts to
claim their new bytes retain original hashes/proof. The viewing assets are
presentation derivatives, not the full raw proof chain.

## Actual bounded environment result (this source snapshot)

Existing host: Python 3.13.12, Node v26.5.0, Pillow 13.0.0. A brand-new source
extraction ran 412 Python tests (one owned-MP4 optional skip) and 34/34 Node
tests. Full original checkout ran 465 Python tests (one skip), plus 34/34 Node.

A new no-pip virtual environment from the actual base interpreter, without
system site packages, ran 396 tests: one module-import error (PIL absent), one
owned-MP4 skip. At that observation, package-free full reproduction was BLOCKED
on missing Pillow 13.0.0; no dependency had been installed. Node independently
passed 34/34. This initial failure is retained, not replaced by the follow-up.
The initial nested-host-interpreter venv could not import encodings; the base
interpreter venv booted correctly and exposed the real Pillow dependency.
No Android build or fresh emulator reproduction ran in either environment.

## Controlled isolated-environment follow-up

The owner subsequently supplied the exact pinned wheel, downloaded by the parent
from official PyPI. This worker made no network call. Wheel:
`pillow-13.0.0-cp313-cp313-macosx_11_0_arm64.whl`, SHA-256:
`f11a3c1358bb3c68012a7b1f41b223c3db9f7bfde90b481df028cfe1c3363313`.
This wheel is CPython 3.13/macOS ARM64-specific, not a universal prerequisite.
The wheel is kept separately as a private prerequisite, not added to the source
candidate or granted public redistribution clearance.

A NEW venv from the previously verified actual base interpreter used Python
3.13.12, no system site packages and disabled user site packages. Bundled
`ensurepip` installed pip 25.3 locally; `--no-index --no-deps` installed ONLY the
supplied Pillow 13.0.0 wheel. Installed distributions were exactly pip and Pillow;
PIL's loaded module path was inside that venv. No global package changed.

A fresh verified extraction of the ORIGINAL candidate (code baseline plus
`70dc3d167fb68fb6751904a5b62d7f390adea423`) ran all 11 Python suites:
**412 tests run, zero failures/errors, one owned-MP4 skip**. Node v26.5.0 passed
**34/34, zero failures/skips/cancellations/todos**. The run summary, per-suite
counts/status and Node semantic fields were checked, not merely process exit.
The missing-Pillow prerequisite is RESOLVED for this controlled environment.
This is not a clean Android machine, native reproduction, human setup read-through,
new final integrated source snapshot, project license or release approval.

The tested original candidate ZIP SHA-256 remains:
`10638bd45283a238c1aa71b9f8f62092bebe47c52eb4160d04305293757be437`.
It was not overwritten to incorporate this documentation follow-up. The parent
owns rebuilding and verifying the later integrated final candidate.

### Equivalent exact offline commands with caller-owned relative locations

Before these commands, set `BASE_PYTHON` to the verified actual base interpreter;
do not infer it from a nested host venv's misleading `sys._base_executable`.
Place the supplied wheel in `dependencies/` and the original archive at
`candidate.zip`. Use brand-new `clean-venv` and `clean-source` destinations.
From a trusted source checkout, verify the wheel bytes first:

```sh
python3 - <<'PYCODE'
from hashlib import sha256
from pathlib import Path
wheel = Path('dependencies/pillow-13.0.0-cp313-cp313-macosx_11_0_arm64.whl')
assert not wheel.is_symlink()
assert sha256(wheel.read_bytes()).hexdigest() == 'f11a3c1358bb3c68012a7b1f41b223c3db9f7bfde90b481df028cfe1c3363313'
PYCODE
"${BASE_PYTHON:?Set verified actual base interpreter}" -m venv --without-pip clean-venv
clean-venv/bin/python -m ensurepip --default-pip
clean-venv/bin/python -m pip --isolated --disable-pip-version-check install --no-index --no-deps dependencies/pillow-13.0.0-cp313-cp313-macosx_11_0_arm64.whl
python3 tools/release_candidate.py --verify candidate.zip --extract-to clean-source
(cd clean-source && env -u PYTHONPATH -u PYTHONHOME -u REPROLOOP_TEST_OWNED_MP4 PYTHONNOUSERSITE=1 ../clean-venv/bin/python tools/check_local.py)
```

The local prerequisite install above was explicitly authorized for this isolated
verification. It is not authority to fetch other wheels, upgrade packages, install
globally, or distribute the supplied wheel. Node was an existing host executable,
not newly installed or an independently clean OS prerequisite.


### Observed privacy-corrected subset (provisional concurrent-work snapshot)

The corrected allowlist emitted 106 payload files plus its manifest. A fresh
verified extraction using the already prepared isolated Python 3.13.12/Pillow
13.0.0 environment ran **383 Python tests across 11 suites, zero failures/errors
or skips**, and existing Node v26.5.0 passed **34/34, zero failures/skips/
cancellations/todos**. This includes 25 candidate boundary tests and nine generic
replay-planning tests. The owned-MP4 optional skip is NOT PRESENT because its
33-test module was excluded; zero skips is not additional native coverage.

Every emitted UTF-8 payload member (including manifest) was inspected for the
provided known original session/serial/account-owner literals: zero matches.
The generic dated-session class check also found no concrete matching identity;
synthetic generic serial fixtures remain. Existing whitelist source bytes were
copied unchanged and full manifest hash/size/file-set closure was verified.

These are provisional artifact-bound observations made while parent-owned UI,
claim bindings, demo and private baseline work could still change. They are NOT
acceptance of the parent's final source or inherited external-review approval.
The private receipt records the tested archive and file hashes. Documentation
observations do not alter original raw/native receipts, source pins or hashes.

## Private offline single-root history preparation

A source ZIP verified by `tools/release_candidate.py` can seed a separate local
Git repository and offline bundle without copying `.git` or any original refs.
Verify one root/commit, exact manifest/blob closure and offline clone equality.
Any synthetic transport-commit identity is not an authorship certification;
root LICENSE retains owner-selected attribution. No remote is configured in the
prepared repository and no existing private history is rewritten. Keep this
candidate private: bounded allowlisting/scanning is not a universal privacy
guarantee, media/binary inclusion, independent host test or release authority.
