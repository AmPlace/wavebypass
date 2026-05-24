<template>
  <main class="mx-auto flex min-h-screen w-full max-w-5xl flex-col px-5 pt-[calc(env(safe-area-inset-top)+3.5rem)] pb-36 sm:px-8">

    <header class="mb-6 flex items-center justify-between">
      <div class="flex items-center gap-3">
        <button
          type="button"
          class="flex size-8 items-center justify-center rounded-full text-neutral-500 transition-colors hover:bg-neutral-200/60 dark:hover:bg-neutral-700/60"
          @click="$router.push('/admin')"
        >
          <svg class="size-4" viewBox="0 0 24 24" fill="none"><path d="M19 12H5M12 5l-7 7 7 7" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg>
        </button>
        <h1 class="text-sm font-semibold text-neutral-800 dark:text-neutral-200">EPG 匹配状态</h1>
        <span class="text-xs text-neutral-400 dark:text-neutral-500">
          {{ filtered.length }} 个频道 / {{ stats.matched }} 已匹配 / {{ stats.unmatched }} 未匹配
        </span>
      </div>
      <div class="flex gap-2">
        <button
          type="button"
          class="rounded-full border border-neutral-200 bg-white/70 px-3 py-1.5 text-xs font-medium text-neutral-600 backdrop-blur-xl transition-all hover:scale-[1.03] active:scale-95 dark:border-neutral-700 dark:bg-neutral-800/70 dark:text-neutral-300"
          :class="filter === 'all' ? 'bg-black text-white dark:bg-white dark:text-black border-black dark:border-white' : ''"
          @click="filter = 'all'"
        >全部</button>
        <button
          type="button"
          class="rounded-full border border-neutral-200 bg-white/70 px-3 py-1.5 text-xs font-medium text-neutral-600 backdrop-blur-xl transition-all hover:scale-[1.03] active:scale-95 dark:border-neutral-700 dark:bg-neutral-800/70 dark:text-neutral-300"
          :class="filter === 'matched' ? 'bg-emerald-500 text-white border-emerald-500' : ''"
          @click="filter = 'matched'"
        >已匹配</button>
        <button
          type="button"
          class="rounded-full border border-neutral-200 bg-white/70 px-3 py-1.5 text-xs font-medium text-neutral-600 backdrop-blur-xl transition-all hover:scale-[1.03] active:scale-95 dark:border-neutral-700 dark:bg-neutral-800/70 dark:text-neutral-300"
          :class="filter === 'unmatched' ? 'bg-red-400 text-white border-red-400' : ''"
          @click="filter = 'unmatched'"
        >未匹配</button>
        <button
          type="button"
          class="rounded-full border border-neutral-200 bg-white/70 px-3 py-1.5 text-xs font-medium text-neutral-600 backdrop-blur-xl transition-all hover:scale-[1.03] active:scale-95 dark:border-neutral-700 dark:bg-neutral-800/70 dark:text-neutral-300"
          :class="filter === 'ambiguous' ? 'bg-amber-400 text-white border-amber-400' : ''"
          @click="filter = 'ambiguous'"
        >冲突</button>
      </div>
    </header>

    <div class="w-full overflow-x-auto">
      <table class="w-full text-left text-xs">
        <thead>
          <tr class="border-b border-neutral-200 text-neutral-400 dark:border-neutral-700 dark:text-neutral-500">
            <th class="py-2 pr-4 font-medium">频道</th>
            <th class="py-2 pr-4 font-medium">canonical_key</th>
            <th class="py-2 pr-4 font-medium">EPG ID</th>
            <th class="py-2 pr-4 font-medium">匹配方式</th>
            <th class="py-2 pr-4 font-medium">置信度</th>
            <th class="py-2 pr-4 font-medium">状态</th>
            <th class="py-2 pr-4 font-medium">当前节目</th>
          </tr>
        </thead>
        <tbody>
          <tr
            v-for="row in filtered"
            :key="row.name"
            class="border-b border-neutral-100 transition-colors hover:bg-neutral-50 dark:border-neutral-800 dark:hover:bg-neutral-800/50"
          >
            <td class="py-2.5 pr-4 font-medium text-neutral-800 dark:text-neutral-200">{{ row.name }}</td>
            <td class="py-2.5 pr-4 font-mono text-neutral-500">{{ row.canonical_key }}</td>
            <td class="py-2.5 pr-4 font-mono text-neutral-500">{{ row.epg_channel_id || '-' }}</td>
            <td class="py-2.5 pr-4 text-neutral-500">{{ row.match_type || '-' }}</td>
            <td class="py-2.5 pr-4">{{ row.confidence || '-' }}</td>
            <td class="py-2.5 pr-4">
              <span
                class="rounded-full px-1.5 py-0.5 text-[0.6rem] font-medium"
                :class="{
                  'bg-emerald-100 text-emerald-700 dark:bg-emerald-900/30 dark:text-emerald-400': row.match_status === 'matched',
                  'bg-red-100 text-red-600 dark:bg-red-900/30 dark:text-red-400': row.match_status === 'unmatched',
                  'bg-amber-100 text-amber-700 dark:bg-amber-900/30 dark:text-amber-400': row.match_status === 'ambiguous',
                }"
              >{{ row.match_status }}</span>
            </td>
            <td class="py-2.5 pr-4 text-neutral-500">{{ row.current_program || '-' }}</td>
          </tr>
        </tbody>
      </table>
    </div>
  </main>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'

const FILTER_ALL = 'all'

const channels = ref([])
const filter = ref(FILTER_ALL)

const stats = computed(() => ({
  matched: channels.value.filter(c => c.match_status === 'matched').length,
  unmatched: channels.value.filter(c => c.match_status === 'unmatched').length,
  ambiguous: channels.value.filter(c => c.match_status === 'ambiguous').length,
}))

const filtered = computed(() => {
  if (filter.value === FILTER_ALL) return channels.value
  return channels.value.filter(c => c.match_status === filter.value)
})

onMounted(async () => {
  try {
    const API_BASE = import.meta.env.VITE_API_BASE_URL || ''

    // 拉匹配状态
    const [statusRes, channelsRes] = await Promise.all([
      fetch(`${API_BASE}/api/iptv/epg/match-status`),
      fetch(`${API_BASE}/api/iptv/channels`),
    ])
    const statusList = statusRes.ok ? await statusRes.json() : []
    const channelsData = channelsRes.ok ? await channelsRes.json() : { channels: [] }

    // 批量拉当前节目
    const keys = statusList.map(s => s.canonical_key).filter(Boolean)
    let epgData = {}
    if (keys.length) {
      const res = await fetch(`${API_BASE}/api/iptv/epg/batch-current`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ canonical_keys: keys }),
        signal: AbortSignal.timeout(8000),
      })
      if (res.ok) epgData = await res.json()
    }

    const statusMap = {}
    for (const s of statusList) statusMap[s.canonical_key] = s

    const result = []
    for (const ch of channelsData.channels || []) {
      const key = ch.canonical_key
      if (!key) continue
      const s = statusMap[key] || {}
      const epg = epgData[key]
      result.push({
        name: ch.name,
        canonical_key: key,
        epg_channel_id: s.epg_channel_id || '',
        match_type: s.match_type || '',
        confidence: s.confidence || 0,
        match_status: s.status || 'unmatched',
        current_program: epg?.current?.title || '',
      })
    }
    channels.value = result
  } catch (e) {
    console.error('加载 EPG 状态失败:', e)
  }
})
</script>
