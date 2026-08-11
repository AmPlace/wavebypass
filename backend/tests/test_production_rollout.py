from __future__ import annotations

import importlib
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import httpx


TARGETS = (
    ("jstv", "org.waveflow/jstv", "jstv://jsws"),
    ("fjtv", "org.waveflow/fjtv", "fjtv://fjzh"),
    ("nd0593tv", "org.waveflow/nd0593tv", "nd0593tv://news"),
    ("gzstv", "org.waveflow/gzstv", "gzstv://ch01"),
)
TARGET_IDENTITIES = {identity for _scheme, identity, _reference in TARGETS}
TARGET_SCHEMES = {scheme for scheme, _identity, _reference in TARGETS}
STREAMS = {
    "fjtv": "https://media.example/fjtv/live.m3u8",
    "nd0593tv": "https://media.example/nd0593tv/live.m3u8",
    "gzstv": "https://media.example/gzstv/live.m3u8",
}


def _clear_modules() -> None:
    for name in (
        "database", "market", "plugin_market", "plugin_permissions", "plugin_production",
        "official_plugin_distribution", "routers.plugins",
    ):
        sys.modules.pop(name, None)


class ProductionRolloutTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old_env = {
            name: os.environ.get(name)
            for name in (
                "WAVEFLOW_DB_PATH", "WAVEFLOW_MODE", "WAVEFLOW_OFFICIAL_PLUGIN_BOOTSTRAP",
                "WAVEFLOW_OFFICIAL_PLUGIN_ROLLOUT",
            )
        }
        os.environ["WAVEFLOW_DB_PATH"] = str(Path(self.tmp.name) / "waveflow.db")
        os.environ["WAVEFLOW_MODE"] = "nas"
        os.environ["WAVEFLOW_OFFICIAL_PLUGIN_BOOTSTRAP"] = "1"
        os.environ["WAVEFLOW_OFFICIAL_PLUGIN_ROLLOUT"] = "1"
        _clear_modules()
        self.db = importlib.import_module("database")
        await self.db.initialize()
        self.requests: list[httpx.Request] = []

        def upstream(request: httpx.Request) -> httpx.Response:
            self.requests.append(request)
            if request.url.host == "live.fjtv.net":
                return httpx.Response(200, json=[{"m3u8": STREAMS["fjtv"]}])
            if request.url.host == "app.0593tv.cn":
                return httpx.Response(200, json={"code": 200, "data": {"link": STREAMS["nd0593tv"]}})
            if request.url.host == "api.gzstv.com":
                return httpx.Response(200, json={"stream_url": STREAMS["gzstv"]})
            return httpx.Response(503, text="offline")

        self.client = httpx.AsyncClient(transport=httpx.MockTransport(upstream))
        self.legacy = mock.AsyncMock(return_value={"url": "https://legacy.example/live.m3u8"})
        self.subsystems = []
        self.safe = mock.patch("plugin_capabilities.assert_safe_target_url", new=mock.AsyncMock())
        self.safe.start()

    async def asyncTearDown(self):
        for subsystem in reversed(self.subsystems):
            await subsystem.shutdown()
        self.safe.stop()
        await self.client.aclose()
        for name, value in self.old_env.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value
        _clear_modules()
        self.tmp.cleanup()

    async def _subsystem(self):
        from plugin_production import ProductionPluginSubsystem

        subsystem = await ProductionPluginSubsystem.create(
            root=Path(self.tmp.name) / "plugin-store", http_client=self.client,
        )
        subsystem.provider_resolver.legacy_resolver = self.legacy
        self.subsystems.append(subsystem)
        return subsystem

    async def _restart(self, subsystem):
        await subsystem.shutdown()
        self.subsystems.remove(subsystem)
        restarted = await self._subsystem()
        results = await restarted.startup()
        return restarted, results

    async def _assert_plugin_routing(self, subsystem, suffix: str) -> None:
        for scheme, identity, reference in TARGETS:
            result = await subsystem.provider_resolver.resolve(reference, self.client)
            self.assertEqual(result["stream_descriptor_version"], "1.0", f"{scheme}:{suffix}")
            self.assertEqual(
                subsystem.service.runtime.registry.route(scheme).manifest.identity,
                identity,
            )

    async def test_signed_fresh_rollout_restart_offline_routing_and_reversible_ownership(self):
        from adapters import _ADAPTER_REGISTRY

        subsystem = await self._subsystem()
        startup = await subsystem.startup()
        self.assertEqual(
            {item["plugin"] for item in startup if item.get("bootstrap") == "installed"},
            TARGET_IDENTITIES,
        )
        self.assertEqual(
            {item["plugin"] for item in startup if item.get("rollout") == "plugin"},
            TARGET_IDENTITIES,
        )
        installations = await self.db.list_plugin_installations()
        self.assertEqual(
            {f"{row['publisher_id']}/{row['plugin_id']}" for row in installations},
            TARGET_IDENTITIES,
        )
        self.assertTrue(all(
            row["enabled"] and row["lifecycle_state"] == "active"
            and row["trust_state"] == "official" and row["source_key"] == "official"
            for row in installations
        ))
        owners = {row["scheme"]: row for row in await self.db.list_plugin_scheme_ownership()}
        self.assertEqual(set(owners), TARGET_SCHEMES)
        self.assertTrue(all(
            owners[scheme]["mode"] == "plugin" and owners[scheme]["plugin_identity"] == identity
            for scheme, identity, _reference in TARGETS
        ))
        self.assertEqual(
            {scheme for scheme in _ADAPTER_REGISTRY if subsystem.provider_resolver.mode(scheme) == "plugin"},
            TARGET_SCHEMES,
        )
        self.assertEqual(len(_ADAPTER_REGISTRY), 61)

        router = importlib.import_module("routers.plugins")
        projections = [await router._plugin_projection(row) for row in installations]
        self.assertTrue(all(item["ownership"] == [{
            "scheme": item["owned_schemes"][0], "mode": "plugin",
            "plugin": item["plugin"],
        }] for item in projections))
        self.assertTrue(all(not item["permissions"]["pending"] for item in projections))
        self.assertTrue(all(
            item["permissions"]["approved"] == item["permissions"]["requested"] for item in projections
        ))

        await self._assert_plugin_routing(subsystem, "fresh")
        self.legacy.assert_not_awaited()
        subsystem, recovered = await self._restart(subsystem)
        self.assertEqual(
            {item["plugin"] for item in recovered if item.get("status") == "active"},
            TARGET_IDENTITIES,
        )
        self.assertFalse(any(item.get("rollout") == "plugin" for item in recovered))
        await self._assert_plugin_routing(subsystem, "restart")
        self.legacy.assert_not_awaited()

        market = importlib.import_module("market")
        with mock.patch.object(
            market, "safe_http_fetch", new=mock.AsyncMock(side_effect=market.MarketError("offline", 502)),
        ):
            refreshed = await market.refresh_market()
        source = next(item for item in refreshed["source_results"] if item["source_key"] == "official")
        self.assertEqual(source["status"], "bundled")
        await self._assert_plugin_routing(subsystem, "offline")

        for scheme, identity, reference in TARGETS:
            self.assertEqual((await subsystem.set_ownership(scheme, "legacy"))["mode"], "legacy")
            self.assertEqual(
                (await subsystem.provider_resolver.resolve(reference, self.client))["url"],
                "https://legacy.example/live.m3u8",
            )
            self.assertEqual(
                (await subsystem.set_ownership(scheme, "plugin", identity))["mode"], "plugin",
            )
            self.assertEqual(
                (await subsystem.provider_resolver.resolve(reference, self.client))["stream_descriptor_version"],
                "1.0",
            )
        self.assertEqual(self.legacy.await_count, 4)
        final = {row["scheme"]: row for row in await self.db.list_plugin_scheme_ownership()}
        self.assertTrue(all(final[scheme]["mode"] == "plugin" for scheme in TARGET_SCHEMES))
        for scheme in TARGET_SCHEMES:
            self.assertTrue((Path("backend/adapters") / f"{scheme}.py").is_file())

    async def test_plugin_failure_has_no_legacy_fallback_and_guards_require_explicit_rollback(self):
        from plugin_runtime import PluginError

        subsystem = await self._subsystem()
        await subsystem.startup()
        for operation in (subsystem.disable, subsystem.uninstall):
            with self.assertRaises(PluginError) as blocked:
                await operation("org.waveflow/jstv")
            self.assertEqual(blocked.exception.code, "SCHEME_CONFLICT")
        with self.assertRaises(PluginError) as revoke:
            await subsystem.revoke_permission("org.waveflow/fjtv", "network.direct", "test")
        self.assertEqual(revoke.exception.code, "SCHEME_CONFLICT")

        instance = subsystem.service.runtime.registry.route("jstv")
        await instance.process.stop()
        with self.assertRaises(PluginError):
            await subsystem.provider_resolver.resolve("jstv://jsws", self.client)
        self.legacy.assert_not_awaited()
        await subsystem.set_ownership("jstv", "legacy")
        self.assertEqual(
            (await subsystem.provider_resolver.resolve("jstv://jsws", self.client))["url"],
            "https://legacy.example/live.m3u8",
        )
        subsystem, _recovered = await self._restart(subsystem)
        self.assertEqual(subsystem.provider_resolver.mode("jstv"), "legacy")
        await subsystem.set_ownership("jstv", "plugin", "org.waveflow/jstv")
        self.assertEqual(
            (await subsystem.provider_resolver.resolve("jstv://jsws", self.client))["stream_descriptor_version"],
            "1.0",
        )

    async def test_missing_installation_never_writes_owner_and_desktop_stays_legacy(self):
        subsystem = await self._subsystem()
        os.environ["WAVEFLOW_OFFICIAL_PLUGIN_BOOTSTRAP"] = "0"
        blocked = await subsystem.rollout_official_plugins()
        self.assertEqual({item["plugin"] for item in blocked}, TARGET_IDENTITIES)
        self.assertTrue(all(item["rollout"] == "blocked" for item in blocked))
        self.assertEqual(await self.db.list_plugin_scheme_ownership(), [])
        await subsystem.shutdown()
        self.subsystems.remove(subsystem)

        os.environ["WAVEFLOW_OFFICIAL_PLUGIN_BOOTSTRAP"] = "1"
        os.environ["WAVEFLOW_MODE"] = "desktop"
        desktop = await self._subsystem()
        startup = await desktop.startup()
        self.assertEqual(
            {item["plugin"] for item in startup if item.get("bootstrap") == "installed"},
            TARGET_IDENTITIES,
        )
        self.assertFalse(any(item.get("rollout") for item in startup))
        self.assertEqual(await self.db.list_plugin_scheme_ownership(), [])
        self.assertTrue(all(desktop.provider_resolver.mode(scheme) == "legacy" for scheme in TARGET_SCHEMES))


if __name__ == "__main__":
    unittest.main()
