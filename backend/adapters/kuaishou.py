import json
from typing import Any

import httpx
from streamget import KwaiLiveStream

from . import ADAPTER_SUCCESS_TTL_SECONDS, AdapterRequest, AdapterResolveError


async def resolve_kuaishou(request: AdapterRequest, client: httpx.AsyncClient) -> dict[str, Any]:
    room_id = request.resource_id.strip("/")
    if not room_id:
        raise AdapterResolveError("invalid_kuaishou_room_id", "快手房间号不能为空")

    kuaishou_url = f"https://live.kuaishou.com/u/{room_id}"

    try:
        live = KwaiLiveStream(cookies="")
        data = await live.fetch_web_stream_data(kuaishou_url)
        stream_obj = await live.fetch_stream_url(data, "OD")
        json_str = stream_obj.to_json()
        result = json.loads(json_str)
    except Exception as exc:
        raise AdapterResolveError(
            "kuaishou_resolve_failed",
            f"快手解析失败: {exc}",
            status_code=502,
            retryable=True,
        ) from exc

    if not result.get("is_live"):
        raise AdapterResolveError(
            "kuaishou_not_live",
            "该快手主播未开播",
            status_code=502,
            retryable=False,
        )

    play_url = result.get("flv_url")
    if not play_url:
        raise AdapterResolveError(
            "kuaishou_no_play_url",
            "快手没有返回可播放地址",
            status_code=502,
            retryable=True,
        )

    return {
        "ok": True,
        "adapter": "kuaishou",
        "source_type": "http_flv",
        "url": play_url,
        "direct_playable": True,
        "requires_proxy": False,
        "headers": {},
        "ttl": ADAPTER_SUCCESS_TTL_SECONDS,
        "expires_at": None,
        "warnings": [],
        "anchor_name": result.get("anchor_name", ""),
    }
