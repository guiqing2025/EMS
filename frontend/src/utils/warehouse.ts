export function fmtWhQty(v?: number | null): string {
  if (v == null || Number.isNaN(Number(v))) return '—'
  const n = Number(v)
  return n % 1 === 0 ? String(n) : n.toFixed(2).replace(/\.?0+$/, '')
}

export function issueStatusLabel(s: string): string {
  return (
    {
      pending_confirm: '待确认',
      confirmed: '已签收',
      rejected: '已拒收',
      pending_warehouse: '待仓库确认',
    }[s] || s
  )
}

export function movementLabel(t: string): string {
  return (
    { stock_in: '手工来料', issue_out: '发料', return_in: '退料', excel_sync: '共享盘同步' }[t] || t
  )
}

export function sourceLabel(s: string): string {
  return ({ manual: '手工来料', excel_sync: '共享盘同步', return: '退料入库' }[s] || s)
}

export function issueLineStatusLabel(s: string): string {
  return (
    {
      ready: '可发',
      shortage: '缺料',
      no_stock: '无库存',
      unregistered: '未建档',
      done: '已发完',
      partial: '部分',
    }[s] || s
  )
}

export function excelMovementLabel(t: string): string {
  return (
    {
      inbound: '进账',
      issue: '发料',
      return: '退料',
      overissue: '超领',
      customer_return: '退客',
      smt_loss: 'SMT损耗',
      adjust: '盘亏超领',
    }[t] || t
  )
}
