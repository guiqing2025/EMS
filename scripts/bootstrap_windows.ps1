# =============================================================================
# EMS Windows 首次安装 / 依赖齐套
# 建议：以「管理员」打开 PowerShell，在仓库根目录执行：
#   Set-ExecutionPolicy -Scope Process Bypass
#   .\scripts\bootstrap_windows.ps1
# =============================================================================
param(
    [switch]$SkipWinget,
    [switch]$SkipDb,
    [switch]$SkipFrontend,
    [string]$PgPassword = ""
)

$ErrorActionPreference = "Stop"
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$Backend = Join-Path $RepoRoot "backend"
$Frontend = Join-Path $RepoRoot "frontend"
Set-Location $RepoRoot

Write-Host "=== EMS Windows bootstrap ==="
Write-Host "仓库: $RepoRoot"

function Ensure-WingetPkg([string]$Id, [string]$Name) {
    Write-Host "安装/确认: $Name ($Id)"
    winget install --id $Id -e --accept-package-agreements --accept-source-agreements --disable-interactivity
}

if (-not $SkipWinget) {
    if (-not (Get-Command winget -ErrorAction SilentlyContinue)) {
        Write-Error "未找到 winget。请先安装「应用安装程序」或手动安装 Python/Node/PostgreSQL/Git。"
    }
    Ensure-WingetPkg "Python.Python.3.11" "Python 3.11"
    Ensure-WingetPkg "OpenJS.NodeJS.LTS" "Node.js LTS"
    Ensure-WingetPkg "PostgreSQL.PostgreSQL.16" "PostgreSQL 16"
    Ensure-WingetPkg "Git.Git" "Git"
    # 刷新 PATH
    $env:Path = [System.Environment]::GetEnvironmentVariable("Path", "Machine") + ";" +
                [System.Environment]::GetEnvironmentVariable("Path", "User")
}

$py = Get-Command python -ErrorAction SilentlyContinue
if (-not $py) { $py = Get-Command py -ErrorAction SilentlyContinue }
if (-not $py) { Write-Error "未找到 python，请重开终端后再跑本脚本。" }
Write-Host "Python: $($py.Source)"

# env/local.env
$LocalEnv = Join-Path $RepoRoot "env\local.env"
$WinExample = Join-Path $RepoRoot "env\env.windows.example"
if (-not (Test-Path $LocalEnv)) {
    Copy-Item $WinExample $LocalEnv
    Write-Host "已生成 env\local.env （请按本机共享盘路径修改）"
} else {
    Write-Host "已存在 env\local.env"
}

# .env.postgres
$PgEnv = Join-Path $Backend ".env.postgres"
$PgExample = Join-Path $Backend ".env.postgres.example"
if (-not (Test-Path $PgEnv)) {
    if (-not $PgPassword) {
        $bytes = New-Object byte[] 24
        [System.Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($bytes)
        $PgPassword = [Convert]::ToBase64String($bytes).Replace("+", "A").Replace("/", "B").Substring(0, 24)
    }
    $content = (Get-Content $PgExample -Raw -Encoding UTF8).
        Replace("change_me", $PgPassword)
    Set-Content -Path $PgEnv -Value $content -Encoding UTF8
    Write-Host "已生成 backend\.env.postgres （密码已随机生成，请妥善保存）"
} else {
    Write-Host "已存在 backend\.env.postgres"
    # 读出现有密码供建库
    Get-Content $PgEnv -Encoding UTF8 | ForEach-Object {
        if ($_ -match '^EMS_PG_PASSWORD=(.+)$') { $PgPassword = $Matches[1].Trim().Trim('"') }
    }
}

# venv + pip
$Venv = Join-Path $Backend ".venv"
$VenvPy = Join-Path $Venv "Scripts\python.exe"
if (-not (Test-Path $VenvPy)) {
    Write-Host "创建 venv…"
    & $py.Source -m venv $Venv
}
Write-Host "安装 Python 依赖…"
& $VenvPy -m pip install --upgrade pip
& $VenvPy -m pip install -r (Join-Path $Backend "requirements.txt")

# Postgres 库
if (-not $SkipDb) {
    $psql = Get-Command psql -ErrorAction SilentlyContinue
    if (-not $psql) {
        $cand = @(
            "C:\Program Files\PostgreSQL\16\bin\psql.exe",
            "C:\Program Files\PostgreSQL\15\bin\psql.exe"
        ) | Where-Object { Test-Path $_ } | Select-Object -First 1
        if ($cand) {
            $env:Path = "$(Split-Path $cand);$env:Path"
            $psql = Get-Command psql
        }
    }
    if ($psql) {
        Write-Host "初始化 Postgres 用户/库（若已存在会忽略错误）…"
        $env:PGPASSWORD = if ($env:POSTGRES_SUPER_PASSWORD) { $env:POSTGRES_SUPER_PASSWORD } else { "postgres" }
        $sql = @"
DO `$`$
BEGIN
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'ems') THEN
    CREATE ROLE ems LOGIN PASSWORD '$PgPassword';
  END IF;
END
`$`$;
SELECT 'ok';
"@
        try {
            & psql -U postgres -h 127.0.0.1 -c $sql 2>$null
            & psql -U postgres -h 127.0.0.1 -c "CREATE DATABASE ems_prod OWNER ems;" 2>$null
            Write-Host "数据库 ems_prod 就绪（或已存在）"
        } catch {
            Write-Host "警告: 自动建库失败，请用 pgAdmin 手工创建用户 ems / 库 ems_prod，并核对 .env.postgres"
        }
        Remove-Item Env:PGPASSWORD -ErrorAction SilentlyContinue
    } else {
        Write-Host "警告: 未找到 psql，跳过自动建库。请手工创建 ems / ems_prod。"
    }

    # migrate
    if (Test-Path (Join-Path $Backend "migrate_postgres.py")) {
        Write-Host "运行 migrate_postgres.py…"
        Push-Location $Backend
        try {
            Get-Content ".env.postgres" -Encoding UTF8 | ForEach-Object {
                if ($_ -match '^\s*#' -or $_ -notmatch '=') { return }
                $i = $_.IndexOf("="); $k = $_.Substring(0, $i).Trim(); $v = $_.Substring($i + 1).Trim()
                [Environment]::SetEnvironmentVariable($k, $v, "Process")
            }
            & $VenvPy migrate_postgres.py
        } catch {
            Write-Host "migrate 警告: $_ （可稍后手动执行）"
        }
        Pop-Location
    }
}

# frontend
if (-not $SkipFrontend) {
    $npm = Get-Command npm -ErrorAction SilentlyContinue
    if (-not $npm) {
        Write-Host "警告: 未找到 npm，跳过前端构建"
    } else {
        Write-Host "npm install + vite build…"
        Push-Location $Frontend
        npm install
        npx vite build
        Pop-Location
    }
}

Write-Host ""
Write-Host "=== bootstrap 完成 ==="
Write-Host "1) 编辑 env\local.env 填好共享盘路径"
Write-Host "2) 确认 backend\.env.postgres"
Write-Host "3) 启动:  cd backend; .\start_ems.ps1 -Force"
Write-Host "4) 日常同步:  ..\scripts\sync.ps1"
