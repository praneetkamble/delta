@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Delta is not installed yet.
  echo Run:  powershell -ExecutionPolicy Bypass -File install.ps1
  pause
  exit /b 1
)
".venv\Scripts\python.exe" -m delta %*
if errorlevel 1 pause
