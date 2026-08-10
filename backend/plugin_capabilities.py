from __future__ import annotations

import logging
from typing import Any

import httpx

from plugin_runtime import PluginError
from plugin_runtime.permissions import PermissionGate
from ssrf_guard import UnsafeTargetError, assert_safe_target_url


class CapabilityGateway:
    def __init__(self, *, client: httpx.AsyncClient, max_response_bytes: int = 2 * 1024 * 1024):
        self.client = client
        self.max_response_bytes = max_response_bytes
        self._cache: dict[str, dict[str, Any]] = {}
        self._config: dict[str, dict[str, Any]] = {}

    async def managed_http_get(self, identity: str, gate: PermissionGate, url: str) -> dict[str, Any]:
        policy = gate.require("network")
        allow_private = bool(policy.get("allow_private")) if isinstance(policy, dict) else False
        try:
            await assert_safe_target_url(url, allow_private=allow_private, allow_loopback=False, allowed_schemes={"https"})
        except UnsafeTargetError as exc:
            raise PluginError("CAPABILITY_DENIED", "Plugin network target is not permitted", category="permission") from exc
        try:
            async with self.client.stream("GET", url, follow_redirects=False) as response:
                response.raise_for_status()
                body = bytearray()
                async for chunk in response.aiter_bytes():
                    body.extend(chunk)
                    if len(body) > self.max_response_bytes:
                        raise PluginError("CAPABILITY_DENIED", "Plugin HTTP response exceeds the limit", category="permission")
                return {"status": response.status_code, "body": bytes(body), "content_type": response.headers.get("content-type", "")}
        except httpx.HTTPError as exc:
            raise PluginError("TEMPORARY_UPSTREAM_FAILURE", "Managed HTTP request failed", retryable=True, category="network") from exc

    def log(self, identity: str, level: str, message: str, fields: dict[str, Any] | None = None) -> None:
        logger = logging.getLogger("waveflow.plugin")
        method = getattr(logger, level.lower(), logger.info)
        method("plugin_event", extra={"plugin": identity, "message": str(message)[:500], "fields": dict(fields or {})})

    def cache_get(self, identity: str, gate: PermissionGate, key: str) -> Any:
        gate.require("cache")
        return self._cache.setdefault(identity, {}).get(key)

    def cache_set(self, identity: str, gate: PermissionGate, key: str, value: Any) -> None:
        gate.require("cache")
        self._cache.setdefault(identity, {})[key] = value

    def scoped_config(self, identity: str) -> dict[str, Any]:
        return dict(self._config.get(identity, {}))

    def set_scoped_config(self, identity: str, values: dict[str, Any]) -> None:
        self._config[identity] = dict(values)
