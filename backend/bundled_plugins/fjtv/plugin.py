#!/usr/bin/env python3
"""Self-contained FJTV Provider Plugin.

It intentionally imports only Python standard-library modules. The provider
implementation is independent from backend/adapters/fjtv.py and uses the
public duplex IPC contract for all network access.
"""
from __future__ import annotations

import json
import argparse
import sys
import threading
import time
import uuid
from typing import Any


UA = "okhttp/3.10.0.7"
REFERER_FJTV = "https://www.fjtv.net/"
REFERER_XMTV = "https://www.xmtv.cn/"
REFERER_JJ = "https://www.ijjnews.com/"
REFERER_SS = "https://www.chinashishi.net/"
MAPI_PLUS = "https://mapi-plus.fjtv.net/api/open/haibo8/tv_channel_list.php?sort_id=665226484646215680"
KXM = ("https://mapi1.kxm.xmtv.cn/api/v1/channel.php?node_id=1&appkey=45920796f66247395069ee6f45d99c5e"
       "&appid=m2ohvecbng7leb8ixo&client_type=iOS&device_token=d25800aafc08fc01eabdf4757762e03c"
       "&version=4.6.4&app_version=4.6.4&avos_device_token=d25800aafc08fc01eabdf4757762e03c"
       "&client_id_ios=1211f05806bca2f5e7d93bc0d1d6f75d&location_city=%E5%8E%A6%E9%97%A8&language=Chinese")


def _channel_info(channel_id: str) -> str:
    return f"https://live.fjtv.net/m2o/channel/channel_info.php?channel_id={channel_id}"


CHANNELS: dict[str, tuple[str, list[Any], str, str]] = {
    "fjzh": (_channel_info("665248990102917120"), [0, "m3u8"], "福建综合", REFERER_FJTV),
    "fjdn": (_channel_info("665248966136664064"), [0, "m3u8"], "东南卫视", REFERER_FJTV),
    "fjnews": (_channel_info("665248914378952704"), [0, "m3u8"], "福建新闻", REFERER_FJTV),
    "fjculture": (_channel_info("665248752898248704"), [0, "m3u8"], "福建文旅体育", REFERER_FJTV),
    "fjkid": (_channel_info("665248553475870720"), [0, "m3u8"], "福建少儿", REFERER_FJTV),
    "fjhxws": (_channel_info("665248523855695872"), [0, "m3u8"], "海峡卫视", REFERER_FJTV),
    **{key: (MAPI_PLUS, [index, "topic_camera", 0, "streams", 0, "hls"], name, REFERER_FJTV)
       for index, (key, name) in enumerate((
           ("xmws", "厦门卫视"), ("fznews", "福州新闻综合"), ("zznews", "漳州新闻综合"),
           ("smtv", "三明综合"), ("qznews", "泉州新闻综合"), ("nptv", "南平综合"),
           ("lytv", "龙岩综合"), ("puttv", "莆田新闻综合"), ("pttv", "平潭综合"),
           ("ndtv", "宁德新闻综合"),
       ))},
    "xmws-xmtv": (KXM, [0, "m3u8"], "厦门卫视(XMTV)", REFERER_XMTV),
    "xmtv-1": (KXM, [1, "m3u8"], "厦视一套", REFERER_XMTV),
    "xmtv-2": (KXM, [2, "m3u8"], "厦视二套", REFERER_XMTV),
    "xmtv-mobile": (KXM, [3, "m3u8"], "厦门电视台移动电视", REFERER_XMTV),
    "jjtv": ("https://mapi.ijjnews.com/cloudlive-manage-mapi/api/topic/detail?preview=&id=657527900022525952&app_secret=31ca2c44a23e6cd127ddee647fa9cf92&tenant_id=0&company_id=1067&lang_type=zh", ["topic_camera", 0, "streams", 0, "hls"], "晋江综合", REFERER_JJ),
    "sstv": ("https://mapi-new.chinashishi.net/cloudlive-manage-mapi/api/topic/detail?preview=&id=662611405685436416&app_secret=5c03f9843fa239c14b52222e83098919&tenant_id=0&company_id=492&lang_type=zh", ["topic_camera", 0, "streams", 0, "hls"], "石狮新闻综合", REFERER_SS),
}
ALIASES = {"fjzhpd": "fjzh", "fjdnws": "fjdn"}
WRITE_LOCK = threading.Lock()
CALLBACK_LOCK = threading.Lock()
CALLBACKS: dict[str, list[Any]] = {}


class CapabilityError(RuntimeError):
    def __init__(self, code: str, *, retryable: bool = False, category: str = "capability"):
        super().__init__(code)
        self.code = code
        self.retryable = retryable
        self.category = category


def frame(value: dict[str, Any]) -> None:
    body = json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode()
    with WRITE_LOCK:
        sys.stdout.buffer.write(f"Content-Length: {len(body)}\r\nContent-Type: application/json; charset=utf-8\r\n\r\n".encode() + body)
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


