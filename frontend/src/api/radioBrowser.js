// src/api/radioBrowser.js

// Radio Browser 官方聚合域名，自动分配到最快节点，不要硬编码单节点
const API_BASE = 'https://all.api.radio-browser.info/json'

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
// 只需要在这里加国家代码，首页就会自动拉取该地区的电台
// 例如想加日本电台：把下面改成 ['TW', 'JP']
export const RB_FETCH_COUNTRIES = ['TW', 'CN']

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
export async function fetchStationsByCountry(countryCode) {
  // 有缓存直接返回
  if (cache[countryCode]) return cache[countryCode]

  try {
    // 调用 Radio Browser API，按投票数降序，优先返回高质量电台，不限制数量
    const res = await fetch(
      `${API_BASE}/stations/bycountrycodeexact/${countryCode}` +
      `?order=votes&reverse=true`
    )

    // 请求失败返回空数组，不影响页面
    if (!res.ok) return []

    const data = await res.json()

    // 把 Radio Browser 格式映射为本项目的 station 格式
    const stations = data.map((item) => mapToStation(item, countryCode)).filter(Boolean)

    // 写入缓存
    cache[countryCode] = stations
    return stations
  } catch {
    // 网络异常等静默返回空数组
    return []
  }
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
