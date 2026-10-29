@echo off
setlocal EnableExtensions
cd /d "%~dp0" || exit /b 1

echo [INFO] Setting up Python 3.13 virtual environment for Smart Home backend.
set "PY_CMD="
py -3.13 -c "import sys; assert sys.version_info[:2] == (3,13)" >nul 2>&1
if not errorlevel 1 set "PY_CMD=py -3.13"
if not defined PY_CMD (
  python -c "import sys; assert sys.version_info[:2] == (3,13)" >nul 2>&1
  if not errorlevel 1 set "PY_CMD=python"
)
if not defined PY_CMD (
  echo [ERROR] Python 3.13 is required. Install it from python.org, then retry.
  pause
  exit /b 1
)
if not exist "backend\.venv\Scripts\python.exe" (
  %PY_CMD% -m venv "backend\.venv"
  if errorlevel 1 goto failed
)
set "PY=backend\.venv\Scripts\python.exe"
"%PY%" -m pip install --upgrade pip
if errorlevel 1 goto failed
if /i "%~1"=="--cuda" (
  echo [INFO] Installing CUDA 12.8 PyTorch wheels before other dependencies...
  "%PY%" -m pip install torch==2.7.1 torchvision==0.22.1 --index-url https://download.pytorch.org/whl/cu128
  if errorlevel 1 goto failed
)
"%PY%" -m pip install -r "backend\requirements-fall.txt"
if errorlevel 1 goto failed
if not exist "backend\.env" (
  copy /y "backend\.env.example" "backend\.env" >nul
  echo [ACTION REQUIRED] Edit backend\.env. Set DASHBOARD_PASSWORD to 12+ characters.
  echo [ACTION REQUIRED] Keep your MQTT / Telegram / VAPID keys in backend\.env.
)
echo.
"%PY%" -c "import sys, torch; print('Python:',sys.version.split()[0]); print('Torch:',torch.__version__); print('CUDA available:',torch.cuda.is_available()); print('GPU:',torch.cuda.get_device_name(0) if torch.cuda.is_available() else '(CPU mode)')"
echo.
echo [OK] Virtual environment prepared at backend\.venv
exit /b 0

:failed
echo [ERROR] Could not set up venv. Review pip output above.
pause
exit /b 1
