// src/api/yunting.js
// 云听 (radio.cn) API 模块 — 按省份动态发现电台
//
// 请求链路：前端 → 后端 /api/yunting/stations/{code}（2h 缓存）→ 云听 API
// 电台 id 前缀 yt_，与 rb_（Radio Browser）区分，避免冲突

// ========== 首页要自动拉取的省份列表 ==========
// 只需要在这里加省份代码，首页就会自动拉取该省份的云听电台
// 350000 = 福建，110000 = 北京，440000 = 广东，310000 = 上海 …
export const YUNTING_PROVINCES = ['350000', '310000', '330000']

// 省份代码 → 中文地区标签，新增省份在这里加一行即可
const PROVINCE_LABELS = {
  '350000': '福建',
  '110000': '北京',
  '440000': '广东',
  '310000': '上海',
  '330000': '浙江',
  '320000': '江苏',
  '510000': '四川',
  '420000': '湖北',
}

// 根据电台名称关键词自动推断类型标签
// 匹配到就用对应类型，否则默认 news（云听电台以新闻/综合为主）
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

// 前端缓存，key 为 provinceCode
const cache = {}

// 拉取指定省份的云听电台列表，返回映射后的 station 数组
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

// 单条云听电台 → 本项目 station 格式
// 云听电台同时打国家标签（CN）和省份标签（如"福建"），解决地区筛选冲突：
//   选"中国大陆" → 看到所有中国电台（RB CN + 云听全部省份）
//   选"福建"     → 只看福建电台（云听福建 + RB 中名字含"福建"的）
// 新增省份只需改 PROVINCE_LABELS，tags 自动生成，无需改其他代码
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
    // CN 是国家标签（与 Radio Browser 的 CN 对齐），provinceLabel 是省份细分
    tags: ['CN', provinceLabel, inferType(name)],
  }
}
