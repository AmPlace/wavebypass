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
          <div
            class="flex flex-1 flex-col items-center justify-center overflow-hidden rounded-3xl lg:flex-[3]"
            :class="isIptvMode ? 'bg-transparent' : 'bg-gradient-to-br from-rose-400/20 via-fuchsia-400/20 to-amber-300/20 dark:from-rose-500/10 dark:via-fuchsia-500/10 dark:to-amber-500/10'"
          >

            <!-- IPTV 视频 -->
            <video
              v-if="isIptvMode"
              ref="iptvVideoRef"
              class="w-full h-full object-contain rounded-lg"
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
                  @error="useDefaultLogo"
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
              <div class="flex flex-wrap items-center justify-center gap-2 sm:gap-3">
                <!-- iOS: 静音切换按钮 -->
                <button
                  v-if="isIOS && isIptvMode"
                  type="button"
                  class="flex size-10 shrink-0 items-center justify-center rounded-full text-neutral-400 transition-colors hover:text-neutral-700 dark:hover:text-neutral-200"
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
                  <div class="flex min-w-0 shrink items-center gap-2">
                    <svg class="size-4 shrink-0 text-neutral-400" viewBox="0 0 24 24" fill="none"><path d="M4 10v4a1 1 0 0 0 1 1h3l4.2 3.15A.5.5 0 0 0 13 17.75V6.25a.5.5 0 0 0-.8-.4L8 9H5a1 1 0 0 0-1 1Z" stroke="currentColor" stroke-width="1.8" stroke-linejoin="round"/><path d="M16 9a4 4 0 0 1 0 6" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/></svg>
                    <input
                      class="h-1 w-20 cursor-pointer appearance-none rounded-full bg-neutral-300 accent-neutral-950 outline-none sm:w-24 dark:bg-neutral-700 dark:accent-white [&::-moz-range-thumb]:size-3 [&::-moz-range-thumb]:appearance-none [&::-moz-range-thumb]:rounded-full [&::-moz-range-thumb]:border-0 [&::-moz-range-thumb]:bg-neutral-950 dark:[&::-moz-range-thumb]:bg-white [&::-webkit-slider-thumb]:size-3 [&::-webkit-slider-thumb]:appearance-none [&::-webkit-slider-thumb]:rounded-full [&::-webkit-slider-thumb]:bg-neutral-950 dark:[&::-webkit-slider-thumb]:bg-white"
                      type="range"
                      min="0"
                      max="1"
                      step="0.01"
                      :value="volume"
                      aria-label="音量"
                      @input="playerStore.setVolume($event.target.value)"
                    />
                    <svg class="size-4 shrink-0 text-neutral-400" viewBox="0 0 24 24" fill="none"><path d="M4 10v4a1 1 0 0 0 1 1h3l4.2 3.15A.5.5 0 0 0 13 17.75V6.25a.5.5 0 0 0-.8-.4L8 9H5a1 1 0 0 0-1 1Z" stroke="currentColor" stroke-width="1.8" stroke-linejoin="round"/><path d="M16 9a4 4 0 0 1 0 6M18.5 6.5a7.5 7.5 0 0 1 0 11" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/></svg>
                  </div>
                </template>

                <!-- 全屏按钮 -->
                <button
                  type="button"
                  class="flex size-10 shrink-0 items-center justify-center rounded-full text-neutral-400 transition-colors hover:text-neutral-700 dark:hover:text-neutral-200"
                  aria-label="全屏"
                  @click="toggleFullscreen"
                >
                  <svg class="size-5" viewBox="0 0 24 24" fill="none">
                    <path d="M7 14H5v5h5v-2H7v-3zm-2-4h2V7h3V5H5v5zm12 7h-3v2h5v-5h-2v3zM14 5v2h3v3h2V5h-5z" fill="currentColor"/>
                  </svg>
                </button>

                <div v-if="isIptvMode && iptvSourceOptions.length" class="relative">
                  <button
                    ref="sourceButtonRef"
                    type="button"
                    class="relative flex size-10 shrink-0 items-center justify-center rounded-full text-neutral-400 transition-colors hover:text-neutral-700 dark:hover:text-neutral-200"
                    :aria-expanded="sourceMenuOpen"
                    aria-controls="iptv-source-menu"
                    aria-label="切换播放源"
                    @click.stop="toggleSourceMenu"
                  >
                    <svg class="size-5" viewBox="0 0 24 24" fill="none" aria-hidden="true">
                      <path d="M6 7.5h12M6 12h12M6 16.5h8" stroke="currentColor" stroke-width="1.9" stroke-linecap="round"/>
                      <path d="M17 15.25 19.25 17.5 17 19.75" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round"/>
                    </svg>
                    <span
                      class="absolute right-1.5 top-1.5 size-2 rounded-full"
                      :class="currentIptvSourceStatusClass"
                    ></span>
                  </button>
                </div>
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
                      <img v-if="station.logoUrl" class="h-full w-full object-cover" :src="station.logoUrl" :alt="station.name" @error="useDefaultLogo" />
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
                      <img v-if="ch.logo_url" class="h-full w-full object-cover" :src="ch.logo_url" :alt="ch.name" @error="useDefaultLogo" />
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

  <Teleport to="body">
    <Transition name="fade">
      <div
        v-show="sourceMenuOpen"
        id="iptv-source-menu"
        class="fixed z-[80] overflow-hidden rounded-2xl border border-neutral-200 bg-white/95 p-1.5 text-left shadow-xl shadow-black/10 backdrop-blur dark:border-white/10 dark:bg-neutral-800/95"
        :style="sourceMenuStyle"
        @click.stop
      >
        <div class="flex items-center justify-between px-2.5 py-2">
          <span class="text-xs font-medium text-neutral-400 dark:text-neutral-500">播放源</span>
          <span class="text-xs text-neutral-400 dark:text-neutral-500">{{ currentIptvSourceLabel }}</span>
        </div>
        <div class="overscroll-contain overflow-y-auto [-webkit-overflow-scrolling:touch]" :style="{ maxHeight: sourceMenuListMaxHeight }">
          <button
            v-for="source in iptvSourceOptions"
            :key="`${source.index}-${source.url}`"
            type="button"
            class="flex w-full items-center gap-2.5 rounded-xl px-2.5 py-2 text-left transition-colors hover:bg-neutral-100 dark:hover:bg-neutral-700/70"
            :class="{ 'bg-neutral-100 dark:bg-neutral-700/70': source.active }"
            @click="switchIptvSource(source.index)"
          >
            <span
              class="size-2.5 shrink-0 rounded-full"
              :class="source.statusClass"
            ></span>
            <span
              class="flex h-6 w-10 shrink-0 items-center justify-center rounded-full text-[0.68rem] font-medium"
              :class="source.type === 'proxy'
                ? 'bg-sky-100 text-sky-700 dark:bg-sky-500/15 dark:text-sky-300'
                : 'bg-emerald-100 text-emerald-700 dark:bg-emerald-500/15 dark:text-emerald-300'"
            >
              {{ source.typeLabel }}
            </span>
            <div class="min-w-0 flex-1">
              <p class="truncate text-sm font-medium text-neutral-800 dark:text-neutral-100">
                {{ source.title }}
              </p>
              <p class="mt-0.5 truncate text-xs text-neutral-400 dark:text-neutral-500">
                {{ source.meta }}
              </p>
            </div>
          </button>
        </div>
      </div>
    </Transition>
  </Teleport>
</template>

<script setup>
import { computed, ref, watch, onBeforeUnmount, onMounted, nextTick } from 'vue'
import { storeToRefs } from 'pinia'
import mpegts from 'mpegts.js'
import { usePlayerStore } from '../stores/player'
import { fetchAggregatedChannels } from '../api/iptv'

const API_BASE = import.meta.env.VITE_API_BASE_URL || ''

const playerStore = usePlayerStore()
const { isPlayerExpanded, currentStation, isPlaying, isLoading, volume, stationMap, stationList } = storeToRefs(playerStore)

const iptvVideoRef = ref(null)
const iptvHlsRef = ref(null)
const iptvMpegtsRef = ref(null)
const sourceButtonRef = ref(null)
const sourceMenuOpen = ref(false)
const sourceMenuStyle = ref({
  left: '12px',
  top: '64px',
  width: 'calc(100vw - 24px)',
  maxHeight: '320px',
})
const sourceMenuListMaxHeight = ref('260px')
const iptvSourceRuntimeStatus = ref({})
const DEFAULT_LOGO_URL = '/logos/default.png'

const isIOS = /iPad|iPhone|iPod/.test(navigator.userAgent) ||
  (navigator.platform === 'MacIntel' && navigator.maxTouchPoints > 1)
const iptvMuted = ref(isIOS)  // iOS 静音绕过自动播放限制

function useDefaultLogo(event) {
  const img = event?.target
  if (!img || img.dataset.logoFallback === '1') return
  img.dataset.logoFallback = '1'
  img.src = DEFAULT_LOGO_URL
}

