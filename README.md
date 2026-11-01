# ReproLoop

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
