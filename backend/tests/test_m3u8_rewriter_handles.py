import os
import sys
import unittest


os.environ["WAVEFLOW_PROXY_HANDLE_SECRET"] = "test-m3u8-handle-secret-32bytes!!!"
os.environ.setdefault("WAVEFLOW_MODE", "nas")
os.environ["WAVEFLOW_DB_PATH"] = ":memory:"
for mod in list(sys.modules):
    if mod in ("security.secrets", "security.proxy_handles", "core.m3u8_rewriter"):
        del sys.modules[mod]

from core.m3u8_rewriter import RewriteContext, rewrite_m3u8
from security.proxy_handles import clear_handle_cache_for_tests


class M3u8RewriterHandleTest(unittest.TestCase):
    def setUp(self):
        clear_handle_cache_for_tests()

    def test_same_upstream_uris_rewrite_to_stable_proxy_handles(self):
        text = """#EXTM3U
#EXT-X-VERSION:7
#EXT-X-MEDIA:TYPE=AUDIO,GROUP-ID="aud",URI="audio/main.m3u8"
#EXT-X-KEY:METHOD=AES-128,URI="keys/live.key?token=1"
#EXT-X-MAP:URI="../init.mp4"
#EXT-X-PART:DURATION=0.333,URI="parts/part-1.m4s"
#EXTINF:6,
seg-100.ts?edge=1
"""
        ctx = RewriteContext(
            base_url="https://cdn.example.com/live/variant/index.m3u8",
            src_id="channel:test",
            src_label="channel:test",
            ctx_id="ctx1",
        )

        first = rewrite_m3u8(text, ctx)
        second = rewrite_m3u8(text, ctx)

        self.assertEqual(first, second)
        self.assertIn("/api/media/proxy/playlist/", first)
        self.assertIn("/api/media/proxy/chunk/", first)
        self.assertNotIn("https://cdn.example.com", first)


if __name__ == "__main__":
    unittest.main()
