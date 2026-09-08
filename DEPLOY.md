# EMS 异地部署说明

本仓库是可交付的 EMS 源码包。换厂部署后，**主要改设备接口与数据接口配置**，无需重写业务代码。

## 1. 新电脑拿到代码后

1. 安装 Git，用 Cursor 打开本仓库，或：
   ```bash
   git clone https://github.com/guiqing2025/EMS.git
   ```
2. 在 Windows 上以管理员 PowerShell 运行：
   ```powershell
   cd EMS
   .\scripts\bootstrap_windows.ps1
   ```
   会安装 Python / Node / PostgreSQL，并生成环境文件、安装依赖、构建前端。
3. 复制配置模板并填写本厂信息：
   ```powershell
   Copy-Item backend\srm_config.example.json backend\srm_config.json
   Copy-Item env\env.windows.example env\local.env
   Copy-Item backend\.env.postgres.example backend\.env.postgres
   Copy-Item tools\ict_gate_app\ict_gate_config.example.json tools\ict_gate_app\ict_gate_config.json
   ```

## 2. 换厂必改（设备 / 数据接口）

| 文件 | 改什么 |
|------|--------|
| `backend/srm_config.json` | SRM/MES/金蝶账号与地址、AOI/ICT/ATS 主机与共享盘、登录口令、`public_base_url` |
| `env/local.env` | 共享盘 UNC/盘符、人事花名册、钢网/治具表、替代料与工艺明细路径 |
| `backend/.env.postgres` | 本机 Postgres 密码 |
| `tools/ict_gate_app/ict_gate_config.json` | 闸道机访问 EMS 的地址与 `api_key`（需与 `srm_config.json` 里 `ict.gate_api_key` 一致） |

改完后按文档启动：

- 生产（Postgres，默认 `:8000`）：`backend\start_ems.ps1`
- 本机快捷（SQLite，`:8888`）：`start_local_windows.ps1`

更细的迁机步骤见 `docs/dual_machine_cutover.md`、`docs/postgres迁移手册.md`。

## 3. 不要提交回仓库的内容

真实密码、`srm_config.json`、`env/local.env`、数据库文件、证书私钥、业务 Excel 等已在 `.gitignore` 中排除。本机改完接口配置后，只需把**源码与模板**同步到 Git；各厂凭据留在各厂现场。
