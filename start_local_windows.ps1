# EMS production start on this Windows PC (LAN + auto sync)
# Usage:
#   Set-ExecutionPolicy -Scope Process Bypass -Force
#   C:\EMS\start_local_windows.ps1 -Force
#
# Colleagues: http://192.168.2.168:8888  (after static IP is set)
# Until then:  http://<this-pc-ip>:8888
param(
    [switch]$Force,
    [switch]$WithFrontendDev
)

$ErrorActionPreference = "Stop"
$RepoRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
if (Test-Path "C:\EMS\backend\main.py") {
    $RepoRoot = "C:\EMS"
}
$Backend = Join-Path $RepoRoot "backend"
$Frontend = Join-Path $RepoRoot "frontend"
$VenvUvicorn = Join-Path $Backend ".venv\Scripts\uvicorn.exe"
$Log = Join-Path $env:TEMP "ems-local-uvicorn.log"
$Port = 8888
$BindHost = "0.0.0.0"
$LanIp = "192.168.2.168"
$PublicUrl = "http://${LanIp}:$Port"

if (-not (Test-Path $VenvUvicorn)) {
    throw "Missing venv: $VenvUvicorn"
}

# Production-like: enable scheduled sync (SRM/warehouse/AOI/ICT/...)
Remove-Item Env:DATABASE_URL -ErrorAction SilentlyContinue
Remove-Item Env:EMS_DEV_MODE -ErrorAction SilentlyContinue
$env:EMS_USE_SQLITE = "1"
$env:EMS_ALLOW_DEV_DB = "1"
$env:EMS_DB = "ems.db"
$env:EMS_SKIP_STARTUP_AUDIT = "1"
$env:EMS_SYNC_WARMUP_SEC = "120"
$env:EMS_PUBLIC_URL = $PublicUrl

# Load env\local.env into process.
# Force-refresh path keys so old Z: values in the shell cannot stick.
$pathKeys = @(
    'EMS_SHARE_ROOT','WAREHOUSE_SHARE_PATH','ENGINEERING_SHARE_BASE','HR_ROSTER_PATH',
    'SUBSTITUTION_FILE_PATH','PROCESS_DETAIL_FILE_PATH','LASER_PRINT_REGISTER_PATH',
    'LASER_IMPORT_DEFAULT_PATH','EMS_PUBLIC_URL','EMS_ROLE'
)
$localEnv = Join-Path $RepoRoot "env\local.env"
if (Test-Path $localEnv) {
    Get-Content -LiteralPath $localEnv -Encoding UTF8 | ForEach-Object {
        $line = $_.Trim()
        if (-not $line -or $line.StartsWith("#") -or -not $line.Contains("=")) { return }
        $i = $line.IndexOf("=")
        $k = $line.Substring(0, $i).Trim()
        $v = $line.Substring($i + 1).Trim().Trim('"').Trim("'")
        if (-not $k) { return }
        $cur = [Environment]::GetEnvironmentVariable($k, "Process")
        if (($pathKeys -contains $k) -or [string]::IsNullOrEmpty($cur)) {
            [Environment]::SetEnvironmentVariable($k, $v, "Process")
        }
    }
}

function Get-Listeners([int]$p) {
    @(Get-NetTCPConnection -LocalPort $p -State Listen -ErrorAction SilentlyContinue |
        Select-Object -ExpandProperty OwningProcess -Unique)
}

if ($Force) {
    foreach ($p in @(8000, $Port)) {
        foreach ($procId in (Get-Listeners $p)) {
            Write-Host "Stopping old process on $p : $procId"
            Stop-Process -Id $procId -Force -ErrorAction SilentlyContinue
        }
    }
    Start-Sleep -Seconds 1
}
elseif ((Get-Listeners $Port).Count -gt 0) {
    Write-Host "Port $Port already listening:"
    Write-Host "  Local: http://127.0.0.1:$Port"
    Write-Host "  LAN:   $PublicUrl"
    exit 0
}

try {
    $ruleName = "EMS HTTP $Port"
    if (-not (Get-NetFirewallRule -DisplayName $ruleName -ErrorAction SilentlyContinue)) {
        New-NetFirewallRule -DisplayName $ruleName -Direction Inbound -Protocol TCP -LocalPort $Port -Action Allow -Profile Any | Out-Null
        Write-Host "Firewall rule added: $ruleName"
    }
} catch {
    Write-Host "Warning: firewall rule failed: $($_.Exception.Message)"
}

# Preflight warnings (do not block start)
$dbPath = Join-Path $Backend "ems.db"
if (-not (Test-Path $dbPath) -or ((Get-Item $dbPath).Length -lt 1MB)) {
    Write-Host "WARNING: ems.db missing or tiny — history will be empty until you import production DB."
}
$shareRoot = $env:EMS_SHARE_ROOT
if ($shareRoot -and -not (Test-Path -LiteralPath $shareRoot)) {
    Write-Host "WARNING: share root not reachable: $shareRoot"
    Write-Host "         Map the network drive / fix env\local.env, otherwise warehouse/HR sync cannot run."
}

if (Test-Path $Log) { Remove-Item $Log -Force }
if (Test-Path "$Log.err") { Remove-Item "$Log.err" -Force }

$proc = Start-Process -FilePath $VenvUvicorn `
    -ArgumentList @("main:app","--host",$BindHost,"--port","$Port") `
    -WorkingDirectory $Backend `
    -RedirectStandardOutput $Log `
    -RedirectStandardError "$Log.err" `
    -WindowStyle Hidden `
    -PassThru

Write-Host "Backend started pid=$($proc.Id) log=$Log"
Write-Host "Auto-sync: ON (EMS_DEV_MODE off, warmup $($env:EMS_SYNC_WARMUP_SEC)s)"

$ok = $false
for ($i = 1; $i -le 90; $i++) {
    if ($proc.HasExited) {
        Write-Host "Process exited early code=$($proc.ExitCode)"
        if (Test-Path $Log) { Get-Content $Log -Tail 40 }
        if (Test-Path "$Log.err") { Get-Content "$Log.err" -Tail 40 }
        exit 1
    }
    try {
        $resp = Invoke-WebRequest -Uri "http://127.0.0.1:$Port/" -UseBasicParsing -TimeoutSec 2
        if ($resp.StatusCode -ge 200 -and $resp.StatusCode -lt 500) {
            $ok = $true
            break
        }
    }
    catch { }
    Start-Sleep -Seconds 1
    Write-Host "Waiting... $i/90"
}

if (-not $ok) {
    Write-Host "Start timeout. Recent log:"
    if (Test-Path $Log) { Get-Content $Log -Tail 80 }
    if (Test-Path "$Log.err") { Get-Content "$Log.err" -Tail 80 }
    exit 1
}

Write-Host ""
Write-Host "EMS ready (production sync enabled):"
Write-Host "  Local: http://127.0.0.1:$Port"
Write-Host "  LAN:   $PublicUrl"
Write-Host "  Check: C:\EMS\scripts\check_prod_ready.ps1"
