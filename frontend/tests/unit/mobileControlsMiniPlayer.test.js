import assert from 'node:assert/strict'
import fs from 'node:fs'
import path from 'node:path'
import test from 'node:test'
import { fileURLToPath } from 'node:url'

const frontendRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../..')

function source(relativePath) {
  return fs.readFileSync(path.join(frontendRoot, relativePath), 'utf8')
}

test('Mobile header controls share 40px visuals with 44px hit targets', () => {
  const css = source('src/style.css')
  assert.match(css, /\.mobile-action-btn::before \{[\s\S]*?inset: 2px;/)
  assert.match(css, /\.mobile-action-btn > svg \{[\s\S]*?width: 1\.125rem;[\s\S]*?height: 1\.125rem;/)
  assert.match(css, /\.mobile-search-shell \{[\s\S]*?background: transparent;[\s\S]*?box-shadow: none;/)
  assert.match(css, /\.mobile-search-collapsed::before \{[\s\S]*?inset: 2px;/)
  assert.match(css, /\.mobile-search-collapsed::before \{[\s\S]*?box-shadow: 0 2px 8px rgba\(0, 0, 0, 0\.06\);/)
  assert.match(css, /\.mobile-search-expanded \{[\s\S]*?border-width: 1px;/)
  assert.match(css, /\.mobile-search-trigger \{[\s\S]*?width: 2\.75rem;[\s\S]*?height: 2\.75rem;/)
  assert.doesNotMatch(source('src/App.vue'), /mobile-search-shell[^>]*shadow-sm|mobile-mode-switch[^>]*shadow-sm/)
})

test('Radio/TV segmented control remains a compact 14px control', () => {
  const app = source('src/App.vue')
  assert.match(app, /mobile-mode-switch flex h-10[\s\S]*text-sm/)
  assert.equal((app.match(/class="flex h-9 items-center rounded-full px-3 transition-all sm:px-4"/g) || []).length, 2)
})

test('IPTV filter chips keep 44px interaction boxes with 40px visual pills', () => {
  const tag = source('src/components/TagFilterRow.vue')
  const css = source('src/style.css')

  assert.match(tag, /tag-filter-row__item/)
  assert.match(tag, /tag-filter-row__item--selected/)
  assert.match(tag, /tag-filter-row__more/)
  assert.match(css, /\.iptv-main \.tag-filter-row__item,[\s\S]*?height: 2\.75rem;/)
  assert.match(css, /\.iptv-main \.tag-filter-row__item::before,[\s\S]*?inset: 2px;/)
})

test('IPTV section controls reduce visible weight without changing sort/density semantics', () => {
  const home = source('src/views/IptvHome.vue')
  const css = source('src/style.css')

  assert.match(home, /class="iptv-density-menu"/)
  assert.match(home, /class="iptv-sort-trigger inline-flex h-10/)
  assert.match(css, /\.iptv-main \.iptv-density-menu__trigger::before \{[\s\S]*?inset: 2px;/)
  assert.match(css, /\.iptv-main \.iptv-sort-trigger::before \{[\s\S]*?inset: 2px;/)
  assert.match(css, /\.iptv-main \.iptv-sort-trigger > svg \{[\s\S]*?width: 1\.125rem;/)
})

test('Mobile BottomPlayer uses bounded 72px presentation and preserves playback controls', () => {
  const player = source('src/components/BottomPlayer.vue')
  const css = source('src/style.css')

  for (const token of [
    'mobile-player-shell',
    'mobile-player-logo',
    'mobile-player-title',
    'mobile-player-status',
    'mobile-player-play-btn',
    'mobile-player-side-icon',
    'mobile-player-list-btn',
    'mobile-player-volume',
  ]) {
    assert.match(player, new RegExp(token))
  }
  assert.match(player, /mobile-player-shell[^>]*h-\[72px\][^>]*rounded-\[18px\]/)
  assert.match(css, /\.mobile-player-shell \{[\s\S]*?height: 4\.5rem;[\s\S]*?border-radius: 1\.125rem;/)
  assert.match(css, /\.mobile-player-info \{[\s\S]*?flex-basis: 30%;/)
  assert.match(css, /\.mobile-player-actions \{[\s\S]*?flex-basis: 30%;/)
  assert.match(css, /\.mobile-player-play-btn \{[\s\S]*?width: 3\.25rem;[\s\S]*?height: 3\.25rem;/)
  assert.match(css, /\.mobile-player-list-btn::before \{[\s\S]*?inset: 2px;/)
  assert.match(css, /\.mobile-player-volume \{[\s\S]*?width: 3rem;/)
  assert.match(css, /\.bottom-player-dock \{[\s\S]*?bottom: calc\(env\(safe-area-inset-bottom\) \+ 0\.75rem\);/)
  assert.match(css, /\.iptv-main \{\s*padding-bottom: calc\(env\(safe-area-inset-bottom\) \+ 6rem\);/)
})

test('Desktop BottomPlayer sizing remains on the existing lg path', () => {
  const player = source('src/components/BottomPlayer.vue')
  const css = source('src/style.css')

  assert.match(player, /lg:h-24/)
  assert.match(css, /@media \(min-width: 1024px\) \{[\s\S]*?\.bottom-player-dock \{[\s\S]*?left: calc\(var\(--sidebar-w\) \+ 40px\);/)
})
