@echo off
setlocal EnableExtensions DisableDelayedExpansion
cd /d "%~dp0"
title FallGuard - Ngrok tunnel only
set "PORT=8000"
if not "%~1"=="" set "PORT=%~1"
set "NGROK=%~dp0ngrok.exe"
if not exist "%NGROK%" (
  where ngrok.exe >nul 2>&1
  if errorlevel 1 (
    echo [ERROR] Khong tim thay ngrok.exe trong thu muc BAT hoac PATH.
    pause
    exit /b 1
  )
  set "NGROK=ngrok.exe"
)
echo [NGROK] Mo tunnel den http://127.0.0.1:%PORT%
echo [NGROK] Chay start-windows.bat trong cua so khac.
echo [NGROK] Nhan Ctrl+C de dung tunnel.
"%NGROK%" http %PORT%
if errorlevel 1 (
  echo [ERROR] Ngrok gap loi. Kiem tra authtoken va ket noi Internet.
  pause
)
