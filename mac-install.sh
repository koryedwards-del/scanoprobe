#!/bin/bash
# Paste this whole file into Terminal on your Mac, or run: bash mac-install.sh
set -e
cd ~/Desktop
echo "Downloading Burn & Build LBA…"
curl -L -o burn-build-lba.zip "https://tmpfiles.org/dl/1788898626.85ba63331dea4a8d/wrwR4uIniCvP/burn-build-lba.zip"
rm -rf burn-build-lba
unzip -o burn-build-lba.zip -d burn-build-lba
cd burn-build-lba
chmod +x go.sh install.sh "Start Burn & Build LBA.command"
./install.sh
open "Start Burn & Build LBA.command"
