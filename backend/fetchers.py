"""电台真实播放地址抓取器。

这个文件先使用“工厂模式”的轻量写法：
用一个字典把“电台 ID”映射到“对应的异步抓取函数”。
后续新增电台时，只需要新增一个 fetch_xxx 函数，并注册到 STATION_FETCHER_MAP。
"""

import json
import logging
import os
import re
from collections.abc import Awaitable, Callable
import asyncio
import random
import httpx


# 定义抓取函数的类型别名：
# 每个抓取函数都不接收参数，并且会异步返回一个字符串形式的 m3u8 播放地址。
StationFetcher = Callable[[], Awaitable[str]]

# 创建抓取器专用日志记录器。
# 后续 Docker 中可以通过 docker logs 查看真实抓取失败原因。
logger = logging.getLogger("wavebypass.fetchers")


import os
import httpx

# 统一的伪装浏览器标识
DEFAULT_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/147.0.0.0 Safari/537.36"
)

# 基础超时与配置
HICHANNEL_TIMEOUT = httpx.Timeout(10.0)

async def fetch_hichannel_engine(station_name: str, api_url: str, referer: str, origin: str, channel_id: str, cookie_env: str = None) -> str:
    """底层通用抓取引擎：只需传入配置，逻辑完全一致"""
    headers = {
        "Accept": "*/*",
        "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
        "X-Requested-With": "XMLHttpRequest",
        "User-Agent": DEFAULT_UA,
        "Referer": referer,
        "Origin": origin,
    }
    
    # 自动加载环境变量中的 Cookie
    if cookie_env:
        cookie = os.getenv(cookie_env, "").strip()
        if cookie:
            headers["Cookie"] = cookie

    payload = {"channelID": channel_id, "action": "getLIVEURL"}

    # 步骤 A：获取带 Token 的 m3u8 地址
    async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
        response = await client.post(api_url, headers=headers, data=payload)
    response.raise_for_status()
    real_url = response.text.strip()
    
    if not real_url.startswith(("http://", "https://")):
        raise ValueError(f"{station_name} 返回内容非有效 URL: {real_url[:50]}")

    # 步骤 B：验证 CDN 连通性 (必须加上 verify=False，有些 CDN 证书链有问题)
    async with httpx.AsyncClient(timeout=10.0, follow_redirects=True, verify=False) as cdn_client:
        cdn_response = await cdn_client.get(real_url, headers={"User-Agent": DEFAULT_UA})
    cdn_response.raise_for_status()

    logger.info(f"[{station_name}] 抓取验证成功")
    return real_url


async def hitfm_factory(name: str, cid: str) -> str:
    """Hit FM 专用工厂函数：自动填充 Hit FM 的共有配置"""
    return await fetch_hichannel_engine(
        station_name=f"HitFM {name}",
        api_url="https://www.hitoradio.com/newweb/hichannel.php",
        referer="https://www.hitoradio.com/newweb/onair_n_ajax.php",
        origin="https://www.hitoradio.com",
        channel_id=cid,
        cookie_env="HITFM_COOKIE"
    )

# 这样你的分台定义就变成了真正的“一行代码”
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
# 泉州无线 APP 系列电台通用抓取逻辑
# ==========================================

QZTV_API_URL = "https://wxqz2.qztv.cn/api/media/info"

QZTV_HEADERS = {
    "Host": "wxqz2.qztv.cn",
    "Accept": "*/*",
    "Content-Type": "application/x-www-form-urlencoded",
    "User-Agent": "QZWireless/20241122 CFNetwork/3860.500.112 Darwin/25.4.0",
}

QZTV_PAYLOAD_TEMPLATE = {
    "app_version": "3.3.4",
    "channel_type": "ios",
    "imei": "6EF23893-9A3E-4C0C-B124-05EA6AFA6EAC",
    "os_version": "26.4.2",
    "device_model": "iPhone17,2",
    "user_id": "",
    "session_id": "",
    "radio_id": "",  # 默认设为空，兼容前面的 88.9 和 90.4
}

QZTV_TIMEOUT = httpx.Timeout(10.0)
 
