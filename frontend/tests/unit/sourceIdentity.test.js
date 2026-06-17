import test from 'node:test'
import assert from 'node:assert/strict'

import {
  adapterNameFromUrl,
  buildChannelProxyUrl,
  extractSourceIdFromUrl,
  isAdapterSchemeUrl,
  isDynamicAdapterProxyPlaylistEntry,
  sourceRaceKey,
  sourceTransport,
} from '../../src/utils/sourceIdentity.js'

const isChannelProxyPlaylistUrl = (url) => {
  try {
    const parsed = new URL(url, 'http://waveflow.local')
    return /\/api\/media\/channel\/.+\/playlist\.m3u8$/i.test(parsed.pathname)
  } catch {
    return false
  }
}

test('direct and proxy entries keep the same logical source_id', () => {
  const direct = { source_id: 'src_same', type: 'direct', url: 'https://up.example/live.m3u8' }
  const proxy = { source_id: 'src_same', type: 'proxy', via_proxy: true, url: '/api/media/channel/c/playlist.m3u8?source_id=src_same' }

  assert.equal(direct.source_id, proxy.source_id)
  assert.equal(sourceTransport(direct), 'direct')
  assert.equal(sourceTransport(proxy), 'proxy')
})

test('loser key is source_id plus transport', () => {
  const direct = { source_id: 'src_a', type: 'direct' }
  const proxy = { source_id: 'src_a', type: 'proxy', via_proxy: true }

  assert.equal(sourceRaceKey(direct), 'src_a:direct')
  assert.equal(sourceRaceKey(proxy), 'src_a:proxy')
  assert.notEqual(sourceRaceKey(direct), sourceRaceKey(proxy))
})

test('direct loser does not mark proxy loser', () => {
  const losers = new Set()
  const direct = { source_id: 'src_a', type: 'direct' }
  const proxy = { source_id: 'src_a', type: 'proxy', via_proxy: true }

  losers.add(sourceRaceKey(direct))

  assert.equal(losers.has(sourceRaceKey(direct)), true)
  assert.equal(losers.has(sourceRaceKey(proxy)), false)
})

test('race winner source_id matches request URL source_id', () => {
  const winner = {
    source_id: 'src_win',
    type: 'proxy',
    via_proxy: true,
    url: buildChannelProxyUrl({ apiBase: '', channelKey: '福建综合', sourceId: 'src_win' }),
  }

  assert.equal(extractSourceIdFromUrl(winner.url), winner.source_id)
})

test('manual second source request contains second source_id', () => {
  const sources = [
    { source_id: 'src_first' },
    { source_id: 'src_second' },
  ]
  const requestUrl = buildChannelProxyUrl({ apiBase: '', channelKey: '频道', sourceId: sources[1].source_id })

  assert.equal(extractSourceIdFromUrl(requestUrl), 'src_second')
})

test('proxy request does not contain upstream URL or token', () => {
  const upstream = 'https://cdn.example/live.m3u8?token=secret'
  const requestUrl = buildChannelProxyUrl({ apiBase: '', channelKey: '频道', sourceId: 'src_safe' })

  assert.equal(requestUrl.includes('source_url='), false)
  assert.equal(requestUrl.includes(encodeURIComponent(upstream)), false)
  assert.equal(requestUrl.includes(upstream), false)
  assert.equal(requestUrl.includes('token=secret'), false)
})

test('http and https URLs are not adapter schemes', () => {
  assert.equal(isAdapterSchemeUrl('https://cdn.example/live.m3u8'), false)
  assert.equal(isAdapterSchemeUrl('http://cdn.example/live.m3u8'), false)
})

test('known adapter schemes are recognized by the shared source helper', () => {
  assert.equal(isAdapterSchemeUrl('huya://31421'), true)
  assert.equal(isAdapterSchemeUrl('adapter://huya/31421'), true)
  assert.equal(adapterNameFromUrl('huya://31421'), 'huya')
  assert.equal(adapterNameFromUrl('adapter://huya/31421'), 'huya')
})

test('ordinary channel proxy fallback with empty adapter is not dynamic adapter proxy', () => {
  const entry = {
    source_id: 'src_hls',
    type: 'proxy',
    via_proxy: true,
    adapter: '',
    original_url: 'https://cdn.example/live.m3u8',
    url: buildChannelProxyUrl({ apiBase: '', channelKey: '普通频道', sourceId: 'src_hls' }),
  }

  assert.equal(isDynamicAdapterProxyPlaylistEntry(entry, isChannelProxyPlaylistUrl), false)
})

test('direct and proxy queue entries classify through shared adapter helpers without ReferenceError', () => {
  const direct = {
    source_id: 'src_hls',
    type: 'direct',
    original_url: 'https://cdn.example/live.m3u8',
    url: 'https://cdn.example/live.m3u8',
  }
  const ordinaryProxy = {
    ...direct,
    type: 'proxy',
    via_proxy: true,
    url: buildChannelProxyUrl({ apiBase: '', channelKey: '普通频道', sourceId: 'src_hls' }),
  }
  const adapterProxyWithoutAdapterField = {
    source_id: 'src_huya',
    type: 'proxy',
    via_proxy: true,
    original_url: 'huya://31421',
    url: buildChannelProxyUrl({ apiBase: '', channelKey: '虎牙', sourceId: 'src_huya' }),
  }
  const adapterProxyWithAdapterField = {
    ...adapterProxyWithoutAdapterField,
    adapter: 'huya',
    original_url: 'https://resolved.example/live.m3u8',
  }

  assert.equal(isDynamicAdapterProxyPlaylistEntry(direct, isChannelProxyPlaylistUrl), false)
  assert.equal(isDynamicAdapterProxyPlaylistEntry(ordinaryProxy, isChannelProxyPlaylistUrl), false)
  assert.equal(isDynamicAdapterProxyPlaylistEntry(adapterProxyWithoutAdapterField, isChannelProxyPlaylistUrl), true)
  assert.equal(isDynamicAdapterProxyPlaylistEntry(adapterProxyWithAdapterField, isChannelProxyPlaylistUrl), true)
})
