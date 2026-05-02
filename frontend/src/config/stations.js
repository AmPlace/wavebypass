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
  },
  {
    id: 'qz_fm889',
    name: '泉州交通之声 FM889',
    logoText: 'FM889',
    logoUrl: '/logos/qz889.png',
  }
]

// 2. 字典/映射格式：利用上面的数组自动生成！
// 专门给 BottomPlayer.vue 和 AudioEngine.vue 做快速查找用
export const stationMap = stationList.reduce((map, station) => {
  map[station.id] = station
  return map
}, {})