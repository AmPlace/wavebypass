<template>
  <main class="iptv-main min-h-screen w-full px-5 pb-32 pt-[calc(env(safe-area-inset-top)+4rem)] sm:px-8 lg:px-10 lg:pb-40 lg:pt-6">
    <header class="mb-7 space-y-7">
      <div class="lg:pr-[300px]">
        <TagFilterRow
          :items="categoryTabs"
          :is-active="isSelectedCategory"
          @select="selectCategoryTab"
        />
      </div>

      <div class="flex items-center justify-between gap-4">
        <div class="flex min-w-0 items-center gap-3">
          <span class="flex size-8 shrink-0 items-center justify-center rounded-full bg-[var(--surface)] text-[var(--text-primary)]">
            <svg class="size-4" viewBox="0 0 24 24" fill="none" aria-hidden="true">
              <path d="M5 12a7 7 0 0 1 14 0M2.5 12a9.5 9.5 0 0 1 19 0M9 12a3 3 0 0 1 6 0" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/>
            </svg>
          </span>
          <h1 class="truncate text-lg font-semibold leading-none text-[var(--text-primary)]">正在直播</h1>
          <span class="shrink-0 text-sm text-[var(--text-secondary)]">
            共 {{ filteredChannels.length }} 个频道
          </span>
          <span v-if="loading" class="hidden text-sm text-[var(--text-tertiary)] sm:inline">加载中...</span>
        </div>

        <button
          type="button"
          class="inline-flex h-10 shrink-0 items-center gap-2 rounded-full border border-[var(--border)] bg-[var(--surface)] px-4 text-sm font-medium text-[var(--text-secondary)] transition-colors hover:bg-[var(--surface-hover)] hover:text-[var(--text-primary)]"
          @click="nextSortMode"
        >
          <svg class="size-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
            <line x1="4" y1="6" x2="20" y2="6"/><line x1="4" y1="12" x2="16" y2="12"/><line x1="4" y1="18" x2="12" y2="18"/>
          </svg>
          {{ currentSortLabel }}
        </button>
      </div>
    </header>

    <section
      ref="gridRef"
      class="relative w-full"
      :style="{ height: `${totalHeight}px` }"
    >
      <div
        v-for="row in virtualRows"
        :key="row.startIndex"
        class="absolute left-0 top-0 w-full"
        :style="{ transform: `translateY(${row.startIndex * (rowHeight + gap)}px)` }"
      >
        <div
          class="grid"
          :style="{ gap: `${gap}px`, gridTemplateColumns: `repeat(${columns}, minmax(0, 1fr))` }"
        >
          <button
            v-for="item in row.items"
            :key="item.channel.name"
            type="button"
            :aria-label="`播放 ${item.channel.name}`"
            :style="{ height: `${cardHeight}px` }"
            :disabled="isUnavailable(item.channel)"
            class="channel-card group relative overflow-hidden rounded-[18px] border border-[var(--border)] bg-[var(--card-bg)] text-left outline-none transition duration-200 ease-out hover:-translate-y-0.5 hover:border-[var(--border-strong)] disabled:cursor-not-allowed disabled:opacity-45"
            :class="[defaultCoverClass(item.channel), { 'channel-card-current': isCurrentChannel(item.channel) }]"
            @click="playChannel(item.channel)"
          >
            <span class="channel-card__logo-card-visual" aria-hidden="true">
              <span
                class="channel-card__logo-stage"
                :class="logoStageClass(item.channel)"
              >
                <img
                  v-if="shouldShowChannelLogo(item.channel)"
                  class="channel-card__center-logo"
                  :class="logoImageClass(item.channel)"
                  :src="channelLogoUrl(item.channel)"
                  alt=""
                  loading="lazy"
                  decoding="async"
                  @load="classifyChannelLogo(item.channel, $event)"
                  @error="markChannelLogoFailed(item.channel)"
                />
                <span
                  v-else
                  class="channel-card__text-logo"
                  :class="textLogoSizeClass(item.channel)"
                  :title="channelDisplayName(item.channel)"
                >
                  {{ channelDisplayName(item.channel) }}
                </span>
              </span>
              <span class="channel-card__logo-card-shade"></span>
            </span>
            <span class="card-info">
              <span class="card-channel">
                <span
                  class="channel-play-state-dot"
                  :class="channelStatusDotClass(item.channel)"
                  :title="channelStatusLabel(item.channel)"
                  :aria-label="channelStatusLabel(item.channel)"
                  role="img"
                />
                <span class="card-channel-name">{{ item.channel.name }}</span>
              </span>
              <span class="card-program-name">{{ cardSubtitle(item.channel) }}</span>
            </span>
          </button>
        </div>
      </div>
    </section>
  </main>
