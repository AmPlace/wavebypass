import { defineStore } from 'pinia'
import { API_BASE } from '../apiBase'

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
    iptvSelectionToken: 0,      // 防止异步解析旧频道覆盖新频道
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

    async playIptvChannel(channel) {
      const selectionToken = ++this.iptvSelectionToken
      this.playbackError = ''
      this.isLoading = true
      const sorted = [...channel.urls].sort((a, b) => {
        if (a.is_working !== b.is_working) return b.is_working - a.is_working
        return (a.latency_ms || 9999) - (b.latency_ms || 9999)
      })
      // 构建回退队列：直连优先，代理在后
      const list = []
      const sourceUrl = (u) => String(u?.url || '').trim()
      const parseYoutubeVideoId = (url) => {
        try {
          const parsed = new URL(url)
          const host = parsed.hostname.toLowerCase()
          const parts = parsed.pathname.split('/').filter(Boolean)
          let id = ''
          if (host === 'youtu.be' || host === 'www.youtu.be') {
            id = parts[0] || ''
          } else if (host === 'youtube.com' || host.endsWith('.youtube.com') || host === 'youtube-nocookie.com' || host.endsWith('.youtube-nocookie.com')) {
            id = parsed.searchParams.get('v') || ''
            if (!id && parts.length >= 2 && ['live', 'embed', 'shorts'].includes(parts[0])) {
              id = parts[1]
            }
          }
          return /^[a-zA-Z0-9_-]{11}$/.test(id) ? id : ''
        } catch {
          return ''
        }
      }
      const isYoutubeUrl = (url) => {
        try {
          const host = new URL(url).hostname.toLowerCase()
          return host === 'youtu.be' || host === 'www.youtu.be' || host === 'youtube.com' || host.endsWith('.youtube.com') || host === 'youtube-nocookie.com' || host.endsWith('.youtube-nocookie.com')
        } catch {
          return false
        }
      }
      const inferSourceType = (url) => {
        const value = String(url || '').trim().toLowerCase()
        if (parseYoutubeVideoId(url)) return 'youtube'
        if (isYoutubeUrl(url)) return 'unsupported_youtube_url'
        if (value.startsWith('migu://') || value.startsWith('douyin://') || value.startsWith('huya://') || value.startsWith('redbook://') || value.startsWith('adapter://')) return 'adapter'
        if (value.startsWith('rtsp://')) return 'rtsp'
        if (/\/(?:rtp|udp)\//i.test(value) || /%2f(?:rtp|udp)%2f/i.test(value)) return 'mpegts'
        if (/\.(?:ts|m2ts|mts)(?:[?#]|$)/i.test(value)) return 'mpegts'
        if (/\.flv(?:[?#]|$)/i.test(value) || /[?&]stream_type=http_flv(?:&|$)/i.test(value)) return 'http_flv'
        return 'hls'
      }
      const sourceType = (u) => {
        const inferred = inferSourceType(sourceUrl(u))
        const declared = String(u?.source_type || '').trim().toLowerCase()
        return declared && declared !== 'hls' ? declared : inferred
      }
      const isIOS = /iPad|iPhone|iPod/.test(navigator.userAgent) ||
        (navigator.platform === 'MacIntel' && navigator.maxTouchPoints > 1)
      const adapterPlayUrlFor = (url) => `${API_BASE}/api/iptv/adapter/play.m3u8?target_url=${encodeURIComponent(url)}`
      const absoluteApiUrl = (url) => {
        if (!url) return ''
        return /^https?:\/\//i.test(url) ? url : `${API_BASE}${url.startsWith('/') ? url : `/${url}`}`
      }
      const resolveAdapterSource = async (url) => {
        const ctrl = new AbortController()
        const timer = setTimeout(() => ctrl.abort(), 10_000)
        try {
          const res = await fetch(`${API_BASE}/api/iptv/adapter/resolve?target_url=${encodeURIComponent(url)}`, {
            signal: ctrl.signal,
          })
          const data = await res.json().catch(() => ({}))
          if (!res.ok || data.ok === false) {
            throw new Error(data.message || data.detail?.message || data.detail || `HTTP ${res.status}`)
          }
          return data
        } finally {
          clearTimeout(timer)
        }
      }
      const adapterName = (url) => {
        const value = String(url || '').trim().toLowerCase()
        if (value.startsWith('migu://')) return 'migu'
        try {
          const parsed = new URL(url)
          return parsed.protocol === 'adapter:' ? parsed.hostname.toLowerCase() : ''
        } catch {
          return ''
        }
      }
      const proxyUrlFor = (u, options = {}) => {
        if (u.adapter_proxy_url) return u.adapter_proxy_url
        const url = sourceUrl(u)
        const ua = u.custom_ua ? `&custom_ua=${encodeURIComponent(u.custom_ua)}` : ''
        const referer = u.referer ? `&referer=${encodeURIComponent(u.referer)}` : ''
        const st = sourceType(u)
        if (st === 'adapter') {
          return adapterPlayUrlFor(url)
        }
        if (st === 'rtsp') {
          const compat = options.compat ? '&compat=1' : ''
          return `${API_BASE}/api/iptv/proxy/rtsp.m3u8?target_url=${encodeURIComponent(url)}${ua}${compat}`
        }
        if (st === 'mpegts' || st === 'http_flv') {
          const streamType = st === 'http_flv' ? '&stream_type=http_flv' : ''
          return `${API_BASE}/api/iptv/proxy/stream?target_url=${encodeURIComponent(url)}${ua}${referer}${streamType}`
        }
        return `${API_BASE}/api/iptv/proxy/wide.m3u8?proxy_ts=1${ua}${referer}&target_url=${encodeURIComponent(url)}`
      }
      // 分两组：直连组 + 必须代理组
      const directUrls = []
      const proxyOnlyUrls = []
      const adapterSources = []
      for (const u of sorted) {
        const url = sourceUrl(u)
        if (!url) continue
        const st = sourceType(u)
        if (st === 'unsupported_youtube_url') continue
        if (st === 'youtube') {
          const youtubeVideoId = u.youtube_video_id || parseYoutubeVideoId(url)
          if (!youtubeVideoId) continue
          directUrls.push({
            ...u,
            url,
            original_url: url,
            type: 'youtube',
            engine: 'youtube',
            source_type: 'youtube',
            youtube_video_id: youtubeVideoId,
          })
          continue
        }
        if (st === 'adapter') {
          adapterSources.push(u)
          continue
        }
        if (st === 'rtsp' || u.force_proxy || u.custom_ua || u.referer) {
          proxyOnlyUrls.push({
            ...u,
            url: proxyUrlFor(u),
            original_url: url,
            type: st === 'mpegts' || st === 'http_flv' ? 'direct' : 'proxy',
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
          directUrls.push({ ...u, url, source_type: st })
        }
      }
      for (const u of adapterSources) {
        const url = sourceUrl(u)
        const adapter = u.adapter || adapterName(url)
        const fallbackProxyUrl = adapterPlayUrlFor(url)
        try {
          const resolved = await resolveAdapterSource(url)
          const proxyUrl = absoluteApiUrl(resolved.proxy_url) || fallbackProxyUrl
          const canDirectPlay = !resolved.requires_proxy && resolved.direct_playable !== false && resolved.url
          if (canDirectPlay) {
            directUrls.push({
              ...u,
              url: resolved.url,
              original_url: url,
              adapter,
              adapter_source_url: url,
              adapter_proxy_url: proxyUrl,
              source_type: resolved.source_type || 'hls',
              type: 'direct',
            })
          }
          if (!canDirectPlay) {
            proxyOnlyUrls.push({
              ...u,
              url: proxyUrl,
              original_url: url,
              adapter,
              type: 'proxy',
              via_proxy: true,
              source_type: resolved.source_type || 'hls',
            })
          }
        } catch (e) {
          console.warn('[IPTV] adapter resolve failed:', e?.message || e)
          proxyOnlyUrls.push({
            ...u,
            url: fallbackProxyUrl,
            original_url: url,
            adapter,
            type: 'proxy',
            via_proxy: true,
            source_type: 'hls',
          })
        }
      }
      if (selectionToken !== this.iptvSelectionToken) return
      // 先所有直连，再所有直连的代理回退，最后是必须代理的
      for (const u of directUrls) {
        list.push({ ...u, url: u.url, original_url: u.original_url || u.url, type: u.type || 'direct' })
      }
      for (const u of directUrls) {
        const url = sourceUrl(u)
        const st = sourceType(u)
        if (st === 'youtube') continue
        list.push({
          ...u,
          url: proxyUrlFor(u),
          original_url: u.original_url || url,
          type: st === 'mpegts' || st === 'http_flv' ? 'direct' : 'proxy',
          via_proxy: true,
          source_type: st,
        })
      }
      list.push(...proxyOnlyUrls)
      this.currentIptvChannel = channel
      this.iptvUrls = list
      this.iptvUrlIndex = 0
      this.playbackError = list.length ? '' : '没有可播放的源'
      this.isLoading = Boolean(list.length)
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
