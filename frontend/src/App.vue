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
// Vue 生命周期与响应式工具。
import { onBeforeUnmount, onMounted, ref } from 'vue'

// 页面主体。
import Home from './views/Home.vue'

// 底部播放器。
import BottomPlayer from './components/BottomPlayer.vue'

// 隐藏音频引擎。
import AudioEngine from './components/AudioEngine.vue'

// 主题本地存储键。
const THEME_STORAGE_KEY = 'wavebypass-theme'

// 当前是否为深色模式。
const isDark = ref(false)

// 保存系统主题监听器，组件卸载时用于清理。
let mediaQuery = null

// 根据当前设置应用主题。
function applyTheme() {
  // 用户手动选择的主题，可能是 light、dark 或 null。
  const savedTheme = window.localStorage.getItem(THEME_STORAGE_KEY)

  // 系统是否偏好深色模式。
  const prefersDark = window.matchMedia('(prefers-color-scheme: dark)').matches

  // 如果用户没有手动选择，就跟随系统；否则使用用户选择。
  const shouldUseDark = savedTheme ? savedTheme === 'dark' : prefersDark

  // 同步响应式状态，供图标切换使用。
  isDark.value = shouldUseDark

  // Tailwind 的 dark: 类默认依赖 html.dark。
  document.documentElement.classList.toggle('dark', shouldUseDark)
}

// 手动切换主题。
function toggleTheme() {
  // 当前深色则切到浅色，当前浅色则切到深色。
  const nextTheme = isDark.value ? 'light' : 'dark'

  // 写入本地存储，表示用户已经做过手动选择。
  window.localStorage.setItem(THEME_STORAGE_KEY, nextTheme)

  // 立刻应用新主题。
  applyTheme()
}

// 组件挂载后初始化主题，并监听系统主题变化。
onMounted(() => {
  // 首次进入页面时应用主题。
  applyTheme()

  // 创建系统主题偏好监听器。
  mediaQuery = window.matchMedia('(prefers-color-scheme: dark)')

  // 当用户没有手动选择主题时，系统主题变化会自动同步。
  mediaQuery.addEventListener('change', applyTheme)
})

// 组件卸载前移除系统主题监听器。
onBeforeUnmount(() => {
  if (mediaQuery) {
    mediaQuery.removeEventListener('change', applyTheme)
  }
})
</script>
