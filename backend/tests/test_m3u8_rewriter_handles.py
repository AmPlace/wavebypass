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
from security.proxy_handles import clear_handle_cache_for_tests, decode_for_kind


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

    def _decode_rewritten_uri(self, uri: str, kind: str):
        prefix = f"/api/media/proxy/{kind}/"
        self.assertTrue(uri.startswith(prefix), uri)
        handle = uri[len(prefix):].split("?access_token=", 1)[0]
        return decode_for_kind(handle, kind)

    def test_extensionless_master_variant_uses_playlist_handle(self):
        text = "#EXTM3U\n#EXT-X-STREAM-INF:BANDWIDTH=800000\nvariant/live?token=one\n"
        rewritten = rewrite_m3u8(text, RewriteContext(
            base_url="https://cdn.example.com/master/index.m3u8",
            src_id="channel:test",
        ))

        uri = rewritten.splitlines()[-1]
        payload = self._decode_rewritten_uri(uri, "playlist")
        self.assertEqual(payload.url, "https://cdn.example.com/master/variant/live?token=one")

    def test_extensionless_media_uri_defaults_to_signed_chunk(self):
        text = "#EXTM3U\n#EXT-X-TARGETDURATION:4\n#EXTINF:4,\nsegments/current?token=one\n"
        rewritten = rewrite_m3u8(text, RewriteContext(
            base_url="https://cdn.example.com/live/index.m3u8",
            src_id="channel:test",
        ))

        uri = rewritten.splitlines()[-1]
        payload = self._decode_rewritten_uri(uri, "chunk")
        self.assertEqual(payload.url, "https://cdn.example.com/live/segments/current?token=one&wf_seq=0")
        self.assertNotIn("https://cdn.example.com", rewritten)

    def test_query_only_variant_uri_uses_playlist_handle(self):
        text = "#EXTM3U\n#EXT-X-STREAM-INF:BANDWIDTH=800000\n?variant=audio\n"
        rewritten = rewrite_m3u8(text, RewriteContext(
            base_url="https://cdn.example.com/live/master",
            src_id="channel:test",
        ))

        payload = self._decode_rewritten_uri(rewritten.splitlines()[-1], "playlist")
        self.assertEqual(payload.url, "https://cdn.example.com/live/master?variant=audio")

    def test_uri_attribute_tags_use_tag_semantics_without_extensions(self):
        text = """#EXTM3U
#EXT-X-MEDIA:TYPE=AUDIO,GROUP-ID="aud",URI="audio/rendition?token=1"
#EXT-X-I-FRAME-STREAM-INF:BANDWIDTH=100000,URI="iframe/rendition"
#EXT-X-RENDITION-REPORT:URI="../other/rendition",LAST-MSN=10
#EXT-X-SESSION-KEY:METHOD=AES-128,URI="keys/session"
#EXT-X-KEY:METHOD=AES-128,URI="keys/current"
#EXT-X-MAP:URI="init/current"
#EXT-X-PRELOAD-HINT:TYPE=PART,URI="parts/next"
"""
        rewritten = rewrite_m3u8(text, RewriteContext(
            base_url="https://cdn.example.com/live/index.m3u8",
            src_id="channel:test",
        ))

        lines = rewritten.splitlines()
        for index in (1, 2, 3):
            self.assertIn("/api/media/proxy/playlist/", lines[index])
        for index in (4, 5, 6, 7):
            self.assertIn("/api/media/proxy/chunk/", lines[index])
        self.assertNotIn("https://cdn.example.com", rewritten)

    def test_session_data_and_special_schemes_remain_unmodified(self):
        text = """#EXTM3U
#EXT-X-SESSION-DATA:DATA-ID="com.example",URI="https://metadata.example/info.json"
#EXT-X-SESSION-KEY:METHOD=SAMPLE-AES,KEYFORMAT="com.apple.streamingkeydelivery",URI="skd://asset-id"
#EXT-X-KEY:METHOD=AES-128,URI="data:text/plain;base64,AAAA"
"""
        rewritten = rewrite_m3u8(text, RewriteContext(
            base_url="https://cdn.example.com/live/index.m3u8",
            src_id="channel:test",
        ))

        self.assertIn('URI="https://metadata.example/info.json"', rewritten)
        self.assertIn('URI="skd://asset-id"', rewritten)
        self.assertIn('URI="data:text/plain;base64,AAAA"', rewritten)

    def test_utf8_bom_header_is_not_rewritten_as_media_uri(self):
        rewritten = rewrite_m3u8(
            "\ufeff#EXTM3U\r\n#EXTINF:4,\r\nsegment.vtt\r\n",
            RewriteContext(
                base_url="https://cdn.example.com/live/index.m3u8",
                src_id="channel:test",
            ),
        )

        self.assertTrue(rewritten.startswith("\ufeff#EXTM3U\n"))
        self.assertIn("/api/media/proxy/chunk/", rewritten)


if __name__ == "__main__":
    unittest.main()
