import { defineStore } from 'pinia'
import { API_BASE } from '../apiBase.js'
import { adapterNameFromUrl, buildChannelProxyUrl, isAdapterSchemeUrl } from '../utils/sourceIdentity.js'

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
    pendingIptvChannel: null,  // 正在异步构建播放队列的频道，用于立即反馈选中态
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

      // 使旧的 playIptvChannel 异步 resolve 失效
      ++this.iptvSelectionToken

      // 停止 IPTV 播放
      this.currentIptvChannel = null
      this.pendingIptvChannel = null
      this.iptvUrls = []
      this.iptvUrlIndex = 0
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
      // 停止电台播放，触发 AudioEngine destroyHls
      this.currentStation = ''
      this.pendingIptvChannel = channel
      this.playbackError = ''
      this.isLoading = true
      try {
      const sorted = [...channel.urls].sort((a, b) => {
        const rank = (u) => {
          const status = String(u?.probe_status || '').trim().toLowerCase()
          if (u?.is_working === 1 || status === 'online') return 0
          if (!status || status === 'untested' || status === 'unknown' || u?.is_working === -1) return 1
          return 2
        }
        const rankDelta = rank(a) - rank(b)
        if (rankDelta) return rankDelta
        return (a.latency_ms || 9999) - (b.latency_ms || 9999)
      })
      // 构建回退队列：直连优先，代理在后
      const list = []
      const sourceUrl = (u) => String(u?.url || '').trim()
      const youtubeParts = (url) => {
        const parsed = new URL(url)
        return parsed.protocol === 'youtube:'
          ? [parsed.hostname, ...parsed.pathname.split('/')].filter(Boolean)
          : parsed.pathname.split('/').filter(Boolean)
      }
      const parseYoutubeVideoId = (url) => {
        try {
          const parsed = new URL(url)
          const host = parsed.hostname.toLowerCase()
          const parts = youtubeParts(url)
          let id = ''
          if (parsed.protocol === 'youtube:') {
            if (parts.length === 1) id = parts[0] || ''
            else if (parts.length >= 2 && ['live', 'embed', 'shorts'].includes(parts[0])) id = parts[1]
          } else if (host === 'youtu.be' || host === 'www.youtu.be') {
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
      const parseYoutubeChannelId = (url) => {
        try {
          const parsed = new URL(url)
          const host = parsed.hostname.toLowerCase()
          const parts = youtubeParts(url)
          let id = ''
          if (parsed.protocol === 'youtube:') {
            if (/^UC[a-zA-Z0-9_-]{20,}$/.test(parts[0] || '')) id = parts[0]
            else if (parts.length >= 2 && parts[0] === 'channel') id = parts[1]
          } else if (host === 'youtube.com' || host.endsWith('.youtube.com') || host === 'youtube-nocookie.com' || host.endsWith('.youtube-nocookie.com')) {
            if (parts.length >= 2 && parts[0] === 'channel') id = parts[1]
          }
          return /^UC[a-zA-Z0-9_-]{20,}$/.test(id) ? id : ''
        } catch {
          return ''
        }
      }
      const isYoutubeLiveChannelUrl = (url) => {
        try {
          const parsed = new URL(url)
          if (parsed.protocol !== 'youtube:' && !isYoutubeUrl(url)) return false
          const parts = youtubeParts(url)
          return parts[parts.length - 1] === 'live'
        } catch {
          return false
        }
      }
      const isYoutubeUrl = (url) => {
        try {
          const parsed = new URL(url)
          if (parsed.protocol === 'youtube:') return true
          const host = parsed.hostname.toLowerCase()
          return host === 'youtu.be' || host === 'www.youtu.be' || host === 'youtube.com' || host.endsWith('.youtube.com') || host === 'youtube-nocookie.com' || host.endsWith('.youtube-nocookie.com')
        } catch {
          return false
        }
      }
      const inferSourceType = (url) => {
        const value = String(url || '').trim().toLowerCase()
        if (parseYoutubeVideoId(url)) return 'youtube'
        if (parseYoutubeChannelId(url) && isYoutubeLiveChannelUrl(url)) return 'youtube'
        if (isYoutubeUrl(url)) return 'unsupported_youtube_url'
        if (isAdapterSchemeUrl(url)) return 'adapter'
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
      const proxyUrlFor = (u, options = {}) => {
        return buildChannelProxyUrl({
          apiBase: API_BASE,
          channelKey: u._canonical_key || '',
          sourceId: options.sourceId || u.source_id || '',
          accessToken: u._access_token || '',
        })
      }
      const resolveUrlFor = (u) => {
        const key = String(u?._canonical_key || '').trim()
        const sourceId = String(u?.source_id || '').trim()
        if (!key || !sourceId) return ''
        const params = new URLSearchParams({ source_id: sourceId })
        if (u._access_token) params.set('access_token', u._access_token)
        return `${API_BASE}/api/media/channel/${encodeURIComponent(key)}/resolve?${params.toString()}`
      }
      const absoluteApiUrl = (url) => {
        if (!url) return ''
        return /^https?:\/\//i.test(url) ? url : `${API_BASE}${url.startsWith('/') ? url : `/${url}`}`
      }
      const resolveAdapterSource = async (u) => {
        const resolveUrl = resolveUrlFor(u)
        if (!resolveUrl) return null
        const ctrl = new AbortController()
        const timer = setTimeout(() => ctrl.abort(), 10_000)
        try {
          const res = await fetch(resolveUrl, { signal: ctrl.signal })
          const data = await res.json().catch(() => ({}))
          if (!res.ok || data.ok === false) {
            throw new Error(data.message || data.detail?.message || data.detail || `HTTP ${res.status}`)
          }
          return { ...data, _resolve_url: resolveUrl }
        } finally {
          clearTimeout(timer)
        }
      }
      const sourceForcesProxy = (u) => Boolean(
        u?.force_proxy || u?.requires_proxy_declared,
      )
      // 分两组：直连组 + 必须代理组
      const directUrls = []
      const proxyOnlyUrls = []
      const adapterSources = []
      const canonicalKey = channel.canonical_key || ''  // 聚合频道 key，用于 media API
      for (const u of sorted) {
        const url = sourceUrl(u)
        if (!url) continue
        const st = sourceType(u)
        if (st === 'youtube') {
          adapterSources.push({
            ...u,
            _canonical_key: canonicalKey,
            original_url: url,
            adapter: 'youtube',
            source_type: 'youtube',
          })
          continue
        }
        if (st === 'unsupported_youtube_url') {
          adapterSources.push({
            ...u,
            _canonical_key: canonicalKey,
            original_url: url,
            adapter: 'youtube',
            source_type: 'unsupported_youtube_url',
          })
          continue
        }
        if (st === 'adapter') {
          adapterSources.push({ ...u, _canonical_key: canonicalKey })
          continue
        }
        if (st === 'rtsp' || u.force_proxy || u.custom_ua || u.referer) {
          const proxyUrl = proxyUrlFor({ ...u, _canonical_key: canonicalKey })
          if (!proxyUrl) continue
          proxyOnlyUrls.push({
            ...u,
            _canonical_key: canonicalKey,
            url: proxyUrl,
            original_url: url,
            type: st === 'mpegts' || st === 'http_flv' ? 'direct' : 'proxy',
            via_proxy: true,
            source_type: st,
          })
        } else {
          directUrls.push({ ...u, _canonical_key: canonicalKey, url, source_type: st })
        }
      }
      for (const u of adapterSources) {
        const url = sourceUrl(u)
        const adapter = u.adapter || adapterNameFromUrl(url)
        const originalUrl = u.original_url || url
        const fallbackProxyUrl = proxyUrlFor(u)
        if (adapter === 'youtube') {
          const youtubeVideoId = parseYoutubeVideoId(originalUrl) || u.youtube_video_id || ''
          const youtubeChannelId = parseYoutubeChannelId(originalUrl) || u.youtube_channel_id || ''
          if (youtubeVideoId || youtubeChannelId) {
            directUrls.push({
              ...u,
              url: originalUrl,
              original_url: originalUrl,
              type: 'youtube',
              engine: 'youtube',
              source_type: 'youtube',
              youtube_video_id: youtubeVideoId,
              youtube_channel_id: youtubeChannelId,
              youtube_live_embed_url: youtubeChannelId && !youtubeVideoId
                ? `https://www.youtube.com/embed/live_stream?channel=${encodeURIComponent(youtubeChannelId)}&autoplay=1&playsinline=1&controls=1&rel=0`
                : '',
            })
          }
        }
        if (adapter !== 'youtube') {
          try {
            const resolved = await resolveAdapterSource(u)
            const resolvedUrl = String(resolved?.url || '').trim()
            const proxyUrl = absoluteApiUrl(resolved?.proxy_url) || fallbackProxyUrl
            // Adapter 自身声明 requires_proxy/direct_playable=false 是硬约束；
            // Market/订阅侧 force_proxy 只能额外要求代理，不能覆盖 adapter 硬约束为 direct。
            const adapterAllowsDirect = !resolved?.requires_proxy && resolved?.direct_playable !== false
            const canDirectPlay = Boolean(resolvedUrl && adapterAllowsDirect && !sourceForcesProxy(u))
            if (canDirectPlay) {
              directUrls.push({
                ...u,
                url: resolvedUrl,
                original_url: originalUrl,
                adapter,
                adapter_source_url: resolved._resolve_url,
                adapter_proxy_url: proxyUrl,
                adapter_volatile_url: resolved.volatile_url === true,
                source_type: resolved.source_type || 'hls',
                type: 'direct',
              })
            } else if (proxyUrl) {
              proxyOnlyUrls.push({
                ...u,
                url: proxyUrl,
                original_url: originalUrl,
                adapter,
                type: 'proxy',
                via_proxy: true,
                source_type: resolved?.source_type === 'probe_only' ? 'hls' : resolved?.source_type || 'hls',
              })
            }
            continue
          } catch (e) {
            console.warn('[IPTV] adapter resolve failed:', e?.message || e)
          }
        }
        if (fallbackProxyUrl) {
          proxyOnlyUrls.push({
            ...u,
            url: fallbackProxyUrl,
            original_url: originalUrl,
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
        const proxyUrl = u.adapter_proxy_url || proxyUrlFor(u)
        if (!proxyUrl) continue
        list.push({
          ...u,
          url: proxyUrl,
          original_url: u.original_url || url,
          type: st === 'mpegts' || st === 'http_flv' ? 'direct' : 'proxy',
          via_proxy: true,
          source_type: st,
        })
      }
      list.push(...proxyOnlyUrls)
      this.currentIptvChannel = channel
      this.pendingIptvChannel = null
      this.iptvUrls = list
      this.iptvUrlIndex = 0
      this.playbackError = list.length ? '' : '没有可播放的源'
      this.isLoading = Boolean(list.length)
      this.isPlaying = false
      // isPlaying 由实际播放事件设置，不提前设
      } catch (e) {
        if (selectionToken === this.iptvSelectionToken) {
          this.pendingIptvChannel = null
        }
        throw e
      }
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

    async reResolveAdapterUrl(resolveUrl) {
      const url = String(resolveUrl || '').trim()
      if (!url || !/\/api\/media\/channel\/.+\/resolve(?:\?|$)/i.test(url)) return null
      const ctrl = new AbortController()
      const timer = setTimeout(() => ctrl.abort(), 10_000)
      try {
        const res = await fetch(url, { signal: ctrl.signal, cache: 'no-store' })
        const data = await res.json().catch(() => ({}))
        if (!res.ok || data.ok === false) {
          throw new Error(data.message || data.detail?.message || data.detail || `HTTP ${res.status}`)
        }
        return data
      } finally {
        clearTimeout(timer)
      }
    },
  },
})
