import { API_BASE } from '../apiBase.js'

function inferType(station) {
  const value = `${station?.name || ''} ${station?.group_name || ''}`.toLowerCase()
  if (/(music|音乐|音樂|金曲|经典|經典)/i.test(value)) return 'music'
  if (/(news|新闻|新聞|资讯|資訊|交通)/i.test(value)) return 'news'
  if (/(talk|谈话|談話|生活|都市|城市)/i.test(value)) return 'talk'
  if (/(sport|体育|體育)/i.test(value)) return 'sports'
  return 'other'
}

function mapRadioStation(station) {
  const stationId = String(station?.station_id || '').trim()
  const sources = Array.isArray(station?.sources)
    ? station.sources.filter((source) => source && source.source_id && source.lifecycle_state !== 'expired')
    : []
  if (!stationId || sources.length === 0) return null

  const source = sources[0]
  const safeSources = sources.map((item) => ({
    source_id: String(item.source_id),
    owner_identity: String(item.owner_identity || ''),
    provider_key: String(item.provider_key || ''),
    provider_station_id: String(item.provider_station_id || ''),
    source_discriminator: String(item.source_discriminator || ''),
    source_revision: String(item.source_revision || ''),
    explicit_priority: item.explicit_priority,
    health_status: String(item.health_status || ''),
    lifecycle_state: String(item.lifecycle_state || ''),
    catalog_expires_at: item.catalog_expires_at,
    resolve_expires_at: item.resolve_expires_at,
  }))
  const metadata = station?.metadata && typeof station.metadata === 'object' ? station.metadata : {}
  const name = String(station?.name || station?.provider_station_id || stationId).trim()
  return {
    id: stationId,
    name,
    subtitle: String(metadata.subtitle || station?.frequency || '').trim(),
    logoUrl: String(station?.logo_url || '').trim(),
    logoText: name.slice(0, 1) || '?',
    // New Radio playback is selected by persisted source_id.  It never
    // carries or accepts an upstream URL in the frontend state.
    radioStationId: stationId,
    radioSourceId: String(source.source_id),
    radioSources: safeSources,
    radioDomain: 'radio',
    livePath: true,
    directPlay: false,
    tags: [station?.country, station?.group_name, station?.language, metadata.tag || inferType(station)]
      .map((tag) => String(tag || '').trim())
      .filter(Boolean),
  }
}

export async function fetchRadioStations({ fetchImpl = fetch } = {}) {
  try {
    const controller = new AbortController()
    const timer = setTimeout(() => controller.abort(), 15_000)
    const response = await fetchImpl(`${API_BASE}/api/radio/stations`, { signal: controller.signal })
    clearTimeout(timer)
    if (!response.ok) return null
    const body = await response.json()
    const rows = Array.isArray(body) ? body : body?.stations
    if (!Array.isArray(rows)) return []
    return rows.map(mapRadioStation).filter(Boolean)
  } catch {
    return null
  }
}

export async function fetchRadioProgramme(station, { fetchImpl = fetch } = {}) {
  const stationId = String(station?.radioStationId || '').trim()
  const sourceId = String(station?.radioSourceId || '').trim()
  if (!stationId || !sourceId) return null
  try {
    const controller = new AbortController()
    const timer = setTimeout(() => controller.abort(), 10_000)
    const query = new URLSearchParams({ source_id: sourceId })
    const response = await fetchImpl(
      `${API_BASE}/api/radio/stations/${encodeURIComponent(stationId)}/programme?${query}`,
      { signal: controller.signal },
    )
    clearTimeout(timer)
    if (!response.ok) return null
    return await response.json()
  } catch {
    return null
  }
}

export function mapRadioStationForTest(station) {
  return mapRadioStation(station)
}
