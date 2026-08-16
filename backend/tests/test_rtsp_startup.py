from __future__ import annotations

import asyncio
import tempfile
import unittest
from pathlib import Path
from unittest import IsolatedAsyncioTestCase, mock

from fastapi import HTTPException

import main


class _AliveProcess:
    def __init__(self):
        self.terminated = False
        self.stderr = None
        self.returncode = None

    def poll(self):
        return self.returncode

    def terminate(self):
        self.terminated = True
        self.returncode = 0

    def wait(self):
        return self.returncode


class RtspStartupSingleFlightTest(IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self._old_sessions = main.RTSP_HLS_SESSIONS
        self._old_startups = main._RTSP_HLS_STARTUPS
        self._old_reserved = main._RTSP_RESERVED_SESSIONS
        self._old_root = main.RTSP_HLS_ROOT
        self._tmp = tempfile.TemporaryDirectory()
        main.RTSP_HLS_SESSIONS = {}
        main._RTSP_HLS_STARTUPS = {}
        main._RTSP_RESERVED_SESSIONS = set()
        main.RTSP_HLS_ROOT = Path(self._tmp.name)

    async def asyncTearDown(self):
        pending = list(main._RTSP_HLS_STARTUPS.values())
        for task in pending:
            if not task.done():
                task.cancel()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)
        main._RTSP_HLS_STARTUPS.clear()
        main._RTSP_RESERVED_SESSIONS.clear()
        main.RTSP_HLS_SESSIONS = self._old_sessions
        main._RTSP_HLS_STARTUPS = self._old_startups
        main._RTSP_RESERVED_SESSIONS = self._old_reserved
        main.RTSP_HLS_ROOT = self._old_root
        self._tmp.cleanup()

    async def _wait_for_no_startup(self):
        for _ in range(20):
            if not main._RTSP_HLS_STARTUPS:
                return
            await asyncio.sleep(0)
        self.fail("RTSP startup entry was not cleaned up")

    async def test_ten_same_key_waiters_share_one_startup(self):
        started = asyncio.Event()
        release = asyncio.Event()
        calls = []

        async def start(target_url, custom_ua, compat):
            calls.append((target_url, custom_ua, compat))
            started.set()
            await release.wait()
            return "a" * 24, Path("/tmp/shared-index.m3u8")

        with mock.patch.object(main, "_start_rtsp_hls_session", new=start):
            waiters = [
                asyncio.create_task(main._ensure_rtsp_hls_session("rtsp://camera.local/live"))
                for _ in range(10)
            ]
            await started.wait()
            await asyncio.sleep(0)
            self.assertEqual(len(calls), 1)
            release.set()
            results = await asyncio.gather(*waiters)

        self.assertEqual(results, [("a" * 24, Path("/tmp/shared-index.m3u8"))] * 10)
        await self._wait_for_no_startup()

    async def test_actual_ffmpeg_startup_path_calls_popen_once(self):
        session_id = main._rtsp_session_id("rtsp://camera.local/live")
        popen_calls = 0

        def popen(*_args, **_kwargs):
            nonlocal popen_calls
            popen_calls += 1
            session_dir = main.RTSP_HLS_ROOT / session_id
            (session_dir / "index.m3u8").write_text("#EXTM3U\n", encoding="utf-8")
            for index in range(main.RTSP_HLS_START_SEGMENTS):
                (session_dir / f"seg_{index:05d}.ts").write_bytes(b"segment")
            return _AliveProcess()

        with mock.patch.object(main, "_ffmpeg_bin", return_value="/usr/bin/ffmpeg"), mock.patch.object(
            main.subprocess,
            "Popen",
            side_effect=popen,
        ):
            results = await asyncio.gather(*[
                main._ensure_rtsp_hls_session("rtsp://camera.local/live")
                for _ in range(3)
            ])

        self.assertEqual(popen_calls, 1)
        self.assertEqual(results, [results[0]] * 3)
        self.assertEqual(main.RTSP_HLS_SESSIONS[session_id]["startup_state"], "ready")
        await self._wait_for_no_startup()

    async def test_different_keys_start_in_parallel(self):
        started_keys = set()
        both_started = asyncio.Event()
        release = asyncio.Event()

        async def start(target_url, custom_ua, compat):
            started_keys.add(target_url)
            if len(started_keys) == 2:
                both_started.set()
            await release.wait()
            return main._rtsp_session_id(target_url, custom_ua, compat), Path("/tmp/index.m3u8")

        with mock.patch.object(main, "_start_rtsp_hls_session", new=start):
            first = asyncio.create_task(main._ensure_rtsp_hls_session("rtsp://camera-a.local/live"))
            second = asyncio.create_task(main._ensure_rtsp_hls_session("rtsp://camera-b.local/live"))
            await asyncio.wait_for(both_started.wait(), timeout=1)
            release.set()
            results = await asyncio.gather(first, second)

        self.assertNotEqual(results[0][0], results[1][0])
        self.assertEqual(len(started_keys), 2)
        await self._wait_for_no_startup()

    async def test_startup_failure_is_shared_cleaned_and_retryable(self):
        started = asyncio.Event()
        fail = asyncio.Event()
        calls = 0

        async def start(target_url, custom_ua, compat):
            nonlocal calls
            calls += 1
            if calls == 1:
                started.set()
                await fail.wait()
                raise HTTPException(status_code=502, detail="ffmpeg exited")
            return "b" * 24, Path("/tmp/retry-index.m3u8")

        with mock.patch.object(main, "_start_rtsp_hls_session", new=start):
            waiters = [
                asyncio.create_task(main._ensure_rtsp_hls_session("rtsp://camera.local/live"))
                for _ in range(4)
            ]
            await started.wait()
            await asyncio.sleep(0)
            self.assertEqual(calls, 1)
            fail.set()
            results = await asyncio.gather(*waiters, return_exceptions=True)

            self.assertEqual(calls, 1)
            self.assertTrue(all(isinstance(result, HTTPException) for result in results))
            self.assertTrue(all(result.status_code == 502 for result in results))
            await self._wait_for_no_startup()

            retried = await main._ensure_rtsp_hls_session("rtsp://camera.local/live")

        self.assertEqual(retried[0], "b" * 24)
        self.assertEqual(calls, 2)
        await self._wait_for_no_startup()

    async def test_startup_timeout_is_shared_and_retryable(self):
        started = asyncio.Event()
        timeout = asyncio.Event()
        calls = 0

        async def start(target_url, custom_ua, compat):
            nonlocal calls
            calls += 1
            if calls == 1:
                started.set()
                await timeout.wait()
                raise HTTPException(status_code=504, detail="startup timeout")
            return "c" * 24, Path("/tmp/timeout-retry-index.m3u8")

        with mock.patch.object(main, "_start_rtsp_hls_session", new=start):
            first = asyncio.create_task(main._ensure_rtsp_hls_session("rtsp://camera.local/live"))
            second = asyncio.create_task(main._ensure_rtsp_hls_session("rtsp://camera.local/live"))
            await started.wait()
            timeout.set()
            results = await asyncio.gather(first, second, return_exceptions=True)
            self.assertTrue(all(isinstance(result, HTTPException) for result in results))
            self.assertTrue(all(result.status_code == 504 for result in results))
            await self._wait_for_no_startup()
            retried = await main._ensure_rtsp_hls_session("rtsp://camera.local/live")

        self.assertEqual(retried[0], "c" * 24)
        self.assertEqual(calls, 2)

    async def test_waiter_cancellation_does_not_cancel_shared_startup(self):
        started = asyncio.Event()
        release = asyncio.Event()
        calls = 0

        async def start(target_url, custom_ua, compat):
            nonlocal calls
            calls += 1
            started.set()
            await release.wait()
            return "d" * 24, Path("/tmp/cancel-index.m3u8")

        with mock.patch.object(main, "_start_rtsp_hls_session", new=start):
            owner = asyncio.create_task(main._ensure_rtsp_hls_session("rtsp://camera.local/live"))
            cancelled_waiter = asyncio.create_task(main._ensure_rtsp_hls_session("rtsp://camera.local/live"))
            surviving_waiter = asyncio.create_task(main._ensure_rtsp_hls_session("rtsp://camera.local/live"))
            await started.wait()
            cancelled_waiter.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await cancelled_waiter
            self.assertFalse(owner.done())
            self.assertFalse(surviving_waiter.done())
            release.set()
            result_owner, result_survivor = await asyncio.gather(owner, surviving_waiter)

        self.assertEqual(result_owner, result_survivor)
        self.assertEqual(calls, 1)
        await self._wait_for_no_startup()

    async def test_ready_session_uses_hot_path_without_new_startup(self):
        session_id = main._rtsp_session_id("rtsp://camera.local/live")
        session_dir = main.RTSP_HLS_ROOT / session_id
        session_dir.mkdir(parents=True)
        playlist = session_dir / "index.m3u8"
        playlist.touch()
        process = _AliveProcess()
        main.RTSP_HLS_SESSIONS[session_id] = {
            "process": process,
            "dir": session_dir,
            "last_access": 0,
            "startup_state": "ready",
        }

        with mock.patch.object(main, "_start_rtsp_hls_session", new=mock.AsyncMock()) as start:
            result = await main._ensure_rtsp_hls_session("rtsp://camera.local/live")

        self.assertEqual(result, (session_id, playlist))
        start.assert_not_awaited()
        self.assertFalse(process.terminated)

    async def test_cleanup_skips_starting_session(self):
        session_id = "e" * 24
        process = _AliveProcess()
        main.RTSP_HLS_SESSIONS[session_id] = {
            "process": process,
            "last_access": 0,
            "startup_state": "starting",
        }
        stop_event = asyncio.Event()
        calls = 0

        async def fake_wait_for(awaitable, timeout):
            nonlocal calls
            if hasattr(awaitable, "close"):
                awaitable.close()
            calls += 1
            if calls > 1:
                stop_event.set()
            raise asyncio.TimeoutError

        with mock.patch.object(main.asyncio, "wait_for", new=fake_wait_for):
            await main._rtsp_hls_cleanup_task(stop_event)

        self.assertIn(session_id, main.RTSP_HLS_SESSIONS)
        self.assertFalse(process.terminated)


