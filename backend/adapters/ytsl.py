import asyncio
import re
from typing import Any
from urllib.parse import unquote

import httpx
from streamlink import Streamlink
from streamlink.exceptions import NoPluginError, NoStreamsError, PluginError, StreamError, StreamlinkError

from . import AdapterRequest, AdapterResolveError


_YOUTUBE_VIDEO_ID_RE = re.compile(r"^[a-zA-Z0-9_-]{11}$")


def _infer_source_type(url: str) -> str:
    lower = url.lower().split("?", 1)[0]
    if ".m3u8" in lower or "manifest/hls" in url.lower():
        return "hls"
    if lower.endswith(".flv"):
        return "http_flv"
    if lower.endswith(".ts"):
        return "mpegts"
    return "hls"


def _build_youtube_url(request: AdapterRequest) -> str:
    query_url = (request.query.get("url") or [""])[0].strip()
    if query_url:
        return query_url

    raw = unquote((request.resource_id or "").strip().strip("/"))
    if not raw:
        raise AdapterResolveError("invalid_ytsl_url", "YouTube Streamlink 地址不能为空")
    if raw.startswith(("http://", "https://")):
        return raw
    if _YOUTUBE_VIDEO_ID_RE.fullmatch(raw):
        return f"https://www.youtube.com/watch?v={raw}"
    if raw.startswith("@"):
        return f"https://www.youtube.com/{raw}"
    if raw.startswith("UC"):
        return f"https://www.youtube.com/channel/{raw}"
    if raw.startswith(("channel/", "c/", "user/")):
        return f"https://www.youtube.com/{raw}"
    return f"https://www.youtube.com/{raw}"


def _pick_stream(streams: dict[str, Any], quality: str = "best") -> tuple[str, Any] | tuple[None, None]:
    quality = (quality or "best").strip()
    if quality in streams:
        return quality, streams[quality]
    if "best" in streams:
        return "best", streams["best"]
    return next(iter(streams.items()), (None, None))


def _resolve_youtube_with_streamlink(url: str, quality: str = "best") -> dict[str, Any]:
    session = Streamlink()
    streams = session.streams(url)
    stream_name, stream = _pick_stream(streams, quality)
    if stream is None:
        raise NoStreamsError(url)

    play_url = stream.to_url()
    if not play_url:
        raise StreamError("streamlink did not return a stream URL")

    return {
        "url": play_url,
        "source_type": _infer_source_type(play_url),
        "stream_name": stream_name or "best",
        "available_streams": list(streams.keys()),
    }


async def resolve_ytsl(request: AdapterRequest, client: httpx.AsyncClient) -> dict[str, Any]:
    youtube_url = _build_youtube_url(request)
    quality = (request.query.get("quality") or ["best"])[0]

    try:
        result = await asyncio.to_thread(_resolve_youtube_with_streamlink, youtube_url, quality)
    except NoStreamsError as exc:
        raise AdapterResolveError(
            "ytsl_no_streams",
            "YouTube 没有返回可播放流，可能未开播、需要登录、地区限制或需要 PO Token",
            status_code=502,
            retryable=False,
        ) from exc
    except (NoPluginError, PluginError, StreamError, StreamlinkError, OSError) as exc:
        raise AdapterResolveError(
            "ytsl_resolve_failed",
            f"YouTube Streamlink 解析失败: {exc}",
            status_code=502,
            retryable=True,
        ) from exc

    return {
        "ok": True,
        "adapter": "ytsl",
        "source_type": result["source_type"],
        "url": result["url"],
        "direct_playable": False,
        "requires_proxy": True,
        "headers": {},
        "ttl": 120,
        "expires_at": None,
        "warnings": [],
        "stream_name": result.get("stream_name", "best"),
        "available_streams": result.get("available_streams", []),
    }
