/** 登录后默认首页 */
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
    return '/engineering/material-control'
  }
  if (role === 'warehouse') return '/warehouse'
  if (role === 'pmc' || role === 'sales' || role === 'admin' || !role) return '/sales/flow'
  // 产线/包装/SMT：进订单列表，点单进工作台过站（PDA 路由仍可用）
  if (role === 'floor' || role === 'packing' || role === 'smt_scan') return '/orders'
  if (role === 'laser') return '/orders'
  if (role === 'planner') return '/sales/flow'
  if (role === 'hr') return '/hr/staff'
  return '/sales/flow'
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

/** 发货审批：与后端 is_ship_approver_username 对齐 */
export function isShipApprover(user?: { username?: string | null; role?: string | null } | null): boolean {
  const name = String(user?.username || '')
    .trim()
    .toLowerCase()
  if (!name) return false
  if (user?.role === 'admin' || user?.role === 'warehouse' || user?.role === 'planner') return true
  return name === 'wgq' || name === 'dx001' || name === 'dx002' || name.endsWith('approve')
}

/** 箱标待打印弹窗：仓库/包装相关账号 */
export function isShipLabelPopupUser(
  user?: { username?: string | null; role?: string | null } | null,
): boolean {
  const role = user?.role
  const name = String(user?.username || '')
    .trim()
    .toLowerCase()
  if (role === 'admin' || role === 'warehouse' || role === 'packing') return true
  return name === 'dxck' || name === 'dxbz001' || name === 'dxbz002' || name === 'wgq'
}
