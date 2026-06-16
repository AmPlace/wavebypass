import asyncio
import os
import sys
import tempfile
import unittest


class SecuritySettingsLayeringTest(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        os.environ["WAVEFLOW_DB_PATH"] = os.path.join(self._tmpdir.name, "t.db")
        for key in list(os.environ):
            if key.startswith("WAVEFLOW_") and key != "WAVEFLOW_DB_PATH":
                os.environ.pop(key, None)
        for mod in list(sys.modules):
            if (
                mod == "database"
                or mod == "security"
                or mod.startswith("security.")
                or mod.startswith("core.config")
                or mod.startswith("core.settings_service")
            ):
                del sys.modules[mod]

    def tearDown(self):
        for key in list(os.environ):
            if key.startswith("WAVEFLOW_"):
                os.environ.pop(key, None)
        self._tmpdir.cleanup()
        for mod in list(sys.modules):
            if (
                mod == "database"
                or mod == "security"
                or mod.startswith("security.")
                or mod.startswith("core.config")
                or mod.startswith("core.settings_service")
            ):
                del sys.modules[mod]

    def _run(self, coro):
        return asyncio.run(coro)

    def test_runtime_setting_overrides_mode_default_when_env_unset(self):
        import database as db
        from core.settings_service import get_effective_settings, update_runtime_settings

        async def go():
            await db.initialize()
            initial = await get_effective_settings()
            self.assertTrue(initial.anonymous_browse)

            await update_runtime_settings({"anonymous_browse": False}, updated_by=None)
            effective = await get_effective_settings()
            self.assertFalse(effective.anonymous_browse)

        self._run(go())

    def test_explicit_env_false_forces_setting_and_blocks_runtime_update(self):
        os.environ["WAVEFLOW_ANONYMOUS_BROWSE"] = "0"
        for mod in list(sys.modules):
            if mod.startswith("core.config") or mod.startswith("core.settings_service"):
                del sys.modules[mod]

        import database as db
        from core.settings_service import SettingsValidationError, get_effective_settings, update_runtime_settings

        async def go():
            await db.initialize()
            effective = await get_effective_settings()
            self.assertFalse(effective.anonymous_browse)
            self.assertIn("anonymous_browse", effective.forced_keys)

            with self.assertRaises(SettingsValidationError):
                await update_runtime_settings({"anonymous_browse": True}, updated_by=None)

        self._run(go())

    def test_runtime_schema_rejects_unknown_keys_and_invalid_ranges(self):
        import database as db
        from core.settings_service import SettingsValidationError, update_runtime_settings

        async def go():
            await db.initialize()
            with self.assertRaises(SettingsValidationError):
                await update_runtime_settings({"desktop_session": "secret"}, updated_by=None)
            with self.assertRaises(SettingsValidationError):
                await update_runtime_settings({"rtsp_max_sessions": 0}, updated_by=None)

        self._run(go())

    def test_new_session_is_valid_until_revoked(self):
        import database as db
        from security import database as security_db
        from security.sessions import hash_token

        async def go():
            await db.initialize()
            user = await security_db.create_admin_user("admin", "hash")
            token = "session-token"
            await security_db.create_session(user["id"], hash_token(token))

            active = await security_db.get_session_by_hash(hash_token(token))
            self.assertIsNotNone(active)
            self.assertEqual(active["username"], "admin")

            await security_db.revoke_session(hash_token(token))
            revoked = await security_db.get_session_by_hash(hash_token(token))
            self.assertIsNone(revoked)

        self._run(go())


if __name__ == "__main__":
    unittest.main()
