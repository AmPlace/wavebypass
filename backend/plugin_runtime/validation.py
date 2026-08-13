from __future__ import annotations

import json
import math
import re
from typing import Any
from urllib.parse import urlparse, urlsplit

from .errors import invalid_response


TRANSPORTS = frozenset({"hls", "dash", "http_flv", "mpegts", "rtsp", "audio_http", "probe_only"})
SECRET_HEADERS = frozenset({"authorization", "cookie", "proxy-authorization", "x-api-key"})
DESCRIPTOR_FIELDS = frozenset({
    "descriptor_version", "transport", "url", "headers", "credential_refs", "ttl_seconds", "expires_at",
    "volatile_url", "requires_proxy", "warnings", "proxy_reasons", "referer", "origin", "user_agent",
    "quality_variants", "drm", "encryption", "probe_hints", "refresh", "provider_diagnostics",
})

# Provider diagnostics and probe hints are data-only extension points.  Keep
# their boundary independent from the frame limit so a valid descriptor can
# still carry the rest of its transport fields without allowing an unbounded
# metadata blob through the Plugin boundary.
DESCRIPTOR_METADATA_MAX_BYTES = 16 * 1024
DESCRIPTOR_METADATA_MAX_DEPTH = 5
DESCRIPTOR_METADATA_MAX_ITEMS = 64
DESCRIPTOR_METADATA_MAX_STRING_LENGTH = 2048
DESCRIPTOR_METADATA_MAX_KEY_LENGTH = 128
CHANNEL_CATALOG_MAX_ITEMS = 256
CHANNEL_CATALOG_MAX_BYTES = 256 * 1024
CHANNEL_CATALOG_MAX_EXTERNAL_ID_LENGTH = 256
CHANNEL_CATALOG_MAX_NAME_LENGTH = 200
CHANNEL_CATALOG_MAX_REFERENCE_LENGTH = 2048
CHANNEL_CATALOG_MAX_GROUP_LENGTH = 128
CHANNEL_CATALOG_MAX_LOGO_LENGTH = 2048
CHANNEL_CATALOG_MAX_TTL_SECONDS = 24 * 60 * 60
CHANNEL_CATALOG_KINDS = frozenset({"channel", "event"})
_CATALOG_SCHEME_RE = re.compile(r"^[a-z][a-z0-9+.-]*$")


def validate_descriptor_metadata(value: Any, *, field: str = "descriptor metadata") -> dict[str, Any]:
    """Validate a JSON-safe, bounded metadata object.

    Metadata is intentionally opaque to the runtime.  It is never interpreted
    as headers, commands, ownership, or capability authority.  Restricting
    the shape here keeps that opaque data safe to carry through IPC and into
    probe diagnostics.
    """
    if not isinstance(value, dict):
        raise invalid_response(f"Invalid {field}")

    active: set[int] = set()

    def walk(item: Any, depth: int) -> None:
        if depth > DESCRIPTOR_METADATA_MAX_DEPTH:
            raise invalid_response(f"{field} exceeds maximum depth")
        if isinstance(item, str):
            if len(item) > DESCRIPTOR_METADATA_MAX_STRING_LENGTH:
                raise invalid_response(f"{field} contains an oversized string")
            return
        if item is None or isinstance(item, bool):
            return
        if isinstance(item, int):
            return
        if isinstance(item, float):
            if not math.isfinite(item):
                raise invalid_response(f"{field} contains a non-finite number")
            return
        if isinstance(item, dict):
            if len(item) > DESCRIPTOR_METADATA_MAX_ITEMS:
                raise invalid_response(f"{field} contains too many object members")
            identity = id(item)
            if identity in active:
                raise invalid_response(f"{field} contains a cycle")
            active.add(identity)
            try:
                for key, child in item.items():
                    if not isinstance(key, str) or len(key) > DESCRIPTOR_METADATA_MAX_KEY_LENGTH:
                        raise invalid_response(f"{field} contains an invalid object key")
                    walk(child, depth + 1)
            finally:
                active.remove(identity)
            return
        if isinstance(item, list):
            if len(item) > DESCRIPTOR_METADATA_MAX_ITEMS:
                raise invalid_response(f"{field} contains too many array items")
            identity = id(item)
            if identity in active:
                raise invalid_response(f"{field} contains a cycle")
            active.add(identity)
            try:
                for child in item:
                    walk(child, depth + 1)
            finally:
                active.remove(identity)
            return
        raise invalid_response(f"{field} contains a non-JSON value")

    walk(value, 1)
    try:
        encoded = json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
    except (TypeError, ValueError, OverflowError) as exc:
        raise invalid_response(f"Invalid {field}") from exc
    if len(encoded.encode("utf-8")) > DESCRIPTOR_METADATA_MAX_BYTES:
        raise invalid_response(f"{field} exceeds maximum size")
    return dict(value)


