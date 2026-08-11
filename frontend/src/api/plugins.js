import { apiRequest } from './client.js'

const JSON_HEADERS = { 'Content-Type': 'application/json' }

function pluginPath(identity) {
  const [publisher, plugin] = String(identity || '').split('/')
  return `${encodeURIComponent(publisher || '')}/${encodeURIComponent(plugin || '')}`
}

export async function fetchPlugins() {
  const response = await apiRequest('/api/admin/plugins')
  return response.json()
}

export async function fetchPlugin(identity) {
  const response = await apiRequest(`/api/admin/plugins/${pluginPath(identity)}`)
  return response.json()
}

export async function enablePlugin(identity) {
  const response = await apiRequest(`/api/admin/plugins/${pluginPath(identity)}/enable`, { method: 'POST' })
  return response.json()
}

export async function disablePlugin(identity) {
  const response = await apiRequest(`/api/admin/plugins/${pluginPath(identity)}/disable`, { method: 'POST' })
  return response.json()
}

export async function recoverPlugin(identity) {
  const response = await apiRequest(`/api/admin/plugins/${pluginPath(identity)}/recover`, { method: 'POST' })
  return response.json()
}

export async function approvePluginPermission(identity, permission, packageId = '') {
  const response = await apiRequest(`/api/admin/plugins/${pluginPath(identity)}/permissions/approve`, {
    method: 'POST', headers: JSON_HEADERS, body: JSON.stringify({ permission, package_id: packageId }),
  })
  return response.json()
}

export async function revokePluginPermission(identity, permission) {
  const response = await apiRequest(`/api/admin/plugins/${pluginPath(identity)}/permissions/revoke`, {
    method: 'POST', headers: JSON_HEADERS, body: JSON.stringify({ permission }),
  })
  return response.json()
}

export async function setPluginOwnership(scheme, mode, identity = '') {
  const response = await apiRequest(`/api/admin/plugins/ownership/${encodeURIComponent(scheme)}`, {
    method: 'PUT', headers: JSON_HEADERS, body: JSON.stringify({ mode, plugin: identity }),
  })
  return response.json()
}

export function pluginErrorCode(error) {
  const payload = error?.detail?.detail || error?.detail || null
  return typeof payload === 'object' && payload ? String(payload.code || '') : ''
}

export function pluginErrorDetails(error) {
  const payload = error?.detail?.detail || error?.detail || null
  return typeof payload === 'object' && payload && typeof payload.details === 'object' ? payload.details : {}
}

export function pluginErrorMessage(error, fallback = '插件操作失败，请稍后重试') {
  const messages = {
    RESOURCE_NOT_FOUND: '插件或 Market 包不存在，请刷新后重试',
    PLUGIN_UNAVAILABLE: '插件运行时当前不可用',
    PLUGIN_QUARANTINED: '插件已被隔离，需要先执行恢复',
    PLUGIN_UNTRUSTED: '插件发布者尚未被信任',
    PLATFORM_UNSUPPORTED: '当前平台不支持这个插件',
    PLUGIN_INCOMPATIBLE: '插件版本与当前 WaveFlow 不兼容',
    PERMISSION_APPROVAL_REQUIRED: '安装前需要批准高风险权限',
    SCHEME_CONFLICT: '请先将相关 scheme 切回 Legacy，再执行此操作',
    CAPABILITY_DENIED: '当前权限策略不允许此操作',
  }
  return messages[pluginErrorCode(error)] || fallback
}
