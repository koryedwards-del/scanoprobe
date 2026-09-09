#!/usr/bin/env bash
# Open the app in Google Chrome (never Safari — probe needs Chrome).
URL="${1:-http://127.0.0.1:8765}"

if /usr/bin/osascript -e 'id of application "Google Chrome"' >/dev/null 2>&1; then
  /usr/bin/osascript <<EOF
tell application "Google Chrome"
  activate
  if (count of windows) = 0 then
    make new window
  end if
  open location "$URL"
end tell
EOF
  exit 0
fi

for app in "/Applications/Google Chrome.app" "/Applications/Chromium.app"; do
  if [[ -d "$app" ]]; then
    open -a "$app" "$URL"
    exit 0
  fi
done

echo ""
echo "============================================"
echo "  Open GOOGLE CHROME (not Safari):"
echo "  $URL"
echo "============================================"
echo ""
