/**
 * 封面加载器：前端并发限制 + 去重 + Abort + IntersectionObserver + TTL Cache。
 *
 * - 最大并发 4
 * - 同一 canonical_key 不重复请求（复用 inflight Promise 或缓存结果）
 * - 切换分类时 AbortController 取消旧请求（signal 贯穿到 fetch）
 * - IntersectionObserver：仅加载视口附近频道
 * - 缓存 TTL：成功 30min、失败 30s、最大 2048 条目
 */

const MAX_CONCURRENT = 4
const CACHE_SUCCESS_TTL = 30 * 60 * 1000   // 30 min
const CACHE_FAILURE_TTL = 30 * 1000        // 30 s
const CACHE_MAX_ENTRIES = 2048

/** @type {Map<string, Promise<any>>} */
const _inflight = new Map()
/** @type {Map<string, {cover_url:string, avatar_url:string, expires:number}>} */
const _cache = new Map()
/** @type {AbortController|null} */
let _currentAbortController = null

let _pendingQueue = []
let _activeCount = 0

/**
 * 取消所有正在进行的封面请求（分类切换时调用）。
 * 外部 signal abort → 底层 fetch 真正取消。
 */
export function abortPendingCoverRequests() {
  if (_currentAbortController) {
    _currentAbortController.abort()
    _currentAbortController = null
  }
  // 唤醒所有排队等待者：它们会在 _enqueue 中检测到 signal.aborted 并快速退出，
  // 由 finally 正确递减 _activeCount。不直接置零 _activeCount 或丢弃等待者。
  while (_pendingQueue.length) {
    const resolve = _pendingQueue.shift()
    if (resolve) resolve()
  }
  _inflight.clear()
}

function _getAbortController() {
  if (!_currentAbortController || _currentAbortController.signal.aborted) {
    _currentAbortController = new AbortController()
  }
  return _currentAbortController
}

function _evictExpired() {
  const now = Date.now()
  for (const [key, entry] of _cache) {
    if (entry.expires <= now) _cache.delete(key)
  }
}

function _cacheGet(key) {
  const entry = _cache.get(key)
  if (!entry) return null
  if (entry.expires <= Date.now()) {
    _cache.delete(key)
    return null
  }
  return entry
}

function _cacheSet(key, cover_url, avatar_url, ttl) {
  if (_cache.size >= CACHE_MAX_ENTRIES) {
    _evictExpired()
    if (_cache.size >= CACHE_MAX_ENTRIES) {
      // 删最旧的条目
      const first = _cache.keys().next().value
      if (first) _cache.delete(first)
    }
  }
  _cache.set(key, { cover_url, avatar_url, expires: Date.now() + ttl })
}

/**
 * 请求单个频道的封面。请求自动受并发限制和去重。
 *
 * @param {string} canonicalKey
 * @param {function} fetchFn - (canonicalKey, signal) => Promise<{cover_url, avatar_url, ...}>
 * @returns {Promise<{cover_url:string, avatar_url:string}>}
 */
export async function loadCover(canonicalKey, fetchFn) {
  if (!canonicalKey) return { cover_url: '', avatar_url: '' }

  // 缓存命中
  const cached = _cacheGet(canonicalKey)
  if (cached) return { cover_url: cached.cover_url, avatar_url: cached.avatar_url }

  // 去重：已有 inflight
  const existing = _inflight.get(canonicalKey)
  if (existing) {
    try {
      return await existing
    } catch {
      return { cover_url: '', avatar_url: '' }
    }
  }

  // 排队等待并发槽位
  const ctrl = _getAbortController()
  const promise = _enqueue(canonicalKey, fetchFn, ctrl.signal)
  _inflight.set(canonicalKey, promise)
  try {
    const result = await promise
    const cover = String(result?.cover_url || '').trim()
    const avatar = String(result?.avatar_url || '').trim()
    const entry = { cover_url: cover, avatar_url: avatar }
    if (cover || avatar) {
      _cacheSet(canonicalKey, cover, avatar, CACHE_SUCCESS_TTL)
    } else {
      _cacheSet(canonicalKey, '', '', CACHE_FAILURE_TTL)
    }
    return entry
  } catch (e) {
    if (e?.name !== 'AbortError' && e?.message !== '请求已取消') {
      _cacheSet(canonicalKey, '', '', CACHE_FAILURE_TTL)
    }
    return { cover_url: '', avatar_url: '' }
  } finally {
    _inflight.delete(canonicalKey)
  }
}

async function _enqueue(key, fetchFn, signal) {
  while (_activeCount >= MAX_CONCURRENT) {
    await new Promise((resolve) => _pendingQueue.push(resolve))
  }
  _activeCount++
  try {
    return await fetchFn(key, signal)
  } finally {
    _activeCount--
    const next = _pendingQueue.shift()
    if (next) next()
  }
}

/**
 * 创建 IntersectionObserver 回调的工厂。
 *
 * @param {function} fetchFn - (canonicalKey, signal) => Promise
 * @returns {{ observer: IntersectionObserver, observe: (el, key) => void, disconnect: () => void }}
 */
export function createCoverObserver(fetchFn) {
  const pending = new Map()

  const observer = new IntersectionObserver(
    (entries) => {
      for (const entry of entries) {
        if (entry.isIntersecting) {
          const key = pending.get(entry.target)
          if (key) {
            pending.delete(entry.target)
            observer.unobserve(entry.target)
            loadCover(key, fetchFn)
          }
        }
      }
    },
    { rootMargin: '200px' }
  )

  return {
    observer,
    observe(el, key) {
      pending.set(el, key)
      observer.observe(el)
    },
    disconnect() {
      observer.disconnect()
      pending.clear()
    },
  }
}
