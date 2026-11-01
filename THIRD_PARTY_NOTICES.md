# Third-party inventory and unresolved rights

## Included redistribution

* Hallmark: upstream https://github.com/Nutlope/hallmark, pinned commit
  `7ec868225c6caa040558c321ee0fefa0e73f83a8`. Included copied files are
  `third_party/hallmark/scripts/sloplint.mjs`, `references/terminal.md`,
  `PROVENANCE.md`, and the original `LICENSE`. The inspected license is MIT,
  copyright 2026 Hallmark contributors. Preserve that copyright, permission and
  disclaimer in copies/substantial portions. No upstream photos/site assets,
  install hooks or plugin marketplace files are included.
* Kotlin runtime notices for NEW APK builds: `third_party/kotlin-stdlib-notices/`
  (see the Kotlin prerequisite entry below).
* Project-owned source: the owner selected MIT in this follow-up; the standard
  grant is in root `LICENSE`, copyright 2026 Yeonwoo Choi. This does not relicense
  Hallmark, Kotlin, any third-party dependency, media/model response or other
  material not owned by the project. Their original notices remain intact.
  The license choice is NOT permission to publish this private repository,
  redistribute APKs/assets or submit to the organizer. Those actions and
  material-specific rights remain held. Historical APKs do not bundle this new first-party LICENSE. NEW builds now
  include its exact bytes at assets/reproloop/LICENSE before signing and verify
  them in unsigned/signed APKs. This closes a notice-preparation gap, not the
  separate binary/material/organizer rights or release approval gates.

## Prerequisites, not bundled dependencies

* Python 3.11+ standard library: external runtime. This source archive does not
  redistribute Python or its libraries. Packaging via setuptools requires the
  declared build requirement; offline checks use PYTHONPATH, not installation.
* Node: external runtime for built-in node:test and the console checks. No npm
  dependencies, node_modules or Node runtime are bundled.
* Pillow 13.0.0: optional pin in requirements-video.txt; not vendored here. Its
  installed 13.0.0 distribution metadata declares MIT-CMU. Its inspected LICENSE
  retains PIL/Secret Labs AB/Fredrik Lundh and Pillow contributor copyrights,
  requires copyright and permission notices in copies/supporting documentation,
  prohibits advertising use of the named authors without written permission,
  and includes a warranty/liability disclaimer. That distribution also carries
  separate bundled-code notices (including AOM, Brotli, bzip2 and dav1d); the
  entire transitive binary notice inventory was NOT reviewed. Preserve/review
  the exact distribution's full license bundle before redistributing wheels,
  native codecs or a runtime. The source candidate includes no Pillow bytes.
  Full offline tests require Pillow even though some runtime paths are optional.
  No install was performed.
* Kotlin 2.3.20 compiler/stdlib, JDK 25.0.3, Android SDK platform 34/build-tools
  34.0.0: external build prerequisites, not in this archive. The compiler, JDK
  and SDK tools are not redistributed. A built APK DOES embed (dexed) classes
  from three pinned Kotlin runtime jars: kotlin-stdlib, kotlin-stdlib-jdk7 and
  kotlin-stdlib-jdk8, 2.3.20-release-208. Exact byte copies of the applicable
  public license/NOTICE/COPYRIGHT files from the installed distribution are in
  `third_party/kotlin-stdlib-notices/` with SHA256SUMS and PROVENANCE.md
  (Apache-2.0 for JetBrains code; GWT/Guava Apache-2.0, ThreeTen-Backport
  3-clause BSD and Boost 1.0 for README-mapped stdlib source paths).
  `android/build.sh` fails if any listed notice is missing/changed or if the
  stdlib jar hashes differ, and packs that folder into each NEW APK under
  `assets/third_party/kotlin-stdlib-notices/` before zipalign/apksigner. The two
  originally pinned historical APKs predate this and contain no notice assets;
  they were not rebuilt, re-pinned or re-signed. The JDK/SDK distribution terms,
  including Android SDK license acceptance, belong to the person who installed
  them and must be checked for the exact distributions before any redistribution.
  This archive contains no APK/toolchain.
* Android SDK packages and the Google Play system image: the bootstrap requires
  an already installed `system-images;android-34;google_apis_playstore;arm64-v8a`
  plus emulator, platform-tools and cmdline-tools. They are run locally and are
  never bundled. Their license acceptance happened (or must happen) at install
  time by the installer under Google's terms; this project does not accept,
  bypass or redistribute any SDK or Google Play image terms.
