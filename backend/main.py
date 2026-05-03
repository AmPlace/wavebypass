"""WaveBypass 后端入口。

本文件负责初始化 FastAPI 应用、配置跨域、维护内存中的电台播放地址，
并在服务启动后开启后台定时任务，持续刷新各电台的 CDN token 地址。
"""

import asyncio
import logging
import time
from collections.abc import AsyncIterator
from urllib.parse import quote, urljoin, urlparse

import httpx
from fastapi import FastAPI, HTTPException, Query, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from contextlib import asynccontextmanager
from fetchers import STATION_FETCHER_MAP


# 每 5 小时刷新一次 token。
# 真实 CDN token 有效期约 6 小时，提前 1 小时刷新可以减少播放中断风险。
TOKEN_REFRESH_INTERVAL_SECONDS = 18_000


# m3u8 微缓存有效期，单位是秒。
# 直播 m3u8 会频繁变化，所以只缓存很短时间，用来削峰而不是长期保存。
M3U8_CACHE_TTL_SECONDS = 3.0


# 下载 m3u8 或 ts 时使用的超时时间。
# connect 控制建立连接时间，read 控制读取数据时间，避免请求永久卡住。
HTTP_TIMEOUT = httpx.Timeout(30.0, connect=10.0)


# 是否校验真实 CDN 的 HTTPS 证书。
# 有些广播 CDN 的证书链在 Python/OpenSSL 中会因为缺少 Subject Key Identifier 被拒绝。
# 这里设置为 False，等价于你测试脚本中的 requests.get(..., verify=False)。
CDN_VERIFY_SSL = False


# 请求真实 CDN 时使用的伪装头。
# Hit FM CDN 对浏览器 UA 更友好，所以 m3u8 和 ts 请求都统一使用这个 UA。
CDN_REQUEST_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/147.0.0.0 Safari/537.36"
    ),
    "Accept": "*/*",
}

def get_cdn_headers_for_station(station_id: str) -> dict[str, str]:
    headers = CDN_REQUEST_HEADERS.copy()
    
    # 只要是 qz_ 开头的电台，统统套用泉州的防盗链破解规则
    if station_id.startswith("qz_"):
        headers["Referer"] = "https://wxqz2.qztv.cn"
        headers["User-Agent"] = "AppleCoreMedia/1.0.0.23E261 (iPhone; U; CPU OS 26_4_2 like Mac OS X; zh_cn)"
        
    return headers

# 这些状态码通常表示真实 m3u8 URL 已经过期、被 CDN 回收或 token 不再可用。
# 顶层播放列表遇到这些状态时，可以立即重新抓取一次最新 token 并重试。
TOKEN_REFRESH_HTTP_STATUS_CODES = {401, 403, 404, 410}


# 非 HLS 的直连音频电台。
# 这些电台不走 playlist.m3u8，而是前端直接请求 /api/{station_id}/stream。
DIRECT_STREAM_STATIONS = {"ufo"}


# 当前进程内存中的最新播放地址。
# key 是电台 ID，例如 "hitfm"；value 是对应电台最新的 m3u8 URL。
CURRENT_STREAMS: dict[str, str] = {}


# m3u8 微缓存。
# 结构示例：
# {
#     "hitfm": {
#         "text": "#EXTM3U\n...",
#         "timestamp": 1710000000.0,
#     }
# }
M3U8_CACHE: dict[str, dict[str, str | float]] = {}


# 每个电台一把异步锁。
# 当缓存过期且同一时间有大量请求进来时，锁可以避免所有请求同时打到真实 CDN。
M3U8_CACHE_LOCKS: dict[str, asyncio.Lock] = {}


# 创建模块级日志记录器。
# 后续 Docker 中可以通过 docker logs 查看这些刷新状态和异常信息。
logger = logging.getLogger("wavebypass")


# 初始化 FastAPI 应用。
app = FastAPI(
    title="WaveBypass",
    description="用于聚合电台 m3u8 与 ts 切片代理的后端服务。",
    version="0.1.0",
)


# 允许所有来源跨域访问。
# 开发期这样最省心；如果后续公开部署，可以改成只允许你的前端域名。
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


