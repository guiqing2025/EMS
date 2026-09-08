# Import production SQLite DB onto this Windows EMS box.
# Usage:
#   1) Copy old machine backend\ems.db to e.g. D:\backup\ems.db
#   2) Set-ExecutionPolicy -Scope Process Bypass -Force
#   3) C:\EMS\scripts\import_sqlite_db.ps1 -SourceDb "D:\backup\ems.db"
param(
    [Parameter(Mandatory = $true)]
    [string]$SourceDb,
    [switch]$SkipRestart
)

$ErrorActionPreference = "Stop"
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$Backend = Join-Path $RepoRoot "backend"
$Target = Join-Path $Backend "ems.db"
$Stamp = Get-Date -Format "yyyyMMdd_HHmmss"

if (-not (Test-Path -LiteralPath $SourceDb)) {
    throw "Source DB not found: $SourceDb"
}

$srcLen = (Get-Item -LiteralPath $SourceDb).Length
Write-Host ("Source size: {0:N1} MB" -f ($srcLen / 1MB))
if ($srcLen -lt 100KB) {
    Write-Host "WARNING: source looks empty (<100KB)."
    $ans = Read-Host "Continue anyway? (Y/N)"
    if ($ans -notin @("Y", "y")) { exit 1 }
}

foreach ($port in @(8888, 8000)) {
    Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue |
        Select-Object -ExpandProperty OwningProcess -Unique |
        ForEach-Object {
            Write-Host "Stopping EMS pid $_ on port $port"
            Stop-Process -Id $_ -Force -ErrorAction SilentlyContinue
        }
}
Start-Sleep -Seconds 2

# Remove SQLite sidecars
Get-ChildItem -LiteralPath $Backend -Filter "ems.db*" |
    Where-Object { $_.Name -match '^ems\.db(-wal|-shm)?$' } |
    ForEach-Object {
        if ($_.Name -eq "ems.db" -and (Test-Path $Target)) {
            $bak = Join-Path $Backend "ems.db.bak_$Stamp"
            Copy-Item -LiteralPath $Target -Destination $bak -Force
            Write-Host "Backed up -> $bak"
        }
        if ($_.Name -ne "ems.db") {
            Remove-Item -LiteralPath $_.FullName -Force -ErrorAction SilentlyContinue
        }
    }

Copy-Item -LiteralPath $SourceDb -Destination $Target -Force
# Also copy wal/shm if present beside source
$srcDir = Split-Path -Parent $SourceDb
foreach ($side in @("ems.db-wal", "ems.db-shm")) {
    $sidePath = Join-Path $srcDir $side
    if (Test-Path -LiteralPath $sidePath) {
        Copy-Item -LiteralPath $sidePath -Destination (Join-Path $Backend $side) -Force
        Write-Host "Copied sidecar $side"
    }
}

Write-Host ("Installed: {0} ({1:N1} MB)" -f $Target, ((Get-Item $Target).Length / 1MB))

$py = Join-Path $Backend ".venv\Scripts\python.exe"
$checkPy = Join-Path $env:TEMP "ems_db_check.py"
@"
import sqlite3
c = sqlite3.connect(r'''$Target''')
tables = [r[0] for r in c.execute("select name from sqlite_master where type='table'").fetchall()]
print('tables:', len(tables))
for t in ('users', 'srm_orders', 'bom_models'):
    try:
        n = c.execute('select count(*) from %s' % t).fetchone()[0]
        print('  %s: %s' % (t, n))
    except Exception:
        print('  %s: (missing)' % t)
"@ | Set-Content -Path $checkPy -Encoding UTF8
if (Test-Path $py) {
    & $py $checkPy
}

if (-not $SkipRestart) {
    & (Join-Path $RepoRoot "start_local_windows.ps1") -Force
}

Write-Host ""
Write-Host "Done. Open http://127.0.0.1:8888"
