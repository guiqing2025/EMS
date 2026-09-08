import { createRouter, createWebHistory } from 'vue-router'
import { canViewDashboard, defaultHomePath } from '@/auth/access'
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
          name: 'dashboard',
          component: () => import('@/views/DashboardView.vue'),
          meta: { title: '首页看板', dashboardOnly: true },
        },
        {
          path: 'quotation/:id?',
          name: 'quotation',
          component: () => import('@/views/quotation/QuotationView.vue'),
          meta: { title: '订单报价', quoteOnly: true },
        },
        {
          path: 'orders/laser',
          name: 'orders-laser',
          component: () => import('@/views/laser/LaserRegisterView.vue'),
          meta: { title: '镭雕登记' },
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
          meta: { title: '订单中心' },
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
          path: 'engineering',
          name: 'engineering-docs',
          component: () => import('@/views/LegacyFrameView.vue'),
          meta: { title: '工程资料', classicPage: 'engineering', classicTab: 'bom' },
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
          redirect: '/engineering',
        },
        {
          path: 'engineering/tooling',
          redirect: '/warehouse/tooling',
        },
        {
          path: 'scheduling/master-plan',
          name: 'scheduling-master-plan',
          component: () => import('@/views/scheduling/MasterPlanView.vue'),
          meta: { title: '生产主计划' },
        },
        {
          path: 'scheduling',
          name: 'scheduling-smt',
          component: () => import('@/views/LegacyFrameView.vue'),
          meta: { title: 'SMT 排产', classicPage: 'scheduling', classicTab: 'smt' },
        },
        {
          path: 'scheduling/dip',
          name: 'scheduling-dip',
          component: () => import('@/views/LegacyFrameView.vue'),
          meta: { title: 'DIP 排产', classicPage: 'scheduling', classicTab: 'dip' },
        },
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
    const allowedPrefixes = ['/engineering', '/orders']
    if (name === 'dxgc' || name === 'dxgc002') {
      allowedPrefixes.push('/warehouse')
    }
    if (!allowedPrefixes.some((p) => to.path === p || to.path.startsWith(p + '/'))) {
      return { path: '/engineering' }
    }
    if (
      role === 'eng_viewer' &&
      (to.path.startsWith('/engineering/process') || to.path.startsWith('/engineering/substitution'))
    ) {
      return { path: '/engineering' }
    }
  }
  if (role === 'eng_auditor') {
    const name = String(auth.user?.username || '')
      .trim()
      .toLowerCase()
    const allowedPrefixes = ['/orders', '/warehouse', '/engineering']
    // dxsmt001：额外开放 AOI 维修改判
    if (name === 'dxsmt001') allowedPrefixes.push('/quality')
    if (!allowedPrefixes.some((p) => to.path === p || to.path.startsWith(p + '/'))) {
      return { path: '/engineering' }
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
    // 产线/包装/SMT 扫码不可进镭雕登记
    if (to.path.startsWith('/orders/laser')) {
      return { path: '/orders' }
    }
  }
  if (role === 'hr') {
    if (!to.path.startsWith('/hr')) {
      return { path: '/hr/staff' }
    }
  }
  if (role === 'laser') {
    if (to.path !== '/orders/laser' && !to.path.startsWith('/orders/laser?')) {
      return { path: '/orders/laser' }
    }
  }
  if (to.meta.dashboardOnly && !canViewDashboard(auth.user)) {
    return { path: defaultHomePath(auth.user) }
  }
  if (to.meta.quoteOnly) {
    const name = String(auth.user?.username || '').trim().toLowerCase()
    if (auth.user?.role !== 'admin' && !['wgq', 'dx001'].includes(name)) {
      return { path: defaultHomePath(auth.user) }
    }
  }
  return true
})

export default router
