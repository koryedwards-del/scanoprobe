#!/usr/bin/env bash
set -euo pipefail
BIN="${1:-/Applications/BodyViewPersonal.app/Contents/MacOS/BodyViewPersonal}"
OUT="$(cd "$(dirname "$0")/.." && pwd)/bodyview-bvalgo-disasm.txt"
[[ ! -f "$BIN" ]] && echo "Not found: $BIN" && exit 1
ARCH=""
if lipo -info "$BIN" 2>/dev/null | grep -q arm64; then ARCH=arm64
elif lipo -info "$BIN" 2>/dev/null | grep -q x86_64; then ARCH=x86_64
else ARCH=$(file "$BIN" | grep -oE 'arm64|x86_64' | head -1); fi
[[ -z "$ARCH" ]] && ARCH=arm64
PATTERNS=(GetThicknessMeasurementfromAverageSignal initthicknessParms GetEstimatedThickness findFirstPeakinArray FindPeaks FindClosestPeak GetPeakLocation readbxMultipleSignals _peakstart _peakend _peakMax _peakiMax _fatThickness _muscleThickness)
{
  echo "BVAlgo disasm v2 — $(date)"
  echo "Binary: $BIN"
  echo "Arch:   $ARCH"
  echo ""
  echo "=== NM symbols ==="
  for pat in "${PATTERNS[@]}"; do
    hits=$(nm -arch "$ARCH" "$BIN" 2>/dev/null | grep -i "$pat" || true)
    [[ -n "$hits" ]] && echo "--- $pat ---" && echo "$hits" && echo ""
  done
  echo "=== DISASM by address ==="
  for pat in "${PATTERNS[@]}"; do
    while IFS= read -r line; do
      [[ -z "$line" ]] && continue
      addr=$(echo "$line" | awk '{print $1}')
      sym=$(echo "$line" | awk '{print $NF}')
      [[ "$addr" =~ ^[0-9a-fA-F]+$ ]] || continue
      echo ""
      echo "──── $sym @ $addr ────"
      otool -arch "$ARCH" -tv "$BIN" 2>/dev/null | grep -A 90 "^${addr}" | head -95 || true
    done < <(nm -arch "$ARCH" "$BIN" 2>/dev/null | grep -i "$pat" | grep -E ' [tT] ' | head -3)
  done
  echo "=== DONE ==="
} | tee "$OUT"
echo "Saved: $OUT"
