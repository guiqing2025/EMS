# Sync EMS from GitHub zip while preserving local runtime data.
# IMPORTANT: never restore backend/static/vue from preserve (it overwrites new frontend builds).
param(
  [string]$Token = "",
  [switch]$SkipDownload
)

$ErrorActionPreference = "Stop"
$env:Path = [System.Environment]::GetEnvironmentVariable("Path","Machine") + ";" + [System.Environment]::GetEnvironmentVariable("Path","User")

$real = (Get-Item C:\EMS -EA SilentlyContinue).Target
if ($real -is [array]) { $real = $real[0] }
if (-not $real) { $real = "C:\Users\Administrator\Desktop\深圳鼎雄电子科技有限公司\EMS" }

$stamp = Get-Date -Format yyyyMMdd_HHmmss
$preserve = "D:\ems_preserve_$stamp"
$zip = "D:\EMS-main-sync.zip"
$fresh = "C:\EMS_fresh"

Write-Host "REAL=$real"
Write-Host "PRESERVE=$preserve"

# Stop service
Get-NetTCPConnection -LocalPort 8888,8000 -State Listen -EA SilentlyContinue |
  Select-Object -ExpandProperty OwningProcess -Unique |
  ForEach-Object { Stop-Process -Id $_ -Force -EA SilentlyContinue }
Get-CimInstance Win32_Process -Filter "Name='python.exe' OR Name='uvicorn.exe'" -EA SilentlyContinue | ForEach-Object {
  if ($_.CommandLine -match 'EMS|uvicorn|8888') { Stop-Process -Id $_.ProcessId -Force -EA SilentlyContinue }
}
Start-Sleep 2

# Preserve runtime only (NOT static/vue)
New-Item -ItemType Directory -Force -Path $preserve | Out-Null
$keep = @(
  'backend\ems.db','backend\ems.db-wal','backend\ems.db-shm',
  'backend\srm_config.json','backend\.env.postgres',
  'backend\data','backend\static\uploads',
  'env\local.env','start_local_windows.ps1',
  'scripts\import_sqlite_db.ps1','scripts\check_prod_ready.ps1','scripts\set_static_ip_168.ps1',
  'scripts\sync_from_github.ps1','scripts\check_schema_drift.py'
)
foreach ($rel in $keep) {
  $src = Join-Path $real $rel
  if (Test-Path -LiteralPath $src) {
    $dst = Join-Path $preserve $rel
    New-Item -ItemType Directory -Force -Path (Split-Path $dst) | Out-Null
    Copy-Item -LiteralPath $src -Destination $dst -Recurse -Force
    Write-Host "preserved $rel"
  }
}
# also keep local excel helpers at repo root
Get-ChildItem -LiteralPath $real -File | Where-Object {
  $_.Extension -match '\.(xls|xlsx|pdf)$' -or $_.Name -match '替代|工艺|wang_captcha'
} | ForEach-Object {
  Copy-Item $_.FullName (Join-Path $preserve $_.Name) -Force
  Write-Host "preserved file $($_.Name)"
}

if (-not $SkipDownload) {
  if (-not $Token) { throw "Token required unless -SkipDownload" }
  Write-Host "Downloading zip..."
  & curl.exe -L -H "Authorization: Bearer $Token" -H "User-Agent: EMS-sync" -o $zip "https://api.github.com/repos/guiqing2025/EMS/zipball/main"
  if (-not (Test-Path $zip) -or (Get-Item $zip).Length -lt 1000000) { throw "zip download failed" }
}

Remove-Item $fresh -Recurse -Force -EA SilentlyContinue
New-Item -ItemType Directory -Force -Path $fresh | Out-Null
Expand-Archive -Path $zip -DestinationPath $fresh -Force
$inner = Get-ChildItem $fresh -Directory | Select-Object -First 1
Get-ChildItem $inner.FullName -Force | ForEach-Object { Move-Item $_.FullName $fresh -Force }
Remove-Item $inner.FullName -Recurse -Force -EA SilentlyContinue

# Restore runtime onto fresh (explicitly skip static/vue)
foreach ($rel in $keep) {
  if ($rel -like '*static\vue*') { continue }
  $src = Join-Path $preserve $rel
  if (Test-Path -LiteralPath $src) {
    $dst = Join-Path $fresh $rel
    New-Item -ItemType Directory -Force -Path (Split-Path $dst) | Out-Null
    if (Test-Path $dst) { Remove-Item $dst -Recurse -Force -EA SilentlyContinue }
    Copy-Item -LiteralPath $src -Destination $dst -Recurse -Force
    Write-Host "restored $rel"
  }
}
Get-ChildItem $preserve -File | ForEach-Object {
  Copy-Item $_.FullName (Join-Path $fresh $_.Name) -Force
}

# Keep old venv/node_modules if present
foreach ($pair in @(
  @{Src=Join-Path $real 'backend\.venv'; Dst=Join-Path $fresh 'backend\.venv'},
  @{Src=Join-Path $real 'frontend\node_modules'; Dst=Join-Path $fresh 'frontend\node_modules'}
)) {
  if (Test-Path $pair.Src) {
    if (Test-Path $pair.Dst) { Remove-Item $pair.Dst -Recurse -Force -EA SilentlyContinue }
    Move-Item $pair.Src $pair.Dst -Force
    Write-Host "moved $($pair.Src)"
  }
}

# Swap
cmd /c "rmdir C:\EMS" 2>$null
$bakName = "EMS_bak_$stamp"
Rename-Item -LiteralPath $real -NewName $bakName
Move-Item -LiteralPath $fresh -Destination $real
cmd /c "mklink /J C:\EMS `"$real`""

# Re-apply local Windows patches that may not be in remote yet
& python (Join-Path $real 'backend\.venv\Scripts\python.exe') -c "print('skip')" 2>$null
Write-Host "swap done. Run migrate + start_local_windows.ps1 -Force"
Write-Host "NOTE: static/vue kept from GitHub zip (not preserve)."
