import asyncio
import hashlib
import ipaddress
import json
import os
import secrets
import socket
import time
from copy import deepcopy
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urljoin, urlparse

import httpx

import database as db
from m3u8_parser import detect_source_type, parse_m3u, parse_youtube_video_id


SCHEMA_VERSION = 1
SUPPORTED_IMPORT_KINDS = {"playlist", "dynamic_playlist", "mixed"}
SUPPORTED_CHANNEL_SOURCE_TYPES = {"inline_channels", "playlist"}
INDEX_EXECUTION_FIELDS = {
    "defaults",
    "channel_sources",
    "inline_channels",
    "channels",
    "channels_url",
    "source_defaults",
    "headers",
}
RECOMMENDED_INDEX_FIELDS = {
    "id",
    "name",
    "description",
    "kind",
    "version",
    "updated_at",
    "manifest_url",
    "region",
    "operators",
    "language",
    "categories",
    "tags",
    "status",
    "source_origin",
    "source_policy",
    "risk_level",
    "importable",
    "previewable",
    "supported_in_v1",
}
RESERVED_KINDS = {
    "provider",
    "remote_resolver",
    "dynamic_provider",
    "platform_pack",
    "radio_pack",
}
DEFAULT_MARKET_URL = "https://market.waveflow.tv/market.json"
OFFICIAL_MARKET_SOURCE_KEY = "official"
MARKET_URL = os.environ.get("WAVEFLOW_MARKET_URL", DEFAULT_MARKET_URL).strip() or DEFAULT_MARKET_URL
ALLOW_PRIVATE_MARKET_URLS = os.environ.get("WAVEFLOW_MARKET_ALLOW_PRIVATE", "").strip().lower() in {"1", "true", "yes", "on"}
PREVIEW_TTL_SECONDS = 10 * 60
MAX_FETCH_BYTES = 10 * 1024 * 1024

_market_cache: dict[str, Any] = {
    "market_url": MARKET_URL,
    "market": None,
    "markets": [],
    "packages": [],
    "sources": [],
    "fetched_at": 0,
    "stale": False,
    "last_error": "",
    "allow_private": ALLOW_PRIVATE_MARKET_URLS,
}
_preview_cache: dict[str, dict[str, Any]] = {}


class MarketError(Exception):
    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.status_code = status_code


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _is_private_hostname(host: str) -> bool:
    value = (host or "").strip().lower().strip("[]")
    return value in {"localhost", "localhost.localdomain"} or value.endswith(".localhost")


def _is_private_ip(value: str) -> bool:
    try:
        ip = ipaddress.ip_address(value)
    except ValueError:
        return False
    return (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
    )


async def _resolve_host(host: str) -> list[str]:
    def _resolve() -> list[str]:
        infos = socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)
        return list({info[4][0] for info in infos})

    return await asyncio.to_thread(_resolve)


async def _validate_fetch_url(url: str, *, allow_private: bool = False) -> str:
    parsed = urlparse((url or "").strip())
    if parsed.scheme not in {"http", "https"}:
        raise MarketError("只允许 http/https 远程资源", 400)
    if not parsed.hostname:
        raise MarketError("远程资源 URL 缺少 hostname", 400)

    host = parsed.hostname
    if not allow_private and (_is_private_hostname(host) or _is_private_ip(host)):
        raise MarketError("安全策略已阻止访问内网或本机地址", 400)

    if not allow_private:
        try:
            ips = await _resolve_host(host)
        except OSError as exc:
            raise MarketError(f"域名解析失败: {exc}", 502) from exc
        if not ips:
            raise MarketError("域名没有可用解析结果", 502)
        if any(_is_private_ip(ip) for ip in ips):
            raise MarketError("安全策略已阻止解析到内网或本机地址", 400)
    return parsed.geturl()


