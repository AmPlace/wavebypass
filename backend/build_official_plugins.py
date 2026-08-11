from __future__ import annotations

import argparse
import base64
import json
import shutil
import tempfile
from pathlib import Path
from typing import Any

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from official_plugin_distribution import (
    OFFICIAL_DISTRIBUTION_ROOT, OFFICIAL_PUBLISHER_ID, load_bundled_official_market,
    load_official_trust_rows,
)
from plugin_runtime import PluginError, validate_manifest
from waveflow_plugin_cli import build_project, sign_build, validate_project


PLAN_PATH = OFFICIAL_DISTRIBUTION_ROOT / "release-plan.json"
DEFAULT_OUTPUT = OFFICIAL_DISTRIBUTION_ROOT / "distribution"
REPOSITORY_ROOT = Path(__file__).resolve().parent.parent


def _json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise PluginError("INVALID_PLUGIN_RESPONSE", "Official release metadata is invalid", category="release")
    return value


def _write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _private_key(path: Path) -> Ed25519PrivateKey:
    resolved = path.expanduser().resolve(strict=True)
    if resolved.is_relative_to(REPOSITORY_ROOT):
        raise PluginError("AUTH_FAILED", "Official signing key must remain outside the repository", category="trust")
    raw = resolved.read_bytes()
    try:
        key = serialization.load_pem_private_key(raw, password=None)
    except ValueError:
        key = Ed25519PrivateKey.from_private_bytes(raw)
    if not isinstance(key, Ed25519PrivateKey):
        raise PluginError("AUTH_FAILED", "Official signing key is not Ed25519", category="trust")
    return key


def _assert_anchor(key: Ed25519PrivateKey, key_id: str, trust_path: Path | None = None) -> None:
    encoded = base64.b64encode(key.public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw,
    )).decode()
    matches = [row for row in load_official_trust_rows(trust_path)
               if row["publisher_id"] == OFFICIAL_PUBLISHER_ID and row["key_id"] == key_id and row["enabled"]]
    if len(matches) != 1 or matches[0]["public_key"] != encoded:
        raise PluginError("PLUGIN_UNTRUSTED", "Signing key does not match the official trust anchor", category="trust")


def build_release(
    *, signing_key: Path, key_id: str, output: Path = DEFAULT_OUTPUT, trust_path: Path | None = None,
) -> dict[str, Any]:
    key = _private_key(signing_key)
    _assert_anchor(key, key_id, trust_path)
    plan = _json(PLAN_PATH)
    if (plan.get("schema_version") != 1 or plan.get("publisher_id") != OFFICIAL_PUBLISHER_ID
            or not isinstance(plan.get("plugins"), list) or not plan["plugins"]):
        raise PluginError("INVALID_PLUGIN_RESPONSE", "Official release plan is invalid", category="release")

    output = output.resolve()
    staging = output.with_name(output.name + ".staging")
    shutil.rmtree(staging, ignore_errors=True)
    (staging / "payloads").mkdir(parents=True)
    (staging / "packages").mkdir(parents=True)
    packages: list[dict[str, Any]] = []
    with tempfile.TemporaryDirectory(prefix="waveflow-official-release-") as directory:
        workspace_root = Path(directory)
        for item in sorted(plan["plugins"], key=lambda value: str(value.get("plugin_id") or "")):
            plugin_id = str(item.get("plugin_id") or "")
            source = (OFFICIAL_DISTRIBUTION_ROOT / str(item.get("source") or "")).resolve()
            if not source.is_relative_to(REPOSITORY_ROOT) or not source.is_dir():
                raise PluginError("ARTIFACT_NOT_FOUND", "Official Plugin source is unavailable", category="release")
            project = workspace_root / plugin_id
            project.mkdir()
            manifest_source = source / "manifest.json"
            manifest_data = _json(manifest_source)
            manifest = validate_manifest(manifest_data)
            if manifest.publisher_id != OFFICIAL_PUBLISHER_ID or manifest.plugin_id != plugin_id:
                raise PluginError("PLUGIN_INCOMPATIBLE", "Official Plugin identity is inconsistent", category="release")
            entrypoint = str(manifest.artifacts[0]["entrypoint"])
            shutil.copyfile(manifest_source, project / "manifest.json")
            shutil.copyfile(source / entrypoint, project / entrypoint)
            validate_project(project)

            artifact_name = f"{plugin_id}-{manifest.version}.pyz"
            built = build_project(project, output=project / "dist" / artifact_name)
            signed = sign_build(built["manifest"], signing_key, key_id=key_id)
            package = _json(Path(signed["package"]))
            artifact_source = Path(built["artifact"])
            artifact_target = staging / "payloads" / artifact_name
            shutil.copyfile(artifact_source, artifact_target)
            package.update({
                "schema_version": 1,
                "id": f"official::{plugin_id}-plugin",
                "name": str(item.get("name") or package.get("name") or manifest.display_name),
                "description": str(item.get("description") or ""),
                "kind": "plugin_package",
                "package_type": "plugin_package",
                "version": manifest.version,
                "updated_at": str(plan.get("updated_at") or ""),
                "status": "active",
                "source_origin": "official",
                "source_policy": "signed_release",
                "risk_level": "official_signed_not_sandboxed",
                "artifact_references": [{
                    "sha256": package["plugin_manifest"]["artifacts"][0]["sha256"],
                    "url": f"payloads/{artifact_name}",
                }],
            })
            rollout = item.get("rollout")
            if rollout is not None:
                if rollout != {"deployment": "python_backed", "default_ownership": "plugin"}:
                    raise PluginError(
                        "INVALID_PLUGIN_RESPONSE", "Official rollout policy is invalid", category="release",
                    )
                package["rollout"] = dict(rollout)
            package.pop("market_source", None)
            _write_json(staging / "packages" / f"{plugin_id}.market-package.json", package)
            packages.append(package)

    market = {
        "schema_version": 1,
        "market_version": str(plan.get("release_version") or ""),
        "updated_at": str(plan.get("updated_at") or ""),
        "packages": sorted(packages, key=lambda item: item["id"]),
    }
    _write_json(staging / "market.json", market)
    load_bundled_official_market(staging)
    if output.exists():
        shutil.rmtree(output)
    staging.replace(output)
    return {
        "publisher": OFFICIAL_PUBLISHER_ID,
        "key_id": key_id,
        "output": str(output),
        "package_count": len(packages),
        "packages": [item["id"] for item in packages],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Build signed WaveFlow official Plugin release artifacts")
    parser.add_argument("--signing-key", type=Path, required=True)
    parser.add_argument("--key-id", required=True)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    try:
        result = build_release(signing_key=args.signing_key, key_id=args.key_id, output=args.output)
    except (OSError, ValueError, json.JSONDecodeError, PluginError) as exc:
        if isinstance(exc, PluginError):
            print(json.dumps({"error": exc.as_contract()}, ensure_ascii=False))
        else:
            print(json.dumps({"error": {"code": "OFFICIAL_RELEASE_FAILED", "message": str(exc)}}))
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
