"""Production Radio domain bridge.

This module deliberately keeps Radio storage and routing separate from the
IPTV channel model.  It owns only the small amount of data needed to publish a
Plugin catalog and resolve an explicitly selected Radio source.  Media bytes
still flow through the existing signed-handle/proxy pipeline.
"""

from __future__ import annotations

import asyncio
import copy
import time
from typing import Any

import database
from plugin_runtime import PluginError
from plugin_runtime.validation import validate_radio_catalog
from provider_resolver import ProviderResolver
from security.source_ids import MediaSourceIdentity, media_source_id_for, media_source_revision_for


RADIO_DOMAIN = "radio"
RADIO_CATALOG_STALE_GRACE_SECONDS = 300
RADIO_DESCRIPTOR_CACHE_DEFAULT_TTL_SECONDS = 300


def radio_station_identity(owner_identity: str, provider_key: str, provider_station_id: str) -> MediaSourceIdentity:
    return MediaSourceIdentity(
        RADIO_DOMAIN,
        owner_identity,
        f"{provider_key.strip().lower()}:{provider_station_id.strip()}",
    )


def radio_source_id(owner_identity: str, provider_key: str, provider_station_id: str) -> str:
    return media_source_id_for(radio_station_identity(owner_identity, provider_key, provider_station_id))


def radio_station_id(owner_identity: str, provider_key: str, provider_station_id: str) -> str:
    # Keep the station container visibly in the Radio namespace while deriving
    # it from the same non-URL identity material as its source.
    return f"radio_station_{radio_source_id(owner_identity, provider_key, provider_station_id)[4:]}"


def _error_text(error: BaseException) -> str:
    text = str(error).replace("\x00", "").strip()
    return text[:2048] or error.__class__.__name__


class RadioCatalogBridge:
    """Validate and atomically project one Plugin Radio catalog."""

    async def refresh(
        self,
        owner_identity: str,
        catalog: dict[str, Any],
        *,
        owned_schemes: set[str] | frozenset[str],
        now: float | None = None,
    ) -> dict:
        normalized = validate_radio_catalog(catalog, owned_schemes=owned_schemes)
        now_value = float(now if now is not None else time.time())
        rows: list[dict[str, Any]] = []
        for item in normalized["stations"]:
            ref = dict(item["station_ref"])
            provider_key = ref["provider_key"].strip().lower()
            provider_station_id = ref["provider_station_id"].strip()
            source_id = radio_source_id(owner_identity, provider_key, provider_station_id)
            station_id = radio_station_id(owner_identity, provider_key, provider_station_id)
            playback_config = dict(item.get("playback_config") or {})
            source_revision = media_source_revision_for({
                "domain": RADIO_DOMAIN,
                "owner": owner_identity,
                "provider_key": provider_key,
                "provider_station_id": provider_station_id,
                "reference": ref,
                "playback_config": playback_config,
            })
            ttl = int(item.get("ttl_seconds", 300))
            rows.append({
                "station_id": station_id,
                "source_id": source_id,
                "owner_identity": owner_identity,
                "provider_key": provider_key,
                "provider_station_id": provider_station_id,
                "name": item["name"],
                "logo_url": item.get("logo_url", ""),
                "group_name": item.get("group_name", ""),
                "country": item.get("country", ""),
                "language": item.get("language", ""),
                "frequency": item.get("frequency", ""),
                "metadata": dict(item.get("metadata") or {}),
                "reference": {"station_ref": ref, "playback_config": playback_config},
                "source_revision": source_revision,
                "explicit_priority": int(item.get("priority", 0)),
                "ttl_seconds": ttl,
                "catalog_expires_at": now_value + ttl,
            })
        return await database.apply_radio_catalog(
            owner_identity,
            rows,
            now_unix=now_value,
            stale_grace_seconds=RADIO_CATALOG_STALE_GRACE_SECONDS,
        )

    async def record_failure(self, owner_identity: str, error: BaseException) -> None:
        await database.record_radio_catalog_failure(owner_identity, _error_text(error))


