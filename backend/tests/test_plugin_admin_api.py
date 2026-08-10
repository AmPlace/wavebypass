from __future__ import annotations

import base64
import importlib
import os
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest import mock

import httpx


def _clear_modules():
    for name in list(sys.modules):
        if name in {"database", "main", "plugin_production", "routers.plugins"}:
            sys.modules.pop(name, None)


class PluginAdminApiTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old_db = os.environ.get("WAVEFLOW_DB_PATH")
        os.environ["WAVEFLOW_DB_PATH"] = os.path.join(self.tmp.name, "waveflow.db")
        _clear_modules()
        self.db = importlib.import_module("database")
        self.main = importlib.import_module("main")
        await self.db.initialize()
        self.subsystem = SimpleNamespace(
            service=mock.Mock(),
            reload_trust=mock.AsyncMock(),
            set_ownership=mock.AsyncMock(return_value={"scheme": "synthetic", "mode": "legacy", "plugin": ""}),
        )
        self.main.app.state.plugin_subsystem = self.subsystem
        self.main.app.state.automation_service = None
        self.client = httpx.AsyncClient(transport=httpx.ASGITransport(app=self.main.app), base_url="http://test")

    async def asyncTearDown(self):
        await self.client.aclose()
        self.main.app.dependency_overrides.clear()
        if self.old_db is None:
            os.environ.pop("WAVEFLOW_DB_PATH", None)
        else:
            os.environ["WAVEFLOW_DB_PATH"] = self.old_db
        _clear_modules()
        self.tmp.cleanup()

    async def test_plugin_routes_require_admin(self):
        for method, path in (("GET", "/api/admin/plugins"), ("PUT", "/api/admin/plugins/ownership/synthetic")):
            response = await self.client.request(method, path, json={"mode": "legacy"} if method == "PUT" else None)
            self.assertIn(response.status_code, {401, 403})

    async def test_trust_write_and_projection_hide_public_key(self):
        async def admin():
            return {"id": 1, "role": "admin"}
        self.main.app.dependency_overrides[self.main.require_admin] = admin
        public_key = base64.b64encode(b"x" * 32).decode()
        response = await self.client.put("/api/admin/plugins/trust", json={
            "publisher_id": "org.example", "key_id": "release-key",
            "public_key": public_key, "trust_level": "third_party", "enabled": True,
        })
        self.assertEqual(response.status_code, 200, response.text)
        self.assertNotIn("public_key", response.json())
        listed = await self.client.get("/api/admin/plugins/trust")
        self.assertEqual(listed.status_code, 200)
        self.assertNotIn(public_key, listed.text)
        self.subsystem.reload_trust.assert_awaited_once()

    async def test_installed_projection_hides_artifact_and_process_details(self):
        async def admin():
            return {"id": 1, "role": "admin"}
        self.main.app.dependency_overrides[self.main.require_admin] = admin
        await self.db.begin_plugin_candidate(
            publisher_id="org.example", plugin_id="fixture", version="1.0.0",
            trust_state="third_party", source_key="third", source_package_id="third::fixture",
            manifest_json='{"display_name":"Fixture","owned_schemes":[],"provider_contracts":[]}',
            manifest_sha256="1" * 64, artifact_sha256="2" * 64,
            artifact_path="/secret/local/plugin", runtime_type="python", entrypoint="plugin.py",
            platform_os="linux", platform_arch="x86_64",
        )
        response = await self.client.get("/api/admin/plugins")
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("/secret/local/plugin", response.text)
        self.assertNotIn("artifact_path", response.text)
        self.assertNotIn("pid", response.text.lower())


if __name__ == "__main__":
    unittest.main()
