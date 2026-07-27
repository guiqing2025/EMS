export interface AuthUser {
  username: string
  role: string
  department?: string | null
  display_name?: string | null
  must_change_password?: boolean
}

export interface AuthStatus {
  authenticated: boolean
  username?: string
  role?: string
  department?: string | null
  display_name?: string | null
  must_change_password?: boolean
}

export interface LoginResponse extends AuthUser {
  token: string
  message?: string
  must_change_password?: boolean
}
