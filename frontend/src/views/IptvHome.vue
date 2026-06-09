<template>
  <main class="mx-auto flex min-h-screen w-full max-w-7xl flex-col items-center px-5 pt-[calc(env(safe-area-inset-top)+3.5rem)] pb-36 sm:px-8 lg:px-10">

    <header class="mb-6 w-full space-y-3">
      <div class="flex flex-wrap items-center gap-2">
        <span class="shrink-0 text-xs text-gray-400 dark:text-gray-500">分组</span>
        <button
          type="button"
          class="rounded-full border px-3 py-1 text-xs transition-colors"
          :class="pillClass(!selectedGroup)"
          @click="selectedGroup = ''; loadChannels()"
        >
          全部
        </button>
        <button
          v-for="g in allGroups"
          :key="g"
          type="button"
          class="rounded-full border px-3 py-1 text-xs transition-colors"
          :class="pillClass(selectedGroup === g)"
          @click="selectedGroup = g; loadChannels()"
        >
          {{ g }}
        </button>
      </div>

      <div class="flex items-center justify-between">
        <p class="text-xs text-gray-400 dark:text-gray-500">
          共 {{ filteredChannels.length }} 个频道
          <span v-if="loading" class="ml-2">加载中…</span>
        </p>
        <button
          type="button"
          class="inline-flex items-center gap-1 rounded-full border px-2.5 py-0.5 text-xs transition-colors"
          :class="channelSortMode !== 'original'
            ? 'border-green-500 bg-green-50 text-green-600 dark:border-green-400 dark:bg-green-900/30 dark:text-green-400'
            : 'border-gray-300 bg-white text-gray-500 hover:bg-gray-100 dark:border-neutral-600 dark:bg-neutral-800 dark:text-gray-400 dark:hover:bg-neutral-700'"
          @click="nextSortMode"
        >
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" width="12" height="12">
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
          class="grid grid-cols-2 sm:grid-cols-4 lg:grid-cols-6"
          :style="{ gap: `${gap}px` }"
        >
          <button
            v-for="ch in row.items"
            :key="ch.name"
            type="button"
            :aria-label="`播放 ${ch.name}`"
            :style="{ height: `${cardSize}px` }"
            :disabled="isAllFailed(ch)"
            class="group rounded-3xl border border-white/70 bg-gray-50/80 p-3 text-left shadow-none outline-none backdrop-blur-none transition-colors duration-200 ease-out hover:bg-white/90 active:bg-white dark:border-white/10 dark:bg-neutral-800/50 dark:hover:bg-neutral-800/75"
            :class="{
              'ring-2 ring-black dark:ring-white': isCurrentChannel(ch),
              'cursor-not-allowed opacity-40 hover:scale-100 hover:bg-gray-50/80 dark:hover:bg-neutral-800/50': isAllFailed(ch),
            }"
            @click="playChannel(ch)"
          >
            <div class="flex h-full flex-col overflow-hidden rounded-[1.25rem]">
              <div class="flex basis-3/5 items-center justify-center">
                <div
                  class="flex size-16 items-center justify-center overflow-hidden rounded-full border border-black/5 bg-white text-lg font-semibold text-neutral-700 shadow-sm shadow-black/[0.04] transition-transform duration-300 ease-out group-hover:scale-105 dark:border-white/10 dark:bg-neutral-900 dark:text-neutral-200 sm:size-20"
                >
                  <img
                    v-if="ch.logo_url"
                    class="h-full w-full object-cover"
                    :src="ch.logo_url"
                    :alt="ch.name"
                    @error="useDefaultLogo"
                  />
                  <span v-else>{{ ch.name.slice(0, 2) }}</span>
                </div>
              </div>
              <div class="flex basis-2/5 flex-col items-center justify-center px-2 text-center">
                <span class="line-clamp-1 text-sm font-medium text-gray-800 dark:text-gray-200 sm:text-[0.95rem]">
                  {{ ch.name }}
                </span>
                <span
                  v-if="ch.group_name"
                  class="mt-0.5 line-clamp-1 text-[0.7rem] text-gray-400 dark:text-gray-500"
                >
                  {{ ch.group_name }}
                </span>
                <span
                  v-if="epgMap[ch.canonical_key]?.current?.title"
                  class="mt-0.5 line-clamp-1 text-[0.65rem] text-gray-500 dark:text-gray-400 italic"
                >
                  {{ epgMap[ch.canonical_key].current.title }}
                </span>
                <span
                  v-if="isUntested(ch)"
                  class="mt-1 rounded-full bg-neutral-200 px-1.5 py-0.5 text-[0.6rem] text-neutral-500 dark:bg-neutral-700 dark:text-neutral-400"
                >
                  未测试
                </span>
                <span
                  v-else-if="isAllFailed(ch)"
                  class="mt-1 rounded-full bg-red-100 px-1.5 py-0.5 text-[0.6rem] text-red-500 dark:bg-red-900/30 dark:text-red-400"
                >
                  不可用
                </span>
              </div>
            </div>
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

const SORT_MODES = [
  { key: 'original', label: '默认' },
  { key: 'natural', label: 'A-Z' },
  { key: 'group', label: '分组' },
]
function naturalSort(a, b) {
  return a.localeCompare(b, undefined, { numeric: true, sensitivity: 'base' })
}
function nextSortMode() {
  const idx = SORT_MODES.findIndex(m => m.key === channelSortMode.value)
  channelSortMode.value = SORT_MODES[(idx + 1) % SORT_MODES.length].key
}
const currentSortLabel = computed(() => SORT_MODES.find(m => m.key === channelSortMode.value)?.label || '默认')

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
    : 'border-gray-300 bg-white text-gray-600 hover:bg-gray-100 dark:border-neutral-600 dark:bg-neutral-800 dark:text-gray-300 dark:hover:bg-neutral-700'
}

// ── 虚拟滚动 ──

const gridRef = ref(null)
const containerWidth = ref(1024)
let resizeObserver = null

const { y: scrollY } = useScroll(scrollRef)
const throttledScrollY = useThrottleFn((val) => { scrollPosition.value = val }, 16)
const scrollPosition = ref(0)
watchEffect(() => { throttledScrollY(scrollY.value) })

const gap = computed(() => 20)

const columns = computed(() => {
  const w = containerWidth.value
  if (w >= 1024) return 6
  if (w >= 640) return 4
  return 2
})

const rowHeight = computed(() => {
  const cols = columns.value
  return (containerWidth.value - gap.value * (cols - 1)) / cols
})

const cardSize = computed(() => rowHeight.value)

const rows = computed(() => {
  const cols = columns.value
  const channels = filteredChannels.value
  const result = []
  for (let i = 0; i < channels.length; i += cols) {
    result.push(channels.slice(i, i + cols))
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
    }
  })
  if (gridRef.value) resizeObserver.observe(gridRef.value)
})

onBeforeUnmount(() => {
  if (resizeObserver) resizeObserver.disconnect()
})
</script>
