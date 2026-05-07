"""WaveBypass 后端入口。

本文件负责初始化 FastAPI 应用、配置跨域、维护内存中的电台播放地址，
并在服务启动后开启后台定时任务，持续刷新各电台的 CDN token 地址。
"""

import asyncio
import logging
import os
import time
import json
from collections.abc import AsyncIterator
from urllib.parse import quote, urljoin, urlparse

import httpx
from fastapi import FastAPI, HTTPException, Query, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from contextlib import asynccontextmanager
from fetchers import STATION_FETCHER_MAP, yunting


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
DIRECT_STREAM_STATIONS = {""}


# ========== 地域限制配置 ==========
# GEO_RESTRICT=1 启用地域限制，大陆 IP 自动屏蔽指定地区电台
GEO_RESTRICT = os.getenv("GEO_RESTRICT", "").strip() == "1"
# 被屏蔽的地区 tag 列表，逗号分隔，默认 TW
GEO_BLOCKED_REGIONS = set(
    r.strip() for r in os.getenv("GEO_BLOCKED_REGIONS", "TW").split(",") if r.strip()
)
# 静态电台配置（与前端 stations.js 同步）
STATIC_STATIONS = [
    {"id": "hitfm", "name": "Hit FM 台北", "logoText": "H", "logoUrl": "/logos/hitfm.png", "tags": ["music", "TW"]},
    {"id": "hitfm_taichung", "name": "Hit FM 台中", "logoText": "台中", "logoUrl": "/logos/hitfm.png", "tags": ["music", "TW"]},
    {"id": "hitfm_tainan", "name": "Hit FM 台南", "logoText": "台南", "logoUrl": "/logos/hitfm.png", "tags": ["music", "TW"]},
    {"id": "hitfm_yilan", "name": "Hit FM 宜兰", "logoText": "宜兰", "logoUrl": "/logos/hitfm.png", "tags": ["music", "TW"]},
    {"id": "hitfm_huadong", "name": "Hit FM 花东", "logoText": "花东", "logoUrl": "/logos/hitfm.png", "tags": ["music", "TW"]},
    {"id": "pop917", "name": "POP Radio 91.7", "logoText": "POP", "logoUrl": "/logos/pop917.jpg", "tags": ["music", "TW"]},
    {"id": "qz_fm889", "name": "泉州新闻综合 88.9", "logoText": "FM889", "logoUrl": "/logos/qz889.png", "tags": ["CN", "福建", "news"]},
    {"id": "qz_fm904", "name": "泉州交通广播 90.4", "logoText": "FM904", "logoUrl": "/logos/qz904.png", "tags": ["CN", "福建", "news"]},
    {"id": "qz_fm1059", "name": "泉州刺桐之声 105.9", "logoText": "FM1059", "logoUrl": "/logos/qz1059.png", "tags": ["CN", "福建", "talk"]},
    {"id": "qz_fm923", "name": "泉州经济生活 92.3", "logoText": "FM923", "logoUrl": "/logos/qz923.png", "tags": ["CN", "福建", "news"]},
]

# 从 STATIC_STATIONS 的 tags 动态提取各地区电台 ID（不硬编码）
_TW_STATION_IDS = {s["id"] for s in STATIC_STATIONS if "TW" in s.get("tags", [])}


def _is_geo_blocked(station_id: str, request: Request) -> bool:
    """检查电台是否因地域限制被屏蔽。根据 tags 动态判断电台所属地区。"""
    if not GEO_RESTRICT or not GEO_BLOCKED_REGIONS:
        return False
    country = request.headers.get("cf-ipcountry", "").upper()
    if country and country != "CN":
        return False  # 海外不限制
    # 根据 ID 前缀和缓存判断电台所属地区（tags 在前端，后端用前缀推断）
    is_tw = (
        station_id.startswith("mr_")       # myradio 全是台湾台
        or station_id in _TW_STATION_IDS    # 静态配置中 tag 含 TW 的
        or station_id in MYRADIO_CACHE      # myradio 缓存中的
    )
    if is_tw and "TW" in GEO_BLOCKED_REGIONS:
        return True
    if not is_tw and "CN" in GEO_BLOCKED_REGIONS:
        return True
    return False


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

        # 非媒体切片资源原样保留，避免误改其他 HLS 标签。
        # 除 .ts 外，.aac/.mp3/.mp4/.fmp4/.m4s 也是常见的 HLS 切片格式。
        SEGMENT_EXTENSIONS = (".ts", ".aac", ".mp3", ".mp4", ".fmp4", ".m4s")
        if not uri_path.endswith(SEGMENT_EXTENSIONS):
            rewritten_lines.append(line)
            continue

        # 生成指向本后端切片代理接口的地址。
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

# 云听 API 专用共享客户端，31 个省份共用连接池，省掉 31 次独立 TLS 握手
yunting_client = httpx.AsyncClient(
    timeout=15.0,
    follow_redirects=True,
    limits=httpx.Limits(max_keepalive_connections=10, max_connections=10),
)


# 云听定时刷新间隔：1 小时（URL 有效期约 19 小时，EPG 每半小时换节目，1h 是安全折中）
YUNTING_REFRESH_INTERVAL = 1 * 3600

# 并发信号量：限制同时发出的云听 API 请求数，避免触发 WAF 封禁
_yunting_sem = asyncio.Semaphore(5)


