// src/api/myradio.js
// myradio.tw 电台 API 模块 — 台湾电台直链
//
// 请求链路：前端 → 后端 /api/myradio/all（24h 缓存）→ myradio-dev.zeabur.app
// 电台 id 前缀 mr_，与 rb_（Radio Browser）和 yt_（云听）区分

// 根据电台名称关键词自动推断类型标签
const NAME_TYPE_KEYWORDS = [
  { keywords: ['音樂', 'music', '金曲', '古典', 'hit'], type: 'music' },
  { keywords: ['新聞', 'news', '資訊', '交通'], type: 'news' },
  { keywords: ['電台', '聯播', '廣播', 'talk'], type: 'talk' },
  { keywords: ['體育', 'sport'], type: 'sports' },
]

function inferType(name) {
  const lower = (name || '').toLowerCase()
  for (const { keywords, type } of NAME_TYPE_KEYWORDS) {
    if (keywords.some((kw) => lower.includes(kw))) return type
  }
  return 'other'
}

// 拉取所有 myradio 电台，返回映射后的 station 数组
export async function fetchMyradioStations() {
  try {
    const ctrl = new AbortController()
    const timer = setTimeout(() => ctrl.abort(), 15_000)
    const res = await fetch('/api/myradio/all', { signal: ctrl.signal })
    clearTimeout(timer)
    if (!res.ok) return []

    const data = await res.json()
    return data
      .filter((item) => item.url)
      .map((item) => ({
        id: `mr_${item.id}`,
        name: item.name,
        subtitle: item.freq || '',
        logoUrl: item.logo || '',
        logoText: item.name[0] || '?',
        directPlay: true,
        tags: ['TW', inferType(item.name)],
      }))
  } catch {
    return []
  }
}
