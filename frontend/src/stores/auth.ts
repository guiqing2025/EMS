import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import type { AuthUser, LoginResponse } from '@/types/auth'
import { apiFetch } from '@/api/http'

const TOKEN_KEY = 'ems_auth_token'
const USER_KEY = 'ems_current_user'
/** 菜单点击不每次打满 /auth/status；扫码不走路由守卫，不受影响 */
const STATUS_TTL_MS = 60_000

export const useAuthStore = defineStore('auth', () => {
  const token = ref(localStorage.getItem(TOKEN_KEY) || '')
  const user = ref<AuthUser | null>(loadUser())

  let lastStatusAt = 0
  let lastStatusOk = false
  let inflight: Promise<boolean> | null = null

  function loadUser(): AuthUser | null {
    try {
      const raw = localStorage.getItem(USER_KEY)
      return raw ? JSON.parse(raw) : null
    } catch {
      return null
    }
  }

  const isAuthenticated = computed(() => !!token.value && !!user.value)
  const mustChangePassword = computed(() => !!user.value?.must_change_password)

  function invalidateStatusCache() {
    lastStatusAt = 0
    lastStatusOk = false
    inflight = null
  }

  function setSession(newToken: string, newUser: AuthUser) {
    token.value = newToken
    user.value = newUser
    localStorage.setItem(TOKEN_KEY, newToken)
    localStorage.setItem(USER_KEY, JSON.stringify(newUser))
    lastStatusAt = Date.now()
    lastStatusOk = true
  }

  function clearSession() {
    token.value = ''
    user.value = null
    localStorage.removeItem(TOKEN_KEY)
    localStorage.removeItem(USER_KEY)
    invalidateStatusCache()
  }

  function applyAuthUser(status: Partial<AuthUser>) {
    if (!user.value) return
    user.value = { ...user.value, ...status }
    localStorage.setItem(USER_KEY, JSON.stringify(user.value))
  }

  async function checkStatus(opts?: { force?: boolean }) {
    if (!token.value) return false
    const force = !!opts?.force
    const now = Date.now()
    if (!force && lastStatusOk && user.value && now - lastStatusAt < STATUS_TTL_MS) {
      return true
    }
    if (inflight) return inflight

    inflight = (async () => {
      try {
        const status = await apiFetch<{ authenticated: boolean } & AuthUser>('/auth/status', {
          token: token.value,
          timeoutMs: 8000,
        }).catch(() => null)
        if (!status?.authenticated) {
          clearSession()
          return false
        }
        user.value = {
          username: status.username!,
          role: status.role || 'admin',
          department: status.department,
          display_name: status.display_name,
          must_change_password: status.must_change_password,
        }
        localStorage.setItem(USER_KEY, JSON.stringify(user.value))
        lastStatusAt = Date.now()
        lastStatusOk = true
        return true
      } finally {
        inflight = null
      }
    })()
    return inflight
  }

  async function login(username: string, password: string) {
    const data = await apiFetch<LoginResponse>('/auth/login', {
      method: 'POST',
      body: JSON.stringify({ username, password }),
    })
    setSession(data.token, {
      username: data.username,
      role: data.role,
      department: data.department,
      display_name: data.display_name,
      must_change_password: data.must_change_password,
    })
    return data
  }

  async function changePassword(oldPassword: string, newPassword: string) {
    const data = await apiFetch<LoginResponse>('/auth/change-password', {
      method: 'POST',
      token: token.value,
      body: JSON.stringify({ old_password: oldPassword, new_password: newPassword }),
    })
    setSession(data.token, {
      username: data.username,
      role: data.role,
      department: data.department,
      display_name: data.display_name,
      must_change_password: false,
    })
  }

  function logout() {
    clearSession()
  }

  return {
    token,
    user,
    isAuthenticated,
    mustChangePassword,
    setSession,
    clearSession,
    applyAuthUser,
    checkStatus,
    login,
    changePassword,
    logout,
  }
})
