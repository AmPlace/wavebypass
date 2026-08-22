import test from 'node:test'
import assert from 'node:assert/strict'

import {
  packageCardTitle,
  packageIdentity,
  packageScaleLabel,
  packageSecondaryMeta,
  packageSourceLabel,
  pluginCardTagItems,
} from '../../src/views/marketCardUi.js'

test('Market identity resolves explicit badge before provider, operator, and region fallbacks', () => {
  assert.deepEqual(
    packageIdentity({
      id: 'custom',
      name: '福建联通 IPTV',
      region: { province: '福建', country: 'CN' },
      operators: ['联通'],
      display: { badge: { text: 'FX', tone: 'sky' } },
    }),
    { text: 'FX', toneClass: 'market-region-sky', sourceLabel: '福建 · 联通' },
  )

  const operator = packageIdentity({ id: 'fj', name: '福建联通 IPTV', region: { province: '福建' }, operators: ['cucc'] })
  assert.equal(operator.text, '联')
  assert.equal(operator.sourceLabel, '福建 · 联通')

  const region = packageIdentity({ id: 'hk', name: '香港内容包', region: { country: '香港' }, operators: ['global'] })
  assert.equal(region.text, '港')
  assert.match(region.toneClass, /^market-region-/)
})

test('Market package presenter keeps Content and Plugin card grammar separate', () => {
  const content = { id: 'wave', name: 'WaveFlow 内容', package_type: 'content_package', kind: 'dynamic_playlist', channel_count: 42, source_origin: 'official', market_source: { name: 'Official' } }
  assert.equal(packageCardTitle(content), 'WaveFlow 内容')
  assert.equal(packageScaleLabel(content), '42 个频道')
  assert.equal(packageSecondaryMeta(content), '官方 Market · 动态目录')
  assert.equal(packageSourceLabel(content), 'Official')

  const plugin = {
    id: 'official::fjtv-plugin',
    name: 'FJTV Provider Plugin',
    package_type: 'plugin_package',
    source_origin: 'official',
    plugin: {
      publisher_id: 'org.waveflow',
      plugin_id: 'fjtv',
      display_name: 'FJTV Provider',
      provider_contracts: [{ contract: 'tv_provider', features: ['resolve_stream'] }],
      owned_schemes: [{ scheme: 'fjtv' }],
      platforms: [{ runtime: 'python' }],
      permissions: ['network.managed'],
    },
  }
  assert.equal(packageCardTitle(plugin), 'FJTV Provider')
  assert.equal(packageScaleLabel(plugin), '1 个 scheme')
  assert.equal(packageSourceLabel(plugin), 'org.waveflow/fjtv')
  assert.equal(packageSecondaryMeta(plugin), 'Python · Managed Network')
  assert.deepEqual(pluginCardTagItems(plugin), [
    { label: 'TVProvider', accentClass: 'market-tag-blue' },
    { label: '自动解析', accentClass: '' },
  ])
})
