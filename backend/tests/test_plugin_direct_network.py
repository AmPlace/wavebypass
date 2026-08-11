from __future__ import annotations

import base64
import asyncio
import hashlib
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey


FIXTURE = Path(__file__).parent / "fixtures" / "synthetic_plugin.py"
IDENTITY = "org.waveflow/fixture-multi-provider"


class DirectNetworkPermissionTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old_db = os.environ.get("WAVEFLOW_DB_PATH")
        os.environ["WAVEFLOW_DB_PATH"] = str(Path(self.tmp.name) / "waveflow.db")
        for name in ("database", "plugin_market", "plugin_permissions"):
            sys.modules.pop(name, None)
        import database
        import plugin_market
        from plugin_runtime import PermissionPolicy, PluginRuntime
        self.db, self.pm = database, plugin_market
        await self.db.initialize()
        self.private = Ed25519PrivateKey.generate()
        public = self.private.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
        self.runtime = PluginRuntime(permission_policy=PermissionPolicy(frozenset({"network"})))
        self.store = plugin_market.PluginArtifactStore(Path(self.tmp.name) / "store", allowed_local_roots=[FIXTURE.parent])
        self.service = plugin_market.PluginMarketService(
            runtime=self.runtime, store=self.store,
            trust_policy=plugin_market.FixtureTrustPolicy({("org.waveflow", "fixture-key"): public}),
            command_factory=lambda manifest, artifact: (sys.executable, str(artifact), "--identity", manifest.identity,
                "--version", manifest.version, "--scheme", "direct-fixture", "--tv-only", "--permissions", "network"),
            os_name="linux", arch="x86_64")

    async def asyncTearDown(self):
        await self.runtime.shutdown()
        if self.old_db is None: os.environ.pop("WAVEFLOW_DB_PATH", None)
        else: os.environ["WAVEFLOW_DB_PATH"] = self.old_db
        self.tmp.cleanup()

    def package(self, version="1.0.0", *, direct=True):
        payload = FIXTURE.read_bytes(); digest = hashlib.sha256(payload).hexdigest()
        manifest = {"manifest_version": 1, "publisher_id": "org.waveflow", "plugin_id": "fixture-multi-provider",
            "display_name": "Direct Fixture", "version": version, "plugin_api_version": "1.0",
            "core_version_range": ">=0.1.0 <1.0.0",
            "provider_contracts": [{"contract": "tv_provider", "contract_version": "1.0", "features": ["resolve_stream"]}],
            "owned_schemes": [{"scheme": "direct-fixture", "contract": "tv_provider"}],
            "capabilities": ["tv.resolve_stream"],
            "permissions": {"network": {"managed": True, **({"direct": True} if direct else {})}},
            "runtime": {"type": "subprocess", "ipc": "stdio_framed_json_v1"},
            "artifacts": [{"os": "linux", "arch": "x86_64", "runtime": "python", "entrypoint": "fixture.py",
                "sha256": digest, "size_bytes": len(payload), "signature": {"algorithm": "ed25519", "key_id": "fixture-key",
                    "value": base64.b64encode(self.private.sign(payload)).decode()}}],
            "dependencies": [], "state_schema_version": 1}
        return {"id": "official::direct-fixture", "package_type": "plugin_package", "version": version,
            "plugin_manifest": manifest, "artifact_references": [{"sha256": digest, "local_path": str(FIXTURE)}],
            "market_source": {"source_key": "official"}}

    async def test_install_gate_approval_revoke_enable_and_recovery(self):
        from plugin_runtime import PluginError
        package = self.package()
        with self.assertRaises(PluginError) as pending:
            await self.service.install_from_packages([package], IDENTITY)
        self.assertEqual(pending.exception.code, "PERMISSION_APPROVAL_REQUIRED")
        self.assertEqual(await self.db.list_plugin_installations(), [])
        self.assertEqual(list(self.store.installed_root.glob("**/artifact")), [])
        projection = await self.service.approve_permission(IDENTITY, [package], "network.direct", "test-admin")
        self.assertEqual([item["name"] for item in projection["approved"]], ["network.managed", "network.direct"])
        installed = await self.service.install_from_packages([package], IDENTITY)
        self.assertEqual(installed["lifecycle_state"], "active")
        cwd = Path(self.service._active[IDENTITY].process.working_directory)
        self.assertTrue(cwd.is_relative_to(self.store.root))
        self.assertNotEqual(cwd, Path.cwd())
        await self.service.revoke_permission(IDENTITY, "network.direct", "test-admin")
        row = await self.db.get_plugin_installation("org.waveflow", "fixture-multi-provider")
        self.assertEqual((row["enabled"], row["lifecycle_state"]), (1, "unavailable"))
        self.assertNotIn(IDENTITY, self.service._active)
        with self.assertRaises(PluginError) as denied:
            await self.service.enable(IDENTITY)
        self.assertEqual(denied.exception.code, "PERMISSION_APPROVAL_REQUIRED")
        self.assertEqual((await self.service.recover_enabled())[0]["status"], "unavailable")
        await self.service.approve_permission(IDENTITY, [package], "network.direct", "test-admin")
        self.assertEqual((await self.service.enable(IDENTITY))["lifecycle_state"], "active")

    async def test_update_permission_escalation_keeps_old_active_and_reduction_is_allowed(self):
        v1 = self.package("1.0.0", direct=False)
        await self.service.install_from_packages([v1], IDENTITY)
        v2 = self.package("2.0.0", direct=True)
        with self.assertRaises(Exception) as pending:
            await self.service.install_from_packages([v2], IDENTITY)
        self.assertEqual(pending.exception.code, "PERMISSION_APPROVAL_REQUIRED")
        self.assertEqual(self.runtime.registry.route("direct-fixture").manifest.version, "1.0.0")
        await self.service.approve_permission(IDENTITY, [v2], "network.direct", "test-admin")
        await self.service.install_from_packages([v2], IDENTITY)
        self.assertEqual(self.runtime.registry.route("direct-fixture").manifest.version, "2.0.0")
        await self.service.install_from_packages([self.package("3.0.0", direct=False)], IDENTITY)
        self.assertEqual(self.runtime.registry.route("direct-fixture").manifest.version, "3.0.0")

    async def test_ownership_and_permission_revoke_share_identity_lock(self):
        from plugin_production import ProductionPluginSubsystem
        from provider_resolver import ProviderResolver
        from plugin_runtime import PluginError

        package = self.package()
        await self.service.approve_permission(IDENTITY, [package], "network.direct", "test-admin")
        await self.service.install_from_packages([package], IDENTITY)
        subsystem = ProductionPluginSubsystem(
            self.service, self.service.trust_policy, Path(self.tmp.name) / "downloads", None,
            ProviderResolver(runtime=self.runtime), object(),
        )
        await subsystem.set_ownership("direct-fixture", "legacy")

        entered = asyncio.Event()
        release = asyncio.Event()
        original_preflight = subsystem._ownership_preflight

        async def paused_preflight(scheme, plugin_identity=""):
            result = await original_preflight(scheme, plugin_identity)
            entered.set()
            await release.wait()
            return result

        subsystem._ownership_preflight = paused_preflight
        owner_task = asyncio.create_task(subsystem.set_ownership("direct-fixture", "plugin", IDENTITY))
        revoke_started = asyncio.Event()

        async def revoke():
            revoke_started.set()
            return await subsystem.revoke_permission(IDENTITY, "network.direct", "test-admin")

        revoke_task = None
        try:
            await entered.wait()
            revoke_task = asyncio.create_task(revoke())
            await revoke_started.wait()
            self.assertFalse(revoke_task.done())
            release.set()
            await owner_task
            with self.assertRaises(PluginError) as blocked:
                await revoke_task
            self.assertEqual(blocked.exception.code, "SCHEME_CONFLICT")
            row = next(item for item in await self.db.list_plugin_scheme_ownership()
                       if item["scheme"] == "direct-fixture")
            self.assertEqual((row["mode"], row["plugin_identity"]), ("plugin", IDENTITY))
            # The ownership guard must run before the permission mutation.  The
            # fingerprint is checked through the persisted approval rows.
            approvals = await self.db.list_plugin_permission_approvals()
            self.assertTrue(any(item["permission_name"] == "network.direct" and item["approved"] for item in approvals))
        finally:
            release.set()
            if not owner_task.done():
                await owner_task
            if revoke_task is not None and not revoke_task.done():
                await revoke_task
            subsystem._ownership_preflight = original_preflight
            await subsystem.set_ownership("direct-fixture", "legacy")

    def test_subprocess_environment_allowlist_removes_core_secrets(self):
        from plugin_runtime.process import sanitized_plugin_environment
        value = sanitized_plugin_environment({"PATH": "/bin", "LANG": "C.UTF-8", "WAVEFLOW_TOKEN": "secret",
                                               "DATABASE_URL": "secret", "API_KEY": "secret"})
        self.assertEqual(value, {"PATH": "/bin", "LANG": "C.UTF-8"})


if __name__ == "__main__": unittest.main()
