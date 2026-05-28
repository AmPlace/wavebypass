import { API_BASE } from '../apiBase'

async function request(url, options = {}) {
  const ctrl = new AbortController()
  const timer = setTimeout(() => ctrl.abort(), options.timeout || 20_000)
  try {
    const res = await fetch(`${API_BASE}${url}`, { signal: ctrl.signal, ...options })
    clearTimeout(timer)
    if (!res.ok) {
      const err = await res.json().catch(() => ({}))
      throw new Error(err.detail || `HTTP ${res.status}`)
    }
    return res
  } catch (e) {
    clearTimeout(timer)
    throw e
  }
}

export async function fetchMarketSummary() {
  const res = await request('/api/market')
  return res.json()
}

export async function refreshMarket(marketUrl = '', { allowPrivate = false } = {}) {
  const res = await request('/api/market/refresh', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      ...(marketUrl ? { market_url: marketUrl } : {}),
      allow_private: allowPrivate,
    }),
    timeout: 30_000,
  })
  return res.json()
}

export async function fetchMarketPackages(filters = {}) {
  const params = new URLSearchParams()
  for (const [key, value] of Object.entries(filters)) {
    if (value === undefined || value === null || value === '') continue
    params.set(key, String(value))
  }
  const qs = params.toString()
  const res = await request(`/api/market/packages${qs ? `?${qs}` : ''}`)
  return res.json()
}

export async function fetchMarketPackage(id) {
  const res = await request(`/api/market/packages/${encodeURIComponent(id)}`)
  return res.json()
}

export async function previewMarketPackage(id) {
  const res = await request(`/api/market/packages/${encodeURIComponent(id)}/preview`, {
    method: 'POST',
    timeout: 45_000,
  })
  return res.json()
}

export async function importMarketPackage(id, previewId = '') {
  const res = await request(`/api/market/packages/${encodeURIComponent(id)}/import`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ preview_id: previewId, prefer_cached_preview: true }),
    timeout: 45_000,
  })
  return res.json()
}
