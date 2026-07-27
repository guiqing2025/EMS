#!/bin/zsh
# =============================================================================
# 把当前代码热更新到生产（192.168.2.168:8000）
# - 只重启生产进程，让它加载磁盘上的最新代码/静态资源
# - 绝不覆盖 ems.db（生产数据）
# - 绝不拿 ems.dev.db 去替换生产库
#
# 用法：
#   ./promote_to_prod.sh              # 需输入 YES 确认
#   ./promote_to_prod.sh --yes        # 跳过确认（脚本/CI）
#   ./promote_to_prod.sh --smoke      # 发布后跑冒烟
# =============================================================================
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"
PUBLIC_URL="${EMS_PUBLIC_URL:-http://192.168.2.168:8000}"
YES=0
SMOKE=0
for arg in "$@"; do
  case "$arg" in
    --yes|-y) YES=1 ;;
    --smoke|-s) SMOKE=1 ;;
    -h|--help) sed -n '2,14p' "$0"; exit 0 ;;
  esac
done

echo "即将发布到生产："
echo "  地址: ${PUBLIC_URL}"
echo "  代码: ${ROOT}（与开发同一份源码）"
echo "  数据库: ${ROOT}/ems.db  —— 不会被改动"
echo "  开发库: ${ROOT}/ems.dev.db —— 不会写入生产"
echo

if [[ "$YES" != "1" ]]; then
  print -n "确认发布？请输入 YES："
  read -r ans
  [[ "$ans" == "YES" ]] || { echo "已取消"; exit 1; }
fi

# 安全闸：拒绝任何「用开发库覆盖生产库」的误操作环境变量
if [[ "${EMS_PROMOTE_DB:-}" == "1" ]]; then
  echo "拒绝：本脚本禁止拷贝数据库。若必须迁移数据，请人工处理并先备份 ems.db。"
  exit 2
fi

export EMS_RUN_SMOKE=0
if [[ "$SMOKE" == "1" ]]; then
  export EMS_RUN_SMOKE=1
fi

# 前端有改动时需先构建到 static/vue（本机若无 npm，用 Cursor 自带 node 跑 vite）
FRONTEND="$(cd "$ROOT/.." && pwd)/frontend"
if [[ -f "$FRONTEND/package.json" ]]; then
  NODE_BIN="$(command -v node || true)"
  if [[ -z "$NODE_BIN" && -x "/Applications/Cursor.app/Contents/Resources/app/resources/helpers/node" ]]; then
    NODE_BIN="/Applications/Cursor.app/Contents/Resources/app/resources/helpers/node"
  fi
  if [[ -n "$NODE_BIN" && -x "$FRONTEND/node_modules/vite/bin/vite.js" ]]; then
    echo "构建前端 → backend/static/vue/ …"
    (cd "$FRONTEND" && "$NODE_BIN" ./node_modules/vite/bin/vite.js build)
  else
    echo "警告: 未找到 node/vite，跳过前端构建（若刚改过 Vue，页面可能仍是旧包）"
  fi
fi

# 强制重启生产（独立进程组，不碰开发 8001）
# 清掉当前 shell 可能残留的开发库变量，避免误连 ems.dev.db
unset EMS_USE_SQLITE EMS_DB EMS_DEV_MODE || true
"$ROOT/start_ems.sh" --force

echo
echo "生产已加载当前代码：${PUBLIC_URL}"
echo "开发仍请用：http://127.0.0.1:5173  → API 8001 / ems.dev.db"