def get_m3u8_cache_lock(cache_key: str) -> asyncio.Lock:
    """获取某个 m3u8 地址专用的微缓存锁。

    使用 setdefault 可以在第一次访问某个 m3u8 时创建锁，
    后续同一个缓存键会复用同一把锁。
    """

    return M3U8_CACHE_LOCKS.setdefault(cache_key, asyncio.Lock())


def get_cached_m3u8_text(cache_key: str) -> str | None:
    """读取仍在有效期内的 m3u8 缓存文本。

    如果缓存不存在、缓存内容为空，或者缓存已经超过 3 秒，则返回 None。
    """

    # 获取当前系统时间戳，用于和缓存写入时间做差值比较。
    now = time.time()

    # 从缓存字典中读取当前 m3u8 地址的缓存记录。
    cache_item = M3U8_CACHE.get(cache_key)

    # 没有缓存记录时，直接告诉调用方需要重新拉取。
    if cache_item is None:
        return None

    # 取出缓存文本；类型转换是为了让字典结构保持简单，方便初学阶段阅读。
    cached_text = str(cache_item.get("text", ""))

    # 取出缓存写入时间；没有 timestamp 时按 0 处理，会自然判定为过期。
    cached_timestamp = float(cache_item.get("timestamp", 0.0))

    # 只要缓存有内容，并且距离写入时间还不到 3 秒，就认为命中微缓存。
    if cached_text and now - cached_timestamp < M3U8_CACHE_TTL_SECONDS:
        return cached_text

    # 走到这里说明缓存不存在有效内容，调用方需要访问真实 CDN。
    return None


def rewrite_m3u8_text(raw_m3u8_text: str, real_m3u8_url: str, station_id: str) -> str:
    """把真实 m3u8 中的子列表和 ts 切片地址改写成后端代理地址。

    Hit FM 这类 HLS 流经常是两级结构：
    顶层 playlist.m3u8 里不是 ts，而是 chunklist.m3u8。
    所以这里需要同时改写子级 .m3u8 和最终 .ts 切片。

    ts 会被改成：
    /api/{station_id}/chunk.ts?target_url=真实切片绝对地址

    子级 m3u8 会被改成：
    /api/{station_id}/playlist.m3u8?target_url=真实子列表绝对地址
    """

    # 用列表收集每一行改写后的结果，最后再一次性 join，效率比反复字符串拼接更好。
    rewritten_lines: list[str] = []

    # splitlines 会按行拆分 m3u8，同时不保留换行符，方便逐行判断。
    for line in raw_m3u8_text.splitlines():
        # 去掉首尾空白只用于判断；真正写回时会使用改写后的标准路径。
        stripped_line = line.strip()

        # 空行和以 # 开头的标签行不是切片 URI，直接原样保留。
        if not stripped_line or stripped_line.startswith("#"):
            rewritten_lines.append(line)
            continue

        # urlparse 可以同时处理相对路径和绝对 URL。
        parsed_uri = urlparse(stripped_line)

        # 取出小写路径，方便判断资源类型。
        uri_path = parsed_uri.path.lower()

        # urljoin 会根据当前真实 m3u8 的地址，把相对路径补成完整 URL。
        absolute_media_url = urljoin(real_m3u8_url, stripped_line)

        # target_url 放在查询参数中，必须 URL 编码，否则其中的 ?、& 等字符会破坏代理路由。
        encoded_target_url = quote(absolute_media_url, safe="")

        # 子级 m3u8 播放列表继续交给 playlist 路由处理。
        if uri_path.endswith(".m3u8"):
            proxy_playlist_url = f"/api/{station_id}/playlist.m3u8?target_url={encoded_target_url}"
            rewritten_lines.append(proxy_playlist_url)
            continue

        # 非 ts 资源先原样保留，避免误改未来可能出现的其他 HLS 标签资源。
        if not uri_path.endswith(".ts"):
            rewritten_lines.append(line)
            continue

        # 生成指向本后端 TS 代理接口的切片地址。
        proxy_ts_url = f"/api/{station_id}/chunk.ts?target_url={encoded_target_url}"

        # 写入改写后的切片行。
        rewritten_lines.append(proxy_ts_url)

    # m3u8 是文本协议，使用 \n 拼回即可；末尾加换行让输出更接近常见 m3u8 文件格式。
    return "\n".join(rewritten_lines) + "\n"


