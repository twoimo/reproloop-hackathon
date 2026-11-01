# Fresh reproduction runbook (separately admitted local build)

Status: **runbook, not a result.** Nothing in this file has been executed on a
fresh or independent host. No fresh device run, new AVD or new target is
authorized by this document. Writing it ran no build, ADB, emulator, model or
network call.

Read this together with `docs/REPRODUCTION.md` (source-only archive and offline
checks) and `android/toolchain-lock.json`. Original private build receipts are
not redistributed in the source-only candidate; all required commands are here.

## 1. What this reproduces and what it cannot

A fresh reproduction builds NEW faulty/fixed debug APKs from source, creates a
NEW owned emulator and a NEW empty journal, then replays a developer-authored
four-step export on both builds without a model and asks the independent
state/event oracle for a verdict.

It differs from the original evidence in these ways, all of which must be
stated in any report:

- **Different APK bytes.** `android/build.sh` generates a new local debug key
  when none exists, and zip entries carry build timestamps. A new build has new
  APK SHA-256 values and a different signing certificate. The two original pins
  in `src/reproloop/lab.py` (faulty `5b7e27d2…33df`, fixed `4bcd2374…3cb6`) are
  NOT changed, and the default code path still rejects any other APK before any
  device command.
- **Explicit owner admission.** The new hashes are accepted only when the
  person running the replay declares both of them with `--admit-local-build`.
  That is a trusted-owner declaration that "these are the two builds I just
  made from this source". It is not source, signature, producer or build
  attestation.
- **Developer-authored export.** The export replayed here is the B1-style
  reference script derived from the frozen scenario. It is NOT a reproduction
  of the video -> model -> export step, and a pass says nothing about model
  accuracy.
- **New target, new journal, new generation.** Results cannot be bound to the
  historical receipts, generations or pair ZIPs.
- **Unchanged history.** The original v3 pilot stays 2/5 (below its >=3/5
  goal), the separate v4obs1 FINAL stays 3/3 in one F01 family, the B1 matched
  comparison stays 3/3 vs 3/3 with no superiority claim, and every recorded
  failure and UNKNOWN stays as recorded. A fresh pass adds a separate,
  separately labelled observation; it is never merged into those cohorts.

## 2. Permission required before any device step

The live commands in **section 8 (Step 5: bootstrap)** and **section 10
(Step 7: replay with `--execute-owned`)** create/control an Android emulator.
They require separate, explicit owner authorization naming the new AVD and
serial on that host. The original target's authorization does not extend to a
new one. The private owner approved one separately recorded fresh target for
this session only; that receipt is not authority for another target. Sections 4-7 are offline; section9
initializes local files only, not a device, and must never replace a journal.

Never point these tools at a physical device, an unowned or pre-existing
emulator, or the original operational journal.

## 3. Supported host (the only one documented)

| Item | Requirement |
|---|---|
| OS / CPU | macOS on Apple Silicon (ARM64). Linux, Windows and x86 emulation are not supported (the replay CLI reads `kern.boottime` via `/usr/sbin/sysctl`, and the system image is arm64-v8a). |
| Android SDK | Already installed: `platforms/android-34`, `build-tools/34.0.0`, `platform-tools`, `emulator`, `cmdline-tools/latest`, and `system-images/android-34/google_apis_playstore/arm64-v8a`. |
| JDK | Already installed JDK used for javac/jar/keytool/D8/apksigner. Original evidence used the JetBrains Runtime bundled with Android Studio, JDK 25.0.3. |
| Kotlin | Already installed Kotlin compiler home with `bin/kotlinc` and the three stdlib jars. Original evidence used the Android Studio bundled `kotlinc`, `2.3.20-release-208`. |
| Python | 3.11+ standard library; full offline suite additionally needs preinstalled Pillow 13.0.0. |
| Node | Preinstalled Node for UI tests; original-host observation v26.5.0, other versions unverified. |

