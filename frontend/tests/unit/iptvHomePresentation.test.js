import assert from 'node:assert/strict'
import fs from 'node:fs'
import path from 'node:path'
import test from 'node:test'
import { fileURLToPath } from 'node:url'

import { iptvCardProgrammeTitle } from '../../src/utils/iptvViewing.js'
import { channelVisualCandidates } from '../../src/utils/channelVisual.js'

const frontendRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../..')

test('IPTV 首页节目卡只显示当前节目名，不显示结束时间', () => {
  assert.equal(
    iptvCardProgrammeTitle({ title: '午间新闻', stop: '2026-08-16T12:30:00+08:00' }, '新闻'),
    '午间新闻',
  )
  assert.equal(iptvCardProgrammeTitle({ title: '  ' }, '新闻'), '新闻')

  const home = fs.readFileSync(path.join(frontendRoot, 'src/views/IptvHome.vue'), 'utf8')
  assert.match(home, /iptvCardProgrammeTitle\(current, ch\.group_name \|\| ''\)/)
  assert.doesNotMatch(home, /channelProgrammeSubtitle\(/)
})

test('正在直播图标保持为非交互的无背景装饰', () => {
  const home = fs.readFileSync(path.join(frontendRoot, 'src/views/IptvHome.vue'), 'utf8')
  assert.match(home, /class="iptv-live-section-icon inline-flex size-6[^>]*text-\[var\(--text-secondary\)\]"/)
  assert.match(home, /<span class="iptv-live-section-icon inline-flex size-6[\s\S]*?<svg class="size-4"/)
  assert.doesNotMatch(home, /iptv-live-section-icon[^>]*rounded-full/)
  assert.doesNotMatch(home, /iptv-live-section-icon[^>]*bg-\[var\(--surface\)\]/)
})

test('IPTV Home 支持 Standard/Compact presentation density，Compact 不渲染 footer', () => {
  const home = fs.readFileSync(path.join(frontendRoot, 'src/views/IptvHome.vue'), 'utf8')
  const styles = fs.readFileSync(path.join(frontendRoot, 'src/style.css'), 'utf8')
  assert.match(home, /iptv-density-compact/)
  assert.match(home, /iptv-density-toggle/)
  assert.match(home, /data-density-toggle/)
  assert.match(home, /:aria-pressed="densityMode === 'standard'"/)
  assert.doesNotMatch(home, /iptv-density-menu|data-density-option="standard"|role="switch"/)
  assert.match(home, /v-if="densityMode === 'standard'" class="card-info"/)
  assert.match(home, /v-else-if="isCompactStatusVisible\(item\.channel\)"/)
  assert.match(home, /defaultIptvCardDensity\(viewportWidth\.value\)/)
  assert.match(home, /writeIptvCardDensityPreference\(value\)/)
  assert.match(styles, /\.iptv-main\.iptv-density-compact \.channel-card--logo-card::after,/)
  assert.match(styles, /\.iptv-main\.iptv-density-compact \.channel-card__logo-stage:not\(/)
  assert.match(styles, /\.iptv-main\.iptv-density-compact \.channel-card__compact-status/)
})

test('IPTV density direct toggle keeps the user-facing information semantics', () => {
  const home = fs.readFileSync(path.join(frontendRoot, 'src/views/IptvHome.vue'), 'utf8')
  assert.match(home, /densityMode === 'standard' \? '仅显示 Logo' : '显示频道信息'/)
  assert.match(home, /densityMode\.value === IPTV_CARD_DENSITIES\.STANDARD\s*\? IPTV_CARD_DENSITIES\.COMPACT/)
  assert.match(home, /densityMode === 'standard' \? '切换为仅显示 Logo' : '切换为显示频道信息'/)
})

test('Huya generic visual candidates prefer stable art and gate offline screenshots', () => {
  const home = fs.readFileSync(path.join(frontendRoot, 'src/views/IptvHome.vue'), 'utf8')
  const helper = fs.readFileSync(path.join(frontendRoot, 'src/utils/channelVisual.js'), 'utf8')
  assert.match(home, /channelVisualCandidates\(ch\?\.logo_url, visual\)/)
  assert.match(helper, /stable_cover_url/)
  assert.match(helper, /dynamic_cover_url.*cover_url/)
  assert.match(helper, /visual\?\.is_live === true/)
  assert.match(helper, /cover_role === 'content'/)

  assert.deepEqual(channelVisualCandidates('', {
    stable_cover_url: 'stable',
    avatar_url: 'avatar',
    dynamic_cover_url: 'offline-screenshot',
    is_live: false,
  }), ['stable', 'avatar'])
  assert.deepEqual(channelVisualCandidates('', {
    avatar_url: 'avatar',
    dynamic_cover_url: 'live-screenshot',
    is_live: true,
  }), ['avatar', 'live-screenshot'])
  assert.deepEqual(channelVisualCandidates('package-logo', {
    stable_cover_url: 'stable',
    avatar_url: 'avatar',
    dynamic_cover_url: 'live-screenshot',
    is_live: true,
  }), ['package-logo', 'stable', 'avatar', 'live-screenshot'])
})
