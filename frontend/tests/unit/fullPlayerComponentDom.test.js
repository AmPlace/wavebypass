import assert from 'node:assert/strict'
import { after, afterEach, before, beforeEach, test } from 'node:test'
import fs from 'node:fs'
import { fileURLToPath } from 'node:url'
import path from 'node:path'
import { JSDOM } from 'jsdom'

const frontendRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../..')

let dom
let builtComponentPath
let FullPlayer
let IptvHome
let mount
let createPinia
let setActivePinia
let usePlayerStore
let flushPromises
let vueRef
const mountedWrappers = []

const channel = (name, sourceId, extra = {}) => ({
  name,
  canonical_key: name.toLowerCase(),
  group_name: '测试',
  urls: [{
    url: `https://media.example/${sourceId}.m3u8`,
    source_id: sourceId,
    source_type: 'hls',
    probe_status: 'online',
    is_working: 1,
  }],
  ...extra,
})

const response = (body, init = {}) => ({
  ok: true,
  status: 200,
  json: async () => body,
  ...init,
})

function installDom() {
  dom = new JSDOM('<!doctype html><html><body><div id="app"></div></body></html>', {
    url: 'http://localhost:5173/',
    pretendToBeVisual: true,
  })
  const globals = {
    window: dom.window,
    document: dom.window.document,
    navigator: dom.window.navigator,
    Element: dom.window.Element,
    Node: dom.window.Node,
    SVGElement: dom.window.SVGElement,
    HTMLElement: dom.window.HTMLElement,
    HTMLIFrameElement: dom.window.HTMLIFrameElement,
    HTMLVideoElement: dom.window.HTMLVideoElement,
    HTMLMediaElement: dom.window.HTMLMediaElement,
    DocumentFragment: dom.window.DocumentFragment,
    DOMRect: dom.window.DOMRect,
    XMLHttpRequest: dom.window.XMLHttpRequest,
    MutationObserver: dom.window.MutationObserver,
    AbortController: dom.window.AbortController,
    AbortSignal: dom.window.AbortSignal,
    Event: dom.window.Event,
    CustomEvent: dom.window.CustomEvent,
    getComputedStyle: dom.window.getComputedStyle,
  }
  for (const [key, value] of Object.entries(globals)) {
    Object.defineProperty(globalThis, key, { configurable: true, writable: true, value })
  }
  Object.defineProperty(dom.window.HTMLElement.prototype, 'clientWidth', {
    configurable: true,
    get() { return 1024 },
  })
  dom.window.HTMLElement.prototype.getBoundingClientRect = function () {
    return {
      width: 100,
      height: 44,
      top: 0,
      left: 0,
      right: 100,
      bottom: 44,
      x: 0,
      y: 0,
      toJSON() {},
    }
  }
  globalThis.ResizeObserver = class {
    observe() {}
    disconnect() {}
  }
  globalThis.IntersectionObserver = class {
    observe() {}
    unobserve() {}
    disconnect() {}
  }
  globalThis.requestAnimationFrame = (callback) => setTimeout(() => callback(Date.now()), 0)
  globalThis.cancelAnimationFrame = (id) => clearTimeout(id)
  window.requestAnimationFrame = globalThis.requestAnimationFrame
  window.cancelAnimationFrame = globalThis.cancelAnimationFrame
  window.matchMedia = () => ({ matches: false, addListener() {}, removeListener() {}, addEventListener() {}, removeEventListener() {} })
  Object.defineProperty(dom.window.HTMLMediaElement.prototype, 'play', {
    configurable: true,
    value() {
      if (!Object.prototype.hasOwnProperty.call(this, '__testCurrentTimeInstalled')) {
        const initialTime = Number(this.currentTime || 0)
        this.__testCurrentTimeInstalled = true
        this.__testCurrentTimeBase = initialTime
        this.__testCurrentTimeStartedAt = Date.now()
        Object.defineProperty(this, 'currentTime', {
          configurable: true,
          get() {
            if (this.paused) return this.__testCurrentTimeBase
            return this.__testCurrentTimeBase + ((Date.now() - this.__testCurrentTimeStartedAt) / 1000)
          },
          set(value) {
            this.__testCurrentTimeBase = Number(value) || 0
            this.__testCurrentTimeStartedAt = Date.now()
          },
        })
      }
      Object.defineProperty(this, 'paused', { configurable: true, value: false })
      Object.defineProperty(this, 'readyState', { configurable: true, value: 4 })
      this.__testCurrentTimeStartedAt = Date.now()
      Object.defineProperty(this, 'buffered', {
        configurable: true,
        value: { length: 1, start: () => 0, end: () => this.currentTime + 1 },
      })
      return Promise.resolve()
    },
  })
  Object.defineProperty(dom.window.HTMLMediaElement.prototype, 'pause', {
    configurable: true,
    value() {
      const currentTime = Number(this.currentTime || 0)
      this.__testCurrentTimeBase = currentTime
      Object.defineProperty(this, 'paused', { configurable: true, value: true })
    },
  })
  Object.defineProperty(dom.window.HTMLMediaElement.prototype, 'load', {
    configurable: true,
    value() {},
  })
}

