"""HMAC 签名的代理 Handle。

格式::

    base64url(json_payload) + "." + base64url(hmac_sha256(json_payload, key))

Payload schema (v=1)::

    {
        "v": 1,
        "kind": "playlist|chunk|stream|rtsp|image",
        "url": "<absolute upstream url>",   # http(s) for non-rtsp; rtsp:// for rtsp kind
        "exp": <unix seconds>,
        "src": "<channel:K | sub:N | adapter:Y | session:HEX>",   # 仅供日志/缓存，不参与上游解析
        "ctx": "<proxy_context id, optional>",                    # 临时 header 上下文 ID
        "src_id": "<channel canonical_key, optional>",            # 稳定频道引用
        "compat": 0|1,                                            # 仅 rtsp kind 使用
    }

调用方约束：

* 路由层根据 ``kind`` 选择对应 ``decode_for_kind``，从而强制 kind 与路由一致。
* Payload 的 ``url`` 字段在使用前必须再次跑 SSRF 校验；HMAC 仅证明「我们之前签过」，
  不能跳过策略变化（``allow_private`` 运行时关闭、DNS rebinding 等）。
* 不同 kind 使用不同 TTL：playlist 较短，chunk 中等，rtsp 较长（直播分片）。
"""

from __future__ import annotations

import base64
import hmac
import json
import time
from dataclasses import dataclass
from typing import Any

from security.secrets import PROXY_HANDLE_PURPOSE, derive_key


HANDLE_VERSION = 1

VALID_KINDS = frozenset({"playlist", "chunk", "stream", "rtsp", "image"})

# 不同 kind 默认 TTL（秒）。Handle 真正的过期时间存在 payload.exp 里；
# 这只是「签发时还没显式给 exp」时的兜底。
DEFAULT_TTL_BY_KIND: dict[str, int] = {
    "playlist": 15 * 60,   # 15 min；hls.js 长直播可以重新拉父 playlist
    "chunk":    30 * 60,   # 30 min；分片 URL 必须能比 playlist 久一点
    "stream":   30 * 60,   # MPEG-TS / FLV 直连流，连接期内复用
    "rtsp":     60 * 60,   # RTSP→HLS session 本身可以更长
    "image":    24 * 60 * 60,  # adapter 封面图，CDN URL 长期 stable
}


class HandleError(Exception):
    """通用 handle 解码失败基类。"""

    status_code: int = 400


class HandleFormatError(HandleError):
    status_code = 400


class HandleSignatureError(HandleError):
    status_code = 400


class HandleVersionError(HandleError):
    status_code = 400


class HandleKindMismatch(HandleError):
    status_code = 400


class HandleExpired(HandleError):
    status_code = 410


@dataclass(frozen=True)
class HandlePayload:
    v: int
    kind: str
    url: str
    exp: int
    src: str = ""
    ctx: str = ""
    src_id: str = ""
    compat: int = 0


def _b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64url_decode(text: str) -> bytes:
    pad = (-len(text)) % 4
    return base64.urlsafe_b64decode(text + ("=" * pad))


def _key() -> bytes:
    return derive_key(PROXY_HANDLE_PURPOSE)


def _now() -> int:
    return int(time.time())


def issue_handle(
    *,
    kind: str,
    url: str,
    ttl_seconds: int | None = None,
    src: str = "",
    ctx: str = "",
    src_id: str = "",
    compat: int = 0,
) -> str:
    if kind not in VALID_KINDS:
        raise ValueError(f"未知 handle kind: {kind}")
    if not url:
        raise ValueError("handle url 不能为空")
    ttl = int(ttl_seconds) if ttl_seconds is not None else DEFAULT_TTL_BY_KIND[kind]
    if ttl <= 0:
        raise ValueError("handle TTL 必须大于 0")
    payload: dict[str, Any] = {
        "v": HANDLE_VERSION,
        "kind": kind,
        "url": url,
        "exp": _now() + ttl,
    }
    if src:
        payload["src"] = src
    if ctx:
        payload["ctx"] = ctx
    if src_id:
        payload["src_id"] = src_id
    if compat:
        payload["compat"] = 1
    body = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    sig = hmac.new(_key(), body, "sha256").digest()
    return f"{_b64url_encode(body)}.{_b64url_encode(sig)}"


def _parse_payload(raw: str) -> tuple[dict[str, Any], bytes, bytes]:
    if not raw or "." not in raw:
        raise HandleFormatError("handle 格式无效")
    payload_part, _, sig_part = raw.partition(".")
    if not payload_part or not sig_part:
        raise HandleFormatError("handle 缺少签名段")
    # 字符集预检
    allowed = set(
        "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_"
    )
    if not (set(payload_part) <= allowed and set(sig_part) <= allowed):
        raise HandleFormatError("handle 含非法字符")
    try:
        body = _b64url_decode(payload_part)
        sig = _b64url_decode(sig_part)
    except (ValueError, base64.binascii.Error) as exc:
        raise HandleFormatError(f"handle base64 解码失败: {exc}") from exc
    try:
        data = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise HandleFormatError(f"handle JSON 解码失败: {exc}") from exc
    if not isinstance(data, dict):
        raise HandleFormatError("handle payload 必须是 object")
    return data, body, sig


def decode_for_kind(raw: str, expected_kind: str) -> HandlePayload:
    """全量校验：格式 → 版本 → HMAC → exp → kind 匹配。

    SSRF 校验由调用方在拿到 payload 之后单独跑（因为策略可能在签发后变化）。
    """
    if expected_kind not in VALID_KINDS:
        raise ValueError(f"未知 handle kind: {expected_kind}")

    data, body, sig = _parse_payload(raw)

    version = data.get("v")
    if not isinstance(version, int) or version != HANDLE_VERSION:
        raise HandleVersionError("handle 版本不被接受")

    expected_sig = hmac.new(_key(), body, "sha256").digest()
    if not hmac.compare_digest(expected_sig, sig):
        raise HandleSignatureError("handle 签名无效")

    kind = data.get("kind")
    if not isinstance(kind, str) or kind not in VALID_KINDS:
        raise HandleFormatError("handle kind 字段无效")
    if kind != expected_kind:
        raise HandleKindMismatch("handle kind 与请求路由不匹配")

    exp = data.get("exp")
    if not isinstance(exp, int):
        raise HandleFormatError("handle exp 字段无效")
    if exp <= _now():
        raise HandleExpired("handle 已过期")

    url = data.get("url")
    if not isinstance(url, str) or not url:
        raise HandleFormatError("handle url 字段无效")

    src = data.get("src", "")
    ctx = data.get("ctx", "")
    src_id = data.get("src_id", "")
    compat_raw = data.get("compat", 0)
    compat = 1 if compat_raw else 0

    return HandlePayload(
        v=version,
        kind=kind,
        url=url,
        exp=exp,
        src=str(src) if isinstance(src, str) else "",
        ctx=str(ctx) if isinstance(ctx, str) else "",
        src_id=str(src_id) if isinstance(src_id, str) else "",
        compat=compat,
    )
