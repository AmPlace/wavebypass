<template>
  <main class="mx-auto flex min-h-screen w-full max-w-6xl flex-col px-5 pt-[calc(env(safe-area-inset-top)+3.5rem)] pb-36 sm:px-8">
    <header class="mb-6 flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
      <div>
        <div class="mb-2 flex items-center gap-2">
          <button type="button"
            class="flex size-8 items-center justify-center rounded-full text-neutral-500 transition-colors hover:bg-neutral-200/60 dark:hover:bg-neutral-700/60"
            @click="$router.push('/iptv')">
            <svg class="size-4" viewBox="0 0 24 24" fill="none"><path d="M19 12H5M12 5l-7 7 7 7" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" /></svg>
          </button>
          <span class="text-sm font-medium text-neutral-400 dark:text-neutral-500">WaveFlow Market</span>
        </div>
        <h1 class="text-3xl font-semibold tracking-tight text-neutral-900 dark:text-neutral-50">频道市场</h1>
        <!-- <p class="mt-2 max-w-2xl text-sm leading-6 text-neutral-500 dark:text-neutral-400">
          Market 只分发数据和配置，不自动执行第三方代码。动态订阅会由后端安全拉取并解析。
        </p> -->
      </div>
      <div class="flex flex-col items-start gap-2 sm:w-[360px] sm:items-end">
        <div class="flex w-full justify-start gap-2 sm:justify-end">
          <button type="button"
            class="shrink-0 rounded-xl border border-neutral-200 bg-white/70 px-3 py-2 text-xs font-medium text-neutral-700 backdrop-blur-xl dark:border-neutral-700 dark:bg-neutral-900/70 dark:text-neutral-200"
            @click="openSourceDialog">
            Market 源管理
          </button>
          <button type="button"
            class="shrink-0 rounded-xl bg-neutral-950 px-3 py-2 text-xs font-medium text-white disabled:opacity-50 dark:bg-white dark:text-black"
            :disabled="refreshing"
            @click="handleRefresh">
            {{ refreshing ? '刷新中' : '刷新全部' }}
          </button>
          <button type="button"
            class="shrink-0 rounded-xl border border-neutral-200 bg-white/70 px-3 py-2 text-xs font-medium text-neutral-700 backdrop-blur-xl disabled:opacity-50 dark:border-neutral-700 dark:bg-neutral-900/70 dark:text-neutral-200"
            :disabled="updating"
            @click="handleUpdateAllInstalled">
            {{ updating ? '更新中' : '更新全部已安装' }}
          </button>
        </div>
        <p class="w-full text-left text-xs text-neutral-400 dark:text-neutral-500 sm:text-right">
          {{ summary.enabled_source_count || 0 }} 个 Market 源启用 | 共 {{ summary.package_count || 0 }} 个包
        </p>
      </div>
    </header>

    <section class="mb-5 grid gap-3 lg:grid-cols-[minmax(0,1fr)_auto] lg:items-center">
      <input v-model="filters.search" type="search" placeholder="搜索频道包、地区、标签…"
        class="rounded-xl border border-neutral-200 bg-white/80 px-4 py-2.5 text-sm text-neutral-800 outline-none backdrop-blur-xl focus:border-neutral-400 dark:border-neutral-700 dark:bg-neutral-900/70 dark:text-neutral-100" />
      <label class="flex items-center gap-2 text-xs text-neutral-500 dark:text-neutral-400">
        <input v-model="filters.supported_only" type="checkbox" class="size-3.5 rounded accent-neutral-950 dark:accent-white" />
        仅显示 V1 可导入
      </label>
    </section>

    <section class="mb-6 flex flex-wrap gap-2">
      <select v-model="filters.region" class="market-select">
        <option value="">全部地区</option>
        <option v-for="item in regionOptions" :key="item" :value="item">{{ item }}</option>
      </select>
      <select v-model="filters.operator" class="market-select">
        <option value="">全部运营商</option>
        <option v-for="item in operatorOptions" :key="item" :value="item">{{ operatorLabel(item) }}</option>
      </select>
      <select v-model="filters.kind" class="market-select">
        <option value="">全部类型</option>
        <option v-for="item in kindOptions" :key="item" :value="item">{{ kindLabel(item) }}</option>
      </select>
      <select v-model="filters.status" class="market-select">
        <option value="">全部状态</option>
        <option v-for="item in statusOptions" :key="item" :value="item">{{ statusLabel(item) }}</option>
      </select>
      <select v-model="filters.tag" class="market-select">
        <option value="">全部标签</option>
        <option v-for="item in tagOptions" :key="item" :value="item">{{ item }}</option>
      </select>
    </section>

    <p v-if="error" class="mb-4 rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-600 dark:border-red-900/50 dark:bg-red-950/30 dark:text-red-300">{{ error }}</p>

    <section v-if="loading" class="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
      <div v-for="i in 6" :key="i" class="h-44 animate-pulse rounded-2xl bg-white/70 dark:bg-neutral-900/60"></div>
    </section>

    <section v-else class="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
      <article v-for="pkg in packages" :key="pkg.id"
        class="rounded-2xl border border-black/5 bg-white/85 p-4 shadow-sm backdrop-blur-xl transition hover:-translate-y-0.5 hover:shadow-lg dark:border-white/10 dark:bg-neutral-900/70">
        <div class="mb-3 flex items-start justify-between gap-3">
          <div class="min-w-0">
            <h2 class="truncate text-base font-semibold text-neutral-900 dark:text-neutral-50">{{ pkg.name }}</h2>
            <p class="mt-1 line-clamp-2 text-xs leading-5 text-neutral-500 dark:text-neutral-400">{{ pkg.description || '暂无描述' }}</p>
          </div>
          <span class="shrink-0 rounded-full px-2 py-1 text-[11px] font-medium" :class="pkg.supported_in_v1 ? 'bg-emerald-50 text-emerald-600 dark:bg-emerald-950/40 dark:text-emerald-300' : 'bg-neutral-100 text-neutral-500 dark:bg-neutral-800 dark:text-neutral-400'">
            {{ pkg.supported_in_v1 ? '可导入' : '预留' }}
          </span>
        </div>

        <div class="mb-3 flex flex-wrap gap-1.5 text-[11px] text-neutral-500 dark:text-neutral-400">
          <span class="market-chip">{{ kindLabel(pkg.kind) }}</span>
          <span class="market-chip">{{ regionLabel(pkg.region) }}</span>
          <span class="market-chip">{{ statusLabel(pkg.status) }}</span>
          <span v-if="pkg.requires_proxy" class="market-chip">需代理</span>
          <span v-if="pkg.requires_resolver" class="market-chip">需解析器</span>
          <span v-if="pkg.requires_cookie" class="market-chip">需 Cookie</span>
        </div>

        <div class="mb-4 flex items-center gap-4 text-xs text-neutral-400 dark:text-neutral-500">
          <span>{{ pkg.channel_count || '未知' }} 频道</span>
          <span>{{ pkg.source_count || '未知' }} 源</span>
          <span v-if="pkg.installed" class="text-emerald-500">已安装</span>
        </div>

        <div class="mb-4 flex flex-wrap gap-1.5">
          <span v-for="tag in (pkg.tags || []).slice(0, 5)" :key="tag" class="rounded-md bg-neutral-100 px-2 py-1 text-[11px] text-neutral-500 dark:bg-neutral-800 dark:text-neutral-400">{{ tag }}</span>
        </div>

        <div class="flex items-center gap-2">
          <button type="button" class="market-action" @click="openDetail(pkg)">详情</button>
          <button type="button" class="market-action" :disabled="!pkg.previewable" @click="handlePreview(pkg)">预览</button>
          <button v-if="!pkg.installed" type="button" class="market-action primary" :disabled="!pkg.importable" @click="handleImport(pkg)">
            导入
          </button>
          <button v-else-if="pkg.update_available" type="button" class="market-action primary" :disabled="!pkg.importable || importLoading" @click="handleReinstall(pkg)">
            更新
          </button>
          <button v-if="pkg.installed" type="button" class="market-action" :disabled="importLoading" @click="handleUninstall(pkg)">卸载</button>
        </div>
        <p v-if="!pkg.supported_in_v1" class="mt-3 text-xs text-neutral-400 dark:text-neutral-500">{{ pkg.unsupported_reason || '当前版本仅展示' }}</p>
        <p v-else-if="pkg.schema_warnings?.length" class="mt-3 line-clamp-2 text-xs text-amber-600 dark:text-amber-300">{{ pkg.schema_warnings[0] }}</p>
      </article>
    </section>

    <p v-if="!loading && packages.length === 0" class="py-14 text-center text-sm text-neutral-400 dark:text-neutral-500">没有匹配的 Market 包</p>
  </main>

  <Teleport to="body">
    <div v-if="sourceDialogOpen"
      class="fixed inset-0 z-[95] flex items-center justify-center bg-neutral-950/35 px-4 py-8 backdrop-blur-md"
      @click.self="closeSourceDialog">
      <section class="max-h-full w-full max-w-3xl overflow-y-auto rounded-3xl border border-white/60 bg-white/95 p-6 shadow-2xl shadow-neutral-950/20 dark:border-white/10 dark:bg-neutral-900/95">
        <div class="mb-5 flex items-start justify-between gap-4">
          <div>
            <h2 class="text-lg font-semibold text-neutral-900 dark:text-neutral-50">Market源管理</h2>
            <!-- <p class="mt-1 text-sm text-neutral-500 dark:text-neutral-400">默认启用官方源，也可以添加第三方 Market 同时加载。</p> -->
          </div>
          <button type="button" class="flex size-8 shrink-0 items-center justify-center rounded-full text-neutral-500 hover:bg-neutral-100 dark:hover:bg-neutral-800" @click="closeSourceDialog">
            <svg class="size-4" viewBox="0 0 24 24" fill="none"><path d="M6 6l12 12M18 6 6 18" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" /></svg>
          </button>
        </div>

        <div class="mb-5 space-y-3">
          <div v-for="source in marketSources" :key="source.id" class="rounded-2xl border border-neutral-100 bg-neutral-50/80 p-3 dark:border-neutral-800 dark:bg-neutral-950/40">
            <div class="mb-3 flex flex-col gap-2 sm:flex-row sm:items-center">
              <input v-model="source.name" class="market-input sm:w-44" placeholder="名称" />
              <input v-model="source.url" class="market-input min-w-0 flex-1" placeholder="market.json URL" :disabled="source.is_builtin" />
            </div>
            <div class="flex flex-wrap items-center gap-3 text-xs text-neutral-500 dark:text-neutral-400">
              <label class="flex items-center gap-1.5">
                <input v-model="source.enabled" type="checkbox" class="size-3.5 rounded accent-neutral-950 dark:accent-white" />
                启用
              </label>
              <label class="flex items-center gap-1.5">
                <input v-model="source.allow_private" type="checkbox" class="size-3.5 rounded accent-neutral-950 dark:accent-white" />
                允许本机/内网
              </label>
              <span :class="source.last_status === 'error' ? 'text-red-500' : source.last_status === 'ok' ? 'text-emerald-500' : ''">
                {{ sourceStatusLabel(source) }}
              </span>
              <span v-if="source.last_error" class="min-w-0 flex-1 truncate text-red-500">{{ source.last_error }}</span>
              <div class="ml-auto flex gap-2">
                <button type="button" class="market-action" :disabled="refreshing" @click="handleRefreshSource(source)">刷新</button>
                <button type="button" class="market-action" @click="handleUpdateSource(source)">保存</button>
                <button type="button" class="market-action" :disabled="source.is_builtin" @click="handleDeleteSource(source)">删除</button>
              </div>
            </div>
          </div>
        </div>

        <div class="rounded-2xl border border-neutral-100 p-3 dark:border-neutral-800">
          <h3 class="mb-3 text-sm font-semibold text-neutral-900 dark:text-neutral-50">添加第三方源</h3>
          <div class="grid gap-2 sm:grid-cols-[160px_minmax(0,1fr)]">
            <input v-model="sourceDraft.name" class="market-input" placeholder="名称" />
            <input v-model="sourceDraft.url" class="market-input" placeholder="https://example.com/market.json" />
          </div>
          <div class="mt-3 flex flex-wrap items-center justify-between gap-3">
            <label class="flex items-center gap-1.5 text-xs text-neutral-500 dark:text-neutral-400">
              <input v-model="sourceDraft.allow_private" type="checkbox" class="size-3.5 rounded accent-neutral-950 dark:accent-white" />
              允许本机/内网 URL
            </label>
            <button type="button" class="market-action primary" @click="handleCreateSource">添加源</button>
          </div>
        </div>
      </section>
    </div>

    <div v-if="dialogOpen"
      class="fixed inset-0 z-[90] flex items-center justify-center bg-neutral-950/35 px-4 py-8 backdrop-blur-md"
      @click.self="closeDialog">
      <section class="max-h-full w-full max-w-3xl overflow-y-auto rounded-3xl border border-white/60 bg-white/95 p-6 shadow-2xl shadow-neutral-950/20 dark:border-white/10 dark:bg-neutral-900/95">
        <div class="mb-5 flex items-start justify-between gap-4">
          <div>
            <h2 class="text-lg font-semibold text-neutral-900 dark:text-neutral-50">{{ selectedPackage?.name }}</h2>
            <p class="mt-1 text-sm text-neutral-500 dark:text-neutral-400">{{ selectedPackage?.description }}</p>
          </div>
          <button type="button" class="flex size-8 shrink-0 items-center justify-center rounded-full text-neutral-500 hover:bg-neutral-100 dark:hover:bg-neutral-800" @click="closeDialog">
            <svg class="size-4" viewBox="0 0 24 24" fill="none"><path d="M6 6l12 12M18 6 6 18" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" /></svg>
          </button>
        </div>

        <div v-if="selectedPackage" class="mb-5 grid gap-2 text-xs text-neutral-500 dark:text-neutral-400 sm:grid-cols-2">
          <div class="market-info">类型：{{ kindLabel(selectedPackage.kind) }}</div>
          <div class="market-info">状态：{{ statusLabel(selectedPackage.status) }}</div>
          <div class="market-info">地区：{{ regionLabel(selectedPackage.region) }}</div>
          <div class="market-info">运营商：{{ (selectedPackage.operators || []).map(operatorLabel).join('、') || '未知' }}</div>
          <div class="market-info">版本：{{ selectedPackage.version || '未知' }}</div>
          <div class="market-info">更新：{{ selectedPackage.updated_at || '未知' }}</div>
          <div class="market-info">来源：{{ selectedPackage.source_origin || 'unknown' }}</div>
          <div class="market-info">策略：{{ selectedPackage.source_policy || 'unknown' }}</div>
          <div class="market-info">Market 源：{{ selectedPackage.market_source?.name || '未知' }}</div>
          <div class="market-info">安装版本：{{ selectedPackage.installed_version || (selectedPackage.installed ? '未知' : '未安装') }}</div>
          <div class="market-info sm:col-span-2">Manifest：{{ selectedPackage.manifest_url || '内联配置' }}</div>
        </div>

        <div v-if="selectedPackage?.installed" class="mb-5 rounded-2xl border border-neutral-100 bg-neutral-50/80 p-3 dark:border-neutral-800 dark:bg-neutral-950/40">
          <label class="flex items-start justify-between gap-4 text-sm text-neutral-700 dark:text-neutral-200">
            <span>
              <span class="block font-semibold">自动更新</span>
              <span class="mt-1 block text-xs leading-5 text-neutral-400 dark:text-neutral-500">用于后续后台自动更新；手动更新和全部更新不受此开关限制。</span>
            </span>
            <input
              :checked="selectedPackage.auto_update"
              type="checkbox"
              class="mt-1 size-4 rounded accent-neutral-950 dark:accent-white"
              :disabled="installConfigLoading"
              @change="handleAutoUpdateChange(selectedPackage, $event)"
            />
          </label>
        </div>

        <div v-if="selectedPackage" class="mb-5 grid gap-2 text-xs text-neutral-500 dark:text-neutral-400 sm:grid-cols-3">
          <div class="market-info">代理：{{ selectedPackage.requires_proxy ? '需要' : '不需要' }}</div>
          <div class="market-info">解析器：{{ selectedPackage.requires_resolver ? '需要' : '不需要' }}</div>
          <div class="market-info">Cookie：{{ selectedPackage.requires_cookie ? '需要' : '不需要' }}</div>
          <div class="market-info">Referer：{{ selectedPackage.requires_referer ? '需要' : '不需要' }}</div>
          <div class="market-info">自定义 UA：{{ selectedPackage.requires_custom_ua ? '需要' : '不需要' }}</div>
          <div class="market-info">风险：{{ selectedPackage.risk_level || 'unknown' }}</div>
        </div>

        <div v-if="selectedPackage?.health || selectedPackage?.compatibility || selectedPackage?.contributors?.length" class="mb-5 grid gap-3 text-xs sm:grid-cols-3">
          <div v-if="selectedPackage.health" class="market-detail-box">
            <h3>健康</h3>
            <p>可用率：{{ selectedPackage.health.rate ?? '未知' }}</p>
            <p>检测：{{ selectedPackage.health.last_checked_at || '未知' }}</p>
          </div>
          <div v-if="selectedPackage.compatibility" class="market-detail-box">
            <h3>兼容</h3>
            <p v-for="(value, key) in selectedPackage.compatibility" :key="key">{{ key }}：{{ value }}</p>
          </div>
          <div v-if="selectedPackage.contributors?.length" class="market-detail-box">
            <h3>贡献者</h3>
            <p v-for="item in selectedPackage.contributors.slice(0, 4)" :key="item.name || item.url">{{ item.name || item.url }}</p>
          </div>
        </div>

        <div v-if="selectedPackage?.schema_warnings?.length" class="mb-5 rounded-2xl bg-amber-50 p-3 text-xs leading-5 text-amber-700 dark:bg-amber-950/30 dark:text-amber-300">
          <p v-for="item in selectedPackage.schema_warnings.slice(0, 4)" :key="item">{{ item }}</p>
        </div>

        <div v-if="previewLoading" class="rounded-2xl bg-neutral-100 p-5 text-sm text-neutral-500 dark:bg-neutral-800 dark:text-neutral-400">正在获取频道列表…</div>

        <div v-else-if="preview" class="space-y-4">
          <div class="grid gap-2 text-sm sm:grid-cols-4">
            <div class="market-stat"><b>{{ preview.channel_count }}</b><span>频道</span></div>
            <div class="market-stat"><b>{{ preview.source_count }}</b><span>可导入源</span></div>
            <div class="market-stat"><b>{{ preview.direct_source_count ?? 0 }}</b><span>直连源</span></div>
            <div class="market-stat"><b>{{ preview.proxy_source_count ?? 0 }}</b><span>代理源</span></div>
          </div>
          <div class="grid gap-2 text-sm sm:grid-cols-1">
            <div class="market-stat"><b>{{ preview.unsupported_source_count }}</b><span>跳过源</span></div>
          </div>
          <div v-if="preview.warnings?.length" class="rounded-2xl bg-amber-50 p-3 text-xs leading-5 text-amber-700 dark:bg-amber-950/30 dark:text-amber-300">
            <p v-for="item in preview.warnings.slice(0, 6)" :key="item">{{ item }}</p>
          </div>
          <div class="max-h-72 overflow-y-auto rounded-2xl border border-neutral-100 dark:border-neutral-800">
            <div v-for="ch in preview.channels.slice(0, 80)" :key="`${ch.name}-${ch.url}`" class="flex items-center justify-between gap-3 border-b border-neutral-100 px-3 py-2 text-xs last:border-0 dark:border-neutral-800">
              <div class="min-w-0">
                <p class="truncate font-medium text-neutral-800 dark:text-neutral-100">{{ ch.name }}</p>
                <p class="truncate text-neutral-400">{{ ch.group_name }} · {{ ch.source_type }}</p>
              </div>
              <span v-if="ch.referer || ch.custom_ua || ch.force_proxy" class="shrink-0 rounded-full bg-neutral-100 px-2 py-1 text-[11px] text-neutral-500 dark:bg-neutral-800">代理</span>
            </div>
          </div>
        </div>

        <div v-else class="rounded-2xl bg-neutral-100 p-5 text-sm text-neutral-500 dark:bg-neutral-800 dark:text-neutral-400">
          {{ selectedPackage?.unsupported_reason || '点击预览获取频道列表。' }}
        </div>

        <div class="mt-5 flex justify-end gap-2">
          <button type="button" class="market-action" :disabled="!selectedPackage?.previewable || previewLoading" @click="handlePreview(selectedPackage)">预览</button>
          <button v-if="!selectedPackage?.installed" type="button" class="market-action primary" :disabled="!selectedPackage?.importable || importLoading" @click="handleImport(selectedPackage)">
            {{ importLoading ? '导入中' : '导入' }}
          </button>
          <button v-else-if="selectedPackage?.update_available" type="button" class="market-action primary" :disabled="!selectedPackage?.importable || importLoading" @click="handleReinstall(selectedPackage)">
            {{ importLoading ? '更新中' : '更新' }}
          </button>
          <button v-if="selectedPackage?.installed" type="button" class="market-action" :disabled="importLoading" @click="handleUninstall(selectedPackage)">卸载</button>
        </div>
      </section>
    </div>
  </Teleport>
