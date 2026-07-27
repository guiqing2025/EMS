import { apiFetch, ApiError } from '@/api/http'

export interface QuoteListItem {
  id: number
  quote_no: string
  customer_name: string
  product_name: string
  product_code: string
  status: string
  unit_price: number
  tooling_total: number
  grand_total: number
  batch_qty: number
  source_filename?: string
  created_by?: string
  updated_at?: string
  created_at?: string
}

export interface QuoteDetail extends QuoteListItem {
  remark?: string
  engineering_fee: number
  rates: Record<string, number>
  bom_lines: Array<Record<string, unknown>>
  cost_lines: Array<{
    id: number
    section: string
    item_key: string
    item_name: string
    qty: number
    points: number
    unit_price: number
    unit: string
    amount: number
    note?: string
    editable: boolean
  }>
}

export async function fetchQuotes(params?: { keyword?: string; status?: string }) {
  const q = new URLSearchParams()
  if (params?.keyword) q.set('keyword', params.keyword)
  if (params?.status) q.set('status', params.status)
  const qs = q.toString()
  return apiFetch<QuoteListItem[]>(`/quotation${qs ? `?${qs}` : ''}`)
}

export async function fetchQuote(id: number) {
  return apiFetch<QuoteDetail>(`/quotation/${id}`)
}

export async function createQuote(payload: {
  customer_name?: string
  product_name?: string
  product_code?: string
  remark?: string
  batch_qty?: number
}) {
  return apiFetch<QuoteDetail>('/quotation', {
    method: 'POST',
    body: JSON.stringify(payload),
  })
}

export async function updateQuote(
  id: number,
  payload: Partial<{
    customer_name: string
    product_name: string
    product_code: string
    remark: string
    batch_qty: number
    engineering_fee: number
  }>,
) {
  return apiFetch<QuoteDetail>(`/quotation/${id}`, {
    method: 'PUT',
    body: JSON.stringify(payload),
  })
}

export async function importQuoteBom(
  id: number,
  file: File,
  opts?: { tangxi?: number; stencil_qty?: number; wave_fixture_qty?: number },
) {
  const token = localStorage.getItem('ems_auth_token') ?? ''
  const fd = new FormData()
  fd.append('file', file)
  const q = new URLSearchParams()
  if (opts?.tangxi != null) q.set('tangxi', String(opts.tangxi))
  if (opts?.stencil_qty != null) q.set('stencil_qty', String(opts.stencil_qty))
  if (opts?.wave_fixture_qty != null) q.set('wave_fixture_qty', String(opts.wave_fixture_qty))
  const qs = q.toString()
  const res = await fetch(`/api/quotation/${id}/import-bom${qs ? `?${qs}` : ''}`, {
    method: 'POST',
    headers: token ? { 'X-Auth-Token': token } : {},
    body: fd,
  })
  if (!res.ok) {
    let msg = res.statusText
    try {
      const body = await res.json()
      if (typeof body.detail === 'string') msg = body.detail
    } catch {
      /* ignore */
    }
    throw new ApiError(msg, res.status)
  }
  return res.json() as Promise<QuoteDetail>
}

export async function patchQuoteCosts(
  id: number,
  lines: Array<{ item_key: string; amount?: number; qty?: number; points?: number; unit_price?: number }>,
) {
  return apiFetch<QuoteDetail>(`/quotation/${id}/cost-lines`, {
    method: 'PUT',
    body: JSON.stringify({ lines }),
  })
}

export async function setQuoteStatus(id: number, status: string) {
  return apiFetch<QuoteDetail>(`/quotation/${id}/status`, {
    method: 'POST',
    body: JSON.stringify({ status }),
  })
}

export async function deleteQuote(id: number) {
  return apiFetch<{ message: string }>(`/quotation/${id}`, { method: 'DELETE' })
}

export async function exportQuoteExcel(id: number) {
  const token = localStorage.getItem('ems_auth_token') ?? ''
  const res = await fetch(`/api/quotation/${id}/export`, {
    headers: token ? { 'X-Auth-Token': token } : {},
  })
  if (!res.ok) throw new Error('导出失败')
  const disposition = res.headers.get('Content-Disposition') || ''
  const match = disposition.match(/filename="?([^"]+)"?/)
  const filename = match ? decodeURIComponent(match[1]) : `quote-${id}.xlsx`
  const blob = await res.blob()
  return { blob, filename }
}
