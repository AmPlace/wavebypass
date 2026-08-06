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
from fastapi import Depends, FastAPI, HTTPException, Query, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse, StreamingResponse
from pydantic import BaseModel, ConfigDict, StrictBool, StrictInt, model_validator
from contextlib import asynccontextmanager
from fetchers import STATION_FETCHER_MAP, yunting
import database
import epg_read_resolver
from adapters import (
    AdapterResolveError,
    adapter_capabilities_map,
    adapter_supports,
    parse_adapter_url,
    resolve_adapter_source,
)
from iptv_probe import probe_channel_source
from media_tools import media_tool_bin
from automation import (
    AutomationBusy,
    AutomationConfigurationError,
    AutomationOwnershipLostError,
    AutomationRequestError,
    AutomationRunRequest,
    AutomationRunResult,
    AutomationTaskNotFoundError,
)
from market_tasks import (
    MARKET_MAXIMUM_INTERVAL_SECONDS,
    MARKET_MINIMUM_INTERVAL_SECONDS,
    MARKET_TASK_ID,
    create_market_automation_service,
)
from ssrf_guard import UnsafeTargetError, assert_safe_target_url, assert_safe_host_ips
from core.config import get_settings
from core.settings_service import get_effective_settings
from routers.auth import router as auth_router
from routers.media_credentials import router as media_credentials_router
from routers.media_proxy import router as media_proxy_router
from routers.settings import router as settings_router
from routers.setup import router as setup_router
from security.dependencies import require_admin, require_browse_access, require_media_access, resolve_media_access
from security.source_ids import source_id_for


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


def _env_int(name: str, default: int, minimum: int = 1) -> int:
    try:
        return max(minimum, int(os.getenv(name, "") or default))
    except ValueError:
        return default


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


# RFC 8216: ``EXT-X-DISCONTINUITY-SEQUENCE`` 是 playlist 级别（出现在头部一次），
# 不是 per-segment。从 prefix tag 列表里挪走，作为 meta 处理（_HLS_META_TAGS）。

# 直连而不走 HLS 处理的电台 ID 集合。空字符串元素是历史遗留，没有任何匹配语义，
# 留着只会让代码读起来怪。这里替换成真正的空集合，需要新增直连电台时再 union。
DIRECT_STREAM_STATIONS: set[str] = set()


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
    # ── 香港电台 (tingfm.com) ──
    {"id": "tf_909", "name": "香港电台第一台", "logoText": "RTHK1", "logoUrl": "https://cdn.tingfm.com/tingfm/2013/04/file5e8d6ff30254e.png?x-oss-process=image/resize,m_fill,w_200,h_200", "subtitle": "RTHK Radio 1", "tags": ["HK", "news"]},
    {"id": "tf_910", "name": "香港电台第二台", "logoText": "RTHK2", "logoUrl": "", "subtitle": "RTHK Radio 2", "tags": ["HK", "music"]},
    {"id": "tf_911", "name": "香港电台第三台", "logoText": "RTHK3", "logoUrl": "", "subtitle": "RTHK Radio 3", "tags": ["HK", "news"]},
    {"id": "tf_1071", "name": "香港电台第四台", "logoText": "RTHK4", "logoUrl": "https://cdn.tingfm.com/tingfm/2020/02/file5e467a134a163.jpg", "subtitle": "RTHK Radio 4", "tags": ["HK", "music"]},
    {"id": "tf_913", "name": "香港电台第五台", "logoText": "RTHK5", "logoUrl": "", "subtitle": "RTHK Radio 5", "tags": ["HK", "news"]},
    {"id": "tf_669", "name": "香港之声", "logoText": "之声", "logoUrl": "https://cdn.tingfm.com/tingfm/img/l/9/67829.v5.png?x-oss-process=image/resize,m_fill,w_200,h_200", "subtitle": "RTHK Radio 6", "tags": ["HK", "news"]},
    {"id": "tf_9855", "name": "香港电台普通话台", "logoText": "普通话", "logoUrl": "", "subtitle": "RTHK Putonghua", "tags": ["HK", "news"]},
    {"id": "tf_743", "name": "新城财经台", "logoText": "新城", "logoUrl": "https://cdn.tingfm.com/tingfm/2023/02/oss-63fcd98d4df88.png?x-oss-process=image/resize,m_fill,w_200,h_200", "subtitle": "FM 102.4-106.3", "tags": ["HK", "news"]},
    {"id": "tf_744", "name": "新城知讯台", "logoText": "知讯", "logoUrl": "", "subtitle": "FM 99.7-102.1", "tags": ["HK", "news"]},
    {"id": "tf_748", "name": "新城 Metro Plus", "logoText": "Metro", "logoUrl": "", "subtitle": "Metro Plus", "tags": ["HK", "music"]},
    {"id": "tf_745", "name": "华语 HITS 香港", "logoText": "HITS", "logoUrl": "https://cdn.tingfm.com/tingfm/2023/02/oss-63e7081b5ade4.jpg?x-oss-process=image/resize,m_fill,w_200,h_200", "subtitle": "Chinese HITS", "tags": ["HK", "music"]},
    {"id": "tf_747", "name": "香港数码台", "logoText": "DRK", "logoUrl": "https://cdn.tingfm.com/tingfm/2023/02/oss-63e70606b73a7.png?x-oss-process=image/resize,m_fill,w_200,h_200", "subtitle": "Digital Radio HK", "tags": ["HK", "news"]},
    {"id": "tf_750", "name": "香港D100 PBS", "logoText": "D100", "logoUrl": "https://cdn.tingfm.com/tingfm/2020/10/file5f766022d365b.jpg", "subtitle": "D100", "tags": ["HK", "talk"]},
    {"id": "tf_21365", "name": "凤凰卫视资讯台", "logoText": "凤凰", "logoUrl": "", "subtitle": "Phoenix InfoNews", "tags": ["HK", "news"]},
    {"id": "tf_21300", "name": "凤凰卫视中文台", "logoText": "凤凰", "logoUrl": "", "subtitle": "Phoenix Chinese", "tags": ["HK", "news"]},
    # ── 新加坡电台 (tingfm.com) ──
    {"id": "tfsg_14467", "name": "963好FM", "logoText": "963", "logoUrl": "https://cdn.tingfm.com/tingfm/img/l/5/10489.v5.png?x-oss-process=image/resize,m_fill,w_200,h_200", "subtitle": "96.3 FM", "tags": ["SG", "music"]},
    {"id": "tfsg_14773", "name": "88.3Jia FM", "logoText": "88.3", "logoUrl": "https://cdn.tingfm.com/tingfm/img/l/1/10376.v5.png?x-oss-process=image/resize,m_fill,w_200,h_200", "subtitle": "88.3 FM", "tags": ["SG", "music"]},
    {"id": "tfsg_14775", "name": "Money FM 89.3", "logoText": "Money", "logoUrl": "https://cdn.tingfm.com/tingfm/img/l/5/10341.v5.png?x-oss-process=image/resize,m_fill,w_200,h_200", "subtitle": "89.3 FM", "tags": ["SG", "news"]},
    {"id": "tfsg_14786", "name": "Ria 89.7 FM", "logoText": "Ria", "logoUrl": "", "subtitle": "89.7 FM", "tags": ["SG", "music"]},
    {"id": "tfsg_14787", "name": "Gold 905", "logoText": "Gold", "logoUrl": "", "subtitle": "90.5 FM", "tags": ["SG", "music"]},
    {"id": "tfsg_14788", "name": "ONE FM 91.3", "logoText": "ONE", "logoUrl": "https://cdn.tingfm.com/tingfm/img/l/5/10342.v5.png?x-oss-process=image/resize,m_fill,w_200,h_200", "subtitle": "91.3 FM", "tags": ["SG", "music"]},
    {"id": "tfsg_14790", "name": "Symphony 924", "logoText": "Sym", "logoUrl": "https://cdn.tingfm.com/tingfm/img/l/1/10377.v5.png?x-oss-process=image/resize,m_fill,w_200,h_200", "subtitle": "92.4 FM", "tags": ["SG", "music"]},
    {"id": "tfsg_14791", "name": "CNA938", "logoText": "CNA", "logoUrl": "", "subtitle": "93.8 FM", "tags": ["SG", "news"]},
    {"id": "tfsg_14792", "name": "Warna 942", "logoText": "Warna", "logoUrl": "", "subtitle": "94.2 FM", "tags": ["SG", "news"]},
    {"id": "tfsg_14793", "name": "Class 95", "logoText": "95", "logoUrl": "", "subtitle": "95 FM", "tags": ["SG", "music"]},
    {"id": "tfsg_14794", "name": "Capital 958", "logoText": "958", "logoUrl": "https://cdn.tingfm.com/tingfm/img/l/1/10378.v5.png?x-oss-process=image/resize,m_fill,w_200,h_200", "subtitle": "95.8 FM", "tags": ["SG", "news"]},
    {"id": "tfsg_14795", "name": "Oli 968", "logoText": "Oli", "logoUrl": "", "subtitle": "96.8 FM", "tags": ["SG", "music"]},
    {"id": "tfsg_14796", "name": "Love 972", "logoText": "972", "logoUrl": "https://cdn.tingfm.com/tingfm/img/l/1/10379.v5.png?x-oss-process=image/resize,m_fill,w_200,h_200", "subtitle": "97.2 FM", "tags": ["SG", "music"]},
    {"id": "tfsg_14797", "name": "987 Hit Music", "logoText": "987", "logoUrl": "", "subtitle": "98.7 FM", "tags": ["SG", "music"]},
    {"id": "tfsg_24099", "name": "UFM 100.3", "logoText": "UFM", "logoUrl": "https://cdn.tingfm.com/tingfm/img/l/5/10343.v5.png?x-oss-process=image/resize,m_fill,w_200,h_200", "subtitle": "100.3 FM", "tags": ["SG", "music"]},
    {"id": "tfsg_14271", "name": "YES 933", "logoText": "YES", "logoUrl": "https://cdn.tingfm.com/tingfm/img/l/5/10344.v5.png?x-oss-process=image/resize,m_fill,w_200,h_200", "subtitle": "93.3 FM", "tags": ["SG", "music"]},
    {"id": "tfsg_63656", "name": "Kiss 92", "logoText": "Kiss", "logoUrl": "https://cdn.tingfm.com/tingfm/img/l/8/15248.v7.png?x-oss-process=image/resize,m_fill,w_200,h_200", "subtitle": "92 FM", "tags": ["SG", "music"]},
    {"id": "tfsg_63610", "name": "Class 95 FM", "logoText": "95", "logoUrl": "", "subtitle": "95 FM", "tags": ["SG", "music"]},
    {"id": "tfsg_22537", "name": "Oli 96.8 FM", "logoText": "Oli", "logoUrl": "", "subtitle": "96.8 FM", "tags": ["SG", "music"]},
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


logger = logging.getLogger("waveflow")



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


# NOTE: 旧 ``rewrite_m3u8_text`` 已被 ``core.m3u8_rewriter.rewrite_m3u8`` 取代，
# 通过 signed handle 屏蔽上游 URL，并把 access_token 透传到子 playlist/分片。
# 旧的电台 raw-url 公共入口已删除，
# 客户端统一使用 ``/api/media/channel/{station_id}/playlist.m3u8``。


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

# 云听 API 鉴权
_YUNTING_SIGN_KEY = "f0fc4c668392f9f9a447e48584c214ee"

def _yunting_sign_headers(params: dict | None = None) -> dict:
    """生成云听 API 鉴权 headers"""
    ts = str(int(time.time() * 1000))
    sorted_params = "&".join(f"{k}={v}" for k, v in sorted((params or {}).items()))
    if params:
        sign_text = sorted_params + "&timestamp=" + ts + "&key=" + _YUNTING_SIGN_KEY
    else:
        sign_text = "timestamp=" + ts + "&key=" + _YUNTING_SIGN_KEY
    sign = hashlib.md5(sign_text.encode()).hexdigest().upper()
    return {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
        "Accept": "application/json",
        "Content-Type": "application/json",
        "Origin": "https://www.radio.cn",
        "Referer": "https://www.radio.cn/",
        "equipmentId": "0000",
        "platformCode": "WEB",
        "timestamp": ts,
        "sign": sign,
    }


YUNTING_REFRESH_INTERVAL = 1 * 3600

_yunting_sem = asyncio.Semaphore(5)


