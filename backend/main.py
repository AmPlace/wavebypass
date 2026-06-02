import asyncio
import hashlib
import logging
import os
import re
import shutil
import subprocess
import tempfile
import threading
import time
import json
from datetime import datetime, timedelta, timezone
from collections.abc import AsyncIterator
from pathlib import Path
from urllib.parse import quote, urljoin, urlparse
from zoneinfo import ZoneInfo

import httpx
from fastapi import FastAPI, HTTPException, Query, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse, StreamingResponse
from contextlib import asynccontextmanager
from fetchers import STATION_FETCHER_MAP, yunting
import database
from adapters import AdapterResolveError, resolve_adapter_source


TOKEN_REFRESH_INTERVAL_SECONDS = 18_000

M3U8_CACHE_TTL_SECONDS = 3.0


HTTP_TIMEOUT = httpx.Timeout(30.0, connect=10.0)
IPTV_STREAM_READ_TIMEOUT_SECONDS = 12.0
IPTV_STREAM_RECONNECT_DELAY_SECONDS = 0.25
IPTV_STREAM_RECONNECT_MAX_DELAY_SECONDS = 2.0
IPTV_STREAM_NO_DATA_RETRIES = 5
IPTV_STREAM_NO_DATA_TIMEOUT_SECONDS = 45.0
IPTV_STREAM_SHORT_CONNECTION_BYTES = 256 * 1024
IPTV_STREAM_SHORT_CONNECTION_SECONDS = 2.0

# 规避部分Hinet CDN的验证问题
CDN_VERIFY_SSL = False


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
    
    if station_id.startswith("qz_"):
        headers["Referer"] = "https://wxqz2.qztv.cn"
        headers["User-Agent"] = "AppleCoreMedia/1.0.0.23E261 (iPhone; U; CPU OS 26_4_2 like Mac OS X; zh_cn)"
        
    return headers

TOKEN_REFRESH_HTTP_STATUS_CODES = {401, 403, 404, 410}


DIRECT_STREAM_STATIONS = {""}


# ========== 地域限制配置 ==========
GEO_RESTRICT = os.getenv("GEO_RESTRICT", "").strip() == "1"
GEO_BLOCKED_REGIONS = set(
    r.strip() for r in os.getenv("GEO_BLOCKED_REGIONS", "TW").split(",") if r.strip()
)

STATIC_STATIONS = [
    {"id": "hitfm", "name": "Hit FM 台北", "logoText": "H", "logoUrl": "/logos/hitfm.png", "subtitle": "FM 107.7", "tags": ["music", "TW"]},
    {"id": "hitfm_taichung", "name": "Hit FM 台中", "logoText": "台中", "logoUrl": "/logos/hitfm.png", "subtitle": "FM 91.5",  "tags": ["music", "TW"]},
    {"id": "hitfm_tainan", "name": "Hit FM 台南", "logoText": "台南", "logoUrl": "/logos/hitfm.png", "subtitle": "FM 90.1", "tags": ["music", "TW"]},
    {"id": "hitfm_yilan", "name": "Hit FM 宜兰", "logoText": "宜兰", "logoUrl": "/logos/hitfm.png", "subtitle": "FM 97.1", "tags": ["music", "TW"]},
    {"id": "hitfm_huadong", "name": "Hit FM 花东", "logoText": "花东", "logoUrl": "/logos/hitfm.png", "subtitle": "FM 107.7", "tags": ["music", "TW"]},
    {"id": "pop917", "name": "POP Radio", "logoText": "POP", "logoUrl": "/logos/pop917.jpg", "subtitle": "FM 91.7", "tags": ["music", "TW"]},
    {"id": "qz_fm889", "name": "泉州新闻综合", "logoText": "FM889", "logoUrl": "/logos/qz889.png", "subtitle": "FM 88.9", "tags": ["CN", "福建", "news"]},
    {"id": "qz_fm904", "name": "泉州交通广播", "logoText": "FM904", "logoUrl": "/logos/qz904.png", "subtitle": "FM 90.4", "tags": ["CN", "福建", "news"]},
    {"id": "qz_fm1059", "name": "泉州刺桐之声", "logoText": "FM1059", "logoUrl": "/logos/qz1059.png", "subtitle": "FM 105.9", "tags": ["CN", "福建", "talk"]},
    {"id": "qz_fm923", "name": "泉州经济生活", "logoText": "FM923", "logoUrl": "/logos/qz923.png", "subtitle": "FM 92.3", "tags": ["CN", "福建", "news"]},
]

_TW_STATION_IDS = {s["id"] for s in STATIC_STATIONS if "TW" in s.get("tags", [])}


def _is_geo_blocked(station_id: str, request: Request) -> bool:
    if not GEO_RESTRICT or not GEO_BLOCKED_REGIONS:
        return False
    country = request.headers.get("cf-ipcountry", "").upper()
    if country and country != "CN":
        return False  
    is_tw = (
        station_id.startswith("mr_")       
        or station_id in _TW_STATION_IDS    
        or station_id in MYRADIO_CACHE      
    )
    if is_tw and "TW" in GEO_BLOCKED_REGIONS:
        return True
    if not is_tw and "CN" in GEO_BLOCKED_REGIONS:
        return True
    return False


CURRENT_STREAMS: dict[str, str] = {}


M3U8_CACHE: dict[str, dict[str, str | float]] = {}



# 当缓存过期且同一时间有大量请求进来时，锁可以避免所有请求同时打到真实 CDN
M3U8_CACHE_LOCKS: dict[str, asyncio.Lock] = {}


logger = logging.getLogger("wavebypass")



def get_m3u8_cache_lock(cache_key: str) -> asyncio.Lock:
    """获取某个 m3u8 地址专用的微缓存锁

    使用 setdefault 可以在第一次访问某个 m3u8 时创建锁，
    后续同一个缓存键会复用同一把锁
    """

    return M3U8_CACHE_LOCKS.setdefault(cache_key, asyncio.Lock())


def get_cached_m3u8_text(cache_key: str) -> str | None:

    now = time.time()

    cache_item = M3U8_CACHE.get(cache_key)

    if cache_item is None:
        return None

    cached_text = str(cache_item.get("text", ""))

    # 取出缓存写入时间；没有 timestamp 时按 0 处理，会自然判定为过期
    cached_timestamp = float(cache_item.get("timestamp", 0.0))

    if cached_text and now - cached_timestamp < M3U8_CACHE_TTL_SECONDS:
        return cached_text

    return None


def rewrite_m3u8_text(raw_m3u8_text: str, real_m3u8_url: str, station_id: str) -> str:

    rewritten_lines: list[str] = []

    for line in raw_m3u8_text.splitlines():
        stripped_line = line.strip()

        if not stripped_line or stripped_line.startswith("#"):
            rewritten_lines.append(line)
            continue

        parsed_uri = urlparse(stripped_line)

        uri_path = parsed_uri.path.lower()

        absolute_media_url = urljoin(real_m3u8_url, stripped_line)

        encoded_target_url = quote(absolute_media_url, safe="")

        if uri_path.endswith(".m3u8"):
            proxy_playlist_url = f"/api/{station_id}/playlist.m3u8?target_url={encoded_target_url}"
            rewritten_lines.append(proxy_playlist_url)
            continue

        # 非媒体切片资源原样保留，避免误改其他 HLS 标签
        SEGMENT_EXTENSIONS = (".ts", ".aac", ".mp3", ".mp4", ".fmp4", ".m4s")
        if not uri_path.endswith(SEGMENT_EXTENSIONS):
            rewritten_lines.append(line)
            continue

        proxy_ts_url = f"/api/{station_id}/chunk.ts?target_url={encoded_target_url}"

        rewritten_lines.append(proxy_ts_url)

    return "\n".join(rewritten_lines) + "\n"


async def refresh_station_stream_url(station_id: str) -> str:
    """立即刷新单个电台的真实 m3u8 地址
    """

    fetcher = STATION_FETCHER_MAP.get(station_id)

    if fetcher is None:
        raise HTTPException(status_code=404, detail="未知电台。")

    latest_stream_url = await fetcher()

    CURRENT_STREAMS[station_id] = latest_stream_url

    logger.info("电台 %s 播放地址已按需刷新", station_id)

    return latest_stream_url


async def refresh_tokens_task() -> None:

    while True:
        for station_id in STATION_FETCHER_MAP:
            try:

                await refresh_station_stream_url(station_id)

                logger.info("电台 %s 播放地址刷新成功", station_id)
            except Exception:
                logger.exception("电台 %s 播放地址刷新失败", station_id)

        await asyncio.sleep(TOKEN_REFRESH_INTERVAL_SECONDS)


# 全局复用的异步 HTTP 客户端，维持与上游 CDN 的 Keep-Alive 长连接
http_client = httpx.AsyncClient(
    timeout=HTTP_TIMEOUT,
    verify=CDN_VERIFY_SSL,
    limits=httpx.Limits(max_keepalive_connections=50, max_connections=100)
)

yunting_client = httpx.AsyncClient(
    timeout=15.0,
    follow_redirects=True,
    limits=httpx.Limits(max_keepalive_connections=10, max_connections=10),
)


YUNTING_REFRESH_INTERVAL = 1 * 3600

_yunting_sem = asyncio.Semaphore(5)


async def _fetch_one_province(prov: str) -> list[dict] | None:
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
    now = time.time()
    tasks = [_fetch_one_province(prov) for prov in YUNTING_PROVINCES]
    results = await asyncio.gather(*tasks)

    prefetched = 0
    merged: list[dict] = []
    for prov, stations in zip(YUNTING_PROVINCES, results):
        if stations is None:
            cached = YUNTING_CACHE.get(prov)
            if cached:
                merged.extend(json.loads(cached["data"]))
            continue
        _write_yunting_caches(prov, stations, now)
        merged.extend(stations)
        prefetched += 1

    if merged:
        YUNTING_ALL_CACHE["data"] = json.dumps(merged, ensure_ascii=False).encode("utf-8")
        YUNTING_ALL_CACHE["ts"] = now

    logger.info("云听缓存预热完成: %d/%d 个省份成功", prefetched, len(YUNTING_PROVINCES))


async def _yunting_refresh_task() -> None:
    while True:
        await _yunting_warmup()
        await asyncio.sleep(YUNTING_REFRESH_INTERVAL)


RTSP_HLS_ROOT = Path(os.getenv("RTSP_HLS_ROOT") or (Path(tempfile.gettempdir()) / "wavebypass_rtsp_hls"))
RTSP_HLS_SESSIONS: dict[str, dict] = {}
RTSP_HLS_IDLE_TTL = 90
RTSP_HLS_START_TIMEOUT = 18
RTSP_SEGMENT_RE = re.compile(r"^seg_\d+\.ts$")
RTSP_SESSION_ID_RE = re.compile(r"^[0-9a-f]{24}$")


def _ffmpeg_bin() -> str | None:
    configured = os.getenv("FFMPEG_BIN", "").strip()
    if configured:
        return configured
    backend_dir = Path(__file__).resolve().parent
    candidates = [
        backend_dir / "ffmpeg.exe",
        backend_dir / "bin" / "ffmpeg.exe",
        backend_dir / "ffmpeg" / "ffmpeg.exe",
        backend_dir / "ffmpeg" / "bin" / "ffmpeg.exe",
        backend_dir / "ffmpeg",
        backend_dir / "bin" / "ffmpeg",
    ]
    for candidate in candidates:
        if candidate.exists() and candidate.is_file():
            return str(candidate)
    return shutil.which("ffmpeg")