</template>

<script setup>
import { computed, onMounted, reactive, ref, watch } from 'vue'
import {
  createMarketSource,
  deleteMarketSource,
  fetchMarketPackages,
  fetchMarketSummary,
  fetchMarketSources,
  importMarketPackage,
  previewMarketPackage,
  refreshMarket,
  refreshMarketSource,
  runMarketUpdates,
  uninstallMarketPackage,
  updateMarketInstall,
  updateMarketPackage,
  updateMarketSource,
} from '../api/market'

const summary = ref({})
const packages = ref([])
const loading = ref(false)
const refreshing = ref(false)
const updating = ref(false)
const previewLoading = ref(false)
const importLoading = ref(false)
const installConfigLoading = ref(false)
const error = ref('')
const dialogOpen = ref(false)
const sourceDialogOpen = ref(false)
const selectedPackage = ref(null)
const preview = ref(null)
const marketSources = ref([])
const sourceDraft = reactive({
  name: '',
  url: '',
  allow_private: false,
})

const filters = reactive({
  search: '',
  region: '',
  operator: '',
  kind: '',
  status: '',
  tag: '',
  supported_only: true,
})

const regionOptions = computed(() => unique(packages.value.flatMap(pkg => Object.values(pkg.region || {}).filter(Boolean))))
const operatorOptions = computed(() => unique(packages.value.flatMap(pkg => pkg.operators || [])))
const kindOptions = computed(() => unique(packages.value.map(pkg => pkg.kind).filter(Boolean)))
const statusOptions = computed(() => unique(packages.value.map(pkg => pkg.status).filter(Boolean)))
const tagOptions = computed(() => unique(packages.value.flatMap(pkg => pkg.tags || [])))