async def _fetch_one_province(prov: str) -> list[dict] | None:
    try:
        params = {"categoryId": 0, "provinceCode": prov}
        async with _yunting_sem:
            resp = await yunting_client.get(
                YUNTING_API_BASE,
                params=params,
                headers=_yunting_sign_headers(params),
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


RTSP_HLS_ROOT = Path(os.getenv("RTSP_HLS_ROOT") or (Path(tempfile.gettempdir()) / "waveflow_rtsp_hls"))
RTSP_HLS_SESSIONS: dict[str, dict] = {}
RTSP_HLS_IDLE_TTL = 90
RTSP_HLS_START_TIMEOUT = 18
RTSP_HLS_SEGMENT_SECONDS = _env_int("RTSP_HLS_SEGMENT_SECONDS", 2)
RTSP_HLS_LIST_SIZE = _env_int("RTSP_HLS_LIST_SIZE", 15, minimum=3)
RTSP_HLS_START_SEGMENTS = _env_int("RTSP_HLS_START_SEGMENTS", 2, minimum=1)
RTSP_HLS_DELETE_THRESHOLD = _env_int("RTSP_HLS_DELETE_THRESHOLD", 4, minimum=1)
RTSP_SEGMENT_RE = re.compile(r"^seg_\d+\.ts$")
RTSP_SESSION_ID_RE = re.compile(r"^[0-9a-f]{24}$")


def _ffmpeg_bin() -> str | None:
    ffmpeg = media_tool_bin("ffmpeg")
    if ffmpeg:
        logger.info("ffmpeg found at: %s", ffmpeg)
    else:
        logger.warning("ffmpeg NOT FOUND")
    return ffmpeg


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
    hls_flags = "delete_segments+append_list+omit_endlist"
    if compat:
        hls_flags += "+independent_segments"

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
        "-hls_time", str(RTSP_HLS_SEGMENT_SECONDS),
        "-hls_list_size", str(RTSP_HLS_LIST_SIZE),
        "-hls_delete_threshold", str(RTSP_HLS_DELETE_THRESHOLD),
        "-hls_flags", hls_flags,
        "-hls_segment_filename", str(session_dir / "seg_%05d.ts"),
        "-hls_base_url", f"/api/media/proxy/rtsp-segments/{session_id}/",
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
        if playlist_path.exists() and len(list(session_dir.glob("seg_*.ts"))) >= RTSP_HLS_START_SEGMENTS:
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


_TINGFM_STREAMS = {
    "tf_909": "https://rthkradio1-live.akamaized.net/hls/live/2035313/radio1/master.m3u8",
    "tf_910": "https://rthkradio2-live.akamaized.net/hls/live/2040078/radio2/master.m3u8",
    "tf_911": "https://rthkradio3-live.akamaized.net/hls/live/2040079/radio3/master.m3u8",
    "tf_1071": "https://rthkradio4-live.akamaized.net/hls/live/2040080/radio4/master.m3u8",
    "tf_913": "https://rthkradio5-live.akamaized.net/hls/live/2040081/radio5/master.m3u8",
    "tf_669": "https://rthkradiocnrhk-live.akamaized.net/hls/live/2046111/radiocnrhk/master.m3u8",
    "tf_9855": "https://rthkradiopth-live.akamaized.net/hls/live/2040082/radiopth/master.m3u8",
    "tf_743": "https://1716664847.rsc.cdn77.org/1716664847/index.m3u8",
    "tf_744": "https://1603884249.rsc.cdn77.org/1603884249/index.m3u8",
    "tf_748": "https://1946218710.rsc.cdn77.org/1946218710/index.m3u8",
    "tf_745": "https://streaming.live365.com/a57743",
    "tf_747": "http://ice.digitalradiohk.net:8000/drhk",
    "tf_750": "https://uk.d100.net:8001/Channel1-128MP3",
    "tf_21365": "https://playtv-live.ifeng.com/live/06OLEEWQKN4_audio.m3u8",
    "tf_21300": "https://playtv-live.ifeng.com/live/06OLEGEGM4G_audio.m3u8",
    # ── 新加坡 ──
    "tfsg_14467": "https://playerservices.streamtheworld.com/api/livestream-redirect/963HITAAC_SC",
    "tfsg_14773": "https://playerservices.streamtheworld.com/api/livestream-redirect/883JIAAAC_SC",
    "tfsg_14775": "https://playerservices.streamtheworld.com/api/livestream-redirect/MONEY893AAC_SC",
    "tfsg_14786": "https://playerservices.streamtheworld.com/api/livestream-redirect/RIA897AAC_SC",
    "tfsg_14787": "https://playerservices.streamtheworld.com/api/livestream-redirect/GOLD905AAC_SC",
    "tfsg_14788": "https://playerservices.streamtheworld.com/api/livestream-redirect/ONE913AAC_SC",
    "tfsg_14790": "https://playerservices.streamtheworld.com/api/livestream-redirect/SYMPHONY924AAC_SC",
    "tfsg_14791": "https://playerservices.streamtheworld.com/api/livestream-redirect/938NOWAAC_SC",
    "tfsg_14792": "https://playerservices.streamtheworld.com/api/livestream-redirect/WARNA942AAC_SC",
    "tfsg_14793": "https://playerservices.streamtheworld.com/api/livestream-redirect/CLASS95AAC_SC",
    "tfsg_14794": "https://playerservices.streamtheworld.com/api/livestream-redirect/CAPITAL958AAC_SC",
    "tfsg_14795": "https://playerservices.streamtheworld.com/api/livestream-redirect/OLI968AAC_SC",
    "tfsg_14796": "https://playerservices.streamtheworld.com/api/livestream-redirect/LOVE972AAC_SC",
    "tfsg_14797": "https://playerservices.streamtheworld.com/api/livestream-redirect/987FMAAC_SC",
    "tfsg_24099": "https://playerservices.streamtheworld.com/api/livestream-redirect/UFM1003AAC_SC",
    "tfsg_14271": "https://playerservices.streamtheworld.com/api/livestream-redirect/YES933AAC_SC",
    "tfsg_63656": "https://playerservices.streamtheworld.com/api/livestream-redirect/KISS_92AAC_SC",
    "tfsg_63610": "https://playerservices.streamtheworld.com/api/livestream-redirect/CLASS95AAC_SC",
    "tfsg_22537": "https://playerservices.streamtheworld.com/api/livestream-redirect/OLI968AAC_SC",
}


def _load_tingfm_streams():
    """加载 tingfm HK 电台流地址到 CURRENT_STREAMS"""
    for station_id, url in _TINGFM_STREAMS.items():
        CURRENT_STREAMS[station_id] = url
    logger.info("tingfm HK 电台加载完成: %d 个", len(_TINGFM_STREAMS))


@asynccontextmanager
async def lifespan(app: FastAPI):
    automation_service = None
    app.state.automation_service = None
    try:
        await database.initialize()
        automation_service = create_market_automation_service()
        app.state.automation_service = automation_service
        await automation_service.start()
        _clear_stale_rtsp_hls_dirs()
        asyncio.create_task(refresh_tokens_task())
        asyncio.create_task(_yunting_refresh_task())
        asyncio.create_task(_myradio_refresh_task())
        asyncio.create_task(_epg_refresh_loop())
        asyncio.create_task(_prefetch_rb())
        asyncio.create_task(_rtsp_hls_cleanup_task())
        # logo 模板：本地兜底已在 import 时加载完成，这里启动后异步拉一次远程覆盖；
        # 拉失败就维持本地，按用户要求不重试。后续接入设置页后再做定时刷新 / 手动刷新。
        asyncio.create_task(refresh_logo_template_from_remote(http_client))
        # 加载 tingfm HK 电台流地址
        _load_tingfm_streams()
        yield
    finally:
        try:
            if automation_service is not None:
                await automation_service.stop()
        finally:
            app.state.automation_service = None
            await _stop_all_rtsp_sessions()
            await http_client.aclose()
            await yunting_client.aclose()

app = FastAPI(
    title="WaveFlow",
    description="用于聚合电台 m3u8 与 ts 切片代理的后端服务。",
    version="0.1.0",
    lifespan=lifespan, 
    docs_url=None if get_settings().production else "/docs",
    redoc_url=None if get_settings().production else "/redoc",
    openapi_url=None if get_settings().production else "/openapi.json",
)
#跨域
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(setup_router)
app.include_router(auth_router)
app.include_router(media_credentials_router)
app.include_router(media_proxy_router)
app.include_router(settings_router)


@app.get("/health")
async def health():
    return {"status": "ok"}


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
    settings = await get_effective_settings()
    base = {
        "mode": settings.mode,
        "anonymousBrowse": settings.anonymous_browse,
        "anonymousPlayback": settings.anonymous_playback,
        "production": settings.production,
    }
    if not GEO_RESTRICT:
        return {**base, "geoRestrict": False}
    country = request.headers.get("cf-ipcountry", "").upper()
    if country and country != "CN":
        return {**base, "geoRestrict": False}
    return {
        **base,
        "geoRestrict": True,
        "blockedRegions": sorted(GEO_BLOCKED_REGIONS),
    }


@app.get("/api/stations", dependencies=[Depends(require_browse_access)])
async def get_stations(request: Request) -> Response:
    """返回静态电台列表，并根据地域限制过滤。"""

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


# 旧 ``/api/{station_id}/playlist.m3u8`` / ``/api/{station_id}/{m3u8_name}.m3u8`` /
# ``/api/{station_id}/chunk.ts`` / ``/api/proxy/stream`` 公共入口已被
# ``/api/media/channel/{key}/playlist.m3u8`` + signed-handle 子路由统一取代，
# 不再注册以避免裸 ``target_url`` / ``url`` 形式的 SSRF 入口残留。


@app.get("/api/{station_id}/stream", dependencies=[Depends(require_media_access)])
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

        # 直连音频流：和 chunk 路径一致，强制 identity，避免 httpx 默认 gzip 把
        # 流式音频解码出错或乱报 Content-Length。
        _stream_headers = {**CDN_REQUEST_HEADERS, "Accept-Encoding": "identity"}
        upstream_req = http_client.build_request("GET", real_stream_url, headers=_stream_headers)
        upstream_response = await http_client.send(upstream_req, stream=True)

        if upstream_response.status_code in TOKEN_REFRESH_HTTP_STATUS_CODES:
            await upstream_response.aclose()

            logger.warning(
                "电台 %s 直连音频流返回 %s，准备刷新地址后重试一次",
                station_id,
                upstream_response.status_code,
            )

            real_stream_url = await refresh_station_stream_url(station_id)
            upstream_req = http_client.build_request("GET", real_stream_url, headers=_stream_headers)
            upstream_response = await http_client.send(upstream_req, stream=True)

        upstream_response.raise_for_status()
    except httpx.HTTPError as exc:
        if upstream_response is not None:
            await upstream_response.aclose()
        logger.exception("电台 %s 直连音频流代理失败：%s", station_id, exc)
        raise HTTPException(status_code=502, detail="真实音频流拉取失败。") from exc

    async def stream_audio_bytes() -> AsyncIterator[bytes]:
        try:
            # 强制 identity 编码（见上方 build_request 处的 headers 注释），
            # 因此用 aiter_raw 直接吐字节，避免 httpx 对未压缩内容做无意义 decode。
            async for chunk in upstream_response.aiter_raw(64 * 1024):
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


@app.get("/api/myradio/all", dependencies=[Depends(require_browse_access)])
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


@app.get("/api/yunting/stations/{province_code}", dependencies=[Depends(require_browse_access)])
async def proxy_yunting_stations(province_code: str) -> Response:
    cached = YUNTING_CACHE.get(province_code)
    if cached and time.time() - cached["ts"] < YUNTING_CACHE_TTL:
        return Response(content=cached["data"], media_type="application/json")

    params = {"categoryId": 0, "provinceCode": province_code}
    try:
        resp = await yunting_client.get(
            YUNTING_API_BASE, params=params, headers=_yunting_sign_headers(params),
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


@app.get("/api/yunting/all", dependencies=[Depends(require_browse_access)])
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


@app.get("/api/yunting/epg", dependencies=[Depends(require_browse_access)])
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
                params = {"categoryId": 0, "provinceCode": prov}
                resp = await yunting_client.get(
                    YUNTING_API_BASE,
                    params=params,
                    headers=_yunting_sign_headers(params),
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


@app.get("/api/{station_id}/all-urls", dependencies=[Depends(require_media_access)])
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


@app.get("/api/{station_id}/reachable-urls", dependencies=[Depends(require_media_access)])
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



@app.get("/api/{station_id}/stream-url", dependencies=[Depends(require_media_access)])
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


@app.get("/api/radio-browser/stations/{country_code}", dependencies=[Depends(require_browse_access)])
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
from logo_template import refresh_logo_template_from_remote
import database as db
import market as _market

@app.post("/api/admin/subscriptions", dependencies=[Depends(require_admin)])
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
    # 频道数据变更后失效 Cover 缓存
    from core.cover_cache import invalidate_all_covers
    invalidate_all_covers()

    return {"id": sub_id, "title": title, "url": url, "channel_count": len(channels)}


@app.get("/api/admin/subscriptions", dependencies=[Depends(require_admin)])
async def list_subscriptions():
    return await db.get_subscriptions()


@app.get("/api/admin/subscriptions/{sub_id}", dependencies=[Depends(require_admin)])
async def get_subscription(sub_id: int):
    sub = await db.get_subscription(sub_id)
    if not sub:
        raise HTTPException(status_code=404, detail="订阅不存在")
    return sub


@app.delete("/api/admin/subscriptions/{sub_id}", dependencies=[Depends(require_admin)])
async def delete_subscription(sub_id: int):
    sub = await db.get_subscription(sub_id)
    if not sub:
        raise HTTPException(status_code=404, detail="订阅不存在")
    await db.delete_subscription(sub_id)
    # 频道数据变更后失效 Cover 缓存
    from core.cover_cache import invalidate_all_covers
    invalidate_all_covers()
    return {"ok": True}


async def _refresh_regular_subscription(sub: dict) -> dict:
    headers = {'User-Agent': sub['custom_ua']} if sub.get('custom_ua') else {}
    try:
        resp = await http_client.get(sub['url'], follow_redirects=True, timeout=15, headers=headers)
        resp.raise_for_status()
    except httpx.HTTPError as exc:
        await db.update_subscription(sub['id'], valid=0)
        raise HTTPException(status_code=502, detail=f"刷新失败: {exc}") from exc

    channels = parse_m3u(resp.text)
    channels = deduplicate_channels(channels)
    if not channels:
        await db.update_subscription(sub['id'], valid=0)
        raise HTTPException(
            status_code=502,
            detail="刷新结果未解析到任何频道，已保留旧数据",
        )
    await db.add_channels_bulk(sub['id'], channels)
    await db.update_subscription(sub['id'], valid=1, channel_count=len(channels))
    # 频道数据变更后失效 Cover 缓存
    from core.cover_cache import invalidate_all_covers
    invalidate_all_covers()

    return {"channel_count": len(channels)}


async def _refresh_market_subscription(sub: dict) -> dict:
    package_id = str(sub.get('url') or '').removeprefix('market://').strip()
    if not package_id:
        raise HTTPException(status_code=400, detail="Market 订阅缺少 package_id")
    try:
        result = await _market.update_installed_package(package_id)
    except Exception as exc:
        _market_http_error(exc)
    # 频道数据变更后失效 Cover 缓存
    from core.cover_cache import invalidate_all_covers
    invalidate_all_covers()
    return result


@app.post("/api/admin/subscriptions/{sub_id}/refresh", dependencies=[Depends(require_admin)])
async def refresh_subscription(sub_id: int):
    sub = await db.get_subscription(sub_id)
    if not sub:
        raise HTTPException(status_code=404, detail="订阅不存在")
    if str(sub.get('url') or '').startswith('market://'):
        return await _refresh_market_subscription(sub)
    return await _refresh_regular_subscription(sub)


@app.post("/api/admin/subscriptions/refresh-all", dependencies=[Depends(require_admin)])
async def refresh_all_subscriptions():
    subs = await db.get_subscriptions()
    results = []
    updated = 0
    failed = 0
    for sub in subs:
        try:
            if str(sub.get('url') or '').startswith('market://'):
                result = await _refresh_market_subscription(sub)
            else:
                result = await _refresh_regular_subscription(sub)
            updated += 1
            results.append({
                "subscription_id": sub.get("id"),
                "title": sub.get("title"),
                "status": "updated",
                **(result or {}),
            })
        except HTTPException as exc:
            failed += 1
            results.append({
                "subscription_id": sub.get("id"),
                "title": sub.get("title"),
                "status": "failed",
                "error": exc.detail,
            })
    # 批量刷新后统一失效一次
    if updated > 0:
        from core.cover_cache import invalidate_all_covers
        invalidate_all_covers()
    return {"ok": True, "updated": updated, "failed": failed, "results": results}


# ── 频道 ──

@app.get("/api/admin/subscriptions/{sub_id}/channels", dependencies=[Depends(require_admin)])
async def list_channels(sub_id: int, group: str = '', search: str = ''):
    sub = await db.get_subscription(sub_id)
    if not sub:
        raise HTTPException(status_code=404, detail="订阅不存在")
    channels = await db.get_channels(sub_id, group=group, search=search)
    groups = await db.get_channel_groups(sub_id)
    return {"channels": channels, "groups": groups, "total": len(channels)}


# =====================================================================
# WaveFlow Market
# =====================================================================


class MarketAutomationUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: StrictBool | None = None
    interval_seconds: StrictInt | None = None

    @model_validator(mode="after")
    def validate_update(self):
        if self.enabled is None and self.interval_seconds is None:
            raise ValueError("至少需要提供 enabled 或 interval_seconds")
        if self.interval_seconds is not None:
            if self.interval_seconds < MARKET_MINIMUM_INTERVAL_SECONDS:
                raise ValueError("interval_seconds 小于允许下限")
            if (
                self.interval_seconds > MARKET_MAXIMUM_INTERVAL_SECONDS
            ):
                raise ValueError("interval_seconds 大于允许上限")
        return self


class MarketAutomationResponse(BaseModel):
    task_id: str
    enabled: bool
    interval_seconds: int
    minimum_interval_seconds: int
    maximum_interval_seconds: int | None
    initial_delay_seconds: int
    scheduled_task_type: str
    service_started: bool
    is_running: bool
    task_type: str
    last_started_at: str
    last_finished_at: str
    last_status: str
    checked_count: int
    updated_count: int
    skipped_count: int
    failed_count: int
    last_error: str


class MarketAutomationRunResponse(BaseModel):
    task_id: str
    task_type: str
    status: str
    checked_count: int
    updated_count: int
    skipped_count: int
    failed_count: int
    error: str
    errors: list[str]
    started_at: str
    finished_at: str


class MarketAutomationBusyResponse(BaseModel):
    code: str = "automation_busy"
    message: str = "Market 自动任务正在运行"
    current_task_type: str
    started_at: str
    status: str


def _get_market_automation_service(request: Request):
    service = getattr(request.app.state, "automation_service", None)
    if service is None or not service.is_started:
        raise HTTPException(
            status_code=503,
            detail={
                "code": "automation_unavailable",
                "message": "Market 自动任务服务尚未就绪",
            },
        )
    return service


def _get_market_automation_definition(service):
    try:
        return service.registry.get(MARKET_TASK_ID)
    except (AutomationTaskNotFoundError, AutomationConfigurationError) as exc:
        raise HTTPException(
            status_code=503,
            detail={
                "code": "automation_unavailable",
                "message": "Market 自动任务配置不可用",
            },
        ) from exc


async def _market_automation_snapshot(request: Request) -> MarketAutomationResponse:
    service = _get_market_automation_service(request)
    try:
        definition = _get_market_automation_definition(service)
        config = await service.repository.ensure_config(definition)
        state = await service.repository.get_state(MARKET_TASK_ID)
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("读取 Market 自动任务状态失败")
        raise HTTPException(
            status_code=500,
            detail={
                "code": "automation_status_failed",
                "message": "读取 Market 自动任务状态失败",
            },
        ) from exc

    return MarketAutomationResponse(
        task_id=definition.task_id,
        enabled=config.enabled,
        interval_seconds=config.interval_seconds,
        minimum_interval_seconds=definition.minimum_interval_seconds,
        maximum_interval_seconds=definition.maximum_interval_seconds,
        initial_delay_seconds=definition.initial_delay_seconds,
        scheduled_task_type=definition.scheduled_task_type or "",
        service_started=service.is_started,
        is_running=bool(state and state.status == "running"),
        task_type=state.task_type if state else "",
        last_started_at=state.last_started_at if state else "",
        last_finished_at=state.last_finished_at if state else "",
        last_status=state.status if state else "never_run",
        checked_count=state.checked_count if state else 0,
        updated_count=state.updated_count if state else 0,
        skipped_count=state.skipped_count if state else 0,
        failed_count=state.failed_count if state else 0,
        last_error=state.last_error if state else "",
    )


async def _execute_market_automation(request: Request, task_type: str):
    service = _get_market_automation_service(request)
    try:
        return await service.runner.run(
            AutomationRunRequest(
                task_id=MARKET_TASK_ID,
                task_type=task_type,
                trigger="manual_api",
            )
        )
    except (AutomationTaskNotFoundError, AutomationConfigurationError) as exc:
        raise HTTPException(
            status_code=503,
            detail={
                "code": "automation_unavailable",
                "message": "Market 自动任务配置不可用",
            },
        ) from exc
    except AutomationRequestError as exc:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "automation_request_invalid",
                "message": str(exc),
            },
        ) from exc
    except AutomationOwnershipLostError as exc:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "automation_ownership_lost",
                "message": "Market 自动任务执行权已失效",
            },
        ) from exc
    except Exception as exc:
        logger.exception("执行 Market 自动任务失败: %s", task_type)
        raise HTTPException(
            status_code=500,
            detail={
                "code": "automation_execution_failed",
                "message": "执行 Market 自动任务失败",
            },
        ) from exc


