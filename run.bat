@echo off
rem Launch VLC Redesign (no console window). Pass files/folders to play as arguments.
set "PYTHONPATH=%~dp0"
start "" "%~dp0.venv\Scripts\pythonw.exe" -m vlcredesign %*
