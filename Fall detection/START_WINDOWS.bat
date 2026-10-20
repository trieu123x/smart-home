@echo off
setlocal EnableExtensions DisableDelayedExpansion
cd /d "%~dp0"
title FallGuard - CCTV AI Server

echo ==== FALLGUARD - SERVER CAMERA AND AI ====

if not exist ".env" (
  echo [SETUP] Chua co .env. Dang tao tu .env.example...
  copy /y ".env.example" ".env" >nul
  echo [SETUP] Mo .env bang Notepad, dien FALLGUARD_PASSWORD ^(it nhat 12 ky tu^), luu va chay lai.
  start "" notepad.exe ".env"
  pause
  exit /b 1
)

if exist ".venv\Scripts\python.exe" goto install

set "PY_LAUNCHER=py -3.13"
py -3.13 --version >nul 2>&1
if not errorlevel 1 goto create
set "PY_LAUNCHER=py -3.12"
py -3.12 --version >nul 2>&1
if not errorlevel 1 goto create
set "PY_LAUNCHER=py -3.11"
py -3.11 --version >nul 2>&1
if not errorlevel 1 goto create
set "PY_LAUNCHER=python"
python --version >nul 2>&1
if errorlevel 1 goto no_python

:create
%PY_LAUNCHER% -m venv .venv
if errorlevel 1 goto failed

:install
".venv\Scripts\python.exe" -c "import sys,struct; assert (3,11) <= sys.version_info[:2] <= (3,13); assert struct.calcsize('P')==8"
if errorlevel 1 goto no_python

echo [GPU] Kiem tra PyTorch va CUDA (se nang cap ban CPU neu co NVIDIA)...
".venv\Scripts\python.exe" -m fallguard.torch_setup
if errorlevel 1 goto failed

if exist ".venv\fallguard-cloudcam-gpu-v3" goto run
if exist ".venv\fallguard-cctv-deps-v1" goto run
echo [SETUP] Dang cai cac goi FastAPI, Ultralytics, OpenCV...
".venv\Scripts\python.exe" -m pip install --upgrade pip
if errorlevel 1 goto failed
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 goto failed
echo OK>".venv\fallguard-cctv-deps-v1"

:run
".venv\Scripts\python.exe" -m fallguard.camera_receiver_setup diagnose
".venv\Scripts\python.exe" -m fallguard.start
if errorlevel 1 goto failed
goto end

:no_python
echo Can Python 3.11, 3.12 hoac 3.13 ban 64-bit.
goto end
:failed
echo [ERROR] Cai dat hoac khoi dong that bai; vui long chup loi tren man hinh.
:end
pause