function unique(items) {
  return Array.from(new Set(items)).sort((a, b) => String(a).localeCompare(String(b), 'zh-CN'))
}

function kindLabel(kind) {
  return {
    playlist: '静态频道包',
    dynamic_playlist: '动态订阅',
    mixed: '混合包',
    provider: 'Provider',
    remote_resolver: '远程解析器',
    dynamic_provider: '动态 Provider',
    platform_pack: '平台直播',
    radio_pack: '电台包',
  }[kind] || kind || '未知'
}

function statusLabel(status) {
  return {
    stable: '稳定',
    experimental: '实验性',
    unstable: '不稳定',
    broken: '失效',
    deprecated: '废弃',
    unknown: '未知',
  }[status] || status || '未知'
}

function operatorLabel(operator) {
  return {
    global: '不限',
    cmcc: '移动',
    ctcc: '电信',
    cucc: '联通',
    cernet: '教育网',
    broadcast: '广电',
    oversea: '海外',
    unknown: '未知',
  }[operator] || operator
}

function regionLabel(region) {
  if (!region) return '未知地区'
  return [region.country, region.province, region.city].filter(Boolean).join(' · ') || '未知地区'
}

function sourceStatusLabel(source) {
  if (source.last_status === 'ok') return '已刷新'
  if (source.last_status === 'error') return '刷新失败'
  return source.is_builtin ? '官方默认' : '未刷新'
}