</template>

<script setup>
import { computed, inject, onBeforeUnmount, onMounted, ref, watch, watchEffect } from 'vue'
import { useScroll, useThrottleFn } from '@vueuse/core'
import { usePlayerStore } from '../stores/player'
import { fetchAggregatedChannels, fetchAdapterCover } from '../api/iptv'
import { useEpg } from '../composables/useEpg'
import { useLogoVisual } from '../composables/useLogoVisual'
import TagFilterRow from '../components/TagFilterRow.vue'

const playerStore = usePlayerStore()

const scrollRef = inject('scrollRef')
const searchQuery = inject('searchQuery')

const allChannels = ref([])
const allGroups = ref([])
const selectedGroup = ref('')
const loading = ref(false)
const epgMap = ref({})
const logoCandidateIndexes = ref({})
const channelSortMode = ref('original')
const categoryTabs = computed(() => ['全部', ...allGroups.value])

const YOUTUBE_THUMBNAIL_VARIANTS = ['maxresdefault', 'hq720', 'hqdefault']

// adapter 直播间封面/头像懒加载。
// 哪些 adapter 支持 cover 不在前端硬编码，由后端 /api/iptv/channels response 顶层
// adapter_capabilities 字段提供：{ bilibili: ["cover"], douyu: ["cover"], ... }。
// 这样后端给某个 adapter 加 ADAPTER_CAPABILITIES = {"cover": True} 后，前端不用改。
const adapterCoverSupported = ref(new Set())
const adapterCoverCache = ref({})    // canonical_key -> { cover_url, avatar_url }
const adapterCoverInflight = new Map()
const adapterCoverFailed = new Set()

const {
  displayName: channelDisplayName,
  shouldShowLogo: shouldShowChannelLogo,
  logoStageClass,
  logoImageClass,
  classifyLogo: classifyChannelLogo,
  markLogoFailed: markChannelLogoFailed,
  textLogoSizeClass,
} = useLogoVisual({
  getLogoUrl: channelLogoUrl,
  getDisplayName: channelDisplayNameValue,
  getIdentityKey: channelLogoIdentityKey,
  getFailureKey: channelLogoCandidateKey,
  getVisualKey: (ch) => `${channelLogoIdentityKey(ch)}|${channelLogoUrl(ch)}`,
  onBeforeShow: ensureAdapterCover,
  onBeforeClassify: (ch, { width, height }) => (
    isCurrentYoutubeThumbnailCandidate(ch)
    && width < 480
    && height < 240
    && advanceChannelLogoCandidate(ch)
  ),
  onBeforeFail: advanceChannelLogoCandidate,
  fallbackName: '未知频道',
})

function adapterCoverTargetUrl(ch) {
  // 一条聚合频道的 ch.urls 可能混着多个来源（例如 ytsl:// + huya://），
  // 顶层 ch.adapter 由"主 url"决定，并不一定就是支持 cover 的那家，
  // 所以这里直接扫 ch.urls，挑第一条 scheme 在能力表里的 adapter URL。
  const urls = Array.isArray(ch?.urls) ? ch.urls : []
  for (const item of urls) {
    const raw = String(item?.url || '').trim()
    const m = /^([a-z][a-z0-9+\-.]*):\/\//i.exec(raw)
    if (!m) continue
    const scheme = m[1].toLowerCase()
    if (adapterCoverSupported.value.has(scheme)) return raw
  }
  return ''
}