class RtspSessionQuotaTest(RtspStartupSingleFlightTest):
    def _register_ready(self, target_url: str) -> tuple[str, Path, _AliveProcess]:
        session_id = main._rtsp_session_id(target_url)
        session_dir = main.RTSP_HLS_ROOT / session_id
        session_dir.mkdir(parents=True, exist_ok=True)
        playlist = session_dir / "index.m3u8"
        playlist.touch()
        process = _AliveProcess()
        main.RTSP_HLS_SESSIONS[session_id] = {
            "process": process,
            "dir": session_dir,
            "last_access": 0,
            "startup_state": "ready",
        }
        return session_id, playlist, process

    async def test_limit_rejects_new_session_before_startup(self):
        calls = []

        async def start(target_url, custom_ua, compat):
            calls.append(target_url)
            session_id, playlist, _process = self._register_ready(target_url)
            return session_id, playlist

        with mock.patch.object(main, "get_effective_settings_sync", return_value=type("Settings", (), {"rtsp_max_sessions": 2})()), \
                mock.patch.object(main, "_start_rtsp_hls_session", new=start):
            await main._ensure_rtsp_hls_session("rtsp://camera-a.local/live")
            await main._ensure_rtsp_hls_session("rtsp://camera-b.local/live")
            with self.assertRaises(HTTPException) as ctx:
                await main._ensure_rtsp_hls_session("rtsp://camera-c.local/live")

        self.assertEqual(ctx.exception.status_code, 503)
        self.assertEqual(ctx.exception.detail, "RTSP session capacity reached")
        self.assertEqual(calls, [
            "rtsp://camera-a.local/live",
            "rtsp://camera-b.local/live",
        ])

    async def test_same_key_waiters_consume_one_slot(self):
        started = asyncio.Event()
        release = asyncio.Event()
        calls = 0

        async def start(target_url, custom_ua, compat):
            nonlocal calls
            calls += 1
            started.set()
            await release.wait()
            session_id, playlist, _process = self._register_ready(target_url)
            return session_id, playlist

        with mock.patch.object(main, "get_effective_settings_sync", return_value=type("Settings", (), {"rtsp_max_sessions": 1})()), \
                mock.patch.object(main, "_start_rtsp_hls_session", new=start):
            waiters = [
                asyncio.create_task(main._ensure_rtsp_hls_session("rtsp://camera.local/live"))
                for _ in range(10)
            ]
            await started.wait()
            await asyncio.sleep(0)
            self.assertEqual(calls, 1)
            self.assertEqual(main._RTSP_RESERVED_SESSIONS, {
                main._rtsp_session_id("rtsp://camera.local/live"),
            })
            release.set()
            results = await asyncio.gather(*waiters)

        self.assertEqual(results, [results[0]] * 10)
        self.assertEqual(calls, 1)
        self.assertEqual(len(main.RTSP_HLS_SESSIONS), 1)
        self.assertFalse(main._RTSP_RESERVED_SESSIONS)

    async def test_different_keys_compete_atomically_for_last_slot(self):
        started = asyncio.Event()
        release = asyncio.Event()
        calls = []

        async def start(target_url, custom_ua, compat):
            calls.append(target_url)
            started.set()
            await release.wait()
            session_id, playlist, _process = self._register_ready(target_url)
            return session_id, playlist

        with mock.patch.object(main, "get_effective_settings_sync", return_value=type("Settings", (), {"rtsp_max_sessions": 1})()), \
                mock.patch.object(main, "_start_rtsp_hls_session", new=start):
            first = asyncio.create_task(main._ensure_rtsp_hls_session("rtsp://camera-a.local/live"))
            second = asyncio.create_task(main._ensure_rtsp_hls_session("rtsp://camera-b.local/live"))
            await started.wait()
            await asyncio.sleep(0)
            release.set()
            results = await asyncio.gather(first, second, return_exceptions=True)

        self.assertEqual(len(calls), 1)
        self.assertEqual(sum(isinstance(result, HTTPException) for result in results), 1)
        rejected = next(result for result in results if isinstance(result, HTTPException))
        self.assertEqual((rejected.status_code, rejected.detail), (503, "RTSP session capacity reached"))
        self.assertEqual(len(main.RTSP_HLS_SESSIONS), 1)

    async def test_startup_failure_releases_slot_for_next_session(self):
        started = asyncio.Event()
        fail = asyncio.Event()
        calls = []

        async def start(target_url, custom_ua, compat):
            calls.append(target_url)
            if len(calls) == 1:
                started.set()
                await fail.wait()
                raise HTTPException(status_code=502, detail="ffmpeg exited")
            session_id, playlist, _process = self._register_ready(target_url)
            return session_id, playlist

        with mock.patch.object(main, "get_effective_settings_sync", return_value=type("Settings", (), {"rtsp_max_sessions": 1})()), \
                mock.patch.object(main, "_start_rtsp_hls_session", new=start):
            first = asyncio.create_task(main._ensure_rtsp_hls_session("rtsp://camera-a.local/live"))
            await started.wait()
            fail.set()
            with self.assertRaises(HTTPException) as ctx:
                await first
            self.assertEqual(ctx.exception.status_code, 502)
            await self._wait_for_no_startup()
            self.assertFalse(main._RTSP_RESERVED_SESSIONS)
            retried = await main._ensure_rtsp_hls_session("rtsp://camera-b.local/live")

        self.assertEqual(retried[0], main._rtsp_session_id("rtsp://camera-b.local/live"))
        self.assertEqual(calls, [
            "rtsp://camera-a.local/live",
            "rtsp://camera-b.local/live",
        ])

    async def test_startup_timeout_releases_slot_for_next_session(self):
        started = asyncio.Event()
        timeout = asyncio.Event()
        calls = []

        async def start(target_url, custom_ua, compat):
            calls.append(target_url)
            if len(calls) == 1:
                started.set()
                await timeout.wait()
                raise HTTPException(status_code=504, detail="startup timeout")
            session_id, playlist, _process = self._register_ready(target_url)
            return session_id, playlist

        with mock.patch.object(main, "get_effective_settings_sync", return_value=type("Settings", (), {"rtsp_max_sessions": 1})()), \
                mock.patch.object(main, "_start_rtsp_hls_session", new=start):
            first = asyncio.create_task(main._ensure_rtsp_hls_session("rtsp://camera-a.local/live"))
            await started.wait()
            timeout.set()
            with self.assertRaises(HTTPException) as ctx:
                await first
            self.assertEqual(ctx.exception.status_code, 504)
            await self._wait_for_no_startup()
            self.assertFalse(main._RTSP_RESERVED_SESSIONS)
            retried = await main._ensure_rtsp_hls_session("rtsp://camera-b.local/live")

        self.assertEqual(retried[0], main._rtsp_session_id("rtsp://camera-b.local/live"))
        self.assertEqual(calls, [
            "rtsp://camera-a.local/live",
            "rtsp://camera-b.local/live",
        ])

    async def test_ready_session_is_not_counted_twice(self):
        target = "rtsp://camera-a.local/live"
        session_id, playlist, process = self._register_ready(target)

        with mock.patch.object(main, "get_effective_settings_sync", return_value=type("Settings", (), {"rtsp_max_sessions": 1})()), \
                mock.patch.object(main, "_start_rtsp_hls_session", new=mock.AsyncMock()) as start:
            result = await main._ensure_rtsp_hls_session(target)

        self.assertEqual(result, (session_id, playlist))
        self.assertFalse(main._RTSP_RESERVED_SESSIONS)
        start.assert_not_awaited()
        self.assertFalse(process.terminated)

    async def test_lowering_limit_does_not_kill_existing_sessions(self):
        processes = []
        for index in range(3):
            _session_id, _playlist, process = self._register_ready(f"rtsp://camera-{index}.local/live")
            processes.append(process)

        with mock.patch.object(main, "get_effective_settings_sync", return_value=type("Settings", (), {"rtsp_max_sessions": 1})()), \
                mock.patch.object(main, "_start_rtsp_hls_session", new=mock.AsyncMock()) as start:
            with self.assertRaises(HTTPException) as ctx:
                await main._ensure_rtsp_hls_session("rtsp://camera-new.local/live")

        self.assertEqual(ctx.exception.status_code, 503)
        self.assertEqual(len(main.RTSP_HLS_SESSIONS), 3)
        self.assertTrue(all(not process.terminated for process in processes))
        start.assert_not_awaited()

    async def test_stopping_session_restores_capacity(self):
        calls = []

        async def start(target_url, custom_ua, compat):
            calls.append(target_url)
            session_id, playlist, _process = self._register_ready(target_url)
            return session_id, playlist

        with mock.patch.object(main, "get_effective_settings_sync", return_value=type("Settings", (), {"rtsp_max_sessions": 1})()), \
                mock.patch.object(main, "_start_rtsp_hls_session", new=start):
            session_id, _playlist = await main._ensure_rtsp_hls_session("rtsp://camera-a.local/live")
            await main._stop_rtsp_session(session_id)
            await main._ensure_rtsp_hls_session("rtsp://camera-b.local/live")

        self.assertEqual(calls, [
            "rtsp://camera-a.local/live",
            "rtsp://camera-b.local/live",
        ])
        self.assertEqual(len(main.RTSP_HLS_SESSIONS), 1)

    async def test_shutdown_stops_all_sessions_and_restores_capacity(self):
        calls = []

        async def start(target_url, custom_ua, compat):
            calls.append(target_url)
            session_id, playlist, _process = self._register_ready(target_url)
            return session_id, playlist

        with mock.patch.object(main, "get_effective_settings_sync", return_value=type("Settings", (), {"rtsp_max_sessions": 1})()), \
                mock.patch.object(main, "_start_rtsp_hls_session", new=start):
            await main._ensure_rtsp_hls_session("rtsp://camera-a.local/live")
            await main._stop_all_rtsp_sessions()
            await main._ensure_rtsp_hls_session("rtsp://camera-b.local/live")

        self.assertEqual(calls, [
            "rtsp://camera-a.local/live",
            "rtsp://camera-b.local/live",
        ])
        self.assertEqual(len(main.RTSP_HLS_SESSIONS), 1)


if __name__ == "__main__":
    unittest.main()