def _market_automation_run_response(result):
    if isinstance(result, AutomationBusy):
        body = MarketAutomationBusyResponse(
            current_task_type=result.task_type,
            started_at=result.started_at,
            status=result.status,
        )
        return JSONResponse(status_code=409, content=body.model_dump())
    if not isinstance(result, AutomationRunResult):
        raise HTTPException(
            status_code=500,
            detail={
                "code": "automation_result_invalid",
                "message": "Market 自动任务返回了无效结果",
            },
        )
    return MarketAutomationRunResponse(
        task_id=result.task_id,
        task_type=result.task_type,
        status=result.status,
        checked_count=result.checked_count,
        updated_count=result.updated_count,
        skipped_count=result.skipped_count,
        failed_count=result.failed_count,
        error=result.error,
        errors=list(result.errors),
        started_at=result.started_at,
        finished_at=result.finished_at,
    )


def _invalidate_market_covers_after_update(result) -> None:
    if isinstance(result, AutomationRunResult) and result.updated_count > 0:
        from core.cover_cache import invalidate_all_covers
        invalidate_all_covers()

def _market_http_error(exc: Exception):
    if isinstance(exc, _market.MarketError):
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.get("/api/admin/market", dependencies=[Depends(require_admin)])
async def get_market_summary():
    try:
        await _market.ensure_market_loaded()
        return _market.market_summary()
    except Exception as exc:
        _market_http_error(exc)


@app.get(
    "/api/admin/market/automation",
    response_model=MarketAutomationResponse,
    dependencies=[Depends(require_admin)],
)
async def get_market_automation(request: Request):
    return await _market_automation_snapshot(request)


@app.patch(
    "/api/admin/market/automation",
    response_model=MarketAutomationResponse,
    dependencies=[Depends(require_admin)],
)
async def update_market_automation(request: Request, body: MarketAutomationUpdateRequest):
    service = _get_market_automation_service(request)
    definition = _get_market_automation_definition(service)
    if body.interval_seconds is not None:
        if body.interval_seconds < definition.minimum_interval_seconds:
            raise HTTPException(status_code=422, detail="interval_seconds 小于允许下限")
        if (
            definition.maximum_interval_seconds is not None
            and body.interval_seconds > definition.maximum_interval_seconds
        ):
            raise HTTPException(status_code=422, detail="interval_seconds 大于允许上限")
    try:
        updated = await service.repository.update_config(
            MARKET_TASK_ID,
            enabled=body.enabled,
            interval_seconds=body.interval_seconds,
        )
    except Exception as exc:
        logger.exception("更新 Market 自动任务配置失败")
        raise HTTPException(
            status_code=500,
            detail={
                "code": "automation_config_update_failed",
                "message": "更新 Market 自动任务配置失败",
            },
        ) from exc
    if updated is None:
        raise HTTPException(
            status_code=503,
            detail={
                "code": "automation_unavailable",
                "message": "Market 自动任务配置不存在",
            },
        )
    try:
        service.notify_config_changed(MARKET_TASK_ID)
    except AutomationTaskNotFoundError as exc:
        raise HTTPException(
            status_code=503,
            detail={
                "code": "automation_unavailable",
                "message": "Market 自动任务调度器尚未就绪",
            },
        ) from exc
    return await _market_automation_snapshot(request)


@app.post(
    "/api/admin/market/check-updates",
    response_model=MarketAutomationRunResponse,
    responses={409: {"model": MarketAutomationBusyResponse}},
    dependencies=[Depends(require_admin)],
)
async def check_market_updates(request: Request):
    result = await _execute_market_automation(request, "check")
    return _market_automation_run_response(result)


@app.post(
    "/api/admin/market/run-auto-update",
    response_model=MarketAutomationRunResponse,
    responses={409: {"model": MarketAutomationBusyResponse}},
    dependencies=[Depends(require_admin)],
)
async def run_market_auto_update(request: Request):
    result = await _execute_market_automation(request, "auto_update")
    _invalidate_market_covers_after_update(result)
    return _market_automation_run_response(result)


@app.post(
    "/api/admin/market/update-all",
    response_model=MarketAutomationRunResponse,
    responses={409: {"model": MarketAutomationBusyResponse}},
    dependencies=[Depends(require_admin)],
)
async def update_all_market_packages(request: Request):
    result = await _execute_market_automation(request, "update_all")
    _invalidate_market_covers_after_update(result)
    return _market_automation_run_response(result)


@app.post("/api/admin/market/refresh", dependencies=[Depends(require_admin)])
async def refresh_market(request: Request):
    try:
        body = await request.json() if request.headers.get("content-type", "").startswith("application/json") else {}
        source_id = (body or {}).get("source_id")
        result = await _market.refresh_market(
            (body or {}).get("market_url"),
            allow_private=_truthy_query((body or {}).get("allow_private", False)),
            source_id=int(source_id) if source_id else None,
        )
        from core.cover_cache import invalidate_all_covers
        invalidate_all_covers()
        return result
    except Exception as exc:
        _market_http_error(exc)


@app.get("/api/admin/market/sources", dependencies=[Depends(require_admin)])
async def list_market_sources():
    try:
        return {"sources": await _market.list_sources()}
    except Exception as exc:
        _market_http_error(exc)


@app.post("/api/admin/market/sources", dependencies=[Depends(require_admin)])
async def create_market_source(request: Request):
    try:
        body = await request.json()
        source = await _market.create_source(
            name=(body or {}).get("name", ""),
            url=(body or {}).get("url", ""),
            enabled=_truthy_query((body or {}).get("enabled", True)),
            allow_private=_truthy_query((body or {}).get("allow_private", False)),
        )
        return source
    except Exception as exc:
        _market_http_error(exc)


@app.put("/api/admin/market/sources/{source_id}", dependencies=[Depends(require_admin)])
async def update_market_source(source_id: int, request: Request):
    try:
        body = await request.json()
        return await _market.update_source(source_id, body or {})
    except Exception as exc:
        _market_http_error(exc)


@app.delete("/api/admin/market/sources/{source_id}", dependencies=[Depends(require_admin)])
async def delete_market_source(source_id: int):
    try:
        return await _market.delete_source(source_id)
    except Exception as exc:
        _market_http_error(exc)


@app.get("/api/admin/market/packages", dependencies=[Depends(require_admin)])
async def list_market_packages(
    search: str = '',
    region: str = '',
    operator: str = '',
    kind: str = '',
    status: str = '',
    tag: str = '',
    supported_only: bool = True,
    importable_only: bool = False,
):
    try:
        packages = await _market.list_packages({
            "search": search,
            "region": region,
            "operator": operator,
            "kind": kind,
            "status": status,
            "tag": tag,
            "supported_only": supported_only,
            "importable_only": importable_only,
        })
        return {"packages": packages, "total": len(packages)}
    except Exception as exc:
        _market_http_error(exc)


@app.get("/api/admin/market/packages/{package_id}", dependencies=[Depends(require_admin)])
async def get_market_package(package_id: str):
    try:
        return await _market.get_package(package_id)
    except Exception as exc:
        _market_http_error(exc)


@app.post("/api/admin/market/packages/{package_id}/preview", dependencies=[Depends(require_admin)])
async def preview_market_package(package_id: str):
    try:
        return await _market.build_preview(package_id)
    except Exception as exc:
        _market_http_error(exc)


@app.post("/api/admin/market/packages/{package_id}/import", dependencies=[Depends(require_admin)])
async def import_market_package(package_id: str, request: Request):
    try:
        body = await request.json() if request.headers.get("content-type", "").startswith("application/json") else {}
        result = await _market.import_package(
            package_id,
            preview_id=(body or {}).get("preview_id", ""),
            prefer_cached_preview=_truthy_query((body or {}).get("prefer_cached_preview", True)),
            reinstall=_truthy_query((body or {}).get("reinstall", False)),
        )
        from core.cover_cache import invalidate_all_covers
        invalidate_all_covers()
        return result
    except Exception as exc:
        _market_http_error(exc)


@app.post("/api/admin/market/packages/{package_id}/update", dependencies=[Depends(require_admin)])
async def update_market_package(package_id: str):
    try:
        result = await _market.update_installed_package(package_id)
        from core.cover_cache import invalidate_all_covers
        invalidate_all_covers()
        return result
    except Exception as exc:
        _market_http_error(exc)


@app.patch("/api/admin/market/packages/{package_id}/install", dependencies=[Depends(require_admin)])
async def update_market_install(package_id: str, request: Request):
    try:
        body = await request.json() if request.headers.get("content-type", "").startswith("application/json") else {}
        return await _market.update_install_config(
            package_id,
            auto_update=_truthy_query((body or {}).get("auto_update", False)) if "auto_update" in (body or {}) else None,
        )
    except Exception as exc:
        _market_http_error(exc)


@app.post(
    "/api/admin/market/updates/run",
    dependencies=[Depends(require_admin)],
    deprecated=True,
)
async def run_market_updates(request: Request):
    result = await _execute_market_automation(request, "update_all")
    _invalidate_market_covers_after_update(result)
    response = _market_automation_run_response(result)
    if isinstance(response, JSONResponse):
        return response
    return {
        **response.model_dump(),
        "updated": response.updated_count,
        "skipped": response.skipped_count,
        "failed": response.failed_count,
        "results": [],
    }


