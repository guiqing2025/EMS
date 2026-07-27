import { createRouter, createWebHistory } from 'vue-router'
import { canViewDashboard, defaultHomePath } from '@/auth/access'
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
          path: 'warehouse/tooling',
          name: 'warehouse-tooling',
          component: () => import('@/views/LegacyFrameView.vue'),
          meta: { title: '工装登记', classicPage: 'warehouse', classicTab: 'tooling' },
        },
        {
          path: 'warehouse/finished-goods',
          name: 'warehouse-finished-goods',
          component: () => import('@/views/warehouse/FinishedGoodsView.vue'),
          meta: { title: '成品库存' },
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
          path: 'dept',
          name: 'dept',
          component: () => import('@/views/warehouse/DeptPickView.vue'),
          meta: { title: '部门领料' },
        },
        {
          path: 'quality/:section?',
          name: 'quality',
          component: () => import('@/views/PlaceholderView.vue'),
          meta: { title: '品质管理', module: 'quality' },
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
          component: () => import('@/views/PlaceholderView.vue'),
          meta: { title: '人事管理', module: 'hr' },
        },
        {
          path: 'settings/:section?',
          name: 'settings',
          component: () => import('@/views/PlaceholderView.vue'),
          meta: { title: '系统设置', module: 'settings' },
        },
      ],
    },
  ],
})

router.beforeEach(async (to) => {
  const auth = useAuthStore()
  if (to.meta.public) return true
  if (!auth.token) return { name: 'login', query: { redirect: to.fullPath } }
  // 每次进入路由都向后端刷新角色，避免后台改权限后本地仍是旧角色
  const ok = await auth.checkStatus()
  if (!ok) return { name: 'login', query: { redirect: to.fullPath } }
  if (auth.mustChangePassword) {
    if (to.name !== 'change-password') return { name: 'change-password' }
    return true
  }
  if (to.name === 'change-password') return { path: defaultHomePath(auth.user) }
  const role = auth.user?.role
  if (role === 'engineering') {
    const allowed = ['/engineering', '/engineering/material-control', '/engineering/substitution']
    if (!allowed.includes(to.path)) {
      return { path: '/engineering' }
    }
  }
  if (role === 'eng_auditor') {
    const allowedPrefixes = ['/orders', '/warehouse', '/engineering']
    if (!allowedPrefixes.some((p) => to.path === p || to.path.startsWith(p + '/'))) {
      return { path: '/engineering' }
    }
  }
  if (role === 'pmc') {
    const allowed = ['/orders', '/warehouse', '/warehouse/tooling']
    if (!allowed.includes(to.path) && !to.path.startsWith('/warehouse')) {
      return { path: '/orders' }
    }
  }
  if (role === 'floor' || role === 'packing') {
    if (to.path !== '/orders' && !to.path.startsWith('/orders/')) {
      return { path: '/orders' }
    }
    // 产线/包装扫码不可进镭雕登记
    if (to.path.startsWith('/orders/laser')) {
      return { path: '/orders' }
    }
  }
  if (role === 'hr') {
    if (!to.path.startsWith('/hr')) {
      return { path: '/hr/staff' }
    }
  }
  if (to.meta.dashboardOnly && !canViewDashboard(auth.user?.username)) {
    return { path: defaultHomePath(auth.user) }
  }
  if (to.meta.quoteOnly) {
    const name = String(auth.user?.username || '').trim().toLowerCase()
    if (!['wgq', 'dx001'].includes(name)) {
      return { path: defaultHomePath(auth.user) }
    }
  }
  return true
})

export default router
