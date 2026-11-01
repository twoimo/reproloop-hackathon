# PUBLIC preparation gate (R01 / R04)

This is an offline, separate preparation gate, not permission to publish, submit,
serve publicly, claim final rights clearance, or mark a native/model run successful.
`release_candidate.py` remains the PRIVATE source-only builder and scanner.
`package_workbench.py` remains the PRIVATE catalog viewer builder. Neither is
promoted to a public-release tool. A source-only candidate is not a media-complete
product. This builder succeeds only with every catalog asset and a complete,
byte-bound supplied review declaration.

## Inputs and use

Use Python 3.11+ and the standard library. No install, network, browser, Meta,
AVD, full rendering or service write is needed or performed. Parents must already
exist and be exclusively owned; input/output mutation by adversarial concurrent
writers is outside this tool's contract. Existing output directories, including
empty ones, files and symlinks are never overwritten.

```sh
python3 tools/public_release.py --source SOURCE --media-root MEDIA \
  --review REVIEW.json --out NEW_STAGING_DIRECTORY
python3 tools/public_release.py --verify NEW_STAGING_DIRECTORY
```

`MEDIA` is a flat directory containing the exact basenames listed in
`ui/fixtures/recorded-assets.json`. Only those files are read; unrelated media is
not copied. Names, bytes, SHA-256 and MIME/extension must match the static catalog.
The catalog's own SHA-256 is pinned in the tool: changing it requires an explicit
code review, not registration through CLI. Conflicting duplicate catalog paths,
duplicate JSON keys, malformed fields, wrong types, path traversal, symlinks and
nonregular files are rejected. PNG and MP4 signatures are checked in addition to
catalog hashes. This is not a full decoder, metadata audit or visual inspection.
No media is substituted, downloaded, transcoded or changed.

Source text is obtained via the existing `source_payload` and `read_source` /
`scan` / `member_name` contracts. Selection is the existing whitelist plus
`tools/public_release.py`, `tests/portable/test_public_release.py`,
`docs/PUBLIC_RELEASE.md` and `tests/portable/test_demo_render_safety.py`.
The source README is replaced only inside the new output by a bounded generated
preparation README. Source copying is never recursive. Original LICENSE and
third-party notices retain their exact bytes. The parent owns any update of the
existing source whitelist; this change does not edit it.

## Required supplied asset review

The parent/reviewer must actually inspect the exact assets and supply a separate
JSON input. The builder does not create or decide completion of those reviews.
Exact schema (no additional fields, free text, owner identity or comments):

```json
{
  "kind": "REPROLOOP_PUBLIC_ASSET_REVIEW_V1",
  "files": [
    {
      "path": "ui/recorded/FINAL-A-faulty.png",
      "sha256": "REPLACE_WITH_EXACT_64_LOWERCASE_HEX_CATALOG_HASH",
      "visual_reviewed": true,
      "metadata_reviewed": true,
      "rights_basis": "PROJECT_AUTHORED_SELF_CAPTURED"
    }
  ]
}
```

This abbreviated example is deliberately not accepted as a complete review.
Every distinct catalog path must appear exactly once with its exact hash.
Both booleans must be JSON `true`, not strings or numbers. The sole supported
rights-basis enum is `PROJECT_AUTHORED_SELF_CAPTURED`; other bases require an
explicit schema/code change rather than unreviewed free text. This enum is a
supplied declaration, not authenticated authorship or a legal conclusion.
Top-level fields are exactly `kind` and `files`; row fields are exactly those
shown. Hashes are lowercase 64-hex. Unknown paths, duplicate rows, false/missing
reviews and stale hashes are rejected. Only canonical safe fields are stored in
`public-asset-review.json`; no original review file, arbitrary prose, raw receipt,
private Git history, browser information or host/session marker is copied.

MIT covers project-owned source only. Third-party licenses, media rights,
organizer terms and final release clearance remain separate. A model's label
agreement does not guarantee licensing, original creation or native reproduction.
All recorded evidence stays UNVERIFIED. Original PILOT 2/5 and later FINAL 3/3
(correlated variants in one family) remain separate, with no score update.

## Output integrity and publication mechanics

`public-preparation.json` is a generated manifest of bounded status declarations.
`public-inventory.json` lists relative path, byte count and SHA-256 for every
other file with roles `source`, `media`, `derived-review`, `license`, `manifest`.
Original third-party notices carry the license role; third-party scripts and
other source documents retain the source role.
The inventory explicitly excludes itself because a file cannot contain its own
hash; verify enforces its exact canonical bytes independently. No absolute paths,
private source revision or source-tree provenance is emitted. Existing public
third-party provenance/license notices remain part of the selected source.

Verification rejects missing, extra, modified, symlink or nonregular files and
unexpected directories; rescans all text; rechecks media and review coverage;
and recomputes the canonical inventory. Integrity is not a signature: an actor
who can rewrite both source and inventory can change non-pinned safe source.
Retain the independently returned/reviewed artifact identity for authenticity.
The privacy scanner is bounded and cannot prove exhaustive absence of secrets
or unsafe content, especially inside binary media. Actual visual/metadata review
is therefore required, not replaced by hashes or tests.

The builder writes to a fresh private sibling temporary directory, verifies it,
then performs an atomic native no-replace directory rename (macOS/Linux).
Unsupported platforms fail closed. This filesystem operation is not publication
of a website. Only its own staging directory is cleaned after failure; prior
outputs/scratch paths remain untouched. Inputs/media bytes are immutable.
The generated README points to `ui/`; no Pages URL is invented. Nothing claims
completed CI, new execution, native success, public posting or final legal review.

## Offline checks

```sh
python3 -m unittest discover -s tests/portable -p test_public_release.py -v
python3 -m unittest discover -s tests/portable -p test_release_candidate.py -v
python3 -m unittest discover -s tests/portable -p test_workbench_package.py -v
python3 -m unittest discover -s tests/portable -p test_demo_render_safety.py -v
```

Synthetic tests cover normal preparation, privacy leakage, missing/invalid review,
hash/type/path failures, symlinks/nonregular inputs, output collisions, cleanup,
closure and post-build tampering. Full local suite: `python3 tools/check_local.py`
requires the project's preinstalled prerequisites. Passing offline tests is not
real-asset visual review, legal clearance, full render, fresh-machine validation,
external audit, CI completion or permission to publish/submit.
