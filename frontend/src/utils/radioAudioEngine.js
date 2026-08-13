export function createRadioAudioEngine({
  audioRef,
  hlsRef,
  directStreamMode,
  playerStore,
  currentStation,
  volume,
  Hls,
  API_BASE,
  publicAsset,
  getNavigator = () => globalThis.navigator,
  getMediaMetadata = () => globalThis.MediaMetadata,
  createAudio = () => new Audio(),
  fetchImpl = (...args) => fetch(...args),
  setTimer = (fn, ms) => setTimeout(fn, ms),
  clearTimer = (id) => clearTimeout(id),
  logger = console,
}) {
  const directStreamStationMap = {}
  let fallbackUrls = []
  let fallbackIndex = 0
  let fallbackStationId = ''
  let directProbeWinner = null
  let attemptSeq = 0
  let activeAttempt = null
  let mainAudioErrorCleanup = null

  function channelStreamUrl(stationId) {
    return `${API_BASE}/api/media/channel/${encodeURIComponent(stationId)}/stream`
  }

  function getDirectUrl(stationId) {
    return playerStore.stationMap[stationId]?.directUrl
  }

  function hasDirectUrl(stationId) {
    return Boolean(getDirectUrl(stationId))
  }

  function persistedRadioStation(stationId) {
    const station = playerStore.stationMap[stationId]
    if (!station?.radioStationId || !station?.radioSourceId) return null
    return station
  }

  function radioResolveUrl(station) {
    const query = new URLSearchParams({ source_id: String(station.radioSourceId) })
    return `${API_BASE}/api/radio/stations/${encodeURIComponent(station.radioStationId)}/resolve?${query}`
  }

  function radioMediaUrl(station, path) {
    const query = new URLSearchParams({ source_id: String(station.radioSourceId) })
    return `${API_BASE}/api/media/radio/${encodeURIComponent(station.radioStationId)}/${path}?${query}`
  }

  function isAttemptActive(attempt) {
    return Boolean(
      attempt
        && activeAttempt === attempt
        && !attempt.cancelled
        && currentStation.value === attempt.stationId
        && !playerStore.currentIptvChannel,
    )
  }

  function addAttemptCleanup(attempt, cleanup) {
    if (!attempt || typeof cleanup !== 'function') return () => {}
    attempt.cleanups.add(cleanup)
    return () => attempt.cleanups.delete(cleanup)
  }

  function runAttemptCleanups(attempt) {
    if (!attempt) return
    const cleanups = Array.from(attempt.cleanups)
    attempt.cleanups.clear()
    for (const cleanup of cleanups) {
      try { cleanup() } catch {}
    }
  }

  function removeMainAudioErrorHandler() {
    if (!mainAudioErrorCleanup) return
    mainAudioErrorCleanup()
    mainAudioErrorCleanup = null
  }

  function bindMainAudioError(attempt) {
    removeMainAudioErrorHandler()
    const el = audioRef.value
    if (!el || !attempt) return
    const onError = () => handleAudioError(attempt)
    el.addEventListener('error', onError)
    mainAudioErrorCleanup = () => el.removeEventListener('error', onError)
    addAttemptCleanup(attempt, () => {
      if (mainAudioErrorCleanup) removeMainAudioErrorHandler()
    })
  }

  function invalidateActiveAttempt() {
    const attempt = activeAttempt
    if (!attempt) return
    attempt.cancelled = true
    if (activeAttempt === attempt) activeAttempt = null
    runAttemptCleanups(attempt)
  }

  function beginAttempt(stationId) {
    invalidateActiveAttempt()
    const attempt = {
      id: ++attemptSeq,
      stationId,
      cancelled: false,
      cleanups: new Set(),
      mainHls: null,
    }
    activeAttempt = attempt
    return attempt
  }

  function destroyCurrentHls() {
    if (!hlsRef.value) return
    hlsRef.value.destroy()
    hlsRef.value = null
  }

  function destroyAttemptHls(attempt) {
    if (!attempt?.mainHls) return
    const hls = attempt.mainHls
    attempt.mainHls = null
    if (hlsRef.value === hls) hlsRef.value = null
    try { hls.destroy() } catch {}
  }

  function resetAudioSource() {
    const el = audioRef.value
    if (!el) return
    removeMainAudioErrorHandler()
    el.pause()
    el.removeAttribute('src')
    el.load()
  }

  function setMainAudioSrc(attempt, url) {
    if (!isAttemptActive(attempt) || !audioRef.value) return false
    bindMainAudioError(attempt)
    audioRef.value.src = url
    audioRef.value.load()
    return true
  }

  function updateSystemMediaSession(stationId, attempt = activeAttempt) {
    if (!isAttemptActive(attempt)) return
    const navigatorRef = getNavigator()
    if (!navigatorRef || !('mediaSession' in navigatorRef)) return
    const meta = playerStore.stationMap[stationId] || {}
    const finalLogo = publicAsset(meta.logoUrl || '/logos/default.png')

    try {
      const MediaMetadataCtor = getMediaMetadata()
      navigatorRef.mediaSession.metadata = new MediaMetadataCtor({
        title: meta.name || '未知频率',
        artist: meta.subtitle || 'WaveFlow Radio',
        album: 'Live Stream',
        artwork: [{ src: finalLogo, sizes: '512x512', type: 'image/png' }],
      })
    } catch (e) {
      logger.warn('MediaSession 写入失败，跳过元数据更新', e)
    }

    navigatorRef.mediaSession.setActionHandler('play', () => playerStore.togglePlay(true))
    navigatorRef.mediaSession.setActionHandler('pause', () => playerStore.togglePlay(false))
  }

  function clearRadioMediaSession() {
    const navigatorRef = getNavigator()
    if (!navigatorRef || !('mediaSession' in navigatorRef)) return
    const session = navigatorRef.mediaSession
    try { session.metadata = null } catch {}
    try { session.playbackState = 'none' } catch {}
    for (const action of ['play', 'pause']) {
      try { session.setActionHandler(action, null) } catch {}
    }
  }

  function updateMediaSessionForCurrentSubtitle(subtitle) {
    const attempt = activeAttempt
    if (subtitle && isAttemptActive(attempt)) updateSystemMediaSession(attempt.stationId, attempt)
  }

  async function playAudioSafely(attempt = activeAttempt) {
    if (!isAttemptActive(attempt) || !audioRef.value) return

    try {
      await audioRef.value.play()
      if (!isAttemptActive(attempt)) return

      playerStore.clearPlaybackError()
      playerStore.setLoading(false)
      playerStore.togglePlay(true)
      updateSystemMediaSession(attempt.stationId, attempt)
    } catch (error) {
      if (!isAttemptActive(attempt)) return
      if (error instanceof DOMException) {
        logger.warn('浏览器阻止了自动播放，需要用户手动点击播放。', error)
        playerStore.setPlaybackError('浏览器阻止自动播放，请手动点击播放。')
      } else {
        logger.warn('音频播放失败。', error)
        playerStore.setPlaybackError('音频播放失败，请稍后重试。')
      }
      playerStore.togglePlay(false)
    }
  }

  function fallbackToProxyStream(stationId, attempt = activeAttempt) {
    if (!isAttemptActive(attempt) || !audioRef.value) return

    if (directStreamMode.value === 'proxy') {
      playerStore.setPlaybackError('后端中转音频流连接失败，请稍后重试。')
      playerStore.togglePlay(false)
      return
    }

    const streamConfig = directStreamStationMap[stationId]
    const proxyUrl = streamConfig?.proxyUrl || channelStreamUrl(stationId)

    directStreamMode.value = 'proxy'
    playerStore.setPlaybackError('直连失败，正在自动切换后端中转。')
    playerStore.setLoading(true)
    if (!setMainAudioSrc(attempt, proxyUrl)) return
    playAudioSafely(attempt)
  }

  function isHlsUrl(url) {
    return /\.m3u8(\?|$)/i.test(url)
  }

  async function playUrl(url, stationId, mode, attempt = activeAttempt) {
    if (!isAttemptActive(attempt)) return false
    destroyCurrentHls()
    directStreamMode.value = mode

    if (isHlsUrl(url) && Hls?.isSupported()) {
      const hls = new Hls({
        enableWorker: true, lowLatencyMode: true, autoStartLoad: true,
        startFragPrefetch: true, liveSyncDurationCount: 2,
        liveMaxLatencyDurationCount: 5, maxBufferLength: 10,
      })
      attempt.mainHls = hls
      hlsRef.value = hls
      hls.loadSource(url)
      hls.attachMedia(audioRef.value)
      await new Promise((resolve, reject) => {
        let settled = false
        let timer = null
        const cleanup = () => {
          if (timer) clearTimer(timer)
          hls.off?.(Hls.Events.MANIFEST_PARSED, onParsed)
          hls.off?.(Hls.Events.ERROR, onError)
        }
        const settle = (fn, value) => {
          if (settled) return
          settled = true
          cleanup()
          fn(value)
        }
        const onParsed = () => {
          if (!isAttemptActive(attempt)) {
            settle(reject, new Error('stale radio attempt'))
            return
          }
          settle(resolve)
        }
        const onError = (_e, d) => {
          if (!isAttemptActive(attempt)) {
            settle(reject, new Error('stale radio attempt'))
            return
          }
          if (d?.fatal) settle(reject, d)
        }
        hls.on(Hls.Events.MANIFEST_PARSED, onParsed)
        hls.on(Hls.Events.ERROR, onError)
        timer = setTimer(() => settle(reject, new Error('HLS 加载超时')), 10_000)
        addAttemptCleanup(attempt, cleanup)
      })
    } else {
      if (!setMainAudioSrc(attempt, url)) return false
    }

    if (!isAttemptActive(attempt)) return false
    audioRef.value.volume = volume.value
    await audioRef.value.play()
    if (!isAttemptActive(attempt)) return false
    playerStore.clearPlaybackError()
    playerStore.setLoading(false)
    playerStore.togglePlay(true)
    updateSystemMediaSession(stationId, attempt)
    return true
  }

  function upgradeHttps(url) {
    return url.startsWith('http://') ? 'https://' + url.slice(7) : url
  }

  async function filterReachable(urls, { tryHttps = false, attempt = activeAttempt } = {}) {
    const activeChecks = new Set()
    const cleanupChecks = () => {
      for (const cancel of Array.from(activeChecks)) cancel()
      activeChecks.clear()
    }
    const removeCleanup = addAttemptCleanup(attempt, cleanupChecks)
    const checks = urls.map((url) => {
      const testUrl = tryHttps ? upgradeHttps(url) : url
      return new Promise((resolve) => {
        const controller = new AbortController()
        let settled = false
        let timer = null
        const finish = (result) => {
          if (settled) return
          settled = true
          if (timer) clearTimer(timer)
          activeChecks.delete(cancel)
          resolve(result)
        }
        const cancel = () => {
          try { controller.abort() } catch {}
          finish(null)
        }
        activeChecks.add(cancel)
        fetchImpl(testUrl, { method: 'HEAD', mode: 'no-cors', signal: controller.signal })
          .then(() => finish([testUrl, url]))
          .catch(() => finish(null))
        timer = setTimer(cancel, 3000)
      })
    })
    const results = await Promise.all(checks)
    cleanupChecks()
    removeCleanup()
    if (!isAttemptActive(attempt)) return []
    return results.filter(Boolean)
  }

  async function probeParallel(urls, stationId, mode, { tryHttps = false, attempt = activeAttempt } = {}) {
    if (!isAttemptActive(attempt) || !urls.length) return null

    const reachable = await filterReachable(urls, { tryHttps, attempt })
    if (!isAttemptActive(attempt) || !reachable.length) return null
    logger.log(`[探测] ${reachable.length}/${urls.length} 个源可达${tryHttps ? '（已升级 HTTPS）' : ''}`)

    const activeHls = new Set()
    const activeAudio = new Set()
    const activeProbeCancels = new Set()

    function cleanupAll() {
      for (const cancel of Array.from(activeProbeCancels)) cancel()
      activeProbeCancels.clear()
      for (const h of activeHls) { try { h.destroy() } catch {} }
      activeHls.clear()
      for (const a of activeAudio) {
        try {
          a.pause()
          a.removeAttribute('src')
          a.load()
        } catch {}
      }
      activeAudio.clear()
    }
    const removeCleanup = addAttemptCleanup(attempt, cleanupAll)

    const promises = reachable.map(([url, origUrl], i) => {
      if (isHlsUrl(url) && Hls?.isSupported()) {
        return new Promise((resolve) => {
          if (!isAttemptActive(attempt)) { resolve(null); return }
          const probeEl = createAudio()
          const hls = new Hls({ autoStartLoad: true, maxBufferLength: 1 })
          activeHls.add(hls)
          activeAudio.add(probeEl)
          hls.loadSource(url)
          hls.attachMedia(probeEl)
          let settled = false
          let timer = null
          let cancelProbe = null
          const onFragLoaded = () => done({ url, origUrl, index: i, type: 'hls' })
          const onError = (_e, d) => { if (d?.fatal) done(null) }
          const cleanup = () => {
            if (timer) clearTimer(timer)
            timer = null
            hls.off(Hls.Events.FRAG_LOADED, onFragLoaded)
            hls.off(Hls.Events.ERROR, onError)
            if (cancelProbe) activeProbeCancels.delete(cancelProbe)
            activeHls.delete(hls)
            activeAudio.delete(probeEl)
            try { hls.destroy() } catch {}
            try {
              probeEl.removeAttribute('src')
              probeEl.load()
            } catch {}
          }
          const done = (result) => {
            if (settled) return
            settled = true
            cleanup()
            if (result) cleanupAll()
            resolve(isAttemptActive(attempt) ? result : null)
          }
          cancelProbe = () => done(null)
          activeProbeCancels.add(cancelProbe)
          hls.on(Hls.Events.FRAG_LOADED, onFragLoaded)
          hls.on(Hls.Events.ERROR, onError)
          timer = setTimer(cancelProbe, 10_000)
        })
      }
      return new Promise((resolve) => {
        if (!isAttemptActive(attempt)) { resolve(null); return }
        const probeEl = createAudio()
        activeAudio.add(probeEl)
        probeEl.preload = 'auto'
        probeEl.src = url
        probeEl.load()
        let settled = false
        let timer = null
        let cancelProbe = null
        const onCanPlay = () => done({ url, origUrl, index: i, type: 'direct' })
        const onError = () => done(null)
        const cleanup = () => {
          if (timer) clearTimer(timer)
          timer = null
          probeEl.removeEventListener('canplay', onCanPlay)
          probeEl.removeEventListener('error', onError)
          if (cancelProbe) activeProbeCancels.delete(cancelProbe)
          activeAudio.delete(probeEl)
          try {
            probeEl.pause()
            probeEl.removeAttribute('src')
            probeEl.load()
          } catch {}
        }
        const done = (result) => {
          if (settled) return
          settled = true
          cleanup()
          if (result) cleanupAll()
          resolve(isAttemptActive(attempt) ? result : null)
        }
        cancelProbe = () => done(null)
        activeProbeCancels.add(cancelProbe)
        probeEl.addEventListener('canplay', onCanPlay, { once: true })
        probeEl.addEventListener('error', onError, { once: true })
        timer = setTimer(cancelProbe, 10_000)
      })
    })

    const winnerPromises = promises.map((promise) => promise.then((winner) => {
      if (!winner) throw new Error('probe failed')
      return winner
    }))
    let overallTimer = null
    const result = await Promise.race([
      Promise.any(winnerPromises).catch(() => null),
      new Promise((resolve) => {
        overallTimer = setTimer(() => { cleanupAll(); resolve(null) }, 12_000)
      }),
    ])
    if (overallTimer) clearTimer(overallTimer)
    cleanupAll()
    removeCleanup()
    if (!isAttemptActive(attempt)) {
      cleanupAll()
      return null
    }
    return result
  }

  async function tryFallbackUrls(attempt = activeAttempt) {
    if (!isAttemptActive(attempt)) return
    destroyCurrentHls()
    const stationId = fallbackStationId
    const urls = fallbackUrls.slice(fallbackIndex)

    if (!urls.length) {
      if (!isAttemptActive(attempt)) return
      playerStore.setPlaybackError('无可用音频源。')
      playerStore.togglePlay(false)
      return
    }

    logger.log(`[回退] 并发直连探测 ${urls.length} 个源...`)
    let winner = await probeParallel(urls, stationId, 'direct', { tryHttps: true, attempt })
    if (!isAttemptActive(attempt)) return
    if (winner) directProbeWinner = winner

    if (!winner && directProbeWinner) {
      const proxyUrl = channelStreamUrl(fallbackStationId)
      logger.log(`[回退] 直连播放失败，直接中转源 #${directProbeWinner.index + 1}...`)
      winner = { url: proxyUrl, origUrl: directProbeWinner.origUrl, index: directProbeWinner.index, type: 'proxy' }
    }

    if (!winner) {
      const fallbackUrl = channelStreamUrl(stationId)
      logger.log(`[回退] 直连全败，fallback 到 channel 入口...`)
      winner = await probeParallel([fallbackUrl], stationId, 'proxy', { attempt })
      if (!isAttemptActive(attempt)) return
    }

    if (!winner) {
      logger.warn('[回退] 所有源（直连+中转）均失败。')
      if (!isAttemptActive(attempt)) return
      playerStore.setPlaybackError('所有音频源均不可用，请稍后重试。')
      playerStore.togglePlay(false)
      return
    }

    logger.log(`[回退] 胜出: ${winner.type} #${winner.index + 1}`)
    try {
      if (!isAttemptActive(attempt)) return
      const played = await playUrl(winner.url, stationId, winner.type, attempt)
      if (!played || !isAttemptActive(attempt)) return
      fallbackIndex = winner.index + 1
      directProbeWinner = null
    } catch {
      if (!isAttemptActive(attempt)) return
      playerStore.setPlaybackError('音频播放失败，请稍后重试。')
      playerStore.togglePlay(false)
    }
  }

  function handleAudioError(attempt = activeAttempt) {
    if (!isAttemptActive(attempt)) return
    const stationId = attempt.stationId

    if (directStreamStationMap[stationId]) {
      fallbackToProxyStream(stationId, attempt)
      return
    }

    if (fallbackUrls.length > 1 && fallbackIndex < fallbackUrls.length && fallbackStationId === stationId) {
      tryFallbackUrls(attempt)
      return
    }

    if (directStreamMode.value === 'proxy') {
      playerStore.setPlaybackError('后端中转音频流连接失败，请稍后重试。')
      playerStore.togglePlay(false)
      return
    }

    if (hasDirectUrl(stationId)) {
      fallbackToProxyStream(stationId, attempt)
      return
    }

    playerStore.setPlaybackError('电台音频加载失败，请检查后端代理或稍后重试。')
    playerStore.togglePlay(false)
  }

  async function fetchAllUrls(stationId, attempt = activeAttempt) {
    const stName = playerStore.stationMap[stationId]?.name || ''
    const ctrl = new AbortController()
    const timer = setTimer(() => ctrl.abort(), 8_000)
    const removeCleanup = addAttemptCleanup(attempt, () => ctrl.abort())
    try {
      const res = await fetchImpl(
        `${API_BASE}/api/${stationId}/all-urls?name=${encodeURIComponent(stName)}`,
        { signal: ctrl.signal },
      )
      if (!isAttemptActive(attempt)) return []
      if (res.ok) {
        const data = await res.json()
        if (!isAttemptActive(attempt)) return []
        return data
      }
    } catch {
      if (!isAttemptActive(attempt)) return []
    } finally {
      clearTimer(timer)
      removeCleanup()
    }
    return []
  }

  function loadStation(stationId, options = {}) {
    if (!audioRef.value || !stationId) return null

    const attempt = beginAttempt(stationId)
    const radioStation = persistedRadioStation(stationId)
    const playlistUrl = radioStation
      ? radioMediaUrl(radioStation, 'playlist.m3u8')
      : `${API_BASE}/api/media/channel/${encodeURIComponent(stationId)}/playlist.m3u8`

    destroyCurrentHls()
    resetAudioSource()
    // 统一绑定 audio error handler 到当前 attempt。
    // 模板原有的 @error 已移至 bindMainAudioError，确保所有路径（包括原生 HLS）
    // 都能捕获 audio element 的 error 事件。
    bindMainAudioError(attempt)
    if (!isAttemptActive(attempt)) return attempt
    playerStore.clearPlaybackError()
    playerStore.setLoading(true)
    directStreamMode.value = ''
    fallbackUrls = []
    fallbackIndex = 0
    fallbackStationId = stationId
    directProbeWinner = null

    if (radioStation && !options.radioTransport) {
      const controller = new AbortController()
      const timer = setTimer(() => controller.abort(), 10_000)
      const removeCleanup = addAttemptCleanup(attempt, () => controller.abort())
      ;(async () => {
        try {
          const response = await fetchImpl(radioResolveUrl(radioStation), { signal: controller.signal })
          if (!isAttemptActive(attempt)) return
          if (!response.ok) throw new Error('Radio source resolve failed')
          const resolved = await response.json()
          const transport = String(resolved?.source_type || '').trim().toLowerCase()
          if (!['audio_http', 'hls'].includes(transport)) throw new Error('Unsupported Radio transport')
          if (isAttemptActive(attempt)) loadStation(stationId, { radioTransport: transport })
        } catch (error) {
          if (!isAttemptActive(attempt)) return
          logger.warn('Radio source resolve failed.', error)
          playerStore.setPlaybackError('电台播放源解析失败，请稍后重试。')
          playerStore.togglePlay(false)
        } finally {
          clearTimer(timer)
          removeCleanup()
        }
      })()
      return attempt
    }

    if (radioStation && options.radioTransport === 'audio_http') {
      directStreamMode.value = 'proxy'
      if (setMainAudioSrc(attempt, radioMediaUrl(radioStation, 'stream'))) playAudioSafely(attempt)
      return attempt
    }

    if (directStreamStationMap[stationId]) {
      directStreamMode.value = 'direct'
      if (setMainAudioSrc(attempt, directStreamStationMap[stationId].directUrl)) playAudioSafely(attempt)
      return attempt
    }

    const directUrl = radioStation ? '' : getDirectUrl(stationId)
    const hasLivePath = radioStation || playerStore.stationMap[stationId]?.livePath

    if (directUrl && !hasLivePath) {
      directStreamMode.value = 'direct'
      fetchAllUrls(stationId, attempt).then((urls) => {
        if (isAttemptActive(attempt) && fallbackStationId === stationId) fallbackUrls = urls
      })
      if (setMainAudioSrc(attempt, directUrl)) playAudioSafely(attempt)
      return attempt
    }

    if (!hasLivePath && playerStore.stationMap[stationId]?.directPlay) {
      ;(async () => {
        const urls = await fetchAllUrls(stationId, attempt)
        if (!isAttemptActive(attempt)) return

        fallbackUrls = urls
        fallbackIndex = 0

        if (urls.length === 0) {
          fallbackToProxyStream(stationId, attempt)
          return
        }

        await tryFallbackUrls(attempt)
      })()
      return attempt
    }

    if (Hls?.isSupported()) {
      const canDirectPlay = playerStore.stationMap[stationId]?.directPlay
      let triedDirect = false

      async function startHlsWithFallback() {
        if (!isAttemptActive(attempt)) return
        let hlsUrl = playlistUrl

        if (canDirectPlay) {
          try {
            const stName = playerStore.stationMap[stationId]?.name || ''
            const ctrl = new AbortController()
            const timer = setTimer(() => ctrl.abort(), 5000)
            const removeCleanup = addAttemptCleanup(attempt, () => ctrl.abort())
            try {
              const res = await fetchImpl(`${API_BASE}/api/${stationId}/stream-url?name=${encodeURIComponent(stName)}`, { signal: ctrl.signal })
              if (!isAttemptActive(attempt)) return
              clearTimer(timer)
              removeCleanup()
              if (res.ok) {
                const { url } = await res.json()
                if (!isAttemptActive(attempt)) return
                if (url) { hlsUrl = url; directStreamMode.value = 'direct' }
              }
            } finally {
              clearTimer(timer)
              removeCleanup()
            }
          } catch {}
        }

        if (!isAttemptActive(attempt)) return

        const hls = new Hls({
          enableWorker: true,
          lowLatencyMode: true,
          autoStartLoad: true,
          startFragPrefetch: true,
          liveSyncDurationCount: 2,
          liveMaxLatencyDurationCount: 5,
          maxBufferLength: 10,
        })
        attempt.mainHls = hls
        hlsRef.value = hls
        hls.loadSource(hlsUrl)
        hls.attachMedia(audioRef.value)

        const onManifestParsed = () => { if (isAttemptActive(attempt)) playAudioSafely(attempt) }
        const onHlsError = (_event, data) => {
          if (!isAttemptActive(attempt) || !data?.fatal) return
          logger.warn('HLS 播放发生致命错误。', data)

          if (canDirectPlay && directStreamMode.value === 'direct' && !triedDirect) {
            triedDirect = true
            directStreamMode.value = 'proxy'
            destroyAttemptHls(attempt)
            startHlsWithFallback()
            return
          }
          if (directUrl) {
            destroyAttemptHls(attempt)
            directStreamMode.value = 'direct'
            if (setMainAudioSrc(attempt, directUrl)) playAudioSafely(attempt)
            return
          }
          if (fallbackUrls.length > 1 && fallbackStationId === stationId) {
            destroyAttemptHls(attempt)
            tryFallbackUrls(attempt)
            return
          }
          playerStore.setPlaybackError('HLS 播放发生错误，请稍后重试。')
          playerStore.togglePlay(false)
        }
        hls.on(Hls.Events.MANIFEST_PARSED, onManifestParsed)
        hls.on(Hls.Events.ERROR, onHlsError)
        addAttemptCleanup(attempt, () => {
          hls.off?.(Hls.Events.MANIFEST_PARSED, onManifestParsed)
          hls.off?.(Hls.Events.ERROR, onHlsError)
        })

        if (canDirectPlay) {
          fetchAllUrls(stationId, attempt).then((urls) => {
            if (isAttemptActive(attempt) && fallbackStationId === stationId) fallbackUrls = urls
          })
        }
      }

      startHlsWithFallback()
      return attempt
    }

    if (audioRef.value.canPlayType('application/vnd.apple.mpegurl')) {
      const canDirectPlay = playerStore.stationMap[stationId]?.directPlay

      async function startSafariHls() {
        if (!isAttemptActive(attempt)) return
        let hlsUrl = playlistUrl

        if (canDirectPlay) {
          try {
            const stName = playerStore.stationMap[stationId]?.name || ''
            const ctrl = new AbortController()
            const timer = setTimer(() => ctrl.abort(), 5000)
            const removeCleanup = addAttemptCleanup(attempt, () => ctrl.abort())
            try {
              const res = await fetchImpl(`${API_BASE}/api/${stationId}/stream-url?name=${encodeURIComponent(stName)}`, { signal: ctrl.signal })
              if (!isAttemptActive(attempt)) return
              if (res.ok) {
                const { url } = await res.json()
                if (!isAttemptActive(attempt)) return
                if (url) hlsUrl = url
              }
            } finally {
              clearTimer(timer)
              removeCleanup()
            }
          } catch {}
        }
        if (!isAttemptActive(attempt)) return

        if (!setMainAudioSrc(attempt, hlsUrl)) return
        const onLoaded = () => playAudioSafely(attempt)
        audioRef.value.addEventListener('loadedmetadata', onLoaded, { once: true })
        addAttemptCleanup(attempt, () => audioRef.value?.removeEventListener('loadedmetadata', onLoaded))
      }

      startSafariHls()
      return attempt
    }

    logger.warn('当前浏览器不支持 HLS 播放，或 hls.js 尚未加载完成。')
    if (!isAttemptActive(attempt)) return attempt
    playerStore.setPlaybackError('当前浏览器不支持 HLS 播放。')
    playerStore.togglePlay(false)
    return attempt
  }

  function stopRadioAttempt() {
    invalidateActiveAttempt()
    destroyCurrentHls()
    resetAudioSource()
    fallbackUrls = []
    fallbackIndex = 0
    fallbackStationId = ''
    directProbeWinner = null
    directStreamMode.value = ''
    clearRadioMediaSession()
  }

  function pauseCurrentAudio() {
    audioRef.value?.pause()
  }

  function setVolume(nextVolume) {
    if (!audioRef.value) return
    audioRef.value.volume = nextVolume
  }

  function activeAttemptInfo() {
    return activeAttempt ? { id: activeAttempt.id, stationId: activeAttempt.stationId, active: isAttemptActive(activeAttempt) } : null
  }

  return {
    activeAttemptInfo,
    fallbackToProxyStream,
    handleAudioError,
    invalidateActiveAttempt,
    loadStation,
    pauseCurrentAudio,
    playAudioSafely,
    playUrl,
    probeParallel,
    setVolume,
    stopRadioAttempt,
    tryFallbackUrls,
    updateMediaSessionForCurrentSubtitle,
  }
}
