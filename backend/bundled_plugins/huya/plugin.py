#!/usr/bin/env python3
"""Official Huya Provider Plugin.

This provider is independently runnable and keeps the legacy Huya selection
policy inside the Plugin.  Core only receives the public TV descriptor;
selection diagnostics are data-only generic metadata.
"""
from __future__ import annotations

import asyncio
import json
from typing import Any
from urllib.request import Request, urlopen

from streamlink import Streamlink
from streamlink.exceptions import NoPluginError, NoStreamsError
from streamlink.exceptions import PluginError as StreamlinkPluginError
from streamlink.exceptions import StreamError, StreamlinkError
from waveflow_plugin_sdk import (
    InvalidResource,
    PluginApplication,
    PluginError,
    ResolveContext,
    StreamDescriptor,
    TemporaryFailure,
    TVProvider,
    TVReference,
    VisualMetadata,
)


HUYA_TTL_SECONDS = 60


def _first_stable_cover(*objects: dict[str, Any]) -> str:
    """Read only explicitly stable room-art fields from Huya metadata.

    ``screenshot`` is deliberately not in this list: it is the live/replay
    visual and is exposed separately as ``dynamic_cover_url``.  The aliases
    below are upstream metadata names, not URL templates; no anchorpost URL
    is ever synthesized by the Plugin.
    """
    stable_fields = (
        "stableCoverUrl", "stable_cover_url", "roomCover", "room_cover",
        "roomPoster", "room_poster", "anchorPost", "anchorpost", "anchor_post",
    )
    for obj in objects:
        if not isinstance(obj, dict):
            continue
        for field in stable_fields:
            value = obj.get(field)
            if isinstance(value, dict):
                value = value.get("url") or value.get("imageUrl") or value.get("image_url")
            value = str(value or "").strip()
            if value.startswith(("http://", "https://")):
                return value
    return ""


def _infer_transport(url: str) -> str:
    lower = url.lower().split("?", 1)[0]
    if lower.endswith(".flv"):
        return "http_flv"
    if lower.endswith(".m3u8"):
        return "hls"
    if lower.endswith(".ts"):
        return "mpegts"
    # Preserve the legacy fallback for Streamlink URLs without a recognized
    # extension.
    return "hls"


def _pick_stream(streams: dict[str, Any], preferred_cdn: str = "tx") -> tuple[str, Any] | tuple[None, None]:
    preferred_cdn = (preferred_cdn or "tx").lower()
    preferred_names = [
        f"{preferred_cdn}_source",
        "tx_source",
        "hs_source",
        "al_source",
        "best",
    ]
    for name in preferred_names:
        stream = streams.get(name)
        if stream is not None:
            return name, stream
    return next(iter(streams.items()), (None, None))


def _resolve_huya_with_streamlink(huya_url: str, preferred_cdn: str = "tx") -> dict[str, Any]:
    session = Streamlink()
    streams = session.streams(huya_url)
    stream_name, stream = _pick_stream(streams, preferred_cdn)
    if stream is None:
        raise NoStreamsError(huya_url)
    play_url = stream.to_url()
    if not play_url:
        raise StreamError("streamlink did not return a stream URL")
    return {
        "url": play_url,
        "transport": _infer_transport(play_url),
        "stream_name": stream_name or "best",
        "available_streams": list(streams.keys()),
    }


def _resolve_with_worker_thread(huya_url: str, preferred_cdn: str) -> dict[str, Any]:
    """Keep Streamlink off the SDK request loop, matching legacy to_thread semantics.

    PluginApplication already invokes each provider request in a worker thread;
    this nested coroutine makes the boundary explicit and keeps the blocking
    Streamlink call isolated from the Plugin IPC reader as well.
    """
    return asyncio.run(asyncio.to_thread(_resolve_huya_with_streamlink, huya_url, preferred_cdn))


