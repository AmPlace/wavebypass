<template>
  <!--
    这是一个无视觉 UI 的全局音频控制器。
    audio 标签保留在页面里，但通过 hidden 隐藏，由 Pinia 状态和 hls.js 来驱动播放。
  -->
  <audio ref="audioRef" hidden playsinline @error="handleAudioError"></audio>
</template>

<script setup>
// 后端 API 基础地址，为空时使用当前域名
const API_BASE = import.meta.env.VITE_API_BASE_URL || ''

// Vue 响应式工具
import { onBeforeUnmount, onMounted, ref, watch } from 'vue'

// storeToRefs 把 Pinia state 转为响应式 ref
import { storeToRefs } from 'pinia'

// 引入播放器全局状态仓库
import { usePlayerStore } from '../stores/player'

// 获取播放器 store 实例
const playerStore = usePlayerStore()

// 从 store 解构响应式状态
const { currentStation, isPlaying, volume } = storeToRefs(playerStore)

// 保存隐藏 audio 元素的 DOM 引用
const audioRef = ref(null)
const hlsRef = ref(null)

// 需要自定义中转地址的电台
const directStreamStationMap = {
}

// 当前播放模式：direct = 直连，proxy = 后端中转
const directStreamMode = ref('')

// 从 store 的 stationMap 动态查找 directUrl，支持静态电台 + Radio Browser 动态电台
function getDirectUrl(stationId) {
  return playerStore.stationMap[stationId]?.directUrl
}

// 判断电台是否有 directUrl（支持动态电台）
function hasDirectUrl(stationId) {
  return Boolean(getDirectUrl(stationId))
}

// 更新系统控制中心和锁屏的播放信息
function updateSystemMediaSession(stationId) {
  if ('mediaSession' in navigator) {
    const meta = playerStore.stationMap[stationId] || {}
    const finalLogo = meta.logoUrl || '/logos/default.png'

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

// 云听电台 EPG 更新时自动刷新 MediaSession 显示
// playerStore.updateStationEpg() 会更新 stationMap[id].subtitle，触发此 watcher
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
// 当前 station 的所有候选 URL 和已尝试索引
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

// 直连失败后回退到后端中转
function fallbackToProxyStream(stationId) {
  if (!audioRef.value) return

  // 已经是中转模式还失败，说明两种都不行，放弃
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

// ========== 工具函数 ==========
function isHlsUrl(url) {
  return /\.m3u8(\?|$)/i.test(url)
}

// 播放指定 URL：自动识别 HLS/直连，设置播放器并播放
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

// ========== 并发探测（三重防护） ==========
// 1. 可达性预检：fetch(mode:'no-cors') 快速过滤不可达的 URL（iOS Safari 不会卡死）
// 2. 资源泄露清理：胜出后立即销毁所有失败者的 Audio/HLS 实例
// 3. HLS 防假解析：等 FRAG_LOADED（第一个切片真正下载成功），而非仅 MANIFEST_PARSED

// 将 http:// 升级为 https://（已有 https 或非 http 开头的 URL 不变）
function upgradeHttps(url) {
  return url.startsWith('http://') ? 'https://' + url.slice(7) : url
}

// 快速可达性检查：fetch HEAD(no-cors)，不可达的直接排除
// iOS Safari 不阻塞 fetch，只阻塞 <audio> preload，所以这个在 iOS 上也能正常工作
// tryHttps: true 时对 http:// URL 先升级为 https:// 尝试
// 返回 [testUrl, origUrl] 元组数组，testUrl 是实际测试的 URL（可能已升级 https），origUrl 是原始 URL
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

  // 第一步：快速过滤不可达 URL（~2-3s，并行 HEAD，不下载数据）
  // tryHttps 时对 http:// URL 升级为 https:// 再测试，通过的 reachable 列表已是 https
  const reachable = await filterReachable(urls, { tryHttps })
  if (!reachable.length) return null
  console.log(`[探测] ${reachable.length}/${urls.length} 个源可达${tryHttps ? '（已升级 HTTPS）' : ''}`)

  // 第二步：并发加载可达 URL，第一个真正可播的胜出
  // 用 Set 跟踪活跃的 probe，胜出后立即清理所有失败者（防资源泄露）
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
      // HLS 探测：等 FRAG_LOADED（第一个切片真正下载成功），防 MANIFEST_PARSED 假解析
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
        // 等第一个 TS 切片真正加载成功（不只是 m3u8 解析成功）
        hls.on(Hls.Events.FRAG_LOADED, () => done({ url, origUrl, index: i, type: 'hls' }))
        hls.on(Hls.Events.ERROR, (_e, d) => { if (d?.fatal) done(null) })
        setTimeout(() => done(null), 10_000)
      })
    }
    // 直连流探测：<audio preload=auto>，canplay 表示可播
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

  // 全局超时兜底
  const result = await Promise.race([
    Promise.any(promises).catch(() => null),
    new Promise((resolve) => setTimeout(() => { cleanupAll(); resolve(null) }, 12_000)),
  ])

  return result // { url, index, type } | null
}

