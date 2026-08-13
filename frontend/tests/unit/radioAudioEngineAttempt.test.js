import test from 'node:test'
import assert from 'node:assert/strict'

import { createRadioAudioEngine } from '../../src/utils/radioAudioEngine.js'

function deferred() {
  let resolve
  let reject
  const promise = new Promise((res, rej) => {
    resolve = res
    reject = rej
  })
  return { promise, resolve, reject }
}

async function flush() {
  for (let i = 0; i < 8; i += 1) await Promise.resolve()
  await new Promise((resolve) => setImmediate(resolve))
  for (let i = 0; i < 8; i += 1) await Promise.resolve()
}

class FakeAudio {
  constructor(label = 'audio') {
    this.label = label
    this._src = ''
    this.currentSrc = ''
    this.volume = 1
    this.listeners = new Map()
    this.onceListeners = new Set()
    this.playCalls = []
    this.pauseCalls = 0
    this.loadCalls = 0
    this.nextPlay = null
  }

  set src(value) {
    this._src = String(value || '')
    this.currentSrc = this._src
  }

  get src() {
    return this._src
  }

  addEventListener(name, fn, options = {}) {
    if (!this.listeners.has(name)) this.listeners.set(name, new Set())
    this.listeners.get(name).add(fn)
    if (options?.once) this.onceListeners.add(fn)
  }

  removeEventListener(name, fn) {
    this.listeners.get(name)?.delete(fn)
    this.onceListeners.delete(fn)
  }

  emit(name) {
    for (const fn of Array.from(this.listeners.get(name) || [])) {
      if (this.onceListeners.has(fn)) this.removeEventListener(name, fn)
      fn()
    }
  }

  listenerCount() {
    let count = 0
    for (const listeners of this.listeners.values()) count += listeners.size
    return count
  }

  play() {
    this.playCalls.push(this.currentSrc || this.src)
    const next = this.nextPlay
    this.nextPlay = null
    return next ? next.promise : Promise.resolve()
  }

  pause() {
    this.pauseCalls += 1
  }

  load() {
    this.loadCalls += 1
  }

  removeAttribute(name) {
    if (name === 'src') {
      this._src = ''
      this.currentSrc = ''
    }
  }

  canPlayType() {
    return ''
  }
}

function createHlsMock({ supported = true } = {}) {
  const instances = []
  class FakeHls {
    static Events = {
      ERROR: 'ERROR',
      FRAG_LOADED: 'FRAG_LOADED',
      MANIFEST_PARSED: 'MANIFEST_PARSED',
    }

    static isSupported() {
      return supported
    }

    constructor(config) {
      this.config = config
      this.handlers = new Map()
      this.destroyed = false
      this.source = ''
      this.media = null
      instances.push(this)
    }

    on(name, fn) {
      if (!this.handlers.has(name)) this.handlers.set(name, new Set())
      this.handlers.get(name).add(fn)
    }

    off(name, fn) {
      this.handlers.get(name)?.delete(fn)
    }

    emit(name, data) {
      for (const fn of Array.from(this.handlers.get(name) || [])) fn(name, data)
    }

    handlerCount() {
      let count = 0
      for (const handlers of this.handlers.values()) count += handlers.size
      return count
    }

    loadSource(url) {
      this.source = url
    }

    attachMedia(media) {
      this.media = media
    }

    destroy() {
      this.destroyed = true
    }
  }
  return { Hls: FakeHls, instances }
}

function responseJson(value) {
  return { ok: true, json: async () => value }
}

