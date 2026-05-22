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

            <!-- IPTV 视频 -->
            <video
              v-if="isIptvMode"
              ref="iptvVideoRef"
              class="h-full w-full object-contain"
              playsinline
              preload="auto"
              :muted="iptvMuted"
              @error="handleIptvError"
              @playing="onVideoEvent('playing')"
              @pause="onVideoEvent('pause')"
              @waiting="onVideoEvent('waiting')"
              @stalled="onVideoStalled"
              @timeupdate="onVideoTimeUpdate"
            ></video>

            <!-- 电台 logo 展示 -->
            <div v-if="!isIptvMode" class="flex flex-col items-center gap-5 p-8">
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

              <!-- 音量 / 静音（iOS 不支持音量条，改用静音切换按钮）-->
              <div class="flex items-center gap-3">
                <!-- iOS: 静音切换按钮 -->
                <button
                  v-if="isIOS && isIptvMode"
                  type="button"
                  class="flex size-10 items-center justify-center rounded-full text-neutral-400 transition-colors hover:text-neutral-700 dark:hover:text-neutral-200"
                  :aria-label="iptvMuted ? '取消静音' : '静音'"
                  @click="toggleIptvMute()"
                >
                  <!-- 静音图标 -->
                  <svg v-if="iptvMuted" class="size-5" viewBox="0 0 24 24" fill="none">
                    <path d="M4 10v4a1 1 0 0 0 1 1h3l4.2 3.15A.5.5 0 0 0 13 17.75V6.25a.5.5 0 0 0-.8-.4L8 9H5a1 1 0 0 0-1 1Z" stroke="currentColor" stroke-width="1.8" stroke-linejoin="round"/>
                    <path d="m22 2-20 20" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/>
                  </svg>
                  <!-- 有声音图标 -->
                  <svg v-else class="size-5" viewBox="0 0 24 24" fill="none">
                    <path d="M4 10v4a1 1 0 0 0 1 1h3l4.2 3.15A.5.5 0 0 0 13 17.75V6.25a.5.5 0 0 0-.8-.4L8 9H5a1 1 0 0 0-1 1Z" stroke="currentColor" stroke-width="1.8" stroke-linejoin="round"/>
                    <path d="M16 9a4 4 0 0 1 0 6M18.5 6.5a7.5 7.5 0 0 1 0 11" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/>
                  </svg>
                </button>

                <!-- 非 iOS: 音量滑动条 -->
                <template v-if="!isIOS || !isIptvMode">
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
                </template>
              </div>
            </div>

            <!-- 分割线 -->
            <div class="h-px bg-neutral-200 dark:bg-neutral-700"></div>

            <!-- 频道列表 -->
            <div class="min-h-0 flex-1 overflow-y-auto scrollbar-hide">
              <p class="mb-2 text-xs font-medium text-neutral-400 dark:text-neutral-500">频道列表</p>
              <div class="space-y-1">
                <!-- 电台列表 -->
                <template v-if="!isIptvMode">
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
                </template>

                <!-- IPTV 列表 -->
                <template v-else>
                  <button
                    v-for="ch in iptvChannelList"
                    :key="ch.name"
                    type="button"
                    :disabled="isIptvUntested(ch)"
                    class="flex w-full items-center gap-3 rounded-xl px-3 py-2.5 text-left transition-colors hover:bg-neutral-200/60 dark:hover:bg-neutral-700/60"
                    :class="{
                      'bg-neutral-200/80 dark:bg-neutral-700/80': isCurrentIptv(ch),
                      'cursor-not-allowed opacity-40 hover:bg-transparent dark:hover:bg-transparent': isIptvUntested(ch),
                    }"
                    @click="playerStore.playIptvChannel(ch)"
                  >
                    <div class="flex size-9 shrink-0 items-center justify-center overflow-hidden rounded-lg border border-black/5 bg-white text-xs font-semibold text-neutral-600 dark:border-white/10 dark:bg-neutral-800 dark:text-neutral-300">
                      <img v-if="ch.logo_url" class="h-full w-full object-cover" :src="ch.logo_url" :alt="ch.name" />
                      <span v-else>{{ ch.name.slice(0, 2) }}</span>
                    </div>
                    <div class="min-w-0 flex-1">
                      <p class="truncate text-sm font-medium text-neutral-800 dark:text-neutral-200">{{ ch.name }}</p>
                      <p v-if="ch.group_name" class="truncate text-xs text-neutral-400 dark:text-neutral-500">{{ ch.group_name }}</p>
                    </div>
                    <div
                      v-if="isCurrentIptv(ch)"
                      class="size-2 shrink-0 rounded-full"
                      :class="isPlaying ? 'bg-emerald-500' : 'bg-neutral-300 dark:bg-neutral-600'"
                    ></div>
                  </button>
                </template>
              </div>
            </div>
          </div>
        </div>
      </div>
    </Transition>
  </Teleport>
