export const CONTENT_PACKAGE = 'content_package'
export const PLUGIN_PACKAGE = 'plugin_package'

export function isPluginPackage(pkg) {
  return pkg?.package_type === PLUGIN_PACKAGE
}

export function pluginIdentity(pkg) {
  const plugin = pkg?.plugin || pkg?.plugin_manifest || {}
  const publisher = String(plugin.publisher_id || '')
  const id = String(plugin.plugin_id || '')
  return publisher && id ? `${publisher}/${id}` : ''
}

export function packageInstallable(pkg) {
  return isPluginPackage(pkg) ? Boolean(pkg?.plugin_installable) : Boolean(pkg?.supported_in_v1 && pkg?.importable)
}

export function packageActionLabel(pkg, action) {
  if (!isPluginPackage(pkg)) return ({ install: '导入', installing: '导入中…', update: '更新', updating: '更新中…', uninstall: '卸载' })[action] || action
  return ({ install: '安装 Plugin', installing: '安装中…', update: '更新 Plugin', updating: '更新中…', uninstall: '卸载 Plugin' })[action] || action
}

export function providerContractLabels(pkg) {
  const values = pkg?.plugin?.provider_contracts || pkg?.plugin_manifest?.provider_contracts || []
  return values.map((item) => {
    const contract = typeof item === 'string' ? item : item?.contract
    if (contract === 'tv_provider') return 'TVProvider'
    if (contract === 'radio_provider') return 'RadioProvider'
    return contract
  }).filter(Boolean)
}

export function pluginSchemeLabels(pkg) {
  const values = pkg?.plugin?.owned_schemes || pkg?.plugin_manifest?.owned_schemes || []
  return values.map((item) => typeof item === 'string' ? item : item?.scheme)
    .filter(Boolean)
    .map(String)
}

export function requestedPermissions(pkg) {
  const values = pkg?.plugin?.permissions || Object.keys(pkg?.plugin_manifest?.permissions || {})
  if (Array.isArray(values)) return values.map(String)
  return []
}

export function permissionLabel(name) {
  return ({ 'network.managed': 'Managed Network', 'network.direct': 'Direct Network', 'network.managed_http': 'Managed Plain HTTP' })[name] || name
}

export function pluginRuntimeLabel(pkg) {
  const runtime = pkg?.plugin_manifest?.runtime || {}
  if (runtime.type === 'python') return runtime.python_version_range ? `Python ${runtime.python_version_range}` : 'Python'
  const platforms = pkg?.plugin?.platforms || []
  const kinds = new Set(platforms.map((item) => item.runtime).filter(Boolean))
  return kinds.has('python') ? 'Python' : runtime.type === 'subprocess' ? 'Binary / subprocess' : 'Subprocess'
}

export function pluginDependencies(pkg) {
  const lock = pkg?.plugin_manifest?.runtime?.dependency_lock || {}
  const items = Array.isArray(lock.artifacts) ? lock.artifacts : []
  const seen = new Set()
  return items.filter((item) => {
    const key = `${item?.name || ''}@${item?.version || ''}`
    if (!item?.name || seen.has(key)) return false
    seen.add(key)
    return true
  }).map(item => ({ name: String(item.name), version: String(item.version || '') }))
}