async def safe_http_fetch(
    url: str,
    *,
    headers: dict[str, str] | None = None,
    allow_private: bool = False,
    max_bytes: int = MAX_FETCH_BYTES,
    max_redirects: int = 3,
    timeout: float = 15.0,
) -> tuple[str, str, httpx.Headers]:
    """Fetch a remote market resource with scheme/IP checks before every request.

    V1 intentionally validates each redirect target. It does not actively probe
    stream content; callers interpret the returned text by manifest/URL rules.
    """
    allow_private = bool(allow_private or ALLOW_PRIVATE_MARKET_URLS)
    current_url = await _validate_fetch_url(url, allow_private=allow_private)
    request_headers = {k: v for k, v in (headers or {}).items() if v}

    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(timeout, connect=5.0), follow_redirects=False) as client:
            for redirect_count in range(max_redirects + 1):
                async with client.stream("GET", current_url, headers=request_headers) as resp:
                    if resp.status_code in {301, 302, 303, 307, 308}:
                        location = resp.headers.get("location")
                        if not location:
                            raise MarketError("远程资源重定向缺少 Location", 502)
                        if redirect_count >= max_redirects:
                            raise MarketError("远程资源重定向次数过多", 502)
                        current_url = await _validate_fetch_url(urljoin(current_url, location), allow_private=allow_private)
                        continue

                    try:
                        resp.raise_for_status()
                    except httpx.HTTPStatusError as exc:
                        raise MarketError(f"远程资源返回 HTTP {resp.status_code}", 502) from exc
                    chunks: list[bytes] = []
                    size = 0
                    async for chunk in resp.aiter_bytes():
                        size += len(chunk)
                        if size > max_bytes:
                            raise MarketError("远程资源超过大小限制", 413)
                        chunks.append(chunk)
                    content = b"".join(chunks)
                    encoding = resp.encoding or "utf-8"
                    return current_url, content.decode(encoding, errors="replace"), resp.headers
    except httpx.HTTPError as exc:
        raise MarketError(f"远程资源拉取失败: {exc}", 502) from exc

    raise MarketError("远程资源拉取失败", 502)


def _as_list(value: Any) -> list:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def _clean_headers(headers: dict | None) -> dict[str, str]:
    allowed = {"User-Agent", "Referer", "Cookie"}
    result: dict[str, str] = {}
    for key, value in (headers or {}).items():
        canonical = next((item for item in allowed if item.lower() == str(key).lower()), str(key))
        if canonical in allowed and value is not None:
            result[canonical] = str(value)
    return result


def _merge_dict(base: dict | None, override: dict | None) -> dict:
    result = deepcopy(base or {})
    for key, value in (override or {}).items():
        if isinstance(value, dict) and isinstance(result.get(key), dict) and value is not None:
            result[key] = _merge_dict(result[key], value)
        else:
            result[key] = deepcopy(value)
    return result


def _merge_source_defaults(*items: dict | None) -> dict:
    result: dict[str, Any] = {}
    for item in items:
        if not item:
            continue
        headers = _merge_dict(result.get("headers", {}), item.get("headers", {}))
        result = _merge_dict(result, item)
        if headers:
            result["headers"] = headers
    result["headers"] = _clean_headers(result.get("headers", {}))
    return result


def _package_supported(package: dict) -> bool:
    return package.get("kind") in SUPPORTED_IMPORT_KINDS and bool(package.get("supported_in_v1", True))


def _schema_warnings(package: dict, *, index: bool = False, manifest: bool = False) -> list[str]:
    warnings: list[str] = []
    if index:
        leaked = sorted(field for field in INDEX_EXECUTION_FIELDS if field in package)
        if leaked:
            warnings.append(f"market.json 索引不应包含执行配置字段: {', '.join(leaked)}")
        missing = sorted(field for field in RECOMMENDED_INDEX_FIELDS if field not in package)
        if missing:
            warnings.append(f"market.json 索引字段不完整: {', '.join(missing[:8])}{'…' if len(missing) > 8 else ''}")
    if manifest and package.get("kind") in SUPPORTED_IMPORT_KINDS:
        channel_sources = package.get("channel_sources")
        if not isinstance(channel_sources, list) or not channel_sources:
            warnings.append("manifest 缺少 channel_sources，无法预览或导入")
    return warnings


def _validate_package_minimal(raw: dict, *, context: str) -> None:
    if not isinstance(raw, dict):
        raise MarketError(f"{context} package 必须是 JSON object", 400)
    if not str(raw.get("id") or "").strip():
        raise MarketError(f"{context} package 缺少 id", 400)
    if not str(raw.get("kind") or "").strip():
        raise MarketError(f"{context} package 缺少 kind", 400)


async def ensure_market_sources() -> list[dict]:
    official = await db.get_market_source_by_key(OFFICIAL_MARKET_SOURCE_KEY)
    if not official:
        await db.upsert_market_source(
            source_key=OFFICIAL_MARKET_SOURCE_KEY,
            name="WaveFlow 官方 Market",
            url=MARKET_URL,
            enabled=1,
            allow_private=1 if ALLOW_PRIVATE_MARKET_URLS else 0,
            is_builtin=1,
        )
    return await db.list_market_sources()


async def list_sources() -> list[dict]:
    return await ensure_market_sources()


def _source_public(source: dict | None) -> dict:
    source = source or {}
    return {
        "id": source.get("id"),
        "source_key": source.get("source_key", ""),
        "name": source.get("name", ""),
        "url": source.get("url", ""),
        "enabled": bool(source.get("enabled", 1)),
        "allow_private": bool(source.get("allow_private", 0)),
        "is_builtin": bool(source.get("is_builtin", 0)),
        "last_fetched_at": source.get("last_fetched_at", ""),
        "last_status": source.get("last_status", ""),
        "last_error": source.get("last_error", ""),
    }


