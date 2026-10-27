@echo off
setlocal
cd /d "%~dp0" || exit /b 1
if exist "backend\.venv\Scripts\python.exe" goto run_dashboard

rem Support both python.org and Microsoft Store installations.
set "DASHBOARD_PYTHON="
set "DASHBOARD_PYTHON_ARGS="
call :try_python py -3.13
call :try_python python
call :try_python python3
call :try_python python3.13
call :try_python "%LocalAppData%\Programs\Python\Python313\python.exe"
call :try_python "%ProgramFiles%\Python313\python.exe"
call :try_python "C:\Python313\python.exe"
if not defined DASHBOARD_PYTHON (
  echo Python 3.13 was not found. Check that python --version reports Python 3.13.x.
  echo If Python is installed, add it to PATH and reopen this terminal.
  exit /b 1
)

echo Creating the dashboard environment with %DASHBOARD_PYTHON%...
"%DASHBOARD_PYTHON%" %DASHBOARD_PYTHON_ARGS% -m venv "backend\.venv"
if errorlevel 1 (
  echo Could not create backend\.venv. See the Python error above.
  exit /b 1
)

:run_dashboard
rem Recover pip if an earlier virtual-environment creation was interrupted.
"backend\.venv\Scripts\python.exe" -m pip --version >nul 2>&1
if errorlevel 1 (
  "backend\.venv\Scripts\python.exe" -m ensurepip --upgrade
  if errorlevel 1 (
    echo Could not initialize pip in backend\.venv. See the Python error above.
    exit /b 1
  )
)
"backend\.venv\Scripts\python.exe" run_dashboard.py
exit /b %errorlevel%

:try_python
if defined DASHBOARD_PYTHON exit /b 0
"%~1" %~2 -c "import sys; sys.exit(0 if sys.version_info[:2] == (3, 13) else 1)" >nul 2>&1
if errorlevel 1 exit /b 0
set "DASHBOARD_PYTHON=%~1"
set "DASHBOARD_PYTHON_ARGS=%~2"
exit /b 0
