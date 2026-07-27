import { apiFetch } from '@/api/http'
import type {
  BatchInboundLine,
  BatchInboundParseResult,
  BatchIssueParseResult,
  BatchOperationResult,
  DeptSummary,
  FinishedGoodsRow,
  OrderIssuePreview,
  StockInRecord,
  StockIssue,
  StockLedger,
  StockReturn,
  WarehouseConfig,
  WarehouseCustomer,
  WarehouseMaterial,
  WarehouseMaterialDetail,
  WarehouseModelMaterials,
  WarehouseMovement,
} from '@/types/warehouse'

const BASE = '/warehouse'

async function whBlob(path: string): Promise<Blob> {
  const token = localStorage.getItem('ems_auth_token') ?? ''
  const res = await fetch(`/api${BASE}${path}`, {
    headers: token ? { 'X-Auth-Token': token } : {},
  })
  if (!res.ok) throw new Error('下载失败')
  return res.blob()
}

function downloadBlob(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  a.click()
  URL.revokeObjectURL(url)
}

export async function fetchWarehouseConfig() {
  return apiFetch<WarehouseConfig>(`${BASE}/config`)
}

export async function fetchWarehouseCustomers() {
  return apiFetch<WarehouseCustomer[]>(`${BASE}/customers`)
}

export async function fetchFinishedGoods(opts: {
  customerId?: string
  keyword?: string
  includeCompleted?: boolean
  onlyWithInbound?: boolean
} = {}) {
  const qs = new URLSearchParams()
  if (opts.customerId) qs.set('customer_id', opts.customerId)
  if (opts.keyword) qs.set('keyword', opts.keyword)
  if (opts.includeCompleted) qs.set('include_completed', 'true')
  if (opts.onlyWithInbound) qs.set('only_with_inbound', 'true')
  const q = qs.toString()
  return apiFetch<FinishedGoodsRow[]>(`${BASE}/finished-goods${q ? `?${q}` : ''}`)
}

export async function fetchMaterials(customerId = '', keyword = '') {
  const qs = new URLSearchParams()
  if (customerId) qs.set('customer_id', customerId)
  if (keyword) qs.set('keyword', keyword)
  const q = qs.toString()
  return apiFetch<WarehouseMaterial[]>(`${BASE}/materials${q ? `?${q}` : ''}`)
}

export async function fetchMaterialsByModel(opts: {
  modelCode: string
  orderQty?: number
  customerId?: string
  bomModelId?: number | null
  purchaseNo?: string
}) {
  const qs = new URLSearchParams()
  qs.set('model_code', opts.modelCode)
  if (opts.orderQty != null) qs.set('order_qty', String(opts.orderQty))
  if (opts.customerId) qs.set('customer_id', opts.customerId)
  if (opts.bomModelId) qs.set('bom_model_id', String(opts.bomModelId))
  if (opts.purchaseNo) qs.set('purchase_no', opts.purchaseNo)
  return apiFetch<WarehouseModelMaterials>(`${BASE}/materials/by-model?${qs}`)
}

export async function fetchStockIns(customerId = '', materialId?: number | null) {
  const qs = new URLSearchParams()
  if (customerId) qs.set('customer_id', customerId)
  if (materialId) qs.set('material_id', String(materialId))
  return apiFetch<StockInRecord[]>(`${BASE}/stock-ins?${qs}`)
}

export async function fetchIssues(status = '') {
  const q = status ? `?status=${encodeURIComponent(status)}` : ''
  return apiFetch<StockIssue[]>(`${BASE}/issues${q}`)
}

export async function fetchReturns() {
  return apiFetch<StockReturn[]>(`${BASE}/returns`)
}

export async function fetchLedger() {
  return apiFetch<StockLedger[]>(`${BASE}/ledger`)
}

export async function fetchMovements(customerId = '', keyword = '', movementType = '') {
  const qs = new URLSearchParams()
  if (customerId) qs.set('customer_id', customerId)
  if (keyword) qs.set('keyword', keyword)
  if (movementType) qs.set('movement_type', movementType)
  const q = qs.toString()
  return apiFetch<WarehouseMovement[]>(`${BASE}/movements${q ? `?${q}` : ''}`)
}

export async function fetchMaterialDetail(materialId: number) {
  return apiFetch<WarehouseMaterialDetail>(`${BASE}/materials/${materialId}/detail`)
}

export async function fetchOperationTypes() {
  return apiFetch<{ type: string; label: string }[]>(`${BASE}/operation-types`)
}

export interface WarehouseOperationPayload {
  material_id: number
  movement_type: string
  qty: number
  order_no?: string
  product_model?: string
  order_qty?: number
  process?: string
  department?: string
  ref_no?: string
  remark?: string
  giver?: string
  receiver?: string
}

export async function createWarehouseOperation(payload: WarehouseOperationPayload) {
  return apiFetch<WarehouseMovement>(`${BASE}/operations`, {
    method: 'POST',
    body: JSON.stringify(payload),
  })
}

