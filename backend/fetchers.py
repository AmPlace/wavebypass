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


STATION_FETCHER_MAP: dict[str, StationFetcher] = {}
