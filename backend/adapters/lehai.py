import json
from typing import Any

import httpx
from streamget import LehaiLiveStream

from . import ADAPTER_SUCCESS_TTL_SECONDS, AdapterRequest, AdapterResolveError


async def resolve_lehai(request: AdapterRequest, client: httpx.AsyncClient) -> dict[str, Any]:
    room_id = request.resource_id.strip("/")
    if not room_id:
        raise AdapterResolveError("invalid_lehai_room_id", "乐嗨 房间号不能为空")

    url = f"https://www.lehaitv.com/{room_id}"

    try:
        live = LehaiLiveStream(cookies="")
        data = await live.fetch_web_stream_data(url)
        stream_obj = await live.fetch_stream_url(data, "OD")
        json_str = stream_obj.to_json()
        result = json.loads(json_str)
    except Exception as exc:
        raise AdapterResolveError(
            "lehai_resolve_failed",
            f"乐嗨 解析失败: {exc}",
            status_code=502,
            retryable=True,
        ) from exc

    if not result.get("is_live"):
        raise AdapterResolveError(
            "lehai_not_live",
            "该 乐嗨 主播未开播",
            status_code=502,
            retryable=False,
        )

    play_url = result.get("flv_url") or result.get("m3u8_url") or result.get("record_url")
    if not play_url:
        raise AdapterResolveError(
            "lehai_no_play_url",
            "乐嗨 没有返回可播放地址",
            status_code=502,
            retryable=True,
        )

    source_type = "http_flv" if result.get("flv_url") else "hls"

    return {
        "ok": True,
        "adapter": "lehai",
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
