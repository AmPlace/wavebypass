import asyncio
import hashlib
import ipaddress
import json
import logging
import os
import re
import secrets
import shutil
import socket
import time
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import urljoin, urlparse

import httpx

import database as db
from m3u8_parser import (
    channel_name_semantics,
    detect_source_type,
    normalize_channel_name,
    parse_m3u,
    parse_youtube_video_id,
)
from plugin_runtime.manifest import RANGE_PART_RE, SUPPORTED_CONTRACTS


SCHEMA_VERSION = 1
SUPPORTED_IMPORT_KINDS = {"playlist", "dynamic_playlist", "mixed"}
SUPPORTED_CHANNEL_SOURCE_TYPES = {"inline_channels", "playlist"}
CONTENT_PACKAGE_TYPE = "content_package"
PLUGIN_PACKAGE_TYPE = "plugin_package"
LOGO_PACKAGE_KIND = "logo_pack"
LOGO_CAPABILITY = "logos"
LOGO_MEDIA_TYPES = {"image/png", "image/webp", "image/jpeg"}
LOGO_MAX_ASSETS = 512
LOGO_MAX_ASSET_BYTES = 5 * 1024 * 1024
LOGO_MAX_ID_LENGTH = 128
LOGO_MAX_PATH_LENGTH = 256
INDEX_EXECUTION_FIELDS = {
    "defaults",
    "channel_sources",
    "inline_channels",
    "channels",
    "channels_url",
    "source_defaults",
    "headers",
    "assets",
    "logos",
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
MARKET_REFRESH_ERROR_MAX_LENGTH = 2048

logger = logging.getLogger(__name__)

_market_cache: dict[str, Any] = {
    "market_url": MARKET_URL,
    "market": None,
    "markets": [],
    "packages": [],
    "sources": [],
    "source_entries": {},
    "fetched_at": 0,
    "stale": False,
    "last_error": "",
    "allow_private": ALLOW_PRIVATE_MARKET_URLS,
}
_preview_cache: dict[str, dict[str, Any]] = {}
_package_update_locks: dict[str, asyncio.Lock] = {}
_market_source_refresh_locks: dict[str, asyncio.Lock] = {}


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


def _logo_safe_relative_path(value: Any) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > LOGO_MAX_PATH_LENGTH:
        raise MarketError("Logo asset path 无效", 400)
    raw = value.replace("\\", "/").strip()
    path = PurePosixPath(raw)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise MarketError("Logo asset path 必须是安全的 package-relative path", 400)
    return "/".join(path.parts)


def _normalize_logo_assets(value: Any) -> list[dict[str, Any]]:
    if value is None:
        return []
    if not isinstance(value, list) or len(value) > LOGO_MAX_ASSETS:
        raise MarketError("assets 必须是受限 array", 400)
    result: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    seen_paths: set[str] = set()
    for raw in value:
        if not isinstance(raw, dict):
            raise MarketError("asset 项格式无效", 400)
        asset_id = str(raw.get("asset_id") or "").strip()
        if not asset_id or len(asset_id) > LOGO_MAX_ID_LENGTH or asset_id in seen_ids:
            raise MarketError("asset_id 无效或重复", 400)
        relative_path = _logo_safe_relative_path(raw.get("path") or raw.get("relative_path"))
        if relative_path in seen_paths:
            raise MarketError("asset path 重复", 400)
        media_type = str(raw.get("media_type") or "").strip().lower()
        if media_type not in LOGO_MEDIA_TYPES:
            raise MarketError("Logo 仅支持 PNG/WebP/JPEG", 400)
        try:
            size = int(raw.get("size"))
        except (TypeError, ValueError) as exc:
            raise MarketError("asset size 无效", 400) from exc
        digest = str(raw.get("sha256") or "").strip().lower()
        if size <= 0 or size > LOGO_MAX_ASSET_BYTES or not re.fullmatch(r"[0-9a-f]{64}", digest):
            raise MarketError("asset size 或 sha256 无效", 400)
        seen_ids.add(asset_id)
        seen_paths.add(relative_path)
        result.append({
            "asset_id": asset_id,
            "relative_path": relative_path,
            "media_type": media_type,
            "sha256": digest,
            "size_bytes": size,
        })
    return result


def _logo_match_keys(value: Any) -> list[str]:
    text = str(value or "").strip()
    if not text:
        return []
    keys: list[str] = []
    try:
        semantic = channel_name_semantics(text)
        keys.extend([str(semantic.get("canonical_candidate") or "").strip()])
    except Exception:
        pass
    try:
        keys.append(normalize_channel_name(text))
    except Exception:
        pass
    keys.append(text)
    return list(dict.fromkeys(item for item in keys if item))


def _normalize_logo_entries(value: Any, assets: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if value is None:
        return []
    if not isinstance(value, list) or len(value) > LOGO_MAX_ASSETS:
        raise MarketError("logos 必须是受限 array", 400)
    asset_ids = {item["asset_id"] for item in assets}
    result: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for raw in value:
        if not isinstance(raw, dict):
            raise MarketError("logos 项格式无效", 400)
        asset_id = str(raw.get("logo_asset_id") or raw.get("asset_id") or "").strip()
        canonical_key = str(raw.get("canonical_key") or raw.get("channel_key") or "").strip()
        if not asset_id or asset_id not in asset_ids or not canonical_key:
            raise MarketError("logo entry 缺少有效 canonical_key/asset_id", 400)
        key = (canonical_key, asset_id)
        if key in seen:
            raise MarketError("logo entry 重复", 400)
        aliases = raw.get("aliases") or []
        if not isinstance(aliases, list):
            raise MarketError("logo aliases 必须是 array", 400)
        try:
            priority = max(0, min(100, int(raw.get("priority", 0))))
        except (TypeError, ValueError) as exc:
            raise MarketError("logo priority 无效", 400) from exc
        seen.add(key)
        result.append({
            "canonical_key": canonical_key[:LOGO_MAX_ID_LENGTH],
            "aliases": [str(alias).strip()[:LOGO_MAX_ID_LENGTH] for alias in aliases[:16] if str(alias).strip()],
            "asset_id": asset_id,
            "priority": priority,
        })
    return result


def _package_supported(package: dict) -> bool:
    if (
        package.get("package_type", CONTENT_PACKAGE_TYPE) == CONTENT_PACKAGE_TYPE
        and package.get("kind") == LOGO_PACKAGE_KIND
    ):
        return (
            bool(package.get("supported_in_v1", True))
            and LOGO_CAPABILITY in (package.get("content_capabilities") or [])
            and (
                bool(package.get("assets")) and bool(package.get("logos"))
                or bool(package.get("manifest_url"))
            )
        )
    return (
        package.get("package_type", CONTENT_PACKAGE_TYPE) == CONTENT_PACKAGE_TYPE
        and package.get("kind") in SUPPORTED_IMPORT_KINDS
        and bool(package.get("supported_in_v1", True))
    )


def _schema_warnings(package: dict, *, index: bool = False, manifest: bool = False) -> list[str]:
    warnings: list[str] = []
    if index:
        leaked = sorted(field for field in INDEX_EXECUTION_FIELDS if field in package)
        if leaked:
            warnings.append(f"market.json 索引不应包含执行配置字段: {', '.join(leaked)}")
        missing = sorted(field for field in RECOMMENDED_INDEX_FIELDS if field not in package)
        if missing:
            warnings.append(f"market.json 索引字段不完整: {', '.join(missing[:8])}{'…' if len(missing) > 8 else ''}")
    if manifest and package.get("kind") == LOGO_PACKAGE_KIND:
        if LOGO_CAPABILITY not in (package.get("content_capabilities") or []):
            warnings.append("logo_pack 必须声明 content_capabilities: logos")
        if not package.get("assets") or not package.get("logos"):
            warnings.append("logo_pack 缺少 assets 或 logos")
    elif manifest and package.get("kind") in SUPPORTED_IMPORT_KINDS:
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


def _normalize_plugin_requirements(value: Any) -> list[dict[str, Any]]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise MarketError("requires_plugins 必须是 array", 400)
    result: list[dict[str, Any]] = []
    for item in value:
        if not isinstance(item, dict) or set(item) != {"plugin", "version_range", "contract", "required_schemes"}:
            raise MarketError("requires_plugins 项格式无效", 400)
        identity = item.get("plugin")
        version_range = item.get("version_range")
        contract = item.get("contract")
        schemes = item.get("required_schemes")
        if (not isinstance(identity, str) or identity.count("/") != 1
                or not all(identity.split("/"))
                or not isinstance(version_range, str)
                or not version_range.split()
                or not all(RANGE_PART_RE.fullmatch(part) for part in version_range.split())
                or contract not in SUPPORTED_CONTRACTS
                or not isinstance(schemes, list) or not schemes
                or any(not isinstance(scheme, str) or not scheme for scheme in schemes)
                or len(set(schemes)) != len(schemes)):
            raise MarketError("requires_plugins 项格式无效", 400)
        result.append({
            "plugin": identity,
            "version_range": version_range,
            "contract": contract,
            "required_schemes": list(schemes),
        })
    result.sort(key=lambda item: (item["plugin"], item["contract"], item["version_range"], item["required_schemes"]))
    return result


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
    out = {
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
    # tag_definitions / tag_definitions_mode 来自 market.json 根级，由
    # _load_source_packages 在 source 字典中临时注入；DB 行不会有这些字段。
    raw_mode = source.get("tag_definitions_mode") if isinstance(source, dict) else None
    if isinstance(raw_mode, str) and raw_mode:
        out["tag_definitions_mode"] = raw_mode
    raw_defs = source.get("tag_definitions") if isinstance(source, dict) else None
    if isinstance(raw_defs, dict) and raw_defs:
        out["tag_definitions"] = raw_defs
    return out


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


def _source_cache_key(source: dict | None) -> str:
    source = source or {}
    return str(source.get("source_key") or source.get("id") or "").strip()


def _source_fetch_revision(source: dict | None) -> tuple[int, str, bool, bool]:
    source = source or {}
    return (
        int(source.get("id") or 0),
        str(source.get("url") or ""),
        bool(source.get("enabled")),
        bool(source.get("allow_private")),
    )


def _source_allow_private(source: dict | None) -> bool:
    source = source or {}
    return bool(source.get("allow_private") or ALLOW_PRIVATE_MARKET_URLS)


def _source_revision_value(source: dict | None) -> str:
    source_id, url, enabled, allow_private = _source_fetch_revision(source)
    return json.dumps(
        {
            "allow_private": allow_private,
            "enabled": enabled,
            "source_id": source_id,
            "url": url,
        },
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def _sanitize_refresh_error(value: Any) -> str:
    text = str(value or "").replace("\x00", " ")
    text = re.sub(r"\b[A-Za-z]:\\[^\s;]+", "[local-path]", text)
    text = re.sub(
        r"(?<!:)/(?:Users|home|private|tmp|var/folders|opt)/[^\s;]+",
        "[local-path]",
        text,
    )
    text = re.sub(r"<[^>]+ object at 0x[0-9a-fA-F]+>", "[internal-object]", text)
    text = " ".join(text.split()).strip()
    if len(text) > MARKET_REFRESH_ERROR_MAX_LENGTH:
        return text[: MARKET_REFRESH_ERROR_MAX_LENGTH - 1].rstrip() + "…"
    return text


def _has_successful_source_cache(entry: dict | None, source: dict) -> bool:
    if not entry or str(entry.get("source_url") or "") != str(source.get("url") or ""):
        return False
    cached_source_allow_private = entry.get("source_allow_private")
    if cached_source_allow_private is not None and bool(cached_source_allow_private) != bool(source.get("allow_private")):
        return False
    cached_fetch_allow_private = entry.get("fetch_allow_private")
    if cached_fetch_allow_private is not None and bool(cached_fetch_allow_private) != _source_allow_private(source):
        return False
    if entry.get("has_successful_cache") is False:
        return False
    return bool(
        entry.get("has_successful_cache")
        or entry.get("last_success_at")
        or entry.get("market")
    )


def _source_refresh_result(
    source: dict,
    *,
    current: dict | None,
    status: str,
    error: Any = "",
    cache_updated: bool = False,
    packages: list[dict] | None = None,
) -> dict:
    accepted_packages = packages or []
    return {
        "source_id": int(source.get("id") or 0),
        "source_key": _source_cache_key(source),
        "source_name": str(source.get("name") or ""),
        "requested_url": str(source.get("url") or ""),
        "current_url": str((current or {}).get("url") or ""),
        "source_revision": _source_revision_value(source),
        "current_source_revision": _source_revision_value(current),
        "status": status,
        "usable_for_update": status == "success",
        "stale": status == "stale",
        "error": _sanitize_refresh_error(error),
        "cache_updated": bool(cache_updated),
        "package_count": len(accepted_packages),
        "package_ids": [
            str(package.get("id") or "")
            for package in accepted_packages
            if str(package.get("id") or "")
        ],
    }


def _with_refresh_results(summary: dict, source_results: list[dict]) -> dict:
    statuses = ("success", "stale", "failed", "revision_discarded", "disabled")
    counts = {
        status: sum(1 for result in source_results if result.get("status") == status)
        for status in statuses
    }
    unsuccessful = counts["stale"] + counts["failed"] + counts["revision_discarded"]
    if unsuccessful and counts["success"]:
        refresh_status = "partial"
    elif unsuccessful:
        refresh_status = "failed"
    else:
        refresh_status = "success"

    result = dict(summary)
    result.update({
        "refresh_status": refresh_status,
        "source_results": source_results,
        "source_result_counts": counts,
        "successful_source_ids": [
            item["source_id"] for item in source_results if item.get("status") == "success"
        ],
        "stale_source_ids": [
            item["source_id"] for item in source_results if item.get("status") == "stale"
        ],
        "failed_source_ids": [
            item["source_id"] for item in source_results if item.get("status") == "failed"
        ],
        "revision_discarded_source_ids": [
            item["source_id"]
            for item in source_results
            if item.get("status") == "revision_discarded"
        ],
        "disabled_source_ids": [
            item["source_id"] for item in source_results if item.get("status") == "disabled"
        ],
    })
    return result


def _source_entries() -> dict[str, dict[str, Any]]:
    entries = _market_cache.get("source_entries")
    if not isinstance(entries, dict):
        entries = {}
        _market_cache["source_entries"] = entries
    return entries


def _rebuild_market_cache(sources: list[dict], *, extra_errors: list[str] | None = None) -> None:
    entries = _source_entries()
    active_sources = [source for source in sources if source.get("enabled")]
    active_by_key = {_source_cache_key(source): source for source in active_sources}

    for key in list(entries):
        source = active_by_key.get(key)
        entry = entries.get(key) or {}
        cached_source_allow_private = entry.get("source_allow_private")
        if cached_source_allow_private is None:
            cached_source_allow_private = any(
                bool(item.get("_allow_private_fetch"))
                for item in entry.get("packages") or []
                if isinstance(item, dict)
            )
        if (
            not source
            or str(entry.get("source_url") or "") != str(source.get("url") or "")
            or bool(cached_source_allow_private) != bool(source.get("allow_private"))
            or bool(entry.get("fetch_allow_private", cached_source_allow_private)) != _source_allow_private(source)
        ):
            entries.pop(key, None)

    markets: list[dict] = []
    packages: list[dict] = []
    errors = list(extra_errors or [])
    stale = False
    for source in active_sources:
        key = _source_cache_key(source)
        entry = entries.get(key)
        if not entry:
            continue
        public_source = _source_public(source)
        market_doc = deepcopy(entry.get("market") or {})
        if market_doc:
            market_doc["_source"] = public_source
            markets.append(market_doc)
        for package in entry.get("packages") or []:
            item = deepcopy(package)
            item["market_source"] = public_source
            packages.append(item)
        if entry.get("stale"):
            stale = True
            if entry.get("last_error"):
                errors.append(f"{source.get('name') or source.get('url')}: {entry['last_error']}")

    error_text = _sanitize_refresh_error("; ".join(dict.fromkeys(error for error in errors if error)))
    _market_cache.update({
        "market_url": ", ".join(str(source.get("url") or "") for source in active_sources),
        "market": markets[0] if markets else {"schema_version": SCHEMA_VERSION, "packages": []},
        "markets": markets,
        "packages": packages,
        "sources": sources,
        "fetched_at": time.time(),
        "stale": bool(stale or error_text),
        "last_error": error_text,
        "allow_private": any(bool(source.get("allow_private")) for source in active_sources),
    })


async def _sync_source_cache_after_mutation(source_id: int | None = None, *, invalidate: bool = False) -> None:
    sources = await db.list_market_sources()
    if source_id is not None and invalidate:
        source = next((item for item in sources if int(item.get("id") or 0) == int(source_id)), None)
        key = _source_cache_key(source)
        if key:
            _source_entries().pop(key, None)
        else:
            for cached_key, entry in list(_source_entries().items()):
                if int(entry.get("source_id") or 0) == int(source_id):
                    _source_entries().pop(cached_key, None)
    _rebuild_market_cache(sources)


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
    await _sync_source_cache_after_mutation()
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
    invalidate = (
        str(updated.get("url") or "") != str(source.get("url") or "")
        or not bool(updated.get("enabled"))
        or bool(updated.get("allow_private")) != bool(source.get("allow_private"))
    )
    await _sync_source_cache_after_mutation(source_id, invalidate=invalidate)
    return _source_public(updated)


async def delete_source(source_id: int) -> dict:
    source = await db.get_market_source(source_id)
    if not source:
        raise MarketError("Market 源不存在", 404)
    try:
        await db.delete_market_source(source_id)
    except ValueError as exc:
        raise MarketError(str(exc), 400) from exc
    key = _source_cache_key(source)
    if key:
        _source_entries().pop(key, None)
    await _sync_source_cache_after_mutation()
    return {"ok": True}


# ── 受控的展示协议字段 ────────────────────────────────────────────────
# Market 源只能向前端提供受控的展示建议（徽章文字 / 色调、Tag 优先级 / 色调 / 别名）。
# 不允许任何 HTML、SVG、CSS class、自由色值；非法值一律忽略并回落到前端 fallback。

BADGE_TONES = {"neutral", "rose", "sky", "emerald", "orange", "violet"}
TAG_TONES = {"neutral", "red", "blue", "orange", "green", "violet"}
TAG_DEFINITIONS_MODES = {"inherit", "replace"}
DEFAULT_TAG_DEFINITIONS_MODE = "inherit"
TAG_DEFS_MAX_ENTRIES = 256
TAG_DEFS_MAX_ALIASES = 16
TAG_LABEL_MAX_LEN = 32
TAG_ALIAS_MAX_LEN = 32
BADGE_TEXT_MAX_GRAPHEMES = 3


def _safe_text(value, *, max_chars: int) -> str:
    if not isinstance(value, str):
        return ""
    cleaned = value.strip()
    if not cleaned:
        return ""
    # 拒绝 HTML / SVG / 标签 / 控制字符。
    if "<" in cleaned or ">" in cleaned:
        return ""
    if any(ord(ch) < 0x20 for ch in cleaned):
        return ""
    if len(cleaned) > max_chars:
        cleaned = cleaned[:max_chars]
    return cleaned


def _normalize_display(value) -> dict:
    if not isinstance(value, dict):
        return {}
    out: dict[str, Any] = {}
    badge_raw = value.get("badge")
    if isinstance(badge_raw, dict):
        text = _safe_text(badge_raw.get("text"), max_chars=BADGE_TEXT_MAX_GRAPHEMES * 4)
        # 简单按字符数（非 grapheme cluster；CJK 全角 + emoji 边界由长度上限近似处理）。
        if text:
            text = text[:BADGE_TEXT_MAX_GRAPHEMES] if len(text) > BADGE_TEXT_MAX_GRAPHEMES else text
        tone = badge_raw.get("tone")
        tone = tone if tone in BADGE_TONES else ""
        badge: dict[str, Any] = {}
        if text:
            badge["text"] = text
        if tone:
            badge["tone"] = tone
        if badge:
            out["badge"] = badge
    return out


def _normalize_tag_definitions_mode(value) -> str:
    """规整化 market.json 根级 tag_definitions_mode。

    inherit  —— 当前 Market 源 tag_definitions 叠加在 WaveFlow 内置 DEFAULT_TAG_RULES 之上（默认）。
    replace  —— 仅使用当前 Market 源显式声明的 tag_definitions；未声明的标签按中性默认。

    缺失 / 非字符串 / 非法值一律回退到 inherit；该字段不参与播放、能力或安全判断。
    """
    if isinstance(value, str) and value in TAG_DEFINITIONS_MODES:
        return value
    return DEFAULT_TAG_DEFINITIONS_MODE


def _normalize_tag_definitions(value) -> dict:
    """规整化 market.json 根级 tag_definitions：受控枚举 + 数量/长度上限。
    非法字段静默丢弃，保证一个坏配置不会让整个 source 加载失败。
    """
    if not isinstance(value, dict):
        return {}
    out: dict[str, dict[str, Any]] = {}
    for raw_label, raw_rule in list(value.items())[:TAG_DEFS_MAX_ENTRIES]:
        label = _safe_text(raw_label, max_chars=TAG_LABEL_MAX_LEN)
        if not label or not isinstance(raw_rule, dict):
            continue
        rule: dict[str, Any] = {}
        # priority 限制 0–100。
        prio = raw_rule.get("priority")
        if isinstance(prio, bool):
            prio_val = None
        elif isinstance(prio, (int, float)):
            prio_val = max(0, min(100, int(prio)))
        else:
            prio_val = None
        if prio_val is not None:
            rule["priority"] = prio_val
        # tone 受控枚举。
        tone = raw_rule.get("tone")
        if tone in TAG_TONES:
            rule["tone"] = tone
        # emphasized 必须显式 boolean。
        emp = raw_rule.get("emphasized")
        if isinstance(emp, bool):
            rule["emphasized"] = emp
        # aliases 数组限长。
        aliases_raw = raw_rule.get("aliases")
        if isinstance(aliases_raw, list):
            aliases: list[str] = []
            for alias in aliases_raw[:TAG_DEFS_MAX_ALIASES]:
                cleaned = _safe_text(alias, max_chars=TAG_ALIAS_MAX_LEN)
                if cleaned:
                    aliases.append(cleaned)
            if aliases:
                rule["aliases"] = aliases
        if rule:
            out[label] = rule
    return out


def _normalize_package(raw: dict, *, manifest_url: str = "", market_url: str = "", schema_warnings: list[str] | None = None) -> dict:
    package = deepcopy(raw or {})
    package.setdefault("schema_version", SCHEMA_VERSION)
    if package.get("schema_version") != SCHEMA_VERSION:
        raise MarketError("不支持的 package schema_version", 400)
    package.setdefault("id", "")
    package.setdefault("name", package.get("id") or "未命名 Market 包")
    package.setdefault("description", "")
    package.setdefault("kind", "playlist")
    package.setdefault("package_type", PLUGIN_PACKAGE_TYPE if package.get("kind") == PLUGIN_PACKAGE_TYPE else CONTENT_PACKAGE_TYPE)
    if package["package_type"] not in {CONTENT_PACKAGE_TYPE, PLUGIN_PACKAGE_TYPE}:
        raise MarketError("不支持的 package_type", 400)
    package["requires_plugins"] = _normalize_plugin_requirements(package.get("requires_plugins"))
    package.setdefault("plugin_manifest", None)
    package.setdefault("artifact_references", [])
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
    capabilities = package.get("content_capabilities") or []
    if not isinstance(capabilities, list):
        raise MarketError("content_capabilities 必须是 array", 400)
    package["content_capabilities"] = list(dict.fromkeys(
        str(item).strip() for item in capabilities if str(item).strip()
    ))
    package["assets"] = _normalize_logo_assets(package.get("assets"))
    package["logos"] = _normalize_logo_entries(package.get("logos"), package["assets"])
    try:
        package["logo_priority"] = max(0, min(100, int(package.get("logo_priority", 0))))
    except (TypeError, ValueError) as exc:
        raise MarketError("logo_priority 无效", 400) from exc
    package.setdefault("contributors", [])
    package.setdefault("manifest_url", manifest_url)
    package.setdefault("market_url", market_url)
    package.setdefault("schema_warnings", [])
    package["display"] = _normalize_display(package.get("display"))
    if schema_warnings:
        package["schema_warnings"] = list(dict.fromkeys([*package.get("schema_warnings", []), *schema_warnings]))

    supported = _package_supported(package)
    package["supported_in_v1"] = supported
    package["previewable"] = bool(package.get("previewable", supported)) and supported and package.get("kind") != LOGO_PACKAGE_KIND
    package["importable"] = bool(package.get("importable", supported)) and supported
    package["plugin_installable"] = bool(
        package["package_type"] == PLUGIN_PACKAGE_TYPE
        and isinstance(package.get("plugin_manifest"), dict)
    )
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
            break
    source_key = _source_cache_key(package.get("market_source"))
    entry = _source_entries().get(source_key)
    if entry:
        for index, item in enumerate(entry.get("packages") or []):
            if item.get("id") == package_id:
                entry["packages"][index] = deepcopy(package)
                break


async def _resolve_package_manifest(package: dict) -> dict:
    if package.get("_manifest_loaded") or not package.get("manifest_url"):
        return package

    manifest_url = urljoin(str(package.get("market_url") or ""), str(package.get("manifest_url") or ""))
    allow_private = await _package_allow_private(package)
    final_url, text, _headers = await safe_http_fetch(manifest_url, allow_private=allow_private)
    try:
        manifest = json.loads(text)
    except json.JSONDecodeError as exc:
        raise MarketError(f"manifest JSON 解析失败: {exc}", 400) from exc

    _validate_package_minimal(manifest, context="manifest")
    manifest_warnings = _schema_warnings(manifest, manifest=True)
    if manifest.get("kind") == LOGO_PACKAGE_KIND and (
        not isinstance(manifest.get("assets"), list)
        or not manifest.get("assets")
        or not isinstance(manifest.get("logos"), list)
        or not manifest.get("logos")
    ):
        raise MarketError("Logo Package manifest 缺少 assets 或 logos", 400)
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


async def _package_allow_private(package: dict) -> bool:
    """Resolve private-fetch authority from the current durable source policy.

    The package cache is only a hint.  A source permission can be revoked
    while a stale package object is still being resolved, so the final
    decision must consult the current source row before any network fetch.
    """
    market_source = package.get("market_source") or {}
    source = None
    source_id = market_source.get("id")
    if source_id is not None:
        try:
            source = await db.get_market_source(int(source_id))
        except (TypeError, ValueError):
            source = None
    if source is None:
        source_key = str(market_source.get("source_key") or "").strip()
        if source_key:
            source = await db.get_market_source_by_key(source_key)
    if source is not None:
        if not bool(source.get("enabled", 1)):
            return False
        return _source_allow_private(source)
    if source_id is not None or str(market_source.get("source_key") or "").strip():
        # A package carrying a durable source identity must not fall back to
        # its stale cached permission after that source is deleted.
        return False
    if ALLOW_PRIVATE_MARKET_URLS:
        return True
    return bool(package.get("_allow_private_fetch"))


async def _load_source_packages(source: dict) -> tuple[dict, list[dict]]:
    url = str(source.get("url") or "").strip()
    if not url:
        raise MarketError("Market 源 URL 不能为空", 400)

    allow_private = _source_allow_private(source)
    try:
        final_url, text, _headers = await safe_http_fetch(url, allow_private=allow_private)
    except Exception:
        if str(source.get("source_key") or "") == OFFICIAL_MARKET_SOURCE_KEY:
            return _load_bundled_official_source(source)
        raise
    try:
        market = json.loads(text)
    except json.JSONDecodeError as exc:
        raise MarketError(f"market.json 解析失败: {exc}", 400) from exc
    if market.get("schema_version", SCHEMA_VERSION) != SCHEMA_VERSION:
        raise MarketError("不支持的 Market schema_version", 400)

    # 根级 tag_definitions / tag_definitions_mode：来自当前 Market 源的展示规则。
    # 先做受控规整，再以浅拷贝注入到这个 source 字典里，让后续 _attach_source /
    # _source_public 能把它们原样带到响应中。注入不会污染 DB 行
    # （外层 source 是 list_market_sources 返回的浅拷贝）。
    tag_definitions = _normalize_tag_definitions(market.get("tag_definitions"))
    tag_definitions_mode = _normalize_tag_definitions_mode(market.get("tag_definitions_mode"))
    market["tag_definitions"] = tag_definitions
    market["tag_definitions_mode"] = tag_definitions_mode
    source_with_defs = dict(source)
    source_with_defs["tag_definitions_mode"] = tag_definitions_mode
    if tag_definitions:
        source_with_defs["tag_definitions"] = tag_definitions

    packages = []
    for item in market.get("packages", []):
        try:
            _validate_package_minimal(item, context="market.json")
            raw_id = str(item.get("id") or "")
            index_warnings = _schema_warnings(item, index=True)
            loaded = _normalize_package(item, market_url=final_url, schema_warnings=index_warnings)
            loaded["_manifest_loaded"] = not bool(loaded.get("manifest_url"))
            packages.append(_attach_source(loaded, source_with_defs, raw_id or loaded.get("id")))
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
            packages.append(_attach_source(broken, source_with_defs, fallback_id))
    for package in packages:
        package["_allow_private_fetch"] = allow_private
    if str(source.get("source_key") or "") == OFFICIAL_MARKET_SOURCE_KEY:
        try:
            _bundled_market, bundled = _load_bundled_official_source(source)
        except Exception:
            logger.exception("Bundled official Plugin fallback is unavailable; using remote official Market")
        else:
            by_id = {str(item.get("original_id") or item.get("id") or ""): index
                     for index, item in enumerate(packages)}
            for fallback in bundled:
                identity = str(fallback.get("original_id") or fallback.get("id") or "")
                current_index = by_id.get(identity)
                if current_index is None:
                    packages.append(fallback)
                    continue
                remote = packages[current_index]
                if _version_status(str(remote.get("version") or ""), str(fallback.get("version") or "")) != "upgrade":
                    # The release-local copy is the immutable baseline for the same
                    # version. Remote sources can only supersede it with a newer one.
                    packages[current_index] = fallback
            market["distribution"] = "remote_with_bundled_fallback"
    market["_source"] = _source_public({**source_with_defs, "url": final_url})
    return market, packages


def _load_bundled_official_source(source: dict) -> tuple[dict, list[dict]]:
    from official_plugin_distribution import load_bundled_official_market

    market, raw_packages = load_bundled_official_market()
    source_with_defs = dict(source)
    packages = []
    for item in raw_packages:
        _validate_package_minimal(item, context="bundled official market")
        raw_id = str(item.get("id") or "")
        loaded = _normalize_package(item, market_url=str(source.get("url") or ""))
        loaded["_manifest_loaded"] = True
        loaded["_allow_private_fetch"] = False
        packages.append(_attach_source(loaded, source_with_defs, raw_id))
    market["_source"] = _source_public(source_with_defs)
    market["_bundled_fallback"] = True
    return market, packages


async def refresh_market(
    market_url: str | None = None,
    *,
    allow_private: bool = False,
    source_id: int | None = None,
) -> dict:
    all_sources = await ensure_market_sources()
    if market_url:
        source = next((item for item in all_sources if item.get("source_key") == "custom"), None)
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
        targets = [source] if source else []
    elif source_id:
        source = await db.get_market_source(source_id)
        if not source:
            raise MarketError("Market 源不存在", 404)
        targets = [source]
    else:
        targets = [source for source in all_sources if source.get("enabled")]

    source_results: list[dict] = []
    if not targets:
        sources_latest = await db.list_market_sources()
        _rebuild_market_cache(sources_latest)
        if any(source.get("enabled") for source in sources_latest):
            return _with_refresh_results(market_summary(), source_results)
        _market_cache.update({
            "market_url": "",
            "market": {"schema_version": SCHEMA_VERSION, "packages": []},
            "markets": [],
            "packages": [],
            "sources": sources_latest,
            "source_entries": {},
            "fetched_at": time.time(),
            "stale": False,
            "last_error": "",
            "allow_private": bool(allow_private or ALLOW_PRIVATE_MARKET_URLS),
        })
        return _with_refresh_results(market_summary(), source_results)

    source_errors: list[str] = []
    entries = _source_entries()
    for source in targets:
        if not source.get("enabled"):
            current = await db.get_market_source(source["id"])
            source_results.append(_source_refresh_result(
                source,
                current=current,
                status="disabled",
            ))
            continue
        key = _source_cache_key(source)
        lock = _market_source_refresh_locks.setdefault(key, asyncio.Lock())
        async with lock:
            current = await db.get_market_source(source["id"])
            if not current or _source_fetch_revision(current) != _source_fetch_revision(source):
                source_results.append(_source_refresh_result(
                    source,
                    current=current,
                    status="revision_discarded",
                    error="Market 来源在刷新开始前已变化，旧请求未执行",
                ))
                continue
            try:
                market, source_packages = await _load_source_packages(source)
            except Exception as exc:
                current = await db.get_market_source(source["id"])
                if not current or _source_fetch_revision(current) != _source_fetch_revision(source):
                    source_results.append(_source_refresh_result(
                        source,
                        current=current,
                        status="revision_discarded",
                        error="Market 来源在失败结果返回前已变化，旧结果已丢弃",
                    ))
                    continue
                error = _sanitize_refresh_error(exc)
                source_errors.append(f"{source.get('name') or source.get('url')}: {error}")
                cached = entries.get(key)
                has_successful_cache = _has_successful_source_cache(cached, source)
                if not cached or str(cached.get("source_url") or "") != str(source.get("url") or ""):
                    cached = {
                        "source_id": source.get("id"),
                        "source_url": source.get("url", ""),
                        "source_allow_private": bool(source.get("allow_private")),
                        "fetch_allow_private": _source_allow_private(source),
                        "market": {},
                        "packages": [],
                        "fetched_at": time.time(),
                        "has_successful_cache": False,
                    }
                    entries[key] = cached
                cached["stale"] = True
                cached["last_error"] = error
                await db.update_market_source(
                    source["id"],
                    last_fetched_at=_now_iso(),
                    last_status="error",
                    last_error=error,
                )
                source_results.append(_source_refresh_result(
                    source,
                    current=current,
                    status="stale" if has_successful_cache else "failed",
                    error=error,
                ))
                continue

            current = await db.get_market_source(source["id"])
            if not current or _source_fetch_revision(current) != _source_fetch_revision(source):
                source_results.append(_source_refresh_result(
                    source,
                    current=current,
                    status="revision_discarded",
                    error="Market 来源在成功结果返回前已变化，旧结果已丢弃",
                ))
                continue
            success_at = time.time()
            refresh_status = "bundled" if market.get("_bundled_fallback") else "success"
            entries[key] = {
                "source_id": source.get("id"),
                "source_url": source.get("url", ""),
                "source_allow_private": bool(source.get("allow_private")),
                "fetch_allow_private": _source_allow_private(source),
                "market": market,
                "packages": source_packages,
                "fetched_at": success_at,
                "last_success_at": success_at,
                "has_successful_cache": True,
                "stale": False,
                "last_error": "",
            }
            await db.update_market_source(
                source["id"],
                last_fetched_at=_now_iso(),
                last_status="bundled" if refresh_status == "bundled" else "ok",
                last_error="",
            )
            source_results.append(_source_refresh_result(
                source,
                current=current,
                status=refresh_status,
                cache_updated=True,
                packages=source_packages,
            ))

    sources_latest = await db.list_market_sources()
    _rebuild_market_cache(sources_latest, extra_errors=source_errors)
    return _with_refresh_results(market_summary(), source_results)


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


def market_packages_snapshot() -> list[dict]:
    return deepcopy(_market_cache.get("packages") or [])


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
            try:
                metadata = json.loads(row.get("metadata_json") or "{}")
            except json.JSONDecodeError:
                metadata = {}
            if metadata.get("kind") != LOGO_PACKAGE_KIND:
                await db.delete_market_install(row["package_id"])
                continue
        row["subscription"] = sub
        result[row["package_id"]] = row
    for row in await db.list_plugin_installations():
        package_id = str(row.get("source_package_id") or "")
        if not package_id:
            continue
        result[package_id] = {
            "package_id": package_id,
            "installed_version": row.get("active_version") or row.get("installed_version") or "",
            "installed_subscription_id": None,
            "auto_update": True,
            "plugin_identity": f"{row['publisher_id']}/{row['plugin_id']}",
            "trust_state": str(row.get("trust_state") or ""),
        }
    return result


def _installed_metadata(install: dict | None) -> dict:
    if not install:
        return {}
    try:
        return json.loads(install.get("metadata_json") or "{}")
    except json.JSONDecodeError:
        return {}


_NUMERIC_VERSION_RE = re.compile(r"^[vV]?(\d+(?:[._-]\d+)*)$")


def _numeric_version(value: str) -> tuple[int, ...] | None:
    match = _NUMERIC_VERSION_RE.fullmatch((value or "").strip())
    if not match:
        return None
    return tuple(int(part) for part in re.split(r"[._-]", match.group(1)))


def _version_status(current_version: str, installed_version: str) -> str:
    current = str(current_version or "").strip()
    installed = str(installed_version or "").strip()
    if not current or not installed:
        return "unknown"
    if current == installed:
        return "same"
    current_numeric = _numeric_version(current)
    installed_numeric = _numeric_version(installed)
    if current_numeric is None or installed_numeric is None:
        return "different"
    width = max(len(current_numeric), len(installed_numeric))
    current_padded = current_numeric + (0,) * (width - len(current_numeric))
    installed_padded = installed_numeric + (0,) * (width - len(installed_numeric))
    if current_padded > installed_padded:
        return "upgrade"
    if current_padded < installed_padded:
        return "downgrade"
    return "same"


def _update_available(package: dict, install: dict | None) -> bool:
    if not install:
        return False
    return _version_status(
        package.get("version", ""),
        install.get("installed_version", ""),
    ) == "upgrade"


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
        if supported_only and not (
            package.get("supported_in_v1") or package.get("plugin_installable")
        ):
            continue
        if importable_only and not package.get("importable"):
            continue
        item = _package_card(package)
        install = installed.get(package.get("id"))
        item["installed"] = bool(install)
        item["installed_version"] = install.get("installed_version", "") if install else ""
        item["installed_subscription_id"] = install.get("installed_subscription_id") if install else None
        item["auto_update"] = bool(install.get("auto_update")) if install else False
        item["version_status"] = _version_status(
            package.get("version", ""),
            install.get("installed_version", "") if install else "",
        )
        item["update_available"] = _update_available(package, install)
        if install and install.get("plugin_identity"):
            item["installed_trust_state"] = install.get("trust_state") or ""
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
        "manifest_url", "market_url", "market_source", "display", "installed",
        "installed_version", "auto_update", "update_available",
        "version_status",
        "package_type", "requires_plugins", "plugin_manifest",
        "plugin_installable", "content_capabilities", "asset_count", "logo_count",
        "logo_priority",
    ]
    card = {key: deepcopy(package.get(key)) for key in keys if key in package}
    card["asset_count"] = len(package.get("assets") or [])
    card["logo_count"] = len(package.get("logos") or [])
    if card.get("package_type") == PLUGIN_PACKAGE_TYPE:
        manifest = card.pop("plugin_manifest", None) or {}
        if isinstance(manifest, dict):
            raw_permissions = manifest.get("permissions") or {}
            permissions = []
            network = raw_permissions.get("network") if isinstance(raw_permissions, dict) else None
            if isinstance(network, dict):
                if network.get("managed") is True:
                    permissions.append("network.managed")
                if network.get("direct") is True:
                    permissions.append("network.direct")
                if network.get("allow_http") is True:
                    permissions.append("network.managed_http")
            if isinstance(raw_permissions, dict):
                permissions.extend(
                    str(key) for key, value in raw_permissions.items()
                    if key != "network" and value is True
                )
            card["plugin"] = {
                "publisher_id": str(manifest.get("publisher_id") or ""),
                "plugin_id": str(manifest.get("plugin_id") or ""),
                "display_name": str(manifest.get("display_name") or package.get("name") or ""),
                "version": str(manifest.get("version") or package.get("version") or ""),
                "provider_contracts": deepcopy(manifest.get("provider_contracts") or []),
                "owned_schemes": deepcopy(manifest.get("owned_schemes") or []),
                "platforms": [
                    {key: artifact.get(key) for key in ("os", "arch", "runtime")}
                    for artifact in manifest.get("artifacts") or [] if isinstance(artifact, dict)
                ],
                "permissions": sorted(set(permissions)),
                "dependencies": [],
            }
            seen_dependencies: set[tuple[Any, Any]] = set()
            lock_artifacts = (manifest.get("runtime", {}).get("dependency_lock", {}).get("artifacts", [])
                              if isinstance(manifest.get("runtime"), dict) else [])
            for item in lock_artifacts:
                if not isinstance(item, dict):
                    continue
                dependency_key = (item.get("name"), item.get("version"))
                if dependency_key in seen_dependencies:
                    continue
                seen_dependencies.add(dependency_key)
                card["plugin"]["dependencies"].append({
                    "name": item.get("name"), "version": item.get("version"),
                })
    return card


async def get_package(package_id: str, *, include_internal: bool = False) -> dict:
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
    # Trusted local resource roots are lifecycle inputs, never API data.
    if not include_internal:
        result.pop("_asset_root", None)
        result.pop("_bundled_asset_root", None)
    if result.get("package_type") == PLUGIN_PACKAGE_TYPE:
        # Local artifact references are lifecycle-service inputs, not an admin
        # read projection. In particular, never expose Core filesystem paths.
        result.pop("artifact_references", None)
        result.pop("dependency_references", None)
    install = installed.get(package_id)
    result["installed"] = bool(install)
    result["installed_version"] = install.get("installed_version", "") if install else ""
    result["installed_subscription_id"] = install.get("installed_subscription_id") if install else None
    result["auto_update"] = bool(install.get("auto_update")) if install else False
    result["version_status"] = _version_status(
        package.get("version", ""),
        install.get("installed_version", "") if install else "",
    )
    result["update_available"] = _update_available(package, install)
    if install and install.get("plugin_identity"):
        result["installed_trust_state"] = install.get("trust_state") or ""
    return result


async def _run_epg_binding_maintenance(trigger: str) -> None:
    """Run post-commit EPG maintenance without changing Market outcomes."""
    try:
        from epg_maintenance import run_epg_binding_maintenance
        result = await run_epg_binding_maintenance(sync_logical=True, trigger=trigger)
        if result.get('status') != 'success':
            logger.warning(
                'market_epg_binding_maintenance_deferred',
                extra={
                    'epg_binding_maintenance': {
                        'trigger': trigger,
                        'error': str(result.get('error') or '')[:512],
                    }
                },
            )
    except asyncio.CancelledError:
        raise
    except Exception as error:
        logger.warning(
            'market_epg_binding_maintenance_trigger_failed',
            extra={
                'epg_binding_maintenance': {
                    'trigger': trigger,
                    'error_type': type(error).__name__,
                }
            },
        )


async def uninstall_package(package_id: str) -> dict:
    lock = _package_update_locks.setdefault(package_id, asyncio.Lock())
    async with lock:
        old_assets = await db.get_package_assets(package_id)
        uninstalled = await db.uninstall_market_package_atomic(package_id)
        if uninstalled:
            await _remove_old_logo_files(old_assets, [])
    if uninstalled:
        await _run_epg_binding_maintenance('market_uninstall')
    return {"ok": True, "uninstalled": uninstalled}


async def update_install_config(package_id: str, *, auto_update: bool | None = None) -> dict:
    installed = await db.get_market_install(package_id)
    if not installed:
        raise MarketError("Market 包尚未安装", 404)
    values: dict[str, int] = {}
    if auto_update is not None:
        values["auto_update"] = 1 if auto_update else 0
    if values:
        await db.update_market_install(package_id, **values)
    updated = await db.get_market_install(package_id)
    return {
        "ok": True,
        "package_id": package_id,
        "auto_update": bool((updated or {}).get("auto_update")),
    }


async def update_installed_package(package_id: str) -> dict:
    preflight = await db.get_market_install(package_id)
    if not preflight:
        raise MarketError("Market 包尚未安装", 404)

    # The snapshot is only a preflight hint.  Re-read the durable install
    # record after acquiring the same lifecycle lock used by uninstall and
    # compare its durable generation before allowing reinstall=True.
    lock = _package_update_locks.setdefault(package_id, asyncio.Lock())
    async with lock:
        installed = await db.get_market_install(package_id)
        if not installed:
            raise MarketError("Market 包安装状态已变化，更新已中止", 409)
        if (
            str(installed.get("installed_at") or "") != str(preflight.get("installed_at") or "")
            or str(installed.get("installed_subscription_id") or "") != str(
                preflight.get("installed_subscription_id") or ""
            )
            or str(installed.get("installed_version") or "") != str(preflight.get("installed_version") or "")
        ):
            raise MarketError("Market 包安装状态已变化，更新已中止", 409)
        return await _import_package_locked(package_id, reinstall=True)


async def run_installed_updates(auto_update_only: bool = False) -> dict:
    await ensure_market_loaded()
    rows = await db.list_market_installs()
    packages = {
        str(package.get("id") or ""): package
        for package in (_market_cache.get("packages") or [])
    }
    results: list[dict[str, Any]] = []
    updated = 0
    skipped = 0
    failed = 0

    for install in rows:
        package_id = str(install.get("package_id") or "").strip()
        if not package_id:
            continue
        if auto_update_only and not install.get("auto_update"):
            skipped += 1
            results.append({
                "package_id": package_id,
                "status": "skipped",
                "reason": "auto_update disabled",
            })
            continue
        package = packages.get(package_id)
        if not package:
            skipped += 1
            results.append({
                "package_id": package_id,
                "status": "skipped",
                "reason": "package missing from current market",
                "version_status": "unknown",
            })
            continue
        version_status = _version_status(
            package.get("version", ""),
            install.get("installed_version", ""),
        )
        if version_status != "upgrade":
            skipped += 1
            results.append({
                "package_id": package_id,
                "status": "skipped",
                "reason": f"version status: {version_status}",
                "version_status": version_status,
            })
            continue
        sub_id = install.get("installed_subscription_id")
        sub = await db.get_subscription(sub_id) if sub_id else None
        if not sub:
            await db.delete_market_install(package_id)
            skipped += 1
            results.append({
                "package_id": package_id,
                "status": "skipped",
                "reason": "installed subscription missing",
            })
            continue
        try:
            result = await update_installed_package(package_id)
            updated += 1
            results.append({
                "package_id": package_id,
                "status": "updated",
                "subscription_id": result.get("subscription_id"),
                "channel_count": result.get("channel_count", 0),
                "source_count": result.get("source_count", 0),
                "version_status": version_status,
            })
        except Exception as exc:
            failed += 1
            results.append({
                "package_id": package_id,
                "status": "failed",
                "error": str(exc),
            })

    return {
        "ok": True,
        "updated": updated,
        "skipped": skipped,
        "failed": failed,
        "results": results,
    }


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
    channel_overrides: dict | None = None,
) -> tuple[dict | None, str | None]:
    if isinstance(source, str):
        source = {"url": source}
    # merge 顺序（左 → 右，后者覆盖前者）：
    #   包级 source_defaults  <  源级 source  <  频道级 channel_overrides
    # 频道级最高，符合"频道配置压过源/包"的语义。
    merged = _merge_source_defaults(source_defaults, source, channel_overrides)
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

    from rtsp_playback import normalize_rtsp_timestamp_mode

    return {
        "name": str(channel.get("name") or "未命名频道"),
        "url": url,
        "logo_url": str(channel.get("logo") or channel.get("logo_url") or ""),
        "logo_asset_id": str(channel.get("logo_asset_id") or ""),
        "group_name": str(channel.get("group_name") or channel.get("group") or _first(channel.get("categories")) or "其他"),
        "tvg_id": str((channel.get("epg") or {}).get("tvg_id") or channel.get("tvg_id") or channel.get("id") or ""),
        "tvg_name": str((channel.get("epg") or {}).get("tvg_name") or channel.get("tvg_name") or channel.get("name") or ""),
        "source_type": source_type,
        "youtube_video_id": str(merged.get("youtube_video_id") or parse_youtube_video_id(url)),
        "custom_ua": custom_ua,
        "referer": referer,
        "rtsp_timestamp_mode": normalize_rtsp_timestamp_mode(
            merged.get("rtsp_timestamp_mode")
        ),
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
    allow_private = await _package_allow_private(package)
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
        allow_private=await _package_allow_private(package),
    )
    channels = parse_m3u(text)
    warnings = [f"已解析动态订阅: {final_url}"]
    for ch in channels:
        # m3u 里 #EXTVLCOPT/#KODIPROP/#WAVEFLOW 描述的是"这个频道整体的播放
        # 要求"——属于频道级，因此写到 channel.defaults.source；优先级
        # build_preview 里高于 sources[i]（源级）。
        ch_overrides_headers: dict[str, str] = {}
        if ch.get("referer"):
            ch_overrides_headers["Referer"] = str(ch["referer"])
        if ch.get("custom_ua"):
            ch_overrides_headers["User-Agent"] = str(ch["custom_ua"])
        ch_overrides: dict = {}
        if ch_overrides_headers:
            ch_overrides["headers"] = ch_overrides_headers
        if ch.get("force_proxy"):
            ch_overrides["requires_proxy"] = True
        if ch_overrides:
            existing = (ch.get("defaults") or {}).get("source") or {}
            ch.setdefault("defaults", {})["source"] = {**existing, **ch_overrides,
                "headers": {**existing.get("headers", {}), **ch_overrides.get("headers", {})}}
        ch.setdefault("sources", [{"url": ch.get("url", "")}])
    return channels, warnings


async def build_preview(package_id: str) -> dict:
    package = await get_package(package_id, include_internal=True)
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
            # channel.defaults.source 是\u300c频道级\u300d配置，最高优先；
            # source_defaults 只承载\u300c包级 + channel_source 级\u300d的默认。
            channel_overrides = (channel.get("defaults") or {}).get("source") or {}
            raw_sources = channel.get("sources")
            if not raw_sources and channel.get("url"):
                raw_sources = [{"url": channel.get("url"), "source_type": channel.get("source_type")}]
            for source_index, raw_source in enumerate(raw_sources or []):
                entry, warning = _normalize_source(
                    channel,
                    raw_source,
                    package,
                    channel_source,
                    source_defaults,
                    source_index,
                    channel_overrides=channel_overrides,
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


def _logo_store_root() -> Path:
    configured = os.environ.get("WAVEFLOW_MARKET_ASSET_ROOT", "").strip()
    if configured:
        return Path(configured).expanduser().resolve()
    db_path = os.environ.get("WAVEFLOW_DB_PATH", "").strip()
    if db_path and db_path != ":memory:":
        return (Path(db_path).expanduser().resolve().parent / "market_assets").resolve()
    return (Path(__file__).resolve().parent / "data" / "market_assets").resolve()


def _trusted_logo_asset_root(package: dict) -> Path:
    # Asset bytes must come from a trusted bundled/developer-local package
    # resource root.  A public manifest cannot supply an arbitrary filesystem
    # path; remote asset URLs are deliberately unsupported in V1.
    candidate = package.get("_asset_root") or package.get("_bundled_asset_root")
    if not candidate:
        raise MarketError("Logo Package 缺少受控的本地资源根目录", 400)
    root = Path(str(candidate)).expanduser().resolve()
    if not root.is_dir():
        raise MarketError("Logo Package 资源根目录不存在", 400)
    return root


def _asset_magic_matches(media_type: str, payload: bytes) -> bool:
    if media_type == "image/png":
        return payload.startswith(b"\x89PNG\r\n\x1a\n")
    if media_type == "image/jpeg":
        return payload.startswith(b"\xff\xd8\xff")
    if media_type == "image/webp":
        return len(payload) >= 12 and payload[:4] == b"RIFF" and payload[8:12] == b"WEBP"
    return False


async def _stage_logo_assets(package: dict) -> tuple[list[dict], Path | None]:
    assets = package.get("assets") or []
    if not assets:
        return [], None
    source_root = _trusted_logo_asset_root(package)
    store_root = _logo_store_root()
    package_key = hashlib.sha256(str(package.get("id") or "").encode("utf-8")).hexdigest()[:24]
    version_key = hashlib.sha256(str(package.get("version") or "").encode("utf-8")).hexdigest()[:24]
    token = secrets.token_hex(8)
    staging = store_root / ".staging" / token
    final_dir = store_root / package_key / version_key / token

    def _stage() -> tuple[list[dict], Path]:
        try:
            staging.mkdir(parents=True, exist_ok=False)
            staged: list[dict] = []
            for asset in assets:
                relative = str(asset["relative_path"])
                source = (source_root / relative).resolve()
                if source != source_root and source_root not in source.parents:
                    raise MarketError("Logo asset path 越过 package 根目录", 400)
                if not source.is_file() or source.is_symlink():
                    raise MarketError(f"Logo asset 不存在: {relative}", 400)
                payload = source.read_bytes()
                if len(payload) != int(asset["size_bytes"]):
                    raise MarketError(f"Logo asset size 不匹配: {asset['asset_id']}", 400)
                digest = hashlib.sha256(payload).hexdigest()
                if digest != str(asset["sha256"]):
                    raise MarketError(f"Logo asset digest 不匹配: {asset['asset_id']}", 400)
                if not _asset_magic_matches(str(asset["media_type"]), payload):
                    raise MarketError(f"Logo asset media_type 不匹配: {asset['asset_id']}", 400)
                target = staging / asset["asset_id"]
                target.write_bytes(payload)
                staged.append({
                    **asset,
                    "stored_path": str(final_dir / asset["asset_id"]),
                })
            final_dir.parent.mkdir(parents=True, exist_ok=True)
            staging.rename(final_dir)
            return staged, final_dir
        except BaseException:
            shutil.rmtree(staging, ignore_errors=True)
            raise

    return await asyncio.to_thread(_stage)


async def _logo_binding_specs(package: dict, preview_entries: list[dict] | None = None) -> list[dict]:
    logical_rows = [
        row for row in await db.get_iptv_logical_channels()
        if str(row.get("status") or "") != "orphaned"
    ]
    if not logical_rows:
        return []
    exact: dict[str, list[dict]] = {}
    normalized: dict[str, list[dict]] = {}
    for row in logical_rows:
        canonical = str(row.get("canonical_key") or "").strip()
        exact.setdefault(canonical, []).append(row)
        for key in _logo_match_keys(canonical):
            normalized.setdefault(key, []).append(row)

    specs: list[dict] = []
    if package.get("kind") == LOGO_PACKAGE_KIND:
        for entry in package.get("logos") or []:
            candidates = [(str(entry.get("canonical_key") or ""), "exact")]
            candidates.extend((alias, "alias") for alias in entry.get("aliases") or [])
            for key, match_kind in candidates:
                matches = exact.get(key, [])
                match_type = "stable_identity" if matches and key in exact else match_kind
                if not matches:
                    normalized_matches = []
                    for candidate_key in _logo_match_keys(key):
                        normalized_matches.extend(normalized.get(candidate_key, []))
                    unique = {str(row["id"]): row for row in normalized_matches}
                    matches = list(unique.values()) if len(unique) == 1 else []
                    match_type = "normalized" if matches else match_type
                if len(matches) != 1:
                    continue
                specs.append({
                    "logical_channel_id": str(matches[0]["id"]),
                    "asset_id": entry["asset_id"],
                    "binding_type": "logo_pack",
                    "match_type": match_type,
                    "match_key": key,
                    "priority": int(package.get("logo_priority") or 0) + int(entry.get("priority") or 0),
                })
    else:
        entries = preview_entries or []
        for entry in entries:
            asset_id = str(entry.get("logo_asset_id") or "")
            if not asset_id:
                continue
            keys = _logo_match_keys(entry.get("name")) + _logo_match_keys(entry.get("tvg_name"))
            found: dict[str, tuple[dict, str, str]] = {}
            for key in keys:
                matches = exact.get(key, [])
                if len(matches) == 1:
                    found[str(matches[0]["id"])] = (matches[0], "stable_identity", key)
                    continue
                normalized_matches: dict[str, dict] = {}
                for normalized_key in _logo_match_keys(key):
                    for row in normalized.get(normalized_key, []):
                        normalized_matches[str(row["id"])] = row
                if len(normalized_matches) == 1:
                    row = next(iter(normalized_matches.values()))
                    found[str(row["id"])] = (row, "normalized", key)
            for row, match_type, key in found.values():
                specs.append({
                    "logical_channel_id": str(row["id"]),
                    "asset_id": asset_id,
                    "binding_type": "content_package",
                    "match_type": match_type,
                    "match_key": key,
                    "priority": int(package.get("logo_priority") or 0),
                })
    unique: dict[tuple[str, str, str, str], dict] = {}
    for spec in specs:
        unique[(spec["logical_channel_id"], spec["asset_id"], spec["match_type"], spec["match_key"])] = spec
    return list(unique.values())


async def _publish_logo_state(
    package: dict,
    staged_assets: list[dict],
    preview_entries: list[dict] | None = None,
) -> None:
    bindings = await _logo_binding_specs(package, preview_entries)
    valid_asset_ids = {item["asset_id"] for item in staged_assets}
    bindings = [item for item in bindings if item["asset_id"] in valid_asset_ids]
    await db.replace_package_logo_state(
        str(package["id"]), str(package.get("version") or ""), staged_assets, bindings,
    )


async def _remove_old_logo_files(old_assets: list[dict], new_assets: list[dict]) -> None:
    keep = {str(item.get("stored_path") or "") for item in new_assets}
    paths = {str(item.get("stored_path") or "") for item in old_assets} - keep

    def _remove() -> None:
        for raw in paths:
            path = Path(raw)
            if not raw or path.is_symlink() or not path.is_file():
                continue
            try:
                path.unlink()
            except OSError:
                continue
        parents = {Path(raw).parent for raw in paths if raw}
        for parent in sorted(parents, key=lambda item: len(item.parts), reverse=True):
            try:
                parent.rmdir()
            except OSError:
                pass

    await asyncio.to_thread(_remove)


async def import_package(
    package_id: str,
    preview_id: str = "",
    prefer_cached_preview: bool = True,
    reinstall: bool = False,
) -> dict:
    lock = _package_update_locks.setdefault(package_id, asyncio.Lock())
    async with lock:
        return await _import_package_locked(
            package_id,
            preview_id=preview_id,
            prefer_cached_preview=prefer_cached_preview,
            reinstall=reinstall,
        )


async def _import_package_locked(
    package_id: str,
    preview_id: str = "",
    prefer_cached_preview: bool = True,
    reinstall: bool = False,
) -> dict:
    package = await get_package(package_id, include_internal=True)
    if not package.get("importable"):
        raise MarketError(package.get("unsupported_reason") or "该包当前版本不可导入", 400)

    installed = await db.get_market_install(package_id)
    preserved_auto_update = int(installed.get("auto_update") or 0) if installed else 0
    if installed:
        try:
            installed_metadata = json.loads(installed.get("metadata_json") or "{}")
        except json.JSONDecodeError:
            installed_metadata = {}
        previous_kind = str(installed_metadata.get("kind") or "").strip()
        if previous_kind and previous_kind != str(package.get("kind") or ""):
            raise MarketError("Market 包类型不能在原地切换", 409)
    if installed and not reinstall:
        sub = await db.get_subscription(installed.get("installed_subscription_id")) if installed.get("installed_subscription_id") else None
        if sub:
            raise MarketError(f"Market 包已安装: {sub.get('title')}", 409)
        raise MarketError("Market 包已安装", 409)

    if package.get("kind") == LOGO_PACKAGE_KIND:
        old_assets = await db.get_package_assets(package_id)
        staged_assets: list[dict] = []
        final_dir: Path | None = None
        try:
            staged_assets, final_dir = await _stage_logo_assets(package)
            metadata = {
                "name": package.get("name"),
                "kind": LOGO_PACKAGE_KIND,
                "package_type": CONTENT_PACKAGE_TYPE,
                "version": package.get("version", ""),
                "content_capabilities": package.get("content_capabilities", []),
                "logos": package.get("logos", []),
                "imported_at": _now_iso(),
            }
            bindings = await _logo_binding_specs(package)
            await db.install_logo_package_atomic(
                package_id=package_id,
                market_url=package.get("market_url") or _market_cache.get("market_url", ""),
                installed_version=package.get("version", ""),
                metadata_json=json.dumps(metadata, ensure_ascii=False),
                assets=staged_assets,
                bindings=bindings,
                auto_update=preserved_auto_update,
            )
        except BaseException:
            if final_dir and final_dir.exists():
                await asyncio.to_thread(shutil.rmtree, final_dir, True)
            raise
        await _remove_old_logo_files(old_assets, staged_assets)
        return {
            "ok": True,
            "package_id": package_id,
            "channel_count": 0,
            "source_count": 0,
            "logo_count": len(staged_assets),
            "bindings": len(bindings),
        }

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

    asset_ids = {item["asset_id"] for item in package.get("assets") or []}
    for entry in channels:
        logo_asset_id = str(entry.get("logo_asset_id") or "")
        if logo_asset_id and logo_asset_id not in asset_ids:
            raise MarketError(f"频道引用了不存在的 logo_asset_id: {logo_asset_id}", 400)

    old_assets = await db.get_package_assets(package_id)
    staged_assets: list[dict] = []
    final_dir: Path | None = None
    try:
        staged_assets, final_dir = await _stage_logo_assets(package)
    except BaseException:
        raise

    # subscription 级属性只允许来自 manifest 明确声明，不得从子 source 聚合。
    # 一个 source 因 Referer/headers 需要代理，不能影响同包其他 source。
    # defaults.source.requires_proxy 是 source 级默认值，在 _normalize_source() 中
    # 逐 source 合并，不应提升到订阅级。
    def _truthy(v):
        if v is None:
            return False
        if isinstance(v, bool):
            return v
        if isinstance(v, (int, float)):
            return v != 0
        return str(v).strip().lower() not in ("", "0", "false", "no", "off", "none", "null")

    force_proxy = 1 if _truthy(package.get("requires_proxy")) else 0
    subscription_custom_ua = str(package.get("custom_ua") or "").strip()
    url = f"market://{package_id}"

    metadata = {
        "name": package.get("name"),
        "kind": package.get("kind"),
        "version": package.get("version", ""),
        "updated_at": package.get("updated_at", ""),
        "manifest_url": package.get("manifest_url", ""),
        "channel_sources": package.get("channel_sources", []),
        "defaults": package.get("defaults", {}),
        "warnings": preview.get("warnings", []),
        "requires_plugins": package.get("requires_plugins", []),
        "imported_at": _now_iso(),
    }
    try:
        sub_id = await db.install_market_package_atomic(
            package_id=package_id,
            market_url=package.get("market_url") or _market_cache.get("market_url", ""),
            title=package.get("name") or package_id,
            subscription_url=url,
            channels=channels,
            installed_version=package.get("version", ""),
            metadata_json=json.dumps(metadata, ensure_ascii=False),
            custom_ua=subscription_custom_ua,
            force_proxy=force_proxy,
            auto_update=preserved_auto_update,
        )
    except db.DuplicateSubscriptionError as exc:
        if final_dir and final_dir.exists():
            await asyncio.to_thread(shutil.rmtree, final_dir, True)
        raise MarketError("Market 包已安装", 409) from exc
    await _run_epg_binding_maintenance('market_install')
    if staged_assets:
        try:
            await _publish_logo_state(package, staged_assets, channels)
        except BaseException:
            # The channel transaction is already durable, but the old logo
            # binding remains authoritative when publication fails.  Do not
            # expose an unverified asset or delete the old files.
            if final_dir and final_dir.exists():
                await asyncio.to_thread(shutil.rmtree, final_dir, True)
            raise
        await _remove_old_logo_files(old_assets, staged_assets)
    elif old_assets:
        await _publish_logo_state(package, [], channels)
        await _remove_old_logo_files(old_assets, [])
    return {
        "ok": True,
        "subscription_id": sub_id,
        "channel_count": preview.get("channel_count", 0),
        "source_count": len(channels),
        "warnings": preview.get("warnings", []),
    }
