<template>
  <section aria-labelledby="plugins-settings-title">
    <header class="mb-6 flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
      <div>
        <h2 id="plugins-settings-title" class="text-xl font-semibold text-[var(--text-primary)]">Plugins</h2>
        <p class="mt-1.5 text-sm leading-6 text-[var(--text-secondary)]">管理已安装插件的运行状态、权限与 scheme ownership</p>
      </div>
      <RouterLink to="/market?type=plugins" class="inline-flex min-h-10 items-center justify-center rounded-xl border border-[var(--border)] px-4 text-sm font-medium text-[var(--text-primary)] hover:bg-[var(--surface-hover)]">
        前往 Market
      </RouterLink>
    </header>

    <section class="mb-6 rounded-2xl border border-amber-500/25 bg-amber-500/5 p-4 sm:p-5">
      <div class="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <h3 class="text-sm font-semibold text-[var(--text-primary)]">Developer Mode</h3>
          <p class="mt-1 text-xs leading-5 text-[var(--text-secondary)]">
            本地 Developer Plugin 不经过 WaveFlow Official 签名验证，但仍必须通过 manifest、digest、权限和隔离运行时校验。
          </p>
        </div>
        <button type="button" class="plugin-btn" :disabled="developerActing" @click="toggleDeveloperMode">
          {{ developerMode ? '关闭 Developer Mode' : '启用 Developer Mode' }}
        </button>
      </div>
      <div v-if="developerMode" class="mt-4 space-y-2">
        <label class="block text-xs font-medium text-[var(--text-secondary)]" for="developer-plugin-path">本地 package 目录、manifest.json 或 .pyz 路径</label>
        <div class="flex flex-col gap-2 sm:flex-row">
          <input id="developer-plugin-path" v-model="developerPath" type="text" class="min-h-10 min-w-0 flex-1 rounded-xl border border-[var(--border)] bg-[var(--card-bg)] px-3 text-sm text-[var(--text-primary)]" placeholder="/path/to/plugin/dist/manifest.json" />
          <label class="plugin-btn cursor-pointer" for="developer-plugin-file">选择文件</label>
          <input id="developer-plugin-file" type="file" class="hidden" accept=".json,.pyz" @change="selectDeveloperFile" />
          <button type="button" class="plugin-btn" :disabled="developerActing || !developerPath.trim()" @click="installLocalPlugin">安装本地 Plugin</button>
        </div>
        <p class="text-xs leading-5 text-[var(--text-tertiary)]">关闭 Developer Mode 不会删除已安装的本地插件；只会阻止新的 unsigned local install/update。</p>
      </div>
    </section>

    <section v-if="loading" class="grid gap-3 md:grid-cols-2" aria-label="正在加载插件" aria-busy="true">
      <div v-for="index in 4" :key="index" class="h-40 animate-pulse rounded-2xl border border-[var(--border)] bg-[var(--surface)]"></div>
    </section>

    <section v-else-if="loadError && !plugins.length" class="rounded-2xl border border-red-500/20 bg-red-500/5 px-6 py-10 text-center" role="alert">
      <h3 class="text-sm font-semibold text-[var(--text-primary)]">插件列表加载失败</h3>
      <p class="mt-2 text-sm text-[var(--text-secondary)]">{{ loadError }}</p>
      <button type="button" class="mt-4 min-h-10 rounded-xl border border-[var(--border)] px-4 text-sm font-medium text-[var(--text-primary)] hover:bg-[var(--surface-hover)]" @click="loadPlugins">重试</button>
    </section>

    <section v-else-if="!plugins.length" class="rounded-2xl border border-[var(--border)] bg-[var(--card-bg)] px-6 py-12 text-center">
      <h3 class="text-sm font-semibold text-[var(--text-primary)]">暂无已安装的 Plugins</h3>
      <p class="mt-2 text-sm text-[var(--text-secondary)]">可以前往 Market 安装扩展。</p>
      <RouterLink to="/market?type=plugins" class="mt-4 inline-flex min-h-10 items-center justify-center rounded-xl bg-[var(--text-primary)] px-4 text-sm font-semibold text-[var(--bg)]">打开 Market</RouterLink>
    </section>

    <template v-else>
      <p v-if="loadError" class="mb-3 rounded-xl border border-amber-500/20 bg-amber-500/5 px-4 py-3 text-sm text-amber-700 dark:text-amber-300" role="status">{{ loadError }}</p>
      <section class="grid gap-3 md:grid-cols-2">
        <article v-for="plugin in plugins" :key="plugin.plugin" class="flex min-w-0 flex-col rounded-2xl border border-[var(--border)] bg-[var(--card-bg)] p-4 sm:p-5">
          <button type="button" class="min-w-0 text-left outline-none focus-visible:ring-2 focus-visible:ring-[var(--border-strong)]" @click="openDetail(plugin)">
            <div class="flex min-w-0 items-start justify-between gap-3">
              <div class="min-w-0">
                <h3 class="truncate text-[15px] font-semibold text-[var(--text-primary)]">{{ plugin.display_name }}</h3>
                <p class="mt-1 truncate text-xs text-[var(--text-tertiary)]">{{ plugin.plugin }}</p>
              </div>
              <span class="plugin-status" :class="statusClass(plugin)">{{ statusLabel(plugin) }}</span>
            </div>
            <div class="mt-4 flex flex-wrap gap-1.5 text-xs text-[var(--text-secondary)]">
              <span class="plugin-chip">v{{ plugin.version || '未知' }}</span>
              <span class="plugin-chip">{{ runtimeLabel(plugin.runtime) }}</span>
              <span v-if="plugin.trust_class === 'developer_local'" class="plugin-chip plugin-chip-warning">Developer Local</span>
              <span v-if="plugin.permissions?.pending?.length" class="plugin-chip plugin-chip-warning">待批准 {{ plugin.permissions.pending.length }}</span>
              <span v-if="plugin.quarantined" class="plugin-chip plugin-chip-danger">Quarantined</span>
              <span v-if="plugin.market?.update_available" class="plugin-chip plugin-chip-update">有更新</span>
            </div>
            <dl class="mt-4 grid grid-cols-[72px_minmax(0,1fr)] gap-y-1.5 text-xs">
              <dt class="text-[var(--text-tertiary)]">Schemes</dt>
              <dd class="truncate text-[var(--text-primary)]">{{ plugin.owned_schemes?.join(', ') || '无' }}</dd>
              <dt class="text-[var(--text-tertiary)]">Ownership</dt>
              <dd class="truncate text-[var(--text-primary)]">{{ ownershipSummary(plugin) }}</dd>
            </dl>
          </button>
          <div class="mt-4 flex flex-wrap items-center justify-end gap-2 border-t border-[var(--border)] pt-3">
            <button type="button" class="plugin-btn" @click="openDetail(plugin)">详情</button>
            <button type="button" class="plugin-btn" :disabled="acting" @click="toggleEnabled(plugin)">{{ plugin.enabled ? '停用' : '启用' }}</button>
          </div>
        </article>
      </section>
    </template>
  </section>

  <Teleport to="body">
    <transition name="plugin-drawer">
      <div v-if="drawerOpen" class="fixed inset-0 z-[80] flex justify-end">
        <button type="button" class="absolute inset-0 bg-black/30 backdrop-blur-[2px]" aria-label="关闭插件详情" @click="closeDetail"></button>
        <aside class="relative flex h-full w-full max-w-xl flex-col border-l border-[var(--border)] bg-[var(--bg)] shadow-2xl" role="dialog" aria-modal="true" aria-labelledby="plugin-detail-title">
          <header class="flex items-start gap-3 border-b border-[var(--border)] px-5 py-4 sm:px-6">
            <div class="min-w-0 flex-1">
              <h2 id="plugin-detail-title" class="truncate text-lg font-semibold text-[var(--text-primary)]">{{ selected?.display_name || '插件详情' }}</h2>
              <p class="mt-1 truncate text-xs text-[var(--text-tertiary)]">{{ selected?.plugin }}</p>
            </div>
            <button type="button" class="flex size-9 items-center justify-center rounded-lg text-xl text-[var(--text-secondary)] hover:bg-[var(--surface-hover)]" aria-label="关闭" @click="closeDetail">×</button>
          </header>

          <div class="min-h-0 flex-1 overflow-y-auto px-5 py-5 sm:px-6">
            <div v-if="detailLoading" class="space-y-3" aria-busy="true"><div v-for="i in 4" :key="i" class="h-24 animate-pulse rounded-2xl bg-[var(--surface)]"></div></div>
            <section v-else-if="detailError" class="rounded-2xl border border-red-500/20 bg-red-500/5 px-5 py-8 text-center" role="alert">
              <p class="text-sm text-[var(--text-secondary)]">{{ detailError }}</p>
              <button type="button" class="plugin-btn mt-4" @click="reloadDetail">重试</button>
            </section>
            <template v-else-if="selected">
              <DetailSection title="运行状态">
                <dl class="plugin-detail-grid">
                  <dt>Lifecycle</dt><dd>{{ selected.lifecycle_state || 'unknown' }}</dd>
                  <dt>Enabled</dt><dd>{{ selected.enabled ? '已启用' : '已停用' }}</dd>
                  <dt>Runtime</dt><dd>{{ runtimeLabel(selected.runtime) }}</dd>
                  <dt>Environment</dt><dd>{{ environmentLabel(selected.runtime?.environment_status) }}</dd>
                  <dt>Trust</dt><dd>{{ trustLabel(selected.trust_state) }}</dd>
                </dl>
                <p v-if="selected.last_error" class="mt-3 rounded-xl border border-red-500/20 bg-red-500/5 px-3 py-2 text-xs leading-5 text-red-600 dark:text-red-300">{{ safeAdminDiagnostic(selected.last_error) }}</p>
                <div class="mt-4 flex flex-wrap gap-2">
                  <button type="button" class="plugin-btn" :disabled="acting" @click="toggleEnabled(selected)">{{ selected.enabled ? '停用插件' : '启用插件' }}</button>
                  <button v-if="selected.quarantined" type="button" class="plugin-btn plugin-btn-primary" :disabled="acting" @click="recoverSelected">恢复插件</button>
                </div>
              </DetailSection>

              <DetailSection title="Provider">
                <p class="text-xs text-[var(--text-secondary)]">{{ contractLabels(selected.provider_contracts) }}</p>
                <div v-if="selected.ownership?.length" class="mt-3 space-y-2">
                  <div v-for="item in selected.ownership" :key="item.scheme" class="flex flex-col gap-3 rounded-xl border border-[var(--border)] bg-[var(--surface)] p-3 sm:flex-row sm:items-center sm:justify-between">
                    <div><p class="text-sm font-medium text-[var(--text-primary)]">{{ item.scheme }}</p><p class="mt-1 text-xs text-[var(--text-secondary)]">当前：{{ item.mode === 'plugin' ? 'Plugin' : 'Legacy' }}</p></div>
                    <button type="button" class="plugin-btn" :disabled="acting || !selected.enabled" @click="switchOwnership(item)">{{ item.mode === 'plugin' ? '切换回 Legacy' : '切换到 Plugin' }}</button>
                  </div>
                </div>
              </DetailSection>

              <DetailSection title="Permissions">
                <div v-if="selected.permissions?.requested?.length" class="space-y-2">
                  <div v-for="permission in selected.permissions.requested" :key="permission.name" class="flex flex-col gap-3 rounded-xl border border-[var(--border)] bg-[var(--surface)] p-3 sm:flex-row sm:items-center sm:justify-between">
                    <div><p class="text-sm font-medium text-[var(--text-primary)]">{{ permissionLabel(permission.name) }}</p><p class="mt-1 text-xs" :class="permission.risk === 'high' ? 'text-red-600 dark:text-red-300' : 'text-[var(--text-secondary)]'">{{ permission.risk === 'high' ? '高风险权限' : '标准权限' }}</p></div>
                    <button v-if="isPending(permission.name)" type="button" class="plugin-btn plugin-btn-primary" :disabled="acting" @click="approvePermission(permission.name)">允许</button>
                    <button v-else-if="isRevocable(permission.name)" type="button" class="plugin-btn" :disabled="acting" @click="revokePermission(permission.name)">撤销</button>
                    <span v-else class="text-xs text-emerald-600 dark:text-emerald-300">已允许</span>
                  </div>
                </div>
                <p v-else class="text-sm text-[var(--text-secondary)]">此插件未申请额外权限。</p>
              </DetailSection>

              <DetailSection title="Dependencies">
                <p class="text-xs text-[var(--text-secondary)]">{{ selected.runtime?.dependency_count || 0 }} dependencies</p>
                <ul v-if="selected.runtime?.dependencies?.length" class="mt-3 divide-y divide-[var(--border)] rounded-xl border border-[var(--border)] bg-[var(--surface)] px-3">
                  <li v-for="dependency in selected.runtime.dependencies" :key="`${dependency.name}-${dependency.version}`" class="flex items-center justify-between gap-3 py-2.5 text-sm"><span class="truncate text-[var(--text-primary)]">{{ dependency.name }}</span><span class="shrink-0 text-xs text-[var(--text-tertiary)]">{{ dependency.version }}</span></li>
                </ul>
              </DetailSection>

              <DetailSection title="Package">
                <dl class="plugin-detail-grid"><dt>Version</dt><dd>{{ selected.version || '未知' }}</dd><dt>Source</dt><dd>{{ selected.source_provenance?.source_key || 'unknown' }}</dd><dt>Package</dt><dd class="truncate">{{ selected.market?.package_id || 'unknown' }}</dd></dl>
                <RouterLink :to="marketLink(selected)" class="plugin-btn plugin-btn-primary mt-4 inline-flex">{{ selected.market?.update_available ? '有可用更新 · 在 Market 中查看' : '在 Market 中查看' }}</RouterLink>
              </DetailSection>
            </template>
          </div>
        </aside>
      </div>
    </transition>
  </Teleport>
