# 发布记录

## 2026-05-02 - 第一步：项目基础设施与 Docker 编排

- 创建初始单体仓库结构，包含独立的 `backend` 和 `frontend` 目录。
- 添加基于 `python:3.11-slim` 的 `backend/Dockerfile`，用于运行后续 FastAPI 异步代理服务。
- 添加 `frontend/Dockerfile`，使用 Node.js 20 构建前端，并使用 `nginx:alpine` 托管静态产物。
- 添加 `frontend/nginx.conf`，通过 `try_files` 解决 Vue history 模式刷新 404 问题，并预留 `/api/` 后端代理。
- 添加根目录 `docker-compose.yml`，定义 `backend` 和 `frontend` 服务，并让它们共享同一个桥接网络。

## 2026-05-02 - 第二步：FastAPI 后端核心与定时任务

- 添加 `backend/requirements.txt`，集中声明 FastAPI、Uvicorn 和 httpx 依赖。
- 添加 `backend/fetchers.py`，使用电台 ID 到异步抓取函数的注册表实现轻量工厂模式。
- 添加 `backend/main.py`，初始化 FastAPI，配置 CORS，并创建后台 token 定时刷新任务。
- 调整 `backend/Dockerfile`，改为从 `requirements.txt` 安装依赖，并使用 `main:app` 作为 Uvicorn 入口。

## 2026-05-02 - 第三步：FastAPI 反向代理路由与微缓存优化引擎

- 在 `backend/main.py` 中添加 `M3U8_CACHE` 微缓存，缓存每个电台改写后的 m3u8 文本 3 秒。
- 添加每电台异步锁，避免缓存过期瞬间多个请求同时打到真实 CDN。
- 添加 `GET /api/{station_id}/playlist.m3u8` 路由，从真实 m3u8 拉取文本并把 `.ts` 切片改写为后端代理地址。
- 添加 `GET /api/{station_id}/chunk.ts` 路由，使用 httpx 流式请求真实切片，并通过 `StreamingResponse` 边下载边转发。
- 对 `target_url` 做协议校验，只允许代理 `http` 和 `https` 地址。

## 2026-05-02 - 第四步：Vue 3 前端核心逻辑

- 添加 `frontend/src/stores/player.js`，使用 Pinia 管理播放状态、电台 ID 和音量。
- 添加 `frontend/src/components/AudioEngine.vue`，作为无 UI 的全局音频控制器。
- 在 `AudioEngine.vue` 中接入 `hls.js`，根据当前电台加载 `/api/{station_id}/playlist.m3u8`。
- 监听 HLS manifest 解析完成事件后触发播放，并捕捉浏览器自动播放限制导致的异常。
- 同步播放、暂停和音量变化到隐藏的 `audio` 元素，保持 UI 状态和真实播放状态一致。

## 2026-05-02 - 第五步：极简且具高级感的前端 UI 布局

- 添加 `frontend/src/views/Home.vue`，实现自适应电台卡片网格，移动端 2 列、平板 4 列、桌面 6 列。
- 添加 `frontend/src/components/BottomPlayer.vue`，实现底部悬浮毛玻璃播放器控制条。
- 添加 `frontend/src/App.vue`，组合选台页面、底部播放器和隐藏音频引擎。
- 支持浅色和深色主题，默认跟随系统偏好，并提供右上角手动切换按钮。
- 使用克制的背景、边框、微投影、圆角和交互缩放，形成 Apple / Vercel 风格的极简界面。

## 2026-05-02 - 第六步：补齐 Vue 前端工程骨架

