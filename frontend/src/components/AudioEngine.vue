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

// 引入静态电台配置（仅用于 MediaSession 等不需要动态更新的场景）
import { stationMap as staticStationMap } from '../config/stations'

// 获取播放器 store 实例
const playerStore = usePlayerStore()

// 从 store 解构响应式状态
const { currentStation, isPlaying, volume } = storeToRefs(playerStore)

// 保存隐藏 audio 元素的 DOM 引用
const audioRef = ref(null)
const hlsRef = ref(null)

// 需要自定义中转地址的电台（如 ufo 用 /stream 而不是 /live）
const directStreamStationMap = {
  ufo: {
    directUrl: playerStore.stationMap.ufo?.directUrl,
    proxyUrl: `${API_BASE}/api/ufo/stream`,
  },
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
    const meta = playerStore.stationMap[stationId] || staticStationMap[stationId] || {}
    const finalLogo = meta.logoUrl || '/logos/default.png'

    try {
      navigator.mediaSession.metadata = new MediaMetadata({
        title: meta.name || '未知频率',
        artist: 'WaveBypass Radio',
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

      // 直连失败：先查 directStreamStationMap（ufo 等有自定义中转地址），再查 store 动态 directUrl
      if (directStreamMode.value === 'direct') {
        if (directStreamStationMap[currentStation.value] || hasDirectUrl(currentStation.value)) {
          fallbackToProxyStream(currentStation.value)
          return
        }
      }

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

// audio 元素 @error 回调：加载失败时触发
function handleAudioError() {
  const stationId = currentStation.value

  // directStreamStationMap 的电台或 store 里有 directUrl 的电台，都走中转回退
  if (directStreamStationMap[stationId] || hasDirectUrl(stationId)) {
    fallbackToProxyStream(stationId)
    return
  }

  playerStore.setPlaybackError('电台音频加载失败，请检查后端代理或稍后重试。')
  playerStore.togglePlay(false)
}

function loadStation(stationId) {
  if (!audioRef.value || !stationId) return

  const playlistUrl = `${API_BASE}/api/${stationId}/playlist.m3u8`

  destroyHls()
  resetAudioSource()
  playerStore.clearPlaybackError()
  playerStore.setLoading(true)
  directStreamMode.value = ''

  // 优先级 1：directStreamStationMap 里的电台（如 ufo），用自定义直连地址
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
    audioRef.value.src = directUrl
    playAudioSafely()
    return
  }

  // 优先级 3：HLS 播放（m3u8 电台，或有 livePath + directUrl 的电台如 ufo）
  if (Hls?.isSupported()) {
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
    hls.loadSource(playlistUrl)
    hls.attachMedia(audioRef.value)

    hls.on(Hls.Events.MANIFEST_PARSED, () => {
      playAudioSafely()
    })

    hls.on(Hls.Events.ERROR, (_event, data) => {
      if (data?.fatal) {
        console.warn('HLS 播放发生致命错误。', data)
        // HLS 失败后，尝试用 directUrl 直连回退（ufo 等同时有 livePath + directUrl 的电台）
        if (directUrl) {
          destroyHls()
          directStreamMode.value = 'direct'
          audioRef.value.src = directUrl
          playAudioSafely()
          return
        }
        playerStore.setPlaybackError('HLS 播放发生错误，请稍后重试。')
        playerStore.togglePlay(false)
      }
    })

    return
  }

  // Safari 原生 HLS 支持
  if (audioRef.value.canPlayType('application/vnd.apple.mpegurl')) {
    audioRef.value.src = playlistUrl
    audioRef.value.addEventListener('loadedmetadata', playAudioSafely, { once: true })
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
