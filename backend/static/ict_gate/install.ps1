# ICT 扫码闸道一键安装（在 ICT 的 Windows PowerShell 中运行）
# 用法：
#   $env:EMS_BASE_URL='http://当前EMS服务器IP:8000'
#   irm "$env:EMS_BASE_URL/static/ict_gate/install.ps1" | iex
#
# 或指定机台：
#   $env:EMS_BASE_URL='http://当前EMS服务器IP:8000'
#   $env:ICT_MACHINE_ID='ict-108'
#   irm "$env:EMS_BASE_URL/static/ict_gate/install.ps1" | iex

$ErrorActionPreference = 'Stop'
$EmsBase = if ($env:EMS_BASE_URL) { $env:EMS_BASE_URL.TrimEnd('/') } else { '' }
if (-not $EmsBase) {
  throw "请先设置环境变量 EMS_BASE_URL（例如 http://192.168.x.x:8000），不要依赖写死的本机 IP"
}
$InstallRoot = if ($env:ICT_GATE_DIR) { $env:ICT_GATE_DIR } else { 'C:\EMS\ict_gate_app' }
$ZipUrl = "$EmsBase/static/ict_gate/ict_gate_app.zip"
$ZipPath = Join-Path $env:TEMP 'ict_gate_app.zip'

function Write-Step($msg) { Write-Host "`n==> $msg" -ForegroundColor Cyan }

Write-Host "EMS: $EmsBase"
Write-Host "安装目录: $InstallRoot"

# --- 1) 下载解压 ---
Write-Step "下载闸道程序"
New-Item -ItemType Directory -Force -Path (Split-Path $InstallRoot) | Out-Null
Invoke-WebRequest -Uri $ZipUrl -OutFile $ZipPath -UseBasicParsing
if (Test-Path $InstallRoot) {
  Remove-Item -Recurse -Force $InstallRoot
}
New-Item -ItemType Directory -Force -Path $InstallRoot | Out-Null
Expand-Archive -Path $ZipPath -DestinationPath (Split-Path $InstallRoot) -Force
# zip 内是 ict_gate_app\...，Expand 到 C:\EMS 即可；若解到嵌套再挪
$nested = Join-Path (Split-Path $InstallRoot) 'ict_gate_app'
if ((Test-Path $nested) -and ($nested -ne $InstallRoot)) {
  if (Test-Path $InstallRoot) { Remove-Item -Recurse -Force $InstallRoot }
  Move-Item $nested $InstallRoot
}

# --- 2) 推断 machine_id ---
Write-Step "写入配置"
$machineId = $env:ICT_MACHINE_ID
if (-not $machineId) {
  try {
    $ip = (Get-NetIPAddress -AddressFamily IPv4 | Where-Object {
      $_.IPAddress -like '192.168.2.*' -and $_.IPAddress -notlike '*.255'
    } | Select-Object -First 1 -ExpandProperty IPAddress)
  } catch { $ip = $null }
  switch ($ip) {
    '192.168.2.123' { $machineId = 'ict-108' }
    '192.168.2.131' { $machineId = 'ict-129' }
    '192.168.2.126' { $machineId = 'ict-136' }
    default { $machineId = 'ict-pilot' }
  }
  if ($ip) { Write-Host "本机 IP: $ip -> machine_id=$machineId" }
}

$cfgPath = Join-Path $InstallRoot 'ict_gate_config.json'
$cfg = @{
  ems_base_url   = $EmsBase
  api_key        = 'ems-ict-gate-2026-dx'
  machine_id     = $machineId
  append_enter   = $true
  focus_delay_ms = 80
  play_sound     = $true
} | ConvertTo-Json
Set-Content -Path $cfgPath -Value $cfg -Encoding UTF8

# --- 3) Python ---
Write-Step "检查 Python"
$py = $null
foreach ($c in @('py', 'python', 'python3')) {
  try {
    $v = & $c -c "import sys; print(sys.version)" 2>$null
    if ($LASTEXITCODE -eq 0 -or $v) { $py = $c; break }
  } catch {}
}

if (-not $py) {
  Write-Host "未找到 Python，尝试 winget 安装..." -ForegroundColor Yellow
  $winget = Get-Command winget -ErrorAction SilentlyContinue
  if ($winget) {
    winget install -e --id Python.Python.3.12 --accept-package-agreements --accept-source-agreements
    $env:Path = [System.Environment]::GetEnvironmentVariable('Path', 'Machine') + ';' +
                [System.Environment]::GetEnvironmentVariable('Path', 'User')
    foreach ($c in @('py', 'python')) {
      try {
        & $c -c "print(1)" 2>$null | Out-Null
        if ($LASTEXITCODE -eq 0) { $py = $c; break }
      } catch {}
    }
  }
}

if (-not $py) {
  Write-Host @"

未自动装上 Python。请手动安装后重新运行本脚本：
  https://www.python.org/downloads/
安装时务必勾选「Add python.exe to PATH」，装完重新打开 PowerShell。

"@ -ForegroundColor Red
  exit 1
}

Write-Host "使用解释器: $py"
& $py -m pip install --upgrade pip
& $py -m pip install keyboard

# --- 4) 启动脚本（用检测到的 python）---
Write-Step "生成启动脚本"
$bat = @"
@echo off
chcp 65001 >nul
cd /d "$InstallRoot"
$py ict_gate.py
if errorlevel 1 pause
"@
Set-Content -Path (Join-Path $InstallRoot 'start_ict_gate.bat') -Value $bat -Encoding ASCII

# 桌面快捷方式
try {
  $desktop = [Environment]::GetFolderPath('Desktop')
  $lnkPath = Join-Path $desktop 'ICT扫码闸道.lnk'
  $w = New-Object -ComObject WScript.Shell
  $lnk = $w.CreateShortcut($lnkPath)
  $lnk.TargetPath = Join-Path $InstallRoot 'start_ict_gate.bat'
  $lnk.WorkingDirectory = $InstallRoot
  $lnk.Save()
  Write-Host "已创建桌面快捷方式: $lnkPath"
} catch {
  Write-Host "桌面快捷方式创建失败（可忽略）: $_" -ForegroundColor Yellow
}

# --- 5) 测 API ---
Write-Step "测试 EMS 接口"
try {
  $headers = @{ 'X-Api-Key' = 'ems-ict-gate-2026-dx' }
  $r = Invoke-RestMethod -Uri "$EmsBase/api/ict-gate/health" -Headers $headers
  Write-Host ("接口 OK: " + ($r | ConvertTo-Json -Compress)) -ForegroundColor Green
} catch {
  Write-Host "接口测试失败，请确认能访问 $EmsBase ：$_" -ForegroundColor Yellow
}

Write-Step "安装完成"
Write-Host @"

下一步：
1. 打开 TRI 测试软件，点到条码输入框
2. 双击桌面「ICT扫码闸道」或运行: $InstallRoot\start_ict_gate.bat
3. 扫码枪对准闸道窗口扫（不要直接扫 TRI）

安装目录: $InstallRoot
机台 ID: $machineId

"@ -ForegroundColor Green

$startNow = Read-Host "现在启动闸道？(Y/N)"
if ($startNow -match '^[Yy]') {
  Start-Process -FilePath (Join-Path $InstallRoot 'start_ict_gate.bat')
}
