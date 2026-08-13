import json
import logging
import os
import re
from collections.abc import Awaitable, Callable
import asyncio
import httpx



StationFetcher = Callable[[], Awaitable[str]]

logger = logging.getLogger("waveflow.fetchers")


import os
import httpx

DEFAULT_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/147.0.0.0 Safari/537.36"
)

HICHANNEL_TIMEOUT = httpx.Timeout(10.0)

async def fetch_hichannel_engine(station_name: str, api_url: str, referer: str, origin: str, channel_id: str, cookie_env: str = None) -> str:
    headers = {
        "Accept": "*/*",
        "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
        "X-Requested-With": "XMLHttpRequest",
        "User-Agent": DEFAULT_UA,
        "Referer": referer,
        "Origin": origin,
    }
    
    if cookie_env:
        cookie = os.getenv(cookie_env, "").strip()
        if cookie:
            headers["Cookie"] = cookie

    payload = {"channelID": channel_id, "action": "getLIVEURL"}

    async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
        response = await client.post(api_url, headers=headers, data=payload)
    response.raise_for_status()
    real_url = response.text.strip()
    
    if not real_url.startswith(("http://", "https://")):
        raise ValueError(f"{station_name} 返回内容非有效 URL: {real_url[:50]}")

    #验证 CDN 连通性 (必须加上 verify=False，有些 CDN 证书链有问题)
    async with httpx.AsyncClient(timeout=10.0, follow_redirects=True, verify=False) as cdn_client:
        cdn_response = await cdn_client.get(real_url, headers={"User-Agent": DEFAULT_UA})
    cdn_response.raise_for_status()

    logger.info(f"[{station_name}] 抓取验证成功")
    return real_url

# =========================================
# Hit FM
# =========================================
async def hitfm_factory(name: str, cid: str) -> str:
    return await fetch_hichannel_engine(
        station_name=f"HitFM {name}",
        api_url="https://www.hitoradio.com/newweb/hichannel.php",
        referer="https://www.hitoradio.com/newweb/onair_n_ajax.php",
        origin="https://www.hitoradio.com",
        channel_id=cid,
        cookie_env="HITFM_COOKIE"
    )


async def fetch_hitfm():         return await hitfm_factory("台北", "1")
async def fetch_hitfm_taichung(): return await hitfm_factory("台中", "2")
async def fetch_hitfm_tainan():   return await hitfm_factory("台南", "3")
async def fetch_hitfm_yilan():    return await hitfm_factory("宜兰", "4")
async def fetch_hitfm_huadong():  return await hitfm_factory("花东", "5")

# =========================================
# POP Radio 91.7
# =========================================
async def fetch_pop917():
    return await fetch_hichannel_engine(
        station_name="POP Radio 91.7",
        api_url="https://www.pop917.com/ajax.aspx",
        referer="https://www.pop917.com/liveStream.aspx?id=1",
        origin="https://www.pop917.com",
        channel_id="1",
        cookie_env="POP917_COOKIE"
    )

# ==========================================
# tingfm.com 系列电台
# ==========================================

TINGFM_API_BASE = "https://api.tingfm.com/wp-json/query/wndt_streams"
TINGFM_TIMEOUT = httpx.Timeout(10.0)

async def fetch_tingfm(post_id: int) -> str:
    """tingfm 通用抓取器，传入 post_id 即可。"""
    params = {"post_id": post_id, "in_web": "true"}
    headers = {
        "Accept": "application/json",
        "Referer": "https://tingfm.com/",
        "Origin": "https://tingfm.com",
        "User-Agent": DEFAULT_UA,
    }

    async with httpx.AsyncClient(timeout=TINGFM_TIMEOUT, follow_redirects=True) as client:
        resp = await client.get(TINGFM_API_BASE, params=params, headers=headers)
    resp.raise_for_status()

    data = resp.json()
    streams = data.get("data", {}).get("streams", [])
    if not streams:
        raise ValueError(f"tingfm post_id={post_id} 无可用流地址")

    m3u8 = next((s for s in streams if s.get("type") == "m3u8"), None)
    chosen = m3u8 or max(streams, key=lambda s: s.get("priority", 0))
    url = chosen.get("url", "")

    if not url.startswith(("http://", "https://")):
        raise ValueError(f"tingfm post_id={post_id} 返回无效 URL: {url}")

    logger.info("tingfm post_id=%d 抓取成功（%s）", post_id, chosen.get("type"))
    return url


