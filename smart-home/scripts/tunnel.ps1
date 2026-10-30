<#
.SYNOPSIS
  Expose the smart-home backend (port 8000) and frontend (port 3000) over two
  Cloudflare quick tunnels, so the dashboard can be opened from a phone on 4G.

.DESCRIPTION
  1. Checks that cloudflared is installed, DASHBOARD_PASSWORD is set (12+ characters)
     and ports 8000 and 3000 are free.
  2. Starts the frontend tunnel and reads its https://*.trycloudflare.com URL.
  3. Starts the backend with CORS_ORIGINS=<frontend url>, then verifies on the running
     backend that login is enforced and the default X-Device-Key is rejected. Only then
     is the backend tunnel opened.
  4. Builds and starts the frontend (production server, not the dev server) with
     NEXT_PUBLIC_API_URL=<backend url>. Environment variables override .env files.
  5. Prints both URLs. Ctrl+C stops all four processes.

  Quick tunnel URLs are random on every run. Run from anywhere:
    powershell -ExecutionPolicy Bypass -File smart-home\scripts\tunnel.ps1
#>
$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $PSScriptRoot
$backendDir = Join-Path $root "backend"
$frontendDir = Join-Path $root "frontend"
$python = Join-Path $backendDir ".venv\Scripts\python.exe"
$logDir = Join-Path $env:TEMP "smarthome-tunnel"
$backendLocal = "http://127.0.0.1:8000"
$defaultDeviceKey = "esp32-secret-key"

function Fail([string]$message) {
    Write-Host $message -ForegroundColor Red
    exit 1
}

function Get-DotEnvValue([string]$path, [string]$name) {
    # Best effort only; the real check is done against the running backend below
    if (-not (Test-Path $path)) { return "" }
    $value = ""
    foreach ($line in Get-Content $path) {
        if ($line -match "^\s*$name\s*=\s*(.*)$") {
            $value = ($Matches[1] -replace "\s+#.*$", "").Trim().Trim('"').Trim("'")
        }
    }
    return $value
}

function Test-PortInUse([int]$port) {
    return [bool](Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue)
}

function Get-StatusCode([string]$url, [hashtable]$headers = @{}) {
    try {
        return [int](Invoke-WebRequest $url -Headers $headers -UseBasicParsing -TimeoutSec 5).StatusCode
    }
    catch [System.Net.WebException] {
        if ($_.Exception.Response) { return [int]$_.Exception.Response.StatusCode }
        return 0
    }
}

function Stop-Tree($process) {
    if ($process -and -not $process.HasExited) {
        # npm and cloudflared spawn children; /T stops the whole tree. A process that
        # already exited after Ctrl+C makes taskkill write to stderr, which must not
        # abort the cleanup loop under ErrorActionPreference=Stop.
        try { & taskkill.exe /PID $process.Id /T /F *> $null } catch { }
    }
}

function Start-Tunnel([int]$port, [string]$name) {
    $log = Join-Path $logDir "tunnel-$name.log"
    Remove-Item $log, "$log.out" -ErrorAction SilentlyContinue
    # cloudflared prints the URL on stderr
    $process = Start-Process cloudflared -PassThru -WindowStyle Hidden `
        -ArgumentList "tunnel", "--no-autoupdate", "--url", "http://localhost:$port" `
        -RedirectStandardError $log -RedirectStandardOutput "$log.out"
    return @{ Process = $process; Log = $log }
}

function Wait-TunnelUrl($tunnel) {
    $deadline = (Get-Date).AddSeconds(60)
    while ((Get-Date) -lt $deadline) {
        if ($tunnel.Process.HasExited) { throw "cloudflared exited early, see $($tunnel.Log)" }
        if (Test-Path $tunnel.Log) {
            $match = Select-String -Path $tunnel.Log -Pattern "https://[a-z0-9-]+\.trycloudflare\.com" |
                Select-Object -First 1
            if ($match) { return $match.Matches[0].Value }
        }
        Start-Sleep -Milliseconds 500
    }
    throw "No trycloudflare.com URL after 60 s, see $($tunnel.Log)"
}

