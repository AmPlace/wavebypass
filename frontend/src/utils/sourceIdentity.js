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

// 真正禁止用户尝试播放的 probe 状态集合。
// 注意：not_live 不在其中——它只是上次测速时未开播的旧结果，不代表当前不能播。
// 不同 schema：新版字符串 probe_status；旧版数字 is_working===0。
const BLOCKED_PROBE_STATUSES = Object.freeze(['offline', 'error', 'timeout'])

function isUrlEntryBlocked(u) {
  const status = String(u?.probe_status || '').toLowerCase()
  if (status) return BLOCKED_PROBE_STATUSES.includes(status)
  return Number(u?.is_working) === 0
}

function isUrlEntryNotLive(u) {
  return String(u?.probe_status || '').toLowerCase() === 'not_live'
}

// 频道是否所有 source 都属于"明确不可用"集合（offline/error/timeout 或旧 is_working===0）。
// 这是首页与 FullPlayer 频道列表共享的唯一事实：true 才禁止点击。
export function isChannelAllUrlsBlocked(channel) {
  const urls = channel?.urls
  if (!Array.isArray(urls) || urls.length === 0) return false
  return urls.every(isUrlEntryBlocked)
}

// 频道是否所有 source 都是 not_live。仅用于显示提示文案，不用于禁止点击。
export function isChannelAllNotLive(channel) {
  const urls = channel?.urls
  if (!Array.isArray(urls) || urls.length === 0) return false
  return urls.every(isUrlEntryNotLive)
}
