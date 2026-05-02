<template>
  <!--
    这是一个无视觉 UI 的全局音频控制器。
    audio 标签保留在页面里，但通过 hidden 隐藏，由 Pinia 状态和 hls.js 来驱动播放。
  -->
  <audio ref="audioRef" hidden playsinline></audio>
</template>

<script setup>
// Vue 的响应式工具。
import { onBeforeUnmount, onMounted, ref, watch } from 'vue'

// storeToRefs 可以把 Pinia state 转成响应式 ref，同时保留状态同步能力。
import { storeToRefs } from 'pinia'

// 引入播放器全局状态仓库。
import { usePlayerStore } from '../stores/player'

// 获取播放器 store 实例。
const playerStore = usePlayerStore()

// 从 store 中取出响应式状态。
const { currentStation, isPlaying, volume } = storeToRefs(playerStore)

// 保存隐藏 audio 元素的 DOM 引用。
const audioRef = ref(null)

// 保存当前 hls.js 实例。
// 切换电台时必须销毁旧实例，否则旧的网络请求和事件监听可能残留。
const hlsRef = ref(null)

// 销毁当前 hls.js 实例。
function destroyHls() {
  // 如果当前没有 hls 实例，直接返回。
  if (!hlsRef.value) {
    return
  }

  // destroy 会移除事件监听、终止加载并释放内部资源。
  hlsRef.value.destroy()

  // 清空引用，避免后续误用已经销毁的实例。
  hlsRef.value = null
}

// 获取 CDN 注入的 hls.js 构造函数。
function getHlsConstructor() {
  // index.html 中通过 CDN 加载 hls.js 后，会在 window 上暴露 Hls。
  return window.Hls
}

// 尝试播放 audio，并处理浏览器自动播放限制。
async function playAudioSafely() {
  // audio 还没挂载完成时，无法播放。
  if (!audioRef.value) {
    return
  }

  try {
    // play() 返回 Promise。
    // 如果浏览器认为这次播放不是由用户手势触发，可能会抛出 DOMException。
    await audioRef.value.play()

    // 播放成功后，同步 Pinia 状态。
    playerStore.togglePlay(true)
  } catch (error) {
    // 自动播放被拦截时，常见错误名是 NotAllowedError。
    // 这里不把它抛出到页面，而是把播放状态同步为暂停，等待用户点击播放按钮。
    if (error instanceof DOMException) {
      console.warn('浏览器阻止了自动播放，需要用户手动点击播放。', error)
    } else {
      console.warn('音频播放失败。', error)
    }

    // 播放失败后同步状态，避免 UI 误显示“正在播放”。
    playerStore.togglePlay(false)
  }
}

// 根据当前电台加载新的 m3u8 播放源。
function loadStation(stationId) {
  // audio 还没有挂载或电台 ID 为空时，直接停止处理。
  if (!audioRef.value || !stationId) {
    return
  }

  // 拼出后端代理后的 m3u8 地址。
  const playlistUrl = `/api/${stationId}/playlist.m3u8`

  // 每次切换电台前，都先销毁旧的 hls 实例。
  destroyHls()

  // 从全局对象读取 hls.js。
  const Hls = getHlsConstructor()

  // 如果浏览器不原生支持 HLS，但 hls.js 支持当前环境，就使用 hls.js。
  if (Hls?.isSupported()) {
    // 创建新的 hls.js 实例。
    const hls = new Hls()

    // 保存实例，方便下次切换电台或组件卸载时销毁。
    hlsRef.value = hls

    // 把 m3u8 地址交给 hls.js 加载。
    hls.loadSource(playlistUrl)

    // 把 hls.js 绑定到隐藏 audio 标签上。
    hls.attachMedia(audioRef.value)

    // 当 m3u8 manifest 解析完成，说明播放器已经知道如何拉取后续切片。
    hls.on(Hls.Events.MANIFEST_PARSED, () => {
      // manifest 准备好后尝试播放。
      playAudioSafely()
    })

    // 监听 hls.js 错误，出现致命错误时同步播放状态。
    hls.on(Hls.Events.ERROR, (_event, data) => {
      if (data?.fatal) {
        console.warn('HLS 播放发生致命错误。', data)
        playerStore.togglePlay(false)
      }
    })

    return
  }

  // Safari 等浏览器可能原生支持 application/vnd.apple.mpegurl。
  if (audioRef.value.canPlayType('application/vnd.apple.mpegurl')) {
    // 原生 HLS 模式下，直接把 m3u8 设置给 audio.src。
    audioRef.value.src = playlistUrl

    // metadata 加载后尝试播放。
    audioRef.value.addEventListener('loadedmetadata', playAudioSafely, { once: true })

    return
  }

  // 如果走到这里，说明当前浏览器既不支持 hls.js，也不支持原生 HLS。
  console.warn('当前浏览器不支持 HLS 播放，或 hls.js CDN 尚未加载完成。')
  playerStore.togglePlay(false)
}

// 组件挂载后，audioRef 才会指向真实 audio 元素。
// 所以默认电台的首次加载放在 onMounted 中执行。
onMounted(() => {
  // 先同步一次音量，保证首次播放就使用 store 中的音量。
  if (audioRef.value) {
    audioRef.value.volume = volume.value
  }

  // 加载当前默认电台。
  loadStation(currentStation.value)
})

// 监听 currentStation 变化。
// 用户切换电台时，会重新加载对应的 m3u8。
watch(currentStation, (stationId) => {
  loadStation(stationId)
})

// 监听播放状态变化。
// UI 按钮后续只需要改变 isPlaying，真正的 audio.play/pause 在这里统一执行。
watch(isPlaying, (nextIsPlaying) => {
  // audio 还没挂载时跳过。
  if (!audioRef.value) {
    return
  }

  // 状态为播放时，尝试播放。
  if (nextIsPlaying) {
    playAudioSafely()
    return
  }

  // 状态为暂停时，暂停 audio。
  audioRef.value.pause()
})

// 监听音量变化，并同步到真实 audio 元素。
watch(
  volume,
  (nextVolume) => {
    // audio 还没挂载时跳过。
    if (!audioRef.value) {
      return
    }

    // audio.volume 的合法范围是 0 到 1。
    audioRef.value.volume = nextVolume
  },
)

// 组件卸载前清理 hls.js 实例。
onBeforeUnmount(() => {
  destroyHls()
})
</script>
