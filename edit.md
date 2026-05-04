# 修改记录

## 2026-05-04 修改：虚拟滚动改用 @vueuse/core，滚动容器重构，修复移动端卡片间距

**背景**
纯 JS 手写虚拟滚动虽然性能达标，但代码复杂度高，用户无法自行维护。决定改用 `@vueuse/core` 提供的 `useScroll` + `useThrottleFn` 组合，大幅简化滚动追踪逻辑。

**方案选型**
- `content-visibility: auto`（CSS 原生）：跳过屏幕外渲染，但 DOM 节点和图片请求仍然全部创建，不能解决图片并发问题
- `@tanstack/vue-virtual`（第三方库）：初始化时 `getScrollElement` 返回 null 导致内部 watcher 崩溃，排查后放弃
- 纯 JS 手写虚拟滚动：性能达标但代码复杂，维护困难
- **最终方案：@vueuse/core 的 `useScroll` + `useThrottleFn`**：用成熟库处理滚动追踪和节流，手写虚拟行计算逻辑保持简洁可控

**实现**
- 滚动容器从 `Home.vue` 的 `main` 移到 `App.vue` 根 `div`（`h-dvh overflow-y-auto`），滚动条贴紧浏览器右侧边缘
- `Home.vue` 通过 `inject('scrollRef')` 获取 App.vue 的滚动容器 ref
- `useScroll`（@vueuse/core）自动追踪滚动位置，兼容 iOS Safari 弹性滚动
- `useThrottleFn` 节流到 60fps（16ms），避免低端机频繁计算
- `gridRef` 独立 ref，`ResizeObserver` 监听 grid 容器实际内容宽度（受 `max-w-7xl` 和 padding 约束），动态计算响应式列数（2/4/6 列）
- `virtualRows` computed 只取当前可视区域 ±3 行缓冲，约 30~40 个 DOM 节点
- `totalHeight` 撑开滚动容器高度，浏览器显示正常滚动条
- 筛选栏用 `shrink-0` 固定在滚动区域顶部，不参与虚拟滚动

**iOS Safari 修复**
- `h-dvh` 替代 `h-screen`：`100vh` 在 iOS Safari 包含地址栏高度，`dvh` 是排除地址栏后的动态视口高度
- `Math.max(0, ...)` 钳制 scrollTop：iOS Safari 弹性滚动会出现负值，导致 translateY 异常

**移动端卡片间距修复**
- 行间距从响应式值（移动端 16px，桌面 20px）统一为 20px，避免移动端卡片上下紧贴
- `gap` computed 简化为固定 `20`，和 Tailwind `gap-5` 一致
- Grid 的 `gap` 从 Tailwind 响应式类（`gap-4 sm:gap-5`）改为动态 style 绑定（`:style="{ gap: '20px' }"`），彻底消除 CSS/JS gap 不一致导致卡片溢出吃掉行间距的问题
- Safari `aspect-ratio` bug 修复：Safari（iOS + macOS）在 Grid 布局中 `aspect-ratio` 不能正确约束卡片高度，卡片溢出后吃掉行间距。去掉 `aspect-square`，改为 JS 算出精确卡片宽度后设为内联 `height`，完全绕过 Safari 的 aspect-ratio 实现缺陷
- ResizeObserver 高度跳变动画 bug 修复：`containerWidth` 初始值为 1024，ResizeObserver 触发后才更新为真实值，`cardSize` 随之变化。`transition-all` 会把高度变化也带动画，导致第一行卡片先短一截再延长。将 `transition-all` 改为 `transition-[background-color,transform,box-shadow,border-color]`，只过渡 hover 真正需要的属性，高度变化瞬间完成无动画

**性能对比**
- 优化前：1000 条电台全部创建 DOM 节点，1000 张图片同时请求
- 优化后：任意时刻只创建约 30~40 个 DOM 节点，只加载屏幕内可见的几十张图片

**改动文件**
- `frontend/src/views/Home.vue`：改用 `useScroll` + `useThrottleFn`，滚动追踪逻辑大幅简化，gap 统一为 20px
- `frontend/src/App.vue`：根 div 改为滚动容器（`h-dvh overflow-y-auto`），`provide('scrollRef')`
- `frontend/package.json`：移除 `@tanstack/vue-virtual`，保留 `@vueuse/core`

---

## 2026-05-04 修复：m3u8 切片改写不支持 .aac/.mp3 等非 .ts 格式

**现象**
福建交通广播（tingfm）的 m3u8 使用 `.aac` 切片，后端返回的 m3u8 中 segment URL 原样保留未改写，前端请求 `/api/fj_traffic/segmentxxx.aac` 返回 404。

**根因**
`rewrite_m3u8_text` 的切片判断条件是 `uri_path.endswith(".ts")`，只认 `.ts` 格式。`.aac`、`.mp3`、`.mp4` 等常见 HLS 切片格式被跳过，原样返回给前端。

**修复**
切片判断从单一 `.ts` 扩展为已知切片格式元组：`(".ts", ".aac", ".mp3", ".mp4", ".fmp4", ".m4s")`。后续如遇新格式，在元组里加一项即可。

**改动文件**
- `backend/main.py`：`rewrite_m3u8_text` 函数，切片扩展名判断改为元组

---

## 2026-05-04 新增：directPlay 直连 CDN 模式，节省后端流量

**背景**
后端代理所有 HLS 流量（m3u8 + 切片），带宽压力大。对于 CORS 友好的 CDN，前端可以直接加载 m3u8 和切片，后端只需提供最新 URL。

