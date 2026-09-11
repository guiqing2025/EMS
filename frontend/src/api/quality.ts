import { apiFetch, ApiError } from '@/api/http'

export interface AoiLookup {
  barcode: string
  result?: string | null
  machine?: string | null
  source_file?: string | null
  tested_at?: string | null
  purchase_no?: string | null
  model_code?: string | null
  product_name?: string | null
  side?: string | null
  synced_at?: string | null
  storage: string
  can_override: boolean
  is_qc_override: boolean
  gate_ok: boolean
  gate_message?: string
}

export interface AoiOverrideResult {
  id: number
  barcode: string
  previous_result?: string | null
  aoi_result: string
  storage: string
  operator: string
  reason: string
  gate_ok: boolean
  gate_message?: string
  created_at?: string
}

export interface AoiOverrideRow {
  id: number
  barcode: string
  prev_result: string
  new_result: string
  prev_machine?: string | null
  prev_source_file?: string | null
  prev_tested_at?: string | null
  purchase_no?: string | null
  model_code?: string | null
  reason: string
  remark?: string | null
  operator: string
  operator_role?: string | null
  storage: string
  created_at?: string | null
}

export interface AoiFailRow {
  barcode: string
  result?: string | null
  machine?: string | null
  source_file?: string | null
  tested_at?: string | null
  synced_at?: string | null
  purchase_no?: string | null
  model_code?: string | null
  product_name?: string | null
  side?: string | null
  defect_summary?: string | null
  defect_detail?: string | null
  storage: string
  can_override: boolean
}

export interface AoiFailsPage {
  total: number
  hot_total?: number
  archive_total?: number
  items: AoiFailRow[]
  limit: number
  offset: number
}

export function listAoiFails(params: {
  keyword?: string
  purchase_no?: string
  model_code?: string
  limit?: number
  offset?: number
} = {}) {
  const q = new URLSearchParams()
  if (params.keyword) q.set('keyword', params.keyword)
  if (params.purchase_no) q.set('purchase_no', params.purchase_no)
  if (params.model_code) q.set('model_code', params.model_code)
  if (params.limit != null) q.set('limit', String(params.limit))
  if (params.offset != null) q.set('offset', String(params.offset))
  const qs = q.toString()
  return apiFetch<AoiFailsPage>(`/quality/aoi/fails${qs ? `?${qs}` : ''}`)
}

export function lookupAoi(barcode: string) {
  const q = new URLSearchParams({ barcode })
  return apiFetch<AoiLookup>(`/quality/aoi/lookup?${q}`)
}

export function overrideAoiPass(payload: {
  barcode: string
  reason: string
  remark?: string
  confirm_password: string
}) {
  return apiFetch<AoiOverrideResult>('/quality/aoi/override-pass', {
    method: 'POST',
    body: JSON.stringify(payload),
  })
}

export function listAoiOverrides(params: { barcode?: string; limit?: number; offset?: number } = {}) {
  const q = new URLSearchParams()
  if (params.barcode) q.set('barcode', params.barcode)
  if (params.limit != null) q.set('limit', String(params.limit))
  if (params.offset != null) q.set('offset', String(params.offset))
  const qs = q.toString()
  return apiFetch<{ total: number; items: AoiOverrideRow[] }>(
    `/quality/aoi/overrides${qs ? `?${qs}` : ''}`,
  )
}

export interface ProcessDefectDashboard {
  kpi: {
    inspect_total: number
    defect_batch_total: number
    detail_qty: number
    defect_rate: number | null
    model_count: number
    phenomenon_count: number
    row_count: number
  }
  pareto: { name: string; qty: number; share: number; cum_share: number }[]
  trend: { date: string; inspect_qty: number; defect_qty: number; detail_qty: number; rate: number | null }[]
  by_customer: { name: string; qty: number }[]
  by_station: { name: string; qty: number }[]
  model_summary: {
    model_code: string
    inspect_qty: number
    defect_qty: number
    detail_qty: number
    rate: number | null
    top_phenomenon: string
  }[]
  heatmap: { models: string[]; phenomena: string[]; data: number[][] }
}

export interface ProcessDefectMeta {
  year_months: string[]
  customers: string[]
  stations: string[]
}

export function fetchProcessDefectMeta() {
  return apiFetch<ProcessDefectMeta>('/quality/process-defects/meta')
}

export function fetchProcessDefectDashboard(params: {
  year_month?: string
  customer?: string
  station?: string
  model_code?: string
} = {}) {
  const q = new URLSearchParams()
  if (params.year_month) q.set('year_month', params.year_month)
  if (params.customer) q.set('customer', params.customer)
  if (params.station) q.set('station', params.station)
  if (params.model_code) q.set('model_code', params.model_code)
  const qs = q.toString()
  return apiFetch<ProcessDefectDashboard>(`/quality/process-defects/dashboard${qs ? `?${qs}` : ''}`)
}

