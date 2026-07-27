export function fmtDate(value?: string | null): string {
  if (!value) return '—'
  return value.replace('T', ' ').slice(0, 19)
}

/** 列表用短日期 YYYY-MM-DD */
export function fmtDay(value?: string | null): string {
  if (!value) return '—'
  return value.replace('T', ' ').slice(0, 10)
}

export function lineNo(order: { purchase_seq?: string | null; purchase_phase_seq?: string | null }): string {
  if (!order.purchase_seq || order.purchase_seq === '0') return '—'
  return `${order.purchase_seq}-${order.purchase_phase_seq || '1'}`
}

export function fmtQty(n?: number | null, completed = false): string | number {
  if (completed && (n === 0 || n == null)) return '—'
  return n ?? 0
}

export function orderQty(order: { batch_pur_qty?: number; output_qty?: number }): number {
  return order.batch_pur_qty || order.output_qty || 0
}