async def fetch_qztv_base(media_id: str, skin: str, station_name: str, radio_id: str = "") -> str:
    """泉州台底层通用抓取引擎"""
    
    # 【核心防御】：随机休眠 5 到 15 秒。
    # 这样如果有 4 个台同时触发刷新任务，它们会被打散在不同的时间点发出去，完美避开 WAF 的瞬时并发检测。
    await asyncio.sleep(random.uniform(5.0, 15.0))
    
    payload = QZTV_PAYLOAD_TEMPLATE.copy()
    payload["media_id"] = media_id
    payload["skin"] = skin
    payload["radio_id"] = radio_id  # 把 radio_id 也塞进去
    
    async with httpx.AsyncClient(timeout=QZTV_TIMEOUT, verify=False) as client:
        response = await client.post(QZTV_API_URL, headers=QZTV_HEADERS, data=payload)
    
    # 【核心调试】：如果不是 200，立刻把服务器返回的真实内容打出来，让我们看看是不是 WAF 的脸
    if response.status_code != 200:
        logger.error(f"[{station_name}] 遭遇非 200 响应！状态码: {response.status_code}, 内容: {response.text}")
        
    response.raise_for_status()
    
    try:
        data = response.json()
        if data.get("error_code") != 0:
             raise ValueError(f"{station_name} API 业务报错: {data}")
        real_url = data["data"]["media_info"]["video_path"]
    except (ValueError, KeyError, TypeError) as e:
        logger.error("解析 %s API 返回 JSON 失败: %s", station_name, response.text)
        raise ValueError(f"无法提取 {station_name} 播放地址。") from e

    if not real_url.startswith(("http://", "https://")):
        raise ValueError(f"{station_name} 提取到的地址格式异常。")

    logger.info("%s 抓取成功：%s", station_name, real_url)
    return real_url
# -----------------------------
# 泉州台各频道具体实现
# -----------------------------

async def fetch_qz_fm889() -> str:
    return await fetch_qztv_base(
        media_id="3", 
        skin="88daf469b4bc0ebb8b760e20f62003a5", 
        station_name="泉州新闻综合 88.9"
    )

async def fetch_qz_fm904() -> str:
    return await fetch_qztv_base(
        media_id="4", 
        skin="27374ae65783ecd9ea344017f42dda85", 
        station_name="泉州交通广播 90.4"
    )

async def fetch_qz_fm1059() -> str:
    return await fetch_qztv_base(
        media_id="6", 
        skin="9027907a948c415a061ff8fec3636b80", 
        station_name="泉州刺桐之声 105.9"
    )

async def fetch_qz_fm923() -> str:
    return await fetch_qztv_base(
        media_id="5", 
        skin="ff3409f7acdeeb923acaf3c4bddc91fc", 
        station_name="泉州经济生活 92.3",
        radio_id="1"  #特别的参数
    )


# ==========================================
# tingfm.com 系列电台通用抓取逻辑
# ==========================================
# tingfm API 返回 JSON，包含 streams[] 数组，按 priority 降序。
# 优先取 m3u8（HLS），没有则取 mp3 直连。
# 新增 tingfm 电台：只需在 STATION_FETCHER_MAP 加一行注册即可。

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

    # 优先取 m3u8，其次按 priority 降序取第一个
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
# 云听 (radio.cn) 系列电台通用抓取逻辑
# ==========================================
# 云听 API 按省份返回电台列表 + m3u8/mp3 地址（带 token，约 19 小时过期）。
# 电台 ID 格式：yt_{contentId}，由 stream-url 端点按需动态注册到 STATION_FETCHER_MAP。

YUNTING_API_BASE = "https://ytmsout.radio.cn/web/appBroadcast/list"
YUNTING_TIMEOUT = httpx.Timeout(15.0)


async def fetch_yunting(province_code: str, content_id: str) -> str:
    """云听通用抓取器：调云听 API，按 contentId 找到电台，返回 m3u8 URL。"""
    params = {"categoryId": 0, "provinceCode": province_code}
    headers = {"User-Agent": DEFAULT_UA, "Accept": "application/json"}

    async with httpx.AsyncClient(timeout=YUNTING_TIMEOUT, follow_redirects=True) as client:
        resp = await client.get(YUNTING_API_BASE, params=params, headers=headers)
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
    """工厂函数：返回绑定了 province_code + content_id 的抓取闭包。"""
    async def _fetch() -> str:
        return await fetch_yunting(province_code, content_id)
    return _fetch


