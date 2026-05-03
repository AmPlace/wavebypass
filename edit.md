# 修改记录

## 2026-05-03 修复：简单直链电台走 HLS playlist 问题

**背景**
新增台湾城市广播网（cityfm）电台，`stations.js` 配置了 `directUrl` 直链地址，期望前端直接用 `<audio>` 原生播放。

**现象**
前端始终请求 `/api/cityfm/playlist.m3u8`，后端返回 `503 Service Unavailable`，电台无法播放。

**原因**
`AudioEngine.vue` 的 `loadStation` 函数（第 174 行）硬编码拼接 `playlistUrl = /api/${stationId}/playlist.m3u8`，完全没读 `stationMap` 里的 `directUrl` 字段。只有 `directStreamStationMap`（仅硬编码了 `ufo`）的电台能走直连，其他电台全部走 HLS。

**修复**
在 `AudioEngine.vue` 的 `loadStation` 中，`directStreamStationMap` 判断之后、HLS 初始化之前，新增一段判断：若 `stationMap[stationId]` 有 `directUrl` 且无 `livePath`，直接设 `audio.src` 为直链地址播放，跳过 HLS。

**改动文件**
- `frontend/src/components/AudioEngine.vue`：`loadStation` 新增 directUrl 自动识别逻辑
- `frontend/src/config/stations.js`：新增 cityfm 电台配置

---

## 2026-05-03 修复：directUrl 电台无回退机制，统一直连回退逻辑

**背景**
之前 directUrl 电台只做了"直连播放"，播放失败就停止，没有自动回退到后端反代。只有 `directStreamStationMap`（硬编码 ufo）有完整的直连→中转回退链路。

**问题**
1. `directStreamStationMap` 只硬编码了 ufo，stationMap 里的 directUrl 电台（如 cityfm）不在其中，无法触发回退
2. `handleAudioError` 只认识 `directStreamStationMap`，directUrl 电台触发 audio 错误时直接报错停止
3. HLS 致命错误时也没有尝试 directUrl 回退，直接停止

**修复方案**
- `directStreamStationMap` 不再纯硬编码，启动时自动合并 `stationMap` 里所有带 `directUrl` 的电台，生成统一的 `{ directUrl, proxyUrl }` 映射
- `loadStation` 中删除冗余的 directUrl 判断分支，统一走 `directStreamStationMap` 路径，复用 `directStreamMode` 状态追踪
- `handleAudioError` 无需修改，已能识别合并后的 directUrl 电台并触发 `fallbackToProxyStream`
- HLS 致命错误处理新增 directUrl 回退：若该电台在 `directStreamStationMap` 中，先尝试直连，而非直接报错

**完整回退链路（以 cityfm 为例）**
1. 直连：`audio.src = directUrl` → 成功则播放 ✓
2. 直连失败：`handleAudioError` → `fallbackToProxyStream` → `audio.src = /api/cityfm/live` → 尝试中转
3. 中转也失败：`directStreamMode === 'proxy'` → 报错"后端中转音频流连接失败"

**改动文件**
- `frontend/src/components/AudioEngine.vue`：`directStreamStationMap` 改为自动合并，删除冗余 directUrl 分支，HLS 错误处理新增回退

---

## 2026-05-03 重构：移除 UFO 硬编码，统一由 stations.js 配置驱动

**背景**
UFO 电台之前在 `AudioEngine.vue` 里硬编码了 `UFO_DIRECT_STREAM_URL` 和专属的 `directStreamStationMap.ufo` 条目，新增电台或修改 URL 需要改两处（stations.js + AudioEngine.vue），不便于维护。

**改法**
- `stations.js`：给 ufo 加 `directUrl`（直连地址）和 `livePath`（HLS 代理路径），配置集中在一处
- `AudioEngine.vue`：删除硬编码的 `UFO_DIRECT_STREAM_URL` 和 `directStreamStationMap` 中的 ufo 条目，改为纯自动合并 `stationMap`
- `proxyUrl` 生成逻辑修正：有 `livePath` 的电台（如 ufo）走 `/api/{id}/stream`（直连流代理），没有 `livePath` 的（如 cityfm）走 `/api/{id}/live`（HLS 代理）

**效果**
- ufo 和 cityfm 共用同一套 `directStreamStationMap` 自动生成逻辑，无硬编码
- 新增简单直链电台只需在 `stations.js` 加 `directUrl`，`AudioEngine.vue` 完全不用改
- ufo 回退行为不变：直连失败 → `/api/ufo/stream` 后端中转

**改动文件**
- `frontend/src/config/stations.js`：ufo 新增 directUrl、livePath
- `frontend/src/components/AudioEngine.vue`：移除 ufo 硬编码，directStreamStationMap 改为纯自动合并，修正 proxyUrl 生成规则

---

## 2026-05-03 新增：中广系列 + iGO531 共 5 个电台

**电台列表**
| id | 名称 | 直链地址 |
|---|---|---|
| bcc_news | 中广新闻网 | https://stream.rcs.revma.com/fgtx07f3qtzuv |
| bcc_pop | 中广流行网 | https://stream.rcs.revma.com/s1zttsg3qtzuv |
| bcc_music | 中广音乐网 | https://stream.rcs.revma.com/ks4vsmg3qtzuv |
| igot531 | iGO531 | https://stream.rcs.revma.com/1qxn2vg3qtzuv |
| bcc_rural | 中广乡亲网 | https://stream.rcs.revma.com/p2e3rfg3qtzuv |

**改动文件**
- `frontend/src/config/stations.js`：新增 5 条 directUrl 配置

**无需其他改动**
AudioEngine.vue 的 directStreamStationMap 自动合并所有 directUrl 电台，前端直连播放 + 失败回退后端中转均自动生效。