async def _fetch_one_province(prov: str) -> list[dict] | None:
    """拉取单个省份的云听电台列表，受信号量限流。

    成功返回电台列表（已做 http→https 改写），失败返回 None（保留旧缓存）。
    """
    try:
        async with _yunting_sem:
            resp = await yunting_client.get(
                YUNTING_API_BASE,
                params={"categoryId": 0, "provinceCode": prov},
                headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json"},
            )
        resp.raise_for_status()
        stations = resp.json().get("data", [])
        for s in stations:
            for key in ("playUrlLow", "mp3PlayUrlLow", "mp3PlayUrlHigh"):
                if isinstance(s.get(key), str) and s[key].startswith("http://"):
                    s[key] = "https://" + s[key][7:]
        return stations
    except Exception:
        logger.warning("云听省份 %s 拉取失败，保留旧缓存", prov)
        return None


def _write_yunting_caches(prov: str, stations: list[dict], now: float) -> None:
    """将单个省份的电台数据写入三层缓存。"""

    # 电台 API 原始数据不含 provinceCode，注入后前端 /api/yunting/all 可按省份分组
    for s in stations:
        s.setdefault("provinceCode", prov)
    YUNTING_CACHE[prov] = {"data": json.dumps(stations, ensure_ascii=False), "ts": now}
    for s in stations:
        cid = str(s.get("contentId", ""))
        if not cid:
            continue
        url = s.get("playUrlLow", "")
        if url.startswith(("http://", "https://")):
            YUNTING_URL_CACHE[f"yt_{cid}"] = {"url": url, "ts": now}
        sub = s.get("subtitle", "")
        if sub:
            YUNTING_EPG_CACHE[f"yt_{cid}"] = {"subtitle": sub, "ts": now}


async def _yunting_warmup() -> None:
    """拉取一轮所有省份的云听数据并写入缓存，同时预合并全量响应。"""
    now = time.time()
    tasks = [_fetch_one_province(prov) for prov in YUNTING_PROVINCES]
    results = await asyncio.gather(*tasks)

    prefetched = 0
    merged: list[dict] = []
    for prov, stations in zip(YUNTING_PROVINCES, results):
        if stations is None:
            # 拉取失败，从旧缓存补充到 merged
            cached = YUNTING_CACHE.get(prov)
            if cached:
                merged.extend(json.loads(cached["data"]))
            continue
        _write_yunting_caches(prov, stations, now)
        merged.extend(stations)
        prefetched += 1

    # 预合并全量响应，后续 /api/yunting/all 直接返回，零 JSON 解析
    if merged:
        YUNTING_ALL_CACHE["data"] = json.dumps(merged, ensure_ascii=False).encode("utf-8")
        YUNTING_ALL_CACHE["ts"] = now

    logger.info("云听缓存预热完成: %d/%d 个省份成功", prefetched, len(YUNTING_PROVINCES))


async def _yunting_refresh_task() -> None:
    """后台定时守护协程：启动时预热 + 每小时静默刷新云听三层缓存。"""
    while True:
        await _yunting_warmup()
        await asyncio.sleep(YUNTING_REFRESH_INTERVAL)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 启动时执行
    asyncio.create_task(refresh_tokens_task())
    asyncio.create_task(_yunting_refresh_task())
    asyncio.create_task(_myradio_refresh_task())
    asyncio.create_task(_prefetch_rb())
    yield
    # 关闭时执行，优雅释放全局客户端
    await http_client.aclose()
    await yunting_client.aclose()

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


@app.get("/api/config")
async def get_config(request: Request) -> dict:
    """返回前端需要的运行时配置（地域限制信息）。"""
    if not GEO_RESTRICT:
        return {"geoRestrict": False}
    country = request.headers.get("cf-ipcountry", "").upper()
    if country and country != "CN":
        return {"geoRestrict": False}
    return {
        "geoRestrict": True,
        "blockedRegions": sorted(GEO_BLOCKED_REGIONS),
    }


@app.get("/api/stations")
async def get_stations(request: Request) -> Response:
    """返回静态电台列表，根据地域限制过滤。前端启动时调用替代本地 stations.js。"""

    if not GEO_RESTRICT:
        stations = STATIC_STATIONS
    else:
        country = request.headers.get("cf-ipcountry", "").upper()
        if country and country != "CN":
            stations = STATIC_STATIONS
        else:
            blocked = GEO_BLOCKED_REGIONS
            stations = [s for s in STATIC_STATIONS if not any(t in blocked for t in s.get("tags", []))]

    return Response(
        content=json.dumps(stations, ensure_ascii=False),
        media_type="application/json",
    )


@app.get("/api/{station_id}/playlist.m3u8")
async def get_station_playlist(
    station_id: str,
    target_url: str | None = Query(default=None, min_length=1),
    request: Request = None,
) -> Response:
    """获取某个电台的代理 m3u8 播放列表。

    这个接口会先尝试命中 3 秒微缓存。
    缓存过期后再访问真实 CDN，并把其中的子级 .m3u8 和 .ts 切片改写到本后端代理接口。
    """
    if request and _is_geo_blocked(station_id, request):
        raise HTTPException(status_code=403, detail="该电台因地域限制不可用。")

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
    if _is_geo_blocked(station_id, request):
        raise HTTPException(status_code=403, detail="该电台因地域限制不可用。")

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
    request: Request = None,
) -> StreamingResponse:
    """代理单个 ts 音频切片。

    该接口已使用全局 HTTP 连接池进行优化，大幅降低 TLS 握手开销。
    边从真实 CDN 读取、边转发给前端播放器，不占用过多内存。
    """
    if request and _is_geo_blocked(station_id, request):
        raise HTTPException(status_code=403, detail="该电台因地域限制不可用。")

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