async function loadSummary() {
  summary.value = await fetchMarketSummary()
  marketSources.value = (summary.value.sources || []).map(source => ({ ...source }))
}

async function loadSources() {
  const data = await fetchMarketSources()
  marketSources.value = (data.sources || []).map(source => ({ ...source }))
}

async function loadPackages() {
  loading.value = true
  error.value = ''
  try {
    const data = await fetchMarketPackages(filters)
    packages.value = data.packages || []
  } catch (e) {
    error.value = e.message || String(e)
  } finally {
    loading.value = false
  }
}

async function handleRefresh() {
  refreshing.value = true
  error.value = ''
  try {
    summary.value = await refreshMarket()
    marketSources.value = (summary.value.sources || []).map(source => ({ ...source }))
    await loadPackages()
  } catch (e) {
    error.value = e.message || String(e)
  } finally {
    refreshing.value = false
  }
}

async function handleUpdateAllInstalled() {
  updating.value = true
  error.value = ''
  try {
    const result = await runMarketUpdates()
    await loadSummary()
    await loadPackages()
    syncSelectedPackageFromList()
    if (result.failed) {
      error.value = `已更新 ${result.updated || 0} 个包，${result.failed} 个失败`
    }
  } catch (e) {
    error.value = e.message || String(e)
  } finally {
    updating.value = false
  }
}

