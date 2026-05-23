<template>
  <main class="mx-auto flex min-h-screen w-full max-w-7xl flex-col items-center px-5 pt-[calc(env(safe-area-inset-top)+3.5rem)] pb-36 sm:px-8 lg:px-10">

    <header class="mb-6 w-full space-y-3">
      <div class="relative flex items-center">
        <button
          v-show="canScrollLeft"
          type="button"
          class="hidden shrink-0 sm:flex absolute left-0 z-10 size-7 items-center justify-center rounded-full bg-white/90 text-gray-500 shadow-sm hover:text-gray-800 dark:bg-neutral-800/90 dark:text-gray-400 dark:hover:text-gray-200"
          aria-label="向左滚动"
          @click="scrollRegionBy(-150)"
        >
          <svg class="size-4" viewBox="0 0 24 24" fill="none"><path d="M15 19l-7-7 7-7" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg>
        </button>

        <div
          ref="regionScrollRef"
          class="flex items-center gap-2 overflow-x-auto scrollbar-hide"
          @scroll="onRegionScroll"
        >
          <span class="shrink-0 text-xs text-gray-400 dark:text-gray-500">地区</span>
          <button
            type="button"
            class="shrink-0 rounded-full border px-3 py-1 text-xs transition-colors"
            :class="pillClass(!selectedRegion)"
            @click="selectedRegion = ''"
          >
            全部
          </button>
          <button
            v-for="r in regions"
            :key="r"
            type="button"
            class="shrink-0 rounded-full border px-3 py-1 text-xs transition-colors"
            :class="pillClass(selectedRegion === r)"
            @click="selectedRegion = selectedRegion === r ? '' : r"
          >
            {{ regionLabels[r] || r }}
          </button>
        </div>

        <button
          v-show="canScrollRight"
          type="button"
          class="hidden shrink-0 sm:flex absolute right-0 z-10 size-7 items-center justify-center rounded-full bg-white/90 text-gray-500 shadow-sm hover:text-gray-800 dark:bg-neutral-800/90 dark:text-gray-400 dark:hover:text-gray-200"
          aria-label="向右滚动"
          @click="scrollRegionBy(150)"
        >
          <svg class="size-4" viewBox="0 0 24 24" fill="none"><path d="M9 5l7 7-7 7" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg>
        </button>

        <div
          v-show="canScrollRight"
          class="pointer-events-none absolute right-0 top-0 bottom-0 w-12 bg-gradient-to-l from-gray-100 to-transparent dark:from-neutral-900 sm:hidden"
        ></div>
      </div>

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

      <p class="text-xs text-gray-400 dark:text-gray-500">
        共 {{ filteredStations.length }} 个电台
        <span v-if="ytLoading || mrLoading" class="ml-2">正在加载…</span>
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
                    @error="useDefaultLogo"
                  />
                  <span v-else>{{ station.logoText }}</span>
                </div>
              </div>
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
import { computed, inject, nextTick, onBeforeUnmount, onMounted, ref, watch, watchEffect } from 'vue'
import { useScroll, useThrottleFn } from '@vueuse/core'

const playerStore = usePlayerStore()
const { currentStation, isPlaying, isLoading, stationList } = storeToRefs(playerStore)

const ytStations = ref([])
const ytLoading = ref(false)

const mrStations = ref([])
const mrLoading = ref(false)
const DEFAULT_LOGO_URL = '/logos/default.png'

function useDefaultLogo(event) {
  const img = event?.target
  if (!img || img.dataset.logoFallback === '1') return
  img.dataset.logoFallback = '1'
  img.src = DEFAULT_LOGO_URL
}

// EPG：初始 subtitle 从云听 API，定期 /api/yunting/epg 刷新，同步到 store 触发 MediaSession
const epgMap = ref({})

function syncEpg(data) {
  epgMap.value = data
  for (const [cid, subtitle] of Object.entries(data)) {
    playerStore.updateStationEpg(`yt_${cid}`, subtitle)
  }
}