def _package_source_id(source: dict, package_id: str) -> str:
    source_key = str(source.get("source_key") or "").strip()
    if source_key == OFFICIAL_MARKET_SOURCE_KEY:
        return package_id
    return f"{source_key}::{package_id}" if source_key else package_id


def _attach_source(package: dict, source: dict, raw_id: str | None = None) -> dict:
    result = deepcopy(package)
    original_id = raw_id or str(result.get("id") or "")
    result["original_id"] = original_id
    result["id"] = _package_source_id(source, original_id)
    result["market_source"] = _source_public(source)
    return result


async def create_source(name: str, url: str, enabled: bool = True, allow_private: bool = False) -> dict:
    key = f"custom-{secrets.token_hex(4)}"
    source_id = await db.create_market_source(
        name=(name or "第三方 Market").strip(),
        url=url.strip(),
        source_key=key,
        enabled=1 if enabled else 0,
        allow_private=1 if allow_private else 0,
    )
    source = await db.get_market_source(source_id)
    return _source_public(source)


async def update_source(source_id: int, data: dict) -> dict:
    source = await db.get_market_source(source_id)
    if not source:
        raise MarketError("Market 源不存在", 404)
    updates = {}
    for key in ("name", "url"):
        if key in data:
            updates[key] = str(data.get(key) or "").strip()
    for key in ("enabled", "allow_private"):
        if key in data:
            updates[key] = 1 if data.get(key) else 0
    if source.get("is_builtin") and updates.get("url") == "":
        raise MarketError("内置 Market 源 URL 不能为空", 400)
    await db.update_market_source(source_id, **updates)
    updated = await db.get_market_source(source_id)
    return _source_public(updated)


async def delete_source(source_id: int) -> dict:
    try:
        await db.delete_market_source(source_id)
    except ValueError as exc:
        raise MarketError(str(exc), 400) from exc
    return {"ok": True}


def _normalize_package(raw: dict, *, manifest_url: str = "", market_url: str = "", schema_warnings: list[str] | None = None) -> dict:
    package = deepcopy(raw or {})
    package.setdefault("schema_version", SCHEMA_VERSION)
    if package.get("schema_version") != SCHEMA_VERSION:
        raise MarketError("不支持的 package schema_version", 400)
    package.setdefault("id", "")
    package.setdefault("name", package.get("id") or "未命名 Market 包")
    package.setdefault("description", "")
    package.setdefault("kind", "playlist")
    package.setdefault("version", "")
    package.setdefault("updated_at", "")
    package.setdefault("region", {})
    package.setdefault("operators", ["global"])
    package.setdefault("language", ["zh-CN"])
    package.setdefault("categories", [])
    package.setdefault("tags", [])
    package.setdefault("status", "unknown")
    package.setdefault("source_origin", "unknown")
    package.setdefault("source_policy", "unknown")
    package.setdefault("risk_level", "unknown")
    package.setdefault("defaults", {})
    package.setdefault("channel_sources", [])
    package.setdefault("channel_count", 0)
    package.setdefault("source_count", 0)
    package.setdefault("contributors", [])
    package.setdefault("manifest_url", manifest_url)
    package.setdefault("market_url", market_url)
    package.setdefault("schema_warnings", [])
    if schema_warnings:
        package["schema_warnings"] = list(dict.fromkeys([*package.get("schema_warnings", []), *schema_warnings]))

    supported = _package_supported(package)
    package["supported_in_v1"] = supported
    package["previewable"] = bool(package.get("previewable", supported)) and supported
    package["importable"] = bool(package.get("importable", supported)) and supported
    if not supported and not package.get("unsupported_reason"):
        package["unsupported_reason"] = "当前版本仅展示，暂不支持预览或导入"
    elif "unsupported_reason" not in package:
        package["unsupported_reason"] = None
    return package


async def _load_manifest(index_item: dict, market_url: str, *, allow_private: bool = False) -> dict:
    manifest_url = index_item.get("manifest_url") or index_item.get("url") or ""
    if manifest_url:
        resolved_url = urljoin(market_url, manifest_url)
        final_url, text, _headers = await safe_http_fetch(resolved_url, allow_private=allow_private)
        try:
            manifest = json.loads(text)
        except json.JSONDecodeError as exc:
            raise MarketError(f"manifest JSON 解析失败: {exc}", 400) from exc
        return _normalize_package(manifest, manifest_url=final_url, market_url=market_url)
    return _normalize_package(index_item, market_url=market_url)


def _cache_package(package: dict) -> None:
    package_id = package.get("id")
    if not package_id:
        return
    packages = _market_cache.get("packages") or []
    for index, item in enumerate(packages):
        if item.get("id") == package_id:
            packages[index] = package
            return