function fakeHlsModule() {
  return `
    class FakeHls {
      static Events = {
        MEDIA_ATTACHED: 'mediaAttached',
        MANIFEST_PARSED: 'manifestParsed',
        FRAG_BUFFERED: 'fragBuffered',
        FRAG_LOADED: 'fragLoaded',
        ERROR: 'error',
      }
      static ErrorTypes = { NETWORK_ERROR: 'networkError', MEDIA_ERROR: 'mediaError' }
      static ErrorDetails = {
        FRAG_LOAD_ERROR: 'fragLoadError', FRAG_LOAD_TIMEOUT: 'fragLoadTimeout',
        KEY_LOAD_ERROR: 'keyLoadError', KEY_LOAD_TIMEOUT: 'keyLoadTimeout',
        LEVEL_LOAD_ERROR: 'levelLoadError', LEVEL_LOAD_TIMEOUT: 'levelLoadTimeout',
        MANIFEST_LOAD_ERROR: 'manifestLoadError', MANIFEST_LOAD_TIMEOUT: 'manifestLoadTimeout',
        LEVEL_PARSING_ERROR: 'levelParsingError', BUFFER_STALLED_ERROR: 'bufferStalledError',
        BUFFER_NUDGE_ON_STALL: 'bufferNudgeOnStall',
      }
      static isSupported() { return true }
      constructor() { this.listeners = new Map(); this.destroyed = false }
      on(name, fn) { const list = this.listeners.get(name) || []; list.push(fn); this.listeners.set(name, list) }
      off(name, fn) { this.listeners.set(name, (this.listeners.get(name) || []).filter(item => item !== fn)) }
      emit(name, ...args) { for (const fn of [...(this.listeners.get(name) || [])]) fn(...args) }
      attachMedia(video) {
        this.video = video
        globalThis.__fullPlayerHlsCalls = globalThis.__fullPlayerHlsCalls || []
        globalThis.__fullPlayerHlsCalls.push({ url: this.url, formal: video.classList.contains('media-video') })
        queueMicrotask(() => {
          if (this.destroyed) return
          this.emit(FakeHls.Events.MEDIA_ATTACHED)
          this.emit(FakeHls.Events.MANIFEST_PARSED)
          this.emit(FakeHls.Events.FRAG_LOADED)
          this.emit(FakeHls.Events.FRAG_BUFFERED)
        })
      }
      loadSource(url) { this.url = url }
      startLoad() {}
      recoverMediaError() {}
      destroy() { this.destroyed = true; this.listeners.clear() }
    }
    export default FakeHls
  `
}

function fakeMpegtsModule() {
  return `
    const Events = { MEDIA_INFO: 'mediaInfo', STATISTICS_INFO: 'statisticsInfo', ERROR: 'error', LOADING_COMPLETE: 'loadingComplete' }
    export default {
      Events,
      isSupported: () => true,
      getFeatureList: () => ({ mseLivePlayback: true }),
      createPlayer: () => ({
        listeners: new Map(),
        on(name, fn) { const list = this.listeners.get(name) || []; list.push(fn); this.listeners.set(name, list) },
        off(name, fn) { this.listeners.set(name, (this.listeners.get(name) || []).filter(item => item !== fn)) },
        attachMediaElement(video) { this.video = video },
        load() { queueMicrotask(() => this.listeners.get(Events.MEDIA_INFO)?.forEach(fn => fn())) },
        play() { return Promise.resolve() },
        destroy() { this.destroyed = true; this.listeners.clear() },
      }),
    }
  `
}

