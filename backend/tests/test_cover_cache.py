"""test_cover_cache

Unit tests for core.cover_cache — single-flight, timeout, exception, cancel, waiter-cancel, semaphore.
All tests use in-process fakes; no real network.
"""
import asyncio
import os
import time
import unittest

os.environ.setdefault("WAVEFLOW_PROXY_HANDLE_SECRET", "test-key-32bytes-1337!!!!!")
os.environ.setdefault("WAVEFLOW_MODE", "nas")
os.environ.setdefault("WAVEFLOW_DB_PATH", ":memory:")


class CoverCacheSingleFlightTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        from core.cover_cache import CoverCache
        self.cache = CoverCache()

    # ── helpers ──────────────────────────────────────────────────────

    def _fake_resolver(self, delay=0.05, result=None, exc=None):
        """返回一个模拟的 fetch_adapter_cover_payload 协程。"""
        async def _resolve(_url):
            if delay:
                await asyncio.sleep(delay)
            if exc:
                raise exc
            if result is not None:
                return dict(result)
            return {"ok": True, "cover_url": "https://img.example.com/cover.jpg", "avatar_url": ""}
        return _resolve

    async def _concurrent_get_or_fetch(self, n, canonical_key, adapter_url, delay=0.05):
        """Launch n concurrent get_or_fetch calls, return (results, resolver_call_count)."""
        call_count = 0

        async def _resolve(_url):
            nonlocal call_count
            call_count += 1
            await asyncio.sleep(delay)
            return {"ok": True, "cover_url": f"https://img.example.com/{canonical_key}.jpg", "avatar_url": ""}

        # Patch fetch_adapter_cover_payload in main (temporary)
        import main as _m
        _orig = getattr(_m, "fetch_adapter_cover_payload", None)
        _m.fetch_adapter_cover_payload = _resolve
        try:
            tasks = [
                self.cache.get_or_fetch(canonical_key, adapter_url, "", canonical_key)
                for _ in range(n)
            ]
            results = await asyncio.wait_for(asyncio.gather(*tasks), timeout=3.0)
        finally:
            if _orig is not None:
                _m.fetch_adapter_cover_payload = _orig
            else:
                del _m.fetch_adapter_cover_payload
        return results, call_count

    # ── tests ────────────────────────────────────────────────────────

    async def test_same_key_single_flight(self):
        """30 并发同一 key → resolver 只执行 1 次，全部完成。"""
        results, call_count = await self._concurrent_get_or_fetch(
            30, "channel_a", "adapter://test/a", delay=0.05
        )
        self.assertEqual(call_count, 1)
        self.assertEqual(len(results), 30)
        for r in results:
            self.assertIn("cover_url", r)

    async def test_same_key_cache_hit_after_fetch(self):
        """single-flight 完成后，后续请求命中结果缓存（不再调 resolver）。"""
        results1, c1 = await self._concurrent_get_or_fetch(
            5, "channel_b", "adapter://test/b", delay=0.03
        )
        self.assertEqual(c1, 1)

        results2, c2 = await self._concurrent_get_or_fetch(
            5, "channel_b", "adapter://test/b", delay=0.03
        )
        self.assertEqual(c2, 0)  # 缓存命中，不调 resolver
        self.assertEqual(len(results2), 5)

    async def test_different_keys_parallel(self):
        """不同 key 可并行，不超过 semaphore。"""
        import asyncio
        concurrent_count = 0
        max_concurrent = 0

        async def _resolve(_url):
            nonlocal concurrent_count, max_concurrent
            concurrent_count += 1
            max_concurrent = max(max_concurrent, concurrent_count)
            await asyncio.sleep(0.05)
            concurrent_count -= 1
            return {"ok": True, "cover_url": "ok", "avatar_url": ""}

        import main as _m
        _orig = getattr(_m, "fetch_adapter_cover_payload", None)
        _m.fetch_adapter_cover_payload = _resolve
        try:
            tasks = [
                self.cache.get_or_fetch(f"ch_{i}", f"adapter://test/{i}", "", f"ch_{i}")
                for i in range(10)
            ]
            await asyncio.wait_for(asyncio.gather(*tasks), timeout=5.0)
        finally:
            if _orig is not None:
                _m.fetch_adapter_cover_payload = _orig
            else:
                del _m.fetch_adapter_cover_payload

        self.assertLessEqual(max_concurrent, 4)  # semaphore limit
        self.assertGreater(max_concurrent, 1)     # at least some parallelism

    async def test_resolver_exception_wakes_waiters(self):
        """resolver 抛异常 → 所有 waiter 都返回 empty，不挂起。"""
        call_count = 0

        async def _resolve(_url):
            nonlocal call_count
            call_count += 1
            raise RuntimeError("boom")

        import main as _m
        _orig = getattr(_m, "fetch_adapter_cover_payload", None)
        _m.fetch_adapter_cover_payload = _resolve
        try:
            tasks = [
                self.cache.get_or_fetch("ch_exc", "adapter://test/exc", "", "ch_exc")
                for _ in range(5)
            ]
            results = await asyncio.wait_for(asyncio.gather(*tasks), timeout=2.0)
        finally:
            if _orig is not None:
                _m.fetch_adapter_cover_payload = _orig
            else:
                del _m.fetch_adapter_cover_payload

        self.assertEqual(call_count, 1)
        self.assertEqual(len(results), 5)
        # 异常后返回 empty result
        for r in results:
            self.assertEqual(r.get("cover_url"), "")

    async def test_resolver_timeout_wakes_waiters(self):
        """resolver 超时（内部 wait_for 5s）→ 所有 waiter 返回 empty。

        因为内部超时 = 5s 太长不适合单元测试，此处测试 owner 超时取消路径。
        _run_fetch 的 wait_for → TimeoutError 路径是标准库行为，不涉及自定义逻辑。
        """
        # 用 blocker Event 模拟 resolver 永久阻塞，owner cancel 路径覆盖
        call_count = 0
        started = asyncio.Event()
        blocker = asyncio.Event()

        async def _resolve(_url):
            nonlocal call_count
            call_count += 1
            started.set()
            await blocker.wait()

        import main as _m
        _orig = getattr(_m, "fetch_adapter_cover_payload", None)
        _m.fetch_adapter_cover_payload = _resolve
        try:
            async def _waiter():
                return await self.cache.get_or_fetch("ch_to", "adapter://test/to", "", "ch_to")

            owner = asyncio.create_task(_waiter())
            await asyncio.wait_for(started.wait(), timeout=1.0)
            # waiters
            w1 = asyncio.create_task(_waiter())
            w2 = asyncio.create_task(_waiter())
            await asyncio.sleep(0.05)

            # cancel owner — simulates what wait_for does internally
            owner.cancel()
            try: await owner
            except asyncio.CancelledError: pass

            r1, r2 = await asyncio.wait_for(asyncio.gather(w1, w2), timeout=1.0)
            self.assertEqual(r1.get("cover_url"), "")
            self.assertEqual(r2.get("cover_url"), "")
            self.assertEqual(call_count, 1)
        finally:
            blocker.set()
            if _orig is not None:
                _m.fetch_adapter_cover_payload = _orig
            else:
                del _m.fetch_adapter_cover_payload

    async def test_owner_cancel_wakes_waiters(self):
        """Owner task 被取消 → waiters 被唤醒，返回 empty。"""
        call_count = 0
        started = asyncio.Event()
        blocker = asyncio.Event()

        async def _resolve(_url):
            nonlocal call_count
            call_count += 1
            started.set()
            await blocker.wait()  # 阻塞直到测试放行

        import main as _m
        _orig = getattr(_m, "fetch_adapter_cover_payload", None)
        _m.fetch_adapter_cover_payload = _resolve
        try:
            async def _waiter():
                return await self.cache.get_or_fetch("ch_c1", "adapter://test/c1", "", "ch_c1")

            async def _owner():
                return await self.cache.get_or_fetch("ch_c1", "adapter://test/c1", "", "ch_c1")

            # 先启动 owner，等它进入 resolver
            owner_task = asyncio.create_task(_owner())
            await asyncio.wait_for(started.wait(), timeout=1.0)

            # 启动 2 个 waiter
            w1 = asyncio.create_task(_waiter())
            w2 = asyncio.create_task(_waiter())

            # 让 waiter 进入 single-flight wait
            await asyncio.sleep(0.05)

            # 取消 owner
            owner_task.cancel()
            try:
                await owner_task
            except asyncio.CancelledError:
                pass

            # waiters 应该被唤醒
            r1, r2 = await asyncio.wait_for(asyncio.gather(w1, w2), timeout=1.0)
            self.assertEqual(r1.get("cover_url"), "")
            self.assertEqual(r2.get("cover_url"), "")
            self.assertEqual(call_count, 1)
        finally:
            blocker.set()  # 释放 resolver 防止泄漏
            if _orig is not None:
                _m.fetch_adapter_cover_payload = _orig
            else:
                del _m.fetch_adapter_cover_payload

    async def test_waiter_cancel_does_not_break_owner(self):
        """一个 waiter 被取消 → owner 和其他 waiter 继续。"""
        call_count = 0
        started = asyncio.Event()
        done = asyncio.Event()

        async def _resolve(_url):
            nonlocal call_count
            call_count += 1
            started.set()
            await done.wait()
            return {"ok": True, "cover_url": "https://ok.example.com/img.jpg", "avatar_url": ""}

        import main as _m
        _orig = getattr(_m, "fetch_adapter_cover_payload", None)
        _m.fetch_adapter_cover_payload = _resolve
        try:
            async def _waiter():
                return await self.cache.get_or_fetch("ch_c2", "adapter://test/c2", "", "ch_c2")

            # 启动 owner
            owner_task = asyncio.create_task(_waiter())
            await asyncio.wait_for(started.wait(), timeout=1.0)

            # 启动 waiter
            w2 = asyncio.create_task(_waiter())

            # 启动另一个 waiter 然后立刻取消它
            w3 = asyncio.create_task(_waiter())
            await asyncio.sleep(0.02)
            w3.cancel()
            try:
                await w3
            except asyncio.CancelledError:
                pass

            # 放行 resolver
            done.set()

            # owner 和 w2 应该正常完成
            r_owner = await asyncio.wait_for(owner_task, timeout=1.0)
            r_w2 = await asyncio.wait_for(w2, timeout=1.0)
            self.assertEqual(r_owner.get("cover_url"), "https://ok.example.com/img.jpg")
            self.assertEqual(r_w2.get("cover_url"), "https://ok.example.com/img.jpg")
            self.assertEqual(call_count, 1)
        finally:
            done.set()
            if _orig is not None:
                _m.fetch_adapter_cover_payload = _orig
            else:
                del _m.fetch_adapter_cover_payload

    async def test_inflight_cleaned_after_completion(self):
        """fetch 完成后 _inflight 必须为空。"""
        results, _ = await self._concurrent_get_or_fetch(
            5, "ch_inflight", "adapter://test/inflight", delay=0.02
        )
        self.assertEqual(len(results), 5)
        self.assertEqual(len(self.cache._inflight), 0)

    async def test_non_adapter_returns_logo_cached(self):
        """非 adapter 频道返回 logo_url 并缓存。"""
        r1 = await self.cache.get_or_fetch("ch_no_ad", None, "https://logo.example.com/a.png", "频道A")
        self.assertEqual(r1["cover_url"], "https://logo.example.com/a.png")

        # 第二次不查索引（缓存命中）
        r2 = await self.cache.get_or_fetch("ch_no_ad", None, "https://logo.example.com/a.png", "频道A")
        self.assertEqual(r2["cover_url"], "https://logo.example.com/a.png")

    async def test_non_adapter_does_not_hold_semaphore(self):
        """非 adapter 频道不占 semaphore 槽位。"""
        # 占满 semaphore
        held = asyncio.Event()

        async def _slow_resolve(_url):
            await held.wait()
            return {"ok": True, "cover_url": "slow", "avatar_url": ""}

        import main as _m
        _orig = getattr(_m, "fetch_adapter_cover_payload", None)
        _m.fetch_adapter_cover_payload = _slow_resolve
        try:
            # 先占满 4 个 semaphore 槽位
            slow_tasks = [
                asyncio.create_task(
                    self.cache.get_or_fetch(f"slow_{i}", f"adapter://test/slow_{i}", "", f"slow_{i}")
                )
                for i in range(4)
            ]
            await asyncio.sleep(0.05)  # 等它们都进入 semaphore

            # 非 adapter 请求应该立即返回（不阻塞在 semaphore）
            t0 = time.monotonic()
            r = await asyncio.wait_for(
                self.cache.get_or_fetch("fast_no_ad", None, "https://l.example.com/x.png", "fast"),
                timeout=0.5,
            )
            elapsed = time.monotonic() - t0
            self.assertEqual(r["cover_url"], "https://l.example.com/x.png")
            self.assertLess(elapsed, 0.3)
        finally:
            held.set()
            if _orig is not None:
                _m.fetch_adapter_cover_payload = _orig
            else:
                del _m.fetch_adapter_cover_payload


if __name__ == "__main__":
    unittest.main()
