# Read-only evidence console

Serve the repository's UI over loopback, then select a local JSON file:

```sh
python3 -m http.server 8000 --bind 127.0.0.1 --directory ui
```

Open the displayed localhost address. The page has no device driver, Meta client, upload endpoint or server validator. The recorded-example module reads only its explicit trusted same-origin static media catalog; uploaded JSON cannot choose URLs or trigger those reads. Its model/device buttons stay disabled. Images and video are explicitly selected local files; video starts paused, muted and at volume zero. Never label this viewer LIVE META.

## Separate cohort contracts

- `reproloop.evidence.v1`: existing `pilot` contract, exactly five unique planned ids. Existing valid v3 pilot and synthetic illustration files remain supported.
- `reproloop.evidence.v2`: exactly one `cohort` object with `id`, `split` (`DEV`, `PILOT`, `FINAL`), `condition`, and 1–64 unique `planned_case_ids`. A three-case FINAL is not a five-case pilot. Do not include both `pilot` and `cohort`.
- Both versions require the existing root `evidence_level`, `mode`, integer call/run counts, `cases` array and optional illustration. Cases must have unique ids belonging to that document's plan; an illustration cannot reuse a case id.
- `attempted = complete + excluded + unknown`. Complete means a known terminal outcome, not success. Not-run is planned minus attempted; its optional id list must contain distinct planned ids with that count. Cases may carry capture information before an evaluation starts; row presence does not certify an attempted result.
- Score fields `valid_export_pairs`, `fixed_failure_signals`, `invalid_confirmations` must remain **null**. `file_claim.verdict` remains text, even when it says success. Matching attachment hashes never change `UNVERIFIED` into backend validation.

The packaged actual, unverified FINAL import is `ui/fixtures/recorded-case.json`. The original `evidence/native-v4obs1/console-import-v2.json` is a private archive identifier, not a file required by this public copy. It refers to recorded Meta work and separately selected PNG/MP4 bytes, not a new provider/device run. Its Android workflow counter covers three CUA explorations plus six model-free controls, excluding source-media creation. It does not replace the earlier v3 2/5 result.

## File and state boundaries

The selected JSON is limited to 200000 bytes. External URLs, path escapes, unsafe keys, excessive nesting and malformed rendered collection members are rejected. Optional null collections are empty; null array elements are not valid model/step/node objects. Model/step/node limits are 8/24/64, with at most 24 task steps.

Selecting a different case or document revokes all image/video object URLs, pauses the old video and clears preview inputs. The same terminal case within the same document preserves manual attachments, including pending byte hashing. A recorded reload may retry non-manual slots; a deliberate saved-step change or different case clears the old media identity. An invalid, oversized or unreadable replacement leaves no active cohort or stale evidence. A later selected document, sample or clear action supersedes earlier asynchronous file reads; old digests cannot label new-case media.

## Checks and limits

`python3 tools/check_local.py` executes local Python and UI suites, not native/Meta evaluation. The post-adversarial corrective suite contains 67 UI tests. Four new regressions fail the pre-correction implementation: manual selection no longer cancels another slot pending on the network, rejected media cancels only its own older read, all media inputs reset for same-file retry, and intermediate manual comparisons name the terminal claim. The renderer separately has 18 safety tests. These are not native or independent-host runs. The new behavioral checks detect the original same-case overwrite, blocked image loading, blank-choice fallback and ellipsis rejection in an isolated baseline copy. Prior independent local reviews retain their original source scope and do not validate this later correction. Actual browser checks cover the real v1 five-case import, v2 FINAL three-case import, malformed-model rejection/recovery and local PNG/video hash comparison. Responsive tests use same-origin iframe viewports at 320, 375, 414, 768, 1024, 1280, 1440 and 1920 CSS pixels. These are not mobile-device emulation or OS-authenticity tests; outer screenshots can crop the larger iframe while DOM width/ink checks cover its layout.

