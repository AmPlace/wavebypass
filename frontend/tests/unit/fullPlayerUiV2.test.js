import assert from 'node:assert/strict'
import { test } from 'node:test'
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const frontendRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../..')
const fullPlayer = fs.readFileSync(path.join(frontendRoot, 'src/components/FullPlayer.vue'), 'utf8')
const template = fullPlayer.split('<script setup>')[0]

test('FullPlayer Desktop overlay owns programme progress and keeps it non-seekable', () => {
  assert.match(template, /class="video-overlay desktop-video-overlay"/)
  const progressBlock = template.match(/class="program-progress video-overlay-progress"[\s\S]*?<div class="video-overlay-controls">/)?.[0] || ''
  assert.match(progressBlock, /role="progressbar"/)
  assert.doesNotMatch(progressBlock, /<input/)
  assert.doesNotMatch(progressBlock, /progress-knob/)
  assert.match(template, /class="video-overlay-button video-overlay-button--main"[\s\S]*?@click="playerStore\.togglePlay\(\)"/)
  assert.match(template, /class="video-overlay-button video-overlay-button--utility"[\s\S]*?aria-label="全屏"/)
})

test('FullPlayer channel rows use logical identity instead of sorted index keys', () => {
  assert.match(fullPlayer, /key: `iptv-\$\{channelIdentity\(ch\) \|\| ch\.canonical_key \|\| ch\.name\}`/)
  assert.doesNotMatch(fullPlayer, /key: `iptv-\$\{ch\.name\}-\$\{index\}`/)
})

test('FullPlayer Desktop geometry keeps a flexible 16:9 main area and compact side rail', () => {
  assert.match(fullPlayer, /--layout-gap: clamp\(20px, 1\.7vw, 24px\)/)
  assert.match(fullPlayer, /--channel-logo-size: 48px/)
  assert.match(fullPlayer, /--channel-min-height: 64px/)
  assert.match(fullPlayer, /minmax\(300px, 340px\)/)
  assert.match(fullPlayer, /const preferredPanelWidth = Math\.min\(340, Math\.max\(320, viewportWidth \* 0\.24\)\)/)
})
