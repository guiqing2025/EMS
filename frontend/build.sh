#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")"
if ! command -v npm >/dev/null 2>&1; then
  echo "未找到 npm，请先安装 Node.js 18+：https://nodejs.org/"
  exit 1
fi
npm install
npm run build
echo "构建完成：backend/static/vue/"
