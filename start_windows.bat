@echo off
rem Startet AkustikMess. Beim ersten Start wird die Python-Umgebung eingerichtet.
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
    echo Richte Python-Umgebung ein ...
    py -3.12 -m venv .venv || python -m venv .venv || goto :nopython
    ".venv\Scripts\python.exe" -m pip install --upgrade pip
    ".venv\Scripts\python.exe" -m pip install -r requirements.txt || goto :error
)
start "" ".venv\Scripts\pythonw.exe" -m akustik
exit /b 0

:nopython
echo Python 3.11 oder neuer wurde nicht gefunden: https://www.python.org/downloads/
pause
exit /b 1

:error
echo Installation der Abhaengigkeiten fehlgeschlagen.
pause
exit /b 1
