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

      <p class="text-xs text-gray-400 dark:text-gray-500">
        共 {{ filteredChannels.length }} 个频道
        <span v-if="loading" class="ml-2">加载中…</span>
      </p>
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
            class="group rounded-3xl border border-white/70 bg-gray-50/80 p-3 text-left shadow-sm shadow-black/[0.03] outline-none backdrop-blur-xl transition-[background-color,transform,box-shadow,border-color] duration-300 ease-out hover:scale-[1.02] hover:bg-white/90 active:scale-95 dark:border-white/10 dark:bg-neutral-800/50 dark:shadow-black/20 dark:hover:bg-neutral-800/75"
            :class="{
              'ring-2 ring-black dark:ring-white': isCurrentChannel(ch),
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

const playerStore = usePlayerStore()
const { currentStation } = storeToRefs(playerStore)

const scrollRef = inject('scrollRef')
const searchQuery = inject('searchQuery')

import { storeToRefs } from 'pinia'

const allChannels = ref([])
const allGroups = ref([])
const selectedGroup = ref('')
const loading = ref(false)

async function loadChannels() {
  loading.value = true
  try {
    const data = await fetchAggregatedChannels({ group: selectedGroup.value, search: searchQuery.value.trim() })
    allChannels.value = data.channels || []
    if (!selectedGroup.value && !searchQuery.value.trim()) {
      allGroups.value = data.groups || []
    }
  } catch (e) {
    console.error('加载频道失败:', e)
  }
  loading.value = false
}

const filteredChannels = computed(() => allChannels.value)

// 初始加载
onMounted(loadChannels)

// 搜索变化时重新加载
watch(searchQuery, () => { loadChannels() })

function isCurrentChannel(ch) {
  // 简单匹配：当前播放的 URL 是否在该频道的 urls 中
  return false // 后续播放功能接入后实现
}

function playChannel(ch) {
  // 找到最优可用链接
  const best = ch.urls.find(u => u.is_working === 1) || ch.urls[0]
  if (best) {
    console.log('播放:', ch.name, best.url)
    // 后续接入播放器
  }
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