async def refresh_station_stream_url(station_id: str) -> str:
    """立即刷新单个电台的真实 m3u8 地址。

    后台任务会每 5 小时刷新一次，但如果 CDN 提前让 URL 失效，
    请求路由可以调用这个函数立即补抓一次，减少用户侧播放失败。
    """

    # 从注册表中找到当前电台对应的抓取函数。
    fetcher = STATION_FETCHER_MAP.get(station_id)

    # 没有注册抓取器时，说明这是未知电台。
    if fetcher is None:
        raise HTTPException(status_code=404, detail="未知电台。")

    # 调用真实抓取函数，获取最新 m3u8 URL。
    latest_stream_url = await fetcher()

    # 写入全局内存字典，覆盖旧的过期 URL。
    CURRENT_STREAMS[station_id] = latest_stream_url

    # 记录日志，方便确认是否发生过按需续命。
    logger.info("电台 %s 播放地址已按需刷新", station_id)

    # 返回最新 URL，调用方可以立刻用它重试。
    return latest_stream_url


async def refresh_tokens_task() -> None:
    """后台定时刷新所有电台的真实播放地址。

    任务启动后会立刻执行一轮抓取，然后每隔 5 小时再次执行。
    单个电台抓取失败不会影响其他电台，也不会让整个后台任务退出。
    """

    while True:
        # 遍历所有已注册的电台抓取器。
        for station_id in STATION_FETCHER_MAP:
            try:
                # 刷新当前电台真实 m3u8 URL。
                await refresh_station_stream_url(station_id)

                # 记录成功刷新日志，方便排查 token 是否按时续命。
                logger.info("电台 %s 播放地址刷新成功", station_id)
            except Exception:
                # 使用 logger.exception 会自动记录异常堆栈，便于定位真实抓取逻辑的问题。
                logger.exception("电台 %s 播放地址刷新失败", station_id)

        # 当前轮次执行完后休眠 5 小时，再进入下一轮刷新。
        await asyncio.sleep(TOKEN_REFRESH_INTERVAL_SECONDS)


# 全局复用的异步 HTTP 客户端，维持与上游 CDN 的 Keep-Alive 长连接
# 限制最大并发连接数，防止拖垮小鸡内存
http_client = httpx.AsyncClient(
    timeout=HTTP_TIMEOUT,
    verify=CDN_VERIFY_SSL,
    limits=httpx.Limits(max_keepalive_connections=50, max_connections=100)
)

@asynccontextmanager
async def lifespan(app: FastAPI):
    # 启动时执行
    asyncio.create_task(refresh_tokens_task())
    yield
    # 关闭时执行，优雅释放全局客户端
    await http_client.aclose()

# 修改 FastAPI 初始化，传入 lifespan
app = FastAPI(
    title="WaveBypass",
    description="用于聚合电台 m3u8 与 ts 切片代理的后端服务。",
    version="0.1.0",
    lifespan=lifespan, # <-- 新增这一行
)
async def startup_event() -> None:
    """FastAPI 启动时创建后台刷新任务。

    asyncio.create_task 会把刷新循环交给事件循环后台执行，
    不会阻塞 FastAPI 继续启动和处理 HTTP 请求。
    """

    asyncio.create_task(refresh_tokens_task())


def validate_target_url(target_url: str) -> None:
    """校验代理目标 URL 是否只使用 HTTP/HTTPS 协议。"""

    # 解析目标 URL，检查协议部分。
    parsed_target_url = urlparse(target_url)

    # 只允许代理 HTTP/HTTPS URL，避免被构造成 file:// 等危险协议。
    if parsed_target_url.scheme not in {"http", "https"}:
        raise HTTPException(status_code=400, detail="target_url 只允许 http 或 https 地址。")