function toggleIptvMute() {
  if (!iptvVideoRef.value) return
  iptvMuted.value = !iptvMuted.value
  iptvVideoRef.value.muted = iptvMuted.value
}

function toggleFullscreen() {
  const el = iptvVideoRef.value
  if (!el) return
  if (document.fullscreenElement) {
    document.exitFullscreen()
  } else if (el.webkitEnterFullscreen) {
    el.webkitEnterFullscreen()  // iOS 私有 API
  } else {
    el.requestFullscreen().catch(() => {})
  }
}  // 跟踪当前播放的 URL，防止重复设置

function updateSourceMenuPosition() {
  const button = sourceButtonRef.value
  if (!button) return
  const rect = button.getBoundingClientRect()
  const gutter = 12
  const width = Math.min(320, window.innerWidth - gutter * 2)
  const maxHeight = Math.min(340, Math.max(180, window.innerHeight - gutter * 2))
  const belowTop = rect.bottom + 8
  const aboveTop = rect.top - maxHeight - 8
  const top = belowTop + maxHeight <= window.innerHeight - gutter
    ? belowTop
    : Math.max(gutter, aboveTop)
  const left = Math.min(
    window.innerWidth - width - gutter,
    Math.max(gutter, rect.right - width),
  )

  sourceMenuStyle.value = {
    left: `${left}px`,
    top: `${top}px`,
    width: `${width}px`,
    maxHeight: `${maxHeight}px`,
  }
  sourceMenuListMaxHeight.value = `${Math.max(120, maxHeight - 48)}px`
}

async function toggleSourceMenu() {
  sourceMenuOpen.value = !sourceMenuOpen.value
  if (sourceMenuOpen.value) {
    await nextTick()
    updateSourceMenuPosition()
  }
}

function closeSourceMenu() {
  sourceMenuOpen.value = false
}

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

function sourceTargetUrl(entry) {
  if (!entry?.url) return ''
  if (entry.original_url) return entry.original_url
  try {
    const parsed = new URL(entry.url)
    return parsed.searchParams.get('target_url') || entry.url
  } catch {
    return entry.url
  }
}