</template>

<script setup>
import { computed, ref, watch, onBeforeUnmount, onMounted, nextTick } from 'vue'
import { storeToRefs } from 'pinia'
import { usePlayerStore } from '../stores/player'
import { fetchAggregatedChannels } from '../api/iptv'

const API_BASE = import.meta.env.VITE_API_BASE_URL || ''

const playerStore = usePlayerStore()
const { isPlayerExpanded, currentStation, isPlaying, isLoading, volume, stationMap, stationList } = storeToRefs(playerStore)

const iptvVideoRef = ref(null)
const iptvHlsRef = ref(null)

const isIOS = /iPad|iPhone|iPod/.test(navigator.userAgent) ||
  (navigator.platform === 'MacIntel' && navigator.maxTouchPoints > 1)
const iptvMuted = ref(isIOS)  // iOS 静音绕过自动播放限制

function toggleIptvMute() {
  if (!iptvVideoRef.value) return
  iptvMuted.value = !iptvMuted.value
  iptvVideoRef.value.muted = iptvMuted.value
}  // 跟踪当前播放的 URL，防止重复设置

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

const iptvChannelList = ref([])

async function loadIptvChannels() {
  try {
    const data = await fetchAggregatedChannels()
    iptvChannelList.value = data.channels || []
  } catch (e) {
    console.error('加载 IPTV 频道失败:', e)
  }
}

function isCurrentIptv(ch) {
  const current = playerStore.currentIptvChannel
  return current && current.name === ch.name
}

function isIptvUntested(ch) {
  return ch.urls.every(u => u.is_working === -1)
}

// 切换到 IPTV 模式时加载频道列表
watch(isIptvMode, (isIptv) => {
  if (isIptv && !iptvChannelList.value.length) loadIptvChannels()
})

onMounted(() => {
  if (isIptvMode.value) loadIptvChannels()
})

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

function canUseHls() {
  if (typeof Hls === 'undefined') return false
  if (Hls.isSupported()) return true
  if (window.ManagedMediaSource) {
    console.log('[IPTV] 使用 ManagedMediaSource (hls.js on iOS)')
    return true
  }
  console.log('[IPTV] 无 MSE/MMS，回退到原生 HLS')
  return false
}

function isHlsUrl(url) {
  return /\.m3u8(\?|$)/i.test(url)
}

function getProxyUrl(url) {
  return `${API_BASE}/api/iptv/proxy/playlist.m3u8?target_url=${encodeURIComponent(url)}`
}

