"""轻量 Cover 缓存：不依赖全量频道聚合的按 key 查询。

核心设计：
1. 频道索引缓存（canonical_key → channel dict），TTL 60s，避免每次 /cover 都跑全量聚合。
2. Cover 结果缓存（成功/失败分开 TTL），有界 LRU。
3. 并发 single-flight：同一 key 的并发请求合并为一次执行。
4. Adapter cover fetcher 专用 Semaphore（4），防止过载。
5. 不持有任何锁执行远端网络请求。

安全边界：
* 不恢复 raw URL 代理；
* 不绕过 handle 签名/SSRF/Media Access；
* 不把管理员凭证写入 URL。
"""

from __future__ import annotations

import asyncio
import time
from collections import OrderedDict
from typing import Any

_COVER_CHANNEL_INDEX_TTL = 60           # 频道索引缓存 60s
_COVER_SUCCESS_TTL = 30 * 60            # 成功封面缓存 30min
_COVER_FAILURE_TTL = 2 * 60             # 失败封面缓存 2min
_COVER_MAX_ENTRIES = 2048               # 最大缓存条目
_COVER_MAX_CONCURRENT_FETCHES = 4       # adapter fetch 最大并发


class CoverCache:
    """封面专用缓存：index + result + single-flight + semaphore。"""

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        # 频道索引缓存
        self._index: list[dict] | None = None
        self._index_expires: float = 0.0
        # Cover 结果缓存
        self._results: OrderedDict[str, dict] = OrderedDict()
        self._expires: dict[str, float] = {}
        # Single-flight: key → asyncio.Event + result
        self._inflight: dict[str, asyncio.Event] = {}
        self._inflight_results: dict[str, dict] = {}
        # Adapter fetch 并发限制
        self._semaphore = asyncio.Semaphore(_COVER_MAX_CONCURRENT_FETCHES)

    async def _get_channel_index(self) -> list[dict]:
        """获取或刷新频道索引（线程安全，仅首次或过期时重建）。"""
        now = time.time()
        if self._index is not None and now < self._index_expires:
            return self._index
        async with self._lock:
            if self._index is not None and now < self._index_expires:
                return self._index
            import main as _m
            channels, _groups = await _m._get_aggregated_iptv_channels()
            self._index = channels
            self._index_expires = now + _COVER_CHANNEL_INDEX_TTL
            return self._index

    async def get_channel(self, canonical_key: str) -> dict | None:
        """按 canonical_key 查频道（使用缓存索引）。"""
        channels = await self._get_channel_index()
        return next((ch for ch in channels if ch.get("canonical_key") == canonical_key), None)

    def _cached_result(self, key: str) -> dict | None:
        now = time.time()
        expires = self._expires.get(key, 0)
        if expires > now:
            return self._results.get(key)
        if key in self._results:
            # 过期淘汰
            self._results.pop(key, None)
            self._expires.pop(key, None)
        return None

    def _set_result(self, key: str, value: dict, ttl: int) -> None:
        self._results[key] = value
        self._expires[key] = time.time() + ttl
        self._results.move_to_end(key)
        while len(self._results) > _COVER_MAX_ENTRIES:
            self._results.popitem(last=False)

    async def get_or_fetch(
        self,
        canonical_key: str,
        adapter_source_url: str | None,
        logo_url: str,
        channel_name: str,
    ) -> dict:
        """获取 cover 结果（缓存命中 / single-flight 合并 / 新 fetch）。

        ``adapter_source_url`` 为 None 表示非 adapter 频道，直接返回 logo 兜底。
        """
        # 非 adapter：直接兜底（也缓存避免重复查索引）
        if not adapter_source_url:
            cache_key = f"noop:{canonical_key}"
            cached = self._cached_result(cache_key)
            if cached:
                return cached
            result = {
                "ok": True,
                "adapter": "",
                "cover_url": logo_url,
                "avatar_url": "",
                "title": channel_name,
                "anchor_name": "",
                "is_live": False,
            }
            self._set_result(cache_key, result, _COVER_SUCCESS_TTL)
            return result

        # 按 adapter source URL 缓存（不同 canonical_key 可能共享同一 adapter URL）
        cache_key = f"adapter:{adapter_source_url}"

        # 1. 缓存命中
        cached = self._cached_result(cache_key)
        if cached:
            return cached

        # 2. Single-flight：已有正在进行的请求
        if cache_key in self._inflight:
            event = self._inflight[cache_key]
            await event.wait()
            return self._inflight_results.get(cache_key) or self._empty_result()

        # 3. 新 fetch
        event = asyncio.Event()
        self._inflight[cache_key] = event
        try:
            async with self._semaphore:
                import main as _m
                try:
                    payload = await asyncio.wait_for(
                        _m.fetch_adapter_cover_payload(adapter_source_url),
                        timeout=5.0,
                    )
                    ttl = _COVER_SUCCESS_TTL
                except asyncio.TimeoutError:
                    payload = self._empty_result()
                    ttl = _COVER_FAILURE_TTL
                except Exception:
                    payload = self._empty_result()
                    ttl = _COVER_FAILURE_TTL

            self._set_result(cache_key, payload, ttl)
            self._inflight_results[cache_key] = payload
            return payload
        finally:
            self._inflight.pop(cache_key, None)
            self._inflight_results.pop(cache_key, None)

    def _empty_result(self) -> dict:
        return {
            "ok": True,
            "adapter": "",
            "cover_url": "",
            "avatar_url": "",
            "title": "",
            "anchor_name": "",
            "is_live": False,
        }


# 进程级单例
_cover_cache = CoverCache()


def get_cover_cache() -> CoverCache:
    return _cover_cache
