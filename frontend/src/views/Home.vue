<template>
  <!-- 页面主体区域：预留底部播放器空间，避免内容被悬浮控制条遮挡。 -->
  <main class="mx-auto flex min-h-screen w-full max-w-7xl flex-col items-center px-5 py-10 pb-36 sm:px-8 lg:px-10">

    <!-- 筛选栏 -->
    <header class="mb-6 w-full space-y-3">
      <!-- 地区筛选 -->
      <div class="flex flex-wrap items-center gap-2">
        <span class="shrink-0 text-xs text-gray-400 dark:text-gray-500">地区</span>
        <!-- "全部"按钮：选中时取消地区筛选 -->
        <button
          type="button"
          class="rounded-full border px-3 py-1 text-xs transition-colors"
          :class="pillClass(!selectedRegion)"
          @click="selectedRegion = ''"
        >
          全部
        </button>
        <button
          v-for="r in regions"
          :key="r"
          type="button"
          class="rounded-full border px-3 py-1 text-xs transition-colors"
          :class="pillClass(selectedRegion === r)"
          @click="selectedRegion = selectedRegion === r ? '' : r"
        >
          {{ regionLabels[r] || r }}
        </button>
      </div>

      <!-- 类型筛选 -->
      <div class="flex flex-wrap items-center gap-2">
        <span class="shrink-0 text-xs text-gray-400 dark:text-gray-500">类型</span>
        <button
          type="button"
          class="rounded-full border px-3 py-1 text-xs transition-colors"
          :class="pillClass(!selectedType)"
          @click="selectedType = ''"
        >
          全部
        </button>
        <button
          v-for="t in types"
          :key="t"
          type="button"
          class="rounded-full border px-3 py-1 text-xs transition-colors"
          :class="pillClass(selectedType === t)"
          @click="selectedType = selectedType === t ? '' : t"
        >
          {{ typeLabels[t] || t }}
        </button>
      </div>

      <!-- 电台数量 -->
      <p class="text-xs text-gray-400 dark:text-gray-500">
        共 {{ filteredStations.length }} 个电台
        <span v-if="rbLoading" class="ml-2">正在加载…</span>
      </p>
    </header>

    <!-- 电台网格：移动端 2 列，平板 4 列，桌面 6 列 -->
    <section class="grid w-full grid-cols-2 gap-4 sm:grid-cols-4 sm:gap-5 lg:grid-cols-6">
      <button
        v-for="station in filteredStations"
        :key="station.id"
        type="button"
        :aria-label="`切换到 ${station.name}`"
        class="group aspect-square rounded-3xl border border-white/70 bg-gray-50/80 p-3 text-left shadow-sm shadow-black/[0.03] outline-none backdrop-blur-xl transition-all duration-300 ease-out hover:scale-[1.02] hover:bg-white/90 active:scale-95 dark:border-white/10 dark:bg-neutral-800/50 dark:shadow-black/20 dark:hover:bg-neutral-800/75"
        :class="{
          'ring-2 ring-black dark:ring-white': isCurrentStationPlaying(station.id),
        }"
        @click="playerStore.switchStation(station.id)"
      >
        <div class="flex h-full flex-col overflow-hidden rounded-[1.25rem]">
          <!-- Logo 区域 -->
          <div class="flex basis-3/5 items-center justify-center">
            <div
              class="flex size-16 items-center justify-center overflow-hidden rounded-full border border-black/5 bg-white text-lg font-semibold text-neutral-700 shadow-sm shadow-black/[0.04] transition-transform duration-300 ease-out group-hover:scale-105 dark:border-white/10 dark:bg-neutral-900 dark:text-neutral-200 sm:size-20"
              :class="{ 'animate-pulse': isCurrentStationLoading(station.id) }"
            >
              <img
                v-if="station.logoUrl"
                class="h-full w-full object-cover"
                :src="station.logoUrl"
                :alt="`${station.name} logo`"
              />
              <span v-else>{{ station.logoText }}</span>
            </div>
          </div>
          <!-- 电台名称 -->
          <div class="flex basis-2/5 items-center justify-center px-2 text-center">
            <span class="line-clamp-2 text-sm font-medium text-gray-800 dark:text-gray-200 sm:text-[0.95rem]">
              {{ station.name }}
            </span>
          </div>
        </div>
      </button>
    </section>
  </main>