// ========== 多源回退：并发直连探测 → 并发中转探测 ==========
// 以 HitFM 为例：
//   阶段1：并发探测 [主源CDN, 云听m3u8, myradio mp3, RB mp3] → 最快成功的胜出
//   阶段1 全败 → 阶段2：并发探测 [主源中转, 云听中转, myradio中转, RB中转]
//   阶段2 全败 → 报错
async function tryFallbackUrls() {
  destroyHls()
  const stationId = _fallbackStationId
  const urls = _fallbackUrls.slice(_fallbackIndex)

  if (!urls.length) {
    playerStore.setPlaybackError('无可用音频源。')
    playerStore.togglePlay(false)
    return
  }

  // 阶段 1：并发直连探测，HTTP URL 自动升级 HTTPS
  // 有的电台源已有 SSL 但后端返回的是 http://，升级后可省掉中转流量
  console.log(`[回退] 并发直连探测 ${urls.length} 个源...`)
  let winner = await probeParallel(urls, stationId, 'direct', { tryHttps: true })
  if (winner) _directProbeWinner = winner

  // 阶段 2a：直连探测成功但播放失败后重试 → 直接用原 URL 走中转，不再重复探测
  if (!winner && _directProbeWinner) {
    const proxyUrl = `${API_BASE}/api/proxy/stream?url=${encodeURIComponent(_directProbeWinner.origUrl)}`
    console.log(`[回退] 直连播放失败，直接中转源 #${_directProbeWinner.index + 1}...`)
    winner = { url: proxyUrl, origUrl: _directProbeWinner.origUrl, index: _directProbeWinner.index, type: 'proxy' }
  }

  // 阶段 2b：直连全败 → 并发中转探测
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

// audio 元素 @error 回调：加载失败时触发
function handleAudioError() {
  const stationId = currentStation.value

  // directStreamStationMap 的电台：直接走自定义中转
  if (directStreamStationMap[stationId]) {
    fallbackToProxyStream(stationId)
    return
  }

  // 有多源回退 URL 时，尝试下一个
  if (_fallbackUrls.length > 1 && _fallbackIndex < _fallbackUrls.length && _fallbackStationId === stationId) {
    tryFallbackUrls()
    return
  }

  // 已经是中转模式还失败
  if (directStreamMode.value === 'proxy') {
    playerStore.setPlaybackError('后端中转音频流连接失败，请稍后重试。')
    playerStore.togglePlay(false)
    return
  }

  // 有 directUrl 的电台（RB 等），回退后端中转
  if (hasDirectUrl(stationId)) {
    fallbackToProxyStream(stationId)
    return
  }

  playerStore.setPlaybackError('电台音频加载失败，请检查后端代理或稍后重试。')
  playerStore.togglePlay(false)
}

// 从后端获取电台所有候选 URL（不带探测，由前端并发探测）
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

  // 优先级 1：directStreamStationMap 里的电台，用自定义直连地址
  if (directStreamStationMap[stationId]) {
    directStreamMode.value = 'direct'
    audioRef.value.src = directStreamStationMap[stationId].directUrl
    playAudioSafely()
    return
  }

  // 优先级 2：store 的 stationMap 里有 directUrl 的电台（含 Radio Browser 动态电台）
  // 没有 livePath 的用 <audio> 直连，有 livePath 的优先尝试 HLS
  const directUrl = getDirectUrl(stationId)
  const hasLivePath = playerStore.stationMap[stationId]?.livePath

  if (directUrl && !hasLivePath) {
    directStreamMode.value = 'direct'
    // 预取回退 URL（后台加载，失败时已就绪）
    fetchAllUrls(stationId).then((urls) => {
      if (_fallbackStationId === stationId) _fallbackUrls = urls
    })
    audioRef.value.src = directUrl
    playAudioSafely()
    return
  }

  // 优先级 3：directPlay 电台（myradio、云听、静态台等，无 directUrl 也无 livePath）
  // 从后端获取所有候选 URL，逐个尝试（直连→中转），全部失败报错
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

      // 复用 tryFallbackUrls 的直连→中转逻辑
      await tryFallbackUrls()
    })()
    return
  }

  // 优先级 4：HLS 播放（m3u8 电台，或有 livePath + directUrl 的电台）
  if (Hls?.isSupported()) {
    const canDirectPlay = playerStore.stationMap[stationId]?.directPlay
    let triedDirect = false

    async function startHlsWithFallback() {
      let hlsUrl = playlistUrl

      // directPlay 电台：先尝试直连 CDN 的 m3u8，节省后端流量
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

        // directPlay 直连失败 → 回退后端代理重试一次
        if (canDirectPlay && directStreamMode.value === 'direct' && !triedDirect) {
          triedDirect = true
          directStreamMode.value = 'proxy'
          destroyHls()
          startHlsWithFallback()
          return
        }
        // 同时有 directUrl 的电台 → 直连 mp3 回退
        if (directUrl) {
          destroyHls()
          directStreamMode.value = 'direct'
          audioRef.value.src = directUrl
          playAudioSafely()
          return
        }
        // 尝试多源回退 URL（跨源：云听/myradio/RB）
        if (_fallbackUrls.length > 1 && _fallbackStationId === stationId) {
          destroyHls()
          tryFallbackUrls()
          return
        }
        playerStore.setPlaybackError('HLS 播放发生错误，请稍后重试。')
        playerStore.togglePlay(false)
      })

      // 预取回退 URL（后台加载，HLS 失败时已就绪）
      if (canDirectPlay) {
        fetchAllUrls(stationId).then((urls) => {
          if (_fallbackStationId === stationId) _fallbackUrls = urls
        })
      }
    }

    startHlsWithFallback()
    return
  }

  // Safari 原生 HLS 支持（无 hls.js 时的降级路径）
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
  loadStation(currentStation.value)
})

watch(currentStation, (stationId) => {
  loadStation(stationId)
})

watch(isPlaying, (nextIsPlaying) => {
  if (!audioRef.value) return
  if (nextIsPlaying) {
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
