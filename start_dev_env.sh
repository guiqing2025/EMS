#!/bin/zsh
# 在 macOS「终端.app」中常驻启动开发环境（不跟 Cursor 会话一起死）
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
BACKEND="$ROOT/backend"
FRONTEND="$ROOT/frontend"
NODE="/Applications/Cursor.app/Contents/Resources/app/resources/helpers/node"
[[ -x "$NODE" ]] || NODE="$(command -v node || true)"
[[ -n "${NODE}" && -x "$NODE" ]] || { echo "找不到 node"; exit 1; }

# 若已在听则直接提示
ok8001=0; ok5173=0
lsof -nP -iTCP:8001 -sTCP:LISTEN >/dev/null 2>&1 && ok8001=1
lsof -nP -iTCP:5173 -sTCP:LISTEN >/dev/null 2>&1 && ok5173=1
if [[ "$ok8001" -eq 1 && "$ok5173" -eq 1 ]]; then
  echo "开发环境已在运行："
  echo "  http://127.0.0.1:5173"
  echo "  http://127.0.0.1:8001/docs"
  exit 0
fi

# 准备开发库
if [[ ! -f "$BACKEND/ems.dev.db" ]]; then
  echo "首次复制生产库 → ems.dev.db …"
  if command -v sqlite3 >/dev/null 2>&1; then
    sqlite3 "$BACKEND/ems.db" ".backup $BACKEND/ems.dev.db"
  else
    cp -f "$BACKEND/ems.db" "$BACKEND/ems.dev.db"
  fi
fi

# 清掉 Cursor 残留的半死进程
pkill -f 'uvicorn main:app --host 127.0.0.1 --port 8001' 2>/dev/null || true
pkill -f 'vite.js --host 127.0.0.1 --port 5173' 2>/dev/null || true
sleep 1

BACKEND_CMD="cd '$BACKEND' && unset DATABASE_URL; export EMS_DB=ems.dev.db EMS_USE_SQLITE=1 EMS_DEV_MODE=1 && exec '$BACKEND/.venv/bin/uvicorn' main:app --host 127.0.0.1 --port 8001 --reload"
FRONTEND_CMD="cd '$FRONTEND' && exec '$NODE' '$FRONTEND/node_modules/vite/bin/vite.js' --host 127.0.0.1 --port 5173"

osascript <<EOF
tell application "Terminal"
  activate
  do script "$BACKEND_CMD"
  delay 1.5
  do script "$FRONTEND_CMD"
end tell
EOF

echo "已在「终端」打开两个窗口启动开发服务，等待就绪…"
for i in {1..30}; do
  sleep 1
  ok8001=0; ok5173=0
  lsof -nP -iTCP:8001 -sTCP:LISTEN >/dev/null 2>&1 && ok8001=1
  lsof -nP -iTCP:5173 -sTCP:LISTEN >/dev/null 2>&1 && ok5173=1
  if [[ "$ok8001" -eq 1 && "$ok5173" -eq 1 ]]; then
    echo
    echo "开发环境已就绪（常驻终端，关 Cursor 也不停）："
    echo "  前端: http://127.0.0.1:5173"
    echo "  API:  http://127.0.0.1:8001/docs"
    echo "  生产: 本机 :8000（地址见 EMS_PUBLIC_URL 或启动脚本探测的局域网 IP）"
    curl -s -o /dev/null -w "检查 5173=%{http_code} 8001=%{http_code}\n" http://127.0.0.1:5173/ http://127.0.0.1:8001/docs
    exit 0
  fi
  printf '.'
done
echo
echo "超时未全部就绪。请查看新打开的终端窗口报错。"
echo "8001=$([[ $ok8001 -eq 1 ]] && echo ok || echo fail)  5173=$([[ $ok5173 -eq 1 ]] && echo ok || echo fail)"
exit 1
