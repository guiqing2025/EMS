#!/bin/zsh
# =============================================================================
# EMS【生产】完全启动 — 端口 8000（访问地址见 EMS_PUBLIC_URL 或自动探测本机局域网 IP）
# 默认连 Postgres（backend/.env.postgres）；回滚 SQLite：EMS_USE_SQLITE=1
# 开发请用：../start_dev_env.sh 或 ./start_ems_dev.sh（8001 + ems.dev.db）
# =============================================================================
# 用法：
#   ./start_ems.sh           # 未启动则启动；已在听端口则只提示
#   ./start_ems.sh --force   # 强制重启
#   ./start_ems.sh --smoke   # 仅冒烟检查
# =============================================================================
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"
LOG=/tmp/ems-uvicorn.log
LOCAL_URL="http://127.0.0.1:8000"
FORCE=0
SMOKE_ONLY=0
for arg in "$@"; do
  case "$arg" in
    --force|-f) FORCE=1 ;;
    --smoke|-s) SMOKE_ONLY=1 ;;
    --help|-h)
      sed -n '2,12p' "$0"
      exit 0
      ;;
  esac
done

ems_guess_public_url() {
  local port="${1:-8000}"
  if [[ -n "${EMS_PUBLIC_URL:-}" ]]; then
    echo "${EMS_PUBLIC_URL}"
    return
  fi
  local ip="" cand=""
  for iface in en0 en1 en2 en3 en4 en5 en6 en7 en8 en9 bridge0; do
    cand="$(ipconfig getifaddr "${iface}" 2>/dev/null || true)"
    [[ -z "${cand}" ]] && continue
    # 跳过链路本地 / 回环
    [[ "${cand}" == 169.254.* || "${cand}" == 127.* ]] && continue
    ip="${cand}"
    break
  done
  if [[ -z "${ip}" ]] && command -v ip >/dev/null 2>&1; then
    ip="$(ip -4 route get 1.1.1.1 2>/dev/null | awk '{for(i=1;i<=NF;i++) if($i=="src"){print $(i+1); exit}}')"
    [[ "${ip}" == 169.254.* || "${ip}" == 127.* ]] && ip=""
  fi
  if [[ -n "${ip}" ]]; then
    echo "http://${ip}:${port}"
  else
    echo "http://127.0.0.1:${port}"
  fi
}

