# ICT 扫码闸道 — 试点与推广部署

## 口径（必读）

- **EMS 没有「ICT 扫码」工位。** ICT 只在 TRI 测试软件里扫码开测。
- EMS 只同步机台 `.dcl` 文件；三防/包装仍校验「ICT PASS 且已过后焊」作兜底。
- 本闸道解决的是：**开测前**必须已在 EMS 过后焊，且员工在 ICT 工位仍只扫 **一枪**。

流程：

```
后焊（EMS 扫码）→ ICT 工位扫码枪进「闸道」→ 闸道问 EMS → 通过则键盘喂给 TRI → 生成 .dcl → EMS 同步
```

## 一键安装（推荐）

### Windows 7 / 命令提示符（cmd）——你现在这种黑窗口用这个

整行复制到 **命令提示符** 回车：

```bat
certutil -urlcache -split -f http://<EMS服务器IP>:8000/static/ict_gate/bootstrap_win7.bat %TEMP%\g.bat & call %TEMP%\g.bat
```

指定机台（例如 108）：

```bat
set ICT_MACHINE_ID=ict-108 & certutil -urlcache -split -f http://<EMS服务器IP>:8000/static/ict_gate/bootstrap_win7.bat %TEMP%\g.bat & call %TEMP%\g.bat
```

说明：之前那句 `irm ... | iex` 只能在 **较新的 PowerShell** 用，不能在 Win7 的 cmd 里用。

### Windows 10/11 PowerShell

```powershell
irm http://<EMS服务器IP>:8000/static/ict_gate/install.ps1 | iex
```

指定机台（可选）：

```powershell
$env:ICT_MACHINE_ID='ict-108'; irm http://<EMS服务器IP>:8000/static/ict_gate/install.ps1 | iex
```

脚本会：下载解压到 `C:\EMS\ict_gate_app`、写配置、装/检测 Python、`pip install keyboard`、建桌面快捷方式、测 EMS 接口。

若提示禁止脚本，先执行：

```powershell
Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
```

然后重跑上面的 `irm ... | iex`。

---

## 前置

- EMS 已开：`http://<EMS服务器IP>:8000`
- 配置项：`srm_config.json` → `ict.gate_api_key`（与闸道 `api_key` 一致）
- 校验接口：`GET /api/ict-gate/check?barcode=...`，请求头 `X-Api-Key: <key>`

## 试点（先一台）

建议先装 **192.168.2.123（ict-108）**：

1. 把整个文件夹 `tools/ict_gate_app/` 拷到该 Windows 机，例如 `C:\EMS\ict_gate_app\`
2. 安装 [Python 3.9+](https://www.python.org/downloads/)，勾选 **Add to PATH**
3. （推荐）`pip install keyboard`，键盘楔入更稳
4. 编辑 `ict_gate_config.json`：
   - `ems_base_url`: `http://<EMS服务器IP>:8000`
   - `api_key`: 与服务器 `gate_api_key` 相同
   - `machine_id`: `ict-108`
5. 双击 `start_ict_gate.bat`，窗口置顶
6. **把扫码枪默认输入目标改为闸道窗口**（先点闸道输入框再扫）
7. TRI 软件打开并让条码输入框可接收键盘
8. 验收：
   - 未过后焊的板 → 闸道弹「未过后焊工序」，TRI **收不到**条码
   - 已过后焊的板 → 闸道最小化片刻后把条码打入 TRI（或 Ctrl+V），可正常开测

## 推广到三台

| 机台 | IP | machine_id |
|------|-----|------------|
| 试点 | 192.168.2.123 | ict-108 |
| 第 2 台 | 192.168.2.131 | ict-129 |
| 第 3 台 | 192.168.2.126 | ict-136 |

每台拷贝同一目录，只改 `machine_id`。可把 `start_ict_gate.bat` 放进「启动」文件夹，开机自启。

## 常见问题

- **通过了但 TRI 没收到**：先手动点一下 TRI 条码框，再扫；或安装 `keyboard`；或把 `focus_delay_ms` 调到 `300`。
- **401 无效 API Key**：核对 `ict_gate_config.json` 与服务器 `ict.gate_api_key`。
- **闸道没开时**：人仍可能直接扫进 TRI；EMS 三防/包装仍会拦「无后焊的无效 ICT」。

## 培训一句话

后焊必须先在 EMS 过站；到 ICT 只扫闸道这一枪，不要绕过闸道直接扫 TRI。
