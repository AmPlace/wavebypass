<template>
  <div
    ref="scrollRef"
    class="app-root h-dvh overflow-y-auto font-sans text-[var(--text-primary)] antialiased transition-colors duration-300"
    :class="{ 'desktop-shell': hasDesktopShell, 'sidebar-collapsed': sidebarCollapsed }"
  >
    <aside
      v-if="showAppShell"
      class="app-sidebar fixed bottom-0 left-0 top-0 z-40 hidden border-r border-[var(--border)] bg-[var(--sidebar-bg)] px-3 py-6 backdrop-blur-[10px] backdrop-saturate-110 lg:flex lg:flex-col"
    >
      <div class="sidebar-header relative mb-8 h-10">
        <button
          type="button"
          class="sidebar-brand absolute left-3 top-0 flex h-10 min-w-0 items-center gap-4 text-left"
          :tabindex="sidebarCollapsed ? -1 : 0"
          aria-label="WaveFlow 首页"
          @click="router.push('/')"
        >
          <span class="flex size-10 shrink-0 items-center justify-center rounded-2xl border border-[var(--border)] bg-[var(--surface)] text-[var(--text-primary)]">
            <svg class="size-6" viewBox="0 0 24 24" fill="none" aria-hidden="true"><path d="m12 3 8 4.5-8 4.5-8-4.5L12 3Zm8 9-8 4.5L4 12m16 4.5L12 21l-8-4.5" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/></svg>
          </span>
          <span class="truncate text-base font-semibold tracking-normal">WaveFlow</span>
        </button>
      </div>

      <button
        type="button"
        class="sidebar-toggle flex size-10 shrink-0 items-center justify-center rounded-2xl border border-transparent text-[var(--text-secondary)] hover:bg-[var(--surface-hover)] hover:text-[var(--text-primary)]"
        :title="sidebarCollapsed ? '展开侧边栏' : '折叠侧边栏'"
        :aria-label="sidebarCollapsed ? '展开侧边栏' : '折叠侧边栏'"
        @click="toggleSidebar"
      >
        <svg
          class="size-6 transition-transform duration-300"
          :class="{ 'rotate-180': sidebarCollapsed }"
          viewBox="0 0 24 24"
          fill="none"
          aria-hidden="true"
        >
          <path d="M15 6 9 12l6 6" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/>
        </svg>
      </button>

      <nav class="flex flex-1 flex-col gap-1">
        <button
          v-for="item in primaryNavItems"
          :key="item.label"
          type="button"
          class="nav-item flex h-14 items-center gap-4 rounded-2xl border px-3 text-base font-medium transition-all duration-300 ease-out"
          :class="[navItemClass(item), justActivatedLabel === item.label ? 'nav-item-just-activated' : '']"
          :title="sidebarCollapsed ? item.label : undefined"
          :aria-current="item.active ? 'page' : undefined"
          @click="activateNavItem(item)"
        >
          <svg v-if="item.icon === 'home'" class="size-6 shrink-0" viewBox="0 0 24 24" fill="none" aria-hidden="true"><path d="m4 10 8-6 8 6v9a1 1 0 0 1-1 1h-5v-6h-4v6H5a1 1 0 0 1-1-1v-9Z" stroke="currentColor" stroke-width="1.8" stroke-linejoin="round"/></svg>
          <svg v-else-if="item.icon === 'tv'" class="size-6 shrink-0" viewBox="0 0 24 24" fill="none" aria-hidden="true"><rect x="4" y="6" width="16" height="12" rx="2" stroke="currentColor" stroke-width="1.8"/><path d="M9 3.5 12 6l3-2.5" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/></svg>
          <svg v-else-if="item.icon === 'star'" class="size-6 shrink-0" viewBox="0 0 24 24" fill="none" aria-hidden="true"><path d="m12 4 2.35 4.76 5.25.76-3.8 3.7.9 5.23L12 15.98l-4.7 2.47.9-5.23-3.8-3.7 5.25-.76L12 4Z" stroke="currentColor" stroke-width="1.8" stroke-linejoin="round"/></svg>
          <svg v-else-if="item.icon === 'calendar'" class="size-6 shrink-0" viewBox="0 0 24 24" fill="none" aria-hidden="true"><rect x="4" y="5.5" width="16" height="15" rx="2" stroke="currentColor" stroke-width="1.8"/><path d="M8 3.5v4M16 3.5v4M4 10h16" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/></svg>
          <svg v-else-if="item.icon === 'clock'" class="size-6 shrink-0" viewBox="0 0 24 24" fill="none" aria-hidden="true"><circle cx="12" cy="12" r="8" stroke="currentColor" stroke-width="1.8"/><path d="M12 7.5v5l3 1.8" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/></svg>
          <span class="nav-label truncate">{{ item.label }}</span>
        </button>

        <div class="my-4 h-px bg-[var(--border)]"></div>

        <button
          v-for="item in secondaryNavItems"
          :key="item.label"
          type="button"
          class="nav-item flex h-14 items-center gap-4 rounded-2xl border px-3 text-base font-medium transition-all duration-300 ease-out"
          :class="[navItemClass(item), justActivatedLabel === item.label ? 'nav-item-just-activated' : '']"
          :title="sidebarCollapsed ? item.label : undefined"
          :aria-current="item.active ? 'page' : undefined"
          @click="activateNavItem(item)"
        >
          <svg v-if="item.icon === 'layers'" class="size-6 shrink-0" viewBox="0 0 24 24" fill="none" aria-hidden="true"><path d="M4 8.4 12 4l8 4.4-8 4.4L4 8.4Z" stroke="currentColor" stroke-width="1.8" stroke-linejoin="round"/><path d="M4 12.2 12 16.6l8-4.4M4 16l8 4.4L20 16" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/></svg>
          <svg v-else-if="item.icon === 'settings'" class="size-6 shrink-0" viewBox="0 0 24 24" fill="none" aria-hidden="true"><path d="M12.22 3h-.44a2 2 0 0 0-2 2v.18a2 2 0 0 1-1 1.73l-.43.25a2 2 0 0 1-2 0l-.15-.08a2 2 0 0 0-2.73.73l-.22.38a2 2 0 0 0 .73 2.73l.15.1a2 2 0 0 1 1 1.72v.51a2 2 0 0 1-1 1.74l-.15.09a2 2 0 0 0-.73 2.73l.22.38a2 2 0 0 0 2.73.73l.15-.08a2 2 0 0 1 2 0l.43.25a2 2 0 0 1 1 1.73V20a2 2 0 0 0 2 2h.44a2 2 0 0 0 2-2v-.18a2 2 0 0 1 1-1.73l.43-.25a2 2 0 0 1 2 0l.15.08a2 2 0 0 0 2.73-.73l.22-.39a2 2 0 0 0-.73-2.73l-.15-.08a2 2 0 0 1-1-1.74v-.5a2 2 0 0 1 1-1.74l.15-.09a2 2 0 0 0 .73-2.73l-.22-.38a2 2 0 0 0-2.73-.73l-.15.08a2 2 0 0 1-2 0l-.43-.25a2 2 0 0 1-1-1.73V5a2 2 0 0 0-2-2Z" stroke="currentColor" stroke-width="1.65"/><circle cx="12" cy="12" r="3" stroke="currentColor" stroke-width="1.65"/></svg>
          <svg v-else class="size-6 shrink-0" viewBox="0 0 24 24" fill="none" aria-hidden="true"><circle cx="12" cy="12" r="8" stroke="currentColor" stroke-width="1.8"/><path d="M12 11.5v5M12 8h.01" stroke="currentColor" stroke-width="2" stroke-linecap="round"/></svg>
          <span class="nav-label truncate">{{ item.label }}</span>
        </button>
      </nav>
    </aside>

    <div v-if="showAppShell" class="fixed inset-x-0 top-0 z-50 bg-[var(--bg)] lg:hidden">
      <div class="h-[env(safe-area-inset-top)]"></div>
      <div class="flex h-12 items-center justify-between px-4 sm:px-6">
        <div class="flex items-center rounded-full border border-[var(--border)] bg-[var(--bg-soft)]/70 p-0.5 text-xs font-medium shadow-sm shadow-black/[0.04] backdrop-blur-xl">
          <button
            type="button"
            class="rounded-full px-3 py-1.5 transition-all sm:px-4"
            :class="activeMode === 'radio' ? 'bg-neutral-950 text-white dark:bg-white dark:text-black' : 'text-[var(--text-secondary)] hover:text-[var(--text-primary)]'"
            @click="router.push('/')"
          >
            Radio
          </button>
          <button
            type="button"
            class="rounded-full px-3 py-1.5 transition-all sm:px-4"
            :class="activeMode === 'iptv' ? 'bg-neutral-950 text-white dark:bg-white dark:text-black' : 'text-[var(--text-secondary)] hover:text-[var(--text-primary)]'"
            @click="router.push('/iptv')"
          >
            TV
          </button>
        </div>
        <div class="flex items-center gap-2">
          <button v-show="activeMode === 'iptv'" type="button" class="mobile-action-btn" aria-label="订阅源" @click="router.push('/market')">
            <svg class="size-5" viewBox="0 0 24 24" fill="none"><path d="M4 8.4 12 4l8 4.4-8 4.4L4 8.4Z" stroke="currentColor" stroke-width="1.8" stroke-linejoin="round"/><path d="M4 12.2 12 16.6l8-4.4M4 16l8 4.4L20 16" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/></svg>
          </button>
          <button v-show="activeMode === 'iptv'" type="button" class="mobile-action-btn" aria-label="设置" @click="router.push('/admin')">
            <svg class="size-5" viewBox="0 0 24 24" fill="none"><path d="M12.22 2h-.44a2 2 0 0 0-2 2v.18a2 2 0 0 1-1 1.73l-.43.25a2 2 0 0 1-2 0l-.15-.08a2 2 0 0 0-2.73.73l-.22.38a2 2 0 0 0 .73 2.73l.15.1a2 2 0 0 1 1 1.72v.51a2 2 0 0 1-1 1.74l-.15.09a2 2 0 0 0-.73 2.73l.22.38a2 2 0 0 0 2.73.73l.15-.08a2 2 0 0 1 2 0l.43.25a2 2 0 0 1 1 1.73V20a2 2 0 0 0 2 2h.44a2 2 0 0 0 2-2v-.18a2 2 0 0 1 1-1.73l.43-.25a2 2 0 0 1 2 0l.15.08a2 2 0 0 0 2.73-.73l.22-.39a2 2 0 0 0-.73-2.73l-.15-.08a2 2 0 0 1-1-1.74v-.5a2 2 0 0 1 1-1.74l.15-.09a2 2 0 0 0 .73-2.73l-.22-.38a2 2 0 0 0-2.73-.73l-.15.08a2 2 0 0 1-2 0l-.43-.25a2 2 0 0 1-1-1.73V4a2 2 0 0 0-2-2z" stroke="currentColor" stroke-width="1.8"/><circle cx="12" cy="12" r="3" stroke="currentColor" stroke-width="1.8"/></svg>
          </button>
          <div class="relative flex items-center rounded-full border border-[var(--border)] bg-[var(--bg-soft)]/70 shadow-sm shadow-black/[0.04] backdrop-blur-xl transition-all duration-300 ease-out" :class="searchExpanded ? 'w-48 sm:w-56' : 'size-10'">
            <button type="button" class="flex size-10 shrink-0 items-center justify-center text-[var(--text-secondary)] transition-colors hover:text-[var(--text-primary)]" aria-label="搜索" @click="toggleSearch">
              <svg class="size-5" viewBox="0 0 24 24" fill="none" aria-hidden="true"><circle cx="11" cy="11" r="7" stroke="currentColor" stroke-width="1.8" /><path d="M16.5 16.5L21 21" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" /></svg>
            </button>
            <input ref="searchInputRef" v-model="searchQuery" type="text" placeholder="搜索频道、节目" class="h-full w-full bg-transparent pr-3 text-sm text-[var(--text-primary)] outline-none placeholder:text-[var(--text-tertiary)]" :class="searchExpanded ? 'opacity-100' : 'pointer-events-none opacity-0'" @blur="onSearchBlur" />
          </div>
          <button type="button" class="mobile-action-btn" :aria-label="isDark ? '切换到浅色模式' : '切换到深色模式'" @click="toggleTheme">
            <svg v-if="isDark" class="size-5" viewBox="0 0 24 24" fill="none" aria-hidden="true"><path d="M12 3v2M12 19v2M4.93 4.93l1.41 1.41M17.66 17.66l1.41 1.41M3 12h2M19 12h2M4.93 19.07l1.41-1.41M17.66 6.34l1.41-1.41" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/><circle cx="12" cy="12" r="4" stroke="currentColor" stroke-width="1.8"/></svg>
            <svg v-else class="size-5" viewBox="0 0 24 24" fill="none" aria-hidden="true"><path d="M20.5 14.4A7.7 7.7 0 0 1 9.6 3.5 8.5 8.5 0 1 0 20.5 14.4Z" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/></svg>
          </button>
        </div>
      </div>
    </div>

    <div v-if="showAppShell" class="fixed right-10 top-6 z-30 hidden items-center gap-3 lg:flex">
      <div
        class="flex h-11 items-center overflow-hidden rounded-full border border-[var(--border)] bg-[var(--surface)] text-[var(--text-secondary)] backdrop-blur-[12px] backdrop-saturate-110 transition-all duration-300 ease-out"
        :class="searchExpanded ? 'w-[260px] px-1' : 'w-11 px-0'"
      >
        <button
          type="button"
          class="flex size-11 shrink-0 items-center justify-center transition-colors hover:text-[var(--text-primary)]"
          aria-label="搜索"
          @click="toggleSearch"
        >
          <svg class="size-5" viewBox="0 0 24 24" fill="none" aria-hidden="true"><circle cx="11" cy="11" r="7" stroke="currentColor" stroke-width="1.8" /><path d="M16.5 16.5L21 21" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" /></svg>
        </button>
        <input
          ref="desktopSearchInputRef"
          v-model="searchQuery"
          type="text"
          placeholder="搜索频道、节目"
          class="min-w-0 flex-1 bg-transparent pr-3 text-sm text-[var(--text-primary)] outline-none placeholder:text-[var(--text-tertiary)]"
          :class="searchExpanded ? 'opacity-100' : 'pointer-events-none opacity-0'"
          @blur="onSearchBlur"
        />
      </div>

      <button type="button" class="desktop-action-btn" aria-label="最近播放">
        <svg class="size-5" viewBox="0 0 24 24" fill="none"><circle cx="12" cy="12" r="8" stroke="currentColor" stroke-width="1.8"/><path d="M12 7.5v5l3.2 1.8" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/></svg>
      </button>
      <button type="button" class="desktop-action-btn" aria-label="通知">
        <svg class="size-5" viewBox="0 0 24 24" fill="none"><path d="M18 9.8a6 6 0 1 0-12 0c0 7.2-2.4 7.2-2.4 7.2h16.8S18 17 18 9.8Z" stroke="currentColor" stroke-width="1.8" stroke-linejoin="round"/><path d="M9.5 20a2.8 2.8 0 0 0 5 0" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/></svg>
      </button>
      <button type="button" class="desktop-action-btn" :aria-label="isDark ? '切换到浅色模式' : '切换到深色模式'" @click="toggleTheme">
        <svg v-if="isDark" class="size-5" viewBox="0 0 24 24" fill="none" aria-hidden="true"><path d="M12 3v2M12 19v2M4.93 4.93l1.41 1.41M17.66 17.66l1.41 1.41M3 12h2M19 12h2M4.93 19.07l1.41-1.41M17.66 6.34l1.41-1.41" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/><circle cx="12" cy="12" r="4" stroke="currentColor" stroke-width="1.8"/></svg>
        <svg v-else class="size-5" viewBox="0 0 24 24" fill="none" aria-hidden="true"><path d="M20.5 14.4A7.7 7.7 0 0 1 9.6 3.5 8.5 8.5 0 1 0 20.5 14.4Z" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/></svg>
      </button>
      <button type="button" class="desktop-action-btn" aria-label="用户">
        <svg class="size-5" viewBox="0 0 24 24" fill="none"><circle cx="12" cy="8.5" r="3.5" stroke="currentColor" stroke-width="1.8"/><path d="M5.5 20a6.5 6.5 0 0 1 13 0" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/></svg>
      </button>
    </div>

    <div class="app-main">
      <router-view />
    </div>

    <BottomPlayer v-if="showAppShell" />

    <AudioEngine v-if="showAppShell" />

    <FullPlayer v-if="showAppShell" />

    <ToastHost />
  </div>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, provide, ref, nextTick, watch } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { storeToRefs } from 'pinia'
