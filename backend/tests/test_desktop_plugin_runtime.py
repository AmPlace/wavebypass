from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from desktop_entry import configure_desktop_environment
from plugin_desktop_runtime import resolve_plugin_python_executable
from plugin_market import FixtureTrustPolicy, PluginArtifactStore, PluginMarketService
from plugin_production import _python_backed_rollout_enabled
from plugin_runtime import PluginError, PluginRuntime
from plugin_runtime.process import PluginProcess


ROOT = Path(__file__).parents[1]


class DesktopPluginRuntimeTest(unittest.IsolatedAsyncioTestCase):
    async def test_frozen_backend_uses_sibling_controlled_runtime(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            backend = root / "backend"
            python = backend / "python-runtime" / "bin" / "python3.14"
            python.parent.mkdir(parents=True)
            python.write_text("#!/bin/sh\n", encoding="utf-8")
            python.chmod(0o755)
            (python.parent.parent / "runtime.json").write_text(
                '{"arch":"arm64","os":"macos","python_version":"3.14","schema_version":1}',
                encoding="utf-8",
            )
            executable = backend / "waveflow-backend"
            executable.write_text("", encoding="utf-8")

            with mock.patch.object(sys, "frozen", True, create=True), \
                    mock.patch.object(sys, "executable", str(executable)):
                self.assertEqual(resolve_plugin_python_executable(), python.resolve())

    async def test_frozen_backend_fails_closed_without_sidecar(self):
        with tempfile.TemporaryDirectory() as temp:
            executable = Path(temp) / "waveflow-backend"
            executable.write_text("", encoding="utf-8")
            with mock.patch.object(sys, "frozen", True, create=True), \
                    mock.patch.object(sys, "executable", str(executable)):
                with self.assertRaises(PluginError) as raised:
                    resolve_plugin_python_executable()
                self.assertEqual(raised.exception.code, "PYTHON_RUNTIME_UNSUPPORTED")

    async def test_default_python_plugin_command_uses_injected_runtime(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            sidecar = root / "python-runtime" / "bin" / "python3.14"
            sidecar.parent.mkdir(parents=True)
            sidecar.write_text("", encoding="utf-8")
            sidecar.chmod(0o755)
            (sidecar.parent.parent / "runtime.json").write_text(
                '{"arch":"arm64","os":"macos","python_version":"3.14","schema_version":1}',
                encoding="utf-8",
            )
            service = PluginMarketService(
                runtime=PluginRuntime(),
                store=PluginArtifactStore(root / "store", allowed_local_roots=[root]),
                trust_policy=FixtureTrustPolicy({}),
                python_executable=sidecar,
            )
            try:
                digest = "a" * 64
                manifest = SimpleNamespace(
                    identity="org.waveflow/fixture",
                    version="1.0.0",
                    artifacts=[{"sha256": digest, "runtime": "python"}],
                )
                command = service._default_command(manifest, root / digest / "plugin.pyz")
                self.assertEqual(command[0], str(sidecar.resolve()))
            finally:
                await service.runtime.shutdown()

    async def test_subprocess_pyz_command_uses_controlled_runtime(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            sidecar = root / "python-runtime" / "bin" / "python3.14"
            sidecar.parent.mkdir(parents=True)
            sidecar.write_text("", encoding="utf-8")
            sidecar.chmod(0o755)
            (sidecar.parent.parent / "runtime.json").write_text(
                '{"arch":"arm64","os":"macos","python_version":"3.14","schema_version":1}',
                encoding="utf-8",
            )
            service = PluginMarketService(
                runtime=PluginRuntime(),
                store=PluginArtifactStore(root / "store", allowed_local_roots=[root]),
                trust_policy=FixtureTrustPolicy({}),
                python_executable=sidecar,
            )
            try:
                digest = "b" * 64
                manifest = SimpleNamespace(
                    identity="org.waveflow/fixture-subprocess",
                    version="1.0.0",
                    artifacts=[{"sha256": digest, "runtime": "subprocess"}],
                )
                command = service._default_command(manifest, root / digest / "fixture.pyz")
                self.assertEqual(command, (
                    str(sidecar.resolve()), "-I", str(root / digest / "fixture.pyz"),
                    "--identity", manifest.identity, "--version", manifest.version,
                ))
            finally:
                await service.runtime.shutdown()

    async def test_real_dependency_free_fjtv_pyz_hello_with_python_process(self):
        artifact = ROOT / "official_plugins" / "distribution" / "payloads" / "fjtv-1.0.0.pyz"
        process = PluginProcess(
            (sys.executable, "-I", str(artifact), "--identity", "org.waveflow/fjtv", "--version", "1.0.0"),
            "desktop-fjtv",
        )
        await process.start()
        try:
            hello = await process.call(
                "runtime.hello", {"protocol_versions": ["1.0", "1.1"], "plugin_instance": "desktop-fjtv"},
            )
            health = await process.call("runtime.health", {})
            self.assertEqual(hello["plugin"], "org.waveflow/fjtv")
            self.assertTrue(health["healthy"])
        finally:
            await process.stop()

    async def test_desktop_data_dir_owns_plugin_store(self):
        with tempfile.TemporaryDirectory() as temp, mock.patch.dict(os.environ, {}, clear=True):
            configure_desktop_environment(temp)
            self.assertEqual(os.environ["WAVEFLOW_DB_PATH"], str(Path(temp) / "waveflow.db"))
            self.assertEqual(os.environ["WAVEFLOW_PLUGIN_ROOT"], str(Path(temp) / "plugins"))

    async def test_frozen_desktop_does_not_take_plugin_ownership(self):
        with mock.patch.object(sys, "frozen", True, create=True):
            self.assertFalse(_python_backed_rollout_enabled())
