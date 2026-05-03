// src/config/stations.js
// tags 数组同时包含地区和类型，用于前端筛选
// 地区：TW = 台湾，CN = 中国大陆
// 类型：music = 音乐，news = 新闻，talk = 谈话

// 1. 数组格式：专门给 Home.vue 循环渲染列表用
export const stationList = [
  {
    id: 'hitfm',
    name: 'Hit FM 台北',
    logoText: 'H',
    logoUrl: '/logos/hitfm.png',
    tags: ['music', 'TW'],
  },
  {
    id: 'hitfm_taichung',
    name: 'Hit FM 台中',
    logoText: '台中',
    logoUrl: '/logos/hitfm.png',
    tags: ['music', 'TW'],
  },
  {
    id: 'hitfm_tainan',
    name: 'Hit FM 台南',
    logoText: '台南',
    logoUrl: '/logos/hitfm.png',
    tags: ['music', 'TW'],
  },
  {
    id: 'hitfm_yilan',
    name: 'Hit FM 宜兰',
    logoText: '宜兰',
    logoUrl: '/logos/hitfm.png',
    tags: ['music', 'TW'],
  },
  {
    id: 'hitfm_hualian',
    name: 'Hit FM 花莲',
    logoText: '花莲',
    logoUrl: '/logos/hitfm.png',
    tags: ['music', 'TW'],
  },
  {
    id: 'ufo',
    name: 'UFO Radio',
    logoText: 'U',
    logoUrl: '/logos/uforadio.png',
    directUrl: 'https://stream.rcs.revma.com/em90w4aeewzuv',
    livePath: 'ufo/live',
    tags: ['talk', 'TW'],
  },
  {
    id: 'pop917',
    name: 'POP Radio 91.7',
    logoText: 'POP',
    logoUrl: '/logos/pop917.png',
    tags: ['music', 'TW'],
  },
  {
    id: 'qz_fm889',
    name: '泉州新闻综合 88.9',
    logoText: 'FM889',
    logoUrl: '/logos/qz889.png',
    tags: ['news', 'CN'],
  },
  {
    id: 'qz_fm904',
    name: '泉州交通广播 90.4',
    logoText: 'FM904',
    logoUrl: '/logos/qz904.png',
    tags: ['news', 'CN'],
  },
  {
    id: 'qz_fm1059',
    name: '泉州刺桐之声 105.9',
    logoText: 'FM1059',
    logoUrl: '/logos/qz1059.png',
    tags: ['talk', 'CN'],
  },
  {
    id: 'qz_fm923',
    name: '泉州经济生活 92.3',
    logoText: 'FM923',
    logoUrl: '/logos/qz923.png',
    tags: ['news', 'CN'],
  },
  {
    id: 'cityfm',
    name: '城市广播网',
    logoText: '城',
    directUrl: 'https://fm901.cityfm.com.tw:8083/901',
    logoUrl: '/logos/twcsgbw.jpg',
    tags: ['music', 'TW'],
  },
  {
    id: 'bcc_news',
    name: '中广新闻网',
    logoText: '新闻',
    directUrl: 'https://stream.rcs.revma.com/fgtx07f3qtzuv',
    logoUrl: '/logos/twzgxww.png',
    tags: ['news', 'TW'],
  },
  {
    id: 'bcc_pop',
    name: '中广流行网',
    logoText: '流行',
    directUrl: 'https://stream.rcs.revma.com/s1zttsg3qtzuv',
    logoUrl: '/logos/twzglxw.jpg',
    tags: ['music', 'TW'],
  },
  {
    id: 'bcc_music',
    name: '中广音乐网',
    logoText: '音乐',
    directUrl: 'https://stream.rcs.revma.com/ks4vsmg3qtzuv',
    logoUrl: '/logos/twzgyyw.jpg',
    tags: ['music', 'TW'],
  },
  {
    id: 'igot531',
    name: 'iGO531',
    logoText: '531',
    directUrl: 'https://stream.rcs.revma.com/1qxn2vg3qtzuv',
    logoUrl: '/logos/twigo531.jpg',
    tags: ['music', 'TW'],
  },
  {
    id: 'bcc_rural',
    name: '中广乡亲网',
    logoText: '乡亲',
    directUrl: 'https://stream.rcs.revma.com/p2e3rfg3qtzuv',
    logoUrl: '/logos/twzgxqw.png',
    tags: ['talk', 'TW'],
  },
  // tingfm 系列：livePath 让前端走 HLS 后端代理，URL 由 fetcher 自动刷新
  // post_id 从 tingfm.com 电台页面 URL 获取
  {
    id: 'fj_traffic',
    name: '福建交通广播 100.7',
    logoText: '闽',
    livePath: 'fj_traffic/live',
    logoUrl: '/logos/fjjtgb.jpg',
    tags: ['news', 'CN'],
  },
]

// 2. 字典/映射格式：利用上面的数组自动生成！
// 专门给 BottomPlayer.vue 和 AudioEngine.vue 做快速查找用
export const stationMap = stationList.reduce((map, station) => {
  map[station.id] = station
  return map
}, {})
