from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import logging
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urljoin, urlparse

import httpx
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

import database as db
import market
from plugin_market import PluginArtifactStore, PluginMarketService, current_platform
from plugin_runtime import PluginError, PluginRuntime
from plugin_runtime.permissions import PermissionPolicy
from provider_resolver import ProviderResolver
from plugin_capabilities import CapabilityGateway, CoreCapabilityDispatcher


logger = logging.getLogger(__name__)
MAX_PLUGIN_ARTIFACT_BYTES = 64 * 1024 * 1024
PLUGIN_DOWNLOAD_TIMEOUT_SECONDS = 60.0
PLUGIN_DOWNLOAD_REDIRECTS = 3


class ProductionTrustPolicy:
    def __init__(self, rows: Iterable[dict[str, Any]] = ()):
        self.replace(rows)

    def replace(self, rows: Iterable[dict[str, Any]]) -> None:
        keys: dict[tuple[str, str], tuple[bytes, str]] = {}
        for row in rows:
            if not row.get("enabled"):
                continue
            try:
                key = base64.b64decode(str(row["public_key"]), validate=True)
                if len(key) != 32:
                    continue
            except (KeyError, ValueError):
                continue
            keys[(str(row["publisher_id"]), str(row["key_id"]))] = (
                key, str(row["trust_level"]),
            )
        self._keys = keys

    def verify(self, manifest, artifact: dict[str, Any], payload: bytes) -> str:
        signature = artifact.get("signature") or {}
        key_id = str(signature.get("key_id") or "")
        trusted = self._keys.get((manifest.publisher_id, key_id))
        if trusted is None:
            raise PluginError("PLUGIN_UNTRUSTED", "Plugin publisher key is not trusted", category="trust")
        key, level = trusted
        try:
            signature_bytes = base64.b64decode(str(signature.get("value") or ""), validate=True)
            Ed25519PublicKey.from_public_bytes(key).verify(signature_bytes, payload)
        except (ValueError, InvalidSignature) as exc:
            raise PluginError(
                "ARTIFACT_SIGNATURE_INVALID", "Plugin artifact signature is invalid", category="trust"
            ) from exc
        return level


async def download_plugin_artifact(
    url: str,
    destination_dir: str | Path,
    *,
    expected_size: int,
    expected_sha256: str,
    max_bytes: int = MAX_PLUGIN_ARTIFACT_BYTES,
    max_redirects: int = PLUGIN_DOWNLOAD_REDIRECTS,
    timeout: float = PLUGIN_DOWNLOAD_TIMEOUT_SECONDS,
    client: httpx.AsyncClient | None = None,
    allow_private: bool = False,
) -> Path:
    if urlparse(url).scheme.lower() != "https":
        raise PluginError("ARTIFACT_INVALID", "Production plugin artifacts require HTTPS", category="artifact")
    if expected_size < 1 or expected_size > max_bytes:
        raise PluginError("ARTIFACT_INVALID", "Plugin artifact size is outside the allowed limit", category="artifact")
    destination = Path(destination_dir)
    destination.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix="plugin-download-", dir=destination)
    os.close(fd)
    path = Path(name)
    owns_client = client is None
    client = client or httpx.AsyncClient(timeout=httpx.Timeout(timeout, connect=10.0), follow_redirects=False)
    current = url
    try:
        for redirect_count in range(max_redirects + 1):
            try:
                current = await market._validate_fetch_url(current, allow_private=allow_private)
                async with client.stream("GET", current, follow_redirects=False) as response:
                    if response.status_code in {301, 302, 303, 307, 308}:
                        location = response.headers.get("location")
                        if not location or redirect_count >= max_redirects:
                            raise PluginError("ARTIFACT_INVALID", "Plugin artifact redirect is invalid", category="artifact")
                        current = urljoin(current, location)
                        continue
                    if response.status_code == 404:
                        raise PluginError("ARTIFACT_NOT_FOUND", "Plugin artifact was not found", category="artifact")
                    response.raise_for_status()
                    declared = response.headers.get("content-length")
                    if declared:
                        try:
                            if int(declared) > max_bytes:
                                raise PluginError("ARTIFACT_INVALID", "Plugin artifact exceeds the size limit", category="artifact")
                        except ValueError as exc:
                            raise PluginError("ARTIFACT_INVALID", "Plugin artifact Content-Length is invalid", category="artifact") from exc
                    digest = hashlib.sha256()
                    size = 0
                    with path.open("wb") as stream:
                        async for chunk in response.aiter_bytes():
                            size += len(chunk)
                            if size > max_bytes:
                                raise PluginError("ARTIFACT_INVALID", "Plugin artifact exceeds the size limit", category="artifact")
                            digest.update(chunk)
                            stream.write(chunk)
                    if size != expected_size or digest.hexdigest() != expected_sha256:
                        raise PluginError("ARTIFACT_INTEGRITY_FAILED", "Plugin artifact integrity check failed", category="artifact")
                    return path
            except PluginError:
                raise
            except (httpx.HTTPError, market.MarketError) as exc:
                raise PluginError("ARTIFACT_INVALID", "Plugin artifact download failed", retryable=True, category="artifact") from exc
        raise PluginError("ARTIFACT_INVALID", "Plugin artifact redirect limit exceeded", category="artifact")
    except BaseException:
        path.unlink(missing_ok=True)
        raise
    finally:
        if owns_client:
            await client.aclose()


