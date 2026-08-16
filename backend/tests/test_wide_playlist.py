import asyncio
import os
import unittest
from unittest import mock

import httpx
from fastapi import HTTPException

os.environ.setdefault("WAVEFLOW_PROXY_HANDLE_SECRET", "test-handle-secret-32bytes!!!")
os.environ.setdefault("WAVEFLOW_MODE", "nas")
os.environ.setdefault("WAVEFLOW_DB_PATH", ":memory:")

import main
from infrastructure import http_client as media_http
from security.dependencies import MediaAccessContext
from security import proxy_handles, proxy_context


QZNEWS_SAMPLE = (
    "#EXTM3U\n"
    "#EXT-X-VERSION:3\n"
    "#EXT-X-MEDIA-SEQUENCE:9375412\n"
    "#EXT-X-TARGETDURATION:8\n"
    "#EXT-X-INDEPENDENT-SEGMENTS\n"
    "#EXT-X-DISCONTINUITY\n"
    "#EXTINF:8.080,\n"
    "/forbid/c170481d/0.ts\n"
    "#EXTINF:4.000,\n"
    "/forbid/c170481d/1.ts\n"
    "#EXTINF:8.000,\n"
    "/forbid/c170481d/2.ts\n"
)


class ParseLiveSegmentsTest(unittest.TestCase):
    BASE = "https://live4-fuyun.fjtv.net/hb_qztv/sd/live.m3u8"

    def test_qznews_sample(self):
        segs, target, last_seq = main._parse_live_segments(QZNEWS_SAMPLE, self.BASE)
        self.assertEqual(target, 8)
        self.assertEqual(len(segs), 3)
        self.assertEqual(
            segs[0]["url"],
            "https://live4-fuyun.fjtv.net/forbid/c170481d/0.ts",
        )
        self.assertEqual(segs[0]["seq"], 9375412)
        self.assertEqual(segs[1]["seq"], 9375413)
        self.assertEqual(segs[2]["seq"], 9375414)
        # DISCONTINUITY 必须挂在第一段上
        self.assertEqual(
            [t.upper() for t in segs[0]["prefix_tags"]],
            ["#EXT-X-DISCONTINUITY"],
        )
        self.assertEqual(segs[1]["prefix_tags"], [])
        self.assertEqual(segs[2]["prefix_tags"], [])

    def test_program_date_time_attaches_to_following_segment(self):
        text = (
            "#EXTM3U\n"
            "#EXT-X-VERSION:3\n"
            "#EXT-X-TARGETDURATION:6\n"
            "#EXT-X-MEDIA-SEQUENCE:1\n"
            "#EXTINF:6.0,\n"
            "a.ts\n"
            "#EXT-X-PROGRAM-DATE-TIME:2026-01-01T00:00:06.000Z\n"
            "#EXTINF:6.0,\n"
            "b.ts\n"
        )
        segs, target, _ = main._parse_live_segments(text, "https://x.com/live.m3u8")
        self.assertEqual(target, 6)
        self.assertEqual(len(segs), 2)
        self.assertEqual(segs[0]["prefix_tags"], [])
        self.assertEqual(
            segs[1]["prefix_tags"][0].upper(),
            "#EXT-X-PROGRAM-DATE-TIME:2026-01-01T00:00:06.000Z",
        )


class StaleGraceTest(unittest.TestCase):
    def test_grace_scales_with_target_duration(self):
        self.assertEqual(main._wide_stale_grace_for(0), main._WIDE_STALE_GRACE_MIN)
        self.assertEqual(main._wide_stale_grace_for(6), 30)
        self.assertEqual(main._wide_stale_grace_for(8), 32)
        self.assertEqual(main._wide_stale_grace_for(60), main._WIDE_STALE_GRACE_MAX)

    def test_refresh_interval_scales_with_target_duration(self):
        self.assertEqual(main._wide_refresh_interval_for(0), main._WIDE_REFRESH_INTERVAL_MIN)
        self.assertEqual(main._wide_refresh_interval_for(6), 3.0)
        self.assertEqual(main._wide_refresh_interval_for(8), 4.0)
        # Cap at MAX
        self.assertEqual(main._wide_refresh_interval_for(60), main._WIDE_REFRESH_INTERVAL_MAX)


