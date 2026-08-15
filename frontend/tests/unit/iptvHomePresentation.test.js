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