def tingfm(post_id: int) -> StationFetcher:
    """工厂函数：返回一个绑定了 post_id 的抓取闭包，用于注册到 STATION_FETCHER_MAP。"""
    async def _fetch() -> str:
        return await fetch_tingfm(post_id)
    return _fetch


# ==========================================
# 云听 (radio.cn) 系列电台
# ==========================================

YUNTING_API_BASE = "https://ytmsout.radio.cn/web/appBroadcast/list"
YUNTING_TIMEOUT = httpx.Timeout(15.0)
_YUNTING_SIGN_KEY = "f0fc4c668392f9f9a447e48584c214ee"


def _yunting_sign_headers(params: dict | None = None) -> dict:
    import hashlib, time as _time
    ts = str(int(_time.time() * 1000))
    sorted_params = "&".join(f"{k}={v}" for k, v in sorted((params or {}).items()))
    sign_text = (sorted_params + "&" if params else "") + "timestamp=" + ts + "&key=" + _YUNTING_SIGN_KEY
    sign = hashlib.md5(sign_text.encode()).hexdigest().upper()
    return {
        "User-Agent": DEFAULT_UA,
        "Accept": "application/json",
        "Content-Type": "application/json",
        "Origin": "https://www.radio.cn",
        "Referer": "https://www.radio.cn/",
        "equipmentId": "0000",
        "platformCode": "WEB",
        "timestamp": ts,
        "sign": sign,
    }


async def fetch_yunting(province_code: str, content_id: str) -> str:
    params = {"categoryId": 0, "provinceCode": province_code}

    async with httpx.AsyncClient(timeout=YUNTING_TIMEOUT, follow_redirects=True) as client:
        resp = await client.get(YUNTING_API_BASE, params=params, headers=_yunting_sign_headers(params))
    resp.raise_for_status()

    for item in resp.json().get("data", []):
        if str(item.get("contentId")) == str(content_id):
            url = item.get("playUrlLow", "")
            # 云听 API 返回 http://，HTTPS 页面会拦截混合内容，统一改为 https://
            if url.startswith("http://"):
                url = "https://" + url[7:]
            if url.startswith(("http://", "https://")):
                logger.info("云听 %s (%s) 抓取成功", item.get("title"), content_id)
                return url
            raise ValueError(f"云听 contentId={content_id} URL 格式异常: {url}")

    raise ValueError(f"云听省份 {province_code} 中未找到 contentId={content_id}")


def yunting(province_code: str, content_id: str) -> StationFetcher:
    async def _fetch() -> str:
        return await fetch_yunting(province_code, content_id)
    return _fetch


# ==========================================
# myradio.tw 系列电台
# ==========================================

MYRADIO_BASE = "https://myradio-dev.zeabur.app"
MYRADIO_TIMEOUT = httpx.Timeout(15.0)
_mr_sem = asyncio.Semaphore(5)
_myradio_build_id: str | None = None

async def resolve_myradio_url(client, url: str) -> str:
    """处理 myradio 的特殊 url 格式，解析成真实的 m3u8/mp3 地址"""
    if url.startswith(("http://", "https://")):
        return url
    if url.startswith("myPop"):
        station = url.split(":")[1]
        get_mypop_url = await client.post(
            "http://pop.olis.com.tw:8080/pop_api/index.php/Basic/GetHLS",
            data={"station": station},
        )
        return get_mypop_url.json()["data"]["hlsurl"][station]
    if url.startswith("myBest"):
        station = url.split(":")[1]
        get_mybest_url = await client.post(
            "http://best.olis.com.tw:8080/best_api/index.php/Basic/GetHLS",
            data={"station": station},
        )
        hls_url = get_mybest_url.json()["data"]["hlsurl"]
        if isinstance(hls_url, str):
            return hls_url.replace("http://", "https://", 1) if hls_url.startswith("http://") else hls_url
        return hls_url
    if url.startswith("myAline"):
        station = url.split(":")[1]
        try:
            if station == "1":
                get_aline_url = await client.get("https://ipget.apple-line.com/alinePlayer.php", verify=False)
            else:
                get_aline_url = await client.get("https://ipget.apple-line.com/youngPlayer.php", verify=False)
            return get_aline_url.text.strip()
        except Exception:
            logger.warning("A-Line Radio API 请求失败，使用备用 URL")
            if station == "1":
                return "http://aline.hichannel.com.tw:8080/3"
            return "http://aline.hichannel.com.tw:8080/young"


_MYRADIO_STATIC_PATH = os.path.join(os.path.dirname(__file__), "myradio_static.json")