# 加载本机路径覆盖（安全解析，避免路径空格被 source 拆坏）
LOCAL_ENV="${ROOT}/../env/local.env"
if [[ -f "${LOCAL_ENV}" ]]; then
  while IFS= read -r line || [[ -n "${line}" ]]; do
    line="${line#"${line%%[![:space:]]*}"}"
    [[ -z "${line}" || "${line}" == \#* ]] && continue
    [[ "${line}" != *=* ]] && continue
    key="${line%%=*}"
    val="${line#*=}"
    key="${key%"${key##*[![:space:]]}"}"
    val="${val#"${val%%[![:space:]]*}"}"
    val="${val%"${val##*[![:space:]]}"}"
    if [[ "${val}" == \"*\" ]]; then
      val="${val:1:${#val}-2}"
    elif [[ "${val}" == \'*\' ]]; then
      val="${val:1:${#val}-2}"
    fi
    [[ -n "${key}" ]] || continue
    export "${key}=${val}"
  done < "${LOCAL_ENV}"
  echo "已加载本机路径: env/local.env"
fi

PUBLIC_URL="$(ems_guess_public_url 8000)"

# 防止从开发 shell 继承 EMS_USE_SQLITE / EMS_DB / EMS_DEV_MODE 误连开发库
# 回滚 SQLite 必须在本脚本参数里显式带：EMS_USE_SQLITE=1 ./start_ems.sh --force
if [[ "${EMS_FORCE_SQLITE_ROLLBACK:-0}" != "1" ]]; then
  # 生产默认清掉开发残留；仅当调用方显式 EMS_USE_SQLITE=1 且未设 FORCE 标记时仍允许回滚路径
  if [[ "${EMS_USE_SQLITE:-0}" == "1" && "${EMS_ALLOW_DEV_DB:-0}" != "1" ]]; then
    # 若误带了 ems.dev.db，直接拒绝
    if [[ "${EMS_DB:-}" == "ems.dev.db" || "${EMS_DEV_MODE:-}" == "1" ]]; then
      echo "拒绝：检测到开发环境变量（EMS_DB=ems.dev.db 或 EMS_DEV_MODE=1），生产拒绝启动。"
      echo "请用干净环境启动，或显式：EMS_ALLOW_DEV_DB=1 EMS_USE_SQLITE=1 EMS_DB=ems.db $0 --force"
      exit 2
    fi
  fi
fi

# Postgres 16（Homebrew；Windows 请用 start_ems.ps1）
export PATH="/usr/local/opt/postgresql@16/bin:${PATH}"
export PATH="/opt/homebrew/opt/postgresql@16/bin:${PATH}"

# 数据库：默认生产用 .env.postgres；EMS_USE_SQLITE=1 则回滚 ems.db
if [[ "${EMS_USE_SQLITE:-0}" == "1" ]]; then
  unset DATABASE_URL || true
  unset EMS_DEV_MODE || true
  export EMS_DB="${EMS_DB:-ems.db}"
  echo "数据库模式: SQLite (${EMS_DB})  【回滚】"
elif [[ -f "${ROOT}/.env.postgres" ]]; then
  unset EMS_USE_SQLITE || true
  unset EMS_DB || true
  unset EMS_DEV_MODE || true
  set -a
  # shellcheck disable=SC1091
  source "${ROOT}/.env.postgres"
  set +a
  echo "数据库模式: Postgres (${EMS_PG_HOST:-127.0.0.1}:${EMS_PG_PORT:-5432}/${EMS_PG_DB:-ems_prod})"
else
  echo "错误: 未找到 ${ROOT}/.env.postgres，拒绝静默回退 SQLite（避免双库分裂）"
  echo "回滚请显式: EMS_USE_SQLITE=1 EMS_DB=ems.db $0 --force"
  exit 1
fi

# 启动环境：跳过启动期重审计；同步任务延后，避免刚起来就被 ICT SMB/锁库拖死
export EMS_SKIP_STARTUP_AUDIT="${EMS_SKIP_STARTUP_AUDIT:-1}"
export EMS_SYNC_WARMUP_SEC="${EMS_SYNC_WARMUP_SEC:-120}"

kill_port_8000() {
  local pids
  pids="$(lsof -nP -iTCP:8000 -sTCP:LISTEN -t 2>/dev/null || true)"
  if [[ -n "${pids}" ]]; then
    echo "结束旧进程: ${pids}"
    # shellcheck disable=SC2086
    kill ${pids} 2>/dev/null || true
    sleep 2
    pids="$(lsof -nP -iTCP:8000 -sTCP:LISTEN -t 2>/dev/null || true)"
    if [[ -n "${pids}" ]]; then
      # shellcheck disable=SC2086
      kill -9 ${pids} 2>/dev/null || true
      sleep 1
    fi
  fi
  pkill -f "uvicorn main:app --host 0.0.0.0 --port 8000" 2>/dev/null || true
}

wait_healthy() {
  local i code
  for i in $(seq 1 40); do
    code="$(curl -s -m 2 -o /dev/null -w '%{http_code}' "${LOCAL_URL}/" 2>/dev/null)" || code="000"
    if [[ "$code" == "200" ]]; then
      echo "健康检查通过（第 ${i} 次）"
      return 0
    fi
    echo "等待启动… ${i}/40 HTTP=${code:-000}"
    sleep 2
  done
  echo "启动超时。请看日志: tail -80 ${LOG}"
  return 1
}

run_smoke() {
  echo "—— 全模块冒烟 —— "
  "${ROOT}/.venv/bin/python" "${ROOT}/smoke_check.py" "${LOCAL_URL}"
}

if [[ "$SMOKE_ONLY" == "1" ]]; then
  run_smoke
  exit $?
fi

# 卸掉旧 LaunchAgent（否则无桌面共享盘权限）
launchctl bootout "gui/$(id -u)/com.dingxiong.ems.uvicorn" 2>/dev/null || true

if [[ "$FORCE" == "1" ]]; then
  kill_port_8000
elif lsof -nP -iTCP:8000 -sTCP:LISTEN >/dev/null 2>&1; then
  echo "端口 8000 已在监听。访问地址：${PUBLIC_URL}"
  echo "若要强制重启： $0 --force"
  echo "若只做检查：   $0 --smoke"
  exit 0
fi

SHARE="${WAREHOUSE_SHARE_PATH:-}"
if [[ -z "${SHARE}" && -f "${ROOT}/../env/local.env" ]]; then
  SHARE="$(grep -E '^WAREHOUSE_SHARE_PATH=' "${ROOT}/../env/local.env" | head -1 | cut -d= -f2-)"
fi
SHARE="${SHARE:-$HOME/Desktop/共享-测试软件资料/D-仓库表格/客户进销表}"
if ! /bin/ls "$SHARE" >/dev/null 2>&1; then
  echo "警告: 无法读取共享盘 $SHARE"
  echo "请确认已挂载，并在「系统设置 → 隐私与安全性」为终端/Python 开启桌面或完全磁盘访问。"
fi

# 日志过大时轮转，避免 /tmp/ems-uvicorn.log 涨到几百 MB 拖慢磁盘与排查
rotate_ems_log() {
  local max_bytes="${EMS_LOG_MAX_BYTES:-52428800}" # 默认 50MB
  local keep="${EMS_LOG_KEEP:-3}"
  [[ -f "${LOG}" ]] || return 0
  local size
  size="$(wc -c < "${LOG}" | tr -d ' ')"
  if [[ "${size}" -lt "${max_bytes}" ]]; then
    return 0
  fi
  local ts
  ts="$(date +%Y%m%d_%H%M%S)"
  local archived="${LOG}.${ts}.old"
  mv "${LOG}" "${archived}"
  : > "${LOG}"
  echo "日志已轮转: ${archived} (${size} bytes)"
  (gzip -f "${archived}" 2>/dev/null || true) &
  # 只保留最近 keep 份压缩归档
  ls -1t "${LOG}".*.old.gz 2>/dev/null | tail -n "+$((keep + 1))" | while read -r f; do
    rm -f "$f"
  done
}
rotate_ems_log

: > "${LOG}.boot"
echo "启动参数: EMS_SKIP_STARTUP_AUDIT=${EMS_SKIP_STARTUP_AUDIT} EMS_SYNC_WARMUP_SEC=${EMS_SYNC_WARMUP_SEC}"

# 用独立进程组启动，避免 Cursor/终端会话结束时把 uvicorn 一起杀掉
EMS_ROOT="$ROOT" EMS_LOG="$LOG" "${ROOT}/.venv/bin/python" - <<'PY'
import os, subprocess
from pathlib import Path
root = Path(os.environ["EMS_ROOT"])
log = Path(os.environ["EMS_LOG"])
env = os.environ.copy()
env["EMS_SKIP_STARTUP_AUDIT"] = os.environ.get("EMS_SKIP_STARTUP_AUDIT", "1")
env["EMS_SYNC_WARMUP_SEC"] = os.environ.get("EMS_SYNC_WARMUP_SEC", "120")
with log.open("a") as fh:
    p = subprocess.Popen(
        [str(root / ".venv/bin/uvicorn"), "main:app", "--host", "0.0.0.0", "--port", "8000"],
        cwd=str(root),
        stdout=fh,
        stderr=subprocess.STDOUT,
        env=env,
        start_new_session=True,
    )
Path("/tmp/ems-uvicorn.pid").write_text(str(p.pid))
print(p.pid)
PY
PID="$(cat /tmp/ems-uvicorn.pid 2>/dev/null || true)"
echo "EMS 已拉起 pid=${PID} ，日志 ${LOG}"

if ! wait_healthy; then
  exit 1
fi

echo "请用浏览器打开：${PUBLIC_URL}"
# 默认不冒烟；FORCE 时仍可用 EMS_RUN_SMOKE=1 或 --smoke 开启
if [[ "${EMS_RUN_SMOKE:-0}" == "1" ]]; then
  run_smoke || true
fi
