from __future__ import annotations

import argparse
import asyncio
import base64
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import urllib.request
import zipfile
from email.parser import BytesParser
from pathlib import Path
from typing import Any

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from packaging.utils import canonicalize_name, parse_wheel_filename

from plugin_runtime import PluginError, load_manifest, validate_manifest, validate_stream_descriptor
from plugin_runtime.process import PluginProcess
from plugin_market import manifest_signature_payload


SDK_ROOT = Path(__file__).with_name("waveflow_plugin_sdk")
FIXED_ZIP_TIME = (1980, 1, 1, 0, 0, 0)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise PluginError("INVALID_PLUGIN_RESPONSE", f"Unable to read {path.name}", category="cli") from exc
    if not isinstance(value, dict):
        raise PluginError("INVALID_PLUGIN_RESPONSE", f"{path.name} must contain an object", category="cli")
    return value


def validate_project(path: str | Path) -> dict[str, Any]:
    target = Path(path).resolve()
    manifest_path = target / "manifest.json" if target.is_dir() else target
    manifest = load_manifest(manifest_path)
    root = manifest_path.parent
    entrypoint = manifest.runtime.get("entrypoint") or manifest.artifacts[0]["entrypoint"]
    source = (root / entrypoint).resolve()
    if not source.is_relative_to(root) or not source.is_file():
        raise PluginError("ARTIFACT_NOT_FOUND", "Plugin entrypoint does not exist", category="cli")
    for artifact in manifest.artifacts:
        if Path(artifact["entrypoint"]).is_absolute() or ".." in Path(artifact["entrypoint"]).parts:
            raise PluginError("INVALID_PLUGIN_RESPONSE", "Plugin artifact path is unsafe", category="cli")
    return {"plugin": manifest.identity, "version": manifest.version, "entrypoint": entrypoint,
            "runtime": manifest.runtime["type"], "valid": True}


def _wheel_metadata(path: Path, *, base_url: str) -> dict[str, Any]:
    try:
        parsed_name, parsed_version, _build, tags = parse_wheel_filename(path.name)
    except Exception as exc:
        raise PluginError("DEPENDENCY_LOCK_INVALID", f"Invalid wheel filename: {path.name}", category="dependency") from exc
    with zipfile.ZipFile(path) as archive:
        metadata_name = next((name for name in archive.namelist() if name.endswith(".dist-info/METADATA")), None)
        if metadata_name is None:
            raise PluginError("DEPENDENCY_LOCK_INVALID", f"Wheel metadata is missing: {path.name}", category="dependency")
        metadata = BytesParser().parsebytes(archive.read(metadata_name))
    name = canonicalize_name(metadata.get("Name") or str(parsed_name))
    version = str(metadata.get("Version") or parsed_version)
    tag = sorted(tags, key=str)[0]
    digest = _sha256(path)
    return {"name": name, "version": version, "filename": path.name,
            "url": f"{base_url.rstrip('/')}/{path.name}", "sha256": digest,
            "size_bytes": path.stat().st_size, "python_tag": tag.interpreter,
            "abi_tag": tag.abi, "platform_tag": tag.platform}


def _pypi_url(name: str, version: str, filename: str) -> str:
    url = f"https://pypi.org/pypi/{name}/{version}/json"
    with urllib.request.urlopen(url, timeout=20) as response:
        payload = json.load(response)
    for item in payload.get("urls", []):
        if item.get("filename") == filename and str(item.get("url") or "").startswith("https://"):
            return str(item["url"])
    raise PluginError("DEPENDENCY_ARTIFACT_NOT_FOUND", f"PyPI artifact URL is unavailable: {filename}", category="dependency")