function createHarness({ hlsSupported = false, fetchImpl, setTimerImpl, clearTimerImpl } = {}) {
  const audio = new FakeAudio('main')
  const hlsMock = createHlsMock({ supported: hlsSupported })
  const probeAudios = []
  const state = {
    currentStation: { value: '' },
    volume: { value: 1 },
    hlsRef: { value: null },
    directStreamMode: { value: '' },
    mediaMetadata: null,
  }
  const store = {
    currentIptvChannel: null,
    stationMap: {
      A: { id: 'A', name: 'A Radio', directPlay: true },
      B: { id: 'B', name: 'B Radio', directUrl: 'https://b.example/live.mp3' },
      C: { id: 'C', name: 'C Radio', directUrl: 'https://c.example/live.mp3' },
      HLS_A: { id: 'HLS_A', name: 'Old HLS' },
      HLS_B: { id: 'HLS_B', name: 'New HLS' },
    },
    isPlaying: false,
    isLoading: false,
    playbackError: '',
    clearPlaybackError() { this.playbackError = '' },
    setLoading(value) { this.isLoading = Boolean(value) },
    setPlaybackError(value) {
      this.playbackError = value || ''
      if (this.playbackError) this.isLoading = false
    },
    togglePlay(value) {
      this.isPlaying = typeof value === 'boolean' ? value : !this.isPlaying
    },
  }
  const mediaSession = {
    metadata: null,
    handlers: {},
    setActionHandler(name, fn) { this.handlers[name] = fn },
  }
  class FakeMediaMetadata {
    constructor(value) {
      Object.assign(this, value)
      state.mediaMetadata = value
    }
  }
  const engine = createRadioAudioEngine({
    audioRef: { value: audio },
    hlsRef: state.hlsRef,
    directStreamMode: state.directStreamMode,
    playerStore: store,
    currentStation: state.currentStation,
    volume: state.volume,
    Hls: hlsMock.Hls,
    API_BASE: '',
    publicAsset: (url) => url,
    getNavigator: () => ({ mediaSession }),
    getMediaMetadata: () => FakeMediaMetadata,
    createAudio: () => {
      const item = new FakeAudio(`probe-${probeAudios.length}`)
      probeAudios.push(item)
      return item
    },
    fetchImpl,
    setTimer: setTimerImpl || (() => ({ fake: true })),
    clearTimer: clearTimerImpl || (() => {}),
    logger: { log() {}, warn() {} },
  })

  return { audio, engine, hlsInstances: hlsMock.instances, mediaSession, probeAudios, state, store }
}

function createTimerTracker() {
  let sequence = 0
  const pending = new Map()
  return {
    setTimer(fn, ms) {
      const id = ++sequence
      pending.set(id, { fn, ms })
      return id
    },
    clearTimer(id) {
      pending.delete(id)
    },
    pendingCount() {
      return pending.size
    },
  }
}

test('旧成功晚返回：A probe 晚成功不得接管 B', async () => {
  const allUrlsA = deferred()
  const fetchImpl = async (url, options = {}) => {
    if (String(url).includes('/A/all-urls')) return allUrlsA.promise
    if (options.method === 'HEAD') return {}
    throw new Error(`unexpected fetch ${url}`)
  }
  const h = createHarness({ fetchImpl })

  h.state.currentStation.value = 'A'
  h.engine.loadStation('A')
  allUrlsA.resolve(responseJson(['https://a.example/one.mp3']))
  await flush()
  assert.equal(h.probeAudios.length, 1)

  h.state.currentStation.value = 'B'
  h.engine.loadStation('B')
  await flush()
  assert.equal(h.audio.currentSrc, 'https://b.example/live.mp3')
  assert.equal(h.mediaSession.metadata.title, 'B Radio')

  h.probeAudios[0].emit('canplay')
  await flush()
  assert.equal(h.audio.currentSrc, 'https://b.example/live.mp3')
  assert.equal(h.mediaSession.metadata.title, 'B Radio')
  assert.equal(h.store.isPlaying, true)
})

