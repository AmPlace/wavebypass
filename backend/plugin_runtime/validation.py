from __future__ import annotations

from typing import Any
from urllib.parse import urlparse

from .errors import invalid_response


TRANSPORTS = frozenset({"hls", "dash", "http_flv", "mpegts", "rtsp", "audio_http", "probe_only"})
SECRET_HEADERS = frozenset({"authorization", "cookie", "proxy-authorization", "x-api-key"})
DESCRIPTOR_FIELDS = frozenset({
    "descriptor_version", "transport", "url", "headers", "credential_refs", "ttl_seconds", "expires_at",
    "volatile_url", "requires_proxy", "warnings", "proxy_reasons", "referer", "origin", "user_agent",
    "quality_variants", "drm", "encryption", "probe_hints", "refresh", "provider_diagnostics",
})


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
    diagnostics = value.get("provider_diagnostics", {})
    if not isinstance(diagnostics, dict) or any(not isinstance(k, str) or not isinstance(v, str) for k, v in diagnostics.items()):
        raise invalid_response("Invalid provider diagnostics")
    return dict(value)


def validate_station_ref(value: Any) -> dict[str, str]:
    if not isinstance(value, dict) or set(value) != {"provider_key", "provider_station_id"}:
        raise invalid_response("Invalid StationRef")
    if any(not isinstance(v, str) or not v for v in value.values()):
        raise invalid_response("Invalid StationRef")
    return dict(value)