def _rtsp_session_id(target_url: str, custom_ua: str = "", compat: bool = False) -> str:
    mode = "compat" if compat else "copy"
    return hashlib.sha256(f"{target_url}\n{custom_ua}\n{mode}".encode("utf-8")).hexdigest()[:24]


def _validate_rtsp_url(target_url: str) -> None:
    parsed = urlparse(target_url)
    if parsed.scheme.lower() != "rtsp":
        raise HTTPException(status_code=400, detail="target_url 只允许 rtsp 地址。")
    if not parsed.netloc:
        raise HTTPException(status_code=400, detail="无效的 rtsp 地址。")


def _rtsp_proc_returncode(proc) -> int | None:
    if proc is None:
        return None
    poll = getattr(proc, "poll", None)
    if callable(poll):
        return poll()
    return getattr(proc, "returncode", None)


def _delete_rtsp_session_dir(session_id: str, session: dict | None = None) -> None:
    if not RTSP_SESSION_ID_RE.fullmatch(session_id):
        return
    raw_dir = session.get("dir") if session else None
    session_dir = Path(raw_dir) if raw_dir else RTSP_HLS_ROOT / session_id
    try:
        root = RTSP_HLS_ROOT.resolve()
        target = session_dir.resolve()
        if target.parent == root and target.name == session_id:
            shutil.rmtree(target, ignore_errors=True)
    except Exception:
        logger.warning("清理 RTSP 临时目录失败: %s", session_dir, exc_info=True)


def _clear_stale_rtsp_hls_dirs() -> None:
    try:
        RTSP_HLS_ROOT.mkdir(parents=True, exist_ok=True)
        for child in RTSP_HLS_ROOT.iterdir():
            if child.is_dir() and RTSP_SESSION_ID_RE.fullmatch(child.name):
                shutil.rmtree(child, ignore_errors=True)
    except Exception:
        logger.warning("清理旧 RTSP 临时目录失败: %s", RTSP_HLS_ROOT, exc_info=True)


async def _stop_rtsp_session(session_id: str) -> None:
    session = RTSP_HLS_SESSIONS.pop(session_id, None)
    if not session:
        _delete_rtsp_session_dir(session_id)
        return
    proc = session.get("process")
    try:
        if proc and _rtsp_proc_returncode(proc) is None:
            proc.terminate()
            try:
                await asyncio.wait_for(asyncio.to_thread(proc.wait), timeout=5)
            except (asyncio.TimeoutError, subprocess.TimeoutExpired):
                proc.kill()
                await asyncio.to_thread(proc.wait)
    finally:
        _delete_rtsp_session_dir(session_id, session)


async def _rtsp_hls_cleanup_task():
    while True:
        await asyncio.sleep(30)
        now = time.time()
        for session_id, session in list(RTSP_HLS_SESSIONS.items()):
            proc = session.get("process")
            idle = now - float(session.get("last_access", 0))
            if idle > RTSP_HLS_IDLE_TTL or (proc and _rtsp_proc_returncode(proc) is not None):
                await _stop_rtsp_session(session_id)


async def _stop_all_rtsp_sessions():
    for session_id in list(RTSP_HLS_SESSIONS):
        await _stop_rtsp_session(session_id)


def _drain_rtsp_stderr(session_id: str, pipe) -> None:
    if not pipe:
        return
    tail = ""
    try:
        while True:
            chunk = pipe.read(1024)
            if not chunk:
                return
            text = chunk.decode("utf-8", errors="ignore")
            tail = (tail + text)[-1200:]
            session = RTSP_HLS_SESSIONS.get(session_id)
            if session is not None:
                session["stderr_tail"] = tail
    except Exception:
        return
    finally:
        try:
            pipe.close()
        except Exception:
            pass