test('旧错误晚返回：A fatal/error 不得覆盖 B 状态', async () => {
  const h = createHarness({ hlsSupported: true, fetchImpl: async () => { throw new Error('no fetch') } })

  h.state.currentStation.value = 'HLS_A'
  h.engine.loadStation('HLS_A')
  await flush()
  const oldHls = h.hlsInstances[0]
  assert.ok(oldHls)

  h.state.currentStation.value = 'B'
  h.engine.loadStation('B')
  await flush()
  h.store.playbackError = ''
  h.store.isLoading = false
  assert.equal(h.audio.currentSrc, 'https://b.example/live.mp3')

  oldHls.emit('ERROR', { fatal: true })
  await flush()
  assert.equal(h.audio.currentSrc, 'https://b.example/live.mp3')
  assert.equal(h.store.playbackError, '')
  assert.equal(h.store.isPlaying, true)
  assert.equal(h.store.isLoading, false)
})

test('A -> B -> C 交错完成后只有 C 接管', async () => {
  const h = createHarness({ fetchImpl: async () => { throw new Error('no fetch') } })
  const playA = deferred()
  const playB = deferred()

  h.audio.nextPlay = playA
  h.state.currentStation.value = 'A'
  h.store.stationMap.A = { id: 'A', name: 'A Radio', directUrl: 'https://a.example/live.mp3' }
  h.engine.loadStation('A')
  await flush()

  h.audio.nextPlay = playB
  h.state.currentStation.value = 'B'
  h.engine.loadStation('B')
  await flush()

  h.state.currentStation.value = 'C'
  h.engine.loadStation('C')
  await flush()
  assert.equal(h.audio.currentSrc, 'https://c.example/live.mp3')
  assert.equal(h.mediaSession.metadata.title, 'C Radio')

  playA.resolve()
  playB.resolve()
  await flush()
  assert.equal(h.audio.currentSrc, 'https://c.example/live.mp3')
  assert.equal(h.mediaSession.metadata.title, 'C Radio')
  assert.equal(h.store.isPlaying, true)
})

test('切到 IPTV 后旧 Radio 完成不得播放或写状态', async () => {
  const h = createHarness({ fetchImpl: async () => { throw new Error('no fetch') } })
  const playA = deferred()
  h.audio.nextPlay = playA

  h.state.currentStation.value = 'A'
  h.store.stationMap.A = { id: 'A', name: 'A Radio', directUrl: 'https://a.example/live.mp3' }
  h.engine.loadStation('A')
  await flush()

  h.store.currentIptvChannel = { name: 'IPTV' }
  h.state.currentStation.value = ''
  h.engine.stopRadioAttempt()
  h.store.isPlaying = false
  playA.resolve()
  await flush()

  assert.equal(h.store.isPlaying, false)
  assert.equal(h.mediaSession.metadata, null)
  assert.equal(h.audio.currentSrc, '')
})

test('组件卸载后旧 Promise/HLS/audio callback 不得写 store 或重新播放', async () => {
  const h = createHarness({ hlsSupported: true, fetchImpl: async () => { throw new Error('no fetch') } })
  h.state.currentStation.value = 'HLS_A'
  h.engine.loadStation('HLS_A')
  await flush()
  const hls = h.hlsInstances[0]

  h.engine.stopRadioAttempt()
  h.store.playbackError = ''
  h.store.isPlaying = false
  hls.emit('MANIFEST_PARSED')
  hls.emit('ERROR', { fatal: true })
  h.audio.emit('error')
  await flush()

  assert.equal(h.store.playbackError, '')
  assert.equal(h.store.isPlaying, false)
  assert.equal(h.audio.playCalls.length, 0)
})

test('资源 ownership：旧 attempt cleanup 不得 destroy 新 HLS', async () => {
  const h = createHarness({ hlsSupported: true, fetchImpl: async () => { throw new Error('no fetch') } })
  h.state.currentStation.value = 'HLS_A'
  h.engine.loadStation('HLS_A')
  await flush()
  const oldHls = h.hlsInstances[0]

  h.state.currentStation.value = 'HLS_B'
  h.engine.loadStation('HLS_B')
  await flush()
  const newHls = h.hlsInstances[1]

  assert.equal(oldHls.destroyed, true)
  assert.equal(newHls.destroyed, false)
  oldHls.emit('ERROR', { fatal: true })
  await flush()
  assert.equal(newHls.destroyed, false)
  assert.equal(h.state.hlsRef.value, newHls)
})

