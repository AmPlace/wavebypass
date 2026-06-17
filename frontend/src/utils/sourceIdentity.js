export function isProxyTransport(entry) {
  return entry?.type === 'proxy' || Boolean(entry?.via_proxy)
}

export function sourceTransport(entry) {
  return isProxyTransport(entry) ? 'proxy' : 'direct'
}

export function sourceIdentity(entry) {
  return String(entry?.source_id || '').trim()
}

export function sourceRaceKey(entry) {
  const sourceId = sourceIdentity(entry)
  if (sourceId) return `${sourceId}:${sourceTransport(entry)}`
  const fallback = String(entry?.original_url || entry?.url || '').trim()
  return fallback ? `${fallback}:${sourceTransport(entry)}` : ''
}

export function buildChannelProxyUrl({ apiBase, channelKey, sourceId = '', accessToken = '' }) {
  const key = String(channelKey || '').trim()
  if (!key) return ''
  const params = new URLSearchParams()
  const sid = String(sourceId || '').trim()
  if (sid) params.set('source_id', sid)
  if (accessToken) params.set('access_token', accessToken)
  const suffix = params.toString() ? `?${params.toString()}` : ''
  return `${apiBase}/api/media/channel/${encodeURIComponent(key)}/playlist.m3u8${suffix}`
}

export function extractSourceIdFromUrl(url) {
  try {
    const parsed = new URL(url, 'http://waveflow.local')
    return parsed.searchParams.get('source_id') || ''
  } catch {
    return ''
  }
}
