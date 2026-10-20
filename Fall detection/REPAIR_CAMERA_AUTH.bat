@echo off
setlocal EnableExtensions DisableDelayedExpansion
cd /d "%~dp0"
title FallGuard - Repair RTSP Camera Authentication

echo ==== FALLGUARD - SUA LOI RTSP 401 UNAUTHORIZED ====
echo Tat cua so START_WINDOWS.bat truoc khi tiep tuc.
echo Giu cua so MediaMTX dang chay. KHONG can setup lai Larix.
echo.

if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" -m fallguard.camera_receiver_setup repair
) else (
  py -3 -m fallguard.camera_receiver_setup repair
)
if errorlevel 1 (
  echo [ERROR] Khong sua duoc. Kiem tra mediamtx.yml va .env.
  pause
  exit /b 1
)
echo.
echo [NEXT] Mo START_WINDOWS.bat va bam Ket noi camera tren dashboard.
pause