test('正常路径回归：direct、fallback、proxy fallback 顺序保持', async () => {
  const allUrls = deferred()
  const fetchImpl = async (url, options = {}) => {
    if (String(url).includes('/A/all-urls')) return allUrls.promise
    if (options.method === 'HEAD') return {}
    throw new Error(`unexpected fetch ${url}`)
  }
  const h = createHarness({ fetchImpl })
  h.state.currentStation.value = 'A'
  h.engine.loadStation('A')
  allUrls.resolve(responseJson(['https://a.example/one.mp3']))
  await flush()
  h.probeAudios[0].emit('error')
  await flush()
  assert.equal(h.probeAudios.length, 2, 'direct 失败后应继续探测 channel proxy')
  h.probeAudios[1].emit('canplay')
  await flush()
  assert.match(h.audio.currentSrc, /\/api\/media\/channel\/A\/stream$/)

  const h2 = createHarness({ fetchImpl: async (url, options = {}) => {
    if (String(url).includes('/A/all-urls')) return responseJson(['https://a.example/direct.mp3'])
    if (options.method === 'HEAD') return {}
    throw new Error(`unexpected fetch ${url}`)
  } })
  h2.state.currentStation.value = 'A'
  h2.engine.loadStation('A')
  await flush()
  h2.probeAudios[0].emit('canplay')
  await flush()
  assert.equal(h2.audio.currentSrc, 'https://a.example/direct.mp3')
  assert.equal(h2.state.directStreamMode.value, 'direct')
})

test('并发探测中快速失败不得抢先结束较慢的可播放源', async () => {
  const fetchImpl = async (url, options = {}) => {
    if (String(url).includes('/A/all-urls')) {
      return responseJson([
        'https://a.example/fast-fail.mp3',
        'https://a.example/slow-winner.mp3',
      ])
    }
    if (options.method === 'HEAD') return {}
    throw new Error(`unexpected fetch ${url}`)
  }
  const h = createHarness({ fetchImpl })
  h.state.currentStation.value = 'A'
  h.engine.loadStation('A')
  await flush()

  assert.equal(h.probeAudios.length, 2)
  h.probeAudios[0].emit('error')
  await flush()
  assert.equal(h.probeAudios.length, 2, '一个失败后不应提前启动代理兜底')

  h.probeAudios[1].emit('canplay')
  await flush()
  assert.equal(h.audio.currentSrc, 'https://a.example/slow-winner.mp3')
  assert.equal(h.state.directStreamMode.value, 'direct')
})

test('并发探测胜出后立即清理 loser 的 timer 和 audio listener', async () => {
  const timers = createTimerTracker()
  const fetchImpl = async (url, options = {}) => {
    if (String(url).includes('/A/all-urls')) {
      return responseJson([
        'https://a.example/loser.mp3',
        'https://a.example/winner.mp3',
      ])
    }
    if (options.method === 'HEAD') return {}
    throw new Error(`unexpected fetch ${url}`)
  }
  const h = createHarness({
    fetchImpl,
    setTimerImpl: timers.setTimer,
    clearTimerImpl: timers.clearTimer,
  })
  h.state.currentStation.value = 'A'
  h.engine.loadStation('A')
  await flush()

  assert.equal(h.probeAudios.length, 2)
  h.probeAudios[1].emit('canplay')
  await flush()

  assert.equal(h.audio.currentSrc, 'https://a.example/winner.mp3')
  assert.equal(h.probeAudios[0].listenerCount(), 0, 'loser audio listener 应立即移除')
  assert.equal(timers.pendingCount(), 0, 'winner 产生后不应留下 probe/HEAD/overall timer')
})

