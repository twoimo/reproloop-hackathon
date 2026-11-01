#!/bin/bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
: "${JAVA_HOME:?Set JDK home}"; : "${KOTLIN_HOME:?Set Kotlin compiler home}"
export JAVA_HOME
mkdir -p "$ROOT/build/tests"
"$KOTLIN_HOME/bin/kotlinc" "$ROOT/src/com/tinyburn/reproloop/lab/Domain.kt" "$ROOT/tests/DomainChecks.kt" -jvm-target 1.8 -d "$ROOT/build/tests/domain-tests.jar"
"$JAVA_HOME/bin/java" -cp "$ROOT/build/tests/domain-tests.jar:$KOTLIN_HOME/lib/kotlin-stdlib.jar" com.tinyburn.reproloop.lab.DomainChecksKt
