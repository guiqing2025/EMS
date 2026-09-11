import { apiFetch } from './http'

export type IssueLine = {
  id?: number
  so_line_id?: number
  material_code: string
  material_name: string
  qty: number
  unit?: string
  unit_price?: number
  packed_qty?: number
}

export type SalesIssue = {
  id: number
  issue_no: string
  so_id?: number
  so_no?: string
  customer_name: string
  status: string
  warehouse_code?: string
  remark?: string
  lines?: IssueLine[]
}

export type DeliveryNote = {
  id: number
  delivery_no: string
  issue_id: number
  issue_no: string
  so_no?: string
  customer_name: string
  status: string
  ship_date?: string
  carrier?: string
  tracking_no?: string
  lines?: Array<{ material_code: string; material_name: string; qty: number; unit_price?: number }>
  pack_barcodes?: Array<{ barcode: string; qty: number; box_no?: string }>
}

export function fetchSalesIssues(params: { q?: string; status?: string } = {}) {
  const qs = new URLSearchParams()
  if (params.q) qs.set('q', params.q)
  if (params.status) qs.set('status', params.status)
  const s = qs.toString()
  return apiFetch<{ items: SalesIssue[] }>(`/shipping/issues${s ? `?${s}` : ''}`)
}

export function createSalesIssue(body: Partial<SalesIssue> & { lines: IssueLine[] }) {
  return apiFetch<SalesIssue>('/shipping/issues', { method: 'POST', body: JSON.stringify(body) })
}

export function createIssueFromSo(soId: number, line_qtys: Array<{ so_line_id: number; qty: number }> = []) {
  return apiFetch<SalesIssue>(`/shipping/issues/from-so/${soId}`, {
    method: 'POST',
    body: JSON.stringify({ line_qtys }),
  })
}

export function postSalesIssue(id: number) {
  return apiFetch<SalesIssue>(`/shipping/issues/${id}/post`, { method: 'POST' })
}

export function voidSalesIssue(id: number) {
  return apiFetch<SalesIssue>(`/shipping/issues/${id}/void`, { method: 'POST' })
}

export function registerPackBarcode(body: {
  issue_id: number
  barcode: string
  material_code?: string
  qty?: number
  box_no?: string
}) {
  return apiFetch('/shipping/pack-barcodes', { method: 'POST', body: JSON.stringify(body) })
}

export function fetchPackBarcodes(issueId: number) {
  return apiFetch<{ items: Array<{ barcode: string; qty: number; box_no: string }> }>(
    `/shipping/issues/${issueId}/pack-barcodes`,
  )
}

export function createDeliveryFromIssue(
  issueId: number,
  body: { carrier?: string; tracking_no?: string; ship_date?: string } = {},
) {
  return apiFetch<DeliveryNote>(`/shipping/deliveries/from-issue/${issueId}`, {
    method: 'POST',
    body: JSON.stringify(body),
  })
}

export function fetchDeliveries() {
  return apiFetch<{ items: DeliveryNote[] }>('/shipping/deliveries')
}

export function confirmDelivery(id: number) {
  return apiFetch<DeliveryNote>(`/shipping/deliveries/${id}/confirm`, { method: 'POST' })
}

export function fetchDeliveryPrint(id: number) {
  return apiFetch<DeliveryNote>(`/shipping/deliveries/${id}/print`)
}