import { usePlayerStore } from './stores/player'
import BottomPlayer from './components/BottomPlayer.vue'
import AudioEngine from './components/AudioEngine.vue'
import FullPlayer from './components/FullPlayer.vue'
import ToastHost from './components/ToastHost.vue'

const THEME_STORAGE_KEY = 'waveflow-theme'
const isDark = ref(false)
let mediaQuery = null

const scrollRef = ref(null)
provide('scrollRef', scrollRef)

const playerStore = usePlayerStore()
const { activeMode } = storeToRefs(playerStore)
const router = useRouter()
const route = useRoute()
const showAppShell = computed(() => !route.meta.authPage)
const hasDesktopShell = computed(() => showAppShell.value)
const SIDEBAR_STORAGE_KEY = 'waveflow-sidebar-collapsed'
const sidebarCollapsed = ref(window.localStorage.getItem(SIDEBAR_STORAGE_KEY) === '1')
const justActivatedLabel = ref('')
watch(sidebarCollapsed, (value) => {
  window.localStorage.setItem(SIDEBAR_STORAGE_KEY, value ? '1' : '0')
})
function toggleSidebar() {
  sidebarCollapsed.value = !sidebarCollapsed.value
}
const primaryNavItems = computed(() => [
  { label: '首页', icon: 'home', route: '/', active: route.path === '/' },
  { label: '直播', icon: 'tv', route: '/iptv', active: route.path === '/iptv' },
  { label: '收藏', icon: 'star', route: '/iptv', active: false },
  { label: '节目单', icon: 'calendar', route: '/admin/epg', active: route.path === '/admin/epg' },
  { label: '回看', icon: 'clock', route: '/iptv', active: false },
])
const secondaryNavItems = computed(() => [
  { label: 'Market', icon: 'layers', route: '/market', active: route.path === '/market' },
  { label: '设置', icon: 'settings', route: '/admin', active: route.path === '/admin' },
  { label: '关于', icon: 'info', route: '', active: false },
])
const THEME_CHROME_COLORS = {
  light: '#F6F7F8',
  dark: '#090A0B',
}
const THEME_STATUS_BAR = {
  light: 'default',
  dark: 'default',
}

