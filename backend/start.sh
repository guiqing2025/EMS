#!/bin/bash
# 简易启动：监听 0.0.0.0（本机与局域网均可访问）
# 对外地址请用 EMS_PUBLIC_URL，或由 start_ems.sh 自动探测本机 IP
cd "$(dirname "$0")"
HOST="${EMS_HOST:-0.0.0.0}"
PORT="${EMS_PORT:-8000}"
exec .venv/bin/uvicorn main:app --host "$HOST" --port "$PORT"
