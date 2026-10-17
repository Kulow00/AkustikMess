@echo off
setlocal
rem AkustikMess starten.
rem Heruntergeladene Dateien tragen eine Internet-Markierung. Weil AkustikMess (noch) nicht digital
rem signiert ist, kann Windows das Programm sonst blockieren. Die Markierung wird ausschliesslich
rem fuer die Dateien in diesem Ordner entfernt.
set "AKM_DIR=%~dp0"
powershell -NoProfile -NonInteractive -Command "Get-ChildItem -LiteralPath $env:AKM_DIR -Recurse -File | Unblock-File" >nul 2>&1
start "" "%~dp0AkustikMess.exe"