async def _resolve_package_manifest(package: dict) -> dict:
    if package.get("_manifest_loaded") or not package.get("manifest_url"):
        return package

    manifest_url = urljoin(str(package.get("market_url") or ""), str(package.get("manifest_url") or ""))
    allow_private = bool(package.get("_allow_private_fetch") or ALLOW_PRIVATE_MARKET_URLS)
    final_url, text, _headers = await safe_http_fetch(manifest_url, allow_private=allow_private)
    try:
        manifest = json.loads(text)
    except json.JSONDecodeError as exc:
        raise MarketError(f"manifest JSON 解析失败: {exc}", 400) from exc

    _validate_package_minimal(manifest, context="manifest")
    manifest_warnings = _schema_warnings(manifest, manifest=True)
    if any("缺少 channel_sources" in warning for warning in manifest_warnings):
        raise MarketError("; ".join(manifest_warnings), 400)

    merged = _merge_dict(package, manifest)
    source = package.get("market_source") or {}
    original_id = str(package.get("original_id") or manifest.get("id") or package.get("id") or "")
    loaded = _normalize_package(merged, manifest_url=final_url, market_url=package.get("market_url", ""), schema_warnings=manifest_warnings)
    loaded = _attach_source(loaded, source, original_id)
    loaded["_allow_private_fetch"] = allow_private
    loaded["_manifest_loaded"] = True
    _cache_package(loaded)
    return loaded


async def _load_source_packages(source: dict) -> tuple[dict, list[dict]]:
    url = str(source.get("url") or "").strip()
    if not url:
        raise MarketError("Market 源 URL 不能为空", 400)

    allow_private = bool(source.get("allow_private") or ALLOW_PRIVATE_MARKET_URLS)
    final_url, text, _headers = await safe_http_fetch(url, allow_private=allow_private)
    try:
        market = json.loads(text)
    except json.JSONDecodeError as exc:
        raise MarketError(f"market.json 解析失败: {exc}", 400) from exc
    if market.get("schema_version", SCHEMA_VERSION) != SCHEMA_VERSION:
        raise MarketError("不支持的 Market schema_version", 400)

    packages = []
    for item in market.get("packages", []):
        try:
            _validate_package_minimal(item, context="market.json")
            raw_id = str(item.get("id") or "")
            index_warnings = _schema_warnings(item, index=True)
            loaded = _normalize_package(item, market_url=final_url, schema_warnings=index_warnings)
            loaded["_manifest_loaded"] = not bool(loaded.get("manifest_url"))
            packages.append(_attach_source(loaded, source, raw_id or loaded.get("id")))
        except Exception as exc:
            fallback_id = str(item.get("id") or f"invalid-{len(packages) + 1}") if isinstance(item, dict) else f"invalid-{len(packages) + 1}"
            broken = _normalize_package(
                item if isinstance(item, dict) else {"id": fallback_id, "name": fallback_id, "kind": "unknown"},
                market_url=final_url,
                schema_warnings=[str(exc)],
            )
            broken["id"] = fallback_id
            broken["supported_in_v1"] = False
            broken["previewable"] = False
            broken["importable"] = False
            broken["unsupported_reason"] = f"索引校验失败: {exc}"
            packages.append(_attach_source(broken, source, fallback_id))
    for package in packages:
        package["_allow_private_fetch"] = allow_private
    market["_source"] = _source_public({**source, "url": final_url})
    return market, packages


