# =============================================================================
# Windows：导出生产库快照（给 Mac 开发库单向导入）
#   .\scripts\export_db.ps1
#   .\scripts\export_db.ps1 -OutDir D:\backups
# =============================================================================
param(
    [string]$OutDir = "",
    [switch]$Help
)

$ErrorActionPreference = "Stop"
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$Backend = Join-Path $RepoRoot "backend"
if ($Help) {
    Write-Host "导出 ems_prod 为自定义格式 dump，供 Mac import_db_dev.sh 使用"
    exit 0
}

function Import-DotEnv([string]$Path) {
    if (-not (Test-Path $Path)) { return }
    Get-Content -LiteralPath $Path -Encoding UTF8 | ForEach-Object {
        $line = $_.Trim()
        if (-not $line -or $line.StartsWith("#") -or -not $line.Contains("=")) { return }
        $i = $line.IndexOf("=")
        $k = $line.Substring(0, $i).Trim()
        $v = $line.Substring($i + 1).Trim().Trim('"').Trim("'")
        if ($k) { [Environment]::SetEnvironmentVariable($k, $v, "Process") }
    }
}

Import-DotEnv (Join-Path $Backend ".env.postgres")
$hostName = if ($env:EMS_PG_HOST) { $env:EMS_PG_HOST } else { "127.0.0.1" }
$port = if ($env:EMS_PG_PORT) { $env:EMS_PG_PORT } else { "5432" }
$user = if ($env:EMS_PG_USER) { $env:EMS_PG_USER } else { "ems" }
$db = if ($env:EMS_PG_DB) { $env:EMS_PG_DB } else { "ems_prod" }
$env:PGPASSWORD = $env:EMS_PG_PASSWORD

$pgDump = Get-Command pg_dump -ErrorAction SilentlyContinue
if (-not $pgDump) {
    $cand = @(
        "C:\Program Files\PostgreSQL\16\bin\pg_dump.exe",
        "C:\Program Files\PostgreSQL\15\bin\pg_dump.exe"
    ) | Where-Object { Test-Path $_ } | Select-Object -First 1
    if (-not $cand) { Write-Error "未找到 pg_dump" }
    $pgDump = $cand
}

if (-not $OutDir) {
    $OutDir = Join-Path $RepoRoot "scripts\_db_exports"
}
New-Item -ItemType Directory -Force -Path $OutDir | Out-Null
$ts = Get-Date -Format "yyyyMMdd_HHmmss"
$out = Join-Path $OutDir "ems_prod_$ts.dump"

Write-Host "导出 $db@$hostName:$port → $out"
& $pgDump -h $hostName -p $port -U $user -Fc -f $out $db
if ($LASTEXITCODE -ne 0) { Write-Error "pg_dump 失败" }
Write-Host "完成: $out"
Write-Host "拷到 Mac 后执行: ./scripts/import_db_dev.sh `"$out`""
