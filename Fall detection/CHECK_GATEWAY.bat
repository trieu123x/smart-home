@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Missing .venv\Scripts\python.exe. Run START_WINDOWS.bat once.
  pause
  exit /b 1
)
if /I "%~1"=="test" (
  ".venv\Scripts\python.exe" check_gateway.py --send-test
) else (
  ".venv\Scripts\python.exe" check_gateway.py
)
pause