async def refresh_market(
    market_url: str | None = None,
    *,
    allow_private: bool = False,
    source_id: int | None = None,
) -> dict:
    sources = await ensure_market_sources()
    if market_url:
        source = next((item for item in sources if item.get("source_key") == "custom"), None)
        if not source:
            custom_id = await db.create_market_source(
                name="自定义 Market",
                url=market_url.strip(),
                source_key="custom",
                enabled=1,
                allow_private=1 if allow_private else 0,
            )
            source = await db.get_market_source(custom_id)
        else:
            await db.update_market_source(source["id"], url=market_url.strip(), enabled=1, allow_private=1 if allow_private else 0)
            source = await db.get_market_source(source["id"])
        sources = [source] if source else []
    elif source_id:
        source = await db.get_market_source(source_id)
        if not source:
            raise MarketError("Market 源不存在", 404)
        sources = [source]
    else:
        sources = [source for source in sources if source.get("enabled")]

    if not sources:
        _market_cache.update({
            "market_url": "",
            "market": {"schema_version": SCHEMA_VERSION, "packages": []},
            "markets": [],
            "packages": [],
            "sources": await db.list_market_sources(),
            "fetched_at": time.time(),
            "stale": False,
            "last_error": "",
            "allow_private": bool(allow_private or ALLOW_PRIVATE_MARKET_URLS),
        })
        return market_summary()

    markets = []
    packages = []
    source_errors = []
    try:
        for source in sources:
            try:
                market, source_packages = await _load_source_packages(source)
                markets.append(market)
                packages.extend(source_packages)
                await db.update_market_source(
                    source["id"],
                    last_fetched_at=_now_iso(),
                    last_status="ok",
                    last_error="",
                )
            except Exception as exc:
                source_errors.append(f"{source.get('name') or source.get('url')}: {exc}")
                await db.update_market_source(
                    source["id"],
                    last_fetched_at=_now_iso(),
                    last_status="error",
                    last_error=str(exc),
                )

        if not markets and source_errors:
            raise MarketError("; ".join(source_errors), 502)

        sources_latest = await db.list_market_sources()
        _market_cache.update({
            "market_url": ", ".join([str(item.get("url") or "") for item in sources]),
            "market": markets[0] if markets else {"schema_version": SCHEMA_VERSION, "packages": []},
            "markets": markets,
            "packages": packages,
            "sources": sources_latest,
            "fetched_at": time.time(),
            "stale": False,
            "last_error": "; ".join(source_errors),
            "allow_private": any(bool(source.get("allow_private")) for source in sources_latest),
        })
    except Exception as exc:
        _market_cache["stale"] = bool(_market_cache.get("packages"))
        _market_cache["last_error"] = str(exc)
        if not _market_cache.get("packages"):
            raise
    return market_summary()


def market_summary() -> dict:
    market = _market_cache.get("market") or {"schema_version": SCHEMA_VERSION, "packages": []}
    sources = _market_cache.get("sources") or []
    return {
        "schema_version": market.get("schema_version", SCHEMA_VERSION),
        "market_version": market.get("market_version", ""),
        "updated_at": market.get("updated_at", ""),
        "market_url": _market_cache.get("market_url", ""),
        "package_count": len(_market_cache.get("packages") or []),
        "source_count": len(sources),
        "enabled_source_count": len([source for source in sources if source.get("enabled")]),
        "sources": [_source_public(source) for source in sources],
        "fetched_at": _market_cache.get("fetched_at", 0),
        "stale": bool(_market_cache.get("stale")),
        "last_error": _market_cache.get("last_error", ""),
        "allow_private": bool(_market_cache.get("allow_private")),
        "preview_cache": "V1 单进程内存缓存，服务重启后会清空",
    }


async def ensure_market_loaded() -> None:
    if _market_cache.get("packages") or _market_cache.get("market") is not None:
        return
    sources = await ensure_market_sources()
    _market_cache["sources"] = sources
    try:
        await refresh_market()
    except Exception as exc:
        _market_cache.update({
            "market": {"schema_version": SCHEMA_VERSION, "packages": []},
            "markets": [],
            "packages": [],
            "sources": await db.list_market_sources(),
            "fetched_at": time.time(),
            "stale": False,
            "last_error": str(exc),
        })


async def _installed_map() -> dict[str, dict]:
    rows = await db.list_market_installs()
    result: dict[str, dict] = {}
    for row in rows:
        sub_id = row.get("installed_subscription_id")
        sub = await db.get_subscription(sub_id) if sub_id else None
        if not sub:
            await db.delete_market_install(row["package_id"])
            continue
        row["subscription"] = sub
        result[row["package_id"]] = row
    return result


def _installed_metadata(install: dict | None) -> dict:
    if not install:
        return {}
    try:
        return json.loads(install.get("metadata_json") or "{}")
    except json.JSONDecodeError:
        return {}


def _update_available(package: dict, install: dict | None) -> bool:
    if not install:
        return False
    current_version = str(package.get("version") or "").strip()
    installed_version = str(install.get("installed_version") or "").strip()
    if current_version and installed_version:
        return current_version != installed_version

    current_updated_at = str(package.get("updated_at") or "").strip()
    installed_updated_at = str(_installed_metadata(install).get("updated_at") or "").strip()
    if current_updated_at and installed_updated_at:
        return current_updated_at != installed_updated_at
    return False