**实现**
1. `main.py`：新增 `GET /api/{station_id}/stream-url` 接口，直接返回 `CURRENT_STREAMS` 中的最新 URL（零开销，内存读取）；内存中没有时按需触发 fetcher 刷新
2. `AudioEngine.vue`：`loadStation` 中新增 directPlay 逻辑——先从 `/api/{station_id}/stream-url` 拿到 CDN 直链，用 HLS.js 直连加载 m3u8；HLS 致命错误时自动回退到后端代理 `/api/{station_id}/playlist.m3u8` 重试一次
3. `stations.js`：新增 `directPlay: true` 配置字段，标记支持直连的电台（目前仅 fj_traffic）

**播放链路（directPlay 电台）**
1. 前端请求 `/api/fj_traffic/stream-url` → 后端返回 `{url: "https://ytcast.radio.cn/..."}`（毫秒级）
2. HLS.js 直连 CDN 加载 m3u8 + .aac 切片 → 成功则播放 ✓（后端零流量）
3. 直连失败（CORS/网络/CDN 挂了）→ 自动回退 `/api/fj_traffic/playlist.m3u8` 走后端代理
4. 后端 fetcher 每 5 小时自动刷新 token，保证 URL 持续有效

**兼容性**
- Safari 原生 HLS（无 hls.js）同样支持 directPlay
- 未设置 `directPlay` 的电台行为完全不变
- ufo 等有 `directUrl` 的电台回退逻辑不受影响

**改动文件**
- `backend/main.py`：新增 `/api/{station_id}/stream-url` 路由
- `frontend/src/components/AudioEngine.vue`：HLS 加载新增 directPlay 直连 + 回退逻辑
- `frontend/src/config/stations.js`：fj_traffic 新增 `directPlay: true`

---

## 2026-05-04 新增：tingfm 通用抓取器，接入福建交通广播 FM100.7

**背景**
tingfm.com 提供公开 API（`api.tingfm.com/wp-json/query/wndt_streams`），返回电台的 m3u8 和 mp3 播放地址。需要设计成通用模板，后续加其他 tingfm 电台只需一行配置。

**实现**
1. `fetchers.py`：新增 `fetch_tingfm(post_id)` 通用抓取函数，请求 tingfm API，优先取 m3u8 流（HLS，quality 更高），没有则取 mp3
2. `fetchers.py`：新增 `tingfm(post_id)` 工厂函数，返回绑定了 post_id 的闭包，用于注册到 `STATION_FETCHER_MAP`
3. `fetchers.py`：`STATION_FETCHER_MAP` 新增 `"fj_traffic": tingfm(94)`（福建交通广播，post_id=94）
4. `stations.js`：新增 `fj_traffic` 电台配置，`livePath: 'fj_traffic/live'` 让前端走 HLS 后端代理

**后续新增 tingfm 电台只需两步**
1. `fetchers.py`：`STATION_FETCHER_MAP` 加一行，如 `"fj_music": tingfm(123)`
2. `stations.js`：加一条配置，`id` 对应 map 的 key，`livePath` 设为 `{id}/live`

**播放链路**
前端请求 `/api/fj_traffic/playlist.m3u8` → 后端通过 fetcher 调用 tingfm API 拿到最新 m3u8 URL → 请求 CDN m3u8 → 改写切片地址为后端代理 → 返回给 hls.js 播放。后台定时任务每 5 小时自动刷新 token。

**改动文件**
- `backend/fetchers.py`：新增 `fetch_tingfm`、`tingfm` 工厂函数，注册 `fj_traffic`
- `frontend/src/config/stations.js`：新增福建交通广播配置

**背景**
Radio Browser 官方 API（`all.api.radio-browser.info`）在大陆无法直连，导致首页电台列表加载失败。

**方案**
- 后端新增 `GET /api/radio-browser/stations/{country_code}` 路由，通过后端云服务器中转请求 Radio Browser
- 后端内存缓存 6 小时（电台数据几乎不变），缓存命中后零开销
- 即使 Radio Browser 临时不可用，缓存未过期时降级返回旧数据，不报错
- 前端改为先请求后端反代（10s 超时），失败后回退直连 Radio Browser（海外用户 / 后端未部署场景）

**请求链路**
1. 前端缓存命中 → 直接返回（无网络请求）
2. 请求后端 `/api/radio-browser/stations/{code}` → 后端缓存命中 → 秒回
3. 后端缓存未命中 → 后端去 Radio Browser 拉取 → 缓存 6 小时 → 返回
4. 后端请求失败 → 前端回退直连 Radio Browser 官方 API

**改动文件**
- `backend/main.py`：新增 Radio Browser 反代路由 + 内存缓存（`RB_CACHE`，6 小时 TTL）
- `frontend/src/api/radioBrowser.js`：`fetchStationsByCountry` 改为后端优先 + 直连回退

**实现**
1. `App.vue`：顶部工具栏新增搜索按钮，与夜间模式按钮同排，样式完全统一（`size-10` 圆形毛玻璃）。点击展开为输入框（`w-48`/`w-56`），自动聚焦；输入框为空时失焦自动收起，再次点击图标收起并清空内容
2. `App.vue`：`searchQuery` 通过 `provide` 传递给子组件
3. `Home.vue`：移除自带搜索框和 `searchQuery` ref，改用 `inject('searchQuery')` 读取关键词，`watchEffect` 中新增名称模糊过滤（不区分大小写，与地区/类型筛选同时生效取交集）

**改动文件**
- `frontend/src/App.vue`：新增搜索按钮组件 + `provide('searchQuery')`
- `frontend/src/views/Home.vue`：移除搜索框，改用 `inject`，`watchEffect` 新增名称过滤

---

## 2026-05-04 修改：Radio Browser 拉取去掉 limit 限制

**背景**
`fetchStationsByCountry` 原来有 `limit=50` 参数，只取前 50 个电台，导致部分电台（如上海音乐广播）被截断不显示。

**改动**
- `radioBrowser.js`：移除 `limit` 参数和函数签名中的解构默认值，API 请求不再带 `limit`，拉取该地区全部电台
- 缓存 key 从 `${countryCode}_${limit}` 简化为 `countryCode`

