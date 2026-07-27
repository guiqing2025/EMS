# =============================================================================
# Windows：代码同步 + 本机适配
#   .\scripts\sync.ps1
#   .\scripts\sync.ps1 -BuildFrontend
#   .\scripts\sync.ps1 -NoPull
# =============================================================================
param(
    [switch]$BuildFrontend,
    [switch]$NoPull,
    [switch]$Help
)

$ErrorActionPreference = "Stop"
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $RepoRoot

if ($Help) {
    Write-Host "用法: .\scripts\sync.ps1 [-BuildFrontend] [-NoPull]"
    exit 0
}

Write-Host "=== EMS sync (Windows / 生产) ==="
Write-Host "仓库: $RepoRoot"

$hasGit = Test-Path (Join-Path $RepoRoot ".git")
if (-not $hasGit) {
    Write-Host "提示: 不是 Git 仓库，跳过 pull（仅做本机适配/依赖）。"
} else {
    Write-Host "—— git status ——"
    git status -sb
    $porcelain = git status --porcelain
    if ($porcelain) {
        Write-Host "提示: 有未提交改动；pull 可能冲突。"
    }

    if (-not $NoPull) {
        Write-Host "—— git pull --ff-only ——"
        git pull --ff-only
        if ($LASTEXITCODE -ne 0) {
            Write-Error "pull 失败。请人工处理冲突后再跑。"
        }
    }
}

$LocalEnv = Join-Path $RepoRoot "env\local.env"
if (-not (Test-Path $LocalEnv)) {
    Copy-Item (Join-Path $RepoRoot "env\env.windows.example") $LocalEnv
    Write-Host "已生成 env\local.env —— 请按本机共享盘修改后重跑。"
    exit 2
}
Write-Host "本机适配: env\local.env 已存在"
$role = "windows_prod"
Get-Content $LocalEnv -Encoding UTF8 | ForEach-Object {
    if ($_ -match '^EMS_ROLE=(.+)$') { $role = $Matches[1].Trim() }
}

$StampDir = Join-Path $RepoRoot "scripts\.sync_stamps"
New-Item -ItemType Directory -Force -Path $StampDir | Out-Null
function Get-FileSha([string]$p) {
    (Get-FileHash -Algorithm SHA256 -LiteralPath $p).Hash
}

$VenvPy = Join-Path $RepoRoot "backend\.venv\Scripts\python.exe"
if (-not (Test-Path $VenvPy)) {
    Write-Host "创建 venv…"
    python -m venv (Join-Path $RepoRoot "backend\.venv")
}
$req = Join-Path $RepoRoot "backend\requirements.txt"
$reqSha = Get-FileSha $req
$reqStamp = Join-Path $StampDir "requirements.sha"
if ((-not (Test-Path $reqStamp)) -or ((Get-Content $reqStamp -Raw).Trim() -ne $reqSha)) {
    Write-Host "—— pip install ——"
    & $VenvPy -m pip install --upgrade pip
    & $VenvPy -m pip install -r $req
    Set-Content $reqStamp $reqSha -Encoding ASCII
} else {
    Write-Host "Python 依赖: 无变化"
}

$pkg = Join-Path $RepoRoot "frontend\package.json"
if (Test-Path $pkg) {
    $npm = Get-Command npm -ErrorAction SilentlyContinue
    if ($npm) {
        $pkgSha = Get-FileSha $pkg
        $pkgStamp = Join-Path $StampDir "package.sha"
        $nm = Join-Path $RepoRoot "frontend\node_modules"
        if ((-not (Test-Path $pkgStamp)) -or ((Get-Content $pkgStamp -Raw).Trim() -ne $pkgSha) -or (-not (Test-Path $nm))) {
            Write-Host "—— npm install ——"
            Push-Location (Join-Path $RepoRoot "frontend")
            npm install
            Pop-Location
            Set-Content $pkgStamp $pkgSha -Encoding ASCII
        } else {
            Write-Host "前端依赖: 无变化"
        }
    } else {
        Write-Host "提示: 无 npm，跳过 frontend install"
    }
}

if ($BuildFrontend) {
    Write-Host "—— vite build ——"
    Push-Location (Join-Path $RepoRoot "frontend")
    npx vite build
    Pop-Location
}

Write-Host ""
Write-Host "当前角色: $role （Windows 生产）"
$pg = Join-Path $RepoRoot "backend\.env.postgres"
if (Test-Path $pg) {
    Write-Host "DB 配置: backend\.env.postgres 存在"
} else {
    Write-Host "DB 配置: 缺少 .env.postgres —— 请复制 example 或跑 bootstrap_windows.ps1"
}
Write-Host "下一步:"
Write-Host "  启动生产:  cd backend; .\start_ems.ps1 -Force"
Write-Host "  导出生产库给 Mac:  .\scripts\export_db.ps1"
