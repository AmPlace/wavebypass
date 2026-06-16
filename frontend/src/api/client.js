import { API_BASE } from '../apiBase'

export class ApiError extends Error {
  constructor(message, { status = 0, detail = null } = {}) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.detail = detail
  }
}

export async function apiRequest(url, options = {}) {
  const ctrl = new AbortController()
  const timer = setTimeout(() => ctrl.abort(), options.timeout || 20_000)
  const method = (options.method || 'GET').toUpperCase()
  const headers = new Headers(options.headers || {})

  if (!headers.has('Accept')) headers.set('Accept', 'application/json')
  if (!['GET', 'HEAD', 'OPTIONS'].includes(method)) {
    headers.set('X-WaveFlow-Request', '1')
  }

  try {
    const res = await fetch(`${API_BASE}${url}`, {
      ...options,
      method,
      headers,
      signal: ctrl.signal,
      credentials: 'same-origin',
    })
    clearTimeout(timer)
    if (!res.ok) {
      const err = await res.json().catch(() => ({}))
      throw new ApiError(err.detail || `HTTP ${res.status}`, {
        status: res.status,
        detail: err,
      })
    }
    return res
  } catch (error) {
    clearTimeout(timer)
    if (error?.name === 'AbortError') {
      throw new ApiError('请求超时', { status: 0 })
    }
    throw error
  }
}
