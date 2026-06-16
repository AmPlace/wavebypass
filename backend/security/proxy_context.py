"""短期 Proxy Context Registry。

用途：adapter 解析后产生的「临时 HTTP Header」（custom_ua / referer / cookie 等）
不能写进签名 handle 的 payload（cookie 明文落 URL 即便 base64 也违反规范），
也不应频繁写 SQLite。改为存进进程内有界 LRU+TTL，handle 仅携带 ctx_id。

约束：

* TTL 与 handle TTL 解耦：context 通常匹配 handle 寿命的最大值。
* 容量上限：超过则 LRU 淘汰，避免 adapter 频繁切频道时无界增长。
* 重启即丢：客户端会重新打 ``/api/media/channel/{id}/playlist.m3u8`` 入口拿新 ctx + handle。
* 永远不持久化敏感 header。

对外暴露 ``put`` / ``get``，``get`` 命中 expired 视为「不存在」。
"""

from __future__ import annotations

import secrets
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass, field


_DEFAULT_TTL = 30 * 60   # 30 min；与最长 handle TTL 持平
_DEFAULT_MAX_ENTRIES = 2048


@dataclass
class ProxyContext:
    """进程内的临时上游请求上下文。

    存的字段都「可以丢」。一旦丢了客户端会重新走入口接口拿新的，不影响业务。
    """
    custom_ua: str = ""
    referer: str = ""
    cookie: str = ""
    no_ua: bool = False
    upstream_url: str = ""
    source_type: str = ""    # adapter 解析得出，hls/mpegts/http_flv/rtsp...
    source_id: str = ""      # canonical_key 或 channel_id；调试 + 风控用
    expires_at: float = 0.0
    extras: dict = field(default_factory=dict)


class ProxyContextRegistry:
    def __init__(self, *, max_entries: int = _DEFAULT_MAX_ENTRIES, default_ttl: int = _DEFAULT_TTL) -> None:
        self._lock = threading.Lock()
        self._items: OrderedDict[str, ProxyContext] = OrderedDict()
        self._max = max_entries
        self._default_ttl = default_ttl

    def _now(self) -> float:
        return time.time()

    def _purge_expired_locked(self) -> None:
        now = self._now()
        # 一次最多扫尾部 16 条；避免被恶意打满后 put 时阻塞过久。
        scan_budget = 16
        for key in list(self._items.keys())[:scan_budget]:
            ctx = self._items.get(key)
            if ctx and ctx.expires_at <= now:
                self._items.pop(key, None)

    def put(self, ctx: ProxyContext, *, ttl: int | None = None) -> str:
        """写入并返回不透明 ctx_id。"""
        ctx_id = secrets.token_urlsafe(18)
        ctx.expires_at = self._now() + (ttl if ttl is not None else self._default_ttl)
        with self._lock:
            self._purge_expired_locked()
            self._items[ctx_id] = ctx
            self._items.move_to_end(ctx_id)
            while len(self._items) > self._max:
                self._items.popitem(last=False)
        return ctx_id

    def get(self, ctx_id: str) -> ProxyContext | None:
        if not ctx_id:
            return None
        with self._lock:
            ctx = self._items.get(ctx_id)
            if not ctx:
                return None
            if ctx.expires_at <= self._now():
                self._items.pop(ctx_id, None)
                return None
            self._items.move_to_end(ctx_id)
            return ctx

    def drop(self, ctx_id: str) -> bool:
        if not ctx_id:
            return False
        with self._lock:
            return self._items.pop(ctx_id, None) is not None

    def clear(self) -> None:
        with self._lock:
            self._items.clear()

    def __len__(self) -> int:
        with self._lock:
            return len(self._items)


# 进程级单例。测试用 ``reset_for_tests`` 清空。
_registry = ProxyContextRegistry()


def get_registry() -> ProxyContextRegistry:
    return _registry


def reset_for_tests() -> None:
    _registry.clear()
