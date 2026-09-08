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
}

export function canAccessMenu(item: MenuItem, user: AuthUser | null): boolean {
  if (!user) return false
  const name = String(user.username || '')
    .trim()
    .toLowerCase()
  const hasUsers = !!(item.usernames && item.usernames.length)
  const inUsers = hasUsers && item.usernames!.map((u) => u.toLowerCase()).includes(name)
  const hasRoles = !!(item.roles && item.roles.length)

  // 账号子页权限（立即生效）：有 module_pages 时以勾选为准
  const pages = user.module_pages
  if (Array.isArray(pages)) {
    if (item.children?.length) {
      return item.children.some((c) => canAccessMenu(c, user))
    }
    if (!pages.includes(item.key)) return false
    // 仅「纯用户名白名单页」（无 roles）才再卡一次；有 roles 时 usernames 是额外放行（如 dxsmt001）
    if (hasUsers && !hasRoles && !inUsers) return false
    return true
  }
  // 兼容：尚未下发 module_pages 时走角色/白名单
  if (user.role === 'pmc') {
    if (item.key === 'dashboard' || item.key === 'quotation' || item.key === 'settings-account-perms') {
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
        // 子页权限模式下只按叶子勾选过滤，父级随子项出现
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

export const menuTree: MenuItem[] = [
  {
    key: 'dashboard',
    title: '首页看板',
    path: '/dashboard',
    usernames: ['dx001', 'dx002', 'dx003', 'WGQ'],
  },
  {
    key: 'quotation',
    title: '订单报价',
    path: '/quotation',
    roles: ['admin'],
    usernames: ['WGQ', 'dx001'],
  },
  {
    key: 'orders',
    title: '订单中心',
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
      'laser',
    ],
    children: [
      {
        key: 'orders-list',
        title: '订单列表',
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
        ],
      },
      { key: 'laser-register', title: '镭雕登记', path: '/orders/laser', roles: ['admin', 'planner', 'laser', 'pmc'] },
    ],
  },
    {
      key: 'production-daily',
      title: '生产日报',
      path: '/production-daily',
      roles: ['admin', 'planner', 'pmc', 'warehouse'],
      usernames: ['dxsmt001'],
    },
  {
    key: 'warehouse',
    title: '仓库管理',
    roles: ['admin', 'warehouse', 'planner', 'pmc', 'eng_auditor', 'packing'],
    usernames: ['dxbz001', 'dxbz002', 'dxgc', 'dxgc002'],
    children: [
      {
        key: 'warehouse-materials',
        title: '物料明细',
        path: '/warehouse',
        roles: ['admin', 'warehouse', 'pmc', 'eng_auditor'],
      },
      {
        key: 'warehouse-finished',
        title: '成品发货',
        path: '/warehouse/finished-goods',
        roles: ['admin', 'warehouse', 'planner', 'pmc', 'eng_auditor', 'packing'],
        usernames: ['dxbz001', 'dxbz002', 'dxgc', 'dxgc002'],
      },
      {
        key: 'warehouse-pack-boxes',
        title: '批次记录',
        path: '/warehouse/pack-boxes',
        roles: ['admin', 'warehouse', 'planner', 'pmc', 'eng_auditor', 'packing'],
        usernames: ['dxbz001', 'dxbz002', 'dxgc', 'dxgc002'],
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
    key: 'engineering',
    title: '工程管理',
    roles: ['admin', 'planner', 'engineering', 'eng_auditor', 'eng_importer', 'eng_viewer', 'pmc'],
    children: [
      {
        key: 'eng-docs',
        title: '工程资料',
        path: '/engineering',
        classicPage: 'engineering',
        roles: ['admin', 'planner', 'engineering', 'eng_auditor', 'eng_importer', 'eng_viewer', 'pmc'],
      },
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
        roles: ['admin', 'planner', 'pmc', 'eng_importer'],
      },
    ],
  },
  {
    key: 'scheduling',
    title: '计划排产',
    roles: ['admin', 'planner', 'pmc'],
    children: [
      { key: 'sch-master', title: '生产主计划', path: '/scheduling/master-plan', roles: ['admin', 'planner', 'pmc'] },
      { key: 'sch-smt', title: 'SMT 排产', path: '/scheduling', classicPage: 'scheduling', roles: ['admin', 'planner', 'pmc'] },
      { key: 'sch-dip', title: 'DIP 排产', path: '/scheduling/dip', classicPage: 'scheduling', roles: ['admin', 'planner', 'pmc'] },
    ],
  },
  {
    key: 'quality',
    title: '品质管理',
    roles: ['admin', 'planner', 'warehouse', 'pmc'],
    usernames: ['dxsmt001'],
    children: [
      {
        key: 'qc-aoi-repair',
        title: 'AOI维修改判',
        path: '/quality/aoi-repair',
        roles: ['admin', 'planner', 'pmc'],
        usernames: ['dxsmt001'],
      },
      {
        key: 'qc-process-defects',
        title: '制程不良看板',
        path: '/quality/process-defects',
        roles: ['admin', 'planner', 'pmc'],
      },
      {
        key: 'qc-complaints',
        title: '客诉看板',
        path: '/quality/complaints',
        roles: ['admin', 'planner', 'pmc'],
      },
      {
        key: 'qc-barcode-trace',
        title: '条码追溯',
        path: '/quality/barcode-trace',
        roles: ['admin', 'planner', 'pmc'],
      },
      {
        key: 'qc-dip-first-article',
        title: 'DIP首件记录',
        path: '/quality/dip-first-article',
        roles: ['admin', 'planner', 'pmc'],
      },
      {
        key: 'qc-smt-ipqc',
        title: 'SMT巡检记录',
        path: '/quality/smt-ipqc',
        roles: ['admin', 'planner', 'pmc'],
      },
    ],
  },
  {
    key: 'hr',
    title: '人事管理',
    roles: ['admin', 'hr', 'pmc'],
    children: [
      { key: 'hr-staff', title: '员工档案', path: '/hr/staff', roles: ['admin', 'hr', 'pmc'] },
      { key: 'hr-attendance', title: '请假登记', path: '/hr/attendance', roles: ['admin', 'hr', 'pmc'] },
    ],
  },
  {
    key: 'settings',
    title: '系统设置',
    roles: ['admin', 'pmc'],
    children: [
      { key: 'settings-sync', title: '同步状态', path: '/settings/sync', roles: ['admin', 'pmc'] },
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
  // 命中菜单项时叠加 usernames 白名单（如账号权限仅 WGQ）
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
    // 纯用户名白名单页才卡死；有 roles 时 usernames 仅为额外放行
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
