# 修改记录

## 2026-05-03 新增：RB_FETCH_COUNTRIES 多地区 Radio Browser 拉取配置

**背景**
之前 `Home.vue` 的 `onMounted` 写死 `fetchStationsByCountry('TW')`，只拉取台湾电台。想加其他地区需要手动改代码，没有注释说明。

**实现**
1. `radioBrowser.js`：新增 `RB_FETCH_COUNTRIES` 常量，集中声明首页要拉取的地区列表，注释说明改法
2. `Home.vue`：导入 `RB_FETCH_COUNTRIES`，`onMounted` 改为 `Promise.all` 并行拉取所有配置地区，结果 `.flat()` 合并

**用法**
只需改 `radioBrowser.js` 的 `RB_FETCH_COUNTRIES` 一行：
```js
export const RB_FETCH_COUNTRIES = ['TW', 'JP']  // 加日本
```
筛选栏的 pill 按钮会自动出现对应地区选项，无需改其他代码。

**改动文件**
- `frontend/src/api/radioBrowser.js`：新增 `RB_FETCH_COUNTRIES`
- `frontend/src/views/Home.vue`：`onMounted` 改为多地区并行拉取

---

## 2026-05-03 修复：筛选后电台列表重复导致数量翻倍、筛选失效

**现象**
首页电台总数显示 117（实际应为约 67），Vue 控制台大量 `Duplicate keys found during update` 警告。连续选择筛选条件后列表数量异常，筛选逻辑失效。

**根因**
`addStation()` 在 `player.js` 中同时更新 `stationMap` 和 `stationList`。`Home.vue` 的 `allStations = stationList + rbStations` 合并了 store 的 `stationList`（已被 `addStation` 追加 RB 电台）和本地 `rbStations`（同样的 RB 电台），导致每个 RB 电台出现两次。Vue 检测到重复 key 后，虚拟 DOM diff 行为异常，筛选结果被覆盖为旧数据。

**修复**
`addStation()` 只更新 `stationMap`（供 AudioEngine/BottomPlayer 查找播放地址和电台名称），不再追加到 `stationList`。`Home.vue` 的 `rbStations` ref 专门负责 RB 电台的显示列表，两者职责分离，不再有重复。

**改动文件**
- `frontend/src/stores/player.js`：`addStation()` 移除 `state.stationList.push(station)`
- `frontend/src/views/Home.vue`：移除调试用 `console.log` 和调试显示文字

---

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

## 2026-05-03 新增：接入 Radio Browser API，自动获取台湾电台

**背景**
手动维护电台列表效率低。Radio Browser 是全球开源电台目录，提供免费 REST API，支持按国家代码筛选，返回的 `url_resolved` 和本项目 `directUrl` 性质相同，可完全复用直连→中转回退链路。

**实现**
1. `api/radioBrowser.js`（新建）：封装 `fetchStationsByCountry(countryCode)`，从 `all.api.radio-browser.info` 拉取电台并映射为本项目 station 格式，国家配置为数组 `RB_COUNTRIES`，新增国家加一行即可
2. `stores/player.js`：新增 `stationList`/`stationMap` 状态（初始值为静态配置），新增 `addStation()` action，支持动态追加电台且去重
3. `views/Home.vue`：从 store 读取 `stationList`，onMounted 拉取 TW 电台追加到 store，computed 合并静态 + 动态电台统一渲染

**改动文件**
- `frontend/src/api/radioBrowser.js`（新建）
- `frontend/src/stores/player.js`
- `frontend/src/views/Home.vue`

---

## 2026-05-03 修复：Radio Browser 电台无法播放 + 播放器显示 ID 而非名称

**现象**
点击 Radio Browser 电台后，前端请求 `/api/rb_xxx/playlist.m3u8`（走 HLS），后端返回 503。播放器名称显示为 `rb_de4271e4-...` 而非电台名称。

**根因**
1. `AudioEngine.vue` 的 `directStreamStationMap` 是模块初始化时从静态 `stationMap` 生成的，Radio Browser 电台是运行时通过 `addStation()` 动态追加到 store 的，不在静态 map 里，`loadStation` 找不到它，直接落入 HLS 分支
2. `BottomPlayer.vue` 从静态配置读 `stationMap`，Radio Browser 电台不在其中，`?.name` 为 undefined，回退显示原始 stationId

**修复**
1. `AudioEngine.vue`：新增 `getDirectUrl()` / `hasDirectUrl()` 函数，从 store 的 `stationMap` 动态查找 directUrl。`loadStation` 在 `directStreamStationMap` 检查之后、HLS 之前新增一步 store 动态查找。错误处理链路同步改为先查 `directStreamStationMap`，再查 store 的 directUrl
2. `BottomPlayer.vue`：移除静态 `stationMap` 导入，改为从 `playerStore.stationMap` 读取，支持动态电台名称

**播放链路（Radio Browser 电台）**
1. `loadStation('rb_xxx')` → `directStreamStationMap` 无 → `getDirectUrl()` 从 store 找到 → `audio.src = url_resolved` → 直连播放
2. 直连失败 → `handleAudioError` → `hasDirectUrl()` true → `fallbackToProxyStream` → `/api/rb_xxx/live`
3. 中转也失败 → 报错

**改动文件**
- `frontend/src/components/AudioEngine.vue`
- `frontend/src/components/BottomPlayer.vue`

---

## 2026-05-03 新增：电台 tags 标签体系 + 前端筛选功能

**背景**
电台数量增多后需要分类筛选。Radio Browser API 的 tags 字段（逗号分隔字符串，如 "music,news,pop"）可直接用于分类。

**实现**
1. `stations.js`：所有静态电台新增 `tags` 数组，同时包含地区（`TW`/`CN`）和类型（`music`/`news`/`talk` 等）
2. `radioBrowser.js`：新增 `parseRbTags()` 函数，将 Radio Browser 的 tags 字符串自动解析归类为本项目统一标签（`music`/`news`/`talk`/`sports`/`religious`/`other`），未知标签归为 `other`
3. `Home.vue`：新增筛选栏（地区 pill + 类型 pill），从所有电台 tags 自动提取可用选项，computed 过滤电台列表，点击切换筛选

**标签设计**
- 地区：`TW`（台湾）、`CN`（中国大陆）、`JP`、`US`、`KR` 等 ISO 代码
- 类型：`music`（音乐）、`news`（新闻）、`talk`（谈话）、`sports`（体育）、`religious`（宗教）、`other`（其他）
- 新增地区/类型：改 `stations.js` 的 tags 和 `radioBrowser.js` 的 `TAG_TYPE_MAP` / `regionLabels` / `typeLabels` 即可

**改动文件**
- `frontend/src/config/stations.js`
- `frontend/src/api/radioBrowser.js`
- `frontend/src/views/Home.vue`

---

## 2026-05-03 修复：连续切换筛选条件后列表显示异常

**现象**
连续选择多个筛选条件后，列表显示不符合预期（如选"其他"+"中国大陆"后仍显示大量电台）。

**根因**
`filteredStations` 使用 `computed` 包含 `.filter()` 循环遍历。连续快速切换筛选条件时，Vue 的 `computed` 依赖追踪在复杂循环内可能丢失对 `selectedRegion`/`selectedType` 的追踪，导致使用旧的筛选状态。

**修复**
将 `filteredStations` 从 `computed` 改为 `ref` + `watch`。`watch` 显式声明 `[allStations, selectedRegion, selectedType]` 三个依赖，任一变化都触发重新计算，`immediate: true` 保证初始加载也执行。

**改动文件**
- `frontend/src/views/Home.vue`

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