function sourceHost(url) {
  if (!url) return '未知地址'
  try {
    return new URL(url).host
  } catch {
    return url.replace(/^https?:\/\//, '').split('/')[0] || url
  }
}

function sourceStatusClass(status) {
  if (status === 'playing') return 'bg-emerald-500'
  if (status === 'trying') return 'bg-amber-400'
  if (status === 'failed') return 'bg-red-500'
  return 'bg-neutral-300 dark:bg-neutral-600'
}

function sourceStatusLabel(status) {
  if (status === 'playing') return '当前可播'
  if (status === 'trying') return '正在尝试'
  if (status === 'failed') return '本次失败'
  if (status === 'stopped') return '已停止'
  return '未尝试'
}

const iptvSourceOptions = computed(() => {
  return playerStore.iptvUrls.map((entry, index) => {
    const targetUrl = sourceTargetUrl(entry)
    const isProxySource = entry.type === 'proxy' || entry.via_proxy
    const typeLabel = isProxySource ? '代理' : '直连'
    const host = sourceHost(targetUrl)
    const working = Number(entry.is_working)
    const latency = Number(entry.latency_ms) > 0 ? `${entry.latency_ms}ms` : ''
    const runtimeStatus = iptvSourceRuntimeStatus.value[index] || 'idle'
    const health = working === 1 ? '检测可用' : working === 0 ? '检测不可用' : '未检测'
    const healthLabel = runtimeStatus === 'idle' || health !== '未检测' ? health : ''
    const ua = entry.custom_ua ? 'UA' : ''
    const transcode = entry.rtsp_compat ? '转码' : ''
    const meta = [sourceStatusLabel(runtimeStatus), healthLabel, latency, ua, transcode].filter(Boolean).join(' · ')

    return {
      index,
      url: entry.url,
      type: isProxySource ? 'proxy' : entry.type,
      typeLabel,
      title: `${index + 1}. ${host}`,
      meta,
      status: runtimeStatus,
      statusClass: sourceStatusClass(runtimeStatus),
      active: index === playerStore.iptvUrlIndex,
    }
  })
})

const currentIptvSourceLabel = computed(() => {
  const current = iptvSourceOptions.value[playerStore.iptvUrlIndex]
  return current ? `${current.index + 1}/${iptvSourceOptions.value.length}` : '未选择'
})

const currentIptvSourceStatusClass = computed(() => {
  const current = iptvSourceOptions.value[playerStore.iptvUrlIndex]
  return current ? current.statusClass : sourceStatusClass('idle')
})

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

function destroyIptvMpegts() {
  if (!iptvMpegtsRef.value) return
  const player = iptvMpegtsRef.value
  iptvMpegtsRef.value = null
  try {
    player.destroy()
  } catch (e) {
    const message = e?.message || ''
    if (!message.includes('removeAllListeners')) {
      console.warn('[IPTV] mpegts cleanup failed:', e)
    }
  }
}

function destroyIptvEngines() {
  destroyIptvHls()
  destroyIptvMpegts()
}

function resetIptvVideo() {
  if (!iptvVideoRef.value) return
  stopPlaybackWatchdogs()
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

function isMpegTsUrl(url) {
  return /\/api\/iptv\/proxy\/stream(\?|$)/i.test(url)
    || /\/(?:rtp|udp)\//i.test(url)
    || /%2F(?:rtp|udp)%2F/i.test(url)
    || /\.m2?ts(\?|$)/i.test(url)
}

function canUseMpegTs() {
  try {
    return Boolean(mpegts?.getFeatureList?.().mseLivePlayback || mpegts?.isSupported?.())
  } catch {
    return false
  }
}

function getProxyUrl(url) {
  return `${API_BASE}/api/iptv/proxy/playlist.m3u8?target_url=${encodeURIComponent(url)}`
}

const STARTUP_RACE_LIMIT = 6

let _playAttemptId = 0
let _racedLosers = new Set()
let _cleanupActiveRace = null
let _cancelCurrentStartup = null
let _suppressIptvUrlWatch = 0

function isAttemptActive(attemptId) {
  return attemptId === _playAttemptId
}

function cancelledError() {
  return new Error('cancelled')
}

function clearCurrentHlsIf(hls) {
  if (iptvHlsRef.value === hls) iptvHlsRef.value = null
}

function clearCurrentMpegtsIf(player) {
  if (iptvMpegtsRef.value === player) iptvMpegtsRef.value = null
}

function cancelActiveProxyRace() {
  if (!_cleanupActiveRace) return
  const cleanup = _cleanupActiveRace
  _cleanupActiveRace = null
  cleanup()
}

function cancelCurrentStartup() {
  if (!_cancelCurrentStartup) return
  const cancel = _cancelCurrentStartup
  _cancelCurrentStartup = null
  cancel()
}

function markAllIptvSourcesUnavailable(attemptId) {
  if (!isAttemptActive(attemptId)) return
  playerStore.setPlaybackError('所有播放源均不可用')
  playerStore.isPlaying = false
  playerStore.isLoading = false
}

function setSourceRuntimeStatus(index, status) {
  if (index < 0) return
  iptvSourceRuntimeStatus.value = {
    ...iptvSourceRuntimeStatus.value,
    [index]: status,
  }
}

function setSourceRuntimeStatusByUrl(url, status) {
  const index = playerStore.iptvUrls.findIndex((entry) => entry.url === url)
  setSourceRuntimeStatus(index, status)
}

function setSourceRuntimeStatusByEntry(entry, status) {
  const index = playerStore.iptvUrls.indexOf(entry)
  setSourceRuntimeStatus(index, status)
}

async function fallbackToNextIptvUrl(attemptId) {
  if (!isAttemptActive(attemptId)) return false
  _suppressIptvUrlWatch++
  const hasNext = playerStore.iptvFallbackNext()
  await nextTick()
  _suppressIptvUrlWatch = Math.max(0, _suppressIptvUrlWatch - 1)
  return hasNext && isAttemptActive(attemptId)
}

async function setIptvUrlIndexForAttempt(index, attemptId) {
  if (!isAttemptActive(attemptId) || index < 0 || playerStore.iptvUrlIndex === index) {
    return isAttemptActive(attemptId)
  }
  _suppressIptvUrlWatch++
  playerStore.iptvUrlIndex = index
  await nextTick()
  _suppressIptvUrlWatch = Math.max(0, _suppressIptvUrlWatch - 1)
  return isAttemptActive(attemptId)
}

async function switchIptvSource(index) {
  if (!isIptvMode.value || index < 0 || index >= playerStore.iptvUrls.length) return
  sourceMenuOpen.value = false

  const entry = playerStore.iptvUrls[index]
  if (entry?.url) _racedLosers.delete(entry.url)

  const attemptId = ++_playAttemptId
  if (!(await setIptvUrlIndexForAttempt(index, attemptId))) return
  setSourceRuntimeStatus(index, 'trying')

  if (entry?.type === 'proxy') {
    try {
      await tryPlayIptv(entry.url, true, entry.custom_ua || '', attemptId, index)
      if (!isAttemptActive(attemptId)) return
      setSourceRuntimeStatus(index, 'playing')
      playerStore.clearPlaybackError()
      playerStore.setLoading(false)
    } catch (e) {
      if (!isAttemptActive(attemptId)) return
      setSourceRuntimeStatus(index, 'failed')
      if (entry?.url) _racedLosers.add(entry.url)
      console.warn('[IPTV] 手动切换代理源失败:', e?.message)
      if (await fallbackToNextIptvUrl(attemptId)) {
        return await playCurrentIptvUrl(attemptId)
      }
      markAllIptvSourcesUnavailable(attemptId)
    }
    return
  }

  await playCurrentIptvUrl(attemptId, { allowStartupRace: false })
}

function attachRuntimeHlsErrorHandlers(hls, sourceUrl, usingProxy, attemptId, sourceIndex = -1) {
  let fragFail = 0
  let switching = false
  const threshold = usingProxy ? 2 : 3
  const setRuntimeStatus = (status) => {
    if (sourceIndex >= 0) setSourceRuntimeStatus(sourceIndex, status)
    else setSourceRuntimeStatusByUrl(sourceUrl, status)
  }

  const cleanup = () => {
    hls.off(Hls.Events.FRAG_LOADED, onFragLoaded)
    hls.off(Hls.Events.ERROR, onError)
  }

  const switchToFallback = async (reason) => {
    if (switching || !isAttemptActive(attemptId)) return
    switching = true
    console.warn(`[IPTV] 播放中断，切备用源: ${reason}`)
    cleanup()
    setRuntimeStatus('failed')
    if (usingProxy) _racedLosers.add(sourceUrl)
    hls.destroy()
    clearCurrentHlsIf(hls)

    const nextAttemptId = ++_playAttemptId
    if (await fallbackToNextIptvUrl(nextAttemptId)) {
      return await playCurrentIptvUrl(nextAttemptId)
    }
    markAllIptvSourcesUnavailable(nextAttemptId)
  }

  const onFragLoaded = () => {
    fragFail = 0
  }

  const onError = (_, data) => {
    if (!isAttemptActive(attemptId)) return
    console.log(`[ERR:runtime] ${data.details} fatal:${data.fatal} type:${data.type}`)
    if (!data.fatal && data.details === Hls.ErrorDetails.FRAG_LOAD_ERROR) {
      fragFail++
      if (fragFail >= threshold) switchToFallback(data.details)
      return
    }
    if (data.fatal || data.type === Hls.ErrorTypes.NETWORK_ERROR) {
      switchToFallback(data.details || data.type)
    }
  }

  hls.on(Hls.Events.FRAG_LOADED, onFragLoaded)
  hls.on(Hls.Events.ERROR, onError)
}

function attachRuntimeMpegtsErrorHandlers(player, sourceUrl, usingProxy, attemptId, sourceIndex = -1) {
  let switching = false
  let completeWatchTimer = null
  let completeLastTime = 0
  let completeLastProgressAt = 0
  const setRuntimeStatus = (status) => {
    if (sourceIndex >= 0) setSourceRuntimeStatus(sourceIndex, status)
    else setSourceRuntimeStatusByUrl(sourceUrl, status)
  }

  const clearCompleteWatchTimer = () => {
    if (!completeWatchTimer) return
    clearInterval(completeWatchTimer)
    completeWatchTimer = null
  }

  const cleanup = () => {
    clearCompleteWatchTimer()
    player.off(mpegts.Events.ERROR, onError)
    player.off(mpegts.Events.LOADING_COMPLETE, onComplete)
  }

  const switchToFallback = async (reason) => {
    if (switching || !isAttemptActive(attemptId)) return
    switching = true
    console.warn(`[IPTV] MPEG-TS 播放中断，切备用源: ${reason}`)
    cleanup()
    setRuntimeStatus('failed')
    if (usingProxy) _racedLosers.add(sourceUrl)
    clearCurrentMpegtsIf(player)
    try {
      player.destroy()
    } catch (e) {
      const message = e?.message || ''
      if (!message.includes('removeAllListeners')) {
        console.warn('[IPTV] mpegts runtime cleanup failed:', e)
      }
    }

    const nextAttemptId = ++_playAttemptId
    if (await fallbackToNextIptvUrl(nextAttemptId)) {
      return await playCurrentIptvUrl(nextAttemptId)
    }
    markAllIptvSourcesUnavailable(nextAttemptId)
  }

  const onError = (type, detail, info) => {
    switchToFallback(`${type || 'mpegts error'}:${detail || info?.msg || ''}`)
  }

  const onComplete = () => {
    if (switching || !isAttemptActive(attemptId)) return
    if (completeWatchTimer) return

    const video = iptvVideoRef.value
    completeLastTime = Number.isFinite(video?.currentTime) ? video.currentTime : 0
    completeLastProgressAt = Date.now()
    console.warn('[IPTV] MPEG-TS loading complete，等待剩余缓冲耗尽')

    completeWatchTimer = setInterval(() => {
      if (switching) return
      if (!isAttemptActive(attemptId)) {
        cleanup()
        return
      }

      const current = iptvVideoRef.value
      if (!current || current.paused) return

      const now = Date.now()
      const currentTime = Number.isFinite(current.currentTime) ? current.currentTime : completeLastTime
      const bufferAhead = getForwardBuffer(current)

      if (currentTime > completeLastTime + 0.05) {
        completeLastTime = currentTime
        completeLastProgressAt = now
        return
      }

      const noProgressMs = now - completeLastProgressAt
      if (current.ended || (noProgressMs > 4500 && bufferAhead < 0.4)) {
        switchToFallback('mpegts loading complete buffer drained')
      }
    }, 1000)
  }

  player.on(mpegts.Events.ERROR, onError)
  player.on(mpegts.Events.LOADING_COMPLETE, onComplete)
}

async function tryPlayIptv(url, usingProxy = false, customUa = '', attemptId = 0, sourceIndex = -1) {
  if (!isAttemptActive(attemptId)) throw cancelledError()
  if (!iptvVideoRef.value) throw new Error('播放器未就绪')

  const setRuntimeStatus = (status) => {
    if (sourceIndex >= 0) setSourceRuntimeStatus(sourceIndex, status)
    else setSourceRuntimeStatusByUrl(url, status)
  }

  setRuntimeStatus('trying')

  const useHls = isHlsUrl(url)
  const useMpegTs = !useHls && isMpegTsUrl(url)

  if (!useHls && !useMpegTs) {
    setRuntimeStatus('failed')
    throw new Error('不支持的播放格式')
  }

  if (useMpegTs && !canUseMpegTs()) {
    setRuntimeStatus('failed')
    throw new Error('当前浏览器不支持 MPEG-TS 播放')
  }

  cancelCurrentStartup()
  cancelActiveProxyRace()
  destroyIptvEngines()
  resetIptvVideo()
  playerStore.setLoading(true)
  console.log(`[START] ${usingProxy ? '(proxy) ' : ''}${url.slice(0, 80)}...`)

  return new Promise((resolve, reject) => {
    let settled = false
    let settling = false
    let timer = null
    let hlsInstance = null
    let mpegtsInstance = null
    const hlsEventFns = []
    const mpegtsEventFns = []
    let nativeCleanup = null  // 原生 HLS listener cleanup
    let cancelStartup = null

    const clearStartupCancel = () => {
      if (_cancelCurrentStartup === cancelStartup) _cancelCurrentStartup = null
    }

    const cleanupPending = () => {
      clearTimeout(timer)
      timer = null
      for (const [evt, fn] of hlsEventFns) hlsInstance?.off(evt, fn)
      hlsEventFns.length = 0
      for (const [evt, fn] of mpegtsEventFns) mpegtsInstance?.off(evt, fn)
      mpegtsEventFns.length = 0
      if (nativeCleanup) {
        nativeCleanup()
        nativeCleanup = null
      }
    }

    const cleanupFailure = () => {
      cleanupPending()
      if (hlsInstance) {
        hlsInstance.destroy()
        clearCurrentHlsIf(hlsInstance)
        hlsInstance = null
      }
      if (mpegtsInstance) {
        try {
          mpegtsInstance.destroy()
        } catch (e) {
          console.warn('[IPTV] mpegts failure cleanup failed:', e)
        }
        clearCurrentMpegtsIf(mpegtsInstance)
        mpegtsInstance = null
      }
    }

    cancelStartup = () => {
      if (settled) return
      settled = true
      cleanupFailure()
      clearStartupCancel()
      reject(cancelledError())
    }
    _cancelCurrentStartup = cancelStartup

    const safeResolve = async () => {
      if (settled || settling) return
      if (!isAttemptActive(attemptId)) {
        settled = true
        cleanupFailure()
        clearStartupCancel()
        reject(cancelledError())
        return
      }
      settling = true
      cleanupPending()
      try {
        if (!iptvVideoRef.value) throw new Error('播放器未就绪')
        iptvVideoRef.value.volume = volume.value
        await iptvVideoRef.value.play()
        if (settled) return
        if (!isAttemptActive(attemptId)) {
          settled = true
          cleanupFailure()
          clearStartupCancel()
          reject(cancelledError())
          return
        }
        if (hlsInstance) attachRuntimeHlsErrorHandlers(hlsInstance, url, usingProxy, attemptId, sourceIndex)
        if (mpegtsInstance) attachRuntimeMpegtsErrorHandlers(mpegtsInstance, url, usingProxy, attemptId, sourceIndex)
        playerStore.togglePlay(true)
        setRuntimeStatus('playing')
        settled = true
        clearStartupCancel()
        resolve()
      } catch (e) {
        if (settled) return
        settled = true
        cleanupFailure()
        if (isAttemptActive(attemptId)) setRuntimeStatus('failed')
        clearStartupCancel()
        reject(e)
      }
    }

    const safeReject = (err) => {
      if (settled) return
      if (!isAttemptActive(attemptId)) {
        settled = true
        cleanupFailure()
        clearStartupCancel()
        reject(cancelledError())
        return
      }
      settled = true
      cleanupFailure()
      setRuntimeStatus('failed')
      clearStartupCancel()
      reject(err)
    }

    // MPEG-TS over MSE path
    if (useMpegTs) {
      const player = mpegts.createPlayer({
        type: 'mse',
        isLive: true,
        cors: true,
        url,
      }, {
        enableWorker: true,
        lazyLoad: false,
        liveBufferLatencyChasing: true,
        statisticsInfoReportInterval: 1000,
      })
      mpegtsInstance = player
      iptvMpegtsRef.value = player

      const video = iptvVideoRef.value
      const onMediaInfo = () => safeResolve()
      const onStats = (stats) => {
        if ((stats?.decodedFrames || 0) > 0) safeResolve()
      }
      const onMpegtsError = (type, detail, info) => {
        safeReject(new Error(`${type || 'mpegts error'}:${detail || info?.msg || ''}`))
      }
      const onVideoReady = () => safeResolve()
      const onVideoError = () => safeReject(new Error('MPEG-TS 视频错误'))

      player.on(mpegts.Events.MEDIA_INFO, onMediaInfo)
      player.on(mpegts.Events.STATISTICS_INFO, onStats)
      player.on(mpegts.Events.ERROR, onMpegtsError)
      mpegtsEventFns.push([mpegts.Events.MEDIA_INFO, onMediaInfo])
      mpegtsEventFns.push([mpegts.Events.STATISTICS_INFO, onStats])
      mpegtsEventFns.push([mpegts.Events.ERROR, onMpegtsError])
      video.addEventListener('loadedmetadata', onVideoReady)
      video.addEventListener('canplay', onVideoReady)
      video.addEventListener('error', onVideoError)
      nativeCleanup = () => {
        video.removeEventListener('loadedmetadata', onVideoReady)
        video.removeEventListener('canplay', onVideoReady)
        video.removeEventListener('error', onVideoError)
      }

      player.attachMediaElement(video)
      player.load()
      timer = setTimeout(() => safeReject(new Error('MPEG-TS 加载超时')), 12_000)
      return
    }

    // HLS path
    if (canUseHls()) {
      const hlsConfig = {
        enableWorker: true, lowLatencyMode: false, liveDurationInfinity: true,
        liveSyncDuration: 20, liveMaxLatencyDuration: 55, liveSyncOnStallIncrease: 2,
        maxLiveSyncPlaybackRate: 1, nudgeOffset: 0.1, nudgeMaxRetry: 3,
        maxBufferLength: 30, maxBufferHole: 0.5,
      }
      if (isIOS) {
        Object.assign(hlsConfig, {
          liveSyncDuration: 30,
          liveMaxLatencyDuration: 90,
          maxBufferLength: 60,
          maxMaxBufferLength: 90,
          liveSyncOnStallIncrease: 5,
        })
      }
      if (customUa) hlsConfig.xhrSetup = (xhr) => { xhr.setRequestHeader('User-Agent', customUa) }
      const hls = new Hls(hlsConfig)
      hlsInstance = hls
      iptvHlsRef.value = hls
      let fragFail = 0
      const threshold = usingProxy ? 2 : 3

      const onFragLoaded = () => { fragFail = 0; safeResolve() }
      hls.on(Hls.Events.FRAG_LOADED, onFragLoaded)
      hlsEventFns.push([Hls.Events.FRAG_LOADED, onFragLoaded])

      const onError = (_, d) => {
        console.log(`[ERR] ${d.details} fatal:${d.fatal}`)
        if (!d.fatal && d.details === Hls.ErrorDetails.FRAG_LOAD_ERROR) {
          fragFail++
          if (fragFail >= threshold) safeReject(new Error(d.details))
          return
        }
        if (d.fatal || d.type === Hls.ErrorTypes.NETWORK_ERROR) {
          safeReject(new Error(d.details))
        }
      }
      hls.on(Hls.Events.ERROR, onError)
      hlsEventFns.push([Hls.Events.ERROR, onError])

      hls.loadSource(url)
      hls.attachMedia(iptvVideoRef.value)
      timer = setTimeout(() => safeReject(new Error('HLS 加载超时')), 10_000)
      return
    }

    // Safari native HLS
    if (iptvVideoRef.value.canPlayType('application/vnd.apple.mpegurl')) {
      const video = iptvVideoRef.value
      video.src = url
      const onLoaded = () => safeResolve()
      const onErr = () => safeReject(new Error('原生 HLS 错误'))
      video.addEventListener('loadedmetadata', onLoaded)
      video.addEventListener('error', onErr)
      nativeCleanup = () => {
        video.removeEventListener('loadedmetadata', onLoaded)
        video.removeEventListener('error', onErr)
      }
      timer = setTimeout(() => safeReject(new Error('原生 HLS 超时')), 10_000)
      return
    }

    safeReject(new Error('当前浏览器不支持 HLS 播放'))
  })
}

function startupRaceEntries(urls, startIndex) {
  const racers = []
  const hlsProbeSupported = canUseHls()
  const mpegtsProbeSupported = canUseMpegTs()
  for (let i = startIndex; i < urls.length && racers.length < STARTUP_RACE_LIMIT; i++) {
    const entry = urls[i]
    if (!entry?.url) continue
    if ((entry.type === 'proxy' || entry.via_proxy) && _racedLosers.has(entry.url)) continue
    if (isHlsUrl(entry.url) && hlsProbeSupported) {
      racers.push({ entry, index: i, kind: 'hls' })
      continue
    }
    if (!isHlsUrl(entry.url) && isMpegTsUrl(entry.url) && mpegtsProbeSupported) {
      racers.push({ entry, index: i, kind: 'mpegts' })
    }
  }
  return racers
}

async function playCurrentIptvUrl(attemptId = 0, options = {}) {
  if (!isAttemptActive(attemptId)) return
  if (!iptvVideoRef.value || !playerStore.currentIptvChannel) return
  const allowStartupRace = options.allowStartupRace !== false
  const urls = playerStore.iptvUrls
  const idx = playerStore.iptvUrlIndex
  if (idx >= urls.length) {
    markAllIptvSourcesUnavailable(attemptId)
    return
  }
  const entry = urls[idx]
  const startupRacers = allowStartupRace ? startupRaceEntries(urls, idx) : []
  if (startupRacers.length > 1) {
    const raced = await raceStartupSources(startupRacers, attemptId)
    if (raced !== false) return raced
    if (!isAttemptActive(attemptId)) return
  }

  console.log(`[START] ${entry.type}:${entry.url.slice(0, 60)}...`)
  try {
    setSourceRuntimeStatus(idx, 'trying')
    await tryPlayIptv(entry.url, Boolean(entry.via_proxy), entry.custom_ua || '', attemptId, idx)
    if (!isAttemptActive(attemptId)) return
    setSourceRuntimeStatus(idx, 'playing')
    playerStore.clearPlaybackError()
    playerStore.setLoading(false)
  } catch (e) {
    if (!isAttemptActive(attemptId)) return
    setSourceRuntimeStatus(idx, 'failed')
    console.warn('[IPTV] 失败:', e?.message)
    if (await fallbackToNextIptvUrl(attemptId)) {
      return await playCurrentIptvUrl(attemptId)
    }
    markAllIptvSourcesUnavailable(attemptId)
  }
}

function resetRacedLosers() { _racedLosers.clear() }

async function raceStartupSources(candidates, attemptId = 0) {
  if (!isAttemptActive(attemptId)) return
  cancelCurrentStartup()
  cancelActiveProxyRace()
  destroyIptvEngines()
  resetIptvVideo()
  playerStore.setLoading(true)

  const fresh = candidates.filter(({ entry, kind }) => {
    if (!entry?.url) return false
    if ((entry.type === 'proxy' || entry.via_proxy) && _racedLosers.has(entry.url)) return false
    if (kind === 'hls') return canUseHls()
    if (kind === 'mpegts') return canUseMpegTs()
    return false
  })

  if (fresh.length < 2) return false

  console.log(`[RACE:startup] ${fresh.length} 个播放源并发探测`)
  fresh.forEach(({ entry }) => setSourceRuntimeStatusByEntry(entry, 'trying'))

  let failCount = 0
  let raceTimer = null
  let settled = false
  const racers = []

  const isProxyLike = (entry) => entry?.type === 'proxy' || entry?.via_proxy

  const cleanupRacer = (racer) => {
    if (!racer || racer.cleaned) return
    racer.cleaned = true
    try {
      if (racer.kind === 'hls') racer.engine.destroy()
      else if (racer.kind === 'mpegts') racer.engine.destroy()
    } catch (e) {
      const message = e?.message || ''
      if (!message.includes('removeAllListeners')) {
        console.warn('[RACE:startup] cleanup failed:', e)
      }
    }
    if (racer.video.parentNode) racer.video.remove()
  }

  const result = await new Promise((resolve) => {
    const finish = (value) => {
      if (settled) return
      settled = true
      clearTimeout(raceTimer)
      for (const racer of racers) {
        if (value && racer !== value.racer) {
          const racerIndex = playerStore.iptvUrls.indexOf(racer.entry)
          if (iptvSourceRuntimeStatus.value[racerIndex] === 'trying') {
            setSourceRuntimeStatus(racerIndex, 'stopped')
          }
        }
        cleanupRacer(racer)
      }
      if (_cleanupActiveRace === cancelRace) _cleanupActiveRace = null
      resolve(value)
    }

    const failRacer = (racer) => {
      if (settled || racer.cleaned || racer.failed) return
      racer.failed = true
      failCount++
      if (isProxyLike(racer.entry)) _racedLosers.add(racer.entry.url)
      setSourceRuntimeStatusByEntry(racer.entry, 'failed')
      cleanupRacer(racer)
      if (failCount >= fresh.length) finish(null)
    }

    const winRacer = (racer, label) => {
      if (!isAttemptActive(attemptId)) { finish(null); return }
      if (settled || racer.cleaned || racer.failed) return
      console.log(`[RACE:startup] ${label} 胜出: ${racer.entry.url.slice(0, 50)}`)
      setSourceRuntimeStatusByEntry(racer.entry, 'trying')
      finish({ racer, entry: racer.entry, index: racer.index })
    }

    const cancelRace = () => finish(null)
    _cleanupActiveRace = cancelRace

    raceTimer = setTimeout(() => {
      for (const racer of racers) {
        if (!racer.cleaned && !racer.failed) {
          if (isProxyLike(racer.entry)) _racedLosers.add(racer.entry.url)
          setSourceRuntimeStatusByEntry(racer.entry, 'failed')
        }
      }
      finish(null)
    }, 12_000)

    fresh.forEach(({ entry, index, kind }, i) => {
      const probeVideo = document.createElement('video')
      probeVideo.muted = true
      probeVideo.playsInline = true
      probeVideo.style.display = 'none'
      document.body.appendChild(probeVideo)

      if (kind === 'hls') {
        const hlsConfig = { enableWorker: false, maxBufferLength: 1, maxMaxBufferLength: 2 }
        if (entry.custom_ua) hlsConfig.xhrSetup = (xhr) => { xhr.setRequestHeader('User-Agent', entry.custom_ua) }
        const hls = new Hls(hlsConfig)
        const racer = { engine: hls, video: probeVideo, entry, index, kind, cleaned: false, failed: false, fragFail: 0 }
        racers.push(racer)

        hls.on(Hls.Events.FRAG_LOADED, () => winRacer(racer, `#${i} HLS`))
        hls.on(Hls.Events.ERROR, (_, d) => {
          if (!isAttemptActive(attemptId)) { finish(null); return }
          if (settled || racer.cleaned || racer.failed) return
          if (!d.fatal && d.details === Hls.ErrorDetails.FRAG_LOAD_ERROR) racer.fragFail++
          if (d.fatal || d.type === Hls.ErrorTypes.NETWORK_ERROR || racer.fragFail >= 2) {
            failRacer(racer)
          }
        })
        hls.loadSource(entry.url)
        hls.attachMedia(probeVideo)
        return
      }

      const player = mpegts.createPlayer({
        type: 'mse',
        isLive: true,
        cors: true,
        url: entry.url,
      }, {
        enableWorker: true,
        lazyLoad: false,
        liveBufferLatencyChasing: true,
        statisticsInfoReportInterval: 1000,
      })
      const racer = { engine: player, video: probeVideo, entry, index, kind, cleaned: false, failed: false }
      racers.push(racer)
      const onWin = () => winRacer(racer, `#${i} MPEG-TS`)
      const onStats = (stats) => {
        if ((stats?.decodedFrames || 0) > 0) onWin()
      }
      player.on(mpegts.Events.MEDIA_INFO, onWin)
      player.on(mpegts.Events.STATISTICS_INFO, onStats)
      player.on(mpegts.Events.ERROR, () => failRacer(racer))
      probeVideo.addEventListener('loadedmetadata', onWin)
      probeVideo.addEventListener('canplay', onWin)
      probeVideo.addEventListener('error', () => failRacer(racer))
      try {
        player.attachMediaElement(probeVideo)
        player.load()
      } catch {
        failRacer(racer)
      }
    })
  })

  if (!isAttemptActive(attemptId)) return

  if (!result) {
    console.warn('[RACE:startup] 本轮播放源探测全部失败')
    const lastRacedIndex = Math.max(...fresh.map(({ index }) => index))
    if (lastRacedIndex >= 0) await setIptvUrlIndexForAttempt(lastRacedIndex, attemptId)
    if (await fallbackToNextIptvUrl(attemptId)) {
      return await playCurrentIptvUrl(attemptId)
    }
    markAllIptvSourcesUnavailable(attemptId)
    return
  }

  const { entry: winnerEntry, index: winnerIndex } = result
  if (!(await setIptvUrlIndexForAttempt(winnerIndex, attemptId))) return

  try {
    await tryPlayIptv(winnerEntry.url, Boolean(winnerEntry.via_proxy), winnerEntry.custom_ua || '', attemptId, winnerIndex)
    if (!isAttemptActive(attemptId)) return
    setSourceRuntimeStatus(winnerIndex, 'playing')
    playerStore.clearPlaybackError()
    playerStore.setLoading(false)
  } catch (e) {
    if (!isAttemptActive(attemptId)) return
    if (isProxyLike(winnerEntry)) _racedLosers.add(winnerEntry.url)
    setSourceRuntimeStatus(winnerIndex, 'failed')
    console.warn('[RACE:startup] 胜出源正式起播失败:', e?.message)
    if (await fallbackToNextIptvUrl(attemptId)) {
      return await playCurrentIptvUrl(attemptId)
    }
    markAllIptvSourcesUnavailable(attemptId)
  }
}

async function raceDirectHlsSources(entries, attemptId = 0) {
  if (!isAttemptActive(attemptId)) return
  cancelCurrentStartup()
  cancelActiveProxyRace()
  destroyIptvEngines()
  resetIptvVideo()
  playerStore.setLoading(true)

  const fresh = entries.filter((entry) => isHlsUrl(entry.url) && !isMpegTsUrl(entry.url))
  if (fresh.length < 2) {
    return false
  }

  console.log(`[RACE:direct] ${fresh.length} 个直连 HLS 源并发探测`)
  fresh.forEach((entry) => setSourceRuntimeStatusByEntry(entry, 'trying'))
  let failCount = 0
  let raceTimer = null
  let settled = false
  const racers = []

  const cleanupRacer = (racer) => {
    if (!racer || racer.cleaned) return
    racer.cleaned = true
    try {
      racer.hls.destroy()
    } catch (e) {
      console.warn('[RACE:direct] cleanup failed:', e)
    }
    if (racer.video.parentNode) racer.video.remove()
  }

  const result = await new Promise((resolve) => {
    const finish = (value) => {
      if (settled) return
      settled = true
      clearTimeout(raceTimer)
      for (const racer of racers) {
        if (value && racer.hls !== value.hls) {
          const racerIndex = playerStore.iptvUrls.indexOf(racer.entry)
          if (iptvSourceRuntimeStatus.value[racerIndex] === 'trying') {
            setSourceRuntimeStatus(racerIndex, 'stopped')
          }
        }
        if (!value || racer.hls !== value.hls) cleanupRacer(racer)
      }
      if (_cleanupActiveRace === cancelRace) _cleanupActiveRace = null
      resolve(value)
    }

    const cancelRace = () => finish(null)
    _cleanupActiveRace = cancelRace

    raceTimer = setTimeout(() => {
      for (const entry of fresh) setSourceRuntimeStatusByEntry(entry, 'failed')
      finish(null)
    }, 12_000)

    fresh.forEach((entry, i) => {
      const hlsConfig = { enableWorker: false, maxBufferLength: 1, maxMaxBufferLength: 2 }
      const hls = new Hls(hlsConfig)
      const probeVideo = document.createElement('video')
      probeVideo.muted = true
      probeVideo.playsInline = true
      probeVideo.style.display = 'none'
      document.body.appendChild(probeVideo)
      const racer = { hls, video: probeVideo, entry, cleaned: false, fragFail: 0 }
      racers.push(racer)

      hls.on(Hls.Events.FRAG_LOADED, () => {
        if (!isAttemptActive(attemptId)) { finish(null); return }
        if (settled) return
        console.log(`[RACE:direct] #${i} 胜出: ${entry.url.slice(0, 50)}`)
        setSourceRuntimeStatusByEntry(entry, 'trying')
        hls.detachMedia()
        finish({ hls, entry, video: probeVideo })
      })

      hls.on(Hls.Events.ERROR, (_, d) => {
        if (!isAttemptActive(attemptId)) { finish(null); return }
        if (settled || racer.cleaned) return
        if (!d.fatal && d.details === Hls.ErrorDetails.FRAG_LOAD_ERROR) {
          racer.fragFail++
        }
        if (d.fatal || d.type === Hls.ErrorTypes.NETWORK_ERROR || racer.fragFail >= 2) {
          failCount++
          setSourceRuntimeStatusByEntry(entry, 'failed')
          cleanupRacer(racer)
          if (failCount >= fresh.length) finish(null)
        }
      })

      hls.loadSource(entry.url)
      hls.attachMedia(probeVideo)
    })
  })

  if (!isAttemptActive(attemptId)) {
    if (result) {
      result.hls.destroy()
      if (result.video.parentNode) result.video.remove()
    }
    return
  }

  if (!result) {
    console.warn('[RACE:direct] 本轮直连 HLS 探测全部失败')
    const lastRacedIndex = Math.max(...fresh.map((entry) => playerStore.iptvUrls.indexOf(entry)))
    if (lastRacedIndex >= 0) await setIptvUrlIndexForAttempt(lastRacedIndex, attemptId)
    if (await fallbackToNextIptvUrl(attemptId)) {
      return await playCurrentIptvUrl(attemptId)
    }
    markAllIptvSourcesUnavailable(attemptId)
    return
  }

  const { hls: winnerHls, entry: winnerEntry, video: winnerVideo } = result
  winnerVideo.remove()
  const winnerIndex = playerStore.iptvUrls.indexOf(winnerEntry)
  if (!(await setIptvUrlIndexForAttempt(winnerIndex, attemptId))) {
    winnerHls.destroy()
    return
  }
  iptvHlsRef.value = winnerHls

  try {
    await new Promise((resolve, reject) => {
      let settledAttach = false
      let attachTimer = null
      const cleanupAttach = () => {
        clearTimeout(attachTimer)
        winnerHls.off(Hls.Events.MEDIA_ATTACHED, onMediaAttached)
        winnerHls.off(Hls.Events.ERROR, onAttachError)
      }
      const settleAttach = (err) => {
        if (settledAttach) return
        settledAttach = true
        cleanupAttach()
        if (err) reject(err)
        else resolve()
      }
      const onMediaAttached = () => settleAttach()
      const onAttachError = (_, data) => {
        if (data.fatal || data.type === Hls.ErrorTypes.NETWORK_ERROR) {
          settleAttach(new Error(data.details || data.type))
        }
      }
      winnerHls.on(Hls.Events.MEDIA_ATTACHED, onMediaAttached)
      winnerHls.on(Hls.Events.ERROR, onAttachError)
      attachTimer = setTimeout(() => settleAttach(new Error('直连源接管超时')), 10_000)
      winnerHls.attachMedia(iptvVideoRef.value)
      winnerHls.startLoad(-1)
    })

    if (!isAttemptActive(attemptId)) throw cancelledError()
    iptvVideoRef.value.volume = volume.value
    await iptvVideoRef.value.play()
    if (!isAttemptActive(attemptId)) throw cancelledError()
    attachRuntimeHlsErrorHandlers(winnerHls, winnerEntry.url, false, attemptId, winnerIndex)
    setSourceRuntimeStatusByEntry(winnerEntry, 'playing')
    playerStore.togglePlay(true)
    playerStore.clearPlaybackError()
    playerStore.setLoading(false)
  } catch (e) {
    if (!isAttemptActive(attemptId)) {
      winnerHls.destroy()
      clearCurrentHlsIf(winnerHls)
      return
    }
    console.warn('[RACE:direct] 胜出直连源接管失败:', e?.message)
    setSourceRuntimeStatusByEntry(winnerEntry, 'failed')
    winnerHls.destroy()
    clearCurrentHlsIf(winnerHls)
    if (await fallbackToNextIptvUrl(attemptId)) {
      return await playCurrentIptvUrl(attemptId)
    }
    markAllIptvSourcesUnavailable(attemptId)
  }
}

async function raceProxySources(entries, attemptId = 0) {
  if (!isAttemptActive(attemptId)) return
  cancelCurrentStartup()
  cancelActiveProxyRace()
  destroyIptvEngines()
  resetIptvVideo()
  playerStore.setLoading(true)

  const fresh = entries.filter(e => !_racedLosers.has(e.url))
  if (!fresh.length) {
    if (await fallbackToNextIptvUrl(attemptId)) {
      return await playCurrentIptvUrl(attemptId)
    }
    markAllIptvSourcesUnavailable(attemptId)
    return
  }

  if (!canUseHls()) {
    const entry = fresh[0]
    const index = playerStore.iptvUrls.indexOf(entry)
    if (!(await setIptvUrlIndexForAttempt(index, attemptId))) return
    try {
      const sourceIndex = playerStore.iptvUrls.indexOf(entry)
      await tryPlayIptv(entry.url, true, entry.custom_ua || '', attemptId, sourceIndex)
      if (!isAttemptActive(attemptId)) return
      playerStore.clearPlaybackError()
      playerStore.setLoading(false)
    } catch (e) {
      if (!isAttemptActive(attemptId)) return
      _racedLosers.add(entry.url)
      console.warn('[IPTV] 原生代理源失败:', e?.message)
      if (await fallbackToNextIptvUrl(attemptId)) {
        return await playCurrentIptvUrl(attemptId)
      }
      markAllIptvSourcesUnavailable(attemptId)
    }
    return
  }

  console.log(`[RACE] ${fresh.length} 个代理源并发探测`)
  fresh.forEach((entry) => setSourceRuntimeStatusByEntry(entry, 'trying'))
  let failCount = 0
  let raceTimer = null
  let settled = false
  const racers = []

  const cleanupRacer = (racer) => {
    if (!racer || racer.cleaned) return
    racer.cleaned = true
    try {
      racer.hls.destroy()
    } catch (e) {
      console.warn('[RACE] cleanup failed:', e)
    }
    if (racer.video.parentNode) racer.video.remove()
  }

  const result = await new Promise((resolve) => {
    const finish = (value) => {
      if (settled) return
      settled = true
      clearTimeout(raceTimer)
      for (const racer of racers) {
        if (value && racer.hls !== value.hls) {
          const racerIndex = playerStore.iptvUrls.indexOf(racer.entry)
          if (iptvSourceRuntimeStatus.value[racerIndex] === 'trying') {
            setSourceRuntimeStatus(racerIndex, 'stopped')
          }
        }
        if (!value || racer.hls !== value.hls) cleanupRacer(racer)
      }
      if (_cleanupActiveRace === cancelRace) _cleanupActiveRace = null
      resolve(value)
    }

    const cancelRace = () => finish(null)
    _cleanupActiveRace = cancelRace

    raceTimer = setTimeout(() => {
      for (const entry of fresh) {
        _racedLosers.add(entry.url)
        setSourceRuntimeStatusByEntry(entry, 'failed')
      }
      finish(null)
    }, 8000)

    fresh.forEach((entry, i) => {
      const customUa = entry.custom_ua || ''
      const hlsConfig = { enableWorker: false, maxBufferLength: 1, maxMaxBufferLength: 2 }
      if (customUa) hlsConfig.xhrSetup = (xhr) => { xhr.setRequestHeader('User-Agent', customUa) }
      const hls = new Hls(hlsConfig)
      const probeVideo = document.createElement('video')
      probeVideo.muted = true
      probeVideo.playsInline = true
      probeVideo.style.display = 'none'
      document.body.appendChild(probeVideo)
      const racer = { hls, video: probeVideo, entry, cleaned: false, fragFail: 0 }
      racers.push(racer)

      hls.on(Hls.Events.FRAG_LOADED, () => {
        if (!isAttemptActive(attemptId)) { finish(null); return }
        if (settled) return
        console.log(`[RACE] #${i} 胜出: ${entry.url.slice(0, 50)}`)
        setSourceRuntimeStatusByEntry(entry, 'trying')
        hls.detachMedia()
        finish({ hls, entry, video: probeVideo })
      })

      hls.on(Hls.Events.ERROR, (_, d) => {
        if (!isAttemptActive(attemptId)) { finish(null); return }
        if (settled || racer.cleaned) return
        if (!d.fatal && d.details === Hls.ErrorDetails.FRAG_LOAD_ERROR) {
          racer.fragFail++
        }
        if (d.fatal || d.type === Hls.ErrorTypes.NETWORK_ERROR || racer.fragFail >= 2) {
          failCount++
          _racedLosers.add(entry.url)
          setSourceRuntimeStatusByEntry(entry, 'failed')
          cleanupRacer(racer)
          if (failCount >= fresh.length) finish(null)
        }
      })

      hls.loadSource(entry.url)
      hls.attachMedia(probeVideo)
    })
  })

  if (!isAttemptActive(attemptId)) {
    if (result) {
      result.hls.destroy()
      if (result.video.parentNode) result.video.remove()
    }
    return
  }

  if (!result) {
    console.warn('[RACE] 全部代理源探测失败')
    if (await fallbackToNextIptvUrl(attemptId)) {
      return await playCurrentIptvUrl(attemptId)
    }
    markAllIptvSourcesUnavailable(attemptId)
    return
  }

  // 胜者接管播放
  const { hls: winnerHls, entry: winnerEntry, video: winnerVideo } = result
  winnerVideo.remove()
  const winnerIndex = playerStore.iptvUrls.indexOf(winnerEntry)
  if (!(await setIptvUrlIndexForAttempt(winnerIndex, attemptId))) {
    winnerHls.destroy()
    return
  }
  iptvHlsRef.value = winnerHls

  try {
    await new Promise((resolve, reject) => {
      let settledAttach = false
      let attachTimer = null
      const cleanupAttach = () => {
        clearTimeout(attachTimer)
        winnerHls.off(Hls.Events.MEDIA_ATTACHED, onMediaAttached)
        winnerHls.off(Hls.Events.ERROR, onAttachError)
      }
      const settleAttach = (err) => {
        if (settledAttach) return
        settledAttach = true
        cleanupAttach()
        if (err) reject(err)
        else resolve()
      }
      const onMediaAttached = () => settleAttach()
      const onAttachError = (_, data) => {
        if (data.fatal || data.type === Hls.ErrorTypes.NETWORK_ERROR) {
          settleAttach(new Error(data.details || data.type))
        }
      }
      winnerHls.on(Hls.Events.MEDIA_ATTACHED, onMediaAttached)
      winnerHls.on(Hls.Events.ERROR, onAttachError)
      attachTimer = setTimeout(() => settleAttach(new Error('代理源接管超时')), 10_000)
      winnerHls.attachMedia(iptvVideoRef.value)
      winnerHls.startLoad(-1)
    })

    if (!isAttemptActive(attemptId)) throw cancelledError()
    iptvVideoRef.value.volume = volume.value
    await iptvVideoRef.value.play()
    if (!isAttemptActive(attemptId)) throw cancelledError()
    attachRuntimeHlsErrorHandlers(winnerHls, winnerEntry.url, true, attemptId, winnerIndex)
    setSourceRuntimeStatusByEntry(winnerEntry, 'playing')
    playerStore.togglePlay(true)
    playerStore.clearPlaybackError()
    playerStore.setLoading(false)
  } catch (e) {
    if (!isAttemptActive(attemptId)) {
      winnerHls.destroy()
      clearCurrentHlsIf(winnerHls)
      return
    }
    console.warn('[RACE] 胜出代理接管失败:', e?.message)
    _racedLosers.add(winnerEntry.url)
    setSourceRuntimeStatusByEntry(winnerEntry, 'failed')
    winnerHls.destroy()
    clearCurrentHlsIf(winnerHls)
    if (await fallbackToNextIptvUrl(attemptId)) {
      return await playCurrentIptvUrl(attemptId)
    }
    markAllIptvSourcesUnavailable(attemptId)
  }
}

async function handleIptvError(e) {
  console.warn('[IPTV] video error:', e?.target?.error?.message || '')
  // hls.js / mpegts.js 接管中 → 由各自 ERROR 事件处理
  if (iptvHlsRef.value || iptvMpegtsRef.value) return
  // 起播阶段（Promise 还没 resolve）→ 由 Promise reject 处理
  if (playerStore.isLoading) return
  // 播放中途暴毙 → 触发 fallback
  const attemptId = ++_playAttemptId
  if (await fallbackToNextIptvUrl(attemptId)) {
    return await playCurrentIptvUrl(attemptId)
  }
  markAllIptvSourcesUnavailable(attemptId)
}

let _stallRecovering = false
let _lastRecoveryTime = 0
let _lastVideoProgressAt = 0
let _lastVideoCurrentTime = 0
let _stallRecoveryTimer = null
let _lastVideoFrameAt = 0
let _lastPresentedFrames = 0
let _lastVideoFrameMediaTime = 0
let _videoFrameCallbackId = null
let _videoFrameWatchTimer = null
let _videoFrameWatchVideo = null
let _videoFrameWatchSeq = 0
let _lastAvSyncRecoveryTime = 0
let _lastReconnectTime = 0
let _lastBufferNudgeTime = 0

function stopVideoFrameWatch() {
  _videoFrameWatchSeq++
  if (_videoFrameCallbackId !== null && _videoFrameWatchVideo?.cancelVideoFrameCallback) {
    try {
      _videoFrameWatchVideo.cancelVideoFrameCallback(_videoFrameCallbackId)
    } catch {}
  }
  _videoFrameCallbackId = null
  _videoFrameWatchVideo = null
  if (_videoFrameWatchTimer) {
    clearInterval(_videoFrameWatchTimer)
    _videoFrameWatchTimer = null
  }
}

function stopPlaybackWatchdogs() {
  clearStallRecoveryTimer()
  stopVideoFrameWatch()
  _lastVideoProgressAt = 0
  _lastVideoCurrentTime = 0
  _lastVideoFrameAt = 0
  _lastPresentedFrames = 0
  _lastVideoFrameMediaTime = 0
}

function clearStallRecoveryTimer() {
  if (!_stallRecoveryTimer) return
  clearTimeout(_stallRecoveryTimer)
  _stallRecoveryTimer = null
}

function markVideoProgress(v) {
  if (!v) return
  const currentTime = v.currentTime || 0
  if (!_lastVideoProgressAt || Math.abs(currentTime - _lastVideoCurrentTime) > 0.05) {
    _lastVideoProgressAt = Date.now()
    _lastVideoCurrentTime = currentTime
    if (!_stallRecovering) clearStallRecoveryTimer()
  }
}

function seekNearLiveEdge(v) {
  const ranges = v?.seekable
  if (!ranges?.length) return false
  const last = ranges.length - 1
  const liveEdge = ranges.end(last)
  const rangeStart = ranges.start(last)
  if (!Number.isFinite(liveEdge)) return false
  if (liveEdge - v.currentTime < 8) return false

  v.currentTime = Math.max(rangeStart, liveEdge - 2)
  return true
}

function getForwardBuffer(v) {
  if (!v?.buffered?.length || !Number.isFinite(v.currentTime)) return 0
  for (let i = 0; i < v.buffered.length; i += 1) {
    const start = v.buffered.start(i)
    const end = v.buffered.end(i)
    if (v.currentTime >= start && v.currentTime <= end) {
      return Math.max(0, end - v.currentTime)
    }
  }
  return 0
}

function getLiveLatency(v) {
  const ranges = v?.seekable
  if (!ranges?.length || !Number.isFinite(v.currentTime)) return 0
  const liveEdge = ranges.end(ranges.length - 1)
  return Number.isFinite(liveEdge) ? Math.max(0, liveEdge - v.currentTime) : 0
}

function seekToStableLivePoint(v, targetBehindEdge = 8) {
  const ranges = v?.seekable
  if (!ranges?.length || !Number.isFinite(v.currentTime)) return false
  const last = ranges.length - 1
  const liveEdge = ranges.end(last)
  const rangeStart = ranges.start(last)
  if (!Number.isFinite(liveEdge)) return false

  const target = Math.max(rangeStart, liveEdge - targetBehindEdge)
  if (target <= v.currentTime + 0.5) return false
  v.currentTime = target
  return true
}

async function doRecovery(v, reason = 'stalled') {
  if (!v || v.paused || _stallRecovering) return
  if (Date.now() - _lastRecoveryTime < 10_000) return

  _stallRecovering = true
  _lastRecoveryTime = Date.now()
  console.warn(`[IPTV] ${reason} 持续无进展，尝试恢复`, {
    currentTime: v.currentTime,
    readyState: v.readyState,
    networkState: v.networkState,
  })

  try {
    await v.play()
    if (Date.now() - _lastVideoProgressAt > 3000) {
      seekNearLiveEdge(v)
    }
  } catch (e) {
    console.warn('[IPTV] stalled 恢复 play() 失败:', e?.message || e)
  } finally {
    _stallRecovering = false
  }
}

async function reconnectCurrentIptvSource(reason = 'stalled') {
  if (!isIptvMode.value || !playerStore.currentIptvChannel) return
  if (Date.now() - _lastReconnectTime < 15_000) return
  _lastReconnectTime = Date.now()

  const idx = playerStore.iptvUrlIndex
  setSourceRuntimeStatus(idx, 'trying')
  playerStore.setLoading(true)
  playerStore.setPlaybackError('播放卡住，正在重新连接当前源')
  console.warn(`[IPTV] ${reason}，重新连接当前源 #${idx + 1}`)

  const attemptId = ++_playAttemptId
  await playCurrentIptvUrl(attemptId, { allowStartupRace: false })
}

function seekForwardTiny(v) {
  if (!v || !Number.isFinite(v.currentTime)) return false
  const ranges = v.seekable
  const nextTime = v.currentTime + 0.08
  if (ranges?.length) {
    for (let i = 0; i < ranges.length; i += 1) {
      if (nextTime >= ranges.start(i) && nextTime <= ranges.end(i)) {
        v.currentTime = nextTime
        return true
      }
    }
    return seekNearLiveEdge(v)
  }
  v.currentTime = nextTime
  return true
}

async function recoverAvSync(v, reason = 'video-frame-stall') {
  if (!v || v.paused || _stallRecovering) return
  if (Date.now() - _lastAvSyncRecoveryTime < 8000) return
  _lastAvSyncRecoveryTime = Date.now()

  console.warn(`[IPTV] ${reason}，尝试音画重同步`, {
    currentTime: v.currentTime,
    readyState: v.readyState,
    networkState: v.networkState,
    presentedFrames: _lastPresentedFrames,
    frameAgeMs: _lastVideoFrameAt ? Date.now() - _lastVideoFrameAt : null,
  })

  try {
    await v.play()
    if (!seekForwardTiny(v)) seekNearLiveEdge(v)
    setTimeout(() => {
      const current = iptvVideoRef.value
      if (!current || current.paused || !isIptvMode.value) return
      const noProgress = Date.now() - _lastVideoProgressAt > 5000
      const noFrame = _lastVideoFrameAt && Date.now() - _lastVideoFrameAt > 5000
      if (noProgress || noFrame) reconnectCurrentIptvSource(`${reason} 恢复后仍无进展`)
    }, 5500)
  } catch (e) {
    console.warn('[IPTV] 音画重同步失败:', e?.message || e)
  }
}

function scheduleStallRecovery(reason) {
  const v = iptvVideoRef.value
  if (!v || v.paused || _stallRecovering) return
  if (!_lastVideoProgressAt) markVideoProgress(v)
  if (_stallRecoveryTimer) return

  _stallRecoveryTimer = setTimeout(() => {
    _stallRecoveryTimer = null
    if (!iptvVideoRef.value || iptvVideoRef.value.paused) return
    if (Date.now() - _lastVideoProgressAt < 6000) return
    doRecovery(iptvVideoRef.value, reason)
  }, 6500)
}

function onVideoTimeUpdate() {
  markVideoProgress(iptvVideoRef.value)
}

function startVideoFrameWatch(v = iptvVideoRef.value) {
  if (!isIOS || !isIptvMode.value || !v?.requestVideoFrameCallback) return
  if (_videoFrameWatchVideo === v && _videoFrameWatchTimer) return

  stopVideoFrameWatch()
  _videoFrameWatchVideo = v
  _lastVideoFrameAt = Date.now()
  _lastVideoFrameMediaTime = v.currentTime || 0
  const seq = ++_videoFrameWatchSeq

  const onFrame = (_now, metadata = {}) => {
    if (seq !== _videoFrameWatchSeq || _videoFrameWatchVideo !== v) return
    _lastVideoFrameAt = Date.now()
    _lastPresentedFrames = metadata.presentedFrames || _lastPresentedFrames
    _lastVideoFrameMediaTime = Number.isFinite(metadata.mediaTime)
      ? metadata.mediaTime
      : (v.currentTime || _lastVideoFrameMediaTime)
    _videoFrameCallbackId = v.requestVideoFrameCallback(onFrame)
  }

  _videoFrameCallbackId = v.requestVideoFrameCallback(onFrame)
  _videoFrameWatchTimer = setInterval(() => {
    if (seq !== _videoFrameWatchSeq || !isIptvMode.value || v.paused || v.ended) return
    const now = Date.now()
    const frameAge = now - _lastVideoFrameAt
    const progressAge = now - _lastVideoProgressAt
    const currentTime = v.currentTime || 0
    const mediaDrift = currentTime - _lastVideoFrameMediaTime
    const bufferAhead = getForwardBuffer(v)
    const liveLatency = getLiveLatency(v)

    if (bufferAhead > 0 && bufferAhead < 0.6 && liveLatency > 9 && now - _lastBufferNudgeTime > 8000) {
      _lastBufferNudgeTime = now
      if (seekToStableLivePoint(v, 8)) {
        console.warn('[IPTV] 前方缓冲过低，提前跳过可能卡顿点', {
          bufferAhead,
          liveLatency,
          currentTime,
        })
        return
      }
    }

    if (frameAge > 2500 && progressAge < 2500 && mediaDrift > 0.35) {
      recoverAvSync(v, '视频帧停滞但播放时钟仍在前进')
      return
    }

    if (frameAge > 5000 && progressAge > 5000) {
      scheduleStallRecovery('video-frame-watchdog')
    }

    if (frameAge > 12_000 && progressAge > 12_000) {
      reconnectCurrentIptvSource('视频帧和播放进度长时间停滞')
    }
  }, 1200)
}

function onVideoStalled() {
  const v = iptvVideoRef.value
  if (!v || v.paused) return
  console.warn('[IPTV] stalled observed', {
    currentTime: v.currentTime,
    readyState: v.readyState,
    networkState: v.networkState,
  })
  scheduleStallRecovery('stalled')
}

function onVideoEvent(evt) {
  if (evt === 'playing') {
    markVideoProgress(iptvVideoRef.value)
    startVideoFrameWatch(iptvVideoRef.value)
    clearStallRecoveryTimer()
    playerStore.setLoading(false)
    playerStore.togglePlay(true)
  }
  if (evt === 'pause') {
    clearStallRecoveryTimer()
    stopVideoFrameWatch()
  }
  if (evt === 'waiting') {
    scheduleStallRecovery('waiting')
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
    sourceMenuOpen.value = false
    iptvSourceRuntimeStatus.value = {}
    await nextTick()
    if (iptvVideoRef.value) {
      resetRacedLosers()
      const attemptId = ++_playAttemptId
      await playCurrentIptvUrl(attemptId)
    }
  }
})

watch(sourceMenuOpen, async (open) => {
  if (!open) return
  await nextTick()
  updateSourceMenuPosition()
})

watch(isPlayerExpanded, (expanded) => {
  if (!expanded) closeSourceMenu()
})

watch(isPlaying, (playing) => {
  if (!iptvVideoRef.value || !isIptvMode.value) return
  // 用户手动暂停后不自动恢复
  if (playing && iptvVideoRef.value.paused) {
    iptvVideoRef.value.play().catch(() => {})
  }
  if (!playing) iptvVideoRef.value.pause()
})

watch(volume, (v) => {
  if (iptvVideoRef.value) iptvVideoRef.value.volume = v
})

watch(() => playerStore.iptvUrlIndex, () => {
  if (_suppressIptvUrlWatch) return
  if (isIptvMode.value && isPlaying.value) {
    const attemptId = ++_playAttemptId
    playCurrentIptvUrl(attemptId)
  }
})

onMounted(() => {
  document.addEventListener('click', closeSourceMenu)
  window.addEventListener('resize', updateSourceMenuPosition)
  window.addEventListener('orientationchange', updateSourceMenuPosition)
})

onBeforeUnmount(() => {
  document.removeEventListener('click', closeSourceMenu)
  window.removeEventListener('resize', updateSourceMenuPosition)
  window.removeEventListener('orientationchange', updateSourceMenuPosition)
  _playAttemptId++
  stopPlaybackWatchdogs()
  cancelCurrentStartup()
  cancelActiveProxyRace()
  destroyIptvEngines()
})
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