function openSourceDialog() {
  sourceDialogOpen.value = true
  loadSources().catch((e) => { error.value = e.message || String(e) })
}

function closeSourceDialog() {
  sourceDialogOpen.value = false
}

async function handleCreateSource() {
  if (!sourceDraft.url.trim()) {
    error.value = 'Market 源 URL 不能为空'
    return
  }
  error.value = ''
  try {
    await createMarketSource({
      name: sourceDraft.name.trim() || '第三方 Market',
      url: sourceDraft.url.trim(),
      enabled: true,
      allow_private: sourceDraft.allow_private,
    })
    sourceDraft.name = ''
    sourceDraft.url = ''
    sourceDraft.allow_private = false
    await loadSources()
  } catch (e) {
    error.value = e.message || String(e)
  }
}

async function handleUpdateSource(source) {
  error.value = ''
  try {
    await updateMarketSource(source.id, {
      name: source.name,
      url: source.url,
      enabled: source.enabled,
      allow_private: source.allow_private,
    })
    await loadSources()
  } catch (e) {
    error.value = e.message || String(e)
  }
}

async function handleDeleteSource(source) {
  if (!source?.id || source.is_builtin) return
  error.value = ''
  try {
    await deleteMarketSource(source.id)
    await loadSources()
  } catch (e) {
    error.value = e.message || String(e)
  }
}

