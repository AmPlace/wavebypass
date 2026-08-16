<template>
  <footer class="bottom-player-dock fixed bottom-4 left-4 right-4 z-40 lg:bottom-7">
    <div class="mobile-player-shell relative mx-auto flex h-[72px] items-center justify-between gap-2 rounded-[18px] border border-[var(--border)] bg-[var(--player-bg)] px-3 shadow-[0_12px_32px_rgba(0,0,0,0.12)] backdrop-blur-[12px] backdrop-saturate-110 dark:shadow-[0_14px_36px_rgba(0,0,0,0.34)] sm:px-5 lg:h-24 lg:rounded-[24px]">
      <section class="mobile-player-info flex min-w-0 basis-[30%] cursor-pointer items-center gap-2 lg:basis-[42%] lg:gap-3" @click="playerStore.expandPlayer()">
        <img
          class="mobile-player-logo size-11 shrink-0 rounded-[10px] border border-[var(--border)] bg-[var(--surface)] object-contain p-1 lg:size-12 lg:rounded-xl"
          :src="currentLogoUrl"
          :alt="currentStationName"
          @error="useDefaultLogo"
        />
        <div ref="nameWrapperRef" class="min-w-0 overflow-hidden">
          <p
            ref="nameRef"
            class="mobile-player-title whitespace-nowrap text-sm font-semibold text-[var(--text-primary)]"
            :class="{ 'marquee': isNameOverflow }"
          >
            {{ currentStationName }}
          </p>
          <p
            ref="statusRef"
            class="mobile-player-status mt-1 whitespace-nowrap text-xs font-medium text-[var(--text-secondary)]"
            :class="{ 'marquee': isStatusOverflow }"
          >
            {{ statusText }}
          </p>
        </div>
      </section>

      <section class="mobile-player-controls absolute inset-0 flex items-center justify-center gap-4 pointer-events-none">
        <button type="button" class="dock-side-control pointer-events-auto" aria-label="上一个" disabled>
          <svg class="mobile-player-side-icon size-5" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><path d="M5.5 5.5h2.6v13H5.5zm4.8 6.5 8.2 6.1V5.9z"/></svg>
        </button>
        <button
          type="button"
          class="mobile-player-play-btn pointer-events-auto flex size-[52px] items-center justify-center rounded-full bg-neutral-950 text-white transition-all duration-200 ease-out hover:scale-[1.03] active:scale-95 dark:bg-white dark:text-black lg:size-14"
          :aria-label="isPlaying ? '暂停播放' : '开始播放'"
          @click="playerStore.togglePlay()"
        >
          <svg v-if="isPlaying" class="size-5" viewBox="0 0 24 24" fill="none" aria-hidden="true">
            <path d="M8 5v14M16 5v14" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" />
          </svg>
          <svg v-else class="ml-0.5 size-5" viewBox="0 0 24 24" fill="none" aria-hidden="true">
            <path d="M8 5.75v12.5c0 .72.78 1.17 1.4.8l10.1-6.25a.94.94 0 0 0 0-1.6L9.4 4.95A.93.93 0 0 0 8 5.75Z" fill="currentColor" />
          </svg>
        </button>
        <button type="button" class="dock-side-control pointer-events-auto" aria-label="下一个" disabled>
          <svg class="mobile-player-side-icon size-5" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><path d="M15.9 5.5h2.6v13h-2.6zM5.5 18.1l8.2-6.1-8.2-6.1z"/></svg>
        </button>
      </section>

      <section class="mobile-player-actions flex basis-[30%] items-center justify-end gap-2 lg:basis-[36%] lg:gap-3">
        <button type="button" class="hidden h-9 rounded-full border border-[var(--border)] bg-[var(--surface)] px-4 text-xs font-semibold text-[var(--text-primary)] transition-colors hover:bg-[var(--surface-hover)] sm:inline-flex sm:items-center">
          LIVE
        </button>
        <svg class="hidden size-5 shrink-0 text-[var(--text-secondary)] sm:block" viewBox="0 0 24 24" fill="none" aria-hidden="true">
          <path d="M4 10v4a1 1 0 0 0 1 1h3l4.2 3.15A.5.5 0 0 0 13 17.75V6.25a.5.5 0 0 0-.8-.4L8 9H5a1 1 0 0 0-1 1Z" stroke="currentColor" stroke-width="1.8" stroke-linejoin="round" />
          <path d="M16 9a4 4 0 0 1 0 6M18.5 6.5a7.5 7.5 0 0 1 0 11" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" />
        </svg>
        <input
          class="mobile-player-volume dock-volume h-1 w-16 cursor-pointer appearance-none rounded-full bg-[var(--surface-strong)] outline-none transition-colors duration-200 sm:w-28"
          type="range"
          min="0"
          max="1"
          step="0.01"
          :value="volume"
          aria-label="音量"
          @input="playerStore.setVolume($event.target.value)"
        />
        <button type="button" class="mobile-player-list-btn dock-list-btn" aria-label="节目列表" @click="playerStore.expandPlayer()">
          <svg class="mobile-player-list-icon size-5" viewBox="0 0 24 24" fill="none" aria-hidden="true"><path d="M8 7h11M8 12h11M8 17h11M4 7h.01M4 12h.01M4 17h.01" stroke="currentColor" stroke-width="2" stroke-linecap="round"/></svg>
          <span class="hidden sm:inline">节目列表</span>
        </button>
      </section>
    </div>
  </footer>
