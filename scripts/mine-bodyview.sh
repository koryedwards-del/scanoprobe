#!/usr/bin/env bash
# Static mine BodyView binary (app does NOT need to run or be licensed).
set -euo pipefail

echo "=== BodyView binary miner (static only — no launch) ==="
echo ""

APPS=(
  "/Applications/BodyView Professional.app"
  "/Applications/BodyViewProfessional.app"
  "/Applications/BodyView Pro.app"
  "$HOME/Applications/BodyView Professional.app"
)

FOUND=""
for app in "${APPS[@]}"; do
  if [[ -d "$app" ]]; then
    FOUND="$app"
    break
  fi
done

if [[ -z "$FOUND" ]]; then
  echo "NOT FOUND in usual locations."
  echo ""
  echo "Find it in Finder:"
  echo "  Applications → BodyView → right-click → Get Info"
  echo "  Copy the path, then run:"
  echo '  ./scripts/mine-bodyview.sh "/path/to/BodyView Professional.app"'
  exit 1
fi

if [[ $# -ge 1 && -d "$1" ]]; then
  FOUND="$1"
fi

echo "App: $FOUND"
echo ""

SEARCH='04d8|fbb7|0x04|0x81|0x01|bulk|interrupt|ctrl_transfer|libusb|IOUSB|USBDevice|BodyMetrix|IntelaMetrix|thickness|MEAS|SCAN|START|SEND|endpoint|vendor|0x40|0xc0|ioctl|pipe|write.*probe|read.*probe'

filter() {
  if command -v rg >/dev/null 2>&1; then
    rg -i "$1" || true
  else
    grep -iE "$1" || true
  fi
}

echo "=== Binaries / dylibs ==="
find "$FOUND" -type f \( -name '*.dylib' -o -name '*.so' -o -path '*/MacOS/*' \) 2>/dev/null \
  | head -40
echo ""

echo "=== USB / probe strings (top hits) ==="
find "$FOUND" -type f 2>/dev/null \
  | while read -r f; do
      file "$f" 2>/dev/null | grep -qiE 'mach-o|executable|bundle|dylib' || continue
      strings "$f" 2>/dev/null
    done \
  | filter "$SEARCH" \
  | sort -u \
  | head -120
echo ""

echo "=== Short hex-like tokens (possible USB payloads) ==="
find "$FOUND" -type f 2>/dev/null \
  | while read -r f; do
      file "$f" 2>/dev/null | grep -qiE 'mach-o|executable|bundle|dylib' || continue
      strings -n 4 "$f" 2>/dev/null
    done \
  | filter '^[0-9a-fA-F]{4,32}$' \
  | sort -u \
  | head -40
echo ""

echo "=== Frameworks linked (main executable) ==="
MAIN=$(find "$FOUND/Contents/MacOS" -maxdepth 1 -type f 2>/dev/null | head -1)
if [[ -n "$MAIN" && -f "$MAIN" ]]; then
  echo "Main: $MAIN"
  otool -L "$MAIN" 2>/dev/null | head -30 || echo "(otool not available)"
else
  echo "(no main executable found)"
fi
echo ""

echo "=== Plug-in / driver bundles ==="
find "$FOUND" -name '*.kext' -o -name '*USB*' -o -name '*Driver*' 2>/dev/null | head -20
echo ""

echo "Done — copy ALL output above and send it."
