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
        :disabled="saving"
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
              <span v-if="isForced(item.key)" class="mt-1 inline-flex rounded-full border border-[var(--border)] px-2 py-0.5 text-[10px] text-[var(--text-tertiary)]">环境变量锁定</span>
            </span>
            <input v-model="draft[item.key]" type="checkbox" class="size-4 shrink-0 rounded accent-neutral-950 disabled:opacity-40 dark:accent-white" :disabled="isForced(item.key)" />
          </label>
        </div>
      </section>

      <section class="mt-4 rounded-3xl border border-[var(--border)] bg-[var(--card-bg)] p-4 sm:p-5" aria-labelledby="credential-policy-title">
        <div class="mb-4">
          <h3 id="credential-policy-title" class="text-sm font-semibold text-[var(--text-primary)]">凭证期限</h3>
          <p class="mt-1 text-xs leading-5 text-[var(--text-secondary)]">设置登录会话与外部播放器授权的默认有效时间</p>
        </div>
        <div class="grid gap-3 sm:grid-cols-2">
          <label v-for="item in numberItems" :key="item.key" class="rounded-2xl border border-[var(--border)] bg-[var(--surface)] p-4">
            <span class="mb-2 flex items-center justify-between gap-3 text-sm font-medium text-[var(--text-primary)]">
              {{ item.label }}
              <span v-if="isForced(item.key)" class="rounded-full border border-[var(--border)] px-2 py-0.5 text-[10px] font-normal text-[var(--text-tertiary)]">环境变量锁定</span>
            </span>
            <input v-model.number="draft[item.key]" type="number" :min="item.min" :max="item.max" class="min-h-11 w-full rounded-xl border border-[var(--border)] bg-[var(--bg-soft)] px-3.5 text-sm text-[var(--text-primary)] outline-none focus:border-[var(--border-strong)] focus:ring-2 focus:ring-[var(--surface-strong)] disabled:opacity-40" :disabled="isForced(item.key)" />
            <span class="mt-2 block text-xs text-[var(--text-tertiary)]">{{ item.description }}</span>
          </label>
        </div>
      </section>

      <p v-if="error" class="mt-4 rounded-2xl border border-red-500/20 bg-red-500/5 px-4 py-3 text-sm text-red-500" role="alert">{{ error }}</p>
    </template>
  </section>
</template>

<script setup>
import { onMounted, ref } from 'vue'
import { fetchSecuritySettings, updateSecuritySettings } from '../../api/settings'
import { useAuthStore } from '../../stores/auth'
import { useToastStore } from '../../stores/toast'

const authStore = useAuthStore()
const toastStore = useToastStore()
const loading = ref(true)
const loaded = ref(false)
const saving = ref(false)
const error = ref('')
const forced = ref(new Set())
const draft = ref({ anonymous_browse: true, anonymous_playback: true, allow_private: false, allow_loopback: true, session_max_age_days: 14, media_credential_default_ttl_days: 90 })
const toggleItems = [
  { key: 'anonymous_browse', label: '匿名浏览', description: '未登录访客可以浏览频道和节目内容' },
  { key: 'anonymous_playback', label: '匿名播放', description: '未登录访客可以直接开始播放' },
  { key: 'allow_private', label: '允许私有地址源', description: '允许访问局域网或私有网段中的媒体来源' },
  { key: 'allow_loopback', label: '允许回环地址源', description: '允许访问当前主机上的媒体服务' },
]
const numberItems = [
  { key: 'session_max_age_days', label: '登录有效天数', description: '1–365 天', min: 1, max: 365 },
  { key: 'media_credential_default_ttl_days', label: '播放凭证有效天数', description: '1–3650 天', min: 1, max: 3650 },
]

function apply(data) {
  const settings = data?.settings || {}
  forced.value = new Set(data?.forced || [])
  draft.value = { ...draft.value, ...settings }
  if (settings.anonymous_browse !== undefined) authStore.setup.anonymousBrowse = Boolean(settings.anonymous_browse)
  if (settings.anonymous_playback !== undefined) authStore.setup.anonymousPlayback = Boolean(settings.anonymous_playback)
  loaded.value = true
}

function isForced(key) {
  return forced.value.has(key)
}

async function load() {
  loading.value = true
  error.value = ''
  try {
    apply(await fetchSecuritySettings())
  } catch (caught) {
    error.value = caught?.message || '安全设置加载失败'
  } finally {
    loading.value = false
  }
}

async function save() {
  if (!loaded.value || saving.value) return
  saving.value = true
  error.value = ''
  const payload = {}
  for (const item of [...toggleItems, ...numberItems]) {
    if (!isForced(item.key)) payload[item.key] = draft.value[item.key]
  }
  try {
    apply(await updateSecuritySettings(payload))
    toastStore.success('安全设置已保存')
  } catch (caught) {
    error.value = caught?.message || '安全设置保存失败'
  } finally {
    saving.value = false
  }
}

onMounted(load)
</script>