async function tryPlayIptv(url, usingProxy = false) {
  destroyIptvHls()
  resetIptvVideo()
  console.log(`[START] ${usingProxy ? '(proxy) ' : ''}${url.slice(0, 80)}...`)

  try {
    if (isHlsUrl(url) && canUseHls()) {
      const hls = new Hls({
        enableWorker: true,
        lowLatencyMode: false,
        liveDurationInfinity: true,
        liveSyncDuration: 20,
        liveMaxLatencyDuration: 55,
        liveSyncOnStallIncrease: 2,
        maxLiveSyncPlaybackRate: 1,
        nudgeOffset: 0.1,
        nudgeMaxRetry: 3,
        maxBufferLength: 30,
        maxBufferHole: 0.5,
      })
      iptvHlsRef.value = hls
      hls.loadSource(url)
      hls.attachMedia(iptvVideoRef.value)

      // 直播状态监控
      hls.on(Hls.Events.LEVEL_LOADED, (_e, data) => {
        const d = data.details
        console.log(`[LEVEL] frags:${d.fragments.length} live:${d.live} dur:${d.totalduration?.toFixed(1)}s seq:${d.startSN}`)
      })
      hls.on(Hls.Events.FRAG_LOADED, (_e, data) => {
        console.log(`[FRAG] ${data.frag?.sn} loaded (${(data.frag?.stats?.loaded/1024).toFixed(0)}KB)`)
      })
      hls.on(Hls.Events.FRAG_BUFFERED, (_e, data) => {
        const v = iptvVideoRef.value
        const buf = v?.buffered?.length ? (v.buffered.end(v.buffered.length-1) - v.currentTime).toFixed(1) : '?'
        console.log(`[BUF] sn:${data.frag?.sn} ahead:${buf}s cur:${v?.currentTime?.toFixed(1)}s`)
      })
      iptvVideoRef.value.addEventListener('seeking', () => {
        console.log(`[SEEK] → ${iptvVideoRef.value.currentTime.toFixed(2)}s`)
      })
      iptvVideoRef.value.addEventListener('stalled', () => {
        const v = iptvVideoRef.value
        console.log(`[STALLED] ready:${v?.readyState} cur:${v?.currentTime?.toFixed(1)}s buf:${v?.buffered?.length ? (v.buffered.end(v.buffered.length-1) - v.currentTime).toFixed(1) : 0}s`)
      })

      hls.on(Hls.Events.ERROR, (_e, d) => {
        console.log(`[ERR] ${d.details} fatal:${d.fatal} type:${d.type}`)
        // bufferStalledError 在 buffer 充足时忽略
        if (!d.fatal && (d.details === 'bufferStalledError' || String(d.details).includes('Stall'))) {
          const v = iptvVideoRef.value
          const ahead = v?.buffered?.length
            ? v.buffered.end(v.buffered.length - 1) - v.currentTime
            : 0
          console.log(`[IGNORE?] buf:${ahead.toFixed(1)}s details:${d.details}`)
          if (ahead > 12) { return }
        }
        // 网络错误立即切代理
        if (d.type === Hls.ErrorTypes.NETWORK_ERROR && !usingProxy) {
          console.log('[FALLBACK] 直连失败，切到代理')
          hls.destroy()
          const proxyUrl = `${API_BASE}/api/iptv/proxy/wide.m3u8?proxy_ts=1&target_url=${encodeURIComponent(url)}`
          tryPlayIptv(proxyUrl, true)
          return
        }
        if (d.fatal) {
          const now = Date.now()
          if (now - _lastRecoveryTime < 3000) return
          _lastRecoveryTime = now
          if (d.type === Hls.ErrorTypes.MEDIA_ERROR && _recoveryCount < 3) {
            _recoveryCount++
            console.log(`[RECOVER] attempt ${_recoveryCount}`)
            hls.recoverMediaError()
          } else {
            _recoveryCount = 0
            console.log('[REBUILD] ' + (forceProxyTs ? 'retry proxy' : 'switch to proxy'))
            hls.destroy()
            // 网络错误时强制走代理
            tryPlayIptv(url, d.type === Hls.ErrorTypes.NETWORK_ERROR ? true : forceProxyTs)
          }
        }
      })

      await new Promise((resolve, reject) => {
        hls.on(Hls.Events.MANIFEST_PARSED, resolve)
        setTimeout(() => reject(new Error('HLS 加载超时 (10s)')), 10_000)
      })
    } else if (iptvVideoRef.value.canPlayType('application/vnd.apple.mpegurl')) {
      iptvVideoRef.value.src = url
      await new Promise((resolve, reject) => {
        iptvVideoRef.value.addEventListener('loadedmetadata', resolve, { once: true })
        iptvVideoRef.value.addEventListener('error', () => {
          const err = iptvVideoRef.value?.error
          reject(new Error(`Video error: code=${err?.code} msg=${err?.message}`))
        }, { once: true })
        setTimeout(() => reject(new Error('原生 HLS 加载超时 (10s)')), 10_000)
      })
    } else {
      iptvVideoRef.value.src = url
      iptvVideoRef.value.load()
      await new Promise((resolve, reject) => {
        iptvVideoRef.value.addEventListener('canplay', resolve, { once: true })
        iptvVideoRef.value.addEventListener('error', () => {
          const err = iptvVideoRef.value?.error
          reject(new Error(`Video error: code=${err?.code} msg=${err?.message}`))
        }, { once: true })
        setTimeout(() => reject(new Error('直连流加载超时 (10s)')), 10_000)
      })
    }

    iptvVideoRef.value.volume = volume.value
    await iptvVideoRef.value.play()
  } catch {
    // play 失败也继续
  } finally {
    playerStore.clearPlaybackError()
    playerStore.setLoading(false)
    playerStore.togglePlay(true)
  }
}