function ensureAdapterCover(ch) {
  const key = ch?.canonical_key || ''
  if (!key) return
  if (adapterCoverCache.value[key]) return
  if (adapterCoverFailed.has(key)) return
  if (adapterCoverInflight.has(key)) return
  const targetUrl = adapterCoverTargetUrl(ch)
  if (!targetUrl) return
  const promise = fetchAdapterCover(targetUrl)
    .then(payload => {
      const cover = String(payload?.cover_url || '').trim()
      const avatar = String(payload?.avatar_url || '').trim()
      if (cover || avatar) {
        adapterCoverCache.value = { ...adapterCoverCache.value, [key]: { cover_url: cover, avatar_url: avatar } }
      } else {
        adapterCoverFailed.add(key)
      }
    })
    .catch(() => { adapterCoverFailed.add(key) })
    .finally(() => { adapterCoverInflight.delete(key) })
  adapterCoverInflight.set(key, promise)
}

const SORT_MODES = [
  { key: 'original', label: '默认排序' },
  { key: 'natural', label: 'A-Z排序' },
  { key: 'group', label: '分组排序' },
]

function naturalSort(a, b) {
  return a.localeCompare(b, undefined, { numeric: true, sensitivity: 'base' })
}

function nextSortMode() {
  const idx = SORT_MODES.findIndex(m => m.key === channelSortMode.value)
  channelSortMode.value = SORT_MODES[(idx + 1) % SORT_MODES.length].key
}

const currentSortLabel = computed(() => SORT_MODES.find(m => m.key === channelSortMode.value)?.label || '默认排序')

function selectCategoryTab(tab) {
  selectedGroup.value = tab === '全部' ? '' : tab
  loadChannels()
}

function isSelectedCategory(tab) {
  return tab === '全部' ? !selectedGroup.value : selectedGroup.value === tab
}

async function loadChannels() {
  loading.value = true
  try {
    const data = await fetchAggregatedChannels({ group: selectedGroup.value, search: searchQuery.value.trim() })
    allChannels.value = data.channels || []
    if (!selectedGroup.value && !searchQuery.value.trim()) {
      allGroups.value = data.groups || []
    }
    // 同步后端 adapter 能力表：仅取支持 "cover" 的 adapter 名字。
    const caps = data.adapter_capabilities || {}
    const next = new Set()
    for (const [name, list] of Object.entries(caps)) {
      if (Array.isArray(list) && list.includes('cover')) next.add(String(name).toLowerCase())
    }
    adapterCoverSupported.value = next
    const keys = (data.channels || []).map(c => c.canonical_key).filter(Boolean)
    if (keys.length) {
      useEpg().batchCurrent(keys).then(m => { epgMap.value = m || {} })
    }
  } catch (e) {
    console.error('加载频道失败:', e)
  }
  loading.value = false
}

const filteredChannels = computed(() => {
  const list = allChannels.value.slice()
  if (channelSortMode.value === 'natural') {
    list.sort((a, b) => naturalSort(a.name || '', b.name || ''))
  } else if (channelSortMode.value === 'group') {
    list.sort((a, b) => naturalSort(a.group_name || '', b.group_name || '') || naturalSort(a.name || '', b.name || ''))
  }
  return list
})

onMounted(loadChannels)

watch(searchQuery, () => { loadChannels() })

function isCurrentChannel(ch) {
  const current = playerStore.pendingIptvChannel || playerStore.currentIptvChannel
  return current && current.name === ch.name
}

function isUntested(ch) {
  return ch.urls.every(u => {
    const status = u.probe_status || ''
    return status ? status === 'untested' : u.is_working === -1
  })
}

function isAllFailed(ch) {
  return ch.urls.every(u => {
    const status = u.probe_status || ''
    if (status) return ['offline', 'error', 'timeout'].includes(status)
    return u.is_working === 0
  })
}

function isAllNotLive(ch) {
  return ch.urls.length > 0 && ch.urls.every(u => u.probe_status === 'not_live')
}

function isUnavailable(ch) {
  return ch.urls.length > 0 && ch.urls.every(u => {
    const status = u.probe_status || ''
    if (status) return ['offline', 'error', 'timeout', 'not_live'].includes(status)
    return u.is_working === 0
  })
}

function isAnyPlayable(ch) {
  return ch.urls?.some(u => {
    const status = u.probe_status || ''
    if (status) return status === 'online'
    return u.is_working === 1
  })
}

function currentProgramTitle(ch) {
  return epgMap.value[ch.canonical_key]?.current?.title || ''
}

function cardSubtitle(ch) {
  return currentProgramTitle(ch) || ch.group_name || ''
}

