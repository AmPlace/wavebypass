<template>

  <audio ref="audioRef" hidden playsinline @error="handleAudioError"></audio>
</template>

<script setup>
import { onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { storeToRefs } from 'pinia'
import { usePlayerStore } from '../stores/player'
import { API_BASE } from '../apiBase'
import { publicAsset } from '../publicAsset'

const playerStore = usePlayerStore()
const { currentStation, isPlaying, volume } = storeToRefs(playerStore)
const audioRef = ref(null)
const hlsRef = ref(null)

const directStreamStationMap = {
}

const directStreamMode = ref('')

function getDirectUrl(stationId) {
  return playerStore.stationMap[stationId]?.directUrl
}

function hasDirectUrl(stationId) {
  return Boolean(getDirectUrl(stationId))
}

function updateSystemMediaSession(stationId) {
  if ('mediaSession' in navigator) {
    const meta = playerStore.stationMap[stationId] || {}
    const finalLogo = publicAsset(meta.logoUrl || '/logos/default.png')

    try {
      navigator.mediaSession.metadata = new MediaMetadata({
        title: meta.name || '未知频率',
        artist: meta.subtitle || 'WaveBypass Radio',
        album: 'Live Stream',
        artwork: [{ src: finalLogo, sizes: '512x512', type: 'image/png' }],
      })
    } catch (e) {
      console.warn('MediaSession 写入失败，跳过元数据更新', e)
    }

    navigator.mediaSession.setActionHandler('play', () => playerStore.togglePlay(true))
    navigator.mediaSession.setActionHandler('pause', () => playerStore.togglePlay(false))
  }
}

// 电台 EPG 更新时自动刷新 MediaSession 显示
watch(
  () => {
    const id = currentStation.value
    return id ? playerStore.stationMap[id]?.subtitle : undefined
  },
  (subtitle) => {
    if (subtitle && currentStation.value) updateSystemMediaSession(currentStation.value)
  },
)

// ========== 多源回退状态 ==========
let _fallbackUrls = []
let _fallbackIndex = 0
let _fallbackStationId = ''
// 阶段 1 直连探测胜出结果，阶段 2 可直接用其原始 URL 走中转（避免重复探测）
let _directProbeWinner = null

function destroyHls() {
  if (!hlsRef.value) return
  hlsRef.value.destroy()
  hlsRef.value = null
}

function resetAudioSource() {
  if (!audioRef.value) return
  audioRef.value.pause()
  audioRef.value.removeAttribute('src')
  audioRef.value.load()
}

async function playAudioSafely() {
  if (!audioRef.value) return

  try {
    await audioRef.value.play()

    playerStore.clearPlaybackError()
    playerStore.setLoading(false)
    playerStore.togglePlay(true)
    updateSystemMediaSession(currentStation.value)
  } catch (error) {
    if (error instanceof DOMException) {
      console.warn('浏览器阻止了自动播放，需要用户手动点击播放。', error)
      playerStore.setPlaybackError('浏览器阻止自动播放，请手动点击播放。')
    } else {
      console.warn('音频播放失败。', error)
      playerStore.setPlaybackError('音频播放失败，请稍后重试。')
    }
    playerStore.togglePlay(false)
  }
}

function fallbackToProxyStream(stationId) {
  if (!audioRef.value) return

  if (directStreamMode.value === 'proxy') {
    playerStore.setPlaybackError('后端中转音频流连接失败，请稍后重试。')
    playerStore.togglePlay(false)
    return
  }

  // 确定中转地址：优先用 directStreamStationMap 的自定义地址，否则用通用 /api/{id}/live
  const streamConfig = directStreamStationMap[stationId]
  const proxyUrl = streamConfig?.proxyUrl || `${API_BASE}/api/${stationId}/live`

  directStreamMode.value = 'proxy'
  playerStore.setPlaybackError('直连失败，正在自动切换后端中转。')
  playerStore.setLoading(true)
  audioRef.value.src = proxyUrl
  audioRef.value.load()
  playAudioSafely()
}

function isHlsUrl(url) {
  return /\.m3u8(\?|$)/i.test(url)
}

async function playUrl(url, stationId, mode) {
  destroyHls()
  directStreamMode.value = mode

  if (isHlsUrl(url) && Hls?.isSupported()) {
    // HLS 流：创建 hls.js 实例
    const hls = new Hls({
      enableWorker: true, lowLatencyMode: true, autoStartLoad: true,
      startFragPrefetch: true, liveSyncDurationCount: 2,
      liveMaxLatencyDurationCount: 5, maxBufferLength: 10,
    })
    hlsRef.value = hls
    hls.loadSource(url)
    hls.attachMedia(audioRef.value)
    await new Promise((resolve, reject) => {
      hls.on(Hls.Events.MANIFEST_PARSED, resolve)
      hls.on(Hls.Events.ERROR, (_e, d) => { if (d?.fatal) reject(d) })
      setTimeout(reject, 10_000)
    })
  } else {
    // 直连流：直接设置 audio src
    audioRef.value.src = url
    audioRef.value.load()
  }

  audioRef.value.volume = volume.value
  await audioRef.value.play()
  playerStore.clearPlaybackError()
  playerStore.setLoading(false)
  playerStore.togglePlay(true)
  updateSystemMediaSession(stationId)
}

// ========== 并发探测 ==========
// 1. 可达性预检：fetch(no-cors) 快速过滤不可达 URL
// 2. 胜出后立即销毁所有失败者的 Audio/HLS 实例（防资源泄露）
// 3. HLS 等 FRAG_LOADED（切片真正下载成功）而非仅 MANIFEST_PARSED

function upgradeHttps(url) {
  return url.startsWith('http://') ? 'https://' + url.slice(7) : url
}

// 快速可达性检查：HEAD(no-cors)，返回 [testUrl, origUrl] 元组数组
async function filterReachable(urls, { tryHttps = false } = {}) {
  const checks = urls.map((url) => {
    const testUrl = tryHttps ? upgradeHttps(url) : url
    return Promise.race([
      fetch(testUrl, { method: 'HEAD', mode: 'no-cors' }).then(() => [testUrl, url]).catch(() => null),
      new Promise((r) => setTimeout(() => r(null), 3000)),
    ])
  })
  const results = await Promise.all(checks)
  return results.filter(Boolean)
}

async function probeParallel(urls, stationId, mode, { tryHttps = false } = {}) {
  if (!urls.length) return null

  const reachable = await filterReachable(urls, { tryHttps })
  if (!reachable.length) return null
  console.log(`[探测] ${reachable.length}/${urls.length} 个源可达${tryHttps ? '（已升级 HTTPS）' : ''}`)

  const activeHls = new Set()
  const activeAudio = new Set()

  function cleanupAll() {
    for (const h of activeHls) { h.destroy() }
    activeHls.clear()
    for (const a of activeAudio) {
      a.pause()
      a.removeAttribute('src')
      a.load()
    }
    activeAudio.clear()
  }

  const promises = reachable.map(([url, origUrl], i) => {
    if (isHlsUrl(url) && Hls?.isSupported()) {
        return new Promise((resolve) => {
        const probeEl = new Audio()
        const hls = new Hls({ autoStartLoad: true, maxBufferLength: 1 })
        activeHls.add(hls)
        activeAudio.add(probeEl)
        hls.loadSource(url)
        hls.attachMedia(probeEl)
        let settled = false
        const done = (result) => {
          if (settled) return; settled = true
          activeHls.delete(hls)
          activeAudio.delete(probeEl)
          hls.destroy()
          probeEl.removeAttribute('src')
          probeEl.load()
          if (result) cleanupAll() // 胜出：清理其余所有 probe
          resolve(result)
        }
        hls.on(Hls.Events.FRAG_LOADED, () => done({ url, origUrl, index: i, type: 'hls' }))
        hls.on(Hls.Events.ERROR, (_e, d) => { if (d?.fatal) done(null) })
        setTimeout(() => done(null), 10_000)
      })
    }
    return new Promise((resolve) => {
      const probeEl = new Audio()
      activeAudio.add(probeEl)
      probeEl.preload = 'auto'
      probeEl.src = url
      probeEl.load()
      let settled = false
      const done = (result) => {
        if (settled) return; settled = true
        activeAudio.delete(probeEl)
        probeEl.pause()
        probeEl.removeAttribute('src')
        probeEl.load()
        if (result) cleanupAll()
        resolve(result)
      }
      probeEl.addEventListener('canplay', () => done({ url, origUrl, index: i, type: 'direct' }), { once: true })
      probeEl.addEventListener('error', () => done(null), { once: true })
      setTimeout(() => done(null), 10_000)
    })
  })

  // 全局超时
  const result = await Promise.race([
    Promise.any(promises).catch(() => null),
    new Promise((resolve) => setTimeout(() => { cleanupAll(); resolve(null) }, 12_000)),
  ])

  return result // { url, index, type } | null
}

// ========== 多源回退：并发直连探测 → 并发中转探测 ==========
async function tryFallbackUrls() {
  destroyHls()
  const stationId = _fallbackStationId
  const urls = _fallbackUrls.slice(_fallbackIndex)

  if (!urls.length) {
    playerStore.setPlaybackError('无可用音频源。')
    playerStore.togglePlay(false)
    return
  }

  // 并发直连探测，HTTP URL 自动升级 HTTPS
  console.log(`[回退] 并发直连探测 ${urls.length} 个源...`)
  let winner = await probeParallel(urls, stationId, 'direct', { tryHttps: true })
  if (winner) _directProbeWinner = winner

  if (!winner && _directProbeWinner) {
    const proxyUrl = `${API_BASE}/api/proxy/stream?url=${encodeURIComponent(_directProbeWinner.origUrl)}`
    console.log(`[回退] 直连播放失败，直接中转源 #${_directProbeWinner.index + 1}...`)
    winner = { url: proxyUrl, origUrl: _directProbeWinner.origUrl, index: _directProbeWinner.index, type: 'proxy' }
  }

  if (!winner) {
    const proxyUrls = urls.map((u) => `${API_BASE}/api/proxy/stream?url=${encodeURIComponent(u)}`)
    console.log(`[回退] 直连全败，并发中转探测 ${proxyUrls.length} 个源...`)
    winner = await probeParallel(proxyUrls, stationId, 'proxy')
  }

  if (!winner) {
    console.warn('[回退] 所有源（直连+中转）均失败。')
    playerStore.setPlaybackError('所有音频源均不可用，请稍后重试。')
    playerStore.togglePlay(false)
    return
  }

  // 播放成功后才消费 URL（前进 _fallbackIndex），播放失败时保留以便中转重试
  console.log(`[回退] 胜出: ${winner.type} #${winner.index + 1}`)
  try {
    await playUrl(winner.url, stationId, winner.type)
    _fallbackIndex = winner.index + 1
    _directProbeWinner = null
  } catch {
    playerStore.setPlaybackError('音频播放失败，请稍后重试。')
    playerStore.togglePlay(false)
  }
}

function handleAudioError() {
  const stationId = currentStation.value

  if (directStreamStationMap[stationId]) {
    fallbackToProxyStream(stationId)
    return
  }

  if (_fallbackUrls.length > 1 && _fallbackIndex < _fallbackUrls.length && _fallbackStationId === stationId) {
    tryFallbackUrls()
    return
  }

  if (directStreamMode.value === 'proxy') {
    playerStore.setPlaybackError('后端中转音频流连接失败，请稍后重试。')
    playerStore.togglePlay(false)
    return
  }

  if (hasDirectUrl(stationId)) {
    fallbackToProxyStream(stationId)
    return
  }

  playerStore.setPlaybackError('电台音频加载失败，请检查后端代理或稍后重试。')
  playerStore.togglePlay(false)
}

async function fetchAllUrls(stationId) {
  const stName = playerStore.stationMap[stationId]?.name || ''
  try {
    const ctrl = new AbortController()
    const timer = setTimeout(() => ctrl.abort(), 8_000)
    const res = await fetch(
      `${API_BASE}/api/${stationId}/all-urls?name=${encodeURIComponent(stName)}`,
      { signal: ctrl.signal },
    )
    clearTimeout(timer)
    if (res.ok) return await res.json()
  } catch {}
  return []
}

function loadStation(stationId) {
  if (!audioRef.value || !stationId) return

  const playlistUrl = `${API_BASE}/api/${stationId}/playlist.m3u8`

  destroyHls()
  resetAudioSource()
  playerStore.clearPlaybackError()
  playerStore.setLoading(true)
  directStreamMode.value = ''
  _fallbackUrls = []
  _fallbackIndex = 0
  _fallbackStationId = stationId
  _directProbeWinner = null

  // directStreamStationMap 里的电台，用自定义直连地址
  if (directStreamStationMap[stationId]) {
    directStreamMode.value = 'direct'
    audioRef.value.src = directStreamStationMap[stationId].directUrl
    playAudioSafely()
    return
  }

  const directUrl = getDirectUrl(stationId)
  const hasLivePath = playerStore.stationMap[stationId]?.livePath

  if (directUrl && !hasLivePath) {
    directStreamMode.value = 'direct'
    fetchAllUrls(stationId).then((urls) => {
      if (_fallbackStationId === stationId) _fallbackUrls = urls
    })
    audioRef.value.src = directUrl
    playAudioSafely()
    return
  }

  if (!hasLivePath && playerStore.stationMap[stationId]?.directPlay) {
    ;(async () => {
      const urls = await fetchAllUrls(stationId)
      if (currentStation.value !== stationId) return

      _fallbackUrls = urls
      _fallbackIndex = 0

      if (urls.length === 0) {
        fallbackToProxyStream(stationId)
        return
      }

      await tryFallbackUrls()
    })()
    return
  }

  if (Hls?.isSupported()) {
    const canDirectPlay = playerStore.stationMap[stationId]?.directPlay
    let triedDirect = false

    async function startHlsWithFallback() {
      let hlsUrl = playlistUrl

      if (canDirectPlay) {
        try {
          const stName = playerStore.stationMap[stationId]?.name || ''
          const ctrl = new AbortController()
          const timer = setTimeout(() => ctrl.abort(), 5000)
          const res = await fetch(`${API_BASE}/api/${stationId}/stream-url?name=${encodeURIComponent(stName)}`, { signal: ctrl.signal })
          clearTimeout(timer)
          if (res.ok) {
            const { url } = await res.json()
            if (url) { hlsUrl = url; directStreamMode.value = 'direct' }
          }
        } catch {}
      }

      if (currentStation.value !== stationId) return

      const hls = new Hls({
        enableWorker: true,
        lowLatencyMode: true,
        autoStartLoad: true,
        startFragPrefetch: true,
        liveSyncDurationCount: 2,
        liveMaxLatencyDurationCount: 5,
        maxBufferLength: 10,
      })
      hlsRef.value = hls
      hls.loadSource(hlsUrl)
      hls.attachMedia(audioRef.value)

      hls.on(Hls.Events.MANIFEST_PARSED, () => { playAudioSafely() })

      hls.on(Hls.Events.ERROR, (_event, data) => {
        if (!data?.fatal) return
        console.warn('HLS 播放发生致命错误。', data)

        if (canDirectPlay && directStreamMode.value === 'direct' && !triedDirect) {
          triedDirect = true
          directStreamMode.value = 'proxy'
          destroyHls()
          startHlsWithFallback()
          return
        }
        if (directUrl) {
          destroyHls()
          directStreamMode.value = 'direct'
          audioRef.value.src = directUrl
          playAudioSafely()
          return
        }
        if (_fallbackUrls.length > 1 && _fallbackStationId === stationId) {
          destroyHls()
          tryFallbackUrls()
          return
        }
        playerStore.setPlaybackError('HLS 播放发生错误，请稍后重试。')
        playerStore.togglePlay(false)
      })

      if (canDirectPlay) {
        fetchAllUrls(stationId).then((urls) => {
          if (_fallbackStationId === stationId) _fallbackUrls = urls
        })
      }
    }

    startHlsWithFallback()
    return
  }

  if (audioRef.value.canPlayType('application/vnd.apple.mpegurl')) {
    const canDirectPlay = playerStore.stationMap[stationId]?.directPlay

    async function startSafariHls() {
      let hlsUrl = playlistUrl

      if (canDirectPlay) {
        try {
          const stName = playerStore.stationMap[stationId]?.name || ''
          const ctrl = new AbortController()
          const timer = setTimeout(() => ctrl.abort(), 5000)
          const res = await fetch(`${API_BASE}/api/${stationId}/stream-url?name=${encodeURIComponent(stName)}`, { signal: ctrl.signal })
          clearTimeout(timer)
          if (res.ok) {
            const { url } = await res.json()
            if (url) hlsUrl = url
          }
        } catch {}
      }
      if (currentStation.value !== stationId) return

      audioRef.value.src = hlsUrl
      audioRef.value.addEventListener('loadedmetadata', playAudioSafely, { once: true })
    }

    startSafariHls()
    return
  }

  console.warn('当前浏览器不支持 HLS 播放，或 hls.js CDN 尚未加载完成。')
  playerStore.setPlaybackError('当前浏览器不支持 HLS 播放。')
  playerStore.togglePlay(false)
}

onMounted(() => {
  if (audioRef.value) {
    audioRef.value.volume = volume.value
  }
  if (playerStore.isPlaying) {
    loadStation(currentStation.value)
  }
})

watch(currentStation, (stationId) => {
  if (!stationId) {
    destroyHls()
    resetAudioSource()
    return
  }
  if (playerStore.isPlaying) {
    loadStation(stationId)
  }
})

watch(isPlaying, (nextIsPlaying) => {
  if (!audioRef.value) return
  if (nextIsPlaying) {
    if (playerStore.currentIptvChannel) return // IPTV 模式下 AudioEngine 不播
    // 首次播放时音源尚未加载，通过 loadStation 加载并播放
    if (!audioRef.value.src && !hlsRef.value && !directStreamMode.value) {
      loadStation(currentStation.value)
      return
    }
    playAudioSafely()
    return
  }
  audioRef.value.pause()
})

watch(volume, (nextVolume) => {
  if (!audioRef.value) return
  audioRef.value.volume = nextVolume
})

onBeforeUnmount(() => {
  destroyHls()
})
</script>
