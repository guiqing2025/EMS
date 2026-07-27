import { apiFetch, ApiError } from '@/api/http'
import type {
  MaterialControl,
  MaterialControlCreateInput,
  MaterialControlImportResult,
  MaterialControlParseResult,
  YonglianEcnImportResult,
  YonglianEcnParseResult,
} from '@/types/materialControl'

export async function fetchMaterialControls(params?: { status?: string; keyword?: string }) {
  const q = new URLSearchParams()
  if (params?.status) q.set('status', params.status)
  if (params?.keyword) q.set('keyword', params.keyword)
  const qs = q.toString()
  return apiFetch<MaterialControl[]>(`/material-controls${qs ? `?${qs}` : ''}`)
}

export async function fetchMaterialControl(id: number) {
  return apiFetch<MaterialControl>(`/material-controls/${id}`)
}

export async function fetchMaterialControlsByPurchase(purchaseNo: string, modelCode?: string) {
  const q = modelCode ? `?model_code=${encodeURIComponent(modelCode)}` : ''
  return apiFetch<MaterialControl[]>(
    `/material-controls/by-purchase/${encodeURIComponent(purchaseNo)}${q}`,
  )
}

export async function createMaterialControl(payload: MaterialControlCreateInput) {
  return apiFetch<MaterialControl>('/material-controls', {
    method: 'POST',
    body: JSON.stringify(payload),
  })
}

export async function updateMaterialControl(id: number, payload: Partial<MaterialControlCreateInput>) {
  return apiFetch<MaterialControl>(`/material-controls/${id}`, {
    method: 'PUT',
    body: JSON.stringify(payload),
  })
}

export async function confirmMaterialControl(id: number) {
  return apiFetch<MaterialControl>(`/material-controls/${id}/confirm`, { method: 'POST' })
}

export async function cancelMaterialControl(id: number, password: string) {
  return apiFetch<MaterialControl>(`/material-controls/${id}/cancel`, {
    method: 'POST',
    body: JSON.stringify({ password }),
  })
}

export async function deleteMaterialControl(id: number, password: string) {
  return apiFetch<{ ok: boolean; control_no: string }>(`/material-controls/${id}/delete`, {
    method: 'POST',
    body: JSON.stringify({ password }),
  })
}

export async function uploadMaterialControlAttachment(id: number, file: File) {
  const token = localStorage.getItem('ems_auth_token') ?? ''
  const fd = new FormData()
  fd.append('file', file)
  const res = await fetch(`/api/material-controls/${id}/attachment`, {
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
  return res.json() as Promise<MaterialControl>
}

export async function parseMaterialControlFile(file: File) {
  const token = localStorage.getItem('ems_auth_token') ?? ''
  const fd = new FormData()
  fd.append('file', file)
  const res = await fetch('/api/material-controls/parse', {
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
  return res.json() as Promise<MaterialControlParseResult>
}

export async function importMaterialControlExcel(file: File) {
  const token = localStorage.getItem('ems_auth_token') ?? ''
  const fd = new FormData()
  fd.append('file', file)
  const res = await fetch('/api/material-controls/import-excel', {
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
  return res.json() as Promise<MaterialControlImportResult>
}

export async function parseYonglianEcnFile(file: File) {
  const token = localStorage.getItem('ems_auth_token') ?? ''
  const fd = new FormData()
  fd.append('file', file)
  const res = await fetch('/api/material-controls/parse-ecn', {
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
  return res.json() as Promise<YonglianEcnParseResult>
}

export async function importYonglianEcnFile(
  file: File,
  opts?: { selectedPurchaseNos?: string[]; controlNo?: string },
) {
  const token = localStorage.getItem('ems_auth_token') ?? ''
  const fd = new FormData()
  fd.append('file', file)
  if (opts?.selectedPurchaseNos?.length) {
    fd.append('selected_purchase_nos', opts.selectedPurchaseNos.join(','))
  }
  if (opts?.controlNo) fd.append('control_no', opts.controlNo)
  const res = await fetch('/api/material-controls/import-ecn', {
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
  return res.json() as Promise<YonglianEcnImportResult>
}

export async function downloadMaterialControlTemplate() {
  const token = localStorage.getItem('ems_auth_token') ?? ''
  const res = await fetch('/api/material-controls/template.xlsx', {
    headers: token ? { 'X-Auth-Token': token } : {},
  })
  if (!res.ok) throw new ApiError('下载模板失败', res.status)
  const blob = await res.blob()
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = 'material_control_template.xlsx'
  a.click()
  URL.revokeObjectURL(url)
}

export function materialControlAttachmentUrl(id: number) {
  return `/api/material-controls/${id}/attachment`
}
