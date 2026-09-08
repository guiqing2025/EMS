import { apiFetch } from '@/api/http'

export type ProcessStation = 'plugin' | 'post_solder' | 'coating'

export interface ProcessScanResult {
  status: 'ok' | 'blocked' | 'already_scanned'
  message: string
  station?: string
  station_label?: string
  barcode?: string
  purchase_no?: string | null
  model_code?: string | null
  scanned_at?: string | null
  operator?: string | null
  id?: number
  aoi_result?: string
  ict_result?: string
  pre_oven_aoi_result?: string
  pre_oven_confirm_required?: boolean
  pre_oven_fail_reason?: string
  pre_oven_fail_items?: PreOvenFailItem[]
}

export interface PreOvenFailItem {
  ref: string
  part_type?: string
  part_type_zh?: string
  defect?: string
  defect_zh?: string
  label: string
}

export interface SmtScanResult {
  status: 'ok' | 'blocked' | 'already_scanned' | 'already_aoi'
  message: string
  barcode?: string
  purchase_no?: string | null
  model_code?: string | null
  scanned_at?: string | null
  operator?: string | null
  id?: number
  aoi_result?: string
  is_new?: boolean
}

export interface ProcessScanList {
  purchase_no: string
  station: string
  total: number
  items: Array<{
    id: number
    barcode: string
    station: string
    station_label: string
    model_code?: string | null
    operator?: string | null
    scanned_at?: string | null
  }>
}

export async function submitProcessScan(payload: {
  station: ProcessStation
  barcode: string
  purchase_no?: string
  model_code?: string
  operator?: string
}) {
  return apiFetch<ProcessScanResult>('/process-scan/scan', {
    method: 'POST',
    body: JSON.stringify(payload),
  })
}

/** 后焊产线：炉前 AOI 真不良复判（独立于 /scan 热路径） */
export async function confirmPreOvenAoiLine(payload: {
  barcode: string
  action: 'pass' | 'fail'
  purchase_no?: string
  model_code?: string
  remark?: string
}) {
  return apiFetch<{
    status: string
    action: string
    barcode: string
    message: string
    gate_ok?: boolean
    fail_reason?: string
    already_confirmed?: boolean
  }>('/process-scan/pre-oven-aoi/line-confirm', {
    method: 'POST',
    body: JSON.stringify(payload),
  })
}

export async function submitSmtScan(payload: {
  barcode: string
  result: 'PASS' | 'FAIL' | string
  purchase_no?: string
  model_code?: string
  operator?: string
}) {
  return apiFetch<SmtScanResult>('/process-scan/smt', {
    method: 'POST',
    body: JSON.stringify(payload),
  })
}

/** 补全历史缺机型扫码，刷新后订单列表数量可回显 */
export async function backfillProcessScanModels(limit = 50000) {
  const q = new URLSearchParams({ limit: String(limit) })
  return apiFetch<{
    status: string
    laser_scanned: number
    laser_fixed: number
    order_scanned: number
    order_filled: number
    order_skipped_multi_model: number
  }>(`/process-scan/backfill-model?${q}`, { method: 'POST' })
}

export async function fetchProcessScans(
  purchaseNo: string,
  opts: { station?: ProcessStation | ''; keyword?: string; limit?: number } = {},
) {
  const q = new URLSearchParams()
  if (opts.station) q.set('station', opts.station)
  if (opts.keyword) q.set('keyword', opts.keyword)
  if (opts.limit) q.set('limit', String(opts.limit))
  return apiFetch<ProcessScanList>(
    `/process-scan/orders/${encodeURIComponent(purchaseNo)}?${q}`,
  )
}