async def _ensure_rtsp_hls_session(target_url: str, custom_ua: str = "", compat: bool = False) -> tuple[str, Path]:
    _validate_rtsp_url(target_url)
    ffmpeg = _ffmpeg_bin()
    if not ffmpeg:
        raise HTTPException(status_code=503, detail="未找到 ffmpeg，请安装 ffmpeg 或设置 FFMPEG_BIN")

    RTSP_HLS_ROOT.mkdir(parents=True, exist_ok=True)
    session_id = _rtsp_session_id(target_url, custom_ua, compat)
    session_dir = RTSP_HLS_ROOT / session_id
    playlist_path = session_dir / "index.m3u8"
    session = RTSP_HLS_SESSIONS.get(session_id)
    proc = session.get("process") if session else None
    if proc and _rtsp_proc_returncode(proc) is None and playlist_path.exists():
        session["last_access"] = time.time()
        return session_id, playlist_path

    if session:
        await _stop_rtsp_session(session_id)

    _delete_rtsp_session_dir(session_id)
    session_dir.mkdir(parents=True, exist_ok=True)

    headers = []
    if custom_ua:
        headers.extend(["-user_agent", custom_ua])

    video_args = [
        "-c:v", "copy",
    ]
    if compat:
        video_args = [
            "-c:v", "libx264",
            "-preset", "veryfast",
            "-tune", "zerolatency",
            "-profile:v", "baseline",
            "-level", "3.1",
            "-pix_fmt", "yuv420p",
            "-x264-params", "keyint=50:min-keyint=50:scenecut=0",
            "-force_key_frames", "expr:gte(t,n_forced*2)",
        ]

    cmd = [
        ffmpeg,
        "-hide_banner",
        "-loglevel", "warning",
        "-nostdin",
        "-fflags", "+genpts",
        "-rtsp_transport", "tcp",
        *headers,
        "-i", target_url,
        "-map", "0:v:0?",
        "-map", "0:a:0?",
        *video_args,
        "-c:a", "aac",
        "-b:a", "128k",
        "-f", "hls",
        "-hls_time", "2",
        "-hls_list_size", "8",
        "-hls_flags", "delete_segments+append_list+omit_endlist+independent_segments",
        "-hls_segment_filename", str(session_dir / "seg_%05d.ts"),
        "-hls_base_url", f"/api/iptv/proxy/rtsp/segments/{session_id}/",
        str(playlist_path),
    ]

    subprocess_kwargs = {
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.PIPE,
    }
    if os.name == "nt":
        subprocess_kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW

    try:
        proc = subprocess.Popen(cmd, **subprocess_kwargs)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=503, detail=f"ffmpeg 不存在或不可执行: {ffmpeg}") from exc
    except Exception as exc:
        logger.exception("启动 ffmpeg 失败")
        raise HTTPException(status_code=500, detail=f"启动 ffmpeg 失败: {exc}") from exc

    RTSP_HLS_SESSIONS[session_id] = {
        "process": proc,
        "dir": session_dir,
        "last_access": time.time(),
        "target_url": target_url,
        "compat": compat,
        "stderr_tail": "",
    }
    threading.Thread(target=_drain_rtsp_stderr, args=(session_id, proc.stderr), daemon=True).start()

    deadline = time.monotonic() + RTSP_HLS_START_TIMEOUT
    while time.monotonic() < deadline:
        if playlist_path.exists() and list(session_dir.glob("seg_*.ts")):
            RTSP_HLS_SESSIONS[session_id]["last_access"] = time.time()
            return session_id, playlist_path
        if _rtsp_proc_returncode(proc) is not None:
            stderr = RTSP_HLS_SESSIONS.get(session_id, {}).get("stderr_tail", "")
            await _stop_rtsp_session(session_id)
            raise HTTPException(status_code=502, detail=f"ffmpeg RTSP 转 HLS 失败: {stderr or '进程退出'}")
        await asyncio.sleep(0.25)

    stderr = RTSP_HLS_SESSIONS.get(session_id, {}).get("stderr_tail", "")
    await _stop_rtsp_session(session_id)
    raise HTTPException(status_code=504, detail=f"RTSP 转 HLS 起播超时{': ' + stderr[-500:] if stderr else ''}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    await database.initialize()
    _clear_stale_rtsp_hls_dirs()
    asyncio.create_task(refresh_tokens_task())
    asyncio.create_task(_yunting_refresh_task())
    asyncio.create_task(_myradio_refresh_task())
    asyncio.create_task(_epg_refresh_loop())
    asyncio.create_task(_prefetch_rb())
    asyncio.create_task(_rtsp_hls_cleanup_task())
    yield
    await _stop_all_rtsp_sessions()
    await http_client.aclose()
    await yunting_client.aclose()

app = FastAPI(
    title="WaveBypass",
    description="用于聚合电台 m3u8 与 ts 切片代理的后端服务。",
    version="0.1.0",
    lifespan=lifespan, 
)
#跨域
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


def validate_target_url(target_url: str) -> None:
    """校验代理目标 URL 是否只使用 HTTP/HTTPS 协议"""

    parsed_target_url = urlparse(target_url)

    if parsed_target_url.scheme not in {"http", "https"}:
        raise HTTPException(status_code=400, detail="target_url 只允许 http 或 https 地址。")


async def fetch_real_m3u8_text(real_m3u8_url: str, station_id: str) -> httpx.Response:
    """请求真实 CDN m3u8，并返回原始响应对象"""
    
    headers = get_cdn_headers_for_station(station_id)
    
    async with httpx.AsyncClient(
        timeout=HTTP_TIMEOUT,
        follow_redirects=True,
        verify=CDN_VERIFY_SSL,
    ) as client:
        return await client.get(real_m3u8_url, headers=headers)


@app.get("/api/config")
async def get_config(request: Request) -> dict:
    """返回前端需要的运行时配置（地域限制信息）"""
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
    if request and _is_geo_blocked(station_id, request):
        raise HTTPException(status_code=403, detail="该电台因地域限制不可用。")

    if station_id in DIRECT_STREAM_STATIONS:
        raise HTTPException(status_code=400, detail="该电台是直连音频流，请使用 /api/{station_id}/stream。")

    real_m3u8_url = target_url or CURRENT_STREAMS.get(station_id)

    if real_m3u8_url is None:
        raise HTTPException(status_code=503, detail="该电台播放地址尚未准备好，请稍后重试。")

    validate_target_url(real_m3u8_url)


    cache_key = f"{station_id}:{real_m3u8_url}"


    cached_text = get_cached_m3u8_text(cache_key)
    if cached_text is not None:
        return Response(content=cached_text, media_type="application/vnd.apple.mpegurl")

    cache_lock = get_m3u8_cache_lock(cache_key)

    async with cache_lock:
        cached_text = get_cached_m3u8_text(cache_key)
        if cached_text is not None:
            return Response(content=cached_text, media_type="application/vnd.apple.mpegurl")

        try:
            real_response = await fetch_real_m3u8_text(real_m3u8_url, station_id)

            if target_url is None and real_response.status_code in TOKEN_REFRESH_HTTP_STATUS_CODES:
                logger.warning(
                    "电台 %s 顶层 m3u8 返回 %s，准备刷新 token 后重试一次",
                    station_id,
                    real_response.status_code,
                )

                real_m3u8_url = await refresh_station_stream_url(station_id)

                cache_key = f"{station_id}:{real_m3u8_url}"

                real_response = await fetch_real_m3u8_text(real_m3u8_url, station_id)

            real_response.raise_for_status()
        except httpx.HTTPError as exc:
            logger.exception("电台 %s 真实 m3u8 拉取失败：%s", station_id, exc)
            raise HTTPException(status_code=502, detail="真实 m3u8 拉取失败。") from exc

        rewritten_m3u8_text = rewrite_m3u8_text(real_response.text, real_m3u8_url, station_id)

        M3U8_CACHE[cache_key] = {
            "text": rewritten_m3u8_text,
            "timestamp": time.time(),
        }

        return Response(content=rewritten_m3u8_text, media_type="application/vnd.apple.mpegurl")


@app.get("/api/{station_id}/{m3u8_name}.m3u8")
async def get_relative_child_playlist(station_id: str, m3u8_name: str, request: Request) -> Response:
    if _is_geo_blocked(station_id, request):
        raise HTTPException(status_code=403, detail="该电台因地域限制不可用。")

    base_m3u8_url = CURRENT_STREAMS.get(station_id)

    if base_m3u8_url is None:
        raise HTTPException(status_code=503, detail="该电台播放地址尚未准备好，请稍后重试。")

    query_string = request.url.query

    relative_m3u8_path = f"{m3u8_name}.m3u8"

    if query_string:
        relative_m3u8_path = f"{relative_m3u8_path}?{query_string}"

    child_m3u8_url = urljoin(base_m3u8_url, relative_m3u8_path)

    return await get_station_playlist(station_id=station_id, target_url=child_m3u8_url)


@app.get("/api/{station_id}/chunk.ts")
async def proxy_ts_chunk(
    station_id: str,
    target_url: str = Query(..., min_length=1),
    request: Request = None,
) -> StreamingResponse:
    if request and _is_geo_blocked(station_id, request):
        raise HTTPException(status_code=403, detail="该电台因地域限制不可用。")

    validate_target_url(target_url)

    upstream_headers = get_cdn_headers_for_station(station_id)

    upstream_response: httpx.Response | None = None

    try:
        upstream_response = await http_client.get(target_url, follow_redirects=True, headers=upstream_headers)

        upstream_response.raise_for_status()
    except httpx.HTTPError as exc:
        if upstream_response is not None:
            await upstream_response.aclose()
        logger.exception("电台 %s ts 切片代理失败：%s", station_id, exc)
        raise HTTPException(status_code=502, detail="真实 ts 切片拉取失败。") from exc

    async def stream_ts_bytes() -> AsyncIterator[bytes]:
        """逐块读取真实 ts 响应并转发给前端。"""
        try:
            # 每次最多读取 64KB，在吞吐和内存之间取得平衡
            async for chunk in upstream_response.aiter_bytes(chunk_size=64 * 1024):
                if chunk:
                    yield chunk
        finally:
            await upstream_response.aclose()

    # StreamingResponse 会消费上面的异步生成器，实现边下边传
    return StreamingResponse(
        stream_ts_bytes(), 
        media_type="video/MP2T",
        headers={
            "Access-Control-Allow-Origin": "*",
            "Cache-Control": "no-cache", # 避免前端缓存旧切片
        }
    )

@app.get("/api/proxy/stream")
async def proxy_stream(url: str = Query(...)) -> StreamingResponse:

    if not url.startswith(("http://", "https://")):
        raise HTTPException(status_code=400, detail="仅支持 http/https 地址。")

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
async def proxy_direct_audio_stream(station_id: str, request: Request) -> StreamingResponse:
    if request and _is_geo_blocked(station_id, request):
        raise HTTPException(status_code=403, detail="该电台因地域限制不可用。")

    if station_id not in DIRECT_STREAM_STATIONS:
        raise HTTPException(status_code=400, detail="该电台不是直连音频流。")

    real_stream_url = CURRENT_STREAMS.get(station_id)

    if real_stream_url is None:
        real_stream_url = await refresh_station_stream_url(station_id)

    validate_target_url(real_stream_url)


    upstream_response: httpx.Response | None = None

    try:

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
            upstream_req = http_client.build_request("GET", real_stream_url, headers=CDN_REQUEST_HEADERS)
            upstream_response = await http_client.send(upstream_req, stream=True)

        upstream_response.raise_for_status()
    except httpx.HTTPError as exc:
        if upstream_response is not None:
            await upstream_response.aclose()
        logger.exception("电台 %s 直连音频流代理失败：%s", station_id, exc)
        raise HTTPException(status_code=502, detail="真实音频流拉取失败。") from exc

    async def stream_audio_bytes() -> AsyncIterator[bytes]:
        try:
            async for chunk in upstream_response.aiter_bytes(chunk_size=64 * 1024):
                if chunk:
                    yield chunk
        finally:
            await upstream_response.aclose()

    media_type = upstream_response.headers.get("content-type", "audio/mpeg")

    return StreamingResponse(stream_audio_bytes(), media_type=media_type)


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

YUNTING_ALL_CACHE: dict[str, bytes | float] = {}  # {"data": json_bytes, "ts": float}

# 电台列表 2 小时足够，但节目每半小时换一次，EPG 用 10 分钟 TTL
YUNTING_EPG_CACHE: dict[str, dict] = {}   # {"yt_{contentId}": {"subtitle": "...", "ts": ...}}
YUNTING_EPG_TTL = 10 * 60

YUNTING_URL_CACHE: dict[str, dict] = {}   # {"yt_{contentId}": {"url": "...", "ts": ...}}
YUNTING_URL_TTL = 1 * 3600


# ==========================================
# myradio.tw 电台缓存
# ==========================================
MYRADIO_CACHE: dict[str, dict] = {}
MYRADIO_CACHE_TTL = 24 * 3600


async def _myradio_refresh_task() -> None:
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

    
    stations = resp.json().get("data", [])
    for s in stations:
        s.setdefault("provinceCode", province_code)  
        for key in ("playUrlLow", "mp3PlayUrlLow", "mp3PlayUrlHigh"):
            if isinstance(s.get(key), str) and s[key].startswith("http://"):
                s[key] = "https://" + s[key][7:]
    stations_json = json.dumps(stations, ensure_ascii=False)
    YUNTING_CACHE[province_code] = {"data": stations_json, "ts": time.time()}

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
    

    now = time.time()

    # 快速路径：预合并缓存命中，直接返回原始 bytes
    all_cached = YUNTING_ALL_CACHE.get("data")
    all_ts = float(YUNTING_ALL_CACHE.get("ts", 0))
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
    
    now = time.time()
    merged: dict[str, str] = {}

    stale_epg_keys: list[str] = []
    for key, entry in YUNTING_EPG_CACHE.items():
        if now - entry["ts"] < YUNTING_EPG_TTL:
            merged[key.replace("yt_", "")] = entry["subtitle"]
        else:
            stale_epg_keys.append(key)

    need_api_refresh: list[str] = []
    if stale_epg_keys:
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
                        YUNTING_EPG_CACHE[f"yt_{cid}"] = {"subtitle": sub, "ts": now}
        if len(fresh_provs) < len(YUNTING_PROVINCES):
            need_api_refresh = [p for p in YUNTING_PROVINCES if p not in fresh_provs]

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
    s = raw.lower().replace(" ", "")
    s = _re.sub(r"(?<![a-z])fm\d[\d.]*", "", s)
    s = _re.sub(r"[一-鿥]{0,4}(之声|之聲|电台|广播电台|广播|联播网|聯播網)$", "", s)
    s = "".join(_T2S.get(c, c) for c in s)
    return s


def _names_match(query: str, target: str) -> bool:
    if not query or not target:
        return False
    if query == target:
        return True
    shorter, longer = (query, target) if len(query) <= len(target) else (target, query)
    if shorter in longer and len(shorter) >= 4 and len(shorter) * 100 >= len(longer) * 60:
        return True
    return False


def _find_yunting_url(station_id: str, name: str = "") -> str | None:

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
                    if url.startswith("http://"):
                        url = "https://" + url[7:]
                    if url.startswith(("http://", "https://")):
                        return url
            except Exception:
                continue
        return None

    if name:
        keyword = _re.sub(r"[\d.\s]", "", name)
        freq_match = _re.search(r"\d{2,3}\.\d", name)
        freq_digits = freq_match.group().replace(".", "") if freq_match else ""
        result = _search(keyword or None, freq_digits)
        if result:
            return result

    parts = station_id.split("_", 1)
    if len(parts) >= 2:
        city_code = parts[0]
        freq_digits = _re.sub(r"[^0-9]", "", parts[1])
        result = _search(city_code, freq_digits)
        if result:
            return result

    return None


def _find_myradio_url(station_id: str, name: str = "") -> str | None:
    if station_id.startswith("mr_"):
        return None

    if not name:
        return None

    query = _normalize_name(name)
    if not query:
        return None

    for _key, entry in MYRADIO_CACHE.items():
        cached = _normalize_name(entry.get("name", ""))
        if not cached:
            continue
        if _names_match(query, cached):
            return entry["url"]

    return None


def _infer_rb_region(station_id: str) -> str | None:
    if station_id.startswith("mr_"):
        return "TW"
    if station_id.startswith("yt_"):
        return "CN"
    return None


def _find_rb_url(station_id: str, name: str = "", region: str | None = None) -> str | None:
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

    _add(CURRENT_STREAMS.get(station_id))

    # mr_* 电台：MYRADIO_CACHE 里可能还没写入 CURRENT_STREAMS
    if station_id.startswith("mr_"):
        mr = MYRADIO_CACHE.get(station_id)
        if mr:
            url = mr.get("url")
            if isinstance(url, dict):
                url = url.get("hlsurl") or url.get("url")
            _add(url)

    _add(_find_yunting_url(station_id, name))

    _add(_find_myradio_url(station_id, name))

    region = _infer_rb_region(station_id)
    _add(_find_rb_url(station_id, name, region=region))

    return urls


@app.get("/api/{station_id}/all-urls")
async def get_all_urls(station_id: str, name: str = "", request: Request = None) -> Response:

    if request and _is_geo_blocked(station_id, request):
        raise HTTPException(status_code=403, detail="该电台因地域限制不可用。")

    urls = _collect_all_urls(station_id, name)
    return Response(
        content=json.dumps(urls, ensure_ascii=False),
        media_type="application/json",
    )


async def _head_check(url: str) -> tuple[str, float]:
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
    

    if request and _is_geo_blocked(station_id, request):
        raise HTTPException(status_code=403, detail="该电台因地域限制不可用。")

    urls = _collect_all_urls(station_id, name)
    if not urls:
        return Response(content="[]", media_type="application/json")

    results = await asyncio.gather(*[_head_check(u) for u in urls])
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

    

    if request and _is_geo_blocked(station_id, request):
        raise HTTPException(status_code=403, detail="该电台因地域限制不可用。")

    url = CURRENT_STREAMS.get(station_id)

    if url is None:
        fetcher = STATION_FETCHER_MAP.get(station_id)

        if fetcher is None and station_id.startswith("yt_"):
            cached_url = YUNTING_URL_CACHE.get(station_id)
            if cached_url and time.time() - cached_url["ts"] < YUNTING_URL_TTL:
                url = cached_url["url"]
                CURRENT_STREAMS[station_id] = url
                logger.info("电台 %s 从 URL 缓存命中", station_id)

        if fetcher is None and station_id.startswith("mr_"):
            mr_cached = MYRADIO_CACHE.get(station_id)
            if mr_cached and time.time() - mr_cached["ts"] < MYRADIO_CACHE_TTL:
                url = mr_cached["url"]
                CURRENT_STREAMS[station_id] = url
                logger.info("电台 %s 从 myradio 缓存命中", station_id)

        if url is None and fetcher is None and station_id.startswith("yt_"):
            content_id = station_id[3:]
            for prov in YUNTING_PROVINCES:
                STATION_FETCHER_MAP[station_id] = yunting(prov, content_id)
                fetcher = STATION_FETCHER_MAP[station_id]
                break

        if url is None and fetcher is None and not station_id.startswith("mr_"):
            raise HTTPException(status_code=404, detail="未知电台。")
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


RB_CACHE: dict[str, dict] = {}
RB_CACHE_TTL = 6 * 3600


@app.get("/api/radio-browser/stations/{country_code}")
async def proxy_radio_browser(country_code: str) -> Response:

    cached = RB_CACHE.get(country_code)
    if cached and time.time() - cached["ts"] < RB_CACHE_TTL:
        return Response(content=cached["data"], media_type="application/json")

    url = f"https://all.api.radio-browser.info/json/stations/bycountrycodeexact/{country_code}?order=votes&reverse=true"
    try:
        resp = await http_client.get(url, follow_redirects=True)
        resp.raise_for_status()
    except httpx.HTTPError as exc:
        if cached:
            logger.warning("Radio Browser 拉取失败，返回缓存: %s", exc)
            return Response(content=cached["data"], media_type="application/json")
        raise HTTPException(status_code=502, detail="Radio Browser 请求失败") from exc

    RB_CACHE[country_code] = {"data": resp.text, "ts": time.time()}
    return Response(content=resp.text, media_type="application/json")


_RB_PREFETCH_REGIONS = ["TW", "CN"]


async def _prefetch_rb() -> None:
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


_EPG_REFRESH_INTERVAL = 6 * 3600


async def _epg_refresh_loop() -> None:
    while True:
        try:
            await _epg.refresh_epg_sources(http_client)
        except Exception:
            logger.exception("EPG 刷新异常")
        await asyncio.sleep(_EPG_REFRESH_INTERVAL)


# =====================================================================
# IPTV 订阅管理
# =====================================================================

from m3u8_parser import parse_m3u, deduplicate_channels
import database as db

@app.post("/api/iptv/subscriptions")
async def add_subscription(request: Request):
    body = await request.json()
    url = (body.get('url') or '').strip()
    title = (body.get('title') or '').strip()
    custom_ua = (body.get('custom_ua') or '').strip()
    force_proxy = 1 if body.get('force_proxy') else 0
    if not url:
        raise HTTPException(status_code=400, detail="url 不能为空")

    existing = await db.get_subscription_by_url(url)
    if existing:
        raise HTTPException(
            status_code=409,
            detail=f"订阅源已存在: {existing.get('title') or url}",
        )

    # 拉取 M3U8
    headers = {'User-Agent': custom_ua} if custom_ua else {}
    try:
        resp = await http_client.get(url, follow_redirects=True, timeout=15, headers=headers)
        resp.raise_for_status()
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"拉取订阅源失败: {exc}") from exc

    # 解析
    channels = parse_m3u(resp.text)
    if not channels:
        raise HTTPException(status_code=400, detail="未解析到任何频道")

    channels = deduplicate_channels(channels)

    # 自动检测标题
    if not title:
        title = _guess_sub_title(url, channels)

    try:
        sub_id = await db.add_subscription(title=title, url=url, channel_count=len(channels), custom_ua=custom_ua, force_proxy=force_proxy)
    except db.DuplicateSubscriptionError as exc:
        raise HTTPException(status_code=409, detail="订阅源已存在") from exc
    await db.add_channels_bulk(sub_id, channels)

    return {"id": sub_id, "title": title, "url": url, "channel_count": len(channels)}


