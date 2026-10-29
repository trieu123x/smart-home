$ErrorActionPreference = 'Stop'
$root = $PSScriptRoot
Set-Location -LiteralPath $root

function Fail([string]$message) {
    Write-Host ('[ERROR] ' + $message) -ForegroundColor Red
    exit 1
}
function IsHealthy([string]$url) {
    try {
        $response = Invoke-WebRequest -UseBasicParsing -Uri $url -TimeoutSec 3
        if ($response.StatusCode -ne 200) { return $false }
        $body = $response.Content | ConvertFrom-Json
        return ($body.status -eq 'ok')
    } catch {
        return $false
    }
}
function AwaitHealth([string]$url, [int]$maxSeconds, [string]$service) {
    $start = Get-Date
    $attempt = 0
    while (((Get-Date) - $start).TotalSeconds -lt $maxSeconds) {
        if (IsHealthy $url) { return $true }
        $attempt++
        if (($attempt % 5) -eq 0) {
            $elapsedSeconds = [int](((Get-Date) - $start).TotalSeconds)
            Write-Host ("[WAIT] Waiting for {0}... {1}s" -f $service, $elapsedSeconds)
        }
        Start-Sleep -Seconds 2
    }
    return $false
}

try {
    $composeFile = Join-Path $root 'docker-compose.yml'
    $python = Join-Path $root 'backend\.venv\Scripts\python.exe'
    $backendEnv = Join-Path $root 'backend\.env'
    if (-not (Test-Path -LiteralPath $composeFile)) { Fail 'docker-compose.yml not found.' }
    if (-not (Test-Path -LiteralPath $python)) { Fail 'Missing backend\.venv. Run SETUP_VENV.bat first.' }
    if (-not (Test-Path -LiteralPath $backendEnv)) { Fail 'Missing backend\.env.' }
    if (-not (Get-Command docker -ErrorAction SilentlyContinue)) { Fail 'Docker CLI not found. Install Docker Desktop.' }

    & docker info 2>$null | Out-Null
    if ($LASTEXITCODE -ne 0) { Fail 'Docker Desktop is not running.' }

    # Do not accidentally detach the existing backend from its old database.
    $oldBackends = @(& docker ps --filter 'name=smarthome-backend' --format '{{.Names}}' 2>$null)
    if ($LASTEXITCODE -ne 0) { Fail 'Cannot inspect running Docker containers.' }
    if ($oldBackends.Count -gt 0) {
        Fail 'Old smarthome-backend container is still running. Stop/migrate it first; do NOT run docker compose down -v.'
    }

    $backendUrl = 'http://127.0.0.1:8000/api/health'
    Write-Host '[1/3] Checking backend on Windows port 8000...'
    if (-not (IsHealthy $backendUrl)) {
        $backendScript = Join-Path $root 'START_BACKEND_VENV.ps1'
        if (-not (Test-Path -LiteralPath $backendScript)) { Fail 'Missing START_BACKEND_VENV.ps1.' }
        Write-Host '[INFO] Starting FastAPI from backend\.venv in a new PowerShell window...'
        $arguments = '-NoExit -NoProfile -ExecutionPolicy Bypass -File "' + $backendScript + '"'
        Start-Process -FilePath 'powershell.exe' -ArgumentList $arguments -WorkingDirectory $root | Out-Null
        if (-not (AwaitHealth $backendUrl 120 'backend')) {
            Fail 'Backend did not become healthy. Read the new PowerShell backend window for the error.'
        }
    }
    Write-Host '[OK] FastAPI is healthy on port 8000.' -ForegroundColor Green

    Write-Host '[2/3] Starting Next.js dashboard in Docker...'
    $images = @(& docker images --format '{{.Repository}}:{{.Tag}}' 'smarthome-dashboard:hybrid')
    if ($LASTEXITCODE -ne 0) { Fail 'Cannot inspect Docker images.' }
    $imageExists = ($images -contains 'smarthome-dashboard:hybrid')
    if ($imageExists) {
        & docker compose up -d --remove-orphans dashboard
    } else {
        Write-Host '[INFO] Dashboard image not found; building it now...'
        & docker compose up -d --build --remove-orphans dashboard
    }
    if ($LASTEXITCODE -ne 0) { Fail 'Docker dashboard startup failed. Run: docker compose logs dashboard' }

    $port = 3000
    $rootEnv = Join-Path $root '.env'
    if (Test-Path -LiteralPath $rootEnv) {
        foreach ($line in (Get-Content -LiteralPath $rootEnv)) {
            if ($line -match '^\s*DASHBOARD_PORT\s*=\s*["'']?(\d+)["'']?\s*(?:#.*)?$') {
                $port = [int]$Matches[1]
            }
        }
    }
    if ($env:DASHBOARD_PORT) {
        $parsedPort = 0
        if (-not [int]::TryParse($env:DASHBOARD_PORT, [ref]$parsedPort)) { Fail 'DASHBOARD_PORT must be a number.' }
        $port = $parsedPort
    }
    if ($port -lt 1 -or $port -gt 65535) { Fail 'DASHBOARD_PORT must be in the range 1-65535.' }

    Write-Host ("[3/3] Checking dashboard on port {0}..." -f $port)
    $dashboardUrl = "http://127.0.0.1:$port/api/health"
    if (-not (AwaitHealth $dashboardUrl 120 'dashboard')) {
        Write-Host '[TIP] Inspect logs with: docker compose logs --tail 80 dashboard'
        Fail 'Dashboard did not become healthy.'
    }
    Write-Host ("[OK] Smart Home hybrid is running at http://127.0.0.1:{0}" -f $port) -ForegroundColor Green
    Write-Host '[TIP] For HTTPS and mobile Web Push, run START_NGROK.bat.'
    exit 0
} catch {
    Fail $_.Exception.Message
}