@app.get("/api/proxy/stream")
async def proxy_stream(url: str = Query(...)) -> StreamingResponse:
    """通用音频流代理：接受任意 URL，流式转发，绕过浏览器 CORS 限制。"""

    if not url.startswith(("http://", "https://")):
        raise HTTPException(status_code=400, detail="仅支持 http/https 地址。")

    # 自动添加基于 URL 来源的 Referer 头，部分 CDN（如 qingting.fm）要求自引用 Referer
    parsed = urlparse(url)
    referer = f"{parsed.scheme}://{parsed.netloc}/"
    headers = {**CDN_REQUEST_HEADERS, "Referer": referer}

    async def _stream():
        try:
            async with httpx.AsyncClient(verify=False, follow_redirects=True) as client:
                async with client.stream("GET", url, headers=headers, timeout=HTTP_TIMEOUT) as resp:
                    resp.raise_for_status()
                    async for chunk in resp.aiter_bytes(8192):
                        yield chunk
        except Exception:
            return

    return StreamingResponse(_stream(), media_type="audio/mpeg")

@app.get("/api/{station_id}/stream")
async def proxy_direct_audio_stream(station_id: str, request: None) -> StreamingResponse:
    """代理直连音频流电台。

    该接口已使用全局 HTTP 连接池进行优化，避免重复建立连接。
    这里使用边读边传，避免把无限直播流读入内存。
    """
    if request and _is_geo_blocked(station_id, request):
        raise HTTPException(status_code=403, detail="该电台因地域限制不可用。")

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
        upstream_req = http_client.build_request("GET", real_stream_url, headers=CDN_REQUEST_HEADERS)
        upstream_response = await http_client.send(upstream_req, stream=True)

        if upstream_response.status_code in TOKEN_REFRESH_HTTP_STATUS_CODES:
            await upstream_response.aclose()

            logger.warning(
                "电台 %s 直连音频流返回 %s，准备刷新地址后重试一次",
                station_id,
                upstream_response.status_code,
            )

            real_stream_url = await refresh_station_stream_url(station_id)
            # 【核心修改 3】：重试机制里也使用全局 http_client
            upstream_req = http_client.build_request("GET", real_stream_url, headers=CDN_REQUEST_HEADERS)
            upstream_response = await http_client.send(upstream_req, stream=True)

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


# 云听 (radio.cn) 代理配置。
# 新增省份只需在 YUNTING_PROVINCES 加一个省份代码。
YUNTING_API_BASE = "https://ytmsout.radio.cn/web/appBroadcast/list"
YUNTING_PROVINCES = [
    '340000',  # 安徽
    '110000',  # 北京
    '500000',  # 重庆
    '350000',  # 福建
    '620000',  # 甘肃
    '440000',  # 广东
    '450000',  # 广西
    '520000',  # 贵州
    '460000',  # 海南
    '130000',  # 河北
    '410000',  # 河南
    '230000',  # 黑龙江
    '420000',  # 湖北
    '430000',  # 湖南
    '220000',  # 吉林
    '320000',  # 江苏
    '360000',  # 江西
    '210000',  # 辽宁
    '150000',  # 内蒙古
    '640000',  # 宁夏
    '630000',  # 青海
    '370000',  # 山东
    '140000',  # 山西
    '610000',  # 陕西
    '310000',  # 上海
    '510000',  # 四川
    '540000',  # 西藏
    '650000',  # 新疆
    '660000',  # 新疆兵团
    '530000',  # 云南
    '330000',  # 浙江
]
YUNTING_CACHE: dict[str, dict] = {}
YUNTING_CACHE_TTL = 2 * 3600

# 云听全量合并缓存：/api/yunting/all 的预合并结果，命中时零 JSON 解析
YUNTING_ALL_CACHE: dict[str, bytes | float] = {}  # {"data": json_bytes, "ts": float}

# 云听 EPG（当前节目名）独立缓存，比电台列表更新更频繁。
# 电台列表 2 小时足够，但节目每半小时换一次，EPG 用 10 分钟 TTL。
YUNTING_EPG_CACHE: dict[str, dict] = {}   # {"yt_{contentId}": {"subtitle": "...", "ts": ...}}
YUNTING_EPG_TTL = 10 * 60

# 云听电台播放 URL 缓存。
# proxy_yunting_stations 加载电台列表时已拿到所有 URL，顺便缓存起来。
# get_stream_url 直接从这里读，省掉每次单独调 fetch_yunting() 的延迟。
# URL 有效期约 19 小时（key+time 参数），缓存 1 小时完全够用。
YUNTING_URL_CACHE: dict[str, dict] = {}   # {"yt_{contentId}": {"url": "...", "ts": ...}}
YUNTING_URL_TTL = 1 * 3600


# ==========================================
# myradio.tw 电台缓存
# ==========================================
# key 格式：mr_{id}（如 mr_A1001），value 包含 name/url/logo/ts
# 24h TTL，myradio 官网直链无 token 过期，长缓存没问题
MYRADIO_CACHE: dict[str, dict] = {}
MYRADIO_CACHE_TTL = 24 * 3600


