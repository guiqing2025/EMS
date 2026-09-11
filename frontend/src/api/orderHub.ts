import { apiFetch } from '@/api/http'

export interface OrderHubInboxItem {
  line_key: string
  purchase_no: string
  product_goods_no?: string
  customer_name?: string
  expect_arrival_date?: string | null
  next_step?: {
    title?: string
    role_hint?: string
    code?: string
  } | null
}

export async function fetchOrderHubInbox(limit = 40) {
  const q = new URLSearchParams({ limit: String(limit) })
  try {
    return await apiFetch<{ count: number; items: OrderHubInboxItem[] }>(
      `/orders/hub-inbox?${q}`,
    )
  } catch {
    return { count: 0, items: [] as OrderHubInboxItem[] }
  }
}

export async function fetchOrderHub(lineKey: string) {
  return apiFetch<Record<string, unknown>>(`/orders/${encodeURIComponent(lineKey)}/hub`)
}
