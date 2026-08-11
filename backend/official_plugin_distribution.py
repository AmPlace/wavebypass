from __future__ import annotations

import base64
import hashlib
import json
from copy import deepcopy
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

from plugin_runtime import PluginError, validate_manifest


OFFICIAL_PUBLISHER_ID = "org.waveflow"
OFFICIAL_SOURCE_KEY = "official"
OFFICIAL_DISTRIBUTION_ROOT = Path(__file__).resolve().with_name("official_plugins")
OFFICIAL_RELEASE_ROOT = OFFICIAL_DISTRIBUTION_ROOT / "distribution"
OFFICIAL_TRUST_PATH = OFFICIAL_DISTRIBUTION_ROOT / "publisher-trust.json"


def _load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise PluginError(
            "ARTIFACT_INVALID", "Bundled official Plugin metadata is unavailable", category="distribution",
        ) from exc
    if not isinstance(value, dict):
        raise PluginError(
            "ARTIFACT_INVALID", "Bundled official Plugin metadata is invalid", category="distribution",
        )
    return value


def load_official_trust_rows(path: str | Path | None = None) -> list[dict[str, Any]]:
    """Load public release keys shipped with WaveFlow; no private material is accepted."""
    data = _load_json(Path(path) if path else OFFICIAL_TRUST_PATH)
    if data.get("schema_version") != 1 or not isinstance(data.get("publishers"), list):
        raise PluginError("PLUGIN_UNTRUSTED", "Official publisher trust metadata is invalid", category="trust")
    rows: list[dict[str, Any]] = []
    for publisher in data["publishers"]:
        if (not isinstance(publisher, dict)
                or publisher.get("publisher_id") != OFFICIAL_PUBLISHER_ID
                or not isinstance(publisher.get("keys"), list)):
            raise PluginError("PLUGIN_UNTRUSTED", "Official publisher trust metadata is invalid", category="trust")
        for item in publisher["keys"]:
            if not isinstance(item, dict):
                raise PluginError("PLUGIN_UNTRUSTED", "Official publisher key metadata is invalid", category="trust")
            key_id = str(item.get("key_id") or "")
            encoded = str(item.get("public_key") or "")
            try:
                raw = base64.b64decode(encoded, validate=True)
            except ValueError as exc:
                raise PluginError("PLUGIN_UNTRUSTED", "Official publisher key is invalid", category="trust") from exc
            if not key_id or len(raw) != 32:
                raise PluginError("PLUGIN_UNTRUSTED", "Official publisher key is invalid", category="trust")
            rows.append({
                "publisher_id": OFFICIAL_PUBLISHER_ID,
                "key_id": key_id,
                "public_key": encoded,
                "trust_level": "official",
                "enabled": 1 if item.get("enabled", True) else 0,
                "description": str(item.get("description") or "WaveFlow official release key"),
                "require_manifest_signature": True,
            })
    if not any(row["enabled"] for row in rows):
        raise PluginError("PLUGIN_UNTRUSTED", "No official publisher key is enabled", category="trust")
    return rows


def _release_artifact(root: Path, url: str) -> Path:
    parsed = urlparse(url)
    if parsed.scheme or parsed.netloc or parsed.query or parsed.fragment:
        raise PluginError("ARTIFACT_INVALID", "Bundled official artifact reference is invalid", category="artifact")
    relative = Path(unquote(parsed.path))
    if relative.is_absolute() or ".." in relative.parts:
        raise PluginError("ARTIFACT_INVALID", "Bundled official artifact path is unsafe", category="artifact")
    path = (root / relative).resolve()
    if not path.is_relative_to(root.resolve()) or not path.is_file():
        raise PluginError("ARTIFACT_NOT_FOUND", "Bundled official artifact is missing", category="artifact")
    return path


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_bundled_official_market(root: str | Path | None = None) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Read immutable release-local packages and attach private local artifact handles."""
    release_root = (Path(root) if root else OFFICIAL_RELEASE_ROOT).resolve()
    market = _load_json(release_root / "market.json")
    if market.get("schema_version") != 1 or not isinstance(market.get("packages"), list):
        raise PluginError("ARTIFACT_INVALID", "Bundled official Market is invalid", category="distribution")
    packages: list[dict[str, Any]] = []
    for raw in market["packages"]:
        if not isinstance(raw, dict) or raw.get("package_type") != "plugin_package":
            raise PluginError("ARTIFACT_INVALID", "Bundled official package is invalid", category="distribution")
        package = deepcopy(raw)
        manifest = validate_manifest(package.get("plugin_manifest"))
        if manifest.publisher_id != OFFICIAL_PUBLISHER_ID:
            raise PluginError("PLUGIN_UNTRUSTED", "Bundled Plugin publisher is not official", category="trust")
        if package.get("version") != manifest.version:
            raise PluginError("PLUGIN_INCOMPATIBLE", "Bundled Plugin package version is inconsistent", category="distribution")
        references = package.get("artifact_references")
        if not isinstance(references, list):
            raise PluginError("ARTIFACT_INVALID", "Bundled official artifact references are invalid", category="artifact")
        local_references = []
        for reference in references:
            if (not isinstance(reference, dict)
                    or set(reference) != {"sha256", "url"}
                    or not isinstance(reference.get("url"), str)):
                raise PluginError("ARTIFACT_INVALID", "Bundled official artifact reference is invalid", category="artifact")
            path = _release_artifact(release_root, reference["url"])
            digest = _sha256(path)
            if digest != reference.get("sha256"):
                raise PluginError("ARTIFACT_INTEGRITY_FAILED", "Bundled official artifact was modified", category="artifact")
            declared = [item for item in manifest.artifacts if item["sha256"] == digest]
            if not declared or any(path.stat().st_size != item["size_bytes"] for item in declared):
                raise PluginError("ARTIFACT_INTEGRITY_FAILED", "Bundled official artifact size is invalid", category="artifact")
            local_references.append({
                "sha256": digest,
                "url": reference["url"],
                "_bundled_path": str(path),
            })
        package["artifact_references"] = local_references
        package["market_source"] = {
            "source_key": OFFICIAL_SOURCE_KEY,
            "name": "WaveFlow 官方 Market",
            "is_builtin": True,
        }
        package["_bundled_release"] = True
        packages.append(package)
    result = deepcopy(market)
    result["packages"] = deepcopy(packages)
    result["distribution"] = "bundled_signed_release"
    return result, packages


def bundled_official_packages(root: str | Path | None = None) -> list[dict[str, Any]]:
    return load_bundled_official_market(root)[1]
