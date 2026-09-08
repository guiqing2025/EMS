/** 数据看板账号白名单（与后端 DASHBOARD_VIEWER_USERNAMES 保持一致） */
export const DASHBOARD_VIEWER_USERNAMES = ['dx001', 'dx002', 'dx003', 'wgq'] as const

export function canViewDashboard(user?: { username?: string | null; role?: string | null } | null): boolean {
  if (user?.role === 'pmc') return true
  const name = String(user?.username || '')
    .trim()
    .toLowerCase()
  return (DASHBOARD_VIEWER_USERNAMES as readonly string[]).includes(name)
}

/** 登录后默认首页：不直接进数据看板（看板仍可从侧栏进入） */
export function defaultHomePath(user?: { username?: string | null; role?: string | null } | null): string {
  const role = user?.role
  const name = String(user?.username || '')
    .trim()
    .toLowerCase()
  // 工程资料员邱梦林/任玉娴 / 审核员黄星：进工程并带出待办
  if (
    name === 'dxgc' ||
    name === 'dxgc002' ||
    name === 'dxsmt001' ||
    role === 'engineering' ||
    role === 'eng_auditor' ||
    role === 'eng_importer' ||
    role === 'eng_viewer'
  ) {
    return '/engineering'
  }
  if (role === 'warehouse') return '/warehouse'
  if (role === 'pmc') return '/orders'
  // 产线/包装/SMT：进订单列表，点单进工作台过站（PDA 路由仍可用）
  if (role === 'floor' || role === 'packing' || role === 'smt_scan') return '/orders'
  if (role === 'laser') return '/orders/laser'
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
    name === 'dxgc002' ||
    name === 'dxsmt001' ||
    name === 'dx003' ||
    name === 'wgq' ||
    role === 'eng_auditor' ||
    role === 'eng_importer' ||
    role === 'engineering' ||
    role === 'admin'
  )
}
