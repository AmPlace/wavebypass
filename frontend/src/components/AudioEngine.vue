<template>
  <!--
    这是一个无视觉 UI 的全局音频控制器。
    audio 标签保留在页面里，但通过 hidden 隐藏，由 Pinia 状态和 hls.js 来驱动播放。
  -->
  <audio ref="audioRef" hidden playsinline @error="handleAudioError"></audio>
</template>

<script setup>
// Vue 的响应式工具。
import { onBeforeUnmount, onMounted, ref, watch } from 'vue'

// storeToRefs 可以把 Pinia state 转成响应式 ref，同时保留状态同步能力。
import { storeToRefs } from 'pinia'

// 引入播放器全局状态仓库。
import { usePlayerStore } from '../stores/player'

// 【核心修改】：引入全局公共电台配置！
import { stationMap } from '../config/stations'

// 获取播放器 store 实例。
const playerStore = usePlayerStore()

// 从 store 中取出响应式状态。
const { currentStation, isPlaying, volume } = storeToRefs(playerStore)

// 保存隐藏 audio 元素的 DOM 引用。
const audioRef = ref(null)
const hlsRef = ref(null)

const UFO_DIRECT_STREAM_URL = 'https://stream.rcs.revma.com/em90w4aeewzuv'

const directStreamStationMap = {
  ufo: {
    directUrl: UFO_DIRECT_STREAM_URL,
    proxyUrl: '/api/ufo/stream',
  },
}

const directStreamMode = ref('')

// ==========================================
// 更新系统控制中心和锁屏的播放信息
// ==========================================
function updateSystemMediaSession(stationId) {
  if ('mediaSession' in navigator) {
    // 【核心修改】：直接去全局配置里拿数据，拿不到就用默认的兜底信息
    const meta = stationMap[stationId] || { name: 'WaveBypass', logoUrl: '/pwa-512x512.png' }

    navigator.mediaSession.metadata = new MediaMetadata({
      title: meta.name,            // 歌曲名位置：显示电台名
      artist: 'WaveBypass Radio',  // 歌手位置：显示你的应用名
      album: 'Live Stream',        // 专辑位置
      artwork: [
        { src: meta.logoUrl, sizes: '512x512', type: 'image/png' }
      ]
    })

    // 绑定系统锁屏界面的播放按钮，同步修改 Pinia 状态
    navigator.mediaSession.setActionHandler('play', () => {
      playerStore.togglePlay(true)
    })
    
    // 绑定系统锁屏界面的暂停按钮，同步修改 Pinia 状态
    navigator.mediaSession.setActionHandler('pause', () => {
      playerStore.togglePlay(false)
    })
  }
}

function destroyHls() {
  if (!hlsRef.value) {
    return
  }
  hlsRef.value.destroy()
  hlsRef.value = null
}

function resetAudioSource() {
  if (!audioRef.value) {
    return
  }
  audioRef.value.pause()
  audioRef.value.removeAttribute('src')
  audioRef.value.load()
}

function getHlsConstructor() {
  return window.Hls
}

async function playAudioSafely() {
  if (!audioRef.value) {
    return
  }

  try {
    await audioRef.value.play()

    playerStore.clearPlaybackError()
    playerStore.setLoading(false)
    playerStore.togglePlay(true)
    
    // 只要底层 audio 真正播放成功了，立刻更新系统锁屏信息
    updateSystemMediaSession(currentStation.value)
    
  } catch (error) {
    if (error instanceof DOMException) {
      console.warn('浏览器阻止了自动播放，需要用户手动点击播放。', error)
      playerStore.setPlaybackError('浏览器阻止自动播放，请手动点击播放。')
    } else {
      console.warn('音频播放失败。', error)

      if (directStreamStationMap[currentStation.value] && directStreamMode.value === 'direct') {
        fallbackToProxyStream(currentStation.value)
        return
      }

      playerStore.setPlaybackError('音频播放失败，请稍后重试。')
    }
    playerStore.togglePlay(false)
  }
}

function fallbackToProxyStream(stationId) {
  const streamConfig = directStreamStationMap[stationId]

  if (!audioRef.value || !streamConfig) {
    return
  }

  if (directStreamMode.value === 'proxy') {
    playerStore.setPlaybackError('后端中转音频流连接失败，请稍后重试。')
    playerStore.togglePlay(false)
    return
  }

  directStreamMode.value = 'proxy'
  playerStore.setPlaybackError('直连失败，正在自动切换后端中转。')
  playerStore.setLoading(true)
  audioRef.value.src = streamConfig.proxyUrl
  audioRef.value.load()
  playAudioSafely()
}

function handleAudioError() {
  const stationId = currentStation.value

  if (directStreamStationMap[stationId]) {
    fallbackToProxyStream(stationId)
    return
  }

  playerStore.setPlaybackError('电台音频加载失败，请检查后端代理或稍后重试。')
  playerStore.togglePlay(false)
}

function loadStation(stationId) {
  if (!audioRef.value || !stationId) {
    return
  }

  const playlistUrl = `/api/${stationId}/playlist.m3u8`

  destroyHls()
  resetAudioSource()
  playerStore.clearPlaybackError()
  playerStore.setLoading(true)
  directStreamMode.value = ''

  if (directStreamStationMap[stationId]) {
    const streamConfig = directStreamStationMap[stationId]
    directStreamMode.value = 'direct'
    audioRef.value.src = streamConfig.directUrl
    playAudioSafely()
    return
  }

  const Hls = getHlsConstructor()

  if (Hls?.isSupported()) {
    const hls = new Hls()
    hlsRef.value = hls
    hls.loadSource(playlistUrl)
    hls.attachMedia(audioRef.value)

    hls.on(Hls.Events.MANIFEST_PARSED, () => {
      playAudioSafely()
    })

    hls.on(Hls.Events.ERROR, (_event, data) => {
      if (data?.fatal) {
        console.warn('HLS 播放发生致命错误。', data)
        playerStore.setPlaybackError('HLS 播放发生错误，请稍后重试。')
        playerStore.togglePlay(false)
      }
    })

    return
  }

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
  if (!audioRef.value) {
    return
  }
  if (nextIsPlaying) {
    playAudioSafely()
    return
  }
  audioRef.value.pause()
})

watch(
  volume,
  (nextVolume) => {
    if (!audioRef.value) {
      return
    }
    audioRef.value.volume = nextVolume
  },
)

onBeforeUnmount(() => {
  destroyHls()
})
</script>