@app.get("/api/iptv/subscriptions")
async def list_subscriptions():
    return await db.get_subscriptions()


@app.get("/api/iptv/subscriptions/{sub_id}")
async def get_subscription(sub_id: int):
    sub = await db.get_subscription(sub_id)
    if not sub:
        raise HTTPException(status_code=404, detail="订阅不存在")
    return sub


@app.delete("/api/iptv/subscriptions/{sub_id}")
async def delete_subscription(sub_id: int):
    sub = await db.get_subscription(sub_id)
    if not sub:
        raise HTTPException(status_code=404, detail="订阅不存在")
    await db.delete_subscription(sub_id)
    return {"ok": True}


@app.post("/api/iptv/subscriptions/{sub_id}/refresh")
async def refresh_subscription(sub_id: int):
    sub = await db.get_subscription(sub_id)
    if not sub:
        raise HTTPException(status_code=404, detail="订阅不存在")

    headers = {'User-Agent': sub['custom_ua']} if sub.get('custom_ua') else {}
    try:
        resp = await http_client.get(sub['url'], follow_redirects=True, timeout=15, headers=headers)
        resp.raise_for_status()
    except httpx.HTTPError as exc:
        await db.update_subscription(sub_id, valid=0)
        raise HTTPException(status_code=502, detail=f"刷新失败: {exc}") from exc

    channels = parse_m3u(resp.text)
    channels = deduplicate_channels(channels)
    await db.add_channels_bulk(sub_id, channels)
    await db.update_subscription(sub_id, valid=1, channel_count=len(channels))

    return {"channel_count": len(channels)}


# ── 频道 ──

@app.get("/api/iptv/subscriptions/{sub_id}/channels")
async def list_channels(sub_id: int, group: str = '', search: str = ''):
    sub = await db.get_subscription(sub_id)
    if not sub:
        raise HTTPException(status_code=404, detail="订阅不存在")
    channels = await db.get_channels(sub_id, group=group, search=search)
    groups = await db.get_channel_groups(sub_id)
    return {"channels": channels, "groups": groups, "total": len(channels)}


# ── 前端聚合频道列表（跨源去重，每个频道保留所有可用链接）──

async def _get_aggregated_iptv_channels(group: str = '', search: str = '') -> tuple[list[dict], list[str]]:
    # 搜索在 SQL 层过滤（性能好），分组在聚合后过滤（归一化后才准）
    raw = await db.get_aggregated_channels(group='', search=search)

    from m3u8_parser import adapter_provider, clean_channel_display_name, detect_source_type, normalize_channel_name, parse_youtube_video_id, _channel_alias
    from template import channel_template, normalize_group_name

    merged: dict[str, dict] = {}
    for ch in raw:
        key = normalize_channel_name(ch['name'])
        display_name = clean_channel_display_name(ch['name'])
        primary_name = _channel_alias.get_primary(display_name)
        if primary_name and primary_name != display_name:
            display_name = primary_name

        primary = _channel_alias.get_primary(ch['name'])
        tmpl_cat = channel_template.match(primary) or channel_template.match(ch['name'])
        raw_grp = ch['group_name'] or '其他'
        grp = normalize_group_name(tmpl_cat or raw_grp)

        if key not in merged:
            merged[key] = {
                'canonical_key': key,
                'name': display_name,
                'group_name': grp,
                'logo_url': ch['logo_url'],
                'tvg_id': key,
                'tvg_name': ch['tvg_name'],
                'urls': [],
            }
        detected_source_type = detect_source_type(ch['url'])
        stored_source_type = ch.get('source_type')
        source_type = stored_source_type if stored_source_type and stored_source_type != 'hls' else detected_source_type
        youtube_video_id = ch.get('youtube_video_id') or parse_youtube_video_id(ch['url'])
        merged[key]['urls'].append({
            'url': ch['url'],
            'is_working': ch['is_working'],
            'latency_ms': ch['latency_ms'],
            'sub_title': ch.get('sub_title', ''),
            'custom_ua': ch.get('custom_ua', ''),
            'force_proxy': ch.get('force_proxy', 0),
            'source_type': source_type,
            'adapter': adapter_provider(ch['url']),
            'youtube_video_id': youtube_video_id,
            'raw_name': ch['name'],
            'raw_tvg_id': ch.get('tvg_id', ''),
            'raw_tvg_name': ch.get('tvg_name', ''),
            'raw_group': ch.get('group_name', ''),
        })

    # 生成 tvg_id_candidates
    for ch in merged.values():
        raw_ids = list(dict.fromkeys(u['raw_tvg_id'] for u in ch['urls'] if u['raw_tvg_id']))
        raw_names = list(dict.fromkeys(u['raw_tvg_name'] or u['raw_name'] for u in ch['urls'] if u['raw_tvg_name'] or u['raw_name']))
        all_raw = [ch['canonical_key'], ch['tvg_id']] + raw_ids + raw_names + [ch['name']]
        candidates = list(dict.fromkeys(c for c in all_raw if c))
        normalized_candidates = list(dict.fromkeys(normalize_channel_name(c) for c in candidates if c))
        ch['tvg_id_candidates'] = candidates[:20]
        ch['normalized_candidates'] = normalized_candidates[:20]

        # 确保 tvg_name 不为空：优先取 display_name
        if not ch.get('tvg_name'):
            ch['tvg_name'] = ch['name']

    # 合并 EPG 绑定信息
    epg_maps = {}
    try:
        maps = await db.get_all_channel_epg_maps()
        epg_maps = {m['canonical_key']: m for m in maps}
    except Exception:
        pass

    for ch in merged.values():
        em = epg_maps.get(ch['canonical_key'])
        if em:
            ch['epg_source_id'] = em.get('epg_source_id')
            ch['epg_channel_id'] = em.get('epg_channel_id') or ''
            ch['epg_match_type'] = em.get('match_type', '')
            ch['epg_confidence'] = em.get('confidence', 0)
            ch['epg_match_status'] = em.get('match_status', 'unmatched')
            ch['epg_locked'] = bool(em.get('locked'))
        else:
            ch['epg_source_id'] = None
            ch['epg_channel_id'] = ''
            ch['epg_match_type'] = ''
            ch['epg_confidence'] = 0
            ch['epg_match_status'] = 'unmatched'
            ch['epg_locked'] = False

    # 排序：可用优先，然后按延迟
    result = sorted(merged.values(), key=lambda c: (
        0 if any(u['is_working'] == 1 for u in c['urls']) else 1,
        min((u['latency_ms'] for u in c['urls'] if u['is_working'] == 1), default=9999),
    ))

    if group:
        result = [c for c in result if c['group_name'] == group]

    groups = sorted(set(c['group_name'] for c in merged.values()))
    return result, groups


@app.get("/api/iptv/channels")
async def aggregated_channels(group: str = '', search: str = ''):
    result, groups = await _get_aggregated_iptv_channels(group=group, search=search)

    return {"channels": result, "groups": groups, "total": len(result)}


# ── 测速 ──

# 测速进度存储（内存）
_test_progress: dict[int, dict] = {}
_global_test_progress: dict = {}


