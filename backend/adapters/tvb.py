import time
from typing import Any

import httpx

from . import AdapterRequest, AdapterResolveError

TVB_API_HOST = "inews-api.tvb.com"
TVB_API_IP = "34.117.164.167"
TVB_CHANNELS = {
    "I-NEWS": "I-NEWS",
    "C2": "C2",
}

# 缓存: Akamai hdntl cookie + 解析后的 URL + 签名 URL
_tvb_cache: dict[str, Any] = {
    "cookie": "",
    "resolved_url": "",
    "signed_url": "",
    "expires_at": 0,
}


async def _resolve_stream(client: httpx.AsyncClient, signed_url: str) -> tuple[str, str]:
    """跟随重定向获取最终 URL 和 hdntl cookie。

    Akamai CDN: 返回 200 + Set-Cookie hdntl
    Edgeware CDN: 返回 302 → session URL（无 cookie）
    Edgeware CDN (非授权IP): 返回 403
    """
    resolved_url = signed_url
    cookie = ""

    try:
        resp = await client.get(signed_url, follow_redirects=True, timeout=10)
        resolved_url = str(resp.url)

        # 从 cookie jar 提取 hdntl（Akamai 设置）
        # httpx 的 client 不会自动存 cookie，需要从响应头提取
        for value in resp.headers.get_list("set-cookie"):
            if "hdntl=" in value:
                cookie = value.split(";")[0].strip()
                break

        # 如果响应不是 200（如 Edgeware 403），返回原始 URL
        if resp.status_code != 200:
            resolved_url = signed_url

    except Exception:
        resolved_url = signed_url

    return resolved_url, cookie


async def resolve_tvb(request: AdapterRequest, client: httpx.AsyncClient) -> dict[str, Any]:
    channel_key = request.resource_id.strip("/").upper()
    content_id = TVB_CHANNELS.get(channel_key)
    if not content_id:
        if channel_key:
            content_id = channel_key
        else:
            supported = ", ".join(TVB_CHANNELS)
            raise AdapterResolveError(
                "invalid_tvb_channel",
                f"不支持的 TVB 频道: {channel_key}，支持: {supported}",
            )

    # 1. 调 TVB API 拿签名 URL
    api_url = f"https://{TVB_API_IP}/news/checkout/live/hd/ott_{content_id}_h264?profile=safari"
    try:
        resp = await client.get(
            api_url,
            headers={"Host": TVB_API_HOST},
            follow_redirects=True,
            timeout=15,
        )
        resp.raise_for_status()
    except httpx.HTTPError as exc:
        raise AdapterResolveError(
            "tvb_api_failed",
            f"TVB API 请求失败: {exc}",
            status_code=502,
            retryable=True,
        ) from exc

    try:
        data = resp.json()
    except ValueError:
        raise AdapterResolveError("tvb_parse_failed", "TVB API 返回非 JSON", status_code=502, retryable=True)

    if data.get("meta", {}).get("status") != "success":
        err_msg = data.get("meta", {}).get("error_message", "未知错误")
        raise AdapterResolveError("tvb_channel_failed", f"TVB 频道 {content_id} 失败: {err_msg}", status_code=502, retryable=True)

    urls = (data.get("content") or {}).get("url") or {}
    signed_url = urls.get("hd") or urls.get("sd")
    if not signed_url:
        raise AdapterResolveError("tvb_no_url", "TVB 未返回播放地址", status_code=502, retryable=True)

    # 2. 获取解析后的 URL 和 cookie（缓存 30 分钟）
    now = time.time()
    if now >= _tvb_cache["expires_at"] or signed_url != _tvb_cache["signed_url"]:
        resolved_url, cookie = await _resolve_stream(client, signed_url)
        _tvb_cache["cookie"] = cookie
        _tvb_cache["resolved_url"] = resolved_url
        _tvb_cache["signed_url"] = signed_url
        _tvb_cache["expires_at"] = now + 30 * 60

    resolved_url = _tvb_cache["resolved_url"]
    cookie = _tvb_cache["cookie"]
    channel_name = f"TVB {content_id}"

    headers_out = {}
    if cookie:
        headers_out["Cookie"] = cookie
    headers_out["no_ua"] = True  # Akamai 反爬：不发 User-Agent

    return {
        "ok": True,
        "adapter": "tvb",
        "source_type": "hls",
        "url": resolved_url,
        "direct_playable": False,
        "requires_proxy": True,
        "headers": headers_out,
        "ttl": 30 * 60,
        "expires_at": None,
        "warnings": [] if cookie else ["未获取到 Akamai cookie，播放可能需要香港 IP"],
        "channel_id": channel_key,
        "channel_name": channel_name,
        "volatile_url": True,
    }
