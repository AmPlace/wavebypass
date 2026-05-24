<template>
  <div ref="scrollRef" class="h-dvh overflow-y-auto bg-[#f8f8f7] font-sans text-neutral-950 antialiased transition-colors duration-300 dark:bg-[#111113] dark:text-neutral-50">
    <div class="fixed inset-x-0 top-0 z-50 bg-[#f8f8f7] dark:bg-[#111113]">
      <div class="h-[env(safe-area-inset-top)]"></div>
      <div class="flex h-12 items-center justify-between px-4 sm:px-6">
        <div class="w-10"></div>
        <div class="flex items-center rounded-full border border-black/5 bg-white/70 p-0.5 text-xs font-medium shadow-sm shadow-black/[0.04] backdrop-blur-xl dark:border-white/10 dark:bg-neutral-950/60">
          <button
            type="button"
            class="rounded-full px-3 py-1.5 transition-all sm:px-4"
            :class="activeMode === 'radio'
              ? 'bg-neutral-950 text-white dark:bg-white dark:text-black'
              : 'text-neutral-500 hover:text-neutral-700 dark:text-neutral-400 dark:hover:text-neutral-200'"
            @click="router.push('/')"
          >
            Radio
          </button>
          <button
            type="button"
            class="rounded-full px-3 py-1.5 transition-all sm:px-4"
            :class="activeMode === 'iptv'
              ? 'bg-neutral-950 text-white dark:bg-white dark:text-black'
              : 'text-neutral-500 hover:text-neutral-700 dark:text-neutral-400 dark:hover:text-neutral-200'"
            @click="router.push('/iptv')"
          >
            TV
          </button>
        </div>
        <div class="flex items-center gap-2">
          <button
            v-show="activeMode === 'iptv'"
            type="button"
            class="flex size-10 items-center justify-center rounded-full border border-black/5 bg-white/70 text-neutral-700 shadow-sm shadow-black/[0.04] backdrop-blur-xl transition-all duration-200 ease-out hover:scale-[1.03] hover:bg-white active:scale-95 dark:border-white/10 dark:bg-neutral-950/60 dark:text-neutral-200 dark:hover:bg-neutral-950"
            aria-label="订阅管理"
            @click="router.push('/admin')"
          >
            <svg class="size-5" viewBox="0 0 24 24" fill="none"><path d="M12.22 2h-.44a2 2 0 0 0-2 2v.18a2 2 0 0 1-1 1.73l-.43.25a2 2 0 0 1-2 0l-.15-.08a2 2 0 0 0-2.73.73l-.22.38a2 2 0 0 0 .73 2.73l.15.1a2 2 0 0 1 1 1.72v.51a2 2 0 0 1-1 1.74l-.15.09a2 2 0 0 0-.73 2.73l.22.38a2 2 0 0 0 2.73.73l.15-.08a2 2 0 0 1 2 0l.43.25a2 2 0 0 1 1 1.73V20a2 2 0 0 0 2 2h.44a2 2 0 0 0 2-2v-.18a2 2 0 0 1 1-1.73l.43-.25a2 2 0 0 1 2 0l.15.08a2 2 0 0 0 2.73-.73l.22-.39a2 2 0 0 0-.73-2.73l-.15-.08a2 2 0 0 1-1-1.74v-.5a2 2 0 0 1 1-1.74l.15-.09a2 2 0 0 0 .73-2.73l-.22-.38a2 2 0 0 0-2.73-.73l-.15.08a2 2 0 0 1-2 0l-.43-.25a2 2 0 0 1-1-1.73V4a2 2 0 0 0-2-2z" stroke="currentColor" stroke-width="1.8"/><circle cx="12" cy="12" r="3" stroke="currentColor" stroke-width="1.8"/></svg>
          </button>

          <div
            class="relative flex items-center rounded-full border border-black/5 bg-white/70 shadow-sm shadow-black/[0.04] backdrop-blur-xl transition-all duration-300 ease-out dark:border-white/10 dark:bg-neutral-950/60"
            :class="searchExpanded ? 'w-48 sm:w-56' : 'size-10'"
          >
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

          <button
            type="button"
            class="flex size-10 items-center justify-center rounded-full border border-black/5 bg-white/70 text-neutral-700 shadow-sm shadow-black/[0.04] backdrop-blur-xl transition-all duration-200 ease-out hover:scale-[1.03] hover:bg-white active:scale-95 dark:border-white/10 dark:bg-neutral-950/60 dark:text-neutral-200 dark:hover:bg-neutral-950"
            :aria-label="isDark ? '切换到浅色模式' : '切换到深色模式'"
            @click="toggleTheme"
          >
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
      </div>
    </div>

    <router-view />

    <BottomPlayer />

    <AudioEngine />

    <FullPlayer />
  </div>
