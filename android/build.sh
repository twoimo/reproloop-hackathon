#!/bin/bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
: "${ANDROID_SDK_ROOT:?Set existing Android SDK root}"
: "${JAVA_HOME:?Set existing JDK home}"
: "${KOTLIN_HOME:?Set existing Kotlin compiler home}"
BT="$ANDROID_SDK_ROOT/build-tools/34.0.0"
AJAR="$ANDROID_SDK_ROOT/platforms/android-34/android.jar"
OUT="$ROOT/build"
NOTICES="$ROOT/../third_party/kotlin-stdlib-notices"
NOTICE_ASSET_PREFIX="assets/third_party/kotlin-stdlib-notices"
OWN_LICENSE="$ROOT/../LICENSE"
OWN_LICENSE_ASSET="assets/reproloop/LICENSE"
# Exact pinned Kotlin runtime jars that D8 bundles; the copied notices apply only to these bytes.
STDLIB_PINS="0ae12504a5040ebaf37703908483420d1a5624dd1d93f357665f8c77c848a01e  kotlin-stdlib.jar
18231e75c68026d90f5487c8dc753be307c273a5eed574cee5a7118dfb04bc14  kotlin-stdlib-jdk7.jar
4d2f1d22a64efd04554108ba71297e10ff399fc0d61f56feb7a9266104be757d  kotlin-stdlib-jdk8.jar"
notice_fail() { echo "NOTICE PACKAGING FAILED: $1" >&2; echo "No fallback: restore the exact files under third_party/kotlin-stdlib-notices (see its PROVENANCE.md)." >&2; exit 3; }
[[ -f "$OWN_LICENSE" && ! -L "$OWN_LICENSE" && -s "$OWN_LICENSE" ]] || notice_fail "missing, symlink or empty project LICENSE"
OWN_LICENSE_SHA=$(/usr/bin/shasum -a 256 "$OWN_LICENSE" | cut -d' ' -f1)
[[ -d "$NOTICES" && ! -L "$NOTICES" ]] || notice_fail "missing notice folder third_party/kotlin-stdlib-notices"
[[ -f "$NOTICES/SHA256SUMS" && ! -L "$NOTICES/SHA256SUMS" && -s "$NOTICES/SHA256SUMS" ]] || notice_fail "missing or empty SHA256SUMS"
[[ -f "$NOTICES/PROVENANCE.md" && ! -L "$NOTICES/PROVENANCE.md" ]] || notice_fail "missing PROVENANCE.md"
(cd "$NOTICES" && printf '%s  SHA256SUMS\n' "6db92c6b684db81e31c77f4c2c2f60a9e890fd2c6c6bc5804de038d766b39142" | /usr/bin/shasum -a 256 -c --status) || notice_fail "notice manifest differs from the reviewed nine-file selection"
NOTICE_FILES=()
while read -r NOTICE_HASH NOTICE_NAME; do
  [[ "$NOTICE_HASH" =~ ^[0-9a-f]{64}$ && "$NOTICE_NAME" =~ ^license/[A-Za-z0-9_./-]+$ && "$NOTICE_NAME" != *..* ]] || notice_fail "malformed SHA256SUMS line"
  [[ -f "$NOTICES/$NOTICE_NAME" && ! -L "$NOTICES/$NOTICE_NAME" ]] || notice_fail "missing notice file $NOTICE_NAME"
  NOTICE_FILES+=("$NOTICE_NAME")
