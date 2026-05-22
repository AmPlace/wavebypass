<template>
  <Teleport to="body">
    <Transition name="slide-up">
      <div
        v-show="isPlayerExpanded"
        class="fixed inset-0 z-50 flex flex-col bg-gray-100 dark:bg-neutral-900"
      >
        <!-- 顶部栏 -->
        <div class="flex h-12 shrink-0 items-center justify-between px-4 sm:px-6">
          <button
            type="button"
            class="flex size-10 items-center justify-center rounded-full text-neutral-600 transition-colors hover:bg-neutral-200/60 dark:text-neutral-300 dark:hover:bg-neutral-700/60"
            aria-label="收起播放器"
            @click="playerStore.collapsePlayer()"
          >
            <svg class="size-5" viewBox="0 0 24 24" fill="none"><path d="M19 12H5M12 5l-7 7 7 7" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg>
          </button>

          <div class="w-10"></div>
        </div>

        <!-- 主内容区 -->
        <div class="flex min-h-0 flex-1 flex-col gap-4 px-4 pb-4 sm:px-6 lg:flex-row lg:gap-6 lg:px-8">

          <!-- 左栏：媒体展示区 -->
          <div class="flex flex-1 flex-col items-center justify-center overflow-hidden rounded-3xl bg-gradient-to-br from-rose-400/20 via-fuchsia-400/20 to-amber-300/20 dark:from-rose-500/10 dark:via-fuchsia-500/10 dark:to-amber-500/10 lg:flex-[3]">

            <!-- IPTV 视频播放 -->
            <video
              v-if="isIptvMode"
              ref="iptvVideoRef"
              class="h-full w-full object-contain"
              playsinline
              preload="auto"
              @error="handleIptvError"
            ></video>

            <!-- 电台 logo 展示 -->
            <div v-else class="flex flex-col items-center gap-5 p-8">
              <div
                class="flex size-28 items-center justify-center overflow-hidden rounded-full border border-white/40 bg-white/30 shadow-xl shadow-black/10 backdrop-blur-sm transition-transform duration-500 sm:size-36 dark:border-white/10 dark:bg-white/10"
                :class="{ 'animate-pulse': isLoading }"
              >
                <img
                  v-if="currentStationData?.logoUrl"
                  class="h-full w-full object-cover"
                  :src="currentStationData.logoUrl"
                  :alt="currentStationName"
                />
                <span v-else class="text-3xl font-semibold text-neutral-700 dark:text-neutral-200">
                  {{ currentStationData?.logoText || '?' }}
                </span>
              </div>
              <div class="text-center">
                <p class="text-lg font-semibold text-neutral-900 dark:text-neutral-100">{{ currentStationName }}</p>
                <p class="mt-1 text-sm text-neutral-500 dark:text-neutral-400">{{ statusText }}</p>
              </div>
            </div>
          </div>

          <!-- 右栏：控制面板 -->
          <div class="flex flex-1 flex-col gap-4 overflow-hidden lg:flex-[2]">
            <!-- 播放控制 -->
            <div class="flex flex-col items-center gap-3">
              <p class="text-center text-2xl font-bold text-neutral-900 dark:text-neutral-50">
                {{ currentStationName }}
              </p>
              <p class="text-center text-sm text-neutral-500 dark:text-neutral-400">
                {{ statusText }}
              </p>

              <div class="mt-2 flex items-center gap-6">
                <button
                  type="button"
                  class="flex size-10 items-center justify-center rounded-full text-neutral-400 transition-colors hover:text-neutral-700 dark:hover:text-neutral-200"
                  aria-label="上一个"
                  @click="playPrev"
                >
                  <svg class="size-6" viewBox="0 0 24 24" fill="currentColor"><path d="M6 6h2v12H6zm3.5 6l8.5 6V6z"/></svg>
                </button>

                <button
                  type="button"
                  class="flex size-14 items-center justify-center rounded-full bg-neutral-950 text-white shadow-lg shadow-black/20 transition-all duration-200 hover:scale-105 active:scale-95 dark:bg-white dark:text-black"
                  :aria-label="isPlaying ? '暂停' : '播放'"
                  @click="playerStore.togglePlay()"
                >
                  <svg v-if="isPlaying" class="size-6" viewBox="0 0 24 24" fill="none"><path d="M8 5v14M16 5v14" stroke="currentColor" stroke-width="2.5" stroke-linecap="round"/></svg>
                  <svg v-else class="ml-0.5 size-6" viewBox="0 0 24 24" fill="none"><path d="M8 5.75v12.5c0 .72.78 1.17 1.4.8l10.1-6.25a.94.94 0 0 0 0-1.6L9.4 4.95A.93.93 0 0 0 8 5.75Z" fill="currentColor"/></svg>
                </button>

                <button
                  type="button"
                  class="flex size-10 items-center justify-center rounded-full text-neutral-400 transition-colors hover:text-neutral-700 dark:hover:text-neutral-200"
                  aria-label="下一个"
                  @click="playNext"
                >
                  <svg class="size-6" viewBox="0 0 24 24" fill="currentColor"><path d="M16 6h2v12h-2zM4 18l8.5-6L4 6z"/></svg>
                </button>
              </div>

              <!-- 音量 -->
              <div class="flex items-center gap-3">
                <svg class="size-4 text-neutral-400" viewBox="0 0 24 24" fill="none"><path d="M4 10v4a1 1 0 0 0 1 1h3l4.2 3.15A.5.5 0 0 0 13 17.75V6.25a.5.5 0 0 0-.8-.4L8 9H5a1 1 0 0 0-1 1Z" stroke="currentColor" stroke-width="1.8" stroke-linejoin="round"/><path d="M16 9a4 4 0 0 1 0 6" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/></svg>
                <input
                  class="h-1 w-24 cursor-pointer appearance-none rounded-full bg-neutral-300 accent-neutral-950 outline-none dark:bg-neutral-700 dark:accent-white [&::-moz-range-thumb]:size-3 [&::-moz-range-thumb]:appearance-none [&::-moz-range-thumb]:rounded-full [&::-moz-range-thumb]:border-0 [&::-moz-range-thumb]:bg-neutral-950 dark:[&::-moz-range-thumb]:bg-white [&::-webkit-slider-thumb]:size-3 [&::-webkit-slider-thumb]:appearance-none [&::-webkit-slider-thumb]:rounded-full [&::-webkit-slider-thumb]:bg-neutral-950 dark:[&::-webkit-slider-thumb]:bg-white"
                  type="range"
                  min="0"
                  max="1"
                  step="0.01"
                  :value="volume"
                  aria-label="音量"
                  @input="playerStore.setVolume($event.target.value)"
                />
                <svg class="size-4 text-neutral-400" viewBox="0 0 24 24" fill="none"><path d="M4 10v4a1 1 0 0 0 1 1h3l4.2 3.15A.5.5 0 0 0 13 17.75V6.25a.5.5 0 0 0-.8-.4L8 9H5a1 1 0 0 0-1 1Z" stroke="currentColor" stroke-width="1.8" stroke-linejoin="round"/><path d="M16 9a4 4 0 0 1 0 6M18.5 6.5a7.5 7.5 0 0 1 0 11" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/></svg>
              </div>
            </div>

            <!-- 分割线 -->
            <div class="h-px bg-neutral-200 dark:bg-neutral-700"></div>

            <!-- 频道列表 -->
            <div class="min-h-0 flex-1 overflow-y-auto scrollbar-hide">
              <p class="mb-2 text-xs font-medium text-neutral-400 dark:text-neutral-500">频道列表</p>
              <div class="space-y-1">
                <button
                  v-for="station in channelList"
                  :key="station.id"
                  type="button"
                  class="flex w-full items-center gap-3 rounded-xl px-3 py-2.5 text-left transition-colors hover:bg-neutral-200/60 dark:hover:bg-neutral-700/60"
                  :class="{ 'bg-neutral-200/80 dark:bg-neutral-700/80': currentStation === station.id }"
                  @click="playerStore.switchStation(station.id)"
                >
                  <div class="flex size-9 shrink-0 items-center justify-center overflow-hidden rounded-lg border border-black/5 bg-white text-xs font-semibold text-neutral-600 dark:border-white/10 dark:bg-neutral-800 dark:text-neutral-300">
                    <img v-if="station.logoUrl" class="h-full w-full object-cover" :src="station.logoUrl" :alt="station.name" />
                    <span v-else>{{ station.logoText }}</span>
                  </div>
                  <div class="min-w-0 flex-1">
                    <p class="truncate text-sm font-medium text-neutral-800 dark:text-neutral-200">{{ station.name }}</p>
                    <p v-if="station.subtitle" class="truncate text-xs text-neutral-400 dark:text-neutral-500">{{ station.subtitle }}</p>
                  </div>
                  <div
                    v-if="currentStation === station.id"
                    class="size-2 shrink-0 rounded-full"
                    :class="isPlaying ? 'bg-emerald-500' : 'bg-neutral-300 dark:bg-neutral-600'"
                  ></div>
                </button>
              </div>
            </div>
          </div>
        </div>
      </div>
    </Transition>
  </Teleport>