def _failure(message: str, provider_code: str) -> TemporaryFailure:
    error = TemporaryFailure(message)
    error.details.update({"provider": "huya", "provider_code": provider_code})
    return error


class Provider(TVProvider):
    def resolve_stream(self, reference: TVReference, context: ResolveContext) -> StreamDescriptor:
        context.raise_if_cancelled()
        room_id = reference.resource_id.strip("/")
        if not room_id:
            raise InvalidResource("Huya room ID is empty")

        huya_url = f"https://www.huya.com/{room_id}"
        preferred_cdn = (reference.query.get("cdn") or ["tx"])[0]
        try:
            result = _resolve_with_worker_thread(huya_url, preferred_cdn)
        except NoStreamsError:
            raise PluginError(
                "NOT_LIVE", "Huya resource is not live or has no playable stream", retryable=False,
                details={"provider": "huya", "provider_code": "huya_not_live"},
            ) from None
        except (NoPluginError, StreamlinkPluginError, StreamError, StreamlinkError, OSError):
            raise _failure("Huya Streamlink resolution failed", "huya_resolve_failed") from None
        except PluginError:
            raise
        except Exception:
            raise _failure("Huya Streamlink resolution failed", "huya_resolve_failed") from None
        context.raise_if_cancelled()
        return StreamDescriptor(
            url=result["url"],
            transport=result["transport"],
            headers={"Origin": "https://www.huya.com", "Referer": "https://www.huya.com/"},
            ttl_seconds=HUYA_TTL_SECONDS,
            expires_at=None,
            volatile_url=False,
            requires_proxy=False,
            provider_diagnostics={
                "provider": "huya",
                "stream_name": result.get("stream_name", "best"),
                "available_streams": result.get("available_streams", []),
                "preferred_cdn": (preferred_cdn or "tx").lower(),
            },
        )

    def visual_metadata(self, reference: TVReference, context: ResolveContext) -> VisualMetadata:
        context.raise_if_cancelled()
        room_id = reference.resource_id.strip("/")
        if not room_id:
            raise InvalidResource("Huya room ID is empty")
        api = (
            "https://mp.huya.com/cache.php?m=Live&do=profileRoom&showSecret=1"
            f"&roomid={room_id}"
        )
        try:
            request = Request(api, headers={"User-Agent": "Mozilla/5.0", "Referer": "https://www.huya.com/"})
            with urlopen(request, timeout=6.0) as response:
                payload = json.loads(response.read(1024 * 1024).decode("utf-8", errors="replace"))
            data = (payload or {}).get("data") or {}
            live_data = data.get("liveData") or {}
            profile = data.get("profileInfo") or {}
            live_status = data.get("liveStatus")
            if live_status is None:
                live_status = live_data.get("liveStatus")
            dynamic_cover = str(live_data.get("screenshot") or "").strip()
            stable_cover = _first_stable_cover(profile, live_data, data)
            is_live = (str(live_status).upper() == "ON") if live_status is not None else bool(dynamic_cover)
            return VisualMetadata(
                avatar_url=str(live_data.get("avatar180") or profile.get("avatar180") or "").strip(),
                stable_cover_url=stable_cover,
                dynamic_cover_url=dynamic_cover,
                # Keep the pre-1.1 field for older Core/Frontend projections.
                cover_url=dynamic_cover,
                is_live=is_live,
                title=str(live_data.get("introduction") or "").strip(),
                owner_name=str(live_data.get("nick") or profile.get("nick") or "").strip(),
                ttl_seconds=300,
                cover_role="live",
            )
        except PluginError:
            raise
        except Exception as exc:
            raise TemporaryFailure("Huya visual metadata request failed") from exc


def main() -> None:
    identity, version = PluginApplication.identity_args("org.waveflow/huya")
    provider = Provider()
    PluginApplication(identity=identity, version=version, permissions=["network"]).register_tv(
        "huya", provider
    ).register_tv_visual("huya", provider).run()


if __name__ == "__main__":
    main()
