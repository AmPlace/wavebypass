<template>
  <!-- 全局应用壳：负责背景、字体、主题色过渡和页面组合。 -->
  <div class="min-h-screen bg-gray-100 font-sans text-neutral-950 antialiased transition-colors duration-300 dark:bg-neutral-900 dark:text-neutral-50">
    <!-- 顶部主题切换按钮。 -->
    <button
      type="button"
      class="fixed right-4 top-4 z-50 flex size-10 items-center justify-center rounded-full border border-black/5 bg-white/70 text-neutral-700 shadow-sm shadow-black/[0.04] backdrop-blur-xl transition-all duration-200 ease-out hover:scale-[1.03] hover:bg-white active:scale-95 dark:border-white/10 dark:bg-neutral-950/60 dark:text-neutral-200 dark:hover:bg-neutral-950 sm:right-6 sm:top-6"
      :aria-label="isDark ? '切换到浅色模式' : '切换到深色模式'"
      @click="toggleTheme"
    >
      <!-- 深色模式图标。 -->
      <svg
        v-if="isDark"
        class="size-5"
        viewBox="0 0 24 24"
        fill="none"
        aria-hidden="true"
      >
        <path
          d="M12 3v2M12 19v2M4.93 4.93l1.41 1.41M17.66 17.66l1.41 1.41M3 12h2M19 12h2M4.93 19.07l1.41-1.41M17.66 6.34l1.41-1.41"
          stroke="currentColor"
          stroke-width="1.8"
          stroke-linecap="round"
        />
        <circle
          cx="12"
          cy="12"
          r="4"
          stroke="currentColor"
          stroke-width="1.8"
        />
      </svg>

      <!-- 浅色模式图标。 -->
      <svg
        v-else
        class="size-5"
        viewBox="0 0 24 24"
        fill="none"
        aria-hidden="true"
      >
        <path
          d="M20.5 14.4A7.7 7.7 0 0 1 9.6 3.5 8.5 8.5 0 1 0 20.5 14.4Z"
          stroke="currentColor"
          stroke-width="1.8"
          stroke-linecap="round"
          stroke-linejoin="round"
        />
      </svg>
    </button>

    <!-- 主体选台页面。 -->
    <Home />

    <!-- 底部播放器。 -->
    <BottomPlayer />

    <!-- 隐藏音频引擎，负责真实 HLS 播放。 -->
    <AudioEngine />
  </div>
</template>

<script setup>
// 1. 导入 Vue 响应式 API
import { onBeforeUnmount, onMounted, ref } from 'vue'

// 2. 导入子组件（白屏就是因为上次漏了这三行！千万别删）
import Home from './views/Home.vue'
import BottomPlayer from './components/BottomPlayer.vue'
import AudioEngine from './components/AudioEngine.vue'

// 3. 主题控制逻辑
const THEME_STORAGE_KEY = 'wavebypass-theme'
const isDark = ref(false)
let mediaQuery = null

// 核心判断逻辑
function applyTheme() {
  const savedTheme = window.localStorage.getItem(THEME_STORAGE_KEY)
  const prefersDark = window.matchMedia('(prefers-color-scheme: dark)').matches

  // 如果有本地存储，优先本地；否则跟随系统
  const shouldUseDark = savedTheme ? savedTheme === 'dark' : prefersDark

  isDark.value = shouldUseDark
  document.documentElement.classList.toggle('dark', shouldUseDark)
}

// 用户手动点击按钮
function toggleTheme() {
  const nextTheme = isDark.value ? 'light' : 'dark'
  window.localStorage.setItem(THEME_STORAGE_KEY, nextTheme)
  applyTheme()
}

// 专门处理系统主题改变的函数
function handleSystemThemeChange(e) {
  // 当系统主动切换深浅色时，说明用户在系统设置里操作了
  // 此时清除网页上的手动锁定，重新跟随系统
  window.localStorage.removeItem(THEME_STORAGE_KEY)
  applyTheme()
}

// 处理 iOS Safari 挂起后重回页面的延迟问题
function handleVisibilityChange() {
  if (document.visibilityState === 'visible') {
    applyTheme()
  }
}

onMounted(() => {
  applyTheme()
  
  mediaQuery = window.matchMedia('(prefers-color-scheme: dark)')
  
  // 监听系统主题变化
  mediaQuery.addEventListener('change', handleSystemThemeChange)
  
  // 监听页面可见性变化，专治 iOS Safari 反应迟钝
  document.addEventListener('visibilitychange', handleVisibilityChange)
})

onBeforeUnmount(() => {
  if (mediaQuery) {
    mediaQuery.removeEventListener('change', handleSystemThemeChange)
  }
  document.removeEventListener('visibilitychange', handleVisibilityChange)
})
</script>