async function handleRefreshSource(source) {
  if (!source?.id) return
  refreshing.value = true
  error.value = ''
  try {
    summary.value = await refreshMarketSource(source.id)
    marketSources.value = (summary.value.sources || []).map(item => ({ ...item }))
    await loadPackages()
  } catch (e) {
    error.value = e.message || String(e)
  } finally {
    refreshing.value = false
  }
}

function openDetail(pkg) {
  selectedPackage.value = pkg
  preview.value = null
  dialogOpen.value = true
}

function closeDialog() {
  dialogOpen.value = false
  selectedPackage.value = null
  preview.value = null
}

async function handlePreview(pkg) {
  if (!pkg?.id) return
  selectedPackage.value = pkg
  dialogOpen.value = true
  previewLoading.value = true
  error.value = ''
  try {
    preview.value = await previewMarketPackage(pkg.id)
  } catch (e) {
    error.value = e.message || String(e)
    preview.value = null
  } finally {
    previewLoading.value = false
  }
}

async function handleImport(pkg) {
  if (!pkg?.id) return
  importLoading.value = true
  error.value = ''
  try {
    const result = await importMarketPackage(pkg.id, preview.value?.preview_id || '')
    markPackageInstalled(pkg.id, result.subscription_id)
    preview.value = preview.value || { warnings: result.warnings || [], channel_count: result.channel_count, source_count: result.source_count, unsupported_source_count: 0, channels: [] }
  } catch (e) {
    error.value = e.message || String(e)
  } finally {
    importLoading.value = false
  }
}

