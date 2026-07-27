import { apiFetch } from '@/api/http'

export interface ReceiveBoardModel {
  model_code: string
  model_name: string
  last_month_qty: number
  this_month_qty: number
  last_month_amount: number
  this_month_amount: number
}

export interface ReceiveBoardCustomer {
  customer_id: string
  customer_name: string
  last_month_total: number
  this_month_total: number
  last_month_amount: number
  this_month_amount: number
  models: ReceiveBoardModel[]
}

export interface ShipFeedItem {
  model_code: string
  model_name: string
  qty: number
}

export interface ShipFeedGroup {
  customer_id: string
  customer_name: string
  items: ShipFeedItem[]
  total_qty: number
}

export interface ShipFeed {
  feed_date: string
  is_today: boolean
  last_synced_at?: string | null
  groups: ShipFeedGroup[]
}

export interface ReceiveBoardMonthlyPoint {
  month: string
  qty: number
  amount: number
}

export interface ReceiveBoardMonthlyCustomer {
  customer_id: string
  customer_name: string
  series: ReceiveBoardMonthlyPoint[]
}

export interface ReceiveBoardMonthly {
  history_start: string
  months: string[]
  customers: ReceiveBoardMonthlyCustomer[]
}

export interface ReceiveBoard {
  as_of: string
  this_month: string
  last_month: string
  note: string
  customers: ReceiveBoardCustomer[]
  feed?: ShipFeed | null
  monthly?: ReceiveBoardMonthly | null
}

export function fetchReceiveBoard() {
  return apiFetch<ReceiveBoard>('/dashboard/receive-board')
}
