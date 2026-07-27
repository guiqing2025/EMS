#!/bin/zsh
# =============================================================================
# Mac：代码同步 + 本机适配
#   ./scripts/sync.sh
#   ./scripts/sync.sh --build-frontend
#   ./scripts/sync.sh --no-pull
# =============================================================================
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
BUILD_FE=0
NO_PULL=0
for arg in "$@"; do
  case "$arg" in
    --build-frontend|-b) BUILD_FE=1 ;;
    --no-pull) NO_PULL=1 ;;
    --help|-h)
      echo "用法: $0 [--build-frontend] [--no-pull]"
      exit 0
      ;;
  esac
done

echo "=== EMS sync (Mac / 开发) ==="
echo "仓库: $ROOT"

HAS_GIT=0
if git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  HAS_GIT=1
else
  echo "提示: 当前目录不是 Git 仓库，跳过 pull（仅做本机适配/依赖）。"
fi

if [[ "$HAS_GIT" == "1" ]]; then
  echo "—— git status ——"
  git status -sb || true
  if [[ -n "$(git status --porcelain 2>/dev/null || true)" ]]; then
    echo "提示: 有未提交改动；pull 可能冲突，请先处理。"
  fi

  if [[ "$NO_PULL" != "1" ]]; then
    echo "—— git pull --ff-only ——"
    if ! git pull --ff-only; then
      echo "pull 失败（非快进或有冲突）。请人工处理后再跑。"
      exit 1
    fi
  fi
fi

# 本机 env
if [[ ! -f "$ROOT/env/local.env" ]]; then
  cp "$ROOT/env/env.mac.example" "$ROOT/env/local.env"
  echo "已从 env.mac.example 生成 env/local.env —— 请确认路径后重跑。"
  exit 2
fi
echo "本机适配: env/local.env 已存在"
ROLE="$(grep -E '^EMS_ROLE=' "$ROOT/env/local.env" | head -1 | cut -d= -f2- || true)"
ROLE="${ROLE:-mac_dev}"

# 依赖指纹
REQ="$ROOT/backend/requirements.txt"
PKG="$ROOT/frontend/package.json"
STAMP_DIR="$ROOT/scripts/.sync_stamps"
mkdir -p "$STAMP_DIR"
hash_file() { shasum -a 256 "$1" 2>/dev/null | awk '{print $1}'; }

if [[ ! -d "$ROOT/backend/.venv" ]]; then
  python3 -m venv "$ROOT/backend/.venv"
fi
REQ_H="$(hash_file "$REQ")"
if [[ ! -f "$STAMP_DIR/requirements.sha" ]] || [[ "$(cat "$STAMP_DIR/requirements.sha")" != "$REQ_H" ]]; then
  echo "—— pip install（requirements 有变）——"
  "$ROOT/backend/.venv/bin/pip" install -q --upgrade pip
  "$ROOT/backend/.venv/bin/pip" install -q -r "$REQ"
  echo "$REQ_H" > "$STAMP_DIR/requirements.sha"
else
  echo "Python 依赖: 无变化"
fi

if [[ -f "$PKG" ]]; then
  PKG_H="$(hash_file "$PKG")"
  if command -v npm >/dev/null 2>&1; then
    if [[ ! -f "$STAMP_DIR/package.sha" ]] || [[ "$(cat "$STAMP_DIR/package.sha")" != "$PKG_H" ]] || [[ ! -d "$ROOT/frontend/node_modules" ]]; then
      echo "—— npm install ——"
      (cd "$ROOT/frontend" && npm install)
      echo "$PKG_H" > "$STAMP_DIR/package.sha"
    else
      echo "前端依赖: 无变化"
    fi
  else
    echo "提示: 无 npm，跳过 frontend install"
  fi
fi

if [[ "$BUILD_FE" == "1" ]]; then
  echo "—— vite build → backend/static/vue ——"
  NODE="$(command -v node || true)"
  if [[ -z "$NODE" && -x "/Applications/Cursor.app/Contents/Resources/app/resources/helpers/node" ]]; then
    NODE="/Applications/Cursor.app/Contents/Resources/app/resources/helpers/node"
  fi
  if [[ -n "$NODE" && -f "$ROOT/frontend/node_modules/vite/bin/vite.js" ]]; then
    (cd "$ROOT/frontend" && "$NODE" ./node_modules/vite/bin/vite.js build)
  else
    echo "错误: 找不到 node/vite"
    exit 1
  fi
fi

echo ""
echo "当前角色: $ROLE （Mac 开发）"
if [[ -f "$ROOT/backend/.env.postgres" ]]; then
  echo "DB 配置: backend/.env.postgres 存在（生产库凭证；开发请用 start_ems_dev）"
else
  echo "DB 配置: 无 .env.postgres（开发用 SQLite/开发库即可）"
fi
echo "下一步:"
echo "  开发: ./start_dev_env.sh   或  backend/start_ems_dev.sh"
echo "  若本机临时跑生产: backend/start_ems.sh --force"
echo "  从 Windows 灌开发库: ./scripts/import_db_dev.sh <dump文件>"
