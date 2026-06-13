<template>
  <main class="iptv-main min-h-screen w-full px-5 pb-32 pt-[calc(env(safe-area-inset-top)+4rem)] sm:px-8 lg:px-10 lg:pb-40 lg:pt-6">
    <header class="mb-7 space-y-7">
      <div class="flex min-h-12 items-start justify-between gap-6 lg:pr-[300px]">
        <div class="scrollbar-hide flex max-w-full gap-2 overflow-x-auto pb-1">
          <button
            v-for="tab in categoryTabs"
            :key="tab"
            type="button"
            class="h-11 shrink-0 rounded-full border px-5 text-sm font-medium transition-colors"
            :class="pillClass(isSelectedCategory(tab))"
            @click="selectCategoryTab(tab)"
          >
            {{ tab }}
          </button>
        </div>
      </div>

      <div class="flex items-center justify-between gap-4">
        <div class="flex min-w-0 items-center gap-3">
          <span class="flex size-8 shrink-0 items-center justify-center rounded-full bg-[var(--surface)] text-[var(--text-primary)]">
            <svg class="size-4" viewBox="0 0 24 24" fill="none" aria-hidden="true"><path d="M5 12a7 7 0 0 1 14 0M2.5 12a9.5 9.5 0 0 1 19 0M9 12a3 3 0 0 1 6 0" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/></svg>
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
            :style="[coverStyle(item.channel), { height: `${cardHeight}px` }]"
            :disabled="isAllFailed(item.channel)"
            class="channel-card group relative overflow-hidden rounded-[18px] border border-[var(--border)] bg-[var(--card-bg)] text-left outline-none transition duration-200 ease-out hover:-translate-y-0.5 hover:border-[var(--border-strong)] disabled:cursor-not-allowed disabled:opacity-45"
            :class="[defaultCoverClass(item.channel), { 'channel-card-current': isCurrentChannel(item.channel) }]"
            @click="playChannel(item.channel)"
          >
            <span
              v-if="cardVisualType(item.channel) === 'logo-card'"
              class="channel-card__logo-card-visual"
              aria-hidden="true"
            >
              <img
                v-if="channelLogoUrl(item.channel)"
                class="channel-card__center-logo"
                :src="channelLogoUrl(item.channel)"
                alt=""
                @error="onCenterLogoError"
              />
              <span class="channel-card__logo-card-shade"></span>
            </span>
            <span class="channel-index-badge">{{ item.index + 1 }}</span>
            <span v-if="cardVisualType(item.channel) === 'cover'" class="channel-card-scrim"></span>
            <span class="card-info">
              <span class="card-channel">
                <img
                  class="card-logo"
                  :src="channelLogoUrl(item.channel) || DEFAULT_LOGO_URL"
                  :alt="item.channel.name"
                  @error="useDefaultLogo"
                />
                <span class="card-channel-name">{{ item.channel.name }}</span>
              </span>
              <span class="card-program-name">{{ currentProgramTitle(item.channel) }}</span>
            </span>
          </button>
        </div>
      </div>
    </section>
  </main>
</template>

<script setup>
import { computed, inject, nextTick, onBeforeUnmount, onMounted, ref, watch, watchEffect } from 'vue'
import { useScroll, useThrottleFn } from '@vueuse/core'
import { usePlayerStore } from '../stores/player'
import { fetchAggregatedChannels } from '../api/iptv'
import { useEpg } from '../composables/useEpg'
import { publicAsset } from '../publicAsset'

const playerStore = usePlayerStore()
const { currentStation } = storeToRefs(playerStore)

const scrollRef = inject('scrollRef')
const searchQuery = inject('searchQuery')

import { storeToRefs } from 'pinia'

const allChannels = ref([])
const allGroups = ref([])
const selectedGroup = ref('')
const loading = ref(false)
const epgMap = ref({})
const channelSortMode = ref('original')
const DEFAULT_LOGO_URL = publicAsset('/logos/default.png')
const categoryTabs = computed(() => ['全部', ...allGroups.value])

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

function useDefaultLogo(event) {
  const img = event?.target
  if (!img || img.dataset.logoFallback === '1') return
  img.dataset.logoFallback = '1'
  img.src = DEFAULT_LOGO_URL
}

