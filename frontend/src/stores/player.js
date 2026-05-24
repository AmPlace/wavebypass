import { defineStore } from 'pinia'

export const usePlayerStore = defineStore('player', {
  state: () => ({
    isPlaying: false,
    isLoading: false,
    currentStation: '',
    volume: 1,
    playbackError: '',
    stationList: [],
    stationMap: {},
    isPlayerExpanded: false,
    activeMode: 'radio',  // 'radio' | 'iptv'
    // IPTV 播放状态
    currentIptvChannel: null,  // { name, group_name, logo_url, urls: [...] }
    iptvUrls: [],              // 当前频道的所有可用链接
    iptvUrlIndex: 0,           // 当前尝试的链接索引
    iptvVideoEl: null,         // FullPlayer 中的 video 元素引用（iOS 同步播放用）
    currentEpgProgram: null,   // EPG: { title, start, stop, progress, remaining_minutes }
  }),

  getters: {
    stationCount: (state) => state.stationList.length,
  },

  actions: {
    // stationId 对应后端路由中的 {station_id}
    switchStation(stationId) {
      if (!stationId) {
        return
      }

      this.currentStation = stationId

      this.playbackError = ''

      this.isLoading = true

      this.isPlaying = true
    },


    togglePlay(forcePlaying) {
      const hasForcedValue = typeof forcePlaying === 'boolean'

      this.isPlaying = hasForcedValue ? forcePlaying : !this.isPlaying
    },

    setLoading(nextLoading) {
      this.isLoading = Boolean(nextLoading)
    },

    setVolume(volumeValue) {
      const nextVolume = Number(volumeValue)

      if (Number.isNaN(nextVolume)) {
        return
      }

      this.volume = Math.min(1, Math.max(0, nextVolume))
    },

    setPlaybackError(message) {
      this.playbackError = message ? String(message) : ''

      if (this.playbackError) {
        this.isLoading = false
      }
    },

    clearPlaybackError() {
      this.playbackError = ''
    },

    addStation(station) {
      if (this.stationMap[station.id]) return
      // 只更新 stationMap（供 AudioEngine/BottomPlayer 查找播放地址和电台名称）
      // 不更新 stationList，因为 Home.vue 有自己的 rbStations 列表单独管理显示
      this.stationMap[station.id] = station
    },

    loadStations(stations) {
      this.stationList = stations
      const merged = { ...this.stationMap }
      for (const s of stations) merged[s.id] = s
      this.stationMap = merged
      if (!this.currentStation && stations.length) {
        this.currentStation = stations[0].id
      }
    },

    updateStationEpg(stationId, subtitle) {
      const station = this.stationMap[stationId]
      if (station) station.subtitle = subtitle
    },

    expandPlayer() {
      this.isPlayerExpanded = true
    },

    collapsePlayer() {
      this.isPlayerExpanded = false
    },

    setActiveMode(mode) {
      this.activeMode = mode
    },

    playIptvChannel(channel) {
      const sorted = [...channel.urls].sort((a, b) => {
        if (a.is_working !== b.is_working) return b.is_working - a.is_working
        return (a.latency_ms || 9999) - (b.latency_ms || 9999)
      })
      // 构建回退队列：直连优先，代理在后
      const list = []
      const API_BASE = import.meta.env?.VITE_API_BASE_URL || window.location.origin
      const sourceUrl = (u) => String(u?.url || '').trim()
      const isIOS = /iPad|iPhone|iPod/.test(navigator.userAgent) ||
        (navigator.platform === 'MacIntel' && navigator.maxTouchPoints > 1)
      const proxyUrlFor = (u, options = {}) => {
        const url = sourceUrl(u)
        const ua = u.custom_ua ? `&custom_ua=${encodeURIComponent(u.custom_ua)}` : ''
        const st = u.source_type || 'hls'
        if (st === 'rtsp') {
          const compat = options.compat ? '&compat=1' : ''
          return `${API_BASE}/api/iptv/proxy/rtsp.m3u8?target_url=${encodeURIComponent(url)}${ua}${compat}`
        }
        if (st === 'mpegts') {
          return `${API_BASE}/api/iptv/proxy/stream?target_url=${encodeURIComponent(url)}${ua}`
        }
        return `${API_BASE}/api/iptv/proxy/wide.m3u8?proxy_ts=1${ua}&target_url=${encodeURIComponent(url)}`
      }
      // 分两组：直连组 + 必须代理组
      const directUrls = []
      const proxyOnlyUrls = []
      for (const u of sorted) {
        const url = sourceUrl(u)
        if (!url) continue
        const st = u.source_type || 'hls'
        if (st === 'rtsp' || u.force_proxy || u.custom_ua) {
          proxyOnlyUrls.push({
            ...u,
            url: proxyUrlFor(u),
            original_url: url,
            type: st === 'mpegts' ? 'direct' : 'proxy',
            via_proxy: true,
            source_type: st,
          })
          if (isIOS && st === 'rtsp') {
            proxyOnlyUrls.push({
              ...u,
              url: proxyUrlFor(u, { compat: true }),
              original_url: url,
              type: 'proxy',
              via_proxy: true,
              rtsp_compat: true,
              source_type: st,
            })
          }
        } else {
          directUrls.push({ ...u, url })
        }
      }
      // 先所有直连，再所有直连的代理回退，最后是必须代理的
      for (const u of directUrls) {
        list.push({ ...u, url: u.url, original_url: u.url, type: 'direct' })
      }
      for (const u of directUrls) {
        const url = sourceUrl(u)
        list.push({
          ...u,
          url: proxyUrlFor(u),
          original_url: url,
          type: isMpegTsUrl(url) ? 'direct' : 'proxy',
          via_proxy: true,
        })
      }
      list.push(...proxyOnlyUrls)
      this.currentIptvChannel = channel
      this.iptvUrls = list
      this.iptvUrlIndex = 0
      this.playbackError = ''
      this.isLoading = true
      this.isPlaying = false
      // isPlaying 由实际播放事件设置，不提前设
    },

    iptvFallbackNext() {
      if (this.iptvUrlIndex < this.iptvUrls.length - 1) {
        this.iptvUrlIndex++
        this.playbackError = `源不可用，正在切换备用源 (${this.iptvUrlIndex + 1}/${this.iptvUrls.length})`
        this.isLoading = true
        return true
      }
      this.playbackError = '所有播放源均不可用'
      this.isPlaying = false
      this.isLoading = false
      return false
    },
  },
})