class PlaylistCacheKeyTest(unittest.TestCase):
    def test_thin_cache_key_uses_source_revision_scope(self):
        url_a = "https://cdn.example/live/index.m3u8?token=a"
        url_b = "https://cdn.example/live/index.m3u8?token=b"

        self.assertEqual(main._thin_cache_key(url_a, "src:rev1"), main._thin_cache_key(url_b, "src:rev1"))
        self.assertNotEqual(main._thin_cache_key(url_a, "src:rev1"), main._thin_cache_key(url_a, "src:rev2"))

    def test_wide_cache_key_uses_source_revision_scope(self):
        url_a = "https://cdn.example/live/index.m3u8?token=a"
        url_b = "https://cdn.example/live/index.m3u8?token=b"

        self.assertEqual(
            main._wide_cache_key_for(url_a, "ctx", source_id="src_a", source_revision="rev1"),
            main._wide_cache_key_for(url_b, "ctx", source_id="src_a", source_revision="rev1"),
        )
        self.assertNotEqual(
            main._wide_cache_key_for(url_a, "ctx", source_id="src_a", source_revision="rev1"),
            main._wide_cache_key_for(url_a, "ctx", source_id="src_a", source_revision="rev2"),
        )


class _FakeUpstreamPlaylist:
    """模拟一个会循环复用 0.ts/1.ts/.../4.ts 的 IPTV 上游。"""

    def __init__(self):
        self.calls = 0
        self.seq = 9375590

    async def get(self, *_args, **_kwargs):
        self.calls += 1
        # 入口拉取阶段会重试多次；这里在 retry 中保持 sequence 不变，
        # 模拟上游 5s cache 期内的稳定窗口；refresher 调用才推进。
        seq = self.seq
        text = (
            "#EXTM3U\n"
            "#EXT-X-VERSION:3\n"
            f"#EXT-X-MEDIA-SEQUENCE:{seq}\n"
            "#EXT-X-TARGETDURATION:8\n"
            "#EXTINF:8.0,\n"
            f"/forbid/{seq % 5}.ts\n"
            "#EXTINF:8.0,\n"
            f"/forbid/{(seq + 1) % 5}.ts\n"
            "#EXTINF:8.0,\n"
            f"/forbid/{(seq + 2) % 5}.ts\n"
        )
        # 不在入口阶段推进 sequence，用 (seq, url) 复合 dedupe 即可保证 3 段
        resp = mock.MagicMock()
        resp.text = text
        resp.url = "https://up.example/live.m3u8"
        resp.raise_for_status = mock.MagicMock()
        return resp