async def fetch_real_m3u8_text(real_m3u8_url: str, station_id: str) -> httpx.Response:
    """请求真实 CDN m3u8，并返回原始响应对象。"""
    
    # 动态获取当前电台专属的防盗链 Header
    headers = get_cdn_headers_for_station(station_id)
    
    # 如果你之前这里已经改成了用 http_client，就保持用 http_client，
    # 如果还是 async with，那就照下面这样写：
    async with httpx.AsyncClient(
        timeout=HTTP_TIMEOUT,
        follow_redirects=True,
        verify=CDN_VERIFY_SSL,
    ) as client:
        return await client.get(real_m3u8_url, headers=headers)


@app.get("/api/{station_id}/playlist.m3u8")
async def get_station_playlist(
    station_id: str,
    target_url: str | None = Query(default=None, min_length=1),
) -> Response:
    """获取某个电台的代理 m3u8 播放列表。

    这个接口会先尝试命中 3 秒微缓存。
    缓存过期后再访问真实 CDN，并把其中的子级 .m3u8 和 .ts 切片改写到本后端代理接口。
    """

    # UFO 这类电台不是 HLS，没有 playlist.m3u8。
    if station_id in DIRECT_STREAM_STATIONS:
        raise HTTPException(status_code=400, detail="该电台是直连音频流，请使用 /api/{station_id}/stream。")

    # 如果 target_url 存在，说明这是子级 m3u8 请求。
    # 如果 target_url 不存在，说明这是顶层电台 m3u8 请求，需要从 CURRENT_STREAMS 读取真实地址。
    real_m3u8_url = target_url or CURRENT_STREAMS.get(station_id)

    # 如果后台任务还没抓到该电台地址，就返回 503，表示服务暂时不可用。
    if real_m3u8_url is None:
        raise HTTPException(status_code=503, detail="该电台播放地址尚未准备好，请稍后重试。")

    # 校验真实 m3u8 地址，只允许代理 http/https。
    validate_target_url(real_m3u8_url)

    # 缓存键必须包含真实 m3u8 地址。
    # 因为同一个电台可能同时有顶层 playlist.m3u8 和子级 chunklist.m3u8。
    cache_key = f"{station_id}:{real_m3u8_url}"

    # 第一次缓存检查：如果请求刚好落在 3 秒窗口内，立即返回，最快也最省资源。
    cached_text = get_cached_m3u8_text(cache_key)
    if cached_text is not None:
        return Response(content=cached_text, media_type="application/vnd.apple.mpegurl")

    # 获取当前 m3u8 地址专用的锁，避免缓存失效瞬间出现并发击穿。
    cache_lock = get_m3u8_cache_lock(cache_key)

    # 同一个 m3u8 地址同一时间只允许一个请求去真实 CDN 重新拉取。
    async with cache_lock:
        # 第二次缓存检查：等待锁期间，可能已有其他请求完成刷新，所以这里再查一次。
        cached_text = get_cached_m3u8_text(cache_key)
        if cached_text is not None:
            return Response(content=cached_text, media_type="application/vnd.apple.mpegurl")

        try:
            # 请求真实 CDN m3u8。
            real_response = await fetch_real_m3u8_text(real_m3u8_url, station_id)

            # 如果顶层 m3u8 返回 410/403 等状态，说明内存里的长效 URL 可能已经失效。
            # 子级 m3u8 由顶层列表派生，无法单独刷新，所以这里只对顶层请求做按需刷新。
            if target_url is None and real_response.status_code in TOKEN_REFRESH_HTTP_STATUS_CODES:
                logger.warning(
                    "电台 %s 顶层 m3u8 返回 %s，准备刷新 token 后重试一次",
                    station_id,
                    real_response.status_code,
                )

                # 立即抓取最新真实 m3u8 URL。
                real_m3u8_url = await refresh_station_stream_url(station_id)

                # 重新计算缓存键，避免继续写入旧 URL 的缓存槽。
                cache_key = f"{station_id}:{real_m3u8_url}"

                # 使用新 URL 重试一次。
                real_response = await fetch_real_m3u8_text(real_m3u8_url, station_id)

            # 非 2xx 状态通常表示 CDN 拒绝、token 失效或源站异常。
            real_response.raise_for_status()
        except httpx.HTTPError as exc:
            # 记录真实异常，返回给前端时隐藏内部细节。
            logger.exception("电台 %s 真实 m3u8 拉取失败：%s", station_id, exc)
            raise HTTPException(status_code=502, detail="真实 m3u8 拉取失败。") from exc

        # 将真实 m3u8 里的子级 .m3u8 和 .ts 切片地址改写成我们的代理地址。
        rewritten_m3u8_text = rewrite_m3u8_text(real_response.text, real_m3u8_url, station_id)

        # 更新微缓存文本和时间戳。
        M3U8_CACHE[cache_key] = {
            "text": rewritten_m3u8_text,
            "timestamp": time.time(),
        }

        # 返回标准 HLS m3u8 MIME 类型，方便播放器正确识别。
        return Response(content=rewritten_m3u8_text, media_type="application/vnd.apple.mpegurl")


