export const stationList = [
  {
    id: 'hitfm',
    name: 'Hit FM 台北',
    logoText: 'H',
    logoUrl: '/logos/hitfm.png',
    subtitle: 'FM 107.7',
    tags: ['music', 'TW'],
  },
  {
    id: 'hitfm_taichung',
    name: 'Hit FM 台中',
    logoText: '台中',
    logoUrl: '/logos/hitfm.png',
    subtitle: 'FM 91.5',
    tags: ['music', 'TW'],
  },
  {
    id: 'hitfm_tainan',
    name: 'Hit FM 台南',
    logoText: '台南',
    logoUrl: '/logos/hitfm.png',
    subtitle: 'FM 90.1',
    tags: ['music', 'TW'],
  },
  {
    id: 'hitfm_yilan',
    name: 'Hit FM 宜兰',
    logoText: '宜兰',
    logoUrl: '/logos/hitfm.png',
    subtitle: 'FM 97.1',
    tags: ['music', 'TW'],
  },
  {
    id: 'hitfm_huadong',
    name: 'Hit FM 花东',
    logoText: '花东',
    logoUrl: '/logos/hitfm.png',
    subtitle: 'FM 107.7',
    tags: ['music', 'TW'],
  },
  {
    id: 'pop917',
    name: 'POP Radio',
    logoText: 'POP',
    logoUrl: '/logos/pop917.jpg',
    subtitle: 'FM 91.7',
    tags: ['music', 'TW'],
  },
  {
    id: 'qz_fm889',
    name: '泉州新闻综合',
    logoText: 'FM889',
    logoUrl: '/logos/qz889.png',
    subtitle: 'FM 88.9',
    tags: ['CN', '福建', 'news'],
  },
  {
    id: 'qz_fm904',
    name: '泉州交通广播',
    logoText: 'FM904',
    logoUrl: '/logos/qz904.png',
    subtitle: 'FM 90.4',
    tags: ['CN', '福建', 'news'],
  },
  {
    id: 'qz_fm1059',
    name: '泉州刺桐之声',
    logoText: 'FM1059',
    logoUrl: '/logos/qz1059.png',
    subtitle: 'FM 105.9',
    tags: ['CN', '福建', 'talk'],
  },
  {
    id: 'qz_fm923',
    name: '泉州经济生活',
    logoText: 'FM923',
    logoUrl: '/logos/qz923.png',
    subtitle: 'FM 92.3',
    tags: ['CN', '福建', 'news'],
  }
]

export const stationMap = stationList.reduce((map, station) => {
  map[station.id] = station
  return map
}, {})