class WidePlaylistSegmentInjectionTest(unittest.TestCase):
    """端到端小测：循环文件名 + sequence 推进时，重写后的 chunk URI 必须按 seq 区分。"""

    def test_recycled_filenames_get_distinct_handles(self):
        os.environ["WAVEFLOW_PROXY_HANDLE_SECRET"] = "test-handle-secret-32bytes!!!"
        proxy_handles.clear_handle_cache_for_tests()
        proxy_context.reset_for_tests()

        fake = _FakeUpstreamPlaylist()
        access = MediaAccessContext(source="anonymous", propagated_access_token="")

        async def go():
            # SSRF 校验在 wide playlist 入口对 ``upstream_url`` 解析 IP；测试
            # 用的是不解析的 .example 主机，临时把 main 上绑的 assert_safe_target_url
            # 替换成 noop 即可（主流程的 SSRF 行为有专门的 test_ssrf_guard /
            # test_media_proxy_chunk 覆盖）。
            ssrf_checked = []

            async def _record_ssrf(url, *a, **kw):
                ssrf_checked.append(url)
                return None

            real_ssrf = main.assert_safe_target_url
            real_media_ssrf = media_http.assert_safe_target_url
            main.assert_safe_target_url = _record_ssrf
            media_http.assert_safe_target_url = _record_ssrf
            try:
                with mock.patch.object(main.http_client, "request", side_effect=fake.get):
                    resp = await main.serve_iptv_wide_playlist_by_source(
                        upstream_url="https://up.example/live.m3u8",
                        ctx_id="",
                        src_label="channel:demo",
                        canonical_key="demo",
                        source_id="src_demo",
                        access=access,
                    )
                    body = resp.body.decode("utf-8")
            finally:
                main.assert_safe_target_url = real_ssrf
                media_http.assert_safe_target_url = real_media_ssrf
            return body, ssrf_checked

        body, ssrf_checked = asyncio.run(go())
        self.assertEqual(ssrf_checked[:1], ["https://up.example/live.m3u8"])
        # 解析重写后的 segment 行
        seg_lines = [
            line for line in body.splitlines()
            if line.startswith("/api/media/proxy/chunk/")
        ]
        self.assertEqual(len(seg_lines), 3)
        # 三个 segment URL 应彼此不同（即使上游文件名循环）
        self.assertEqual(len(set(seg_lines)), 3)
        # 而每个 chunk handle 解出来仍然指向上游真实 ts URL（带上 wf_seq 标记）
        for line in seg_lines:
            handle = line.rsplit("/", 1)[-1].split("?", 1)[0]
            payload = proxy_handles.decode_for_kind(handle, "chunk")
            self.assertEqual(payload.src_id, "src_demo")
            self.assertIn(".ts", payload.url)
            self.assertIn("wf_seq=", payload.url)

    def tearDown(self):
        # 清掉这次测试塞进去的 wide cache，避免污染后续测试
        for key in list(main._wide_cache.keys()):
            main._drop_wide_cache(key)
        proxy_handles.clear_handle_cache_for_tests()
        proxy_context.reset_for_tests()