async def list_packages(filters: dict[str, str | bool]) -> list[dict]:
    await ensure_market_loaded()
    installed = await _installed_map()
    packages = []
    search = str(filters.get("search") or "").strip().lower()
    region = str(filters.get("region") or "").strip()
    operator = str(filters.get("operator") or "").strip()
    kind = str(filters.get("kind") or "").strip()
    status = str(filters.get("status") or "").strip()
    tag = str(filters.get("tag") or "").strip()
    supported_only = bool(filters.get("supported_only"))
    importable_only = bool(filters.get("importable_only"))

    for package in _market_cache.get("packages") or []:
        region_values = [str(v or "") for v in (package.get("region") or {}).values()]
        haystack = " ".join([
            package.get("id", ""),
            package.get("name", ""),
            package.get("description", ""),
            " ".join(package.get("tags") or []),
            " ".join(region_values),
        ]).lower()
        if search and search not in haystack:
            continue
        if region and region not in region_values:
            continue
        if operator and operator not in (package.get("operators") or []):
            continue
        if kind and package.get("kind") != kind:
            continue
        if status and package.get("status") != status:
            continue
        if tag and tag not in (package.get("tags") or []):
            continue
        if supported_only and not package.get("supported_in_v1"):
            continue
        if importable_only and not package.get("importable"):
            continue
        item = _package_card(package)
        install = installed.get(package.get("id"))
        item["installed"] = bool(install)
        item["installed_version"] = install.get("installed_version", "") if install else ""
        item["installed_subscription_id"] = install.get("installed_subscription_id") if install else None
        item["update_available"] = _update_available(package, install)
        packages.append(item)
    return packages


def _package_card(package: dict) -> dict:
    keys = [
        "id", "name", "description", "kind", "version", "updated_at", "region",
        "operators", "language", "categories", "tags", "status", "source_origin",
        "source_policy", "risk_level", "requires_proxy", "requires_resolver",
        "requires_cookie", "requires_referer", "requires_custom_ua", "channel_count",
        "source_count", "health", "compatibility", "contributors", "importable",
        "previewable", "supported_in_v1", "unsupported_reason", "schema_warnings",
        "manifest_url", "market_url", "market_source", "installed", "installed_version",
        "update_available",
    ]
    return {key: deepcopy(package.get(key)) for key in keys if key in package}


async def get_package(package_id: str) -> dict:
    await ensure_market_loaded()
    installed = await _installed_map()
    package = next((item for item in _market_cache.get("packages") or [] if item.get("id") == package_id), None)
    if not package:
        raise MarketError("Market 包不存在", 404)
    try:
        package = await _resolve_package_manifest(package)
    except Exception as exc:
        package = deepcopy(package)
        package["supported_in_v1"] = False
        package["previewable"] = False
        package["importable"] = False
        package["unsupported_reason"] = f"manifest 加载失败: {exc}"
        _cache_package(package)
    result = deepcopy(package)
    install = installed.get(package_id)
    result["installed"] = bool(install)
    result["installed_version"] = install.get("installed_version", "") if install else ""
    result["installed_subscription_id"] = install.get("installed_subscription_id") if install else None
    result["update_available"] = _update_available(package, install)
    return result


async def uninstall_package(package_id: str) -> dict:
    installed = await db.get_market_install(package_id)
    if not installed:
        return {"ok": True, "uninstalled": False}
    sub_id = installed.get("installed_subscription_id")
    if sub_id:
        sub = await db.get_subscription(sub_id)
        if sub:
            await db.delete_subscription(sub_id)
    await db.delete_market_install(package_id)
    return {"ok": True, "uninstalled": True}


def _source_type_for(source: dict) -> str:
    declared = str(source.get("type") or source.get("source_type") or "").strip()
    if declared:
        return declared.lower()
    return detect_source_type(str(source.get("url") or ""))


def _source_headers(source: dict) -> dict[str, str]:
    return _clean_headers(source.get("headers") or {})


def _source_tracking_ids(channel: dict, source: dict, package: dict, channel_source: dict, source_index: int) -> dict[str, str]:
    package_id = str(package.get("id") or "").strip()
    channel_source_id = str(channel_source.get("id") or channel_source.get("name") or "").strip()
    channel_id = str(
        channel.get("id")
        or channel.get("canonical_key")
        or channel.get("tvg_id")
        or (channel.get("epg") or {}).get("tvg_id")
        or channel.get("name")
        or ""
    ).strip()
    explicit_source_id = str(source.get("id") or source.get("source_id") or "").strip()
    if explicit_source_id:
        source_item_id = explicit_source_id
    else:
        seed = "|".join([
            package_id,
            channel_source_id,
            channel_id,
            str(source_index),
            str(source.get("url") or ""),
        ])
        source_item_id = f"auto-{hashlib.sha1(seed.encode('utf-8')).hexdigest()[:16]}"
    return {
        "market_package_id": package_id,
        "market_source_id": channel_source_id,
        "market_channel_id": channel_id,
        "market_source_item_id": source_item_id,
    }


