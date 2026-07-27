# =============================================================================
# EMS【生产】Windows 启动 — 端口 8000（对标 start_ems.sh）
#   .\start_ems.ps1
#   .\start_ems.ps1 -Force
#   .\start_ems.ps1 -Smoke
# =============================================================================
param(
    [switch]$Force,
    [switch]$Smoke,
    [switch]$Help
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root
$RepoRoot = Split-Path -Parent $Root
$Log = Join-Path $env:TEMP "ems-uvicorn.log"
$PidFile = Join-Path $env:TEMP "ems-uvicorn.pid"
$LocalUrl = "http://127.0.0.1:8000"
$PublicUrl = if ($env:EMS_PUBLIC_URL) { $env:EMS_PUBLIC_URL } else { "http://192.168.2.168:8000" }

if ($Help) {
    Write-Host "用法: .\start_ems.ps1 [-Force] [-Smoke]"
    exit 0
}

function Import-DotEnv([string]$Path, [switch]$Overwrite) {
    if (-not (Test-Path $Path)) { return }
    Get-Content -LiteralPath $Path -Encoding UTF8 | ForEach-Object {
        $line = $_.Trim()
        if (-not $line -or $line.StartsWith("#") -or -not $line.Contains("=")) { return }
        $i = $line.IndexOf("=")
        $k = $line.Substring(0, $i).Trim()
        $v = $line.Substring($i + 1).Trim().Trim('"').Trim("'")
        if (-not $k) { return }
        if (-not $Overwrite -and -not [string]::IsNullOrEmpty([Environment]::GetEnvironmentVariable($k, "Process"))) {
            return
        }
        [Environment]::SetEnvironmentVariable($k, $v, "Process")
    }
}

Import-DotEnv (Join-Path $RepoRoot "env\local.env")
Import-DotEnv (Join-Path $Root ".env.postgres") -Overwrite

if ($env:EMS_USE_SQLITE -eq "1" -and $env:EMS_ALLOW_DEV_DB -ne "1") {
    if ($env:EMS_DB -eq "ems.dev.db" -or $env:EMS_DEV_MODE -eq "1") {
        Write-Error "拒绝：检测到开发环境变量，生产请用 .env.postgres"
        exit 2
    }
}

if ($env:EMS_USE_SQLITE -eq "1") {
    Remove-Item Env:DATABASE_URL -ErrorAction SilentlyContinue
    if (-not $env:EMS_DB) { $env:EMS_DB = "ems.db" }
    Write-Host "数据库模式: SQLite ($($env:EMS_DB)) 【回滚】"
} elseif (Test-Path (Join-Path $Root ".env.postgres")) {
    Remove-Item Env:EMS_USE_SQLITE -ErrorAction SilentlyContinue
    Remove-Item Env:EMS_DB -ErrorAction SilentlyContinue
    Remove-Item Env:EMS_DEV_MODE -ErrorAction SilentlyContinue
    Write-Host "数据库模式: Postgres ($($env:EMS_PG_HOST):$($env:EMS_PG_PORT)/$($env:EMS_PG_DB))"
} else {
    Write-Error "未找到 .env.postgres。请复制 .env.postgres.example 并填写。"
    exit 1
}

if (-not $env:EMS_SKIP_STARTUP_AUDIT) { $env:EMS_SKIP_STARTUP_AUDIT = "1" }
if (-not $env:EMS_SYNC_WARMUP_SEC) { $env:EMS_SYNC_WARMUP_SEC = "120" }

$VenvPython = Join-Path $Root ".venv\Scripts\python.exe"
$VenvUvicorn = Join-Path $Root ".venv\Scripts\uvicorn.exe"
if (-not (Test-Path $VenvPython)) {
    Write-Error "缺少 venv，请先运行 ..\scripts\bootstrap_windows.ps1"
    exit 1
}

function Get-Listeners8000 {
    @(Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue |
        Select-Object -ExpandProperty OwningProcess -Unique)
}

function Stop-Port8000 {
    foreach ($p in (Get-Listeners8000)) {
        Write-Host "结束旧进程: $p"
        Stop-Process -Id $p -Force -ErrorAction SilentlyContinue
    }
    Start-Sleep -Seconds 2
}

function Wait-Healthy {
    for ($i = 1; $i -le 40; $i++) {
        try {
            $resp = Invoke-WebRequest -Uri $LocalUrl -UseBasicParsing -TimeoutSec 2
            if ($resp.StatusCode -eq 200) {
                Write-Host "健康检查通过（第 $i 次）"
                return $true
            }
            $code = $resp.StatusCode
        } catch { $code = "000" }
        Write-Host "等待启动… $i/40 HTTP=$code"
        Start-Sleep -Seconds 2
    }
    Write-Host "启动超时。请看日志: Get-Content `"$Log`" -Tail 80"
    return $false
}

function Rotate-Log {
    if (-not (Test-Path $Log)) { return }
    $max = 52428800L
    if ($env:EMS_LOG_MAX_BYTES) { $max = [int64]$env:EMS_LOG_MAX_BYTES }
    $keep = 3
    if ($env:EMS_LOG_KEEP) { $keep = [int]$env:EMS_LOG_KEEP }
    $size = (Get-Item $Log).Length
    if ($size -lt $max) { return }
    $ts = Get-Date -Format "yyyyMMdd_HHmmss"
    $archived = "$Log.$ts.old"
    Move-Item -LiteralPath $Log -Destination $archived -Force
    New-Item -ItemType File -Path $Log -Force | Out-Null
    Write-Host "日志已轮转: $archived ($size bytes)"
    Get-ChildItem "$Log.*.old" -ErrorAction SilentlyContinue |
        Sort-Object LastWriteTime -Descending |
        Select-Object -Skip $keep |
        Remove-Item -Force
}

if ($Smoke) {
    & $VenvPython (Join-Path $Root "smoke_check.py") $LocalUrl
    exit $LASTEXITCODE
}

if ($Force) {
    Stop-Port8000
} elseif ((Get-Listeners8000).Count -gt 0) {
    Write-Host "端口 8000 已在监听。访问地址：$PublicUrl"
    Write-Host "强制重启： .\start_ems.ps1 -Force"
    exit 0
}

if ($env:WAREHOUSE_SHARE_PATH -and -not (Test-Path -LiteralPath $env:WAREHOUSE_SHARE_PATH)) {
    Write-Host "警告: 无法读取共享盘 $($env:WAREHOUSE_SHARE_PATH)"
}

Rotate-Log
Write-Host "启动参数: EMS_SKIP_STARTUP_AUDIT=$($env:EMS_SKIP_STARTUP_AUDIT) EMS_SYNC_WARMUP_SEC=$($env:EMS_SYNC_WARMUP_SEC)"

# 用 cmd start 脱离当前控制台；stdout/err 追加到日志
$cmd = @"
cd /d "$Root"
"$VenvUvicorn" main:app --host 0.0.0.0 --port 8000 >> "$Log" 2>&1
"@
$bat = Join-Path $env:TEMP "ems-start-uvicorn.bat"
Set-Content -Path $bat -Value $cmd -Encoding ASCII
$p = Start-Process -FilePath "cmd.exe" -ArgumentList "/c", "`"$bat`"" -WindowStyle Hidden -PassThru
Set-Content -Path $PidFile -Value $p.Id -Encoding ASCII
Write-Host "EMS 已拉起 pid=$($p.Id) ，日志 $Log"

if (-not (Wait-Healthy)) { exit 1 }
Write-Host "请用浏览器打开：$PublicUrl"
if ($env:EMS_RUN_SMOKE -eq "1") {
    & $VenvPython (Join-Path $Root "smoke_check.py") $LocalUrl
}
