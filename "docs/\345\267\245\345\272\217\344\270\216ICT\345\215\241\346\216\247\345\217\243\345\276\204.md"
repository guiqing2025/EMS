# 工序与 ICT 卡控口径

## 扫码工位（EMS 订单列表）

| 工位 | EMS 是否扫码 | 卡控 |
|------|--------------|------|
| AOI | 否（机台同步） | 插件要求 AOI PASS |
| 插件 | 是 | AOI PASS |
| 后焊 | 是 | 已过插件 |
| **ICT** | **否** | 在 **TRI 测试软件**扫码开测；开测前由 **ICT 闸道**查 EMS 是否已过后焊；结果文件 `.dcl` 由 EMS 同步 |
| 三防 | 是 | 已过后焊 + ICT 有效 PASS |
| 包装 | 是 | AOI/ICT 良品 + 插件/后焊/三防均已过站；不良锁死 |

**不要**在 EMS 再做「ICT 扫码」——会变成扫两遍。

## ICT 与后焊联动

- 接口：`/api/ict-gate/check`（API Key）
- 工位程序：[`tools/ict_gate_app/`](../tools/ict_gate_app/README.md)
- 下游兜底：三防/包装仍要求「有效 ICT = PASS 且已有后焊」

## 女声提示（EMS 工序/包装扫码）

成功播 PASS，失败播 FALL：`/static/sounds/pass.wav`、`fall.wav`。
