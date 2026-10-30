# Smart Home Hybrid: start backend + dashboard, then expose ONLY dashboard via ngrok.
# Compatible with Windows PowerShell 5.1.
$ErrorActionPreference = 'Stop'
$root = $PSScriptRoot
Set-Location -LiteralPath $root

function Fail([string]$message) {
    Write-Host ('[ERROR] ' + $message) -ForegroundColor Red
    exit 1
}

try {
    $startup = Join-Path $root 'START_SMART_HOME.ps1'
    if (-not (Test-Path -LiteralPath $startup)) {
        Fail 'Missing START_SMART_HOME.ps1. Apply the previous PowerShell startup fix first.'
    }

    $ngrokExe = Join-Path $root 'ngrok.exe'
    if (-not (Test-Path -LiteralPath $ngrokExe)) {
        $ngrokCommand = Get-Command 'ngrok.exe' -ErrorAction SilentlyContinue
        if (-not $ngrokCommand) {
            $ngrokCommand = Get-Command 'ngrok' -ErrorAction SilentlyContinue
        }
        if (-not $ngrokCommand) {
            Fail 'ngrok.exe not found. Put ngrok.exe in the project folder or add it to PATH.'
        }
        $ngrokExe = $ngrokCommand.Source
    }

    Write-Host '[INFO] Starting hybrid Smart Home before opening the public tunnel...'
    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $startup
    if ($LASTEXITCODE -ne 0) {
        Fail 'Smart Home startup failed. ngrok will NOT open.'
    }

    # Must match the port chosen by START_SMART_HOME.ps1.
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
        $parsed = 0
        if (-not [int]::TryParse($env:DASHBOARD_PORT, [ref]$parsed)) {
            Fail 'DASHBOARD_PORT must be a number.'
        }
        $port = $parsed
    }
    if ($port -lt 1 -or $port -gt 65535) {
        Fail 'DASHBOARD_PORT must be between 1 and 65535.'
    }

    # Never publish an unprotected Smart Home dashboard.
    $sessionUrl = 'http://127.0.0.1:{0}/api/auth/session' -f $port
    try {
        $session = Invoke-RestMethod -Uri $sessionUrl -TimeoutSec 6 -ErrorAction Stop
    } catch {
        Fail ('Cannot verify dashboard authentication at ' + $sessionUrl + '. Tunnel NOT opened.')
    }
    if ($session.configured -ne $true) {
        Fail 'Dashboard password is not configured. Set DASHBOARD_PASSWORD (12+ characters) in backend\.env. Tunnel NOT opened.'
    }

    Write-Host ''
    Write-Host '============================================================='
    Write-Host ' SMART HOME HYBRID - HTTPS VIA NGROK'
    Write-Host (' Dashboard: http://127.0.0.1:{0}' -f $port)
    Write-Host ' Backend port 8000 stays local (not tunneled).'
    Write-Host ' Use the HTTPS forwarding URL from ngrok on your phone.'
    Write-Host ' Ctrl+C stops ngrok; FastAPI and Docker keep running.'
    Write-Host '============================================================='
    Write-Host ''

    & $ngrokExe http $port
    $ngrokExitCode = $LASTEXITCODE
    if ($ngrokExitCode -ne 0) {
        Fail ('ngrok exited with status ' + $ngrokExitCode + '. Check your auth token with: ngrok config add-authtoken YOUR_TOKEN')
    }
    exit 0
} catch {
    Fail $_.Exception.Message
}
