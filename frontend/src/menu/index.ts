import type { Component } from 'vue'
import type { AuthUser } from '@/types/auth'

export interface MenuItem {
  key: string
  title: string
  icon?: Component
  path?: string
  classicPage?: string
  roles?: string[]
  /** 若设置，仅这些用户名可见（不区分大小写）；仍可叠加 roles */
  usernames?: string[]
  children?: MenuItem[]
  /** 流程图节点尚未开发：菜单可见，进入占位页 */
  comingSoon?: boolean
  phase?: string
}

/** 流程图泳道常用角色组合 */
const R_ALL_BIZ = ['admin', 'sales', 'pmc', 'planner']
const R_PLAN = ['admin', 'pmc', 'planner']
const R_BUY = ['admin', 'purchasing', 'pmc', 'planner', 'warehouse']
const R_PROD = ['admin', 'production', 'planner', 'pmc', 'floor', 'packing', 'laser', 'smt_scan']
const R_QC = ['admin', 'quality', 'pmc', 'planner', 'eng_auditor']
const R_WH = ['admin', 'warehouse', 'pmc', 'planner', 'purchasing', 'packing', 'eng_auditor']
const R_FIN = ['admin', 'finance', 'pmc']
const R_ENG = ['admin', 'planner', 'engineering', 'eng_auditor', 'eng_importer', 'eng_viewer', 'pmc']
const R_SYS = ['admin', 'pmc']

export function canAccessMenu(item: MenuItem, user: AuthUser | null): boolean {
  if (!user) return false
  const name = String(user.username || '')
    .trim()
    .toLowerCase()
  const hasUsers = !!(item.usernames && item.usernames.length)
  const inUsers = hasUsers && item.usernames!.map((u) => u.toLowerCase()).includes(name)
  const hasRoles = !!(item.roles && item.roles.length)

  const pages = user.module_pages
  if (Array.isArray(pages)) {
    if (item.children?.length) {
      return item.children.some((c) => canAccessMenu(c, user))
    }
    if (!pages.includes(item.key)) return false
    if (hasUsers && !hasRoles && !inUsers) return false
    return true
  }
  if (user.role === 'pmc') {
    if (item.key === 'settings-account-perms') {
      return false
    }
    return true
  }
  if (inUsers) return true
  if (hasRoles) {
    if (user.role === 'admin') return true
    return item.roles!.includes(user.role)
  }
  if (hasUsers) return false
  return true
}

export function filterMenu(items: MenuItem[], user: AuthUser | null): MenuItem[] {
  const usePages = Array.isArray(user?.module_pages)
  return items
    .map((item) => {
      if (item.children?.length) {
        if (
          !usePages &&
          (item.roles?.length || item.usernames?.length) &&
          !canAccessMenu({ ...item, children: undefined }, user)
        ) {
          return null
        }
        const children = filterMenu(item.children, user)
        if (!children.length) return null
        return { ...item, children }
      }
      return canAccessMenu(item, user) ? item : null
    })
    .filter(Boolean) as MenuItem[]
}

/**
 * 菜单按「销售订单至销售出货流程图」重排。
 * comingSoon=true 的节点进入占位页；已有制造能力挂到对应泳道。
 */