# ---- 1. Preconditions
if (-not (Get-Command cloudflared -ErrorAction SilentlyContinue)) {
    Fail "cloudflared is not installed. Run: winget install Cloudflare.cloudflared"
}
if (-not (Test-Path $python)) { Fail "Backend venv not found at $python. See CLAUDE.md for install steps." }
$password = $env:DASHBOARD_PASSWORD
if (-not $password) { $password = Get-DotEnvValue (Join-Path $backendDir ".env") "DASHBOARD_PASSWORD" }
if (-not $password) { Fail "DASHBOARD_PASSWORD is empty in backend\.env. Set it before exposing the dashboard." }
if ($password.Length -lt 12) { Fail "DASHBOARD_PASSWORD must be at least 12 characters before exposing the dashboard." }
foreach ($port in 8000, 3000) {
    if (Test-PortInUse $port) { Fail "Port $port is already in use. Stop that app first (FallGuard and Anti-theft also use 8000)." }
}

New-Item -ItemType Directory -Force $logDir | Out-Null
$processes = @()
try {
    # ---- 2. Frontend tunnel first: the backend needs its URL for CORS
    Write-Host "Starting frontend tunnel..."
    $frontendTunnel = Start-Tunnel 3000 "frontend"
    $processes += $frontendTunnel.Process
    $frontendUrl = Wait-TunnelUrl $frontendTunnel

    # ---- 3. Backend (child processes inherit these variables). No access log, so
    # tokens in the /ws query string are not printed.
    $env:CORS_ORIGINS = "$frontendUrl,http://localhost:3000"
    $processes += Start-Process $python -PassThru -WorkingDirectory $backendDir -NoNewWindow `
        -ArgumentList "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "8000", "--no-access-log"

    Write-Host "Waiting for the backend..."
    $deadline = (Get-Date).AddSeconds(60)
    while ((Get-StatusCode "$backendLocal/api/health") -ne 200) {
        if ((Get-Date) -gt $deadline) { throw "Backend did not answer /api/health within 60 s." }
        Start-Sleep -Milliseconds 500
    }
    # Verify what the backend actually loaded instead of trusting our .env parsing
    if ((Get-StatusCode "$backendLocal/api/auth/me") -ne 401) {
        throw "The backend accepts dashboard requests without a token (is DASHBOARD_PASSWORD loaded?). Not exposing it."
    }
    $probe = Get-StatusCode "$backendLocal/api/devices/__tunnel_probe__/commands" @{ "X-Device-Key" = $defaultDeviceKey }
    if ($probe -ne 401) {
        throw "DEVICE_API_KEY is still the default '$defaultDeviceKey'. Set a long random key in backend\.env (and in any HTTP device) first."
    }

    Write-Host "Starting backend tunnel..."
    $backendTunnel = Start-Tunnel 8000 "backend"
    $processes += $backendTunnel.Process
    $backendUrl = Wait-TunnelUrl $backendTunnel

    # ---- 4. Frontend: production build, since the dev server should not face the Internet.
    # NEXT_PUBLIC_API_URL is baked in at build time.
    $env:NEXT_PUBLIC_API_URL = $backendUrl
    Write-Host "Building the frontend (about a minute)..."
    $build = Start-Process "npm.cmd" -PassThru -Wait -WorkingDirectory $frontendDir -NoNewWindow `
        -ArgumentList "run", "build"
    if ($build.ExitCode -ne 0) { throw "npm run build failed (exit $($build.ExitCode))." }
    $processes += Start-Process "npm.cmd" -PassThru -WorkingDirectory $frontendDir -NoNewWindow `
        -ArgumentList "run", "start"

    # ---- 5. Report and wait for Ctrl+C
    Write-Host ""
    Write-Host "Dashboard (open on your phone): $frontendUrl" -ForegroundColor Green
    Write-Host "Backend API:                    $backendUrl" -ForegroundColor Green
    Write-Host "URLs change on every run. Press Ctrl+C to stop all processes."
    while ($true) {
        foreach ($process in $processes) {
            if ($process.HasExited) { throw "A process exited (PID $($process.Id)); stopping the rest." }
        }
        Start-Sleep -Seconds 1
    }
}
finally {
    Write-Host "Stopping tunnels, backend and frontend..."
    foreach ($process in $processes) { Stop-Tree $process }
}
