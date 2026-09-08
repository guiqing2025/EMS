#!/bin/zsh
# 开发环境 · 局域网演示（老板可在同一网段打开你电脑上的看板）
# 只动 5173 / 8001，绝不碰生产 8000。
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
BACKEND="$ROOT/backend"
FRONTEND="$ROOT/frontend"
NODE="/Applications/Cursor.app/Contents/Resources/app/resources/helpers/node"
[[ -x "$NODE" ]] || NODE="$(command -v node || true)"
[[ -n "${NODE}" && -x "$NODE" ]] || { echo "找不到 node"; exit 1; }

lan_ip() {
  # 优先取常见内网口
  local ip
  ip="$(ipconfig getifaddr en0 2>/dev/null || true)"
  [[ -n "$ip" ]] || ip="$(ipconfig getifaddr en1 2>/dev/null || true)"
  if [[ -z "$ip" ]]; then
    ip="$(ifconfig 2>/dev/null | awk '/inet / && $2 !~ /^127\./ {print $2; exit}')"
  fi
  echo "${ip:-<请手动查看本机 IP>}"
}

# 准备开发库
if [[ ! -f "$BACKEND/ems.dev.db" ]]; then
  echo "首次复制生产库 → ems.dev.db …"
  if command -v sqlite3 >/dev/null 2>&1; then
    sqlite3 "$BACKEND/ems.db" ".backup $BACKEND/ems.dev.db"
  else
    cp -f "$BACKEND/ems.db" "$BACKEND/ems.dev.db"
  fi
fi

echo "停止仅本机监听的开发进程（不影响 8000 生产）…"
pkill -f 'uvicorn main:app --host 127.0.0.1 --port 8001' 2>/dev/null || true
pkill -f 'uvicorn main:app --host 0.0.0.0 --port 8001' 2>/dev/null || true
pkill -f 'vite.js --host 127.0.0.1 --port 5173' 2>/dev/null || true
pkill -f 'vite.js --host 0.0.0.0 --port 5173' 2>/dev/null || true
# 兼容未带 host 参数的残留
lsof -nP -iTCP:8001 -sTCP:LISTEN -t 2>/dev/null | while read -r pid; do
  cmd="$(ps -p "$pid" -o command= 2>/dev/null || true)"
  if [[ "$cmd" == *'port 8001'* || "$cmd" == *':8001'* || "$cmd" == *uvicorn* ]]; then
    kill "$pid" 2>/dev/null || true
  fi
done
lsof -nP -iTCP:5173 -sTCP:LISTEN -t 2>/dev/null | while read -r pid; do
  cmd="$(ps -p "$pid" -o command= 2>/dev/null || true)"
  if [[ "$cmd" == *vite* || "$cmd" == *5173* ]]; then
    kill "$pid" 2>/dev/null || true
  fi
done
sleep 1

BACKEND_CMD="cd '$BACKEND' && export EMS_DB=ems.dev.db EMS_DEV_MODE=1 && exec '$BACKEND/.venv/bin/uvicorn' main:app --host 0.0.0.0 --port 8001 --reload"
FRONTEND_CMD="cd '$FRONTEND' && exec '$NODE' '$FRONTEND/node_modules/vite/bin/vite.js' --host 0.0.0.0 --port 5173"

osascript <<EOF
tell application "Terminal"
  activate
  do script "$BACKEND_CMD"
  delay 1.5
  do script "$FRONTEND_CMD"
end tell
EOF

IP="$(lan_ip)"
echo "已在「终端」启动局域网开发服务，等待就绪…"
for i in {1..40}; do
  sleep 1
  ok8001=0; ok5173=0
  lsof -nP -iTCP:8001 -sTCP:LISTEN >/dev/null 2>&1 && ok8001=1
  lsof -nP -iTCP:5173 -sTCP:LISTEN >/dev/null 2>&1 && ok5173=1
  if [[ "$ok8001" -eq 1 && "$ok5173" -eq 1 ]]; then
    echo
    echo "=============================================="
    echo "  局域网演示已就绪（开发库，非生产）"
    echo "  看板地址： http://${IP}:5173/dashboard"
    echo "  登录账号： dx001 / dx002 / dx003 / wgq"
    echo "  （密码与平时系统登录相同）"
    echo "  本机也可： http://127.0.0.1:5173/dashboard"
    echo "  生产勿动： 本机 :8000"
    echo "=============================================="
    echo
    echo "提示：老板需与你同一局域网；若打不开，检查 Mac「系统设置 → 网络 → 防火墙」。"
    exit 0
  fi
  printf '.'
done
echo
echo "超时未全部就绪。请查看新打开的终端窗口报错。"
echo "8001=$([[ $ok8001 -eq 1 ]] && echo ok || echo fail)  5173=$([[ $ok5173 -eq 1 ]] && echo ok || echo fail)"
exit 1