async function loadComponent() {
  installDom()
  const [{ build }, { default: vue }, compiler] = await Promise.all([
    import('vite'),
    import('@vitejs/plugin-vue'),
    import('@vue/compiler-sfc'),
  ])
  const tmpDir = path.resolve('/tmp/waveflow-full-player-dom-test')
  const tmpEntry = path.resolve('/tmp/waveflow-full-player-dom-entry.mjs')
  fs.writeFileSync(tmpEntry, `
    import FullPlayer from ${JSON.stringify(path.join(frontendRoot, 'src/components/FullPlayer.vue'))}
    import IptvHome from ${JSON.stringify(path.join(frontendRoot, 'src/views/IptvHome.vue'))}
    export { IptvHome }
    export default FullPlayer
  `)
  const fakePlugin = {
    name: 'full-player-test-media-mocks',
    enforce: 'pre',
    resolveId(id) {
      if (id === 'hls.js') return '\0full-player-test-hls'
      if (id === 'mpegts.js') return '\0full-player-test-mpegts'
    },
    load(id) {
      if (id === '\0full-player-test-hls') return fakeHlsModule()
      if (id === '\0full-player-test-mpegts') return fakeMpegtsModule()
    },
  }
  await build({
    root: frontendRoot,
    configFile: false,
    logLevel: 'error',
    plugins: [fakePlugin, vue({ compiler: compiler.default || compiler })],
    build: {
      outDir: tmpDir,
      emptyOutDir: true,
      lib: {
        entry: tmpEntry,
        formats: ['es'],
        fileName: 'full-player-dom',
      },
      rollupOptions: {
        external: ['vue', 'pinia'],
        output: {
          paths: {
            vue: new URL('../../node_modules/vue/index.js', import.meta.url).href,
            pinia: new URL('../../node_modules/pinia/dist/pinia.mjs', import.meta.url).href,
          },
        },
      },
    },
  })
  const testUtils = await import('@vue/test-utils')
  const vueRuntime = await import('vue')
  const pinia = await import('pinia')
  builtComponentPath = path.join(tmpDir, 'full-player-dom.js')
  const componentModule = await import(`${builtComponentPath}?dom-test=${Date.now()}`)
  mount = testUtils.mount
  flushPromises = testUtils.flushPromises
  createPinia = pinia.createPinia
  setActivePinia = pinia.setActivePinia
  usePlayerStore = (await import('../../src/stores/player.js')).usePlayerStore
  FullPlayer = componentModule.default
  IptvHome = componentModule.IptvHome
  vueRef = vueRuntime.ref
}

let channels
let fetchCalls
let fetchOverride

function installFetch() {
  fetchCalls = []
  globalThis.fetch = async (input) => {
    const url = String(input?.url || input)
    fetchCalls.push(url)
    const overrideResult = await fetchOverride?.(url, input)
    if (overrideResult) return overrideResult
    if (url.includes('/api/iptv/channels')) {
      const parsed = new URL(url, window.location.origin)
      const group = parsed.searchParams.get('group') || ''
      const search = parsed.searchParams.get('search') || ''
      const filtered = channels.filter((item) => (
        (!group || item.group_name === group)
        && (!search || item.name.includes(search))
      ))
      return response({
        channels: filtered,
        groups: [...new Set(channels.map((item) => item.group_name).filter(Boolean))],
      })
    }
    if (url.includes('/api/iptv/epg/programs/')) {
      const date = new URL(url, window.location.origin).searchParams.get('date') || '2026-08-05'
      return response({
        current: { title: `${date}-current`, start: `${date}T10:00:00Z`, stop: `${date}T11:00:00Z` },
        next: null,
        programs: [{ title: `${date}-program`, start: `${date}T10:00:00Z`, stop: `${date}T11:00:00Z`, status: 'current' }],
        date,
        available_dates: ['2026-08-04', '2026-08-05', '2026-08-06'],
      })
    }
    return response({ ok: true })
  }
}

async function mountPlayer({ current = channels[0], expanded = true } = {}) {
  setActivePinia(createPinia())
  const store = usePlayerStore()
  store.isPlayerExpanded = expanded
  store.activeMode = 'iptv'
  store.currentIptvChannel = current
  store.iptvUrls = current.urls
  store.iptvUrlIndex = 0
  store.isPlaying = true
  store.isLoading = false
  const wrapper = mount(FullPlayer, {
    attachTo: document.body,
  })
  mountedWrappers.push(wrapper)
  await flushPromises()
  await wrapper.vm.$nextTick()
  return { wrapper, store }
}

async function mountFullPlayerForStore(store, { expanded = true } = {}) {
  store.isPlayerExpanded = expanded
  store.activeMode = 'iptv'
  const wrapper = mount(FullPlayer, { attachTo: document.body })
  mountedWrappers.push(wrapper)
  await flushPromises()
  await wrapper.vm.$nextTick()
  return wrapper
}

