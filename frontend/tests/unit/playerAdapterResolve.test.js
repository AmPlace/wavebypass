import test from 'node:test'
import assert from 'node:assert/strict'

import { createPinia, setActivePinia } from 'pinia'

import { usePlayerStore } from '../../src/stores/player.js'

function installFetchStub(payloads) {
  const calls = []
  globalThis.fetch = async (url) => {
    calls.push(String(url))
    const next = payloads.shift()
    if (next instanceof Error) throw next
    return {
      ok: next?.ok !== false,
      status: next?.status || 200,
      json: async () => next?.body || next || {},
    }
  }
  return calls
}

function adapterChannel(source = {}) {
  return {
    canonical_key: '虎牙',
    urls: [{
      url: 'huya://31421',
      source_id: 'src_huya',
      source_type: 'adapter',
      enabled: true,
      ...source,
    }],
  }
}

test('adapter source resolves to direct plus source_id proxy fallback by default', async () => {
  setActivePinia(createPinia())
  const calls = installFetchStub([{
    ok: true,
    source_id: 'src_huya',
    url: 'https://tx.flv.huya.com/live/room.flv?token=secret',
    source_type: 'http_flv',
    direct_playable: true,
    requires_proxy: false,
    volatile_url: true,
    proxy_url: '/api/media/channel/%E8%99%8E%E7%89%99/playlist.m3u8?source_id=src_huya',
  }])
  const store = usePlayerStore()

  await store.playIptvChannel(adapterChannel())

  assert.equal(calls.length, 1)
  assert.match(calls[0], /\/api\/media\/channel\/%E8%99%8E%E7%89%99\/resolve\?source_id=src_huya/)
  assert.equal(store.iptvUrls.length, 2)
  assert.equal(store.iptvUrls[0].type, 'direct')
  assert.equal(store.iptvUrls[0].source_id, 'src_huya')
  assert.equal(store.iptvUrls[0].source_type, 'http_flv')
  assert.equal(store.iptvUrls[0].adapter_volatile_url, true)
  assert.match(store.iptvUrls[0].adapter_source_url, /\/api\/media\/channel\/%E8%99%8E%E7%89%99\/resolve\?source_id=src_huya/)
  assert.equal(store.iptvUrls[1].type, 'direct')
  assert.equal(store.iptvUrls[1].via_proxy, true)
  assert.equal(store.iptvUrls[1].source_id, 'src_huya')
  assert.equal(store.iptvUrls[1].url.includes('token=secret'), false)
})

test('probe proxy_required_hint does not suppress adapter direct when adapter allows it', async () => {
  setActivePinia(createPinia())
  installFetchStub([{
    ok: true,
    source_id: 'src_huya',
    url: 'https://tx.flv.huya.com/live/room.flv?token=secret',
    source_type: 'http_flv',
    direct_playable: true,
    requires_proxy: false,
    proxy_url: '/api/media/channel/%E8%99%8E%E7%89%99/playlist.m3u8?source_id=src_huya',
  }])
  const store = usePlayerStore()

  await store.playIptvChannel(adapterChannel({ proxy_required_hint: 1 }))

  assert.equal(store.iptvUrls.length, 2)
  assert.equal(store.iptvUrls[0].type, 'direct')
  assert.equal(store.iptvUrls[0].via_proxy, undefined)
  assert.equal(store.iptvUrls[0].source_type, 'http_flv')
  assert.equal(store.iptvUrls[1].via_proxy, true)
  assert.equal(store.iptvUrls[1].source_type, 'http_flv')
})

test('market force_proxy suppresses adapter direct even when adapter allows it', async () => {
  setActivePinia(createPinia())
  installFetchStub([{
    ok: true,
    source_id: 'src_huya',
    url: 'https://tx.flv.huya.com/live/room.flv',
    source_type: 'http_flv',
    direct_playable: true,
    requires_proxy: false,
    proxy_url: '/api/media/channel/%E8%99%8E%E7%89%99/playlist.m3u8?source_id=src_huya',
  }])
  const store = usePlayerStore()

  await store.playIptvChannel(adapterChannel({ force_proxy: true }))

  assert.equal(store.iptvUrls.length, 1)
  assert.equal(store.iptvUrls[0].type, 'proxy')
  assert.equal(store.iptvUrls[0].via_proxy, true)
})

test('adapter requires_proxy is a hard constraint over market/default direct behavior', async () => {
  setActivePinia(createPinia())
  installFetchStub([{
    ok: true,
    source_id: 'src_huya',
    url: 'https://tx.flv.huya.com/live/room.flv',
    source_type: 'http_flv',
    direct_playable: true,
    requires_proxy: true,
    proxy_url: '/api/media/channel/%E8%99%8E%E7%89%99/playlist.m3u8?source_id=src_huya',
  }])
  const store = usePlayerStore()

  await store.playIptvChannel(adapterChannel())

  assert.equal(store.iptvUrls.length, 1)
  assert.equal(store.iptvUrls[0].type, 'proxy')
  assert.equal(store.iptvUrls[0].via_proxy, true)
})

test('adapter direct_playable false suppresses direct and keeps source_id proxy', async () => {
  setActivePinia(createPinia())
  installFetchStub([{
    ok: true,
    source_id: 'src_huya',
    url: 'https://tx.flv.huya.com/live/room.flv',
    source_type: 'http_flv',
    direct_playable: false,
    requires_proxy: false,
    proxy_url: '/api/media/channel/%E8%99%8E%E7%89%99/playlist.m3u8?source_id=src_huya',
  }])
  const store = usePlayerStore()

  await store.playIptvChannel(adapterChannel())

  assert.equal(store.iptvUrls.length, 1)
  assert.equal(store.iptvUrls[0].type, 'proxy')
  assert.equal(store.iptvUrls[0].via_proxy, true)
  assert.match(store.iptvUrls[0].url, /source_id=src_huya/)
})

test('adapter resolve failure falls back to source_id proxy without target_url', async () => {
  setActivePinia(createPinia())
  installFetchStub([new Error('resolve down')])
  const store = usePlayerStore()

  await store.playIptvChannel(adapterChannel())

  assert.equal(store.iptvUrls.length, 1)
  assert.equal(store.iptvUrls[0].type, 'proxy')
  assert.equal(store.iptvUrls[0].via_proxy, true)
  assert.match(store.iptvUrls[0].url, /\/api\/media\/channel\/%E8%99%8E%E7%89%99\/playlist\.m3u8\?source_id=src_huya/)
  assert.equal(store.iptvUrls[0].url.includes('huya://31421'), false)
  assert.equal(store.iptvUrls[0].url.includes('target_url='), false)
})
