#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

if ! command -v python3 >/dev/null 2>&1; then
  echo "Install Python 3 from https://www.python.org/downloads/ then run this again."
  exit 1
fi

echo "Installing…"
rm -rf .venv

if python3 -m venv .venv 2>/dev/null; then
  .venv/bin/pip install -q -r requirements.txt
else
  rm -rf .venv
  pip3 install -q -r requirements.txt
fi

if [[ ! -f config.json ]]; then
  cp config.example.json config.json
fi

echo "Done."