async function playCurrentIptvUrl() {
  if (!iptvVideoRef.value || !playerStore.currentIptvChannel) return
  const urls = playerStore.iptvUrls
  const idx = playerStore.iptvUrlIndex
  if (idx >= urls.length) return

  const originalUrl = urls[idx].url
  console.log(`[START] ${originalUrl.slice(0, 60)}...`)
  try {
    await tryPlayIptv(originalUrl)
  } catch (e) {
    console.warn('[IPTV] 失败:', e?.message)
    playerStore.setPlaybackError(`失败: ${e?.message}`)
    if (playerStore.iptvFallbackNext()) {
      playCurrentIptvUrl()
    }
  }
}

function handleIptvError() {
  console.warn('[IPTV] video error event triggered')
  if (playerStore.iptvFallbackNext()) {
    playCurrentIptvUrl()
  }
}

let _stallRecovering = false
let _lastRecoveryTime = 0
let _recoveryCount = 0

function doRecovery(v) {
  _stallRecovering = true
  // 轻量 nudge：回退一小段位置触发浏览器重新拉数据
  // 不用 load()，避免重建整个播放管线导致白屏
  const wasMuted = v.muted
  v.muted = true
  v.currentTime = Math.max(v.currentTime - 0.5, v.currentTime - 1)
  v.play().then(() => {
    setTimeout(() => {
      v.muted = wasMuted
      iptvMuted.value = wasMuted
    }, 500)
    _stallRecovering = false
  }).catch(() => {
    _stallRecovering = false
  })
}

function onVideoTimeUpdate() {}

function onVideoStalled() {
  const v = iptvVideoRef.value
  if (!v || v.paused || _stallRecovering) return
  if (Date.now() - _lastRecoveryTime < 10_000) return
  console.warn('[IPTV] stalled 兜底恢复')
  _lastRecoveryTime = Date.now()
  doRecovery(v)
}

function onVideoEvent(evt) {
  if (evt === 'playing') {
    playerStore.setLoading(false)
    playerStore.togglePlay(true)
  }
}

// 注册 video 元素到 store，同步 muted 状态
watch(iptvVideoRef, (el) => {
  playerStore.iptvVideoEl = el
  if (el) el.muted = iptvMuted.value
})

// IptvHome 已同步设置 src + play，这里跳过
watch(() => playerStore.currentIptvChannel, async (ch) => {
  if (ch) {
    await nextTick()
    if (iptvVideoRef.value) playCurrentIptvUrl()
  }
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
