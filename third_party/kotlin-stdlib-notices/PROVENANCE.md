# Kotlin standard library notices: provenance

These files are exact byte copies of public license/notice files shipped in an
installed Kotlin compiler distribution. They are kept so that a NEW debug APK
built by `android/build.sh` carries the notices for the Kotlin runtime that D8
bundles into it. This is notice retention, not legal clearance and not a
license grant for ReproLoop's own code. At notice-collection/build time that
choice was undecided; the later owner-selected MIT is recorded in root LICENSE.
It does not replace these third-party licenses or clear a binary release.

## Source distribution (observed, read-only)

- Installed location class: the Kotlin compiler home bundled with Android Studio
  on macOS (`<Android Studio.app>/Contents/plugins/Kotlin/kotlinc`).
- `build.txt`: `2.3.20-release-208`.
- Files were read from that home's `license/` directory only. No download, no
  network fetch, no edits, no normalization of line endings.

## Library bytes these notices were taken for

`android/build.sh` passes exactly these three jars to D8. The build re-checks
these hashes and fails if they differ, because the copied notices are only known
to correspond to these bytes.

| Jar | SHA-256 | Manifest `Implementation-Title` / `Implementation-Version` / vendor |
|---|---|---|
| `kotlin-stdlib.jar` | `0ae12504a5040ebaf37703908483420d1a5624dd1d93f357665f8c77c848a01e` | kotlin-stdlib / 2.3.20-release-208 / JetBrains |
| `kotlin-stdlib-jdk7.jar` | `18231e75c68026d90f5487c8dc753be307c273a5eed574cee5a7118dfb04bc14` | kotlin-stdlib-jdk7 / 2.3.20-release-208 / JetBrains |
| `kotlin-stdlib-jdk8.jar` | `4d2f1d22a64efd04554108ba71297e10ff399fc0d61f56feb7a9266104be757d` | kotlin-stdlib-jdk8 / 2.3.20-release-208 / JetBrains |

The `kotlin-stdlib.jar` hash equals `kotlin_stdlib` in `android/toolchain-lock.json`.
None of the three jars contains an embedded LICENSE/NOTICE entry; each contains
only `META-INF/MANIFEST.MF` plus classes (the jdk7/jdk8 jars contain only a
manifest and a `module-info.class`).

## Copied files and why each is included

| File | Reason |
|---|---|
| `license/LICENSE.txt` | Apache License 2.0 text; the distribution README says it applies to JetBrains-copyright code. |
| `license/NOTICE.txt` | Apache-2.0 section 4(d) NOTICE of the distribution. Its text names the "Kotlin Compiler distribution"; it is retained verbatim because it is the distribution's only NOTICE file, not because it names the stdlib. |
| `license/COPYRIGHT.txt`, `license/COPYRIGHT_HEADER.txt` | Distribution copyright statements. |
| `license/README.md` | The distribution's map from source paths to third-party licenses. Retained verbatim; it also lists compiler/test/example paths that are NOT in the APK. |
| `license/third_party/gwt_license.txt` | README maps `libraries/stdlib/src/kotlin/collections` (GWT-derived) to it. |
| `license/third_party/threetenbp_license.txt` | README maps `libraries/stdlib/src/kotlin/time` to it. |
| `license/third_party/guava_license.txt` | README maps `libraries/stdlib/jvm/src/kotlin/util/UnsignedJVM.kt` to it. |
| `license/third_party/boost_LICENSE.txt` | README maps `libraries/stdlib/jvm/src/kotlin/util/MathJVM.kt` to it. |

Selection rule: every README entry under `libraries/stdlib/src` or
`libraries/stdlib/jvm/src` (the JVM stdlib sources). JS, Wasm, Native, compiler,
plugin, test-data and example entries were not copied because those sources are
not part of the three JVM jars. This mapping is the distribution's own statement,
inspected by reading the README; it was not independently verified against
class files, and it is not a complete per-class provenance audit.

## Hashes

`SHA256SUMS` lists every copied file. `android/build.sh` requires every listed
file to exist as a regular non-symlink file with the listed hash, and requires
exactly the reviewed nine entries. Its manifest SHA-256 is also pinned in the
build script, so duplicate/replaced/omitted entries fail, not just missing payloads.
A missing or changed file fails the build with no fallback.
The same folder (SHA256SUMS, this file and `license/**`) is packed into each new
APK under `assets/third_party/kotlin-stdlib-notices/` before zipalign/apksigner.

## Limits

- Only the Kotlin runtime embedded in the APK is covered. Android framework,
  JDK, SDK tools and the Google Play system image are build/run prerequisites
  that are not redistributed in the APK; see `THIRD_PARTY_NOTICES.md`.
- Existing historical APKs (including the two originally pinned builds) were not
  rebuilt or modified and do not contain these assets.
- No lawyer or rights holder reviewed this selection.
