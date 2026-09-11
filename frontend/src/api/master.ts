import { ApiError, apiFetch } from './http'

export type CertKind = 'business' | 'org' | 'tax'

export type Partner = {
  id: number
  code: string
  name: string
  short_name?: string
  contact?: string
  phone?: string
  address?: string
  tax_no?: string
  remark?: string
  is_active: boolean
  cert_business?: string
  cert_org?: string
  cert_tax?: string
  cert_business_url?: string
  cert_org_url?: string
  cert_tax_url?: string
}

export type Warehouse = {
  id: number
  code: string
  name: string
  wh_type: string
  remark?: string
  is_active: boolean
  sort_no: number
}

export type StockProduct = {
  id: number
  material_code: string
  material_name: string
  spec?: string
  unit?: string
  category?: string
  can_stock: boolean
  safety_qty: number
  remark?: string
  is_active: boolean
}

export type PriceItem = {
  id: number
  price_type: string
  customer_id?: number | null
  material_code: string
  material_name?: string
  unit_price: number
  currency?: string
  effective_from?: string
  effective_to?: string
  remark?: string
  is_active: boolean
}

export type DocNumberRule = {
  doc_type: string
  prefix: string
  name: string
  date_fmt: string
  seq_width: number
  last_date: string
  last_seq: number
}

export function bootstrapMaster() {
  return apiFetch<{ ok: boolean; seeded: Record<string, number>; message: string }>('/master/bootstrap')
}

export function fetchCustomers(params: { q?: string; active_only?: boolean } = {}) {
  const qs = new URLSearchParams()
  if (params.q) qs.set('q', params.q)
  if (params.active_only === false) qs.set('active_only', 'false')
  const s = qs.toString()
  return apiFetch<{ total: number; items: Partner[] }>(`/master/customers${s ? `?${s}` : ''}`)
}

export function fetchCustomer(id: number) {
  return apiFetch<Partner>(`/master/customers/${id}`)
}

export function saveCustomer(body: Omit<Partner, 'id'> & { id?: number }) {
  const payload = {
    code: body.code,
    name: body.name,
    short_name: body.short_name || '',
    contact: body.contact || '',
    phone: body.phone || '',
    address: body.address || '',
    tax_no: body.tax_no || '',
    remark: body.remark || '',
    is_active: body.is_active,
  }
  if (body.id) {
    return apiFetch<Partner>(`/master/customers/${body.id}`, { method: 'PUT', body: JSON.stringify(payload) })
  }
  return apiFetch<Partner>('/master/customers', { method: 'POST', body: JSON.stringify(payload) })
}

export function deleteCustomer(id: number) {
  return apiFetch<{ ok: boolean }>(`/master/customers/${id}`, { method: 'DELETE' })
}

export async function uploadCustomerCert(id: number, kind: CertKind, file: File) {
  const token = localStorage.getItem('ems_auth_token') ?? ''
  const fd = new FormData()
  fd.append('file', file)
  const res = await fetch(`/api/master/customers/${id}/certs/${kind}`, {
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
  return res.json() as Promise<Partner>
}

export function deleteCustomerCert(id: number, kind: CertKind) {
  return apiFetch<Partner>(`/master/customers/${id}/certs/${kind}`, { method: 'DELETE' })
}

export function fetchSuppliers(params: { q?: string; active_only?: boolean } = {}) {
  const qs = new URLSearchParams()
  if (params.q) qs.set('q', params.q)
  if (params.active_only === false) qs.set('active_only', 'false')
  const s = qs.toString()
  return apiFetch<{ total: number; items: Partner[] }>(`/master/suppliers${s ? `?${s}` : ''}`)
}

export function saveSupplier(body: Omit<Partner, 'id'> & { id?: number }) {
  if (body.id) {
    const { id, ...rest } = body
    return apiFetch<Partner>(`/master/suppliers/${id}`, { method: 'PUT', body: JSON.stringify(rest) })
  }
  return apiFetch<Partner>('/master/suppliers', { method: 'POST', body: JSON.stringify(body) })
}

export function deleteSupplier(id: number) {
  return apiFetch<{ ok: boolean }>(`/master/suppliers/${id}`, { method: 'DELETE' })
}

export function fetchWarehouses(activeOnly = true) {
  return apiFetch<{ total: number; items: Warehouse[] }>(
    `/master/warehouses?active_only=${activeOnly ? 'true' : 'false'}`,
  )
}

export function saveWarehouse(body: Omit<Warehouse, 'id'> & { id?: number }) {
  if (body.id) {
    const { id, ...rest } = body
    return apiFetch<Warehouse>(`/master/warehouses/${id}`, { method: 'PUT', body: JSON.stringify(rest) })
  }
  return apiFetch<Warehouse>('/master/warehouses', { method: 'POST', body: JSON.stringify(body) })
}

export function fetchStockProducts(params: { q?: string; active_only?: boolean } = {}) {
  const qs = new URLSearchParams()
  if (params.q) qs.set('q', params.q)
  if (params.active_only === false) qs.set('active_only', 'false')
  const s = qs.toString()
  return apiFetch<{ total: number; items: StockProduct[] }>(`/master/stock-products${s ? `?${s}` : ''}`)
}

export function saveStockProduct(body: Omit<StockProduct, 'id'> & { id?: number }) {
  if (body.id) {
    const { id, ...rest } = body
    return apiFetch<StockProduct>(`/master/stock-products/${id}`, { method: 'PUT', body: JSON.stringify(rest) })
  }
  return apiFetch<StockProduct>('/master/stock-products', { method: 'POST', body: JSON.stringify(body) })
}

export function deleteStockProduct(id: number) {
  return apiFetch<{ ok: boolean }>(`/master/stock-products/${id}`, { method: 'DELETE' })
}

export function fetchPrices(params: { q?: string; price_type?: string; active_only?: boolean } = {}) {
  const qs = new URLSearchParams()
  if (params.q) qs.set('q', params.q)
  if (params.price_type) qs.set('price_type', params.price_type)
  if (params.active_only === false) qs.set('active_only', 'false')
  const s = qs.toString()
  return apiFetch<{ total: number; items: PriceItem[] }>(`/master/prices${s ? `?${s}` : ''}`)
}

export function savePrice(body: Omit<PriceItem, 'id'> & { id?: number }) {
  if (body.id) {
    const { id, ...rest } = body
    return apiFetch<PriceItem>(`/master/prices/${id}`, { method: 'PUT', body: JSON.stringify(rest) })
  }
  return apiFetch<PriceItem>('/master/prices', { method: 'POST', body: JSON.stringify(body) })
}

export function deletePrice(id: number) {
  return apiFetch<{ ok: boolean }>(`/master/prices/${id}`, { method: 'DELETE' })
}

export function fetchDocNumbers() {
  return apiFetch<{ items: DocNumberRule[] }>('/master/doc-numbers')
}

export function previewDocNumber(doc_type: string) {
  return apiFetch<{ doc_type: string; doc_no: string }>('/master/doc-numbers/preview', {
    method: 'POST',
    body: JSON.stringify({ doc_type }),
  })
}
