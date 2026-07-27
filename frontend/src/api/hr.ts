import { apiFetch } from '@/api/http'

export interface HrEmployee {
  id: number
  employee_no: string
  name: string
  gender?: string | null
  id_card?: string | null
  id_card_masked?: string | null
  age?: number | null
  age_band?: string | null
  phone?: string | null
  address?: string | null
  hire_date?: string | null
  tenure_years?: number | null
  tenure_band?: string | null
  department?: string | null
  position?: string | null
  education?: string | null
  remark?: string | null
  hire_grade?: string | null
  leave_date?: string | null
  leave_reason?: string | null
  lives_in_dorm: boolean
  dorm_room?: string | null
  source?: string
  status_locked?: boolean
  is_active: boolean
  synced_at?: string | null
}

export interface HrEmployeesPage {
  total: number
  items: HrEmployee[]
}

export interface HrMeta {
  roster_path: string
  accessible: boolean
  active_count: number
  total_count: number
  dorm_count?: number
  last_synced_at?: string | null
  departments: string[]
  hire_grades?: string[]
  leave_types?: string[]
  leave_reason_presets?: string[]
}

export interface HrSyncResult {
  path: string
  parsed: number
  created: number
  updated: number
  inactivated: number
  active_count: number
  dorm_count?: number
  dorm_matched?: number
  dorm_total?: number
  dorm_cleared?: number
  dorm_unmatched?: string[]
  synced_at: string
}

export interface HrEmployeePayload {
  employee_no?: string
  name?: string
  gender?: string | null
  id_card?: string | null
  phone?: string | null
  address?: string | null
  hire_date?: string | null
  department?: string | null
  position?: string | null
  education?: string | null
  remark?: string | null
  hire_grade?: string | null
  lives_in_dorm?: boolean
  dorm_room?: string | null
}

export interface HrLeaveRecord {
  id: number
  employee_id: number
  employee_no: string
  employee_name: string
  leave_type: string
  start_date: string
  end_date: string
  days: number
  reason?: string | null
  status: string
  created_by?: string | null
  created_at?: string | null
}

export interface HrLeavesPage {
  total: number
  items: HrLeaveRecord[]
}

export function fetchHrMeta() {
  return apiFetch<HrMeta>('/hr/employees/meta')
}

export function fetchHrEmployees(params: {
  keyword?: string
  department?: string
  active?: 'all' | 'active' | 'inactive'
  dorm?: 'all' | 'yes' | 'no'
  page?: number
  page_size?: number
}) {
  const q = new URLSearchParams()
  Object.entries(params).forEach(([k, v]) => {
    if (v != null && v !== '') q.set(k, String(v))
  })
  return apiFetch<HrEmployeesPage>(`/hr/employees?${q}`)
}

export function syncHrEmployees() {
  return apiFetch<HrSyncResult>('/hr/employees/sync', { method: 'POST' })
}

export function createHrEmployee(body: HrEmployeePayload & { employee_no: string; name: string }) {
  return apiFetch<HrEmployee>('/hr/employees', { method: 'POST', body: JSON.stringify(body) })
}

export function updateHrEmployee(id: number, body: HrEmployeePayload) {
  return apiFetch<HrEmployee>(`/hr/employees/${id}`, { method: 'PATCH', body: JSON.stringify(body) })
}

export function resignHrEmployee(id: number, body: { leave_date?: string; leave_reason: string }) {
  return apiFetch<HrEmployee>(`/hr/employees/${id}/resign`, {
    method: 'POST',
    body: JSON.stringify(body),
  })
}

export function rehireHrEmployee(
  id: number,
  body: { hire_date?: string; hire_grade?: string; clear_leave?: boolean } = {},
) {
  return apiFetch<HrEmployee>(`/hr/employees/${id}/rehire`, {
    method: 'POST',
    body: JSON.stringify(body),
  })
}

export function fetchHrLeaves(params: {
  keyword?: string
  leave_type?: string
  status?: 'all' | 'approved' | 'cancelled'
  date_from?: string
  date_to?: string
  page?: number
  page_size?: number
}) {
  const q = new URLSearchParams()
  Object.entries(params).forEach(([k, v]) => {
    if (v != null && v !== '') q.set(k, String(v))
  })
  return apiFetch<HrLeavesPage>(`/hr/leaves?${q}`)
}

export function createHrLeave(body: {
  employee_id: number
  leave_type: string
  start_date: string
  end_date?: string
  days?: number
  reason: string
}) {
  return apiFetch<HrLeaveRecord>('/hr/leaves', { method: 'POST', body: JSON.stringify(body) })
}

export function cancelHrLeave(id: number) {
  return apiFetch<HrLeaveRecord>(`/hr/leaves/${id}/cancel`, { method: 'POST' })
}

export function deleteHrLeave(id: number) {
  return apiFetch<{ ok: boolean }>(`/hr/leaves/${id}`, { method: 'DELETE' })
}
