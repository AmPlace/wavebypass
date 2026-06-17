export const ADAPTER_SCHEMES = Object.freeze([
  'youtube',
  'migu', 'hnntv', 'nmtv', 'gzstv', 'sxbc', 'xjtv', 'jstv', 'sdtv', 'sdly',
  'douyin', 'douyu', 'huya', 'hbtv', 'hntv', 'tvb', 'nowtv',
  'redbook', 'tiktok', 'kuaishou', 'bilibili', 'yy', 'bigo', 'blued', 'soop',
  'netease', 'pandatv', 'maoer', 'look', 'flextv', 'popkontv', 'twitcasting',
  'baidu', 'weibo', 'kugou', 'twitch', 'huajiao', 'showroom', 'inke', 'acfun',
  'haixiu', 'liveme', 'zhihu', 'chzzk', 'live17', 'langlive', 'changliao',
  'jd', 'faceit', 'lianjie', 'sixroom', 'lehai', 'huamao', 'shopee', 'laixiu', 'picarto',
  'fjtv', 'ptbtv', 'nd0593tv', 'qukan', 'woniu',
  'adapter',
])

export function isAdapterSchemeUrl(url) {
  const value = String(url || '').trim().toLowerCase()
  return ADAPTER_SCHEMES.some((scheme) => value.startsWith(`${scheme}://`))
}

export function adapterNameFromUrl(url) {
  const value = String(url || '').trim().toLowerCase()
  for (const scheme of ADAPTER_SCHEMES) {
    if (scheme === 'adapter') continue
    if (value.startsWith(`${scheme}://`)) return scheme
  }
  try {
    const parsed = new URL(url)
    return parsed.protocol === 'adapter:' ? parsed.hostname.toLowerCase() : ''
  } catch {
    return ''
  }
}

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

export function isDynamicAdapterProxyPlaylistEntry(entry, isChannelProxyPlaylistUrl) {
  return Boolean(
    isProxyTransport(entry)
    && typeof isChannelProxyPlaylistUrl === 'function'
    && isChannelProxyPlaylistUrl(entry?.url || '')
    && (entry?.adapter || isAdapterSchemeUrl(entry?.original_url || entry?.url || '')),
  )
}