function channelStatusKind(ch) {
  if (isAnyPlayable(ch)) return 'live'
  if (isAllNotLive(ch)) return 'warn'
  if (isUntested(ch)) return 'neutral'
  if (isAllFailed(ch) || isUnavailable(ch)) return 'danger'
  return 'neutral'
}

function channelStatusDotClass(ch) {
  return `channel-play-state-dot--${channelStatusKind(ch)}`
}

function channelStatusLabel(ch) {
  const kind = channelStatusKind(ch)
  if (kind === 'warn') return '未开播'
  if (kind === 'danger') return '不可用'
  if (kind === 'neutral') return '未测试'
  return '可播放'
}

function defaultCoverClass() {
  return 'channel-card--logo-card'
}

function channelLogoUrl(ch) {
  const candidates = channelLogoCandidates(ch)
  if (!candidates.length) return ''
  const index = logoCandidateIndexes.value[channelLogoCandidateKey(ch)] || 0
  return candidates[index] || candidates[0] || ''
}

function channelLogoCandidates(ch) {
  const logoUrl = String(ch?.logo_url || '').trim()
  const youtubeVideoId = channelYoutubeVideoId(ch)
  const candidates = youtubeVideoId ? youtubeThumbnailUrls(youtubeVideoId) : []
  const adapterCover = adapterCoverCache.value[ch?.canonical_key || '']
  if (adapterCover) {
    if (adapterCover.cover_url) candidates.push(adapterCover.cover_url)
    if (adapterCover.avatar_url) candidates.push(adapterCover.avatar_url)
  }
  if (logoUrl) candidates.push(logoUrl)
  return Array.from(new Set(candidates))
}

function channelLogoIdentityKey(ch) {
  return ch?.canonical_key || ch?.tvg_id || ch?.tvg_name || ch?.name || ''
}

function channelLogoCandidateKey(ch) {
  return `${channelLogoIdentityKey(ch)}|${channelLogoCandidates(ch).join('|')}`
}

function channelDisplayNameValue(ch) {
  return String(ch?.name || '未知频道').trim() || '未知频道'
}

function advanceChannelLogoCandidate(ch) {
  const candidates = channelLogoCandidates(ch)
  const key = channelLogoCandidateKey(ch)
  const index = logoCandidateIndexes.value[key] || 0
  if (index < candidates.length - 1) {
    logoCandidateIndexes.value = {
      ...logoCandidateIndexes.value,
      [key]: index + 1,
    }
    return true
  }
  return false
}

function youtubeThumbnailUrls(videoId) {
  if (!videoId) return []
  return YOUTUBE_THUMBNAIL_VARIANTS.map(variant => `https://i.ytimg.com/vi/${videoId}/${variant}.jpg`)
}

function isCurrentYoutubeThumbnailCandidate(ch) {
  const youtubeVideoId = channelYoutubeVideoId(ch)
  if (!youtubeVideoId) return false
  const key = channelLogoCandidateKey(ch)
  const index = logoCandidateIndexes.value[key] || 0
  return index < YOUTUBE_THUMBNAIL_VARIANTS.length
}

function channelYoutubeVideoId(ch) {
  const urls = Array.isArray(ch?.urls) ? ch.urls : []
  for (const item of urls) {
    const parsedId = parseYoutubeVideoId(item?.url)
    if (parsedId) return parsedId
    const directId = sanitizeYoutubeVideoId(item?.youtube_video_id)
    if (directId) return directId
  }
  return parseYoutubeThumbnailVideoId(ch?.logo_url)
}

function sanitizeYoutubeVideoId(value) {
  const id = String(value || '').trim()
  return /^[a-zA-Z0-9_-]{11}$/.test(id) ? id : ''
}

