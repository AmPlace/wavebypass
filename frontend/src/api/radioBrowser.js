const RB_DIRECT_BASE = 'https://all.api.radio-browser.info/json'

export const RB_COUNTRIES = [
  { code: 'TW', label: '台湾' },
  { code: 'CN', label: '中国' },
  { code: 'JP', label: '日本' },
  { code: 'US', label: '美国' },
  { code: 'KR', label: '韩国' },
  { code: 'GB', label: '英国' },
  { code: 'DE', label: '德国' },
  { code: 'FR', label: '法国' },
]

export const RB_FETCH_COUNTRIES = []

const TAG_TYPE_MAP = {
  music: 'music',
  pop: 'music',
  rock: 'music',
  jazz: 'music',
  classical: 'music',
  electronic: 'music',
  hiphop: 'music',
  country: 'music',
  rnb: 'music',
  folk: 'music',
  metal: 'music',
  dance: 'music',
  news: 'news',
  talk: 'talk',
  sports: 'sports',
  sport: 'sports',
  religious: 'religious',
  christian: 'religious',
  islamic: 'religious',
  buddhist: 'religious',
}

const REGION_TAGS = new Set(['TW', 'CN', 'JP', 'US', 'KR', 'GB', 'DE', 'FR', 'HK', 'MO'])

const cache = {}

export function parseRbTags(tagsStr, countryCode) {
  if (!tagsStr && !countryCode) return []


  const tags = countryCode ? [countryCode] : []

  if (tagsStr) {
    const seen = new Set(tags)
    for (const raw of tagsStr.split(',')) {
      const tag = raw.trim().toLowerCase()
      if (!tag || REGION_TAGS.has(tag.toUpperCase())) continue

      const mapped = TAG_TYPE_MAP[tag]
      const finalTag = mapped || 'other'
      if (!seen.has(finalTag)) {
        tags.push(finalTag)
        seen.add(finalTag)
      }
    }
  }

  return tags
}

export async function fetchStationsByCountry(countryCode) {
  if (cache[countryCode]) return cache[countryCode]

  // 先尝试后端反代(RB API被墙)
  let data = null
  try {
    const ctrl = new AbortController()
    const timer = setTimeout(() => ctrl.abort(), 10_000)
    const res = await fetch(`/api/radio-browser/stations/${countryCode}`, { signal: ctrl.signal })
    clearTimeout(timer)
    if (res.ok) data = await res.json()
  } catch {}

  if (!data) {
    try {
      const res = await fetch(`${RB_DIRECT_BASE}/stations/bycountrycodeexact/${countryCode}?order=votes&reverse=true`)
      if (res.ok) data = await res.json()
    } catch {}
  }

  if (!data) return []

  const stations = data.map((item) => mapToStation(item, countryCode)).filter(Boolean)
  cache[countryCode] = stations
  return stations
}

function mapToStation(item, countryCode) {
  if (!item.url_resolved) return null

  return {
    id: `rb_${item.stationuuid}`,
    name: item.name || '未知电台',
    logoUrl: item.favicon || '',
    logoText: (item.name || '?')[0],
    directUrl: item.url_resolved,
    tags: parseRbTags(item.tags, countryCode),
  }
}
