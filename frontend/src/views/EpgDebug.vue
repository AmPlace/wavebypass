<template>
  <main class="mx-auto flex min-h-screen w-full max-w-7xl flex-col px-5 pb-36 pt-[calc(env(safe-area-inset-top)+4rem)] sm:px-8 lg:px-10 lg:pt-6">
    <header class="mb-7 flex flex-col gap-5 lg:pr-[300px]">
      <div class="flex flex-wrap items-start justify-between gap-4">
        <div class="flex min-w-0 items-center gap-3">
          <button
            type="button"
            class="flex size-10 shrink-0 items-center justify-center rounded-full border border-[var(--border)] bg-[var(--surface)] text-[var(--text-secondary)] transition-colors hover:bg-[var(--surface-hover)] hover:text-[var(--text-primary)]"
            aria-label="返回设置"
            @click="$router.push('/admin')"
          >
            <svg class="size-5" viewBox="0 0 24 24" fill="none"><path d="M19 12H5M12 5l-7 7 7 7" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg>
          </button>
          <div class="min-w-0">
            <h1 class="truncate text-lg font-semibold leading-tight text-[var(--text-primary)]">EPG 匹配状态</h1>
            <p class="mt-1 text-sm text-[var(--text-secondary)]">
              {{ filtered.length }} 个频道 / {{ stats.matched }} 已匹配 / {{ stats.unmatched }} 未匹配
            </p>
          </div>
        </div>

        <div class="scrollbar-hide flex max-w-full gap-2 overflow-x-auto pb-1">
          <button
            v-for="option in filterOptions"
            :key="option.key"
            type="button"
            class="h-10 shrink-0 rounded-full border px-4 text-sm font-medium transition-colors"
            :class="filterClass(option.key)"
            @click="filter = option.key"
          >
            {{ option.label }}
          </button>
        </div>
      </div>

      <section class="grid gap-3 sm:grid-cols-3">
        <div class="rounded-2xl border border-[var(--border)] bg-[var(--surface)] px-4 py-3">
          <p class="text-xs font-medium text-[var(--text-tertiary)]">已匹配</p>
          <div class="mt-2 flex items-end justify-between gap-3">
            <span class="text-2xl font-semibold leading-none text-[var(--text-primary)]">{{ stats.matched }}</span>
            <span class="text-xs text-[var(--text-secondary)]">{{ matchRate }}%</span>
          </div>
        </div>
        <div class="rounded-2xl border border-[var(--border)] bg-[var(--surface)] px-4 py-3">
          <p class="text-xs font-medium text-[var(--text-tertiary)]">未匹配</p>
          <div class="mt-2 flex items-end justify-between gap-3">
            <span class="text-2xl font-semibold leading-none text-[var(--text-primary)]">{{ stats.unmatched }}</span>
            <span class="text-xs text-[var(--text-secondary)]">待处理</span>
          </div>
        </div>
        <div class="rounded-2xl border border-[var(--border)] bg-[var(--surface)] px-4 py-3">
          <p class="text-xs font-medium text-[var(--text-tertiary)]">冲突</p>
          <div class="mt-2 flex items-end justify-between gap-3">
            <span class="text-2xl font-semibold leading-none text-[var(--text-primary)]">{{ stats.ambiguous }}</span>
            <span class="text-xs text-[var(--text-secondary)]">需确认</span>
          </div>
        </div>
      </section>
    </header>

    <section class="overflow-hidden rounded-3xl border border-[var(--border)] bg-[var(--bg-soft)]/70">
      <div class="border-b border-[var(--border)] px-5 py-4">
        <div class="flex items-center justify-between gap-4">
          <div class="min-w-0">
            <h2 class="truncate text-sm font-semibold text-[var(--text-primary)]">频道映射</h2>
            <p class="mt-1 text-xs text-[var(--text-tertiary)]">canonical key、EPG ID 和当前节目来自现有匹配状态接口</p>
          </div>
          <span class="shrink-0 rounded-full border border-[var(--border)] bg-[var(--surface)] px-3 py-1 text-xs font-medium text-[var(--text-secondary)]">
            {{ filterLabel }}
          </span>
        </div>
      </div>

      <div class="w-full overflow-x-auto">
        <table class="w-full min-w-[960px] text-left text-xs">
          <thead>
            <tr class="border-b border-[var(--border)] text-[var(--text-tertiary)]">
              <th class="px-5 py-3 font-medium">频道</th>
              <th class="px-4 py-3 font-medium">canonical_key</th>
              <th class="px-4 py-3 font-medium">EPG ID</th>
              <th class="px-4 py-3 font-medium">匹配方式</th>
              <th class="px-4 py-3 font-medium">置信度</th>
              <th class="px-4 py-3 font-medium">状态</th>
              <th class="px-4 py-3 font-medium">当前节目</th>
            </tr>
          </thead>
          <tbody>
            <tr
              v-for="row in filtered"
              :key="row.name"
              class="border-b border-[var(--border)] transition-colors last:border-b-0 hover:bg-[var(--surface-hover)]"
            >
              <td class="px-5 py-3.5 font-medium text-[var(--text-primary)]">{{ row.name }}</td>
              <td class="px-4 py-3.5 font-mono text-[var(--text-secondary)]">{{ row.canonical_key }}</td>
              <td class="px-4 py-3.5 font-mono text-[var(--text-secondary)]">{{ row.epg_channel_id || '-' }}</td>
              <td class="px-4 py-3.5 text-[var(--text-secondary)]">{{ row.match_type || '-' }}</td>
              <td class="px-4 py-3.5 text-[var(--text-secondary)]">{{ confidenceText(row.confidence) }}</td>
              <td class="px-4 py-3.5">
                <span class="inline-flex h-7 items-center rounded-full border px-2.5 text-[0.7rem] font-medium" :class="statusClass(row.match_status)">
                  {{ statusLabel(row.match_status) }}
                </span>
              </td>
              <td class="max-w-[260px] truncate px-4 py-3.5 text-[var(--text-secondary)]">{{ row.current_program || '-' }}</td>
            </tr>
          </tbody>
        </table>
      </div>
    </section>
  </main>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { API_BASE } from '../apiBase'