class RadioResolver:
    """Resolve a persisted Radio source through the Plugin runtime only."""

    def __init__(self, *, runtime=None, clock=time.time):
        self.runtime = runtime
        self.clock = clock
        self._descriptor_cache: dict[tuple[str, str, str], tuple[float, dict[str, Any]]] = {}
        self._locks: dict[tuple[str, str, str], asyncio.Lock] = {}

    def _lock_for(self, key: tuple[str, str, str]) -> asyncio.Lock:
        lock = self._locks.get(key)
        if lock is None:
            lock = asyncio.Lock()
            self._locks[key] = lock
        return lock

    async def resolve_source(self, source_id: str, *, station_id: str = "") -> dict[str, Any]:
        source = await database.get_radio_station_source(
            source_id, station_id=station_id, now_unix=float(self.clock()),
        )
        if source is None or source.get("lifecycle_state") == "expired":
            raise PluginError("RESOURCE_NOT_FOUND", "Radio source is unavailable", category="routing")
        owner = str(source.get("owner_identity") or "")
        provider_key = str(source.get("provider_key") or "").strip().lower()
        revision = str(source.get("source_revision") or "")
        key = (RADIO_DOMAIN, str(source_id), revision)
        now = float(self.clock())
        cached = self._descriptor_cache.get(key)
        if cached and cached[0] > now:
            return copy.deepcopy(cached[1])
        if self.runtime is None:
            raise PluginError("PLUGIN_UNAVAILABLE", "Radio Plugin runtime is unavailable", category="lifecycle")

        async with self._lock_for(key):
            now = float(self.clock())
            cached = self._descriptor_cache.get(key)
            if cached and cached[0] > now:
                return copy.deepcopy(cached[1])
            try:
                instance = self.runtime.registry.route(provider_key)
                if instance.manifest.identity != owner:
                    raise PluginError(
                        "SCHEME_CONFLICT", "Radio source owner does not match the active Plugin", category="routing",
                    )
                owned = {
                    scheme for scheme, contract in instance.manifest.owned_schemes
                    if contract == "radio_provider"
                }
                if not owned:
                    # Compatibility for the pre-existing mixed TV/Radio V1
                    # fixture. Production Radio manifests declare the radio
                    # contract on their owned scheme explicitly.
                    owned = {scheme for scheme, _contract in instance.manifest.owned_schemes}
                if provider_key not in owned:
                    raise PluginError(
                        "SCHEME_CONFLICT", "Active Plugin does not own this Radio scheme", category="routing",
                    )
                reference = source.get("reference") or {}
                station_ref = reference.get("station_ref") if isinstance(reference, dict) else None
                if not isinstance(station_ref, dict):
                    raise PluginError("INVALID_PLUGIN_RESPONSE", "Persisted Radio reference is invalid", category="routing")
                descriptor = await self.runtime.request(
                    instance, "radio.resolve_stream", {"station_ref": station_ref},
                )
                # Keep the Radio projection aligned with the existing TV
                # descriptor bridge. Domain/source fields are additive routing
                # context; transport and generic metadata use one validator.
                bridged = ProviderResolver._bridge_descriptor(provider_key, descriptor)
                bridged.update({
                    "domain": RADIO_DOMAIN,
                    "station_id": source.get("station_id"),
                    "source_id": source_id,
                    "source_revision": revision,
                })
                ttl = descriptor.get("ttl_seconds")
                cache_ttl = (
                    int(ttl) if isinstance(ttl, int) and ttl > 0
                    else RADIO_DESCRIPTOR_CACHE_DEFAULT_TTL_SECONDS if ttl is None else 0
                )
                expires_at = now + cache_ttl if cache_ttl else now
                if cache_ttl:
                    self._descriptor_cache[key] = (expires_at, copy.deepcopy(bridged))
                await database.update_radio_source_health(
                    source_id, success=True, resolve_expires_at=expires_at,
                )
                return bridged
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                await database.update_radio_source_health(source_id, success=False, error=_error_text(exc))
                raise

    def invalidate(self, source_id: str, source_revision: str | None = None) -> None:
        keys = [key for key in self._descriptor_cache if key[1] == source_id and (source_revision is None or key[2] == source_revision)]
        for key in keys:
            self._descriptor_cache.pop(key, None)
