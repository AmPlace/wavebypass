<template>
  <main class="mx-auto flex min-h-screen w-full max-w-4xl flex-col px-5 pt-[calc(env(safe-area-inset-top)+3.5rem)] pb-36 sm:px-8">

    <header class="mb-6 flex items-center justify-between">
      <div class="flex items-center gap-3">
        <button
          type="button"
          class="flex size-8 items-center justify-center rounded-full text-neutral-500 transition-colors hover:bg-neutral-200/60 dark:hover:bg-neutral-700/60"
          @click="$router.push('/iptv')"
        >
          <svg class="size-4" viewBox="0 0 24 24" fill="none"><path d="M19 12H5M12 5l-7 7 7 7" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg>
        </button>
        <h1 class="text-sm font-semibold text-neutral-800 dark:text-neutral-200">订阅管理</h1>
      </div>
      <div class="flex items-center gap-2">
        <button
          type="button"
          class="rounded-full border border-neutral-200 bg-white/70 px-3 py-1.5 text-xs font-medium text-neutral-600 backdrop-blur-xl transition-all hover:scale-[1.03] active:scale-95 dark:border-neutral-700 dark:bg-neutral-800/70 dark:text-neutral-300"
          :disabled="testRunning"
          @click="handleTestAll"
        >
          {{ testRunning ? `测速中 ${testProgress.tested}/${testProgress.total}` : '全部测速' }}
        </button>
        <a
          :href="exportUrl"
          target="_blank"
          class="rounded-full bg-neutral-950 px-3 py-1.5 text-xs font-medium text-white transition-all hover:scale-[1.03] active:scale-95 dark:bg-white dark:text-black"
        >
          导出 M3U8
        </a>
      </div>
    </header>

    <!-- 测速进度条 -->
    <div v-if="testRunning" class="mb-4 h-1.5 overflow-hidden rounded-full bg-neutral-200 dark:bg-neutral-700">
      <div
        class="h-full rounded-full bg-emerald-500 transition-all duration-300"
        :style="{ width: `${(testProgress.tested / testProgress.total * 100) || 0}%` }"
      ></div>
    </div>

    <div v-if="testRunning" class="mb-4 flex gap-4 text-xs text-neutral-400 dark:text-neutral-500">
      <span>可用: {{ testProgress.working }}</span>
      <span>不可用: {{ testProgress.failed }}</span>
      <span>剩余: {{ testProgress.total - testProgress.tested }}</span>
    </div>

    <!-- 添加订阅 -->
    <div class="mb-6 flex gap-2">
      <input
        v-model="addUrl"
        type="url"
        placeholder="输入 M3U/M3U8 订阅链接…"
        class="min-w-0 flex-1 rounded-xl border border-neutral-200 bg-white/70 px-4 py-2.5 text-sm text-neutral-800 outline-none backdrop-blur-xl transition-colors focus:border-neutral-400 dark:border-neutral-600 dark:bg-neutral-800/70 dark:text-neutral-200 dark:focus:border-neutral-500"
        @keydown.enter="handleAdd"
      />
      <button
        type="button"
        class="shrink-0 rounded-xl bg-neutral-950 px-4 py-2.5 text-sm font-medium text-white transition-all hover:scale-[1.03] active:scale-95 disabled:opacity-50 dark:bg-white dark:text-black"
        :disabled="!addUrl.trim() || addLoading"
        @click="handleAdd"
      >
        {{ addLoading ? '解析中…' : '添加' }}
      </button>
    </div>

    <p v-if="addError" class="mb-4 text-xs text-red-500">{{ addError }}</p>

    <!-- 订阅列表 -->
    <div class="space-y-3">
      <div
        v-for="sub in subscriptions"
        :key="sub.id"
        class="rounded-2xl border border-black/5 bg-white/80 p-4 shadow-sm backdrop-blur-xl dark:border-white/10 dark:bg-neutral-800/50"
      >
        <div class="mb-2 flex items-start justify-between">
          <div class="min-w-0 flex-1">
            <h3 class="truncate text-sm font-semibold text-neutral-800 dark:text-neutral-200">{{ sub.title }}</h3>
            <div class="mt-1 flex items-center gap-3 text-xs text-neutral-400 dark:text-neutral-500">
              <span class="flex items-center gap-1">
                <span class="size-1.5 rounded-full" :class="sub.valid ? 'bg-emerald-400' : 'bg-red-400'"></span>
                {{ sub.channel_count }} 个频道
              </span>
              <span v-if="sub.last_updated">更新于 {{ formatTime(sub.last_updated) }}</span>
            </div>
          </div>
        </div>
        <div class="flex items-center gap-2 border-t border-black/5 pt-3 dark:border-white/5">
          <button
            type="button"
            class="rounded-lg bg-neutral-100 px-2.5 py-1 text-xs text-neutral-600 transition-colors hover:bg-neutral-200 dark:bg-neutral-700 dark:text-neutral-300 dark:hover:bg-neutral-600"
            @click="handleRefresh(sub)"
          >
            刷新
          </button>
          <button
            type="button"
            class="rounded-lg px-2.5 py-1 text-xs text-red-400 transition-colors hover:bg-red-50 dark:hover:bg-red-900/20"
            @click="handleDelete(sub)"
          >
            删除
          </button>
          <a
            :href="`/api/iptv/export.m3u?tested_only=false`"
            target="_blank"
            class="rounded-lg px-2.5 py-1 text-xs text-neutral-400 transition-colors hover:bg-neutral-100 dark:hover:bg-neutral-700"
          >
            导出
          </a>
        </div>
      </div>

      <p v-if="subscriptions.length === 0 && !loading" class="py-10 text-center text-sm text-neutral-400 dark:text-neutral-500">
        暂无订阅源，在上方输入链接添加
      </p>
    </div>
  </main>
