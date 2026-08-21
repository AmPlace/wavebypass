<template>
  <section aria-labelledby="security-settings-title">
    <header class="mb-6 flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
      <div>
        <h2 id="security-settings-title" class="text-xl font-semibold tracking-[-0.015em] text-[var(--text-primary)]">安全与访问</h2>
        <p class="mt-1.5 text-sm leading-6 text-[var(--text-secondary)]">管理匿名访问、网络来源与登录凭证期限</p>
      </div>
      <button
        v-if="loaded"
        type="button"
        class="min-h-10 shrink-0 rounded-xl bg-[var(--text-primary)] px-4 text-sm font-semibold text-[var(--bg)] transition-transform hover:-translate-y-px focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--border-strong)] focus-visible:ring-offset-2 focus-visible:ring-offset-[var(--bg)] active:translate-y-0 disabled:cursor-not-allowed disabled:opacity-50"
        :disabled="saving || !dirty"
        @click="save"
      >
        {{ saving ? '保存中…' : '保存设置' }}
      </button>
    </header>

    <section v-if="loading" class="grid gap-3 sm:grid-cols-2" aria-label="正在加载安全设置" aria-busy="true">
      <div v-for="index in 4" :key="index" class="h-24 animate-pulse rounded-3xl border border-[var(--border)] bg-[var(--surface)]"></div>
    </section>

    <section v-else-if="error && !loaded" class="rounded-3xl border border-red-500/20 bg-red-500/5 px-6 py-10 text-center" role="alert">
      <h3 class="text-sm font-semibold text-[var(--text-primary)]">安全设置加载失败</h3>
      <p class="mt-2 text-sm text-[var(--text-secondary)]">{{ error }}</p>
      <button type="button" class="mt-4 min-h-10 rounded-xl border border-[var(--border)] px-4 text-sm font-medium text-[var(--text-primary)] hover:bg-[var(--surface-hover)]" @click="load">重试</button>
    </section>

    <template v-else>
      <section class="rounded-3xl border border-[var(--border)] bg-[var(--card-bg)] p-4 sm:p-5" aria-labelledby="access-policy-title">
        <div class="mb-4">
          <h3 id="access-policy-title" class="text-sm font-semibold text-[var(--text-primary)]">访问策略</h3>
          <p class="mt-1 text-xs leading-5 text-[var(--text-secondary)]">控制访客浏览、播放和可访问的网络地址</p>
        </div>
        <div class="grid gap-3 sm:grid-cols-2">
          <label
            v-for="item in toggleItems"
            :key="item.key"
            class="flex min-h-[76px] items-center justify-between gap-4 rounded-2xl border border-[var(--border)] bg-[var(--surface)] px-4 py-3"
          >
            <span class="min-w-0">
              <span class="block text-sm font-medium text-[var(--text-primary)]">{{ item.label }}</span>
              <span class="mt-1 block text-xs leading-5 text-[var(--text-secondary)]">{{ item.description }}</span>
              <span class="mt-1 block text-[11px] leading-5 text-[var(--text-tertiary)]">当前生效：{{ formatValue(effective[item.key]) }} · 已保存：{{ storedValue(item.key) }}</span>
              <span v-if="isForced(item.key)" class="mt-1 inline-flex rounded-full border border-[var(--border)] px-2 py-0.5 text-[10px] text-[var(--text-tertiary)]">环境变量锁定</span>
            </span>
            <input v-model="draft[item.key]" type="checkbox" class="size-4 shrink-0 rounded accent-neutral-950 disabled:opacity-40 dark:accent-white" :disabled="saving || isForced(item.key)" />
          </label>
        </div>
      </section>

      <section class="mt-4 rounded-3xl border border-[var(--border)] bg-[var(--card-bg)] p-4 sm:p-5" aria-labelledby="credential-policy-title">
        <div class="mb-4">
          <h3 id="credential-policy-title" class="text-sm font-semibold text-[var(--text-primary)]">运行参数</h3>
          <p class="mt-1 text-xs leading-5 text-[var(--text-secondary)]">有效值由环境变量、已保存值和 {{ mode || '当前模式' }} 默认值共同决定</p>
        </div>
        <div class="grid gap-3 sm:grid-cols-2">
          <label v-for="item in numberItems" :key="item.key" class="rounded-2xl border border-[var(--border)] bg-[var(--surface)] p-4">
            <span class="mb-2 flex items-center justify-between gap-3 text-sm font-medium text-[var(--text-primary)]">
              {{ item.label }}
              <span class="flex shrink-0 flex-wrap justify-end gap-1">
                <span v-if="schema[item.key]?.restart_required" class="rounded-full border border-amber-500/30 px-2 py-0.5 text-[10px] font-normal text-amber-700 dark:text-amber-300">重启后生效</span>
                <span v-if="isForced(item.key)" class="rounded-full border border-[var(--border)] px-2 py-0.5 text-[10px] font-normal text-[var(--text-tertiary)]">环境变量锁定</span>
              </span>
            </span>
            <input v-model.number="draft[item.key]" type="number" :min="schema[item.key]?.min" :max="schema[item.key]?.max" class="min-h-11 w-full rounded-xl border border-[var(--border)] bg-[var(--bg-soft)] px-3.5 text-sm text-[var(--text-primary)] outline-none focus:border-[var(--border-strong)] focus:ring-2 focus:ring-[var(--surface-strong)] disabled:opacity-40" :disabled="saving || isForced(item.key)" />
            <span class="mt-2 block text-xs leading-5 text-[var(--text-tertiary)]">{{ item.description }}<br>当前生效：{{ formatValue(effective[item.key]) }} · 已保存：{{ storedValue(item.key) }}</span>
          </label>
        </div>
      </section>

      <section class="mt-4 rounded-3xl border border-[var(--border)] bg-[var(--card-bg)] p-4 sm:p-5" aria-labelledby="public-address-title">
        <div class="mb-4">
          <h3 id="public-address-title" class="text-sm font-semibold text-[var(--text-primary)]">公开访问地址</h3>
          <p class="mt-1 text-xs leading-5 text-[var(--text-secondary)]">用于生成需要公开 WaveFlow 地址的链接；留空时使用请求上下文</p>
        </div>
        <label v-for="item in textItems" :key="item.key" class="block rounded-2xl border border-[var(--border)] bg-[var(--surface)] p-4">
          <span class="mb-2 flex items-center justify-between gap-3 text-sm font-medium text-[var(--text-primary)]">
            {{ item.label }}
            <span v-if="isForced(item.key)" class="rounded-full border border-[var(--border)] px-2 py-0.5 text-[10px] font-normal text-[var(--text-tertiary)]">环境变量锁定</span>
          </span>
          <input v-model="draft[item.key]" type="url" autocomplete="off" spellcheck="false" class="min-h-11 w-full rounded-xl border border-[var(--border)] bg-[var(--bg-soft)] px-3.5 text-sm text-[var(--text-primary)] outline-none focus:border-[var(--border-strong)] focus:ring-2 focus:ring-[var(--surface-strong)] disabled:opacity-40" :disabled="saving || isForced(item.key)" placeholder="https://waveflow.example" />
          <span class="mt-2 block text-xs leading-5 text-[var(--text-tertiary)]">当前生效：{{ formatValue(effective[item.key]) }} · 已保存：{{ storedValue(item.key) }}</span>
        </label>
      </section>

      <p v-if="error" class="mt-4 rounded-2xl border border-red-500/20 bg-red-500/5 px-4 py-3 text-sm text-red-500" role="alert">{{ error }}</p>
    </template>
  </section>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { fetchSecuritySettings, updateSecuritySettings } from '../../api/settings'