function parseYoutubeVideoId(url) {
  try {
    const value = String(url || '').trim()
    if (!value) return ''
    const parsed = new URL(value)
    const host = parsed.hostname.toLowerCase()
    const parts = parsed.protocol === 'youtube:'
      ? [parsed.hostname, ...parsed.pathname.split('/')].filter(Boolean)
      : parsed.pathname.split('/').filter(Boolean)

    if (parsed.protocol === 'youtube:') {
      if (parts[0] === 'resolve') {
        return parseYoutubeVideoId(parsed.searchParams.get('url') || '')
      }
      if (parts.length === 1) return sanitizeYoutubeVideoId(parts[0])
      if (parts.length >= 2 && ['live', 'embed', 'shorts'].includes(parts[0])) {
        return sanitizeYoutubeVideoId(parts[1])
      }
      return ''
    }

    if (host === 'youtu.be' || host === 'www.youtu.be') {
      return sanitizeYoutubeVideoId(parts[0])
    }

    const isYoutubeHost = host === 'youtube.com'
      || host.endsWith('.youtube.com')
      || host === 'youtube-nocookie.com'
      || host.endsWith('.youtube-nocookie.com')
    if (!isYoutubeHost) return ''

    const queryVideoId = sanitizeYoutubeVideoId(parsed.searchParams.get('v'))
    if (queryVideoId) return queryVideoId
    if (parts.length >= 2 && ['live', 'embed', 'shorts'].includes(parts[0])) {
      return sanitizeYoutubeVideoId(parts[1])
    }
  } catch {
    return ''
  }
  return ''
}

function parseYoutubeThumbnailVideoId(url) {
  try {
    const parsed = new URL(String(url || '').trim())
    const host = parsed.hostname.toLowerCase()
    if (
      host !== 'i.ytimg.com'
      && host !== 'img.youtube.com'
      && !host.endsWith('.ytimg.com')
      && !host.endsWith('.youtube.com')
    ) {
      return ''
    }
    const parts = parsed.pathname.split('/').filter(Boolean)
    const viIndex = parts.findIndex(part => part === 'vi' || part === 'vi_webp')
    if (viIndex < 0 || viIndex + 1 >= parts.length) return ''
    return sanitizeYoutubeVideoId(parts[viIndex + 1])
  } catch {
    return ''
  }
}

async function playChannel(ch) {
  if (isUnavailable(ch)) return
  if (!ch.urls || !ch.urls.length) return
  const videoEl = playerStore.iptvVideoEl
  if (videoEl) videoEl.play().catch(() => {})
  await playerStore.playIptvChannel(ch)
}

const gridRef = ref(null)
const containerWidth = ref(1024)
const viewportWidth = ref(typeof window === 'undefined' ? 1280 : window.innerWidth)
let resizeObserver = null

const { y: scrollY } = useScroll(scrollRef)
const throttledScrollY = useThrottleFn((val) => { scrollPosition.value = val }, 16)
const scrollPosition = ref(0)
watchEffect(() => { throttledScrollY(scrollY.value) })

const gap = computed(() => 20)
const cardFooterHeight = 44

const columns = computed(() => {
  const w = viewportWidth.value
  if (w >= 1280) return 5
  if (w >= 1024) return 4
  return 2
})

const rowHeight = computed(() => {
  const cols = columns.value
  const cardWidth = (containerWidth.value - gap.value * (cols - 1)) / cols
  return cardWidth * 9 / 16 + cardFooterHeight
})

const cardHeight = computed(() => rowHeight.value)

const rows = computed(() => {
  const cols = columns.value
  const channels = filteredChannels.value
  const result = []
  for (let i = 0; i < channels.length; i += cols) {
    result.push(channels.slice(i, i + cols).map((channel) => ({
      channel,
    })))
  }
  return result
})

const virtualRows = computed(() => {
  const totalRows = rows.value.length
  if (totalRows === 0) return []
  const rh = rowHeight.value + gap.value
  const startRow = Math.max(0, Math.floor(scrollPosition.value / rh) - 3)
  const viewportH = scrollRef.value?.clientHeight || window.innerHeight
  const endRow = Math.min(totalRows, Math.ceil((scrollPosition.value + viewportH) / rh) + 3)
  return rows.value.slice(startRow, endRow).map((items, i) => ({
    items,
    startIndex: startRow + i,
  }))
})

const totalHeight = computed(() => rows.value.length * (rowHeight.value + gap.value))

onMounted(() => {
  resizeObserver = new ResizeObserver((entries) => {
    for (const entry of entries) {
      containerWidth.value = entry.contentRect.width
      viewportWidth.value = window.innerWidth
    }
  })
  if (gridRef.value) resizeObserver.observe(gridRef.value)
})

onBeforeUnmount(() => {
  if (resizeObserver) resizeObserver.disconnect()
})
</script>