watch(ytStations, (list) => {
  const initial = {}
  for (const s of list) {
    if (s.subtitle) initial[s.id.replace('yt_', '')] = s.subtitle
  }
  if (Object.keys(initial).length) syncEpg(initial)
}, { once: true })

const T2S = { '樂':'乐','聲':'声','網':'网','廣':'广','聯':'联','華':'华','國':'国','東':'东','電':'电','視':'视','經':'经','發':'发','動':'动','學':'学','機':'机','區':'区','車':'车','產':'产','業':'业','問':'问','開':'开','長':'长','報':'报','點':'点','號':'号','團':'团','場':'场','處':'处','間':'间','書':'书','術':'术','議':'议','記':'记','設':'设','計':'计','話':'话','題':'题','調':'调','論':'论','辦':'办','營':'营','環':'环','競':'竞','衛':'卫','實':'实','總':'总','統':'统','義':'义','資':'资','運':'运','選':'选','達':'达','進':'进','鄉':'乡','錢':'钱','鐵':'铁','門':'门','陽':'阳','雲':'云','飛':'飞','魚':'鱼','馬':'马','風':'风','齊':'齐','龍':'龙' }

function normalizeForDedup(str) {
  return (str || '').replace(/\s+/g, '').toLowerCase().replace(/[一-鿿]/g, (c) => T2S[c] || c)
}

function deduplicateByName(stations) {
  const groups = new Map()
  for (const s of stations) {
    const key = normalizeForDedup(s.name)
    if (!groups.has(key)) groups.set(key, [])
    groups.get(key).push(s)
  }
  return [...groups.values()].map((group) => {
    if (group.length === 1) return group[0]
    const pri = (s) => {
      if (s.id.startsWith('mr_')) return 1
      if (s.id.startsWith('yt_')) return 2
      if (s.id.startsWith('rb_')) return 3
      return 0
    }
    group.sort((a, b) => pri(a) - pri(b))
    const primary = { ...group[0] }
    primary.tags = [...new Set(group.flatMap((s) => s.tags || []))]
    if (!primary.logoUrl) {
      const found = group.find((s) => s.logoUrl)
      if (found) primary.logoUrl = found.logoUrl
    }
    return primary
  })
}

const allStations = computed(() => {
  if (!geoConfigLoaded.value) return []
  const merged = deduplicateByName([...stationList.value, ...mrStations.value, ...ytStations.value])
  if (!geoConfig.value.geoRestrict) return merged
  const blocked = new Set(geoConfig.value.blockedRegions || [])
  if (!blocked.size) return merged
  return merged.filter((s) => !(s.tags || []).some((t) => blocked.has(t)))
})

const regionLabels = {
  TW: '台湾', CN: '中国大陆', JP: '日本', US: '美国', KR: '韩国', GB: '英国', DE: '德国', FR: '法国',
  安徽: '安徽', 北京: '北京', 重庆: '重庆', 福建: '福建', 甘肃: '甘肃', 广东: '广东', 广西: '广西',
  贵州: '贵州', 海南: '海南', 河北: '河北', 河南: '河南', 黑龙江: '黑龙江', 湖北: '湖北', 湖南: '湖南',
  吉林: '吉林', 江苏: '江苏', 江西: '江西', 辽宁: '辽宁', 内蒙古: '内蒙古', 宁夏: '宁夏', 青海: '青海',
  山东: '山东', 山西: '山西', 陕西: '陕西', 上海: '上海', 四川: '四川', 西藏: '西藏', 新疆: '新疆',
  新疆兵团: '新疆兵团', 云南: '云南', 浙江: '浙江',
}

const typeLabels = { music: '音乐', news: '新闻', talk: '谈话', sports: '体育', religious: '宗教', other: '其他' }

const selectedRegion = ref('')
const selectedType = ref('')
const searchQuery = inject('searchQuery')

const regionScrollRef = ref(null)
const canScrollLeft = ref(false)
const canScrollRight = ref(false)

function updateScrollState() {
  const el = regionScrollRef.value
  if (!el) return
  canScrollLeft.value = el.scrollLeft > 2
  canScrollRight.value = el.scrollLeft < el.scrollWidth - el.clientWidth - 2
}