</template>

<script setup>
import { computed, defineComponent, h, onBeforeUnmount, onMounted, ref } from 'vue'
import { RouterLink } from 'vue-router'
import { approvePluginPermission, disablePlugin, enablePlugin, fetchDeveloperMode, fetchPlugin, fetchPlugins, installDeveloperPlugin, pluginErrorMessage, recoverPlugin, revokePluginPermission, setDeveloperMode, setPluginOwnership } from '../../api/plugins'
import { safeAdminDiagnostic } from '../../api/adminUi.js'
import { useToastStore } from '../../stores/toast'

const DetailSection = defineComponent({
  props: { title: { type: String, required: true } },
  setup(props, { slots }) { return () => h('section', { class: 'mb-4 rounded-2xl border border-[var(--border)] bg-[var(--card-bg)] p-4' }, [h('h3', { class: 'mb-3 text-sm font-semibold text-[var(--text-primary)]' }, props.title), slots.default?.()]) },
})

const toastStore = useToastStore()
const plugins = ref([])
const loading = ref(true)
const loadError = ref('')
const drawerOpen = ref(false)
const selected = ref(null)
const detailLoading = ref(false)
const detailError = ref('')
const acting = ref(false)
const developerMode = ref(false)
const developerPath = ref('')
const developerActing = ref(false)
const selectedIdentity = computed(() => selected.value?.plugin || '')
let listController = null
let detailController = null
let developerModeController = null
let componentDisposed = false

