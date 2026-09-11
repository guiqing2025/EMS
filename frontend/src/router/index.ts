import { createRouter, createWebHistory } from 'vue-router'
import { defaultHomePath } from '@/auth/access'
import { canAccessPath } from '@/menu'
import { useAuthStore } from '@/stores/auth'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    {
      path: '/login',
      name: 'login',
      component: () => import('@/views/LoginView.vue'),
      meta: { public: true },
    },
    {
      path: '/change-password',
      name: 'change-password',
      component: () => import('@/views/ChangePasswordView.vue'),
    },
    {
      path: '/floor',
      component: () => import('@/views/floor/FloorLayout.vue'),
      meta: { floor: true, pda: true },
      children: [
        {
          path: '',
          name: 'floor-tasks',
          component: () => import('@/views/floor/FloorTasksView.vue'),
          meta: { floor: true, title: '我的任务' },
        },
        {
          path: 'scan',
          name: 'floor-scan',
          component: () => import('@/views/floor/FloorScanView.vue'),
          meta: { floor: true, title: '工序报工' },
        },
        {
          path: 'board',
          name: 'floor-board',
          component: () => import('@/views/floor/FloorBoardView.vue'),
          meta: { floor: true, title: '进度看板' },
        },
        {
          path: 'me',
          name: 'floor-me',
          component: () => import('@/views/floor/FloorMeView.vue'),
          meta: { floor: true, title: '我的工位' },
        },
      ],
    },
    {
      path: '/pda',
      component: () => import('@/views/pda/PdaLayout.vue'),
      meta: { pda: true },
      children: [
        {
          path: '',
          name: 'pda-home',
          component: () => import('@/views/pda/PdaHomeView.vue'),
          meta: { pda: true, title: 'PDA 选工位' },
        },
        {
          path: 'box-query',
          name: 'pda-box-query',
          component: () => import('@/views/pda/PdaBoxQueryView.vue'),
          meta: { pda: true, title: 'PDA 查箱号' },
        },
        {
          path: 'resolve',
          name: 'pda-resolve',
          component: () => import('@/views/pda/PdaResolveView.vue'),
          meta: { pda: true, title: 'PDA 盲扫认单' },
        },
        {
          path: 'pick',
          name: 'pda-pick',
          component: () => import('@/views/pda/PdaOrderPickView.vue'),
          meta: { pda: true, title: 'PDA 选订单' },
        },
        {
          path: 'scan',
          name: 'pda-scan',
          component: () => import('@/views/pda/PdaScanView.vue'),
          meta: { pda: true, title: 'PDA 扫码' },
        },
        {
          path: 'dip-fai',
          name: 'pda-dip-fai',
          component: () => import('@/views/pda/PdaDipFaiPickView.vue'),
          meta: { pda: true, title: 'DIP 首件选单' },
        },
        {
          path: 'dip-fai/:id',
          name: 'pda-dip-fai-session',
          component: () => import('@/views/pda/PdaDipFaiSessionView.vue'),
          meta: { pda: true, title: 'DIP 首件对料' },
        },
        {
          path: 'smt-ipqc',
          name: 'pda-smt-ipqc',
          component: () => import('@/views/pda/PdaSmtIpqcPickView.vue'),
          meta: { pda: true, title: 'SMT 巡检选单' },
        },
        {
          path: 'smt-ipqc/:id',
          name: 'pda-smt-ipqc-session',
          component: () => import('@/views/pda/PdaSmtIpqcSessionView.vue'),
          meta: { pda: true, title: 'SMT 巡检查料' },
        },
      ],
    },
    {
      path: '/',
      component: () => import('@/layouts/ErpLayout.vue'),
      children: [
        {
          path: '',
          redirect: () => {
            const auth = useAuthStore()
            return defaultHomePath(auth.user)
          },
        },
        {
          path: 'dashboard',
          redirect: '/sales/flow',
        },
        {
          path: 'quotation/:id?',
          redirect: '/sales/flow',
        },
        {
          path: 'orders/laser',
          redirect: '/orders',
        },
        {
          path: 'orders/hub/:lineKey',
          name: 'orders-hub',
          component: () => import('@/views/orders/OrderHubView.vue'),
          meta: { title: '订单工作台' },
        },
        {
          path: 'orders/packing',
          redirect: '/orders',
        },
        {
          path: 'orders/:section?',
          name: 'orders',
          component: () => import('@/views/orders/OrdersListView.vue'),
          meta: { title: '销售订单跟踪' },
        },
        {
          path: 'production-daily',
          name: 'production-daily',
          component: () => import('@/views/production/ProductionDailyView.vue'),
          meta: { title: '生产日报' },
        },
        {
          path: 'warehouse/tooling',
          name: 'warehouse-tooling',
          component: () => import('@/views/LegacyFrameView.vue'),
          meta: { title: '工装登记', classicPage: 'warehouse', classicTab: 'tooling' },
        },
        {
          path: 'warehouse/finished-goods',
          name: 'warehouse-finished-goods',
          component: () => import('@/views/warehouse/FinishedGoodsView.vue'),
          meta: { title: '成品发货' },
        },
        {
          path: 'warehouse/pack-boxes',
          name: 'warehouse-pack-boxes',
          component: () => import('@/views/warehouse/ShipmentRecordsView.vue'),
          meta: { title: '批次记录' },
        },
        {
          path: 'warehouse/:section?',
          name: 'warehouse',
          component: () => import('@/views/warehouse/WarehouseView.vue'),
          meta: { title: '仓库管理' },
          beforeEnter: (to) => {
            if (to.params.section) return { path: '/warehouse' }
            return true
          },
        },
        {
          path: 'planning',
          name: 'planning-home',
          component: () => import('@/views/planning/PlanningHomeView.vue'),
          meta: { title: '计划' },
        },
        {
          path: 'planning/mc-kitting',
          name: 'planning-mc-kitting',
          component: () => import('@/views/planning/McKittingView.vue'),
          meta: { title: 'MC齐套运算' },
        },
        {
          path: 'planning/pmc-schedule',
          name: 'planning-pmc-schedule',
          component: () => import('@/views/planning/PmcScheduleView.vue'),
          meta: { title: 'PMC排产' },
        },
        {
          path: 'planning/bom',
          redirect: '/planning',
        },
        {
          path: 'planning/mrp',
          redirect: '/planning',
        },
        {
          path: 'planning/stock-warning',
          redirect: '/planning',
        },
        {
          path: 'planning/customer-forecast',
          redirect: '/planning',
        },
        {
          path: 'planning/purchase-forecast',
          redirect: '/planning',
        },
        {
          path: 'planning/purchase-plan',
          redirect: '/planning',
        },
        {
          path: 'planning/production-plan',
          redirect: '/planning',
        },
        {
          path: 'planning/outsource-plan',
          redirect: '/planning',
        },
        {
          path: 'planning/pmc-board',
          redirect: '/planning',
        },
        {
          path: 'engineering',
          name: 'engineering-docs',
          redirect: '/engineering/material-control',
        },
        {
          path: 'engineering/material-control',
          name: 'engineering-material-control',
          component: () => import('@/views/engineering/MaterialControlView.vue'),
          meta: { title: '物料管制' },
        },
        {
          path: 'engineering/substitution',
          name: 'engineering-substitution',
          component: () => import('@/views/LegacyFrameView.vue'),
          meta: { title: '替代料', classicPage: 'engineering', classicTab: 'substitution' },
        },
        {
          path: 'engineering/process',
          name: 'engineering-process',
          component: () => import('@/views/LegacyFrameView.vue'),
          meta: { title: '工序对照', classicPage: 'engineering', classicTab: 'process' },
        },
        {
          path: 'engineering/files',
          redirect: '/engineering/material-control',
        },
        {
          path: 'engineering/tooling',
          redirect: '/warehouse/tooling',
        },
        {
          path: 'scheduling/master-plan',
          redirect: '/planning',
        },
        {
          path: 'scheduling',
          redirect: '/planning',
        },
        {
          path: 'scheduling/dip',
          redirect: '/planning',
        },
        {
          path: 'master/customers',
          name: 'master-customers',
          component: () => import('@/views/master/CustomersView.vue'),
          meta: { title: '客户资料' },
        },
        {
          path: 'master/suppliers',
          name: 'master-suppliers',
          component: () => import('@/views/master/PartnersView.vue'),
          meta: { title: '供应商', partnerKind: 'supplier' },
        },
        {
          path: 'master/prices',
          redirect: '/master/customers',
        },
        {
          path: 'master/stock-products',
          redirect: '/master/customers',
        },
        {
          path: 'master/warehouses',
          redirect: '/master/customers',
        },
        {
          path: 'master/doc-numbers',
          redirect: '/master/customers',
        },
        // 售前已下线，旧路径跳订单流程
        {
          path: 'presales/inquiry',
          redirect: '/sales/flow',
        },
        {
          path: 'presales/design',
          redirect: '/sales/flow',
        },
        {
          path: 'presales/sample-mail',
          redirect: '/sales/flow',
        },
        {
          path: 'presales/sample-loan',
          redirect: '/sales/flow',
        },
        {
          path: 'sales/flow',
          name: 'sales-flow',
          component: () => import('@/views/sales/SalesFlowWorkbench.vue'),
          meta: { title: '订单流程' },
        },
        {
          path: 'sales/orders',
          name: 'sales-orders',
          component: () => import('@/views/sales/SalesOrderView.vue'),
          meta: { title: '销售订单' },
        },
        {
          path: 'sales/order-code',
          name: 'sales-order-code',
          component: () => import('@/views/sales/OrderCodeView.vue'),
          meta: { title: '订单编码' },
        },
        {
          path: 'sales/sample-orders',
          redirect: '/sales/flow',
        },
        {
          path: 'sales/stock-orders',
          redirect: '/sales/flow',
        },
        {
          path: 'purchase/orders',
          name: 'purchase-orders',
          component: () => import('@/views/purchase/PurchaseOrderView.vue'),
          meta: { title: '采购单' },
        },
        {
          path: 'purchase/inspect',
          name: 'purchase-inspect',
          component: () => import('@/views/purchase/PurchaseInspectView.vue'),
          meta: { title: '采购入库送检' },
        },
        {
          path: 'purchase/receipt',
          name: 'purchase-receipt',
          component: () => import('@/views/purchase/PurchaseReceiptReturnView.vue'),
          meta: { title: '采购入库 / 验收', purchaseKind: 'receipt' },
        },
        {
          path: 'purchase/return',
          name: 'purchase-return',
          component: () => import('@/views/purchase/PurchaseReceiptReturnView.vue'),
          meta: { title: '采购退货', purchaseKind: 'return' },
        },
        {
          path: 'production/orders',
          name: 'production-orders',
          component: () => import('@/views/production/ProductionOrderView.vue'),
          meta: { title: '生产单' },
        },
        {
          path: 'production/material',
          name: 'production-material',
          component: () => import('@/views/production/ProductionMaterialView.vue'),
          meta: { title: '领料 / 补料 / 退料' },
        },
        {
          path: 'production/qa',
          name: 'production-qa',
          component: () => import('@/views/production/ProductionQaView.vue'),
          meta: { title: '生产检查 / QA' },
        },
        {
          path: 'production/fg-receipt',
          name: 'production-fg-receipt',
          component: () => import('@/views/production/FgReceiptView.vue'),
          meta: { title: '成品入库单' },
        },
        {
          path: 'outsource/orders',
          name: 'outsource-orders',
          component: () => import('@/views/outsource/OutsourceOrderView.vue'),
          meta: { title: '委外单' },
        },
        {
          path: 'outsource/inspect',
          name: 'outsource-inspect',
          component: () => import('@/views/outsource/OutsourceInspectView.vue'),
          meta: { title: '委外入库送检' },
        },
        {
          path: 'outsource/receipt',
          name: 'outsource-receipt',
          component: () => import('@/views/outsource/OutsourceReceiptReturnView.vue'),
          meta: { title: '委托入库', outsourceKind: 'receipt' },
        },
        {
          path: 'outsource/return',
          name: 'outsource-return',
          component: () => import('@/views/outsource/OutsourceReceiptReturnView.vue'),
          meta: { title: '委外退货', outsourceKind: 'return' },
        },
        {
          path: 'shipping/sales-issue',
          name: 'shipping-sales-issue',
          component: () => import('@/views/shipping/SalesIssueView.vue'),
          meta: { title: '销售出库单' },
        },
        {
          path: 'shipping/delivery',
          name: 'shipping-delivery',
          component: () => import('@/views/shipping/DeliveryNoteView.vue'),
          meta: { title: '发货单' },
        },
        {
          path: 'aftersales/complaint',
          name: 'aftersales-complaint',
          component: () => import('@/views/aftersales/ComplaintView.vue'),
          meta: { title: '投诉单' },
        },
        {
          path: 'aftersales/return',
          name: 'aftersales-return',
          component: () => import('@/views/aftersales/SalesReturnView.vue'),
          meta: { title: '销售退货 / 补发补货' },
        },
        {
          path: 'aftersales/sample',
          name: 'aftersales-sample',
          component: () => import('@/views/aftersales/SampleLoanAfterView.vue'),
          meta: { title: '借样还入 / 转销售' },
        },
        {
          path: 'warehouse/stocktake',
          name: 'warehouse-stocktake',
          component: () => import('@/views/warehouse/StocktakeTransferView.vue'),
          meta: { title: '库存盘点' },
        },
        {
          path: 'warehouse/transfer',
          name: 'warehouse-transfer',
          component: () => import('@/views/warehouse/TransferView.vue'),
          meta: { title: '库存调拨 / 出库', transferKind: 'transfer' },
        },
        {
          path: 'finance/ap',
          name: 'finance-ap',
          component: () => import('@/views/finance/ApView.vue'),
          meta: { title: '应付统计 / 付款申请' },
        },
        {
          path: 'finance/ar',
          name: 'finance-ar',
          component: () => import('@/views/finance/ArView.vue'),
          meta: { title: '应收统计 / 收款' },
        },
        {
          path: 'finance/cashier',
          name: 'finance-cashier',
          component: () => import('@/views/finance/CashierView.vue'),
          meta: { title: '出纳' },
        },
        {
          path: 'finance/gl',
          name: 'finance-gl',
          component: () => import('@/views/finance/GlView.vue'),
          meta: { title: '总账 / 月末' },
        },
        // 流程图待建节点（阶段 11+ 或其它）
        ...[
          ['sales/orders', '销售订单', '阶段2'],
          ['purchase/orders', '采购单', '阶段4'],
          ['purchase/inspect', '采购入库送检', '阶段4'],
          ['purchase/receipt', '采购入库 / 验收', '阶段4'],
          ['purchase/return', '采购退货', '阶段4'],
          ['production/orders', '生产单', '阶段5'],
          ['production/material', '领料 / 补料 / 退料', '阶段5'],
          ['production/qa', '生产检查 / QA', '阶段5'],
          ['production/fg-receipt', '成品入库单', '阶段5'],
          ['outsource/orders', '委外单', '阶段6'],
          ['outsource/inspect', '委外入库送检', '阶段6'],
          ['outsource/receipt', '委托入库', '阶段6'],
          ['outsource/return', '委外退货', '阶段6'],
          ['warehouse/stocktake', '库存盘点', '阶段8'],
          ['warehouse/transfer', '库存调拨 / 出库', '阶段8'],
          ['shipping/sales-issue', '销售出库单', '阶段7'],
          ['shipping/delivery', '发货单', '阶段7'],
          ['aftersales/complaint', '投诉单', '阶段8'],
          ['aftersales/return', '销售退货 / 补发补货', '阶段8'],
          ['aftersales/sample', '借样还入 / 转销售', '阶段8'],
          ['quality/gates', 'IQC / IPQC / QA', '阶段4-5'],
          ['finance/ap', '应付统计 / 付款申请', '阶段9'],
          ['finance/ar', '应收统计 / 收款', '阶段9'],
          ['finance/cashier', '出纳', '阶段9'],
          ['finance/gl', '总账 / 月末', '阶段10'],
        ]
          .filter(
            ([path]) =>
              ![
                'sales/orders',
                'sales/flow',
                'purchase/orders',
                'purchase/inspect',
                'purchase/receipt',
                'purchase/return',
                'production/orders',
                'production/material',
                'production/qa',
                'production/fg-receipt',
                'outsource/orders',
                'outsource/inspect',
                'outsource/receipt',
                'outsource/return',
                'shipping/sales-issue',
                'shipping/delivery',
                'aftersales/complaint',
                'aftersales/return',
                'aftersales/sample',
                'warehouse/stocktake',
                'warehouse/transfer',
                'finance/ap',
                'finance/ar',
                'finance/cashier',
                'finance/gl',
              ].includes(path as string),
          )
          .map(([path, title, phase]) => ({
          path: path as string,
          name: `soon-${(path as string).replace(/\//g, '-')}`,
          component: () => import('@/views/ComingSoonView.vue'),
          meta: { title, phase, comingSoon: true },
        })),
        {
          path: 'quality/aoi-repair',
          name: 'quality-aoi-repair',
          component: () => import('@/views/quality/AoiRepairOverrideView.vue'),
          meta: { title: 'AOI维修改判', module: 'quality' },
        },
        {
          path: 'quality/process-defects',
          name: 'quality-process-defects',
          component: () => import('@/views/quality/ProcessDefectDashboardView.vue'),
          meta: { title: '制程不良看板', module: 'quality' },
        },
        {
          path: 'quality/complaints',
          name: 'quality-complaints',
          component: () => import('@/views/quality/ComplaintDashboardView.vue'),
          meta: { title: '客诉看板', module: 'quality' },
        },
        {
          path: 'quality/barcode-trace',
          name: 'quality-barcode-trace',
          component: () => import('@/views/quality/BarcodeTraceView.vue'),
          meta: { title: '条码追溯', module: 'quality' },
        },
        {
          path: 'quality/dip-first-article',
          name: 'quality-dip-first-article',
          component: () => import('@/views/quality/DipFirstArticleView.vue'),
          meta: { title: 'DIP首件记录', module: 'quality' },
        },
        {
          path: 'quality/smt-ipqc',
          name: 'quality-smt-ipqc',
          component: () => import('@/views/quality/SmtIpqcView.vue'),
          meta: { title: 'SMT巡检记录', module: 'quality' },
        },
        {
          path: 'quality/:section?',
          name: 'quality',
          redirect: '/quality/barcode-trace',
        },
        {
          path: 'hr/staff',
          name: 'hr-staff',
          component: () => import('@/views/hr/HrStaffView.vue'),
          meta: { title: '员工档案' },
        },
        {
          path: 'hr/attendance',
          name: 'hr-attendance',
          component: () => import('@/views/hr/HrAttendanceView.vue'),
          meta: { title: '考勤管理' },
        },
        {
          path: 'hr/:section?',
          name: 'hr',
          redirect: '/hr/staff',
        },
        {
          path: 'settings/sync',
          name: 'settings-sync',
          component: () => import('@/views/settings/SyncStatusView.vue'),
          meta: { title: '同步状态', module: 'settings' },
        },
        {
          path: 'settings/account-permissions',
          name: 'settings-account-perms',
          component: () => import('@/views/settings/AccountPermsView.vue'),
          meta: { title: '账号权限', module: 'settings' },
        },
        {
          path: 'settings/:section?',
          name: 'settings',
          redirect: '/settings/sync',
        },
      ],
    },
  ],
})

