@echo off
setlocal
cd /d "%~dp0"
title FallGuard - Larix Setup
set "PY=python"
if exist ".venv\Scripts\python.exe" set "PY=.venv\Scripts\python.exe"
if exist "mediamtx.yml" (
  echo [INFO] Existing mediamtx.yml found. Not overwriting credentials.
) else (
  "%PY%" -m fallguard.camera_receiver_setup setup
  if errorlevel 1 goto fail
)
"%PY%" -m fallguard.camera_receiver_setup download
if errorlevel 1 goto fail
if exist "LARIX_CONNECTION.txt" (
  start "" notepad "LARIX_CONNECTION.txt"
) else (
  echo [INFO] Existing private MediaMTX configuration kept. Use saved Streamlabs credentials.
)
echo [OK] Finish Tailscale setup, then run RUN_MEDIAMTX.bat, START_WINDOWS.bat and RUN_TAILSCALE_FUNNEL.bat.
pause
exit /b 0
:fail
echo [ERROR] See messages above. If MediaMTX download fails, download it manually from the official release.
pause
exit /b 1