import { adminRequestErrorMessage } from '../../api/adminUi.js'
import { useAuthStore } from '../../stores/auth'
import { useToastStore } from '../../stores/toast'

const authStore = useAuthStore()
const toastStore = useToastStore()
const loading = ref(true)
const loaded = ref(false)
const saving = ref(false)
const error = ref('')
const forced = ref(new Set())
const effective = ref({})
const persisted = ref({})
const defaults = ref({})
const schema = ref({})
const mode = ref('')
const draft = ref({})
const baselineDraft = ref({})
let loadController = null
let saveController = null
let saveRequestId = 0
let componentDisposed = false
const toggleItems = [
  { key: 'anonymous_browse', label: '匿名浏览', description: '未登录访客可以浏览频道和节目内容' },
  { key: 'anonymous_playback', label: '匿名播放', description: '未登录访客可以直接开始播放' },
  { key: 'allow_private', label: '允许私有地址源', description: '允许访问局域网或私有网段中的媒体来源' },
  { key: 'allow_loopback', label: '允许回环地址源', description: '允许访问当前主机上的媒体服务' },
  { key: 'enable_rtsp_proxy', label: '启用 RTSP 代理', description: '允许 Core 为浏览器启动受控 RTSP 转换会话' },
]
const numberItems = [
  { key: 'rtsp_max_sessions', label: 'RTSP 最大会话数', description: '同时允许的 RTSP 转换会话' },
  { key: 'session_max_age_days', label: '登录有效天数', description: '1–365 天', min: 1, max: 365 },
  { key: 'media_credential_default_ttl_days', label: '播放凭证有效天数', description: '1–3650 天', min: 1, max: 3650 },
  { key: 'm3u8_cache_ttl', label: 'M3U8 缓存秒数', description: '兼容缓存参数，后端标记为重启后生效' },
  { key: 'm3u8_cache_max_entries', label: 'M3U8 缓存条目上限', description: '兼容缓存容量，后端标记为重启后生效' },
  { key: 'probe_concurrency', label: '探测并发数', description: '同时执行的频道探测任务上限' },
  { key: 'subscription_refresh_cooldown', label: '订阅刷新冷却秒数', description: '重复刷新同一订阅前的最短间隔' },
]
const textItems = [
  { key: 'public_base_url', label: '公开基础 URL' },
]
const settingItems = [...toggleItems, ...numberItems, ...textItems]
const dirty = computed(() => settingItems.some((item) => (
  !isForced(item.key) && draft.value[item.key] !== baselineDraft.value[item.key]
)))