def validate_channel_catalog(value: Any, *, owned_schemes: set[str] | frozenset[str]) -> dict[str, Any]:
    """Validate a bounded runtime catalog owned by one Plugin instance.

    Catalog references are opaque provider references, not arbitrary network
    URLs.  Their scheme must be one of the Plugin's declared TV schemes; the
    existing ProviderResolver remains the authority that resolves them.
    """
    if not isinstance(value, dict) or set(value) != {"items"}:
        raise invalid_response("Channel catalog must contain only items")
    items = value["items"]
    if not isinstance(items, list) or len(items) > CHANNEL_CATALOG_MAX_ITEMS:
        raise invalid_response("Invalid channel catalog items")

    allowed = {str(scheme).lower() for scheme in owned_schemes}
    seen_external_ids: set[str] = set()
    normalized: list[dict[str, Any]] = []
    allowed_fields = {
        "external_id", "name", "reference", "kind", "group", "logo",
        "starts_at", "ends_at", "ttl_seconds", "metadata",
    }
    for item in items:
        if not isinstance(item, dict) or not set(item).issubset(allowed_fields):
            raise invalid_response("Invalid channel catalog item")
        required = {"external_id", "name", "reference", "kind", "ttl_seconds"}
        if required - item.keys():
            raise invalid_response("Channel catalog item is missing required fields")
        external_id = item["external_id"]
        name = item["name"]
        reference = item["reference"]
        kind = item["kind"]
        if (not isinstance(external_id, str) or not external_id.strip()
                or len(external_id) > CHANNEL_CATALOG_MAX_EXTERNAL_ID_LENGTH):
            raise invalid_response("Invalid channel catalog external_id")
        if external_id in seen_external_ids:
            raise invalid_response("Duplicate channel catalog external_id")
        seen_external_ids.add(external_id)
        if not isinstance(name, str) or not name.strip() or len(name) > CHANNEL_CATALOG_MAX_NAME_LENGTH:
            raise invalid_response("Invalid channel catalog name")
        if not isinstance(reference, str) or not reference or len(reference) > CHANNEL_CATALOG_MAX_REFERENCE_LENGTH:
            raise invalid_response("Invalid channel catalog reference")
        try:
            parsed = urlsplit(reference)
        except ValueError as exc:
            raise invalid_response("Invalid channel catalog reference") from exc
        scheme = parsed.scheme.lower()
        if (not _CATALOG_SCHEME_RE.fullmatch(scheme) or scheme not in allowed
                or not (parsed.netloc or parsed.path.strip("/"))
                or parsed.username is not None or parsed.password is not None
                or parsed.fragment):
            raise invalid_response("Channel catalog reference scheme is not owned")
        if kind not in CHANNEL_CATALOG_KINDS:
            raise invalid_response("Invalid channel catalog kind")
        ttl = item["ttl_seconds"]
        if (not isinstance(ttl, int) or isinstance(ttl, bool)
                or ttl < 1 or ttl > CHANNEL_CATALOG_MAX_TTL_SECONDS):
            raise invalid_response("Invalid channel catalog TTL")
        for field, limit in (("group", CHANNEL_CATALOG_MAX_GROUP_LENGTH), ("logo", CHANNEL_CATALOG_MAX_LOGO_LENGTH)):
            if field in item and item[field] is not None:
                if not isinstance(item[field], str) or len(item[field]) > limit:
                    raise invalid_response(f"Invalid channel catalog {field}")
        logo = item.get("logo")
        if logo:
            try:
                logo_scheme = urlsplit(logo).scheme.lower()
            except ValueError as exc:
                raise invalid_response("Invalid channel catalog logo") from exc
            if logo_scheme not in {"http", "https"}:
                raise invalid_response("Invalid channel catalog logo")
        starts_at = item.get("starts_at")
        ends_at = item.get("ends_at")
        for field, timestamp in (("starts_at", starts_at), ("ends_at", ends_at)):
            if timestamp is not None and (not isinstance(timestamp, int) or isinstance(timestamp, bool) or timestamp < 0):
                raise invalid_response(f"Invalid channel catalog {field}")
        if starts_at is not None and ends_at is not None and ends_at < starts_at:
            raise invalid_response("Channel catalog event window is invalid")
        if "metadata" in item and item["metadata"] is not None:
            validate_descriptor_metadata(item["metadata"], field="channel catalog metadata")
        normalized.append(dict(item))

    try:
        encoded = json.dumps({"items": normalized}, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
    except (TypeError, ValueError, OverflowError) as exc:
        raise invalid_response("Channel catalog is not JSON serializable") from exc
    if len(encoded.encode("utf-8")) > CHANNEL_CATALOG_MAX_BYTES:
        raise invalid_response("Channel catalog exceeds the size limit")
    return {"items": normalized}


def validate_stream_descriptor(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise invalid_response("Stream descriptor must be an object")
    required = {"descriptor_version", "transport", "url", "headers", "credential_refs", "ttl_seconds",
                "expires_at", "volatile_url", "requires_proxy", "warnings"}
    if required - value.keys():
        raise invalid_response("Stream descriptor is missing required fields")
    if not set(value).issubset(DESCRIPTOR_FIELDS):
        raise invalid_response("Stream descriptor contains unsupported fields")
    if value["descriptor_version"] != "1.0" or value["transport"] not in TRANSPORTS:
        raise invalid_response("Unsupported stream descriptor version or transport")
    url = value["url"]
    if not isinstance(url, str) or len(url) > 4096:
        raise invalid_response("Invalid stream URL")
    if value["transport"] != "probe_only":
        try:
            scheme = urlparse(url).scheme.lower()
        except ValueError as exc:
            raise invalid_response("Invalid stream URL") from exc
        if scheme not in {"http", "https", "rtsp"}:
            raise invalid_response("Invalid stream URL")
    headers = value["headers"]
    if not isinstance(headers, dict) or any(not isinstance(k, str) or not isinstance(v, str) for k, v in headers.items()):
        raise invalid_response("Invalid stream headers")
    if SECRET_HEADERS.intersection(k.lower() for k in headers):
        raise invalid_response("Secret headers must use credential references")
    refs = value["credential_refs"]
    if not isinstance(refs, list) or any(not isinstance(v, str) or not v for v in refs):
        raise invalid_response("Invalid credential references")
    ttl = value["ttl_seconds"]
    if ttl is not None and (not isinstance(ttl, int) or isinstance(ttl, bool) or ttl < 0):
        raise invalid_response("Invalid stream TTL")
    expiry = value["expires_at"]
    if expiry is not None and (not isinstance(expiry, int) or isinstance(expiry, bool)):
        raise invalid_response("Invalid stream expiry")
    for key in ("volatile_url", "requires_proxy"):
        if not isinstance(value[key], bool):
            raise invalid_response(f"Invalid {key}")
    if not isinstance(value["warnings"], list) or any(not isinstance(v, str) for v in value["warnings"]):
        raise invalid_response("Invalid stream warnings")
    for key in ("quality_variants", "proxy_reasons"):
        if key in value and not isinstance(value[key], list):
            raise invalid_response(f"Invalid {key}")
    if "quality_variants" in value:
        for variant in value["quality_variants"]:
            if not isinstance(variant, dict):
                raise invalid_response("Invalid quality variant")
    for key in ("referer", "origin", "user_agent"):
        if key in value and value[key] is not None and not isinstance(value[key], str):
            raise invalid_response(f"Invalid {key}")
    for key in ("drm", "encryption", "probe_hints", "refresh"):
        if key in value and value[key] is not None and not isinstance(value[key], dict):
            raise invalid_response(f"Invalid {key}")
    if "probe_hints" in value and value["probe_hints"] is not None:
        validate_descriptor_metadata(value["probe_hints"], field="probe_hints")
    diagnostics = value.get("provider_diagnostics", {})
    validate_descriptor_metadata(diagnostics, field="provider diagnostics")
    return dict(value)


def validate_station_ref(value: Any) -> dict[str, str]:
    if not isinstance(value, dict) or set(value) != {"provider_key", "provider_station_id"}:
        raise invalid_response("Invalid StationRef")
    if any(not isinstance(v, str) or not v for v in value.values()):
        raise invalid_response("Invalid StationRef")
    return dict(value)
