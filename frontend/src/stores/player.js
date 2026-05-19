import { defineStore } from 'pinia'

export const usePlayerStore = defineStore('player', {
  state: () => ({
    isPlaying: false,
    isLoading: false,
    currentStation: '',
    volume: 1,
    playbackError: '',
    stationList: [],
    stationMap: {},
    isPlayerExpanded: false,
    activeMode: 'radio',  // 'radio' | 'iptv'
  }),

  getters: {
    stationCount: (state) => state.stationList.length,
  },

  actions: {
    // stationId 对应后端路由中的 {station_id}
    switchStation(stationId) {
      if (!stationId) {
        return
      }

      this.currentStation = stationId

      this.playbackError = ''

      this.isLoading = true

      this.isPlaying = true
    },


    togglePlay(forcePlaying) {
      const hasForcedValue = typeof forcePlaying === 'boolean'

      this.isPlaying = hasForcedValue ? forcePlaying : !this.isPlaying
    },

    setLoading(nextLoading) {
      this.isLoading = Boolean(nextLoading)
    },

    setVolume(volumeValue) {
      const nextVolume = Number(volumeValue)

      if (Number.isNaN(nextVolume)) {
        return
      }

      this.volume = Math.min(1, Math.max(0, nextVolume))
    },

    setPlaybackError(message) {
      this.playbackError = message ? String(message) : ''

      if (this.playbackError) {
        this.isLoading = false
      }
    },

    clearPlaybackError() {
      this.playbackError = ''
    },

    addStation(station) {
      if (this.stationMap[station.id]) return
      // 只更新 stationMap（供 AudioEngine/BottomPlayer 查找播放地址和电台名称）
      // 不更新 stationList，因为 Home.vue 有自己的 rbStations 列表单独管理显示
      this.stationMap[station.id] = station
    },

    loadStations(stations) {
      this.stationList = stations
      const merged = { ...this.stationMap }
      for (const s of stations) merged[s.id] = s
      this.stationMap = merged
      if (!this.currentStation && stations.length) {
        this.currentStation = stations[0].id
      }
    },

    updateStationEpg(stationId, subtitle) {
      const station = this.stationMap[stationId]
      if (station) station.subtitle = subtitle
    },

    expandPlayer() {
      this.isPlayerExpanded = true
    },

    collapsePlayer() {
      this.isPlayerExpanded = false
    },

    setActiveMode(mode) {
      this.activeMode = mode
    },
  },
})