@app.get("/api/{station_id}/{m3u8_name}.m3u8")
async def get_relative_child_playlist(station_id: str, m3u8_name: str, request: Request) -> Response:
    """兼容播放器直接请求相对子级 m3u8 的情况。

    修复前端已经拿到旧主列表时，浏览器可能会请求：
    /api/hitfm/chunklist.m3u8?token1=...

    这里会根据当前电台的顶层真实 m3u8 URL，把 chunklist.m3u8 补成真实 CDN URL，
    然后复用 get_station_playlist 的代理、缓存和改写逻辑。
    """

    # 从内存中读取当前电台顶层真实 m3u8 地址。
    base_m3u8_url = CURRENT_STREAMS.get(station_id)

    # 如果后台任务还没准备好地址，就返回 503。
    if base_m3u8_url is None:
        raise HTTPException(status_code=503, detail="该电台播放地址尚未准备好，请稍后重试。")

    # 保留原请求中的 token、expire 等查询参数。
    query_string = request.url.query

    # 重新拼出相对子级 m3u8 文件名。
    relative_m3u8_path = f"{m3u8_name}.m3u8"

    # 如果有查询参数，就接回文件名后面。
    if query_string:
        relative_m3u8_path = f"{relative_m3u8_path}?{query_string}"

    # 根据顶层真实 m3u8 URL，把相对子列表地址补成真实 CDN 绝对地址。
    child_m3u8_url = urljoin(base_m3u8_url, relative_m3u8_path)

    # 复用主 playlist 路由逻辑。
    return await get_station_playlist(station_id=station_id, target_url=child_m3u8_url)


@app.get("/api/{station_id}/chunk.ts")
async def proxy_ts_chunk(
    station_id: str,
    target_url: str = Query(..., min_length=1),
) -> StreamingResponse:
    """代理单个 ts 音频切片。

    该接口已使用全局 HTTP 连接池进行优化，大幅降低 TLS 握手开销。
    边从真实 CDN 读取、边转发给前端播放器，不占用过多内存。
    """

    # 校验真实切片地址，只允许代理 http/https。
    validate_target_url(target_url)

    # 主动设置请求头，不透传浏览器的真实客户端 IP。
    upstream_headers = get_cdn_headers_for_station(station_id)

    # 先把响应变量设为 None，方便异常分支释放资源。
    upstream_response: httpx.Response | None = None

    try:
        # 【核心修改 1】：直接使用全局的 http_client 构建请求
        request = http_client.build_request("GET", target_url, headers=upstream_headers)

        # stream=True 表示只打开响应流，不一次性读进内存。
        upstream_response = await http_client.send(request, stream=True)

        # 如果真实 CDN 返回错误，先关闭响应流，再返回 502 给前端。
        upstream_response.raise_for_status()
    except httpx.HTTPError as exc:
        if upstream_response is not None:
            await upstream_response.aclose()
        # 【核心修改 2】：删除了 await client.aclose()，不关闭全局客户端
        logger.exception("电台 %s ts 切片代理失败：%s", station_id, exc)
        raise HTTPException(status_code=502, detail="真实 ts 切片拉取失败。") from exc

    async def stream_ts_bytes() -> AsyncIterator[bytes]:
        """逐块读取真实 ts 响应并转发给前端。"""
        try:
            # 每次最多读取 64KB，在吞吐和内存之间取得平衡。
            async for chunk in upstream_response.aiter_bytes(chunk_size=64 * 1024):
                if chunk:
                    yield chunk
        finally:
            # 【核心修改 3】：无论播放正常结束还是中途断开，只需关闭响应流。
            # 绝对不能写 await http_client.aclose()，要把连接还给全局池！
            await upstream_response.aclose()

    # StreamingResponse 会消费上面的异步生成器，实现边下边传。
    # 在最后返回 StreamingResponse 的时候加上 headers
    return StreamingResponse(
        stream_ts_bytes(), 
        media_type="video/MP2T",
        headers={
            "Access-Control-Allow-Origin": "*",
            "Cache-Control": "no-cache", # 避免前端缓存旧切片
            # "Content-Disposition": "attachment; filename=chunk.ts" # 可选：强制定制下载名，主要用于调试
        }
    )