</template>

<script setup>
import { computed, ref, watch, onBeforeUnmount } from 'vue'
import { storeToRefs } from 'pinia'
import { usePlayerStore } from '../stores/player'

const API_BASE = import.meta.env.VITE_API_BASE_URL || ''

const playerStore = usePlayerStore()
const { isPlayerExpanded, currentStation, isPlaying, isLoading, volume, stationMap, stationList } = storeToRefs(playerStore)

const iptvVideoRef = ref(null)
const iptvHlsRef = ref(null)

const isIptvMode = computed(() => Boolean(playerStore.currentIptvChannel))

const currentStationData = computed(() => stationMap.value[currentStation.value])

const currentStationName = computed(() => {
  if (playerStore.currentIptvChannel) return playerStore.currentIptvChannel.name
  return currentStationData.value?.name || '未选择电台'
})

const statusText = computed(() => {
  if (playerStore.playbackError) return playerStore.playbackError
  if (isLoading.value) return '正在连接'
  if (playerStore.currentIptvChannel) return playerStore.currentIptvChannel.group_name || 'IPTV'
  const subtitle = currentStationData.value?.subtitle
  if (subtitle) return subtitle
  return 'Live'
})

const channelList = computed(() => stationList.value)

function playPrev() {
  const list = stationList.value
  if (!list.length) return
  const idx = list.findIndex((s) => s.id === currentStation.value)
  const prevIdx = idx <= 0 ? list.length - 1 : idx - 1
  playerStore.switchStation(list[prevIdx].id)
}

