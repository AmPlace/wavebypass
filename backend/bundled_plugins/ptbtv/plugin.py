#!/usr/bin/env python3
"""Independent PTBTV Provider Plugin with direct curl-cffi and managed fallback."""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import sys
import threading
import time
import uuid
from typing import Any, Callable

from curl_cffi.requests import AsyncSession


API_KEY = "f33ba15effa5c10e873bf3842afb46a6"
API_SECRET = "YWFkZDYwMjNkNzMzNzUwZWJjYjE4NWFjZjY3YmQyYzE="
API_VERSION = "1.0.0"
API_URL = "https://www.ptbtv.com/m2o/channel/channel_info.php"
USER_AGENT = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
              "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36")
CHANNELS = {
    "1": {"name": "莆田1套", "channel_id": "4", "referer": "https://www.ptbtv.com/live/pt1t/"},
    "2": {"name": "莆田2套", "channel_id": "5", "referer": "https://www.ptbtv.com/live/pt2t/"},
    "xianyou": {"name": "仙游电视", "channel_id": "6", "referer": "https://www.ptbtv.com/live/xyds/"},
}
ALIASES = {"ptbtv-1": "1", "ptbtv-2": "2", "pt1": "1", "pt2": "2", "xianyoutv": "xianyou", "xy": "xianyou"}
WRITE_LOCK = threading.Lock()
CALLBACK_LOCK = threading.Lock()
CALLBACKS: dict[str, tuple[threading.Event, dict[str, Any] | None]] = {}


def frame(value: dict[str, Any]) -> None:
    payload = json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode()
    with WRITE_LOCK:
        sys.stdout.buffer.write(f"Content-Length: {len(payload)}\r\nContent-Type: application/json; charset=utf-8\r\n\r\n".encode() + payload)
        sys.stdout.buffer.flush()


def read_frame() -> dict[str, Any] | None:
    headers = {}
    while True:
        line = sys.stdin.buffer.readline()
        if not line:
            return None
        if line == b"\r\n":
            break
        name, value = line.decode("ascii").rstrip("\r\n").split(": ", 1)
        headers[name.lower()] = value
    return json.loads(sys.stdin.buffer.read(int(headers["content-length"])).decode())


def reply(request: dict[str, Any], result: Any = None, error: dict[str, Any] | None = None) -> None:
    frame({"protocol_version": "1.1", "kind": "response", "sender": "plugin",
           "request_id": request["request_id"], "status": "error" if error else "ok",
           "result": result, "error": error, "diagnostics": {}})


def provider_error(code: str, message: str, *, retryable: bool = True, category: str = "provider") -> dict[str, Any]:
    return {"code": code, "message": message, "retryable": retryable, "category": category, "details": {}}


def build_headers(referer: str, *, now: Callable[[], float] = time.time) -> dict[str, str]:
    timestamp = str(int(now()))
    signature = hashlib.md5(f"{API_KEY}&{API_SECRET}&{API_VERSION}&{timestamp}".encode()).hexdigest()
    return {"Accept": "application/json, text/javascript, */*; q=0.01", "Accept-Language": "zh-CN,zh;q=0.9",
            "Cache-Control": "no-cache", "Origin": "https://www.ptbtv.com", "Pragma": "no-cache",
            "Referer": referer, "Sec-Fetch-Dest": "empty", "Sec-Fetch-Mode": "cors",
            "Sec-Fetch-Site": "same-origin", "User-Agent": USER_AGENT, "X-Requested-With": "XMLHttpRequest",
            "X-API-TIMESTAMP": timestamp, "X-API-KEY": API_KEY, "X-AUTH-TYPE": "md5",
            "X-API-VERSION": API_VERSION, "X-API-SIGNATURE": signature}


async def direct_fetch(channel_id: str, headers: dict[str, str], *, session_factory=AsyncSession) -> tuple[int, str] | None:
    try:
        async with session_factory(impersonate="chrome", timeout=10) as session:
            response = await session.get(API_URL, params={"channel_id": str(channel_id)}, headers=headers)
        return response.status_code, response.text
    except Exception:
        return None


