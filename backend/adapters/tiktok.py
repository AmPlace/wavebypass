import json
from typing import Any

import httpx
from streamget import TikTokLiveStream

from . import ADAPTER_SUCCESS_TTL_SECONDS, AdapterRequest, AdapterResolveError


async def resolve_tiktok(request: AdapterRequest, client: httpx.AsyncClient) -> dict[str, Any]:
    room_id = request.resource_id.strip("/")
    if not room_id:
        raise AdapterResolveError("invalid_tiktok_room_id", "TikTok 房间号不能为空")

    tiktok_url = f"https://www.tiktok.com/@{room_id}/live"

    try:
        live = TikTokLiveStream()
        data = await live.fetch_web_stream_data(tiktok_url)
        stream_obj = await live.fetch_stream_url(data, "OD")
        json_str = stream_obj.to_json()
        result = json.loads(json_str)
    except Exception as exc:
        raise AdapterResolveError(
            "tiktok_resolve_failed",
            f"TikTok 解析失败: {exc}",
            status_code=502,
            retryable=True,
        ) from exc

    if not result.get("is_live"):
        raise AdapterResolveError(
            "tiktok_not_live",
            "该 TikTok 主播未开播",
            status_code=502,
            retryable=False,
        )

    play_url = result.get("flv_url") or result.get("m3u8_url")
    if not play_url:
        raise AdapterResolveError(
            "tiktok_no_play_url",
            "TikTok 没有返回可播放地址",
            status_code=502,
            retryable=True,
        )

    source_type = "http_flv" if result.get("flv_url") else "hls"

    return {
        "ok": True,
        "adapter": "tiktok",
        "source_type": source_type,
        "url": play_url,
        "direct_playable": True,
        "requires_proxy": False,
        "headers": {},
        "ttl": ADAPTER_SUCCESS_TTL_SECONDS,
        "expires_at": None,
        "warnings": [],
        "anchor_name": result.get("anchor_name", ""),
    }