@app.post("/api/iptv/test-all")
async def test_all_subscriptions():
    """测速所有订阅源的所有频道"""
    subs = await db.get_subscriptions()
    if not subs:
        raise HTTPException(status_code=400, detail="无订阅源")

    total = 0
    all_channels = []
    for sub in subs:
        channels = await db.get_channels(sub['id'])
        all_channels.extend(channels)
        total += len(channels)

    if not total:
        raise HTTPException(status_code=400, detail="无频道可测速")

    await db.reset_channel_statuses_all()
    _global_test_progress.update({"total": total, "tested": 0, "working": 0, "failed": 0})
    logger.info("开始测速: %d 个频道", total)
    asyncio.create_task(_run_speed_test_global(all_channels))
    return {"total": total}


@app.post("/api/iptv/subscriptions/{sub_id}/test-all")
async def test_subscription(sub_id: int):
    """测速单个订阅源的所有频道"""
    sub = await db.get_subscription(sub_id)
    if not sub:
        raise HTTPException(status_code=404, detail="订阅不存在")

    channels = await db.get_channels(sub_id)
    if not channels:
        raise HTTPException(status_code=400, detail="该订阅无频道")

    await db.reset_channel_statuses(sub_id)
    _test_progress[sub_id] = {"total": len(channels), "tested": 0, "working": 0, "failed": 0}
    _global_test_progress.update({"total": len(channels), "tested": 0, "working": 0, "failed": 0})
    logger.info("开始测速订阅 %s: %d 个频道", sub['title'], len(channels))
    asyncio.create_task(_run_speed_test_sub(sub_id, channels))
    return {"total": len(channels)}


async def _run_speed_test_sub(sub_id: int, channels: list[dict]):
    semaphore = asyncio.Semaphore(10)

    async def _limited_test(ch):
        async with semaphore:
            try:
                return ch, await asyncio.wait_for(_test_single_channel(ch), timeout=12)
            except asyncio.TimeoutError:
                return ch, {"working": False, "latency_ms": 0}

    tasks = [_limited_test(ch) for ch in channels]
    for coro in asyncio.as_completed(tasks):
        try:
            ch, result = await coro
            await db.update_channel_status(ch['id'], is_working = 1 if result['working'] is True else (-1 if result['working'] == -1 else 0), latency_ms=result['latency_ms'])
        except Exception as e:
            logger.warning("测速异常: %s", e)
        _test_progress[sub_id]['tested'] += 1
        _global_test_progress['tested'] += 1
        if result.get('working'):
            _test_progress[sub_id]['working'] += 1
            _global_test_progress['working'] += 1
        else:
            _test_progress[sub_id]['failed'] += 1
            _global_test_progress['failed'] += 1
    await db.update_subscription(sub_id, last_tested=datetime.now(timezone.utc).isoformat())


async def _run_speed_test_global(channels: list[dict]):
    semaphore = asyncio.Semaphore(10)

    async def _limited_test(ch):
        async with semaphore:
            try:
                return ch, await asyncio.wait_for(_test_single_channel(ch), timeout=12)
            except asyncio.TimeoutError:
                logger.warning("测速超时: %s", ch.get('name', ch.get('url', ''))[:60])
                return ch, {"working": False, "latency_ms": 0}

    tasks = [_limited_test(ch) for ch in channels]
    for coro in asyncio.as_completed(tasks):
        try:
            ch, result = await coro
            await db.update_channel_status(
                ch['id'],
                is_working = 1 if result['working'] is True else (-1 if result['working'] == -1 else 0),
                latency_ms=result['latency_ms'],
            )
        except Exception as e:
            logger.warning("测速异常: %s", e)
        _global_test_progress['tested'] += 1
        if result.get('working'):
            _global_test_progress['working'] += 1
        else:
            _global_test_progress['failed'] += 1
        tested = _global_test_progress['tested']
        total = _global_test_progress['total']
        if tested % 50 == 0 or tested == total:
            logger.info("测速进度: %d/%d (可用:%d 不可用:%d)", tested, total, _global_test_progress['working'], _global_test_progress['failed'])
    # 测速完成，更新所有订阅的 last_tested
    now = datetime.now(timezone.utc).isoformat()
    subs = await db.get_subscriptions()
    for sub in subs:
        await db.update_subscription(sub['id'], last_tested=now)


@app.get("/api/iptv/test-status")
async def global_test_status():
    return _global_test_progress


async def _test_single_channel(ch: dict) -> dict:
    """测速单个频道：GET URL → 判断是否 M3U8 → HEAD 第一个 TS 分片"""
    url = ch['url']
    custom_ua = ch.get('custom_ua', '')
    headers = {'User-Agent': custom_ua} if custom_ua else {}
    start = time.time()
    from m3u8_parser import detect_source_type

    source_type = ch.get('source_type') if ch.get('source_type') and ch.get('source_type') != 'hls' else detect_source_type(url)
    if source_type == 'adapter':
        try:
            resolved = await resolve_adapter_source(url, http_client)
            url = str(resolved.get('url') or '')
            resolved_headers = resolved.get('headers') if isinstance(resolved.get('headers'), dict) else {}
            headers.update({str(k): str(v) for k, v in resolved_headers.items()})
        except AdapterResolveError:
            return {"working": False, "latency_ms": 0}

    # RTSP/RTMP 暂不支持 HTTP 测速，标记为未测试
    if url.startswith(('rtsp://', 'rtmp://')):
        return {"working": -1, "latency_ms": 0}
    try:
        resp = await http_client.get(url, follow_redirects=True, timeout=8, headers=headers)
        latency = (time.time() - start) * 1000

        content_type = resp.headers.get('content-type', '').lower()
        is_m3u8 = any(t in content_type for t in ('mpegurl', 'm3u8', 'x-mpegurl')) or url.endswith('.m3u8')

        if is_m3u8 and resp.status_code == 200:
            # 解析 M3U8 找第一个 TS 分片
            ts_url = _find_first_ts_url(resp.text, url)
            if ts_url:
                ts_start = time.time()
                ts_resp = await http_client.head(ts_response_url(ts_url), follow_redirects=True, timeout=5, headers=headers)
                ts_latency = (time.time() - ts_start) * 1000
                if ts_resp.status_code < 400:
                    return {"working": True, "latency_ms": round(latency + ts_latency, 1)}
            # M3U8 可达就算可用
            return {"working": True, "latency_ms": round(latency, 1)}

        if resp.status_code < 400:
            return {"working": True, "latency_ms": round(latency, 1)}

        return {"working": False, "latency_ms": 0}
    except Exception:
        return {"working": False, "latency_ms": 0}


def _find_first_ts_url(m3u8_text: str, base_url: str) -> str | None:
    """从 M3U8 文本中找第一个 TS 分片 URL"""
    base = base_url.rsplit('/', 1)[0] + '/'
    for line in m3u8_text.splitlines():
        line = line.strip()
        if line and not line.startswith('#') and (
            '.ts' in line or '.aac' in line or '.mp4' in line or '.fmp4' in line
        ):
            if line.startswith('http'):
                return line
            return base + line
    return None


def ts_response_url(ts_url: str) -> str:
    return ts_url


@app.post("/api/iptv/subscriptions/{sub_id}/test-all")
async def test_all_channels(sub_id: int):
    sub = await db.get_subscription(sub_id)
    if not sub:
        raise HTTPException(status_code=404, detail="订阅不存在")

    channels = await db.get_channels(sub_id)
    if not channels:
        raise HTTPException(status_code=400, detail="无频道可测速")

    # 重置状态
    await db.reset_channel_statuses(sub_id)
    _test_progress[sub_id] = {"total": len(channels), "tested": 0, "working": 0, "failed": 0}

    asyncio.create_task(_run_speed_test(sub_id, channels))
    return {"total": len(channels)}


async def _run_speed_test(sub_id: int, channels: list[dict]):
    semaphore = asyncio.Semaphore(10)

    async def _limited_test(ch):
        async with semaphore:
            return ch, await _test_single_channel(ch)

    tasks = [_limited_test(ch) for ch in channels]
    for coro in asyncio.as_completed(tasks):
        ch, result = await coro
        await db.update_channel_status(
            ch['id'],
            is_working = 1 if result['working'] is True else (-1 if result['working'] == -1 else 0),
            latency_ms=result['latency_ms'],
        )
        prog = _test_progress[sub_id]
        prog['tested'] += 1
        if result['working']:
            prog['working'] += 1
        else:
            prog['failed'] += 1


@app.get("/api/iptv/subscriptions/{sub_id}/test-status")
async def test_status(sub_id: int):
    return _test_progress.get(sub_id, {"total": 0, "tested": 0, "working": 0, "failed": 0})


# ── 播放代理 ──

# 扩展窗口代理：定期拉上游 playlist
_wide_cache: dict[str, dict] = {}
_WIDE_WINDOW = 20  
_WIDE_TTL = 120    
_IPTV_SEGMENT_EXTENSIONS = (".ts", ".m4s", ".mp4", ".m4v", ".aac", ".mp3")


def _drop_wide_cache(cache_key: str) -> None:
    _wide_cache.pop(cache_key, None)
    _wide_cache.pop(cache_key + '_ts', None)


def _iptv_wide_playlist_proxy_path(target_url: str, proxy_ts: int = 0, custom_ua: str = '') -> str:
    ua = f'&custom_ua={quote(custom_ua, safe="")}' if custom_ua else ''
    return f'/api/iptv/proxy/wide.m3u8?proxy_ts={1 if proxy_ts else 0}{ua}&target_url={quote(target_url, safe="")}'


def _iptv_adapter_play_path(target_url: str) -> str:
    # TODO: V2 should prefer source_id-based adapter resolve/play paths over target_url.
    return f'/api/iptv/adapter/play.m3u8?target_url={quote(target_url, safe="")}'


def _iptv_chunk_proxy_path(target_url: str, custom_ua: str = '') -> str:
    ua = f'&custom_ua={quote(custom_ua, safe="")}' if custom_ua else ''
    return f'/api/iptv/proxy/chunk.ts?target_url={quote(target_url, safe="")}{ua}'


def _rewrite_iptv_wide_m3u8_text(raw_m3u8_text: str, base_url: str, proxy_ts: int = 0, custom_ua: str = '') -> str:
    rewritten_lines: list[str] = []

    for line in raw_m3u8_text.splitlines():
        stripped_line = line.strip()
        if not stripped_line or stripped_line.startswith("#"):
            rewritten_lines.append(line)
            continue

        absolute_media_url = urljoin(base_url, stripped_line)
        parsed_url = urlparse(absolute_media_url)
        uri_path = parsed_url.path.lower()

        if uri_path.endswith(".m3u8"):
            rewritten_lines.append(_iptv_wide_playlist_proxy_path(absolute_media_url, proxy_ts, custom_ua))
        elif proxy_ts and parsed_url.scheme == "http" and uri_path.endswith(_IPTV_SEGMENT_EXTENSIONS):
            rewritten_lines.append(_iptv_chunk_proxy_path(absolute_media_url, custom_ua))
        else:
            rewritten_lines.append(absolute_media_url)

    return "\n".join(rewritten_lines)


def _adapter_error_response(exc: AdapterResolveError) -> JSONResponse:
    return JSONResponse(status_code=exc.status_code, content=exc.to_payload())