async function loadChannels() {
  loading.value = true
  try {
    const data = await fetchAggregatedChannels({ group: selectedGroup.value, search: searchQuery.value.trim() })
    allChannels.value = data.channels || []
    if (!selectedGroup.value && !searchQuery.value.trim()) {
      allGroups.value = data.groups || []
    }
    // 批量拉 EPG 摘要
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

// 初始加载
onMounted(loadChannels)

// 搜索变化时重新加载
watch(searchQuery, () => { loadChannels() })

function isCurrentChannel(ch) {
  const current = playerStore.pendingIptvChannel || playerStore.currentIptvChannel
  return current && current.name === ch.name
}

function isUntested(ch) {
  return ch.urls.every(u => u.is_working === -1)
}

function isAllFailed(ch) {
  return ch.urls.every(u => u.is_working === 0)
}

function currentProgramTitle(ch) {
  return epgMap.value[ch.canonical_key]?.current?.title || ''
}

function channelCoverUrl(ch) {
  return ch.cover || ch.cover_url || ch.poster || ch.poster_url || ch.thumbnail || ch.thumbnail_url || ch.image || ch.image_url || ''
}

function cardVisualType(ch) {
  if (channelCoverUrl(ch)) return 'cover'
  return 'logo-card'
}

function coverStyle(ch) {
  const cover = channelCoverUrl(ch)
  if (!cover) return {}
  return {
    backgroundImage: `url("${String(cover).replace(/"/g, '\\"')}")`,
    backgroundSize: 'cover',
    backgroundPosition: 'center',
  }
}

function defaultCoverClass(ch) {
  if (channelCoverUrl(ch)) return 'has-cover-image'
  return 'channel-card--logo-card'
}

function onCenterLogoError(event) {
  if (event?.currentTarget) event.currentTarget.style.display = 'none'
}

function channelLogoUrl(ch) {
  return ch.logo_url || knownIptvLogoUrl(ch) || ''
}

function knownIptvLogoUrl(ch) {
  const normalized = normalizeChannelLogoKey(`${ch.name || ''} ${ch.tvg_name || ''} ${ch.canonical_key || ''}`)
  if (normalized.includes('cgtn')) return 'https://live.fanmingming.com/tv/CGTN.png'
  const cctvMatch = normalized.match(/cctv(\d{1,2})(plus|\+)?/)
  if (!cctvMatch) return ''
  const suffix = cctvMatch[2] ? `${cctvMatch[1]}%2B` : cctvMatch[1]
  return `https://live.fanmingming.com/tv/CCTV${suffix}.png`
}

function normalizeChannelLogoKey(value) {
  return String(value || '')
    .toLowerCase()
    .replace(/[\s_\-－综合高清新闻纪录少儿音乐电影电视剧体育中文外语财经农业农村科教社会与法国防军事戏曲]/g, '')
}

async function playChannel(ch) {
  if (isAllFailed(ch)) return
  if (!ch.urls || !ch.urls.length) return
  const videoEl = playerStore.iptvVideoEl
  // 仅调 play() 满足 iOS 手势，其余由 store.playIptvChannel 接管
  if (videoEl) videoEl.play().catch(() => {})
  await playerStore.playIptvChannel(ch)
}

function pillClass(active) {
  return active
    ? 'border-black bg-black text-white dark:border-white dark:bg-white dark:text-black'
    : 'border-[var(--border)] bg-[var(--surface)] text-[var(--text-secondary)] hover:bg-[var(--surface-hover)] hover:text-[var(--text-primary)]'
}

// ── 虚拟滚动 ──

const gridRef = ref(null)
const containerWidth = ref(1024)
const viewportWidth = ref(typeof window === 'undefined' ? 1280 : window.innerWidth)
let resizeObserver = null

const { y: scrollY } = useScroll(scrollRef)
const throttledScrollY = useThrottleFn((val) => { scrollPosition.value = val }, 16)
const scrollPosition = ref(0)
watchEffect(() => { throttledScrollY(scrollY.value) })

const gap = computed(() => 20)

const columns = computed(() => {
  const w = viewportWidth.value
  if (w >= 1280) return 4
  if (w >= 1024) return 3
  return 2
})

const rowHeight = computed(() => {
  const cols = columns.value
  const cardWidth = (containerWidth.value - gap.value * (cols - 1)) / cols
  return cardWidth * 9 / 16
})

const cardHeight = computed(() => rowHeight.value)

const rows = computed(() => {
  const cols = columns.value
  const channels = filteredChannels.value
  const result = []
  for (let i = 0; i < channels.length; i += cols) {
    result.push(channels.slice(i, i + cols).map((channel, offset) => ({
      channel,
      index: i + offset,
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
