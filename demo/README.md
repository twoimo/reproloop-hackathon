# Recorded demo and submission artifact roles

This is a presentation redesign of the existing recorded demo, **not a new experiment**. Frost `#EEF3F8`, white `#FFFFFF`, ink `#10233F` and cobalt `#245CEC`, with amber/rose evidence accents, match the product workbench. Installed Arial/Arial Bold remain the only fonts. The binary film is delivered separately, not committed as source. Preparation does not itself publish it.

## Current delivered film roles, observed 2026-11-01

The current master is fully encoded and decoded, not a pending render. The
master was produced with renderer source `7a6d594` and the UI capture source `c572f75`;
later corrective source does not retroactively change those provenance facts.

| Role | Duration / frames | SHA-256 |
| --- | --- | --- |
| Preserved master | 180.000000 s /4320 | `8dbb45ab3f48d4c5644668889ebc0ab98c8ac4ebf968713fa62f87fd9c5dc2ab` |
| Prepared YouTube upload derivative | 179.958333 s /4319 | `2be767355d2ee1d597501d91ff7fab6d33cd80d858b0bffce6526c567f32bbfc` |

Both are 1920 x 1080, 24 fps, silent H.264 and fully decoded successfully. The
upload derivative removes only the last exactly repeated whole-RGB frame
and is newly encoded, not source-byte identical. No content-bearing frame,
new experiment, Meta call or device execution was added. The original master
and its 49 inventoried payloads plus self-excluded distribution manifest remain
unchanged. The upload derivative is a separate 3-file delivery, not a replacement
inside that original 50-file inventory. YouTube re-encodes uploaded video;
its served stream is not claimed byte-identical to either local file.

The 23 actual segment midpoint samples and two full-resolution details were
visually inspected. This is not a claim of manually watching all 4320 frames.
Source-video coverage was separately 262 decoded frames: 184 directly inspected
and 78 exact whole-RGB duplicate expansions; this is not independent capture
corroboration. No unreviewed source frame remains after that exact expansion.

The generated `demo/generation-manifest.json`, `demo/ffprobe-validation.json`
and `demo/REHEARSAL.md` retained in the source tree are **historical artifacts**,
not current-master manifests. Their 4c625561/d4df6737 hashes must not identify
the current 8dbb45ab/2be76735 deliveries. The current distribution/probe records
belong to those delivered film artifacts; no raw private receipt is shipped.
Publication and final contest acceptance require their own remote receipts.

## Local render

Use the existing Python/Pillow and installed ffmpeg/ffprobe. No installs, TTS, audio, model/device calls, network, credentials or paid APIs are used.

```sh
test ! -e "$SESSION/tmp/demo-presentation-new"
test ! -e "$SESSION/artifacts/ReproLoop_Demo_presentation_new"
python3 demo/render.py --session "$SESSION" \
  --scratch "$SESSION/tmp/demo-presentation-new" \
  --out "$SESSION/artifacts/ReproLoop_Demo_presentation_new"
```

`SESSION` points to the task directory containing the original FINAL-C safe summaries, semantic export, saved PNG traces and clean original MP4. The existing three-argument command still works: without optional workbench inputs, 18–28s retains its recorded Meta frame and input facts. Use genuinely unused output/scratch paths with existing parent directories. Existing files, directories and symlinks at either destination are rejected without modification; symlink ancestors and nested output/scratch paths are rejected. Rendering uses a fresh sibling staging directory and exclusively created scratch directory. Only a successful render is atomically renamed to `--out`, without replacing a concurrently created final path (macOS/Linux no-replace rename required; unsupported hosts fail closed). Failure removes owned staging/scratch, never an existing final destination. Scratch is also removed after success. The renderer never mirrors products over historical files in `demo/`.

### Optional recorded product workbench

Supply **both** flags to replace only the existing 18–28s presentation segment with the parent's actual screenshot:

```sh
CAPTURE_DIR="$SESSION/tmp/workbench-capture"
python3 demo/render.py --session "$SESSION" \
  --scratch "$SESSION/tmp/demo-workbench-new" \
  --out "$SESSION/artifacts/ReproLoop_Demo_workbench_new" \
  --workbench-image "$CAPTURE_DIR/product-desktop-proof.webp" \
  --workbench-source-manifest "$CAPTURE_DIR/workbench-capture-source.json"
```

The receipt must be JSON with `kind: PRIVATE_RECORDED_WORKBENCH_SOFTWARE_CAPTURE`, `capture_sha256` matching the exact screenshot bytes, and boolean `not_a_new_native_or_Meta_run` / `not_producer_attestation` both true. A missing pair or mismatched receipt is rejected before output creation. The exact screenshot is copied and hash-bound. The original receipt stays untouched outside the output: only a sanitized derivative is distributed as `captures/workbench-source-receipt.json`. Its explicit fields contain the capture hashes, fixed evidence-level/role labels, required booleans, original receipt SHA-256/byte count, and optional lowercase hexadecimal source revision/commit/renderer hashes, including `base_revision` and `committed_snapshot_matching_captured_bytes` (40 or 64 characters). If supplied, `source_files` must declare exactly these seven unique paths with 64-character lowercase SHA-256 values: `ui/index.html`, `ui/console.css`, `ui/app.js`, `ui/adapter.js`, `ui/recorded-demo.js`, `ui/fixtures/recorded-case.json`, `ui/fixtures/recorded-assets.json`. Invalid provenance hashes, duplicate/conflicting entries, missing entries within a supplied list and non-allowlisted paths are rejected before output creation. Legacy receipts may omit the optional provenance fields; their absence makes no source-file verification claim. Unknown fields, free-form text and nested extras are dropped, not copied; `capture` and `captured_at` are deliberately omitted. Original-input and derivative hashes and roles are distinct in the derivative and `source-manifest.json`; presentation metadata repeats both hashes. Any retained UI source provenance is a declaration, not independently verified source access or native evidence. Sanitization does not inspect or redact the screenshot pixels themselves, so the caller must supply a privacy-reviewed screenshot.

