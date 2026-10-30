@echo off
setlocal
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0START_SMART_HOME.ps1" %*
exit /b %errorlevel%