export const menuTree: MenuItem[] = [
  {
    key: 'master',
    title: '主数据',
    roles: [...R_ALL_BIZ, 'purchasing', 'warehouse', 'finance', 'production', 'quality'],
    children: [
      { key: 'md-customers', title: '客户资料', path: '/master/customers', roles: R_ALL_BIZ },
      { key: 'md-suppliers', title: '供应商', path: '/master/suppliers', roles: [...R_BUY, 'sales'] },
    ],
  },
  {
    key: 'sales',
    title: '销售',
    roles: R_ALL_BIZ,
    children: [
      { key: 'sales-flow', title: '订单流程', path: '/sales/flow', roles: R_ALL_BIZ },
      { key: 'sales-order', title: '销售订单', path: '/sales/orders', roles: R_ALL_BIZ },
      { key: 'sales-order-code', title: '订单编码', path: '/sales/order-code', roles: R_ALL_BIZ },
      {
        key: 'orders-list',
        title: '销售订单跟踪',
        path: '/orders',
        classicPage: 'orders',
        roles: [
          'admin',
          'planner',
          'warehouse',
          'pmc',
          'eng_auditor',
          'eng_importer',
          'eng_viewer',
          'floor',
          'packing',
          'smt_scan',
          'sales',
          'laser',
        ],
      },
    ],
  },
  {
    key: 'front-eng',
    title: '前端工程',
    roles: R_ENG,
    children: [
      {
        key: 'eng-control',
        title: '物料管制',
        path: '/engineering/material-control',
        roles: ['admin', 'planner', 'engineering', 'warehouse', 'eng_auditor', 'eng_importer', 'eng_viewer', 'pmc'],
      },
      {
        key: 'eng-sub',
        title: '替代料',
        path: '/engineering/substitution',
        classicPage: 'engineering',
        roles: ['admin', 'planner', 'engineering', 'eng_importer', 'pmc'],
      },
      {
        key: 'eng-process',
        title: '工序对照',
        path: '/engineering/process',
        classicPage: 'engineering',
        roles: ['admin', 'planner', 'pmc', 'eng_importer', 'production'],
      },
    ],
  },
  {
    key: 'planning',
    title: '计划',
    roles: R_PLAN,
    children: [
      { key: 'plan-home', title: '计划首页', path: '/planning', roles: R_PLAN },
      { key: 'plan-mc-kitting', title: 'MC齐套运算', path: '/planning/mc-kitting', roles: R_PLAN },
      { key: 'plan-pmc-schedule', title: 'PMC排产', path: '/planning/pmc-schedule', roles: R_PLAN },
    ],
  },
  {
    key: 'purchase',
    title: '采购',
    roles: R_BUY,
    children: [
      { key: 'pur-order', title: '采购单', path: '/purchase/orders', roles: R_BUY },
      { key: 'pur-inspect', title: '采购入库送检', path: '/purchase/inspect', roles: [...R_BUY, 'quality'] },
      { key: 'pur-receipt', title: '采购入库 / 验收', path: '/purchase/receipt', roles: R_BUY },
      { key: 'pur-return', title: '采购退货', path: '/purchase/return', roles: R_BUY },
    ],
  },
  {
    key: 'production',
    title: '生产',
    roles: R_PROD,
    children: [
      { key: 'prd-order', title: '生产单', path: '/production/orders', roles: R_PROD },
      { key: 'prd-issue', title: '领料 / 补料 / 退料', path: '/production/material', roles: [...R_PROD, 'warehouse'] },
      { key: 'prd-qa', title: '生产检查 / QA', path: '/production/qa', roles: [...R_PROD, 'quality'] },
      { key: 'prd-fg', title: '成品入库单', path: '/production/fg-receipt', roles: [...R_PROD, 'warehouse'] },
      {
        key: 'production-daily',
        title: '生产日报(过渡)',
        path: '/production-daily',
        roles: ['admin', 'planner', 'pmc', 'warehouse', 'production'],
        usernames: ['dxsmt001'],
      },
    ],
  },
  {
    key: 'outsource',
    title: '委外',
    roles: [...R_BUY, 'production'],
    children: [
      { key: 'os-order', title: '委外单', path: '/outsource/orders', roles: [...R_BUY, 'production'] },
      { key: 'os-inspect', title: '委外入库送检', path: '/outsource/inspect', roles: [...R_BUY, 'quality'] },
      { key: 'os-receipt', title: '委托入库', path: '/outsource/receipt', roles: R_BUY },
      { key: 'os-return', title: '委外退货', path: '/outsource/return', roles: R_BUY },
    ],
  },
  {
    key: 'warehouse',
    title: '仓储',
    roles: R_WH,
    usernames: ['dxbz001', 'dxbz002', 'dxgc', 'dxgc002'],
    children: [
      {
        key: 'warehouse-materials',
        title: '库存明细',
        path: '/warehouse',
        roles: ['admin', 'warehouse', 'pmc', 'eng_auditor', 'purchasing'],
      },
      {
        key: 'wh-stocktake',
        title: '库存盘点',
        path: '/warehouse/stocktake',
        roles: R_WH,
      },
      {
        key: 'wh-transfer',
        title: '库存调拨 / 出库',
        path: '/warehouse/transfer',
        roles: R_WH,
      },
      {
        key: 'warehouse-tooling',
        title: '工装登记',
        path: '/warehouse/tooling',
        classicPage: 'warehouse',
        roles: ['admin', 'warehouse', 'planner', 'pmc', 'eng_auditor'],
      },
    ],
  },
  {
    key: 'shipping',
    title: '出货',
    roles: [...R_WH, 'sales', 'packing'],
    usernames: ['dxbz001', 'dxbz002', 'dxgc', 'dxgc002'],
    children: [
      {
        key: 'ship-sales-issue',
        title: '销售出库单',
        path: '/shipping/sales-issue',
        roles: [...R_WH, 'sales'],
      },
      {
        key: 'warehouse-finished',
        title: '成品发货(过渡)',
        path: '/warehouse/finished-goods',
        roles: ['admin', 'warehouse', 'planner', 'pmc', 'eng_auditor', 'packing', 'sales'],
        usernames: ['dxbz001', 'dxbz002', 'dxgc', 'dxgc002'],
      },
      {
        key: 'warehouse-pack-boxes',
        title: '打包 / 批次记录',
        path: '/warehouse/pack-boxes',
        roles: ['admin', 'warehouse', 'planner', 'pmc', 'eng_auditor', 'packing'],
        usernames: ['dxbz001', 'dxbz002', 'dxgc', 'dxgc002'],
      },
      {
        key: 'ship-delivery',
        title: '发货单',
        path: '/shipping/delivery',
        roles: [...R_WH, 'sales'],
      },
    ],
  },
  {
    key: 'aftersales',
    title: '售后',
    roles: [...R_ALL_BIZ, 'quality', 'warehouse'],
    children: [
      { key: 'as-complaint', title: '投诉单', path: '/aftersales/complaint', roles: [...R_ALL_BIZ, 'quality'] },
      { key: 'as-return', title: '销售退货 / 补发补货', path: '/aftersales/return', roles: [...R_ALL_BIZ, 'warehouse'] },
      { key: 'as-sample', title: '借样还入 / 转销售', path: '/aftersales/sample', roles: R_ALL_BIZ },
    ],
  },
  {
    key: 'quality',
    title: '品质',
    roles: R_QC,
    usernames: ['dxsmt001'],
    children: [
      { key: 'qc-iqc', title: 'IQC / IPQC / QA', path: '/quality/gates', roles: R_QC, comingSoon: true, phase: '阶段4-5' },
      {
        key: 'qc-aoi-repair',
        title: 'AOI维修改判',
        path: '/quality/aoi-repair',
        roles: ['admin', 'planner', 'pmc', 'quality'],
        usernames: ['dxsmt001'],
      },
      { key: 'qc-process-defects', title: '制程不良', path: '/quality/process-defects', roles: R_QC },
      { key: 'qc-complaints', title: '客诉看板', path: '/quality/complaints', roles: R_QC },
      { key: 'qc-barcode-trace', title: '条码追溯', path: '/quality/barcode-trace', roles: R_QC },
      { key: 'qc-dip-first-article', title: 'DIP首件', path: '/quality/dip-first-article', roles: R_QC },
      { key: 'qc-smt-ipqc', title: 'SMT巡检', path: '/quality/smt-ipqc', roles: R_QC },
    ],
  },
  {
    key: 'finance',
    title: '财务',
    roles: R_FIN,
    children: [
      { key: 'fin-ap', title: '应付统计 / 付款申请', path: '/finance/ap', roles: R_FIN },
      { key: 'fin-ar', title: '应收统计 / 收款', path: '/finance/ar', roles: R_FIN },
      { key: 'fin-cashier', title: '出纳', path: '/finance/cashier', roles: R_FIN },
      { key: 'fin-gl', title: '总账 / 月末', path: '/finance/gl', roles: R_FIN },
    ],
  },
  {
    key: 'hr',
    title: '人事',
    roles: ['admin', 'hr', 'pmc'],
    children: [
      { key: 'hr-staff', title: '员工档案', path: '/hr/staff', roles: ['admin', 'hr', 'pmc'] },
      { key: 'hr-attendance', title: '请假登记', path: '/hr/attendance', roles: ['admin', 'hr', 'pmc'] },
    ],
  },
  {
    key: 'settings',
    title: '系统',
    roles: R_SYS,
    children: [
      { key: 'settings-sync', title: '同步 / 集成', path: '/settings/sync', roles: R_SYS },
      {
        key: 'settings-account-perms',
        title: '账号权限',
        path: '/settings/account-permissions',
        roles: ['admin'],
        usernames: ['WGQ', 'dx001'],
      },
    ],
  },
]

