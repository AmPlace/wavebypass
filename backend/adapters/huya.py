import json
from streamget import HuyaLiveStream
from datetime import datetime
from typing import Any
from urllib.parse import urlparse

import httpx

from . import ADAPTER_SUCCESS_TTL_SECONDS, AdapterRequest, AdapterResolveError

async def resolve_huya(request: AdapterRequest, client: httpx.AsyncClient) -> dict[str, Any]:
    room_id = request.resource_id.strip("/")
    if not room_id:
        raise AdapterResolveError("invalid_huya_room_id", "虎牙房间号不能为空")
    
    huya_url = f"https://www.huya.com/{room_id}"

    try:
       live = HuyaLiveStream()
       data = await live.fetch_web_stream_data(huya_url)
       stream_obj = await(live.fetch_stream_url(data, "OD"))
       json_str = stream_obj.to_json()
       result = json.loads(json_str)
    except Exception as exc:
        raise AdapterResolveError(
            "huya_resolve_failed",
            f"虎牙解析失败: {exc}",
            status_code=502,
            retryable=True,
        ) from exc

    if not result.get("is_live"):
        raise AdapterResolveError(
            "huya_not_live",
            "该虎牙主播未开播",
            status_code=502,
            retryable=False,
        )

    play_url = result.get("m3u8_url") or result.get("flv_url")
    if not play_url:
        raise AdapterResolveError(
            "huya_no_play_url",
            "虎牙没有返回可播放地址",
            status_code=502,
            retryable=True,
        )

    return {
        "ok": True,
        "adapter": "huya",
        "source_type": "hls",
        "url": play_url,
        "direct_playable": True,
        "requires_proxy": False,
        "headers": {},
        "ttl": 60,
        "expires_at": None,
        "warnings": [],
    }

