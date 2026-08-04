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

function createYoutubeHarness() {
  const source = fs.readFileSync(fullPlayerPath, 'utf8')
  const clearTimerSource = extractFunction(source, 'function clearYoutubeStartupTimer()')
  const destroySource = extractFunction(source, 'function destroyYoutubePlayer(')
  const syncAudioSource = extractFunction(source, 'function syncYoutubeAudioState()')
  const youtubeSource = extractBetween(
    source,
    'async function handleActiveYoutubeFailure(',
    '\nfunction canUseHls(',
  )
  const factory = new Function('deps', `
    let _playAttemptId = 1
    let _componentDisposed = false
    let _youtubePlayer = null
    let _youtubeStartupTimer = null
    const { calls, timers, window, youtubeHostRef, activeIptvEngine } = deps
    const isAttemptActive = (attemptId) => !_componentDisposed && attemptId === _playAttemptId
    const cancelledError = () => new Error('cancelled')
    const setSourceRuntimeStatus = (index, status) => calls.push('status:' + index + ':' + status)
    const setSourceRuntimeStatusByEntry = (_entry, status) => calls.push('status:entry:' + status)
    const playerStore = {
      setLoading: (value) => calls.push('loading:' + value),
      togglePlay: (value) => calls.push('playing:' + value),
      clearPlaybackError: () => calls.push('error:clear'),
    }
    const cancelCurrentStartup = () => {}
    const cancelActiveProxyRace = () => {}
    const destroyIptvHls = () => {}
    const destroyIptvMpegts = () => {}
    const resetIptvVideo = () => {}
    const resetMediaAspect = () => {}
    const youtubeVideoId = () => 'video-1'
    const youtubeLiveEmbedUrl = () => ''
    const loadYoutubeIframeApi = async () => true
    const syncIptvMediaSession = (state) => calls.push('media:' + state)
    const fallbackToNextIptvUrl = async () => false
    const playCurrentIptvUrl = async () => {}
    const markAllIptvSourcesUnavailable = () => calls.push('all-unavailable')
    const volume = { value: 1 }
    const iptvMuted = { value: false }
    const setTimeout = (callback, delay) => {
      const timer = { callback, delay }
      timers.add(timer)
      return timer
    }
    const clearTimeout = (timer) => timers.delete(timer)
    ${clearTimerSource}
    ${destroySource}
    ${syncAudioSource}
    ${youtubeSource}
    return {
      startYoutubeCandidate,
      setAttempt: (value) => { _playAttemptId = value },
    }
  `)

  const calls = []
  const timers = new Set()
  let events = null
  const player = {
    playVideo: () => calls.push('youtube.play'),
    pauseVideo: () => calls.push('youtube.pause'),
    stopVideo: () => calls.push('youtube.stop'),
    destroy: () => calls.push('youtube.destroy'),
    setVolume: () => {},
    unMute: () => {},
  }
  const window = {
    YT: {
      Player: function Player(_host, options) {
        events = options.events
        return player
      },
      PlayerState: { PLAYING: 1, PAUSED: 2, BUFFERING: 3, ENDED: 0 },
    },
  }
  const harness = factory({
    calls,
    timers,
    window,
    youtubeHostRef: { value: { innerHTML: '' } },
    activeIptvEngine: { value: 'video' },
  })
  return { calls, events: () => events, harness, timers }
}

test('旧 YouTube callback 晚到后不能暂停、报错或 fallback 新频道', async () => {
  const h = createYoutubeHarness()
  const pending = h.harness.startYoutubeCandidate({ url: 'youtube://video-1' }, 1, 0)
  await Promise.resolve()
  await Promise.resolve()
  const events = h.events()
  assert.ok(events)

  events.onReady()
  events.onStateChange({ data: 1 })
  await pending
  assert.equal(h.timers.size, 0)

  h.calls.length = 0
  h.harness.setAttempt(2)
  events.onStateChange({ data: 2 })
  events.onStateChange({ data: 0 })
  events.onError({ data: 500 })

  assert.deepEqual(h.calls, [])
  assert.equal(h.timers.size, 0)
})
