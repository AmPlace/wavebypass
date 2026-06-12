import json
import re
from urllib.parse import unquote
from typing import Any

import httpx
from streamget.requests.async_http import async_req

from . import ADAPTER_SUCCESS_TTL_SECONDS, AdapterRequest, AdapterResolveError

_REDBOOK_HEADERS = {
    "user-agent": "ios/7.830 (ios 17.0; ; iPhone 15 (A2846/A3089/A3090/A3092))",
    "xy-common-params": "platform=iOS&sid=session.1722166379345546829388",
    "referer": "https://app.xhs.cn/",
}


async def resolve_redbook(request: AdapterRequest, client: httpx.AsyncClient) -> dict[str, Any]:
    room_id = request.resource_id.strip("/")
    if not room_id:
        raise AdapterResolveError("invalid_redbook_room_id", "小红书房间号不能为空")

    # redbook://570315774021735275 → https://www.xiaohongshu.com/livestream/570315774021735275
    redbook_url = f"https://www.xiaohongshu.com/livestream/{room_id}"

    try:
        html_str = await async_req(redbook_url, headers=_REDBOOK_HEADERS)
        match_data = re.search(r"<script>window\.__INITIAL_STATE__=(.*?)</script>", html_str)
        if not match_data:
            raise AdapterResolveError(
                "redbook_parse_failed",
                "小红书页面解析失败",
                status_code=502,
                retryable=True,
            )

        json_str = match_data.group(1).replace("undefined", "null")
        data = json.loads(json_str)
        stream_data = data.get("liveStream", {})

        if stream_data.get("liveStatus") != "success":
            raise AdapterResolveError(
                "redbook_not_live",
                "该小红书主播未开播",
                status_code=502,
                retryable=False,
            )

        room_info = stream_data["roomData"]["roomInfo"]
        deeplink = room_info.get("deeplink", "")

        # 解码 deeplink（streamget 没有解码，导致 URL 解析失败）
        decoded_link = unquote(deeplink)

        # 提取 flvUrl
        flv_match = re.search(r"flvUrl=([^&]+)", decoded_link)
        if not flv_match:
            raise AdapterResolveError(
                "redbook_no_play_url",
                "小红书没有返回可播放地址",
                status_code=502,
                retryable=True,
            )

        flv_url = flv_match.group(1)
        m3u8_url = flv_url.replace('.flv', '.m3u8')

        # 提取主播名
        nickname_match = re.search(r"host_nickname=([^&]+)", decoded_link)
        anchor_name = unquote(nickname_match.group(1)) if nickname_match else ""

    except AdapterResolveError:
        raise
    except Exception as exc:
        raise AdapterResolveError(
            "redbook_resolve_failed",
            f"小红书解析失败: {exc}",
            status_code=502,
            retryable=True,
        ) from exc

    return {
        "ok": True,
        "adapter": "redbook",
        "source_type": "hls",
        "url": m3u8_url,
        "direct_playable": True,
        "requires_proxy": False,
        "headers": {},
        "ttl": ADAPTER_SUCCESS_TTL_SECONDS,
        "expires_at": None,
        "warnings": [],
        "anchor_name": anchor_name,
    }