watch(() => route.path, (path) => {
  playerStore.setActiveMode(path.startsWith('/iptv') || path.startsWith('/admin') || path.startsWith('/market') ? 'iptv' : 'radio')
}, { immediate: true })

watch(showAppShell, (visible) => {
  if (!visible) playerStore.stopAndClearPlayback()
}, { immediate: true, flush: 'sync' })

function forceMetaContent(name, content) {
  const old = document.querySelector(`meta[name="${name}"]`)
  if (old) {
    if (old.content !== content) old.content = content
    return old
  }
  const meta = document.createElement('meta')
  meta.name = name
  meta.content = content
  document.head.appendChild(meta)
  return meta
}

// 动态修改 Safari / PWA 浏览器 chrome 颜色
function updateThemeColor(isDarkMode = document.documentElement.classList.contains('dark'), source = '', options = {}) {
  const themeColor = isDarkMode ? THEME_CHROME_COLORS.dark : THEME_CHROME_COLORS.light
  const statusBarStyle = isDarkMode ? THEME_STATUS_BAR.dark : THEME_STATUS_BAR.light
  const colorScheme = isDarkMode ? 'dark' : 'light'
  const refreshChrome = options.refreshChrome !== false

  console.log('[theme-sync]', {
    source,
    inputIsDark: isDarkMode,
    htmlDark: document.documentElement.classList.contains('dark'),
    bodyDark: document.body.classList.contains('dark'),
    prefersDark: window.matchMedia('(prefers-color-scheme: dark)').matches,
    themeColor,
    colorScheme,
    metaBefore: [...document.querySelectorAll('meta[name="theme-color"]')].map(m => m.outerHTML),
  })

  forceMetaContent('theme-color', themeColor)
  forceMetaContent('apple-mobile-web-app-status-bar-style', statusBarStyle)
  forceMetaContent('color-scheme', colorScheme)

  console.log('[theme-sync-after]', {
    themeMetas: [...document.querySelectorAll('meta[name="theme-color"]')].map(m => m.outerHTML),
    colorSchemeMetas: [...document.querySelectorAll('meta[name="color-scheme"]')].map(m => m.outerHTML),
    htmlBg: getComputedStyle(document.documentElement).backgroundColor,
    bodyBg: getComputedStyle(document.body).backgroundColor,
    appBg: getComputedStyle(document.getElementById('app')).backgroundColor,
  })

  document.documentElement.style.setProperty('background-color', themeColor, 'important')
  document.documentElement.style.setProperty('color-scheme', colorScheme, 'important')
  document.documentElement.style.setProperty('--waveflow-page-bg', themeColor, 'important')
  if (document.body) {
    document.body.style.setProperty('background-color', themeColor, 'important')
    document.body.style.setProperty('color-scheme', colorScheme, 'important')
  }
  const appEl = document.getElementById('app')
  appEl?.style.setProperty('background-color', themeColor, 'important')
  appEl?.style.setProperty('color-scheme', colorScheme, 'important')

  window.dispatchEvent(new CustomEvent('waveflow-theme-chrome-sync', {
    detail: { isDarkMode, themeColor, refreshChrome, source },
  }))
}

