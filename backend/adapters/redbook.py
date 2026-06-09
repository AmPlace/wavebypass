import asyncio
import json
from streamget import RedNoteLiveStream
from typing import Any

import httpx

from . import ADAPTER_SUCCESS_TTL_SECONDS, AdapterRequest, AdapterResolveError


async def resolve_redbook(request: AdapterRequest, client: httpx.AsyncClient) -> dict[str, Any]:
    room_id = request.resource_id.strip("/")
    if not room_id:
        raise AdapterResolveError("invalid_redbook_room_id", "小红书房间号不能为空")

    redbook_url = f"https://live.xiaohongshu.com/{room_id}"

    try:
        live = RedNoteLiveStream()
        data = await live.fetch_web_stream_data(redbook_url)
        stream_obj = await live.fetch_stream_url(data, "OD")
        json_str = stream_obj.to_json()
        result = json.loads(json_str)
    except Exception as exc:
        raise AdapterResolveError(
            "redbook_resolve_failed",
            f"小红书解析失败: {exc}",
            status_code=502,
            retryable=True,
        ) from exc

    if not result.get("is_live"):
        raise AdapterResolveError(
            "redbook_not_live",
            "该小红书主播未开播",
            status_code=502,
            retryable=False,
        )

    play_url = result.get("m3u8_url") or result.get("flv_url")
    if not play_url:
        raise AdapterResolveError(
            "redbook_no_play_url",
            "小红书没有返回可播放地址",
            status_code=502,
            retryable=True,
        )

    source_type = "hls" if result.get("m3u8_url") else "mpegts"

    return {
        "ok": True,
        "adapter": "redbook",
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
