#!/bin/bash
# Baut den macOS-Installer (.pkg) auf einem Mac.
# Voraussetzung: Python 3.12 von python.org, Xcode-Kommandozeilenwerkzeuge (xcode-select --install).
#   chmod +x tools/build_macos.sh && tools/build_macos.sh
set -euo pipefail
cd "$(dirname "$0")/.."
if [ ! -x .venv/bin/python ]; then
    python3 -m venv .venv
    .venv/bin/python -m pip install --upgrade pip
    .venv/bin/python -m pip install -r requirements.txt pytest pyinstaller cryptography
fi
export QT_QPA_PLATFORM=offscreen   # Oberflächentests ohne Bildschirm
.venv/bin/python tools/release.py build
echo
echo "Den erzeugten .pkg-Installer aus release_build/ auf den Rechner mit dem Signaturschlüssel kopieren"
echo "und dort mit 'python tools/release.py add-asset --platform macos --file …' veröffentlichen."