The original repository/history and Meta ledger are preserved. The owner has authorized a separate sanitized publication/submission path, but preparation, asset rights, full external review and actual remote acceptance remain distinct checks. This page never runs a replay or claims a backend verdict.

## B1 producer integration correction

`ui/scripts/build-host-bundle.py` exports an existing saved non-pilot B1 record
under the existing v1 `illustration` field, with object-shaped `task_steps`.
It does not insert DEV into the five planned pilot rows, count a new attempt,
change old files or issue a backend verdict. Here illustration means a non-scoring
record, not invented/synthetic pixels; mode/evidence claims remain separate.

The preview hash lookup uses the same `rowChoices` owner as row selection, so
non-scoring records also support matching/mismatching image and video claims.
Hashes do not upgrade `UNVERIFIED`. The single checker now runs the standalone
producer tests (formerly absent from its discovery), including the actual Node
consumer roundtrip and two negative controls for the reproduced contract defects.
The source allowlist copies the current producer/test source byte-for-byte; synthetic negative
path vectors are assembled at runtime and original private execution is untouched.

## Existing files and failed replacement boundaries

The B1 exporter creates a NEW destination outside its read-only case root. It
rejects existing files/symlinks, noncanonical/symlink parents and output inside
the case. Like the source builder, it privately stages complete JSON and links
without replacing any winner; partial staging is removed on failure. These are
trusted-stable-local-filesystem boundaries, not protection against a hostile OS.
Normal export bytes/schema/counts are unchanged. Use a new output path; do not
retry a refused destination without inspection.

Selecting invalid/wrong-slot/oversized media revokes and clears only that slot
before error display. Old pending digests cannot relabel it; old video is paused.
Other slots, the selected record, null score fields and UNVERIFIED stay unchanged.

## Product workbench / recorded example

The light paired-control workbench keeps the existing strict adapter and local
import contracts. The trusted recorded catalog is separate from uploaded data.
FINAL-C has actual saved four-step control frames; A/B have final captures only.
Frames are selected, not a new run or simulated live progress. Shared/duplicate
pixels add no independent visual corroboration. Source video stays paused, muted
and volume0 until explicitly played. Old case/source/step reads cannot restore
revoked media. Manual media selection supersedes pending bundled reads.

`tools/package_workbench.py` can create a new private viewer with exact catalog
bytes and retained own/Hallmark notices. It does not install, upload or publish.
The source-only candidate intentionally omits `ui/recorded/` media; its unavailable
state retains metadata as unverified claims and asks for local files/private kit.
The actual first ChatGPT thesis is saved and source-readable. Its UI defects were corrected with behavioral regressions; Gemini adversarial and ChatGPT reverse are still incomplete. Local peer/tests are separate evidence. See docs/design/product-workbench.md.

Ready recorded images are attached independently of a pending video or another slot's byte hash. Each load has a fresh source/case/step request generation; explicit manual ownership and object-URL checks prevent late replacements. Selecting `No case row` stays empty and does not request a fallback case. JSON input is cleared after capturing the selected File object, enabling the same filename after clear or corrected parse errors. The actual Chromium journey checked those user paths; Safari is not claimed. Ordinary prose ellipses are allowed, while parent path segments, external URL schemes, encoded escapes and unsafe keys remain rejected. Synthetic imports show their counts as unverified file claims, never real executions; non-recorded imports use neutral comparison headings. The web UI inspects but does not export evidence; CLI packaging is a separate operation.


## Manual-media retry and step claims

Manual selection invalidates only that slot's pending catalog read. Other
slots continue loading; case/document/step changes still revoke all old
identities. File inputs reset immediately after File capture, including
rejected media. An explicit same-case retry can reload a missing non-manual
slot. Manual intermediate images are compared with the imported terminal
control claim, explicitly labeled as not the selected saved-step claim.
Matching hashes remain unverified and do not create a score.