</template>

<script setup>
import { onBeforeUnmount, onMounted, provide, ref, nextTick, watch } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { storeToRefs } from 'pinia'
import { usePlayerStore } from './stores/player'
import BottomPlayer from './components/BottomPlayer.vue'
import AudioEngine from './components/AudioEngine.vue'
import FullPlayer from './components/FullPlayer.vue'

const THEME_STORAGE_KEY = 'wavebypass-theme'
const isDark = ref(false)
let mediaQuery = null

const scrollRef = ref(null)
provide('scrollRef', scrollRef)

const playerStore = usePlayerStore()
const { activeMode } = storeToRefs(playerStore)
const router = useRouter()
const route = useRoute()
const THEME_CHROME_COLORS = {
  light: '#f8f8f7',
  dark: '#111113',
}
const THEME_STATUS_BAR = {
  light: 'default',
  dark: 'default',
}

watch(() => route.path, (path) => {
  playerStore.setActiveMode(path.startsWith('/iptv') ? 'iptv' : 'radio')
}, { immediate: true })

function upsertMeta(name) {
  const metas = Array.from(document.querySelectorAll(`meta[name="${name}"]`))
  let meta = metas[0]
  metas.slice(1).forEach((node) => node.remove())
  if (!meta) {
    meta = document.createElement('meta')
    meta.name = name
    document.head.appendChild(meta)
  }
  meta.removeAttribute('media')
  return meta
}

function forceMetaContent(name, content) {
  const meta = upsertMeta(name)
  meta.setAttribute('content', content)
  meta.removeAttribute('media')

  // iOS Safari 有时不会立刻重绘地址栏/状态栏，替换节点比单纯改 content 更稳定。
  const clone = meta.cloneNode(true)
  meta.replaceWith(clone)
  return clone
}

// 动态修改 Safari / PWA 浏览器 chrome 颜色
function updateThemeColor(isDarkMode = document.documentElement.classList.contains('dark')) {
  const themeColor = isDarkMode ? THEME_CHROME_COLORS.dark : THEME_CHROME_COLORS.light
  const statusBarStyle = isDarkMode ? THEME_STATUS_BAR.dark : THEME_STATUS_BAR.light
  const colorScheme = isDarkMode ? 'dark' : 'light'
  
  forceMetaContent('theme-color', themeColor)
  forceMetaContent('apple-mobile-web-app-status-bar-style', statusBarStyle)
  forceMetaContent('color-scheme', colorScheme)

  document.documentElement.style.backgroundColor = themeColor
  document.documentElement.style.colorScheme = colorScheme
  document.documentElement.style.setProperty('--wavebypass-page-bg', themeColor)
  if (document.body) {
    document.body.style.backgroundColor = themeColor
    document.body.style.colorScheme = colorScheme
  }
  const appEl = document.getElementById('app')
  appEl?.style.setProperty('background-color', themeColor)
  appEl?.style.setProperty('color-scheme', colorScheme)

  window.dispatchEvent(new CustomEvent('wavebypass-theme-chrome-sync', {
    detail: { isDarkMode, themeColor },
  }))
}

window.__wavebypassSyncThemeChrome = updateThemeColor

function applyTheme() {
  const savedTheme = window.localStorage.getItem(THEME_STORAGE_KEY)
  const prefersDark = window.matchMedia('(prefers-color-scheme: dark)').matches

  const shouldUseDark = savedTheme ? savedTheme === 'dark' : prefersDark

  isDark.value = shouldUseDark
  document.documentElement.classList.toggle('dark', shouldUseDark)
  
  updateThemeColor(shouldUseDark)
}

applyTheme()

const searchQuery = ref('')
provide('searchQuery', searchQuery)

const searchExpanded = ref(false)
const searchInputRef = ref(null)

function toggleSearch() {
  searchExpanded.value = !searchExpanded.value
  if (searchExpanded.value) {
    nextTick(() => searchInputRef.value?.focus())
  } else {
    searchQuery.value = ''
  }
}

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