def _load_myradio_static() -> list[dict]:
    """从本地 JSON 加载静态 URL 电台"""
    try:
        with open(_MYRADIO_STATIC_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data.get("static", [])
    except Exception:
        logger.warning("myradio 静态列表加载失败")
        return []


async def fetch_myradio_all() -> list[dict]:
    global _myradio_build_id

    # 1. 加载静态 URL 电台（不需要 API 调用）
    static_stations = []
    for item in _load_myradio_static():
        url = item.get("url", "")
        if url.startswith(("http://", "https://")):
            static_stations.append({
                "id": item["id"],
                "name": item["name"],
                "url": url,
                "logo": item.get("logo", f"https://images.myradio.com.tw/images/{item['id']}.jpg"),
                "freq": item.get("freq", ""),
                "tag": item.get("tag", ""),
                "codec": 0,
            })

    # 2. 获取动态 URL 电台（需要 API 调用）
    dynamic_ids = []
    try:
        sitemap_resp = httpx.get(f"{MYRADIO_BASE}/sitemap.xml", headers={"User-Agent": DEFAULT_UA}, timeout=MYRADIO_TIMEOUT)
        sitemap_resp.raise_for_status()
        all_ids = set(re.findall(r'<loc>https?://myradio\.com\.tw/radios/(A\d{4})</loc>', sitemap_resp.text))
        static_ids = {s["id"] for s in static_stations}
        dynamic_ids = list(all_ids - static_ids)
    except Exception:
        logger.warning("myradio sitemap 获取失败，尝试从静态列表的动态部分获取")
        try:
            with open(_MYRADIO_STATIC_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
            dynamic_ids = [item["id"] for item in data.get("dynamic", [])]
        except Exception:
            pass

    logger.info("myradio 静态: %d 个, 动态: %d 个", len(static_stations), len(dynamic_ids))

    # 3. 获取 buildId
    if dynamic_ids and not _myradio_build_id:
        try:
            resp = httpx.get(f"{MYRADIO_BASE}/zh-TW", headers={"User-Agent": DEFAULT_UA, "x-nextjs-data": "1"}, timeout=MYRADIO_TIMEOUT)
            m_build = re.search(r'"buildId"\s*:\s*"([^"]+)"', resp.text)
            if m_build:
                _myradio_build_id = m_build.group(1)
            else:
                _myradio_build_id = "NbGrNnycPXoV9eY5v4Kt-"
                logger.warning("myradio buildId 提取失败，使用硬编码兜底")
        except Exception:
            _myradio_build_id = "NbGrNnycPXoV9eY5v4Kt-"

    # 4. 获取动态电台数据
    dynamic_stations = []
    if dynamic_ids and _myradio_build_id:
        async with httpx.AsyncClient(timeout=MYRADIO_TIMEOUT, follow_redirects=True) as client:
            async def _fetch_one(sid: str) -> dict | None:
                async with _mr_sem:
                    try:
                        url = f"{MYRADIO_BASE}/_next/data/{_myradio_build_id}/zh-TW/radios/{sid}.json?id={sid}"
                        r = await client.get(url, headers={"User-Agent": DEFAULT_UA, "x-nextjs-data": "1"}, timeout=10)
                        r.raise_for_status()
                        radio = r.json()["pageProps"]["radio"]
                        real_url = await resolve_myradio_url(client, radio["url"])
                        logger.info("myradio %s url=%s", sid, real_url)
                        return {
                            "id": radio["id"],
                            "name": radio["name"],
                            "url": real_url,
                            "logo": f"https://images.myradio.com.tw/images/{radio['id']}.jpg",
                            "freq": radio.get("des", ""),
                            "tag": radio.get("tag", ""),
                            "codec": radio.get("codec", 0),
                        }
                    except Exception as exc:
                        logger.error("myradio %s 详情获取失败: %s", sid, exc)
                return None

            results = await asyncio.gather(*[_fetch_one(sid) for sid in dynamic_ids])
            dynamic_stations = [r for r in results if r]

    return static_stations + dynamic_stations


STATION_FETCHER_MAP: dict[str, StationFetcher] = {
    "hitfm": fetch_hitfm,
    "hitfm_taichung": fetch_hitfm_taichung,
    "hitfm_tainan": fetch_hitfm_tainan,
    "hitfm_yilan": fetch_hitfm_yilan,
    "hitfm_huadong": fetch_hitfm_huadong,
    "pop917": fetch_pop917,
    # "fj_traffic": tingfm(94),   # 福建交通广播 FM100.7
}
