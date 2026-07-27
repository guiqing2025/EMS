#!/bin/bash
# 内网固定访问：http://192.168.2.168:8000
# （本机 USB 网卡静态 IP；服务监听 0.0.0.0，兼容本机与局域网）
cd "$(dirname "$0")"
HOST="${EMS_HOST:-0.0.0.0}"
PORT="${EMS_PORT:-8000}"
exec .venv/bin/uvicorn main:app --host "$HOST" --port "$PORT"
