import { apiFetch } from '@/api/http'
import type { ScanRecord, ScanResult, ShipmentResult } from '@/types/order'

export async function fetchPendingScans(lineKey: string) {
  return apiFetch<ScanRecord[]>(
    `/packing/scans/${encodeURIComponent(lineKey)}?status=pending&limit=15`,
  )
}

export async function submitScan(lineKey: string, barcode: string, operator: string) {
  return apiFetch<ScanResult>('/packing/scan', {
    method: 'POST',
    body: JSON.stringify({ line_key: lineKey, barcode, operator }),
  })
}

export interface ShipInput {
  line_key: string
  ship_date: string
  box_count: number
  logistics?: string
  remark?: string
  operator?: string
}

export async function confirmShipment(payload: ShipInput) {
  return apiFetch<ShipmentResult>('/packing/ship', {
    method: 'POST',
    body: JSON.stringify(payload),
  })
}
