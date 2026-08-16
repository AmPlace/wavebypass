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

test('FullPlayer video-first geometry has one sizing authority and no fixed rail jump', () => {
  assert.match(fullPlayer, /--layout-gap: clamp\(20px, 1\.7vw, 24px\)/)
  assert.match(fullPlayer, /--channel-logo-size: 48px/)
  assert.match(fullPlayer, /--channel-min-height: 64px/)
  assert.match(fullPlayer, /minmax\(300px, 400px\)/)
  assert.match(fullPlayer, /calculateFullPlayerSizing\(/)
  assert.match(fullPlayer, /full-player--mobile-layout/)
  assert.doesNotMatch(fullPlayer, /const isWideViewport = viewportWidth >= 1440/)
})

test('FullPlayer 1.5 overlay provides delayed loading, status, and unified volume semantics', () => {
  assert.match(template, /class="video-loading-indicator"/)
  assert.match(template, /class="video-loading-spinner"/)
  assert.match(template, /class="video-overlay-status"/)
  assert.match(template, /class="video-overlay-volume-panel"/)
  assert.match(template, /:value="effectiveVolume"/)
  assert.match(template, /@input="setOverlayVolume\(\$event\.target\.value\)"/)
  assert.match(fullPlayer, /setTimeout\(\(\) => \{[\s\S]*?isOverlayLoadingCandidate\.value/s)
  assert.match(fullPlayer, /const overlayPlaybackStatusText = computed/)
  assert.match(fullPlayer, /const volumeIconState = computed/)
})

test('FullPlayer 1.5 desktop metadata uses structured next-programme fields', () => {
  assert.match(template, /:class="\{ 'now-metadata--without-programme': !hasProgrammeMetadata \}"/)
  assert.match(template, /v-if="hasProgrammeMetadata" class="now-programme"/)
  assert.match(template, /class="desktop-now-program-next"[\s\S]*?下一节目[\s\S]*?desktop-now-program-next__title/)
  assert.match(fullPlayer, /\.now-panel \.mobile-now-program-next/)
  assert.match(fullPlayer, /\.now-panel \.desktop-now-program-next/)
  assert.doesNotMatch(fullPlayer, /暂无节目单/)
})

test('FullPlayer overlay activity hides only stable playback and restores on interaction', () => {
  assert.match(template, /@pointerenter="handleOverlayActivity"/)
  assert.match(template, /@pointermove="handleOverlayActivity"/)
  assert.match(template, /@keydown\.capture="handlePlayerKeyboard"/)
  assert.match(template, /@focusin\.capture="handleOverlayFocusIn"/)
  assert.match(template, /:class="\{ 'is-hidden': isDesktopOverlayHidden \}"/)
  assert.match(fullPlayer, /}, 2800\)/)
  assert.match(fullPlayer, /}, 900\)/)
  assert.match(fullPlayer, /overlayControlsFocused\.value/)
  assert.match(fullPlayer, /overlayVolumeInteracting\.value/)
  assert.match(fullPlayer, /sourceMenuOpen\.value/)
})

test('FullPlayer desktop shortcuts reuse the existing capture path without a second global keydown listener', () => {
  assert.match(template, /ref="playerRootRef"[\s\S]*?tabindex="-1"/)
  assert.match(fullPlayer, /function handlePlayerKeyboard\(event\)/)
  assert.match(fullPlayer, /const KEYBOARD_VOLUME_STEP = 0\.05/)
  assert.match(fullPlayer, /code === 'Space' \|\| code === 'KeyK'/)
  assert.match(fullPlayer, /code === 'KeyM'/)
  assert.match(fullPlayer, /code === 'KeyF'/)
  assert.match(fullPlayer, /code === 'PageUp' \|\| code === 'PageDown'/)
  assert.match(fullPlayer, /event\.repeat && !isVolumeShortcut/)
  assert.match(fullPlayer, /event\.preventDefault\(\)/)
  assert.match(fullPlayer, /input, textarea, select, option, button, a/)
  assert.doesNotMatch(fullPlayer, /addEventListener\(['"]keydown['"]/)
})

test('FullPlayer custom fullscreen targets the media wrapper and tracks fullscreenchange', () => {
  assert.match(template, /ref="mediaSurfaceRef"[\s\S]*?class="media-card"/)
  assert.match(fullPlayer, /target\.requestFullscreen/)
  assert.match(fullPlayer, /document\.addEventListener\('fullscreenchange', handleFullscreenChange\)/)
  assert.match(fullPlayer, /document\.removeEventListener\('fullscreenchange', handleFullscreenChange\)/)
  assert.match(fullPlayer, /mediaSurfaceRef\.value\.contains\(fullscreenElement\)/)
  const videoTag = template.match(/<video[\s\S]*?<\/video>/)?.[0] || ''
  assert.doesNotMatch(videoTag, /\bcontrols(?:=|\s)/)
})

test('FullPlayer separates source selector and Desktop channel rail controls', () => {
  assert.match(template, /aria-label="切换播放源"[\s\S]*?m4\.5 7 7\.5-3 7\.5 3/s)
  assert.match(template, /:aria-label="isFullscreen \? '全屏中不可显示频道列表' : \(isRailLayout \? '隐藏频道列表' : '显示频道列表'\)"/)
  assert.match(template, /:aria-expanded="isRailLayout"/)
  assert.match(fullPlayer, /function toggleDesktopRail\(\)/)
  assert.match(fullPlayer, /desktopRailPreference\.value = isRailLayout\.value \? 'hidden' : 'shown'/)
  assert.match(fullPlayer, /full-player--theater/)
  assert.match(fullPlayer, /sourceMenuTeleportTarget/)
  assert.match(fullPlayer, /source-menu-in-fullscreen/)
})

test('Desktop rail keeps its presentation rules scoped away from Mobile FullPlayer', () => {
  assert.match(fullPlayer, /\.side-panel \{[\s\S]*?--channel-logo-size: 46px;[\s\S]*?--channel-min-height: 62px;/)
  assert.match(fullPlayer, /\.side-panel \.channel-logo img \{[\s\S]*?object-fit: contain;/)
  assert.match(fullPlayer, /\.channel-logo img \{[\s\S]*?object-fit: cover;/)
  assert.match(fullPlayer, /\.channel-logo \{[\s\S]*?width: var\(--channel-logo-size\);[\s\S]*?height: var\(--channel-logo-size\);[\s\S]*?overflow: hidden;/)
  assert.match(fullPlayer, /\.side-panel \.channel-row\.active \{[\s\S]*?box-shadow: inset 2px 0 0 var\(--accent\)/)
  assert.match(fullPlayer, /\.side-panel \.sort-btn:focus-visible/)
  assert.match(fullPlayer, /\.desktop-panel-scroll::-webkit-scrollbar/)
  assert.match(fullPlayer, /class="channel-title-text">\{\{ item\.name \}\}<\/span>/)
})