async function mountHome({ store = null, search = '' } = {}) {
  if (!store) {
    setActivePinia(createPinia())
    store = usePlayerStore()
  }
  const searchQuery = vueRef(search)
  const scrollRef = vueRef(document.documentElement)
  const wrapper = mount(IptvHome, {
    attachTo: document.body,
    global: {
      provide: { searchQuery, scrollRef },
    },
  })
  mountedWrappers.push(wrapper)
  await flushPromises()
  await wrapper.vm.$nextTick()
  await new Promise((resolve) => setTimeout(resolve, 0))
  await flushPromises()
  await wrapper.vm.$nextTick()
  return { wrapper, store, searchQuery }
}

function buttonByText(selector, text) {
  const buttons = domElements(selector)
  const button = buttons.find((item) => item.textContent.trim().includes(text))
  assert.ok(button, `找不到按钮: ${selector} / ${text}; 当前按钮=${buttons.map((item) => item.textContent.trim()).join('|')}`)
  return button
}

async function clickButtonByText(selector, text) {
  buttonByText(selector, text).dispatchEvent(new window.MouseEvent('click', { bubbles: true }))
  await flushPromises()
}

function domElements(selector) {
  return [...document.querySelectorAll(selector)]
}

function domElement(selector, index = 0) {
  const element = domElements(selector)[index]
  assert.ok(element, `找不到真实 DOM 元素: ${selector}[${index}]`)
  return element
}

async function clickDom(selector, index = 0) {
  domElement(selector, index).dispatchEvent(new window.MouseEvent('click', { bubbles: true }))
  await flushPromises()
}

function activeMediaCount() {
  return document.querySelectorAll('.media-video, .youtube-player-host.active iframe').length
}

async function settlePlayback() {
  await new Promise(resolve => setTimeout(resolve, 760))
  await flushPromises()
}

before(async () => {
  await loadComponent()
})

beforeEach(() => {
  document.body.innerHTML = '<div id="app"></div>'
  channels = [
    channel('Alpha', 'alpha'),
    channel('Bravo', 'bravo'),
    channel('Charlie', 'charlie'),
    channel('Not Live', 'not-live', { urls: [{ url: 'https://media.example/not-live.m3u8', source_id: 'not-live', source_type: 'hls', probe_status: 'not_live' }] }),
    channel('Disabled', 'disabled', { urls: [{ url: 'https://media.example/disabled.m3u8', source_id: 'disabled', source_type: 'hls', disabled: true }] }),
    channel('Unsupported', 'unsupported', { urls: [{ url: 'https://media.example/unsupported.xyz', source_id: 'unsupported', source_type: 'unsupported' }] }),
  ]
  installFetch()
  fetchOverride = null
})

afterEach(() => {
  for (const wrapper of mountedWrappers.splice(0)) {
    if (wrapper.exists()) wrapper.unmount()
  }
  document.body.innerHTML = '<div id="app"></div>'
})

after(async () => {
  dom?.window.close()
})

function desktopChannelNames() {
  return domElements('.side-panel .channel-row .channel-title').map((element) => element.textContent.trim())
}

function mobileChannelNames() {
  return domElements('.mobile-panel .channel-row .channel-title').map((element) => element.textContent.trim())
}

function homeChannelNames() {
  return domElements('.channel-card').map((element) => String(element.getAttribute('aria-label') || '').replace(/^播放\s*/, ''))
}

test('IptvHome 从全部频道进入后 FullPlayer 继承全部集合和基础顺序', async () => {
  channels = [
    channel('Charlie', 'charlie', { group_name: '体育' }),
    channel('Alpha', 'alpha', { group_name: '央视' }),
    channel('Bravo', 'bravo', { group_name: '卫视' }),
  ]
  installFetch()
  const { store } = await mountHome()
  assert.deepEqual(homeChannelNames(), ['Charlie', 'Alpha', 'Bravo'])
  await clickDom('.channel-card', 0)
  assert.equal(store.iptvChannelContext.group, '')
  assert.equal(store.iptvChannelContext.search, '')
  assert.deepEqual(store.iptvChannelContext.channels.map((item) => item.name), ['Charlie', 'Alpha', 'Bravo'])
  await mountFullPlayerForStore(store)
  assert.deepEqual(desktopChannelNames(), ['Charlie', 'Alpha', 'Bravo'])
  assert.deepEqual(mobileChannelNames(), desktopChannelNames())
})

