import test from 'node:test'
import assert from 'node:assert/strict'
import fs from 'node:fs'

const fullPlayerPath = new URL('../../src/components/FullPlayer.vue', import.meta.url)

function extractFunction(source, signature) {
  const start = source.indexOf(signature)
  assert.notEqual(start, -1, `missing function: ${signature}`)
  const bodyStart = source.indexOf('{', start)
  let depth = 0
  for (let index = bodyStart; index < source.length; index += 1) {
    if (source[index] === '{') depth += 1
    if (source[index] === '}') depth -= 1
    if (depth === 0) return source.slice(start, index + 1)
  }
  throw new Error(`unterminated function: ${signature}`)
}

function extractBetween(source, startSignature, endSignature) {
  const start = source.indexOf(startSignature)
  assert.notEqual(start, -1, `missing start: ${startSignature}`)
  const end = source.indexOf(endSignature, start)
  assert.notEqual(end, -1, `missing end: ${endSignature}`)
  return source.slice(start, end).trim()
}

class FakeHls {
  static Events = {
    MEDIA_ATTACHED: 'media-attached',
    FRAG_BUFFERED: 'frag-buffered',
    FRAG_LOADED: 'frag-loaded',
    ERROR: 'error',
  }

  static ErrorDetails = { FRAG_LOAD_ERROR: 'frag-load-error' }
  static ErrorTypes = { NETWORK_ERROR: 'network-error' }
  static loadedUrls = []

  constructor() {
    this.handlers = new Map()
  }

  on(event, handler) {
    this.handlers.set(event, handler)
  }

  off(event, handler) {
    if (this.handlers.get(event) === handler) this.handlers.delete(event)
  }

  loadSource(url) {
    FakeHls.loadedUrls.push(url)
  }

  attachMedia() {
    queueMicrotask(() => {
      this.handlers.get(FakeHls.Events.MEDIA_ATTACHED)?.()
      this.handlers.get(FakeHls.Events.FRAG_BUFFERED)?.()
      this.handlers.get(FakeHls.Events.FRAG_LOADED)?.()
    })
  }

  stopLoad() {}
  detachMedia() {}
  destroy() {}
}

function createRaceHarness() {
  const source = fs.readFileSync(fullPlayerPath, 'utf8')
  const runHedgedRaceSource = extractBetween(
    source,
    'async function runHedgedRace(',
    '\nasync function handleIptvError(',
  )
  const factory = new Function('deps', `
    let _cleanupActiveRace = null
    const {
      calls, playerStore, preflightProxyPlaylistTransport, document, Hls,
    } = deps
    const HEDGED_PROXY_DELAY_MS = 0
    const RACE_HLS_CONFIRM_MS = 0
    const RACE_HLS_CONFIRM_RETRY_MS = 0
    const isAttemptActive = () => true
    const cancelCurrentStartup = () => {}
    const cancelActiveProxyRace = () => {}
    const destroyIptvEngines = () => {}
    const resetIptvVideo = () => {}
    const isMpegTsEngineType = () => false
    const getSourceRuntimeStatus = () => 'trying'
    const setSourceRuntimeStatus = () => {}
    const setSourceRuntimeStatusByEntry = () => {}
    const markRaceLoser = () => {}
    const clearRaceLoser = () => {}
    const entrySourceId = (entry) => entry.source_id || ''
    const extractSourceIdFromUrl = () => ''
    const sourceTransport = (entry) => entry.source_type || ''
    const hlsProbeHasRealProgress = () => true
    const trackHlsSource = () => {}
    const canUseHls = () => true
    const canUseMpegTs = () => false
    const startupRaceCandidateKind = (_entry, options) => options.sourceType === 'hls' ? 'hls' : ''
    const mpegts = { createPlayer: () => { throw new Error('unexpected mpegts') }, Events: {} }
    const mpegtsPlayerType = () => 'mse'
    const setIptvUrlIndexForAttempt = async () => true
    const fallbackToNextIptvUrl = async () => false
    const playCurrentIptvUrl = async () => {}
    const markAllIptvSourcesUnavailable = () => {}
    const isProxyLikeEntry = (entry) => entry.via_proxy === true
    const sourceType = (entry) => entry.source_type || 'hls'
    const tryPlayIptv = async (...args) => { calls.push(args) }
    ${runHedgedRaceSource}
    return { runHedgedRace }
  `)

  const calls = []
  const first = {
    url: '/api/media/channel/adapter/playlist.m3u8?source_id=src_adapter',
    source_id: 'src_adapter',
    source_type: 'adapter',
    adapter_transport_pending: true,
    via_proxy: true,
  }
  const second = {
    url: '/api/media/channel/other/playlist.m3u8?source_id=src_other',
    source_id: 'src_other',
    source_type: 'adapter',
    adapter_transport_pending: true,
    via_proxy: true,
  }
  const videos = []
  const document = {
    body: { appendChild() {} },
    createElement() {
      const video = {
        currentTime: 1,
        readyState: 2,
        buffered: { length: 1, start: () => 0, end: () => 2 },
        style: {},
        play: async () => {},
        addEventListener() {},
        removeEventListener() {},
        remove() {},
      }
      videos.push(video)
      return video
    },
  }
  const harness = factory({
    calls,
    document,
    Hls: FakeHls,
    playerStore: {
      iptvUrls: [first, second],
      setLoading() {},
      clearPlaybackError() {},
    },
    preflightProxyPlaylistTransport: async (url) => (
      url.includes('src_adapter') ? null : { url: '/api/media/proxy/rtsp/other', sourceType: 'rtsp' }
    ),
  })
  return { calls, first, harness }
}

