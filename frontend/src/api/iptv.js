import { API_BASE } from '../apiBase'

async function request(url, options = {}) {
  const ctrl = new AbortController()
  const timer = setTimeout(() => ctrl.abort(), options.timeout || 15_000)
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

export async function fetchSubscriptions() {
  const res = await request('/api/iptv/subscriptions')
  return res.json()
}

export async function addSubscription(url, title = '', custom_ua = '', force_proxy = false) {
  const res = await request('/api/iptv/subscriptions', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ url, title, custom_ua, force_proxy }),
  })
  return res.json()
}

export async function deleteSubscription(id) {
  await request(`/api/iptv/subscriptions/${id}`, { method: 'DELETE' })
}

export async function refreshSubscription(id) {
  const res = await request(`/api/iptv/subscriptions/${id}/refresh`, { method: 'POST' })
  return res.json()
}

export async function refreshAllSubscriptions() {
  const res = await request('/api/iptv/subscriptions/refresh-all', {
    method: 'POST',
    timeout: 120_000,
  })
  return res.json()
}

export async function fetchChannels(subId, { group = '', search = '' } = {}) {
  const params = new URLSearchParams()
  if (group) params.set('group', group)
  if (search) params.set('search', search)
  const qs = params.toString()
  const res = await request(`/api/iptv/subscriptions/${subId}/channels${qs ? '?' + qs : ''}`)
  return res.json()
}

export async function testAllChannels(subId) {
  const res = await request(`/api/iptv/subscriptions/${subId}/test-all`, { method: 'POST' })
  return res.json()
}

export async function cancelTest() {
  const res = await request('/api/iptv/test-cancel', { method: 'POST' })
  return res.json()
}

export async function fetchTestStatus(subId) {
  const res = await request(`/api/iptv/subscriptions/${subId}/test-status`)
  return res.json()
}

// ── 聚合频道（前端用）──

export async function fetchAggregatedChannels({ group = '', search = '' } = {}) {
  const params = new URLSearchParams()
  if (group) params.set('group', group)
  if (search) params.set('search', search)
  const qs = params.toString()
  const res = await request(`/api/iptv/channels${qs ? '?' + qs : ''}`)
  return res.json()
}

export async function testAllGlobal() {
  const res = await request('/api/iptv/test-all', { method: 'POST' })
  return res.json()
}

export async function fetchGlobalTestStatus() {
  const res = await request('/api/iptv/test-status')
  return res.json()
}

// ── adapter 直播间封面/头像（B站 / 斗鱼 / 虎牙 / 快手；其他 adapter 后端会返回空对象）──
export async function fetchAdapterCover(targetUrl) {
  const params = new URLSearchParams({ target_url: targetUrl })
  const res = await request(`/api/iptv/adapter/cover?${params.toString()}`, { timeout: 8_000 })
  return res.json()
}
