@echo off
setlocal
cd /d "%~dp0"
title FallGuard - MediaMTX Receiver
if not exist "mediamtx.yml" (
  echo [ERROR] Run SETUP_CAMERA_RECEIVER.bat first.
  pause
  exit /b 1
)
if not exist "tools\mediamtx.exe" (
  echo [ERROR] tools\mediamtx.exe missing. Run SETUP_CAMERA_RECEIVER.bat.
  pause
  exit /b 1
)
echo [RUN] MediaMTX local RTMP 1935 / RTSP 8554 - keep window open.
"tools\mediamtx.exe" mediamtx.yml
pause