export function fetchProcessDefectBatches(limit = 20) {
  return apiFetch<{ items: {
    id: number
    filename: string
    operator: string
    row_count: number
    replaced_rows: number
    customers?: string | null
    year_months?: string | null
    imported_at?: string | null
  }[] }>(`/quality/process-defects/batches?limit=${limit}`)
}

export function fetchProcessDefectDetails(params: {
  year_month?: string
  customer?: string
  station?: string
  model_code?: string
  phenomenon?: string
  limit?: number
  offset?: number
} = {}) {
  const q = new URLSearchParams()
  if (params.year_month) q.set('year_month', params.year_month)
  if (params.customer) q.set('customer', params.customer)
  if (params.station) q.set('station', params.station)
  if (params.model_code) q.set('model_code', params.model_code)
  if (params.phenomenon) q.set('phenomenon', params.phenomenon)
  if (params.limit != null) q.set('limit', String(params.limit))
  if (params.offset != null) q.set('offset', String(params.offset))
  const qs = q.toString()
  return apiFetch<{ total: number; items: Record<string, unknown>[] }>(
    `/quality/process-defects/details${qs ? `?${qs}` : ''}`,
  )
}

export async function importProcessDefectExcel(file: File) {
  const token = localStorage.getItem('ems_auth_token') ?? ''
  const fd = new FormData()
  fd.append('file', file)
  const res = await fetch('/api/quality/process-defects/import', {
    method: 'POST',
    headers: token ? { 'X-Auth-Token': token } : {},
    body: fd,
  })
  if (!res.ok) {
    let msg = res.statusText
    try {
      const body = await res.json()
      if (typeof body.detail === 'string') msg = body.detail
    } catch {
      /* ignore */
    }
    throw new ApiError(msg || '导入失败', res.status)
  }
  return res.json() as Promise<{
    batch_id: number
    filename: string
    row_count: number
    replaced_rows: number
    customers?: string
    year_months?: string
    imported_at?: string
  }>
}

export interface ComplaintDashboard {
  kpi: {
    complaint_count: number
    qty_total: number
    model_count: number
    phenomenon_count: number
    image_count: number
    with_action_count: number
    action_rate: number | null
  }
  pareto: { name: string; qty: number; share: number; cum_share: number }[]
  trend: { date: string; qty: number }[]
  by_customer: { name: string; qty: number }[]
  by_station: { name: string; qty: number }[]
  by_dept: { name: string; qty: number }[]
  model_summary: { model_code: string; qty: number; top_phenomenon: string }[]
  heatmap: { models: string[]; phenomena: string[]; data: number[][] }
}

export interface ComplaintMeta {
  year_months: string[]
  customers: string[]
  stations: string[]
  depts: string[]
}

export function fetchComplaintMeta() {
  return apiFetch<ComplaintMeta>('/quality/complaints/meta')
}

export function fetchComplaintDashboard(params: {
  year_month?: string
  customer?: string
  station?: string
  dept?: string
  model_code?: string
} = {}) {
  const q = new URLSearchParams()
  if (params.year_month) q.set('year_month', params.year_month)
  if (params.customer) q.set('customer', params.customer)
  if (params.station) q.set('station', params.station)
  if (params.dept) q.set('dept', params.dept)
  if (params.model_code) q.set('model_code', params.model_code)
  const qs = q.toString()
  return apiFetch<ComplaintDashboard>(`/quality/complaints/dashboard${qs ? `?${qs}` : ''}`)
}

export function fetchComplaintBatches(limit = 20) {
  return apiFetch<{ items: {
    id: number
    filename: string
    operator: string
    customer: string
    row_count: number
    image_count: number
    replaced_rows: number
    year_months?: string | null
    imported_at?: string | null
  }[] }>(`/quality/complaints/batches?limit=${limit}`)
}

