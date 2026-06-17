import asyncio
import os
import unittest
from unittest import mock

os.environ.setdefault("WAVEFLOW_PROXY_HANDLE_SECRET", "test-handle-secret-32bytes!!!")
os.environ.setdefault("WAVEFLOW_MODE", "nas")
os.environ.setdefault("WAVEFLOW_DB_PATH", ":memory:")

import main
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
            async def _noop(*a, **kw):
                return None

            real_ssrf = main.assert_safe_target_url
            main.assert_safe_target_url = _noop
            try:
                with mock.patch.object(main.http_client, "get", side_effect=fake.get):
                    resp = await main.serve_iptv_wide_playlist_by_source(
                        upstream_url="https://up.example/live.m3u8",
                        ctx_id="",
                        src_label="channel:demo",
                        canonical_key="demo",
                        access=access,
                    )
                    body = resp.body.decode("utf-8")
            finally:
                main.assert_safe_target_url = real_ssrf
            return body

        body = asyncio.run(go())
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
            self.assertIn(".ts", payload.url)
            self.assertIn("wf_seq=", payload.url)

    def tearDown(self):
        # 清掉这次测试塞进去的 wide cache，避免污染后续测试
        for key in list(main._wide_cache.keys()):
            main._drop_wide_cache(key)
        proxy_handles.clear_handle_cache_for_tests()
        proxy_context.reset_for_tests()


if __name__ == "__main__":
    unittest.main()