@app.get("/api/{station_id}/stream")
async def proxy_direct_audio_stream(station_id: str) -> StreamingResponse:
    """代理直连音频流电台。

    该接口已使用全局 HTTP 连接池进行优化，避免重复建立连接。
    UFO Radio 这类源是一个持续输出的 MP3/AAC 音频流。
    这里使用边读边传，避免把无限直播流读入内存。
    """

    # 只允许已声明为直连流的电台使用这个接口。
    if station_id not in DIRECT_STREAM_STATIONS:
        raise HTTPException(status_code=400, detail="该电台不是直连音频流。")

    # 从内存中读取后台任务维护的最新真实音频流 URL。
    real_stream_url = CURRENT_STREAMS.get(station_id)

    # 如果后台还没准备好 URL，就立即刷新一次。
    if real_stream_url is None:
        real_stream_url = await refresh_station_stream_url(station_id)

    # 校验真实音频流地址。
    validate_target_url(real_stream_url)

    # 【核心修改 1】：删除了局部 client 的创建代码

    # 先把响应变量设为 None，方便异常分支释放资源。
    upstream_response: httpx.Response | None = None

    try:
        # 【核心修改 2】：使用全局 http_client 构造和发送请求
        request = http_client.build_request("GET", real_stream_url, headers=CDN_REQUEST_HEADERS)
        upstream_response = await http_client.send(request, stream=True)

        # 如果 token 失效，立即刷新一次 UFO 跳转地址后重试。
        if upstream_response.status_code in TOKEN_REFRESH_HTTP_STATUS_CODES:
            await upstream_response.aclose()

            logger.warning(
                "电台 %s 直连音频流返回 %s，准备刷新地址后重试一次",
                station_id,
                upstream_response.status_code,
            )

            real_stream_url = await refresh_station_stream_url(station_id)
            # 【核心修改 3】：重试机制里也使用全局 http_client
            request = http_client.build_request("GET", real_stream_url, headers=CDN_REQUEST_HEADERS)
            upstream_response = await http_client.send(request, stream=True)

        # 非 2xx 状态说明真实音频流仍然不可用。
        upstream_response.raise_for_status()
    except httpx.HTTPError as exc:
        if upstream_response is not None:
            await upstream_response.aclose()
        # 【核心修改 4】：删除了 await client.aclose()，不关闭全局连接池
        logger.exception("电台 %s 直连音频流代理失败：%s", station_id, exc)
        raise HTTPException(status_code=502, detail="真实音频流拉取失败。") from exc

    async def stream_audio_bytes() -> AsyncIterator[bytes]:
        """逐块读取真实音频流并转发给前端。"""
        try:
            # 直播音频流没有固定结束时间，所以必须逐块转发。
            async for chunk in upstream_response.aiter_bytes(chunk_size=64 * 1024):
                if chunk:
                    yield chunk
        finally:
            # 【核心修改 5】：用户断开时，只释放上游响应流，绝对不能关闭全局 http_client
            await upstream_response.aclose()

    # 优先复用上游 Content-Type；如果上游没给，就用通用音频类型。
    media_type = upstream_response.headers.get("content-type", "audio/mpeg")

    return StreamingResponse(stream_audio_bytes(), media_type=media_type)