async def _myradio_refresh_task() -> None:
    """后台定时守护协程：预热 + 每 24 小时静默刷新 myradio 缓存。"""
    from fetchers import fetch_myradio_all

    while True:
        try:
            stations = await fetch_myradio_all()
            if stations:
                now = time.time()
                MYRADIO_CACHE.clear()
                for s in stations:
                    MYRADIO_CACHE[f"mr_{s['id']}"] = {
                        "name": s["name"],
                        "url": s["url"],
                        "logo": s["logo"],
                        "freq": s.get("freq", ""),
                        "tag": s.get("tag", ""),
                        "ts": now,
                    }
                logger.info("myradio 电台预热完成: %d 个", len(stations))
            else:
                logger.warning("myradio 抓取返回空列表")
        except Exception:
            logger.exception("myradio 预热/刷新失败")
        await asyncio.sleep(MYRADIO_CACHE_TTL)


@app.get("/api/myradio/all")
async def get_myradio_all(request: Request) -> Response:
    """返回所有已缓存的 myradio 电台列表（从预热缓存读取）。"""

    stations = [
        {"id": k.replace("mr_", ""), "name": v["name"], "url": v["url"],
         "logo": v["logo"], "freq": v.get("freq", ""), "tag": v.get("tag", "")}
        for k, v in MYRADIO_CACHE.items()
        if not _is_geo_blocked(k, request)
    ]
    return Response(
        content=json.dumps(stations, ensure_ascii=False),
        media_type="application/json",
    )


@app.get("/api/yunting/stations/{province_code}")
async def proxy_yunting_stations(province_code: str) -> Response:
    """反代云听电台列表 API，缓存 2 小时。

    前端通过此接口发现云听电台，返回的电台 ID 格式为 yt_{contentId}。
    流地址由 stream-url 端点按需提供，不在此处暴露（token 会过期）。
    """
    cached = YUNTING_CACHE.get(province_code)
    if cached and time.time() - cached["ts"] < YUNTING_CACHE_TTL:
        return Response(content=cached["data"], media_type="application/json")

    params = {"categoryId": 0, "provinceCode": province_code}
    headers = {"User-Agent": "Mozilla/5.0", "Accept": "application/json"}
    try:
        resp = await yunting_client.get(
            YUNTING_API_BASE, params=params, headers=headers,
        )
        resp.raise_for_status()
    except httpx.HTTPError as exc:
        if cached:
            logger.warning("云听 API 拉取失败，返回缓存: %s", exc)
            return Response(content=cached["data"], media_type="application/json")
        raise HTTPException(status_code=502, detail="云听 API 请求失败") from exc

    # 只缓存 data 数组（不存整个 {code, message, data} 包装），前端和 EPG 端点都直接遍历数组
    # 云听 API 返回的 URL 是 http://，HTTPS 页面会拦截混合内容，统一改为 https://
    
    stations = resp.json().get("data", [])
    for s in stations:
        s.setdefault("provinceCode", province_code)  # 注入省份代码，供前端 /api/yunting/all 分组
        for key in ("playUrlLow", "mp3PlayUrlLow", "mp3PlayUrlHigh"):
            if isinstance(s.get(key), str) and s[key].startswith("http://"):
                s[key] = "https://" + s[key][7:]
    stations_json = json.dumps(stations, ensure_ascii=False)
    YUNTING_CACHE[province_code] = {"data": stations_json, "ts": time.time()}

    # 同时预填充 URL 缓存和 EPG 缓存，后续 get_stream_url 和 EPG 端点可直接命中，无需再调云听 API
    now = time.time()
    for s in stations:
        cid = str(s.get("contentId", ""))
        if not cid:
            continue
        url = s.get("playUrlLow", "")
        if url.startswith(("http://", "https://")):
            YUNTING_URL_CACHE[f"yt_{cid}"] = {"url": url, "ts": now}
        subtitle = s.get("subtitle", "")
        if subtitle:
            YUNTING_EPG_CACHE[f"yt_{cid}"] = {"subtitle": subtitle, "ts": now}

    return Response(content=stations_json, media_type="application/json")


@app.get("/api/yunting/all")
async def proxy_yunting_all() -> Response:
    """一次返回所有省份的云听电台列表，前端只需一个请求。

    优先读预合并缓存 YUNTING_ALL_CACHE（预热时填充），命中时零 JSON 解析。
    未命中时从各省缓存拼接，缺失的省份实时拉取。
    """
    

    now = time.time()

    # 快速路径：预合并缓存命中，直接返回原始 bytes
    all_cached = YUNTING_ALL_CACHE.get("data")
    all_ts = YUNTING_ALL_CACHE.get("ts", 0)
    if all_cached and now - all_ts < YUNTING_CACHE_TTL:
        return Response(
            content=all_cached,
            media_type="application/json",
            headers={"Cache-Control": "public, s-maxage=3600, max-age=300"},
        )

    # 慢速路径：从各省缓存拼接
    merged: list[dict] = []
    missing: list[str] = []

    for prov in YUNTING_PROVINCES:
        cached = YUNTING_CACHE.get(prov)
        if cached and now - cached["ts"] < YUNTING_CACHE_TTL:
            merged.extend(json.loads(cached["data"]))
        else:
            missing.append(prov)

    if missing:
        tasks = [_fetch_one_province(prov) for prov in missing]
        results = await asyncio.gather(*tasks)
        for prov, stations in zip(missing, results):
            if stations is None:
                continue
            _write_yunting_caches(prov, stations, now)
            merged.extend(stations)

    # 写入预合并缓存，下次请求命中
    result_bytes = json.dumps(merged, ensure_ascii=False).encode("utf-8")
    YUNTING_ALL_CACHE["data"] = result_bytes
    YUNTING_ALL_CACHE["ts"] = now
    return Response(
        content=result_bytes,
        media_type="application/json",
        headers={"Cache-Control": "public, s-maxage=3600, max-age=300"},
    )