def provider_error(code: str, message: str, *, retryable: bool = False) -> dict[str, Any]:
    return {"code": code, "message": message, "retryable": retryable, "category": "provider", "details": {}}


def walk(value: Any, path: list[Any]) -> Any:
    for key in path:
        if isinstance(key, int):
            if not isinstance(value, list) or key >= len(value):
                raise KeyError(key)
        elif not isinstance(value, dict) or key not in value:
            raise KeyError(key)
        value = value[key]
    return value


def fetch(request: dict[str, Any], url: str) -> dict[str, Any]:
    callback_id = f"plugin:{uuid.uuid4().hex}"
    event = threading.Event()
    with CALLBACK_LOCK:
        CALLBACKS[callback_id] = [event, None]
    frame({"protocol_version": "1.1", "kind": "request", "sender": "plugin",
           "request_id": callback_id, "method": "core.http.fetch",
           "plugin_instance": request.get("plugin_instance"), "deadline_unix_ms": int((time.time() + 12) * 1000),
           "context": {"parent_request_id": request["request_id"]},
           "payload": {"method": "GET", "url": url, "headers": {"Accept": "application/json, text/plain, */*", "User-Agent": UA}, "response_mode": "json"}})
    if not event.wait(12):
        with CALLBACK_LOCK:
            CALLBACKS.pop(callback_id, None)
        raise RuntimeError("PLUGIN_TIMEOUT")
    with CALLBACK_LOCK:
        response = CALLBACKS.pop(callback_id)[1]
    if response.get("status") == "error":
        error = response.get("error") or {}
        raise CapabilityError(
            str(error.get("code") or "TEMPORARY_UPSTREAM_FAILURE"),
            retryable=bool(error.get("retryable")),
            category=str(error.get("category") or "capability"),
        )
    return response.get("result") or {}


def resolve(request: dict[str, Any]) -> None:
    resource = str((request.get("payload") or {}).get("resource_id") or "").strip("/").lower()
    key = ALIASES.get(resource, resource)
    entry = CHANNELS.get(key)
    if not entry:
        reply(request, error=provider_error("RESOURCE_NOT_FOUND", "FJTV channel is not supported"))
        return
    url, path, _name, referer = entry
    try:
        data = fetch(request, url)
        data = data.get("body") if isinstance(data, dict) else data
        if isinstance(data, dict) and data.get("error_code", 0) not in (0, None):
            raise RuntimeError("TEMPORARY_UPSTREAM_FAILURE")
        play_url = walk(data, path)
    except CapabilityError as exc:
        if exc.code in {"CAPABILITY_DENIED", "PLUGIN_TIMEOUT", "AUTH_FAILED", "RATE_LIMITED",
                        "TEMPORARY_UPSTREAM_FAILURE"}:
            reply(request, error={"code": exc.code, "message": "FJTV Core capability failed",
                                  "retryable": exc.retryable, "category": exc.category, "details": {}})
        else:
            reply(request, error=provider_error(
                "TEMPORARY_UPSTREAM_FAILURE", "FJTV upstream response was invalid", retryable=True,
            ))
        return
    except RuntimeError:
        reply(request, error=provider_error("TEMPORARY_UPSTREAM_FAILURE", "FJTV upstream request failed", retryable=True))
        return
    except (KeyError, IndexError, TypeError):
        reply(request, error=provider_error("TEMPORARY_UPSTREAM_FAILURE", "FJTV upstream response was malformed", retryable=True))
        return
    if not isinstance(play_url, str) or not play_url.startswith(("http://", "https://")):
        reply(request, error=provider_error("NOT_LIVE", "FJTV channel has no playable stream", retryable=True))
        return
    reply(request, {"descriptor_version": "1.0", "transport": "hls", "url": play_url,
                    "headers": {"Referer": referer}, "credential_refs": [], "ttl_seconds": 180,
                    "expires_at": None, "volatile_url": True, "requires_proxy": False, "warnings": []})


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--identity", default="org.waveflow/fjtv")
    parser.add_argument("--version", default="1.0.0")
    args = parser.parse_args()
    while True:
        request = read_frame()
        if request is None:
            return
        if request.get("kind") == "response" and request.get("sender") == "core":
            with CALLBACK_LOCK:
                callback = CALLBACKS.get(request.get("request_id"))
                if callback:
                    callback[1] = request
                    callback[0].set()
            continue
        method = request.get("method")
        if method == "runtime.hello":
            frame({"protocol_version": "1.1", "kind": "response", "sender": "plugin",
                   "request_id": request["request_id"], "status": "ok", "result": {
                       "protocol_version": "1.1", "plugin": args.identity, "version": args.version,
                       "provider_contracts": [{"contract": "tv_provider", "contract_version": "1.0", "features": ["resolve_stream"]}],
                       "owned_schemes": [{"scheme": "fjtv", "contract": "tv_provider"}],
                       "capabilities": ["tv.resolve_stream"], "permissions": ["network"]},
                   "error": None, "diagnostics": {}})
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