export function fetchComplaintDetails(params: {
  year_month?: string
  customer?: string
  station?: string
  dept?: string
  model_code?: string
  phenomenon?: string
  limit?: number
  offset?: number
} = {}) {
  const q = new URLSearchParams()
  if (params.year_month) q.set('year_month', params.year_month)
  if (params.customer) q.set('customer', params.customer)
  if (params.station) q.set('station', params.station)
  if (params.dept) q.set('dept', params.dept)
  if (params.model_code) q.set('model_code', params.model_code)
  if (params.phenomenon) q.set('phenomenon', params.phenomenon)
  if (params.limit != null) q.set('limit', String(params.limit))
  if (params.offset != null) q.set('offset', String(params.offset))
  const qs = q.toString()
  return apiFetch<{
    total: number
    items: {
      id: number
      customer: string
      complaint_date: string | null
      model_code: string
      barcode: string | null
      pcba_code: string | null
      station: string
      ref_des: string | null
      phenomenon: string
      phenomenon_norm: string
      category: string | null
      qty: number
      dept: string | null
      analysis: string | null
      action: string | null
      images: { id: number; url: string; sort_no: number }[]
    }[]
    limit: number
    offset: number
  }>(`/quality/complaints/details${qs ? `?${qs}` : ''}`)
}

export interface BarcodeTraceScanRow {
  id: number
  barcode: string
  purchase_no: string
  line_key: string
  status: string
  status_label: string
  code_type?: string | null
  operator?: string | null
  scanned_at?: string | null
  shipped_at?: string | null
  shipment_id?: number | null
  shipment_no?: string | null
  box_id?: number | null
  box_no?: string | null
  box_status?: string | null
  box_status_label?: string | null
  box_qty?: number | null
  box_qty_target?: number | null
  box_barcodes?: string[]
  source: string
}

export interface BarcodeTraceLegacyRow {
  id: number
  barcode: string
  barcode_norm: string
  order_no: string
  product_code: string
  product_name: string
  package_no: string
  package_status: string
  package_at?: string | null
  line_key?: string | null
  match_status: string
  synced_to_scans: boolean
  remote_id?: number | null
  updated_at?: string | null
}

export interface BarcodeTraceProcessRow {
  id: number
  barcode: string
  station: string
  station_label: string
  purchase_no?: string | null
  model_code?: string | null
  customer_id?: string | null
  operator?: string | null
  scanned_at?: string | null
  from_legacy?: boolean
}

export interface BarcodeTraceChecklistItem {
  key: string
  label: string
  passed: boolean
  status_text: string
  at?: string | null
  operator?: string | null
  detail?: string | null
  source?: string | null
}

export interface BarcodeTraceLegacyInfo {
  has_packing: boolean
  has_process: boolean
  has_synced_to_local?: boolean
  has_any: boolean
  summary: string
}

export interface BarcodeTraceResult {
  barcode: string
  barcode_norm: string
  resolved_barcode?: string
  found: boolean
  match_mode?: 'exact' | 'fuzzy' | 'none' | string
  checklist?: BarcodeTraceChecklistItem[]
  legacy?: BarcodeTraceLegacyInfo
  local_inbound: BarcodeTraceScanRow[]
  legacy_packing: BarcodeTraceLegacyRow[]
  legacy_in_local_scans: BarcodeTraceScanRow[]
  process_scans?: BarcodeTraceProcessRow[]
  ict?: {
    barcode: string
    result?: string | null
    machine_id?: string | null
    model_code?: string | null
    purchase_no?: string | null
    tested_at?: string | null
    source_file?: string | null
  } | null
  aoi?: {
    barcode: string
    result?: string | null
    machine?: string | null
    model_code?: string | null
    purchase_no?: string | null
    side?: string | null
    tested_at?: string | null
    source_file?: string | null
  } | null
  pack_box?: {
    id: number
    box_no: string
    purchase_no?: string
    goods_no?: string
    goods_name?: string
    qty: number
    qty_target: number
    status: string
    status_label: string
    barcodes: string[]
  } | null
  summary: string
}

export function fetchBarcodeTrace(barcode: string) {
  const q = new URLSearchParams({ barcode: barcode.trim() })
  return apiFetch<BarcodeTraceResult>(`/quality/barcode-trace?${q}`)
}

export interface BatchTraceOption {
  purchase_no: string
  model_code: string
  scan_rows: number
  plugin_barcodes: number
  label: string
}

export interface BatchTraceStation {
  station: string
  label: string
  passed: number
  missing: number
  universe: number
  note?: string
}

export interface BatchTraceSummary {
  purchase_no: string
  model_code: string
  plugin_universe: number
  stations: BatchTraceStation[]
  summary: string
}

export interface BatchTraceBarcodeItem {
  barcode: string
  station: string
  station_label: string
  scope: string
  at?: string | null
  operator?: string | null
}

export function fetchBatchTraceOptions(keyword: string, limit = 40) {
  const q = new URLSearchParams({ keyword, limit: String(limit) })
  return apiFetch<{ keyword: string; options: BatchTraceOption[]; summary: string }>(
    `/quality/barcode-trace/options?${q}`,
  )
}