**改动文件**
- `frontend/src/api/radioBrowser.js`

---

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

---

## 2026-05-04 新增：接入云听 (radio.cn) API，按省份动态加载电台

**背景**
云听官方 API（`ytmsout.radio.cn/web/appBroadcast/list?provinceCode=xxx`）按省份返回电台列表和 m3u8 地址，token 有效期约 19 小时。设计成通用模板，后续新增省份只需改一行配置。

**架构**
电台 ID 统一用 `yt_{contentId}` 前缀，避免和现有电台冲突。播放链路：
```
前端发现电台 → 直接加入 allStations（directPlay: true）
→ 用户点击 → AudioEngine 请求 /api/yt_{id}/stream-url
→ 后端首次请求时动态创建 fetcher 并注册到 STATION_FETCHER_MAP（自动纳入后台刷新）
→ 后端返回最新 m3u8 URL → 前端 HLS.js 直连 CDN 播放（失败则自动回退后端代理）
```

**后端实现**
1. `fetchers.py`：新增 `fetch_yunting(province_code, content_id)` 通用抓取函数，调云听 API 按 contentId 查找电台，返回 m3u8 URL
2. `fetchers.py`：新增 `yunting(province_code, content_id)` 工厂函数，返回闭包（同 tingfm 工厂模式）
3. `main.py`：新增 `GET /api/yunting/stations/{province_code}` 路由，反代云听 API 并缓存 2 小时，返回电台列表原始 JSON
4. `main.py`：`get_stream_url` 中新增 `yt_*` 动态 fetcher 注册逻辑：首次请求时自动创建并注册，后续请求复用，后台定时任务自动刷新已注册电台

**前端实现**
1. `api/yunting.js`（新建）：`YUNTING_PROVINCES` 配置省份列表，`fetchYuntingStations(provinceCode)` 请求后端代理，`mapToStation()` 映射为项目格式（`directPlay: true`，根据电台名称自动推断类型标签）
2. `Home.vue`：新增 `ytStations` ref + `ytLoading` ref，`onMounted` 中与 Radio Browser 并行拉取，`allStations` 合并三源（stationList + rbStations + ytStations）
3. `Home.vue`：`regionLabels` 新增 `'福建'`，筛选栏自动出现云听电台的省份选项

**配置方式**
```js
// frontend/src/api/yunting.js
export const YUNTING_PROVINCES = ['350000']  // 福建，加其他省加一个代码即可
```
```python
# backend/main.py
YUNTING_PROVINCES = ['350000']
```
新增省份：前后端各加一个省份代码，筛选栏自动出现对应地区，无需改其他代码。

**改动文件**
- `backend/fetchers.py`：新增 `fetch_yunting`、`yunting` 工厂
- `backend/main.py`：新增云听反代路由 + `yt_*` 动态 fetcher 注册
- `frontend/src/api/yunting.js`（新建）
- `frontend/src/views/Home.vue`：新增云听电台加载 + 合并逻辑

---

## 2026-05-04 新增：云听 EPG 当前节目字幕显示 + MediaSession 集成

**背景**
云听 API 返回的 `subtitle` 字段包含当前正在播出的节目名（如"音乐无人驾驶"）。将这个字段映射到电台卡片上，让界面比普通 Radio Browser 高级得多。同时将 EPG 信息同步到系统 MediaSession（锁屏/通知栏显示当前节目名）。

**实现**
1. `api/yunting.js`：`mapToStation()` 新增 `subtitle` 字段映射
2. `stores/player.js`：新增 `updateStationEpg(stationId, subtitle)` action，更新 `stationMap[id].subtitle`
3. `Home.vue`：新增 `epgMap` ref + `syncEpg(data)` 函数，同时更新 `epgMap`（卡片显示）和 `playerStore`（MediaSession）
4. `Home.vue`：`watch(ytStations, { once: true })` 从云听电台初始加载的 `subtitle` 填充 `epgMap`
5. `Home.vue`：`onMounted` 中新增 EPG 轮询定时器（每 3 分钟调用 `/api/yunting/epg`），`syncEpg()` 同步更新卡片和 store
6. `Home.vue`：卡片电台名下方新增字幕行（`line-clamp-1`，`text-[0.7rem]`，灰色）
7. `AudioEngine.vue`：`updateSystemMediaSession` 使用 `meta.subtitle` 作为 artist（当前节目名），非云听电台回退到 'WaveBypass Radio'
8. `AudioEngine.vue`：新增 `watch(stationMap[id].subtitle)` 监听 EPG 更新，自动刷新 MediaSession 显示

**EPG 数据流**
```
云听 API → /api/yunting/stations → Home.vue ytStations → watch → syncEpg()
                                                          ↓
每 3 分钟 → /api/yunting/epg → syncEpg() → epgMap（卡片显示）
                                        → playerStore.updateStationEpg()
                                              → AudioEngine watcher
                                                  → updateSystemMediaSession()
                                                      → 锁屏/通知栏显示当前节目
```

**改动文件**
- `frontend/src/api/yunting.js`：`mapToStation` 新增 `subtitle`
- `frontend/src/stores/player.js`：新增 `updateStationEpg` action
- `frontend/src/views/Home.vue`：新增 `epgMap` + `syncEpg` + `watch(ytStations)` + 轮询 + 卡片字幕
- `frontend/src/components/AudioEngine.vue`：MediaSession artist 改为 `meta.subtitle` + 新增 subtitle watcher

---

## 多源回退架构（myradio.tw + 统一回退链）

**背景**
每个电台只有一个流来源，一旦失效就无法播放。接入 myradio.tw 作为台湾电台主源，建立跨源回退链（云听 → myradio → RB），同名电台前端只显示一张卡片。

