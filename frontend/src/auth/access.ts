/** 数据看板账号白名单（与后端 DASHBOARD_VIEWER_USERNAMES 保持一致） */
export const DASHBOARD_VIEWER_USERNAMES = ['dx001', 'dx002', 'dx003', 'wgq'] as const

export function canViewDashboard(username?: string | null): boolean {
  const name = String(username || '')
    .trim()
    .toLowerCase()
  return (DASHBOARD_VIEWER_USERNAMES as readonly string[]).includes(name)
}

/** 登录后默认首页：无看板权限时落到业务页 */
export function defaultHomePath(user?: { username?: string | null; role?: string | null } | null): string {
  if (canViewDashboard(user?.username)) return '/dashboard'
  const role = user?.role
  const name = String(user?.username || '')
    .trim()
    .toLowerCase()
  // 工程资料员邱梦林 / 审核员黄星：进工程并带出待办（dx003 有看板，默认仍进看板，有待办时登录会跳转工程）
  if (name === 'dxgc' || name === 'dxsmt001' || role === 'engineering' || role === 'eng_auditor') {
    return '/engineering'
  }
  if (role === 'dept') return '/dept'
  if (role === 'warehouse') return '/warehouse'
  if (role === 'pmc') return '/orders'
  if (role === 'floor' || role === 'packing') return '/orders'
  if (role === 'planner') return '/scheduling'
  if (role === 'hr') return '/hr/staff'
  return '/orders'
}

export function isEngPushUser(user?: { username?: string | null; role?: string | null } | null): boolean {
  const role = user?.role
  const name = String(user?.username || '')
    .trim()
    .toLowerCase()
  return (
    name === 'dxgc' ||
    name === 'dxsmt001' ||
    name === 'dx003' ||
    name === 'wgq' ||
    role === 'eng_auditor' ||
    role === 'engineering' ||
    role === 'admin'
  )
}
