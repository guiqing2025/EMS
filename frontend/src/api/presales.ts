import { apiFetch } from './http'

export type InquiryLine = {
  id?: number
  material_code: string
  material_name: string
  spec?: string
  qty: number
  unit?: string
  remark?: string
}

export type Inquiry = {
  id: number
  inquiry_no: string
  customer_id?: number | null
  customer_name: string
  contact?: string
  phone?: string
  title: string
  status: string
  remark?: string
  lines?: InquiryLine[]
  created_at?: string
}

export type SampleDesign = {
  id: number
  design_no: string
  inquiry_id?: number | null
  quote_id?: number | null
  customer_name: string
  product_code: string
  product_name: string
  status: string
  owner?: string
  remark?: string
}

export type SampleOrder = {
  id: number
  sample_no: string
  customer_name: string
  product_code: string
  product_name: string
  qty: number
  status: string
  quote_id?: number | null
}

export type SalesOrder = {
  id: number
  so_no: string
  customer_name: string
  status: string
  quote_id?: number | null
  lines?: Array<{ material_code: string; material_name: string; qty: number; unit_price: number; amount: number }>
}

export type SampleMail = {
  id: number
  mail_no: string
  customer_name: string
  product_name: string
  channel: string
  tracking_no: string
  link_url: string
  status: string
  sent_at?: string
  remark?: string
}

export type SampleLoan = {
  id: number
  loan_no: string
  customer_name: string
  product_code: string
  product_name: string
  qty: number
  status: string
  lent_at?: string
  expect_return_at?: string
  returned_at?: string
  remark?: string
}

export function fetchInquiries(params: { q?: string; status?: string } = {}) {
  const qs = new URLSearchParams()
  if (params.q) qs.set('q', params.q)
  if (params.status) qs.set('status', params.status)
  const s = qs.toString()
  return apiFetch<{ items: Inquiry[] }>(`/presales/inquiries${s ? `?${s}` : ''}`)
}

export function fetchInquiry(id: number) {
  return apiFetch<Inquiry>(`/presales/inquiries/${id}`)
}

export function saveInquiry(body: Partial<Inquiry> & { lines?: InquiryLine[] }, id?: number) {
  if (id) return apiFetch<Inquiry>(`/presales/inquiries/${id}`, { method: 'PUT', body: JSON.stringify(body) })
  return apiFetch<Inquiry>('/presales/inquiries', { method: 'POST', body: JSON.stringify(body) })
}

export function inquiryToQuote(id: number) {
  return apiFetch<{ quote_id: number; quote_no: string }>(`/presales/inquiries/${id}/to-quote`, { method: 'POST' })
}

export function fetchDesigns(params: { q?: string; status?: string } = {}) {
  const qs = new URLSearchParams()
  if (params.q) qs.set('q', params.q)
  if (params.status) qs.set('status', params.status)
  const s = qs.toString()
  return apiFetch<{ items: SampleDesign[] }>(`/presales/designs${s ? `?${s}` : ''}`)
}

export function saveDesign(body: Partial<SampleDesign>, id?: number) {
  if (id) return apiFetch<SampleDesign>(`/presales/designs/${id}`, { method: 'PUT', body: JSON.stringify(body) })
  return apiFetch<SampleDesign>('/presales/designs', { method: 'POST', body: JSON.stringify(body) })
}

export function quoteToDesign(qid: number) {
  return apiFetch<SampleDesign>(`/presales/quotes/${qid}/to-design`, { method: 'POST' })
}

export function quoteToSampleOrder(qid: number) {
  return apiFetch<SampleOrder>(`/presales/quotes/${qid}/to-sample-order`, { method: 'POST' })
}

export function quoteToSalesOrder(qid: number) {
  return apiFetch<SalesOrder>(`/presales/quotes/${qid}/to-sales-order`, { method: 'POST' })
}

export function patchQuotePresales(
  qid: number,
  body: { supplier_name?: string; supplier_cost?: number; sell_price?: number; quote_kind?: string; inquiry_id?: number },
) {
  return apiFetch(`/presales/quotes/${qid}/presales-fields`, { method: 'PATCH', body: JSON.stringify(body) })
}

export function fetchSampleOrders(params: { q?: string; status?: string } = {}) {
  const qs = new URLSearchParams()
  if (params.q) qs.set('q', params.q)
  if (params.status) qs.set('status', params.status)
  const s = qs.toString()
  return apiFetch<{ items: SampleOrder[] }>(`/presales/sample-orders${s ? `?${s}` : ''}`)
}

export function fetchSalesOrders(params: { q?: string; status?: string } = {}) {
  const qs = new URLSearchParams()
  if (params.q) qs.set('q', params.q)
  if (params.status) qs.set('status', params.status)
  const s = qs.toString()
  return apiFetch<{ items: SalesOrder[] }>(`/presales/sales-orders${s ? `?${s}` : ''}`)
}

export function fetchSampleMails(params: { q?: string; status?: string } = {}) {
  const qs = new URLSearchParams()
  if (params.q) qs.set('q', params.q)
  if (params.status) qs.set('status', params.status)
  const s = qs.toString()
  return apiFetch<{ items: SampleMail[] }>(`/presales/sample-mails${s ? `?${s}` : ''}`)
}

export function saveSampleMail(body: Partial<SampleMail>, id?: number) {
  if (id) return apiFetch<SampleMail>(`/presales/sample-mails/${id}`, { method: 'PUT', body: JSON.stringify(body) })
  return apiFetch<SampleMail>('/presales/sample-mails', { method: 'POST', body: JSON.stringify(body) })
}

export function fetchSampleLoans(params: { q?: string; status?: string } = {}) {
  const qs = new URLSearchParams()
  if (params.q) qs.set('q', params.q)
  if (params.status) qs.set('status', params.status)
  const s = qs.toString()
  return apiFetch<{ items: SampleLoan[] }>(`/presales/sample-loans${s ? `?${s}` : ''}`)
}

export function saveSampleLoan(body: Partial<SampleLoan>, id?: number) {
  if (id) return apiFetch<SampleLoan>(`/presales/sample-loans/${id}`, { method: 'PUT', body: JSON.stringify(body) })
  return apiFetch<SampleLoan>('/presales/sample-loans', { method: 'POST', body: JSON.stringify(body) })
}
