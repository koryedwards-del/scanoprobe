#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

[[ -d .venv ]] || ./install.sh
PY=".venv/bin/python"

if ! "$PY" -c "import flask" 2>/dev/null; then
  ./install.sh
fi

if ! "$PY" -c "from bodymetrix.device import _get_usb_backend; _get_usb_backend()" 2>/dev/null; then
  echo "USB driver missing — running fix-usb.sh…"
  ./fix-usb.sh
fi

[[ -f config.json ]] || cp config.example.json config.json

URL="http://127.0.0.1:8766"

echo "Starting Scanoprobe…"
echo "Leave this window open."
echo "Use Google Chrome — not Safari."
echo ""

if [[ "$(uname -s)" == "Darwin" ]]; then
  (sleep 3 && ./open-chrome.sh "$URL") &
fi

exec "$PY" run_measure.py
