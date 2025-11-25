import { api } from './apiClient'

export interface User {
  email: string
  username?: string
  full_name?: string
  id?: string
}

export type AuthResponse = { ok: boolean; error?: string }

export type LoginSuccess = { access_token: string; token_type: string }
export type RegisterSuccess = User
export type ErrorResponse = { detail?: string | { msg: string }[]; error?: string }

function isErrorResponse(d: unknown): d is ErrorResponse {
  return !!d && typeof d === 'object' && ('detail' in (d as any) || 'error' in (d as any))
}

export type LoginResult = {
  ok: boolean
  token?: string
  user?: User | null
  error?: string
}

export async function login(email: string, password: string): Promise<LoginResult> {
  // fastapi-users /auth/jwt/login expects form data (username, password)
  const formData = new URLSearchParams()
  formData.append('username', email)
  formData.append('password', password)

  const res = await api<LoginSuccess | ErrorResponse>('/auth/jwt/login', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/x-www-form-urlencoded',
    },
    body: formData.toString(),
  })

  if (res.ok && res.data && 'access_token' in res.data) {
    // After login, we need to fetch the user details
    const token = res.data.access_token
    const userRes = await fetchMeWithToken(token)
    if (userRes.ok && userRes.user) {
      return { ok: true, token, user: userRes.user }
    }
    return { ok: true, token, user: null }
  }

  const error = getErrorMessage(res.data, res.status)
  return { ok: false, error }
}

export async function register(
  email: string,
  password: string,
  username?: string
): Promise<LoginResult> {
  // fastapi-users /auth/register
  const res = await api<RegisterSuccess | ErrorResponse>('/auth/register', {
    method: 'POST',
    json: {
      email,
      password,
      is_active: true,
      is_superuser: false,
      is_verified: false,
      full_name: username,
    },
  })

  if (res.ok && res.data && 'id' in res.data) {
    // Registration successful, now auto-login
    return login(email, password)
  }

  const error = getErrorMessage(res.data, res.status)
  return { ok: false, error }
}

export async function logout(token: string): Promise<void> {
  await api('/auth/jwt/logout', {
    method: 'POST',
    headers: {
      Authorization: `Bearer ${token}`,
    },
  })
}

type MeResponse = User

async function fetchMeWithToken(token: string): Promise<{ ok: boolean; user?: User; error?: string }> {
  const res = await api<MeResponse | ErrorResponse>('/users/me', {
    headers: {
      Authorization: `Bearer ${token}`,
    },
  })
  if (res.ok && res.data && 'email' in res.data) {
    return { ok: true, user: res.data as User }
  }
  const error = getErrorMessage(res.data, res.status)
  return { ok: false, error }
}

export async function fetchMe(): Promise<{ ok: boolean; user?: User; error?: string }> {
  // This function assumes the token is already managed by the caller (e.g. via localStorage or interceptors)
  // But for consistency with the previous implementation which seemed to rely on the token being passed or stored
  // We'll use the token from localStorage if available, similar to how useAuth works
  const token = localStorage.getItem('token')
  if (!token) return { ok: false, error: 'No token' }
  return fetchMeWithToken(token)
}

function getErrorMessage(data: any, status: number): string {
  if (isErrorResponse(data)) {
    if (typeof data.detail === 'string') return data.detail
    if (Array.isArray(data.detail)) return data.detail.map((e) => e.msg).join(', ')
    return data.error || `Request failed (${status})`
  }
  return `Request failed (${status})`
}