@app.delete("/api/admin/market/packages/{package_id}/install", dependencies=[Depends(require_admin)])
async def uninstall_market_package(package_id: str):
    try:
        result = await _market.uninstall_package(package_id)
        from core.cover_cache import invalidate_all_covers
        invalidate_all_covers()
        return result
    except Exception as exc:
        _market_http_error(exc)


# ── 前端聚合频道列表（跨源去重，每个频道保留所有可用链接）──

def _content_category(name: str) -> str:
    """内容分类兜底：全国频道（无省份归属）按内容词分类。"""
    import re
    if re.search(r'少儿|卡通|动画|动漫|宝宝|宝贝', name): return '少儿'
    if re.search(r'电影|影院|剧场', name): return '电影'
    if re.search(r'体育|足球|篮球|网球|高尔夫', name): return '体育'
    if re.search(r'纪录|探索|地理', name): return '纪录'
    if re.search(r'购物', name): return '购物'
    if re.search(r'戏曲|梨园', name): return '戏曲'
    if re.search(r'新闻|资讯', name): return '新闻'
    if re.search(r'音乐|MTV', name): return '音乐'
    return ''


async def _get_aggregated_iptv_channels(group: str = '', search: str = '') -> tuple[list[dict], list[str]]:
    # 搜索在 SQL 层过滤（性能好），分组在聚合后过滤（归一化后才准）
    raw = await db.get_aggregated_channels(group='', search=search)

    from m3u8_parser import adapter_provider, clean_channel_display_name, detect_source_type, normalize_channel_name, parse_youtube_channel_id, parse_youtube_video_id, _channel_alias
    from template import channel_template, normalize_group_name, detect_province
    from logo_template import logo_template

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
        norm_grp = normalize_group_name(raw_grp)
        # 分类优先级（央视>卫视>省份>内容）：
        #   ① template 命中（CCTV5→央视、浙江卫视→卫视、金鹰卡通→少儿）
        #   ② detect_province 频道名识别省份（比源 group 可靠：临沂新闻→山东）
        #   ③ 源 group 有效省份（黑龙江地区→黑龙江）
        #   ④ 内容规则兜底（少儿/电影/体育/购物/戏曲）
        #   ⑤ 源 group 兜底
        if tmpl_cat:
            grp = tmpl_cat
        else:
            prov = detect_province(ch['name'])
            if prov:
                grp = prov
            elif norm_grp not in ('地方', '其他', '超清', 'hytest', 'zgzk'):
                grp = norm_grp
            else:
                grp = _content_category(ch['name']) or norm_grp

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
        youtube_video_id = parse_youtube_video_id(ch['url']) or ch.get('youtube_video_id')
        youtube_channel_id = parse_youtube_channel_id(ch['url'])
        source_entry = {
            'url': ch['url'],
            'is_working': ch['is_working'],
            'latency_ms': ch['latency_ms'],
            'last_tested': ch.get('last_tested', ''),
            'probe_status': ch.get('probe_status', 'untested'),
            'live_status': ch.get('live_status', 'unknown'),
            'probe_method': ch.get('probe_method', ''),
            'speed_mbps': ch.get('speed_mbps', 0),
            'resolution': ch.get('resolution', ''),
            'fps': ch.get('fps', 0),
            'video_codec': ch.get('video_codec', ''),
            'audio_codec': ch.get('audio_codec', ''),
            'requires_headers': ch.get('requires_headers', 0),
            'requires_proxy_declared': ch.get('requires_proxy_declared', 0),
            'proxy_required_hint': ch.get('proxy_required_hint', 0),
            'last_success_at': ch.get('last_success_at', ''),
            'last_error': ch.get('last_error', ''),
            'adapter_provider': ch.get('adapter_provider', ''),
            'adapter_title': ch.get('adapter_title', ''),
            'probe_meta_json': ch.get('probe_meta_json', '{}'),
            'sub_title': ch.get('sub_title', ''),
            'custom_ua': ch.get('custom_ua', ''),
            'referer': ch.get('referer', ''),
            'force_proxy': ch.get('force_proxy', 0),
            'source_type': source_type,
            'adapter': adapter_provider(ch['url']),
            'youtube_video_id': youtube_video_id,
            'youtube_channel_id': youtube_channel_id,
            'raw_name': ch['name'],
            'raw_tvg_id': ch.get('tvg_id', ''),
            'raw_tvg_name': ch.get('tvg_name', ''),
            'raw_group': ch.get('group_name', ''),
            'market_package_id': ch.get('market_package_id', ''),
            'market_source_id': ch.get('market_source_id', ''),
            'market_channel_id': ch.get('market_channel_id', ''),
            'market_source_item_id': ch.get('market_source_item_id', ''),
        }
        source_entry['source_id'] = source_id_for(ch)
        merged[key]['urls'].append(source_entry)

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

        # 用 logo 模板覆盖：命中即换成 CDN 高清版，未命中维持原 M3U logo 兜底。
        # 见 backend/logo_template.py，模板按 canonical_key 查询，零误判、不影响去重。
        tmpl_logo = logo_template.lookup(ch['canonical_key'])
        if tmpl_logo:
            ch['logo_url'] = tmpl_logo

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


@app.get("/api/iptv/channels", dependencies=[Depends(require_browse_access)])
async def aggregated_channels(group: str = '', search: str = ''):
    result, groups = await _get_aggregated_iptv_channels(group=group, search=search)

    return {
        "channels": result,
        "groups": groups,
        "total": len(result),
        # adapter 能力表，前端据此决定要对哪些 adapter 触发 cover 懒加载等增强请求。
        # 由各 adapter 模块顶层 ADAPTER_CAPABILITIES 自描述 + adapters/__init__.py 采集。
        "adapter_capabilities": adapter_capabilities_map(),
    }


# ── 测速 ──

# 测速进度存储（内存）
_test_progress: dict[int, dict] = {}
_global_test_progress: dict = {}
_speed_test_lock = asyncio.Lock()
_speed_test_running = False
_speed_test_cancel_event: asyncio.Event | None = None
_speed_test_task: asyncio.Task | None = None


def _empty_test_progress(total: int = 0) -> dict:
    return {
        "total": total,
        "tested": 0,
        "working": 0,
        "failed": 0,
        "not_live": 0,
        "untested": 0,
        "phase": "",
        "current": "",
        "ffmpeg_active": 0,
        "cancelled": False,
    }


async def _begin_speed_test() -> None:
    global _speed_test_cancel_event, _speed_test_running
    async with _speed_test_lock:
        if _speed_test_running:
            raise HTTPException(status_code=409, detail="已有测速任务正在进行中")
        _speed_test_running = True
        _speed_test_cancel_event = asyncio.Event()


async def _finish_speed_test() -> None:
    global _speed_test_cancel_event, _speed_test_running, _speed_test_task
    async with _speed_test_lock:
        _speed_test_running = False
        _speed_test_cancel_event = None
        _speed_test_task = None


def _set_speed_test_task(task: asyncio.Task) -> None:
    global _speed_test_task
    _speed_test_task = task


def _current_speed_test_cancel_event() -> asyncio.Event:
    return _speed_test_cancel_event or asyncio.Event()


def _probe_status_to_bucket(status: str) -> str:
    if status == "online":
        return "working"
    if status == "not_live":
        return "not_live"
    if status in {"unsupported", "untested"}:
        return "untested"
    return "failed"


@app.post("/api/admin/probes/test-all", dependencies=[Depends(require_admin)])
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

    await _begin_speed_test()
    try:
        await db.reset_channel_statuses_all()
    except Exception:
        await _finish_speed_test()
        raise
    _global_test_progress.clear()
    _global_test_progress.update(_empty_test_progress(total))
    logger.info("开始测速: %d 个频道", total)
    task = asyncio.create_task(_run_speed_test_global(all_channels, _current_speed_test_cancel_event()))
    _set_speed_test_task(task)
    return {"total": total}


@app.post("/api/admin/subscriptions/{sub_id}/test-all", dependencies=[Depends(require_admin)])
async def test_subscription(sub_id: int):
    """测速单个订阅源的所有频道"""
    sub = await db.get_subscription(sub_id)
    if not sub:
        raise HTTPException(status_code=404, detail="订阅不存在")

    channels = await db.get_channels(sub_id)
    if not channels:
        raise HTTPException(status_code=400, detail="该订阅无频道")

    await _begin_speed_test()
    try:
        await db.reset_channel_statuses(sub_id)
    except Exception:
        await _finish_speed_test()
        raise
    _test_progress[sub_id] = _empty_test_progress(len(channels))
    _global_test_progress.clear()
    _global_test_progress.update(_empty_test_progress(len(channels)))
    logger.info("开始测速订阅 %s: %d 个频道", sub['title'], len(channels))
    task = asyncio.create_task(_run_speed_test_sub(sub_id, channels, _current_speed_test_cancel_event()))
    _set_speed_test_task(task)
    return {"total": len(channels)}


def _speed_test_semaphore_for_channel(
    ch: dict,
    semaphores: dict[str, asyncio.Semaphore],
    default_sem: asyncio.Semaphore,
    adapter_limits: dict[str, int],
) -> asyncio.Semaphore:
    from m3u8_parser import adapter_provider as _ap, is_youtube_url as _is_yt

    url = ch.get("url", "")
    name = "youtube" if _is_yt(url) else _ap(url)
    limit = adapter_limits.get(name)
    if limit is None:
        return default_sem
    return semaphores.setdefault(name, asyncio.Semaphore(limit))


async def _run_speed_test_sub(sub_id: int, channels: list[dict], cancel_event: asyncio.Event):
    adapter_limits: dict[str, int] = {"youtube": 1}
    semaphores: dict[str, asyncio.Semaphore] = {}
    default_sem = asyncio.Semaphore(10)

    tasks: list[asyncio.Task] = []

    async def _limited_test(ch):
        async with _speed_test_semaphore_for_channel(ch, semaphores, default_sem, adapter_limits):
            if cancel_event.is_set():
                return ch, {"probe_status": "untested", "latency_ms": 0, "last_error": "cancelled"}
            try:
                return ch, await asyncio.wait_for(probe_channel_source(ch, http_client), timeout=24)
            except asyncio.TimeoutError:
                return ch, {"probe_status": "timeout", "latency_ms": 0, "last_error": "timeout"}
            except Exception as exc:
                return ch, {"probe_status": "error", "latency_ms": 0, "last_error": str(exc)[:300]}

    try:
        tasks = [asyncio.create_task(_limited_test(ch)) for ch in channels]
        for coro in asyncio.as_completed(tasks):
            if cancel_event.is_set():
                break
            result = {"probe_status": "error", "latency_ms": 0, "last_error": "unknown"}
            ch = None
            try:
                ch, result = await coro
                _test_progress[sub_id]["current"] = ch.get("name", "")
                _test_progress[sub_id]["phase"] = result.get("probe_method", "")
                _global_test_progress["current"] = ch.get("name", "")
                _global_test_progress["phase"] = result.get("probe_method", "")
                await db.update_channel_probe_result(ch['id'], result)
            except Exception as e:
                logger.warning("测速异常: %s", e)
                if ch:
                    await db.update_channel_probe_result(ch['id'], result)
            bucket = _probe_status_to_bucket(str(result.get("probe_status") or "error"))
            _test_progress[sub_id]['tested'] += 1
            _global_test_progress['tested'] += 1
            _test_progress[sub_id][bucket] += 1
            _global_test_progress[bucket] += 1
        if cancel_event.is_set():
            for task in tasks:
                task.cancel()
            _test_progress[sub_id]["phase"] = "cancelled"
            _global_test_progress["phase"] = "cancelled"
            _test_progress[sub_id]["cancelled"] = True
            _global_test_progress["cancelled"] = True
            await asyncio.gather(*tasks, return_exceptions=True)
        else:
            await db.update_subscription(sub_id, last_tested=datetime.now(timezone.utc).isoformat())
    except asyncio.CancelledError:
        cancel_event.set()
        _test_progress[sub_id]["phase"] = "cancelled"
        _global_test_progress["phase"] = "cancelled"
        _test_progress[sub_id]["cancelled"] = True
        _global_test_progress["cancelled"] = True
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
    finally:
        await _finish_speed_test()


async def _run_speed_test_global(channels: list[dict], cancel_event: asyncio.Event):
    adapter_limits: dict[str, int] = {"youtube": 1}
    semaphores: dict[str, asyncio.Semaphore] = {}
    default_sem = asyncio.Semaphore(10)

    tasks: list[asyncio.Task] = []

    async def _limited_test(ch):
        async with _speed_test_semaphore_for_channel(ch, semaphores, default_sem, adapter_limits):
            if cancel_event.is_set():
                return ch, {"probe_status": "untested", "latency_ms": 0, "last_error": "cancelled"}
            try:
                return ch, await asyncio.wait_for(probe_channel_source(ch, http_client), timeout=24)
            except asyncio.TimeoutError:
                logger.warning("测速超时: %s", ch.get('name', ch.get('url', ''))[:60])
                return ch, {"probe_status": "timeout", "latency_ms": 0, "last_error": "timeout"}
            except Exception as exc:
                return ch, {"probe_status": "error", "latency_ms": 0, "last_error": str(exc)[:300]}

    try:
        tasks = [asyncio.create_task(_limited_test(ch)) for ch in channels]
        for coro in asyncio.as_completed(tasks):
            if cancel_event.is_set():
                break
            result = {"probe_status": "error", "latency_ms": 0, "last_error": "unknown"}
            ch = None
            try:
                ch, result = await coro
                _global_test_progress["current"] = ch.get("name", "")
                _global_test_progress["phase"] = result.get("probe_method", "")
                await db.update_channel_probe_result(ch['id'], result)
            except Exception as e:
                logger.warning("测速异常: %s", e)
                if ch:
                    await db.update_channel_probe_result(ch['id'], result)
            bucket = _probe_status_to_bucket(str(result.get("probe_status") or "error"))
            _global_test_progress['tested'] += 1
            _global_test_progress[bucket] += 1
            tested = _global_test_progress['tested']
            total = _global_test_progress['total']
            if tested % 50 == 0 or tested == total:
                logger.info(
                    "测速进度: %d/%d (可用:%d 不可用:%d 未开播:%d 未测试:%d)",
                    tested,
                    total,
                    _global_test_progress['working'],
                    _global_test_progress['failed'],
                    _global_test_progress['not_live'],
                    _global_test_progress['untested'],
                )
        if cancel_event.is_set():
            for task in tasks:
                task.cancel()
            _global_test_progress["phase"] = "cancelled"
            _global_test_progress["cancelled"] = True
            await asyncio.gather(*tasks, return_exceptions=True)
        else:
            # 测速完成，更新所有订阅的 last_tested
            now = datetime.now(timezone.utc).isoformat()
            subs = await db.get_subscriptions()
            for sub in subs:
                await db.update_subscription(sub['id'], last_tested=now)
    except asyncio.CancelledError:
        cancel_event.set()
        _global_test_progress["phase"] = "cancelled"
        _global_test_progress["cancelled"] = True
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
    finally:
        await _finish_speed_test()