done < "$NOTICES/SHA256SUMS"
(( ${#NOTICE_FILES[@]} == 9 )) || notice_fail "expected exact reviewed 9 notice files"
(cd "$NOTICES" && /usr/bin/shasum -a 256 -c --status SHA256SUMS) || notice_fail "notice file hash mismatch"
(cd "$KOTLIN_HOME/lib" && printf '%s\n' "$STDLIB_PINS" | /usr/bin/shasum -a 256 -c --status) || notice_fail "Kotlin stdlib jar bytes differ from the pins the copied notices were taken for"
mkdir -p "$OUT"
export JAVA_HOME
"$KOTLIN_HOME/bin/kotlinc" -version
"$BT/aapt2" compile --dir "$ROOT/res" -o "$OUT/resources.zip"
"$BT/aapt2" link -o "$OUT/resources.apk" --manifest "$ROOT/AndroidManifest.xml" -I "$AJAR" --java "$OUT/generated" "$OUT/resources.zip"
if [[ ! -f "$OUT/debug.keystore" ]]; then
  "$JAVA_HOME/bin/keytool" -genkeypair -keystore "$OUT/debug.keystore" -storepass android -keypass android -alias androiddebugkey -keyalg RSA -keysize 2048 -validity 365 -dname 'CN=ReproLoop Local Debug,O=Self Owned Fixture,C=KR'
fi
for MODE in faulty fixed; do
  DIR="$OUT/$MODE"
  mkdir -p "$DIR/generated/com/tinyburn/reproloop/lab" "$DIR/classes" "$DIR/dex"
  FLAG=false; [[ "$MODE" == faulty ]] && FLAG=true
  cat > "$DIR/generated/com/tinyburn/reproloop/lab/BuildConfig.kt" <<GEN
package com.tinyburn.reproloop.lab
object BuildConfig { const val DEBUG = true; const val FAULTY = $FLAG; const val MODE = "$MODE" }
GEN
  "$JAVA_HOME/bin/javac" --release 8 -cp "$AJAR" -d "$DIR/classes" "$OUT/generated/com/tinyburn/reproloop/lab/R.java"
  "$KOTLIN_HOME/bin/kotlinc" "$ROOT/src" "$DIR/generated" -jvm-target 1.8 -classpath "$AJAR:$DIR/classes" -d "$DIR/classes"
  "$JAVA_HOME/bin/jar" --create --file "$DIR/app-classes.jar" -C "$DIR/classes" .
  "$JAVA_HOME/bin/java" -cp "$BT/lib/d8.jar" com.android.tools.r8.D8 --min-api 26 --lib "$AJAR" --output "$DIR/dex" "$DIR/app-classes.jar" "$KOTLIN_HOME/lib/kotlin-stdlib.jar" "$KOTLIN_HOME/lib/kotlin-stdlib-jdk7.jar" "$KOTLIN_HOME/lib/kotlin-stdlib-jdk8.jar"
  cp "$OUT/resources.apk" "$DIR/unsigned.apk"
  (cd "$DIR/dex" && /usr/bin/zip -q -j "$DIR/unsigned.apk" classes*.dex)
  # Inject the exact notice folder into this NEW APK before zipalign/apksigner (signature covers it).
  rm -rf "$DIR/notice-assets"
  mkdir -p "$DIR/notice-assets/$NOTICE_ASSET_PREFIX"
  mkdir -p "$DIR/notice-assets/assets/reproloop"
  cp "$OWN_LICENSE" "$DIR/notice-assets/$OWN_LICENSE_ASSET"
  cp "$NOTICES/SHA256SUMS" "$NOTICES/PROVENANCE.md" "$DIR/notice-assets/$NOTICE_ASSET_PREFIX/"
  for NOTICE_NAME in "${NOTICE_FILES[@]}"; do
    mkdir -p "$DIR/notice-assets/$NOTICE_ASSET_PREFIX/$(dirname "$NOTICE_NAME")"
    cp "$NOTICES/$NOTICE_NAME" "$DIR/notice-assets/$NOTICE_ASSET_PREFIX/$NOTICE_NAME"
  done
  (cd "$DIR/notice-assets/$NOTICE_ASSET_PREFIX" && /usr/bin/shasum -a 256 -c --status SHA256SUMS) || notice_fail "staged notice copy differs"
  find "$DIR/notice-assets" -exec env TZ=UTC touch -h -t 198001010000 {} +
  (cd "$DIR/notice-assets" && TZ=UTC /usr/bin/zip -q -X -D -r "$DIR/unsigned.apk" assets)
  for NOTICE_NAME in SHA256SUMS PROVENANCE.md "${NOTICE_FILES[@]}"; do
    /usr/bin/unzip -Z1 "$DIR/unsigned.apk" | grep -Fx "$NOTICE_ASSET_PREFIX/$NOTICE_NAME" >/dev/null || notice_fail "APK lacks $NOTICE_ASSET_PREFIX/$NOTICE_NAME"
  done
  [[ "$(/usr/bin/unzip -p "$DIR/unsigned.apk" "$OWN_LICENSE_ASSET" | /usr/bin/shasum -a 256 | cut -d' ' -f1)" == "$OWN_LICENSE_SHA" ]] || notice_fail "unsigned APK project LICENSE differs"
  "$BT/zipalign" -f 4 "$DIR/unsigned.apk" "$DIR/aligned.apk"
  "$JAVA_HOME/bin/java" -jar "$BT/lib/apksigner.jar" sign --ks "$OUT/debug.keystore" --ks-key-alias androiddebugkey --ks-pass pass:android --key-pass pass:android --out "$OUT/pockettasks-$MODE-debug.apk" "$DIR/aligned.apk"
  "$JAVA_HOME/bin/java" -jar "$BT/lib/apksigner.jar" verify --verbose "$OUT/pockettasks-$MODE-debug.apk"
  [[ "$(/usr/bin/unzip -p "$OUT/pockettasks-$MODE-debug.apk" "$OWN_LICENSE_ASSET" | /usr/bin/shasum -a 256 | cut -d' ' -f1)" == "$OWN_LICENSE_SHA" ]] || notice_fail "signed APK project LICENSE differs"
  for NOTICE_NAME in SHA256SUMS PROVENANCE.md "${NOTICE_FILES[@]}"; do
    /usr/bin/unzip -Z1 "$OUT/pockettasks-$MODE-debug.apk" | grep -Fx "$NOTICE_ASSET_PREFIX/$NOTICE_NAME" >/dev/null || notice_fail "signed APK lacks $NOTICE_ASSET_PREFIX/$NOTICE_NAME"
  done
done
shasum -a 256 "$OUT/"*.apk
