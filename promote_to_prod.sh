#!/bin/zsh
# 将当前代码发布到生产 8000（不覆盖生产库）
exec "$(cd "$(dirname "$0")" && pwd)/backend/promote_to_prod.sh" "$@"
