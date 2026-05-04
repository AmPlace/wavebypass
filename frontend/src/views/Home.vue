<template>
  <!-- 页面主体：居中布局，不负责滚动（滚动容器在 App.vue 根 div）。 -->
  <main class="mx-auto flex min-h-screen w-full max-w-7xl flex-col items-center px-5 py-10 pb-36 sm:px-8 lg:px-10">

    <!-- 筛选栏 -->
    <header class="mb-6 w-full space-y-3">
      <!-- 地区筛选 -->
      <div class="flex flex-wrap items-center gap-2">
        <span class="shrink-0 text-xs text-gray-400 dark:text-gray-500">地区</span>
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
        <span v-if="ytLoading || mrLoading" class="ml-2">正在加载…</span>
      </p>
    </header>

    <!-- 虚拟滚动区域：totalHeight 撑开滚动高度，只创建可视区域附近的 DOM 节点。 -->
    <!-- gridRef 用于 ResizeObserver 测量实际宽度，驱动列数和行高重新计算。 -->
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
            v-for="station in row.items"
            :key="station.id"
            type="button"
            :aria-label="`切换到 ${station.name}`"
            :style="{ height: `${cardSize}px` }"
            class="group rounded-3xl border border-white/70 bg-gray-50/80 p-3 text-left shadow-sm shadow-black/[0.03] outline-none backdrop-blur-xl transition-[background-color,transform,box-shadow,border-color] duration-300 ease-out hover:scale-[1.02] hover:bg-white/90 active:scale-95 dark:border-white/10 dark:bg-neutral-800/50 dark:shadow-black/20 dark:hover:bg-neutral-800/75"
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
              <!-- 电台名称 + EPG 当前节目 -->
              <div class="flex basis-2/5 flex-col items-center justify-center px-2 text-center">
                <span class="line-clamp-1 text-sm font-medium text-gray-800 dark:text-gray-200 sm:text-[0.95rem]">
                  {{ station.name }}
                </span>
                <span
                  v-if="station.subtitle || epgMap[station.id.replace('yt_', '')]"
                  class="mt-0.5 line-clamp-1 text-[0.7rem] text-gray-400 dark:text-gray-500"
                >
                  {{ station.subtitle || epgMap[station.id.replace('yt_', '')] }}
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
import { storeToRefs } from 'pinia'
import { usePlayerStore } from '../stores/player'
import { fetchAllYuntingStations } from '../api/yunting'
import { fetchMyradioStations } from '../api/myradio'
import { computed, inject, onBeforeUnmount, onMounted, ref, watch, watchEffect } from 'vue'
import { useScroll, useThrottleFn } from '@vueuse/core'

const playerStore = usePlayerStore()
const { currentStation, isPlaying, isLoading, stationList } = storeToRefs(playerStore)

// ========== 云听 (radio.cn) 数据 ==========
const ytStations = ref([])
const ytLoading = ref(false)

// ========== myradio.tw 数据 ==========
const mrStations = ref([])
const mrLoading = ref(false)

// ========== EPG（当前节目名）==========
// epgMap 用于卡片显示：key 是 contentId（无 yt_ 前缀），value 是节目名
// 两路数据源：
//   1. 初始加载：云听 API 返回的 subtitle → watch(ytStations) 填充
//   2. 定期刷新：每 3 分钟调 /api/yunting/epg → syncEpg() 同时更新 epgMap 和 store
// store 中的 subtitle 变化会触发 AudioEngine 的 watcher → 自动刷新 MediaSession（锁屏/通知栏）
const epgMap = ref({})

// 将 EPG 数据同步到 epgMap（卡片显示）和 playerStore（MediaSession）
function syncEpg(data) {
  epgMap.value = data
  for (const [cid, subtitle] of Object.entries(data)) {
    playerStore.updateStationEpg(`yt_${cid}`, subtitle)
  }
}

// 云听电台加载完成后，用初始 subtitle 填充 epgMap
watch(ytStations, (list) => {
  const initial = {}
  for (const s of list) {
    if (s.subtitle) initial[s.id.replace('yt_', '')] = s.subtitle
  }
  if (Object.keys(initial).length) syncEpg(initial)
}, { once: true })

// 繁→简高频字映射（电台名常见字，与后端 _T2S 保持一致）
const T2S = { '樂':'乐','聲':'声','網':'网','廣':'广','聯':'联','華':'华','國':'国','東':'东','電':'电','視':'视','經':'经','發':'发','動':'动','學':'学','機':'机','區':'区','車':'车','產':'产','業':'业','問':'问','開':'开','長':'长','報':'报','點':'点','號':'号','團':'团','場':'场','處':'处','間':'间','書':'书','術':'术','議':'议','記':'记','設':'设','計':'计','話':'话','題':'题','調':'调','論':'论','辦':'办','營':'营','環':'环','競':'竞','衛':'卫','實':'实','總':'总','統':'统','義':'义','資':'资','運':'运','選':'选','達':'达','進':'进','鄉':'乡','錢':'钱','鐵':'铁','門':'门','陽':'阳','雲':'云','飛':'飞','魚':'鱼','馬':'马','風':'风','齊':'齐','龍':'龙' }
// 字符标准化：繁→简 + 全角→半角，用于生成稳定的去重 key
function normalizeForDedup(str) {
  return (str || '').replace(/\s+/g, '').toLowerCase().replace(/[一-鿿]/g, (c) => T2S[c] || c)
}

