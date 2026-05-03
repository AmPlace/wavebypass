// src/config/stations.js

// 1. 数组格式：专门给 Home.vue 循环渲染列表用
export const stationList = [
  {
    id: 'hitfm',
    name: 'Hit FM 台北',
    logoText: 'H',
    logoUrl: '/logos/hitfm.png',
  },
  {
    id: 'hitfm_taichung',
    name: 'Hit FM 台中',
    logoText: '台中',
    logoUrl: '/logos/hitfm.png',
  },
  {
    id: 'hitfm_tainan',
    name: 'Hit FM 台南',
    logoText: '台南',
    logoUrl: '/logos/hitfm.png',
  },
  {
    id: 'hitfm_yilan',
    name: 'Hit FM 宜兰',
    logoText: '宜兰',
    logoUrl: '/logos/hitfm.png',
  },
  {
    id: 'hitfm_hualian',
    name: 'Hit FM 花莲',
    logoText: '花莲',
    logoUrl: '/logos/hitfm.png',
  },
  {
    id: 'ufo',
    name: 'UFO Radio',
    logoText: 'U',
    logoUrl: '/logos/uforadio.png',
    // UFO 直连音频流地址，前端优先直连，失败自动回退后端中转
    directUrl: 'https://stream.rcs.revma.com/em90w4aeewzuv',
    // UFO 同时支持 HLS 后端代理，保留 livePath 供 HLS 回退使用
    livePath: 'ufo/live',
  },
    {
    id: 'pop917',
    name: 'POP Radio 91.7',
    logoText: 'POP',
    logoUrl: '/logos/pop917.png',
  },
  {
    id: 'qz_fm889',
    name: '泉州新闻综合 88.9',
    logoText: 'FM889',
    logoUrl: '/logos/qz889.png',
  },
    {
    id: 'qz_fm904',
    name: '泉州交通广播 90.4',
    logoText: 'FM904',
    logoUrl: '/logos/qz904.png',
  },
  {
    id: 'qz_fm1059',
    name: '泉州刺桐之声 105.9',
    logoText: 'FM1059',
    logoUrl: '/logos/qz1059.png',
  },
    {
    id: 'qz_fm923',
    name: '泉州经济生活 92.3',
    logoText: 'FM923',
    logoUrl: '/logos/qz923.png',
  },
  {
    id: 'cityfm',
    name: '城市广播网',
    logoText: '城',
    // 台湾城市广播网直链，无 m3u8 列表，直接返回音频流
    directUrl: 'https://fm901.cityfm.com.tw:8083/901',
    // 暂无官方 logo，用字母占位
    logoUrl: '/logos/twcsgbw.jpg',
  },
  {
    id: 'bcc_news',
    name: '中广新闻网',
    logoText: '新闻',
    directUrl: 'https://stream.rcs.revma.com/fgtx07f3qtzuv',
    logoUrl: '/logos/twzgxww.png',
  },
  {
    id: 'bcc_pop',
    name: '中广流行网',
    logoText: '流行',
    directUrl: 'https://stream.rcs.revma.com/s1zttsg3qtzuv',
    logoUrl: '/logos/twzglxw.jpg',
  },
  {
    id: 'bcc_music',
    name: '中广音乐网',
    logoText: '音乐',
    directUrl: 'https://stream.rcs.revma.com/ks4vsmg3qtzuv',
    logoUrl: '/logos/twzgyyw.jpg',
  },
  {
    id: 'igot531',
    name: 'iGO531',
    logoText: '531',
    directUrl: 'https://stream.rcs.revma.com/1qxn2vg3qtzuv',
    logoUrl: '/logos/twigo531.jpg',
  },
  {
    id: 'bcc_rural',
    name: '中广乡亲网',
    logoText: '乡亲',
    directUrl: 'https://stream.rcs.revma.com/p2e3rfg3qtzuv',
    logoUrl: '/logos/twzgxqw.png',
  },
]

// 2. 字典/映射格式：利用上面的数组自动生成！
// 专门给 BottomPlayer.vue 和 AudioEngine.vue 做快速查找用
export const stationMap = stationList.reduce((map, station) => {
  map[station.id] = station
  return map
}, {})