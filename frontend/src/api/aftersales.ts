import { apiFetch } from './http'

export type Complaint = {
  id: number
  complaint_no: string
  so_id?: number
  so_no?: string
  delivery_id?: number
  delivery_no?: string
  customer_name: string
  title: string
  content?: string
  status: string
}

export type SalesReturn = {
  id: number
  return_no: string
  so_no?: string
  issue_no?: string
  delivery_no?: string
  customer_name: string
  status: string
  branch: string
  reissue_issue_id?: number
  reissue_delivery_id?: number
  replenish_mo_id?: number
  lines?: Array<{ material_code: string; qty: number }>
}

export type SampleLoan = {
  id: number
  loan_no: string
  customer_name: string
  product_code: string
  product_name: string
  qty: number
  status: string
  converted_so_id?: number
}

export function fetchComplaints(q = '') {
  const qs = q ? `?q=${encodeURIComponent(q)}` : ''
  return apiFetch<{ items: Complaint[] }>(`/aftersales/complaints${qs}`)
}

export function createComplaint(body: Partial<Complaint> & { title: string }) {
  return apiFetch<Complaint>('/aftersales/complaints', { method: 'POST', body: JSON.stringify(body) })
}

export function setComplaintStatus(id: number, status: string) {
  return apiFetch<Complaint>(`/aftersales/complaints/${id}/status`, {
    method: 'POST',
    body: JSON.stringify({ status }),
  })
}

export function fetchSalesReturns() {
  return apiFetch<{ items: SalesReturn[] }>('/aftersales/returns')
}

export function createReturnFromIssue(issueId: number) {
  return apiFetch<SalesReturn>(`/aftersales/returns/from-issue/${issueId}`, { method: 'POST' })
}

export function createReturnFromDelivery(deliveryId: number) {
  return apiFetch<SalesReturn>(`/aftersales/returns/from-delivery/${deliveryId}`, { method: 'POST' })
}

export function confirmSalesReturn(id: number) {
  return apiFetch<SalesReturn>(`/aftersales/returns/${id}/confirm`, { method: 'POST' })
}

export function reissueReturn(id: number) {
  return apiFetch<SalesReturn>(`/aftersales/returns/${id}/reissue`, { method: 'POST' })
}

export function replenishReturn(id: number) {
  return apiFetch<SalesReturn>(`/aftersales/returns/${id}/replenish`, { method: 'POST' })
}

export function fetchSampleLoans() {
  return apiFetch<{ items: SampleLoan[] }>('/aftersales/sample-loans')
}

export function returnSampleLoan(id: number, restock = true) {
  return apiFetch<SampleLoan>(`/aftersales/sample-loans/${id}/return`, {
    method: 'POST',
    body: JSON.stringify({ restock }),
  })
}

export function convertSampleLoan(id: number, unit_price = 0) {
  return apiFetch<{ loan: SampleLoan; sales_order: { so_no: string; id: number } }>(
    `/aftersales/sample-loans/${id}/convert`,
    { method: 'POST', body: JSON.stringify({ unit_price }) },
  )
}