**myradio 抓取策略**
- 列表页 HTML 只抓一次，用正则提取所有 station ID（`A\d{4}`）+ buildId
- 之后用 Next.js JSON API（`_next/data/{buildId}/zh-TW/{id}.json`）并发获取每个电台详情
- `x-nextjs-data: 1` 请求头，返回 JSON，无需解析 HTML
- `asyncio.Semaphore(5)` 限流防 WAF

**后端新增**
- `fetchers.py`：`fetch_myradio_all()` — 抓取器，缓存 buildId 供后续复用
- `main.py`：`MYRADIO_CACHE`（24h TTL）+ `_myradio_refresh_task()` 后台定时守护
- `main.py`：`GET /api/myradio/all` — 从预热缓存返回所有电台
- `main.py`：`_find_fallback_url(station_id, name)` — 统一回退链
  - `_find_yunting_url` → `_find_myradio_url` → `_find_rb_url`
  - 名称匹配策略：中文字符全包含即命中
- `main.py`：`get_stream_url` 支持 `mr_*` 电台直接读 MYRADIO_CACHE，fetcher 失败走 `_find_fallback_url`

**前端新增**
- `api/myradio.js`：调 `/api/myradio/all`，ID 前缀 `mr_`，自动推断类型标签
- `Home.vue`：`deduplicateByName()` 四源去重，优先级 静态 > mr_ > yt_ > rb_
  - 合并 tags（如台湾电台同时有 `TW` + `music`）
  - 选最好的 logo（优先级高的源没有 logo 时用低优先级源的）
- `radioBrowser.js`：`RB_FETCH_COUNTRIES` 从 `['TW', 'CN']` 改为 `['CN']`

**改动文件**
- `backend/fetchers.py`：新增 `fetch_myradio_all()`
- `backend/main.py`：新增 `MYRADIO_CACHE`、`_myradio_refresh_task`、`GET /api/myradio/all`、`_find_myradio_url`、`_find_rb_url`、`_find_fallback_url`，更新 `get_stream_url`
- `frontend/src/api/myradio.js`：新建
- `frontend/src/api/radioBrowser.js`：`RB_FETCH_COUNTRIES` 去掉 TW
- `frontend/src/views/Home.vue`：新增 `mrStations`、`deduplicateByName()`、myradio 加载 IIFE

---

## 多源并发探测 + 直连/中转分离回退

**背景**
原回退链是串行的：每个源试直连(5s超时)→中转(5s超时)，8个源最差40秒。且后端 HEAD 探测不能代表前端连通性（地理位置、CORS 不同）。

**方案：前端双模式并发探测**
- 直连流 (mp3/aac)：用 `<audio>` 探测，`canplay` 触发即成功（不设 `crossOrigin` 可跨域播放）
- HLS 流 (m3u8)：用 hls.js 探测，`MANIFEST_PARSED` 触发即成功
- `Promise.race` 取所有探测中最快成功的，约 2-3 秒（并发），不是串行加起来
- 后端 HEAD 探测不可靠：后端在中国能连云听但前端在海外可能连不上，反之亦然

**两阶段回退链（以 HitFM 为例）**
```
阶段1 并发直连:
  [主源m3u8→hls.js, 云听m3u8→hls.js, myradio mp3→audio, RB mp3→audio]
  → 最快成功的胜出
  ↓ 全败
阶段2 并发中转:
  [主源中转→hls.js, 云听中转→hls.js, myradio中转→audio, RB中转→audio]
  → 最快成功的胜出
  ↓ 全败
报错 "所有音频源均不可用"
```

**后端新增**
- `GET /api/{station_id}/all-urls`：返回所有源 URL 列表（去重有序）
- `GET /api/{station_id}/reachable-urls`：并行 HEAD 探测，返回可达 URL（备用）
- `GET /api/proxy/stream?url=xxx`：通用音频流中转代理
- `_normalize_name` 增强：繁→简（电台高频字）、更多后缀（之声/之聲）

**前端新增**
- `isHlsUrl(url)`：判断 URL 是否为 HLS 流（`.m3u8`）
- `playUrl(url, stationId, mode)`：统一播放函数，自动识别 HLS/直连
- `probeParallel(urls, stationId, mode)`：双模式并发探测，返回 `{ url, index, type }` 或 null
- `tryFallbackUrls` 改为两阶段：并发直连探测 → 并发中转探测
- `fetchAllUrls` 调 `/api/{id}/all-urls`
- `handleAudioError` 失败时调 `tryFallbackUrls` 继续回退

**改动文件**
- `backend/main.py`：新增 `all-urls`、`reachable-urls`、`proxy/stream` 端点，改进 `_normalize_name`
- `frontend/src/components/AudioEngine.vue`：新增 `isHlsUrl`、`playUrl`、`probeParallel`，重写 `tryFallbackUrls`，更新 `loadStation`

---

## 2026-05-04 新增：云听 EPG 轻量端点

**背景**
前端需要定期刷新当前节目信息（EPG），但主省份代理缓存 2 小时，直接复用会拿到过期节目数据。需要一个轻量端点只返回 `{contentId: subtitle}` 映射。

**实现**
1. `main.py`：新增 `GET /api/yunting/epg`，遍历 `YUNTING_CACHE` 已缓存省份，拼接所有电台的 `contentId → subtitle` 映射
2. 缓存命中 → 零网络请求，直接从内存拼接；缓存未命中 → 拉取云听 API 并顺便更新主省份缓存
3. 返回体很小（只有 id→节目名映射），适合前端每 3 分钟轮询

**改动文件**
- `backend/main.py`：新增 `yunting_epg` 端点

---

## 2026-05-04 新增：多源流回退（云听兜底现有 fetcher 电台）

**背景**
现有的泉州系列等静态 fetcher 电台，如果各自的 API 暂时不可用，播放就会失败。云听 API 也包含这些电台，可以作为备用源。

