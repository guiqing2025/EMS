import { apiFetch } from './http'

export type Mo = {
  id: number
  mo_no: string
  material_code: string
  material_name: string
  qty: number
  status: string
  bom_model_id?: number | null
  source_plan_no?: string
  source_so_no?: string
  issued_sets?: number
  qa_pass_qty?: number
  fg_qty?: number
}

export type MaterialDoc = {
  id: number
  doc_no: string
  kind: string
  mo_no: string
  status: string
  lines?: Array<{ material_code: string; material_name: string; qty: number }>
}

export type QaDoc = {
  id: number
  qa_no: string
  mo_no: string
  status: string
  result: string
  qty: number
  pass_qty: number
  fail_qty: number
}

export type FgDoc = {
  id: number
  receipt_no: string
  mo_no: string
  material_code: string
  qty: number
  status: string
  direct_outbound?: boolean
}

export function fetchMos(params: { q?: string; status?: string } = {}) {
  const qs = new URLSearchParams()
  if (params.q) qs.set('q', params.q)
  if (params.status) qs.set('status', params.status)
  const s = qs.toString()
  return apiFetch<{ items: Mo[] }>(`/production/orders${s ? `?${s}` : ''}`)
}

export function createMo(body: Partial<Mo> & { material_code: string; qty: number; bom_model_id?: number }) {
  return apiFetch<Mo>('/production/orders', { method: 'POST', body: JSON.stringify(body) })
}

export function setMoStatus(id: number, status: string) {
  return apiFetch<Mo>(`/production/orders/${id}/status`, { method: 'POST', body: JSON.stringify({ status }) })
}

export function createMoFromPlan(planId: number) {
  return apiFetch<{ items: Mo[] }>(`/production/orders/from-plan/${planId}`, {
    method: 'POST',
    body: JSON.stringify({}),
  })
}

export function registerMoBarcode(moId: number, barcode: string) {
  return apiFetch(`/production/orders/${moId}/barcodes`, {
    method: 'POST',
    body: JSON.stringify({ barcode }),
  })
}

export function createMaterialDoc(body: {
  mo_id: number
  kind: string
  from_bom?: boolean
  lines?: Array<{ material_code: string; material_name: string; qty: number }>
}) {
  return apiFetch<MaterialDoc>('/production/materials', { method: 'POST', body: JSON.stringify(body) })
}

export function fetchMaterialDocs(params: { kind?: string; mo_id?: number } = {}) {
  const qs = new URLSearchParams()
  if (params.kind) qs.set('kind', params.kind)
  if (params.mo_id) qs.set('mo_id', String(params.mo_id))
  const s = qs.toString()
  return apiFetch<{ items: MaterialDoc[] }>(`/production/materials${s ? `?${s}` : ''}`)
}

export function confirmMaterialDoc(id: number) {
  return apiFetch<MaterialDoc>(`/production/materials/${id}/confirm`, { method: 'POST' })
}

export function createQaFromMo(moId: number) {
  return apiFetch<QaDoc>(`/production/qa/from-mo/${moId}`, { method: 'POST' })
}

export function fetchQas() {
  return apiFetch<{ items: QaDoc[] }>('/production/qa')
}

export function judgeQa(id: number, pass_qty: number, fail_qty: number) {
  return apiFetch<QaDoc>(`/production/qa/${id}/judge`, {
    method: 'POST',
    body: JSON.stringify({ pass_qty, fail_qty }),
  })
}

export function createFgFromQa(qaId: number, direct_outbound = false) {
  return apiFetch<FgDoc>(`/production/fg-receipts/from-qa/${qaId}`, {
    method: 'POST',
    body: JSON.stringify({ direct_outbound }),
  })
}

export function fetchFgReceipts() {
  return apiFetch<{ items: FgDoc[] }>('/production/fg-receipts')
}

export function postFg(id: number) {
  return apiFetch<FgDoc>(`/production/fg-receipts/${id}/post`, { method: 'POST' })
}

export function fetchPmcBoard() {
  return apiFetch<{ items: Array<Record<string, unknown>> }>('/production/pmc-board')
}