</template>

<script setup>
import { computed, nextTick, ref, watch } from 'vue'
import { storeToRefs } from 'pinia'
import { usePlayerStore } from '../stores/player'
import { publicAsset } from '../publicAsset'

const playerStore = usePlayerStore()
const { currentStation, isPlaying, isLoading, volume, playbackError } = storeToRefs(playerStore)
const nameRef = ref(null)
const statusRef = ref(null)
const isNameOverflow = ref(false)
const isStatusOverflow = ref(false)
const DEFAULT_LOGO_URL = publicAsset('/logos/default.png')

function checkOverflow() {
  if (nameRef.value) {
    isNameOverflow.value = nameRef.value.scrollWidth > nameRef.value.parentElement.clientWidth
  }
  if (statusRef.value) {
    isStatusOverflow.value = statusRef.value.scrollWidth > statusRef.value.parentElement.clientWidth
  }
}

const displayIptvChannel = computed(() => playerStore.pendingIptvChannel || playerStore.currentIptvChannel)

function useDefaultLogo(event) {
  const img = event?.target
  if (!img || img.dataset.logoFallback === '1') return
  img.dataset.logoFallback = '1'
  img.src = DEFAULT_LOGO_URL
}

watch([currentStation, playbackError, isLoading, () => displayIptvChannel.value], () => nextTick(checkOverflow))

const currentStationName = computed(() => {
  if (displayIptvChannel.value) {
    return displayIptvChannel.value.name
  }
  return playerStore.stationMap[currentStation.value]?.name || currentStation.value || '未选择频道'
})

const currentLogoUrl = computed(() => {
  if (displayIptvChannel.value?.logo_url) return displayIptvChannel.value.logo_url
  return playerStore.stationMap[currentStation.value]?.logoUrl || DEFAULT_LOGO_URL
})

const statusText = computed(() => {
  if (playbackError.value) {
    return playbackError.value
  }

  if (isLoading.value) {
    return '正在连接'
  }

  if (displayIptvChannel.value) {
    const prog = playerStore.currentEpgProgram
    return prog?.title || displayIptvChannel.value.group_name || 'IPTV'
  }

  return 'WaveFlow'
})
</script>

<style scoped>
.marquee {
  animation: marquee 8s linear infinite;
  padding-right: 2rem;
}
@keyframes marquee {
  0%   { transform: translateX(0); }
  20%  { transform: translateX(0); }
  80%  { transform: translateX(-50%); }
  100% { transform: translateX(-50%); }
}
</style>
