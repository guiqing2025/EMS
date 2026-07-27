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
  if (item.usernames?.length) {
    const name = String(user.username || '').trim().toLowerCase()
    if (!item.usernames.map((u) => u.toLowerCase()).includes(name)) return false
  }
  if (!item.roles?.length) return true
  const role = user.role
  if (role === 'admin' && !item.usernames?.length) return true
  // 有 usernames 白名单时，不再因 admin 角色放行所有人
  if (item.usernames?.length) return true
  return item.roles.includes(role)
}

export function filterMenu(items: MenuItem[], user: AuthUser | null): MenuItem[] {
  return items
    .map((item) => {
      if (item.children?.length) {
        // 父级声明了 roles/usernames 时先拦一层，避免子项无 roles 时菜单泄漏
        if ((item.roles?.length || item.usernames?.length) && !canAccessMenu({ ...item, children: undefined }, user)) {
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
    usernames: ['WGQ', 'dx001'],
  },
  {
    key: 'orders',
    title: '订单中心',
    roles: ['admin', 'planner', 'warehouse', 'pmc', 'eng_auditor', 'floor', 'packing'],
    children: [
      { key: 'orders-list', title: '订单列表', path: '/orders', classicPage: 'orders', roles: ['admin', 'planner', 'warehouse', 'pmc', 'eng_auditor', 'floor', 'packing'] },
      { key: 'laser-register', title: '镭雕登记', path: '/orders/laser', roles: ['admin', 'planner'] },
    ],
  },
  {
    key: 'warehouse',
    title: '仓库管理',
    roles: ['admin', 'warehouse', 'planner', 'pmc', 'eng_auditor'],
    children: [
      { key: 'warehouse-materials', title: '物料明细', path: '/warehouse', roles: ['admin', 'warehouse', 'pmc', 'eng_auditor'] },
      { key: 'warehouse-finished', title: '成品库存', path: '/warehouse/finished-goods', roles: ['admin', 'warehouse', 'planner', 'pmc', 'eng_auditor'] },
      { key: 'warehouse-tooling', title: '工装登记', path: '/warehouse/tooling', classicPage: 'warehouse', roles: ['admin', 'warehouse', 'planner', 'pmc', 'eng_auditor'] },
    ],
  },
  {
    key: 'engineering',
    title: '工程管理',
    roles: ['admin', 'planner', 'engineering', 'eng_auditor'],
    children: [
      { key: 'eng-docs', title: '工程资料', path: '/engineering', classicPage: 'engineering', roles: ['admin', 'planner', 'engineering', 'eng_auditor'] },
      { key: 'eng-control', title: '物料管制', path: '/engineering/material-control', roles: ['admin', 'planner', 'engineering', 'warehouse', 'eng_auditor'] },
      { key: 'eng-sub', title: '替代料', path: '/engineering/substitution', classicPage: 'engineering', roles: ['admin', 'planner', 'engineering'] },
      { key: 'eng-process', title: '工序对照', path: '/engineering/process', classicPage: 'engineering', roles: ['admin', 'planner'] },
    ],
  },
  {
    key: 'scheduling',
    title: '计划排产',
    roles: ['admin', 'planner'],
    children: [
      { key: 'sch-smt', title: 'SMT 排产', path: '/scheduling', classicPage: 'scheduling' },
      { key: 'sch-dip', title: 'DIP 排产', path: '/scheduling/dip', classicPage: 'scheduling' },
    ],
  },
  {
    key: 'quality',
    title: '品质管理',
    roles: ['admin', 'planner', 'warehouse'],
    children: [
      { key: 'qc-iqc', title: '来料检验', path: '/quality/iqc' },
      { key: 'qc-ipqc', title: '过程检验', path: '/quality/ipqc' },
      { key: 'qc-oqc', title: '出货检验', path: '/quality/oqc' },
      { key: 'qc-ng', title: '不良品台账', path: '/quality/ng' },
    ],
  },
  {
    key: 'hr',
    title: '人事管理',
    roles: ['admin', 'hr'],
    children: [
      { key: 'hr-staff', title: '员工档案', path: '/hr/staff', roles: ['admin', 'hr'] },
      { key: 'hr-attendance', title: '考勤管理', path: '/hr/attendance', roles: ['admin', 'hr'] },
      { key: 'hr-piece', title: '计件统计', path: '/hr/piece', roles: ['admin', 'hr'] },
    ],
  },
  {
    key: 'dept',
    title: '部门领料',
    roles: ['dept'],
    children: [
      { key: 'dept-pick', title: '领料确认', path: '/dept' },
    ],
  },
  {
    key: 'settings',
    title: '系统设置',
    roles: ['admin'],
    children: [
      { key: 'settings-sync', title: '同步日志', path: '/settings/sync' },
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
