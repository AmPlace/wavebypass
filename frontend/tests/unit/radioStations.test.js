import test from 'node:test'
import assert from 'node:assert/strict'

import { fetchRadioStations, fetchRadioProgramme, mapRadioStationForTest } from '../../src/api/radioStations.js'

test('Radio catalog maps explicit station/source identity without upstream URLs', async () => {
  const station = mapRadioStationForTest({
    station_id: 'radio_station_yunting',
    name: '云听新闻',
    country: 'CN',
    group_name: '北京',
    metadata: { subtitle: '午间新闻' },
    sources: [{
      source_id: 'radio_source_1',
      provider_key: 'yunting',
      provider_station_id: 'content-1',
      lifecycle_state: 'active',
      reference: { playback_config: { stream_url: 'https://upstream.invalid/live.m3u8' } },
    }],
  })

  assert.equal(station.id, 'radio_station_yunting')
  assert.equal(station.radioStationId, 'radio_station_yunting')
  assert.equal(station.radioSourceId, 'radio_source_1')
  assert.equal('directUrl' in station, false)
  assert.equal(JSON.stringify(station).includes('upstream.invalid'), false)
})

test('Radio catalog fetch uses the bounded domain endpoint and preserves duplicate names', async () => {
  const calls = []
  const stations = await fetchRadioStations({
    fetchImpl: async (url) => {
      calls.push(String(url))
      return {
        ok: true,
        json: async () => ({ stations: [
          { station_id: 'radio_a', name: '同名', sources: [{ source_id: 'source_a', lifecycle_state: 'active' }] },
          { station_id: 'radio_b', name: '同名', sources: [{ source_id: 'source_b', lifecycle_state: 'active' }] },
        ] }),
      }
    },
  })

  assert.deepEqual(calls, ['/api/radio/stations'])
  assert.deepEqual(stations.map((station) => station.id), ['radio_a', 'radio_b'])
})

test('Radio programme fetch submits only the persisted source_id', async () => {
  const calls = []
  const result = await fetchRadioProgramme({ radioStationId: 'radio_a', radioSourceId: 'source_a' }, {
    fetchImpl: async (url) => {
      calls.push(String(url))
      return { ok: true, json: async () => ({ programmes: [] }) }
    },
  })

  assert.deepEqual(result, { programmes: [] })
  assert.equal(calls[0], '/api/radio/stations/radio_a/programme?source_id=source_a')
})
