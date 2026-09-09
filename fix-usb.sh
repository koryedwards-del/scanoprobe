#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

echo "Fixing USB driver for BodyMetrix probe…"

if [[ "$(uname -s)" == "Darwin" ]] && command -v brew >/dev/null 2>&1; then
  brew list libusb >/dev/null 2>&1 || brew install libusb
fi

[[ -d .venv ]] || ./install.sh
.venv/bin/pip install -q -r requirements.txt libusb-package

echo ""
echo "Checking USB…"
if .venv/bin/python -c "from bodymetrix.device import _get_usb_backend; _get_usb_backend(); print('USB driver OK')"; then
  .venv/bin/python -c "from bodymetrix.device import BodyMetrixProbe; print(BodyMetrixProbe().status().message)"
  echo ""
  echo "Done. Run: ./go.sh"
else
  echo "USB driver still not working. Send this screenshot to support."
  exit 1
fi
