#!/usr/bin/env bash
# One script — gel, skin, hold SEND. That's it.
set -euo pipefail
cd "$(dirname "$0")"

echo ""
echo "  ══════════════════════════════════════"
echo "    BURN & BUILD — wand test"
echo "  ══════════════════════════════════════"
echo ""
echo "  Before we start:"
echo "    1. Wand plugged DIRECT into Mac (no hub)"
echo "    2. Unplug wand → wait 3 seconds → plug back in"
echo "    3. Put gel on skin, wand on thigh or waist"
echo ""
read -r -p "  Press ENTER when ready… " _
echo ""

[[ -d .venv ]] || ./install.sh
PY=".venv/bin/python"

echo "  Hold SEND on the wand now (up to 20 seconds)…"
echo ""

if "$PY" scripts/probe_usb.py bx --seconds 20; then
  echo ""
  echo "  ✓ Done. If you see a mm number above, the wand is working."
  echo ""
  read -r -p "  Start the app in Chrome? (y/n) " START
  case "$(echo "$START" | tr '[:upper:]' '[:lower:]')" in
    y|yes) ./go.sh ;;
  esac
else
  echo ""
  echo "  ✗ No reading. Unplug wand, wait 3s, replug, run again:"
  echo "      ./wand.sh"
  echo ""
fi
