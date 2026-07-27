import { apiFetch } from '@/api/http'
import type {
  CustomerOption,
  ManualOrderInput,
  OrderFilters,
  SrmOrder,
  StatusOption,
} from '@/types/order'

function toParams(filters: OrderFilters & { page?: number; page_size?: number }) {
  const params = new URLSearchParams()
  Object.entries(filters).forEach(([key, value]) => {
    if (value !== undefined && value !== null && value !== '') {
      params.set(key, String(value))
    }
  })
  return params
}

export async function fetchOrders(filters: OrderFilters & { page: number; page_size: number }) {
  return apiFetch<SrmOrder[]>(`/orders?${toParams(filters)}`)
}

export async function fetchOrderCount(filters: OrderFilters) {
  return apiFetch<{ total: number }>(`/orders/count?${toParams(filters)}`)
}

export async function fetchNewOrders(limit = 200) {
  return apiFetch<{
    days: number
    date_from: string
    count: number
    items: SrmOrder[]
  }>(`/orders/new-orders?limit=${limit}`)
}

export async function fetchStatusOptions(customerId = '') {
  const q = customerId ? `?customer_id=${encodeURIComponent(customerId)}` : ''
  return apiFetch<StatusOption[]>(`/orders/status-options${q}`)
}

export async function fetchSyncCustomers() {
  return apiFetch<CustomerOption[]>('/sync/customers')
}

export async function fetchManualCustomers() {
  return apiFetch<CustomerOption[]>('/orders/manual-customers').catch(() => [] as CustomerOption[])
}

export async function createManualOrder(payload: ManualOrderInput) {
  return apiFetch<SrmOrder>('/orders/manual', {
    method: 'POST',
    body: JSON.stringify(payload),
  })
}

export async function exportOrdersBlob(filters: OrderFilters) {
  const token = localStorage.getItem('ems_auth_token') ?? ''
  const res = await fetch(`/api/orders/export?${toParams(filters)}`, {
    headers: token ? { 'X-Auth-Token': token } : {},
  })
  if (!res.ok) throw new Error('导出失败')
  const disposition = res.headers.get('Content-Disposition') || ''
  const match = disposition.match(/filename="?([^"]+)"?/)
  const filename = match ? decodeURIComponent(match[1]) : 'orders.xlsx'
  const blob = await res.blob()
  return { blob, filename }
}

export async function updateOrderRemark(lineKey: string, remark: string) {
  return apiFetch<SrmOrder>(`/orders/${encodeURIComponent(lineKey)}/remark`, {
    method: 'PATCH',
    body: JSON.stringify({ remark }),
  })
}

export async function deleteOrder(lineKey: string, password: string) {
  return apiFetch<{
    ok: boolean
    line_key: string
    purchase_no: string
    product_goods_no: string
    message: string
  }>(`/orders/${encodeURIComponent(lineKey)}/delete`, {
    method: 'POST',
    body: JSON.stringify({ password }),
  })
}

export async function mergeCustomers(): Promise<CustomerOption[]> {
  const [syncCustomers, manualCustomers] = await Promise.all([
    fetchSyncCustomers(),
    fetchManualCustomers(),
  ])
  const merged = [...syncCustomers]
  const seen = new Set(syncCustomers.map((c) => c.id))
  for (const c of manualCustomers) {
    if (!seen.has(c.id)) {
      merged.push({ id: c.id, name: `${c.name}（手动）` })
      seen.add(c.id)
    }
  }
  return merged
}
