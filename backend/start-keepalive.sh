#!/bin/bash
# 长期运行：崩溃后自动重启。在本机终端执行并保持窗口打开：
#   cd /Users/dx/Desktop/EMS/backend && ./start-keepalive.sh
cd "$(dirname "$0")"
HOST="${EMS_HOST:-0.0.0.0}"
PORT="${EMS_PORT:-8000}"
LOG="${EMS_LOG:-/tmp/ems-uvicorn.log}"

while true; do
  echo "$(date '+%F %T') 启动 EMS 服务..." >> "$LOG"
  .venv/bin/uvicorn main:app --host "$HOST" --port "$PORT" >> "$LOG" 2>&1
  code=$?
  echo "$(date '+%F %T') 服务退出(code=$code)，3 秒后重启..." >> "$LOG"
  sleep 3
done