@app.post("/api/admin/probes/test-cancel", dependencies=[Depends(require_admin)])
async def cancel_speed_test():
    async with _speed_test_lock:
        if not _speed_test_running:
            return {"cancelled": False, "running": False}
        if _speed_test_cancel_event:
            _speed_test_cancel_event.set()
        if _speed_test_task and not _speed_test_task.done():
            _speed_test_task.cancel()
        return {"cancelled": True, "running": True}


@app.get("/api/admin/probes/test-status", dependencies=[Depends(require_admin)])
async def global_test_status():
    return _global_test_progress or _empty_test_progress()


@app.get("/api/admin/subscriptions/{sub_id}/test-status", dependencies=[Depends(require_admin)])
async def test_status(sub_id: int):
    return _test_progress.get(sub_id, _empty_test_progress())


# ── 播放代理 ──

# 扩展窗口代理：定期拉上游 playlist
_wide_cache: dict[str, dict] = {}
# 扩展窗口设计目标：维持「比上游 sliding window 略大但不要长到老 segment 404」。
# 实际上游窗口典型 3~6 段；这里取 8 既能覆盖瞬时缺段，又能让 hls.js 看到一个稳定的
# live edge。``_WIDE_WINDOW`` 只是上限，实际 deque 仍然按 seq 推进。
# 一些 IPTV 上游会用循环文件名（如 0.ts/1.ts/.../4.ts）+ 滚动 MEDIA-SEQUENCE；
# 同一文件名的内容会被覆盖。窗口必须 ≤ 上游 sliding window，否则队尾的旧
# segment URL 拉回来已是新内容，hls.js 会触发 levelParsingError / bufferStalled。
# 取 6：略大于福建系上游的 5 段，给一两段缓冲；其它源上游窗口通常 ≥ 6。
_WIDE_WINDOW = 6
_WIDE_TTL = 120
# stale grace 不再写死秒数；按 target_duration 折算，至少 30s、最多 90s。
_WIDE_STALE_GRACE_MIN = 30
_WIDE_STALE_GRACE_MAX = 90
_WIDE_REFRESH_LOG_INTERVAL = 30
# 后台 refresher 的最短/最长睡眠时间，按 target_duration 自适应。
_WIDE_REFRESH_INTERVAL_MIN = 1.0
_WIDE_REFRESH_INTERVAL_MAX = 4.0
# 后台刷新最多允许的连续失败次数。超过后主动释放缓存，让下一请求重新
# 调用 adapter resolve 拿到新鲜 token。fjtv 等上游的动态 ``_upt`` token
# 可能几个月也不变，也可能几分钟就过期；我们靠「反复失败」来推断。
_WIDE_MAX_CONSECUTIVE_ERRORS = 12
_IPTV_SEGMENT_EXTENSIONS = (".ts", ".m4s", ".mp4", ".m4v", ".aac", ".mp3", ".key")
_HLS_URI_TAGS = ("EXT-X-KEY", "EXT-X-MAP", "EXT-X-PART", "EXT-X-PRELOAD-HINT", "EXT-X-MEDIA", "EXT-X-I-FRAME-STREAM-INF")
_HLS_URI_RE = re.compile(r'(URI=")([^"]+)(")', re.IGNORECASE)

WIDE_ENABLED = False  # 全局扩窗开关；False=统一直通重写，True=恢复旧扩窗行为

# ── 薄韧性 playlist 代理缓存（非扩窗）────────────────────────────
# 扩窗关闭时，所有 playlist 拉取走这里：重试 + single-flight + 短暂成功回退。
# 不做队列、不做后台 refresher、不自己维护 MEDIA-SEQUENCE。
_THIN_CACHE: dict[str, tuple[str, str, float]] = {}   # cache_key → (text, final_url, ts)
_THIN_LOCKS: dict[str, asyncio.Lock] = {}
_THIN_TTL = 1.5          # 新鲜窗口：合并并发请求 + 极短回放，避免 short-window 上游（如 yxfy 3×5s）丢段
_THIN_MAX_ENTRIES = 200


def _thin_cache_key(url: str, cache_scope: str = "") -> str:
    """稳定 cache key：source/config scope + scheme://netloc/path，去掉 query（含动态 token）。"""
    parsed = urlparse(url)
    stable_url = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
    return f"{cache_scope}\x1f{stable_url}" if cache_scope else stable_url


async def _thin_playlist_fetch(url: str, headers: dict[str, str] | None = None, *, cache_scope: str = "") -> tuple[str, str]:
    """拉取上游 playlist，带薄韧性。

    - single-flight：同一 URL 并发请求合并为一次上游 fetch
    - 重试 1 次（共 2 次尝试，间隔 0.3s）
    - 成功结果按稳定 key 缓存 5s，作为后续失败时的回退
    - 全失败且缓存中有未过期结果 → 返回缓存
    - 全失败且无缓存 → raise HTTPException(502)

    返回 ``(响应文本, 最终 URL)``。
    """
    _h = dict(headers or {})
    _h.setdefault("Accept-Encoding", "identity")

    ck = _thin_cache_key(url, cache_scope)
    lock = _THIN_LOCKS.setdefault(ck, asyncio.Lock())

    async with lock:
        # single-flight：锁内再检查一次缓存（可能被上一个持有者写入）
        cached = _THIN_CACHE.get(ck)
        if cached and cached[2] > time.time():
            return cached[0], cached[1]

        last_exc = None
        last_text = ""
        last_url = ""

        for attempt in range(2):
            try:
                resp = await http_client.get(
                    url, follow_redirects=True, timeout=8, headers=_h,
                )
                resp.raise_for_status()
                last_text = resp.text
                last_url = str(resp.url)

                # 成功：写入短暂缓存（按稳定 key）
                now = time.time()
                _THIN_CACHE[ck] = (last_text, last_url, now + _THIN_TTL)
                # 防止缓存无限制增长
                if len(_THIN_CACHE) > _THIN_MAX_ENTRIES:
                    expired = [k for k, v in _THIN_CACHE.items() if v[2] <= now]
                    for k in expired:
                        _THIN_CACHE.pop(k, None)
                    # 如果过期清理不够，删最老的
                    while len(_THIN_CACHE) > _THIN_MAX_ENTRIES:
                        oldest = min(_THIN_CACHE, key=lambda k: _THIN_CACHE[k][2], default=None)
                        if oldest:
                            _THIN_CACHE.pop(oldest, None)
                        else:
                            break

                return last_text, last_url
            except httpx.HTTPError as exc:
                last_exc = exc
                if attempt == 0:
                    await asyncio.sleep(0.3)

        # 全部尝试失败 → 尝试返回缓存（即使已过期，作为最后回退）
        cached = _THIN_CACHE.get(ck)
        if cached:
            logger.warning(
                "薄韧性回退: 上游 %s 拉取失败 (%s)，返回 %ds 前缓存",
                url[:100], last_exc, int(time.time() - cached[2] + _THIN_TTL),
            )
            return cached[0], cached[1]

        raise HTTPException(status_code=502, detail=f"拉取 playlist 失败: {last_exc}")


def _wide_stale_grace_for(target_duration: int) -> float:
    return min(
        _WIDE_STALE_GRACE_MAX,
        max(_WIDE_STALE_GRACE_MIN, float(target_duration) * 4.0),
    )


def _wide_refresh_interval_for(target_duration: int) -> float:
    base = max(1.0, float(target_duration) / 2.0)
    return min(_WIDE_REFRESH_INTERVAL_MAX, max(_WIDE_REFRESH_INTERVAL_MIN, base))


def _drop_wide_cache(cache_key: str) -> None:
    _wide_cache.pop(cache_key, None)
    _wide_cache.pop(cache_key + '_ts', None)


def _ensure_hls_playlist_text(text: str, url: str) -> None:
    if not (text or "").lstrip().startswith("#EXTM3U"):
        raise HTTPException(status_code=502, detail=f"上游没有返回有效 M3U8: {url}")


def _should_proxy_iptv_chunk(seg_url: str, proxy_ts: int = 0) -> bool:
    scheme = urlparse(seg_url).scheme.lower()
    return bool(proxy_ts) and scheme in {"http", "https"}


def _make_handle_path(*, kind: str, upstream_url: str, ctx_id: str, src_id: str, src_label: str, access_token: str = "") -> str:
    """统一封装 signed handle URL 生成。

    ctx_id / src_id / src_label 来自调用方所处的请求上下文（rewriter / wide refresher）。
    access_token 仅在调用方持有 Media Credential 时透传。
    """
    from security.proxy_handles import issue_cached_handle as _issue
    handle = _issue(
        kind=kind,
        url=upstream_url,
        src=src_label,
        src_id=src_id,
        ctx=ctx_id,
    )
    suffix = ""
    if access_token:
        suffix = f"?access_token={quote(access_token, safe='')}"
    return f"/api/media/proxy/{kind}/{handle}{suffix}"


def _iptv_chunk_handle_path(seg_url: str, ctx_id: str, src_id: str, src_label: str, access_token: str = "") -> str:
    return _make_handle_path(
        kind="chunk",
        upstream_url=seg_url,
        ctx_id=ctx_id,
        src_id=src_id,
        src_label=src_label,
        access_token=access_token,
    )


def _iptv_playlist_handle_path(playlist_url: str, ctx_id: str, src_id: str, src_label: str, access_token: str = "") -> str:
    return _make_handle_path(
        kind="playlist",
        upstream_url=playlist_url,
        ctx_id=ctx_id,
        src_id=src_id,
        src_label=src_label,
        access_token=access_token,
    )


def _rewrite_hls_tag_uri(line: str, base_url: str, ctx_id: str, src_id: str, src_label: str, *, access_token: str = "", proxy_ts: int = 1) -> str:
    """重写 HLS 标签行内的 ``URI="..."``。"""
    upper = line.upper()
    if not any(f"#{tag}:" in upper for tag in _HLS_URI_TAGS):
        return line

    def _replace_uri(m):
        uri = m.group(2)
        scheme = urlparse(uri).scheme.lower()
        if scheme and scheme not in ("http", "https"):
            return m.group(0)

        absolute_url = urljoin(base_url, uri)
        parsed = urlparse(absolute_url)
        uri_path = parsed.path.lower()

        if uri_path.endswith(".m3u8"):
            return f'{m.group(1)}{_iptv_playlist_handle_path(absolute_url, ctx_id, src_id, src_label, access_token)}{m.group(3)}'
        if uri_path.endswith(_IPTV_SEGMENT_EXTENSIONS) and _should_proxy_iptv_chunk(absolute_url, proxy_ts):
            return f'{m.group(1)}{_iptv_chunk_handle_path(absolute_url, ctx_id, src_id, src_label, access_token)}{m.group(3)}'
        return m.group(0)

    return _HLS_URI_RE.sub(_replace_uri, line)


def _rewrite_iptv_wide_m3u8_text(raw_m3u8_text: str, base_url: str, ctx_id: str, src_id: str, src_label: str, *, access_token: str = "", proxy_ts: int = 1) -> str:
    rewritten_lines: list[str] = []
    for line in raw_m3u8_text.splitlines():
        stripped_line = line.strip()
        if not stripped_line:
            rewritten_lines.append(line)
            continue
        if stripped_line.startswith("#"):
            rewritten_lines.append(_rewrite_hls_tag_uri(line, base_url, ctx_id, src_id, src_label, access_token=access_token, proxy_ts=proxy_ts))
            continue
        try:
            absolute_media_url = urljoin(base_url, stripped_line)
        except ValueError:
            logger.warning("跳过无法解析的 HLS URI: base=%s line=%s", base_url, stripped_line[:200])
            rewritten_lines.append(line)
            continue
        parsed_url = urlparse(absolute_media_url)
        uri_path = parsed_url.path.lower()
        if uri_path.endswith(".m3u8"):
            rewritten_lines.append(_iptv_playlist_handle_path(absolute_media_url, ctx_id, src_id, src_label, access_token))
        elif uri_path.endswith(_IPTV_SEGMENT_EXTENSIONS) and _should_proxy_iptv_chunk(absolute_media_url, proxy_ts):
            rewritten_lines.append(_iptv_chunk_handle_path(absolute_media_url, ctx_id, src_id, src_label, access_token))
        else:
            rewritten_lines.append(absolute_media_url)
    return "\n".join(rewritten_lines)


# 旧 adapter 公共解析/播放入口已被 ``/api/media/channel/{key}/playlist.m3u8`` 取代：
# 入口完全基于稳定 channel canonical_key，后端内部完成 adapter resolve →
# ProxyContext 注入 → signed handle → 重写。前端不再传 adapter URL。


# ── adapter 直播间封面/头像 ─────────────────────────────────────────────
# 哪些 adapter 支持 cover，由 adapter 模块自己声明 ADAPTER_CAPABILITIES = {"cover": True}，
# 这里只做"中央实现"：轻量 metadata 抓取 + URL 缓存。失败/未声明一律返回 200 + 空字符串，
# 让前端继续走 logo_url 兜底，避免把这条非关键路径变成报错弹窗源。

_ADAPTER_COVER_SUCCESS_TTL_SECONDS = 6 * 3600  # cover URL 都是平台 CDN 长期 URL，6h 足够
_ADAPTER_COVER_FAILURE_TTL_SECONDS = 5 * 60    # 失败/未开播短缓存，避免反复打风控接口
_ADAPTER_COVER_HTTP_TIMEOUT = 6.0

_adapter_cover_cache: dict[str, dict] = {}
_adapter_cover_locks: dict[str, asyncio.Lock] = {}


def _adapter_cover_empty(adapter_name: str = '') -> dict:
    return {
        "ok": True,
        "adapter": adapter_name,
        "cover_url": "",
        "avatar_url": "",
        "title": "",
        "anchor_name": "",
        "is_live": False,
    }