export function findMenuByPath(path: string, items: MenuItem[] = menuTree): MenuItem | null {
  for (const item of items) {
    if (item.path === path) return item
    if (item.children) {
      const found = findMenuByPath(path, item.children)
      if (found) return found
    }
  }
  return null
}

/** 路由 path → 子页 key；无法映射则返回 null（不按子页卡） */
export function pageKeyForPath(path: string): string | null {
  const p = (path || '').split('?')[0]
  if (p === '/pda' || p.startsWith('/pda/')) return 'pda'
  if (p === '/floor' || p.startsWith('/floor/')) return 'pda'
  if (p.startsWith('/orders/hub/')) return 'orders-list'
  const exact = findMenuByPath(p)
  if (exact?.key && exact.path) return exact.key
  let best: MenuItem | null = null
  const walk = (items: MenuItem[]) => {
    for (const it of items) {
      if (it.path && (p === it.path || p.startsWith(it.path + '/'))) {
        if (!best || (it.path.length > (best.path || '').length)) best = it
      }
      if (it.children) walk(it.children)
    }
  }
  walk(menuTree)
  return best?.key || null
}

export function canAccessPath(path: string, user: AuthUser | null): boolean {
  if (!user) return false
  const key = pageKeyForPath(path)
  if (!key) return true
  const pages = user.module_pages
  if (Array.isArray(pages) && !pages.includes(key)) return false
  let matched: MenuItem | null = null
  const walk = (items: MenuItem[]) => {
    for (const it of items) {
      if (it.key === key) matched = it
      if (it.children) walk(it.children)
    }
  }
  walk(menuTree)
  if (matched?.usernames?.length) {
    const name = String(user.username || '')
      .trim()
      .toLowerCase()
    const inUsers = matched.usernames.map((u) => u.toLowerCase()).includes(name)
    if (!inUsers && !(matched.roles && matched.roles.length)) return false
  }
  return true
}

export function breadcrumbFor(path: string): string[] {
  const crumbs: string[] = []
  function walk(items: MenuItem[], parents: string[]): boolean {
    for (const item of items) {
      const chain = [...parents, item.title]
      if (item.path === path) {
        crumbs.push(...chain)
        return true
      }
      if (item.children && walk(item.children, chain)) return true
    }
    return false
  }
  walk(menuTree, [])
  return crumbs
}
