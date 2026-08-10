#!/usr/bin/env python3
"""Self-contained NOW TV provider Plugin using the public IPC contract."""
from __future__ import annotations

import argparse
import json
import sys
import threading
import time
import uuid
from typing import Any

API_URL = "https://webtvapi.now.com/10/7/getLiveURL"
USER_AGENT = "NNC/6.3.0 (com.now.news; build:2309121224; iOS 17.1.0) Alamofire/5.2.2"
CHANNELS = {
    "NEWS": ("331", "NOW 新闻台"),
    "FINANCE": ("332", "NOW 财经台"),
    "LIVE": ("333", "NOW 直播新闻台"),
}
WRITE_LOCK = threading.Lock()
CALLBACK_LOCK = threading.Lock()
CALLBACKS: dict[str, tuple[threading.Event, dict[str, Any] | None]] = {}


def frame(value: dict[str, Any]) -> None:
    body = json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode()
    with WRITE_LOCK:
        sys.stdout.buffer.write(
            f"Content-Length: {len(body)}\r\nContent-Type: application/json; charset=utf-8\r\n\r\n".encode()
            + body
        )
        sys.stdout.buffer.flush()


def read_frame() -> dict[str, Any] | None:
    headers: dict[str, str] = {}
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


def error(code: str, message: str, *, retryable: bool = False, category: str = "provider") -> dict[str, Any]:
    return {"code": code, "message": message, "retryable": retryable, "category": category, "details": {}}


def capability(request: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    callback_id = f"plugin:{uuid.uuid4().hex}"
    event = threading.Event()
    with CALLBACK_LOCK:
        CALLBACKS[callback_id] = (event, None)
    frame({"protocol_version": "1.1", "kind": "request", "sender": "plugin",
           "request_id": callback_id, "method": "core.http.fetch",
           "plugin_instance": request.get("plugin_instance"),
           "deadline_unix_ms": int((time.time() + 10) * 1000),
           "context": {"parent_request_id": request["request_id"]}, "payload": payload})
    if not event.wait(10):
        with CALLBACK_LOCK:
            CALLBACKS.pop(callback_id, None)
        raise RuntimeError("PLUGIN_TIMEOUT")
    with CALLBACK_LOCK:
        response = CALLBACKS.pop(callback_id)[1] or {}
    if response.get("status") == "error":
        detail = response.get("error") or {}
        raise RuntimeError(str(detail.get("code") or "TEMPORARY_UPSTREAM_FAILURE"))
    return response.get("result") or {}


def resolve(request: dict[str, Any]) -> None:
    payload = request.get("payload") or {}
    resource = str(payload.get("resource_id") or "").strip("/").upper()
    channel = CHANNELS.get(resource)
    if channel is None:
        if resource.isdigit():
            channel = (resource, f"NOW CH{resource}")
        else:
            reply(request, error=error("RESOURCE_NOT_FOUND", "NOW TV channel is not supported"))
            return
    body = {"deviceType": "IOS_PHONE", "contentId": channel[0], "audioCode": "A",
            "deviceId": "8269809F-7702-45CE-9378-D7157A2E6819", "mode": "prod",
            "callerReferenceNo": "20140702122500", "contentType": "Channel"}
    try:
        response = capability(request, {"method": "POST", "url": API_URL,
            "headers": {"Content-Type": "application/json", "User-Agent": USER_AGENT},
            "body": {"json": body}, "response_mode": "json"})
    except RuntimeError as exc:
        code = str(exc)
        if code == "CAPABILITY_DENIED":
            reply(request, error=error(code, "NOW TV managed network was denied", category="permission"))
        elif code == "PLUGIN_TIMEOUT":
            reply(request, error=error(code, "NOW TV request timed out", retryable=True, category="timeout"))
        elif code in {"AUTH_FAILED", "RATE_LIMITED"}:
            reply(request, error=error(code, "NOW TV upstream request failed", retryable=code == "RATE_LIMITED", category="network"))
        else:
            reply(request, error=error("TEMPORARY_UPSTREAM_FAILURE", "NOW TV upstream request failed", retryable=True, category="network"))
        return
    data = response.get("body")
    if not isinstance(data, dict) or data.get("responseCode") != "SUCCESS":
        reply(request, error=error("TEMPORARY_UPSTREAM_FAILURE", f"NOW TV {channel[1]} returned no success", retryable=True))
        return
    assets = data.get("asset")
    if not isinstance(assets, list) or not assets or not isinstance(assets[0], str) or not assets[0].startswith(("http://", "https://")):
        reply(request, error=error("TEMPORARY_UPSTREAM_FAILURE", f"NOW TV {channel[1]} returned no playable asset", retryable=True))
        return
    reply(request, {"descriptor_version": "1.0", "transport": "hls", "url": assets[0],
                    "headers": {}, "credential_refs": [], "ttl_seconds": 300, "expires_at": None,
                    "volatile_url": True, "requires_proxy": True, "warnings": []})


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--identity", default="org.waveflow/nowtv")
    parser.add_argument("--version", default="1.0.0")
    args = parser.parse_args()
    while True:
        request = read_frame()
        if request is None:
            return
        if request.get("kind") == "response" and request.get("sender") == "core":
            with CALLBACK_LOCK:
                pending = CALLBACKS.get(request.get("request_id"))
                if pending:
                    CALLBACKS[request["request_id"]] = (pending[0], request)
                    pending[0].set()
            continue
        method = request.get("method")
        if method == "runtime.hello":
            reply(request, {"protocol_version": "1.1", "plugin": args.identity, "version": args.version,
                "provider_contracts": [{"contract": "tv_provider", "contract_version": "1.0", "features": ["resolve_stream"]}],
                "owned_schemes": [{"scheme": "nowtv", "contract": "tv_provider"}],
                "capabilities": ["tv.resolve_stream"], "permissions": ["network"]})
        elif method == "runtime.health":
            reply(request, {"healthy": True})
        elif method == "runtime.shutdown":
            reply(request, {"accepted": True})
            return
        elif method == "tv.resolve_stream":
            threading.Thread(target=resolve, args=(request,), daemon=True).start()
        else:
            reply(request, error=error("RESOURCE_NOT_FOUND", "Provider method is not supported"))


if __name__ == "__main__":
    main()