@app.get("/api/yunting/epg")
async def yunting_epg() -> Response:
    """返回所有已缓存省份电台的 EPG（当前节目名），供前端定期刷新。

    优先读 YUNTING_EPG_CACHE（10 分钟 TTL），命中即零网络请求。
    EPG 过期时从 YUNTING_CACHE（2h）补充；两者都过期才拉云听 API。
    返回格式：{"contentId": "节目名", ...}
    """
    

    now = time.time()
    merged: dict[str, str] = {}

    # 第一优先级：从独立 EPG 缓存读取（10 分钟 TTL）
    stale_epg_keys: list[str] = []
    for key, entry in YUNTING_EPG_CACHE.items():
        if now - entry["ts"] < YUNTING_EPG_TTL:
            merged[key.replace("yt_", "")] = entry["subtitle"]
        else:
            stale_epg_keys.append(key)

    # 第二优先级：从省份列表缓存补充过期的 EPG 条目（2h TTL）
    need_api_refresh: list[str] = []
    if stale_epg_keys:
        # 哪些省份的列表缓存还新鲜？直接从里面读 subtitle
        fresh_provs: list[str] = []
        for prov in YUNTING_PROVINCES:
            cached = YUNTING_CACHE.get(prov)
            if cached and now - cached["ts"] < YUNTING_CACHE_TTL:
                fresh_provs.append(prov)
                for item in json.loads(cached["data"]):
                    cid = str(item.get("contentId", ""))
                    sub = item.get("subtitle", "")
                    if cid and sub and f"yt_{cid}" in stale_epg_keys:
                        merged[cid] = sub
                        # 同步回写 EPG 缓存，延长寿命
                        YUNTING_EPG_CACHE[f"yt_{cid}"] = {"subtitle": sub, "ts": now}
        # EPG 过期 + 列表缓存也过期的省份，需要调 API
        if len(fresh_provs) < len(YUNTING_PROVINCES):
            need_api_refresh = [p for p in YUNTING_PROVINCES if p not in fresh_provs]

    # 第三优先级：调云听 API 获取最新数据，同时更新两个缓存
    if need_api_refresh:
        for prov in need_api_refresh:
            try:
                resp = await yunting_client.get(
                    YUNTING_API_BASE,
                    params={"categoryId": 0, "provinceCode": prov},
                    headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json"},
                )
                resp.raise_for_status()
                stations_data = resp.json().get("data", [])
                for s in stations_data:
                    s.setdefault("provinceCode", prov)
                    for key in ("playUrlLow", "mp3PlayUrlLow", "mp3PlayUrlHigh"):
                        if isinstance(s.get(key), str) and s[key].startswith("http://"):
                            s[key] = "https://" + s[key][7:]
                YUNTING_CACHE[prov] = {"data": json.dumps(stations_data, ensure_ascii=False), "ts": now}
                for item in stations_data:
                    cid = str(item.get("contentId", ""))
                    sub = item.get("subtitle", "")
                    if cid and sub:
                        merged[cid] = sub
                        YUNTING_EPG_CACHE[f"yt_{cid}"] = {"subtitle": sub, "ts": now}
            except Exception:
                pass

    return Response(content=json.dumps(merged), media_type="application/json")


import re as _re


# 繁→简映射（仅电台名高频字，覆盖 myradio.tw 台湾电台常见用字）
_T2S = {
    "樂": "乐", "聲": "声", "網": "网", "廣": "广", "聯": "联",
    "談": "谈", "體": "体", "車": "车", "濟": "济", "鄉": "乡",
    "訊": "讯", "藝": "艺", "語": "语", "華": "华", "電": "电",
    "視": "视", "國": "国", "劇": "剧", "寶": "宝", "環": "环",
    "紅": "红", "節": "节", "製": "制", "報": "报", "導": "导",
    "續": "续", "話": "话", "兒": "儿", "動": "动", "預": "预",
    "後": "后", "獨": "独", "經": "经", "選": "选", "顧": "顾",
    "慶": "庆", "親": "亲", "師": "师", "勞": "劳", "樹": "树",
    "費": "费", "際": "际", "婦": "妇", "軍": "军", "黨": "党",
    "陽": "阳", "萬": "万", "聖": "圣", "誕": "诞", "與": "与",
    "術": "术", "雜": "杂", "舞": "舞", "戲": "戏", "戲": "戏",
    "廳": "厅", "錄": "录", "紀": "纪", "繪": "绘", "攝": "摄",
    "書": "书", "畫": "画", "詩": "诗", "詞": "词", "謠": "谣",
    "調": "调", "擊": "击", "搖": "摇", "滾": "滚", "藍": "蓝",
    "靈": "灵", "處": "处", "號": "号", "機": "机", "檔": "档",
    "線": "线", "練": "练", "組": "组", "團": "团", "隊": "队",
    "員": "员", "場": "场", "館": "馆", "園": "园", "區": "区",
    "鄉": "乡", "鎮": "镇", "縣": "县", "島": "岛", "峽": "峡",
    "灣": "湾", "裡": "里", "裡": "里", "週": "周", "東": "东",
    "西": "西", "南": "南", "北": "北", "中": "中",
}