function createFormalPlaybackHarness() {
  const source = fs.readFileSync(fullPlayerPath, 'utf8')
  const helpers = [
    'function isHlsUrl(',
    'function isMpegTsUrl(',
    'function isHttpFlvUrl(',
    'function isMpegTsEngineType(',
    'function sourceTypeFromProxyRedirect(',
    'function mpegtsPlayerType(',
    'function playbackEngineType(',
  ].map((signature) => extractFunction(source, signature)).join('\n')
  const tryPlaySource = extractBetween(source, 'async function tryPlayIptv(', '\nfunction pruneRaceLosers(')
  const factory = new Function('deps', `
    let _playAttemptId = 1
    let _componentDisposed = false
    let _softPausedAt = 0
    let _softPauseReleased = false
    let _cancelCurrentStartup = null
    const { Hls, loadedUrls, playerStore, preflightProxyPlaylistTransport } = deps
    const iptvVideoRef = { value: {
      currentTime: 0, volume: 1, canPlayType: () => '',
      play: async () => {}, addEventListener() {}, removeEventListener() {},
    } }
    const iptvHlsRef = { value: null }
    const iptvMpegtsRef = { value: null }
    const activeIptvEngine = { value: 'video' }
    const window = { location: { origin: 'http://localhost:5173' } }
    const volume = { value: 1 }
    const isIOS = false
    const isAttemptActive = (attemptId) => !_componentDisposed && attemptId === _playAttemptId
    const cancelledError = () => new Error('cancelled')
    const clearPauseReleaseTimer = () => {}
    const cancelCurrentStartup = () => {
      if (!_cancelCurrentStartup) return
      const cancel = _cancelCurrentStartup
      _cancelCurrentStartup = null
      cancel()
    }
    const cancelActiveProxyRace = () => {}
    const destroyIptvEngines = () => {}
    const stopPlaybackWatchdogs = () => {}
    const resetMediaAspect = () => {}
    const resetIptvVideo = () => {}
    const sourceType = () => 'hls'
    const canUseHls = () => true
    const canUseMpegTs = () => false
    const mpegts = { createPlayer: () => { throw new Error('unexpected mpegts') }, Events: {} }
    const setSourceRuntimeStatus = () => {}
    const setSourceRuntimeStatusByUrl = () => {}
    const updateMediaAspectFromVideo = () => {}
    const attachRuntimeHlsErrorHandlers = () => {}
    const attachRuntimeMpegtsErrorHandlers = () => {}
    const releaseTrackedHls = () => {}
    const clearCurrentHlsIf = () => {}
    const clearCurrentMpegtsIf = () => {}
    const trackHlsSource = () => {}
    ${helpers}
    ${tryPlaySource}
    return { tryPlayIptv }
  `)

  const loadedUrls = []
  class FormalHls extends FakeHls {
    loadSource(url) {
      loadedUrls.push(url)
    }
  }
  return {
    harness: factory({
      Hls: FormalHls,
      loadedUrls,
      playerStore: { setLoading() {}, togglePlay() {} },
      preflightProxyPlaylistTransport: async () => ({
        url: '/api/media/proxy/rtsp/signed-handle',
        sourceType: 'rtsp',
      }),
    }),
    loadedUrls,
  }
}

test('adapter proxy Race 以 HLS 胜出后正式起播继续使用同一 effective transport', async () => {
  const h = createRaceHarness()
  await h.harness.runHedgedRace([], [
    { entry: h.first, index: 0, kind: 'proxy_auto' },
    {
      entry: {
        url: '/api/media/channel/other/playlist.m3u8?source_id=src_other',
        source_id: 'src_other',
        source_type: 'adapter',
        adapter_transport_pending: true,
        via_proxy: true,
      },
      index: 1,
      kind: 'proxy_auto',
    },
  ], 1)

  assert.equal(h.calls.length, 1)
  assert.equal(h.calls[0][5], 'hls')
})

test('RTSP channel proxy 跳转到无 m3u8 后缀的 HLS endpoint 时使用 HLS 引擎', async () => {
  const h = createFormalPlaybackHarness()
  await h.harness.tryPlayIptv(
    '/api/media/channel/camera/playlist.m3u8?source_id=src_rtsp',
    true,
    '',
    1,
    0,
    'rtsp',
  )
  assert.deepEqual(h.loadedUrls, ['/api/media/proxy/rtsp/signed-handle'])
})
