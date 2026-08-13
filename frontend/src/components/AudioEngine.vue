<template>

  <audio ref="audioRef" hidden playsinline></audio>
</template>

<script setup>
import { onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { storeToRefs } from 'pinia'
import Hls from 'hls.js'
import { usePlayerStore } from '../stores/player'
import { API_BASE } from '../apiBase'
import { publicAsset } from '../publicAsset'
import { createRadioAudioEngine } from '../utils/radioAudioEngine'

const playerStore = usePlayerStore()
const { currentStation, isPlaying, volume } = storeToRefs(playerStore)
const audioRef = ref(null)
const hlsRef = ref(null)
const directStreamMode = ref('')

const radioEngine = createRadioAudioEngine({
  audioRef,
  hlsRef,
  directStreamMode,
  playerStore,
  currentStation,
  volume,
  Hls,
  API_BASE,
  publicAsset,
})

// 电台 EPG 更新时自动刷新 MediaSession 显示
watch(
  () => {
    const id = currentStation.value
    return id ? playerStore.stationMap[id]?.subtitle : undefined
  },
  (subtitle) => {
    radioEngine.updateMediaSessionForCurrentSubtitle(subtitle)
  },
)

onMounted(() => {
  if (audioRef.value) {
    audioRef.value.volume = volume.value
  }
  if (playerStore.isPlaying) {
    radioEngine.loadStation(currentStation.value)
  }
})

watch(currentStation, (stationId) => {
  if (!stationId) {
    radioEngine.stopRadioAttempt()
    return
  }
  if (playerStore.isPlaying) {
    radioEngine.loadStation(stationId)
  }
})

watch(
  () => {
    const station = currentStation.value ? playerStore.stationMap[currentStation.value] : null
    return station?.radioSourceId || ''
  },
  (sourceId, previousSourceId) => {
    if (!sourceId || sourceId === previousSourceId || !playerStore.isPlaying) return
    radioEngine.loadStation(currentStation.value)
  },
)

watch(() => playerStore.currentIptvChannel, (channel) => {
  if (channel) radioEngine.stopRadioAttempt()
})

watch(isPlaying, (nextIsPlaying) => {
  if (!audioRef.value) return
  if (nextIsPlaying) {
    if (playerStore.currentIptvChannel) return // IPTV 模式下 AudioEngine 不播
    // 首次播放时音源尚未加载，通过 loadStation 加载并播放
    if (!audioRef.value.src && !hlsRef.value && !directStreamMode.value) {
      radioEngine.loadStation(currentStation.value)
      return
    }
    radioEngine.playAudioSafely()
    return
  }
  radioEngine.pauseCurrentAudio()
})

watch(volume, (nextVolume) => {
  radioEngine.setVolume(nextVolume)
})

onBeforeUnmount(() => {
  radioEngine.stopRadioAttempt()
})
</script>
