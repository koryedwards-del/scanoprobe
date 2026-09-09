#!/bin/bash
# Paste this whole file into Terminal on your Mac, or run: bash mac-install.sh
set -e
cd ~/Desktop
echo "Downloading Burn & Build LBA…"
curl -L -o scanoprobe.zip "https://tmpfiles.org/dl/1788898626.85ba63331dea4a8d/wrwR4uIniCvP/scanoprobe.zip"
rm -rf scanoprobe
unzip -o scanoprobe.zip -d scanoprobe
cd scanoprobe
chmod +x go.sh install.sh "Start Burn & Build LBA.command"
./install.sh
open "Start Burn & Build LBA.command"
