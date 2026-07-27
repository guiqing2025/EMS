# EMS 新版前端（Vue3 + Element Plus）

智邦风格 ERP 界面壳子，构建产物输出到 `backend/static/vue/`。

## 环境要求

- Node.js 18+
- npm 9+

## 开发

```bash
cd frontend
npm install
npm run dev
```

浏览器打开 http://127.0.0.1:5173（API 代理到 8000 端口）。

## 构建上线

```bash
cd frontend
npm install
npm run build
```

然后重启后端，访问 http://127.0.0.1:8000 即为新版界面。

经典版完整界面仍保留在：http://127.0.0.1:8000/classic/

## 目录说明

- `src/layouts/ErpLayout.vue` — 左侧树菜单 + 顶栏面包屑
- `src/menu/index.ts` — 菜单结构与权限
- `src/views/orders/OrdersListView.vue` — 订单列表（已迁移）
- `src/views/warehouse/WarehouseView.vue` — 仓库管理（已迁移）
- `src/views/warehouse/DeptPickView.vue` — 部门领料（已迁移）
- `src/views/LegacyFrameView.vue` — 内嵌经典版业务页（仓库/工程等过渡期）
- `src/views/PlaceholderView.vue` — 品质/人事等待开发模块