test('IptvHome 从分组进入后 FullPlayer 只继承该分组', async () => {
  channels = [
    channel('CCTV-1', 'cctv-1', { group_name: '央视' }),
    channel('CCTV-2', 'cctv-2', { group_name: '央视' }),
    channel('湖南卫视', 'hunan', { group_name: '卫视' }),
  ]
  installFetch()
  const { store } = await mountHome()
  await clickButtonByText('.tag-filter-row button, header button', '央视')
  assert.deepEqual(homeChannelNames(), ['CCTV-1', 'CCTV-2'])
  await clickDom('.channel-card', 0)
  assert.equal(store.iptvChannelContext.group, '央视')
  await mountFullPlayerForStore(store)
  assert.deepEqual(desktopChannelNames(), ['CCTV-1', 'CCTV-2'])
})

test('IptvHome 搜索以及分组加搜索的结果集合被 FullPlayer 原样继承', async () => {
  channels = [
    channel('福建新闻', 'fj-news', { group_name: '福建' }),
    channel('福建综合', 'fj-main', { group_name: '福建' }),
    channel('泉州新闻', 'qz-news', { group_name: '福建' }),
    channel('央视新闻', 'cctv-news', { group_name: '央视' }),
  ]
  installFetch()
  const first = await mountHome({ search: '新闻' })
  assert.deepEqual(homeChannelNames(), ['福建新闻', '泉州新闻', '央视新闻'])
  await clickDom('.channel-card', 0)
  assert.equal(first.store.iptvChannelContext.search, '新闻')
  await mountFullPlayerForStore(first.store)
  assert.deepEqual(desktopChannelNames(), ['福建新闻', '泉州新闻', '央视新闻'])

  for (const wrapper of mountedWrappers.splice(0)) {
    if (wrapper.exists()) wrapper.unmount()
  }
  document.body.innerHTML = '<div id="app"></div>'
  installFetch()
  const second = await mountHome()
  await clickButtonByText('.tag-filter-row button, header button', '福建')
  second.searchQuery.value = '新闻'
  await flushPromises()
  await second.wrapper.vm.$nextTick()
  assert.deepEqual(homeChannelNames(), ['福建新闻', '泉州新闻'])
  await clickDom('.channel-card', 0)
  assert.equal(second.store.iptvChannelContext.group, '福建')
  assert.equal(second.store.iptvChannelContext.search, '新闻')
  await mountFullPlayerForStore(second.store)
  assert.deepEqual(desktopChannelNames(), ['福建新闻', '泉州新闻'])
})

test('首页和 FullPlayer 共用排序状态，默认基础顺序与双向切换保持一致', async () => {
  channels = [
    channel('Charlie', 'charlie', { group_name: '卫视' }),
    channel('Alpha', 'alpha', { group_name: '央视' }),
    channel('Bravo', 'bravo', { group_name: '央视' }),
  ]
  installFetch()
  const { store } = await mountHome()
  assert.equal(store.iptvChannelSortMode, 'original')
  assert.match(buttonByText('.iptv-main header button', '默认排序').textContent, /默认排序/)
  assert.deepEqual(homeChannelNames(), ['Charlie', 'Alpha', 'Bravo'])
  await clickButtonByText('.iptv-main header button', '默认排序')
  assert.equal(store.iptvChannelSortMode, 'natural')
  assert.deepEqual(homeChannelNames(), ['Alpha', 'Bravo', 'Charlie'])
  await clickDom('.channel-card', 0)
  await mountFullPlayerForStore(store)
  assert.deepEqual(desktopChannelNames(), ['Alpha', 'Bravo', 'Charlie'])
  assert.match(domElement('.side-panel .sort-btn').textContent, /A-Z排序/)
  await clickDom('.side-panel .sort-btn')
  assert.equal(store.iptvChannelSortMode, 'group')
  assert.deepEqual(desktopChannelNames(), ['Charlie', 'Alpha', 'Bravo'])
  assert.deepEqual(homeChannelNames(), ['Charlie', 'Alpha', 'Bravo'])
  assert.match(domElement('.side-panel .sort-btn').textContent, /分组排序/)
  await clickDom('.side-panel .sort-btn')
  assert.equal(store.iptvChannelSortMode, 'original')
  assert.deepEqual(desktopChannelNames(), ['Charlie', 'Alpha', 'Bravo'])
  assert.doesNotMatch(document.body.textContent, /直播中排序/)
  store.setIptvChannelSortMode('group')
  await flushPromises()
  await clickDom('[aria-label="下一个"]')
  assert.equal(store.currentIptvChannel.name, 'Bravo')
})