async function loadPlugins({ background = false } = {}) {
  if (componentDisposed) return
  listController?.abort()
  const controller = new AbortController()
  listController = controller
  if (!background) loading.value = true
  loadError.value = ''
  try {
    const result = await fetchPlugins({ signal: controller.signal })
    if (!controller.signal.aborted && !componentDisposed) plugins.value = result.plugins || []
  } catch (error) {
    if (!controller.signal.aborted && !componentDisposed) loadError.value = pluginErrorMessage(error, '插件列表加载失败')
  } finally {
    if (listController === controller && !componentDisposed && !background) loading.value = false
  }
}
async function openDetail(plugin) { drawerOpen.value = true; selected.value = plugin; detailError.value = ''; await loadDetail(plugin.plugin) }
async function loadDetail(identity) {
  detailController?.abort()
  const controller = new AbortController()
  detailController = controller
  detailLoading.value = true
  detailError.value = ''
  try {
    const result = await fetchPlugin(identity, { signal: controller.signal })
    if (controller.signal.aborted || componentDisposed || selected.value?.plugin !== identity) return
    selected.value = result
  } catch (error) {
    if (!controller.signal.aborted && !componentDisposed && selected.value?.plugin === identity) detailError.value = pluginErrorMessage(error, '插件详情加载失败')
  } finally {
    if (detailController === controller && !componentDisposed) detailLoading.value = false
  }
}
async function reloadDetail() { if (selectedIdentity.value) await loadDetail(selectedIdentity.value) }
function closeDetail() { detailController?.abort(); drawerOpen.value = false; selected.value = null; detailError.value = '' }
async function refreshAfterAction(identity = selectedIdentity.value) { await loadPlugins({ background: true }); if (drawerOpen.value && identity) await loadDetail(identity) }
async function loadDeveloperMode() {
  developerModeController?.abort()
  const controller = new AbortController()
  developerModeController = controller
  try {
    const result = await fetchDeveloperMode({ signal: controller.signal })
    if (!controller.signal.aborted && !componentDisposed) developerMode.value = Boolean(result.enabled)
  } catch (error) {
    if (!controller.signal.aborted && !componentDisposed) toastStore.error(pluginErrorMessage(error, 'Developer Mode 状态加载失败'))
  }
}
async function toggleDeveloperMode() {
  if (developerActing.value || componentDisposed) return
  developerActing.value = true
  try {
    const result = await setDeveloperMode(!developerMode.value)
    if (componentDisposed) return
    developerMode.value = Boolean(result.enabled)
    toastStore.success(developerMode.value ? 'Developer Mode 已启用' : 'Developer Mode 已关闭')
  } catch (error) {
    if (!componentDisposed) toastStore.error(pluginErrorMessage(error))
  } finally {
    if (!componentDisposed) developerActing.value = false
  }
}
function selectDeveloperFile(event) { const file = event.target?.files?.[0]; if (file?.path) developerPath.value = file.path; else if (file?.name) developerPath.value = file.name }
async function installLocalPlugin() {
  if (developerActing.value || !developerPath.value.trim() || componentDisposed) return
  developerActing.value = true
  try {
    await installDeveloperPlugin(developerPath.value.trim())
    if (componentDisposed) return
    toastStore.success('本地 Developer Plugin 已安装')
    await loadPlugins()
  } catch (error) {
    if (!componentDisposed) toastStore.error(pluginErrorMessage(error, '本地 Plugin 安装失败'))
  } finally {
    if (!componentDisposed) developerActing.value = false
  }
}

