import { apiFetch } from './http'

export type Stocktake = {
  id: number
  stocktake_no: string
  stock_owner: string
  status: string
  lines?: Array<{ material_code: string; book_qty: number; count_qty: number; diff_qty?: number }>
}

export type Transfer = {
  id: number
  doc_no: string
  kind: string
  from_owner: string
  to_owner: string
  status: string
  lines?: Array<{ material_code: string; qty: number }>
}

export function fetchStocktakes() {
  return apiFetch<{ items: Stocktake[] }>('/warehouse-aux/stocktakes')
}

export function createStocktake(body: {
  stock_owner?: string
  remark?: string
  lines: Array<{ material_code: string; material_name?: string; book_qty?: number; count_qty: number }>
}) {
  return apiFetch<Stocktake>('/warehouse-aux/stocktakes', { method: 'POST', body: JSON.stringify(body) })
}

export function postStocktake(id: number) {
  return apiFetch<Stocktake>(`/warehouse-aux/stocktakes/${id}/post`, { method: 'POST' })
}

export function fetchTransfers(kind = '') {
  const qs = kind ? `?kind=${encodeURIComponent(kind)}` : ''
  return apiFetch<{ items: Transfer[] }>(`/warehouse-aux/transfers${qs}`)
}

export function createTransfer(body: {
  kind: 'transfer' | 'out'
  from_owner?: string
  to_owner?: string
  remark?: string
  lines: Array<{ material_code: string; material_name?: string; qty: number }>
}) {
  return apiFetch<Transfer>('/warehouse-aux/transfers', { method: 'POST', body: JSON.stringify(body) })
}

export function postTransfer(id: number) {
  return apiFetch<Transfer>(`/warehouse-aux/transfers/${id}/post`, { method: 'POST' })
}