**实现**
1. `main.py`：新增 `_find_yunting_url(station_id, name)` 辅助函数，从云听缓存中按名称匹配电台
2. `get_stream_url` 新增 `name` 查询参数，AudioEngine 调用时从 `stationMap` 获取电台中文名并传递
3. 匹配策略（按优先级）：
   - 策略 1（前端传名）：从中文名提取关键词（去掉数字/空格）+ 频率，在云听缓存中精确查找
   - 策略 2（兜底）：从 station_id 提取城市代码（如 `qz`→泉州），按城市名模糊匹配
4. `get_stream_url` 的 `except` 块中调用：主 fetcher 失败时，自动从云听找同名电台的流地址兜底
5. 对前端完全透明：现有的泉州 88.9 等电台 ID 不变，只是多了个备用源
6. `yt_*` 和 `rb_*` 电台跳过回退（它们有自己的播放链路）

**匹配示例**
- `qz_fm889`，name="泉州新闻综合 88.9" → 关键词"泉州新闻综合" + 频率"889" → 匹配云听"泉州889新闻综合广播"
- `fj_traffic`，name="福建交通广播 100.7" → 关键词"福建交通广播" + 频率"1007" → 匹配云听"福建交通广播 FM100.7"

**设计决策**
- 电台中文名由前端从 `stations.js` 的 `stationMap` 中获取并传递，无需后端维护额外字典
- 云听 API 请求无需 Cookie 或 Token，直接 GET 即可
- 云听 API 返回的 `playUrlLow` 每次通过 `fetch_yunting()` 实时获取，token 不会过期（过期的是播放 URL 本身，而非 API 列表）

**改动文件**
- `backend/main.py`：新增 `_find_yunting_url` + `get_stream_url` 新增 `name` 参数
- `frontend/src/components/AudioEngine.vue`：两处 `stream-url` 请求新增 `name` 查询参数

---

## 2026-05-04 修复：云听电台地区标签与现有筛选冲突

**问题**
- Radio Browser 中国电台 tag 为 `['CN']`（显示为"中国大陆"）
- 云听福建电台 tag 为 `['福建']`（省份标签）
- 选"中国大陆"看不到云听福建台，选"福建"看不到 RB 中国台
- 本地泉州/福建电台也只有 `CN` 标签，选"福建"看不到它们

**修复**
1. `yunting.js`：`mapToStation()` tags 改为 `['CN', provinceLabel, inferType(name)]`，同时打国家标签和省份标签
2. `stations.js`：泉州 4 台 + 福建交通 + 福州左海 tags 从 `['news', 'CN']` 改为 `['CN', '福建', 'news']`

**标签层级设计**
- 国家标签（`CN`/`TW`/`JP`）：Radio Browser 电台和云听电台共用，选国家看全部
- 省份标签（`福建`/`广东`等）：云听电台自动打，本地电台手动打，RB 电台无省份信息
- 类型标签（`news`/`music`/`talk`）：所有电台通用

**筛选逻辑**：选"中国大陆" → 匹配 `CN` → 看到所有中国电台；选"福建" → 匹配 `福建` → 只看福建电台。省份是国家的子集，两者不冲突。

**新增省份操作**
1. `yunting.js`：`YUNTING_PROVINCES` 加省份代码 + `PROVINCE_LABELS` 加省份名
2. `Home.vue`：`regionLabels` 加省份名
3. `mapToStation` 自动附加 `CN` 标签，无需手动改

**改动文件**
- `frontend/src/api/yunting.js`：`mapToStation` tags 加 `CN`
- `frontend/src/config/stations.js`：6 个福建电台 tags 加 `'福建'`

---

## 2026-05-04 优化：云听 EPG 独立缓存 + URL 预缓存

**问题**
1. EPG（当前节目名）原来和电台列表共享 2 小时缓存，节目半小时换一次，EPG 过时太久
2. 每次 `/api/{station_id}/stream-url` 对云听电台都要调 `fetch_yunting()` 请求云听 API 拿 URL，耗时 1-2 秒
3. `proxy_yunting_stations` 加载电台列表时已经拿到所有 URL 和 subtitle，但只缓存了列表本身

**方案**
新增两层独立缓存，在 `proxy_yunting_stations` 加载时预填充，读取端零网络请求：

| 缓存 | TTL | 写入时机 | 读取端 |
|------|-----|---------|--------|
| `YUNTING_EPG_CACHE` | 10 分钟 | proxy_yunting_stations + yunting_epg API 刷新时 | `GET /api/yunting/epg` |
| `YUNTING_URL_CACHE` | 1 小时 | proxy_yunting_stations 加载时 | `GET /api/{id}/stream-url` |

**EPG 三级优先级读取**
1. `YUNTING_EPG_CACHE`（10 min）命中 → 直接返回，零网络请求
2. EPG 过期 → 从 `YUNTING_CACHE`（2h 省份列表缓存）提取 subtitle 补充
3. 两者都过期 → 调云听 API，同时更新 `YUNTING_CACHE` + `YUNTING_EPG_CACHE`

**URL 缓存读取**
`get_stream_url` 对 `yt_*` 电台：先查 `YUNTING_URL_CACHE` → 命中直接返回 → 未命中才创建 fetcher 调 API

**改动文件**
- `backend/main.py`：
  - 新增 `YUNTING_EPG_CACHE`、`YUNTING_EPG_TTL`（600s）、`YUNTING_URL_CACHE`、`YUNTING_URL_TTL`（3600s）
  - `proxy_yunting_stations` 加载时预填充两层缓存
  - `yunting_epg` 改为三级优先级读取，EPG 过期从列表缓存补充
  - `get_stream_url` 对 `yt_*` 先查 URL 缓存再调 fetcher

---

## 2026-05-04 优化：云听 31 省份全量接入 + 启动预热 + 单请求加载

**问题**
1. 31 个省份全部接入后，前端 31 个并发请求吃满浏览器同域 6 连接上限，logo 图片被排队等待
2. 后端每个请求新建 `httpx.AsyncClient`，31 次独立 TLS 握手浪费时间
3. 首次加载无缓存时，所有请求都要等云听 API 返回

