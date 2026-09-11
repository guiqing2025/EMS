/** 阶段2：销售订单 + 订单流程链 */
import { apiFetch } from './http'

export type SalesOrderLine = {
  id?: number
  material_code: string
  material_name: string
  spec?: string
  qty: number
  unit?: string
  unit_price?: number
  amount?: number
  due_date?: string
  shipped_qty?: number
  bom_model_id?: number | null
  remark?: string
}

export type SalesOrder = {
  id: number
  so_no: string
  order_kind: string
  customer_id?: number | null
  customer_name: string
  external_po_no?: string
  source_srm_line_key?: string
  require_bom?: boolean
  status: string
  remark?: string
  quote_id?: number | null
  sample_order_id?: number | null
  lines?: SalesOrderLine[]
}

function qs(params: Record<string, string | undefined>) {
  const u = new URLSearchParams()
  Object.entries(params).forEach(([k, v]) => {
    if (v) u.set(k, v)
  })
  const s = u.toString()
  return s ? `?${s}` : ''
}

export function fetchSalesOrders(params: { q?: string; status?: string } = {}) {
  return apiFetch<{ items: SalesOrder[] }>(`/sales/sales-orders${qs(params)}`)
}

export function fetchSalesOrder(id: number) {
  return apiFetch<SalesOrder>(`/sales/sales-orders/${id}`)
}

export function createSalesOrder(body: Partial<SalesOrder> & { lines: SalesOrderLine[] }) {
  return apiFetch<SalesOrder>('/sales/sales-orders', { method: 'POST', body: JSON.stringify(body) })
}

export function updateSalesOrder(id: number, body: Partial<SalesOrder> & { lines: SalesOrderLine[] }) {
  return apiFetch<SalesOrder>(`/sales/sales-orders/${id}`, { method: 'PUT', body: JSON.stringify(body) })
}

export function setSalesOrderStatus(id: number, status: string) {
  return apiFetch<SalesOrder>(`/sales/sales-orders/${id}/status`, {
    method: 'POST',
    body: JSON.stringify({ status }),
  })
}

export function bindSalesLineBom(soId: number, lineId: number, bom_model_id: number | null) {
  return apiFetch<SalesOrderLine>(`/sales/sales-orders/${soId}/lines/${lineId}/bind-bom`, {
    method: 'POST',
    body: JSON.stringify({ bom_model_id }),
  })
}

export function importSalesFromSrm(body: { line_key?: string; purchase_no?: string }) {
  return apiFetch<SalesOrder>('/sales/sales-orders/from-srm', { method: 'POST', body: JSON.stringify(body) })
}

export type SalesOrderCodeRule = {
  doc_type: string
  prefix: string
  name: string
  date_fmt: string
  seq_width: number
  last_date: string
  last_seq: number
  updated_at?: string
  preview_no?: string
}

export function fetchSalesOrderCode() {
  return apiFetch<SalesOrderCodeRule>('/sales/order-code')
}

export function saveSalesOrderCode(body: {
  prefix: string
  name?: string
  date_fmt: string
  seq_width: number
}) {
  return apiFetch<SalesOrderCodeRule>('/sales/order-code', {
    method: 'PUT',
    body: JSON.stringify(body),
  })
}

export function previewSalesOrderCode() {
  return apiFetch<{ doc_type: string; doc_no: string }>('/sales/order-code/preview')
}

export type FlowAction = {
  code: string
  label: string
  plan_id?: number
  issue_id?: number
  delivery_id?: number
  navigate?: string
}

export type FlowStep = {
  key: string
  title: string
  status: string
  hint?: string
  docs: Array<{ kind: string; id: number; no: string; status: string }>
}

export type FlowChain = {
  so_id: number
  so_no: string
  customer_name: string
  status: string
  qty: number
  shipped_qty: number
  steps: FlowStep[]
  next_actions: FlowAction[]
  pmc_hint: string
}

export function fetchFlowChain(soId: number) {
  return apiFetch<FlowChain>(`/sales/sales-orders/${soId}/flow-chain`)
}

export function pushFlowStep(
  soId: number,
  step: string,
  body: { plan_id?: number; issue_id?: number; delivery_id?: number; supplier_name?: string } = {},
) {
  return apiFetch<{ message?: string; chain: FlowChain; step: string }>(
    `/sales/sales-orders/${soId}/push/${step}`,
    { method: 'POST', body: JSON.stringify(body) },
  )
}
