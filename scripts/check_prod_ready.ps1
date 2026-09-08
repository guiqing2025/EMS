# Preflight checklist: can this PC run EMS like the old production box?
# Usage: C:\EMS\scripts\check_prod_ready.ps1
$ErrorActionPreference = "Continue"
$RepoRoot = "C:\EMS"
$Backend = Join-Path $RepoRoot "backend"
$ok = 0
$bad = 0

function Show([string]$status, [string]$msg) {
    Write-Host ("[{0}] {1}" -f $status, $msg)
    if ($status -eq "OK") { $script:ok++ } else { $script:bad++ }
}

Write-Host "=== EMS production readiness ==="
Write-Host ""

# 1 code
if (Test-Path (Join-Path $Backend "main.py")) { Show "OK" "Source code present" } else { Show "FAIL" "Source code missing" }

# 2 venv
if (Test-Path (Join-Path $Backend ".venv\Scripts\uvicorn.exe")) { Show "OK" "Python venv ready" } else { Show "FAIL" "venv missing" }

# 3 frontend build
if (Test-Path (Join-Path $Backend "static\vue\index.html")) { Show "OK" "Frontend built" } else { Show "FAIL" "Frontend not built (run npm/vite build)" }

# 4 config
if (Test-Path (Join-Path $Backend "srm_config.json")) { Show "OK" "srm_config.json present (API customers)" } else { Show "FAIL" "srm_config.json missing" }

# 5 db
$db = Join-Path $Backend "ems.db"
if (Test-Path $db) {
    $mb = [math]::Round((Get-Item $db).Length / 1MB, 1)
    if ((Get-Item $db).Length -ge 5MB) { Show "OK" "ems.db size ${mb}MB (looks like real data)" }
    else { Show "NEED" "ems.db only ${mb}MB — import old production ems.db once" }
} else { Show "NEED" "ems.db missing — import old production ems.db once" }

# 6 local.env paths
$localEnv = Join-Path $RepoRoot "env\local.env"
$shareOk = $false
if (Test-Path $localEnv) {
    Show "OK" "env\local.env exists"
    Get-Content $localEnv -Encoding UTF8 | ForEach-Object {
        if ($_ -match '^(EMS_SHARE_ROOT|WAREHOUSE_SHARE_PATH|HR_ROSTER_PATH|ENGINEERING_SHARE_BASE)=(.*)$') {
            $k = $Matches[1]; $v = $Matches[2].Trim().Trim('"')
            if ($v -and (Test-Path -LiteralPath $v)) {
                Show "OK" "$k reachable: $v"
                if ($k -eq "EMS_SHARE_ROOT") { $shareOk = $true }
            } elseif ($v) {
                Show "NEED" "$k NOT reachable: $v  (map network drive / fix path)"
            }
        }
    }
} else {
    Show "NEED" "env\local.env missing"
}

# 7 network drives
$maps = net use 2>$null | Out-String
if ($maps -match "OK|\\\\") { Show "OK" "Some network drives mapped" } else { Show "NEED" "No network drives mapped (net use is empty)" }

# 8 service listening
$listen = Get-NetTCPConnection -LocalPort 8888 -State Listen -ErrorAction SilentlyContinue
if ($listen) { Show "OK" "EMS listening on :8888" } else { Show "NEED" "EMS not running — start_local_windows.ps1 -Force" }

# 9 IP
$ip = (Get-NetIPAddress -InterfaceIndex 8 -AddressFamily IPv4 -ErrorAction SilentlyContinue | Where-Object { $_.IPAddress -like '192.168.*' }).IPAddress
if ($ip -eq "192.168.2.168") { Show "OK" "Static IP is 192.168.2.168" }
elseif ($ip) { Show "NEED" "Current IP is $ip (wanted 192.168.2.168)" }
else { Show "NEED" "No LAN IPv4 found" }

Write-Host ""
Write-Host "=== Summary ==="
Write-Host "You do NOT keep copying forever."
Write-Host "Copy ems.db ONCE for history; then auto-sync keeps modules updating."
Write-Host "Auto-sync needs: reachable share paths + running service (not DEV_MODE)."
Write-Host ""
if ($bad -eq 0) {
    Write-Host "All checks passed."
} else {
    Write-Host "Pending items above marked NEED/FAIL. Fix those, then restart EMS."
}
