import { ref } from 'vue'
import { API_BASE } from '../apiBase'

async function request(url, options = {}) {
  const ctrl = new AbortController()
  const timer = setTimeout(() => ctrl.abort(), options.timeout || 10_000)
  try {
    const res = await fetch(`${API_BASE}${url}`, { signal: ctrl.signal, ...options })
    clearTimeout(timer)
    if (!res.ok) throw new Error(`HTTP ${res.status}`)
    return res.json()
  } catch (e) {
    clearTimeout(timer)
    throw e
  }
}

export function useEpg() {
  const current = ref(null)
  const next = ref(null)
  const schedule = ref([])
  const selectedDate = ref('')
  const availableDates = ref([])
  const loading = ref(false)

  async function fetchPrograms(canonicalKey, options = {}) {
    if (!canonicalKey) return
    loading.value = true
    try {
      const params = new URLSearchParams()
      const tz = options.tz || Intl.DateTimeFormat().resolvedOptions().timeZone || 'Asia/Shanghai'
      if (options.date) params.set('date', options.date)
      if (tz) params.set('tz', tz)
      const qs = params.toString()
      const data = await request(`/api/iptv/epg/programs/${encodeURIComponent(canonicalKey)}${qs ? `?${qs}` : ''}`)
      current.value = data.current || null
      next.value = data.next || null
      schedule.value = data.programs || []
      selectedDate.value = data.date || options.date || ''
      availableDates.value = data.available_dates || []
    } catch (e) {
      console.warn('[EPG] fetch failed:', e?.message)
      current.value = null
      next.value = null
      schedule.value = []
      selectedDate.value = options.date || ''
      availableDates.value = []
    }
    loading.value = false
  }

  async function batchCurrent(canonicalKeys) {
    if (!canonicalKeys.length) return {}
    try {
      const res = await fetch(`${API_BASE}/api/iptv/epg/batch-current`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ canonical_keys: canonicalKeys }),
        signal: AbortSignal.timeout(8000),
      })
      if (!res.ok) return {}
      return res.json()
    } catch (e) {
      console.warn('[EPG] batch fetch failed:', e?.message)
      return {}
    }
  }

  return { current, next, schedule, selectedDate, availableDates, loading, fetchPrograms, batchCurrent }
}