def _normalize_source(
    channel: dict,
    source: dict,
    package: dict,
    channel_source: dict,
    source_defaults: dict,
    source_index: int,
) -> tuple[dict | None, str | None]:
    if isinstance(source, str):
        source = {"url": source}
    merged = _merge_source_defaults(source_defaults, source)
    url = str(merged.get("url") or "").strip()
    source_type = _source_type_for(merged)
    headers = _source_headers(merged)
    custom_ua = headers.get("User-Agent", "")
    referer = headers.get("Referer", "")
    has_cookie = bool(headers.get("Cookie") or merged.get("requires_cookie"))

    if has_cookie:
        return None, f"{channel.get('name', '未命名频道')} 源需要 Cookie，V1 已跳过"
    if source_type in {"provider", "remote_resolver", "bilibili_live", "douyin_live", "huya_live", "douyu_live", "unknown"}:
        return None, f"{channel.get('name', '未命名频道')} 源类型 {source_type} V1 暂不支持"
    if not url:
        return None, f"{channel.get('name', '未命名频道')} 源缺少 URL"

    return {
        "name": str(channel.get("name") or "未命名频道"),
        "url": url,
        "logo_url": str(channel.get("logo") or channel.get("logo_url") or ""),
        "group_name": str(channel.get("group_name") or channel.get("group") or _first(channel.get("categories")) or "其他"),
        "tvg_id": str((channel.get("epg") or {}).get("tvg_id") or channel.get("tvg_id") or channel.get("id") or ""),
        "tvg_name": str((channel.get("epg") or {}).get("tvg_name") or channel.get("tvg_name") or channel.get("name") or ""),
        "source_type": source_type,
        "youtube_video_id": str(merged.get("youtube_video_id") or parse_youtube_video_id(url)),
        "custom_ua": custom_ua,
        "referer": referer,
        "force_proxy": 1 if (
            merged.get("requires_proxy")
            or merged.get("requires_referer")
            or merged.get("requires_custom_ua")
            or custom_ua
            or referer
        ) else 0,
        **_source_tracking_ids(channel, merged, package, channel_source, source_index),
    }, None


def _first(value: Any) -> str:
    items = _as_list(value)
    return str(items[0]) if items else ""


async def _channels_from_inline(source: dict, package: dict) -> tuple[list[dict], list[str]]:
    warnings: list[str] = []
    channels = list(source.get("channels") or [])
    channels_url = str(source.get("channels_url") or "").strip()
    allow_private = bool(package.get("_allow_private_fetch") or ALLOW_PRIVATE_MARKET_URLS)
    if channels_url:
        headers = _clean_headers(source.get("headers") or {})
        final_url, text, _headers = await safe_http_fetch(
            urljoin(package.get("manifest_url") or package.get("market_url") or "", channels_url),
            headers=headers,
            allow_private=allow_private,
        )
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            raise MarketError(f"channels_url JSON 解析失败: {exc}", 400) from exc
        if isinstance(data, list):
            channels.extend(data)
        else:
            channels.extend(data.get("channels") or [])
        warnings.append(f"已从 channels_url 加载频道: {final_url}")
    return channels, warnings


async def _channels_from_playlist(source: dict, package: dict) -> tuple[list[dict], list[str]]:
    url = str(source.get("url") or "").strip()
    if not url:
        raise MarketError("playlist channel_source 缺少 url", 400)
    headers = _clean_headers(source.get("headers") or {})
    final_url, text, _resp_headers = await safe_http_fetch(
        url,
        headers=headers,
        allow_private=bool(package.get("_allow_private_fetch") or ALLOW_PRIVATE_MARKET_URLS),
    )
    channels = parse_m3u(text)
    warnings = [f"已解析动态订阅: {final_url}"]
    for ch in channels:
        ch.setdefault("sources", [{"url": ch.get("url", "")}])
    return channels, warnings


