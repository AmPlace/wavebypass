from __future__ import annotations

import base64
import hashlib
import importlib
import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import httpx
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from packaging import tags


IDENTITIES = {
    "org.waveflow/jstv", "org.waveflow/fjtv", "org.waveflow/nd0593tv", "org.waveflow/gzstv",
    "org.waveflow/nowtv", "org.waveflow/nmtv", "org.waveflow/sdtv",
}
SCHEMES = {identity.rsplit("/", 1)[1] for identity in IDENTITIES}
DEPENDENCIES = {
    "org.waveflow/nowtv": [],
    "org.waveflow/nmtv": [("xxtea", "5.0.0")],
    "org.waveflow/sdtv": [("cryptography", "48.0.1"), ("cffi", "2.0.0"), ("pycparser", "3.0")],
}


def _clear_modules() -> None:
    for name in (
        "database", "market", "plugin_market", "plugin_production", "official_plugin_distribution",
        "routers.plugins",
    ):
        sys.modules.pop(name, None)


def _tree(root: Path) -> dict[str, bytes]:
    return {str(path.relative_to(root)): path.read_bytes() for path in sorted(root.rglob("*")) if path.is_file()}


class OfficialReleaseBuildTest(unittest.TestCase):
    def test_production_anchor_and_committed_packages_verify_without_private_material(self):
        from official_plugin_distribution import (
            OFFICIAL_DISTRIBUTION_ROOT, load_bundled_official_market, load_official_trust_rows,
        )
        from plugin_production import ProductionTrustPolicy
        from plugin_runtime import validate_manifest

        rows = load_official_trust_rows()
        self.assertEqual({row["publisher_id"] for row in rows}, {"org.waveflow"})
        self.assertTrue(all(row["trust_level"] == "official" for row in rows))
        self.assertTrue(all(row["require_manifest_signature"] for row in rows))
        self.assertEqual(list(OFFICIAL_DISTRIBUTION_ROOT.rglob("*.pem")), [])
        self.assertNotIn("PRIVATE KEY", (OFFICIAL_DISTRIBUTION_ROOT / "publisher-trust.json").read_text())

        _market, packages = load_bundled_official_market()
        self.assertEqual({f"{p['plugin_manifest']['publisher_id']}/{p['plugin_manifest']['plugin_id']}"
                          for p in packages}, IDENTITIES)
        self.assertEqual(_market["market_version"], "1.2.0")
        policy = ProductionTrustPolicy(rows)
        for package in packages:
            manifest = validate_manifest(package["plugin_manifest"])
            for artifact in manifest.artifacts:
                reference = next(item for item in package["artifact_references"]
                                 if item["sha256"] == artifact["sha256"])
                payload = Path(reference["_bundled_path"]).read_bytes()
                policy.verify_manifest(manifest, artifact, package["manifest_signature"])
                self.assertEqual(policy.verify(manifest, artifact, payload), "official")
            identity = manifest.identity
            lock = manifest.runtime.get("dependency_lock", {})
            expected = DEPENDENCIES.get(identity, [])
            self.assertEqual({(item["name"], item["version"]) for item in lock.get("artifacts", [])}, set(expected))
            dependency_refs = package.get("dependency_references", [])
            self.assertEqual(
                {item["sha256"] for item in dependency_refs},
                {item["sha256"] for item in lock.get("artifacts", [])},
            )
            for reference in dependency_refs:
                dependency = next(item for item in lock["artifacts"] if item["sha256"] == reference["sha256"])
                dependency_payload = Path(reference["_bundled_path"]).read_bytes()
                self.assertEqual(len(dependency_payload), dependency["size_bytes"])
                self.assertEqual(hashlib.sha256(dependency_payload).hexdigest(), dependency["sha256"])

    def test_nmtv_sdtv_candidates_cover_published_targets_without_cross_platform_fallback(self):
        from plugin_python_runtime import select_dependency_artifacts
        from plugin_runtime import PluginError

        _market, packages = importlib.import_module("official_plugin_distribution").load_bundled_official_market()
        by_identity = {
            f"{item['plugin_manifest']['publisher_id']}/{item['plugin_manifest']['plugin_id']}": item
            for item in packages
        }
        macos_cp314 = {
            tags.Tag("cp314", "cp314", "macosx_11_0_arm64"),
            tags.Tag("cp311", "abi3", "macosx_10_9_universal2"),
            tags.Tag("py3", "none", "any"),
        }
        linux_cp311 = {
            tags.Tag("cp311", "cp311", "manylinux2014_x86_64"),
            tags.Tag("cp311", "abi3", "manylinux2014_x86_64"),
            tags.Tag("py3", "none", "any"),
        }
        linux_arm64_cp311 = {
            tags.Tag("cp311", "cp311", "manylinux2014_aarch64"),
            tags.Tag("cp311", "abi3", "manylinux2014_aarch64"),
            tags.Tag("py3", "none", "any"),
        }
        expected = {
            "org.waveflow/nmtv": {
                "macos": {"83212c868cd88decde39467579282464853942e36764031f9507ee81e803ac9a"},
                "linux": {"b11d6b8119e1f4413e07f24741b6d1ad78a93012d968afabd15448b9912712ac"},
            },
            "org.waveflow/sdtv": {
                "macos": {
                    "3e4a1a3232eef2e6c732827d5722db29a0cc8b27af2a4d865b094cf954be9ca1",
                    "c654de545946e0db659b3400168c9ad31b5d29593291482c43e3564effbcee13",
                    "b727414169a36b7d524c1c3e31839a521725078d7b2ff038656844266160a992",
                },
                "linux": {
                    "f0d27a5696721ef7a672b8c810f6aded391058e0b9486e63e6d93baf765da691",
                    "8941aaadaf67246224cee8c3803777eed332a19d909b47e29c9842ef1e79ac26",
                    "b727414169a36b7d524c1c3e31839a521725078d7b2ff038656844266160a992",
                },
            },
        }
        for identity, package in by_identity.items():
            if identity not in expected:
                continue
            manifest = package["plugin_manifest"]
            self.assertEqual({(item["os"], item["arch"]) for item in manifest["artifacts"]},
                             {( "macos", "arm64"), ("linux", "x86_64")})
            lock = manifest["runtime"]["dependency_lock"]
            self.assertEqual({item["sha256"] for item in select_dependency_artifacts(lock, supported_tags=macos_cp314)},
                             expected[identity]["macos"])
            self.assertEqual({item["sha256"] for item in select_dependency_artifacts(lock, supported_tags=linux_cp311)},
                             expected[identity]["linux"])
            with self.assertRaises(PluginError) as unsupported:
                select_dependency_artifacts(lock, supported_tags=linux_arm64_cp311)
            self.assertEqual(unsupported.exception.code, "DEPENDENCY_PLATFORM_UNSUPPORTED")

    def test_release_builder_is_deterministic_with_a_test_only_key(self):
        from build_official_plugins import build_release

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            key = Ed25519PrivateKey.generate()
            key_path = root / "fixture-release-key.pem"
            key_path.write_bytes(key.private_bytes(
                serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption(),
            ))
            public = base64.b64encode(key.public_key().public_bytes(
                serialization.Encoding.Raw, serialization.PublicFormat.Raw,
            )).decode()
            trust = root / "fixture-trust.json"
            trust.write_text(json.dumps({
                "schema_version": 1,
                "publishers": [{"publisher_id": "org.waveflow", "keys": [{
                    "key_id": "fixture-release-key", "public_key": public, "enabled": True,
                }]}],
            }))
            first, second = root / "first", root / "second"
            build_release(signing_key=key_path, key_id="fixture-release-key", output=first, trust_path=trust)
            build_release(signing_key=key_path, key_id="fixture-release-key", output=second, trust_path=trust)
            self.assertEqual(_tree(first), _tree(second))


class OfficialDistributionProductionTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old_db = os.environ.get("WAVEFLOW_DB_PATH")
        self.old_bootstrap = os.environ.get("WAVEFLOW_OFFICIAL_PLUGIN_BOOTSTRAP")
        self.old_rollout = os.environ.get("WAVEFLOW_OFFICIAL_PLUGIN_ROLLOUT")
        os.environ["WAVEFLOW_DB_PATH"] = str(Path(self.tmp.name) / "waveflow.db")
        os.environ["WAVEFLOW_OFFICIAL_PLUGIN_BOOTSTRAP"] = "1"
        os.environ["WAVEFLOW_OFFICIAL_PLUGIN_ROLLOUT"] = "0"
        _clear_modules()
        self.db = importlib.import_module("database")
        await self.db.initialize()
        self.network_requests: list[httpx.Request] = []

        def transport(request: httpx.Request) -> httpx.Response:
            self.network_requests.append(request)
            return httpx.Response(503, text="offline")

        self.client = httpx.AsyncClient(transport=httpx.MockTransport(transport))
        self.subsystems = []

    async def asyncTearDown(self):
        for subsystem in reversed(self.subsystems):
            await subsystem.shutdown()
        await self.client.aclose()
        if self.old_db is None:
            os.environ.pop("WAVEFLOW_DB_PATH", None)
        else:
            os.environ["WAVEFLOW_DB_PATH"] = self.old_db
        if self.old_bootstrap is None:
            os.environ.pop("WAVEFLOW_OFFICIAL_PLUGIN_BOOTSTRAP", None)
        else:
            os.environ["WAVEFLOW_OFFICIAL_PLUGIN_BOOTSTRAP"] = self.old_bootstrap
        if self.old_rollout is None:
            os.environ.pop("WAVEFLOW_OFFICIAL_PLUGIN_ROLLOUT", None)
        else:
            os.environ["WAVEFLOW_OFFICIAL_PLUGIN_ROLLOUT"] = self.old_rollout
        _clear_modules()
        self.tmp.cleanup()

    async def _subsystem(self):
        from plugin_production import ProductionPluginSubsystem

        subsystem = await ProductionPluginSubsystem.create(
            root=Path(self.tmp.name) / "plugin-store", http_client=self.client,
        )
        self.subsystems.append(subsystem)
        return subsystem

    async def test_fresh_bootstrap_installs_official_plugins_keeps_legacy_and_projects_settings(self):
        subsystem = await self._subsystem()
        results = await subsystem.startup()
        self.assertEqual({item["plugin"] for item in results if item.get("bootstrap") == "installed"}, IDENTITIES)
        rows = await self.db.list_plugin_installations()
        self.assertEqual({f"{row['publisher_id']}/{row['plugin_id']}" for row in rows}, IDENTITIES)
        self.assertTrue(all(row["lifecycle_state"] == "active" and row["trust_state"] == "official" for row in rows))
        self.assertEqual(await self.db.list_plugin_scheme_ownership(), [])
        self.assertTrue(all(subsystem.provider_resolver.mode(scheme) == "legacy" for scheme in SCHEMES))

        router = importlib.import_module("routers.plugins")
        projections = [await router._plugin_projection(row) for row in rows]
        self.assertTrue(all(item["runtime_available"] and item["trust_state"] == "official" for item in projections))
        self.assertTrue(all(item["source_provenance"]["source_key"] == "official" for item in projections))
        projection_by_plugin = {item["plugin"]: item for item in projections}
        self.assertEqual(
            projection_by_plugin["org.waveflow/nmtv"]["runtime"],
            {
                "type": "python", "python_version_range": ">=3.11.0 <3.15.0",
                "environment_status": "ready", "dependency_count": 1,
                "dependencies": [{"name": "xxtea", "version": "5.0.0"}],
            },
        )
        self.assertEqual(
            projection_by_plugin["org.waveflow/sdtv"]["runtime"]["dependencies"],
            [{"name": name, "version": version} for name, version in DEPENDENCIES["org.waveflow/sdtv"]],
        )
        self.assertEqual(projection_by_plugin["org.waveflow/nowtv"]["runtime"]["dependency_count"], 0)
        self.assertTrue(all(item["ownership"] == [{
            "scheme": item["owned_schemes"][0], "mode": "legacy", "plugin": "",
        }] for item in projections))
        market = importlib.import_module("market")
        with mock.patch.object(market, "safe_http_fetch", new=mock.AsyncMock(side_effect=market.MarketError("offline", 502))):
            await market.refresh_market()
        cards = [item for item in await market.list_packages({}) if item.get("package_type") == "plugin_package"]
        self.assertEqual(len(cards), len(IDENTITIES))
        self.assertTrue(all(item["installed"] and item["installed_trust_state"] == "official" for item in cards))
        self.assertEqual(self.network_requests, [])
        card_by_plugin = {
            f"{item['plugin']['publisher_id']}/{item['plugin']['plugin_id']}": item for item in cards
        }
        self.assertEqual(card_by_plugin["org.waveflow/nmtv"]["plugin"]["dependencies"],
                         [{"name": "xxtea", "version": "5.0.0"}])
        self.assertEqual(card_by_plugin["org.waveflow/sdtv"]["plugin"]["dependencies"],
                         [{"name": name, "version": version} for name, version in DEPENDENCIES["org.waveflow/sdtv"]])
        detail = await market.get_package("official::nmtv-plugin")
        self.assertNotIn("artifact_references", detail)
        self.assertNotIn("dependency_references", detail)

    async def test_restart_recovers_without_market_and_uninstall_is_not_reversed(self):
        first = await self._subsystem()
        await first.startup()
        await first.shutdown()
        self.subsystems.remove(first)

        second = await self._subsystem()
        recovered = await second.startup()
        self.assertEqual({item["plugin"] for item in recovered if item.get("status") == "active"}, IDENTITIES)
        self.assertEqual(self.network_requests, [])
        self.assertTrue(all(second.service.runtime.registry.route(scheme).health == "healthy" for scheme in SCHEMES))

        await second.uninstall("org.waveflow/jstv")
        await second.shutdown()
        self.subsystems.remove(second)
        third = await self._subsystem()
        await third.startup()
        self.assertIsNone(await self.db.get_plugin_installation("org.waveflow", "jstv"))
        self.assertEqual(len(await self.db.list_plugin_installations()), len(IDENTITIES) - 1)

    async def test_python_dependency_cold_cache_warm_restart_and_environment_projection(self):
        first = await self._subsystem()
        await first.startup()
        environments = first.service.python_environments
        from plugin_python_runtime import select_dependency_artifacts
        expected_digests = {
            item["sha256"]
            for identity in ("org.waveflow/nmtv", "org.waveflow/sdtv")
            for item in select_dependency_artifacts(
                first.service.runtime.registry.route(identity.rsplit("/", 1)[1]).manifest.runtime[
                    "dependency_lock"
                ]
            )
        }
        self.assertEqual({path.parent.name for path in environments.cache_objects()}, expected_digests)
        dependency_rows = await self.db.list_plugin_dependency_artifacts()
        self.assertEqual({row["sha256"] for row in dependency_rows}, expected_digests)
        for identity in ("org.waveflow/nmtv", "org.waveflow/sdtv"):
            rows = await self.db.list_plugin_python_environments("org.waveflow", identity.rsplit("/", 1)[1])
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["state"], "active")
            self.assertTrue(Path(rows[0]["path"], "waveflow-environment.json").is_file())

        await first.shutdown()
        self.subsystems.remove(first)
        second = await self._subsystem()
        recovered = await second.startup()
        self.assertEqual({item["plugin"] for item in recovered if item.get("status") == "active"}, IDENTITIES)
        self.assertEqual({path.parent.name for path in second.service.python_environments.cache_objects()}, expected_digests)
        self.assertEqual(self.network_requests, [])
        for identity in ("org.waveflow/nmtv", "org.waveflow/sdtv"):
            plugin = identity.rsplit("/", 1)[1]
            rows = await self.db.list_plugin_python_environments("org.waveflow", plugin)
            self.assertEqual([row["state"] for row in rows], ["active"])
            self.assertEqual(second.service.runtime.registry.route(plugin).health, "healthy")

    async def test_corrupt_bundled_catalog_does_not_tear_down_recovered_installations(self):
        from official_plugin_distribution import OFFICIAL_RELEASE_ROOT

        first = await self._subsystem()
        await first.startup()
        await first.shutdown()
        self.subsystems.remove(first)
        copied = Path(self.tmp.name) / "corrupt-distribution"
        shutil.copytree(OFFICIAL_RELEASE_ROOT, copied)
        payload = next((copied / "payloads").glob("*.pyz"))
        payload.write_bytes(payload.read_bytes() + b"tamper")

        second = await self._subsystem()
        second.official_release_root = copied
        results = await second.startup()
        self.assertEqual({item["plugin"] for item in results if item.get("status") == "active"}, IDENTITIES)
        self.assertIn("org.waveflow/*", {item["plugin"] for item in results if item.get("status") == "unavailable"})
        self.assertTrue(all(second.service.runtime.registry.route(scheme).health == "healthy" for scheme in SCHEMES))

    async def test_market_offline_discovers_bundled_packages_without_update_provenance(self):
        market = importlib.import_module("market")
        with mock.patch.object(market, "safe_http_fetch", new=mock.AsyncMock(side_effect=market.MarketError("offline", 502))):
            result = await market.refresh_market()
        packages = await market.list_packages({})
        official = [item for item in packages if item.get("package_type") == "plugin_package"]
        self.assertEqual({f"{item['plugin']['publisher_id']}/{item['plugin']['plugin_id']}" for item in official}, IDENTITIES)
        source = next(item for item in result["source_results"] if item["source_key"] == "official")
        self.assertEqual((source["status"], source["usable_for_update"], source["package_count"]),
                         ("bundled", False, len(IDENTITIES)))
        subsystem = await self._subsystem()
        installed = await subsystem.install("org.waveflow/fjtv", market.market_packages_snapshot())
        self.assertEqual((installed["trust_state"], installed["source_key"], installed["active_version"]),
                         ("official", "official", "1.0.0"))
        self.assertEqual(subsystem.provider_resolver.mode("fjtv"), "legacy")

    async def test_missing_target_platform_fails_before_installation_or_ownership(self):
        from official_plugin_distribution import bundled_official_packages
        from plugin_runtime import PluginError

        subsystem = await self._subsystem()
        prepared, temporary_paths = await subsystem._prepare_packages(bundled_official_packages())
        try:
            subsystem.service.os_name = "linux"
            subsystem.service.arch = "arm64"
            with self.assertRaises(PluginError) as unsupported:
                await subsystem.service.install_from_packages(prepared, "org.waveflow/nmtv")
            self.assertEqual(unsupported.exception.code, "PLATFORM_UNSUPPORTED")
            self.assertIsNone(await self.db.get_plugin_installation("org.waveflow", "nmtv"))
            self.assertEqual(await self.db.list_plugin_scheme_ownership(), [])
        finally:
            for path in temporary_paths:
                path.unlink(missing_ok=True)

    async def test_manifest_artifact_signature_and_wrong_key_tamper_are_rejected(self):
        from official_plugin_distribution import OFFICIAL_RELEASE_ROOT, load_bundled_official_market
        from plugin_runtime import PluginError

        with tempfile.TemporaryDirectory() as directory:
            copied = Path(directory) / "distribution"
            shutil.copytree(OFFICIAL_RELEASE_ROOT, copied)
            _market, packages = load_bundled_official_market(copied)
            subsystem = await self._subsystem()
            subsystem.official_release_root = copied

            changed_manifest = json.loads(json.dumps(packages[0]))
            changed_manifest["plugin_manifest"]["display_name"] += " tampered"
            with self.assertRaises(PluginError) as manifest_error:
                await subsystem.install("org.waveflow/fjtv", [changed_manifest])
            self.assertEqual(manifest_error.exception.code, "ARTIFACT_SIGNATURE_INVALID")

            changed_signature = json.loads(json.dumps(packages[0]))
            changed_signature["manifest_signature"]["value"] = base64.b64encode(b"invalid").decode()
            with self.assertRaises(PluginError) as signature_error:
                await subsystem.install("org.waveflow/fjtv", [changed_signature])
            self.assertEqual(signature_error.exception.code, "ARTIFACT_SIGNATURE_INVALID")

            artifact_path = Path(packages[0]["artifact_references"][0]["_bundled_path"])
            artifact_path.write_bytes(artifact_path.read_bytes() + b"tamper")
            with self.assertRaises(PluginError) as artifact_error:
                load_bundled_official_market(copied)
            self.assertEqual(artifact_error.exception.code, "ARTIFACT_INTEGRITY_FAILED")

            dependency_copy = Path(directory) / "dependency-distribution"
            shutil.copytree(OFFICIAL_RELEASE_ROOT, dependency_copy)
            dependency_package = next(
                item for item in load_bundled_official_market(dependency_copy)[1]
                if item["plugin_manifest"]["plugin_id"] == "nmtv"
            )
            dependency_path = Path(dependency_package["dependency_references"][0]["_bundled_path"])
            dependency_path.write_bytes(dependency_path.read_bytes() + b"tamper")
            with self.assertRaises(PluginError) as dependency_error:
                load_bundled_official_market(dependency_copy)
            self.assertEqual(dependency_error.exception.code, "DEPENDENCY_ARTIFACT_INTEGRITY_FAILED")

        test_key = Ed25519PrivateKey.generate()
        test_public = base64.b64encode(test_key.public_key().public_bytes(
            serialization.Encoding.Raw, serialization.PublicFormat.Raw,
        )).decode()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            key_path = root / "test-key.pem"
            key_path.write_bytes(test_key.private_bytes(
                serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption(),
            ))
            trust_path = root / "test-trust.json"
            trust_path.write_text(json.dumps({"schema_version": 1, "publishers": [{
                "publisher_id": "org.waveflow", "keys": [{
                    "key_id": "test-key", "public_key": test_public, "enabled": True,
                }],
            }]}))
            from build_official_plugins import build_release
            from official_plugin_distribution import load_bundled_official_market
            build_release(signing_key=key_path, key_id="test-key", output=root / "release", trust_path=trust_path)
            _market, test_packages = load_bundled_official_market(root / "release")
            await self.db.upsert_plugin_publisher_trust(
                publisher_id="org.waveflow", key_id="test-key", public_key=test_public,
                trust_level="official", enabled=True, description="must not override distribution trust",
            )
            subsystem = await self._subsystem()
            subsystem.official_release_root = root / "release"
            with self.assertRaises(PluginError) as wrong_key:
                await subsystem.install("org.waveflow/fjtv", test_packages)
            self.assertEqual(wrong_key.exception.code, "PLUGIN_UNTRUSTED")

    async def test_signed_update_and_failed_provenance_keep_previous_active(self):
        from official_plugin_distribution import OFFICIAL_DISTRIBUTION_ROOT
        from plugin_capabilities import CapabilityGateway
        from plugin_market import PluginArtifactStore, PluginMarketService, current_platform, manifest_signature_payload
        from plugin_production import ProductionPluginSubsystem, ProductionTrustPolicy
        from plugin_runtime import PluginError, PluginRuntime, validate_manifest
        from provider_resolver import ProviderResolver
        from waveflow_plugin_cli import build_sdk_artifact

        key = Ed25519PrivateKey.generate()
        public = base64.b64encode(key.public_key().public_bytes(
            serialization.Encoding.Raw, serialization.PublicFormat.Raw,
        )).decode()
        policy = ProductionTrustPolicy([{
            "publisher_id": "org.waveflow", "key_id": "fixture-release-key", "public_key": public,
            "trust_level": "official", "enabled": 1, "require_manifest_signature": True,
        }])
        root = Path(self.tmp.name) / "signed-update"
        artifact = root / "jstv.pyz"
        artifact.parent.mkdir(parents=True)
        build_sdk_artifact(OFFICIAL_DISTRIBUTION_ROOT.parent / "bundled_plugins" / "jstv" / "plugin.py", artifact)
        payload = artifact.read_bytes()
        os_name, arch = current_platform()

        def package(version: str, *, source: Path = artifact) -> dict:
            source_payload = source.read_bytes()
            source_digest = hashlib.sha256(source_payload).hexdigest()
            data = json.loads((OFFICIAL_DISTRIBUTION_ROOT.parent / "bundled_plugins" / "jstv" / "manifest.json").read_text())
            data["version"] = version
            data["artifacts"] = [{
                "os": os_name, "arch": arch, "runtime": "python", "entrypoint": "jstv.pyz",
                "sha256": source_digest, "size_bytes": len(source_payload), "signature": {
                    "algorithm": "ed25519", "key_id": "fixture-release-key",
                    "value": base64.b64encode(key.sign(source_payload)).decode(),
                },
            }]
            manifest = validate_manifest(data)
            return {
                "schema_version": 1, "id": "official::jstv-plugin", "kind": "plugin_package",
                "package_type": "plugin_package", "version": version, "plugin_manifest": data,
                "manifest_signature": {
                    "algorithm": "ed25519", "key_id": "fixture-release-key",
                    "value": base64.b64encode(key.sign(manifest_signature_payload(manifest))).decode(),
                },
                "artifact_references": [{"sha256": source_digest, "local_path": str(source)}],
                "market_source": {"source_key": "official"},
            }

        runtime = PluginRuntime()
        service = PluginMarketService(
            runtime=runtime,
            store=PluginArtifactStore(root / "store", allowed_local_roots=[root]),
            trust_policy=policy, os_name=os_name, arch=arch,
        )
        subsystem = ProductionPluginSubsystem(
            service=service, trust_policy=policy, download_root=root / "downloads",
            http_client=self.client, provider_resolver=ProviderResolver(runtime=runtime),
            capability_gateway=CapabilityGateway(client=self.client),
        )
        try:
            await service.install_from_packages([package("1.0.0")], "org.waveflow/jstv")
            await subsystem.set_ownership("jstv", "plugin", "org.waveflow/jstv")
            await service.install_from_packages([package("1.1.0")], "org.waveflow/jstv")
            self.assertEqual(runtime.registry.route("jstv").manifest.version, "1.1.0")
            owner = next(item for item in await self.db.list_plugin_scheme_ownership()
                         if item["scheme"] == "jstv")
            self.assertEqual((owner["mode"], owner["plugin_identity"]),
                             ("plugin", "org.waveflow/jstv"))
            alternate = root / "jstv-alternate.pyz"
            alternate.write_bytes(payload + b"different-signed-artifact")
            with self.assertRaises(PluginError) as immutable_conflict:
                await service.install_from_packages(
                    [package("1.1.0", source=alternate)], "org.waveflow/jstv",
                )
            self.assertEqual(immutable_conflict.exception.code, "PLUGIN_INCOMPATIBLE")
            self.assertEqual(runtime.registry.route("jstv").manifest.version, "1.1.0")
            invalid = package("1.2.0")
            invalid["manifest_signature"] = package("1.1.0")["manifest_signature"]
            with self.assertRaises(PluginError) as rejected:
                await service.install_from_packages([invalid], "org.waveflow/jstv")
            self.assertEqual(rejected.exception.code, "ARTIFACT_SIGNATURE_INVALID")
            self.assertEqual(runtime.registry.route("jstv").manifest.version, "1.1.0")
            owner = next(item for item in await self.db.list_plugin_scheme_ownership()
                         if item["scheme"] == "jstv")
            self.assertEqual((owner["mode"], owner["plugin_identity"]),
                             ("plugin", "org.waveflow/jstv"))
        finally:
            await runtime.shutdown()


if __name__ == "__main__":
    unittest.main()