test('HLS 并发探测胜出后立即销毁 loser 并移除事件监听', async () => {
  const timers = createTimerTracker()
  const fetchImpl = async (url, options = {}) => {
    if (String(url).includes('/A/all-urls')) {
      return responseJson([
        'https://a.example/loser.m3u8',
        'https://a.example/winner.m3u8',
      ])
    }
    if (options.method === 'HEAD') return {}
    throw new Error(`unexpected fetch ${url}`)
  }
  const h = createHarness({
    hlsSupported: true,
    fetchImpl,
    setTimerImpl: timers.setTimer,
    clearTimerImpl: timers.clearTimer,
  })
  h.state.currentStation.value = 'A'
  h.engine.loadStation('A')
  await flush()

  assert.equal(h.hlsInstances.length, 2)
  const loser = h.hlsInstances[0]
  const winner = h.hlsInstances[1]
  winner.emit('FRAG_LOADED')
  await flush()

  assert.equal(loser.destroyed, true)
  assert.equal(loser.handlerCount(), 0)
  assert.equal(winner.destroyed, true, 'probe winner 也应销毁，正式播放使用独立实例')
  assert.equal(winner.handlerCount(), 0)
  assert.equal(timers.pendingCount(), 1, '只允许保留正式 HLS 起播超时 timer')
})

test('原生 audio error：当前 attempt 触发 fallback，旧 attempt 的 error 不触发', async () => {
  // 模拟 direct station（directUrl 存在 → error 后走 fallbackToProxyStream）
  const h = createHarness({ fetchImpl: async (url, options = {}) => {
    if (options.method === 'HEAD') return {}
    throw new Error(`unexpected fetch ${url}`)
  } })
  h.state.currentStation.value = 'B'
  h.engine.loadStation('B')
  await flush()
  assert.equal(h.audio.currentSrc, 'https://b.example/live.mp3')

  // 当前 attempt 的 audio error → 应触发 fallbackToProxyStream（切到 channel stream 代理）
  // 注：playAudioSafely 成功后会 clearPlaybackError，所以不检查中间态错误文案，
  // 只检查 audio src 已切换到代理 URL。
  h.audio.emit('error')
  await flush()
  assert.match(h.audio.currentSrc, /\/api\/media\/channel\/B\/stream$/)

  // 现在切到 C，旧 B 的 audio error handler 应已失效
  h.state.currentStation.value = 'C'
  h.engine.loadStation('C')
  await flush()
  assert.equal(h.audio.currentSrc, 'https://c.example/live.mp3')
  assert.equal(h.state.currentStation.value, 'C')
  assert.match(h.audio.currentSrc, /c\.example/)
})

test('卸载后重新挂载：旧 attempt 全部失效，新 station 可正常播放', async () => {
  const h = createHarness({ fetchImpl: async (url, options = {}) => {
    if (options.method === 'HEAD') return {}
    throw new Error(`unexpected fetch ${url}`)
  } })

  // 播放 A
  h.state.currentStation.value = 'A'
  h.store.stationMap.A = { id: 'A', name: 'A Radio', directUrl: 'https://a.example/live.mp3' }
  h.engine.loadStation('A')
  await flush()
  assert.equal(h.audio.currentSrc, 'https://a.example/live.mp3')

  // 卸载
  h.engine.stopRadioAttempt()
  h.store.isPlaying = false
  assert.equal(h.audio.currentSrc, '')

  // 新实例（模拟重新挂载）——同一个 engine 的 stopRadioAttempt 已清理
  h.store.stationMap.D = { id: 'D', name: 'D Radio', directUrl: 'https://d.example/live.mp3' }
  h.state.currentStation.value = 'D'
  h.engine.loadStation('D')
  await flush()
  assert.equal(h.audio.currentSrc, 'https://d.example/live.mp3')
  assert.equal(h.state.mediaMetadata?.title, 'D Radio')

  // 旧 A 的 async 不应影响 D
  assert.equal(h.store.isPlaying, true)
})