async def build_preview(package_id: str) -> dict:
    package = await get_package(package_id)
    if not package.get("previewable"):
        raise MarketError(package.get("unsupported_reason") or "该包当前版本不可预览", 400)

    defaults = package.get("defaults") or {}
    channel_defaults = defaults.get("channel") or {}
    package_source_defaults = defaults.get("source") or {}
    entries: list[dict] = []
    warnings: list[str] = []
    unsupported_source_count = 0

    for channel_source in package.get("channel_sources") or []:
        source_type = channel_source.get("type")
        if source_type not in SUPPORTED_CHANNEL_SOURCE_TYPES:
            warnings.append(f"channel_source {source_type} V1 暂不支持，已跳过")
            continue
        if source_type == "inline_channels":
            channels, source_warnings = await _channels_from_inline(channel_source, package)
        else:
            channels, source_warnings = await _channels_from_playlist(channel_source, package)
        warnings.extend(source_warnings)

        source_defaults = _merge_source_defaults(
            package_source_defaults,
            channel_source.get("source_defaults"),
        )
        for raw_channel in channels:
            channel = _merge_dict(channel_defaults, raw_channel)
            channel_source_defaults = _merge_source_defaults(source_defaults, (channel.get("defaults") or {}).get("source"))
            raw_sources = channel.get("sources")
            if not raw_sources and channel.get("url"):
                raw_sources = [{"url": channel.get("url"), "source_type": channel.get("source_type")}]
            for source_index, raw_source in enumerate(raw_sources or []):
                entry, warning = _normalize_source(
                    channel,
                    raw_source,
                    package,
                    channel_source,
                    channel_source_defaults,
                    source_index,
                )
                if entry:
                    entries.append(entry)
                else:
                    unsupported_source_count += 1
                    if warning:
                        warnings.append(warning)

    preview_id = secrets.token_urlsafe(18)
    now = time.time()
    result = {
        "preview_id": preview_id,
        "package": _package_card(package),
        "channels": entries[:200],
        "channel_count": len({entry["name"] for entry in entries}),
        "source_count": len(entries),
        "direct_source_count": len([entry for entry in entries if not entry.get("force_proxy") and not entry.get("custom_ua") and not entry.get("referer")]),
        "proxy_source_count": len([entry for entry in entries if entry.get("force_proxy") or entry.get("custom_ua") or entry.get("referer")]),
        "unsupported_source_count": unsupported_source_count,
        "warnings": list(dict.fromkeys([*(package.get("schema_warnings") or []), *warnings]))[:50],
        "created_at": now,
        "expires_at": now + PREVIEW_TTL_SECONDS,
        "cache_note": "V1 单进程内存缓存，服务重启后会清空",
    }
    _preview_cache[preview_id] = {
        **result,
        "all_channels": entries,
        "manifest": package,
    }
    _drop_expired_previews()
    return result


def _drop_expired_previews() -> None:
    now = time.time()
    for preview_id in list(_preview_cache):
        if _preview_cache[preview_id].get("expires_at", 0) < now:
            _preview_cache.pop(preview_id, None)


async def import_package(
    package_id: str,
    preview_id: str = "",
    prefer_cached_preview: bool = True,
    reinstall: bool = False,
) -> dict:
    package = await get_package(package_id)
    if not package.get("importable"):
        raise MarketError(package.get("unsupported_reason") or "该包当前版本不可导入", 400)

    installed = await db.get_market_install(package_id)
    if installed and installed.get("installed_subscription_id"):
        sub = await db.get_subscription(installed["installed_subscription_id"])
        if sub:
            if not reinstall:
                raise MarketError(f"Market 包已安装: {sub.get('title')}", 409)
            await db.delete_subscription(sub["id"])
        await db.delete_market_install(package_id)

    preview = None
    _drop_expired_previews()
    if preview_id and prefer_cached_preview:
        cached = _preview_cache.get(preview_id)
        if cached and cached.get("package", {}).get("id") == package_id:
            preview = cached
    if preview is None:
        built = await build_preview(package_id)
        preview = _preview_cache[built["preview_id"]]

    channels = preview.get("all_channels") or []
    if not channels:
        raise MarketError("没有可导入的频道源", 400)

    force_proxy = 1 if any(ch.get("force_proxy") for ch in channels) else 0
    custom_uas = sorted({str(ch.get("custom_ua") or "").strip() for ch in channels if ch.get("custom_ua")})
    subscription_custom_ua = custom_uas[0] if custom_uas else ""
    if len(custom_uas) > 1:
        preview.setdefault("warnings", []).append("V1 仅支持订阅级 User-Agent；检测到多个 UA，导入时使用第一个。")
    url = f"market://{package_id}"
    try:
        sub_id = await db.add_subscription(
            title=package.get("name") or package_id,
            url=url,
            channel_count=len(channels),
            custom_ua=subscription_custom_ua,
            force_proxy=force_proxy,
        )
    except db.DuplicateSubscriptionError as exc:
        raise MarketError("Market 包已安装", 409) from exc
    await db.add_channels_bulk(sub_id, channels)

    metadata = {
        "name": package.get("name"),
        "kind": package.get("kind"),
        "version": package.get("version", ""),
        "updated_at": package.get("updated_at", ""),
        "manifest_url": package.get("manifest_url", ""),
        "channel_sources": package.get("channel_sources", []),
        "defaults": package.get("defaults", {}),
        "warnings": preview.get("warnings", []),
        "imported_at": _now_iso(),
    }
    await db.upsert_market_install(
        package_id=package_id,
        market_url=package.get("market_url") or _market_cache.get("market_url", ""),
        installed_subscription_id=sub_id,
        installed_version=package.get("version", ""),
        metadata_json=json.dumps(metadata, ensure_ascii=False),
    )
    return {
        "ok": True,
        "subscription_id": sub_id,
        "channel_count": preview.get("channel_count", 0),
        "source_count": len(channels),
        "warnings": preview.get("warnings", []),
    }