async function handleReinstall(pkg) {
  if (!pkg?.id) return
  importLoading.value = true
  error.value = ''
  try {
    const result = await updateMarketPackage(pkg.id)
    markPackageInstalled(pkg.id, result.subscription_id)
    preview.value = preview.value || { warnings: result.warnings || [], channel_count: result.channel_count, source_count: result.source_count, unsupported_source_count: 0, channels: [] }
  } catch (e) {
    error.value = e.message || String(e)
  } finally {
    importLoading.value = false
  }
}

async function handleAutoUpdateChange(pkg, event) {
  if (!pkg?.id) return
  const enabled = Boolean(event?.target?.checked)
  installConfigLoading.value = true
  error.value = ''
  try {
    const result = await updateMarketInstall(pkg.id, { auto_update: enabled })
    setPackageAutoUpdate(pkg.id, result.auto_update)
  } catch (e) {
    error.value = e.message || String(e)
    if (event?.target) event.target.checked = !enabled
  } finally {
    installConfigLoading.value = false
  }
}

async function handleUninstall(pkg) {
  if (!pkg?.id) return
  importLoading.value = true
  error.value = ''
  try {
    await uninstallMarketPackage(pkg.id)
    packages.value = packages.value.map(item => item.id === pkg.id
      ? { ...item, installed: false, installed_subscription_id: null, installed_version: '', auto_update: false }
      : item)
    if (selectedPackage.value?.id === pkg.id) {
      selectedPackage.value = { ...selectedPackage.value, installed: false, installed_subscription_id: null, installed_version: '', auto_update: false }
    }
  } catch (e) {
    error.value = e.message || String(e)
  } finally {
    importLoading.value = false
  }
}