@app.get("/api/iptv/adapter/resolve")
async def iptv_adapter_resolve(target_url: str = ''):
    try:
        resolved = await resolve_adapter_source(target_url, http_client)
    except AdapterResolveError as exc:
        return _adapter_error_response(exc)

    payload = dict(resolved)
    payload["proxy_url"] = _iptv_adapter_play_path(target_url)
    return payload


@app.get("/api/iptv/adapter/play.m3u8")
async def iptv_adapter_play_m3u8(target_url: str = ''):
    try:
        resolved = await resolve_adapter_source(target_url, http_client)
    except AdapterResolveError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.to_payload()) from exc

    resolved_url = str(resolved.get('url') or '').strip()
    if not resolved_url:
        raise HTTPException(status_code=502, detail="adapter 未返回播放地址")

    source_type = str(resolved.get('source_type') or 'hls').lower()
    headers = resolved.get('headers') if isinstance(resolved.get('headers'), dict) else {}
    custom_ua = str(headers.get('User-Agent') or headers.get('user-agent') or '')

    if source_type == 'hls':
        validate_target_url(resolved_url)
        return await iptv_wide_playlist(target_url=resolved_url, proxy_ts=1, custom_ua=custom_ua)
    if source_type == 'mpegts':
        return RedirectResponse(
            f'/api/iptv/proxy/stream?target_url={quote(resolved_url, safe="")}',
            status_code=307,
        )
    if source_type == 'rtsp':
        return await iptv_proxy_rtsp_playlist(target_url=resolved_url, custom_ua=custom_ua, compat=0)

    raise HTTPException(status_code=502, detail=f"adapter 返回了暂不支持的流类型: {source_type}")


async def _wide_refresher(cache_key: str, target_url: str, custom_ua: str = ''):
    """后台任务：每 2s 拉一次上游，更新分片队列"""
    _h = {'User-Agent': custom_ua} if custom_ua else {}
    while True:
        cache = _wide_cache.get(cache_key)
        last_access = _wide_cache.get(cache_key + '_ts', 0)
        if not cache:
            return
        if time.time() - last_access > _WIDE_TTL:
            _drop_wide_cache(cache_key)
            logger.info("IPTV wide playlist 后台刷新停止: idle %.0fs url=%s", time.time() - last_access, target_url)
            return

        try:
            resp = await http_client.get(target_url, follow_redirects=True, timeout=6, headers=_h)
            resp.raise_for_status()
            playlist_base_url = str(resp.url)
            lines = resp.text.splitlines()

            # 解析 EXTINF + URL 对，同时追踪 MEDIA-SEQUENCE
            segments = []
            target_duration = 6
            media_seq = 0
            i = 0
            while i < len(lines):
                line = lines[i].strip()
                if line.startswith('#EXT-X-TARGETDURATION:'):
                    target_duration = int(line.split(':')[1])
                elif line.startswith('#EXT-X-MEDIA-SEQUENCE:'):
                    media_seq = int(line.split(':')[1])
                elif line.startswith('#EXTINF:'):
                    dur = line.split(':')[1].rstrip(',')
                    url = lines[i + 1].strip() if i + 1 < len(lines) else ''
                    if url and not url.startswith('#'):
                        abs_url = urljoin(playlist_base_url, url)
                        segments.append({'dur': dur, 'url': abs_url, 'seq': media_seq})
                        media_seq += 1
                    i += 1
                i += 1

            cache = _wide_cache.get(cache_key)
            if not cache:
                return
            cache['target_duration'] = target_duration
            seen = cache.get('seen', set())
            for seg in segments:
                if seg['url'] not in seen:
                    cache['queue'].append(seg)
                    seen.add(seg['url'])
            while len(cache['queue']) > _WIDE_WINDOW:
                cache['queue'].popleft()
            cache['seen'] = seen
        except Exception:
            pass
        await asyncio.sleep(2)


@app.post("/api/iptv/proxy/wide/release")
async def release_iptv_wide_playlist(target_url: str = ''):
    if not target_url:
        raise HTTPException(status_code=400, detail="缺少 target_url")

    cache_key = quote(target_url, safe='')
    released = cache_key in _wide_cache or cache_key + '_ts' in _wide_cache
    _drop_wide_cache(cache_key)
    return {"released": released}


@app.get("/api/iptv/proxy/wide.m3u8")
async def iptv_wide_playlist(target_url: str = '', proxy_ts: int = 0, custom_ua: str = '', compat: int = 0):
    if not target_url:
        raise HTTPException(status_code=400, detail="缺少 target_url")

    if urlparse(target_url).scheme.lower() == "rtsp":
        return await iptv_proxy_rtsp_playlist(target_url=target_url, custom_ua=custom_ua, compat=compat)

    _headers = {'User-Agent': custom_ua} if custom_ua else {}

    def _rewrite_ts(seg_url: str) -> str:
        if proxy_ts and urlparse(seg_url).scheme == 'http':
            return _iptv_chunk_proxy_path(seg_url, custom_ua)
        return seg_url

    cache_key = quote(target_url, safe='')
    if cache_key not in _wide_cache:
        # 首次：快速连拉积累分片
        from collections import deque
        queue = deque(maxlen=_WIDE_WINDOW)
        seen = set()
        target_dur = 6

        for attempt in range(4):
            try:
                resp = await http_client.get(target_url, follow_redirects=True, timeout=6, headers=_headers)
                resp.raise_for_status()
                playlist_base_url = str(resp.url)
                lines = resp.text.splitlines()
                media_seq = 0
                i = 0
                while i < len(lines):
                    line = lines[i].strip()
                    if line.startswith('#EXT-X-TARGETDURATION:'):
                        target_dur = int(line.split(':')[1])
                    elif line.startswith('#EXT-X-MEDIA-SEQUENCE:'):
                        media_seq = int(line.split(':')[1])
                    elif line.startswith('#EXTINF:'):
                        dur = line.split(':')[1].rstrip(',')
                        url = lines[i + 1].strip() if i + 1 < len(lines) else ''
                        if url and not url.startswith('#'):
                            abs_url = urljoin(playlist_base_url, url)
                            if abs_url not in seen:
                                queue.append({'dur': dur, 'url': abs_url, 'seq': media_seq})
                                seen.add(abs_url)
                            media_seq += 1
                        i += 1
                    i += 1
            except Exception:
                pass
            if attempt < 3:
                await asyncio.sleep(0.3)

        cache = {
            'queue': queue,
            'seen': seen,
            'target_duration': target_dur,
        }
        _wide_cache[cache_key] = cache
        _wide_cache[cache_key + '_ts'] = time.time()
        asyncio.create_task(_wide_refresher(cache_key, target_url, custom_ua))

        # 返回扩展窗口 playlist
        if queue:
            lines = [
                '#EXTM3U', '#EXT-X-VERSION:3',
                f'#EXT-X-TARGETDURATION:{target_dur}',
                f'#EXT-X-MEDIA-SEQUENCE:{queue[0]["seq"]}',
            ]
            for seg in queue:
                lines.append(f'#EXTINF:{seg["dur"]},')
                lines.append(_rewrite_ts(seg['url']))
            content = '\n'.join(lines)
            return Response(content=content, media_type="application/x-mpegURL",
                headers={'Cache-Control': 'no-cache, no-store, must-revalidate'})
        # 直接转发
        try:
            resp = await http_client.get(target_url, follow_redirects=True, timeout=6, headers=_headers)
            rewritten = _rewrite_iptv_wide_m3u8_text(resp.text, str(resp.url), proxy_ts=proxy_ts, custom_ua=custom_ua)
            return Response(content=rewritten, media_type="application/x-mpegURL")
        except httpx.HTTPError as exc:
            raise HTTPException(status_code=502, detail=f"拉取失败: {exc}") from exc

    # 已存在缓存：返回扩展 playlist
    _wide_cache[cache_key + '_ts'] = time.time()
    cache = _wide_cache[cache_key]
    queue = cache['queue']
    if not queue:
        try:
            resp = await http_client.get(target_url, follow_redirects=True, timeout=6, headers=_headers)
            rewritten = _rewrite_iptv_wide_m3u8_text(resp.text, str(resp.url), proxy_ts=proxy_ts, custom_ua=custom_ua)
            return Response(content=rewritten, media_type="application/x-mpegURL")
        except httpx.HTTPError as exc:
            raise HTTPException(status_code=502, detail=f"拉取失败: {exc}") from exc

    target_dur = cache.get('target_duration', 6)
    lines = [
        '#EXTM3U',
        '#EXT-X-VERSION:3',
        f'#EXT-X-TARGETDURATION:{target_dur}',
        f'#EXT-X-MEDIA-SEQUENCE:{queue[0]["seq"]}',
    ]
    for seg in queue:
        lines.append(f'#EXTINF:{seg["dur"]},')
        lines.append(_rewrite_ts(seg['url']))
    content = '\n'.join(lines)
    return Response(
        content=content,
        media_type="application/x-mpegURL",
        headers={'Cache-Control': 'no-cache, no-store, must-revalidate'},
    )


# ── 旧代理（不变）──

@app.get("/api/iptv/proxy/rtsp.m3u8")
async def iptv_proxy_rtsp_playlist(target_url: str = '', custom_ua: str = '', compat: int = 0):
    if not target_url:
        raise HTTPException(status_code=400, detail="缺少 target_url")

    try:
        session_id, playlist_path = await _ensure_rtsp_hls_session(target_url, custom_ua, compat=bool(compat))
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("RTSP 代理失败")
        raise HTTPException(status_code=500, detail=f"RTSP 代理失败: {exc}") from exc

    session = RTSP_HLS_SESSIONS.get(session_id)
    if session:
        session["last_access"] = time.time()
    return FileResponse(
        playlist_path,
        media_type="application/x-mpegURL",
        headers={"Cache-Control": "no-cache, no-store, must-revalidate"},
    )


@app.get("/api/iptv/proxy/rtsp/segments/{session_id}/{filename}")
async def iptv_proxy_rtsp_segment(session_id: str, filename: str):
    if not re.fullmatch(r"[0-9a-f]{24}", session_id) or not RTSP_SEGMENT_RE.fullmatch(filename):
        raise HTTPException(status_code=400, detail="无效的分片地址")

    session = RTSP_HLS_SESSIONS.get(session_id)
    if session:
        session["last_access"] = time.time()
    segment_path = RTSP_HLS_ROOT / session_id / filename
    if not segment_path.exists():
        raise HTTPException(status_code=404, detail="分片不存在")

    return FileResponse(
        segment_path,
        media_type="video/MP2T",
        headers={"Cache-Control": "no-cache"},
    )