function apply(data) {
  const settings = data?.settings || {}
  const runtime = data?.runtime || {}
  const nextSchema = data?.schema || {}
  effective.value = { ...settings }
  persisted.value = { ...runtime }
  defaults.value = { ...(data?.defaults || {}) }
  schema.value = { ...nextSchema }
  mode.value = String(data?.mode || '')
  forced.value = new Set(data?.forced || [])
  const nextDraft = {}
  for (const item of settingItems) {
    nextDraft[item.key] = Object.prototype.hasOwnProperty.call(runtime, item.key)
      ? runtime[item.key]
      : settings[item.key]
  }
  draft.value = nextDraft
  baselineDraft.value = { ...nextDraft }
  if (settings.anonymous_browse !== undefined) authStore.setup.anonymousBrowse = Boolean(settings.anonymous_browse)
  if (settings.anonymous_playback !== undefined) authStore.setup.anonymousPlayback = Boolean(settings.anonymous_playback)
  loaded.value = true
}

function isForced(key) {
  return forced.value.has(key)
}

function formatValue(value) {
  if (value === true) return '开启'
  if (value === false) return '关闭'
  if (value === '' || value === undefined || value === null) return '未设置'
  return String(value)
}

function storedValue(key) {
  return Object.prototype.hasOwnProperty.call(persisted.value, key)
    ? formatValue(persisted.value[key])
    : `未单独保存（默认 ${formatValue(defaults.value[key])}）`
}

async function load() {
  loadController?.abort()
  const controller = new AbortController()
  loadController = controller
  loading.value = true
  error.value = ''
  try {
    const data = await fetchSecuritySettings({ signal: controller.signal })
    if (!controller.signal.aborted && !componentDisposed) apply(data)
  } catch (caught) {
    if (!controller.signal.aborted && !componentDisposed) {
      error.value = adminRequestErrorMessage(caught, '安全设置加载失败')
    }
  } finally {
    if (loadController === controller && !componentDisposed) loading.value = false
  }
}

async function save() {
  if (!loaded.value || saving.value || !dirty.value || componentDisposed) return
  const requestId = ++saveRequestId
  saveController?.abort()
  const controller = new AbortController()
  saveController = controller
  saving.value = true
  error.value = ''
  const payload = {}
  for (const item of settingItems) {
    if (!isForced(item.key) && draft.value[item.key] !== baselineDraft.value[item.key]) {
      payload[item.key] = draft.value[item.key]
    }
  }
  try {
    const data = await updateSecuritySettings(payload, { signal: controller.signal })
    if (requestId !== saveRequestId || controller.signal.aborted || componentDisposed) return
    apply(data)
    toastStore.success(schema.value && Object.keys(payload).some(key => schema.value[key]?.restart_required)
      ? '安全设置已保存，部分设置将在后端重启后生效'
      : '安全设置已保存')
  } catch (caught) {
    if (requestId === saveRequestId && !controller.signal.aborted && !componentDisposed) {
      error.value = adminRequestErrorMessage(caught, '安全设置保存失败')
    }
  } finally {
    if (requestId === saveRequestId && !componentDisposed) saving.value = false
  }
}

onMounted(load)
onBeforeUnmount(() => {
  componentDisposed = true
  saveRequestId += 1
  loadController?.abort()
  saveController?.abort()
})
</script>