def _adapter_cover_cache_get(cache_key: str) -> dict | None:
    item = _adapter_cover_cache.get(cache_key)
    if not item:
        return None
    if float(item.get("expires_at", 0)) <= time.time():
        _adapter_cover_cache.pop(cache_key, None)
        return None
    return dict(item.get("payload") or {})


def _adapter_cover_cache_set(cache_key: str, payload: dict, ttl: int) -> None:
    if ttl <= 0:
        _adapter_cover_cache.pop(cache_key, None)
        return
    _adapter_cover_cache[cache_key] = {
        "expires_at": time.time() + ttl,
        "payload": dict(payload),
    }


async def _fetch_bilibili_cover(room_id: str) -> dict:
    api = (
        "https://api.live.bilibili.com/xlive/web-room/v1/index/getH5InfoByRoom"
        f"?room_id={quote(room_id, safe='')}"
    )
    resp = await http_client.get(
        api,
        timeout=_ADAPTER_COVER_HTTP_TIMEOUT,
        headers={
            "User-Agent": "Mozilla/5.0",
            "Referer": f"https://live.bilibili.com/{room_id}",
        },
    )
    resp.raise_for_status()
    data = (resp.json() or {}).get("data") or {}
    room_info = data.get("room_info") or {}
    base_info = ((data.get("anchor_info") or {}).get("base_info")) or {}
    cover = str(room_info.get("cover") or room_info.get("keyframe") or "").strip()
    avatar = str(base_info.get("face") or "").strip()
    return {
        "ok": True,
        "adapter": "bilibili",
        "cover_url": cover,
        "avatar_url": avatar,
        "title": str(room_info.get("title") or "").strip(),
        "anchor_name": str(base_info.get("uname") or "").strip(),
        "is_live": int(room_info.get("live_status") or 0) == 1,
    }


async def _fetch_douyu_cover(room_id: str) -> dict:
    api = f"https://www.douyu.com/betard/{quote(room_id, safe='')}"
    resp = await http_client.get(
        api,
        timeout=_ADAPTER_COVER_HTTP_TIMEOUT,
        headers={
            "User-Agent": "Mozilla/5.0",
            "Referer": "https://www.douyu.com/",
        },
    )
    resp.raise_for_status()
    room = (resp.json() or {}).get("room") or {}
    avatar_field = room.get("avatar")
    if isinstance(avatar_field, dict):
        avatar = str(avatar_field.get("big") or avatar_field.get("middle") or "").strip()
    else:
        avatar = str(avatar_field or room.get("avatar_mid") or "").strip()
    return {
        "ok": True,
        "adapter": "douyu",
        "cover_url": str(room.get("room_pic") or "").strip(),
        "avatar_url": avatar,
        "title": str(room.get("room_name") or "").strip(),
        "anchor_name": str(room.get("owner_name") or "").strip(),
        "is_live": int(room.get("show_status") or 0) == 1 and int(room.get("videoLoop") or 0) == 0,
    }


async def _fetch_huya_cover(room_id: str) -> dict:
    api = (
        "https://mp.huya.com/cache.php?m=Live&do=profileRoom&showSecret=1"
        f"&roomid={quote(room_id, safe='')}"
    )
    resp = await http_client.get(
        api,
        timeout=_ADAPTER_COVER_HTTP_TIMEOUT,
        headers={
            "User-Agent": "Mozilla/5.0",
            "Referer": "https://www.huya.com/",
        },
    )
    resp.raise_for_status()
    data = (resp.json() or {}).get("data") or {}
    live_data = data.get("liveData") or {}
    profile = data.get("profileInfo") or {}
    avatar = str(live_data.get("avatar180") or profile.get("avatar180") or "").strip()
    live_status = live_data.get("liveStatus")
    is_live = (str(live_status).upper() == "ON") if live_status is not None else bool(live_data.get("screenshot"))
    return {
        "ok": True,
        "adapter": "huya",
        "cover_url": str(live_data.get("screenshot") or "").strip(),
        "avatar_url": avatar,
        "title": str(live_data.get("introduction") or "").strip(),
        "anchor_name": str(live_data.get("nick") or profile.get("nick") or "").strip(),
        "is_live": is_live,
    }


async def _fetch_kuaishou_cover(room_id: str) -> dict:
    # 复用 kuaishou.py 同款 __INITIAL_STATE__ 解析，但只读 poster/avatar，不取 playUrls。
    from curl_cffi.requests import AsyncSession

    url = f"https://live.kuaishou.com/u/{quote(room_id, safe='')}"
    async with AsyncSession(impersonate="chrome", timeout=_ADAPTER_COVER_HTTP_TIMEOUT) as session:
        resp = await session.get(url)
    if resp.status_code != 200:
        raise RuntimeError(f"kuaishou http {resp.status_code}")
    html = resp.text or ''
    match = re.search(r'<script>window\.__INITIAL_STATE__=(.*?);\(function\(\)\{var s;', html)
    if not match:
        return _adapter_cover_empty("kuaishou")
    raw = match.group(1)
    blocks = re.findall(r'(\{"liveStream".*?),"gameInfo', raw)
    if not blocks:
        return _adapter_cover_empty("kuaishou")
    obj = json.loads(blocks[0] + "}")
    live_stream = obj.get("liveStream") or {}
    author = obj.get("author") or {}
    poster = str(live_stream.get("poster") or live_stream.get("coverUrl") or "").strip()
    return {
        "ok": True,
        "adapter": "kuaishou",
        "cover_url": poster,
        "avatar_url": str(author.get("avatar") or author.get("headurl") or "").strip(),
        "title": str(live_stream.get("caption") or "").strip(),
        "anchor_name": str(author.get("name") or "").strip(),
        "is_live": bool(live_stream),
    }


_ADAPTER_COVER_FETCHERS = {
    "bilibili": _fetch_bilibili_cover,
    "douyu": _fetch_douyu_cover,
    "huya": _fetch_huya_cover,
    "kuaishou": _fetch_kuaishou_cover,
}


# ── 封面图片代理（绕过 CDN Referer 防盗链）──────────────────────────────
# 白名单：仅允许代理这些域名下的图片，防止被当作公共代理滥用。
# 格式: {域名后缀: 需要伪造的 Referer}
_COVER_IMG_PROXY_SOURCES = {
    "hdslb.com": "https://www.bilibili.com",
    "bilibili.com": "https://www.bilibili.com",
}


def _cover_img_referer_for(raw_url: str) -> str:
    """命中白名单返回需要伪造的 Referer；否则返回空串。"""
    host = (urlparse(raw_url).hostname or "").lower()
    for suffix, ref in _COVER_IMG_PROXY_SOURCES.items():
        if host == suffix or host.endswith("." + suffix):
            return ref
    return ""


def _cover_img_proxy_url(raw_url: str) -> str:
    """如果 raw_url 命中防盗链白名单，返回 image handle 路径；否则原样返回。"""
    if not _cover_img_referer_for(raw_url):
        return raw_url
    from security.proxy_handles import issue_cached_handle as _issue
    handle = _issue(kind="image", url=raw_url, src="adapter:cover")
    return f"/api/media/proxy/image/{handle}"


async def fetch_adapter_cover_payload(adapter_url: str) -> dict:
    """供 /api/media/channel/{key}/cover 调用。返回封面 payload。"""
    try:
        request = parse_adapter_url(adapter_url)
    except AdapterResolveError:
        return _adapter_cover_empty()

    if not adapter_supports(request.adapter, "cover"):
        return _adapter_cover_empty(request.adapter)

    cache_key = request.raw_url
    cached = _adapter_cover_cache_get(cache_key)
    if cached is not None:
        return cached

    lock = _adapter_cover_locks.setdefault(cache_key, asyncio.Lock())
    async with lock:
        cached = _adapter_cover_cache_get(cache_key)
        if cached is not None:
            return cached

        fetcher = _ADAPTER_COVER_FETCHERS.get(request.adapter)
        if not fetcher:
            payload = _adapter_cover_empty(request.adapter)
            _adapter_cover_cache_set(cache_key, payload, _ADAPTER_COVER_FAILURE_TTL_SECONDS)
            return payload
        try:
            payload = await fetcher(request.resource_id.strip("/"))
            has_image = bool(str(payload.get("cover_url") or "").strip()) or bool(str(payload.get("avatar_url") or "").strip())
            ttl = _ADAPTER_COVER_SUCCESS_TTL_SECONDS if has_image else _ADAPTER_COVER_FAILURE_TTL_SECONDS
            for field in ("cover_url", "avatar_url"):
                raw = str(payload.get(field) or "").strip()
                if raw:
                    payload[field] = _cover_img_proxy_url(raw)
            _adapter_cover_cache_set(cache_key, payload, ttl)
            return payload
        except Exception as exc:
            logger.info("adapter cover fetch failed adapter=%s room=%s err=%s",
                        request.adapter, request.resource_id, exc)
            payload = _adapter_cover_empty(request.adapter)
            _adapter_cover_cache_set(cache_key, payload, _ADAPTER_COVER_FAILURE_TTL_SECONDS)
            return payload


# 旧 /api/iptv/adapter/cover / cover-img 入口已删除：
# 封面元数据走 /api/media/channel/{key}/cover；封面图片走 image handle。


# Header-level 全局元数据（出现在 playlist 头部一次的标签）。
# DISCONTINUITY / DISCONTINUITY-SEQUENCE / PROGRAM-DATE-TIME 是「跨 segment」标签，
# 必须按出现位置和顺序写入，不能放在头部，故此处不包含。
_HLS_META_TAGS = (
    "EXT-X-MAP",
    "EXT-X-KEY",
    "EXT-X-VERSION",
    "EXT-X-PLAYLIST-TYPE",
    "EXT-X-INDEPENDENT-SEGMENTS",
    "EXT-X-START",
    # RFC 8216 §4.3.3.3: DISCONTINUITY-SEQUENCE 只能在 playlist 头部出现一次，
    # 不是 per-segment。归到 meta（出现一次即可）。
    "EXT-X-DISCONTINUITY-SEQUENCE",
)

# 这些标签作用域是「下一个 segment」，要按位置插在 EXTINF 之前。
_HLS_PER_SEGMENT_PREFIX_TAGS = (
    "EXT-X-DISCONTINUITY",
    "EXT-X-PROGRAM-DATE-TIME",
    "EXT-X-BYTERANGE",
    "EXT-X-CUE-OUT",
    "EXT-X-CUE-IN",
    "EXT-X-CUE",
)


def _extract_hls_meta_lines(m3u8_text: str, base_url: str, ctx_id: str, src_id: str, src_label: str, *, access_token: str = "", proxy_ts: int = 1) -> list[str]:
    """Extract metadata lines (MAP, KEY, VERSION, etc.) from m3u8 text, rewritten as signed-handle URLs."""
    meta = []
    for line in m3u8_text.splitlines():
        stripped = line.strip()
        if not stripped.startswith('#'):
            continue
        upper = stripped.upper()
        for tag in _HLS_META_TAGS:
            if upper.startswith(f'#{tag}:'):
                meta.append(_rewrite_hls_tag_uri(line, base_url, ctx_id, src_id, src_label, access_token=access_token, proxy_ts=proxy_ts))
                break
            if upper == f'#{tag}':
                # 无值标签（如 #EXT-X-INDEPENDENT-SEGMENTS）
                meta.append(line)
                break
    return meta


def _is_per_segment_prefix_tag(line: str) -> bool:
    upper = line.strip().upper()
    if not upper.startswith('#'):
        return False
    body = upper[1:]
    for tag in _HLS_PER_SEGMENT_PREFIX_TAGS:
        if body == tag or body.startswith(f'{tag}:'):
            return True
    return False


def _parse_live_segments(text: str, base_url: str) -> tuple[list[dict], int, int]:
    """从 m3u8 文本中提取 segment 列表，并保留每段前置标签（DISCONTINUITY 等）。

    返回 ``(segments, target_duration, last_media_seq)``。每个 segment dict::

        {"url": <abs upstream url>, "dur": "8.080",
         "seq": <媒体序号>, "prefix_tags": [<原文 #EXT-X-...>...]}
    """
    segments: list[dict] = []
    target_duration = 6
    media_seq = 0
    pending_tags: list[str] = []
    lines = text.splitlines()
    i = 0
    while i < len(lines):
        raw = lines[i]
        line = raw.strip()
        upper = line.upper()
        if upper.startswith('#EXT-X-TARGETDURATION:'):
            try:
                target_duration = int(line.split(':', 1)[1].split(',', 1)[0])
            except Exception:
                pass
        elif upper.startswith('#EXT-X-MEDIA-SEQUENCE:'):
            try:
                media_seq = int(line.split(':', 1)[1].split(',', 1)[0])
            except Exception:
                pass
        elif _is_per_segment_prefix_tag(line):
            pending_tags.append(raw.rstrip())
        elif upper.startswith('#EXTINF:'):
            dur = line.split(':', 1)[1].rstrip(',')
            seg_url = ''
            j = i + 1
            # 跳过 EXTINF 与 URL 之间可能出现的注释/扩展标签
            while j < len(lines):
                nxt = lines[j].strip()
                if not nxt:
                    j += 1
                    continue
                if nxt.startswith('#'):
                    if _is_per_segment_prefix_tag(nxt):
                        pending_tags.append(lines[j].rstrip())
                    j += 1
                    continue
                seg_url = nxt
                break
            if seg_url:
                abs_url = urljoin(base_url, seg_url)
                segments.append({
                    'dur': dur,
                    'url': abs_url,
                    'seq': media_seq,
                    'prefix_tags': pending_tags,
                })
                pending_tags = []
                media_seq += 1
                i = j
        i += 1
    return segments, target_duration, media_seq