@app.get("/api/iptv/proxy/stream")
async def iptv_proxy_stream(request: Request, target_url: str = '', custom_ua: str = ''):
    if not target_url:
        raise HTTPException(status_code=400, detail="缺少 target_url")

    validate_target_url(target_url)
    parsed = urlparse(target_url)
    upstream_headers = {
        'User-Agent': custom_ua or CDN_REQUEST_HEADERS['User-Agent'],
        'Accept': '*/*',
        'Connection': 'keep-alive',
        'Referer': f'{parsed.scheme}://{parsed.netloc}/',
    }

    stream_timeout = httpx.Timeout(None, connect=10.0, read=IPTV_STREAM_READ_TIMEOUT_SECONDS)
    stream_client = httpx.AsyncClient(
        timeout=stream_timeout,
        follow_redirects=True,
        verify=CDN_VERIFY_SSL,
    )

    async def open_upstream() -> httpx.Response:
        req = stream_client.build_request("GET", target_url, headers=upstream_headers)
        response: httpx.Response | None = None
        try:
            response = await stream_client.send(req, stream=True)
            response.raise_for_status()
        except httpx.HTTPError:
            if response is not None:
                await response.aclose()
            raise

        content_length = response.headers.get("content-length")
        if content_length and content_length.isdigit():
            length = int(content_length)
            if 0 < length < IPTV_STREAM_SHORT_CONNECTION_BYTES:
                logger.warning(
                    "IPTV MPEG-TS 上游 Content-Length 较小: %s bytes url=%s",
                    length,
                    target_url,
                )
        return response

    try:
        initial_upstream = await open_upstream()
    except httpx.HTTPError as exc:
        await stream_client.aclose()
        raise HTTPException(status_code=502, detail=f"拉取直播流失败: {exc}") from exc

    async def stream_bytes() -> AsyncIterator[bytes]:
        upstream: httpx.Response | None = initial_upstream
        no_data_retries = 0
        last_data_at = time.monotonic()

        async def client_disconnected() -> bool:
            return bool(request and await request.is_disconnected())

        async def sleep_unless_disconnected(delay: float) -> bool:
            deadline = time.monotonic() + delay
            while time.monotonic() < deadline:
                if await client_disconnected():
                    return True
                await asyncio.sleep(min(0.25, max(0.0, deadline - time.monotonic())))
            return await client_disconnected()

        try:
            while True:
                if await client_disconnected():
                    break

                opened_at = time.monotonic()
                bytes_this_connection = 0
                close_reason = "eof"

                try:
                    async for chunk in upstream.aiter_bytes(64 * 1024):
                        if await client_disconnected():
                            close_reason = "client disconnected"
                            break
                        if chunk:
                            bytes_this_connection += len(chunk)
                            no_data_retries = 0
                            last_data_at = time.monotonic()
                            yield chunk
                except httpx.ReadTimeout:
                    close_reason = f"read timeout after {IPTV_STREAM_READ_TIMEOUT_SECONDS:.0f}s"
                except httpx.HTTPError as exc:
                    close_reason = f"{type(exc).__name__}: {exc}"
                finally:
                    if upstream is not None:
                        await upstream.aclose()
                        upstream = None

                if await client_disconnected():
                    break

                elapsed = time.monotonic() - opened_at
                if bytes_this_connection < IPTV_STREAM_SHORT_CONNECTION_BYTES and elapsed < IPTV_STREAM_SHORT_CONNECTION_SECONDS:
                    logger.warning(
                        "IPTV MPEG-TS 上游短连接结束: reason=%s bytes=%s elapsed=%.2fs url=%s",
                        close_reason,
                        bytes_this_connection,
                        elapsed,
                        target_url,
                    )
                else:
                    logger.info(
                        "IPTV MPEG-TS 上游连接结束，准备重连: reason=%s bytes=%s elapsed=%.2fs",
                        close_reason,
                        bytes_this_connection,
                        elapsed,
                    )

                if bytes_this_connection == 0:
                    no_data_retries += 1
                    no_data_age = time.monotonic() - last_data_at
                    if no_data_retries >= IPTV_STREAM_NO_DATA_RETRIES or no_data_age > IPTV_STREAM_NO_DATA_TIMEOUT_SECONDS:
                        logger.warning(
                            "IPTV MPEG-TS 上游连续无数据，结束代理流: retries=%s no_data_age=%.2fs url=%s",
                            no_data_retries,
                            no_data_age,
                            target_url,
                        )
                        break

                delay = min(
                    IPTV_STREAM_RECONNECT_DELAY_SECONDS * max(1, no_data_retries),
                    IPTV_STREAM_RECONNECT_MAX_DELAY_SECONDS,
                )
                if await sleep_unless_disconnected(delay):
                    break

                while True:
                    if await client_disconnected():
                        return
                    try:
                        upstream = await open_upstream()
                        break
                    except httpx.HTTPError as exc:
                        no_data_retries += 1
                        no_data_age = time.monotonic() - last_data_at
                        logger.warning(
                            "IPTV MPEG-TS 上游重连失败: retries=%s no_data_age=%.2fs error=%s url=%s",
                            no_data_retries,
                            no_data_age,
                            exc,
                            target_url,
                        )
                        if no_data_retries >= IPTV_STREAM_NO_DATA_RETRIES or no_data_age > IPTV_STREAM_NO_DATA_TIMEOUT_SECONDS:
                            return
                        retry_delay = min(
                            IPTV_STREAM_RECONNECT_DELAY_SECONDS * no_data_retries,
                            IPTV_STREAM_RECONNECT_MAX_DELAY_SECONDS,
                        )
                        if await sleep_unless_disconnected(retry_delay):
                            return
        finally:
            await stream_client.aclose()

    return StreamingResponse(
        stream_bytes(),
        media_type="video/MP2T",
        headers={
            "Cache-Control": "no-cache, no-store, must-revalidate",
            "Access-Control-Allow-Origin": "*",
        },
    )


@app.get("/api/iptv/proxy/playlist.m3u8")
async def iptv_proxy_playlist(target_url: str = '', compat: int = 0):
    if not target_url:
        raise HTTPException(status_code=400, detail="缺少 target_url")

    if urlparse(target_url).scheme.lower() == "rtsp":
        return await iptv_proxy_rtsp_playlist(target_url=target_url, compat=compat)

    try:
        resp = await http_client.get(target_url, follow_redirects=True, timeout=8)
        resp.raise_for_status()
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"拉取 M3U8 失败: {exc}") from exc

    rewritten = rewrite_m3u8_text(resp.text, target_url, 'iptv')
    return Response(
        content=rewritten,
        media_type="application/x-mpegURL",
        headers={"Cache-Control": "no-cache, no-store, must-revalidate"},
    )


@app.get("/api/iptv/proxy/chunk.ts")
async def iptv_proxy_chunk(target_url: str = '', custom_ua: str = ''):
    if not target_url:
        raise HTTPException(status_code=400, detail="缺少 target_url")

    try:
        upstream = await http_client.get(target_url, follow_redirects=True, headers={
            'User-Agent': custom_ua or 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/130.0.0.0 Safari/537.36',
        })
        upstream.raise_for_status()
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"拉取分片失败: {exc}") from exc

    return Response(content=upstream.content, media_type="video/MP2T")


# ── EPG ──

import epg as _epg


@app.post("/api/iptv/epg/sources")
async def add_epg_source(request: Request):
    body = await request.json()
    url = (body.get('url') or '').strip()
    name = (body.get('name') or '').strip() or url
    if not url:
        raise HTTPException(status_code=400, detail="缺少 url")
    try:
        sid = await db.add_epg_source(name, url)
        return {"id": sid, "name": name, "url": url}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@app.get("/api/iptv/epg/sources")
async def list_epg_sources():
    return await db.get_epg_sources()


@app.delete("/api/iptv/epg/sources/{source_id}")
async def delete_epg_source(source_id: int):
    await db.delete_epg_source(source_id)
    return {"ok": True}


@app.post("/api/iptv/epg/refresh")
async def refresh_epg():
    asyncio.create_task(_epg.refresh_epg_sources(http_client))
    return {"ok": True}


def _epg_zoneinfo(tz: str = ''):
    try:
        return ZoneInfo(tz or 'Asia/Shanghai')
    except Exception:
        return timezone(timedelta(hours=8), 'Asia/Shanghai')


def _epg_parse_iso(value: str) -> datetime:
    return datetime.fromisoformat(value.replace('Z', '+00:00')).astimezone(timezone.utc)


def _epg_date_from_query(value: str, tzinfo) -> str:
    if value:
        try:
            return datetime.strptime(value, '%Y-%m-%d').date().isoformat()
        except ValueError:
            pass
    return datetime.now(tzinfo).date().isoformat()


def _epg_day_bounds(date_value: str, tzinfo) -> tuple[str, str]:
    day = datetime.strptime(date_value, '%Y-%m-%d').date()
    start_local = datetime(day.year, day.month, day.day, tzinfo=tzinfo)
    end_local = start_local + timedelta(days=1) - timedelta(microseconds=1)
    return start_local.astimezone(timezone.utc).isoformat(), end_local.astimezone(timezone.utc).isoformat()


def _epg_available_dates(programs: list[dict], tzinfo, center_date: str) -> list[str]:
    center = datetime.strptime(center_date, '%Y-%m-%d').date()
    window_start = center - timedelta(days=7)
    window_end = center + timedelta(days=7)
    dates: set[str] = set()

    for program in programs:
        try:
            start_local = _epg_parse_iso(program['start']).astimezone(tzinfo)
            stop_local = _epg_parse_iso(program['stop']).astimezone(tzinfo) - timedelta(microseconds=1)
        except Exception:
            continue

        current_day = start_local.date()
        last_day = max(current_day, stop_local.date())
        while current_day <= last_day:
            if window_start <= current_day <= window_end:
                dates.add(current_day.isoformat())
            current_day += timedelta(days=1)

    return sorted(dates)


def _epg_nearest_date(requested_date: str, available_dates: list[str]) -> str:
    if not available_dates or requested_date in available_dates:
        return requested_date
    requested = datetime.strptime(requested_date, '%Y-%m-%d').date()
    return min(
        available_dates,
        key=lambda value: abs((datetime.strptime(value, '%Y-%m-%d').date() - requested).days),
    )


