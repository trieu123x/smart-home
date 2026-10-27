@echo off
setlocal
cd /d "%~dp0" || exit /b 1
if not exist "backend\.venv\Scripts\python.exe" (
  py -3.13 -m venv backend\.venv
  if errorlevel 1 (
    echo Install Python 3.13 with the Python launcher, then run this file again.
    exit /b 1
  )
)
"backend\.venv\Scripts\python.exe" run_dashboard.py
exit /b %errorlevel%