**方案**

### 后端：启动预热（核心）
新增 `_prefetch_yunting()`，在 `lifespan` 中通过 `asyncio.create_task` 启动：
- `asyncio.gather` 并行发出 31 个请求（单客户端连接池复用 TCP）
- 结果写入三层缓存：`YUNTING_CACHE`（电台列表 2h）、`YUNTING_URL_CACHE`（URL 1h）、`YUNTING_EPG_CACHE`（EPG 10min）
- Docker 启动日志出现 `云听省份预热完成: 31/31 个省份` 即预热成功

### 后端：共享客户端
新增 `yunting_client = httpx.AsyncClient(timeout=15, follow_redirects=True, limits=10)`：
- `proxy_yunting_stations`、`yunting_epg`、`_prefetch_yunting` 共用
- 省掉每次请求新建客户端的 DNS + TCP + TLS 开销
- `lifespan` 关闭时调用 `yunting_client.aclose()` 释放资源

### 后端：单端点全量返回
新增 `GET /api/yunting/all`：
- 从 `YUNTING_CACHE` 读取所有省份数据，缓存命中时零网络请求、纯内存拼接
- 未命中的省份逐个拉取后写入缓存

### 前端：单请求替代 31 请求
- 新增 `fetchAllYuntingStations()`：请求 `/api/yunting/all`，按 `provinceCode` 分组缓存
- `Home.vue` 的云听 IIFE 改为 `await fetchAllYuntingStations()`
- 原 `fetchYuntingStations(provinceCode)` 保留，单省查询直接命中前端缓存（`fetchAllYuntingStations` 已预填充）

### 修复：省份筛选标签丢失
**现象**：31 省份全部接入后，地区筛选栏只显示"全部/台湾/中国大陆/福建"，其他省份消失。
**原因**：云听 API 返回的电台数据对象本身不含 `provinceCode` 字段（该字段只在省份列表端点出现）。后端将电台数据原样缓存，`/api/yunting/all` 返回扁平数组时前端无法按省份分组，`PROVINCE_LABELS[undefined]` 返回空，省份标签丢失。
**修复**：三处缓存写入路径（`_write_yunting_caches`、`proxy_yunting_stations`、`yunting_epg`）在写入前通过 `s.setdefault("provinceCode", prov)` 注入省份代码，前端分组逻辑正常工作。

**改动文件**
- `backend/main.py`：新增 `yunting_client`、`_prefetch_yunting`、`/api/yunting/all`，更新 `lifespan`、`proxy_yunting_stations`、`yunting_epg`
- `frontend/src/api/yunting.js`：新增 `fetchAllYuntingStations`
- `frontend/src/views/Home.vue`：云听加载改为单请求，移除 `YUNTING_PROVINCES` 导入

---

## 2026-05-04 修改：直连探测自动升级 HTTP→HTTPS + 中转智能复用

**背景**
myradio.tw 和 Radio Browser 返回的流地址多为 `http://`，但很多源站实际已部署 SSL 证书。浏览器对 http 页面加载 http 资源虽然不触发 mixed content，但部分站点会强制 301 到 https，或 CDN 直接支持 https。原先的直连探测原样使用 http URL，白白浪费了一次省掉中转的机会。

**方案**
直连探测阶段（阶段 1）对所有 `http://` URL 自动尝试 `https://`：
- `upgradeHttps(url)` 工具函数：`http://` → `https://`，已是 https 或其他协议的不变
- `filterReachable(urls, { tryHttps })` 参数：为 true 时 HEAD 请求发往 https 版本，返回的 reachable 列表已是 https URL
- `probeParallel(urls, stationId, mode, { tryHttps })` 参数透传
- 阶段 1 调用 `probeParallel(urls, stationId, 'direct', { tryHttps: true })`

中转阶段（阶段 2）使用**原始 http URL**：
- 后端 `/api/proxy/stream?url=` 做的是服务端到源站的请求，无跨域限制，http 完全可用
- 后端到源站走 http 还是 https 取决于原始 URL，不做强制升级（服务端无 mixed content 问题）
- 万一某源只有 http（无 SSL），中转是唯一可用路径

**`_directProbeWinner` 智能复用**
问题：直连 HTTPS 探测成功 → `playUrl` 播放失败（如 CORS）→ `handleAudioError` → `tryFallbackUrls` 重试 → 阶段 1 又探测成功 → 又播放失败 → 死循环。
根因：探测成功只能说明"源站可达"，不能说明"浏览器能直连播放"（CORS/mixed content 限制）。

解决：
- `_directProbeWinner` 保存阶段 1 胜出结果
- `tryFallbackUrls` 第二次进入时：阶段 1 探测失败（因为 `destroyHls` 已清理上一轮播放器），但 `_directProbeWinner` 还在 → 阶段 2a 跳过探测，直接用该源的原始 URL 构造 proxy URL 播放
- 阶段 2a 失败才进入阶段 2b（全量中转探测）

**`_fallbackIndex` 延迟消费**
原先 `_fallbackIndex = winner.index + 1` 在播放前执行，一旦 `playUrl` 失败，该 URL 就被"消费"了，中转重试时找不到它。
改为：`_fallbackIndex` 和 `_directProbeWinner` 都在 `playUrl` 成功后才更新。播放失败时 URL 保持可用，`handleAudioError` 触发的重试可以中转同一源。

**改动文件**
- `frontend/src/components/AudioEngine.vue`：新增 `upgradeHttps`、`_directProbeWinner`；更新 `filterReachable`、`probeParallel`、`tryFallbackUrls`、`loadStation`

---

## 2026-05-04 修复：RB 台湾数据缺失 + 跨源名称误匹配