* Apple frameworks and SDK: `tools/inspect_video.swift` imports Foundation,
  AVFoundation, AppKit and CryptoKit; `tools/ocr_video_frames.swift` imports
  Foundation, Vision, AppKit and CryptoKit. These are macOS system frameworks
  used at run time on the user's own Mac via the installed Swift toolchain.
  Nothing from Apple is copied into this source tree.
* ffmpeg/ffprobe (expected at the Homebrew location used by `demo/render.py`):
  an external executable, not bundled. The renderer invokes the `libx264`
  encoder. Licensing obligations for an ffmpeg build that includes libx264
  (commonly GPL) attach to distributing that ffmpeg/libx264 BINARY. This project
  does not distribute it. Official FFmpeg legal guidance concerns its build and
  binary; the GNU GPL FAQ says program output is generally not covered by the
  program's code copyright, except when the output copies program text/art.
  Using FFmpeg/libx264 alone therefore does not establish that this encoded MP4
  is GPL. The separately sourced input pixels, actual content rights, codec/
  patent questions and event terms remain distinct; no blanket legal clearance.
  Sources: https://www.ffmpeg.org/legal.html and
  https://www.gnu.org/licenses/gpl-faq.html#WhatCaseIsOutputGPL (read2026-11-01).
* Arial / Arial Bold (macOS system fonts used by `demo/render.py`): the renderer
  rasterizes text with the locally installed fonts. Font software is NOT copied
  or redistributed; only rendered words/phrases appear in derived frames.
  On2026-11-01 both exact installed system-font name tables identified Monotype
  Version5.01.2x and permitted display/print subject to the including product's
  license. Apple's macOS27 font list names Arial/Arial Bold5.01.2x, and its SLA
  section2E permits included fonts to display/print content while running macOS,
  subject to font embedding restrictions. No font program or bitmap alphabet
  is embedded/redistributed here. Microsoft's graphics/bitmap-video FAQ supports
  the output/file distinction but is Windows-scoped, not the license for this
  Mac copy. This is a bounded source/provenance review, not a statutory rights
  or OS-entitlement attestation. Sources:
  https://support.apple.com/en-us/127491
  https://www.apple.com/legal/sla/docs/macOS27.pdf
  https://learn.microsoft.com/en-us/typography/fonts/font-faq
* Current `ui/console.css` uses installed system sans/monospace stacks, including
  ui-monospace/SFMono-Regular/Consolas, not downloaded font files. Historical CSS
  named Martian Mono; no Martian font file was ever bundled in this candidate.
* Hallmark-derived console styling: `ui/console.css` declares it is
  Hallmark-derived. If those styles are a substantial portion of Hallmark, the
  MIT copyright and permission notice must accompany them; it is kept at
  `third_party/hallmark/LICENSE`, and a distribution that ships `ui/` should
  ship that LICENSE alongside (for example in the footer/about notice or next to
  the stylesheet). Whether the derived CSS is a "substantial portion" is not
  decided here; retaining the notice is the conservative choice.
* Meta API/model service: an external optional exploration service, not model
  weight redistribution. The official Terms observed on 2026-10-29, section4.1,
  allocate Input/Output rights to the user "To the extent permitted by applicable
  law, and as between the parties"; Meta does not claim ownership. The same
  section says outputs need not be unique and may contain third-party-licensed
  material, and requires rights to Inputs. This is not statutory-copyright or
  third-party/media clearance. Section1 and the AUP impose applicable disclosure
  and Meta-applied provenance-preservation duties; the AUP prohibits representing
  Outputs as human-generated. Preserve any applied signals and review actual
  materials before distribution. No account/mode, billing or service-use setting
  was changed by reading public policies, and no new inference/upload ran.
  Re-read2026-11-01: ownership remains section4.1 Content Rights; section5.1
  is Processor Terms and must not be cited as the ownership clause.
  Sources: https://dev.meta.ai/legal/terms-of-service and
  https://dev.meta.ai/legal/acceptable-use-policy . No key/raw model response
  or model-service license is redistributed in the source archive.

Inventory is bounded to inspected tracked source and dependency declarations.
It is not an exhaustive transitive binary SBOM or legal clearance. Media,
recordings, raw response rights and contest submission rights remain separate.
