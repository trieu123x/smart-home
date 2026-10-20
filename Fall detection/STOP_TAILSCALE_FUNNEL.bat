@echo off
setlocal
cd /d "%~dp0"
title FallGuard - Stop Tailscale Funnel
set "TS=tailscale"
where tailscale >nul 2>&1
if errorlevel 1 if exist "%ProgramFiles%\Tailscale\tailscale.exe" set "TS=%ProgramFiles%\Tailscale\tailscale.exe"
echo [STOP] Disable ONLY the two published FallGuard services.
"%TS%" funnel --https=443 off
"%TS%" funnel --tls-terminated-tcp=8443 off
"%TS%" funnel status
pause
