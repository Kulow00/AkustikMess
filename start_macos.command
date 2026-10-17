#!/bin/bash
# Startet AkustikMess unter macOS. Beim ersten Start wird die Python-Umgebung eingerichtet.
# Einmalig ausführbar machen:  chmod +x start_macos.command
cd "$(dirname "$0")" || exit 1
if [ ! -x ".venv/bin/python" ]; then
    echo "Richte Python-Umgebung ein ..."
    python3 -m venv .venv || { echo "Python 3.11+ fehlt: https://www.python.org/downloads/"; exit 1; }
    .venv/bin/python -m pip install --upgrade pip
    .venv/bin/python -m pip install -r requirements.txt || exit 1
fi
exec .venv/bin/python -m akustik
