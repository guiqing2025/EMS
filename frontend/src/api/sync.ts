import { apiFetch } from '@/api/http'

export interface SyncResult {
  status: string
  message?: string
  new_orders_count?: number
  kitting_alert_count?: number
  sync_log_id?: number
  new_orders?: Array<Record<string, string>>
  kitting_alerts?: Array<Record<string, string>>
}

export async function runSync() {
  return apiFetch<SyncResult>('/sync/run', { method: 'POST' })
}

export interface NotifyItem {
  sync_log_id: number
  new_orders_count: number
  kitting_alert_count: number
  orders: Array<Record<string, string>>
  kitting_alerts: Array<Record<string, string>>
}

export async function fetchNotifications(sinceId = 0) {
  return apiFetch<{ items: NotifyItem[] }>(`/sync/notifications?since_id=${sinceId}`)
}