async function toggleEnabled(plugin) {
  const action = plugin.enabled ? '停用' : '启用'
  await runConfirmedAction(
    { title: `${action}插件`, message: plugin.enabled ? '停用不会自动切换 scheme ownership。若插件仍拥有 scheme，后端会拒绝此操作。' : '启用后插件恢复运行，但不会自动接管任何 scheme。', confirmText: action, danger: plugin.enabled },
    () => plugin.enabled ? disablePlugin(plugin.plugin) : enablePlugin(plugin.plugin),
    `插件已${action}`,
    plugin.plugin,
  )
}
async function recoverSelected() { const identity = selectedIdentity.value; await runConfirmedAction({ title: '恢复插件', message: 'WaveFlow 将清除 quarantine 状态。恢复后仍需显式启用或重新检查运行状态。', confirmText: '恢复' }, () => recoverPlugin(identity), '插件已恢复', identity) }
async function approvePermission(permission) { const identity = selectedIdentity.value; const packageId = selected.value?.market?.package_id || ''; await runConfirmedAction({ title: '允许高风险权限', message: permission === 'network.direct' ? '此插件需要直接访问网络。该能力不经过 Core managed HTTP，并非强安全沙箱。' : permission === 'network.managed_http' ? '此插件需要通过 Core managed HTTP 访问明文 HTTP。目标、DNS、重定向和 SSRF 检查仍然有效。' : `允许 ${permission}？`, confirmText: '允许并继续', danger: true }, () => approvePluginPermission(identity, permission, packageId), '权限已允许', identity) }
async function revokePermission(permission) { const identity = selectedIdentity.value; await runConfirmedAction({ title: '撤销权限', message: '撤销会停止插件运行。若 scheme 仍由此插件拥有，后端会拒绝并要求先切回 Legacy。', confirmText: '撤销', danger: true }, () => revokePluginPermission(identity, permission), '权限已撤销', identity) }
async function switchOwnership(item) { const identity = selectedIdentity.value; const toPlugin = item.mode !== 'plugin'; const message = toPlugin ? `切换后，${item.scheme}:// 来源将由 ${selected.value.display_name} 解析。Legacy Adapter 将保留，可随时回滚。` : `切换后，${item.scheme}:// 来源将重新由内置 Legacy Adapter 解析。`; await runConfirmedAction({ title: toPlugin ? '切换到 Plugin' : '切换回 Legacy', message, confirmText: toPlugin ? '切换到 Plugin' : '切换回 Legacy', danger: toPlugin }, () => setPluginOwnership(item.scheme, toPlugin ? 'plugin' : 'legacy', toPlugin ? identity : ''), `已切换到 ${toPlugin ? 'Plugin' : 'Legacy'}`, identity) }
async function runConfirmedAction(confirmOptions, action, success, identity) {
  if (acting.value || componentDisposed) return
  acting.value = true
  try {
    const ok = await toastStore.askConfirm(confirmOptions)
    if (!ok || componentDisposed) return
    await action()
    if (componentDisposed) return
    toastStore.success(success)
    await refreshAfterAction(identity)
  } catch (error) {
    if (!componentDisposed) toastStore.error(pluginErrorMessage(error))
  } finally {
    if (!componentDisposed) acting.value = false
  }
}