**问题 1：台湾电台缺少 RB 回退源**
`RB_FETCH_COUNTRIES` 被改为 `['CN']`（myradio 接管台湾时），导致 `RB_CACHE` 里没有 `TW` 数据。`_find_rb_url` 遍历 RB_CACHE 时找不到台湾电台，`/api/{id}/all-urls` 永远不会返回 RB 的台湾流。

**修复**：`RB_FETCH_COUNTRIES` 恢复为 `['TW', 'CN']`。

**问题 2：跨源名称匹配太松导致误匹配**
`_find_rb_url` 和 `_find_myradio_url` 使用 `query in rb_name or rb_name in query` 纯子串匹配。"Needs Radio 全球華語廣播網" 规范化后包含 "全球华语广播网"，这个子串在很多大陆电台名里都出现，导致多个台湾电台误匹配到同一个 xmcdn 流。

**修复**：
- 新增 `_names_match(query, target)` 函数，规则：
  1. 完全相等 → True
  2. 短串是长串的子串：要求短串 ≥ 4 字符 **且** 长度 ≥ 长串的 60%
     - "hitfm"(5) in "hitfm台北"(7) → 5/7=71% → ✓
     - "全球华语广播网"(7) in "needsradio全球华语广播网"(15) → 7/15=47% < 60% → ✗
- `_find_rb_url`、`_find_myradio_url` 都改用 `_names_match`
- 删除 `_find_myradio_url` 的策略 2（中文字符全包含，太松）

**问题 3：RB 跨区误匹配**
即使名称匹配收紧，仍可能有同名电台跨区（如大陆和台湾都有"中央广播电台"）。需要从源头限制搜索范围。

**修复**：
- 新增 `_infer_rb_region(station_id)`：`mr_*` → `'TW'`，`yt_*` → `'CN'`，其他 → `None`
- `_find_rb_url` 新增 `region` 参数：`region='TW'` 时只搜 `RB_CACHE['TW']`，`region=None` 时全量搜索（兜底）
- `_collect_all_urls` 和 `_find_fallback_url` 都自动推断 region 并传入

**改动文件**
- `frontend/src/api/radioBrowser.js`：`RB_FETCH_COUNTRIES` 恢复 `['TW', 'CN']`
- `backend/main.py`：新增 `_names_match`、`_infer_rb_region`；更新 `_find_rb_url`、`_find_myradio_url`、`_find_fallback_url`、`_collect_all_urls`

**架构调整：RB 从前端展示中剥离**
RB 电台只用于后端回退匹配，不再出现在前端卡片列表里。前端只展示 fetcher + myradio + 云听三源，界面更干净；后端 `all-urls` 和 `_find_fallback_url` 仍可返回 RB 流供并发探测。

- `RB_FETCH_COUNTRIES` 改为 `[]`（前端不再请求 RB 数据）
- `Home.vue` 移除 `rbStations`、`rbLoading`、RB 导入、RB 加载 IIFE，`allStations` 从四源改为三源
- 后端新增 `_prefetch_rb()`：启动时自动预热 TW + CN 的 `RB_CACHE`，每 6 小时静默刷新。之前 RB 数据靠前端请求写入缓存，前端不请求后需要后端自己维护
- `/api/radio-browser/stations/{country_code}` 路由保留，供手动刷新或未来重新启用

**改动文件**
- `frontend/src/api/radioBrowser.js`：`RB_FETCH_COUNTRIES` → `[]`
- `frontend/src/views/Home.vue`：移除 RB 导入、rbStations/rbLoading、RB 加载 IIFE、allStations 中 RB 源
- `backend/main.py`：新增 `_prefetch_rb()`，更新 `lifespan`

---

**问题 4：RB TW 重新接入后前端卡片重复**
`RB_FETCH_COUNTRIES` 恢复 TW 后，myradio 和 RB 的同名台湾电台各自生成独立卡片。原因：`deduplicateByName` 的去重键只做 `replace(/\s+/g, '').toLowerCase()`，没有繁→简转换。myradio 的"古典音樂"和 RB 的"古典音乐" key 不同，无法归组。

**修复**：
- 新增 `normalizeForDedup(str)`：去空格 + 小写 + 繁→简（`T2S` 映射表，与后端 `_T2S` 一致，覆盖电台名高频字）
- `deduplicateByName` 改用 `normalizeForDedup(s.name)` 生成去重 key

**改动文件**
- `frontend/src/views/Home.vue`：新增 `T2S`、`normalizeForDedup`，更新 `deduplicateByName`

---

## 2026-05-04 修复：qingting.fm 等 CDN 代理请求返回 400

**现象**
邯郸新闻综合广播（yt_783）的 all-urls 包含 `[yunting m3u8, qingting mp3]`。yunting m3u8 失败后，qingting.fm 的 mp3 直连播放失败，回退到后端代理 `/api/proxy/stream?url=https://lhttp.qingting.fm/live/5072/64k.mp3` 也返回 400。但手动在浏览器打开该 URL 可以播放。

**根因**
qingting.fm 的 CDN 要求请求携带自引用 `Referer` 头（`Referer: https://lhttp.qingting.fm/...`），否则返回 400。后端 `/api/proxy/stream` 仅使用 `CDN_REQUEST_HEADERS`（包含 `User-Agent` 和 `Accept`），缺少 `Referer`。

Chrome 直接打开能播放是因为浏览器自动设置了 Referer 头（同源或地址栏 URL）。

**修复**
`/api/proxy/stream` 端点自动从目标 URL 提取 origin 作为 `Referer` 头：
```python
parsed = urlparse(url)
referer = f"{parsed.scheme}://{parsed.netloc}/"
headers = {**CDN_REQUEST_HEADERS, "Referer": referer}
```

这对所有 CDN 都安全——大部分 CDN 不检查 Referer，少数检查的（如 qingting.fm）接受自引用 Referer。