def _normalize_name(raw: str) -> str:
    """电台名称规范化：去空格、转小写、去常见后缀和频率、繁→简，用于跨源模糊匹配。

    "HitFM 台北"       → "hitfm台北"
    "HitFM台北之聲"     → "hitfm台北"
    "Hit FM 97.7 古典音樂" → "hitfm古典音乐"
    "泉州新闻综合 88.9"  → "泉州新闻综合"
    "泉州新闻综合广播"   → "泉州新闻综合"
    """
    s = raw.lower().replace(" ", "")
    # 去频率数字（FM 97.7、88.9 等，保留 "HitFM" 中的 FM）
    s = _re.sub(r"(?<![a-z])fm\d[\d.]*", "", s)
    # 去常见后缀（支持 城市+后缀 的组合，如 "台北之声" → 去掉）
    s = _re.sub(r"[一-鿥]{0,4}(之声|之聲|电台|广播电台|广播|联播网|聯播網)$", "", s)
    # 繁→简（电台名高频字）
    s = "".join(_T2S.get(c, c) for c in s)
    return s


def _names_match(query: str, target: str) -> bool:
    """保守的名称匹配，防止短子串误匹配。

    规则：
    1. 完全相等 → True
    2. 短串是长串的子串：要求短串 ≥ 4 字符，且长度 ≥ 长串的 60%
       例：'hitfm' in 'hitfm台北'       → 5≥4, 5/7=71%  → True
       例：'新闻综合' in '泉州新闻综合广播' → 4≥4, 4/8=50%  → True（反向：长串含短串时同理）
       例：'全球华语广播网' in 'needsradio全球华语广播网' → 7/15=47% < 60% → False
    3. 其他情况 → False
    """
    if not query or not target:
        return False
    if query == target:
        return True
    shorter, longer = (query, target) if len(query) <= len(target) else (target, query)
    if shorter in longer and len(shorter) >= 4 and len(shorter) * 100 >= len(longer) * 60:
        return True
    return False


def _find_yunting_url(station_id: str, name: str = "") -> str | None:
    """在云听缓存中按名称匹配电台，返回 playUrlLow 或 None。

    匹配策略（按优先级）：
    1. 前端传来的电台名称：提取中文关键词（去掉数字和空格）+ 频率，在云听中精确查找
    2. station_id 城市代码兜底（如 qz → "泉州"）

    name 由前端 AudioEngine 从 stations.js 的 stationMap 中获取并传递，无需后端维护额外字典。
    """
    

    if station_id.startswith(("yt_", "rb_")):
        return None

    def _search(keyword: str | None, freq_digits: str) -> str | None:
        for prov in YUNTING_PROVINCES:
            cached = YUNTING_CACHE.get(prov)
            if not cached:
                continue
            try:
                for item in json.loads(cached["data"]):
                    title = item.get("title", "")
                    if keyword and keyword not in title:
                        continue
                    if freq_digits:
                        title_freqs = _re.findall(r"\d{2,3}\.\d", title)
                        if not any(f.replace(".", "") == freq_digits for f in title_freqs):
                            continue
                    url = item.get("playUrlLow", "")
                    # 防御性修复：缓存数据理论上已改为 HTTPS，但旧缓存可能残留 HTTP
                    if url.startswith("http://"):
                        url = "https://" + url[7:]
                    if url.startswith(("http://", "https://")):
                        return url
            except Exception:
                continue
        return None

    # 策略 1：用前端传来的电台名称匹配
    if name:
        # 去掉数字和小数点，只保留中文字符（提取电台核心名称）
        # "泉州新闻综合 88.9" → "泉州新闻综合"，"福建交通广播" → "福建交通广播"
        keyword = _re.sub(r"[\d.\s]", "", name)
        # 提取名称中的频率（"88.9" → "889"，用于精确匹配云听标题中的频率）
        freq_match = _re.search(r"\d{2,3}\.\d", name)
        freq_digits = freq_match.group().replace(".", "") if freq_match else ""
        result = _search(keyword or None, freq_digits)
        if result:
            return result

    # 策略 2：station_id 城市代码兜底（处理前端未传 name 的情况）
    parts = station_id.split("_", 1)
    if len(parts) >= 2:
        city_code = parts[0]
        freq_digits = _re.sub(r"[^0-9]", "", parts[1])
        result = _search(city_code, freq_digits)
        if result:
            return result

    return None


def _find_myradio_url(station_id: str, name: str = "") -> str | None:
    """在 myradio 缓存中按名称匹配电台，返回直连流 URL 或 None。

    使用 _normalize_name 规范化后匹配，解决：
    - "HitFM 台北" vs "Hit FM"（去空格后都是 "hitfm"）
    - "泉州新闻综合 88.9" vs "泉州新闻综合广播"（去后缀后都是 "泉州新闻综合"）
    """
    if station_id.startswith("mr_"):
        return None

    if not name:
        return None

    query = _normalize_name(name)
    if not query:
        return None

    # 规范化后子串匹配（双向，带长度校验，防止短子串误匹配）
    for _key, entry in MYRADIO_CACHE.items():
        cached = _normalize_name(entry.get("name", ""))
        if not cached:
            continue
        if _names_match(query, cached):
            return entry["url"]

    return None


def _infer_rb_region(station_id: str) -> str | None:
    """从 station_id 前缀推断所属地区，用于 RB 匹配时限定国家，防止跨区误匹配。

    mr_* → 'TW'（myradio 只有台湾台）
    yt_* → 'CN'（云听只有大陆台）
    其他 → None（不限制，全量搜索）
    """
    if station_id.startswith("mr_"):
        return "TW"
    if station_id.startswith("yt_"):
        return "CN"
    return None