</template>

<script setup>
import { ref, onMounted, onBeforeUnmount } from 'vue'
import {
  fetchSubscriptions, addSubscription, deleteSubscription, refreshSubscription,
  testAllGlobal, fetchGlobalTestStatus, getExportUrl,
} from '../api/iptv'

const API_BASE = import.meta.env.VITE_API_BASE_URL || ''

const subscriptions = ref([])
const loading = ref(false)
const addUrl = ref('')
const addError = ref('')
const addLoading = ref(false)
const testRunning = ref(false)
const testProgress = ref({ total: 0, tested: 0, working: 0, failed: 0 })
const exportUrl = ref('')

let testTimer = null

async function loadSubscriptions() {
  loading.value = true
  try {
    subscriptions.value = await fetchSubscriptions()
  } catch (e) {
    console.error('加载订阅失败:', e)
  }
  loading.value = false
}

async function handleAdd() {
  const url = addUrl.value.trim()
  if (!url) return
  addLoading.value = true
  addError.value = ''
  try {
    await addSubscription(url)
    addUrl.value = ''
    await loadSubscriptions()
  } catch (e) {
    addError.value = e.message
  }
  addLoading.value = false
}

async function handleDelete(sub) {
  if (!confirm(`确定删除「${sub.title}」？`)) return
  try {
    await deleteSubscription(sub.id)
    await loadSubscriptions()
  } catch (e) {
    console.error('删除失败:', e)
  }
}

async function handleRefresh(sub) {
  try {
    await refreshSubscription(sub.id)
    await loadSubscriptions()
  } catch (e) {
    alert(`刷新失败: ${e.message}`)
  }
}

async function handleTestAll() {
  if (testRunning.value) return
  try {
    await testAllGlobal()
    testRunning.value = true
    testProgress.value = { total: 0, tested: 0, working: 0, failed: 0 }
    testTimer = setInterval(pollTestStatus, 2000)
  } catch (e) {
    alert(`启动测速失败: ${e.message}`)
  }
}

async function pollTestStatus() {
  try {
    const status = await fetchGlobalTestStatus()
    testProgress.value = status
    if (status.tested >= status.total && status.total > 0) {
      testRunning.value = false
      clearInterval(testTimer)
      testTimer = null
    }
  } catch {}
}

function formatTime(iso) {
  if (!iso) return ''
  try {
    return new Date(iso).toLocaleDateString('zh-CN', { month: 'short', day: 'numeric' })
  } catch { return iso }
}

onMounted(() => {
  loadSubscriptions()
  exportUrl.value = `${API_BASE}/api/iptv/export.m3u?tested_only=true`
})

onBeforeUnmount(() => {
  if (testTimer) clearInterval(testTimer)
})
</script>
