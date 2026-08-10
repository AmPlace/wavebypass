#!/usr/bin/env python3
"""Independent NMTV Provider Plugin using managed HTTP and environment xxtea."""
from __future__ import annotations

import argparse
import json
import sys
import threading
import time
import uuid
from typing import Any

API_URL = "https://api-bt.nmtv.cn/broadcast/list"
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
REFERER = "https://www.nmtv.cn/"
KEY = b"5b28bae827e651b3"
CHANNELS = {
    "nmws": 262, "nmmyws": 126, "nmxwzh": 127, "nmjjsh": 128, "nmse": 129,
    "nmwtyl": 130, "nmnm": 131, "nmwh": 132, "hhht1": 141, "xlgl1": 156,
    "als1": 157, "byle1": 158, "erds1": 159, "cf1": 161, "tl1": 163,
    "wlcb1": 164, "wh1": 165, "hlbe1": 166, "xa1": 167, "bt1": 168,
}
import base64
import xxtea

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


def provider_error(code: str, message: str) -> dict[str, Any]:
    return {"code": code, "message": message, "retryable": code != "RESOURCE_NOT_FOUND",
            "category": "provider", "details": {}}


def fetch(request: dict[str, Any]) -> dict[str, Any]:
    callback_id = f"plugin:{uuid.uuid4().hex}"
    event = threading.Event()
    with CALLBACK_LOCK:
        CALLBACKS[callback_id] = (event, None)
    frame({"protocol_version": "1.1", "kind": "request", "sender": "plugin", "request_id": callback_id,
           "method": "core.http.fetch", "plugin_instance": request.get("plugin_instance"),
           "deadline_unix_ms": int((time.time() + 10) * 1000),
           "context": {"parent_request_id": request["request_id"]},
           "payload": {"method": "GET", "url": API_URL, "query": {"size": "100", "type": "1"},
                       "headers": {"User-Agent": USER_AGENT, "Referer": REFERER}, "response_mode": "text"}})
    if not event.wait(10):
        raise RuntimeError("PLUGIN_TIMEOUT")
    with CALLBACK_LOCK:
        response = CALLBACKS.pop(callback_id)[1] or {}
    if response.get("status") == "error":
        raise RuntimeError(str((response.get("error") or {}).get("code") or "TEMPORARY_UPSTREAM_FAILURE"))
    return response.get("result") or {}


def resolve(request: dict[str, Any]) -> None:
    resource = str((request.get("payload") or {}).get("resource_id") or "").strip("/").lower()
    target_id = CHANNELS.get(resource)
    if target_id is None:
        if resource.isdigit():
            target_id = int(resource)
        else:
            reply(request, error=provider_error("RESOURCE_NOT_FOUND", "NMTV channel is not supported")); return
    try:
        result = fetch(request)
        raw = str(result.get("body") or "").strip().strip('"')
        text = xxtea.decrypt(base64.b64decode(raw), KEY, padding=False).decode("utf-8", errors="ignore")
        data = json.JSONDecoder().raw_decode(text)[0]
        target = next((v.get("data", {}) for v in data.get("data", []) if v.get("data", {}).get("id") == target_id), None)
        streams = target.get("streamUrls", []) if target else []
        url = streams[0] if streams else ""
        if not isinstance(url, str) or not url.startswith(("http://", "https://")):
            raise ValueError("missing stream")
    except RuntimeError as exc:
        code = str(exc)
        reply(request, error={"code": code if code in {"CAPABILITY_DENIED", "PLUGIN_TIMEOUT", "RATE_LIMITED", "AUTH_FAILED"} else "TEMPORARY_UPSTREAM_FAILURE",
                              "message": "NMTV upstream request failed", "retryable": True, "category": "network", "details": {}}); return
    except Exception:
        reply(request, error=provider_error("TEMPORARY_UPSTREAM_FAILURE", "NMTV response decode failed")); return
    reply(request, {"descriptor_version": "1.0", "transport": "hls", "url": url,
                    "headers": {"User-Agent": USER_AGENT, "Referer": REFERER}, "credential_refs": [],
                    "ttl_seconds": 1800, "expires_at": None, "volatile_url": True,
                    "requires_proxy": False, "warnings": [],
                    "provider_diagnostics": {"dependency_origin": str(xxtea.__file__)}})


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--identity", default="org.waveflow/nmtv")
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
                "owned_schemes": [{"scheme": "nmtv", "contract": "tv_provider"}],
                "capabilities": ["tv.resolve_stream"], "permissions": ["network"], "dependency_origin": xxtea.__file__})
        elif method == "runtime.health":
            reply(request, {"healthy": True})
        elif method == "runtime.shutdown":
            reply(request, {"accepted": True})
            return
        elif method == "tv.resolve_stream":
            threading.Thread(target=resolve, args=(request,), daemon=True).start()
        else:
            reply(request, error=provider_error("RESOURCE_NOT_FOUND", "Provider method is not supported"))


if __name__ == "__main__":
    main()
