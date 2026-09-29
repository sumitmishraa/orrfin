<#
.SYNOPSIS
  Start or stop the local Orrfin stack: Postgres (Docker), API (port 8000), job worker, web (port 3000).

.DESCRIPTION
  Local-first development, BUILD_PLAN section 3. First run also creates .env from
  .env.example, the Python virtual environment and node_modules, so it can take a few minutes.
  The API and web app run hidden in the background; their logs go to .dev\*.log.

.EXAMPLE
  .\scripts\dev.ps1          # start everything
  .\scripts\dev.ps1 -Stop    # stop everything
  .\scripts\dev.ps1 -WebPort 3001   # if another app already uses port 3000
#>
param([switch]$Stop, [int]$WebPort = 3000)

$ErrorActionPreference = 'Stop'
$Root     = Split-Path -Parent $PSScriptRoot
$StateDir = Join-Path $Root '.dev'
$PidFile  = Join-Path $StateDir 'pids.json'
$EnvFile  = Join-Path $Root '.env'
$Compose  = Join-Path $Root 'infra\docker-compose.yml'
$Backend  = Join-Path $Root 'backend'
$Frontend = Join-Path $Root 'frontend'
$VenvPy   = Join-Path $Backend '.venv\Scripts\python.exe'

function Find-Docker {
    $onPath = Get-Command docker -ErrorAction SilentlyContinue
    if ($onPath) { return $onPath.Source }
    # Terminals opened before Docker Desktop was installed don't have it on PATH yet.
    $candidates = @(
        (Join-Path $env:LOCALAPPDATA 'Programs\DockerDesktop\resources\bin\docker.exe'),
        (Join-Path $env:ProgramFiles 'Docker\Docker\resources\bin\docker.exe')
    )
    foreach ($path in $candidates) { if (Test-Path $path) { return $path } }
    throw 'Docker CLI not found. Install Docker Desktop, open it once, then try again.'
}

function Invoke-Native([string]$FailureMessage, [scriptblock]$Command) {
    # Windows PowerShell 5.1 turns a program's stderr output into a fatal error when
    # ErrorActionPreference is Stop. docker, alembic and npm print normal progress to
    # stderr, so judge them by exit code instead (this setting is local to the function).
    $ErrorActionPreference = 'Continue'
    & $Command
    if ($LASTEXITCODE -ne 0) { throw $FailureMessage }
}

function Invoke-Compose([string[]]$ComposeArgs) {
    Invoke-Native "docker compose $($ComposeArgs -join ' ') failed." {
        & $script:Docker compose --env-file $EnvFile -f $Compose @ComposeArgs
    }
}

function Test-DockerEngine {
    $ErrorActionPreference = 'Continue'
    & $script:Docker info *> $null
    return ($LASTEXITCODE -eq 0)
}

function Start-DockerEngine {
    if (Test-DockerEngine) { return }
    $desktopApp = Join-Path $env:LOCALAPPDATA 'Programs\DockerDesktop\Docker Desktop.exe'
    if (-not (Test-Path $desktopApp)) { $desktopApp = Join-Path $env:ProgramFiles 'Docker\Docker\Docker Desktop.exe' }
    if (-not (Test-Path $desktopApp)) { throw 'Docker Desktop is not running. Open it, wait for "Engine running", then try again.' }
    Write-Host 'Opening Docker Desktop and waiting for its engine (up to 3 minutes)...'
    Start-Process $desktopApp | Out-Null
    $deadline = (Get-Date).AddMinutes(3)
    while ((Get-Date) -lt $deadline) {
        Start-Sleep -Seconds 3
        if (Test-DockerEngine) { return }
    }
    throw 'Docker Desktop did not start in time. Open it, wait for "Engine running", then try again.'
}

function Stop-AppProcesses {
    if (-not (Test-Path $PidFile)) { return }
    $saved = Get-Content $PidFile -Raw | ConvertFrom-Json
    foreach ($name in 'api', 'worker', 'web') {
        $id = $saved.$name
        if ($id -and (Get-Process -Id $id -ErrorAction SilentlyContinue)) {
            # /T kills the whole tree: uvicorn's reloader child and npm's node child.
            & taskkill.exe /T /F /PID $id | Out-Null
            Write-Host "Stopped $name (process $id)."
        }
    }
    Remove-Item $PidFile -Force
}

function Test-PortInUse([int]$Port) {
    return [bool](Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue)
}

function Read-DotEnv {
    $values = @{}
    foreach ($line in Get-Content $EnvFile) {
        if ($line -match '^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)\s*$') { $values[$Matches[1]] = $Matches[2] }
    }
    return $values
}

function Wait-ForUrl([string]$Url, [int]$Seconds) {
    $deadline = (Get-Date).AddSeconds($Seconds)
    while ((Get-Date) -lt $deadline) {
        try {
            $response = Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec 5
            if ($response.StatusCode -eq 200) { return $true }
        } catch { Start-Sleep -Seconds 2 }
    }
    return $false
}

$script:Docker = Find-Docker

if ($Stop) {
    Stop-AppProcesses
    if ((Test-Path $EnvFile) -and (Test-DockerEngine)) { Invoke-Compose @('stop') }
    Write-Host 'Orrfin stopped. (Database data is kept in the Docker volume.)'
    exit 0
}