router.beforeEach(async (to) => {
  const auth = useAuthStore()
  if (to.meta.public) return true
  if (!auth.token) return { name: 'login', query: { redirect: to.fullPath } }
  // 短缓存鉴权：菜单连点不每次等 /auth/status；产线扫码在页内弹窗，不经过本守卫
  const ok = await auth.checkStatus()
  if (!ok) return { name: 'login', query: { redirect: to.fullPath } }
  if (auth.mustChangePassword) {
    if (to.name !== 'change-password') return { name: 'change-password' }
    return true
  }
  if (to.name === 'change-password') return { path: defaultHomePath(auth.user) }
  // 子页勾选权限：有 module_pages 时以此为准（立即生效），跳过旧角色硬拦
  if (Array.isArray(auth.user?.module_pages)) {
    if (!canAccessPath(to.path, auth.user)) {
      return { path: defaultHomePath(auth.user) }
    }
    return true
  }
  const role = auth.user?.role
  if (role === 'engineering' || role === 'eng_importer' || role === 'eng_viewer') {
    const name = String(auth.user?.username || '')
      .trim()
      .toLowerCase()
    const allowedPrefixes = ['/engineering', '/orders', '/sales']
    if (name === 'dxgc' || name === 'dxgc002') {
      allowedPrefixes.push('/warehouse')
    }
    if (!allowedPrefixes.some((p) => to.path === p || to.path.startsWith(p + '/'))) {
      return { path: '/engineering/material-control' }
    }
    if (
      role === 'eng_viewer' &&
      (to.path.startsWith('/engineering/process') || to.path.startsWith('/engineering/substitution'))
    ) {
      return { path: '/engineering/material-control' }
    }
  }
  if (role === 'eng_auditor') {
    const name = String(auth.user?.username || '')
      .trim()
      .toLowerCase()
    const allowedPrefixes = ['/orders', '/warehouse', '/engineering', '/sales']
    // dxsmt001：额外开放 AOI 维修改判
    if (name === 'dxsmt001') allowedPrefixes.push('/quality')
    if (!allowedPrefixes.some((p) => to.path === p || to.path.startsWith(p + '/'))) {
      return { path: '/engineering/material-control' }
    }
    if (name === 'dxsmt001' && to.path.startsWith('/quality') && to.path !== '/quality/aoi-repair') {
      return { path: '/quality/aoi-repair' }
    }
  }
  // PMC：全模块查看，不再限制路由
  if (role === 'floor' || role === 'packing' || role === 'smt_scan') {
    // 经典 PDA 仍放行；订单列表/工作台是主入口
    if (to.path === '/pda' || to.path.startsWith('/pda/')) {
      return true
    }
    const name = String(auth.user?.username || '')
      .trim()
      .toLowerCase()
    // dxbz001 / dxbz002：仅入库，走批次记录页
    if (
      role === 'packing' &&
      (
        to.path === '/warehouse/pack-boxes' ||
        to.path.startsWith('/warehouse/pack-boxes?')
      )
    ) {
      return true
    }
    if (
      (name === 'dxbz001' || name === 'dxbz002') &&
      (
        to.path === '/warehouse/pack-boxes' ||
        to.path.startsWith('/warehouse/pack-boxes?')
      )
    ) {
      return true
    }
    if (to.path !== '/orders' && !to.path.startsWith('/orders/')) {
      return { path: '/orders' }
    }
  }
  if (role === 'hr') {
    if (!to.path.startsWith('/hr')) {
      return { path: '/hr/staff' }
    }
  }
  if (role === 'laser') {
    if (to.path !== '/orders' && !to.path.startsWith('/orders/')) {
      return { path: '/orders' }
    }
  }
  return true
})

export default router