export function fetchBatchTraceSummary(purchaseNo: string, modelCode = '') {
  const q = new URLSearchParams({ purchase_no: purchaseNo })
  if (modelCode) q.set('model_code', modelCode)
  return apiFetch<BatchTraceSummary>(`/quality/barcode-trace/batch-summary?${q}`)
}

export function fetchBatchTraceBarcodes(params: {
  purchase_no: string
  model_code?: string
  station: string
  scope: 'passed' | 'missing'
  page?: number
  page_size?: number
}) {
  const q = new URLSearchParams({
    purchase_no: params.purchase_no,
    station: params.station,
    scope: params.scope,
    page: String(params.page ?? 1),
    page_size: String(params.page_size ?? 50),
  })
  if (params.model_code) q.set('model_code', params.model_code)
  return apiFetch<{
    purchase_no: string
    model_code: string
    station: string
    station_label: string
    scope: string
    page: number
    page_size: number
    total: number
    items: BatchTraceBarcodeItem[]
    note?: string
  }>(`/quality/barcode-trace/batch-barcodes?${q}`)
}

/** 图片 URL（带 access_token，供 <img>/<el-image> 使用） */
export function complaintImageSrc(imageId: number) {
  const token = localStorage.getItem('ems_auth_token') ?? ''
  const q = token ? `?access_token=${encodeURIComponent(token)}` : ''
  return `/api/quality/complaints/images/${imageId}${q}`
}

export async function importComplaintExcel(file: File) {
  const token = localStorage.getItem('ems_auth_token') ?? ''
  const fd = new FormData()
  fd.append('file', file)
  const res = await fetch('/api/quality/complaints/import', {
    method: 'POST',
    headers: token ? { 'X-Auth-Token': token } : {},
    body: fd,
  })
  if (!res.ok) {
    let msg = res.statusText
    try {
      const body = await res.json()
      if (typeof body.detail === 'string') msg = body.detail
    } catch {
      /* ignore */
    }
    throw new ApiError(msg || '导入失败', res.status)
  }
  return res.json() as Promise<{
    batch_id: number
    filename: string
    customer: string
    row_count: number
    image_count: number
    replaced_rows: number
    year_months?: string
    imported_at?: string
  }>
}

export interface PreOvenAoiFailRow {
  barcode: string
  result?: string | null
  fail_reason?: string
  fail_kind?: string
  fail_kind_label?: string
  purchase_no?: string | null
  model_code?: string | null
  product_name?: string | null
  side?: string | null
  machine?: string | null
  tested_at?: string | null
  source_file?: string | null
}

export interface PreOvenAoiOverrideResult {
  id: number
  barcode: string
  previous_result?: string | null
  pre_oven_aoi_result: string
  operator: string
  reason: string
  gate_ok: boolean
  gate_message?: string
  created_at?: string
}

export async function fetchPreOvenAoiFails(params: {
  keyword?: string
  purchase_no?: string
  model_code?: string
  limit?: number
  offset?: number
} = {}) {
  const q = new URLSearchParams()
  if (params.keyword) q.set('keyword', params.keyword)
  if (params.purchase_no) q.set('purchase_no', params.purchase_no)
  if (params.model_code) q.set('model_code', params.model_code)
  if (params.limit != null) q.set('limit', String(params.limit))
  if (params.offset != null) q.set('offset', String(params.offset))
  const qs = q.toString()
  return apiFetch<{ total: number; items: PreOvenAoiFailRow[] }>(
    `/quality/pre-oven-aoi/fails${qs ? `?${qs}` : ''}`,
  )
}

export async function overridePreOvenAoiPass(payload: {
  barcode: string
  reason: string
  remark?: string
  confirm_password: string
}) {
  return apiFetch<PreOvenAoiOverrideResult>('/quality/pre-oven-aoi/override-pass', {
    method: 'POST',
    body: JSON.stringify(payload),
  })
}

export async function fetchPreOvenAoiQcRecords(params: {
  barcode?: string
  limit?: number
  offset?: number
} = {}) {
  const q = new URLSearchParams()
  if (params.barcode) q.set('barcode', params.barcode)
  if (params.limit != null) q.set('limit', String(params.limit))
  if (params.offset != null) q.set('offset', String(params.offset))
  const qs = q.toString()
  return apiFetch<{
    total: number
    items: Array<{
      id: number
      barcode: string
      action: string
      prev_result: string
      fail_reason?: string
      reason?: string
      remark?: string
      operator: string
      purchase_no?: string | null
      model_code?: string | null
      created_at?: string | null
    }>
  }>(`/quality/pre-oven-aoi/records${qs ? `?${qs}` : ''}`)
}
