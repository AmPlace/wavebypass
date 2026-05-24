const desktopApiBase = typeof window !== 'undefined'
  ? window.WAVEFLOW_DESKTOP?.apiBase
  : ''

const currentOrigin = typeof window !== 'undefined' && /^https?:$/.test(window.location.protocol)
  ? window.location.origin
  : ''

export const API_BASE = desktopApiBase || import.meta.env.VITE_API_BASE_URL || currentOrigin || ''