window.__waveflowSyncThemeChrome = updateThemeColor

function applyTheme(source = 'applyTheme', options = {}) {
  const savedTheme = window.localStorage.getItem(THEME_STORAGE_KEY)
  const prefersDark = window.matchMedia('(prefers-color-scheme: dark)').matches

  const shouldUseDark = savedTheme ? savedTheme === 'dark' : prefersDark

  isDark.value = shouldUseDark
  document.documentElement.classList.toggle('dark', shouldUseDark)
  
  updateThemeColor(shouldUseDark, `${source}:${savedTheme ? 'manual' : 'system'}`, options)
}

applyTheme()

const searchQuery = ref('')
provide('searchQuery', searchQuery)

const searchExpanded = ref(false)
const searchInputRef = ref(null)
const desktopSearchInputRef = ref(null)

function navItemClass(item) {
  if (item.active) {
    return 'border-[var(--border-strong)] bg-[var(--surface-active)] text-[var(--text-primary)]'
  }
  return 'border-transparent text-[var(--text-secondary)] hover:bg-[var(--surface-hover)] hover:text-[var(--text-primary)]'
}

function activateNavItem(item) {
  if (!item.route) return
  justActivatedLabel.value = item.label
  setTimeout(() => { justActivatedLabel.value = '' }, 350)
  router.push(item.route)
}

function toggleSearch() {
  searchExpanded.value = !searchExpanded.value
  if (searchExpanded.value) {
    nextTick(() => {
      searchInputRef.value?.focus()
      desktopSearchInputRef.value?.focus()
    })
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
  applyTheme('toggleTheme')
}

function handleSystemThemeChange(e) {
  window.localStorage.removeItem(THEME_STORAGE_KEY)
  applyTheme('systemThemeChange')
}

function handleVisibilityChange() {
  if (document.visibilityState === 'visible') {
    applyTheme('visibilitychange', { refreshChrome: false })
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