function statusLabel(plugin) { if (plugin.quarantined) return 'Quarantined'; if (!plugin.enabled) return '已停用'; if (isPluginCrashed(plugin)) return 'Crashed'; if (plugin.runtime_available) return 'Running'; return 'Unavailable' }
function statusClass(plugin) { if (plugin.quarantined || !plugin.runtime_available && plugin.enabled) return 'is-danger'; if (!plugin.enabled) return 'is-muted'; return 'is-healthy' }
function isPluginCrashed(plugin) { return plugin?.lifecycle_state === 'unavailable' && /\bPLUGIN_CRASHED\b/.test(String(plugin?.last_error || '')) }
function runtimeLabel(runtime) { if (runtime?.type === 'python') return runtime.python_version_range ? `Python ${runtime.python_version_range}` : 'Python'; if (runtime?.type === 'subprocess') return 'Binary / subprocess'; return runtime?.type || 'Unknown runtime' }
function environmentLabel(status) { return ({ ready: 'Healthy', unavailable: 'Unavailable', not_applicable: 'Not applicable' })[status] || status || 'Unknown' }
function trustLabel(value) { return ({ official: 'Official publisher', third_party: 'Trusted third party', developer_local: 'Developer Local（未经过 Official 签名）' })[value] || value || 'Unknown' }
function ownershipSummary(plugin) { const values = plugin.ownership || []; if (!values.length) return 'Legacy'; const owned = values.filter((item) => item.mode === 'plugin').length; return owned ? `${owned}/${values.length} Plugin` : 'Legacy' }
function contractLabels(contracts) { return (contracts || []).map((item) => item.contract === 'tv_provider' ? 'TVProvider' : item.contract === 'radio_provider' ? 'RadioProvider' : item.contract).join(' · ') || '无 Provider Contract' }
function permissionLabel(name) { return ({ 'network.managed': 'Managed Network', 'network.direct': 'Direct Network', 'network.managed_http': 'Managed Plain HTTP' })[name] || name }
function isPending(name) { return Boolean(selected.value?.permissions?.pending?.some((item) => item.name === name)) }
function isRevocable(name) { return (name === 'network.direct' || name === 'network.managed_http') && Boolean(selected.value?.permissions?.approved?.some((item) => item.name === name)) }
function marketLink(plugin) { const params = new URLSearchParams({ type: 'plugins' }); if (plugin?.market?.package_id) params.set('package', plugin.market.package_id); return `/market?${params}` }

