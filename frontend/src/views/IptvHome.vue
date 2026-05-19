<template>
  <main class="mx-auto flex min-h-screen w-full max-w-7xl flex-col items-center px-5 pt-[calc(env(safe-area-inset-top)+3.5rem)] pb-36 sm:px-8 lg:px-10">

    <header class="mb-6 w-full space-y-3">
      <p class="text-xs text-gray-400 dark:text-gray-500">
        共 {{ filteredChannels.length }} 个频道
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
            :key="ch.id"
            type="button"
            :aria-label="`切换到 ${ch.name}`"
            :style="{ height: `${cardSize}px` }"
            class="group rounded-3xl border border-white/70 bg-gray-50/80 p-3 text-left shadow-sm shadow-black/[0.03] outline-none backdrop-blur-xl transition-[background-color,transform,box-shadow,border-color] duration-300 ease-out hover:scale-[1.02] hover:bg-white/90 active:scale-95 dark:border-white/10 dark:bg-neutral-800/50 dark:shadow-black/20 dark:hover:bg-neutral-800/75"
          >
            <div class="flex h-full flex-col overflow-hidden rounded-[1.25rem]">
              <div class="flex basis-3/5 items-center justify-center">
                <div
                  class="flex size-16 items-center justify-center overflow-hidden rounded-full border border-black/5 bg-white text-lg font-semibold text-neutral-700 shadow-sm shadow-black/[0.04] transition-transform duration-300 ease-out group-hover:scale-105 dark:border-white/10 dark:bg-neutral-900 dark:text-neutral-200 sm:size-20"
                >
                  <span>{{ ch.name.slice(0, 2) }}</span>
                </div>
              </div>
              <div class="flex basis-2/5 flex-col items-center justify-center px-2 text-center">
                <span class="line-clamp-1 text-sm font-medium text-gray-800 dark:text-gray-200 sm:text-[0.95rem]">
                  {{ ch.name }}
                </span>
                <span
                  v-if="ch.group"
                  class="mt-0.5 line-clamp-1 text-[0.7rem] text-gray-400 dark:text-gray-500"
                >
                  {{ ch.group }}
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

const scrollRef = inject('scrollRef')
const searchQuery = inject('searchQuery')

// 模拟频道数据，后续接入后端替换
const mockChannels = [
  { id: 'cctv1', name: 'CCTV-1 综合', group: '央视' },
  { id: 'cctv2', name: 'CCTV-2 财经', group: '央视' },
  { id: 'cctv3', name: 'CCTV-3 综艺', group: '央视' },
  { id: 'cctv4', name: 'CCTV-4 中文国际', group: '央视' },
  { id: 'cctv5', name: 'CCTV-5 体育', group: '央视' },
  { id: 'cctv6', name: 'CCTV-6 电影', group: '央视' },
  { id: 'cctv7', name: 'CCTV-7 国防军事', group: '央视' },
  { id: 'cctv8', name: 'CCTV-8 电视剧', group: '央视' },
  { id: 'cctv9', name: 'CCTV-9 纪录', group: '央视' },
  { id: 'cctv10', name: 'CCTV-10 科教', group: '央视' },
  { id: 'cctv11', name: 'CCTV-11 戏曲', group: '央视' },
  { id: 'cctv12', name: 'CCTV-12 社会与法', group: '央视' },
  { id: 'cctv13', name: 'CCTV-13 新闻', group: '央视' },
  { id: 'cctv14', name: 'CCTV-14 少儿', group: '央视' },
  { id: 'cctv15', name: 'CCTV-15 音乐', group: '央视' },
  { id: 'cctv16', name: 'CCTV-16 奥林匹克', group: '央视' },
  { id: 'cctv17', name: 'CCTV-17 农业农村', group: '央视' },
  { id: 'hunan', name: '湖南卫视', group: '卫视' },
  { id: 'zhejiang', name: '浙江卫视', group: '卫视' },
  { id: 'jiangsu', name: '江苏卫视', group: '卫视' },
  { id: 'dongfang', name: '东方卫视', group: '卫视' },
  { id: 'beijing', name: '北京卫视', group: '卫视' },
  { id: 'tianjin', name: '天津卫视', group: '卫视' },
  { id: 'shandong', name: '山东卫视', group: '卫视' },
  { id: 'hebei', name: '河北卫视', group: '卫视' },
  { id: 'henan', name: '河南卫视', group: '卫视' },
  { id: 'sichuan', name: '四川卫视', group: '卫视' },
  { id: 'hubei', name: '湖北卫视', group: '卫视' },
  { id: 'fujian', name: '东南卫视', group: '卫视' },
  { id: 'guangdong', name: '广东卫视', group: '卫视' },
  { id: 'shenzhen', name: '深圳卫视', group: '卫视' },
  { id: 'chongqing', name: '重庆卫视', group: '卫视' },
  { id: 'heilongjiang', name: '黑龙江卫视', group: '卫视' },
  { id: 'liaoning', name: '辽宁卫视', group: '卫视' },
  { id: 'jilin', name: '吉林卫视', group: '卫视' },
  { id: 'anhui', name: '安徽卫视', group: '卫视' },
  { id: 'jiangxi', name: '江西卫视', group: '卫视' },
  { id: 'yunnan', name: '云南卫视', group: '卫视' },
  { id: 'guizhou', name: '贵州卫视', group: '卫视' },
  { id: 'shaanxi', name: '陕西卫视', group: '卫视' },
  { id: 'gansu', name: '甘肃卫视', group: '卫视' },
  { id: 'guangxi', name: '广西卫视', group: '卫视' },
  { id: 'hainan', name: '海南卫视', group: '卫视' },
  { id: 'shanxi', name: '山西卫视', group: '卫视' },
  { id: 'neimenggu', name: '内蒙古卫视', group: '卫视' },
  { id: 'xizang', name: '西藏卫视', group: '卫视' },
  { id: 'xinjiang', name: '新疆卫视', group: '卫视' },
  { id: 'ningxia', name: '宁夏卫视', group: '卫视' },
  { id: 'qinghai', name: '青海卫视', group: '卫视' },
]

const filteredChannels = ref(mockChannels)

watchEffect(() => {
  const query = searchQuery.value.trim().toLowerCase()
  if (!query) {
    filteredChannels.value = mockChannels
    return
  }
  filteredChannels.value = mockChannels.filter((ch) =>
    ch.name.toLowerCase().includes(query) || ch.group.toLowerCase().includes(query),
  )
})

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
