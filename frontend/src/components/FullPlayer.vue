<template>
  <Teleport to="body">
    <Transition name="ios-sheet">
      <div
        v-show="isPlayerExpanded"
        class="full-player fixed inset-0 z-50 overflow-y-auto"
        :class="{ 'theme-dark': isFullPlayerDark, 'safari-chrome-refresh': isSafariChromeRefreshing }"
      >
        <div class="player-layout">
          <main class="player-main">
            <section class="media-card">
              <div class="mobile-live-pill" aria-hidden="true">
                <div class="pill-logo">
                  <img
                    v-if="currentArtworkUrl"
                    :src="currentArtworkUrl"
                    :alt="currentStationName"
                    @error="useDefaultLogo"
                  />
                  <span v-else>{{ currentStationName.slice(0, 1) }}</span>
                </div>
                <span class="mini-eq active"></span>
              </div>

              <button
                type="button"
                class="overlay-btn overlay-back"
                aria-label="收起播放器"
                @click="playerStore.collapsePlayer()"
              >
                <svg viewBox="0 0 24 24" fill="none"><path d="M19 12H5M12 5l-7 7 7 7" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"/></svg>
              </button>

              <button
                type="button"
                class="overlay-btn overlay-info"
                aria-label="频道信息"
              >
                <svg viewBox="0 0 24 24" fill="none"><circle cx="12" cy="12" r="8.5" stroke="currentColor" stroke-width="2"/><path d="M12 10.8v5.2M12 7.8h.01" stroke="currentColor" stroke-width="2.2" stroke-linecap="round"/></svg>
              </button>

              <video
                v-if="isIptvMode"
                v-show="activeIptvEngine !== 'youtube'"
                ref="iptvVideoRef"
                class="media-video"
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
              <div
                v-if="isIptvMode"
                ref="youtubeHostRef"
                class="youtube-player-host"
                :class="{ active: activeIptvEngine === 'youtube' }"
              ></div>

              <div v-else class="radio-art-stage">
                <div class="radio-art">
                  <img
                    v-if="currentArtworkUrl"
                    :src="currentArtworkUrl"
                    :alt="currentStationName"
                    @error="useDefaultLogo"
                  />
                  <span v-else>{{ currentStationData?.logoText || '?' }}</span>
                </div>
              </div>
            </section>

            <section class="now-panel">
              <h1>{{ currentStationName }}</h1>
              <p>{{ currentChannelSubtitle }}</p>

              <div class="program-progress">
                <div class="progress-track">
                  <div class="progress-fill" :style="{ width: currentProgramProgressPercent }"></div>
                  <span class="progress-knob" :style="{ left: currentProgramProgressPercent }"></span>
                </div>
                <div class="progress-times">
                  <span>{{ currentProgram.start }}</span>
                  <span>{{ currentProgram.end }}</span>
                </div>
              </div>

              <p class="program-state">
                <span class="state-dot" :class="playbackStateClass"></span>
                <span>{{ fullPlayerStatusText }}</span>
                <span v-if="showProgramRemaining">·</span>
                <span v-if="showProgramRemaining">剩余 {{ currentProgram.remaining }} 分钟</span>
              </p>

              <div class="transport-row">
                <button type="button" class="transport-side" aria-label="上一个" @click="playPrev">
                  <svg viewBox="0 0 24 24" fill="currentColor"><path d="M5.5 5.5h2.6v13H5.5zm4.8 6.5 8.2 6.1V5.9z"/></svg>
                </button>
                <button
                  type="button"
                  class="transport-main"
                  :aria-label="isPlaying ? '暂停' : '播放'"
                  @click="playerStore.togglePlay()"
                >
                  <svg v-if="isPlaying" viewBox="0 0 24 24" fill="none"><path d="M8.5 5.5v13M15.5 5.5v13" stroke="currentColor" stroke-width="2.6" stroke-linecap="round"/></svg>
                  <svg v-else viewBox="0 0 24 24" fill="currentColor"><path d="M8 5.6v12.8c0 .75.83 1.2 1.46.78l9.65-6.39a.95.95 0 0 0 0-1.58L9.46 4.82A.94.94 0 0 0 8 5.6Z"/></svg>
                </button>
                <button type="button" class="transport-side" aria-label="下一个" @click="playNext">
                  <svg viewBox="0 0 24 24" fill="currentColor"><path d="M15.9 5.5h2.6v13h-2.6zM5.5 18.1l8.2-6.1-8.2-6.1z"/></svg>
                </button>
              </div>

              <div class="utility-row">
                <button
                  v-if="isIOS && isIptvMode"
                  type="button"
                  class="utility-btn"
                  :aria-label="iptvMuted ? '取消静音' : '静音'"
                  @click="toggleIptvMute()"
                >
                  <svg v-if="iptvMuted" viewBox="0 0 24 24" fill="none">
                    <path d="M4 10v4a1 1 0 0 0 1 1h3l4.2 3.15A.5.5 0 0 0 13 17.75V6.25a.5.5 0 0 0-.8-.4L8 9H5a1 1 0 0 0-1 1Z" stroke="currentColor" stroke-width="1.8" stroke-linejoin="round"/>
                    <path d="m21 3-18 18" stroke="currentColor" stroke-width="1.9" stroke-linecap="round"/>
                  </svg>
                  <svg v-else viewBox="0 0 24 24" fill="none">
                    <path d="M4 10v4a1 1 0 0 0 1 1h3l4.2 3.15A.5.5 0 0 0 13 17.75V6.25a.5.5 0 0 0-.8-.4L8 9H5a1 1 0 0 0-1 1Z" stroke="currentColor" stroke-width="1.8" stroke-linejoin="round"/>
                    <path d="M16 9a4 4 0 0 1 0 6M18.5 6.5a7.5 7.5 0 0 1 0 11" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/>
                  </svg>
                </button>

                <div v-if="!isIOS || !isIptvMode" class="volume-control">
                  <svg viewBox="0 0 24 24" fill="none"><path d="M4 10v4a1 1 0 0 0 1 1h3l4.2 3.15A.5.5 0 0 0 13 17.75V6.25a.5.5 0 0 0-.8-.4L8 9H5a1 1 0 0 0-1 1Z" stroke="currentColor" stroke-width="1.8" stroke-linejoin="round"/></svg>
                  <input
                    type="range"
                    min="0"
                    max="1"
                    step="0.01"
                    :value="volume"
                    aria-label="音量"
                    @input="playerStore.setVolume($event.target.value)"
                  />
                </div>

                <button type="button" class="utility-btn" aria-label="全屏" @click="toggleFullscreen">
                  <svg viewBox="0 0 24 24" fill="none"><path d="M7 14H5v5h5v-2H7v-3zm-2-4h2V7h3V5H5v5zm12 7h-3v2h5v-5h-2v3zM14 5v2h3v3h2V5h-5z" fill="currentColor"/></svg>
                </button>

                <button
                  v-if="isIptvMode && iptvSourceOptions.length"
                  ref="sourceButtonRef"
                  type="button"
                  class="utility-btn relative"
                  :aria-expanded="sourceMenuOpen"
                  aria-controls="iptv-source-menu"
                  aria-label="切换播放源"
                  @click.stop="toggleSourceMenu"
                >
                  <svg viewBox="0 0 24 24" fill="none"><path d="M6 7.5h12M6 12h12M6 16.5h8" stroke="currentColor" stroke-width="1.9" stroke-linecap="round"/></svg>
                  <span class="source-dot" :class="currentIptvSourceStatusClass"></span>
                </button>
              </div>
            </section>

            <section class="mobile-panel">
              <div class="panel-tabs">
                <button
                  type="button"
                  :class="{ active: activePlayerPanel === 'channels' }"
                  @click="activePlayerPanel = 'channels'"
                >
                  频道列表
                </button>
                <button
                  type="button"
                  :class="{ active: activePlayerPanel === 'schedule' }"
                  @click="activePlayerPanel = 'schedule'"
                >
                  节目单
                </button>
              </div>

              <div v-if="activePlayerPanel === 'channels'" class="channel-panel">
                <button
                  v-for="item in displayChannelRows"
                  :key="item.key"
                  type="button"
                  class="channel-row"
                  :class="{ active: item.active }"
                  @click="handleChannelRowClick(item)"
                >
                  <span class="channel-logo">
                    <img v-if="item.logo" :src="item.logo" :alt="item.name" @error="useDefaultLogo" />
                    <span v-else>{{ item.name.slice(0, 2) }}</span>
                  </span>
                  <span class="channel-copy">
                    <span class="channel-title">
                      {{ item.name }}
                      <span v-if="item.live" class="live-dot"></span>
                    </span>
                    <span class="channel-subtitle">{{ item.summary }}</span>
                  </span>
                  <svg
                    v-if="item.playing"
                    class="eq-icon active"
                    viewBox="0 0 24 24"
                    aria-hidden="true"
                  >
                    <rect x="4" y="8" width="2.5" height="8" rx="1.25" />
                    <rect x="8.5" y="5" width="2.5" height="14" rx="1.25" />
                    <rect x="13" y="3" width="2.5" height="18" rx="1.25" />
                    <rect x="17.5" y="6" width="2.5" height="12" rx="1.25" />
                  </svg>
                </button>
              </div>

              <div v-else class="schedule-panel">
                <div class="schedule-date">
                  <span>今天 · 2月22日</span>
                  <svg viewBox="0 0 24 24" fill="none"><path d="m7 10 5 5 5-5" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg>
                </div>
                <div class="timeline">
                  <div v-for="program in displaySchedule" :key="program.time" class="timeline-row" :class="{ current: program.current, past: program.past }">
                    <span class="timeline-time">{{ program.time }}</span>
                    <span class="timeline-dot"></span>
                    <span class="timeline-title">
                      {{ program.title }}
                      <span v-if="program.current" class="tag live-tag">直播中</span>
                    </span>
                  </div>
                </div>
              </div>
            </section>
          </main>

          <aside class="side-panel">
            <div class="panel-tabs">
              <button
                type="button"
                :class="{ active: activePlayerPanel === 'channels' }"
                @click="activePlayerPanel = 'channels'"
              >
                频道列表
              </button>
              <button
                type="button"
                :class="{ active: activePlayerPanel === 'schedule' }"
                @click="activePlayerPanel = 'schedule'"
              >
                节目单
              </button>
            </div>

            <div v-if="activePlayerPanel === 'channels'" class="channel-panel desktop-panel-scroll">
              <button
                v-for="item in displayChannelRows"
                :key="item.key"
                type="button"
                class="channel-row"
                :class="{ active: item.active }"
                @click="handleChannelRowClick(item)"
              >
                <span class="channel-logo">
                  <img v-if="item.logo" :src="item.logo" :alt="item.name" @error="useDefaultLogo" />
                  <span v-else>{{ item.name.slice(0, 2) }}</span>
                </span>
                <span class="channel-copy">
                  <span class="channel-title">
                    {{ item.name }}
                    <span v-if="item.live" class="live-dot"></span>
                  </span>
                  <span class="channel-subtitle">{{ item.summary }}</span>
                </span>
                <svg
                  v-if="item.playing"
                  class="eq-icon active"
                  viewBox="0 0 24 24"
                  aria-hidden="true"
                >
                  <rect x="4" y="8" width="2.5" height="8" rx="1.25" />
                  <rect x="8.5" y="5" width="2.5" height="14" rx="1.25" />
                  <rect x="13" y="3" width="2.5" height="18" rx="1.25" />
                  <rect x="17.5" y="6" width="2.5" height="12" rx="1.25" />
                </svg>
              </button>
            </div>

            <div v-else class="schedule-panel desktop-panel-scroll">
              <div class="schedule-date">
                <span>今天 · 2月22日</span>
                <svg viewBox="0 0 24 24" fill="none"><path d="m7 10 5 5 5-5" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg>
              </div>
              <div class="timeline">
                <div v-for="program in displaySchedule" :key="program.time" class="timeline-row" :class="{ current: program.current, past: program.past }">
                  <span class="timeline-time">{{ program.time }}</span>
                  <span class="timeline-dot"></span>
                  <span class="timeline-title">
                    {{ program.title }}
                    <span v-if="program.current" class="tag live-tag">直播中</span>
                  </span>
                </div>
              </div>
            </div>
          </aside>
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
import { useEpg } from '../composables/useEpg'
import { API_BASE } from '../apiBase'
import { publicAsset } from '../publicAsset'

