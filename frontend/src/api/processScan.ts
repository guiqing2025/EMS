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
  operator?: string
}) {
  return apiFetch<ProcessScanResult>('/process-scan/scan', {
    method: 'POST',
    body: JSON.stringify(payload),
  })
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