test('同名不同 canonical identity 只有当前频道行 active', async () => {
  channels = [
    channel('同名频道', 'same-a', { canonical_key: 'same-a' }),
    channel('同名频道', 'same-b', { canonical_key: 'same-b' }),
  ]
  installFetch()
  const { store } = await mountPlayer({ current: channels[1] })
  store.setIptvChannelContext({ channels })
  await flushPromises()
  const rows = domElements('.side-panel .channel-row')
  assert.equal(rows.length, 2)
  assert.equal(rows.filter((row) => row.classList.contains('active')).length, 1)
  assert.equal(rows[1].classList.contains('active'), true)
})

test('上下文刷新移除旧频道并加入新频道，当前被删除频道只临时置顶', async () => {
  const alpha = channel('Alpha', 'alpha')
  const bravo = channel('Bravo', 'bravo')
  const charlie = channel('Charlie', 'charlie')
  channels = [bravo, charlie]
  installFetch()
  setActivePinia(createPinia())
  const store = usePlayerStore()
  store.currentIptvChannel = alpha
  store.iptvUrls = alpha.urls
  store.isPlaying = true
  store.setIptvChannelContext({ channels: [alpha, bravo] })
  await mountFullPlayerForStore(store)
  assert.deepEqual(desktopChannelNames(), ['Alpha', 'Bravo', 'Charlie'])
  await clickDom('.side-panel .channel-row', 1)
  assert.equal(store.currentIptvChannel.name, 'Bravo')
  assert.deepEqual(desktopChannelNames(), ['Bravo', 'Charlie'])
})

test('无首页上下文时按当前频道分组兜底，分组不存在时回退全量', async () => {
  const cctv = channel('CCTV-1', 'cctv', { group_name: '央视' })
  const hunan = channel('湖南卫视', 'hunan', { group_name: '卫视' })
  channels = [cctv, hunan]
  installFetch()
  const first = await mountPlayer({ current: cctv })
  assert.equal(first.store.iptvChannelContext, null)
  assert.deepEqual(desktopChannelNames(), ['CCTV-1'])

  for (const wrapper of mountedWrappers.splice(0)) {
    if (wrapper.exists()) wrapper.unmount()
  }
  document.body.innerHTML = '<div id="app"></div>'
  const missing = channel('临时频道', 'temporary', { group_name: '不存在分组' })
  installFetch()
  await mountPlayer({ current: missing })
  assert.deepEqual(desktopChannelNames(), ['临时频道', 'CCTV-1', '湖南卫视'])
})

test('桌面频道行点击 A→B，使用真实模板且只保留当前频道', async () => {
  const { wrapper, store } = await mountPlayer()
  const rows = domElements('.side-panel .channel-row')
  assert.equal(rows.length, channels.length)
  rows[1].click()
  await flushPromises()
  assert.equal(store.currentIptvChannel.name, 'Bravo')
  assert.equal(store.pendingIptvChannel, null)
  assert.equal(domElements('.side-panel .channel-row')[1].classList.contains('active'), true)
  assert.equal(store.iptvSelectionToken > 0, true)
  assert.equal(activeMediaCount(), 1)
})

test('移动端频道行点击 A→B 与桌面端共用选择入口', async () => {
  const { wrapper, store } = await mountPlayer()
  const rows = domElements('.mobile-panel .channel-row')
  assert.equal(rows.length, channels.length)
  rows[1].click()
  await flushPromises()
  assert.equal(store.currentIptvChannel.name, 'Bravo')
  assert.equal(domElements('.mobile-panel .channel-row')[1].classList.contains('active'), true)
  assert.equal(activeMediaCount(), 1)
})

test('快速点击 A→B→C 最终只留下 C，上一台/下一台按可见顺序切换', async () => {
  const { wrapper, store } = await mountPlayer()
  const rows = domElements('.side-panel .channel-row')
  rows[0].click()
  rows[1].click()
  rows[2].click()
  await flushPromises()
  assert.equal(store.currentIptvChannel.name, 'Charlie')
  assert.equal(store.pendingIptvChannel, null)
  await clickDom('[aria-label="上一个"]')
  assert.equal(store.currentIptvChannel.name, 'Bravo')
  await clickDom('[aria-label="下一个"]')
  assert.equal(store.currentIptvChannel.name, 'Charlie')
  assert.equal(activeMediaCount(), 1)
})

