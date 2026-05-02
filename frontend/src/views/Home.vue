<template>
  <!-- 页面主体区域：预留底部播放器空间，避免内容被悬浮控制条遮挡。 -->
  <main class="mx-auto flex min-h-screen w-full max-w-7xl items-center px-5 py-10 pb-36 sm:px-8 lg:px-10">
    <!-- 自适应电台网格：移动端 2 列，平板 4 列，桌面 6 列。 -->
    <section class="grid w-full grid-cols-2 gap-4 sm:grid-cols-4 sm:gap-5 lg:grid-cols-6">
      <!-- 单个电台卡片。 -->
      <button
        v-for="station in stations"
        :key="station.id"
        type="button"
        :aria-label="`切换到 ${station.name}`"
        class="group aspect-square rounded-3xl border border-white/70 bg-gray-50/80 p-3 text-left shadow-sm shadow-black/[0.03] outline-none backdrop-blur-xl transition-all duration-300 ease-out hover:scale-[1.02] hover:bg-white/90 active:scale-95 dark:border-white/10 dark:bg-neutral-800/50 dark:shadow-black/20 dark:hover:bg-neutral-800/75"
        :class="{
          'ring-2 ring-black dark:ring-white': isCurrentStationPlaying(station.id),
        }"
        @click="playerStore.switchStation(station.id)"
      >
        <!-- 卡片内部纵向布局，上方 60% 放 Logo，下方 40% 放名称。 -->
        <div class="flex h-full flex-col overflow-hidden rounded-[1.25rem]">
          <!-- Logo 区域。 -->
          <div class="flex basis-3/5 items-center justify-center">
            <!-- Logo 外层容器，固定圆形尺寸，避免图片加载前后导致卡片跳动。 -->
            <div
              class="flex size-16 items-center justify-center overflow-hidden rounded-full border border-black/5 bg-white text-lg font-semibold text-neutral-700 shadow-sm shadow-black/[0.04] transition-transform duration-300 ease-out group-hover:scale-105 dark:border-white/10 dark:bg-neutral-900 dark:text-neutral-200 sm:size-20"
            >
              <!-- 如果配置了真实 logo 图片，就优先显示图片。 -->
              <img
                v-if="station.logoUrl"
                class="h-full w-full object-contain p-2"
                :src="station.logoUrl"
                :alt="`${station.name} logo`"
              />

              <!-- 如果还没有真实 logo，就回退到字母占位符。 -->
              <span v-else>
                {{ station.logoText }}
              </span>
            </div>
          </div>

          <!-- 电台名称区域。 -->
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
// storeToRefs 用于把 Pinia 状态转为响应式 ref。
import { storeToRefs } from 'pinia'

// 引入播放器状态仓库。
import { usePlayerStore } from '../stores/player'

// 获取播放器 store。
const playerStore = usePlayerStore()

// 解构当前电台和播放状态，用于判断卡片是否高亮。
const { currentStation, isPlaying } = storeToRefs(playerStore)

// 电台列表。
// 当前只展示后端已经注册抓取器的电台，避免用户点到尚未接入的电台后出现 503。
// 后续如果电台变多，可以把这个数组抽到独立配置文件中统一维护。
const stations = [
  {
    id: 'hitfm',
    name: 'Hit FM',
    logoText: 'H',
    logoUrl: '/logos/hitfm.png',
  },
  {
    id: 'ufo',
    name: 'UFO Radio',
    logoText: 'U',
  },
]

// 判断某个电台是否是当前正在播放的电台。
function isCurrentStationPlaying(stationId) {
  return currentStation.value === stationId && isPlaying.value
}
</script>
