@echo off
setlocal EnableExtensions
cd /d "%~dp0" || exit /b 1

rem Smart Home: start dashboard if needed, then expose ONLY the dashboard through ngrok.
rem Requirements: Windows PowerShell, ngrok.exe and a configured ngrok authtoken.
rem Use SMART_HOME_MODE=local to force START_DASHBOARD.bat instead of Docker.
rem Use DASHBOARD_PORT to override the default Docker host port (3000).

set "PUBLIC_PORT=3000"
if exist ".env" (
  for /f "usebackq eol=# tokens=1,* delims==" %%A in (".env") do (
    if /i "%%A"=="DASHBOARD_PORT" if not "%%B"=="" set "PUBLIC_PORT=%%B"
  )
)
if defined DASHBOARD_PORT set "PUBLIC_PORT=%DASHBOARD_PORT%"

set "NGROK_BIN="
if exist "%~dp0ngrok.exe" set "NGROK_BIN=%~dp0ngrok.exe"
if not defined NGROK_BIN (
  for /f "delims=" %%I in ('where ngrok.exe 2^>nul') do if not defined NGROK_BIN set "NGROK_BIN=%%I"
)
if not defined NGROK_BIN (
  echo [ERROR] ngrok.exe not found.
  echo Download ngrok for Windows: https://ngrok.com/download
  echo Put ngrok.exe next to START_NGROK.bat or add ngrok to PATH.
  echo Configure once: ngrok config add-authtoken YOUR_TOKEN
  pause
  exit /b 1
)

if not exist "docker-compose.yml" (
  echo [ERROR] Run this script from the smart-home project folder.
  pause
  exit /b 1
)

echo [INFO] Dashboard port: %PUBLIC_PORT%
call :is_ready
if not errorlevel 1 goto dashboard_ready

if /i "%SMART_HOME_MODE%"=="local" goto start_local
if /i "%SMART_HOME_MODE%"=="docker" goto start_docker
where docker.exe >nul 2>&1
if errorlevel 1 goto start_local
docker info >nul 2>&1
if errorlevel 1 goto start_local

:start_docker
echo [INFO] Starting Smart Home via Docker Compose...
docker compose up -d
if errorlevel 1 (
  echo [ERROR] Docker startup failed. Check: docker compose logs
  echo [TIP] Run docker compose up -d --build after editing code.
  pause
  exit /b 1
)
goto wait_for_dashboard

:start_local
if not exist "START_DASHBOARD.bat" (
  echo [ERROR] START_DASHBOARD.bat not found.
  pause
  exit /b 1
)
echo [INFO] Starting Smart Home in a separate terminal...
start "Smart Home Dashboard" /D "%CD%" cmd /k "call START_DASHBOARD.bat"

:wait_for_dashboard
echo [INFO] Checking http://127.0.0.1:%PUBLIC_PORT%/api/health ...
for /l %%N in (1,1,180) do (
  call :is_ready
  if not errorlevel 1 goto dashboard_ready
  timeout /t 3 /nobreak >nul
)
echo [ERROR] Dashboard did not become healthy. Review Docker or dashboard logs.
pause
exit /b 1

:dashboard_ready
rem Refuse to make a public tunnel unless the backend has an active dashboard password.
call :is_auth_configured
if errorlevel 1 (
  echo [ERROR] Dashboard authentication is NOT configured or not reachable.
  echo Set DASHBOARD_PASSWORD to at least 12 characters in backend\.env.
  echo Restart the dashboard and run this file again.
  pause
  exit /b 1
)

echo.
echo =============================================================
echo   SMART HOME - NGROK PUBLIC HTTPS

echo   Local dashboard: http://127.0.0.1:%PUBLIC_PORT%
echo   The https://...ngrok-free.app URL appears below.
echo   Use that HTTPS address on Android and iPhone for Web Push.
echo   Ctrl+C stops ngrok only; Docker/services remain running.
echo =============================================================
echo.
"%NGROK_BIN%" http %PUBLIC_PORT%
set "NGROK_EXIT=%errorlevel%"
if not "%NGROK_EXIT%"=="0" (
  echo.
  echo [ERROR] ngrok stopped with error %NGROK_EXIT%.
  echo [TIP] First-time setup: ngrok config add-authtoken YOUR_TOKEN
  pause
)
exit /b %NGROK_EXIT%

:is_ready
powershell.exe -NoProfile -NonInteractive -Command "try { $r=Invoke-WebRequest -UseBasicParsing -Uri 'http://127.0.0.1:%PUBLIC_PORT%/api/health' -TimeoutSec 2; if($r.StatusCode -eq 200) { exit 0 } } catch {}; exit 1" >nul 2>&1
exit /b %errorlevel%

:is_auth_configured
powershell.exe -NoProfile -NonInteractive -Command "try { $r=Invoke-RestMethod -Uri 'http://127.0.0.1:%PUBLIC_PORT%/api/auth/session' -TimeoutSec 4; if($r.configured -eq $true) { exit 0 } } catch {}; exit 1" >nul 2>&1
exit /b %errorlevel%