export async function batchInbound(
  customerId: string,
  items: BatchInboundLine[],
  opts: { remark?: string; giver?: string; receiver?: string } | string = '',
) {
  const options = typeof opts === 'string' ? { remark: opts } : opts
  return apiFetch<BatchOperationResult>(`${BASE}/batch-inbound`, {
    method: 'POST',
    timeoutMs: 180_000,
    body: JSON.stringify({
      customer_id: customerId,
      items,
      remark: options.remark || '',
      giver: options.giver || '',
      receiver: options.receiver || '',
    }),
  })
}

export async function parseInboundExcel(file: File) {
  const token = localStorage.getItem('ems_auth_token') ?? ''
  const form = new FormData()
  form.append('file', file)
  const res = await fetch(`/api${BASE}/batch-inbound/parse-excel`, {
    method: 'POST',
    headers: token ? { 'X-Auth-Token': token } : {},
    body: form,
  })
  if (!res.ok) {
    let msg = '解析失败'
    try {
      const data = await res.json()
      msg = data.detail || msg
    } catch {
      /* ignore */
    }
    throw new Error(msg)
  }
  return res.json() as Promise<BatchInboundParseResult>
}

export async function downloadInboundTemplate() {
  const blob = await whBlob('/inbound-template')
  downloadBlob(blob, '来料导入模板.xlsx')
}

export async function fetchOrderIssuePreview(lineKey: string) {
  return apiFetch<OrderIssuePreview>(`${BASE}/orders/${encodeURIComponent(lineKey)}/issue-preview`)
}

export async function batchIssueOrder(
  lineKey: string,
  lines: Array<{ material_id: number; qty: number; process?: string; department?: string; remark?: string }>,
  opts: { remark?: string; giver?: string; receiver?: string } | string = '',
) {
  const options = typeof opts === 'string' ? { remark: opts } : opts
  return apiFetch<BatchOperationResult>(`${BASE}/orders/${encodeURIComponent(lineKey)}/batch-issue`, {
    method: 'POST',
    body: JSON.stringify({
      lines,
      remark: options.remark || '',
      skip_shortage: true,
      giver: options.giver || '',
      receiver: options.receiver || '',
    }),
  })
}

export async function downloadOrderIssueTemplate(lineKey: string, filename?: string) {
  const blob = await whBlob(`/orders/${encodeURIComponent(lineKey)}/issue-template`)
  downloadBlob(blob, filename || `发料_${lineKey}.xlsx`)
}

export async function parseIssueExcel(lineKey: string, file: File) {
  const token = localStorage.getItem('ems_auth_token') ?? ''
  const form = new FormData()
  form.append('file', file)
  const res = await fetch(`/api${BASE}/orders/${encodeURIComponent(lineKey)}/batch-issue/parse-excel`, {
    method: 'POST',
    headers: token ? { 'X-Auth-Token': token } : {},
    body: form,
  })
  if (!res.ok) {
    let msg = '解析失败'
    try {
      const data = await res.json()
      const detail = data.detail ?? data.message
      msg = typeof detail === 'string' ? detail : msg
    } catch {
      /* ignore */
    }
    throw new Error(msg)
  }
  return res.json() as Promise<BatchIssueParseResult>
}

export async function syncWarehouseShare() {
  return apiFetch<{ message?: string; files?: Array<{ status: string }> }>(`${BASE}/sync-now`, {
    method: 'POST',
    // 多客户进销表 + 归档，可能超过默认 20s
    timeoutMs: 180000,
  })
}

export async function createStockIn(materialId: number, qty: number, remark = '') {
  return apiFetch(`${BASE}/stock-in`, {
    method: 'POST',
    body: JSON.stringify({ material_id: materialId, qty, remark }),
  })
}

export async function createIssue(materialId: number, qty: number, department: string, remark = '') {
  return apiFetch(`${BASE}/issues`, {
    method: 'POST',
    body: JSON.stringify({ material_id: materialId, qty, department, remark }),
  })
}

export async function confirmReturn(id: number) {
  return apiFetch(`${BASE}/returns/${id}/confirm`, { method: 'POST' })
}

export async function rejectReturn(id: number, remark = '') {
  return apiFetch(`${BASE}/returns/${id}/reject?remark=${encodeURIComponent(remark)}`, {
    method: 'POST',
  })
}

export async function confirmIssue(id: number) {
  return apiFetch(`${BASE}/issues/${id}/confirm`, { method: 'POST' })
}

export async function rejectIssue(id: number, remark = '') {
  return apiFetch(`${BASE}/issues/${id}/reject?remark=${encodeURIComponent(remark)}`, {
    method: 'POST',
  })
}

export async function createReturn(materialId: number, qty: number, remark = '') {
  return apiFetch(`${BASE}/returns`, {
    method: 'POST',
    body: JSON.stringify({ material_id: materialId, qty, remark }),
  })
}

export async function fetchDeptSummary() {
  return apiFetch<DeptSummary>(`${BASE}/dept/summary`)
}

export async function downloadWarehouseTemplate() {
  const blob = await whBlob('/template')
  downloadBlob(blob, '_模板.xlsx')
}

export async function exportWarehouseInventory() {
  const blob = await whBlob('/export-inventory')
  downloadBlob(blob, '库存导出.xlsx')
}
