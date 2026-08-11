from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import os
import platform
import shutil
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Awaitable, Callable, Iterable, Sequence

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

import database as db
from plugin_runtime import LifecycleState, PluginError, PluginInstance, PluginManifest, PluginRuntime, validate_manifest
from plugin_runtime.manifest import _range_allows, _version_tuple
from plugin_python_runtime import PythonEnvironmentManager, select_dependency_artifacts, validate_python_runtime
from plugin_permissions import permission_projection, require_high_risk_approvals, requested_permissions


PLUGIN_PACKAGE_TYPE = "plugin_package"
CONTENT_PACKAGE_TYPE = "content_package"
DEPENDENCY_STATES = frozenset({"ready", "dependency_missing", "plugin_incompatible", "provider_unavailable"})


def _safe_error(error: BaseException) -> str:
    if isinstance(error, PluginError):
        return f"{error.code}: {error.message}"[:1024]
    return "Plugin lifecycle operation failed"


def _manifest_json(manifest: PluginManifest) -> str:
    return json.dumps(manifest.raw, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def _manifest_sha256(manifest: PluginManifest) -> str:
    return hashlib.sha256(_manifest_json(manifest).encode("utf-8")).hexdigest()


def manifest_signature_payload(manifest: PluginManifest) -> bytes:
    """Canonical release statement covered by a Market Package signature."""
    return b"waveflow-plugin-manifest-v1\0" + _manifest_json(manifest).encode("utf-8")


def current_platform() -> tuple[str, str]:
    system = platform.system().lower()
    os_name = {"darwin": "macos", "linux": "linux", "windows": "windows"}.get(system, system)
    machine = platform.machine().lower()
    arch = {"amd64": "x86_64", "x64": "x86_64", "aarch64": "arm64"}.get(machine, machine)
    return os_name, arch


@dataclass(frozen=True)
class PluginCandidate:
    package_id: str
    source_key: str
    manifest: PluginManifest
    artifact: dict[str, Any]
    local_reference: Path
    dependency_references: dict[str, Path]
    manifest_signature: dict[str, Any] | None

    @property
    def identity(self) -> str:
        return self.manifest.identity


@dataclass(frozen=True)
class PreparedPluginCandidate:
    candidate: PluginCandidate
    staged_artifact: Path
    trust_state: str
    environment: Any | None = None


class FixtureTrustPolicy:
    """Explicit publisher/key trust for local fixtures; no remote trust inference."""

    def __init__(self, trusted_keys: dict[tuple[str, str], bytes]):
        self._keys = dict(trusted_keys)

    def verify(self, manifest: PluginManifest, artifact: dict[str, Any], payload: bytes) -> str:
        signature = artifact.get("signature") or {}
        if signature.get("algorithm") != "ed25519":
            raise PluginError("PLUGIN_INCOMPATIBLE", "Unsupported plugin signature", category="trust")
        key_id = str(signature.get("key_id") or "")
        key = self._keys.get((manifest.publisher_id, key_id))
        if key is None:
            raise PluginError("AUTH_FAILED", "Plugin publisher is not trusted", category="trust")
        try:
            encoded = base64.b64decode(str(signature.get("value") or ""), validate=True)
            Ed25519PublicKey.from_public_bytes(key).verify(encoded, payload)
        except (ValueError, InvalidSignature) as exc:
            raise PluginError("AUTH_FAILED", "Plugin signature verification failed", category="trust") from exc
        return "fixture_trusted"

    def verify_manifest(
        self, manifest: PluginManifest, artifact: dict[str, Any], signature: dict[str, Any] | None,
    ) -> None:
        # Manifest signatures are a compatible Market Package extension. Old
        # fixture/third-party packages remain valid, while fixtures that opt in
        # are checked by the same publisher key as their artifact.
        if signature is None:
            return
        if (not isinstance(signature, dict)
                or set(signature) != {"algorithm", "key_id", "value"}
                or signature.get("algorithm") != "ed25519"):
            raise PluginError("AUTH_FAILED", "Plugin manifest signature is invalid", category="trust")
        key_id = str(signature.get("key_id") or "")
        if key_id != str((artifact.get("signature") or {}).get("key_id") or ""):
            raise PluginError("AUTH_FAILED", "Plugin manifest signer does not match its artifact", category="trust")
        key = self._keys.get((manifest.publisher_id, key_id))
        if key is None:
            raise PluginError("AUTH_FAILED", "Plugin publisher is not trusted", category="trust")
        try:
            encoded = base64.b64decode(str(signature.get("value") or ""), validate=True)
            Ed25519PublicKey.from_public_bytes(key).verify(encoded, manifest_signature_payload(manifest))
        except (ValueError, InvalidSignature) as exc:
            raise PluginError("AUTH_FAILED", "Plugin manifest signature verification failed", category="trust") from exc


def _read_artifact(path: Path, *, max_bytes: int | None = None) -> bytes:
    if max_bytes is not None and path.stat().st_size > max_bytes:
        raise PluginError("ARTIFACT_INVALID", "Plugin artifact exceeds the verification limit", category="artifact")
    with path.open("rb") as stream:
        return stream.read()


class PluginArtifactStore:
    def __init__(self, root: str | Path, *, allowed_local_roots: Iterable[str | Path]):
        self.root = Path(root).resolve()
        self.allowed_local_roots = tuple(Path(value).resolve() for value in allowed_local_roots)
        self.staged_root = self.root / "staged"
        self.installed_root = self.root / "installed"
        self.staged_root.mkdir(parents=True, exist_ok=True)
        self.installed_root.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _part(value: str) -> str:
        if not value or value in {".", ".."} or any(ch not in "abcdefghijklmnopqrstuvwxyz0123456789._-" for ch in value):
            raise PluginError("INVALID_PLUGIN_RESPONSE", "Invalid plugin artifact namespace", category="artifact")
        return value

    def _source(self, reference: Path) -> Path:
        resolved = reference.resolve(strict=True)
        if not resolved.is_file() or not any(resolved.is_relative_to(root) for root in self.allowed_local_roots):
            raise PluginError("CAPABILITY_DENIED", "Local plugin artifact is outside an allowed fixture root", category="artifact")
        return resolved

    def stage(self, candidate: PluginCandidate, trust: FixtureTrustPolicy) -> tuple[Path, str]:
        source = self._source(candidate.local_reference)
        artifact = candidate.artifact
        identity_dir = Path(self._part(candidate.manifest.publisher_id)) / self._part(candidate.manifest.plugin_id)
        version = self._part(candidate.manifest.version)
        digest = str(artifact["sha256"])
        target_dir = self.staged_root / identity_dir / version / digest
        target_dir.mkdir(parents=True, exist_ok=True)
        fd, temp_name = tempfile.mkstemp(prefix="artifact-", dir=target_dir)
        os.close(fd)
        temp = Path(temp_name)
        try:
            shutil.copyfile(source, temp)
            payload = _read_artifact(temp, max_bytes=int(artifact["size_bytes"]))
            actual = hashlib.sha256(payload).hexdigest()
            if actual != digest or len(payload) != int(artifact["size_bytes"]):
                raise PluginError("INVALID_PLUGIN_RESPONSE", "Plugin artifact digest or size mismatch", category="artifact")
            trust_state = trust.verify(candidate.manifest, artifact, payload)
            staged = target_dir / "artifact"
            os.replace(temp, staged)
            return staged, trust_state
        except BaseException:
            temp.unlink(missing_ok=True)
            shutil.rmtree(target_dir, ignore_errors=True)
            raise

    def promote(self, candidate: PluginCandidate, staged: Path) -> Path:
        identity_dir = Path(self._part(candidate.manifest.publisher_id)) / self._part(candidate.manifest.plugin_id)
        target_dir = self.installed_root / identity_dir / self._part(candidate.manifest.version) / candidate.artifact["sha256"]
        target_dir.parent.mkdir(parents=True, exist_ok=True)
        if target_dir.exists():
            shutil.rmtree(target_dir)
        os.replace(staged.parent, target_dir)
        return target_dir / "artifact"

    def remove_path(self, value: str | Path) -> None:
        path = Path(value).resolve()
        if path.is_relative_to(self.staged_root) or path.is_relative_to(self.installed_root):
            shutil.rmtree(path.parent, ignore_errors=True)

    def remove_plugin(self, publisher_id: str, plugin_id: str) -> None:
        relative = Path(self._part(publisher_id)) / self._part(plugin_id)
        shutil.rmtree(self.staged_root / relative, ignore_errors=True)
        shutil.rmtree(self.installed_root / relative, ignore_errors=True)

    def cleanup_orphan_staging(self, live_paths: Iterable[str]) -> int:
        live = {str(Path(path).resolve()) for path in live_paths}
        removed = 0
        if not self.staged_root.exists():
            return 0
        for artifact in self.staged_root.glob("*/*/*/*/artifact"):
            if str(artifact.resolve()) not in live:
                shutil.rmtree(artifact.parent, ignore_errors=True)
                removed += 1
        return removed

    def cleanup_orphan_installed(self, live_paths: Iterable[str]) -> int:
        live = {str(Path(path).resolve()) for path in live_paths}
        removed = 0
        if not self.installed_root.exists():
            return 0
        for artifact in self.installed_root.glob("*/*/*/*/artifact"):
            if str(artifact.resolve()) not in live:
                shutil.rmtree(artifact.parent, ignore_errors=True)
                removed += 1
        return removed


def _artifact_reference(package: dict, sha256: str) -> Path:
    matches = [item for item in package.get("artifact_references", [])
               if isinstance(item, dict) and item.get("sha256") == sha256]
    if len(matches) != 1 or set(matches[0]) != {"sha256", "local_path"}:
        raise PluginError("RESOURCE_NOT_FOUND", "Plugin artifact reference is missing or ambiguous", category="artifact")
    return Path(str(matches[0]["local_path"]))


def candidates_from_packages(
    packages: Iterable[dict], *, os_name: str, arch: str, core_version: str = "0.1.0"
) -> list[PluginCandidate]:
    candidates: list[PluginCandidate] = []
    for package in packages:
        if package.get("package_type") != PLUGIN_PACKAGE_TYPE:
            continue
        manifest = validate_manifest(package.get("plugin_manifest"), core_version=core_version)
        artifacts = [item for item in manifest.artifacts if item["os"] == os_name and item["arch"] == arch]
        if not artifacts:
            continue
        for artifact in artifacts:
            source = package.get("market_source") or {}
            candidates.append(PluginCandidate(
                str(package.get("id") or ""), str(source.get("source_key") or ""), manifest,
                artifact, _artifact_reference(package, artifact["sha256"]),
                _dependency_references(package, manifest),
                dict(package["manifest_signature"]) if isinstance(package.get("manifest_signature"), dict) else None,
            ))
    return candidates


def _dependency_references(package: dict, manifest: PluginManifest) -> dict[str, Path]:
    if manifest.runtime.get("type") != "python":
        return {}
    references = package.get("dependency_references") or []
    if not isinstance(references, list):
        raise PluginError("DEPENDENCY_LOCK_INVALID", "Dependency references are invalid", category="dependency")
    result = {}
    for item in select_dependency_artifacts(manifest.runtime["dependency_lock"]):
        matches = [ref for ref in references if isinstance(ref, dict) and ref.get("sha256") == item["sha256"]]
        if len(matches) == 1 and set(matches[0]) == {"sha256", "local_path"}:
            result[item["sha256"]] = Path(str(matches[0]["local_path"]))
    return result


def select_candidate(candidates: Iterable[PluginCandidate], identity: str) -> PluginCandidate:
    matching = [candidate for candidate in candidates if candidate.identity == identity]
    if not matching:
        raise PluginError("RESOURCE_NOT_FOUND", "No compatible plugin candidate is available", category="market")
    by_version: dict[str, list[PluginCandidate]] = {}
    for candidate in matching:
        by_version.setdefault(candidate.manifest.version, []).append(candidate)
    version = max(by_version, key=_version_tuple)
    selected = by_version[version]
    digests = {candidate.artifact["sha256"] for candidate in selected}
    if len(digests) != 1:
        raise PluginError("PLUGIN_INCOMPATIBLE", "Conflicting plugin artifacts were published for the same version", category="market")
    selected.sort(key=lambda value: (value.source_key, value.package_id, str(value.local_reference)))
    return selected[0]


def evaluate_dependency(
    requirement: dict[str, Any], installation: dict | None, runtime: PluginRuntime | None
) -> dict[str, Any]:
    identity = str(requirement.get("plugin") or "")
    base = {"plugin": identity, "status": "dependency_missing"}
    if not installation:
        return base
    version = str(installation.get("active_version") or installation.get("installed_version") or "")
    expression = str(requirement.get("version_range") or "")
    try:
        version_ok = _range_allows(version, expression)
    except ValueError:
        version_ok = False
    try:
        manifest = validate_manifest(json.loads(installation["manifest_json"]))
    except (KeyError, TypeError, json.JSONDecodeError, PluginError):
        return {**base, "status": "plugin_incompatible"}
    contract = str(requirement.get("contract") or "")
    required_schemes = {str(value) for value in requirement.get("required_schemes", [])}
    contracts = {item.contract for item in manifest.provider_contracts}
    schemes = {scheme for scheme, owned_contract in manifest.owned_schemes if owned_contract == contract}
    if not version_ok or contract not in contracts or not required_schemes.issubset(schemes):
        return {**base, "status": "plugin_incompatible", "version": version}
    if not installation.get("enabled") or installation.get("quarantined") or not runtime:
        return {**base, "status": "provider_unavailable", "version": version}
    try:
        instances = [runtime.registry.route(scheme) for scheme in sorted(required_schemes)]
    except PluginError:
        return {**base, "status": "provider_unavailable", "version": version}
    if any(instance.manifest.identity != identity for instance in instances):
        return {**base, "status": "provider_unavailable", "version": version}
    return {**base, "status": "ready", "version": version}


class PluginMarketService:
    def __init__(
        self,
        *,
        runtime: PluginRuntime,
        store: PluginArtifactStore,
        trust_policy: FixtureTrustPolicy,
        command_factory: Callable[[PluginManifest, Path], Sequence[str]] | None = None,
        os_name: str | None = None,
        arch: str | None = None,
        python_environments: PythonEnvironmentManager | None = None,
        dependency_fetcher: Callable[[dict[str, Any], Path], Any] | None = None,
        runtime_command_factory: Callable[[PluginManifest, Path, Any | None], Sequence[str]] | None = None,
    ):
        self.runtime = runtime
        self.store = store
        self.trust_policy = trust_policy
        self.os_name, self.arch = (os_name, arch) if os_name and arch else current_platform()
        self.command_factory = command_factory or self._default_command
        self.python_environments = python_environments or PythonEnvironmentManager(self.store.root / "python")
        self.dependency_fetcher = dependency_fetcher
        self.runtime_command_factory = runtime_command_factory
        self._active: dict[str, PluginInstance] = {}
        self._locks: dict[str, asyncio.Lock] = {}
        self._preparation_locks: dict[str, asyncio.Lock] = {}
        self.destructive_guard: Callable[[str], Awaitable[None]] | None = None
        self.workspaces_root = self.store.root / "workspaces"
        self.workspaces_root.mkdir(parents=True, exist_ok=True)

    def lifecycle_lock(self, identity: str) -> asyncio.Lock:
        """Return the process-wide lifecycle lock for one canonical Plugin."""
        return self._locks.setdefault(str(identity), asyncio.Lock())

    def preparation_lock(self, identity: str) -> asyncio.Lock:
        """Serialize filesystem preparation/removal without blocking lifecycle state changes."""
        return self._preparation_locks.setdefault(str(identity), asyncio.Lock())

    def _working_directory(self, manifest: PluginManifest, *, create: bool = True) -> Path:
        path = self.workspaces_root / self.store._part(manifest.publisher_id) / self.store._part(manifest.plugin_id)
        if create:
            path.mkdir(parents=True, exist_ok=True)
        return path

    def _runtime_command(self, manifest: PluginManifest, artifact: Path, environment: Any | None) -> Sequence[str]:
        if self.runtime_command_factory:
            return self.runtime_command_factory(manifest, artifact, environment)
        if environment:
            return (str(environment.python), "-I", str(artifact), "--identity", manifest.identity,
                    "--version", manifest.version)
        return self.command_factory(manifest, artifact)

    @staticmethod
    def _default_command(manifest: PluginManifest, artifact: Path) -> Sequence[str]:
        selected = next(item for item in manifest.artifacts if item["sha256"] == artifact.parent.name)
        if selected["runtime"] == "python":
            return (sys.executable, str(artifact), "--identity", manifest.identity,
                    "--version", manifest.version)
        return (str(artifact),)

    async def install_from_packages(self, packages: Iterable[dict], identity: str) -> dict:
        packages = list(packages)
        candidates = candidates_from_packages(packages, os_name=self.os_name, arch=self.arch)
        matching = [candidate for candidate in candidates if candidate.identity == identity]
        if not matching:
            declared = []
            for package in packages:
                if package.get("package_type") != PLUGIN_PACKAGE_TYPE:
                    continue
                try:
                    manifest = validate_manifest(package.get("plugin_manifest"))
                except PluginError:
                    continue
                if manifest.identity == identity:
                    declared.append(manifest)
            if declared:
                raise PluginError("PLATFORM_UNSUPPORTED", "Plugin has no artifact for this platform", category="compatibility")
            raise PluginError("RESOURCE_NOT_FOUND", "No compatible plugin candidate is available", category="market")
        highest = max((candidate.manifest.version for candidate in matching), key=_version_tuple)
        version_candidates = [candidate for candidate in matching if candidate.manifest.version == highest]
        digests = {candidate.artifact["sha256"] for candidate in version_candidates}
        if len(digests) != 1:
            raise PluginError("PLUGIN_INCOMPATIBLE", "Conflicting plugin artifacts were published for the same version", category="market")
        trusted: list[PluginCandidate] = []
        trust_errors: list[PluginError] = []
        for candidate in version_candidates:
            try:
                payload = _read_artifact(
                    self.store._source(candidate.local_reference),
                    max_bytes=int(candidate.artifact["size_bytes"]),
                )
                if hashlib.sha256(payload).hexdigest() != candidate.artifact["sha256"]:
                    raise PluginError("INVALID_PLUGIN_RESPONSE", "Plugin artifact digest or size mismatch", category="artifact")
                self.trust_policy.verify_manifest(
                    candidate.manifest, candidate.artifact, candidate.manifest_signature,
                )
                self.trust_policy.verify(candidate.manifest, candidate.artifact, payload)
            except PluginError as error:
                trust_errors.append(error)
            else:
                trusted.append(candidate)
        if not trusted:
            raise trust_errors[0]
        manifests = {_manifest_sha256(candidate.manifest) for candidate in trusted}
        if len(manifests) != 1:
            raise PluginError("PLUGIN_INCOMPATIBLE", "Conflicting trusted plugin manifests were published for the same version", category="market")
        candidate = select_candidate(trusted, identity)
        await require_high_risk_approvals(candidate.manifest)
        async with self.preparation_lock(identity):
            prepared = await self._prepare_candidate(candidate)
            try:
                async with self.lifecycle_lock(identity):
                    # This is the authoritative permission check.  Preparation
                    # deliberately happens outside the lifecycle lock, so a
                    # concurrent revoke must be observed immediately before any
                    # durable candidate/runtime activation is started.
                    await require_high_risk_approvals(candidate.manifest)
                    return await self._activate(prepared)
            except BaseException:
                await self._discard_prepared(prepared)
                raise

    async def _prepare_candidate(self, candidate: PluginCandidate) -> PreparedPluginCandidate:
        staged: Path | None = None
        environment = None
        try:
            staged, trust_state = await asyncio.to_thread(self.store.stage, candidate, self.trust_policy)
            if candidate.manifest.runtime.get("type") == "python":
                safe_references = {
                    digest: self.store._source(path)
                    for digest, path in candidate.dependency_references.items()
                }
                environment = await self.python_environments.prepare(
                    candidate.manifest, safe_references, fetch=self.dependency_fetcher,
                )
            return PreparedPluginCandidate(candidate, staged, trust_state, environment)
        except BaseException:
            if staged:
                await asyncio.to_thread(self.store.remove_path, staged)
            raise

    async def _discard_prepared(self, prepared: PreparedPluginCandidate) -> None:
        if prepared.staged_artifact.exists():
            await asyncio.to_thread(self.store.remove_path, prepared.staged_artifact)
        if prepared.environment:
            candidate = prepared.candidate
            row = await db.get_plugin_installation(
                candidate.manifest.publisher_id, candidate.manifest.plugin_id,
            )
            # Never remove an environment reused by the durable active version.
            # A lock-losing/revoked candidate has no durable reference and can
            # be discarded immediately.
            if not row or str(row.get("active_version") or "") != candidate.manifest.version:
                await asyncio.to_thread(
                    self.python_environments.remove_environment, prepared.environment.path,
                )

    async def _activate(self, prepared: PreparedPluginCandidate) -> dict:
        candidate = prepared.candidate
        identity = candidate.identity
        existing = await db.get_plugin_installation(candidate.manifest.publisher_id, candidate.manifest.plugin_id)
        if existing and existing.get("active_version") == candidate.manifest.version:
            if (existing.get("artifact_sha256") == candidate.artifact["sha256"]
                    and existing.get("manifest_sha256") == _manifest_sha256(candidate.manifest)):
                await self._discard_prepared(prepared)
                return self._public(existing)
            raise PluginError(
                "PLUGIN_INCOMPATIBLE",
                "Installed plugin version conflicts with different immutable package metadata",
                category="market",
            )
        if existing and existing.get("active_version"):
            try:
                if _version_tuple(candidate.manifest.version) < _version_tuple(existing["active_version"]):
                    raise PluginError("PLUGIN_INCOMPATIBLE", "Plugin downgrade is not supported", category="market")
            except ValueError as exc:
                raise PluginError("PLUGIN_INCOMPATIBLE", "Installed plugin version is invalid", category="persistence") from exc
        old = self._active.get(identity)
        staged: Path | None = prepared.staged_artifact
        promoted: Path | None = None
        instance: PluginInstance | None = None
        committed = False
        environment = prepared.environment
        try:
            promoted = await asyncio.to_thread(self.store.promote, candidate, staged)
            if environment:
                cache_by_digest = {path.parent.name: path for path in self.python_environments.cache_objects()}
                await db.begin_plugin_python_environment(
                    publisher_id=candidate.manifest.publisher_id, plugin_id=candidate.manifest.plugin_id,
                    plugin_version=candidate.manifest.version, runtime_identity=environment.runtime_identity,
                    lock_digest=environment.lock_digest, path=str(environment.path),
                    dependencies=[{**item, "path": str(cache_by_digest[item["sha256"]])}
                                  for item in environment.dependencies],
                )
            manifest_json = _manifest_json(candidate.manifest)
            manifest_signature_json = json.dumps(
                candidate.manifest_signature or {}, ensure_ascii=False, separators=(",", ":"), sort_keys=True,
            )
            await db.begin_plugin_candidate(
                publisher_id=candidate.manifest.publisher_id, plugin_id=candidate.manifest.plugin_id,
                version=candidate.manifest.version, trust_state=prepared.trust_state,
                source_key=candidate.source_key, source_package_id=candidate.package_id,
                manifest_json=manifest_json, manifest_sha256=_manifest_sha256(candidate.manifest),
                manifest_signature_json=manifest_signature_json,
                artifact_sha256=candidate.artifact["sha256"], artifact_path=str(promoted),
                runtime_type=candidate.artifact["runtime"], entrypoint=candidate.artifact["entrypoint"],
                platform_os=self.os_name, platform_arch=self.arch,
            )
            command = self._runtime_command(candidate.manifest, promoted, environment)
            instance = self.runtime.install(candidate.manifest, command,
                                            working_directory=str(self._working_directory(candidate.manifest)))
            async def persist_activation() -> None:
                activated = await db.activate_plugin_candidate(
                    publisher_id=candidate.manifest.publisher_id, plugin_id=candidate.manifest.plugin_id,
                    candidate_version=candidate.manifest.version, trust_state=prepared.trust_state,
                    source_key=candidate.source_key, source_package_id=candidate.package_id,
                    manifest_json=manifest_json, manifest_sha256=_manifest_sha256(candidate.manifest),
                    manifest_signature_json=manifest_signature_json,
                    artifact_sha256=candidate.artifact["sha256"], artifact_path=str(promoted),
                    runtime_type=candidate.artifact["runtime"], entrypoint=candidate.artifact["entrypoint"],
                    platform_os=self.os_name, platform_arch=self.arch,
                    environment={"runtime_identity": environment.runtime_identity,
                                 "lock_digest": environment.lock_digest} if environment else None,
                )
                if not activated:
                    raise PluginError("PLUGIN_UNAVAILABLE", "Plugin activation state changed concurrently", category="persistence")

            if old:
                await self.runtime.activate_candidate(old, instance, commit=persist_activation)
            else:
                await self.runtime.enable(instance)
                await persist_activation()
            self._active[identity] = instance
            committed = True
        except BaseException as error:
            if committed:
                return self._public(await db.get_plugin_installation(
                    candidate.manifest.publisher_id, candidate.manifest.plugin_id
                ))
            await db.fail_plugin_candidate(
                candidate.manifest.publisher_id, candidate.manifest.plugin_id, candidate.manifest.version, _safe_error(error)
            )
            if environment:
                await db.fail_plugin_python_environment(
                    candidate.manifest.publisher_id, candidate.manifest.plugin_id, candidate.manifest.version,
                    environment.runtime_identity, environment.lock_digest,
                )
                await asyncio.to_thread(self.python_environments.remove_environment, environment.path)
            if instance and instance is not old and instance.instance_id in self.runtime.registry.instances:
                try:
                    await self.runtime.uninstall(instance)
                except PluginError:
                    if instance.process:
                        await instance.process.stop(graceful=False)
            if promoted:
                await asyncio.to_thread(self.store.remove_path, promoted)
            elif staged:
                await asyncio.to_thread(self.store.remove_path, staged)
            raise
        if old and old.state == LifecycleState.INSTALLED_DISABLED:
            try:
                await self.runtime.uninstall(old)
            except PluginError:
                pass
        if existing and existing.get("artifact_path") and existing["artifact_path"] != str(promoted):
            try:
                await asyncio.to_thread(self.store.remove_path, existing["artifact_path"])
                await db.delete_retained_plugin_artifacts(candidate.manifest.publisher_id, candidate.manifest.plugin_id)
            except (OSError, RuntimeError):
                pass
        return self._public(await db.get_plugin_installation(candidate.manifest.publisher_id, candidate.manifest.plugin_id))

    async def disable(self, identity: str) -> dict:
        async with self.lifecycle_lock(identity):
            if self.destructive_guard is not None:
                await self.destructive_guard(identity)
            return await self._disable_unlocked(identity)

    async def _disable_unlocked(self, identity: str) -> dict:
        row = await self._row(identity)
        instance = self._active.pop(identity, None)
        if instance:
            await self.runtime.disable(instance)
        await db.set_plugin_enabled(row["publisher_id"], row["plugin_id"], False, lifecycle_state="disabled")
        return self._public(await db.get_plugin_installation(row["publisher_id"], row["plugin_id"]))

    async def enable(self, identity: str) -> dict:
        async with self.lifecycle_lock(identity):
            return await self._enable_unlocked(identity)

    async def _enable_unlocked(self, identity: str) -> dict:
        row = await self._row(identity)
        if row.get("quarantined"):
            raise PluginError("PLUGIN_QUARANTINED", "Plugin requires explicit recovery", category="lifecycle")
        if identity in self._active:
            return self._public(row)
        manifest = validate_manifest(json.loads(row["manifest_json"]))
        await require_high_risk_approvals(manifest)
        artifact = Path(row["artifact_path"])
        if not artifact.is_file():
            await db.set_plugin_enabled(row["publisher_id"], row["plugin_id"], True, lifecycle_state="unavailable", error="Installed artifact integrity check failed")
            raise PluginError("PLUGIN_UNAVAILABLE", "Installed plugin artifact failed integrity verification", category="artifact")
        payload = await asyncio.to_thread(_read_artifact, artifact, max_bytes=int(artifact.stat().st_size))
        if hashlib.sha256(payload).hexdigest() != row["artifact_sha256"]:
            await db.set_plugin_enabled(row["publisher_id"], row["plugin_id"], True, lifecycle_state="unavailable", error="Installed artifact integrity check failed")
            raise PluginError("ARTIFACT_INTEGRITY_FAILED", "Installed plugin artifact failed integrity verification", category="artifact")
        selected = next(
            (item for item in manifest.artifacts if item["sha256"] == row["artifact_sha256"]),
            None,
        )
        if selected is None:
            raise PluginError("ARTIFACT_INVALID", "Installed artifact is absent from the manifest", category="artifact")
        try:
            try:
                manifest_signature = json.loads(row.get("manifest_signature_json") or "{}")
            except json.JSONDecodeError as exc:
                raise PluginError(
                    "ARTIFACT_SIGNATURE_INVALID", "Installed Plugin manifest signature is invalid", category="trust",
                ) from exc
            self.trust_policy.verify_manifest(manifest, selected, manifest_signature or None)
            self.trust_policy.verify(manifest, selected, payload)
        except PluginError as error:
            await db.set_plugin_enabled(
                row["publisher_id"], row["plugin_id"], True,
                lifecycle_state="unavailable", error=_safe_error(error),
            )
            raise
        environment = None
        if manifest.runtime.get("type") == "python":
            try:
                _lock, digest = validate_python_runtime(manifest)
                path = self.python_environments.environment_path(manifest, digest)
                try:
                    environment = self.python_environments.verify(manifest, path)
                except PluginError:
                    environment = await self.python_environments.rebuild(manifest, {})
            except PluginError as exc:
                raise PluginError("PLUGIN_ENVIRONMENT_INVALID", "Installed Plugin environment is unavailable", category="runtime") from exc
        instance = self.runtime.install(
            manifest, self._runtime_command(manifest, artifact, environment),
            working_directory=str(self._working_directory(manifest)))
        try:
            await self.runtime.enable(instance)
        except BaseException as error:
            await db.set_plugin_enabled(row["publisher_id"], row["plugin_id"], True, lifecycle_state="unavailable", error=_safe_error(error))
            raise
        self._active[identity] = instance
        await db.set_plugin_enabled(row["publisher_id"], row["plugin_id"], True, lifecycle_state="active")
        return self._public(await db.get_plugin_installation(row["publisher_id"], row["plugin_id"]))

    async def recover_quarantine(self, identity: str) -> dict:
        async with self.lifecycle_lock(identity):
            return await self._recover_quarantine_unlocked(identity)

    async def _recover_quarantine_unlocked(self, identity: str) -> dict:
        row = await self._row(identity)
        if not row.get("quarantined"):
            raise PluginError("PLUGIN_UNAVAILABLE", "Plugin is not quarantined", category="lifecycle")
        instance = self._active.pop(identity, None)
        if instance and instance.state == LifecycleState.QUARANTINED:
            self.runtime.registry.recover(instance)
        if not await db.recover_quarantined_plugin(row["publisher_id"], row["plugin_id"]):
            raise PluginError("PLUGIN_UNAVAILABLE", "Plugin quarantine state changed", category="persistence")
        return self._public(await db.get_plugin_installation(row["publisher_id"], row["plugin_id"]))

    async def uninstall(self, identity: str) -> bool:
        # Filesystem preparation/removal always takes this order.  Permission
        # revoke/disable only need the lifecycle lock and therefore cannot form
        # the reverse edge of a deadlock.
        async with self.preparation_lock(identity):
            async with self.lifecycle_lock(identity):
                if self.destructive_guard is not None:
                    await self.destructive_guard(identity)
                return await self._uninstall_unlocked(identity)

    async def _uninstall_unlocked(self, identity: str) -> bool:
        row = await self._row(identity)
        instance = self._active.pop(identity, None)
        if instance:
            await self.runtime.uninstall(instance)
        removed = await db.delete_plugin_installation(row["publisher_id"], row["plugin_id"])
        if json.loads(row["manifest_json"]).get("runtime", {}).get("type") == "python":
            manifest = validate_manifest(json.loads(row["manifest_json"]))
            _lock, digest = validate_python_runtime(manifest)
            await asyncio.to_thread(self.python_environments.remove_environment,
                                    self.python_environments.environment_path(manifest, digest))
        for path in await db.delete_plugin_python_environments(row["publisher_id"], row["plugin_id"]):
            await asyncio.to_thread(self.python_environments.remove_environment, path)
        await asyncio.to_thread(self.store.remove_plugin, row["publisher_id"], row["plugin_id"])
        await asyncio.to_thread(shutil.rmtree,
                                self._working_directory(validate_manifest(json.loads(row["manifest_json"])), create=False), True)
        return removed

    async def recover_enabled(self) -> list[dict[str, Any]]:
        results = []
        for row in await db.list_plugin_installations():
            candidate_version = str(row.get("candidate_version") or "")
            if candidate_version:
                artifacts = await db.list_plugin_artifacts(row["publisher_id"], row["plugin_id"], state="candidate")
                environments = [item for item in await db.list_plugin_python_environments(
                    row["publisher_id"], row["plugin_id"]) if item["state"] == "candidate"]
                await db.fail_plugin_candidate(
                    row["publisher_id"], row["plugin_id"], candidate_version,
                    "Interrupted candidate was rolled back during startup recovery",
                )
                for artifact in artifacts:
                    await asyncio.to_thread(self.store.remove_path, artifact["path"])
                for environment in environments:
                    await db.fail_plugin_python_environment(
                        environment["publisher_id"], environment["plugin_id"], environment["plugin_version"],
                        environment["runtime_identity"], environment["lock_digest"])
                    await asyncio.to_thread(self.python_environments.remove_environment, environment["path"])
                row = await db.get_plugin_installation(row["publisher_id"], row["plugin_id"])
                if not row:
                    results.append({
                        "plugin": f"{artifacts[0]['publisher_id']}/{artifacts[0]['plugin_id']}" if artifacts else "unknown",
                        "status": "unavailable",
                        "error": "Interrupted initial plugin install was removed",
                    })
                    continue
            if not row.get("enabled"):
                continue
            identity = f"{row['publisher_id']}/{row['plugin_id']}"
            try:
                await self.enable(identity)
                results.append({"plugin": identity, "status": "active"})
            except BaseException as error:
                results.append({"plugin": identity, "status": "unavailable", "error": _safe_error(error)})
        live_artifact_paths: list[str] = []
        for row in await db.list_plugin_installations():
            live_artifact_paths.extend(
                artifact["path"]
                for artifact in await db.list_plugin_artifacts(row["publisher_id"], row["plugin_id"])
            )
        await asyncio.to_thread(self.store.cleanup_orphan_staging, live_artifact_paths)
        await asyncio.to_thread(self.store.cleanup_orphan_installed, live_artifact_paths)
        return results

    async def permission_projection(self, identity: str) -> dict[str, Any]:
        row = await self._row(identity)
        return await permission_projection(validate_manifest(json.loads(row["manifest_json"])))

    async def approve_permission(self, identity: str, packages: Iterable[dict], permission: str, actor: str) -> dict[str, Any]:
        candidates = candidates_from_packages(packages, os_name=self.os_name, arch=self.arch)
        candidate = select_candidate(candidates, identity)
        payload = _read_artifact(self.store._source(candidate.local_reference), max_bytes=int(candidate.artifact["size_bytes"]))
        if len(payload) != int(candidate.artifact["size_bytes"]) or hashlib.sha256(payload).hexdigest() != candidate.artifact["sha256"]:
            raise PluginError("ARTIFACT_INTEGRITY_FAILED", "Plugin artifact failed integrity verification", category="artifact")
        self.trust_policy.verify(candidate.manifest, candidate.artifact, payload)
        request = next((item for item in requested_permissions(candidate.manifest) if item.name == permission), None)
        if request is None or request.name not in {"network.direct"}:
            raise PluginError("INVALID_CAPABILITY_REQUEST", "Permission is not approvable", category="permission")
        await db.set_plugin_permission_approval(
            candidate.manifest.publisher_id, candidate.manifest.plugin_id, request.name, request.fingerprint,
            approved=True, actor=actor, manifest_version=candidate.manifest.version,
        )
        return await permission_projection(candidate.manifest)

    async def revoke_permission(self, identity: str, permission: str, actor: str) -> dict[str, Any]:
        async with self.lifecycle_lock(identity):
            if self.destructive_guard is not None:
                await self.destructive_guard(identity)
            return await self._revoke_permission_unlocked(identity, permission, actor)

    async def _revoke_permission_unlocked(self, identity: str, permission: str, actor: str) -> dict[str, Any]:
        row = await self._row(identity)
        manifest = validate_manifest(json.loads(row["manifest_json"]))
        request = next((item for item in requested_permissions(manifest) if item.name == permission), None)
        if request is None or request.name not in {"network.direct"}:
            raise PluginError("INVALID_CAPABILITY_REQUEST", "Permission is not revocable", category="permission")
        instance = self._active.pop(identity, None)
        if instance:
            await self.runtime.disable(instance)
        await db.set_plugin_permission_approval(
            manifest.publisher_id, manifest.plugin_id, request.name, request.fingerprint,
            approved=False, actor=actor, manifest_version=manifest.version,
        )
        await db.set_plugin_enabled(
            row["publisher_id"], row["plugin_id"], True,
            lifecycle_state="unavailable", error="PERMISSION_APPROVAL_REQUIRED: network.direct",
        )
        return await permission_projection(manifest)

    async def dependency_projection(self, requirements: Iterable[dict[str, Any]]) -> dict[str, Any]:
        items = []
        for requirement in requirements:
            identity = str(requirement.get("plugin") or "")
            publisher, _, plugin_id = identity.partition("/")
            row = await db.get_plugin_installation(publisher, plugin_id) if publisher and plugin_id else None
            items.append(evaluate_dependency(requirement, row, self.runtime))
        states = {item["status"] for item in items}
        status = "ready" if not states or states == {"ready"} else next(
            value for value in ("dependency_missing", "plugin_incompatible", "provider_unavailable") if value in states
        )
        return {"status": status, "dependencies": items}

    async def installed_content_dependency_projection(self, package_id: str) -> dict[str, Any]:
        install = await db.get_market_install(package_id)
        if not install:
            raise PluginError("RESOURCE_NOT_FOUND", "Content package is not installed", category="market")
        try:
            metadata = json.loads(install.get("metadata_json") or "{}")
        except json.JSONDecodeError as exc:
            raise PluginError("INVALID_PLUGIN_RESPONSE", "Installed Content package metadata is invalid", category="persistence") from exc
        requirements = metadata.get("requires_plugins") or []
        if not isinstance(requirements, list):
            raise PluginError("INVALID_PLUGIN_RESPONSE", "Installed Content package dependencies are invalid", category="persistence")
        return await self.dependency_projection(requirements)

    async def _row(self, identity: str) -> dict:
        publisher, separator, plugin_id = identity.partition("/")
        row = await db.get_plugin_installation(publisher, plugin_id) if separator else None
        if not row:
            raise PluginError("RESOURCE_NOT_FOUND", "Plugin is not installed", category="market")
        return row

    @staticmethod
    def _public(row: dict | None) -> dict:
        if not row:
            return {}
        return {
            "plugin": f"{row['publisher_id']}/{row['plugin_id']}",
            "installed_version": row["installed_version"],
            "active_version": row["active_version"],
            "enabled": bool(row["enabled"]),
            "trust_state": row["trust_state"],
            "source_key": row["source_key"],
            "lifecycle_state": row["lifecycle_state"],
            "last_activation_status": row["last_activation_status"],
            "last_error": row["last_error"],
            "quarantined": bool(row.get("quarantined")),
            "runtime": _runtime_projection(row),
        }


def _runtime_projection(row: dict) -> dict[str, Any]:
    try:
        manifest = validate_manifest(json.loads(row["manifest_json"]))
    except Exception:
        return {"type": row.get("runtime_type") or "unknown", "environment_status": "invalid"}
    runtime = manifest.runtime
    if runtime.get("type") != "python":
        return {"type": "subprocess", "environment_status": "not_applicable", "dependency_count": 0}
    lock, digest = validate_python_runtime(manifest)
    selected = select_dependency_artifacts(lock)
    return {"type": "python", "python_version_range": runtime["python_version_range"],
            "environment_status": "ready" if row.get("lifecycle_state") == "active" else "unavailable",
            "dependency_count": len(selected), "lock_digest": digest,
            "dependencies": [{"name": item["name"], "version": item["version"]} for item in selected]}