- 添加 `frontend/package.json`，声明 Vite、Vue、Pinia、TailwindCSS、PostCSS 和 Autoprefixer 依赖与脚本。
- 添加 `frontend/index.html`，作为 Vite 入口页面，并通过 CDN 在线引入 `hls.js`。
- 添加 `frontend/vite.config.js`，配置 Vue 插件、开发服务器端口和 `/api` 后端代理。
- 添加 `frontend/tailwind.config.js`，启用 `darkMode: 'class'`，并配置系统无衬线字体栈。
- 添加 `frontend/postcss.config.js` 和 `frontend/src/style.css`，完成 Tailwind 构建入口与全局基础样式。
- 添加 `frontend/src/main.js`，创建 Vue 应用并注册 Pinia。
- 调整 `AudioEngine.vue`，改为读取 CDN 暴露的 `window.Hls`，减少本地运行时依赖。
- 生成 `frontend/package-lock.json`，锁定前端依赖版本，方便后续部署复现。
- 添加根目录 `.gitignore`，排除 `node_modules`、`dist`、缓存、环境变量等不应提交的文件。
- 已执行 `npm run build`，确认前端骨架可以成功完成生产构建。

## 2026-05-02 - 第七步：整合 Hit FM 真实抓取逻辑

- 将 `backend/fetchers.py` 中的 `fetch_hitfm` 从 mock 占位逻辑替换为真实异步抓取流程。
- 使用 `httpx.AsyncClient` 向 Hit FM 官网 Ajax 接口提交 `channelID=1` 和 `action=getLIVEURL`，获取带 token 的 m3u8 地址。
- 使用获取到的真实 m3u8 地址请求 CDN，验证当前服务器 IP 是否能成功拿到播放列表。
- 新增 `HITFM_COOKIE` 环境变量读取逻辑，避免把会话 Cookie 硬编码进开源仓库。
- 在 `docker-compose.yml` 中为后端服务透传 `HITFM_COOKIE`，并新增 `.env.example` 作为配置模板。

## 2026-05-02 - 第八步：兼容 Hit FM CDN 证书链异常

- 在 `backend/main.py` 中新增 `CDN_VERIFY_SSL = False`，用于兼容部分 CDN 证书链缺少 Subject Key Identifier 的问题。
- 调整 m3u8 真实源拉取逻辑，使用 `httpx.AsyncClient(..., verify=False)` 跳过 CDN 证书校验。
- 调整 ts 切片流式代理逻辑，同样跳过 CDN 证书校验，避免切片请求阶段再次触发 SSL 错误。

## 2026-05-02 - 第九步：支持 Hit FM 两级 HLS 播放列表

- 调整 m3u8 改写逻辑，除 `.ts` 切片外，也会把子级 `.m3u8` 改写到 `/api/{station_id}/playlist.m3u8?target_url=...`。
- 调整 m3u8 微缓存键，从单纯电台 ID 改为 `电台 ID + 真实 m3u8 URL`，避免顶层列表和子级列表共用同一份缓存。
- 新增 `/api/{station_id}/{m3u8_name}.m3u8` 兼容路由，用于兜底播放器直接请求 `chunklist.m3u8` 这类相对子列表的情况。
- m3u8 和 ts 真实 CDN 请求统一使用浏览器 User-Agent，减少 CDN 因请求头差异导致的连接或访问问题。

## 2026-05-02 - 第十步：支持电台真实 Logo 展示

- 调整 `frontend/src/views/Home.vue` 的电台卡片，优先显示 `logoUrl` 配置的真实图片。
- 没有配置真实图片的电台会自动回退到字母占位符，避免图片缺失导致界面空白。
- 新增 `frontend/public/logos/` 目录，用于存放部署时可直接访问的电台 Logo 静态资源。

## 2026-05-02 - 第十一步：m3u8 过期后按需刷新 token

- 新增 `refresh_station_stream_url`，支持在请求过程中立即刷新单个电台的真实 m3u8 URL。
- 新增 `fetch_real_m3u8_text`，统一封装真实 CDN m3u8 请求逻辑。
- 当顶层 m3u8 返回 `401`、`403`、`404` 或 `410` 时，后端会立即重新抓取最新 token 并重试一次。
- 后台定时任务改为复用单电台刷新函数，减少重复代码并保持刷新行为一致。

