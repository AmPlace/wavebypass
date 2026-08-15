import assert from 'node:assert/strict'
import fs from 'node:fs'
import path from 'node:path'
import test from 'node:test'
import { fileURLToPath } from 'node:url'

import { iptvCardProgrammeTitle } from '../../src/utils/iptvViewing.js'

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

test('IPTV Home 支持 Standard/Compact presentation density，Compact 不渲染 footer', () => {
  const home = fs.readFileSync(path.join(frontendRoot, 'src/views/IptvHome.vue'), 'utf8')
  const styles = fs.readFileSync(path.join(frontendRoot, 'src/style.css'), 'utf8')
  assert.match(home, /iptv-density-compact/)
  assert.match(home, /iptv-density-menu/)
  assert.match(home, /data-density-option="standard"/)
  assert.match(home, /role="switch"/)
  assert.doesNotMatch(home, /iptv-density-toggle__button/)
  assert.match(home, /v-if="densityMode === 'standard'" class="card-info"/)
  assert.match(home, /v-else-if="isCompactStatusVisible\(item\.channel\)"/)
  assert.match(home, /defaultIptvCardDensity\(viewportWidth\.value\)/)
  assert.match(home, /writeIptvCardDensityPreference\(value\)/)
  assert.match(styles, /\.iptv-main\.iptv-density-compact \.channel-card--logo-card::after,/)
  assert.match(styles, /\.iptv-main\.iptv-density-compact \.channel-card__logo-stage:not\(/)
  assert.match(styles, /\.iptv-main\.iptv-density-compact \.channel-card__compact-status/)
})

test('IPTV density menu keeps the user-facing information switch semantics', () => {
  const home = fs.readFileSync(path.join(frontendRoot, 'src/views/IptvHome.vue'), 'utf8')
  assert.match(home, /aria-label="显示频道信息"/)
  assert.match(home, /densityMode === 'standard' \? 'compact' : 'standard'/)
  assert.match(home, /标准：Logo、频道名和节目/)
  assert.match(home, /紧凑：仅显示 Logo/)
})
