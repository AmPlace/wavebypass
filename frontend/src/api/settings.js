import { apiRequest } from './client'

export async function fetchSecuritySettings() {
  const res = await apiRequest('/api/admin/settings/security')
  return res.json()
}

export async function updateSecuritySettings(payload) {
  const res = await apiRequest('/api/admin/settings/security', {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload || {}),
  })
  return res.json()
}
