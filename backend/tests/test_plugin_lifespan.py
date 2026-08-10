from __future__ import annotations

import contextlib
import importlib
import os
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest import mock


def _clear_modules():
    for name in list(sys.modules):
        if name in {"database", "main", "plugin_production", "routers.plugins"}:
            sys.modules.pop(name, None)


class PluginLifespanTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old_db = os.environ.get("WAVEFLOW_DB_PATH")
        os.environ["WAVEFLOW_DB_PATH"] = os.path.join(self.tmp.name, "waveflow.db")
        _clear_modules()
        self.main = importlib.import_module("main")

    async def asyncTearDown(self):
        if self.old_db is None:
            os.environ.pop("WAVEFLOW_DB_PATH", None)
        else:
            os.environ["WAVEFLOW_DB_PATH"] = self.old_db
        _clear_modules()
        self.tmp.cleanup()

    def patches(self, automation):
        stack = contextlib.ExitStack()
        stack.enter_context(mock.patch.object(self.main, "create_production_automation_service", new=mock.AsyncMock(return_value=automation)))
        for name in ("refresh_tokens_task", "_yunting_refresh_task", "_myradio_refresh_task", "_prefetch_rb", "_rtsp_hls_cleanup_task", "refresh_logo_template_from_remote"):
            stack.enter_context(mock.patch.object(self.main, name, new=mock.AsyncMock()))
        stack.enter_context(mock.patch.object(self.main, "_clear_stale_rtsp_hls_dirs"))
        stack.enter_context(mock.patch.object(self.main, "_load_tingfm_streams"))
        stack.enter_context(mock.patch.object(self.main, "_stop_all_rtsp_sessions", new=mock.AsyncMock()))
        stack.enter_context(mock.patch.object(self.main.http_client, "aclose", new=mock.AsyncMock()))
        stack.enter_context(mock.patch.object(self.main.yunting_client, "aclose", new=mock.AsyncMock()))
        return stack

    async def test_recovery_and_shutdown_are_lifespan_owned(self):
        events = []
        subsystem = SimpleNamespace(
            provider_resolver=object(),
            startup=mock.AsyncMock(side_effect=lambda: events.append("plugin_start") or []),
            shutdown=mock.AsyncMock(side_effect=lambda: events.append("plugin_stop")),
        )
        automation = SimpleNamespace(
            registry=SimpleNamespace(),
            start=mock.AsyncMock(side_effect=lambda: events.append("automation_start")),
            stop=mock.AsyncMock(side_effect=lambda: events.append("automation_stop")),
        )
        with self.patches(automation), mock.patch.object(
            self.main.ProductionPluginSubsystem, "create", new=mock.AsyncMock(return_value=subsystem),
        ), mock.patch.object(self.main.database, "list_plugin_installations", new=mock.AsyncMock(return_value=[])):
            async with self.main.lifespan(self.main.app):
                self.assertIs(self.main.app.state.plugin_subsystem, subsystem)
                self.assertIs(self.main.app.state.provider_resolver, subsystem.provider_resolver)
                self.assertLess(events.index("plugin_start"), events.index("automation_start"))
        self.assertLess(events.index("automation_stop"), events.index("plugin_stop"))
        subsystem.shutdown.assert_awaited_once()
        self.assertIsNone(self.main.app.state.plugin_subsystem)
        self.assertIsNone(self.main.app.state.provider_resolver)

    async def test_bad_plugin_subsystem_does_not_block_core_startup(self):
        automation = SimpleNamespace(registry=SimpleNamespace(), start=mock.AsyncMock(), stop=mock.AsyncMock())
        with self.patches(automation), mock.patch.object(
            self.main.ProductionPluginSubsystem, "create", new=mock.AsyncMock(side_effect=RuntimeError("bad plugin")),
        ):
            async with self.main.lifespan(self.main.app):
                self.assertIsNone(self.main.app.state.plugin_subsystem)
                automation.start.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()
