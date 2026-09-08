import { apiFetch, ApiError } from './http'
import type { PdaOrderPick } from '@/views/pda/pdaSession'
import { compressImageForUpload } from '@/utils/imageCompress'

export interface DipFaiLine {
  id: number
  session_id: number
  material_code: string
  material_name?: string | null
  spec?: string | null
  position?: string | null
  qty_per: number
  process?: string | null
  mount_type: string
  status: string
  ocr_text?: string | null
  recognized_code?: string | null
  verify_method?: string | null
  has_material_image?: boolean
  verified_by?: string | null
  verified_at?: string | null
  sort_no: number
}

export interface DipFaiSession {
  id: number
  line_key: string
  purchase_no: string
  model_code: string
  customer_name: string
  bom_model_id?: number | null
  status: string
  operator: string
  has_board_image: boolean
  board_image_rel?: string | null
  remark?: string | null
  created_at?: string | null
  completed_at?: string | null
  line_total: number
  line_passed: number
  line_pending: number
  line_failed: number
  lines: DipFaiLine[]
}

export interface DipFaiListPage {
  total: number
  items: Array<{
    id: number
    line_key: string
    purchase_no: string
    model_code: string
    customer_name: string
    status: string
    operator: string
    has_board_image: boolean
    line_total: number
    line_passed: number
    created_at?: string | null
    completed_at?: string | null
  }>
  limit: number
  offset: number
}

export interface DipFaiVerifyResult {
  ok: boolean
  message: string
  expected_code: string
  recognized_code: string
  ocr_text: string
  line: DipFaiLine
  session: DipFaiSession
  /** 手写/反光无法可靠识别时，PDA 弹窗目视确认 */
  needs_confirm?: boolean
  suggest_line_id?: number | null
  suggest_code?: string
  candidates?: Array<{
    line_id: number
    material_code: string
    matched_alias?: string
    score: number
  }>
}

function authHeaders(): Record<string, string> {
  const token = localStorage.getItem('ems_auth_token') ?? ''
  return token ? { 'X-Auth-Token': token } : {}
}

async function uploadForm<T>(path: string, form: FormData, timeoutMs = 90000): Promise<T> {
  const controller = new AbortController()
  const timer = window.setTimeout(() => controller.abort(), timeoutMs)
  let res: Response
  try {
    res = await fetch(`/api${path}`, {
      method: 'POST',
      headers: authHeaders(),
      body: form,
      signal: controller.signal,
    })
  } catch (err) {
    if (err instanceof Error && err.name === 'AbortError') {
      throw new ApiError('上传超时，请重试', 0)
    }
    throw new ApiError('无法连接服务器', 0)
  } finally {
    window.clearTimeout(timer)
  }
  if (!res.ok) {
    let msg = res.statusText
    try {
      const body = await res.json()
      if (typeof body.detail === 'string') msg = body.detail
    } catch {
      /* ignore */
    }
    throw new ApiError(msg || '上传失败', res.status)
  }
  return (await res.json()) as T
}

export function searchPdaOrders(keyword: string, limit = 40) {
  const q = new URLSearchParams()
  if (keyword) q.set('keyword', keyword)
  q.set('limit', String(limit))
  return apiFetch<{ items: PdaOrderPick[]; total: number }>(`/pda/search-orders?${q}`)
}

export function startDipFaiSession(lineKey: string) {
  return apiFetch<DipFaiSession>('/pda/dip-first-article/sessions', {
    method: 'POST',
    body: JSON.stringify({ line_key: lineKey }),
  })
}

export function getDipFaiSession(sessionId: number, via: 'pda' | 'quality' = 'pda') {
  const base = via === 'quality' ? '/quality' : '/pda'
  return apiFetch<DipFaiSession>(`${base}/dip-first-article/sessions/${sessionId}`)
}

export async function verifyDipFaiLine(sessionId: number, lineId: number, file: File) {
  const form = new FormData()
  form.append('file', await compressImageForUpload(file, { maxSide: 1280, quality: 0.72 }))
  return uploadForm<DipFaiVerifyResult>(
    `/pda/dip-first-article/sessions/${sessionId}/lines/${lineId}/verify`,
    form,
  )
}

/** 拍照后自动匹配本单任意 DIP 料号（不强制顺序） */
export async function verifyDipFaiSessionPhoto(sessionId: number, file: File) {
  const form = new FormData()
  form.append('file', await compressImageForUpload(file, { maxSide: 1280, quality: 0.72 }))
  return uploadForm<DipFaiVerifyResult>(`/pda/dip-first-article/sessions/${sessionId}/verify`, form)
}

/** 扫码/输入后自动匹配本单任意 DIP 料号（与拍照同一逻辑） */
export function verifyDipFaiSessionScan(sessionId: number, code: string) {
  return apiFetch<DipFaiVerifyResult>(`/pda/dip-first-article/sessions/${sessionId}/verify-scan`, {
    method: 'POST',
    body: JSON.stringify({ code }),
  })
}

export function manualPassDipFaiLine(sessionId: number, lineId: number, reason: string) {
  return apiFetch<DipFaiVerifyResult>(
    `/pda/dip-first-article/sessions/${sessionId}/lines/${lineId}/manual-pass`,
    {
      method: 'POST',
      body: JSON.stringify({ reason }),
    },
  )
}

export async function uploadDipFaiBoardPhoto(sessionId: number, file: File) {
  const form = new FormData()
  form.append('file', await compressImageForUpload(file, { maxSide: 1600, quality: 0.8 }))
  return uploadForm<DipFaiSession>(`/pda/dip-first-article/sessions/${sessionId}/board-photo`, form)
}

export function completeDipFaiSession(sessionId: number) {
  return apiFetch<DipFaiSession>(`/pda/dip-first-article/sessions/${sessionId}/complete`, {
    method: 'POST',
    body: '{}',
  })
}

export function cancelDipFaiSession(sessionId: number, remark = '') {
  return apiFetch<DipFaiSession>(`/pda/dip-first-article/sessions/${sessionId}/cancel`, {
    method: 'POST',
    body: JSON.stringify({ remark }),
  })
}

export function deleteDipFaiSession(sessionId: number) {
  return apiFetch<{ ok: boolean; deleted_id: number }>(
    `/quality/dip-first-article/sessions/${sessionId}`,
    { method: 'DELETE' },
  )
}

export function listDipFaiSessions(params: {
  keyword?: string
  status?: string
  limit?: number
  offset?: number
} = {}) {
  const q = new URLSearchParams()
  if (params.keyword) q.set('keyword', params.keyword)
  if (params.status) q.set('status', params.status)
  if (params.limit != null) q.set('limit', String(params.limit))
  if (params.offset != null) q.set('offset', String(params.offset))
  const qs = q.toString()
  return apiFetch<DipFaiListPage>(`/quality/dip-first-article/sessions${qs ? `?${qs}` : ''}`)
}

export function dipFaiBoardImageUrl(sessionId: number, via: 'pda' | 'quality' = 'quality') {
  const token = localStorage.getItem('ems_auth_token') ?? ''
  const base = via === 'pda' ? '/api/pda' : '/api/quality'
  return `${base}/dip-first-article/sessions/${sessionId}/board-image?access_token=${encodeURIComponent(token)}`
}

export function dipFaiLineImageUrl(lineId: number) {
  const token = localStorage.getItem('ems_auth_token') ?? ''
  return `/api/quality/dip-first-article/lines/${lineId}/image?access_token=${encodeURIComponent(token)}`
}