**Observed versions, not interchangeable compatibility claims.** The recorded
local toolchain is bundled JDK 25.0.3 and Kotlin 2.3.20-release-208. The six byte
pins and runtime notice jar pins apply to the observed installed binaries.
Other versions/hosts remain unverified; adopting different bytes requires a
separate observed lock and matching notices, not overwriting the original lock.

**No downloading, no license acceptance.** This runbook never runs
`sdkmanager`, never installs packages and never accepts SDK or Google Play
image licenses. If a component is missing, stop: installing it (and accepting
its terms) is the host owner's own separate decision outside this project.

Generic examples of where these usually live on macOS (adjust to your install):

```sh
export ANDROID_SDK_ROOT="$HOME/Library/Android/sdk"
export JAVA_HOME="/Applications/Android Studio.app/Contents/jbr/Contents/Home"
export KOTLIN_HOME="/Applications/Android Studio.app/Contents/plugins/Kotlin/kotlinc"
```

## 4. Step 1: offline source checks (no device)

From the verified source directory:

```sh
python3 tools/check_local.py
```

Report the actual counts you see. Do not copy counts from other documents.

## 5. Step 2: verify installed toolchain bytes (no device)

```sh
python3 android/scripts/verify-toolchain.py
```

- Missing/unset `ANDROID_SDK_ROOT` or `KOTLIN_HOME`, or a missing pinned file,
  prints `TOOLCHAIN CHECK FAILED: ...` and exits 2. Fix the variable; do not
  install anything to make it pass.
- `Tool pin mismatch: NAME` means your installed bytes differ from the observed
  original host. On a different machine this is expected for at least `aapt2`
  (OS/CPU specific). Do not edit `android/toolchain-lock.json`. Either stop, or
  have the owner record a SEPARATE observed lock for that host and label every
  later result as built with a different toolchain. Mixing a mismatched
  toolchain into a "same toolchain" claim is not allowed.

## 6. Step 3: domain checks and build (no device)

```sh
bash android/test-domain.sh
bash android/build.sh
```

`build.sh` now also:

1. Requires `third_party/kotlin-stdlib-notices/` with `SHA256SUMS`,
   `PROVENANCE.md` and every listed notice file present as regular files with
   matching hashes (exactly the reviewed nine entries and pinned manifest). Missing or altered notices fail the
   build with exit 3. There is no fallback.
2. Requires the three Kotlin stdlib jars in `$KOTLIN_HOME/lib` to match the
   pins the notices were copied for, else exit 3.
3. Adds the notice folder to each NEW APK under
   `assets/third_party/kotlin-stdlib-notices/` BEFORE `zipalign` and
   `apksigner`, so the signature covers it, and checks the entries exist in
   both the unsigned and the signed APK.

Record the two printed SHA-256 values:

```sh
shasum -a 256 android/build/pockettasks-faulty-debug.apk android/build/pockettasks-fixed-debug.apk
```

Keep `android/build/debug.keystore` private and local. Never copy, publish or
reuse the original project key, and never commit any key.

Expected warnings recorded on the original host (D8 Kotlin metadata messages,
JDK native-access deprecations, `Bundle.get` deprecations) are not failures by
themselves, and do not prove runtime compatibility.

## 7. Step 4: generate the developer-reference export (no device)

Implemented CLI (compare with `--help`, see section 11):

```sh
python3 tools/emit_reference_export.py \
  --case-id FINAL-C \
  --faulty-sha <FAULTY_SHA_FROM_STEP_3> \
  --fixed-sha <FIXED_SHA_FROM_STEP_3> \
  --out <NEW_PRIVATE_DIR>/final-c-export.json
```

This is pure: no SDK, model or device. The output must not already exist. The
result is a developer-authored B1 reference script, not original video
inference. For the three FINAL cases the export digest is expected to equal the
historically recorded values (FINAL-A `3bbbd8cb…460f`, FINAL-B `86963eb6…06b7`,
FINAL-C `0f2185d9…565d`), because the export does not depend on APK bytes; if
it differs, stop and report it.

## 8. Step 5: create a NEW owned emulator (device step, needs section 2)