onMounted(() => { loadPlugins(); loadDeveloperMode() })
onBeforeUnmount(() => {
  componentDisposed = true
  listController?.abort()
  detailController?.abort()
  developerModeController?.abort()
})
</script>

<style scoped>
.plugin-status,.plugin-chip{display:inline-flex;align-items:center;border:1px solid var(--border);border-radius:999px;padding:.2rem .55rem;white-space:nowrap}.plugin-status{font-size:.7rem}.plugin-status.is-healthy{color:#047857;border-color:rgb(16 185 129 / .25);background:rgb(16 185 129 / .08)}.plugin-status.is-danger,.plugin-chip-danger{color:#dc2626;border-color:rgb(239 68 68 / .25);background:rgb(239 68 68 / .07)}.plugin-status.is-muted{color:var(--text-tertiary)}.plugin-chip-warning{color:#b45309;border-color:rgb(245 158 11 / .25);background:rgb(245 158 11 / .08)}.plugin-chip-update{color:#0369a1;border-color:rgb(14 165 233 / .25);background:rgb(14 165 233 / .08)}.plugin-btn{display:inline-flex;min-height:var(--control-height-small);align-items:center;justify-content:center;border:1px solid var(--border);border-radius:var(--control-radius);padding:0 .8rem;font-size:.78rem;font-weight:500;color:var(--text-primary)}.plugin-btn:hover{background:var(--surface-hover)}.plugin-btn:disabled{cursor:not-allowed;opacity:.45}.plugin-btn-primary{border-color:var(--text-primary);background:var(--text-primary);color:var(--bg)}.plugin-detail-grid{display:grid;grid-template-columns:88px minmax(0,1fr);gap:.45rem;font-size:.8rem}.plugin-detail-grid dt{color:var(--text-tertiary)}.plugin-detail-grid dd{min-width:0;color:var(--text-primary)}.plugin-drawer-enter-active,.plugin-drawer-leave-active{transition:opacity .18s ease}.plugin-drawer-enter-from,.plugin-drawer-leave-to{opacity:0}
</style>
