import { apiFetch } from '@/api/http'

export interface LaserBatch {
  id: number
  customer_id: string
  customer_name?: string | null
  laser_date: string
  model_code: string
  purchase_no: string
  order_qty: number
  seq_from: number
  seq_to: number
  barcode_prefix?: string | null
  remark?: string | null
  source: string
  created_by?: string | null
}

export interface LaserBatchInput {
  customer_id: string
  customer_name: string
  laser_date: string
  model_code: string
  purchase_no: string
  order_qty: number
  seq_range: string
  remark?: string
}

export interface OrderBoardSummary {
  purchase_no: string
  total: number
  pass_count: number
  fail_count: number
  unknown_count: number
  items_limit?: number
  items_truncated?: boolean
  result_filter?: string
  laser_batches: Array<{
    id: number
    laser_date: string
    model_code: string
    seq_from: number
    seq_to: number
    order_qty: number
  }>
  items: Array<{
    barcode: string
    model_code?: string | null
    laser_date?: string | null
    seq?: number | null
    side?: string | null
    result: string
    machine?: string | null
    tested_at?: string | null
    source_file?: string | null
  }>
}

export async function fetchLaserBatches(params: Record<string, string | number> = {}) {
  const q = new URLSearchParams()
  Object.entries(params).forEach(([k, v]) => {
    if (v !== undefined && v !== null && v !== '') q.set(k, String(v))
  })
  return apiFetch<LaserBatch[]>(`/laser/batches?${q}`)
}

export async function createLaserBatch(payload: LaserBatchInput) {
  return apiFetch<LaserBatch[]>('/laser/batches', {
    method: 'POST',
    body: JSON.stringify(payload),
  })
}

export async function deleteLaserBatch(id: number) {
  return apiFetch<{ ok: boolean }>(`/laser/batches/${id}`, { method: 'DELETE' })
}

export async function importDefaultLaserExcel() {
  return apiFetch<Record<string, unknown>>('/laser/batches/import-default', { method: 'POST' })
}

export async function importFeilisiPrintRegister() {
  return apiFetch<{
    path: string
    sheet: string
    created: number
    updated: number
    skipped: number
    errors: string[]
    ict_rematch_linked?: number
    aoi_rematch_matched?: number
  }>('/laser/batches/import-feilisi-print-register', { method: 'POST' })
}

export async function importEnjiuPrintRegister() {
  return apiFetch<{
    path: string
    sheet: string
    created: number
    updated: number
    skipped: number
    errors: string[]
    ict_rematch_linked?: number
  }>('/laser/batches/import-enjiu-print-register', { method: 'POST' })
}

export async function syncAoi(forceAll = false) {
  return apiFetch<Record<string, unknown>>(`/laser/aoi/sync?force_all=${forceAll ? 'true' : 'false'}`, {
    method: 'POST',
  })
}

export async function syncIct(forceAll = false) {
  return apiFetch<Record<string, unknown>>(`/laser/ict/sync?force_all=${forceAll ? 'true' : 'false'}`, {
    method: 'POST',
  })
}

export async function syncTtsLaser(rematch = true) {
  return apiFetch<Record<string, unknown>>(`/laser/tts/sync?rematch=${rematch ? 'true' : 'false'}`, {
    method: 'POST',
  })
}

export interface OrderIctBoardSummary {
  purchase_no: string
  total: number
  pass_count: number
  fail_count: number
  unknown_count: number
  items_limit?: number
  items_truncated?: boolean
  result_filter?: string
  items: Array<{
    barcode: string
    model_code?: string | null
    board_name?: string | null
    result: string
    machine_id?: string | null
    tested_at?: string | null
    source_file?: string | null
    source_host?: string | null
  }>
}

export interface OrderPreOvenAoiSummary {
  purchase_no: string
  total: number
  pass_count: number
  fail_count: number
  unknown_count: number
  false_positive_count?: number
  items_limit?: number
  items_truncated?: boolean
  result_filter?: string
  model_code?: string
  items: Array<{
    barcode: string
    model_code?: string | null
    result: string
    side?: string | null
    laser_date?: string | null
    seq?: number | null
    tested_at?: string | null
    machine?: string | null
    fail_summary?: string | null
    fail_kind?: string | null
  }>
}

export async function fetchOrderBoards(
  purchaseNo: string,
  customerId = '',
  keyword = '',
  opts: { result?: string; includeItems?: boolean; limit?: number } = {},
) {
  const q = new URLSearchParams()
  if (customerId) q.set('customer_id', customerId)
  if (keyword) q.set('keyword', keyword)
  if (opts.result) q.set('result', opts.result)
  q.set('include_items', opts.includeItems === false ? 'false' : 'true')
  if (opts.limit) q.set('limit', String(opts.limit))
  return apiFetch<OrderBoardSummary>(
    `/laser/orders/${encodeURIComponent(purchaseNo)}/boards?${q}`,
  )
}

export async function fetchOrderIctBoards(
  purchaseNo: string,
  customerId = '',
  keyword = '',
  opts: { result?: string; includeItems?: boolean; limit?: number } = {},
) {
  const q = new URLSearchParams()
  if (customerId) q.set('customer_id', customerId)
  if (keyword) q.set('keyword', keyword)
  if (opts.result) q.set('result', opts.result)
  q.set('include_items', opts.includeItems === false ? 'false' : 'true')
  if (opts.limit) q.set('limit', String(opts.limit))
  return apiFetch<OrderIctBoardSummary>(
    `/laser/orders/${encodeURIComponent(purchaseNo)}/ict-boards?${q}`,
  )
}

export async function fetchOrderPreOvenAoiBoards(
  purchaseNo: string,
  customerId = '',
  keyword = '',
  opts: {
    result?: string
    includeItems?: boolean
    limit?: number
    modelCode?: string
  } = {},
) {
  const q = new URLSearchParams()
  if (customerId) q.set('customer_id', customerId)
  if (opts.modelCode) q.set('model_code', opts.modelCode)
  if (keyword) q.set('keyword', keyword)
  if (opts.result) q.set('result', opts.result)
  q.set('include_items', opts.includeItems === false ? 'false' : 'true')
  if (opts.limit) q.set('limit', String(opts.limit))
  return apiFetch<OrderPreOvenAoiSummary>(
    `/laser/orders/${encodeURIComponent(purchaseNo)}/pre-oven-aoi-boards?${q}`,
  )
}
