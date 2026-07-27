#!/bin/zsh
# Mac 依赖校验 / 补齐（不强制重装系统软件）
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
BACKEND="$ROOT/backend"
FRONTEND="$ROOT/frontend"

echo "=== EMS Mac bootstrap / check ==="
echo "仓库: $ROOT"

if [[ ! -f "$ROOT/env/local.env" ]]; then
  cp "$ROOT/env/env.mac.example" "$ROOT/env/local.env"
  echo "已生成 env/local.env"
else
  echo "已存在 env/local.env"
fi

if [[ ! -d "$BACKEND/.venv" ]]; then
  python3 -m venv "$BACKEND/.venv"
fi
"$BACKEND/.venv/bin/pip" install -q --upgrade pip
"$BACKEND/.venv/bin/pip" install -q -r "$BACKEND/requirements.txt"

if [[ ! -f "$BACKEND/.env.postgres" && -f "$BACKEND/.env.postgres.example" ]]; then
  echo "提示: 缺少 backend/.env.postgres（生产用）。开发可用 start_ems_dev.sh。"
fi

if command -v npm >/dev/null 2>&1; then
  (cd "$FRONTEND" && npm install)
else
  echo "提示: 未找到 npm；前端可用 Cursor 自带 node 构建。"
fi

echo "完成。开发启动: ./start_ems_dev.sh 或 ./start_dev_env.sh"
echo "同步: ./scripts/sync.sh"
