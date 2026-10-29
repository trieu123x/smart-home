@echo off
setlocal EnableExtensions
cd /d "%~dp0" || exit /b 1
where docker.exe >nul 2>&1
if errorlevel 1 (
  echo [ERROR] Docker Desktop is required.
  pause
  exit /b 1
)
echo [INFO] Rebuilding only Next.js in Docker. Backend venv will not be modified.
docker compose up -d --build --remove-orphans dashboard
if errorlevel 1 (
  echo [ERROR] Frontend build failed.
  pause
  exit /b 1
)
echo [OK] Frontend rebuilt. Verify http://localhost:3000
exit /b 0