def _find_rb_url(station_id: str, name: str = "", region: str | None = None) -> str | None:
    """在 Radio Browser 缓存中按名称匹配电台，返回直连流 URL 或 None。

    region: 限定只搜索指定国家的 RB 数据（如 'TW'、'CN'），防止跨区误匹配。
    """

    if station_id.startswith("rb_"):
        return None

    if not name:
        return None

    query = _normalize_name(name)
    if not query:
        return None

    countries = [region] if region else list(RB_CACHE.keys())
    for country in countries:
        cached = RB_CACHE.get(country)
        if not cached:
            continue
        try:
            for item in json.loads(cached["data"]):
                rb_name = _normalize_name(item.get("name") or "")
                if not rb_name:
                    continue
                if _names_match(query, rb_name):
                    url = item.get("url_resolved") or item.get("url") or ""
                    if url.startswith(("http://", "https://")):
                        return url
        except Exception:
            continue

    return None


def _find_fallback_url(station_id: str, name: str = "") -> str | None:
    """统一回退链：云听 → myradio → RB。按顺序尝试，第一个命中即返回。"""
    # yt_* 电台：直接查 YUNTING_URL_CACHE（_find_yunting_url 会跳过 yt_ 前缀）
    if station_id.startswith("yt_"):
        cached = YUNTING_URL_CACHE.get(station_id)
        if cached:
            url = cached.get("url") if isinstance(cached, dict) else cached
            if url:
                return url
    region = _infer_rb_region(station_id)
    for finder in (_find_yunting_url, _find_myradio_url):
        url = finder(station_id, name)
        if url:
            return url
    return _find_rb_url(station_id, name, region=region)


def _collect_all_urls(station_id: str, name: str = "") -> list[str]:
    """收集电台所有可用流 URL（去重），供前端逐个尝试。

    顺序：当前主源 → 云听 → myradio → RB
    """

    urls: list[str] = []
    seen: set[str] = set()

    def _add(url: str | None):
        if url and url not in seen:
            seen.add(url)
            urls.append(url)

    # yt_* 电台：优先用 yunting m3u8（比 CURRENT_STREAMS 里的直连 mp3 更可靠）
    # 有些电台（如畅行876）的直连流被浏览器 Range 头打回 400，但 yunting m3u8 正常
    if station_id.startswith("yt_"):
        cached = YUNTING_URL_CACHE.get(station_id)
        if cached:
            _add(cached.get("url") if isinstance(cached, dict) else cached)

    # 当前主源（fetcher 注册的直连流，可能不如 yunting m3u8 稳定）
    _add(CURRENT_STREAMS.get(station_id))

    # mr_* 电台：MYRADIO_CACHE 里可能还没写入 CURRENT_STREAMS
    if station_id.startswith("mr_"):
        mr = MYRADIO_CACHE.get(station_id)
        if mr:
            _add(mr.get("url"))

    # 云听（非 yt_ 电台的跨源匹配）
    _add(_find_yunting_url(station_id, name))

    # myradio
    _add(_find_myradio_url(station_id, name))

    # Radio Browser（限定地区，防止跨区误匹配）
    region = _infer_rb_region(station_id)
    _add(_find_rb_url(station_id, name, region=region))

    return urls


@app.get("/api/{station_id}/all-urls")
async def get_all_urls(station_id: str, name: str = "", request: Request = None) -> Response:
    """返回电台所有可用流 URL（去重有序），供前端逐个尝试直连。"""
    

    if request and _is_geo_blocked(station_id, request):
        raise HTTPException(status_code=403, detail="该电台因地域限制不可用。")

    urls = _collect_all_urls(station_id, name)
    return Response(
        content=json.dumps(urls, ensure_ascii=False),
        media_type="application/json",
    )


async def _head_check(url: str) -> tuple[str, float]:
    """HEAD 探测单个 URL，返回 (url, 响应时间秒)。失败返回 inf。"""
    t0 = time.monotonic()
    try:
        async with httpx.AsyncClient(verify=False, follow_redirects=True, timeout=5.0) as client:
            resp = await client.head(url, headers=CDN_REQUEST_HEADERS)
            if resp.status_code < 400:
                return (url, time.monotonic() - t0)
    except Exception:
        pass
    return (url, float("inf"))


@app.get("/api/{station_id}/reachable-urls")
async def get_reachable_urls(station_id: str, name: str = "", request: Request = None) -> Response:
    """并行 HEAD 探测所有源 URL，返回按响应速度排序的可达 URL 列表。

    前端拿到后直接按顺序尝试，不可达的 URL 已被过滤，省掉每个 5s 超时。
    """
    

    if request and _is_geo_blocked(station_id, request):
        raise HTTPException(status_code=403, detail="该电台因地域限制不可用。")

    urls = _collect_all_urls(station_id, name)
    if not urls:
        return Response(content="[]", media_type="application/json")

    # 并行 HEAD 探测所有 URL
    results = await asyncio.gather(*[_head_check(u) for u in urls])
    # 过滤不可达（inf），按响应时间排序
    reachable = sorted(
        [(u, t) for u, t in results if t < float("inf")],
        key=lambda x: x[1],
    )
    sorted_urls = [u for u, _ in reachable]

    logger.info("电台 %s 可达性探测: %d/%d 可达, 最快: %s",
                station_id, len(sorted_urls), len(urls),
                sorted_urls[0] if sorted_urls else "无")

    return Response(
        content=json.dumps(sorted_urls, ensure_ascii=False),
        media_type="application/json",
    )



