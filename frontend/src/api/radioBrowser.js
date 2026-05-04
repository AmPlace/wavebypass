// src/api/radioBrowser.js

// Radio Browser 官方聚合域名，自动分配到最快节点，不要硬编码单节点
const RB_DIRECT_BASE = 'https://all.api.radio-browser.info/json'

// 支持的国家列表，新增国家只需在这里加一行
// code 是 ISO 3166-1 alpha-2 国家代码，label 是中文显示名
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

// ========== 首页要自动拉取的地区列表 ==========
// 前端不再拉取 RB 电台（隐藏 RB 卡片），RB 数据由后端启动时自动预热，仅用于回退匹配。
// 如需在前端显示某地区的 RB 电台，把国家代码加回这里即可。
export const RB_FETCH_COUNTRIES = []

// Radio Browser 常见标签 → 本项目统一类型标签
// 只要原始 tag 包含左边关键词，就归类为右边的类型
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

// 已知地区标签（不会被当作类型标签处理）
const REGION_TAGS = new Set(['TW', 'CN', 'JP', 'US', 'KR', 'GB', 'DE', 'FR', 'HK', 'MO'])

// 缓存已获取的电台列表，避免重复请求
const cache = {}

// 解析 Radio Browser 返回的 tags 字符串为本项目 tags 数组
// 输入："music,news,pop" → 输出：['music', 'news']
// 会自动去重、过滤空值、归类未知标签
export function parseRbTags(tagsStr, countryCode) {
  if (!tagsStr && !countryCode) return []

  // 地区标签：直接用国家代码
  const tags = countryCode ? [countryCode] : []

  // 解析类型标签
  if (tagsStr) {
    const seen = new Set(tags)
    for (const raw of tagsStr.split(',')) {
      const tag = raw.trim().toLowerCase()
      if (!tag || REGION_TAGS.has(tag.toUpperCase())) continue

      // 查映射表，匹配到就用统一标签，否则归为 other
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

// 按国家代码获取电台列表，返回已映射为本项目格式的 station 数组
// 请求链路：前端缓存 → 后端反代（带 6 小时缓存）→ 直连 Radio Browser 回退
export async function fetchStationsByCountry(countryCode) {
  if (cache[countryCode]) return cache[countryCode]

  // 先尝试后端反代（大陆用户可达，且后端有 6 小时缓存，命中后秒回）
  let data = null
  try {
    const ctrl = new AbortController()
    const timer = setTimeout(() => ctrl.abort(), 10_000)
    const res = await fetch(`/api/radio-browser/stations/${countryCode}`, { signal: ctrl.signal })
    clearTimeout(timer)
    if (res.ok) data = await res.json()
  } catch {}

  // 后端失败则直连 Radio Browser 回退（海外用户 / 后端未部署时）
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

// 单条 Radio Browser 电台 → 本项目 station 格式
function mapToStation(item, countryCode) {
  // url_resolved 是最终播放直链，必须存在
  if (!item.url_resolved) return null

  return {
    // stationuuid 加 rb_ 前缀，避免和手动配置的电台 id 冲突
    id: `rb_${item.stationuuid}`,
    name: item.name || '未知电台',
    logoUrl: item.favicon || '',
    logoText: (item.name || '?')[0],
    // 核心字段：直链地址，AudioEngine 自动识别并走直连→中转回退
    directUrl: item.url_resolved,
    // 解析 tags 字符串为数组，同时包含地区和类型
    tags: parseRbTags(item.tags, countryCode),
  }
}