# ==========================================
# myradio.tw 系列电台抓取逻辑
# ==========================================
# 策略：列表页 HTML 只抓一次提取所有 station ID + buildId，
# 之后用 Next.js JSON API（_next/data/{buildId}/zh-TW/{id}.json）获取电台详情。
# 避免反复请求 HTML 触发风控。

MYRADIO_BASE = "https://myradio-dev.zeabur.app"
MYRADIO_TIMEOUT = httpx.Timeout(15.0)
_mr_sem = asyncio.Semaphore(5)
_myradio_build_id: str | None = None


async def fetch_myradio_all() -> list[dict]:
    """抓取 myradio 全量台湾电台。返回 [{id, name, url, logo, freq, tag, codec}]。"""
    global _myradio_build_id
    headers = {"User-Agent": DEFAULT_UA, "x-nextjs-data": "1"}

    async with httpx.AsyncClient(timeout=MYRADIO_TIMEOUT, follow_redirects=True) as client:
        # 第 1 步：列表页 HTML 只抓一次，提取所有 station ID + buildId
        resp = await client.get(f"{MYRADIO_BASE}/zh-TW", headers=headers)
        resp.raise_for_status()
        ids = list(set(re.findall(r'href="[^"]*?/(A\d{4})"', resp.text)))

        if not _myradio_build_id:
            m_build = re.search(r'"buildId"\s*:\s*"([^"]+)"', resp.text)
            if m_build:
                _myradio_build_id = m_build.group(1)
            else:
                _myradio_build_id = "zyHz39BkSpQMj2O8YxLfe"
                logger.warning("myradio buildId 提取失败，使用硬编码兜底")

        logger.info("myradio 发现 %d 个电台 ID，buildId=%s", len(ids), _myradio_build_id)

        # 第 2 步：并发请求 JSON API（轻量，无 HTML 解析）
        async def _fetch_one(sid: str) -> dict | None:
            async with _mr_sem:
                try:
                    url = f"{MYRADIO_BASE}/_next/data/{_myradio_build_id}/zh-TW/{sid}.json?id={sid}"
                    r = await client.get(url, headers=headers)
                    r.raise_for_status()
                    radio = r.json()["pageProps"]["radio"]
                    return {
                        "id": radio["id"],
                        "name": radio["name"],
                        "url": radio["url"],
                        "logo": f"https://images.myradio.com.tw/images/{radio['id']}.jpg",
                        "freq": radio.get("des", ""),
                        "tag": radio.get("tag", ""),
                        "codec": radio.get("codec", 0),
                    }
                except Exception as exc:
                    logger.debug("myradio %s 详情获取失败: %s", sid, exc)
            return None

        results = await asyncio.gather(*[_fetch_one(sid) for sid in ids])
    return [r for r in results if r]


# 电台抓取器注册表。
# key 是前端或 API 使用的电台 ID，value 是负责刷新该电台真实播放地址的异步函数。
STATION_FETCHER_MAP: dict[str, StationFetcher] = {
    "hitfm": fetch_hitfm,
    "hitfm_taichung": fetch_hitfm_taichung,
    "hitfm_tainan": fetch_hitfm_tainan,
    "hitfm_yilan": fetch_hitfm_yilan,
    "hitfm_huadong": fetch_hitfm_huadong,
    "qz_fm889": fetch_qz_fm889,
    "qz_fm904": fetch_qz_fm904,
    "qz_fm1059": fetch_qz_fm1059,
    "qz_fm923": fetch_qz_fm923,
    "pop917": fetch_pop917,
    # tingfm 系列：只需在这里加一行，post_id 从 tingfm.com 电台页面 URL 获取
    # "fj_traffic": tingfm(94),   # 福建交通广播 FM100.7
    # "fzzhzs":     tingfm(100),  # 福州左海之声 FM90.1
}
