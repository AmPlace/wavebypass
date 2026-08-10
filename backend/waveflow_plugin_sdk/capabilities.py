from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from .errors import PluginError


@dataclass(frozen=True)
class CapabilityResponse:
    status: int
    headers: dict[str, str]
    body: Any
    response_mode: str


class CapabilityClient:
    def __init__(self, invoke: Callable[[str, dict[str, Any], float], Any]):
        self._invoke = invoke

    def call(self, method: str, payload: dict[str, Any], *, timeout: float = 10.0) -> Any:
        return self._invoke(method, payload, timeout)

    def managed_http(self, url: str, *, method: str = "GET", headers: dict[str, str] | None = None,
                     query: dict[str, Any] | None = None, json_body: Any = None, text_body: str | None = None,
                     response_mode: str = "text", timeout: float = 10.0) -> CapabilityResponse:
        if json_body is not None and text_body is not None:
            raise ValueError("managed_http accepts either json_body or text_body")
        payload: dict[str, Any] = {"method": method, "url": url, "headers": dict(headers or {}),
                                   "response_mode": response_mode}
        if query is not None:
            payload["query"] = dict(query)
        if json_body is not None:
            payload["body"] = {"json": json_body}
        elif text_body is not None:
            payload["body"] = {"text": text_body}
        result = self.call("core.http.fetch", payload, timeout=timeout)
        return CapabilityResponse(int(result.get("status", 0)), dict(result.get("headers") or {}),
                                  result.get("body"), str(result.get("response_mode") or response_mode))

    def cache_get(self, key: str, *, allow_stale: bool = False) -> dict[str, Any]:
        return self.call("core.cache.get", {"key": key, "allow_stale": allow_stale})

    def cache_set(self, key: str, value: Any, *, ttl_seconds: float | None = None) -> dict[str, Any]:
        return self.call("core.cache.set", {"key": key, "value": value, "ttl_seconds": ttl_seconds})

    def cache_delete(self, key: str) -> dict[str, Any]:
        return self.call("core.cache.delete", {"key": key})

    def config_get(self, key: str) -> dict[str, Any]:
        return self.call("core.config.get", {"key": key})

    def log(self, level: str, message: str, **fields: Any) -> None:
        self.call("core.log", {"level": level, "message": message, "fields": fields})

    def secret_get(self, name: str) -> Any:
        return self.call("core.secret.get", {"name": name})


def capability_error(error: dict[str, Any]) -> PluginError:
    return PluginError(str(error.get("code") or "TEMPORARY_UPSTREAM_FAILURE"),
                       str(error.get("message") or "Core capability failed"),
                       retryable=bool(error.get("retryable")),
                       category=str(error.get("category") or "capability"),
                       details=error.get("details") if isinstance(error.get("details"), dict) else {})
