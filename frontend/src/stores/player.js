// 引入 Pinia 的 defineStore，用来创建一个全局状态仓库。
import { defineStore } from 'pinia'

// 创建播放器状态仓库。
// 其他 Vue 组件可以通过 usePlayerStore() 读取播放状态，也可以调用这里的 actions 改变播放行为。
export const usePlayerStore = defineStore('player', {
  // state 是播放器的全局状态。
  // 这里使用函数返回对象，是 Pinia 推荐写法，可以避免服务端渲染或测试时状态互相污染。
  state: () => ({
    // 当前是否处于播放状态。
    isPlaying: false,

    // 当前是否正在连接音频源。
    // 切台、加载 m3u8、尝试直连流或中转流时会短暂变成 true。
    isLoading: false,

    // 当前选择的电台 ID。
    // 初始值先使用 hitfm，后续 UI 可以通过 switchStation 切换为 ufo 等其他电台。
    currentStation: 'hitfm',

    // 当前音量，范围约定为 0 到 1。
    // 1 表示最大音量，0 表示静音。
    volume: 1,

    // 当前播放错误信息。
    // 为空字符串表示没有错误；有内容时底部播放器会展示给用户。
    playbackError: '',
  }),

  // actions 是改变状态的方法。
  // 把状态变更集中放在这里，后续排查播放问题会更清晰。
  actions: {
    // 切换当前电台。
    // stationId 对应后端路由中的 {station_id}，例如 hitfm 会请求 /api/hitfm/playlist.m3u8。
    switchStation(stationId) {
      // 如果传入空字符串或 undefined，直接忽略，避免把播放器切到无效电台。
      if (!stationId) {
        return
      }

      // 写入新的电台 ID。
      this.currentStation = stationId

      // 切换电台时清空上一条错误，避免旧错误影响新电台判断。
      this.playbackError = ''

      // 切换电台后立刻进入连接中状态，让 UI 有一个轻量反馈。
      this.isLoading = true

      // 用户主动切换电台时，默认认为希望继续播放。
      // 真正能否播放成功，由 AudioEngine 捕捉浏览器自动播放限制后再同步回来。
      this.isPlaying = true
    },

    // 播放或暂停。
    // 如果调用时不传参数，就在播放和暂停之间切换。
    // 如果传入 true 或 false，就强制设置为指定状态。
    togglePlay(forcePlaying) {
      // 判断调用方是否明确给了布尔值。
      const hasForcedValue = typeof forcePlaying === 'boolean'

      // 有明确值就使用明确值；没有明确值就取反当前状态。
      this.isPlaying = hasForcedValue ? forcePlaying : !this.isPlaying
    },

    // 设置加载状态。
    setLoading(nextLoading) {
      this.isLoading = Boolean(nextLoading)
    },

    // 设置音量。
    // volumeValue 推荐传入 0 到 1 之间的小数，例如 0.5 表示 50% 音量。
    setVolume(volumeValue) {
      // Number(...) 可以把 input range 传来的字符串数字转成真正的数字。
      const nextVolume = Number(volumeValue)

      // 如果转换后不是有效数字，直接忽略，避免 audio.volume 收到 NaN。
      if (Number.isNaN(nextVolume)) {
        return
      }

      // 把音量限制在 0 到 1 之间，防止 UI 或调用方传入越界值。
      this.volume = Math.min(1, Math.max(0, nextVolume))
    },

    // 设置播放错误信息。
    setPlaybackError(message) {
      // 统一转成字符串，避免传入 Error 对象时界面显示成奇怪内容。
      this.playbackError = message ? String(message) : ''

      // 出现错误时结束加载状态。
      if (this.playbackError) {
        this.isLoading = false
      }
    },

    // 清空播放错误信息。
    clearPlaybackError() {
      this.playbackError = ''
    },
  },
})