async def _wide_refresher(cache_key: str, target_url: str, ctx_id: str, src_id: str, src_label: str):
    """后台任务：按 target_duration 自适应频率拉上游 playlist，更新分片队列。

    上游 header 由 ProxyContext (按 ctx_id 索引) 提供；access_token 在生成
    response 阶段由 wide_playlist 调用方按需注入，refresher 不持有该 token。
    """
    from security.proxy_context import get_registry as _get_registry
    ctx = _get_registry().get(ctx_id) if ctx_id else None
    _h: dict[str, str] = {}
    if ctx:
        if ctx.no_ua:
            if ctx.custom_ua:
                _h['User-Agent'] = ctx.custom_ua
        elif ctx.custom_ua:
            _h['User-Agent'] = ctx.custom_ua
        if ctx.referer:
            _h['Referer'] = ctx.referer
        if ctx.cookie:
            _h['Cookie'] = ctx.cookie
    # 直播 m3u8 不要被中间层缓存，且我们处理 raw 文本，不要 gzip。
    _h.setdefault('Accept-Encoding', 'identity')
    while True:
        cache = _wide_cache.get(cache_key)
        _consec_error_key = cache_key + '_err'
        last_access = _wide_cache.get(cache_key + '_ts', 0)
        if not cache:
            return
        if time.time() - last_access > _WIDE_TTL:
            _drop_wide_cache(cache_key)
            logger.info("IPTV wide playlist 后台刷新停止: idle %.0fs key=%s", time.time() - last_access, cache_key)
            return
        active_target_url = cache.get('target_url') or target_url

        try:
            resp = await http_client.get(active_target_url, follow_redirects=True, timeout=6, headers=_h)
            resp.raise_for_status()
            playlist_base_url = str(resp.url)
            segments, target_duration, _ = _parse_live_segments(resp.text, playlist_base_url)

            # Extract and rewrite metadata lines (MAP, KEY, etc.) — refresher 不带 access_token，
            # 重写后的 meta 由响应阶段按需附加；此处生成的 path 不含 access_token，
            # 调用方在写入 cache 后由响应阶段做一次覆盖（细节：response 阶段重新跑 _rewrite_meta_with_token）。
            meta_lines = _extract_hls_meta_lines(resp.text, playlist_base_url, ctx_id, src_id, src_label, proxy_ts=1)

            cache = _wide_cache.get(cache_key)
            if not cache:
                return
            cache['last_refresh_at'] = time.time()
            cache['stale_since'] = 0
            cache['target_duration'] = target_duration
            # 成功刷新 → 重置连续失败计数
            _wide_cache[cache_key + '_err'] = 0
            if meta_lines:
                cache['meta'] = meta_lines
            cache['base_url'] = playlist_base_url
            cache['raw_meta_text'] = resp.text  # 缓存原文，响应阶段按 token 重写
            # 上游有些频道（如福建 qznews）会循环复用 0.ts/1.ts/... 文件名，
            # 内容随 MEDIA-SEQUENCE 变化。**只用 URL 去重会让 refresher 永远丢掉
            # 后续段**，sequence 永远卡在第一次见到的队尾。这里以「比当前队尾大
            # 的 seq」为追加门槛。
            #
            # 但还有一种真实场景需要照顾：上游直播流被中断后重启（CDN 切换、
            # 编码器重启），新一轮 MEDIA-SEQUENCE 会从一个比当前 tail 小很多的
            # 值重新开始。如果一直靠 ``seg.seq > tail`` 跳过，整个 queue 会冻结，
            # 直到 stale_grace 过期才被清掉，造成 30-90s 的假冻结窗口。
            # 检测条件：上游 playlist 头部 MEDIA-SEQUENCE 比我们记下的 tail_seq
            # 还小很多（差距 > _WIDE_WINDOW * 2），认为是 reset，清空 queue。
            queue = cache['queue']
            current_tail_seq = queue[-1]['seq'] if queue else -1
            upstream_head_seq = segments[0]['seq'] if segments else -1
            if (
                queue
                and upstream_head_seq >= 0
                and upstream_head_seq < current_tail_seq - (_WIDE_WINDOW * 2)
            ):
                logger.warning(
                    "IPTV wide playlist 检测到上游 sequence 重置: tail=%d upstream_head=%d key=%s",
                    current_tail_seq,
                    upstream_head_seq,
                    cache_key,
                )
                queue.clear()
                current_tail_seq = -1
            for seg in segments:
                if seg['seq'] > current_tail_seq:
                    queue.append(seg)
                    current_tail_seq = seg['seq']
            while len(queue) > _WIDE_WINDOW:
                queue.popleft()
            # 维护与 queue 一致的 seen（仅作向后兼容，不再参与去重判定）
            cache['seen'] = {s['url'] for s in queue}
        except Exception as exc:
            cache = _wide_cache.get(cache_key)
            if cache:
                now = time.time()
                if not cache.get('stale_since'):
                    cache['stale_since'] = now
                last_log = float(cache.get('last_refresh_log_at') or 0)
                if now - last_log >= _WIDE_REFRESH_LOG_INTERVAL:
                    logger.warning(
                        "IPTV wide playlist 后台刷新失败，暂时保留旧缓存: key=%s error=%s",
                        cache_key,
                        exc,
                    )
                    cache['last_refresh_log_at'] = now
        # 自适应：按 target_duration 折算，避免对 8s targetDuration 的源 2s 一刷的过密流量。
        cache_now = _wide_cache.get(cache_key) or {}
        sleep_for = _wide_refresh_interval_for(cache_now.get('target_duration', 6))
        await asyncio.sleep(sleep_for)


def release_iptv_wide_playlist_by_key(cache_key: str) -> bool:
    """供 router 调用的稳定 cache_key 释放接口。"""
    if not cache_key:
        return False
    released = cache_key in _wide_cache or cache_key + '_ts' in _wide_cache
    _drop_wide_cache(cache_key)
    return released


def _wide_cache_key_for(upstream_url: str, ctx_id: str, *, source_id: str = "", source_revision: str = "") -> str:
    """稳定 cache key：source/config scope + playlist identity + ctx_id。

    不使用 signed handle 当 cache key（每次签发都不同），避免缓存反复失效。

    fjtv 等 adapter 每次 resolve 带不同的 ``_upt`` / session token，导致
    upstream_url 次次换，cache_key 跟着换，刚建起来的 wide cache + 后台
    refresher 立刻被孤立成 dead entry。这里只取 scheme://netloc/path 作为
    playlist 层级，query（含动态 token）不参与 cache key；source_revision
    负责源配置变更时主动切到新缓存。
    """
    parsed = urlparse(upstream_url)
    stable_url = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
    parts = [
        source_id or "",
        source_revision or "",
        stable_url,
        ctx_id or "",
    ]
    return quote("\x1f".join(parts), safe='')


async def serve_iptv_wide_playlist_by_source(
    *,
    upstream_url: str,
    ctx_id: str,
    src_label: str,
    canonical_key: str,
    source_id: str = "",
    source_revision: str = "",
    access,
):
    """供 ``routers/media_proxy.py`` 调用：按上游 URL + ctx_id 拉播放列表。

    内部维护稳定 cache_key + 后台刷新任务。重写产物使用 signed handle，
    并按 ``access`` 是否来自 Media Credential 决定是否透传 access_token。
    """
    from security.proxy_context import get_registry as _get_registry

    if urlparse(upstream_url).scheme.lower() not in ("http", "https"):
        raise HTTPException(status_code=400, detail="上游 scheme 不被允许")
    # 第一次拉上游必须跑 SSRF 校验。adapter 解析后的 URL 进入这里之前并没有
    # 别的拦截层；后续 chunk/playlist 各自的子路由有 _validate_handle_url_or_403
    # 兜底，但这里是入口，直接 fetch 之前必须挡一次。
    try:
        await assert_safe_target_url(upstream_url, allowed_schemes={"http", "https"})
    except UnsafeTargetError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc

    ctx = _get_registry().get(ctx_id) if ctx_id else None
    _headers: dict[str, str] = {}
    if ctx:
        if ctx.no_ua:
            if ctx.custom_ua:
                _headers['User-Agent'] = ctx.custom_ua
        elif ctx.custom_ua:
            _headers['User-Agent'] = ctx.custom_ua
        if ctx.referer:
            _headers['Referer'] = ctx.referer
        if ctx.cookie:
            _headers['Cookie'] = ctx.cookie
    _headers.setdefault('Accept-Encoding', 'identity')
    source_ref = source_id or f"channel:{canonical_key}"
    cache_scope = f"{source_ref}:{source_revision or ''}"

    if not WIDE_ENABLED:
        # ── 薄韧性直通路径（非扩窗）─────────────────────────────
        text, final_url = await _thin_playlist_fetch(upstream_url, _headers, cache_scope=cache_scope)
        from core.m3u8_rewriter import RewriteContext as _RC, rewrite_m3u8 as _rw
        rewrite_ctx = _RC(
            base_url=final_url,
            src_id=source_ref,
            src_label=src_label,
            ctx_id=ctx_id,
            propagated_access_token=access.propagated_access_token or "" if access else "",
            proxy_segments=True,
        )
        body = _rw(text, rewrite_ctx)
        return Response(
            content=body,
            media_type="application/x-mpegURL",
            headers={"Cache-Control": "no-cache, no-store, must-revalidate"},
        )
    # ── 扩窗路径（WIDE_ENABLED=True）───────────────────────────

    access_token = access.propagated_access_token or "" if access else ""
    src_id = source_ref
    cache_key = _wide_cache_key_for(upstream_url, ctx_id, source_id=source_ref, source_revision=source_revision)

    def _rewrite_ts(seg_url: str, seg_seq: int = -1) -> str:
        if not _should_proxy_iptv_chunk(seg_url, 1):
            return seg_url
        # 上游若复用 segment 文件名（如 0.ts/1.ts/...），仅靠 url 作为 handle cache
        # key 会让连续不同 sequence 都映射到同一个 handle URL；hls.js 把它当作
        # 重复段去重，导致缺帧 / bufferStalled。把 seq 注入上游 URL 的 query，
        # CDN 一般忽略未知 query 参数，但我们的 handle 就能按 seq 区分。
        upstream_with_seq = seg_url
        if seg_seq >= 0:
            sep = '&' if urlparse(seg_url).query else '?'
            upstream_with_seq = f'{seg_url}{sep}wf_seq={seg_seq}'
        return _iptv_chunk_handle_path(upstream_with_seq, ctx_id, src_id, src_label, access_token)

    def _emit_segment_lines(seg: dict) -> list[str]:
        out: list[str] = []
        for tag in seg.get('prefix_tags') or ():
            out.append(tag)
        out.append(f'#EXTINF:{seg["dur"]},')
        out.append(_rewrite_ts(seg['url'], seg.get('seq', -1)))
        return out

    if cache_key not in _wide_cache:
        from collections import deque
        queue = deque(maxlen=_WIDE_WINDOW)
        seen = set()
        target_dur = 6

        playlist_base_url = upstream_url
        last_text = ""
        for attempt in range(4):
            try:
                resp = await http_client.get(upstream_url, follow_redirects=True, timeout=8, headers=_headers)
                resp.raise_for_status()
                playlist_base_url = str(resp.url)
                last_text = resp.text
                fresh_segs, fresh_target, _ = _parse_live_segments(resp.text, playlist_base_url)
                if fresh_target:
                    target_dur = fresh_target
                tail_seq = queue[-1]['seq'] if queue else -1
                for seg in fresh_segs:
                    if seg['seq'] > tail_seq:
                        queue.append(seg)
                        seen.add(seg['url'])
                        tail_seq = seg['seq']
            except Exception:
                pass
            if attempt < 3:
                await asyncio.sleep(0.3)

        meta_lines = _extract_hls_meta_lines(last_text, playlist_base_url, ctx_id, src_id, src_label, access_token=access_token, proxy_ts=1) if last_text else []

        cache = {
            'queue': queue,
            'seen': seen,
            'target_duration': target_dur,
            'meta': meta_lines,
            'base_url': playlist_base_url,
            'raw_meta_text': last_text,
            'target_url': upstream_url,
            'last_refresh_at': time.time(),
            'stale_since': 0,
            'last_refresh_log_at': 0,
        }
        _wide_cache[cache_key] = cache
        _wide_cache[cache_key + '_ts'] = time.time()
        asyncio.create_task(_wide_refresher(cache_key, upstream_url, ctx_id, src_id, src_label))

        if queue:
            first_seq = queue[0]["seq"]
            out_lines = [
                '#EXTM3U', '#EXT-X-VERSION:3',
                f'#EXT-X-TARGETDURATION:{target_dur}',
                f'#EXT-X-MEDIA-SEQUENCE:{first_seq}',
            ]
            for m in meta_lines:
                if not m.upper().startswith('#EXT-X-VERSION:'):
                    out_lines.append(m)
            for seg in queue:
                out_lines.extend(_emit_segment_lines(seg))
            content = '\n'.join(out_lines)
            return Response(content=content, media_type="application/x-mpegURL",
                headers={'Cache-Control': 'no-cache, no-store, must-revalidate'})
        # 没拿到 segment（可能是 master playlist），直接重写转发
        try:
            resp = await http_client.get(upstream_url, follow_redirects=True, timeout=8, headers=_headers)
            _ensure_hls_playlist_text(resp.text, str(resp.url))
            rewritten = _rewrite_iptv_wide_m3u8_text(resp.text, str(resp.url), ctx_id, src_id, src_label, access_token=access_token, proxy_ts=1)
            return Response(
                content=rewritten,
                media_type="application/x-mpegURL",
                headers={'Cache-Control': 'no-cache, no-store, must-revalidate'},
            )
        except httpx.HTTPError as exc:
            raise HTTPException(status_code=502, detail=f"拉取失败: {exc}") from exc

    # 命中缓存：返回扩展窗口 playlist。重写时根据当前请求的 access_token 重生成（meta + chunk）
    _wide_cache[cache_key + '_ts'] = time.time()
    cache = _wide_cache[cache_key]
    cache['target_url'] = upstream_url
    target_dur = cache.get('target_duration', 6)
    stale_since = float(cache.get('stale_since') or 0)
    if stale_since and time.time() - stale_since > _wide_stale_grace_for(target_dur):
        _drop_wide_cache(cache_key)
        # 用 503 显式告诉前端「上游暂不可用」，hls.js 在 levelLoadError 上会重试，
        # 不会立刻把整个播放器 destroy 掉。
        raise HTTPException(status_code=503, detail="直播 playlist 刷新失败，缓存已过期")
    queue = cache['queue']
    if not queue:
        # 队列为空（冷启动阶段上游 4 次尝试都失败）：直接释放缓存，让下一轮
        # 请求重新触发 adapter resolve + 新的缓存 + 新的后台 refresher，
        # 不再走「每次直接取一次上游但不持久」的 half-baked 路径。
        # 这里抛 503 告诉 hls.js 暂时不可用；hls.js 的 levelLoadError 会重试，
        # 重试时 cache_key 已不在 _wide_cache，就会进入带 4 次重试的冷启动。
        _drop_wide_cache(cache_key)
        raise HTTPException(status_code=503, detail="直播 playlist 队列未就绪，请稍后重试")

    base_url = cache.get('base_url') or upstream_url
    raw_meta_text = cache.get('raw_meta_text') or ""
    meta_lines = _extract_hls_meta_lines(raw_meta_text, base_url, ctx_id, src_id, src_label, access_token=access_token, proxy_ts=1) if raw_meta_text else []
    out_lines = [
        '#EXTM3U',
        '#EXT-X-VERSION:3',
        f'#EXT-X-TARGETDURATION:{target_dur}',
        f'#EXT-X-MEDIA-SEQUENCE:{queue[0]["seq"]}',
    ]
    for m in meta_lines:
        if not m.upper().startswith('#EXT-X-VERSION:'):
            out_lines.append(m)
    for seg in queue:
        out_lines.extend(_emit_segment_lines(seg))
    content = '\n'.join(out_lines)
    return Response(
        content=content,
        media_type="application/x-mpegURL",
        headers={'Cache-Control': 'no-cache, no-store, must-revalidate'},
    )


