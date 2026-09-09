#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
clang -Wall -Wno-deprecated-declarations \
  -I"$(dirname "$0")" \
  -framework IOKit -framework CoreFoundation \
  scripts/iokit_bx.m -o scripts/iokit_bx
echo "Built: $ROOT/scripts/iokit_bx"
ls -la scripts/iokit_bx