test('排序变化后上一台/下一台按当前可见频道顺序切换', async () => {
  channels = [channels[2], channels[0], channels[1], ...channels.slice(3)]
  installFetch()
  const { store } = await mountPlayer({ current: channels[1] })
  await clickDom('.side-panel .sort-btn')
  const visibleNames = domElements('.side-panel .channel-row .channel-title')
    .map(element => element.textContent.trim())
  assert.deepEqual(visibleNames.slice(0, 3), ['Alpha', 'Bravo', 'Charlie'])
  await clickDom('[aria-label="下一个"]')
  assert.equal(store.currentIptvChannel.name, 'Bravo')
  await clickDom('[aria-label="上一个"]')
  assert.equal(store.currentIptvChannel.name, 'Alpha')
})

test('快速 A→B→C 只有最终频道进入正式起播', async () => {
  globalThis.__fullPlayerHlsCalls = []
  const { store } = await mountPlayer()
  const rows = domElements('.side-panel .channel-row')
  rows[0].click()
  rows[1].click()
  rows[2].click()
  await settlePlayback()
  assert.equal(store.currentIptvChannel.name, 'Charlie')
  const formalStarts = (globalThis.__fullPlayerHlsCalls || []).filter(item => item.formal)
  assert.equal(formalStarts.length, 1)
  assert.match(formalStarts[0].url, /charlie\.m3u8$/)
})

test('not_live 可点击，显式 disabled 和 unsupported 不可点击', async () => {
  const { wrapper, store } = await mountPlayer()
  const rows = domElements('.side-panel .channel-row')
  rows[3].click()
  await flushPromises()
  assert.equal(store.currentIptvChannel.name, 'Not Live')
  rows[4].click()
  await flushPromises()
  assert.equal(store.currentIptvChannel.name, 'Not Live')
  assert.equal(rows[4].classList.contains('disabled'), true)
  rows[5].click()
  await flushPromises()
  assert.equal(store.currentIptvChannel.name, 'Not Live')
  assert.equal(rows[5].classList.contains('disabled'), true)
})

test('混合 supported + unsupported 频道仍可点击并使用受支持 source', async () => {
  const mixed = channel('Mixed', 'mixed-supported', {
    urls: [
      { url: 'https://media.example/mixed.xyz', source_id: 'mixed-unsupported', source_type: 'unsupported' },
      { url: 'https://media.example/mixed-supported.m3u8', source_id: 'mixed-supported', source_type: 'hls', probe_status: 'online', is_working: 1 },
    ],
  })
  channels = [channels[0], mixed, ...channels.slice(1)]
  installFetch()
  const { store } = await mountPlayer()
  const mixedRow = domElements('.side-panel .channel-row')[1]
  assert.equal(mixedRow.classList.contains('disabled'), false)
  mixedRow.click()
  await flushPromises()
  assert.equal(store.currentIptvChannel.name, 'Mixed')
  assert.equal(store.iptvUrls.some(entry => entry.source_id === 'mixed-supported'), true)
})

test('播放源菜单切换 direct→proxy→direct，active source 与 store 一致', async () => {
  const sourceA = { url: 'https://media.example/direct.m3u8', source_id: 'direct', source_type: 'hls', type: 'direct', probe_status: 'online', is_working: 1 }
  const sourceB = { url: 'http://localhost:5173/api/media/channel/test/playlist.m3u8', source_id: 'proxy', source_type: 'hls', type: 'proxy', via_proxy: true, probe_status: 'online', is_working: 1 }
  const current = { ...channels[0], urls: [sourceA, sourceB] }
  const { wrapper, store } = await mountPlayer({ current })
  await clickDom('[aria-label="切换播放源"]')
  const options = domElements('#iptv-source-menu button')
  assert.equal(options.length, 2)
  options[1].click()
  await flushPromises()
  assert.equal(store.iptvUrls[store.iptvUrlIndex].source_id, 'proxy')
  await clickDom('[aria-label="切换播放源"]')
  domElements('#iptv-source-menu button')[0].click()
  await flushPromises()
  assert.equal(store.iptvUrls[store.iptvUrlIndex].source_id, 'direct')
})

