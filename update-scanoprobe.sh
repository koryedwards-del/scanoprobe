#!/usr/bin/env bash
# Pull Scanoprobe-style measurement stack to Mac Desktop copy.
set -euo pipefail
cd "$(dirname "$0")"

echo "Updating Scanoprobe measurement mode…"

FILES=(
  bodymetrix/scanoprobe.py
  bodymetrix/device.py
  bodymetrix/app.py
  bodymetrix/amode.py
  scripts/probe_usb.py
  scripts/analyze_capture.py
  static/app.js
  templates/index.html
  config.example.json
)

for f in "${FILES[@]}"; do
  [[ -f "$f" ]] && echo "  ok $f"
done

if [[ ! -f config.json ]]; then
  cp config.example.json config.json
else
  python3 -c "
import json
from pathlib import Path
p = Path('config.json')
cfg = json.loads(p.read_text())
cfg['measurement_mode'] = 'scanoprobe'
p.write_text(json.dumps(cfg, indent=2) + '\n')
"
fi

echo ""
echo "Done. Restart ./go.sh then test:"
echo "  .venv/bin/python scripts/probe_usb.py send --seconds 30"
echo "  (press SEND on wand while on skin)"