def lock_dependencies(requirements: Path, output: Path, *, wheel_dir: Path | None = None,
                      base_url: str = "https://files.pythonhosted.org/packages/waveflow-lock",
                      platform: str | None = None, python_version: str | None = None,
                      implementation: str = "cp", abi: str | None = None, merge: bool = False,
                      manifest_path: Path | None = None) -> dict[str, Any]:
    if not requirements.is_file():
        raise PluginError("DEPENDENCY_LOCK_INVALID", "Dependency declaration is missing", category="dependency")
    temporary: tempfile.TemporaryDirectory[str] | None = None
    if wheel_dir is None:
        temporary = tempfile.TemporaryDirectory()
        wheel_dir = Path(temporary.name)
        command = [sys.executable, "-m", "pip", "download", "--only-binary=:all:",
                   "--dest", str(wheel_dir), "-r", str(requirements)]
        if platform:
            command.extend(["--platform", platform])
        if python_version:
            command.extend(["--python-version", python_version])
        if implementation:
            command.extend(["--implementation", implementation])
        if abi:
            command.extend(["--abi", abi])
        completed = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=False)
        if completed.returncode:
            raise PluginError("DEPENDENCY_LOCK_INVALID", "Python dependency resolution failed", category="dependency",
                              details={"resolver": "pip"})
    wheels = sorted(wheel_dir.glob("*.whl"))
    if not wheels:
        raise PluginError("DEPENDENCY_ARTIFACT_NOT_FOUND", "No compatible wheels were resolved", category="dependency")
    artifacts = [_wheel_metadata(path, base_url=base_url) for path in wheels]
    if temporary is not None:
        for item in artifacts:
            item["url"] = _pypi_url(item["name"], item["version"], item["filename"])
    existing = _json(output).get("artifacts", []) if merge and output.is_file() else []
    by_key = {(item["name"], item["version"], item["python_tag"], item["abi_tag"], item["platform_tag"]): item
              for item in [*existing, *artifacts]}
    lock = {"lock_version": 1, "artifacts": sorted(by_key.values(), key=lambda item: (
        item["name"], item["version"], item["python_tag"], item["abi_tag"], item["platform_tag"]))}
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(lock, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if manifest_path is not None:
        manifest_data = _json(manifest_path)
        runtime = manifest_data.get("runtime")
        if not isinstance(runtime, dict) or runtime.get("type") != "python":
            raise PluginError("PLUGIN_INCOMPATIBLE", "Dependency lock requires a Python Plugin runtime",
                              category="runtime")
        runtime["dependency_lock"] = lock
        validate_manifest(manifest_data)
        manifest_path.write_text(json.dumps(manifest_data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if temporary is not None:
        temporary.cleanup()
    return lock


def _zip_write(archive: zipfile.ZipFile, name: str, data: bytes, *, executable: bool = False) -> None:
    info = zipfile.ZipInfo(name, FIXED_ZIP_TIME)
    info.compress_type = zipfile.ZIP_DEFLATED
    info.external_attr = ((0o755 if executable else 0o644) & 0xFFFF) << 16
    archive.writestr(info, data)


def build_sdk_artifact(entrypoint: str | Path, output: str | Path) -> dict[str, Any]:
    source = Path(entrypoint).resolve()
    target = Path(output).resolve()
    if not source.is_file():
        raise PluginError("ARTIFACT_NOT_FOUND", "Plugin entrypoint does not exist", category="cli")
    target.parent.mkdir(parents=True, exist_ok=True)
    staging = target.with_suffix(target.suffix + ".tmp")
    with zipfile.ZipFile(staging, "w") as archive:
        _zip_write(archive, "__main__.py", source.read_bytes(), executable=True)
        for path in sorted(SDK_ROOT.rglob("*.py")):
            _zip_write(archive, str(Path("waveflow_plugin_sdk") / path.relative_to(SDK_ROOT)), path.read_bytes())
    os.replace(staging, target)
    return {"artifact": str(target), "sha256": _sha256(target),
            "size_bytes": target.stat().st_size}


def build_project(project: str | Path, *, output: str | Path | None = None) -> dict[str, Any]:
    root = Path(project).resolve()
    manifest_data = _json(root / "manifest.json")
    lock_path = root / "dependency-lock.json"
    if lock_path.is_file():
        lock_data = _json(lock_path)
        if manifest_data.get("runtime", {}).get("dependency_lock") != lock_data:
            raise PluginError("DEPENDENCY_LOCK_INVALID", "Manifest dependency lock is not synchronized",
                              category="dependency")
    manifest = validate_manifest(manifest_data)
    entrypoint = str(manifest.runtime.get("entrypoint") or manifest.artifacts[0]["entrypoint"])
    source = (root / entrypoint).resolve()
    if not source.is_relative_to(root) or not source.is_file():
        raise PluginError("ARTIFACT_NOT_FOUND", "Plugin entrypoint does not exist", category="cli")
    target = Path(output).resolve() if output else root / "dist" / f"{manifest.plugin_id}-{manifest.version}.pyz"
    built = build_sdk_artifact(source, target)
    digest = built["sha256"]
    for artifact in manifest_data["artifacts"]:
        artifact.update({"entrypoint": target.name, "sha256": digest, "size_bytes": target.stat().st_size})
        artifact["signature"] = {
            "algorithm": "ed25519", "key_id": artifact["signature"].get("key_id") or "unsigned",
            "value": "UNSIGNED",
        }
    if manifest_data["runtime"]["type"] == "python":
        manifest_data["runtime"]["entrypoint"] = target.name
    dist_manifest = target.parent / "manifest.json"
    dist_manifest.write_text(json.dumps(manifest_data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return {"artifact": str(target), "manifest": str(dist_manifest), "sha256": digest,
            "size_bytes": target.stat().st_size}


def sign_build(manifest_path: str | Path, key_path: str | Path, *, key_id: str) -> dict[str, Any]:
    manifest_file = Path(manifest_path).resolve()
    data = _json(manifest_file)
    manifest = validate_manifest(data)
    artifact = data["artifacts"][0]
    artifact_path = (manifest_file.parent / artifact["entrypoint"]).resolve()
    if not artifact_path.is_relative_to(manifest_file.parent) or not artifact_path.is_file():
        raise PluginError("ARTIFACT_NOT_FOUND", "Built Plugin artifact is missing", category="cli")
    if _sha256(artifact_path) != artifact["sha256"] or artifact_path.stat().st_size != artifact["size_bytes"]:
        raise PluginError("ARTIFACT_INTEGRITY_FAILED", "Built Plugin artifact integrity check failed", category="cli")
    payload = artifact_path.read_bytes()
    raw = Path(key_path).read_bytes()
    try:
        key = serialization.load_pem_private_key(raw, password=None)
    except ValueError:
        key = Ed25519PrivateKey.from_private_bytes(raw)
    if not isinstance(key, Ed25519PrivateKey):
        raise PluginError("AUTH_FAILED", "Signing key is not Ed25519", category="trust")
    signature = {"algorithm": "ed25519", "key_id": key_id,
                 "value": base64.b64encode(key.sign(payload)).decode()}
    for candidate in data["artifacts"]:
        if (candidate["entrypoint"], candidate["sha256"], candidate["size_bytes"]) != (
                artifact["entrypoint"], artifact["sha256"], artifact["size_bytes"]):
            raise PluginError("ARTIFACT_INTEGRITY_FAILED", "Build contains inconsistent platform artifacts",
                              category="cli")
        candidate["signature"] = dict(signature)
    signed_manifest = validate_manifest(data)
    manifest_signature = {
        "algorithm": "ed25519", "key_id": key_id,
        "value": base64.b64encode(key.sign(manifest_signature_payload(signed_manifest))).decode(),
    }
    manifest_file.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    package = {"schema_version": 1, "id": f"local::{manifest.plugin_id}", "name": manifest.display_name,
               "kind": "plugin_package", "package_type": "plugin_package", "version": manifest.version,
               "plugin_manifest": data,
               "manifest_signature": manifest_signature,
               "artifact_references": [{"sha256": artifact["sha256"], "local_path": str(artifact_path)}],
               "market_source": {"source_key": "local"}}
    package_path = manifest_file.parent / "market-package.json"
    package_path.write_text(json.dumps(package, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return {"manifest": str(manifest_file), "package": str(package_path), "key_id": key_id}


async def test_build(manifest_path: Path, *, method: str, payload: dict[str, Any],
                     capabilities: dict[str, Any] | None = None, python: str = sys.executable) -> dict[str, Any]:
    manifest = load_manifest(manifest_path)
    artifact = (manifest_path.parent / manifest.artifacts[0]["entrypoint"]).resolve()
    capability_values = capabilities or {}

    async def capability(method_name: str, request: dict[str, Any], _timeout: float, _context: dict[str, Any]) -> Any:
        value = capability_values.get(method_name)
        if value is None:
            raise PluginError("CAPABILITY_DENIED", "Test capability fixture is unavailable", category="capability")
        return value

    process = PluginProcess((python, str(artifact), "--identity", manifest.identity, "--version", manifest.version),
                            "cli-test", capability_handler=capability)
    await process.start()
    try:
        hello = await process.call("runtime.hello", {})
        process.negotiate_protocol(str(hello.get("protocol_version") or "1.0"))
        health = await process.call("runtime.health", {})
        result = await process.call(method, payload)
        if method.endswith("resolve_stream"):
            validate_stream_descriptor(result)
        return {"hello": hello, "health": health, "result": result}
    finally:
        try:
            await process.call("runtime.shutdown", {}, timeout=2)
        except PluginError:
            pass
        await process.stop()


def init_project(path: Path, *, kind: str, publisher: str, plugin_id: str, scheme: str) -> None:
    path.mkdir(parents=True, exist_ok=False)
    contract = "tv_provider" if kind == "tv" else "radio_provider"
    features = ["resolve_stream"] if kind == "tv" else ["catalog", "resolve_stream"]
    capabilities = ["tv.resolve_stream"] if kind == "tv" else ["radio.catalog", "radio.resolve_stream"]
    manifest = {"manifest_version": 1, "publisher_id": publisher, "plugin_id": plugin_id,
        "display_name": plugin_id.replace("-", " ").title(), "version": "0.1.0", "plugin_api_version": "1.0",
        "core_version_range": ">=0.1.0 <1.0.0",
        "provider_contracts": [{"contract": contract, "contract_version": "1.0", "features": features}],
        "owned_schemes": [{"scheme": scheme, "contract": contract}], "capabilities": capabilities,
        "permissions": {}, "runtime": {"type": "python", "ipc": "stdio_framed_json_v1",
            "python_version_range": ">=3.11.0 <4.0.0", "entrypoint": "provider.py",
            "dependency_lock": {"lock_version": 1, "artifacts": []}},
        "artifacts": [{"os": "linux", "arch": "x86_64", "runtime": "python", "entrypoint": "provider.py",
                       "sha256": "0" * 64, "size_bytes": 1,
                       "signature": {"algorithm": "ed25519", "key_id": "developer-key", "value": "UNSIGNED"}}],
        "dependencies": [], "state_schema_version": 1}
    (path / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    base = "TVProvider, TVReference" if kind == "tv" else "RadioProvider, RadioReference"
    provider_class = "TVProvider" if kind == "tv" else "RadioProvider"
    reference = "TVReference" if kind == "tv" else "RadioReference"
    catalog = "" if kind == "tv" else '''\n    def catalog(self, payload: dict, context: ResolveContext) -> dict:\n        return {"stations": []}\n'''
    source = f'''from waveflow_plugin_sdk import PluginApplication, {base}, ResolveContext, StreamDescriptor\n\nclass Provider({provider_class}):{catalog}\n    def resolve_stream(self, reference: {reference}, context: ResolveContext) -> StreamDescriptor:\n        return StreamDescriptor.hls("https://example.invalid/live.m3u8", ttl_seconds=60)\n\ndef main() -> None:\n    identity, version = PluginApplication.identity_args("{publisher}/{plugin_id}", "0.1.0")\n    app = PluginApplication(identity=identity, version=version)\n    app.register_{kind}("{scheme}", Provider())\n    app.run()\n\nif __name__ == "__main__":\n    main()\n'''
    (path / "provider.py").write_text(source)
    (path / "requirements.in").write_text("")
    (path / "dependency-lock.json").write_text(json.dumps({"lock_version": 1, "artifacts": []}, indent=2) + "\n")
    (path / "README.md").write_text("# WaveFlow Provider Plugin\n\nRun validate, test, build, sign, then publish market-package.json.\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="waveflow-plugin")
    sub = parser.add_subparsers(dest="command", required=True)
    init = sub.add_parser("init"); init.add_argument("path", type=Path); init.add_argument("--kind", choices=("tv", "radio"), default="tv")
    init.add_argument("--publisher", required=True); init.add_argument("--plugin-id", required=True); init.add_argument("--scheme", required=True)
    validate = sub.add_parser("validate"); validate.add_argument("path")
    lock = sub.add_parser("lock"); lock.add_argument("requirements", type=Path); lock.add_argument("--output", type=Path, required=True)
    lock.add_argument("--manifest", type=Path)
    lock.add_argument("--wheel-dir", type=Path); lock.add_argument("--base-url", default="https://files.pythonhosted.org/packages/waveflow-lock")
    lock.add_argument("--platform"); lock.add_argument("--python-version"); lock.add_argument("--implementation", default="cp"); lock.add_argument("--abi"); lock.add_argument("--merge", action="store_true")
    build = sub.add_parser("build"); build.add_argument("project"); build.add_argument("--output")
    sign = sub.add_parser("sign"); sign.add_argument("manifest"); sign.add_argument("--key", required=True); sign.add_argument("--key-id", required=True)
    test = sub.add_parser("test"); test.add_argument("manifest", type=Path); test.add_argument("--method", default="tv.resolve_stream")
    test.add_argument("--payload", default='{"scheme":"synthetic","resource_id":"one","query":{}}')
    test.add_argument("--capabilities"); test.add_argument("--python", default=sys.executable)
    args = parser.parse_args(argv)
    try:
        if args.command == "init":
            init_project(args.path, kind=args.kind, publisher=args.publisher, plugin_id=args.plugin_id, scheme=args.scheme); result = {"created": str(args.path)}
        elif args.command == "validate": result = validate_project(args.path)
        elif args.command == "lock": result = lock_dependencies(args.requirements, args.output, wheel_dir=args.wheel_dir,
            base_url=args.base_url, platform=args.platform, python_version=args.python_version,
            implementation=args.implementation, abi=args.abi, merge=args.merge, manifest_path=args.manifest)
        elif args.command == "build": result = build_project(args.project, output=args.output)
        elif args.command == "sign": result = sign_build(args.manifest, args.key, key_id=args.key_id)
        else:
            fixtures = _json(Path(args.capabilities)) if args.capabilities else {}
            result = asyncio.run(test_build(args.manifest, method=args.method, payload=json.loads(args.payload),
                                            capabilities=fixtures, python=args.python))
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (PluginError, OSError, ValueError) as exc:
        code = exc.code if isinstance(exc, PluginError) else "INVALID_PLUGIN_RESPONSE"
        print(json.dumps({"error": {"code": code, "message": str(exc)[:500]}}), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