@dataclass
class ProductionPluginSubsystem:
    service: PluginMarketService
    trust_policy: ProductionTrustPolicy
    download_root: Path
    http_client: httpx.AsyncClient
    provider_resolver: ProviderResolver
    capability_gateway: CapabilityGateway

    @classmethod
    async def create(
        cls, *, root: str | Path, http_client: httpx.AsyncClient,
        command_factory=None,
    ) -> "ProductionPluginSubsystem":
        root = Path(root).resolve()
        downloads = root / "downloads"
        downloads.mkdir(parents=True, exist_ok=True)
        trust_rows = await db.list_plugin_publisher_trust()
        trust_rows.extend(_official_trust_rows())
        trust = ProductionTrustPolicy(trust_rows)
        gateway = CapabilityGateway(client=http_client)
        dispatcher = CoreCapabilityDispatcher(gateway)
        runtime = PluginRuntime(
            permission_policy=PermissionPolicy(frozenset({"network", "cache"})),
            capability_dispatcher=dispatcher,
        )
        store = PluginArtifactStore(root / "artifacts", allowed_local_roots=[downloads])
        service = PluginMarketService(
            runtime=runtime, store=store, trust_policy=trust, command_factory=command_factory,
        )
        ownership_rows = await db.list_plugin_scheme_ownership()
        resolver = ProviderResolver(
            runtime=runtime,
            ownership={row["scheme"]: row["mode"] for row in ownership_rows},
        )
        for row in ownership_rows:
            resolver.set_mode(row["scheme"], row["mode"], str(row.get("plugin_identity") or ""))
        return cls(service, trust, downloads, http_client, resolver, gateway)

    async def startup(self) -> list[dict[str, Any]]:
        try:
            return await self.service.recover_enabled()
        except BaseException:
            await self.service.runtime.shutdown()
            raise

    async def shutdown(self) -> None:
        await self.service.runtime.shutdown()

    async def reload_trust(self) -> None:
        rows = await db.list_plugin_publisher_trust()
        rows.extend(_official_trust_rows())
        self.trust_policy.replace(rows)

    async def set_ownership(self, scheme: str, mode: str, plugin_identity: str = '') -> dict[str, Any]:
        scheme = str(scheme or '').strip().lower()
        if mode not in {"legacy", "plugin", "migration_test"}:
            raise PluginError("INVALID_PLUGIN_RESPONSE", "Invalid provider ownership mode", category="routing")
        if mode != "legacy":
            instance = self.service.runtime.registry.route(scheme)
            if plugin_identity and instance.manifest.identity != plugin_identity:
                raise PluginError("SCHEME_CONFLICT", "Requested Plugin does not own this scheme", category="routing")
            plugin_identity = instance.manifest.identity
        else:
            plugin_identity = ''
        row = await db.set_plugin_scheme_ownership(scheme, mode, plugin_identity)
        self.provider_resolver.set_mode(scheme, mode, plugin_identity)
        return {"scheme": row["scheme"], "mode": row["mode"], "plugin": row["plugin_identity"]}

    async def install(self, identity: str, packages: Iterable[dict[str, Any]]) -> dict[str, Any]:
        prepared: list[dict[str, Any]] = []
        temp_paths: list[Path] = []
        try:
            os_name, arch = current_platform()
            for package in packages:
                package = json.loads(json.dumps(package))
                manifest = package.get("plugin_manifest") or {}
                references = package.get("artifact_references") or []
                local_references = []
                for artifact in manifest.get("artifacts") or []:
                    if artifact.get("os") != os_name or artifact.get("arch") != arch:
                        continue
                    remote = next((item for item in references if item.get("sha256") == artifact.get("sha256")), None)
                    if not remote or not remote.get("url"):
                        continue
                    path = await download_plugin_artifact(
                        str(remote["url"]), self.download_root,
                        expected_size=int(artifact["size_bytes"]), expected_sha256=str(artifact["sha256"]),
                        client=self.http_client,
                    )
                    temp_paths.append(path)
                    local_references.append({"sha256": artifact["sha256"], "local_path": str(path)})
                package["artifact_references"] = local_references
                prepared.append(package)
            return await self.service.install_from_packages(prepared, identity)
        finally:
            for path in temp_paths:
                path.unlink(missing_ok=True)


def default_plugin_root() -> Path:
    configured = os.environ.get("WAVEFLOW_PLUGIN_ROOT")
    if configured:
        return Path(configured)
    return Path(__file__).resolve().parent / "data" / "plugins"


def _official_trust_rows() -> list[dict[str, Any]]:
    """Load public official keys from deployment config; private keys never enter Core."""
    raw = os.environ.get("WAVEFLOW_OFFICIAL_PLUGIN_KEYS", "")
    if not raw:
        return []
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        logger.warning("Ignoring invalid WAVEFLOW_OFFICIAL_PLUGIN_KEYS configuration")
        return []
    rows = []
    if not isinstance(data, dict):
        return rows
    for publisher_id, keys in data.items():
        if not isinstance(keys, dict):
            continue
        for key_id, public_key in keys.items():
            rows.append({
                "publisher_id": str(publisher_id), "key_id": str(key_id),
                "public_key": str(public_key), "trust_level": "official",
                "enabled": 1,
            })
    return rows
