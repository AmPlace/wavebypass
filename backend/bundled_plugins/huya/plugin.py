#!/usr/bin/env python3
"""Official Huya Provider Plugin.

This provider is independently runnable and keeps the legacy Huya selection
policy inside the Plugin.  Core only receives the public TV descriptor;
selection diagnostics are data-only generic metadata.
"""
from __future__ import annotations

import asyncio
from typing import Any

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
)


HUYA_TTL_SECONDS = 60


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


def main() -> None:
    identity, version = PluginApplication.identity_args("org.waveflow/huya")
    PluginApplication(identity=identity, version=version, permissions=["network"]).register_tv(
        "huya", Provider()
    ).run()


if __name__ == "__main__":
    main()
