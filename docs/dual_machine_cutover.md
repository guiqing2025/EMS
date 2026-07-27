# EMS 双机迁机切流清单（Windows 生产 + Mac 开发）

## 角色

| 机器 | 角色 | 启动 | 数据库 |
|--|--|--|--|
| **Windows** | 生产权威 | `backend\start_ems.ps1` | Postgres `ems_prod` |
| **Mac** | 开发 | `start_dev_env.sh` / `start_ems_dev.sh` | 开发库 `ems_dev` 或 `ems.dev.db` |

代码同步：Git + `scripts/sync.ps1`（Win）/ `scripts/sync.sh`（Mac）。  
库同步：仅 **Windows → Mac 单向**（`export_db.ps1` → `import_db_dev.sh`）。

---

## Windows 首次上线

1. 安装 Git，克隆本仓库到如 `C:\EMS`。
2. 管理员 PowerShell：
   ```powershell
   Set-ExecutionPolicy -Scope Process Bypass
   cd C:\EMS
   .\scripts\bootstrap_windows.ps1
   ```
3. 编辑 `env\local.env`：共享盘盘符/UNC、`EMS_PUBLIC_URL`。
4. 确认 `backend\.env.postgres`。
5. 从旧 Mac 生产导出并恢复（切流当天）：
   - Mac：`pg_dump -Fc ... -f ems_prod_cutover.dump`
   - 拷到 Windows 后用 `pg_restore` 进 `ems_prod`（或先空库 bootstrap 再恢复）。
6. 启动：`cd backend; .\start_ems.ps1 -Force`
7. 浏览器打开 `http://本机IP:8000`，冒烟：登录、看板、工程、订单、包装。
8. 复测：ICT/AOI/恩玖 SMB、SRM、共享盘路径。

---

## 切流（内网入口）

1. 确认 Windows 服务稳定、冒烟通过。
2. 将原 `http://192.168.2.168:8000` 指向 Windows（改 DNS / 换机同 IP / 通知书签）。
3. Mac 上停止生产 `8000`（或仅保留开发 `8001`）。
4. 更新本仓库 Cursor 规则：生产 = Windows（见 `.cursor/rules/dev-prod-isolation.mdc`）。

---

## Mac 日常开发

```bash
./scripts/sync.sh                 # 拉代码 + 适配
./start_dev_env.sh                # 或 backend/start_ems_dev.sh
# 需要新数据时：
# 1) Windows: .\scripts\export_db.ps1
# 2) 拷 dump 到 Mac
# 3) EMS_ALLOW_DEV_DB_IMPORT=1 ./scripts/import_db_dev.sh ./ems_prod_xxx.dump
```

---

## 禁止事项

- 不要用网盘/U 盘整目录同步 `.venv`、`node_modules`、数据库文件。
- 不要把 `import_db_dev` 目标设为 `ems_prod`。
- 不要在 Mac 开发机未授权时对 Windows 生产库直连写入。
- 两台不要同时当「权威生产」双写。
