<#
.SYNOPSIS
  One-time setup of the local Odoo 19 used by Orrfin's live Odoo connector (PROMPTS Step 20).

.DESCRIPTION
  1. Starts Odoo + its own Postgres in Docker (compose profile "odoo", bound to 127.0.0.1:8069 only).
  2. Creates the database "orrfin" with the Purchase, Inventory and Invoicing apps (no demo data).
  3. Creates an API key for the admin user and prints it ONCE. Paste it into Orrfin -> Connectors -> Odoo.
  Safe to run again: an existing database is kept; a new API key is printed each run.
  Odoo's own login (http://localhost:8069): admin / admin. Local, synthetic demo only.

  Stop Odoo:  .\scripts\odoo_setup.ps1 -Stop
  Start over: .\scripts\odoo_setup.ps1 -Reset   (deletes the Odoo demo database, then sets it up again;
              paste the new API key into Orrfin and press Prepare demo data again)
#>
param([switch]$Stop, [switch]$Reset)

$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $PSScriptRoot
$Compose = Join-Path $Root 'infra\docker-compose.yml'
$EnvFile = Join-Path $Root '.env'
$Docker = (Get-Command docker -ErrorAction SilentlyContinue).Source
if (-not $Docker) { $Docker = Join-Path $env:LOCALAPPDATA 'Programs\DockerDesktop\resources\bin\docker.exe' }

function Compose([string[]]$ComposeArgs) {
    # Docker writes progress to stderr; Windows PowerShell 5.1 would treat that as an error, so judge by exit code.
    $previous = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    & $Docker compose --env-file $EnvFile -f $Compose --profile odoo @ComposeArgs 2>&1 | ForEach-Object { "$_" } | Out-Host
    $code = $LASTEXITCODE
    $ErrorActionPreference = $previous
    if ($code -ne 0) { throw "docker compose $($ComposeArgs -join ' ') failed (exit $code)." }
}

if ($Stop) {
    Compose @('stop', 'odoo', 'odoo-db')
    Write-Host 'Odoo stopped (its data is kept in Docker volumes).'
    exit 0
}

Write-Host 'Starting Odoo (first run downloads the Odoo image, about 1 GB)...'
Compose @('up', '-d', 'odoo-db', 'odoo')

$DbPassword = 'odoo-local-only'
if (Test-Path $EnvFile) {
    $line = Select-String -Path $EnvFile -Pattern '^\s*ODOO_DB_PASSWORD\s*=\s*(.+)$' | Select-Object -First 1
    if ($line) { $DbPassword = $line.Matches[0].Groups[1].Value.Trim() }
}
$DbArgs = @('--db_host', 'odoo-db', '--db_user', 'odoo', '--db_password', $DbPassword)

if ($Reset) {
    # A half-finished 'Prepare demo data' leaves POs Orrfin then treats as already there; starting over is simplest.
    Write-Host 'Deleting the Odoo database "orrfin" (local demo data only)...'
    Compose @('exec', '-T', 'odoo-db', 'dropdb', '-U', 'odoo', '--if-exists', '--force', 'orrfin')
    Compose @('exec', '-T', 'odoo', 'rm', '-rf', '/var/lib/odoo/filestore/orrfin')
}

Write-Host 'Creating database "orrfin" with Purchase, Inventory and Invoicing (a few minutes the first time)...'
Compose (@('exec', '-T', 'odoo', 'odoo', '-d', 'orrfin', '-i', 'purchase,stock,account', '--without-demo',
           '--stop-after-init', '--no-http') + $DbArgs)

Write-Host 'Creating an API key for Orrfin...'
$Python = @"
from datetime import timedelta
from odoo import fields
admin = env.ref('base.user_admin')
key = env['res.users.apikeys'].with_user(admin)._generate(None, 'Orrfin connector', fields.Datetime.now() + timedelta(days=90))
env.cr.commit()
print('ORRFIN_ODOO_API_KEY=' + key)
"@
# Piping text into docker from Windows PowerShell adds a byte-order mark that Odoo's Python shell rejects,
# so the script goes in as a BOM-less file copied into the container.
$ScriptFile = Join-Path $env:TEMP 'orrfin_odoo_key.py'
[IO.File]::WriteAllText($ScriptFile, $Python, (New-Object System.Text.UTF8Encoding $false))
Compose @('cp', $ScriptFile, 'odoo:/tmp/orrfin_odoo_key.py')
Remove-Item $ScriptFile -Force
$ErrorActionPreference = 'Continue'
$Output = & $Docker compose --env-file $EnvFile -f $Compose --profile odoo exec -T odoo sh -c "odoo shell -d orrfin $($DbArgs -join ' ') --no-http < /tmp/orrfin_odoo_key.py; rm -f /tmp/orrfin_odoo_key.py" 2>$null
$ErrorActionPreference = 'Stop'
$KeyLine = $Output | Where-Object { $_ -like 'ORRFIN_ODOO_API_KEY=*' } | Select-Object -First 1
if (-not $KeyLine) { throw 'Odoo did not print an API key. Create one in Odoo: My Profile -> Account Security -> New API Key.' }

Write-Host ''
Write-Host 'Odoo is ready at http://localhost:8069 (login admin / admin).'
Write-Host 'Paste this API key into Orrfin -> Connectors -> Odoo -> API key (shown once; valid 90 days):'
Write-Host ('    ' + $KeyLine.Substring('ORRFIN_ODOO_API_KEY='.Length))
Write-Host 'Leave "Odoo address" and "Database" blank. Then: Save keys -> Test connection -> Prepare demo data -> Make active.'
