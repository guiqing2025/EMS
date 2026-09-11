import { apiFetch } from './http'

export type McKittingComponent = {
  material_code: string
  material_name: string
  qty_per: number
  required_qty: number
  available_qty: number
  shortage_qty: number
  unit?: string
  process?: string
}

export type McKittingItem = {
  so_id: number
  so_no: string
  so_status: string
  customer_name: string
  external_po_no?: string
  line_id: number
  material_code: string
  material_name: string
  qty: number
  unit?: string
  due_date?: string
  bom_model_id?: number | null
  kitting_status: string
  kitting_status_label: string
  component_count: number
  shortage_count: number
  purchase_shortage_qty: number
  outsource_shortage_qty: number
  components: McKittingComponent[]
}

export type McKittingResult = {
  run_at: string
  order_count: number
  line_count: number
  ready_count: number
  shortage_count: number
  items: McKittingItem[]
  status_labels?: Record<string, string>
}

export function runMcKitting(body: { so_ids?: number[]; q?: string } = {}) {
  return apiFetch<McKittingResult>('/planning/mc-kitting/run', {
    method: 'POST',
    body: JSON.stringify(body),
  })
}

export type ScheduleRow = {
  id: number
  line_type: string
  sort_order: number
  line_name?: string | null
  line_key?: string | null
  internal_code?: string | null
  customer_id?: string | null
  purchase_no?: string | null
  model_code?: string | null
  model_name?: string | null
  process?: string | null
  order_qty: number
  due_date?: string | null
  material_status: string
  daily_plan?: string | null
  schedule_status: string
  remark?: string | null
  updated_by?: string | null
  updated_at?: string
  tooling_status_label?: string
}

export type ScheduleMeta = {
  material_statuses: Record<string, string>
  schedule_statuses: Record<string, string>
  tooling_statuses: Record<string, string>
}

export function fetchScheduleMeta() {
  return apiFetch<ScheduleMeta>('/scheduling/meta')
}

export function fetchSchedules(line_type: 'smt' | 'dip' = 'smt') {
  return apiFetch<ScheduleRow[]>(`/scheduling?line_type=${line_type}`)
}

export function createSchedule(body: Partial<ScheduleRow> & { line_type: string }) {
  return apiFetch<ScheduleRow>('/scheduling', { method: 'POST', body: JSON.stringify(body) })
}

export function updateSchedule(id: number, body: Partial<ScheduleRow> & { line_type: string }) {
  return apiFetch<ScheduleRow>(`/scheduling/${id}`, { method: 'PUT', body: JSON.stringify(body) })
}

export function deleteSchedule(id: number) {
  return apiFetch<{ message: string }>(`/scheduling/${id}`, { method: 'DELETE' })
}

export function refreshScheduleKitting(line_type: 'smt' | 'dip') {
  return apiFetch<{ message: string }>(`/scheduling/refresh-kitting?line_type=${line_type}`, {
    method: 'POST',
  })
}
