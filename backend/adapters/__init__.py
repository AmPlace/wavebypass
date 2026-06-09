import asyncio
import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import parse_qs, urlparse

import httpx


ADAPTER_SUCCESS_TTL_SECONDS = 30 * 60
ADAPTER_FAILURE_TTL_SECONDS = 60


@dataclass(frozen=True)
class AdapterRequest:
    raw_url: str
    adapter: str
    resource_id: str
    query: dict[str, list[str]]


class AdapterResolveError(Exception):
    def __init__(
        self,
        error_code: str,
        message: str,
        *,
        status_code: int = 400,
        retryable: bool = False,
    ):
        super().__init__(message)
        self.error_code = error_code
        self.message = message
        self.status_code = status_code
        self.retryable = retryable

    def to_payload(self) -> dict[str, Any]:
        return {
            "ok": False,
            "error_code": self.error_code,
            "message": self.message,
            "retryable": self.retryable,
        }


_adapter_cache: dict[str, dict[str, Any]] = {}
_adapter_locks: dict[str, asyncio.Lock] = {}


def _cache_get(cache_key: str) -> dict[str, Any] | None:
    item = _adapter_cache.get(cache_key)
    if not item:
        return None
    if float(item.get("expires_at", 0)) <= time.time():
        _adapter_cache.pop(cache_key, None)
        return None
    if item.get("error"):
        err = item["error"]
        raise AdapterResolveError(
            err["error_code"],
            err["message"],
            status_code=int(err.get("status_code", 400)),
            retryable=bool(err.get("retryable")),
        )
    result = item.get("result")
    return dict(result) if isinstance(result, dict) else None


def _cache_success(cache_key: str, result: dict[str, Any]) -> None:
    ttl = int(result.get("ttl") or ADAPTER_SUCCESS_TTL_SECONDS)
    _adapter_cache[cache_key] = {
        "expires_at": time.time() + max(1, ttl),
        "result": dict(result),
    }


def _cache_failure(cache_key: str, exc: AdapterResolveError) -> None:
    _adapter_cache[cache_key] = {
        "expires_at": time.time() + ADAPTER_FAILURE_TTL_SECONDS,
        "error": {
            **exc.to_payload(),
            "status_code": exc.status_code,
        },
    }


def parse_adapter_url(target_url: str) -> AdapterRequest:
    raw_url = (target_url or "").strip()
    if not raw_url:
        raise AdapterResolveError("invalid_adapter_url", "adapter 地址不能为空")
    if len(raw_url) > 2048:
        raise AdapterResolveError("invalid_adapter_url", "adapter 地址过长")

    try:
        parsed = urlparse(raw_url)
    except ValueError as exc:
        raise AdapterResolveError("invalid_adapter_url", "adapter 地址格式错误") from exc

    scheme = parsed.scheme.lower()
    if scheme == "migu":
        adapter = "migu"
        resource_id = (parsed.netloc or parsed.path.lstrip("/")).strip()
    elif scheme == "douyin":
        adapter = "douyin"
        resource_id = (parsed.netloc or parsed.path.lstrip("/")).strip()
    elif scheme == "douyu":
        adapter = "douyu"
        resource_id = (parsed.netloc or parsed.path.lstrip("/")).strip()
    elif scheme == "huya":
        adapter = "huya"
        resource_id = (parsed.netloc or parsed.path.lstrip("/")).strip()
    elif scheme == "redbook":
        adapter = "redbook"
        resource_id = (parsed.netloc or parsed.path.lstrip("/")).strip()
    elif scheme == "tiktok":
        adapter = "tiktok"
        resource_id = (parsed.netloc or parsed.path.lstrip("/")).strip()
    elif scheme == "kuaishou":
        adapter = "kuaishou"
        resource_id = (parsed.netloc or parsed.path.lstrip("/")).strip()
    elif scheme == "bilibili":
        adapter = "bilibili"
        resource_id = (parsed.netloc or parsed.path.lstrip("/")).strip()
    elif scheme == "adapter":
        adapter = (parsed.netloc or "").lower().split("@")[-1].split(":")[0]
        resource_id = parsed.path.lstrip("/").strip()
    else:
        raise AdapterResolveError(
            "invalid_adapter_url",
            "只允许 migu://、douyin://、douyu://、huya://、redbook://、tiktok://、kuaishou://、bilibili:// 或 adapter:// 开头的 adapter 地址",
        )

    if not adapter or adapter not in _ADAPTER_REGISTRY:
        raise AdapterResolveError("unsupported_adapter", "暂不支持该 adapter")
    if not resource_id:
        raise AdapterResolveError("invalid_adapter_url", "adapter 缺少资源 ID")

    return AdapterRequest(
        raw_url=raw_url,
        adapter=adapter,
        resource_id=resource_id,
        query=parse_qs(parsed.query, keep_blank_values=False),
    )


async def resolve_adapter_source(target_url: str, client: httpx.AsyncClient) -> dict[str, Any]:
    request = parse_adapter_url(target_url)
    cache_key = request.raw_url

    cached = _cache_get(cache_key)
    if cached:
        return cached

    lock = _adapter_locks.setdefault(cache_key, asyncio.Lock())
    async with lock:
        cached = _cache_get(cache_key)
        if cached:
            return cached

        resolver = _ADAPTER_REGISTRY[request.adapter]
        try:
            result = await resolver(request, client)
            result.setdefault("ok", True)
            result.setdefault("adapter", request.adapter)
            result.setdefault("source_type", "hls")
            result.setdefault("direct_playable", True)
            result.setdefault("requires_proxy", False)
            result.setdefault("headers", {})
            result.setdefault("ttl", ADAPTER_SUCCESS_TTL_SECONDS)
            result.setdefault("expires_at", None)
            result.setdefault("warnings", [])
            _cache_success(cache_key, result)
            return dict(result)
        except AdapterResolveError as exc:
            _cache_failure(cache_key, exc)
            raise


from .migu import resolve_migu
from .douyin import resolve_douyin
from .douyu import resolve_douyu
from .huya import resolve_huya
from .redbook import resolve_redbook
from .tiktok import resolve_tiktok
from .kuaishou import resolve_kuaishou
from .bilibili import resolve_bilibili


_ADAPTER_REGISTRY = {
    "migu": resolve_migu,
    "douyin": resolve_douyin,
    "douyu": resolve_douyu,
    "huya": resolve_huya,
    "redbook": resolve_redbook,
    "tiktok": resolve_tiktok,
    "kuaishou": resolve_kuaishou,
    "bilibili": resolve_bilibili,
}