# ── RTSP 代理内部入口（公共路由由 routers/media_proxy.py 提供）──


async def serve_rtsp_playlist_response(
    *,
    upstream_url: str,
    custom_ua: str = "",
    compat: bool = False,
) -> FileResponse:
    """供 media_proxy router 调用的 RTSP 内部入口。

    handle payload 已通过 SSRF 校验，此处不再做 URL 校验。
    """
    if not upstream_url:
        raise HTTPException(status_code=400, detail="缺少 target_url")
    try:
        session_id, playlist_path = await _ensure_rtsp_hls_session(upstream_url, custom_ua, compat=compat)
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


@app.get("/api/media/proxy/rtsp-segments/{session_id}/{filename}", dependencies=[Depends(require_media_access)])
async def media_proxy_rtsp_segment(session_id: str, filename: str):
    """RTSP→HLS 本地分片（不签 handle，由 session_id 鉴权）。"""
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


async def serve_iptv_proxy_stream_response(
    *,
    request: Request,
    upstream_url: str,
    upstream_headers: dict[str, str],
    stream_type: str = "",
) -> StreamingResponse:
    """供 media_proxy router 调用的 MPEG-TS/FLV 流代理。

    handle payload 已通过 SSRF 校验，reconnect 内部直接使用上游 URL。
    """
    parsed = urlparse(upstream_url)
    headers = {
        "User-Agent": upstream_headers.get("User-Agent", CDN_REQUEST_HEADERS["User-Agent"]),
        "Accept": "*/*",
        "Connection": "keep-alive",
        "Referer": upstream_headers.get("Referer", f"{parsed.scheme}://{parsed.netloc}/"),
        # 与 chunk 路径一致：强制 identity，避免 httpx 默认 gzip,br 在 mpegts/flv
        # 长连接上把 Content-Encoding 误标。下游不需要解码。
        "Accept-Encoding": "identity",
    }
    if upstream_headers.get("Cookie"):
        headers["Cookie"] = upstream_headers["Cookie"]

    stream_timeout = httpx.Timeout(None, connect=10.0, read=IPTV_STREAM_READ_TIMEOUT_SECONDS)
    stream_client = httpx.AsyncClient(
        timeout=stream_timeout,
        follow_redirects=True,
        verify=CDN_VERIFY_SSL,
    )

    async def open_upstream() -> httpx.Response:
        req = stream_client.build_request("GET", upstream_url, headers=headers)
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
                    "IPTV stream 上游 Content-Length 较小: %s bytes url=%s",
                    length,
                    upstream_url,
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
                    # identity 编码（headers 已声明），用 aiter_raw 跳过 httpx 解码层。
                    async for chunk in upstream.aiter_raw():
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
                        "IPTV stream 上游短连接结束: reason=%s bytes=%s elapsed=%.2fs url=%s",
                        close_reason,
                        bytes_this_connection,
                        elapsed,
                        upstream_url,
                    )
                else:
                    logger.info(
                        "IPTV stream 上游连接结束，准备重连: reason=%s bytes=%s elapsed=%.2fs",
                        close_reason,
                        bytes_this_connection,
                        elapsed,
                    )

                if bytes_this_connection == 0:
                    no_data_retries += 1
                    no_data_age = time.monotonic() - last_data_at
                    if no_data_retries >= IPTV_STREAM_NO_DATA_RETRIES or no_data_age > IPTV_STREAM_NO_DATA_TIMEOUT_SECONDS:
                        logger.warning(
                            "IPTV stream 上游连续无数据，结束代理流: retries=%s no_data_age=%.2fs url=%s",
                            no_data_retries,
                            no_data_age,
                            upstream_url,
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
                            "IPTV stream 上游重连失败: retries=%s no_data_age=%.2fs error=%s url=%s",
                            no_data_retries,
                            no_data_age,
                            exc,
                            upstream_url,
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
            if upstream is not None:
                await upstream.aclose()
                upstream = None
            await stream_client.aclose()

    stream_kind = (stream_type or "").strip().lower()
    media_type = "video/x-flv" if stream_kind == "http_flv" else "video/MP2T"

    return StreamingResponse(
        stream_bytes(),
        media_type=media_type,
        headers={
            "Cache-Control": "no-cache, no-store, must-revalidate",
            "Access-Control-Allow-Origin": "*",
        },
    )


def config_rtsp_proxy_enabled() -> bool:
    """供 media_proxy router 同步查询当前 RTSP 策略。"""
    from core.settings_service import get_effective_settings_sync
    return get_effective_settings_sync().enable_rtsp_proxy


# ── EPG ──

import epg as _epg


@app.post("/api/admin/epg/sources", dependencies=[Depends(require_admin)])
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


@app.get("/api/admin/epg/sources", dependencies=[Depends(require_admin)])
async def list_epg_sources():
    return await db.get_epg_sources()


@app.delete("/api/admin/epg/sources/{source_id}", dependencies=[Depends(require_admin)])
async def delete_epg_source(source_id: int):
    await db.delete_epg_source(source_id)
    return {"ok": True}


@app.post("/api/admin/epg/refresh", dependencies=[Depends(require_admin)])
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


@app.get("/api/iptv/epg/programs/{canonical_key}", dependencies=[Depends(require_browse_access)])
async def get_epg_programs(canonical_key: str, date: str = '', tz: str = ''):
    em = await db.get_channel_epg_map(canonical_key)
    try:
        comparison = await epg_read_resolver.resolve_epg_read(
            canonical_key,
            legacy_mapping=em,
        )
        epg_read_resolver.emit_epg_read_diagnostic(comparison, context='programme')
    except Exception as exc:
        # EPG-2F-a is diagnostic-only. Shadow resolution must never alter or
        # break the legacy production programme path.
        epg_read_resolver.emit_epg_read_resolver_error(context='programme', error=exc)
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


@app.post("/api/iptv/epg/batch-current", dependencies=[Depends(require_browse_access)])
async def batch_current_programs(request: Request):
    body = await request.json()
    keys = body.get('canonical_keys', [])
    if not keys:
        return {}
    return await db.batch_get_current_programs(keys)


@app.put("/api/admin/epg/bind/{canonical_key}", dependencies=[Depends(require_admin)])
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


@app.delete("/api/admin/epg/bind/{canonical_key}", dependencies=[Depends(require_admin)])
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


@app.get("/api/iptv/epg/match-status", dependencies=[Depends(require_browse_access)])
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

    declared = str(source.get('source_type') or '').strip().lower()
    if declared and declared != 'hls':
        return declared
    return detect_source_type(source.get('url', ''))


def _sorted_sources(sources: list[dict]) -> list[dict]:
    def _health_rank(source: dict) -> int:
        status = str(source.get("probe_status") or "").strip().lower()
        if source.get("is_working") == 1 or status == "online":
            return 0
        if status in {"", "untested", "unknown", "pending"} or source.get("is_working") in {-1, None}:
            return 1
        return 2

    return sorted(sources, key=lambda u: (
        _health_rank(u),
        u.get('latency_ms') or 9999,
        -(u.get('speed_mbps') or 0),
    ))


def _is_supported_export_source(source: dict, healthy_only: bool = True) -> bool:
    if not source.get('url'):
        return False
    if not _truthy_query(source.get('enabled', True)):
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
    """用于 M3U 导出：按 source 的 canonical_key 生成 media API 入口。

    不再把 raw upstream URL / Header 明文编入 query。
    导出的 .m3u 中每条频道地址都是：

        /api/media/channel/{canonical_key}/playlist.m3u8

    外部播放器通过 ``?access_token=wbm_...`` 传递 Media Credential。
    canonical_key 从频道聚合表中取，source dict 上没有该字段时回退到
    旧 ``source['url']`` 产生一个 channel-key-hash 的中间入口（极少触发）。
    """
    canonical_key = str(source.get('canonical_key') or '')
    if not canonical_key:
        # 极少数 source 脱离了聚合上下文（不到一轮）；回退到按 url hash 的入口
        import hashlib
        canonical_key = "src_" + hashlib.sha256(
            str(source.get('url') or '').encode()
        ).hexdigest()[:20]
    return f"/api/media/channel/{quote(canonical_key, safe='')}/playlist.m3u8"


def _iptv_proxy_url_for_source(source: dict, request: Request, *, access: object | None = None) -> str:
    """对外 URL + 可选 Media Credential 附加。

    ``access`` 应为 ``MediaAccessContext``（仅在确认为 credential 时透传 token）。
    """
    base = _absolute_api_url(request, _iptv_proxy_path_for_source(source))
    token = getattr(access, 'propagated_access_token', None) or ""
    if not token:
        return base
    return f"{base}?access_token={quote(token, safe='')}"


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


def _format_m3u_options(source: dict | None) -> list[str]:
    """为单条原始 url 生成 EXTVLCOPT/KODIPROP/WAVEFLOW 行。

    Referer / Custom UA 双写：EXTVLCOPT 给 VLC，KODIPROP:stream_headers 给 Kodi。
    KODIPROP 值要 url-encode，EXTVLCOPT 是裸值。
    """
    if not source:
        return []
    ref = str(source.get('referer') or '').strip()
    ua = str(source.get('custom_ua') or '').strip()
    force_proxy = bool(source.get('force_proxy'))
    out: list[str] = []
    if ref:
        out.append(f'#EXTVLCOPT:http-referrer={ref}')
    if ua:
        out.append(f'#EXTVLCOPT:http-user-agent={ua}')
    # KODIPROP stream_headers 把所有 header 拼成 url-encoded form
    if ref or ua:
        kodi_parts = []
        if ref:
            kodi_parts.append(f'Referer={quote(ref, safe="")}')
        if ua:
            kodi_parts.append(f'User-Agent={quote(ua, safe="")}')
        out.append(f'#KODIPROP:inputstream.adaptive.stream_headers={"&".join(kodi_parts)}')
    if force_proxy:
        out.append('#WAVEFLOW:requires_proxy=1')
    return out


def _subscription_urls_for_channel(
    channel: dict, mode: str, request: Request, healthy_only: bool, include_rtsp: bool, *, access: object = None
) -> list[tuple[str, dict | None]]:
    """返回 [(url, source_for_options), ...]。

    source_for_options 不为 None 时，表示这条 url 是裸的原始流地址，
    导出 m3u 时需要附加 EXTVLCOPT/KODIPROP/WAVEFLOW（让 VLC/Kodi 直连也能播）。
    为 None 时，表示这条 url 已经是 proxy/adapter/smart 包装地址，
    所有 header / proxy 语义已经编码到 url 内部，不需要也不能再附加注解。
    """
    sources = _sorted_sources([
        source for source in channel.get('urls', [])
        if _is_supported_export_source(source, healthy_only=healthy_only)
    ])

    if mode == 'smart':
        if sources:
            return [(_absolute_api_url(request, f'/api/iptv/smart/{quote(channel["canonical_key"], safe="")}.m3u8'), None)]
        return []

    if mode == 'direct':
        out: list[tuple[str, dict | None]] = []
        for source in sources:
            if _source_type(source) == 'adapter':
                continue
            if not include_rtsp and _source_type(source) == 'rtsp':
                continue
            # direct 模式下保留 referer/custom_ua 的源——它们靠 EXTVLCOPT 直连
            if source.get('force_proxy') or source.get('proxy_required_hint'):
                continue
            out.append((source['url'], source))
        return out

    if mode == 'proxy':
        return [(_iptv_proxy_url_for_source(source, request, access=access), None) for source in sources]

    direct_sources = []
    proxy_only_sources = []
    for source in sources:
        source_type = _source_type(source)
        if source_type in {'adapter', 'rtsp'} or source.get('force_proxy') or source.get('proxy_required_hint'):
            proxy_only_sources.append(source)
        else:
            direct_sources.append(source)

    out: list[tuple[str, dict | None]] = []
    out.extend((source['url'], source) for source in direct_sources)
    out.extend((_iptv_proxy_url_for_source(source, request, access=access), None) for source in direct_sources)
    out.extend((_iptv_proxy_url_for_source(source, request, access=access), None) for source in proxy_only_sources)
    return out


@app.get("/api/iptv/subscription.m3u")
async def export_iptv_subscription(
    request: Request,
    mode: str = 'hybrid',
    healthy_only: bool = True,
    include_rtsp: bool = False,
    include_epg: bool = True,
    include_logo: bool = True,
    groups: str = '',
    access: object = Depends(resolve_media_access),
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
        urls = _subscription_urls_for_channel(channel, mode, request, healthy, rtsp, access=access)
        if not urls:
            continue
        attrs = _m3u_attrs_for_channel(channel, include_epg=epg, include_logo=logo)
        for url, source_opts in urls:
            lines.append(f'#EXTINF:-1 {attrs},{channel["name"]}')
            lines.extend(_format_m3u_options(source_opts))
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


@app.get("/api/iptv/smart/{canonical_key}.m3u8", dependencies=[Depends(require_media_access)])
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
        # 把 canonical_key 注入 source dict，让 _iptv_proxy_path_for_source 能匹配
        source_with_key = {**source, "canonical_key": canonical_key}
        try:
            if source_type == 'rtsp':
                return await serve_rtsp_playlist_response(
                    upstream_url=source['url'],
                    custom_ua=source.get('custom_ua', ''),
                    compat=False,
                )
            if source_type in {'mpegts', 'http_flv'}:
                return RedirectResponse(_iptv_proxy_url_for_source(source_with_key, request), status_code=307)
            if source_type == 'adapter':
                return RedirectResponse(_iptv_proxy_url_for_source(source_with_key, request), status_code=307)
            # HLS: 直接通过 channel 入口渲染
            return RedirectResponse(
                f"/api/media/channel/{quote(canonical_key, safe='')}/playlist.m3u8",
                status_code=307,
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