function playNext() {
  const list = stationList.value
  if (!list.length) return
  const idx = list.findIndex((s) => s.id === currentStation.value)
  const nextIdx = idx >= list.length - 1 ? 0 : idx + 1
  playerStore.switchStation(list[nextIdx].id)
}

// ── IPTV 视频播放 ──

function destroyIptvHls() {
  if (iptvHlsRef.value) {
    iptvHlsRef.value.destroy()
    iptvHlsRef.value = null
  }
}

function resetIptvVideo() {
  if (!iptvVideoRef.value) return
  iptvVideoRef.value.pause()
  iptvVideoRef.value.removeAttribute('src')
  iptvVideoRef.value.load()
}

function isHlsUrl(url) {
  return /\.m3u8(\?|$)/i.test(url)
}

function getProxyUrl(url) {
  return `${API_BASE}/api/iptv/proxy/playlist.m3u8?target_url=${encodeURIComponent(url)}`
}

async function tryPlayIptv(url) {
  destroyIptvHls()
  resetIptvVideo()

  if (isHlsUrl(url) && typeof Hls !== 'undefined' && Hls.isSupported()) {
    const hls = new Hls({
      enableWorker: true, lowLatencyMode: true, autoStartLoad: true,
      startFragPrefetch: true, liveSyncDurationCount: 2,
      liveMaxLatencyDurationCount: 5, maxBufferLength: 10,
    })
    iptvHlsRef.value = hls
    hls.loadSource(url)
    hls.attachMedia(iptvVideoRef.value)
    await new Promise((resolve, reject) => {
      hls.on(Hls.Events.MANIFEST_PARSED, resolve)
      hls.on(Hls.Events.ERROR, (_e, d) => { if (d?.fatal) reject(d) })
      setTimeout(reject, 10_000)
    })
  } else if (iptvVideoRef.value.canPlayType('application/vnd.apple.mpegurl')) {
    iptvVideoRef.value.src = url
    await new Promise((resolve, reject) => {
      iptvVideoRef.value.addEventListener('loadedmetadata', resolve, { once: true })
      iptvVideoRef.value.addEventListener('error', reject, { once: true })
      setTimeout(reject, 10_000)
    })
  } else {
    iptvVideoRef.value.src = url
    iptvVideoRef.value.load()
    await new Promise((resolve, reject) => {
      iptvVideoRef.value.addEventListener('canplay', resolve, { once: true })
      iptvVideoRef.value.addEventListener('error', reject, { once: true })
      setTimeout(reject, 10_000)
    })
  }

  iptvVideoRef.value.volume = volume.value
  await iptvVideoRef.value.play()
  playerStore.clearPlaybackError()
  playerStore.setLoading(false)
  playerStore.togglePlay(true)
}

async function playCurrentIptvUrl() {
  if (!iptvVideoRef.value || !playerStore.currentIptvChannel) return
  const urls = playerStore.iptvUrls
  const idx = playerStore.iptvUrlIndex
  if (idx >= urls.length) return

  const originalUrl = urls[idx].url
  try {
    await tryPlayIptv(originalUrl)
  } catch {
    try {
      await tryPlayIptv(getProxyUrl(originalUrl))
    } catch {
      if (playerStore.iptvFallbackNext()) {
        playCurrentIptvUrl()
      }
    }
  }
}

function handleIptvError() {
  if (playerStore.iptvFallbackNext()) {
    playCurrentIptvUrl()
  }
}

watch(() => playerStore.currentIptvChannel, (ch) => {
  if (ch) playCurrentIptvUrl()
})

watch(isPlaying, (playing) => {
  if (!iptvVideoRef.value || !isIptvMode.value) return
  playing ? iptvVideoRef.value.play().catch(() => {}) : iptvVideoRef.value.pause()
})

watch(volume, (v) => {
  if (iptvVideoRef.value) iptvVideoRef.value.volume = v
})

watch(() => playerStore.iptvUrlIndex, () => {
  if (isIptvMode.value && isPlaying.value) playCurrentIptvUrl()
})

onBeforeUnmount(() => destroyIptvHls())
</script>

<style scoped>
.slide-up-enter-active,
.slide-up-leave-active {
  transition: transform 0.3s cubic-bezier(0.32, 0.72, 0, 1);
}
.slide-up-enter-from {
  transform: translateY(100%);
}
.slide-up-leave-to {
  transform: translateY(100%);
}
</style>
