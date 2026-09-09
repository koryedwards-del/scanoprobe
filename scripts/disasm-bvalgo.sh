#!/usr/bin/env bash
set -euo pipefail
BIN="${1:-/Applications/BodyViewPersonal.app/Contents/MacOS/BodyViewPersonal}"
OUT="$(cd "$(dirname "$0")/.." && pwd)/bodyview-bvalgo-disasm.txt"
if [[ ! -f "$BIN" ]]; then echo "Not found: $BIN"; exit 1; fi
SYMS=(
  GetThicknessMeasurementfromAverageSignal
  initthicknessParms
  GetEstimatedThickness
  findFirstPeakinArray
  FindPeaks
  GetPeakLocation
  readbxMultipleSignals
)
{
  echo "BVAlgo disasm — $(date)"
  echo "Binary: $BIN"
  echo ""
  for sym in "${SYMS[@]}"; do
    echo "══════════════════════════════════════════════════"
    echo "$sym"
    echo "══════════════════════════════════════════════════"
    otool -arch x86_64 -tv "$BIN" 2>/dev/null | grep -A 100 "<-${sym}" | head -105 || true
    echo ""
  done
} | tee "$OUT"
echo "Saved: $OUT"