def managed_fetch(request: dict[str, Any], channel_id: str, headers: dict[str, str]) -> dict[str, Any]:
    callback_id = f"plugin:{uuid.uuid4().hex}"
    event = threading.Event()
    with CALLBACK_LOCK:
        CALLBACKS[callback_id] = (event, None)
    frame({"protocol_version": "1.1", "kind": "request", "sender": "plugin", "request_id": callback_id,
           "method": "core.http.fetch", "plugin_instance": request.get("plugin_instance"),
           "deadline_unix_ms": int((time.time() + 10) * 1000),
           "context": {"parent_request_id": request["request_id"]},
           "payload": {"method": "GET", "url": API_URL, "query": {"channel_id": channel_id},
                       "headers": headers, "response_mode": "text"}})
    if not event.wait(10):
        raise RuntimeError("PLUGIN_TIMEOUT")
    with CALLBACK_LOCK:
        response = CALLBACKS.pop(callback_id)[1] or {}
    if response.get("status") == "error":
        raise RuntimeError(str((response.get("error") or {}).get("code") or "TEMPORARY_UPSTREAM_FAILURE"))
    return response.get("result") or {}


def resolve(request: dict[str, Any]) -> None:
    resource = str((request.get("payload") or {}).get("resource_id") or "").strip("/").lower()
    resource = ALIASES.get(resource, resource)
    channel = CHANNELS.get(resource)
    if channel is None:
        reply(request, error=provider_error("RESOURCE_NOT_FOUND", "PTBTV channel is not supported", retryable=False)); return
    headers = build_headers(channel["referer"])
    try:
        direct = asyncio.run(direct_fetch(channel["channel_id"], headers))
        text = direct[1] if direct is not None and direct[0] == 200 and direct[1] else None
        if text is None:
            text = str(managed_fetch(request, channel["channel_id"], headers).get("body") or "")
        data = json.loads(text)
        url = data[0]["m3u8"]
    except RuntimeError as exc:
        code = str(exc)
        reply(request, error=provider_error(code if code in {"CAPABILITY_DENIED", "PLUGIN_TIMEOUT", "RATE_LIMITED"}
                                            else "TEMPORARY_UPSTREAM_FAILURE",
                                            "PTBTV upstream request failed", category="network")); return
    except (ValueError, KeyError, TypeError, IndexError):
        reply(request, error=provider_error("TEMPORARY_UPSTREAM_FAILURE", "PTBTV response structure is invalid")); return
    if not isinstance(url, str) or not url.startswith(("http://", "https://")):
        reply(request, error=provider_error("TEMPORARY_UPSTREAM_FAILURE", "PTBTV returned no playable stream")); return
    reply(request, {"descriptor_version": "1.0", "transport": "hls", "url": url, "headers": {},
                    "credential_refs": [], "ttl_seconds": 180, "expires_at": None, "volatile_url": True,
                    "requires_proxy": False, "warnings": [],
                    "provider_diagnostics": {"dependency_origin": str(sys.modules["curl_cffi"].__file__)}})


def main() -> None:
    parser = argparse.ArgumentParser(); parser.add_argument("--identity", default="org.waveflow/ptbtv")
    parser.add_argument("--version", default="1.0.0"); parser.add_argument("--fixture-direct-unavailable", action="store_true")
    args = parser.parse_args()
    if args.fixture_direct_unavailable:
        async def unavailable(*_args, **_kwargs):
            return None
        globals()["direct_fetch"] = unavailable
    while True:
        request = read_frame()
        if request is None:
            return
        if request.get("kind") == "response" and request.get("sender") == "core":
            with CALLBACK_LOCK:
                pending = CALLBACKS.get(request.get("request_id"))
                if pending:
                    CALLBACKS[request["request_id"]] = (pending[0], request); pending[0].set()
            continue
        method = request.get("method")
        if method == "runtime.hello":
            reply(request, {"protocol_version": "1.1", "plugin": args.identity, "version": args.version,
                "provider_contracts": [{"contract": "tv_provider", "contract_version": "1.0", "features": ["resolve_stream"]}],
                "owned_schemes": [{"scheme": "ptbtv", "contract": "tv_provider"}],
                "capabilities": ["tv.resolve_stream"], "permissions": ["network"]})
        elif method == "runtime.health": reply(request, {"healthy": True})
        elif method == "runtime.shutdown": reply(request, {"accepted": True}); return
        elif method == "tv.resolve_stream": threading.Thread(target=resolve, args=(request,), daemon=True).start()
        else: reply(request, error=provider_error("RESOURCE_NOT_FOUND", "Provider method is not supported", retryable=False))


if __name__ == "__main__":
    main()
