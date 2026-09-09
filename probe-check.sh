#!/usr/bin/env bash
# Step A — USB baseline check. Run on your Mac, paste probe-report.txt back.
set -euo pipefail
cd "$(dirname "$0")"

REPORT="probe-report.txt"
PY=".venv/bin/python"

echo "══════════════════════════════════════════════════"
echo "  Burn & Build LBA — Probe Check (Step A)"
echo "══════════════════════════════════════════════════"
echo ""
echo "Use your NORMAL setup (USB-C hub + wand) for this run."
echo ""

[[ -d .venv ]] || ./install.sh
if ! "$PY" -c "from bodymetrix.device import _get_usb_backend; _get_usb_backend()" 2>/dev/null; then
  ./fix-usb.sh
fi

{
  echo "Burn & Build LBA — Probe Report"
  echo "Generated: $(date)"
  echo "Setup: USB-C hub (normal)"
  echo ""

  echo "─── STATUS ───"
  "$PY" scripts/probe_usb.py status || true
  echo ""

  echo "─── DEVICE INFO ───"
  "$PY" scripts/probe_usb.py describe || true
  echo ""

  echo "─── SEND TEST (20 seconds) ───"
  echo "When you see HOLD SEND below: gel → skin → press and hold SEND on wand."
  echo ""
  "$PY" scripts/probe_usb.py bx --seconds 20 || true
  echo ""

  echo "─── END ───"
} | tee "$REPORT"

echo ""
echo "Saved: $(pwd)/$REPORT"
echo ""
echo "Copy the entire file and paste it back in chat:"
echo "  open -a TextEdit $REPORT"
echo ""