Choose a NEW, empty, private runtime root that has never held a bootstrap, and
a NEW AVD name matching `ReproLoop_[A-Za-z0-9_]{4,60}`. Use a free even console
port between 5554 and 5682.

Create that directory exclusively with owner-only permissions first. This
fails if it already exists; do not add `-p`, reuse a directory, or chmod an
existing operational workspace. Replace all angle-bracket placeholders before
executing any command.

```sh
mkdir -m 700 <NEW_RUNTIME_ROOT>
python3 tools/bootstrap_owned_avd.py \
  --state-dir <NEW_RUNTIME_ROOT> \
  --sdk "$ANDROID_SDK_ROOT" \
  --jdk "$JAVA_HOME" \
  --name <NEW_AVD_NAME> \
  --port <EVEN_PORT>
```

It refuses an existing receipt or AVD path, launches headless, waits for boot,
records the guest boot ID and writes an owner marker. It preserves the
prelaunch config pin as `created_config_sha256` and computes `config_sha256`
AFTER verified boot/owner readback, because the trusted emulator can normalize
spacing and finalize its data-partition size during first boot. Success prints
`"phase": "READY"` with the serial (`emulator-<EVEN_PORT>`). Any other phase
(`LAUNCH_EXITED`, `BOOT_UNKNOWN`) means stop and inspect the owned
`emulator.log`; do not relaunch into the same state directory.

After any emulator or host restart the recorded boot ID no longer matches and
that state directory cannot be reused. A new state directory and AVD (and a new
authorization) are needed. Do not edit `bootstrap.json` to make it match.

## 9. Step 6: initialize the NEW journal (no device)

Implemented CLI (compare with `--help`):

```sh
# Preview (default): writes nothing, calls no device.
python3 tools/init_owned_journal.py \
  --runtime-root <NEW_RUNTIME_ROOT> \
  --expected-avd <NEW_AVD_NAME> \
  --expected-serial emulator-<EVEN_PORT>

# Only after the preview is clean:
python3 tools/init_owned_journal.py \
  --runtime-root <NEW_RUNTIME_ROOT> \
  --expected-avd <NEW_AVD_NAME> \
  --expected-serial emulator-<EVEN_PORT> \
  --execute-init
```

Implemented source behavior (offline tests; not fresh-device acceptance): it requires a `READY` bootstrap for that exact
AVD/serial inside the same runtime root, refuses any existing journal, init
receipt or lock (even an empty one), creates exactly one new empty
`runtime.sqlite` and records STARTED/COMPLETED receipts. It does not copy,
reset or replace a journal and makes no ADB call. If it stops partway, keep
every file, reconcile read-only, and do not retry under a new name in the same
root. Never pass the original operational journal's directory to it.

Optional host smoke (device step): `tools/native_smoke.py` still uses a fixed
adb location and is not required by this runbook.

## 10. Step 7: dry run, then the admitted paired replay

Dry run first (default; no device action):

```sh
python3 tools/replay_owned_case.py \
  --runtime-root <NEW_RUNTIME_ROOT> \
  --apk-root android/build \
  --export <NEW_PRIVATE_DIR>/final-c-export.json \
  --out <NEW_PRIVATE_DIR>/fresh-final-c-run \
  --case-id FINAL-C \
  --run-id <STABLE_RUN_ID> \
  --expected-avd <NEW_AVD_NAME> \
  --expected-serial emulator-<EVEN_PORT> \
  --source-revision <40_HEX_SOURCE_COMMIT_YOU_BUILT> \
  --admit-local-build <FAULTY_SHA> <FIXED_SHA> \
  --adb "$ANDROID_SDK_ROOT/platform-tools/adb"
```

Check the printed plan: generation (expected 1 for a newly initialized
journal), export digest, both build hashes and the admission label. The two
admitted hashes must equal the actual APK files; they must be different
lowercase 64-hex values in faulty-then-fixed order. Without
`--admit-local-build`, a fresh build is expected to be REJECTED (original pins
only); that rejection is correct behaviour, not a bug.