// 四源去重：同名电台只保留一张卡片，优先级 静态 > myradio > 云听 > RB
function deduplicateByName(stations) {
  const groups = new Map()
  for (const s of stations) {
    const key = normalizeForDedup(s.name)
    if (!groups.has(key)) groups.set(key, [])
    groups.get(key).push(s)
  }
  return [...groups.values()].map((group) => {
    if (group.length === 1) return group[0]
    // 优先级：静态(id 无前缀) 0 > mr_ 1 > yt_ 2 > rb_ 3
    const pri = (s) => {
      if (s.id.startsWith('mr_')) return 1
      if (s.id.startsWith('yt_')) return 2
      if (s.id.startsWith('rb_')) return 3
      return 0
    }
    group.sort((a, b) => pri(a) - pri(b))
    const primary = { ...group[0] }
    // 合并所有源的 tags
    primary.tags = [...new Set(group.flatMap((s) => s.tags || []))]
    // 选最好的 logo
    if (!primary.logoUrl) {
      const found = group.find((s) => s.logoUrl)
      if (found) primary.logoUrl = found.logoUrl
    }
    return primary
  })
}

const allStations = computed(() =>
  deduplicateByName([...stationList.value, ...mrStations.value, ...ytStations.value])
)

// ========== 筛选配置 ==========
// 地区标签映射，新增地区只需在这里加一行
const regionLabels = {
  TW: '台湾', CN: '中国大陆', JP: '日本', US: '美国', KR: '韩国', GB: '英国', DE: '德国', FR: '法国',
  安徽: '安徽', 北京: '北京', 重庆: '重庆', 福建: '福建', 甘肃: '甘肃', 广东: '广东', 广西: '广西',
  贵州: '贵州', 海南: '海南', 河北: '河北', 河南: '河南', 黑龙江: '黑龙江', 湖北: '湖北', 湖南: '湖南',
  吉林: '吉林', 江苏: '江苏', 江西: '江西', 辽宁: '辽宁', 内蒙古: '内蒙古', 宁夏: '宁夏', 青海: '青海',
  山东: '山东', 山西: '山西', 陕西: '陕西', 上海: '上海', 四川: '四川', 西藏: '西藏', 新疆: '新疆',
  新疆兵团: '新疆兵团', 云南: '云南', 浙江: '浙江',
}

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

// ========== 虚拟滚动（@vueuse/core 辅助函数组合） ==========
// 从 App.vue 注入滚动容器 ref（App.vue 根 div，h-dvh overflow-y-auto）。
const scrollRef = inject('scrollRef')
// grid 容器 ref，用于 ResizeObserver 测量实际内容宽度（受 main 的 max-w-7xl 和 padding 约束）。
const gridRef = ref(null)
// grid 容器实际宽度，由 ResizeObserver 持续更新。
const containerWidth = ref(1024)
let resizeObserver = null
let epgTimer = null

// useScroll（@vueuse/core）：响应式追踪滚动位置，自动处理 iOS Safari 弹性滚动等边界。
const { y: scrollY } = useScroll(scrollRef)
// 节流到 60fps（16ms），避免低端机频繁计算。
const throttledScrollY = useThrottleFn((val) => { scrollPosition.value = val }, 16)
const scrollPosition = ref(0)
// scrollY 变化时触发节流更新。
watchEffect(() => { throttledScrollY(scrollY.value) })

// 响应式列数：移动端 2 列、平板 4 列、桌面 6 列。
const columns = computed(() => {
  const w = containerWidth.value
  if (w >= 1024) return 6
  if (w >= 640) return 4
  return 2
})

// 行间距：统一 20px，同时绑定到 grid 的 :style 保证 CSS/JS 完全同步。
const gap = computed(() => 20)

// 单行高度 = 卡片宽度（正方形）+ 行间距。
const rowHeight = computed(() => {
  const cols = columns.value
  return (containerWidth.value - gap.value * (cols - 1)) / cols
})

// 卡片尺寸（宽=高）：Safari 对 aspect-ratio + Grid 有 bug，改用 JS 直接设 height。
const cardSize = computed(() => rowHeight.value)

// 电台按行分组，每行包含 columns 个电台。
const rows = computed(() => {
  const cols = columns.value
  const stations = filteredStations.value
  const result = []
  for (let i = 0; i < stations.length; i += cols) {
    result.push(stations.slice(i, i + cols))
  }
  return result
})

// 虚拟行计算：只取可视区域附近 ±3 行，其余不创建 DOM。
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

// 总滚动高度，撑开滚动容器的滚动条。
const totalHeight = computed(() => rows.value.length * (rowHeight.value + gap.value))

// 监听 grid 容器宽度变化，驱动列数和行高重新计算。
onMounted(() => {
  resizeObserver = new ResizeObserver((entries) => {
    for (const entry of entries) {
      containerWidth.value = entry.contentRect.width
    }
  })
  if (gridRef.value) resizeObserver.observe(gridRef.value)

  // 一次请求拉取所有省份云听电台（后端 /api/yunting/all 从预热缓存返回，零延迟）
  ;(async () => {
    ytLoading.value = true
    const list = await fetchAllYuntingStations()
    ytStations.value = list
    list.forEach((s) => playerStore.addStation(s))
    ytLoading.value = false
  })()

  // myradio.tw 台湾电台（后端 /api/myradio/all 从预热缓存返回）
  ;(async () => {
    mrLoading.value = true
    const list = await fetchMyradioStations()
    mrStations.value = list
    list.forEach((s) => playerStore.addStation(s))
    mrLoading.value = false
  })()

  // EPG 定期刷新（每 3 分钟），同时更新卡片显示和 store（触发 MediaSession 刷新）
  epgTimer = setInterval(async () => {
    try {
      const res = await fetch('/api/yunting/epg')
      if (res.ok) syncEpg(await res.json())
    } catch {}
  }, 180_000)
})

// 组件卸载时断开 ResizeObserver，防止内存泄漏。
onBeforeUnmount(() => {
  if (resizeObserver) resizeObserver.disconnect()
  if (epgTimer) clearInterval(epgTimer)
})
</script>
