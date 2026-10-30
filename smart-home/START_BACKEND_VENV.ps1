$ErrorActionPreference = 'Stop'
$root = $PSScriptRoot
$backend = Join-Path $root 'backend'
$python = Join-Path $backend '.venv\Scripts\python.exe'
$envFile = Join-Path $backend '.env'

try {
    if (-not (Test-Path -LiteralPath $python)) {
        throw 'Python venv missing. Run SETUP_VENV.bat first.'
    }
    if (-not (Test-Path -LiteralPath $envFile)) {
        throw 'Missing backend\.env. Copy backend\.env.example and configure it.'
    }
    # Use a Python file rather than `python -c`: Windows PowerShell 5.1
    # may remove embedded double quotes when forwarding native arguments.
    $passwordCheck = Join-Path $backend 'check_dashboard_password.py'
    if (-not (Test-Path -LiteralPath $passwordCheck)) {
        throw 'Missing backend\check_dashboard_password.py. Reapply the startup patch.'
    }
    & $python $passwordCheck
    if ($LASTEXITCODE -ne 0) {
        throw 'Dashboard password preflight failed. See the error above.'
    }

    $pose = Join-Path $backend 'models\pose\yolo11n-pose.pt'
    $fall = Join-Path $backend 'models\fall\best_fall_lstm.pth'
    $adb = Join-Path $backend 'tools\adb\adb.exe'
    if (-not (Test-Path -LiteralPath $pose)) { Write-Warning 'Missing pose model; fall detection might not work.' }
    if (-not (Test-Path -LiteralPath $fall)) { Write-Warning 'Missing LSTM model; fall detection might not work.' }
    if (-not (Test-Path -LiteralPath $adb)) { Write-Warning 'ADB not found; USB camera might not work.' }

    $env:YOLO_AUTOINSTALL = 'false'
    $env:FALL_ASSETS_DIR = $backend
    Write-Host '[INFO] FastAPI + AI + MQTT + Web Push use Windows venv.'
    Write-Host '[INFO] Binding backend to 0.0.0.0:8000 for Docker Desktop.'
    Write-Host '[SECURITY] Restrict TCP 8000 in Windows Firewall; publish only dashboard 3000 with ngrok.'
    Set-Location -LiteralPath $backend
    & $python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 1
    if ($LASTEXITCODE -ne 0) { throw "FastAPI exited with status $LASTEXITCODE" }
} catch {
    Write-Host ('[ERROR] ' + $_.Exception.Message) -ForegroundColor Red
    exit 1
}