## 2026-05-02 - 第十二步：接入 UFO Radio 直连音频流

- 将 `fetch_ufo` 从 mock 占位逻辑替换为真实 Revma 跳转解析逻辑。
- UFO 入口地址 `https://stream.rcs.revma.com/em90w4aeewzuv` 会自动跟随跳转，保存最终带 `rj-tok` 的真实音频流地址。
- 新增 `DIRECT_STREAM_STATIONS`，区分 UFO 这类直连音频流和 Hit FM 这类 HLS/m3u8 电台。
- 新增 `/api/{station_id}/stream` 路由，使用 httpx 流式代理直连音频，避免把无限直播流读入内存。
- 前端 `AudioEngine.vue` 识别 `ufo` 时直接播放 `/api/ufo/stream`，不再走 hls.js。

## 2026-05-02 - 第十三步：UFO 直连优先与前端错误提示

- 调整 UFO 前端播放策略，优先直接播放 `https://stream.rcs.revma.com/em90w4aeewzuv`。
- UFO 直连触发 audio 错误时，会自动回退到后端 `/api/ufo/stream` 中转代理。
- Pinia 播放器状态新增 `playbackError`，用于保存当前播放错误信息。
- `AudioEngine.vue` 会捕捉自动播放限制、HLS 致命错误和 audio 加载错误，并同步错误状态。
- `BottomPlayer.vue` 会在底部控制条展示错误文案，HitFM 和 UFO 播放失败时用户能直接看到提示。

## 2026-05-02 - 第十四步：增加克制的播放加载反馈

- Pinia 播放器状态新增 `isLoading`，用于表示当前正在连接音频源。
- `AudioEngine.vue` 在切台、直连、中转和 HLS 加载阶段同步加载状态，播放成功或失败后自动结束。
- `BottomPlayer.vue` 在加载时将状态点切换为小型旋转指示器，并显示“正在连接”。
- `Home.vue` 当前加载中的电台 Logo 会轻微脉冲，提供不打扰的选台反馈。

## 2026-05-02 - 第十五步：增加HitFM其他地方的几个电台，增加HTTP连接池
- 新增 `HITFM_OTHER_STATIONS` 包括HitFM的台中、台南、宜兰、花莲
- 增加HTTP连接池，减少TLS请求握手耗费毫秒

## 2026-05-02 - 第十六步：增加泉州FM889电台逻辑，修复暗黑模式切换逻辑
- 增加泉州FM889逻辑，接口来自无线泉州APP
- 修复iOS暗黑模式切换逻辑
- 修复Safari 状态栏颜色沉浸式逻辑
- 增加Media Session信息
- 将地址配置集合为单独配置文件

## 2026-05-03 - 增加泉州FM904/923/1059电台，添加防止风控措施
- 增加泉州FM904/923/1059
- 增加异步延时获取泉州url
- 修复泉州923特殊的radioid
- 增加前后端分离部署支持，添加环境变量
- 增加pop923电台，优化hinetfm模板逻辑
- 增加HLS.js低延迟参数

## 2026-05-03 - 增加台湾城市广播网电台，支持简单直链电台自动识别播放

