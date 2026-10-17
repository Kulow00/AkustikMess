#!/bin/bash
# AkustikMess starten.
# Heruntergeladene Dateien tragen unter macOS eine Quarantäne-Markierung. Weil AkustikMess (noch) nicht
# von Apple beglaubigt ist, verhindert Gatekeeper sonst den Start. Die Markierung wird ausschließlich für
# das Programm in diesem Ordner entfernt.
cd "$(dirname "$0")" || exit 1
xattr -dr com.apple.quarantine "AkustikMess.app" 2>/dev/null
open "AkustikMess.app"
