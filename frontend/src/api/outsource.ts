import { apiFetch } from './http'

export type WwLine = {
  id?: number
  material_code: string
  material_name: string
  qty: number
  unit?: string
  unit_price?: number
  process?: string
  due_date?: string
  shipped_qty?: number
  pass_qty?: number
  fail_qty?: number
  received_qty?: number
  returned_qty?: number
}

export type OutsourceOrder = {
  id: number
  ww_no: string
  supplier_name: string
  process?: string
  source_plan_no?: string
  status: string
  stock_owner?: string
  remark?: string
  lines?: WwLine[]
}

export type ShipDoc = {
  id: number
  ship_no: string
  ww_id: number
  ww_no: string
  status: string
  lines?: Array<{ material_code: string; qty: number }>
}

export type InspectDoc = {
  id: number
  inspect_no: string
  ww_id: number
  ww_no: string
  status: string
  result: string
  lines?: Array<{
    id: number
    material_code: string
    material_name: string
    qty: number
    pass_qty: number
    fail_qty: number
  }>
}

export type ReceiptDoc = {
  id: number
  receipt_no: string
  ww_no: string
  status: string
  warehouse_code: string
  lines?: Array<{ material_code: string; qty: number }>
}

export type ReturnDoc = {
  id: number
  return_no: string
  ww_no: string
  status: string
  warehouse_code: string
  lines?: Array<{ material_code: string; qty: number }>
}

export function fetchOutsourceOrders(params: { q?: string; status?: string } = {}) {
  const qs = new URLSearchParams()
  if (params.q) qs.set('q', params.q)
  if (params.status) qs.set('status', params.status)
  const s = qs.toString()
  return apiFetch<{ items: OutsourceOrder[] }>(`/outsource/orders${s ? `?${s}` : ''}`)
}

export function createOutsourceOrder(body: Partial<OutsourceOrder> & { lines: WwLine[] }) {
  return apiFetch<OutsourceOrder>('/outsource/orders', { method: 'POST', body: JSON.stringify(body) })
}

export function setOutsourceOrderStatus(id: number, status: string) {
  return apiFetch<OutsourceOrder>(`/outsource/orders/${id}/status`, {
    method: 'POST',
    body: JSON.stringify({ status }),
  })
}

export function createWwFromPlan(planId: number, body: { supplier_name?: string } = {}) {
  return apiFetch<OutsourceOrder>(`/outsource/orders/from-plan/${planId}`, {
    method: 'POST',
    body: JSON.stringify(body),
  })
}

export function createShipFromWw(wwId: number) {
  return apiFetch<ShipDoc>(`/outsource/ships/from-order/${wwId}`, { method: 'POST' })
}

export function fetchShips() {
  return apiFetch<{ items: ShipDoc[] }>('/outsource/ships')
}

export function confirmShip(id: number) {
  return apiFetch<ShipDoc>(`/outsource/ships/${id}/confirm`, { method: 'POST' })
}

export function registerBarcode(body: {
  ww_id: number
  barcode: string
  material_code?: string
  qty?: number
}) {
  return apiFetch('/outsource/barcodes', { method: 'POST', body: JSON.stringify(body) })
}

export function createInspectFromWw(wwId: number) {
  return apiFetch<InspectDoc>(`/outsource/inspects/from-order/${wwId}`, { method: 'POST' })
}

export function fetchInspects() {
  return apiFetch<{ items: InspectDoc[] }>('/outsource/inspects')
}

export function judgeInspect(id: number, lines: Array<{ line_id: number; pass_qty: number; fail_qty: number }>) {
  return apiFetch<InspectDoc>(`/outsource/inspects/${id}/judge`, {
    method: 'POST',
    body: JSON.stringify({ lines }),
  })
}

export function createReceiptFromInspect(inspectId: number) {
  return apiFetch<ReceiptDoc>(`/outsource/receipts/from-inspect/${inspectId}`, { method: 'POST' })
}

export function fetchReceipts() {
  return apiFetch<{ items: ReceiptDoc[] }>('/outsource/receipts')
}

export function postReceipt(id: number) {
  return apiFetch<ReceiptDoc>(`/outsource/receipts/${id}/post`, { method: 'POST' })
}

export function createReturnFromInspect(inspectId: number) {
  return apiFetch<ReturnDoc>(`/outsource/returns/from-inspect/${inspectId}`, { method: 'POST' })
}

export function fetchReturns() {
  return apiFetch<{ items: ReturnDoc[] }>('/outsource/returns')
}

export function confirmReturn(id: number) {
  return apiFetch<ReturnDoc>(`/outsource/returns/${id}/confirm`, { method: 'POST' })
}
