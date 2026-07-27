# EMS · PostgreSQL 迁移手册（本机过渡版）

> 决策：Postgres **先装本机**，以后整体迁走；**生产先切**，开发第二周跟；**SQLite 回滚保留 ≥ 2 周**。

## 当前进度（2026-07-23 19:55）

| 项 | 状态 |
|----|------|
| 本机 Postgres 16 | ✅ Homebrew 已启动 |
| 全量迁库 | ✅ 48 表，行数校验 **0 mismatches** |
| 生产 8000 | ✅ 已切 `DATABASE_URL` → `ems_prod` |
| 冒烟 | ✅ 关键接口通过 |
| SQLite 冷备（回滚用，保留 ≥2 周） | `backend/backups/ems_pre_pg_20260723.db` 与 `ems_pre_pg_20260723_1953.db` |
| 开发 | 仍用 `ems.dev.db` + 8001（第二周再跟） |

### 日常启动（Mac 终端）

```bash
/Users/dx/EMS/backend/start_ems.sh --force
```

启动时会打印：`数据库模式: Postgres (127.0.0.1:5432/ems_prod)`

### 回滚到 SQLite

```bash
EMS_USE_SQLITE=1 /Users/dx/EMS/backend/start_ems.sh --force
```


## 你需要在 Mac「终端」执行的安装（需输入开机密码）

系统 Homebrew 无写 `/usr/local/var/log` 权限，Cursor 里无法 `sudo`。请在**本机终端**执行：

```bash
sudo chown -R "$(whoami)" /usr/local/var/log
chmod u+w /usr/local/var/log

# 用系统 brew 装瓶子（快，勿用 ~/homebrew 源码编译）
brew install postgresql@16
echo 'export PATH="/usr/local/opt/postgresql@16/bin:$PATH"' >> ~/.zshrc
export PATH="/usr/local/opt/postgresql@16/bin:$PATH"

brew services start postgresql@16
```

然后初始化库（密码从 `.env.postgres` 里的 `EMS_PG_PASSWORD` 复制）：

```bash
cd /Users/dx/EMS/backend
source .env.postgres

# 若本机 postgres 超级用户是你的 mac 用户名：
createuser -s ems 2>/dev/null || true
psql -d postgres -v ON_ERROR_STOP=1 <<SQL
DO \$\$
BEGIN
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'ems') THEN
    CREATE ROLE ems LOGIN PASSWORD '${EMS_PG_PASSWORD}';
  ELSE
    ALTER ROLE ems WITH LOGIN PASSWORD '${EMS_PG_PASSWORD}';
  END IF;
END
\$\$;
SELECT 'ok' WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'ems_prod');
SQL
createdb -O ems ems_prod 2>/dev/null || true
psql -d ems_prod -c 'SELECT 1'
```

装好后告诉我「PG 好了」，或直接跑下面「一键迁库」。

## 一键迁库 + 切生产（PG 就绪后）

```bash
cd /Users/dx/EMS/backend
source .env.postgres
export PATH="/usr/local/opt/postgresql@16/bin:$PATH"

# 1) 再停生产，再冷备一份最新
/Users/dx/EMS/backend/start_ems.sh --force 2>/dev/null || true
# 若上面会拉起服务，请先手动停 8000：
#   kill $(lsof -t -iTCP:8000 -sTCP:LISTEN)

cp -f ems.db "backups/ems_pre_pg_$(date +%Y%m%d_%H%M).db"

# 2) 全量拷入 Postgres
.venv/bin/pip install -q 'psycopg[binary]>=3.1'
DATABASE_URL="$DATABASE_URL" .venv/bin/python scripts/copy_sqlite_to_pg.py ems.db

# 3) 行数校验（应为 0 mismatches）
DATABASE_URL="$DATABASE_URL" .venv/bin/python scripts/verify_pg_counts.py ems.db

# 4) 用 PG 启动生产
EMS_USE_POSTGRES=1 /Users/dx/EMS/backend/start_ems.sh --force
/Users/dx/EMS/backend/start_ems.sh --smoke
```

### 回滚到 SQLite（2 周内随时可用）

必须带 `EMS_USE_SQLITE=1`（仅 `unset DATABASE_URL` **不够**，因为存在 `.env.postgres` 时启动脚本仍会加载它）：

```bash
EMS_USE_SQLITE=1 /Users/dx/EMS/backend/start_ems.sh --force
```

如需回到迁库前快照：
```bash
cp -f backups/ems_pre_pg_20260723_1953.db ems.db
EMS_USE_SQLITE=1 /Users/dx/EMS/backend/start_ems.sh --force
```

## 开发（第二周）

继续 `ems.dev.db` + 8001，直到生产稳定后再建 `ems_dev` 库跟进。