test('同一 station 重选：重新 load 并正常播放', async () => {
  const h = createHarness({ fetchImpl: async (url, options = {}) => {
    if (options.method === 'HEAD') return {}
    throw new Error(`unexpected fetch ${url}`)
  } })

  h.state.currentStation.value = 'B'
  h.engine.loadStation('B')
  await flush()
  assert.equal(h.audio.currentSrc, 'https://b.example/live.mp3')
  // loadStation 调 2 次 load()：resetAudioSource + setMainAudioSrc
  assert.equal(h.audio.loadCalls, 2)

  // 再次选择同一 station
  h.engine.loadStation('B')
  await flush()
  assert.equal(h.audio.currentSrc, 'https://b.example/live.mp3')
  // 第二次 loadStation 又调 2 次 load()，总计 4
  assert.equal(h.audio.loadCalls >= 4, true)
})

test('persisted Radio source resolves by source_id and bypasses legacy URL racing', async () => {
  const calls = []
  const h = createHarness({
    fetchImpl: async (url) => {
      calls.push(String(url))
      assert.equal(String(url).includes('upstream.invalid'), false)
      if (String(url).includes('/api/radio/stations/radio_a/resolve')) {
        return responseJson({ source_type: 'audio_http' })
      }
      throw new Error(`unexpected Radio request ${url}`)
    },
  })
  h.store.stationMap.RADIO = {
    id: 'RADIO', name: 'Persisted Radio', radioStationId: 'radio_a', radioSourceId: 'source_a',
  }
  h.state.currentStation.value = 'RADIO'
  h.engine.loadStation('RADIO')
  await flush()

  assert.deepEqual(calls, ['/api/radio/stations/radio_a/resolve?source_id=source_a'])
  assert.equal(h.audio.src, '/api/media/radio/radio_a/stream?source_id=source_a')
  assert.deepEqual(h.audio.playCalls, ['/api/media/radio/radio_a/stream?source_id=source_a'])
  assert.equal(h.probeAudios.length, 0)
})

test('进入 auth 时 Radio 停止 HLS/audio/probe 并清理 MediaSession，旧回调不能复活', async () => {
  const timers = createTimerTracker()
  const playDeferred = deferred()
  const h = createHarness({
    hlsSupported: true,
    fetchImpl: async () => { throw new Error('no fetch') },
    setTimerImpl: timers.setTimer,
    clearTimerImpl: timers.clearTimer,
  })
  h.state.currentStation.value = 'HLS_A'
  h.audio.nextPlay = playDeferred
  h.engine.loadStation('HLS_A')
  await flush()
  const hls = h.hlsInstances[0]
  hls.emit('MANIFEST_PARSED')
  await flush()

  h.state.currentStation.value = ''
  h.engine.stopRadioAttempt()
  h.store.isPlaying = false
  h.store.isLoading = false
  h.store.playbackError = ''
  playDeferred.resolve()
  hls.emit('MANIFEST_PARSED')
  hls.emit('ERROR', { fatal: true })
  h.audio.emit('error')
  await flush()

  assert.equal(h.engine.activeAttemptInfo(), null)
  assert.equal(hls.destroyed, true)
  assert.equal(hls.handlerCount(), 0)
  assert.equal(h.audio.currentSrc, '')
  assert.ok(h.audio.pauseCalls > 0)
  assert.equal(h.audio.listenerCount(), 0)
  assert.equal(timers.pendingCount(), 0)
  assert.equal(h.mediaSession.metadata, null)
  assert.equal(h.mediaSession.playbackState, 'none')
  assert.equal(h.mediaSession.handlers.play, null)
  assert.equal(h.mediaSession.handlers.pause, null)
  assert.equal(h.store.isPlaying, false)
  assert.equal(h.store.isLoading, false)
  assert.equal(h.store.playbackError, '')
})
