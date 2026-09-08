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
