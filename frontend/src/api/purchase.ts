import { apiFetch } from './http'

export type PoLine = {
  id?: number
  material_code: string
  material_name: string
  qty: number
  unit?: string
  unit_price?: number
  due_date?: string
  arrived_qty?: number
  pass_qty?: number
  fail_qty?: number
  received_qty?: number
  returned_qty?: number
}

export type PurchaseOrder = {
  id: number
  po_no: string
  supplier_name: string
  source_plan_no?: string
  status: string
  stock_owner?: string
  remark?: string
  lines?: PoLine[]
}

export type InspectDoc = {
  id: number
  inspect_no: string
  po_id: number
  po_no: string
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
  po_no: string
  status: string
  warehouse_code: string
  lines?: Array<{ material_code: string; qty: number }>
}

export type ReturnDoc = {
  id: number
  return_no: string
  po_no: string
  status: string
  warehouse_code: string
  lines?: Array<{ material_code: string; qty: number }>
}

export function fetchPurchaseOrders(params: { q?: string; status?: string } = {}) {
  const qs = new URLSearchParams()
  if (params.q) qs.set('q', params.q)
  if (params.status) qs.set('status', params.status)
  const s = qs.toString()
  return apiFetch<{ items: PurchaseOrder[] }>(`/purchase/orders${s ? `?${s}` : ''}`)
}

export function createPurchaseOrder(body: Partial<PurchaseOrder> & { lines: PoLine[] }) {
  return apiFetch<PurchaseOrder>('/purchase/orders', { method: 'POST', body: JSON.stringify(body) })
}

export function setPurchaseOrderStatus(id: number, status: string) {
  return apiFetch<PurchaseOrder>(`/purchase/orders/${id}/status`, {
    method: 'POST',
    body: JSON.stringify({ status }),
  })
}

export function createPoFromPlan(planId: number, body: { supplier_name?: string } = {}) {
  return apiFetch<PurchaseOrder>(`/purchase/orders/from-plan/${planId}`, {
    method: 'POST',
    body: JSON.stringify(body),
  })
}

export function registerArrival(body: {
  po_id: number
  po_line_id?: number
  barcode: string
  material_code?: string
  qty?: number
}) {
  return apiFetch('/purchase/arrivals', { method: 'POST', body: JSON.stringify(body) })
}

export function createInspectFromPo(poId: number) {
  return apiFetch<InspectDoc>(`/purchase/inspects/from-po/${poId}`, { method: 'POST' })
}

export function fetchInspects() {
  return apiFetch<{ items: InspectDoc[] }>('/purchase/inspects')
}

export function judgeInspect(id: number, lines: Array<{ line_id: number; pass_qty: number; fail_qty: number }>) {
  return apiFetch<InspectDoc>(`/purchase/inspects/${id}/judge`, {
    method: 'POST',
    body: JSON.stringify({ lines }),
  })
}

export function createReceiptFromInspect(inspectId: number) {
  return apiFetch<ReceiptDoc>(`/purchase/receipts/from-inspect/${inspectId}`, { method: 'POST' })
}

export function fetchReceipts() {
  return apiFetch<{ items: ReceiptDoc[] }>('/purchase/receipts')
}

export function postReceipt(id: number) {
  return apiFetch<ReceiptDoc>(`/purchase/receipts/${id}/post`, { method: 'POST' })
}

export function createReturnFromInspect(inspectId: number) {
  return apiFetch<ReturnDoc>(`/purchase/returns/from-inspect/${inspectId}`, { method: 'POST' })
}

export function fetchReturns() {
  return apiFetch<{ items: ReturnDoc[] }>('/purchase/returns')
}

export function confirmReturn(id: number) {
  return apiFetch<ReturnDoc>(`/purchase/returns/${id}/confirm`, { method: 'POST' })
}
