import test from 'node:test'
import assert from 'node:assert/strict'
import { createPinia, setActivePinia } from 'pinia'

import { usePlayerStore } from '../../src/stores/player.js'

function radio(id, name, sourceId, state = 'active') {
  return {
    id,
    name,
    radioDomain: 'radio',
    radioStationId: id,
    radioSourceId: sourceId,
    radioSources: [{ source_id: sourceId, lifecycle_state: state }],
    tags: ['CN'],
  }
}

test('Radio catalog refresh updates existing station metadata and source state', () => {
  setActivePinia(createPinia())
  const store = usePlayerStore()
  store.loadStations([{ id: 'tf_909', name: '香港台' }])
  store.addRadioStations([radio('radio_a', '旧名称', 'source_a')])
  store.addRadioStations([radio('radio_a', '新名称', 'source_b', 'stale')])

  assert.equal(store.stationMap.radio_a.name, '新名称')
  assert.equal(store.stationMap.radio_a.radioSourceId, 'source_b')
  assert.equal(store.stationMap.radio_a.radioSources[0].lifecycle_state, 'stale')
  assert.ok(store.stationMap.tf_909)
})

test('successful empty Radio catalog removes old dynamic rows but keeps static rows', () => {
  setActivePinia(createPinia())
  const store = usePlayerStore()
  store.loadStations([{ id: 'tf_909', name: '香港台' }])
  store.addRadioStations([radio('radio_a', '电台', 'source_a')])
  store.addRadioStations([])

  assert.equal(store.stationMap.radio_a, undefined)
  assert.deepEqual(store.stationList.map((item) => item.id), ['tf_909'])
})

test('Radio selection and explicit Play keep distinct playback intents', () => {
  setActivePinia(createPinia())
  const store = usePlayerStore()
  store.addRadioStations([radio('radio_a', '电台', 'source_a')])

  store.switchStation('radio_a')
  assert.equal(store.consumeRadioPlaybackIntent(), 'station_click')
  assert.equal(store.consumeRadioPlaybackIntent(), 'passive')

  store.togglePlay(false)
  store.togglePlay(true)
  assert.equal(store.consumeRadioPlaybackIntent(), 'play_button')

  store.selectRadioSource('radio_a', 'source_a')
  assert.equal(store.consumeRadioPlaybackIntent(), 'source_switch')
})