function onRegionScroll() {
  updateScrollState()
}

function scrollRegionBy(delta) {
  regionScrollRef.value?.scrollBy({ left: delta, behavior: 'smooth' })
}

const geoConfig = ref({ geoRestrict: false, blockedRegions: [] })
const geoConfigLoaded = ref(false)

const regions = computed(() => {
  const set = new Set()
  for (const s of allStations.value) {
    for (const t of s.tags || []) {
      if (regionLabels[t]) set.add(t)
    }
  }
  return [...set]
})

watch(regions, () => nextTick(updateScrollState))

const types = computed(() => {
  const set = new Set()
  for (const s of allStations.value) {
    for (const t of s.tags || []) {
      if (typeLabels[t]) set.add(t)
    }
  }
  return [...set]
})

const filteredStations = ref([])

watchEffect(() => {
  const region = selectedRegion.value
  const type = selectedType.value
  const query = searchQuery.value.trim().toLowerCase()
  const result = allStations.value.filter((s) => {
    const tags = s.tags || []
    if (region && !tags.includes(region)) return false
    if (type && !tags.includes(type)) return false
    if (query && !(s.name || '').toLowerCase().includes(query)) return false
    return true
  })
  filteredStations.value = result
})

function pillClass(active) {
  return active
    ? 'border-black bg-black text-white dark:border-white dark:bg-white dark:text-black'
    : 'border-gray-300 bg-white text-gray-600 hover:bg-gray-100 dark:border-neutral-600 dark:bg-neutral-800 dark:text-gray-300 dark:hover:bg-neutral-700'
}

function isCurrentStationPlaying(stationId) {
  return currentStation.value === stationId && isPlaying.value
}

function isCurrentStationLoading(stationId) {
  return currentStation.value === stationId && isLoading.value
}

const scrollRef = inject('scrollRef')
const gridRef = ref(null)
const containerWidth = ref(1024)
let resizeObserver = null
let epgTimer = null

const { y: scrollY } = useScroll(scrollRef)
const throttledScrollY = useThrottleFn((val) => { scrollPosition.value = val }, 16)
const scrollPosition = ref(0)
watchEffect(() => { throttledScrollY(scrollY.value) })

const columns = computed(() => {
  const w = containerWidth.value
  if (w >= 1024) return 6
  if (w >= 640) return 4
  return 2
})

const gap = computed(() => 20)

const rowHeight = computed(() => {
  const cols = columns.value
  return (containerWidth.value - gap.value * (cols - 1)) / cols
})

const cardSize = computed(() => rowHeight.value)

const rows = computed(() => {
  const cols = columns.value
  const stations = filteredStations.value
  const result = []
  for (let i = 0; i < stations.length; i += cols) {
    result.push(stations.slice(i, i + cols))
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

  nextTick(updateScrollState)

  ;(async () => {
    try {
      const [cfgRes, stRes] = await Promise.all([
        fetch('/api/config'),
        fetch('/api/stations'),
      ])
      if (cfgRes.ok) geoConfig.value = await cfgRes.json()
      if (stRes.ok) {
        const stations = await stRes.json()
        playerStore.loadStations(stations)
      }
    } catch {}
    geoConfigLoaded.value = true
  })()

  ;(async () => {
    ytLoading.value = true
    const list = await fetchAllYuntingStations()
    ytStations.value = list
    list.forEach((s) => playerStore.addStation(s))
    ytLoading.value = false
  })()

  ;(async () => {
    mrLoading.value = true
    const list = await fetchMyradioStations()
    mrStations.value = list
    list.forEach((s) => playerStore.addStation(s))
    mrLoading.value = false
  })()

  epgTimer = setInterval(async () => {
    try {
      const res = await fetch('/api/yunting/epg')
      if (res.ok) syncEpg(await res.json())
    } catch {}
  }, 180_000)
})

onBeforeUnmount(() => {
  if (resizeObserver) resizeObserver.disconnect()
  if (epgTimer) clearInterval(epgTimer)
})
</script>
