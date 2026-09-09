#!/bin/bash
cd "$(dirname "$0")"
chmod +x go.sh install.sh 2>/dev/null || true
[[ -d .venv ]] || ./install.sh
./go.sh
read -r -p "Press Enter to close…"
