#!/bin/zsh
# 快捷入口：完全启动 / 强制重启 EMS 生产服务
exec "$(cd "$(dirname "$0")" && pwd)/backend/start_ems.sh" "$@"