Then, only with the section 2 authorization in hand, rerun the same command
with `--execute-owned` added. `--out` must be a new path every time; an
existing `--out` is refused. Exit 0 with `"status": "CONFIRMED"` means the
oracle confirmed the faulty/fixed pair for this fresh build. Exit 2 /
`INCOMPLETE_NO_RETRY` means stop and inspect; never rerun into the same `--out`
or rewrite the journal.

## 11. Parent reconciliation required

The three commands in sections 7, 9 and 10 (`emit_reference_export.py`,
`init_owned_journal.py`, and the new `replay_owned_case.py` options
`--admit-local-build` / `--adb`) are being implemented concurrently by the
parent owner. The options above follow the parent's planned interface at the
time of writing. **Before release, reconcile every command line in this file
with the final `--help` output** and update the text; do not trust this file
over the code.

## 12. What to record from a fresh run

- Host: macOS version, chip, and whether it is a genuinely different machine
  from the original host (the parent's own fresh build was on the SAME Mac and
  is not independent).
- Toolchain check output (pass, or which pin differed).
- Build output tail, the two APK hashes, `apksigner verify` result, and a
  listing of `assets/third_party/kotlin-stdlib-notices/` in each APK.
- Bootstrap phase, AVD name and serial (as authorized), init receipts.
- Dry-run plan JSON, then `summary.json` and every failure, unedited.
- The authorization reference for the new target.

Do not claim: fresh-machine reproduction unless the host really was different;
model or video accuracy; producer/OS attestation; physical-touch proof; or any
change to the original cohorts.

## 13. Limits

- Unexecuted runbook. No part of it has been run end to end on a fresh or
  different host.
- Command options for the parent's new tools may change; see section 11.
- The notice folder covers only the Kotlin runtime embedded in the APK; other
  prerequisites and media are covered in `THIRD_PARTY_NOTICES.md` and are not
  legally cleared.
- The owner selected MIT for project-owned source; see root LICENSE.
  Third-party/material rights and public/binary release remain separate holds.

## Trust and API boundary

Initialization provenance is enforced by the standalone replay CLI. Direct
trusted `OwnedLab` callers retain their older auto-creating-journal contract;
they are not a supported substitute for this fresh-runbook admission path.
Completion metadata is not historical rollback protection or OS attestation.
The initial DB hash is a record of initialization, not a frozen hash to enforce
after legitimate runtime history has been appended.

## First-use Android system UI

A new emulator can show "Viewing full screen" / "Got it" after the first app
launch. It belongs to package android, not the fixture. The app-only validator
correctly stops; do not weaken it, disable system/security settings or count
the failed control as completed. The owner may separately acknowledge this
non-permission help outside the measured app flow, or explicitly authorize an
exact setup acknowledgment. Any extra replay attempt must retain the failure,
use a new run/generation on the SAME journal and have exact retry authority.
See evaluation/FRESH_SETUP_REFERENCE_v1.md for the actual incomplete attempt.

The later separately approved v2 continuation is recorded in
`evaluation/FRESH_SETUP_REFERENCE_v2.md`; the original v1 failure remains.
A private successful run is not new-target or extra-retry authority for a
reader of this runbook, nor evidence of a clean independent-machine setup.

## Read-only observation from a prospective different host

On an already authorized host, without downloads, installations or device work:

```sh
python3 android/scripts/verify-toolchain.py --record-observed <NEW_PRIVATE_REPORT.json>
```

Set the usual existing ANDROID_SDK_ROOT/KOTLIN_HOME; JAVA_HOME adds an optional
version observation. The report records six observed file hashes, limited
version/OS/CPU metadata and the original lock digest. It excludes environment
dumps and private home paths. It does NOT execute SDK/JDK binaries, make network
requests, choose a target, accept licenses, adopt pins or prove independence.
The file must be new; no report overwrite/symlink-parent traversal is accepted.

A mismatch still exits1 and records original_six_pins_match=false; missing files
or variables still exit2. Saving a report is not a green preflight. Preserve
the original android/toolchain-lock.json. Bring the report and actual different-
host identity/access scope to the owner for a separate compatibility/admission
decision. Do not copy it over the original lock or call it a successful replay.