**备注**
这与泉州电台的防盗链处理思路一致：`get_cdn_headers_for_station()` 已经为 `qz_*` 电台设置了 `Referer: https://wxqz2.qztv.cn`，但那只对已知电台生效。`/api/proxy/stream` 是通用代理，需要对任意 URL 生效。

**改动文件**
- `backend/main.py`：`proxy_stream` 端点添加基于 URL origin 的 `Referer` 头

---

## 2026-05-04 功能：IP 地域自动识别 + 前后端双重敏感内容过滤

**背景**
用户前置套了 Cloudflare Tunnel，需要大陆 IP 自动屏蔽台湾分区（敏感内容），海外 IP 无限制。Cloudflare Tunnel 自动在请求中注入 `CF-IPCountry` 头（ISO 3166-1 国家代码，如 `CN`），无需自建 GeoIP 数据库。

**方案**

### 配置
- `GEO_RESTRICT=1`：启用地域限制（默认关闭）
- `GEO_BLOCKED_REGIONS=TW`：被屏蔽的地区 tag，逗号分隔，默认 `TW`

### 后端
- 新增 `_is_geo_blocked(station_id, request)` 辅助函数：
  - 读取 `CF-IPCountry` 头，非 `CN`（海外）→ 不限制
  - 无 CF 头（直接访问）→ 默认限制（安全侧，宁可多屏蔽不漏）
  - `mr_*` 前缀 → 台湾 myradio 电台，自动屏蔽
  - `_TW_STATION_IDS` 集合：已知静态台湾电台 ID（hitfm、pop917、cityfm 等），硬编码
  - `MYRADIO_CACHE` 反查：以防遗漏
- 新增 `GET /api/config`：返回 `{geoRestrict, blockedRegions}` 供前端使用
- `/api/myradio/all`：过滤被屏蔽地区的电台（不返回给前端）
- 所有流端点加入 403 拦截：`playlist.m3u8`、`chunk.ts`、`stream`、`stream-url`、`all-urls`、`reachable-urls`、`{m3u8_name}.m3u8`
- 云听端点无需过滤（全是大陆台）

### 前端
- `Home.vue` 启动时调 `/api/config` 获取地域配置
- `allStations` 计算属性根据 `geoConfig.blockedRegions` 过滤电台
- `regions` 筛选 pill 基于过滤后的 `allStations` 生成，被屏蔽地区自动消失

### Docker
- `docker-compose.yml` 新增 `GEO_RESTRICT`、`GEO_BLOCKED_REGIONS` 环境变量
- `.env.example` 新增配置说明

**改动文件**
- `backend/main.py`：新增 `GEO_RESTRICT`/`GEO_BLOCKED_REGIONS` 配置、`STATIC_STATIONS`（静态电台数据）、`_TW_STATION_IDS`（从 tags 动态提取）、`_is_geo_blocked()`、`/api/config`、`/api/stations` 端点；`get_myradio_all` 过滤；7 个流端点 403 拦截
- `frontend/src/stores/player.js`：移除静态导入，新增 `loadStations()` 动态加载方法，初始状态为空
- `frontend/src/components/AudioEngine.vue`：移除 `staticStationMap` 导入，仅用 store 的 `stationMap`
- `frontend/src/views/Home.vue`：启动时先调 `/api/config` + `/api/stations`，`geoConfigLoaded` 门控防止闪现
- `docker-compose.yml`：新增环境变量
- `.env.example`：新增配置说明
- `frontend/src/config/stations.js`：保留作参考，不再被任何代码导入（不进入构建产物）

**防 GFW 设计**
- 前端构建产物不含任何台湾电台数据（stations.js 不再被导入，Vite tree-shake 排除）
- 后端 `/api/stations` 和 `/api/myradio/all` 根据 `CF-IPCountry` 头过滤，大陆 IP 收到的响应中不含台湾电台
- 流端点 403 拦截，即使知道 station ID 也无法播放

---

## 2026-05-04 优化：云听 `/api/yunting/all` 响应加速

**问题**
`/api/yunting/all` 响应耗时约 3 秒。原因：
1. 缓存存的是 JSON 字符串，每次请求要 `json.loads` 31 次再 `json.dumps` 合并
2. 启动预热是后台 `create_task`，首次请求可能在缓存就绪前到达，触发 31 省份实时拉取

**方案**

### 预合并缓存 `YUNTING_ALL_CACHE`
- 新增 `YUNTING_ALL_CACHE`（`{"data": bytes, "ts": float}`），存储预合并的 JSON bytes
- `_yunting_warmup()` 预热时同时构建全量 merged 结果写入 `YUNTING_ALL_CACHE`
- `proxy_yunting_all` 快速路径：`YUNTING_ALL_CACHE` 命中时直接返回原始 bytes，零 `json.loads`/`json.dumps`
- 慢速路径（缓存未就绪）：从各省 `YUNTING_CACHE` 拼接，缺失省份实时拉取，结果写入 `YUNTING_ALL_CACHE` 供后续请求命中
- TTL 与省份缓存一致（2 小时），预热时同一 `now` 时间戳

### `_yunting_warmup()` 提取
- 从 `_yunting_refresh_task()` 的 while 循环中提取为独立函数
- `_yunting_refresh_task()` 改为：warmup → sleep → warmup → sleep
- 预热逻辑不变：`asyncio.gather` + `Semaphore(5)` 限流，单省失败保留旧缓存

**效果**
- 预热完成后：`/api/yunting/all` 从 ~3 秒降到 <10ms（纯内存 bytes 返回）
- 预热前首次请求：仍走慢速路径（~3 秒），但结果写入缓存后后续请求命中快速路径
- 启动流程不变：后台 `create_task` 非阻塞，不延迟服务器启动

**改动文件**
- `backend/main.py`：新增 `YUNTING_ALL_CACHE`、`_yunting_warmup()`；更新 `_yunting_refresh_task`、`proxy_yunting_all`