const playerStore = usePlayerStore()
const { isPlayerExpanded, currentStation, isPlaying, isLoading, volume, stationMap, stationList } = storeToRefs(playerStore)

const iptvVideoRef = ref(null)
const iptvHlsRef = ref(null)
const iptvMpegtsRef = ref(null)
const youtubeHostRef = ref(null)
const activeIptvEngine = ref('video')
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
const activePlayerPanel = ref('channels')
const DEFAULT_LOGO_URL = publicAsset('/logos/default.png')
const isFullPlayerDark = ref(document.documentElement.classList.contains('dark'))
const isSafariChromeRefreshing = ref(false)
let themeObserver = null

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
  iptvMuted.value = !iptvMuted.value
  if (activeIptvEngine.value === 'youtube') {
    syncYoutubeAudioState()
    return
  }
  if (iptvVideoRef.value) iptvVideoRef.value.muted = iptvMuted.value
}

function toggleFullscreen() {
  if (activeIptvEngine.value === 'youtube') return
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

function syncFullPlayerTheme() {
  const shouldUseDark = document.documentElement.classList.contains('dark') ||
    document.body.classList.contains('dark')
  isFullPlayerDark.value = shouldUseDark
}

function setFullPlayerChromeOpen(open) {
  const appEl = document.getElementById('app')
  document.documentElement.classList.toggle('full-player-open', open)
  document.body.classList.toggle('full-player-open', open)
  appEl?.classList.toggle('full-player-open', open)

  if (open) {
    syncFullPlayerTheme()
  } else {
    window.__wavebypassSyncThemeChrome?.()
  }
}

function handleThemeChromeSync(event) {
  if (typeof event?.detail?.isDarkMode === 'boolean') {
    isFullPlayerDark.value = event.detail.isDarkMode
  } else {
    syncFullPlayerTheme()
  }
  refreshSafariChrome()
}

function refreshSafariChrome() {
  if (!isPlayerExpanded.value) return
  if (!isIOS) return
  isSafariChromeRefreshing.value = true
  requestAnimationFrame(() => {
    requestAnimationFrame(() => {
      isSafariChromeRefreshing.value = false
    })
  })
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

const currentArtworkUrl = computed(() => {
  if (playerStore.currentIptvChannel) return playerStore.currentIptvChannel.logo_url || ''
  return currentStationData.value?.logoUrl || ''
})

const currentChannelSubtitle = computed(() => {
  if (playerStore.currentIptvChannel) return playerStore.currentIptvChannel.group_name || '直播频道'
  return statusText.value
})

const currentProgram = computed(() => {
  const epg = playerStore.currentEpgProgram
  if (epg) {
    const startD = new Date(epg.start)
    const stopD = new Date(epg.stop)
    return {
      title: epg.title,
      start: startD.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' }),
      end: stopD.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' }),
      remaining: epg.remaining_minutes,
      progress: Math.round(epg.progress * 100),
    }
  }
  return { title: currentStationName.value, start: '', end: '', remaining: 0, progress: 0 }
})

const currentProgramProgressPercent = computed(() => `${currentProgram.value.progress}%`)

const fullPlayerStatusText = computed(() => {
  if (playerStore.playbackError) return playerStore.playbackError
  if (isLoading.value) return '正在连接'
  if (isPlaying.value) return '直播中'
  return '已暂停'
})

const showProgramRemaining = computed(() => (
  !playerStore.playbackError && !isLoading.value && isPlaying.value
))

const playbackStateClass = computed(() => {
  if (playerStore.playbackError) return 'error'
  if (isLoading.value) return 'loading'
  if (isPlaying.value) return 'playing'
  return 'idle'
})

const isPlaybackConfirmed = computed(() => (
  !playerStore.playbackError && !isLoading.value && isPlaying.value
))

const displaySchedule = computed(() => {
  const epg = playerStore.currentEpgProgram
  if (epg) {
    // EPG 有数据时用 EPG schedule
    const schedule = _epgSchedule.value || []
    return schedule.map(p => {
      const startD = new Date(p.start)
      return {
        time: startD.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' }),
        title: p.title,
        current: p.status === 'current',
        past: p.status === 'past',
      }
    })
  }
  // 没有 EPG 时回退
  return [
    { time: '', title: currentProgram.value.title, current: true },
  ]
})

const displayChannelRows = computed(() => {
  if (isIptvMode.value) {
    const channels = iptvChannelList.value.length
      ? iptvChannelList.value
      : (playerStore.currentIptvChannel ? [playerStore.currentIptvChannel] : [])
    return channels.map((ch, index) => {
      const active = isCurrentIptv(ch)
      const playing = active && isPlaybackConfirmed.value
      return {
        key: `iptv-${ch.name}-${index}`,
        name: ch.name,
        logo: ch.logo_url || '',
        live: playing,
        playing,
        active,
        channel: ch,
        summary: active
          ? `当前：${currentProgram.value.title} · 剩余 ${currentProgram.value.remaining} 分钟`
          : `${ch.group_name || '直播频道'} · ${15 + (index % 5) * 5} 分钟`,
        select: () => playIptvChannelFromFullPlayer(ch),
      }
    })
  }

  return channelList.value.map((station, index) => {
    const active = currentStation.value === station.id
    const playing = active && isPlaybackConfirmed.value
    return {
      key: `radio-${station.id}`,
      name: station.name,
      logo: station.logoUrl || '',
      live: playing,
      playing,
      active,
      stationId: station.id,
      summary: active
        ? `当前：${station.subtitle || station.name} · 剩余 ${currentProgram.value.remaining} 分钟`
        : `${station.subtitle || '直播电台'} · ${15 + (index % 5) * 5} 分钟`,
      select: () => playerStore.switchStation(station.id),
    }
  })
})

function playIptvChannelFromFullPlayer(channel) {
  if (!channel?.urls?.length) {
    playerStore.setPlaybackError('频道没有可用播放源')
    return
  }

  const videoEl = playerStore.iptvVideoEl || iptvVideoRef.value
  if (videoEl) videoEl.play().catch(() => {})
  _manualIptvStartPending += 1
  playerStore.playIptvChannel(channel)
  nextTick(() => {
    _manualIptvStartPending = Math.max(0, _manualIptvStartPending - 1)
    if (!iptvVideoRef.value || !playerStore.currentIptvChannel) {
      return
    }
    resetRacedLosers()
    const attemptId = ++_playAttemptId
    playCurrentIptvUrl(attemptId).catch((e) => {
      console.warn('[IPTV] 列表切台起播失败:', e?.message)
    })
  })
}

function handleChannelRowClick(item) {
  if (import.meta.env.DEV) {
    console.log('channel row clicked', item)
    console.log(typeof item?.select)
  }

  if (typeof item?.select === 'function') {
    item.select()
    return
  }

  if (item?.channel) {
    playIptvChannelFromFullPlayer(item.channel)
    return
  }

  if (item?.stationId) {
    playerStore.switchStation(item.stationId)
  }
}

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

function syncIptvMediaSession(playbackState = isPlaying.value ? 'playing' : 'paused') {
  if (!isIptvMode.value || !('mediaSession' in navigator)) return
  try {
    navigator.mediaSession.metadata = new MediaMetadata({
      title: currentProgram.value?.title || currentStationName.value,
      artist: currentStationName.value,
      artwork: currentArtworkUrl.value ? [{ src: currentArtworkUrl.value }] : [],
    })
    navigator.mediaSession.playbackState = playbackState
    navigator.mediaSession.setActionHandler('play', () => {
      if (activeIptvEngine.value === 'youtube') {
        try { _youtubePlayer?.playVideo?.() } catch {}
      }
      playerStore.togglePlay(true)
    })
    navigator.mediaSession.setActionHandler('pause', () => {
      if (activeIptvEngine.value === 'youtube') {
        try { _youtubePlayer?.pauseVideo?.() } catch {}
      }
      playerStore.togglePlay(false)
    })
    navigator.mediaSession.setActionHandler('stop', () => {
      if (activeIptvEngine.value === 'youtube') destroyYoutubePlayer()
      playerStore.togglePlay(false)
      navigator.mediaSession.playbackState = 'none'
    })
  } catch (e) {
    console.warn('[IPTV] MediaSession 更新失败:', e)
  }
}

const iptvSourceOptions = computed(() => {
  return playerStore.iptvUrls.map((entry, index) => {
    const targetUrl = sourceTargetUrl(entry)
    const isProxySource = entry.type === 'proxy' || entry.via_proxy
    const st = sourceType(entry)
    const typeLabel = st === 'youtube' ? 'YT' : isProxySource ? '代理' : '直连'
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
      type: st === 'youtube' ? 'youtube' : isProxySource ? 'proxy' : entry.type,
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
  destroyYoutubePlayer()
}

function resetIptvVideo() {
  if (!iptvVideoRef.value) return
  stopPlaybackWatchdogs()
  iptvVideoRef.value.pause()
  iptvVideoRef.value.removeAttribute('src')
  iptvVideoRef.value.load()
}

function clearYoutubeStartupTimer() {
  if (!_youtubeStartupTimer) return
  clearTimeout(_youtubeStartupTimer)
  _youtubeStartupTimer = null
}

function destroyYoutubePlayer(resetEngine = true) {
  clearYoutubeStartupTimer()
  if (_youtubePlayer) {
    try {
      _youtubePlayer.stopVideo?.()
    } catch {}
    try {
      _youtubePlayer.destroy?.()
    } catch (e) {
      console.warn('[IPTV] YouTube cleanup failed:', e)
    }
    _youtubePlayer = null
  }
  if (youtubeHostRef.value) youtubeHostRef.value.innerHTML = ''
  if (resetEngine && activeIptvEngine.value === 'youtube') {
    activeIptvEngine.value = 'video'
  }
}

function syncYoutubeAudioState() {
  if (!_youtubePlayer) return
  try {
    _youtubePlayer.setVolume?.(Math.round(volume.value * 100))
    if (iptvMuted.value || volume.value <= 0) _youtubePlayer.mute?.()
    else _youtubePlayer.unMute?.()
  } catch {}
}

async function loadYoutubeIframeApi(timeoutMs = 3000) {
  const now = Date.now()
  if (window.YT?.Player) {
    _youtubeApiReachable = true
    _youtubeApiCheckedAt = now
    return true
  }
  if (_youtubeApiPromise && now - _youtubeApiCheckedAt < 60_000) return _youtubeApiPromise
  if (_youtubeApiReachable === false && now - _youtubeApiCheckedAt < 60_000) return false

  _youtubeApiCheckedAt = now
  _youtubeApiPromise = new Promise((resolve) => {
    let settled = false
    const previousReady = window.onYouTubeIframeAPIReady
    const finish = (ok) => {
      if (settled) return
      settled = true
      clearTimeout(timer)
      _youtubeApiReachable = ok
      _youtubeApiCheckedAt = Date.now()
      _youtubeApiPromise = null
      resolve(ok)
    }

    window.onYouTubeIframeAPIReady = () => {
      if (typeof previousReady === 'function') {
        try { previousReady() } catch {}
      }
      finish(Boolean(window.YT?.Player))
    }

    const timer = setTimeout(() => finish(Boolean(window.YT?.Player)), timeoutMs)

    if (!document.querySelector('script[data-wavebypass-youtube-api="1"]')) {
      const script = document.createElement('script')
      script.src = 'https://www.youtube.com/iframe_api'
      script.async = true
      script.dataset.wavebypassYoutubeApi = '1'
      script.onerror = () => {
        script.remove()
        finish(false)
      }
      document.head.appendChild(script)
    }
  })

  return _youtubeApiPromise
}

function preflightYoutubeApiForQueue(urls) {
  if (!urls?.some((entry) => sourceType(entry) === 'youtube')) return
  loadYoutubeIframeApi().catch(() => false)
}

async function handleActiveYoutubeFailure(reason, attemptId, sourceIndex) {
  if (!isAttemptActive(attemptId)) return
  console.warn('[IPTV] YouTube 播放中断，切备用源:', reason)
  setSourceRuntimeStatus(sourceIndex, 'failed')
  destroyYoutubePlayer()
  const nextAttemptId = ++_playAttemptId
  if (await fallbackToNextIptvUrl(nextAttemptId)) {
    return await playCurrentIptvUrl(nextAttemptId)
  }
  markAllIptvSourcesUnavailable(nextAttemptId)
}

async function startYoutubeCandidate(entry, attemptId = 0, sourceIndex = -1) {
  if (!isAttemptActive(attemptId)) throw cancelledError()
  const videoId = youtubeVideoId(entry)
  if (!videoId) throw new Error('YouTube video_id 缺失')

  const setRuntimeStatus = (status) => {
    if (sourceIndex >= 0) setSourceRuntimeStatus(sourceIndex, status)
    else setSourceRuntimeStatusByEntry(entry, status)
  }

  setRuntimeStatus('trying')
  playerStore.setLoading(true)
  cancelCurrentStartup()
  cancelActiveProxyRace()
  destroyIptvHls()
  destroyIptvMpegts()
  destroyYoutubePlayer(false)
  resetIptvVideo()

  const reachable = await loadYoutubeIframeApi()
  if (!isAttemptActive(attemptId)) throw cancelledError()
  if (!reachable || !window.YT?.Player) {
    setRuntimeStatus('failed')
    throw new Error('YouTube API 不可达')
  }
  if (!youtubeHostRef.value) throw new Error('YouTube 播放容器未就绪')

  activeIptvEngine.value = 'youtube'
  youtubeHostRef.value.innerHTML = ''
  console.log(`[START] YouTube:${videoId}`)

  return new Promise((resolve, reject) => {
    let settled = false
    let confirmed = false
    const cleanupFailure = () => {
      clearYoutubeStartupTimer()
      destroyYoutubePlayer()
    }
    const safeReject = (err) => {
      if (settled) return
      settled = true
      cleanupFailure()
      if (isAttemptActive(attemptId)) setRuntimeStatus('failed')
      reject(err)
    }
    const safeResolve = () => {
      if (settled || !isAttemptActive(attemptId)) return
      settled = true
      confirmed = true
      clearYoutubeStartupTimer()
      setRuntimeStatus('playing')
      playerStore.togglePlay(true)
      playerStore.clearPlaybackError()
      playerStore.setLoading(false)
      syncIptvMediaSession('playing')
      resolve()
    }

    _youtubeStartupTimer = setTimeout(() => {
      safeReject(new Error('YouTube 起播超时'))
    }, 8000)

    _youtubePlayer = new window.YT.Player(youtubeHostRef.value, {
      videoId,
      width: '100%',
      height: '100%',
      playerVars: {
        autoplay: 1,
        playsinline: 1,
        controls: 1,
        rel: 0,
        modestbranding: 1,
      },
      events: {
        onReady: () => {
          if (!isAttemptActive(attemptId)) {
            safeReject(cancelledError())
            return
          }
          syncYoutubeAudioState()
          try {
            _youtubePlayer?.playVideo?.()
          } catch (e) {
            safeReject(e)
          }
        },
        onStateChange: (event) => {
          if (!isAttemptActive(attemptId)) return
          const state = event?.data
          if (state === window.YT.PlayerState.PLAYING || state === window.YT.PlayerState.BUFFERING) {
            safeResolve()
            return
          }
          if (state === window.YT.PlayerState.PAUSED) {
            playerStore.togglePlay(false)
            syncIptvMediaSession('paused')
            return
          }
          if (state === window.YT.PlayerState.ENDED) {
            playerStore.togglePlay(false)
            syncIptvMediaSession('none')
            if (!confirmed) safeReject(new Error('YouTube 直播已结束'))
          }
        },
        onError: (event) => {
          const err = new Error(`YouTube 错误:${event?.data ?? ''}`)
          if (!confirmed) {
            safeReject(err)
            return
          }
          handleActiveYoutubeFailure(err.message, attemptId, sourceIndex)
        },
      },
    })
  })
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
}

function parseYoutubeVideoId(url) {
  try {
    const parsed = new URL(url)
    const host = parsed.hostname.toLowerCase()
    const parts = parsed.pathname.split('/').filter(Boolean)
    let id = ''
    if (host === 'youtu.be' || host === 'www.youtu.be') {
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

function isYoutubeUrl(url) {
  try {
    const host = new URL(url).hostname.toLowerCase()
    return host === 'youtu.be' || host === 'www.youtu.be' || host === 'youtube.com' || host.endsWith('.youtube.com') || host === 'youtube-nocookie.com' || host.endsWith('.youtube-nocookie.com')
  } catch {
    return false
  }
}

// source_type 优先，兜底回 URL 猜测
function sourceType(entry) {
  const url = entry?.url || ''
  const inferred = parseYoutubeVideoId(url)
    ? 'youtube'
    : isYoutubeUrl(url)
      ? 'unsupported_youtube_url'
      : isHlsUrl(url)
        ? 'hls'
        : isMpegTsUrl(url) ? 'mpegts' : 'hls'
  return entry?.source_type && entry.source_type !== 'hls' ? entry.source_type : inferred
}

function youtubeVideoId(entry) {
  return entry?.youtube_video_id || parseYoutubeVideoId(entry?.original_url || entry?.url || '')
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
const MPEGTS_RECONNECT_DELAY_MS = 1200
const MPEGTS_RECONNECT_WINDOW_MS = 60_000
const MPEGTS_RECONNECT_LIMIT = 3

let _playAttemptId = 0
let _racedLosers = new Set()
let _mpegtsRecoveries = new Map()
let _cleanupActiveRace = null
let _cancelCurrentStartup = null
let _suppressIptvUrlWatch = 0
let _manualIptvStartPending = 0
let _youtubePlayer = null
let _youtubeStartupTimer = null
let _youtubeApiPromise = null
let _youtubeApiReachable = null
let _youtubeApiCheckedAt = 0

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

function recordMpegtsReconnect(sourceUrl) {
  const now = Date.now()
  const record = _mpegtsRecoveries.get(sourceUrl)
  if (!record || now - record.firstAt > MPEGTS_RECONNECT_WINDOW_MS) {
    const nextRecord = { firstAt: now, count: 1 }
    _mpegtsRecoveries.set(sourceUrl, nextRecord)
    return nextRecord.count
  }

  record.count += 1
  _mpegtsRecoveries.set(sourceUrl, record)
  return record.count
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
  const setRuntimeStatus = (status) => {
    if (sourceIndex >= 0) setSourceRuntimeStatus(sourceIndex, status)
    else setSourceRuntimeStatusByUrl(sourceUrl, status)
  }

  const clearCompleteWatchTimer = () => {
    if (!completeWatchTimer) return
    clearTimeout(completeWatchTimer)
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

  const scheduleReconnectCurrentSource = (reason) => {
    if (switching || !isAttemptActive(attemptId)) return
    const reconnectCount = recordMpegtsReconnect(sourceUrl)
    const video = iptvVideoRef.value
    console.warn('[IPTV] MPEG-TS 播放中断，准备重连当前源', {
      reason,
      reconnectCount,
      limit: MPEGTS_RECONNECT_LIMIT,
      currentTime: Number.isFinite(video?.currentTime) ? video.currentTime : null,
      readyState: video?.readyState,
      networkState: video?.networkState,
    })

    if (reconnectCount > MPEGTS_RECONNECT_LIMIT) {
      switchToFallback(`${reason} repeated`)
      return
    }

    switching = true
    cleanup()
    setRuntimeStatus('trying')
    playerStore.setPlaybackError('直播连接断开，正在重新连接当前源')
    playerStore.setLoading(true)

    completeWatchTimer = setTimeout(async () => {
      completeWatchTimer = null
      if (!isAttemptActive(attemptId)) return
      clearCurrentMpegtsIf(player)
      try {
        player.destroy()
      } catch (e) {
        const message = e?.message || ''
        if (!message.includes('removeAllListeners')) {
          console.warn('[IPTV] mpegts reconnect cleanup failed:', e)
        }
      }

      const nextAttemptId = ++_playAttemptId
      await playCurrentIptvUrl(nextAttemptId, { allowStartupRace: false })
    }, MPEGTS_RECONNECT_DELAY_MS)
  }

  const onError = (type, detail, info) => {
    scheduleReconnectCurrentSource(`${type || 'mpegts error'}:${detail || info?.msg || ''}`)
  }

  const onComplete = () => {
    if (switching || !isAttemptActive(attemptId)) return
    if (completeWatchTimer) return

    scheduleReconnectCurrentSource('mpegts EOF')
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
  activeIptvEngine.value = 'video'
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
    const st = sourceType(entry)
    if (st === 'hls' && hlsProbeSupported) {
      racers.push({ entry, index: i, kind: 'hls' })
      continue
    }
    if (st === 'mpegts' && mpegtsProbeSupported) {
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
  preflightYoutubeApiForQueue(urls)
  if (idx >= urls.length) {
    markAllIptvSourcesUnavailable(attemptId)
    return
  }
  const entry = urls[idx]
  const st = sourceType(entry)
  if (st === 'unsupported_youtube_url') {
    setSourceRuntimeStatus(idx, 'failed')
    console.warn('[IPTV] 不支持的 YouTube URL:', entry.url)
    if (await fallbackToNextIptvUrl(attemptId)) {
      return await playCurrentIptvUrl(attemptId)
    }
    markAllIptvSourcesUnavailable(attemptId)
    return
  }
  const startupRacers = allowStartupRace && st !== 'youtube' ? startupRaceEntries(urls, idx) : []
  if (startupRacers.length > 1) {
    const raced = await raceStartupSources(startupRacers, attemptId)
    if (raced !== false) return raced
    if (!isAttemptActive(attemptId)) return
  }

  console.log(`[START] ${entry.type}:${entry.url.slice(0, 60)}...`)
  try {
    setSourceRuntimeStatus(idx, 'trying')
    if (st === 'youtube') {
      await startYoutubeCandidate(entry, attemptId, idx)
    } else {
      await tryPlayIptv(entry.url, Boolean(entry.via_proxy), entry.custom_ua || '', attemptId, idx)
    }
    if (!isAttemptActive(attemptId)) return
    setSourceRuntimeStatus(idx, 'playing')
    playerStore.clearPlaybackError()
    playerStore.setLoading(false)
  } catch (e) {
    if (!isAttemptActive(attemptId)) return
    setSourceRuntimeStatus(idx, 'failed')
    console.warn('[IPTV] 失败:', e?.message)
    if (st === 'mpegts' && allowStartupRace === false) {
      const reconnectCount = recordMpegtsReconnect(entry.url)
      if (reconnectCount <= MPEGTS_RECONNECT_LIMIT) {
        console.warn('[IPTV] MPEG-TS 重连起播失败，继续重试当前源', {
          reconnectCount,
          limit: MPEGTS_RECONNECT_LIMIT,
          reason: e?.message || 'startup failed',
        })
        setSourceRuntimeStatus(idx, 'trying')
        playerStore.setPlaybackError('直播连接断开，正在重新连接当前源')
        playerStore.setLoading(true)
        await new Promise(resolve => setTimeout(resolve, MPEGTS_RECONNECT_DELAY_MS))
        if (!isAttemptActive(attemptId)) return
        const nextAttemptId = ++_playAttemptId
        return await playCurrentIptvUrl(nextAttemptId, { allowStartupRace: false })
      }
    }
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

  const fresh = entries.filter((entry) => sourceType(entry) === 'hls' && isHlsUrl(entry.url) && !isMpegTsUrl(entry.url))
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

  const fresh = entries.filter(e => sourceType(e) !== 'youtube' && sourceType(e) !== 'unsupported_youtube_url' && !_racedLosers.has(e.url))
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
  if (activeIptvEngine.value === 'youtube') return
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
    syncIptvMediaSession('playing')
  }
  if (evt === 'pause') {
    clearStallRecoveryTimer()
    stopVideoFrameWatch()
    syncIptvMediaSession('paused')
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
    if (_manualIptvStartPending > 0) return
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
  nextTick(() => setFullPlayerChromeOpen(expanded))
})

watch(isPlaying, (playing) => {
  if (!isIptvMode.value) return
  if (activeIptvEngine.value === 'youtube') {
    if (!_youtubePlayer) return
    try {
      if (playing) _youtubePlayer.playVideo?.()
      else _youtubePlayer.pauseVideo?.()
    } catch {}
    syncIptvMediaSession(playing ? 'playing' : 'paused')
    return
  }
  if (!iptvVideoRef.value) return
  // 用户手动暂停后不自动恢复
  if (playing && iptvVideoRef.value.paused) {
    iptvVideoRef.value.play().catch(() => {})
  }
  if (!playing) iptvVideoRef.value.pause()
  syncIptvMediaSession(playing ? 'playing' : 'paused')
})

watch(volume, (v) => {
  if (activeIptvEngine.value === 'youtube') {
    syncYoutubeAudioState()
    return
  }
  if (iptvVideoRef.value) iptvVideoRef.value.volume = v
})

watch(() => playerStore.iptvUrlIndex, () => {
  if (_suppressIptvUrlWatch) return
  if (isIptvMode.value && isPlaying.value) {
    const attemptId = ++_playAttemptId
    playCurrentIptvUrl(attemptId)
  }
})

// EPG 集成
const { current: _epgCurrent, next: _epgNext, schedule: _epgSchedule, fetchPrograms: _epgFetch } = useEpg()

watch(() => playerStore.currentIptvChannel, (ch) => {
  if (ch?.canonical_key) {
    _epgFetch(ch.canonical_key).then(() => {
      playerStore.currentEpgProgram = _epgCurrent.value
    })
  } else {
    playerStore.currentEpgProgram = null
  }
})

onMounted(() => {
  syncFullPlayerTheme()
  setFullPlayerChromeOpen(isPlayerExpanded.value)
  themeObserver = new MutationObserver(syncFullPlayerTheme)
  themeObserver.observe(document.documentElement, { attributes: true, attributeFilter: ['class'] })
  themeObserver.observe(document.body, { attributes: true, attributeFilter: ['class'] })
  window.addEventListener('wavebypass-theme-chrome-sync', handleThemeChromeSync)
  document.addEventListener('click', closeSourceMenu)
  window.addEventListener('resize', updateSourceMenuPosition)
  window.addEventListener('orientationchange', updateSourceMenuPosition)
})

onBeforeUnmount(() => {
  setFullPlayerChromeOpen(false)
  themeObserver?.disconnect()
  themeObserver = null
  window.removeEventListener('wavebypass-theme-chrome-sync', handleThemeChromeSync)
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
.ios-sheet-enter-active {
  transition: transform 520ms cubic-bezier(0.22, 1, 0.36, 1), opacity 260ms ease;
  will-change: transform, opacity;
}
.ios-sheet-leave-active {
  transition: transform 420ms cubic-bezier(0.32, 0.72, 0, 1), opacity 200ms ease;
  will-change: transform, opacity;
}
.ios-sheet-enter-from,
.ios-sheet-leave-to {
  transform: translate3d(0, 18px, 0) scale(0.985);
  opacity: 0;
}
.ios-sheet-enter-to,
.ios-sheet-leave-from {
  transform: translate3d(0, 0, 0) scale(1);
  opacity: 1;
}

.fade-enter-active,
.fade-leave-active {
  transition: opacity 0.16s ease;
}

.fade-enter-from,
.fade-leave-to {
  opacity: 0;
}

.full-player {
  --page-bg: #f8f8f7;
  --surface-bg: #ffffff;
  --surface-soft: rgba(255, 255, 255, 0.72);
  --text-primary: #111827;
  --text-secondary: rgba(17, 24, 39, 0.56);
  --text-tertiary: rgba(17, 24, 39, 0.42);
  --text-quaternary: rgba(17, 24, 39, 0.28);
  --row-active-bg: rgba(15, 23, 42, 0.055);
  --row-separator: rgba(10, 10, 10, 0.045);
  --tag-bg: rgba(17, 24, 39, 0.08);
  --tag-text: rgba(17, 24, 39, 0.46);
  --logo-shadow: 0 6px 16px rgba(15, 23, 42, 0.08);
  --control-surface: rgba(255, 255, 255, 0.72);
  --control-shadow: 0 18px 42px rgba(0, 0, 0, 0.08), inset 0 0 0 1px rgba(255, 255, 255, 0.8);
  --media-placeholder-bg: #0b0d12;
  --progress-knob-bg: #fff;
  --accent: #35c87a;
  --black: #111827;
  --gold: #c79a2b;
  --muted: #8d9299;
  --line: rgba(17, 24, 39, 0.08);
  --layout-width: min(1580px, calc(100% - 88px));
  --layout-height: 100dvh;
  --layout-gap: clamp(36px, 3.4vw, 60px);
  --layout-padding: clamp(28px, 4vh, 44px) 0 clamp(24px, 3.2vh, 36px);
  --media-width: min(100%, 1040px, calc(58dvh * 1.8605));
  --media-height: auto;
  --media-radius: 8px;
  --media-shadow: 0 18px 42px rgba(15, 23, 42, 0.18);
  --panel-inline: 22px;
  --title-size: clamp(26px, 2.4vw, 36px);
  --title-weight: 750;
  --subtitle-size: 15px;
  --meta-size: 14px;
  --control-gap: clamp(38px, 5vw, 60px);
  --control-main-size: 62px;
  --control-main-icon: 26px;
  --control-side-size: 44px;
  --control-side-icon: 28px;
  --utility-gap: 30px;
  --utility-size: 30px;
  --utility-icon: 22px;
  --tab-gap: 30px;
  --tab-min-height: 42px;
  --tab-size: 15px;
  --tab-weight: 400;
  --tab-active-weight: 600;
  --tab-line-width: 46px;
  --channel-grid: 64px minmax(0, 1fr) 34px;
  --channel-gap: 16px;
  --channel-logo-size: 58px;
  --channel-min-height: 78px;
  --channel-margin: 12px;
  --channel-padding: 10px 14px 10px 8px;
  --channel-title-size: 16px;
  --channel-title-weight: 500;
  --channel-subtitle-size: 13px;
  --channel-subtitle-color: rgba(107, 114, 128, 0.68);
  --eq-width: 22px;
  --eq-height: 22px;
  --eq-opacity: 0.35;
  --timeline-grid: 66px 46px minmax(0, 1fr);
  --timeline-line-left: 89px;
  --timeline-row-height: 84px;
  --timeline-time-size: 15px;
  --timeline-title-size: 18px;
  --progress-track: rgba(17, 24, 39, 0.10);
  --progress-fill: rgba(17, 24, 39, 0.82);
  --progress-knob-bg: #ffffff;
  --progress-knob-border: rgba(17, 24, 39, 0.42);
  --progress-knob-ring: rgba(17, 24, 39, 0.12);
  overflow: hidden;
  min-height: 100dvh;
  isolation: isolate;
  background: var(--page-bg);
  color: var(--text-primary);
  font-family: -apple-system, BlinkMacSystemFont, "SF Pro Display", "SF Pro Text", "PingFang SC", "Hiragino Sans", "Microsoft YaHei", sans-serif;
  -webkit-font-smoothing: antialiased;
  text-rendering: optimizeLegibility;
}

.full-player::after {
  content: "";
  position: fixed;
  right: 0;
  bottom: 0;
  left: 0;
  z-index: 0;
  height: calc(env(safe-area-inset-bottom) + 120px);
  background: var(--page-bg);
  pointer-events: none;
}

:global(html.full-player-open),
:global(body.full-player-open),
:global(#app.full-player-open) {
  overflow: hidden !important;
}

.full-player.safari-chrome-refresh {
  display: none !important;
}

.full-player.theme-dark {
  --page-bg: #111113;
  --surface-bg: #18181b;
  --surface-soft: rgba(39, 39, 42, 0.72);
  --text-primary: rgba(250, 250, 250, 0.94);
  --text-secondary: rgba(250, 250, 250, 0.6);
  --text-tertiary: rgba(250, 250, 250, 0.42);
  --text-quaternary: rgba(250, 250, 250, 0.28);
  --row-active-bg: rgba(255, 255, 255, 0.055);
  --row-separator: rgba(255, 255, 255, 0.07);
  --tag-bg: rgba(255, 255, 255, 0.09);
  --tag-text: rgba(250, 250, 250, 0.48);
  --logo-shadow: 0 6px 16px rgba(0, 0, 0, 0.28);
  --control-surface: rgba(39, 39, 42, 0.72);
  --control-shadow: 0 18px 42px rgba(0, 0, 0, 0.22), inset 0 0 0 1px rgba(255, 255, 255, 0.08);
  --media-placeholder-bg: #050507;
  --progress-knob-bg: #f8f8f7;
  --gold: #d3aa43;
  --muted: rgba(250, 250, 250, 0.46);
  --line: rgba(255, 255, 255, 0.09);
  --channel-subtitle-color: rgba(250, 250, 250, 0.44);
  --progress-track: rgba(255, 255, 255, 0.14);
  --progress-fill: rgba(255, 255, 255, 0.82);
  --progress-knob-bg: #111113;
  --progress-knob-border: rgba(255, 255, 255, 0.48);
  --progress-knob-ring: rgba(255, 255, 255, 0.14);
}

.full-player,
.full-player *,
.full-player *::before,
.full-player *::after {
  box-sizing: border-box;
}

.player-layout {
  position: relative;
  z-index: 1;
  display: grid;
  grid-template-columns: minmax(0, 1.72fr) minmax(340px, 0.9fr);
  gap: var(--layout-gap);
  width: var(--layout-width);
  height: var(--layout-height);
  margin: 0 auto;
  padding: var(--layout-padding);
  background: var(--page-bg);
}

.player-main {
  display: flex;
  min-height: 0;
  min-width: 0;
  flex-direction: column;
}

.media-card {
  position: relative;
  box-sizing: border-box;
  overflow: hidden;
  width: var(--media-width);
  height: var(--media-height);
  aspect-ratio: 16 / 8.6;
  border-radius: var(--media-radius);
  background: var(--media-placeholder-bg);
  box-shadow: var(--media-shadow);
}

.media-video {
  display: block;
  width: 100%;
  height: 100%;
  object-fit: contain;
  background: var(--media-placeholder-bg);
}

.youtube-player-host {
  position: absolute;
  inset: 0;
  display: none;
  background: #000;
}

.youtube-player-host.active {
  display: block;
}

.youtube-player-host iframe {
  width: 100%;
  height: 100%;
}

.radio-art-stage {
  display: grid;
  place-items: center;
  width: 100%;
  height: 100%;
  background:
    radial-gradient(circle at 30% 20%, rgba(255, 255, 255, 0.32), transparent 36%),
    linear-gradient(135deg, #dfe8f2, #f4f1eb 52%, #e7f0ed);
}

.radio-art {
  display: grid;
  place-items: center;
  width: min(28vw, 190px);
  aspect-ratio: 1;
  overflow: hidden;
  border-radius: 24px;
  background: var(--surface-soft);
  color: var(--text-primary);
  font-size: 44px;
  font-weight: 700;
  box-shadow: 0 18px 40px rgba(15, 23, 42, 0.16);
}

.radio-art img,
.pill-logo img,
.channel-logo img {
  width: 100%;
  height: 100%;
  object-fit: cover;
}

.overlay-btn {
  position: absolute;
  z-index: 2;
  display: grid;
  place-items: center;
  width: 48px;
  height: 48px;
  border: 0;
  border-radius: 999px;
  background: rgba(15, 23, 42, 0.62);
  color: #fff;
  cursor: pointer;
  backdrop-filter: blur(12px);
  transition: transform 0.16s ease, background 0.16s ease;
}

.overlay-btn:hover {
  background: rgba(15, 23, 42, 0.76);
  transform: translateY(-1px);
}

.overlay-btn svg {
  width: 23px;
  height: 23px;
}

.overlay-back {
  top: 24px;
  left: 24px;
}

.overlay-info {
  top: 24px;
  right: 24px;
}

.mobile-live-pill {
  position: absolute;
  top: 16px;
  left: 50%;
  z-index: 3;
  display: none;
  align-items: center;
  justify-content: space-between;
  width: 180px;
  height: 48px;
  padding: 6px 14px 6px 8px;
  border: 1px solid rgba(255, 255, 255, 0.28);
  border-radius: 999px;
  background: rgba(0, 0, 0, 0.72);
  transform: translateX(-50%);
  backdrop-filter: blur(18px);
}

.pill-logo {
  display: grid;
  place-items: center;
  width: 36px;
  height: 36px;
  overflow: hidden;
  border-radius: 11px;
  background: var(--surface-bg);
  color: var(--text-primary);
  font-weight: 600;
}

.mini-eq {
  width: var(--eq-width);
  height: var(--eq-height);
  background: linear-gradient(90deg, currentColor 12%, transparent 12% 22%, currentColor 22% 34%, transparent 34% 45%, currentColor 45% 57%, transparent 57% 68%, currentColor 68% 80%, transparent 80% 90%, currentColor 90%);
  color: var(--text-quaternary);
  mask: linear-gradient(to top, transparent 10%, #000 10%);
  opacity: var(--eq-opacity);
}

.eq-icon {
  display: block;
  width: var(--eq-width);
  height: var(--eq-height);
  color: var(--accent);
  fill: currentColor;
  opacity: 0;
}

.mini-eq.active,
.eq-icon.active {
  color: var(--accent);
  opacity: 0.9;
}

.now-panel {
  padding: 18px var(--panel-inline) 0;
  text-align: left;
}

.now-panel h1 {
  margin: 0;
  font-size: var(--title-size);
  line-height: 1.18;
  font-weight: var(--title-weight);
  letter-spacing: -0.03em;
}

.now-panel > p {
  margin: 10px 0 0;
  color: var(--text-tertiary);
  font-size: var(--subtitle-size);
  font-weight: 500;
  line-height: 1.2;
}

.program-progress {
  margin-top: 18px;
}

.progress-track {
  position: relative;
  height: 2px;
  border-radius: 999px;
  background: var(--progress-track);
}

.progress-fill {
  height: 100%;
  border-radius: inherit;
  background: var(--progress-fill);
}

.progress-knob {
  position: absolute;
  top: 50%;
  width: 12px;
  height: 12px;
  border: 2px solid var(--progress-knob-border);
  border-radius: 999px;
  background: var(--progress-knob-bg);
  transform: translate(-50%, -50%);
  box-shadow: 0 0 0 1px var(--progress-knob-ring);
}

.progress-times,
.program-state {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-top: 14px;
  color: var(--text-primary);
  font-size: var(--meta-size);
  font-weight: 400;
}

.program-state {
  justify-content: center;
  gap: 7px;
  color: var(--text-secondary);
  font-weight: 500;
}

.state-dot {
  width: 7px;
  height: 7px;
  border-radius: 999px;
  background: var(--text-quaternary);
}

.state-dot.playing {
  background: var(--accent);
}

.state-dot.playing + span {
  color: var(--accent);
}

.state-dot.loading {
  border: 1px solid var(--text-quaternary);
  border-top-color: var(--gold);
  background: transparent;
  animation: spin 0.9s linear infinite;
}

.state-dot.error {
  background: rgba(239, 68, 68, 0.75);
}

@keyframes spin {
  to {
    transform: rotate(360deg);
  }
}

.transport-row {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: var(--control-gap);
  margin-top: 20px;
}

.transport-side,
.transport-main,
.utility-btn {
  display: grid;
  place-items: center;
  border: 0;
  background: transparent;
  color: var(--text-primary);
  cursor: pointer;
}

.transport-side {
  width: var(--control-side-size);
  height: var(--control-side-size);
}

.transport-side svg {
  width: var(--control-side-icon);
  height: var(--control-side-icon);
}

.transport-main {
  width: var(--control-main-size);
  height: var(--control-main-size);
  border-radius: 999px;
  background: var(--control-surface);
  box-shadow: var(--control-shadow);
  backdrop-filter: blur(20px);
  -webkit-backdrop-filter: blur(20px);
}

.transport-main svg {
  width: var(--control-main-icon);
  height: var(--control-main-icon);
}

.utility-row {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: var(--utility-gap);
  margin-top: 14px;
  min-height: 30px;
}

.utility-btn {
  position: relative;
  width: var(--utility-size);
  height: var(--utility-size);
  color: var(--tag-text);
}

.utility-btn svg {
  width: var(--utility-icon);
  height: var(--utility-icon);
}

.source-dot {
  position: absolute;
  top: 6px;
  right: 5px;
  width: 7px;
  height: 7px;
  border-radius: 999px;
}

.volume-control {
  display: flex;
  align-items: center;
  gap: 10px;
  color: var(--text-tertiary);
}

.volume-control svg {
  width: 21px;
  height: 21px;
}

.volume-control input {
  width: 70px;
  accent-color: var(--text-primary);
}

.side-panel {
  min-width: 0;
  min-height: 0;
  padding-top: 14px;
}

.mobile-panel {
  display: none;
}

.panel-tabs {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: var(--tab-gap);
  border-bottom: 1px solid var(--line);
}

.panel-tabs button {
  position: relative;
  min-height: var(--tab-min-height);
  border: 0;
  background: transparent;
  color: var(--text-tertiary);
  font-size: var(--tab-size);
  font-weight: var(--tab-weight);
  letter-spacing: 0;
  text-align: left;
  cursor: pointer;
}

.panel-tabs button.active {
  color: var(--text-primary);
  font-weight: var(--tab-active-weight);
}

.panel-tabs button.active::after {
  content: "";
  position: absolute;
  left: 0;
  bottom: -1px;
  width: var(--tab-line-width);
  height: 3px;
  border-radius: 999px;
  background: var(--black);
}

.desktop-panel-scroll {
  max-height: calc(100dvh - 126px);
  overflow-y: auto;
  padding-right: 8px;
}

.channel-panel {
  padding-top: 24px;
}

.channel-row {
  display: grid;
  grid-template-columns: var(--channel-grid);
  align-items: center;
  gap: var(--channel-gap);
  width: 100%;
  min-height: var(--channel-min-height);
  margin-bottom: var(--channel-margin);
  padding: var(--channel-padding);
  border: 0;
  border-radius: 8px;
  background: transparent;
  color: inherit;
  text-align: left;
  cursor: pointer;
}

.channel-row.active {
  background: var(--row-active-bg);
}

.channel-logo {
  display: grid;
  place-items: center;
  width: var(--channel-logo-size);
  height: var(--channel-logo-size);
  overflow: hidden;
  border-radius: 8px;
  background: var(--surface-bg);
  color: var(--text-primary);
  font-size: 14px;
  font-weight: 600;
  box-shadow: var(--logo-shadow);
}

.channel-copy {
  display: block;
  min-width: 0;
}

.channel-title {
  display: flex;
  min-width: 0;
  align-items: center;
  gap: 8px;
  color: var(--text-primary);
  font-size: var(--channel-title-size);
  font-weight: var(--channel-title-weight);
  line-height: 1.25;
}

.channel-title > :first-child {
  min-width: 0;
}

.channel-subtitle {
  display: block;
  margin-top: 6px;
  overflow: hidden;
  color: var(--channel-subtitle-color);
  font-size: var(--channel-subtitle-size);
  font-weight: 500;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.tag {
  display: inline-flex;
  align-items: center;
  min-height: 20px;
  padding: 2px 8px;
  border-radius: 6px;
  background: var(--tag-bg);
  color: var(--text-tertiary);
  font-size: 12px;
  font-weight: 500;
  white-space: nowrap;
}

.live-dot {
  width: 6px;
  height: 6px;
  border-radius: 999px;
  background: var(--accent);
  opacity: 0.72;
}

.live-label {
  color: var(--accent);
  font-size: 15px;
  font-weight: 500;
  white-space: nowrap;
}

.schedule-panel {
  padding-top: 30px;
}

.schedule-date {
  display: inline-flex;
  align-items: center;
  gap: 10px;
  color: var(--text-primary);
  font-size: 24px;
  font-weight: 800;
  letter-spacing: -0.02em;
}

.schedule-date svg {
  width: 21px;
  height: 21px;
}

.timeline {
  position: relative;
  margin-top: 34px;
}

.timeline::before {
  content: "";
  position: absolute;
  top: 13px;
  bottom: 24px;
  left: var(--timeline-line-left);
  width: 2px;
  background: var(--line);
}

.timeline-row {
  position: relative;
  display: grid;
  grid-template-columns: var(--timeline-grid);
  align-items: center;
  min-height: var(--timeline-row-height);
  color: var(--text-primary);
}

.timeline-time {
  color: var(--text-tertiary);
  font-size: var(--timeline-time-size);
  font-weight: 500;
  font-variant-numeric: tabular-nums;
}

.timeline-dot {
  position: relative;
  z-index: 1;
  width: 15px;
  height: 15px;
  border: 2px solid var(--text-quaternary);
  border-radius: 999px;
  background: var(--page-bg);
  justify-self: center;
}

.timeline-row.current .timeline-dot {
  border-color: var(--accent);
  background: var(--accent);
  box-shadow: 0 0 22px rgba(47, 189, 115, 0.55);
}

.timeline-row.past {
  opacity: 0.4;
}

.timeline-title {
  display: flex;
  align-items: center;
  gap: 12px;
  font-size: var(--timeline-title-size);
  font-weight: 700;
  line-height: 1.3;
}

.live-tag {
  border: 1px solid rgba(47, 189, 115, 0.62);
  background: rgba(47, 189, 115, 0.08);
  color: #20a760;
}

@media (max-width: 980px) {
  .full-player {
    --layout-width: 100%;
    --layout-height: auto;
    --layout-padding: 0 0 calc(env(safe-area-inset-bottom) + 96px);
    --media-width: 100vw;
    --media-height: clamp(220px, 56vw, 245px);
    --media-radius: 0;
    --media-shadow: none;
    --panel-inline: 32px;
    --title-size: 21px;
    --title-weight: 500;
    --subtitle-size: 13px;
    --meta-size: 12px;
    --control-gap: 28px;
    --control-main-size: 56px;
    --control-main-icon: 22px;
    --control-side-size: 42px;
    --control-side-icon: 22px;
    --utility-gap: 32px;
    --utility-size: 38px;
    --utility-icon: 18px;
    --tab-gap: 0;
    --tab-min-height: 32px;
    --tab-size: 14px;
    --tab-weight: 550;
    --tab-active-weight: 600;
    --tab-line-width: 32px;
    --channel-grid: 44px minmax(0, 1fr) 22px;
    --channel-gap: 14px;
    --channel-logo-size: 44px;
    --channel-min-height: 68px;
    --channel-margin: 0;
    --channel-padding: 6px 30px;
    --channel-title-size: 14px;
    --channel-title-weight: 500;
    --channel-subtitle-size: 11px;
    --channel-subtitle-color: rgba(10, 10, 10, 0.34);
    --eq-width: 20px;
    --eq-height: 22px;
    --eq-opacity: 0.16;
    --timeline-grid: 56px 30px minmax(0, 1fr);
    --timeline-line-left: 70px;
    --timeline-row-height: 58px;
    --timeline-time-size: 13px;
    --timeline-title-size: 15px;
    overflow-y: auto;
    background: var(--page-bg);
  }

  .player-layout {
    display: block;
    width: var(--layout-width);
    min-height: 100dvh;
    padding: var(--layout-padding);
    background: var(--page-bg);
  }

  .media-card {
    width: var(--media-width);
    height: var(--media-height);
    margin-left: calc(50% - 50vw);
    aspect-ratio: auto;
    border-radius: var(--media-radius);
    box-shadow: var(--media-shadow);
  }

  .media-video {
    position: absolute;
    inset: 0;
    object-fit: cover;
    object-position: center 45%;
  }

  .radio-art-stage {
    position: absolute;
    inset: 0;
  }

  .mobile-live-pill {
    display: none;
  }

  .overlay-btn {
    top: 16px;
    display: grid;
    width: 44px;
    height: 44px;
    background: rgba(0, 0, 0, 0.36);
    color: #fff;
    backdrop-filter: blur(18px);
    -webkit-backdrop-filter: blur(18px);
  }

  .overlay-btn:hover {
    background: rgba(0, 0, 0, 0.44);
    transform: none;
  }

  .overlay-btn svg {
    width: 23px;
    height: 23px;
  }

  .overlay-back {
    left: 24px;
  }

  .overlay-info {
    right: 24px;
  }

  .now-panel {
    padding: 22px var(--panel-inline) 0;
    text-align: center;
  }

  .now-panel h1 {
    font-size: var(--title-size);
    line-height: 1.16;
    font-weight: var(--title-weight);
    letter-spacing: -0.03em;
    font-synthesis: none;
  }

  .now-panel > p {
    margin-top: 6px;
    font-size: var(--subtitle-size);
    font-weight: 400;
    color: var(--text-tertiary);
  }

  .program-progress {
    margin-top: 16px;
  }

  .progress-knob {
    width: 11px;
    height: 11px;
  }

  .progress-times {
    margin-top: 8px;
    font-size: var(--meta-size);
    font-weight: 400;
  }

  .program-state {
    margin-top: 8px;
    color: var(--text-secondary);
    font-size: var(--meta-size);
    font-weight: 400;
  }

  .transport-row {
    gap: var(--control-gap);
    margin-top: 16px;
  }

  .transport-side {
    width: var(--control-side-size);
    height: var(--control-side-size);
  }

  .transport-side svg {
    width: var(--control-side-icon);
    height: var(--control-side-icon);
  }

  .transport-main {
    width: var(--control-main-size);
    height: var(--control-main-size);
  }

  .transport-main svg {
    width: var(--control-main-icon);
    height: var(--control-main-icon);
  }

  .utility-row {
    gap: var(--utility-gap);
    margin-top: 10px;
  }

  .utility-btn {
    width: var(--utility-size);
    height: var(--utility-size);
  }

  .utility-btn svg {
    width: var(--utility-icon);
    height: var(--utility-icon);
  }

  .volume-control {
    display: grid;
    place-items: center;
    width: var(--utility-size);
    height: var(--utility-size);
  }

  .volume-control svg {
    width: var(--utility-icon);
    height: var(--utility-icon);
  }

  .volume-control input {
    display: none;
  }

  .side-panel {
    display: none;
  }

  .mobile-panel {
    display: block;
    padding: 22px 0 0;
  }

  .panel-tabs {
    gap: var(--tab-gap);
    padding: 0 52px;
    border-bottom: 0;
  }

  .panel-tabs button {
    min-height: var(--tab-min-height);
    font-size: var(--tab-size);
    font-weight: var(--tab-weight);
    text-align: center;
  }

  .panel-tabs button.active {
    font-weight: var(--tab-active-weight);
  }

  .panel-tabs button.active::after {
    left: 50%;
    bottom: -10px;
    width: var(--tab-line-width);
    transform: translateX(-50%);
  }

  .channel-panel {
    padding-top: 14px;
  }

  .channel-row {
    grid-template-columns: var(--channel-grid);
    min-height: var(--channel-min-height);
    margin-bottom: var(--channel-margin);
    padding: var(--channel-padding);
    border-bottom: 1px solid var(--row-separator);
    border-radius: 0;
  }

  .channel-row:last-child {
    border-bottom: 0;
  }

  .channel-row.active {
    background: transparent;
  }

  .channel-logo {
    width: var(--channel-logo-size);
    height: var(--channel-logo-size);
    border-radius: 13px;
    font-weight: 500;
    box-shadow: var(--logo-shadow);
  }

  .channel-title {
    gap: 6px;
    font-size: var(--channel-title-size);
    font-weight: var(--channel-title-weight);
    line-height: 1.22;
    letter-spacing: -0.01em;
    font-synthesis: none;
  }

  .channel-subtitle {
    margin-top: 5px;
    font-size: var(--channel-subtitle-size);
    font-weight: 400;
    color: var(--channel-subtitle-color);
  }

  .channel-row .eq-icon {
    align-self: center;
    justify-self: end;
  }

  .channel-row .eq-icon.active {
    opacity: 0.9;
  }

  .tag {
    min-height: 18px;
    padding: 1px 7px;
    font-size: 11px;
  }

  .schedule-panel {
    padding: 24px 30px 0;
  }

  .schedule-date {
    font-size: 20px;
    font-weight: 720;
  }

  .timeline {
    margin-top: 24px;
  }

  .timeline-row {
    grid-template-columns: var(--timeline-grid);
    min-height: var(--timeline-row-height);
  }

  .timeline::before {
    left: var(--timeline-line-left);
  }

  .timeline-title {
    font-size: var(--timeline-title-size);
    font-weight: 700;
  }

  .timeline-time {
    font-size: var(--timeline-time-size);
    font-weight: 500;
  }

  .timeline-dot {
    width: 11px;
    height: 11px;
  }

  .timeline-row.current .timeline-dot {
    width: 14px;
    height: 14px;
    box-shadow: 0 0 0 6px rgba(53, 200, 122, 0.14);
  }

  .live-tag {
    min-height: 26px;
    font-size: 13px;
  }
}

@media (max-width: 520px) {
  .full-player {
    --panel-inline: 30px;
    --media-height: clamp(220px, 56vw, 245px);
    --title-size: 21px;
    --title-weight: 500;
    --subtitle-size: 13px;
    --meta-size: 12px;
    --control-gap: 24px;
    --control-main-size: 56px;
    --control-main-icon: 22px;
    --control-side-size: 42px;
    --control-side-icon: 22px;
    --utility-gap: 32px;
    --utility-size: 38px;
    --utility-icon: 18px;
    --channel-padding: 6px 30px;
    --channel-grid: 44px minmax(0, 1fr) 22px;
    --channel-logo-size: 44px;
    --channel-min-height: 68px;
    --channel-title-size: 14px;
    --channel-title-weight: 500;
    --channel-subtitle-size: 11px;
    --channel-subtitle-color: rgba(10, 10, 10, 0.34);
    --eq-width: 20px;
    --eq-height: 22px;
    --eq-opacity: 0.16;
    --timeline-grid: 56px 30px minmax(0, 1fr);
    --timeline-line-left: 70px;
  }
}
</style>
