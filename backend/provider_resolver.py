from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Awaitable, Callable
from urllib.parse import parse_qs, urlparse

import httpx

from adapters import AdapterRequest, AdapterResolveError, parse_adapter_url, resolve_adapter_source
from plugin_runtime import PluginError, PluginRuntime


OWNERSHIP_MODES = frozenset({"legacy", "plugin", "migration_test"})


@dataclass(frozen=True)
class TVReferenceV1:
    raw_url: str
    scheme: str
    resource_id: str
    query: dict[str, list[str]]


def parse_tv_reference(value: str) -> TVReferenceV1:
    raw = str(value or "").strip()
    try:
        legacy = parse_adapter_url(raw)
    except AdapterResolveError:
        parsed = urlparse(raw)
        scheme = parsed.scheme.lower()
        resource = (parsed.netloc + parsed.path).strip("/")
        if not scheme or not resource:
            raise
        return TVReferenceV1(raw, scheme, resource, parse_qs(parsed.query, keep_blank_values=False))
    return TVReferenceV1(legacy.raw_url, legacy.adapter, legacy.resource_id, legacy.query)


class ProviderResolver:
    def __init__(
        self, *, runtime: PluginRuntime | None,
        ownership: dict[str, str] | None = None,
        legacy_resolver: Callable[[str, httpx.AsyncClient], Awaitable[dict[str, Any]]] = resolve_adapter_source,
    ):
        self.runtime = runtime
        self.legacy_resolver = legacy_resolver
        self._ownership = {str(k).lower(): str(v) for k, v in (ownership or {}).items()}
        self._expected_plugins: dict[str, str] = {}
        if any(mode not in OWNERSHIP_MODES for mode in self._ownership.values()):
            raise ValueError("invalid provider ownership mode")

    def mode(self, scheme: str) -> str:
        return self._ownership.get(scheme.lower(), "legacy")

    def set_mode(self, scheme: str, mode: str, plugin_identity: str = "") -> None:
        if mode not in OWNERSHIP_MODES:
            raise ValueError("invalid provider ownership mode")
        self._ownership[scheme.lower()] = mode
        if mode == "legacy":
            self._expected_plugins.pop(scheme.lower(), None)
        elif plugin_identity:
            self._expected_plugins[scheme.lower()] = plugin_identity

    async def resolve(self, target_url: str, client: httpx.AsyncClient) -> dict[str, Any]:
        reference = parse_tv_reference(target_url)
        mode = self.mode(reference.scheme)
        if mode == "legacy":
            return await self.legacy_resolver(target_url, client)
        if self.runtime is None:
            raise PluginError("PLUGIN_UNAVAILABLE", "Plugin subsystem is unavailable", category="lifecycle")
        instance = self.runtime.registry.route(reference.scheme)
        expected = self._expected_plugins.get(reference.scheme)
        if expected and instance.manifest.identity != expected:
            raise PluginError("SCHEME_CONFLICT", "Configured Plugin does not own this scheme", category="routing")
        descriptor = await self.runtime.request(instance, "tv.resolve_stream", {
            "reference_version": "1.0",
            "scheme": reference.scheme,
            "resource_id": reference.resource_id,
            "query": reference.query,
            "raw_reference": reference.raw_url,
        })
        return self._bridge_descriptor(reference.scheme, descriptor)

    @staticmethod
    def _bridge_descriptor(scheme: str, descriptor: dict[str, Any]) -> dict[str, Any]:
        transport = str(descriptor.get("transport") or "hls")
        return {
            "ok": True,
            "adapter": scheme,
            "url": descriptor.get("url") or "",
            "source_type": transport,
            "direct_playable": not bool(descriptor.get("requires_proxy")),
            "requires_proxy": bool(descriptor.get("requires_proxy")),
            "headers": dict(descriptor.get("headers") or {}),
            "ttl": descriptor.get("ttl_seconds"),
            "expires_at": descriptor.get("expires_at"),
            "volatile_url": bool(descriptor.get("volatile_url")),
            "warnings": list(descriptor.get("warnings") or []),
            "stream_descriptor_version": descriptor.get("descriptor_version"),
        }