# --- Start -----------------------------------------------------------------

New-Item -ItemType Directory -Force $StateDir | Out-Null

if (-not (Test-Path $EnvFile)) {
    Copy-Item (Join-Path $Root '.env.example') $EnvFile
    Write-Host 'Created .env from .env.example (local placeholder values only).'
}

if (Test-Path $PidFile) {
    Write-Host 'Orrfin looks like it is already running. Stopping the old processes first...'
    Stop-AppProcesses
}
foreach ($port in 8000, $WebPort) {
    if (Test-PortInUse $port) { throw "Port $port is already in use by another program. Close it and try again." }
}

Start-DockerEngine

Write-Host 'Starting Postgres...'
Invoke-Compose @('up', '-d', '--wait')

if (-not (Test-Path $VenvPy)) {
    Write-Host 'First run: creating the Python environment (a few minutes)...'
    Invoke-Native 'Creating the Python environment failed (is Python 3.12 installed?).' {
        & py -3.12 -m venv (Join-Path $Backend '.venv')
    }
}
# Reinstall backend packages whenever pyproject.toml changes (a later step may add a dependency).
$PipStamp = Join-Path $StateDir 'pip.stamp'
$Pyproject = Join-Path $Backend 'pyproject.toml'
if (-not (Test-Path $PipStamp) -or (Get-Item $Pyproject).LastWriteTime -gt (Get-Item $PipStamp).LastWriteTime) {
    Write-Host 'Installing backend packages...'
    Invoke-Native 'Installing backend packages failed.' {
        & $VenvPy -m pip install --quiet -e "$Backend[dev]"
    }
    Set-Content $PipStamp (Get-Date -Format o)
}

Write-Host 'Applying database migrations and demo data...'
Push-Location $Backend
try {
    Invoke-Native 'alembic upgrade head failed.' { & $VenvPy -m alembic upgrade head }
    # Safe to repeat: existing demo users and categories are left untouched.
    Invoke-Native 'Loading demo data failed.' { & $VenvPy -m app.seed_demo }
} finally { Pop-Location }

if (-not (Test-Path (Join-Path $Frontend 'node_modules'))) {
    Write-Host 'First run: installing web packages (a few minutes)...'
    Push-Location $Frontend
    try {
        Invoke-Native 'npm install failed.' { & npm.cmd install --no-audit --no-fund }
    } finally { Pop-Location }
}

# The web app reads NEXT_PUBLIC_API_URL from its environment; child processes inherit this.
$dotenv = Read-DotEnv
if ($dotenv.ContainsKey('NEXT_PUBLIC_API_URL')) { $env:NEXT_PUBLIC_API_URL = $dotenv['NEXT_PUBLIC_API_URL'] }
# The API only accepts browser calls from the web app's own origin (CORS), so follow -WebPort.
if ($WebPort -ne 3000) { $env:CORS_ORIGINS = "[`"http://localhost:$WebPort`"]" }

Write-Host 'Starting API and web app...'
$api = Start-Process -FilePath $VenvPy -WorkingDirectory $Backend -WindowStyle Hidden -PassThru `
    -ArgumentList '-m', 'uvicorn', 'app.main:app', '--reload', '--host', '127.0.0.1', '--port', '8000' `
    -RedirectStandardOutput (Join-Path $StateDir 'api.log') -RedirectStandardError (Join-Path $StateDir 'api.err.log')
$web = Start-Process -FilePath 'npm.cmd' -WorkingDirectory $Frontend -WindowStyle Hidden -PassThru `
    -ArgumentList 'run', 'dev', '--', '--port', "$WebPort" `
    -RedirectStandardOutput (Join-Path $StateDir 'web.log') -RedirectStandardError (Join-Path $StateDir 'web.err.log')
# The worker runs background jobs such as "Sync from ERP" (BUILD_PLAN §4).
$worker = Start-Process -FilePath $VenvPy -WorkingDirectory $Backend -WindowStyle Hidden -PassThru `
    -ArgumentList '-m', 'app.worker' `
    -RedirectStandardOutput (Join-Path $StateDir 'worker.log') -RedirectStandardError (Join-Path $StateDir 'worker.err.log')
@{ api = $api.Id; worker = $worker.Id; web = $web.Id } | ConvertTo-Json | Set-Content $PidFile

$apiUp = Wait-ForUrl 'http://localhost:8000/health' 60
$webUp = Wait-ForUrl "http://localhost:$WebPort" 120
# The worker has no URL to wait for; a dead worker means "Sync from ERP" jobs would never run.
$workerUp = -not $worker.HasExited

Write-Host ''
if ($apiUp) { Write-Host 'API  ready:  http://localhost:8000/health   (docs: http://localhost:8000/docs)' }
else        { Write-Host 'API  did not start. See .dev\api.err.log' }
if ($workerUp) { Write-Host 'Worker running (background jobs such as Sync from ERP).' }
else           { Write-Host "Worker stopped (exit code $($worker.ExitCode)). See .dev\worker.err.log" }
if ($webUp) { Write-Host "Web  ready:  http://localhost:$WebPort" }
else        { Write-Host 'Web  did not start. See .dev\web.err.log' }
Write-Host 'Stop everything with: .\scripts\dev.ps1 -Stop'
if (-not ($apiUp -and $webUp -and $workerUp)) { exit 1 }
