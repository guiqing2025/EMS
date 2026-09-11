import { apiFetch } from './http'

export type GlAccount = { code: string; name: string; category: string; balance: number }
export type GlVoucher = {
  id: number
  voucher_no: string
  period: string
  status: string
  source_type: string
  source_no: string
  summary: string
  total_debit?: number
  total_credit?: number
  lines?: Array<{ account_code: string; account_name: string; debit: number; credit: number }>
}
export type GlPeriod = { period: string; status: string }

export function glBootstrap() {
  return apiFetch<{ period: string }>('/finance/gl/bootstrap', { method: 'POST' })
}

export function fetchGlAccounts() {
  return apiFetch<{ items: GlAccount[] }>('/finance/gl/accounts')
}

export function fetchGlPeriods() {
  return apiFetch<{ items: GlPeriod[] }>('/finance/gl/periods')
}

export function fetchGlVouchers(params: { period?: string; status?: string } = {}) {
  const qs = new URLSearchParams()
  if (params.period) qs.set('period', params.period)
  if (params.status) qs.set('status', params.status)
  const s = qs.toString()
  return apiFetch<{ items: GlVoucher[] }>(`/finance/gl/vouchers${s ? `?${s}` : ''}`)
}

export function reviewGlVoucher(id: number) {
  return apiFetch<GlVoucher>(`/finance/gl/vouchers/${id}/review`, { method: 'POST' })
}

export function postGlVoucher(id: number) {
  return apiFetch<GlVoucher>(`/finance/gl/vouchers/${id}/post`, { method: 'POST' })
}

export function createCostAccrual(amount: number, remark = '') {
  return apiFetch<GlVoucher>('/finance/gl/cost-accrual', {
    method: 'POST',
    body: JSON.stringify({ amount, remark }),
  })
}

export function createFixedAsset(body: { name: string; original_value: number; months?: number }) {
  return apiFetch('/finance/gl/assets', { method: 'POST', body: JSON.stringify(body) })
}

export function depreciateAsset(id: number) {
  return apiFetch<GlVoucher>(`/finance/gl/assets/${id}/depreciate`, { method: 'POST' })
}

export function fetchAssets() {
  return apiFetch<{ items: Array<{ id: number; asset_no: string; name: string; original_value: number }> }>(
    '/finance/gl/assets',
  )
}

export function fxAdjust() {
  return apiFetch<{ skipped: boolean; reason: string }>('/finance/gl/fx-adjust', { method: 'POST' })
}

export function closePnl() {
  return apiFetch<GlVoucher>('/finance/gl/close-pnl', { method: 'POST' })
}

export function closePeriod(period = '') {
  return apiFetch<GlPeriod>('/finance/gl/close-period', {
    method: 'POST',
    body: JSON.stringify({ period }),
  })
}