test('EPG 日期切换与频道切换后，节目单属于当前频道且旧请求不覆盖新请求', async () => {
  const { wrapper, store } = await mountPlayer()
  await clickDom('.side-panel .panel-tabs button', 1)
  if (domElements('.side-panel .schedule-date-chip').length) {
    await clickDom('.side-panel .schedule-date-chip', 0)
  }
  await clickDom('.side-panel .panel-tabs button', 0)
  await clickDom('.side-panel .channel-row', 1)
  await flushPromises()
  assert.equal(store.currentIptvChannel.name, 'Bravo')
  assert.match(document.body.textContent, /Bravo|2026-08-05-current/)
  assert.equal(activeMediaCount(), 1)
})

test('EPG 日期和频道请求交错时，慢请求不能覆盖当前频道和日期', async () => {
  const pending = []
  fetchOverride = async (url) => {
    if (!url.includes('/api/iptv/epg/programs/')) return null
    return await new Promise((resolve, reject) => pending.push({ url, resolve, reject }))
  }
  const { wrapper, store } = await mountPlayer()
  await flushPromises()
  const rows = domElements('.side-panel .channel-row')
  rows[1].click()
  await flushPromises()
  rows[2].click()
  await flushPromises()
  assert.ok(pending.length >= 2)
  const bravoRequest = pending[0]
  const charlieRequest = pending[1]
  charlieRequest.resolve(response({
    current: { title: 'Charlie-base', start: '2026-08-05T10:00:00Z', stop: '2026-08-05T11:00:00Z' },
    next: null,
    programs: [],
    date: '2026-08-05',
    available_dates: ['2026-08-04', '2026-08-05', '2026-08-06'],
  }))
  await flushPromises()
  await new Promise(resolve => setTimeout(resolve, 0))
  await flushPromises()
  assert.equal(store.currentEpgProgram?.title, 'Charlie-base')
  await clickDom('.side-panel .panel-tabs button', 1)
  const dates = domElements('.side-panel .schedule-date-chip')
  assert.equal(dates.length, 3)
  dates[0].click()
  dates[2].click()
  await flushPromises()
  assert.ok(pending.length >= 4)
  const newest = pending.at(-1)
  newest.resolve(response({
    current: { title: 'Charlie-new', start: '2026-08-05T10:00:00Z', stop: '2026-08-05T11:00:00Z' },
    next: null,
    programs: [],
    date: '2026-08-06',
    available_dates: ['2026-08-05', '2026-08-06'],
  }))
  await flushPromises()
  pending[2].resolve(response({
    current: { title: 'Charlie-old-date', start: '2026-08-04T10:00:00Z', stop: '2026-08-04T11:00:00Z' },
    next: null,
    programs: [],
    date: '2026-08-04',
    available_dates: ['2026-08-04'],
  }))
  bravoRequest.resolve(response({
    current: { title: 'Bravo-old', start: '2026-08-04T10:00:00Z', stop: '2026-08-04T11:00:00Z' },
    next: null,
    programs: [],
    date: '2026-08-04',
    available_dates: ['2026-08-04'],
  }))
  await flushPromises()
  assert.equal(store.currentIptvChannel.name, 'Charlie')
  assert.match(document.body.textContent, /Charlie-new/)
})

test('auth 停播后卸载资源，重新进入普通页面不会自动起播', async () => {
  const { wrapper, store } = await mountPlayer()
  await settlePlayback()
  assert.equal(activeMediaCount(), 1)
  store.stopAndClearPlayback()
  await wrapper.vm.$nextTick()
  wrapper.unmount()
  assert.equal(store.currentIptvChannel, null)
  assert.equal(store.iptvChannelContext, null)
  assert.equal(store.iptvVideoEl, null)
  assert.equal(store.isPlaying, false)
  assert.equal(document.querySelectorAll('video, iframe').length, 0)

  const next = mount(FullPlayer, { attachTo: document.body })
  mountedWrappers.push(next)
  await flushPromises()
  assert.equal(activeMediaCount(), 0)
  assert.equal(store.currentIptvChannel, null)
})

test('收起再展开保持当前频道/source；同一频道重复点击不制造第二个媒体元素', async () => {
  const { wrapper, store } = await mountPlayer()
  const sourceToken = store.iptvSelectionToken
  await clickDom('.desktop-collapse-btn')
  assert.equal(store.isPlayerExpanded, false)
  store.expandPlayer()
  await wrapper.vm.$nextTick()
  await clickDom('.side-panel .channel-row', 0)
  assert.equal(store.currentIptvChannel.name, 'Alpha')
  assert.equal(store.iptvSelectionToken, sourceToken + 1)
  assert.equal(activeMediaCount(), 1)
})