class WidePlaylistLifecycleTest(unittest.IsolatedAsyncioTestCase):
    URL_BASE = "https://up.example/"

    async def asyncSetUp(self):
        await main._shutdown_wide_playlist_state()
        self._old_wide_enabled = main.WIDE_ENABLED
        main.WIDE_ENABLED = True

    async def asyncTearDown(self):
        await main._shutdown_wide_playlist_state()
        main.WIDE_ENABLED = self._old_wide_enabled
        proxy_handles.clear_handle_cache_for_tests()
        proxy_context.reset_for_tests()

    def _url(self, key: str) -> str:
        return f"{self.URL_BASE}{key}.m3u8"

    def _cache_key(self, key: str) -> str:
        return main._wide_cache_key_for(
            self._url(key),
            "",
            source_id=f"src:{key}",
            source_revision="1",
        )

    def _response(self, url: str, sequence: int = 100) -> mock.MagicMock:
        response = mock.MagicMock()
        response.url = url
        response.text = (
            "#EXTM3U\n"
            "#EXT-X-VERSION:3\n"
            f"#EXT-X-MEDIA-SEQUENCE:{sequence}\n"
            "#EXT-X-TARGETDURATION:2\n"
            "#EXTINF:2.0,\n"
            "/segment-a.ts\n"
            "#EXTINF:2.0,\n"
            "/segment-b.ts\n"
        )
        response.raise_for_status = mock.MagicMock()
        return response

    async def _serve(self, key: str):
        return await main.serve_iptv_wide_playlist_by_source(
            upstream_url=self._url(key),
            ctx_id="",
            src_label=f"channel:{key}",
            canonical_key=key,
            source_id=f"src:{key}",
            source_revision="1",
            access=MediaAccessContext(source="anonymous"),
        )

    async def _noop_ssrf(self, *_args, **_kwargs):
        return None

    async def test_same_key_cold_start_is_single_flight_and_single_refresher(self):
        entered = asyncio.Event()
        release = asyncio.Event()
        refresher_release = asyncio.Event()
        calls = 0

        async def fake_get(_method, url, **_kwargs):
            nonlocal calls
            calls += 1
            if calls == 1:
                entered.set()
                await release.wait()
            return self._response(url)

        async def hold_refresher(*_args):
            await refresher_release.wait()

        with mock.patch.object(main, "assert_safe_target_url", new=self._noop_ssrf), \
             mock.patch.object(media_http, "assert_safe_target_url", new=self._noop_ssrf), \
             mock.patch.object(main.http_client, "request", side_effect=fake_get), \
             mock.patch.object(main, "_run_wide_refresher", new=hold_refresher):
            first = asyncio.create_task(self._serve("same"))
            await entered.wait()
            second = asyncio.create_task(self._serve("same"))
            await asyncio.sleep(0)
            self.assertEqual(calls, 1)
            release.set()
            responses = await asyncio.gather(first, second)

        self.assertEqual(len(responses), 2)
        self.assertEqual(calls, 4)
        cache_key = self._cache_key("same")
        self.assertIn(cache_key, main._wide_cache)
        self.assertIsNotNone(main._wide_refresher_tasks.get(cache_key))
        self.assertEqual(
            len([key for key in main._wide_refresher_tasks if key == cache_key]),
            1,
        )
        body = responses[0].body.decode("utf-8")
        self.assertEqual(
            len([line for line in body.splitlines() if "/api/media/proxy/chunk/" in line]),
            2,
        )
        refresher_release.set()

    async def test_different_keys_initialize_in_parallel(self):
        entered = {key: asyncio.Event() for key in ("a", "b")}
        release = asyncio.Event()
        calls: dict[str, int] = {"a": 0, "b": 0}
        active = 0
        maximum_active = 0
        refresher_release = asyncio.Event()

        async def fake_get(_method, url, **_kwargs):
            nonlocal active, maximum_active
            key = "a" if "/a.m3u8" in url else "b"
            calls[key] += 1
            if calls[key] == 1:
                active += 1
                maximum_active = max(maximum_active, active)
                entered[key].set()
                await release.wait()
                active -= 1
            return self._response(url, sequence=100 if key == "a" else 200)

        async def hold_refresher(*_args):
            await refresher_release.wait()

        with mock.patch.object(main, "assert_safe_target_url", new=self._noop_ssrf), \
             mock.patch.object(media_http, "assert_safe_target_url", new=self._noop_ssrf), \
             mock.patch.object(main.http_client, "request", side_effect=fake_get), \
             mock.patch.object(main, "_run_wide_refresher", new=hold_refresher):
            first = asyncio.create_task(self._serve("a"))
            second = asyncio.create_task(self._serve("b"))
            await entered["a"].wait()
            await entered["b"].wait()
            self.assertEqual(maximum_active, 2)
            release.set()
            await asyncio.gather(first, second)

        self.assertEqual(calls, {"a": 4, "b": 4})
        self.assertEqual(len(main._wide_refresher_tasks), 2)
        refresher_release.set()

    async def test_waiter_cancellation_does_not_cancel_initializer(self):
        entered = asyncio.Event()
        release = asyncio.Event()
        refresher_release = asyncio.Event()
        calls = 0

        async def fake_get(_method, url, **_kwargs):
            nonlocal calls
            calls += 1
            if calls == 1:
                entered.set()
                await release.wait()
            return self._response(url)

        async def hold_refresher(*_args):
            await refresher_release.wait()

        with mock.patch.object(main, "assert_safe_target_url", new=self._noop_ssrf), \
             mock.patch.object(media_http, "assert_safe_target_url", new=self._noop_ssrf), \
             mock.patch.object(main.http_client, "request", side_effect=fake_get), \
             mock.patch.object(main, "_run_wide_refresher", new=hold_refresher):
            owner = asyncio.create_task(self._serve("cancel-waiter"))
            await entered.wait()
            waiter = asyncio.create_task(self._serve("cancel-waiter"))
            await asyncio.sleep(0)
            waiter.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await waiter
            self.assertFalse(owner.done())
            release.set()
            await owner

        self.assertEqual(calls, 4)
        self.assertIn(self._cache_key("cancel-waiter"), main._wide_cache)
        refresher_release.set()

    async def test_initializer_cancellation_leaves_no_cache_or_refresher(self):
        entered = asyncio.Event()

        async def blocked_get(_method, _url, **_kwargs):
            entered.set()
            await asyncio.Event().wait()

        with mock.patch.object(main, "assert_safe_target_url", new=self._noop_ssrf), \
             mock.patch.object(media_http, "assert_safe_target_url", new=self._noop_ssrf), \
             mock.patch.object(main.http_client, "request", side_effect=blocked_get):
            owner = asyncio.create_task(self._serve("cancel-owner"))
            await entered.wait()
            owner.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await owner

        self.assertEqual(main._wide_cache, {})
        self.assertEqual(main._wide_refresher_tasks, {})

    async def test_eviction_cancels_inflight_initializer(self):
        entered = asyncio.Event()

        async def blocked_get(_method, _url, **_kwargs):
            entered.set()
            await asyncio.Event().wait()

        with mock.patch.object(main, "assert_safe_target_url", new=self._noop_ssrf), \
             mock.patch.object(media_http, "assert_safe_target_url", new=self._noop_ssrf), \
             mock.patch.object(main.http_client, "request", side_effect=blocked_get):
            owner = asyncio.create_task(self._serve("evict-owner"))
            await entered.wait()
            self.assertTrue(main.release_iptv_wide_playlist_by_key(self._cache_key("evict-owner")))
            with self.assertRaises(asyncio.CancelledError):
                await owner

        self.assertEqual(main._wide_cache, {})
        self.assertEqual(main._wide_initialization_tasks, {})
        self.assertEqual(main._wide_refresher_tasks, {})

    async def test_shutdown_cancels_inflight_initializer_before_clearing_state(self):
        entered = asyncio.Event()

        async def blocked_get(_method, _url, **_kwargs):
            entered.set()
            await asyncio.Event().wait()

        with mock.patch.object(main, "assert_safe_target_url", new=self._noop_ssrf), \
             mock.patch.object(media_http, "assert_safe_target_url", new=self._noop_ssrf), \
             mock.patch.object(main.http_client, "request", side_effect=blocked_get):
            owner = asyncio.create_task(self._serve("shutdown-owner"))
            await entered.wait()
            self.assertTrue(main._wide_initialization_tasks)
            await main._shutdown_wide_playlist_state()
            self.assertTrue(owner.cancelled())

        self.assertEqual(main._wide_cache, {})
        self.assertEqual(main._wide_refresher_tasks, {})
        self.assertEqual(main._wide_initialization_tasks, {})

    async def test_initializer_failure_releases_key_for_retry(self):
        calls = 0
        should_fail = True
        refresher_release = asyncio.Event()

        async def fake_get(_method, url, **_kwargs):
            nonlocal calls
            calls += 1
            if should_fail:
                raise httpx.ConnectError("fixture failure", request=httpx.Request("GET", url))
            return self._response(url)

        async def hold_refresher(*_args):
            await refresher_release.wait()

        with mock.patch.object(main, "assert_safe_target_url", new=self._noop_ssrf), \
             mock.patch.object(media_http, "assert_safe_target_url", new=self._noop_ssrf), \
             mock.patch.object(main.http_client, "request", side_effect=fake_get), \
             mock.patch.object(main, "_run_wide_refresher", new=hold_refresher):
            with self.assertRaises(HTTPException) as failure:
                await self._serve("retry")
            self.assertEqual(failure.exception.status_code, 502)
            self.assertEqual(main._wide_cache, {})
            self.assertEqual(main._wide_refresher_tasks, {})

            should_fail = False
            await self._serve("retry")

        self.assertEqual(calls, 9)
        self.assertIn(self._cache_key("retry"), main._wide_refresher_tasks)
        refresher_release.set()

    async def test_refresher_failure_cleans_tracking_and_cache(self):
        crashed = asyncio.Event()

        async def failing_refresher(*_args):
            crashed.set()
            raise RuntimeError("fixture refresher failure")

        async def fake_get(_method, url, **_kwargs):
            return self._response(url)

        with mock.patch.object(main, "assert_safe_target_url", new=self._noop_ssrf), \
             mock.patch.object(media_http, "assert_safe_target_url", new=self._noop_ssrf), \
             mock.patch.object(main.http_client, "request", side_effect=fake_get), \
             mock.patch.object(main, "_run_wide_refresher", new=failing_refresher):
            await self._serve("refresher-failure")
            await crashed.wait()
            await asyncio.sleep(0)

        cache_key = self._cache_key("refresher-failure")
        self.assertNotIn(cache_key, main._wide_cache)
        self.assertNotIn(cache_key, main._wide_refresher_tasks)

    async def test_eviction_and_shutdown_reclaim_refresher_tasks(self):
        refresher_release = asyncio.Event()

        async def hold_refresher(*_args):
            await refresher_release.wait()

        async def fake_get(_method, url, **_kwargs):
            return self._response(url)

        with mock.patch.object(main, "assert_safe_target_url", new=self._noop_ssrf), \
             mock.patch.object(media_http, "assert_safe_target_url", new=self._noop_ssrf), \
             mock.patch.object(main.http_client, "request", side_effect=fake_get), \
             mock.patch.object(main, "_run_wide_refresher", new=hold_refresher):
            await self._serve("evict")
            await self._serve("shutdown")
            evict_key = self._cache_key("evict")
            shutdown_key = self._cache_key("shutdown")
            self.assertEqual(len(main._wide_refresher_tasks), 2)
            self.assertTrue(main.release_iptv_wide_playlist_by_key(evict_key))
            self.assertNotIn(evict_key, main._wide_cache)
            await asyncio.sleep(0)
            self.assertNotIn(evict_key, main._wide_refresher_tasks)
            await main._shutdown_wide_playlist_state()

        self.assertEqual(main._wide_cache, {})
        self.assertEqual(main._wide_refresher_tasks, {})
        self.assertNotIn(shutdown_key, main._wide_cache)

    async def test_stale_refresher_cancellation_cannot_drop_new_cache(self):
        refresher_started = asyncio.Event()
        refresher_release = asyncio.Event()

        async def hold_refresher(*_args):
            refresher_started.set()
            await refresher_release.wait()

        async def fake_get(_method, url, **_kwargs):
            return self._response(url)

        with mock.patch.object(main, "assert_safe_target_url", new=self._noop_ssrf), \
             mock.patch.object(media_http, "assert_safe_target_url", new=self._noop_ssrf), \
             mock.patch.object(main.http_client, "request", side_effect=fake_get), \
             mock.patch.object(main, "_run_wide_refresher", new=hold_refresher):
            await self._serve("recycle")
            await refresher_started.wait()
            cache_key = self._cache_key("recycle")
            old_task = main._wide_refresher_tasks[cache_key]
            self.assertTrue(main.release_iptv_wide_playlist_by_key(cache_key))

            # The old task is cancelled but has not yet received cancellation.
            # Reinitialization must publish a new owner before that stale task
            # gets a chance to run its cancellation handler.
            await self._serve("recycle")
            new_task = main._wide_refresher_tasks[cache_key]
            self.assertIsNot(old_task, new_task)
            await asyncio.sleep(0)

            self.assertIn(cache_key, main._wide_cache)
            self.assertIs(main._wide_refresher_tasks.get(cache_key), new_task)

        refresher_release.set()


if __name__ == "__main__":
    unittest.main()
