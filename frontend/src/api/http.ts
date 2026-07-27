export class ApiError extends Error {
  status: number
  constructor(message: string, status: number) {
    super(message)
    this.status = status
  }
}

interface FetchOptions extends RequestInit {
  token?: string
  /** 请求超时（毫秒），默认 20s，避免服务重启时路由守卫一直挂起导致白屏 */
  timeoutMs?: number
}

function networkErrorMessage(err: unknown): string {
  if (!(err instanceof Error)) return '无法连接服务器，请确认后台服务已启动'
  const raw = err.message || ''
  if (
    err.name === 'TypeError' ||
    raw === 'Load failed' ||
    raw === 'Failed to fetch' ||
    raw.includes('NetworkError') ||
    raw.includes('network')
  ) {
    return '无法连接服务器，请确认后台服务已启动'
  }
  return raw || '无法连接服务器，请确认后台服务已启动'
}

export async function apiFetch<T>(path: string, options: FetchOptions = {}): Promise<T> {
  const { token: optToken, timeoutMs = 20000, signal: userSignal, ...init } = options
  const token = optToken ?? localStorage.getItem('ems_auth_token') ?? ''
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    ...(init.headers as Record<string, string> | undefined),
  }
  if (token) headers['X-Auth-Token'] = token

  const controller = new AbortController()
  const timer = window.setTimeout(() => controller.abort(), timeoutMs)
  if (userSignal) {
    if (userSignal.aborted) controller.abort()
    else userSignal.addEventListener('abort', () => controller.abort(), { once: true })
  }

  let res: Response
  try {
    res = await fetch(`/api${path}`, { ...init, headers, signal: controller.signal })
  } catch (err) {
    if (err instanceof DOMException && err.name === 'AbortError') {
      throw new ApiError('请求超时，请刷新页面或确认后台服务已启动', 0)
    }
    if (err instanceof Error && err.name === 'AbortError') {
      throw new ApiError('请求超时，请刷新页面或确认后台服务已启动', 0)
    }
    throw new ApiError(networkErrorMessage(err), 0)
  } finally {
    window.clearTimeout(timer)
  }
  if (res.status === 401 && !path.startsWith('/auth/')) {
    localStorage.removeItem('ems_auth_token')
    localStorage.removeItem('ems_current_user')
    if (!window.location.pathname.startsWith('/login')) {
      window.location.href = `/login?redirect=${encodeURIComponent(window.location.pathname)}`
    }
  }
  if (!res.ok) {
    let msg = res.statusText
    try {
      const body = await res.json()
      const detail = body.detail ?? body.message
      if (typeof detail === 'string') {
        msg = detail
      } else if (Array.isArray(detail)) {
        msg = detail.map((d: { msg?: string; loc?: unknown[] }) => {
          const field = Array.isArray(d.loc) ? d.loc.filter((x) => typeof x === 'string').pop() : ''
          return field ? `${field}: ${d.msg || ''}` : d.msg || ''
        }).filter(Boolean).join('；') || msg
      } else if (detail && typeof detail === 'object') {
        msg = JSON.stringify(detail)
      }
    } catch {
      const text = await res.text().catch(() => '')
      if (text) msg = text
    }
    throw new ApiError(msg, res.status)
  }
  if (res.status === 204) return undefined as T
  return res.json() as Promise<T>
}
