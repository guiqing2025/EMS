#!/bin/zsh
# =============================================================================
# Mac：把 Windows 导出的生产 dump 导入【开发库】（默认 ems_dev）
#   ./scripts/import_db_dev.sh /path/to/ems_prod_YYYYMMDD.dump
#
# 安全：拒绝写入 ems_prod；拒绝在未设 EMS_ALLOW_DEV_DB_IMPORT=1 时覆盖
# =============================================================================
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DUMP="${1:-}"
if [[ -z "$DUMP" || ! -f "$DUMP" ]]; then
  echo "用法: $0 <ems_prod_xxx.dump>"
  exit 1
fi

# 默认开发库名（与生产 ems_prod 隔离）
DEV_DB="${EMS_DEV_PG_DB:-ems_dev}"
HOST="${EMS_PG_HOST:-127.0.0.1}"
PORT="${EMS_PG_PORT:-5432}"
USER="${EMS_PG_USER:-ems}"

if [[ "$DEV_DB" == "ems_prod" ]]; then
  echo "拒绝：开发导入目标不能是 ems_prod"
  exit 2
fi

if [[ "${EMS_ALLOW_DEV_DB_IMPORT:-0}" != "1" ]]; then
  echo "将导入到开发库: ${USER}@${HOST}:${PORT}/${DEV_DB}"
  echo "确认无误后执行:"
  echo "  EMS_ALLOW_DEV_DB_IMPORT=1 $0 \"$DUMP\""
  exit 3
fi

# 加载密码：优先开发 env，其次 .env.postgres（仅取密码）
if [[ -f "$ROOT/backend/.env.postgres" ]]; then
  # shellcheck disable=SC1091
  set -a
  source "$ROOT/backend/.env.postgres"
  set +a
fi
export PGPASSWORD="${EMS_PG_PASSWORD:-${PGPASSWORD:-}}"

export PATH="/opt/homebrew/opt/postgresql@16/bin:/usr/local/opt/postgresql@16/bin:${PATH}"

echo "确保开发库存在: $DEV_DB"
psql -h "$HOST" -p "$PORT" -U "$USER" -d postgres -tc "SELECT 1 FROM pg_database WHERE datname='${DEV_DB}'" | grep -q 1 \
  || psql -h "$HOST" -p "$PORT" -U postgres -c "CREATE DATABASE ${DEV_DB} OWNER ${USER};" \
  || psql -h "$HOST" -p "$PORT" -U "$USER" -d postgres -c "CREATE DATABASE ${DEV_DB};"

echo "清空并恢复（自定义格式）…"
pg_restore -h "$HOST" -p "$PORT" -U "$USER" -d "$DEV_DB" --clean --if-exists --no-owner --no-acl "$DUMP" \
  || echo "警告: pg_restore 有非零退出（常见于权限/扩展提示），请抽查表计数"

echo "完成。请用开发库连接串启动，例如："
echo "  DATABASE_URL=postgresql+psycopg://${USER}@${HOST}:${PORT}/${DEV_DB} backend/start_ems_dev.sh"
echo "切勿把该库当生产 8000 使用。"
