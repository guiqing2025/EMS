#!/bin/zsh
# EMS 开发实例：端口 8001 + 独立库 ems.dev.db，不影响同事使用的 8000 生产。
# 用法：
#   ./start_ems_dev.sh           # 前台 + --reload（Cursor/本机终端开发）
#   ./start_ems_dev.sh --bg      # 后台 nohup
#   ./start_ems_dev.sh --refresh # 从生产 ems.db 重新拷一份开发库后再启动
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

PORT=8001
DB_DEV="ems.dev.db"
DB_PROD="ems.db"
LOG=/tmp/ems-uvicorn-dev.log
PUBLIC_URL="http://127.0.0.1:${PORT}"
MODE="fg"
REFRESH=0

for arg in "$@"; do
  case "$arg" in
    --bg) MODE="bg" ;;
    --refresh) REFRESH=1 ;;
    -h|--help)
      sed -n '2,8p' "$0"
      exit 0
      ;;
  esac
done

if lsof -nP -iTCP:"$PORT" -sTCP:LISTEN >/dev/null 2>&1; then
  echo "开发端口 ${PORT} 已在监听。访问：${PUBLIC_URL}"
  echo "前端：../frontend/start_frontend_dev.sh → http://127.0.0.1:5173"
  exit 0
fi

if [[ ! -f "$DB_PROD" ]]; then
  echo "错误：找不到生产库 $ROOT/$DB_PROD"
  exit 1
fi

if [[ "$REFRESH" -eq 1 || ! -f "$DB_DEV" ]]; then
  echo "正在复制生产库 → ${DB_DEV} …"
  if command -v sqlite3 >/dev/null 2>&1; then
    rm -f "$DB_DEV"
    sqlite3 "$DB_PROD" ".backup $DB_DEV"
  else
    cp -f "$DB_PROD" "$DB_DEV"
  fi
  echo "开发库已就绪：$(du -h "$DB_DEV" | awk '{print $1}')"
fi

# 强制开发走 SQLite，避免 shell 里残留的 DATABASE_URL 误连生产 Postgres
unset DATABASE_URL || true
export EMS_DB="$DB_DEV"
export EMS_USE_SQLITE=1
export EMS_DEV_MODE=1

echo "EMS 开发实例"
echo "  端口: ${PORT}"
echo "  数据库: ${ROOT}/${DB_DEV}（SQLite，已屏蔽 DATABASE_URL）"
echo "  定时同步: 关闭（不影响生产扫盘）"
echo "  API: ${PUBLIC_URL}/docs"
echo "  前端: ../frontend/start_frontend_dev.sh → http://127.0.0.1:5173（已代理到 8001）"
echo "  生产同事入口仍是: http://192.168.2.168:8000"
echo

if [[ "$MODE" == "bg" ]]; then
  nohup "$ROOT/.venv/bin/uvicorn" main:app --host 127.0.0.1 --port "$PORT" --reload \
    >>"$LOG" 2>&1 &
  echo "已后台启动 pid=$! ，日志 $LOG"
else
  exec "$ROOT/.venv/bin/uvicorn" main:app --host 127.0.0.1 --port "$PORT" --reload
fi
