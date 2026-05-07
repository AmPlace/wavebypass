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
    id: 'hitfm_huadong',
    name: 'Hit FM 花东',
    logoText: '花东',
    logoUrl: '/logos/hitfm.png',
    tags: ['music', 'TW'],
  },
  {
    id: 'pop917',
    name: 'POP Radio 91.7',
    logoText: 'POP',
    logoUrl: '/logos/pop917.jpg',
    tags: ['music', 'TW'],
  },
  {
    id: 'qz_fm889',
    name: '泉州新闻综合 88.9',
    logoText: 'FM889',
    logoUrl: '/logos/qz889.png',
    tags: ['CN', '福建', 'news'],
  },
  {
    id: 'qz_fm904',
    name: '泉州交通广播 90.4',
    logoText: 'FM904',
    logoUrl: '/logos/qz904.png',
    tags: ['CN', '福建', 'news'],
  },
  {
    id: 'qz_fm1059',
    name: '泉州刺桐之声 105.9',
    logoText: 'FM1059',
    logoUrl: '/logos/qz1059.png',
    tags: ['CN', '福建', 'talk'],
  },
  {
    id: 'qz_fm923',
    name: '泉州经济生活 92.3',
    logoText: 'FM923',
    logoUrl: '/logos/qz923.png',
    tags: ['CN', '福建', 'news'],
  }
]

// 2. 字典/映射格式：利用上面的数组自动生成！
// 专门给 BottomPlayer.vue 和 AudioEngine.vue 做快速查找用
export const stationMap = stationList.reduce((map, station) => {
  map[station.id] = station
  return map
}, {})