@app.get("/api/{station_id}/stream-url")
async def get_stream_url(station_id: str, name: str = "", request: Request = None) -> Response:
    """返回电台最新播放地址的直链，供前端直连 CDN 播放，节省后端流量。

    前端拿到 URL 后用 HLS.js 直接加载 CDN 的 m3u8，CORS 或加载失败时再回退到后端代理。
    该接口零开销：直接读内存字典，不做任何网络请求。
    name 参数由前端从 stations.js 的 stationMap 中获取并传递，用于云听回退时按名称匹配。
    """

    

    if request and _is_geo_blocked(station_id, request):
        raise HTTPException(status_code=403, detail="该电台因地域限制不可用。")

    url = CURRENT_STREAMS.get(station_id)

    # 内存里没有，尝试立即刷新一次（按需触发 fetcher）
    if url is None:
        fetcher = STATION_FETCHER_MAP.get(station_id)

        # yt_* 云听电台：先查 URL 缓存（proxy_yunting_stations 已预填充），省掉网络请求
        if fetcher is None and station_id.startswith("yt_"):
            cached_url = YUNTING_URL_CACHE.get(station_id)
            if cached_url and time.time() - cached_url["ts"] < YUNTING_URL_TTL:
                url = cached_url["url"]
                CURRENT_STREAMS[station_id] = url
                logger.info("电台 %s 从 URL 缓存命中", station_id)

        # mr_* myradio 电台：直接从 MYRADIO_CACHE 读取（24h TTL，后台预热）
        if fetcher is None and station_id.startswith("mr_"):
            mr_cached = MYRADIO_CACHE.get(station_id)
            if mr_cached and time.time() - mr_cached["ts"] < MYRADIO_CACHE_TTL:
                url = mr_cached["url"]
                CURRENT_STREAMS[station_id] = url
                logger.info("电台 %s 从 myradio 缓存命中", station_id)

        # 缓存未命中：动态创建 fetcher 并注册（自动纳入后台刷新）
        if url is None and fetcher is None and station_id.startswith("yt_"):
            content_id = station_id[3:]
            for prov in YUNTING_PROVINCES:
                STATION_FETCHER_MAP[station_id] = yunting(prov, content_id)
                fetcher = STATION_FETCHER_MAP[station_id]
                break

        if url is None and fetcher is None and not station_id.startswith("mr_"):
            raise HTTPException(status_code=404, detail="未知电台。")
        # mr_* 电台缓存过期或缺失，数据由后台预热任务刷新，返回 503
        if url is None and station_id.startswith("mr_"):
            raise HTTPException(status_code=503, detail="myradio 电台数据正在刷新，请稍后重试。")
        if url is None and fetcher is not None:
            try:
                url = await fetcher()
                CURRENT_STREAMS[station_id] = url
            except Exception as exc:
                logger.warning("电台 %s 主 fetcher 失败: %s，尝试多源回退", station_id, exc)
                fallback_url = _find_fallback_url(station_id, name)
                if fallback_url:
                    logger.info("电台 %s 多源回退成功", station_id)
                    url = fallback_url
                    CURRENT_STREAMS[station_id] = url
                else:
                    logger.exception("电台 %s stream-url 刷新失败（多源均无匹配）", station_id)
                    raise HTTPException(status_code=503, detail="播放地址暂不可用") from exc

    return Response(
        content=json.dumps({"url": url}),
        media_type="application/json",
    )


# Radio Browser 代理缓存，key 是国家代码，缓存 6 小时（电台数据几乎不变）。
RB_CACHE: dict[str, dict] = {}
RB_CACHE_TTL = 6 * 3600


@app.get("/api/radio-browser/stations/{country_code}")
async def proxy_radio_browser(country_code: str) -> Response:
    """反代 Radio Browser API，内存缓存 6 小时。

    大陆无法直连 Radio Browser，通过后端中转可以绕过网络限制。
    缓存命中后零开销，适合每次页面加载都调用。
    """

    cached = RB_CACHE.get(country_code)
    if cached and time.time() - cached["ts"] < RB_CACHE_TTL:
        return Response(content=cached["data"], media_type="application/json")

    url = f"https://all.api.radio-browser.info/json/stations/bycountrycodeexact/{country_code}?order=votes&reverse=true"
    try:
        resp = await http_client.get(url, follow_redirects=True)
        resp.raise_for_status()
    except httpx.HTTPError as exc:
        # 缓存未过期时降级返回旧数据，比报错好
        if cached:
            logger.warning("Radio Browser 拉取失败，返回缓存: %s", exc)
            return Response(content=cached["data"], media_type="application/json")
        raise HTTPException(status_code=502, detail="Radio Browser 请求失败") from exc

    RB_CACHE[country_code] = {"data": resp.text, "ts": time.time()}
    return Response(content=resp.text, media_type="application/json")


# 后端启动时预热 RB 缓存（TW + CN），供 _find_rb_url / _collect_all_urls 匹配用。
# 前端不再拉取 RB 数据（隐藏 RB 电台卡片），但后端仍需 RB 数据作回退源。
_RB_PREFETCH_REGIONS = ["TW", "CN"]


async def _prefetch_rb() -> None:
    """启动时预热 RB 缓存，之后每 6 小时静默刷新。"""
    while True:
        for code in _RB_PREFETCH_REGIONS:
            try:
                url = f"https://all.api.radio-browser.info/json/stations/bycountrycodeexact/{code}?order=votes&reverse=true"
                resp = await http_client.get(url, follow_redirects=True)
                resp.raise_for_status()
                RB_CACHE[code] = {"data": resp.text, "ts": time.time()}
                logger.info("RB %s 预热完成: %d bytes", code, len(resp.text))
            except Exception as exc:
                logger.warning("RB %s 预热失败: %s", code, exc)
        await asyncio.sleep(RB_CACHE_TTL)