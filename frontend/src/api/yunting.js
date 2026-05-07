export const YUNTING_PROVINCES = [
  '340000', // 安徽
  '110000', // 北京
  '500000', // 重庆
  '350000', // 福建
  '620000', // 甘肃
  '440000', // 广东
  '450000', // 广西
  '520000', // 贵州
  '460000', // 海南
  '130000', // 河北
  '410000', // 河南
  '230000', // 黑龙江
  '420000', // 湖北
  '430000', // 湖南
  '220000', // 吉林
  '320000', // 江苏
  '360000', // 江西
  '210000', // 辽宁
  '150000', // 内蒙古
  '640000', // 宁夏
  '630000', // 青海
  '370000', // 山东
  '140000', // 山西
  '610000', // 陕西
  '310000', // 上海
  '510000', // 四川
  '540000', // 西藏
  '650000', // 新疆
  '660000', // 新疆兵团
  '530000', // 云南
  '330000', // 浙江
]

const PROVINCE_LABELS = {
  '340000': '安徽',
  '110000': '北京',
  '500000': '重庆',
  '350000': '福建',
  '620000': '甘肃',
  '440000': '广东',
  '450000': '广西',
  '520000': '贵州',
  '460000': '海南',
  '130000': '河北',
  '410000': '河南',
  '230000': '黑龙江',
  '420000': '湖北',
  '430000': '湖南',
  '220000': '吉林',
  '320000': '江苏',
  '360000': '江西',
  '210000': '辽宁',
  '150000': '内蒙古',
  '640000': '宁夏',
  '630000': '青海',
  '370000': '山东',
  '140000': '山西',
  '610000': '陕西',
  '310000': '上海',
  '510000': '四川',
  '540000': '西藏',
  '650000': '新疆',
  '660000': '新疆兵团',
  '530000': '云南',
  '330000': '浙江',
}


const NAME_TYPE_KEYWORDS = [
  { keywords: ['音乐', 'music', '金曲', '经典'], type: 'music' },
  { keywords: ['交通', '新闻', '综合', '资讯', '新闻广播'], type: 'news' },
  { keywords: ['经济', '都市', '城市', '生活'], type: 'talk' },
  { keywords: ['体育', 'sport'], type: 'sports' },
]

function inferType(name) {
  for (const { keywords, type } of NAME_TYPE_KEYWORDS) {
    if (keywords.some((kw) => name.includes(kw))) return type
  }
  return 'news'
}

const cache = {}

export async function fetchYuntingStations(provinceCode) {
  if (cache[provinceCode]) return cache[provinceCode]

  let data = null
  try {
    const ctrl = new AbortController()
    const timer = setTimeout(() => ctrl.abort(), 10_000)
    const res = await fetch(`/api/yunting/stations/${provinceCode}`, { signal: ctrl.signal })
    clearTimeout(timer)
    if (res.ok) data = await res.json()
  } catch {}

  if (!data) return []

  const stations = data.map((item) => mapToStation(item, provinceCode)).filter(Boolean)
  cache[provinceCode] = stations
  return stations
}

export async function fetchAllYuntingStations() {
  try {
    const ctrl = new AbortController()
    const timer = setTimeout(() => ctrl.abort(), 15_000)
    const res = await fetch('/api/yunting/all', { signal: ctrl.signal })
    clearTimeout(timer)
    if (!res.ok) return []
    const data = await res.json()

    // 按 provinceCode 分组并缓存，供 fetchYuntingStations 单省查询复用
    const grouped = {}
    for (const item of data) {
      const prov = String(item.provinceCode || '')
      if (!grouped[prov]) grouped[prov] = []
      grouped[prov].push(item)
    }

    const all = []
    for (const [prov, items] of Object.entries(grouped)) {
      const stations = items.map((item) => mapToStation(item, prov)).filter(Boolean)
      cache[prov] = stations
      all.push(...stations)
    }
    return all
  } catch {
    return []
  }
}

function mapToStation(item, provinceCode) {
  const contentId = item.contentId || item.id
  if (!contentId) return null

  const name = item.title || item.name || '未知电台'
  const provinceLabel = PROVINCE_LABELS[provinceCode] || provinceCode

  return {
    id: `yt_${contentId}`,
    name,
    subtitle: item.subtitle || '',
    logoUrl: item.image || item.img || item.logo || '',
    logoText: name[0] || '?',
    directPlay: true,
    tags: ['CN', provinceLabel, inferType(name)],
  }
}
