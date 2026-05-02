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
