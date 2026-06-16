/**
 * 封面加载器：前端并发限制 + 去重 + Abort + IntersectionObserver。
 *
 * - 最大并发 4
 * - 同一 canonical_key 不重复请求（复用 inflight Promise 或缓存结果）
 * - 切换分类时 AbortController 取消旧请求
 * - IntersectionObserver：仅加载视口附近频道
 * - 非 adapter 频道也请求 /cover，后端快速返回 logo_url（已缓存）
 */

const MAX_CONCURRENT = 4

/** @type {Map<string, Promise<any>>} */
const _inflight = new Map()
/** @type {Map<string, {cover_url:string, avatar_url:string}>} */
const _cache = new Map()
/** @type {Set<string>} */
const _failed = new Set()
/** @type {AbortController|null} */
let _currentAbortController = null

let _pendingQueue = []
let _activeCount = 0

/**
 * 取消所有正在进行的封面请求（分类切换时调用）。
 */
export function abortPendingCoverRequests() {
  if (_currentAbortController) {
    _currentAbortController.abort()
    _currentAbortController = null
  }
  _pendingQueue = []
  _activeCount = 0
  _inflight.clear()
}

/**
 * 获取或创建 AbortController。
 */
function _getAbortController() {
  if (!_currentAbortController || _currentAbortController.signal.aborted) {
    _currentAbortController = new AbortController()
  }
  return _currentAbortController
}

/**
 * 请求单个频道的封面。请求自动受并发限制和去重。
 *
 * @param {string} canonicalKey
 * @param {function} fetchFn - 实际请求函数 (key) => Promise
 * @returns {Promise<{cover_url:string, avatar_url:string}>}
 */
export async function loadCover(canonicalKey, fetchFn) {
  if (!canonicalKey) return { cover_url: '', avatar_url: '' }

  // 缓存命中
  const cached = _cache.get(canonicalKey)
  if (cached) return cached

  // 失败缓存（30s 内不重试）
  if (_failed.has(canonicalKey)) return { cover_url: '', avatar_url: '' }

  // 去重：已有 inflight
  const existing = _inflight.get(canonicalKey)
  if (existing) return existing

  // 排队等待并发槽位
  const promise = _enqueue(canonicalKey, fetchFn)
  _inflight.set(canonicalKey, promise)
  try {
    const result = await promise
    const cover = String(result?.cover_url || '').trim()
    const avatar = String(result?.avatar_url || '').trim()
    const entry = { cover_url: cover, avatar_url: avatar }
    if (cover || avatar) {
      _cache.set(canonicalKey, entry)
    } else {
      _failed.add(canonicalKey)
      // 30s 后允许重试
      setTimeout(() => _failed.delete(canonicalKey), 30_000)
    }
    return entry
  } catch (e) {
    if (e?.name !== 'AbortError') {
      _failed.add(canonicalKey)
      setTimeout(() => _failed.delete(canonicalKey), 30_000)
    }
    return { cover_url: '', avatar_url: '' }
  } finally {
    _inflight.delete(canonicalKey)
  }
}

async function _enqueue(key, fetchFn) {
  // 等待槽位
  while (_activeCount >= MAX_CONCURRENT) {
    await new Promise((resolve) => _pendingQueue.push(resolve))
  }
  _activeCount++
  try {
    const ctrl = _getAbortController()
    return await fetchFn(key, ctrl.signal)
  } finally {
    _activeCount--
    // 释放下一个等待者
    const next = _pendingQueue.shift()
    if (next) next()
  }
}

/**
 * 创建 IntersectionObserver 回调的工厂。
 * 当元素进入视口时触发 loadCover。
 *
 * @param {function} fetchFn - (canonicalKey, signal) => Promise
 * @returns {{ observer: IntersectionObserver, observe: (el, key) => void }}
 */
export function createCoverObserver(fetchFn) {
  const pending = new Map() // element -> key

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
    { rootMargin: '200px' } // 提前 200px 加载
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