The segment badge says **RECORDED WORKBENCH**. This is a static, full-frame software screenshot, not a native capture, live progress or new Meta inference. The original 0–18s source MP4 playback is unchanged in meaning. The 28–38s segment retains the actual Meta input facts: `muse-spark-1.3`, VIDEO + 12 uniform frames, native pointer pixels and temporal OCR. No simulated touches or progress animations are added.

## Evidence and limits

The silent MP4 remains exactly **180 seconds / 1920×1080 / 24fps**, with the same 23 boundaries:

`0, 18, 28, 38, 46, 53, 60, 67, 75, 87, 100, 108, 114, 120, 125, 130, 136, 142, 147, 152, 158, 166, 172, 180`.

Original source MP4 and all saved original captures are retained byte-for-byte in output assets. On screen they are aspect-ratio-preserving, contain/full-frame scaled, never cropped or stretched. Opening playback speed is calculated from the actual source container duration divided by 18 seconds, disclosed on screen and in generation metadata, not hardcoded to the historical rounded 1.731x. Saved capture holds omit transitions and are explicitly labeled **RECORDED FRAME SEQUENCE; transitions omitted**. Recorded inference is **RECORDED META**; controls are **RECORDED NO-MODEL REPLAY**. The final comparison enlarges the two opposing controls without inventing new evidence.

Faulty and fixed app logic is developer-supplied with AI-assisted implementation, **not a ReproLoop-generated repair**. This is one self-owned F01 synthetic Cancel-persistence family with three correlated variants. Original pilot **2/5** remains below the ≥3/5 target with all three failures. Separate v4obs1 FINAL **3/3** is never pooled with it and is not general accuracy, causal gain or an independent bug population. This presentation adds no baseline, benefit or superiority score. FINAL-C uses one exact export for both fresh controls. All FINAL cases used zero optional read-only observations; no native-effect claim is made for that branch. Sampled pointer context is consistency, not causal or physical-tap proof.

Numeric claims still read unchanged `safe-aggregates.json`: 54/60 cumulative inference calls, $1.030238 recorded token fees; uploads **UNPRICED**, not final billing. The renderer reads no raw provider response or operational database and makes no new live upload or Responses call.

`source_revision` in the source manifest remains a historical original-native-source alias, now explicitly scoped and repeated as `original_native_source_revision`. Current presentation checkout HEAD and exact `renderer_sha256` are separate under `presentation`; HEAD is not proof that the working tree is clean or newly native-executed. Allowlisted UI source provenance is separately retained in the sanitized receipt, not relabeled as the original native revision. Source-manifest schema is now 2. Hashes bind bytes, not producer, physical-tap, timestamp or OS authenticity.

## Distribution integrity

`distribution-manifest.json` is written last and inventories every distributed file with relative filename, bytes, SHA-256 and role, including copied source media, the sanitized receipt, both earlier manifests, safe JSON summaries, storyboard JSON/Markdown, SRT, rehearsal, probe metadata, review JPEGs, contact sheet and edited MP4. It excludes only itself to avoid a self-hash cycle. Original media copies and source-reference declarations are distinguished from edited presentation outputs. The manifest does not ingest the scratch directory or its large intermediate frames/parts. Hashes prove byte binding, not media authenticity.

Offline regression coverage: `python3 -m unittest discover -s tests/portable -p test_demo_render_safety.py -v`. Encoder/probe behavior is stubbed in these tests; this is not real 180-second encoding or visual acceptance.

## Acceptance checklist for any future render

- Render to unused paths with optional inputs, and check the no-flags path separately. The two invocation modes must each retain 23 contiguous segments and the exact boundaries above.
- Check `ffprobe-validation.json`: one H.264 yuv420p video stream, 1920×1080, 24fps, 4,320 decoded frames, exactly 180.000s, no audio. Perform a full decode in addition to inspecting metadata.
- Inspect **all 23 actual output samples** in `CONTACT_SHEET.jpg` plus full-resolution frames/playback. Check text fit/contrast, long mode badges, captions, phone evidence legibility, source video pacing, the 18–28s full-frame workbench and 152–158s comparison. Font-metric bounds are not visual acceptance. No important source pixels may be cropped.
- Rehash copied original assets, workbench screenshot and sanitized derivative; verify original-input hash against the private original receipt, both manifests' links, and every distribution inventory entry. Confirm no original receipt or unknown metadata was copied. A wrong capture hash / missing paired flag should reject without rendering. Receipt provenance does not establish native evidence.
- Read `REHEARSAL.md` as automated local checks only. Novice human readthrough remains **NOT_DONE**; a new render does not close human comprehension, independent-machine setup, release or external-review gates.

Generalization is not evaluated. The owner now authorizes a separately sanitized publication/submission path; this local renderer supplies no publication, rights clearance, payment permission or remote acceptance receipt. The historical recorded-v3 film SHA-256 remains `4c6255616a98cba7400886115ffbfd97bd387685ffd6d8ccc43c5ab22b59feb6`; it is not a hash to reuse for a later redesign; read that output generation manifest. Existing generated files in `demo/` remain historical until explicitly updated by their owner.
