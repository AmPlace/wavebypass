<template>
  <!-- 底部悬浮播放器：使用 fixed 和安全区 padding 适配移动端底部手势区域。 -->
  <footer class="fixed inset-x-0 bottom-0 z-40 px-4 pb-4 sm:px-6 sm:pb-6">
    <!-- 毛玻璃播放器容器。 -->
    <div
      class="mx-auto flex h-20 max-w-4xl items-center justify-between gap-3 rounded-3xl border border-white/20 bg-white/70 px-4 shadow-lg shadow-black/[0.06] backdrop-blur-xl dark:border-white/10 dark:bg-black/70 dark:shadow-black/30 sm:px-5"
    >
      <!-- 左侧：当前电台与直播状态。 -->
      <section class="flex min-w-0 basis-[30%] items-center gap-3">
        <!-- 状态点：播放中是绿色呼吸点，加载中是克制的小转圈，错误时是红点。 -->
        <span class="relative flex size-3 shrink-0 items-center justify-center">
          <span
            v-if="isLoading"
            class="size-3 rounded-full border border-neutral-300 border-t-neutral-900 animate-spin dark:border-neutral-700 dark:border-t-white"
          ></span>
          <span
            v-else-if="isPlaying"
            class="absolute inline-flex size-2.5 animate-ping rounded-full bg-emerald-400 opacity-60"
          ></span>
          <span
            v-if="!isLoading"
            class="relative inline-flex size-2.5 rounded-full"
            :class="statusDotClass"
          ></span>
        </span>

        <!-- 电台名称，窄屏时单行省略。 -->
        <div class="min-w-0">
          <p class="truncate text-sm font-medium text-neutral-900 dark:text-neutral-100">
            {{ currentStationName }}
          </p>
          <p
            class="truncate text-xs font-medium"
            :class="playbackError ? 'text-red-500 dark:text-red-400' : 'text-neutral-500 dark:text-neutral-500'"
          >
            {{ statusText }}
          </p>
        </div>
      </section>

      <!-- 中间：播放 / 暂停按钮。 -->
      <section class="flex basis-[40%] justify-center">
        <button
          type="button"
          class="flex size-12 items-center justify-center rounded-full bg-neutral-950 text-white shadow-sm shadow-black/10 transition-all duration-200 ease-out hover:scale-[1.03] hover:bg-black active:scale-95 dark:bg-white dark:text-black dark:hover:bg-neutral-100"
          :aria-label="isPlaying ? '暂停播放' : '开始播放'"
          @click="playerStore.togglePlay()"
        >
          <!-- 暂停图标。 -->
          <svg
            v-if="isPlaying"
            class="size-5"
            viewBox="0 0 24 24"
            fill="none"
            aria-hidden="true"
          >
            <path
              d="M8 5v14M16 5v14"
              stroke="currentColor"
              stroke-width="2.5"
              stroke-linecap="round"
            />
          </svg>

          <!-- 播放图标。 -->
          <svg
            v-else
            class="ml-0.5 size-5"
            viewBox="0 0 24 24"
            fill="none"
            aria-hidden="true"
          >
            <path
              d="M8 5.75v12.5c0 .72.78 1.17 1.4.8l10.1-6.25a.94.94 0 0 0 0-1.6L9.4 4.95A.93.93 0 0 0 8 5.75Z"
              fill="currentColor"
            />
          </svg>
        </button>
      </section>

      <!-- 右侧：音量控制。 -->
      <section class="flex basis-[30%] items-center justify-end gap-3">
        <!-- 音量图标。 -->
        <svg
          class="hidden size-5 shrink-0 text-neutral-500 dark:text-neutral-400 sm:block"
          viewBox="0 0 24 24"
          fill="none"
          aria-hidden="true"
        >
          <path
            d="M4 10v4a1 1 0 0 0 1 1h3l4.2 3.15A.5.5 0 0 0 13 17.75V6.25a.5.5 0 0 0-.8-.4L8 9H5a1 1 0 0 0-1 1Z"
            stroke="currentColor"
            stroke-width="1.8"
            stroke-linejoin="round"
          />
          <path
            d="M16 9a4 4 0 0 1 0 6"
            stroke="currentColor"
            stroke-width="1.8"
            stroke-linecap="round"
          />
          <path
            d="M18.5 6.5a7.5 7.5 0 0 1 0 11"
            stroke="currentColor"
            stroke-width="1.8"
            stroke-linecap="round"
          />
        </svg>

        <!-- 极简音量滑动条。 -->
        <input
          class="h-1 w-20 cursor-pointer appearance-none rounded-full bg-neutral-300 accent-neutral-950 outline-none transition-colors duration-200 dark:bg-neutral-700 dark:accent-white sm:w-28 [&::-moz-range-thumb]:size-3 [&::-moz-range-thumb]:appearance-none [&::-moz-range-thumb]:rounded-full [&::-moz-range-thumb]:border-0 [&::-moz-range-thumb]:bg-neutral-950 dark:[&::-moz-range-thumb]:bg-white [&::-webkit-slider-thumb]:size-3 [&::-webkit-slider-thumb]:appearance-none [&::-webkit-slider-thumb]:rounded-full [&::-webkit-slider-thumb]:bg-neutral-950 dark:[&::-webkit-slider-thumb]:bg-white"
          type="range"
          min="0"
          max="1"
          step="0.01"
          :value="volume"
          aria-label="音量"
          @input="playerStore.setVolume($event.target.value)"
        />
      </section>
    </div>
  </footer>
</template>

<script setup>
// computed 用于根据当前电台 ID 计算展示名称。
import { computed } from 'vue'

// storeToRefs 用于保持 Pinia state 的响应式。
import { storeToRefs } from 'pinia'

// 引入播放器状态仓库。
import { usePlayerStore } from '../stores/player'

// 获取播放器 store。
const playerStore = usePlayerStore()

// 解构播放器状态。
const { currentStation, isPlaying, isLoading, volume, playbackError } = storeToRefs(playerStore)

// 电台名称映射。
// 这里和 Home.vue 的电台列表保持一致，后续可以抽到公共配置文件。
import { stationMap } from '../config/stations'

// 根据当前电台 ID 获取展示名称。
const currentStationName = computed(() => {
  // 1. 变量名换成引入的 stationMap
  // 2. 加上 ?.name 提取对象里的名字属性
  return stationMap[currentStation.value]?.name || currentStation.value || '未选择电台'
})

// 底部状态文案。
// 有错误时展示错误；没有错误时保持简洁的 Live 状态。
const statusText = computed(() => {
  if (playbackError.value) {
    return playbackError.value
  }

  if (isLoading.value) {
    return '正在连接'
  }

  return 'Live'
})

// 状态圆点颜色。
// 错误时显示红色；播放中显示绿色；空闲时显示灰色。
const statusDotClass = computed(() => {
  if (playbackError.value) {
    return 'bg-red-500'
  }

  if (isPlaying.value) {
    return 'bg-emerald-500'
  }

  return 'bg-neutral-300 dark:bg-neutral-700'
})
</script>