- 新增台湾城市广播网（cityfm）电台，直链地址为 `https://fm901.cityfm.com.tw:8083/901`
- `stations.js` 新增 `directUrl` 字段，简单直链电台只需配置 `directUrl` 即可，无需后端 fetcher
- 修复 `AudioEngine.vue` 的 `loadStation` 未识别 `stationMap.directUrl` 导致简单电台仍走 HLS playlist 的问题
- 现在 `stationMap` 里有 `directUrl` 且无 `livePath` 的电台，前端自动跳过 HLS 直接用 `<audio>` 原生播放
- 统一直连电台回退机制：`directStreamStationMap` 自动合并 `stationMap` 的 directUrl 电台，共用直连→中转回退逻辑
- HLS 致命错误时也会尝试 directUrl 直连回退，不再直接报错停止
- 重构 UFO 电台：移除 AudioEngine.vue 中硬编码的直连 URL，改由 stations.js 配置 directUrl，统一收编进自动合并逻辑
- proxyUrl 生成规则：有 livePath 的电台走 /api/{id}/stream（直连流代理），无 livePath 的走 /api/{id}/live（HLS 代理）
- 新增中广新闻网、中广流行网、中广音乐网、iGO531、中广乡亲网，均为 Revma 直链，仅需在 stations.js 配置 directUrl
- 接入 Radio Browser API，首页自动拉取台湾电台并追加到电台列表末尾
- 新增 `api/radioBrowser.js`：封装 Radio Browser 请求、数据映射、国家配置
- `player.js` 新增 `stationList`、`stationMap` 状态和 `addStation()` 方法，支持动态追加电台
- Home.vue 改为从 store 读取电台列表，合并静态 + Radio Browser 电台后统一渲染
- 所有电台新增 tags 字段，同时包含地区标签（TW/CN）和类型标签（music/news/talk 等）
- Radio Browser 电台的 tags 字段自动解析归类，常见标签映射为统一类型
- 首页新增筛选栏：地区 pill + 类型 pill，从所有电台的 tags 自动提取可用选项，点击过滤电台列表
- 修复电台列表重复 bug：`addStation()` 同时写入 stationList 和 stationMap 导致每个 RB 电台出现两次，筛选数量翻倍
- `addStation()` 改为只更新 stationMap，显示列表由 Home.vue 的 rbStations 单独管理，职责分离避免重复
- 新增 `RB_FETCH_COUNTRIES` 配置项，集中声明首页要拉取的 Radio Browser 地区列表，新增地区只需加一个国家代码
- `onMounted` 改为从 `RB_FETCH_COUNTRIES` 读取地区列表，`Promise.all` 并行拉取多个地区电台

## 2026-05-04
- 顶部工具栏新增可收起搜索框，点击放大镜图标展开为输入框，输入时实时按电台名过滤，失焦自动收起
- 搜索关键词通过 `provide/inject` 从 App.vue 传递给 Home.vue，与地区/类型筛选同时生效
- Radio Browser 拉取去掉 `limit=50` 限制，改为拉取该地区全部电台
- 虚拟滚动改用 `@vueuse/core` 的 `useScroll` + `useThrottleFn`，替代纯 JS 手写滚动追踪，代码更简洁可维护
- 滚动容器从 Home.vue 的 `main` 移到 App.vue 根 div（`h-dvh overflow-y-auto`），滚动条贴紧浏览器右侧边缘
- `ResizeObserver` 监听 grid 容器宽度（非视口宽度），准确计算响应式列数（2/4/6）和行高
- `virtualRows` computed 只取可视区域 ±3 行缓冲，1000+ 电台任意时刻只渲染约 30~40 个 DOM 节点
- 修复 iOS Safari 视口高度问题：`h-dvh` 替代 `h-screen`，排除地址栏高度
- 修复 iOS Safari 弹性滚动负 scrollTop 导致的布局异常
- 统一移动端和桌面端卡片行间距为 20px，修复移动端卡片上下紧贴问题
- Grid 的 `gap` 改为动态 style 绑定，消除 CSS/JS gap 不一致导致卡片溢出的问题
- 修复 Safari（iOS + macOS）卡片间距拥挤：Safari 的 `aspect-ratio` + Grid 布局有兼容性 bug，卡片高度溢出吃掉行间距。去掉 `aspect-square`，改用 JS 算出精确高度并设为内联 style
- `transition-all` 改为 `transition-[background-color,transform,box-shadow,border-color]`，排除 height，修复 ResizeObserver 触发时第一行卡片高度跳变带动画的问题