@app.get("/api/iptv/epg/programs/{canonical_key}")
async def get_epg_programs(canonical_key: str, date: str = '', tz: str = ''):
    em = await db.get_channel_epg_map(canonical_key)
    if not em or not em.get('epg_channel_id'):
        tzinfo = _epg_zoneinfo(tz)
        return {
            "canonical_key": canonical_key,
            "match_status": em['match_status'] if em else 'unmatched',
            "current": None,
            "next": None,
            "programs": [],
            "date": _epg_date_from_query(date, tzinfo),
            "requested_date": date,
            "tz": str(tzinfo),
            "available_dates": [],
        }

    sid = em['epg_source_id']
    cid = em['epg_channel_id']
    tzinfo = _epg_zoneinfo(tz)
    requested_date = _epg_date_from_query(date, tzinfo)
    now = datetime.now(timezone.utc).isoformat()

    today_local = datetime.now(tzinfo).date()
    window_start_local = datetime(today_local.year, today_local.month, today_local.day, tzinfo=tzinfo) - timedelta(days=7)
    window_end_local = window_start_local + timedelta(days=15) - timedelta(microseconds=1)
    window_programs = await db.get_epg_programs(
        sid,
        cid,
        start_after=window_start_local.astimezone(timezone.utc).isoformat(),
        start_before=window_end_local.astimezone(timezone.utc).isoformat(),
    )
    available_dates = _epg_available_dates(window_programs, tzinfo, today_local.isoformat())
    selected_date = _epg_nearest_date(requested_date, available_dates)
    day_start, day_end = _epg_day_bounds(selected_date, tzinfo)

    programs = await db.get_epg_programs(sid, cid, start_after=day_start, start_before=day_end)
    now_programs = await db.get_epg_programs(
        sid,
        cid,
        start_after=(datetime.now(timezone.utc) - timedelta(hours=12)).isoformat(),
        start_before=(datetime.now(timezone.utc) + timedelta(days=2)).isoformat(),
    )
    current = None
    next_prog = None
    for p in now_programs:
        if p['start'] <= now < p['stop']:
            total = (datetime.fromisoformat(p['stop']) - datetime.fromisoformat(p['start'])).total_seconds()
            elapsed = (datetime.now(timezone.utc) - datetime.fromisoformat(p['start'])).total_seconds()
            current = {
                'title': p['title'],
                'start': p['start'], 'stop': p['stop'],
                'progress': max(0, min(1, elapsed / total)) if total > 0 else 0,
                'remaining_minutes': max(0, int((datetime.fromisoformat(p['stop']) - datetime.now(timezone.utc)).total_seconds() / 60)),
            }
        elif p['start'] > now:
            if not next_prog:
                next_prog = {'title': p['title'], 'start': p['start'], 'stop': p['stop']}

    schedule = [{
        'title': p['title'], 'start': p['start'], 'stop': p['stop'],
        'status': 'current' if (p['start'] <= now < p['stop']) else ('past' if p['stop'] <= now else 'future'),
    } for p in programs]

    return {
        "canonical_key": canonical_key, "epg_source_id": sid, "epg_channel_id": cid,
        "match_status": em.get('match_status', 'unmatched'),
        "current": current, "next": next_prog, "programs": schedule,
        "date": selected_date, "requested_date": requested_date, "tz": str(tzinfo),
        "available_dates": available_dates,
    }


@app.post("/api/iptv/epg/batch-current")
async def batch_current_programs(request: Request):
    body = await request.json()
    keys = body.get('canonical_keys', [])
    if not keys:
        return {}
    return await db.batch_get_current_programs(keys)


@app.put("/api/iptv/epg/bind/{canonical_key}")
async def bind_epg_channel(canonical_key: str, request: Request):
    body = await request.json()
    await db.upsert_channel_epg_map(
        canonical_key,
        epg_source_id=body.get('epg_source_id'),
        epg_channel_id=body.get('epg_channel_id'),
        match_type='manual',
        confidence=100,
        match_status='locked',
        match_detail='{"matched_by":"manual"}',
        locked=1,
    )
    return {"ok": True}


@app.delete("/api/iptv/epg/bind/{canonical_key}")
async def unbind_epg_channel(canonical_key: str):
    await db.upsert_channel_epg_map(
        canonical_key,
        epg_channel_id='',
        match_type='',
        confidence=0,
        match_status='unmatched',
        match_detail='',
        locked=0,
    )
    return {"ok": True}


@app.get("/api/iptv/epg/match-status")
async def epg_match_status():
    maps = await db.get_all_channel_epg_maps()
    return [{"canonical_key": m['canonical_key'], "status": m['match_status'], "epg_channel_id": m.get('epg_channel_id', ''), "confidence": m.get('confidence', 0)} for m in maps]


# ── 订阅导出 ──

IPTV_SUBSCRIPTION_MODES = {"hybrid", "direct", "proxy", "smart"}


def _csv_set(value: str = '') -> set[str]:
    return {item.strip() for item in (value or '').split(',') if item.strip()}


def _truthy_query(value: bool | int | str) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() not in {"0", "false", "no", "off", ""}


def _m3u_attr(value: str = '') -> str:
    return str(value or '').replace('"', "'").replace('\n', ' ').strip()


def _source_type(source: dict) -> str:
    from m3u8_parser import detect_source_type

    declared = source.get('source_type')
    if declared and declared != 'hls':
        return declared
    return detect_source_type(source.get('url', ''))


def _sorted_sources(sources: list[dict]) -> list[dict]:
    return sorted(sources, key=lambda u: (
        0 if u.get('is_working') == 1 else 1 if u.get('is_working') == -1 else 2,
        u.get('latency_ms') or 9999,
    ))


def _is_supported_export_source(source: dict, healthy_only: bool = True) -> bool:
    if not source.get('url'):
        return False
    if healthy_only and source.get('is_working') != 1:
        return False
    return _source_type(source) not in {'youtube', 'unsupported_youtube_url'}

def _request_public_base_url(request: Request) -> str:
    proto = request.headers.get("x-forwarded-proto") or request.url.scheme
    host = request.headers.get("x-forwarded-host") or request.headers.get("host") or request.url.netloc
    return f"{proto}://{host}".rstrip("/")

def _absolute_api_url(request: Request, path: str) -> str:
    return f"{_request_public_base_url(request)}{path}"


def _iptv_proxy_path_for_source(source: dict) -> str:
    url = str(source.get('url') or '').strip()
    custom_ua = str(source.get('custom_ua') or '').strip()
    ua = f'&custom_ua={quote(custom_ua, safe="")}' if custom_ua else ''
    source_type = _source_type(source)
    if source_type == 'adapter':
        return _iptv_adapter_play_path(url)
    if source_type == 'rtsp':
        return f'/api/iptv/proxy/rtsp.m3u8?target_url={quote(url, safe="")}{ua}'
    if source_type == 'mpegts':
        return f'/api/iptv/proxy/stream?target_url={quote(url, safe="")}{ua}'
    return f'/api/iptv/proxy/wide.m3u8?proxy_ts=1{ua}&target_url={quote(url, safe="")}'


def _iptv_proxy_url_for_source(source: dict, request: Request) -> str:
    return _absolute_api_url(request, _iptv_proxy_path_for_source(source))


def _m3u_attrs_for_channel(channel: dict, include_epg: bool, include_logo: bool) -> str:
    attrs = []
    tvg_name = channel.get('tvg_name') or channel.get('name') or ''
    if tvg_name:
        attrs.append(f'tvg-name="{_m3u_attr(tvg_name)}"')
    export_tvg = channel.get('epg_channel_id') or channel.get('tvg_id') or channel.get('canonical_key', '')
    if include_epg and export_tvg:
        attrs.append(f'tvg-id="{_m3u_attr(export_tvg)}"')
    if include_logo and channel.get('logo_url'):
        attrs.append(f'tvg-logo="{_m3u_attr(channel["logo_url"])}"')
    if channel.get('group_name'):
        attrs.append(f'group-title="{_m3u_attr(channel["group_name"])}"')
    return ' '.join(attrs)


def _subscription_urls_for_channel(channel: dict, mode: str, request: Request, healthy_only: bool, include_rtsp: bool) -> list[str]:
    sources = _sorted_sources([
        source for source in channel.get('urls', [])
        if _is_supported_export_source(source, healthy_only=healthy_only)
    ])

    if mode == 'smart':
        if sources:
            return [_absolute_api_url(request, f'/api/iptv/smart/{quote(channel["canonical_key"], safe="")}.m3u8')]
        return []

    if mode == 'direct':
        return [
            source['url'] for source in sources
            if _source_type(source) != 'adapter' and (include_rtsp or _source_type(source) != 'rtsp')
        ]

    if mode == 'proxy':
        return [_iptv_proxy_url_for_source(source, request) for source in sources]

    direct_sources = []
    proxy_only_sources = []
    for source in sources:
        source_type = _source_type(source)
        if source_type in {'adapter', 'rtsp'} or source.get('force_proxy') or source.get('custom_ua'):
            proxy_only_sources.append(source)
        else:
            direct_sources.append(source)

    urls = [source['url'] for source in direct_sources]
    urls.extend(_iptv_proxy_url_for_source(source, request) for source in direct_sources)
    urls.extend(_iptv_proxy_url_for_source(source, request) for source in proxy_only_sources)
    return urls


@app.get("/api/iptv/subscription.m3u")
async def export_iptv_subscription(
    request: Request,
    mode: str = 'hybrid',
    healthy_only: bool = True,
    include_rtsp: bool = False,
    include_epg: bool = True,
    include_logo: bool = True,
    groups: str = '',
):
    mode = (mode or 'hybrid').strip().lower()
    if mode not in IPTV_SUBSCRIPTION_MODES:
        raise HTTPException(status_code=400, detail="无效导出模式")

    channels, _groups = await _get_aggregated_iptv_channels()
    selected_groups = _csv_set(groups)
    if selected_groups:
        channels = [ch for ch in channels if ch.get('group_name') in selected_groups]

    healthy = _truthy_query(healthy_only)
    rtsp = _truthy_query(include_rtsp)
    epg = _truthy_query(include_epg)
    logo = _truthy_query(include_logo)

    lines = ["#EXTM3U"]
    exported = 0
    for channel in channels:
        urls = _subscription_urls_for_channel(channel, mode, request, healthy, rtsp)
        if not urls:
            continue
        attrs = _m3u_attrs_for_channel(channel, include_epg=epg, include_logo=logo)
        for url in urls:
            lines.append(f'#EXTINF:-1 {attrs},{channel["name"]}')
            lines.append(url)
            exported += 1

    if exported == 0:
        raise HTTPException(status_code=404, detail="无可导出的频道")

    content = '\n'.join(lines)
    return Response(
        content=content,
        media_type="audio/x-mpegurl",
        headers={"Content-Disposition": f'attachment; filename="waveflow_{mode}.m3u"'},
    )


@app.get("/api/iptv/smart/{canonical_key}.m3u8")
async def iptv_smart_playlist(canonical_key: str, request: Request):
    channels, _groups = await _get_aggregated_iptv_channels()
    channel = next((ch for ch in channels if ch.get('canonical_key') == canonical_key), None)
    if not channel:
        raise HTTPException(status_code=404, detail="频道不存在")

    sources = _sorted_sources([
        source for source in channel.get('urls', [])
        if _is_supported_export_source(source, healthy_only=True)
    ])
    for source in sources:
        source_type = _source_type(source)
        try:
            if source_type == 'rtsp':
                return await iptv_proxy_rtsp_playlist(
                    target_url=source['url'],
                    custom_ua=source.get('custom_ua', ''),
                    compat=0,
                )
            if source_type == 'mpegts':
                return RedirectResponse(_iptv_proxy_url_for_source(source, request), status_code=307)
            if source_type == 'adapter':
                return RedirectResponse(_iptv_proxy_url_for_source(source, request), status_code=307)
            return await iptv_wide_playlist(
                target_url=source['url'],
                proxy_ts=1,
                custom_ua=source.get('custom_ua', ''),
                compat=0,
            )
        except HTTPException:
            continue

    raise HTTPException(status_code=503, detail="没有可用播放源")


# ── 工具函数 ──

def _guess_sub_title(url: str, channels: list[dict]) -> str:
    """从 URL 或频道分组推测订阅源标题"""
    # 尝试从分组名推断
    groups = set(ch.get('group_name', '') for ch in channels if ch.get('group_name'))
    if groups:
        return ' / '.join(sorted(groups)[:3])

    # 从 URL 文件名推断
    parsed = urlparse(url)
    path = parsed.path.rstrip('/')
    if path:
        name = path.split('/')[-1]
        name = name.replace('.m3u', '').replace('.m3u8', '').replace('.txt', '')
        if name:
            return name

    return parsed.netloc or '未知订阅源'
