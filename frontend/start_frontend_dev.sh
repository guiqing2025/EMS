#!/bin/zsh
# 启动前端 Vite 开发服（5173），代理到 8001。
# 优先系统 node/npm；若无则用 Cursor 自带 node + 本地 vite。
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"
PORT=5173
LOG=/tmp/ems-vite-dev.log

if lsof -nP -iTCP:"$PORT" -sTCP:LISTEN >/dev/null 2>&1; then
  echo "Vite 已在监听 ${PORT} → http://127.0.0.1:${PORT}"
  exit 0
fi

# 确保开发后端 8001 在跑
if ! lsof -nP -iTCP:8001 -sTCP:LISTEN >/dev/null 2>&1; then
  echo "开发后端 8001 未启动，正在拉起…"
  /Users/dx/EMS/backend/start_ems_dev.sh --bg
  sleep 3
fi

pick_node() {
  if command -v node >/dev/null 2>&1; then
    command -v node
    return
  fi
  local candidates=(
    "/Applications/Cursor.app/Contents/Resources/app/resources/helpers/node"
    "/opt/homebrew/bin/node"
    "/usr/local/bin/node"
  )
  for n in "${candidates[@]}"; do
    if [[ -x "$n" ]]; then
      echo "$n"
      return
    fi
  done
  return 1
}

NODE="$(pick_node)" || {
  echo "错误：找不到 node。请安装 Node.js，或确认已安装 Cursor。"
  exit 1
}

VITE="$ROOT/node_modules/vite/bin/vite.js"
if [[ ! -f "$VITE" ]]; then
  echo "错误：缺少依赖，请先在本目录安装：npm install"
  exit 1
fi

echo "使用 node: $NODE"
echo "Vite → http://127.0.0.1:${PORT} （API 代理 → 8001）"
nohup "$NODE" "$VITE" --host 127.0.0.1 --port "$PORT" >>"$LOG" 2>&1 &
echo "已启动 pid=$! ，日志 $LOG"
