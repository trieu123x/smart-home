@echo off
setlocal
cd /d "%~dp0"
title FallGuard - Tailscale Funnel
set "TS=tailscale"
where tailscale >nul 2>&1
if errorlevel 1 (
  if exist "%ProgramFiles%\Tailscale\tailscale.exe" (
    set "TS=%ProgramFiles%\Tailscale\tailscale.exe"
  ) else (
    echo [ERROR] Tailscale CLI not found. Install and sign in to your own tailnet first.
    pause
    exit /b 1
  )
)
echo [STEP 1] Check Tailscale connection...
"%TS%" status
if errorlevel 1 goto fail
echo [STEP 2] Public website HTTPS 443 - FastAPI 127.0.0.1:8000
"%TS%" funnel --bg --https=443 http://127.0.0.1:8000
if errorlevel 1 goto fail
echo [STEP 3] Public RTMPS 8443 - RTMP MediaMTX 127.0.0.1:1935
"%TS%" funnel --bg --tls-terminated-tcp=8443 tcp://127.0.0.1:1935
if errorlevel 1 goto fail
echo [OK] Verify both entries below:
"%TS%" funnel status
echo [INFO] On Streamlabs use server rtmps://YOUR-NODE.YOUR-TAILNET.ts.net:8443/live and your publisher stream key.
pause
exit /b 0
:fail
echo [ERROR] Funnel could not start. Check permissions, MagicDNS, HTTPS and Funnel approval in the Admin console.
pause
exit /b 1
