#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
OUT="${ROOT}/bodyview-decode-mine.txt"
APPS=("/Applications/BodyViewPersonal.app" "/Applications/BodyView Professional.app" "$HOME/Applications/BodyViewPersonal.app")
FOUND=""
for app in "${APPS[@]}"; do [[ -d "$app" ]] && FOUND="$app" && break; done
[[ -z "$FOUND" ]] && echo "BodyView not found in Applications" && exit 1
SYM_GREP='readbx|MultipleSignal|thickness|Thickness|depth|Depth|envelope|Envelope|peak|Peak|ascan|AScan|fatMuscle|subcut|millimeter|binWidth|sampleRate|gain|bodymetrix|BodyMetrix|parsePacket|decode|header'
STR_GREP='thickness|millimeter|depth|envelope|peak|ascan|fat.muscle|subcut|readbx|MultipleSignal|0\.1|bin|sample.rate|gain|04d8|fbb7|bodymetrix'
BINS=()
while IFS= read -r f; do
  file "$f" 2>/dev/null | grep -qiE 'mach-o|executable|bundle|dylib' && BINS+=("$f")
done < <(find "$FOUND" -type f 2>/dev/null | sort -u)
{
  echo "BodyView DECODE miner — $(date)"
  echo "App: $FOUND"
  echo ""
  echo "=== SYMBOLS ==="
  for BIN in "${BINS[@]}"; do
    H=$(nm -arch all "$BIN" 2>/dev/null | grep -iE "$SYM_GREP" | sort -u || true)
    [[ -n "$H" ]] && echo "--- $BIN ---" && echo "$H" && echo ""
  done
  echo "=== DEMANGLED ==="
  for BIN in "${BINS[@]}"; do
    nm -arch all "$BIN" 2>/dev/null | grep -iE "$SYM_GREP" | awk '{print $NF}' | sort -u | while read -r sym; do
      echo "$BIN :: $(c++filt "$sym" 2>/dev/null || echo "$sym")"
    done
  done | sort -u | head -120
  echo ""
  echo "=== STRINGS ==="
  for BIN in "${BINS[@]}"; do strings "$BIN" 2>/dev/null; done | grep -iE "$STR_GREP" | sort -u | head -200
  echo ""
  echo "=== DISASM (readbx / thickness) ==="
  for BIN in "${BINS[@]}"; do
    nm -arch all "$BIN" 2>/dev/null | grep -iE 'readbx|MultipleSignal|thickness|envelope' | awk '{print $NF}' | sort -u | while read -r sym; do
      echo "──── $sym ────"
      c++filt "$sym" 2>/dev/null || true
      otool -arch all -tv "$BIN" 2>/dev/null | grep -A 60 "<${sym}>" | head -65 || true
    done
  done
  echo "DONE"
} | tee "$OUT"
echo "Saved: $OUT"
open -a TextEdit "$OUT"
