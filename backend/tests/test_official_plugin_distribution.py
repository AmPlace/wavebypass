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


IDENTITIES = {
    "org.waveflow/jstv", "org.waveflow/fjtv", "org.waveflow/nd0593tv", "org.waveflow/gzstv",
}
SCHEMES = {identity.rsplit("/", 1)[1] for identity in IDENTITIES}


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
        policy = ProductionTrustPolicy(rows)
        for package in packages:
            manifest = validate_manifest(package["plugin_manifest"])
            for artifact in manifest.artifacts:
                reference = next(item for item in package["artifact_references"]
                                 if item["sha256"] == artifact["sha256"])
                payload = Path(reference["_bundled_path"]).read_bytes()
                policy.verify_manifest(manifest, artifact, package["manifest_signature"])
                self.assertEqual(policy.verify(manifest, artifact, payload), "official")

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
        os.environ["WAVEFLOW_DB_PATH"] = str(Path(self.tmp.name) / "waveflow.db")
        os.environ["WAVEFLOW_OFFICIAL_PLUGIN_BOOTSTRAP"] = "1"
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
        _clear_modules()
        self.tmp.cleanup()

    async def _subsystem(self):
        from plugin_production import ProductionPluginSubsystem

        subsystem = await ProductionPluginSubsystem.create(
            root=Path(self.tmp.name) / "plugin-store", http_client=self.client,
        )
        self.subsystems.append(subsystem)
        return subsystem

    async def test_fresh_bootstrap_installs_four_keeps_legacy_and_projects_settings(self):
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
        self.assertTrue(all(item["ownership"] == [{
            "scheme": item["owned_schemes"][0], "mode": "legacy", "plugin": "",
        }] for item in projections))
        market = importlib.import_module("market")
        with mock.patch.object(market, "safe_http_fetch", new=mock.AsyncMock(side_effect=market.MarketError("offline", 502))):
            await market.refresh_market()
        cards = [item for item in await market.list_packages({}) if item.get("package_type") == "plugin_package"]
        self.assertEqual(len(cards), 4)
        self.assertTrue(all(item["installed"] and item["installed_trust_state"] == "official" for item in cards))
        self.assertEqual(self.network_requests, [])

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
        self.assertEqual(len(await self.db.list_plugin_installations()), 3)

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
                         ("bundled", False, 4))
        subsystem = await self._subsystem()
        installed = await subsystem.install("org.waveflow/fjtv", market.market_packages_snapshot())
        self.assertEqual((installed["trust_state"], installed["source_key"], installed["active_version"]),
                         ("official", "official", "1.0.0"))
        self.assertEqual(subsystem.provider_resolver.mode("fjtv"), "legacy")

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
        from plugin_market import PluginArtifactStore, PluginMarketService, current_platform, manifest_signature_payload
        from plugin_production import ProductionTrustPolicy
        from plugin_runtime import PluginError, PluginRuntime, validate_manifest
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
        try:
            await service.install_from_packages([package("1.0.0")], "org.waveflow/jstv")
            await service.install_from_packages([package("1.1.0")], "org.waveflow/jstv")
            self.assertEqual(runtime.registry.route("jstv").manifest.version, "1.1.0")
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
        finally:
            await runtime.shutdown()


if __name__ == "__main__":
    unittest.main()