</template>

<script setup>
import { storeToRefs } from 'pinia'
import { usePlayerStore } from '../stores/player'
import { fetchStationsByCountry, RB_FETCH_COUNTRIES } from '../api/radioBrowser'
import { computed, inject, onMounted, ref, watchEffect } from 'vue'

const playerStore = usePlayerStore()
const { currentStation, isPlaying, isLoading, stationList } = storeToRefs(playerStore)

// ========== Radio Browser 数据 ==========
const rbStations = ref([])
const rbLoading = ref(false)

// 合并静态电台 + Radio Browser 电台
const allStations = computed(() => [...stationList.value, ...rbStations.value])

// ========== 筛选配置 ==========
// 地区标签映射，新增地区只需在这里加一行
const regionLabels = { TW: '台湾', CN: '中国大陆', JP: '日本', US: '美国', KR: '韩国', GB: '英国', DE: '德国', FR: '法国' }

// 类型标签映射，对应 radioBrowser.js 的 TAG_TYPE_MAP 输出值
const typeLabels = { music: '音乐', news: '新闻', talk: '谈话', sports: '体育', religious: '宗教', other: '其他' }

// 当前选中的筛选条件，空字符串表示"全部"
const selectedRegion = ref('')
const selectedType = ref('')
// 搜索关键词，从 App.vue 通过 provide/inject 共享过来
const searchQuery = inject('searchQuery')

// 从当前所有电台的 tags 中自动提取出现过的地区列表
const regions = computed(() => {
  const set = new Set()
  for (const s of allStations.value) {
    for (const t of s.tags || []) {
      if (regionLabels[t]) set.add(t)
    }
  }
  return [...set]
})

// 从当前所有电台的 tags 中自动提取出现过的类型列表
const types = computed(() => {
  const set = new Set()
  for (const s of allStations.value) {
    for (const t of s.tags || []) {
      if (typeLabels[t]) set.add(t)
    }
  }
  return [...set]
})

// watchEffect 自动追踪内部所有响应式依赖，任何一个变化都会同步触发重新筛选
const filteredStations = ref([])

watchEffect(() => {
  const region = selectedRegion.value
  const type = selectedType.value
  // 搜索关键词转小写，用于不区分大小写的模糊匹配
  const query = searchQuery.value.trim().toLowerCase()
  const result = allStations.value.filter((s) => {
    // 地区筛选
    const tags = s.tags || []
    if (region && !tags.includes(region)) return false
    // 类型筛选
    if (type && !tags.includes(type)) return false
    // 名称搜索：电台名包含关键词即匹配
    if (query && !(s.name || '').toLowerCase().includes(query)) return false
    return true
  })
  filteredStations.value = result
})

// pill 按钮样式：选中为黑色填充，未选中为灰色边框
function pillClass(active) {
  return active
    ? 'border-black bg-black text-white dark:border-white dark:bg-white dark:text-black'
    : 'border-gray-300 bg-white text-gray-600 hover:bg-gray-100 dark:border-neutral-600 dark:bg-neutral-800 dark:text-gray-300 dark:hover:bg-neutral-700'
}

// ========== 工具函数 ==========
function isCurrentStationPlaying(stationId) {
  return currentStation.value === stationId && isPlaying.value
}

function isCurrentStationLoading(stationId) {
  return currentStation.value === stationId && isLoading.value
}

// ========== 初始化 ==========
// 按 RB_FETCH_COUNTRIES 配置并行拉取多个地区的电台
// 想加其他地区：去 radioBrowser.js 的 RB_FETCH_COUNTRIES 里加国家代码即可
onMounted(async () => {
  rbLoading.value = true
  // 并行拉取所有配置的地区，Promise.all 等全部完成
  const results = await Promise.all(
    RB_FETCH_COUNTRIES.map((code) => fetchStationsByCountry(code))
  )
  // 把各地区结果合并成一个数组
  const list = results.flat()
  rbStations.value = list
  // 注册到 store 的 stationMap，供 AudioEngine 查找播放地址
  list.forEach((s) => playerStore.addStation(s))
  rbLoading.value = false
})
</script>