function markPackageInstalled(packageId, subscriptionId) {
  packages.value = packages.value.map(item => item.id === packageId
    ? { ...item, installed: true, installed_subscription_id: subscriptionId, installed_version: item.version || '', update_available: false }
    : item)
  if (selectedPackage.value?.id === packageId) {
    selectedPackage.value = { ...selectedPackage.value, installed: true, installed_subscription_id: subscriptionId, installed_version: selectedPackage.value.version || '', update_available: false }
  }
}

function setPackageAutoUpdate(packageId, autoUpdate) {
  packages.value = packages.value.map(item => item.id === packageId
    ? { ...item, auto_update: Boolean(autoUpdate) }
    : item)
  if (selectedPackage.value?.id === packageId) {
    selectedPackage.value = { ...selectedPackage.value, auto_update: Boolean(autoUpdate) }
  }
}

function syncSelectedPackageFromList() {
  if (!selectedPackage.value?.id) return
  const latest = packages.value.find(item => item.id === selectedPackage.value.id)
  if (latest) selectedPackage.value = { ...selectedPackage.value, ...latest }
}

watch(filters, () => {
  loadPackages()
}, { deep: true })

onMounted(async () => {
  await loadSummary().catch((e) => { error.value = e.message || String(e) })
  await loadPackages()
})
</script>

<style scoped>
.market-select {
  border-radius: 12px;
  border: 1px solid rgb(229 229 229);
  background: rgb(255 255 255 / 0.78);
  padding: 8px 12px;
  font-size: 12px;
  color: rgb(64 64 64);
  outline: none;
}

.market-input {
  border-radius: 12px;
  border: 1px solid rgb(229 229 229);
  background: rgb(255 255 255 / 0.78);
  padding: 8px 10px;
  font-size: 12px;
  color: rgb(64 64 64);
  outline: none;
}

.dark .market-select {
  border-color: rgb(64 64 64);
  background: rgb(23 23 23 / 0.72);
  color: rgb(212 212 212);
}

.dark .market-input {
  border-color: rgb(64 64 64);
  background: rgb(23 23 23 / 0.72);
  color: rgb(212 212 212);
}

.market-chip,
.market-info {
  border-radius: 8px;
  background: rgb(245 245 245);
  padding: 6px 8px;
}

.dark .market-chip,
.dark .market-info {
  background: rgb(38 38 38);
}

.market-detail-box {
  border-radius: 14px;
  background: rgb(245 245 245);
  padding: 10px 12px;
  color: rgb(115 115 115);
  line-height: 1.65;
}

.market-detail-box h3 {
  margin-bottom: 4px;
  font-weight: 700;
  color: rgb(38 38 38);
}

.dark .market-detail-box {
  background: rgb(38 38 38);
  color: rgb(163 163 163);
}

.dark .market-detail-box h3 {
  color: white;
}

.market-action {
  border-radius: 10px;
  background: rgb(245 245 245);
  padding: 7px 11px;
  font-size: 12px;
  font-weight: 500;
  color: rgb(82 82 82);
  transition: transform 0.15s ease, background 0.15s ease;
}

.market-action:hover:not(:disabled) {
  background: rgb(229 229 229);
  transform: translateY(-1px);
}

.market-action:disabled {
  cursor: not-allowed;
  opacity: 0.45;
}

.market-action.primary {
  background: rgb(23 23 23);
  color: white;
}

.dark .market-action {
  background: rgb(38 38 38);
  color: rgb(212 212 212);
}

.dark .market-action:hover:not(:disabled) {
  background: rgb(64 64 64);
}

.dark .market-action.primary {
  background: white;
  color: black;
}

.market-stat {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  border-radius: 14px;
  background: rgb(245 245 245);
  padding: 12px;
  color: rgb(82 82 82);
}

.market-stat b {
  color: rgb(23 23 23);
  font-size: 22px;
}

.dark .market-stat {
  background: rgb(38 38 38);
  color: rgb(163 163 163);
}

.dark .market-stat b {
  color: white;
}
</style>
