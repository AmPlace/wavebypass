<template>
  <!-- 全局应用壳：负责背景、字体、主题色过渡和页面组合。 -->
  <div class="min-h-screen bg-gray-100 font-sans text-neutral-950 antialiased transition-colors duration-300 dark:bg-neutral-900 dark:text-neutral-50">
    <!-- 顶部工具栏：搜索按钮 + 主题切换按钮，同一排，样式统一。 -->
    <div class="fixed right-4 top-4 z-50 flex items-center gap-2 sm:right-6 sm:top-6">
      <!-- 搜索框：默认收起为圆形图标，点击展开为输入框 -->
      <div
        class="relative flex items-center rounded-full border border-black/5 bg-white/70 shadow-sm shadow-black/[0.04] backdrop-blur-xl transition-all duration-300 ease-out dark:border-white/10 dark:bg-neutral-950/60"
        :class="searchExpanded ? 'w-48 sm:w-56' : 'size-10'"
      >
        <!-- 搜索图标按钮：点击展开/收起 -->
        <button
          type="button"
          class="flex size-10 shrink-0 items-center justify-center text-neutral-700 transition-colors hover:text-neutral-900 dark:text-neutral-200 dark:hover:text-white"
          aria-label="搜索电台"
          @click="toggleSearch"
        >
          <svg class="size-5" viewBox="0 0 24 24" fill="none" aria-hidden="true">
            <circle cx="11" cy="11" r="7" stroke="currentColor" stroke-width="1.8" />
            <path d="M16.5 16.5L21 21" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" />
          </svg>
        </button>
        <!-- 输入框：展开后显示，收起后隐藏 -->
        <input
          ref="searchInputRef"
          v-model="searchQuery"
          type="text"
          placeholder="搜索电台…"
          class="h-full w-full bg-transparent pr-3 text-sm text-neutral-800 outline-none placeholder:text-gray-400 dark:text-neutral-200 dark:placeholder:text-gray-500"
          :class="searchExpanded ? 'opacity-100' : 'pointer-events-none opacity-0'"
          @blur="onSearchBlur"
        />
      </div>

      <!-- 主题切换按钮 -->
      <button
        type="button"
        class="flex size-10 items-center justify-center rounded-full border border-black/5 bg-white/70 text-neutral-700 shadow-sm shadow-black/[0.04] backdrop-blur-xl transition-all duration-200 ease-out hover:scale-[1.03] hover:bg-white active:scale-95 dark:border-white/10 dark:bg-neutral-950/60 dark:text-neutral-200 dark:hover:bg-neutral-950"
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
    </div>

    <!-- 主体选台页面。 -->
    <Home />

    <!-- 底部播放器。 -->
    <BottomPlayer />

    <!-- 隐藏音频引擎，负责真实 HLS 播放。 -->
    <AudioEngine />
  </div>
</template>

<script setup>
import { onBeforeUnmount, onMounted, provide, ref, nextTick } from 'vue'
import Home from './views/Home.vue'
import BottomPlayer from './components/BottomPlayer.vue'
import AudioEngine from './components/AudioEngine.vue'

const THEME_STORAGE_KEY = 'wavebypass-theme'
const isDark = ref(false)
let mediaQuery = null

// 【新增核心功能】：动态修改手机状态栏颜色
function updateThemeColor(isDarkMode) {
  // 查找是否已经有 theme-color 标签
  let metaThemeColor = document.querySelector('meta[name="theme-color"]')
  
  if (!metaThemeColor) {
    // 如果没有，就动态创建一个插入到 <head> 中
    metaThemeColor = document.createElement('meta')
    metaThemeColor.name = 'theme-color'
    document.head.appendChild(metaThemeColor)
  }
  
  // 完美对接你的 Tailwind 背景色：
  // 浅色模式你的背景是 bg-gray-100，对应 Hex 色值是 #f3f4f6
  // 深色模式你的背景是 bg-neutral-900，对应 Hex 色值是 #171717
  metaThemeColor.content = isDarkMode ? '#171717' : '#f3f4f6'
}

// 核心判断逻辑
function applyTheme() {
  const savedTheme = window.localStorage.getItem(THEME_STORAGE_KEY)
  const prefersDark = window.matchMedia('(prefers-color-scheme: dark)').matches

  const shouldUseDark = savedTheme ? savedTheme === 'dark' : prefersDark

  isDark.value = shouldUseDark
  document.documentElement.classList.toggle('dark', shouldUseDark)
  
  // 每次切换主题时，同步修改手机状态栏颜色！
  updateThemeColor(shouldUseDark)
}

// 【关键修复】：将 applyTheme() 移出 onMounted！
// 直接在 script setup 顶层同步执行，组件还没挂载到 DOM 时就先算好主题，
// 彻底解决第一次进入时”慢半拍”不跟随系统的问题。
applyTheme()

// ========== 搜索功能 ==========
// 搜索关键词，通过 provide 传递给 Home.vue 做电台过滤
const searchQuery = ref('')
provide('searchQuery', searchQuery)

// 搜索框展开状态：默认收起为圆形图标，点击展开为输入框
const searchExpanded = ref(false)
// 输入框 ref，展开后自动聚焦
const searchInputRef = ref(null)

// 点击搜索图标：切换展开/收起
function toggleSearch() {
  searchExpanded.value = !searchExpanded.value
  // 展开后自动聚焦输入框
  if (searchExpanded.value) {
    nextTick(() => searchInputRef.value?.focus())
  } else {
    // 收起时清空搜索内容
    searchQuery.value = ''
  }
}

// 输入框失焦且内容为空时自动收起
function onSearchBlur() {
  if (!searchQuery.value.trim()) {
    searchExpanded.value = false
  }
}

function toggleTheme() {
  const nextTheme = isDark.value ? 'light' : 'dark'
  window.localStorage.setItem(THEME_STORAGE_KEY, nextTheme)
  applyTheme()
}

function handleSystemThemeChange(e) {
  window.localStorage.removeItem(THEME_STORAGE_KEY)
  applyTheme()
}

function handleVisibilityChange() {
  if (document.visibilityState === 'visible') {
    applyTheme()
  }
}

onMounted(() => {
  // 挂载后只需要绑定监听器，不需要再调 applyTheme 了
  mediaQuery = window.matchMedia('(prefers-color-scheme: dark)')
  mediaQuery.addEventListener('change', handleSystemThemeChange)
  document.addEventListener('visibilitychange', handleVisibilityChange)
})

onBeforeUnmount(() => {
  if (mediaQuery) {
    mediaQuery.removeEventListener('change', handleSystemThemeChange)
  }
  document.removeEventListener('visibilitychange', handleVisibilityChange)
})
</script>