const FILTER_ALL = 'all'

const channels = ref([])
const filter = ref(FILTER_ALL)
const filterOptions = [
  { key: 'all', label: '全部' },
  { key: 'matched', label: '已匹配' },
  { key: 'unmatched', label: '未匹配' },
  { key: 'ambiguous', label: '冲突' },
]

const stats = computed(() => ({
  matched: channels.value.filter(c => c.match_status === 'matched').length,
  unmatched: channels.value.filter(c => c.match_status === 'unmatched').length,
  ambiguous: channels.value.filter(c => c.match_status === 'ambiguous').length,
}))

const filtered = computed(() => {
  if (filter.value === FILTER_ALL) return channels.value
  return channels.value.filter(c => c.match_status === filter.value)
})

const matchRate = computed(() => {
  if (!channels.value.length) return 0
  return Math.round((stats.value.matched / channels.value.length) * 100)
})

const filterLabel = computed(() => filterOptions.find(option => option.key === filter.value)?.label || '全部')

function filterClass(key) {
  if (filter.value === key) return 'border-black bg-black text-white dark:border-white dark:bg-white dark:text-black'
  return 'border-[var(--border)] bg-[var(--surface)] text-[var(--text-secondary)] hover:bg-[var(--surface-hover)] hover:text-[var(--text-primary)]'
}

function statusLabel(status) {
  if (status === 'matched') return '已匹配'
  if (status === 'ambiguous') return '冲突'
  return '未匹配'
}

function statusClass(status) {
  if (status === 'matched') return 'border-[var(--border-strong)] bg-[var(--surface-active)] text-[var(--text-primary)]'
  if (status === 'ambiguous') return 'border-[var(--border-strong)] bg-[var(--surface-strong)] text-[var(--text-primary)]'
  return 'border-[var(--border)] bg-[var(--surface)] text-[var(--text-secondary)]'
}

function confidenceText(value) {
  return value || value === 0 ? value : '-'
}

onMounted(async () => {
  try {
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
