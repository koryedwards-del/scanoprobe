#!/usr/bin/env bash
# Search BodyView install for USB / probe clues (run on your Mac).
set -euo pipefail

echo "Looking for BodyView…"
APPS=(
  "/Applications/BodyView Professional.app"
  "/Applications/BodyViewProfessional.app"
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
  echo "BodyView app not found in usual locations."
  echo "Find it in Finder → right-click BodyView → Get Info → copy path."
  exit 1
fi

echo "Found: $FOUND"
BIN="$FOUND/Contents/MacOS"
echo ""
echo "=== USB / probe strings ==="
find "$FOUND" -type f \( -perm +111 -o -name '*.dylib' -o -name '*.so' \) 2>/dev/null \
  | while read -r f; do strings "$f" 2>/dev/null; done \
  | rg -i '04d8|fbb7|libusb|usb|bulk|interrupt|ctrl|meas|edwards|bodymetrix|thickness|mm' \
  | sort -u | head -80

echo ""
echo "=== Container / prefs ==="
CONTAINER="$HOME/Library/Containers/intelametrix.com.BodyViewProfessional"
if [[ -d "$CONTAINER" ]]; then
  find "$CONTAINER" -name '*.plist' -o -name '*.json' -o -name '*.xml' 2>/dev/null | head -20
  rg -i 'edwards|formula|thigh|waist|hip|mm' "$CONTAINER" 2>/dev/null | head -30 || true
else
  echo "(no sandbox container found)"
fi

echo ""
echo "Done. Copy ALL output above and send it."
