import unittest
import asyncio
import sys
import time
import types

from security.dependencies import MediaAccessContext
from security.proxy_handles import issue_handle
from routers import media_proxy
from routers.media_proxy import _playback_source_supported


class _FakeMain:
    @staticmethod
    def _source_type(source):
        return source.get("source_type") or "hls"


class MediaProxyLogicTest(unittest.TestCase):
    def test_playback_keeps_untested_sources(self):
        source = {
            "url": "https://example.com/live.m3u8",
            "enabled": True,
            "is_working": 0,
            "probe_status": "untested",
            "source_type": "hls",
        }

        self.assertTrue(_playback_source_supported(_FakeMain, source))

    def test_playback_hard_excludes_disabled_sources(self):
        source = {
            "url": "https://example.com/live.m3u8",
            "enabled": False,
            "is_working": 1,
            "probe_status": "online",
            "source_type": "hls",
        }

        self.assertFalse(_playback_source_supported(_FakeMain, source))

    def test_myradio_stream_uses_signed_stream_redirect(self):
        fake_main = types.SimpleNamespace(
            CURRENT_STREAMS={},
            STATION_FETCHER_MAP={},
            DIRECT_STREAM_STATIONS=set(),
            MYRADIO_CACHE={
                "mr_A6002": {
                    "url": "http://media.example.test/TY.AM1062",
                    "ts": time.time(),
                },
            },
            MYRADIO_CACHE_TTL=3600,
            time=time,
            _is_geo_blocked=lambda station_id, request: False,
            refresh_station_stream_url=lambda station_id: asyncio.sleep(0, result=""),
        )
        old_main = sys.modules.get("main")
        old_validate = media_proxy._validate_handle_url_or_403

        async def noop_validate(*args, **kwargs):
            return None

        try:
            sys.modules["main"] = fake_main
            media_proxy._validate_handle_url_or_403 = noop_validate
            response = asyncio.run(media_proxy.media_channel_stream(
                "mr_A6002",
                types.SimpleNamespace(headers={}),
                MediaAccessContext(source="anonymous"),
            ))
        finally:
            media_proxy._validate_handle_url_or_403 = old_validate
            if old_main is not None:
                sys.modules["main"] = old_main
            else:
                sys.modules.pop("main", None)

        self.assertEqual(response.status_code, 307)
        self.assertIn("/api/media/proxy/stream/", response.headers["location"])

    def test_myradio_playlist_redirects_to_stream_endpoint(self):
        fake_main = types.SimpleNamespace(
            CURRENT_STREAMS={},
            STATION_FETCHER_MAP={},
            DIRECT_STREAM_STATIONS=set(),
            MYRADIO_CACHE={
                "mr_A6002": {
                    "url": "http://media.example.test/TY.AM1062",
                    "ts": time.time(),
                },
            },
            MYRADIO_CACHE_TTL=3600,
            time=time,
            _is_geo_blocked=lambda station_id, request: False,
            refresh_station_stream_url=lambda station_id: asyncio.sleep(0, result=""),
        )
        old_main = sys.modules.get("main")
        try:
            sys.modules["main"] = fake_main
            response = asyncio.run(media_proxy._serve_radio_station_playlist(
                "mr_A6002",
                types.SimpleNamespace(headers={}),
                MediaAccessContext(source="anonymous"),
            ))
        finally:
            if old_main is not None:
                sys.modules["main"] = old_main
            else:
                sys.modules.pop("main", None)

        self.assertEqual(response.status_code, 307)
        self.assertEqual(response.headers["location"], "/api/media/channel/mr_A6002/stream")

    def test_iptv_playlist_source_url_selects_exact_source(self):
        selected = {}
        first_source = {"url": "http://[2409::1]/live.m3u8", "source_type": "hls", "enabled": True}
        second_source = {"url": "https://fjzh.example/live.m3u8", "source_type": "hls", "enabled": True}
        fake_main = types.SimpleNamespace(
            _get_aggregated_iptv_channels=lambda: asyncio.sleep(0, result=([
                {"canonical_key": "福建综合", "urls": [first_source, second_source]},
            ], [])),
            _sorted_sources=lambda sources: list(sources),
            _source_type=lambda source: source.get("source_type") or "hls",
        )
        old_main = sys.modules.get("main")
        old_serve = media_proxy._serve_iptv_source_playlist

        async def fake_serve(source, canonical_key, access):
            selected["source"] = source
            selected["canonical_key"] = canonical_key
            return types.SimpleNamespace(status_code=200)

        try:
            sys.modules["main"] = fake_main
            media_proxy._serve_iptv_source_playlist = fake_serve
            response = asyncio.run(media_proxy._serve_iptv_channel_playlist(
                "福建综合",
                types.SimpleNamespace(headers={}),
                MediaAccessContext(source="anonymous"),
                source_url=second_source["url"],
            ))
        finally:
            media_proxy._serve_iptv_source_playlist = old_serve
            if old_main is not None:
                sys.modules["main"] = old_main
            else:
                sys.modules.pop("main", None)

        self.assertEqual(response.status_code, 200)
        self.assertIs(selected["source"], second_source)
        self.assertEqual(selected["canonical_key"], "福建综合")

    def test_chunk_preserves_upstream_404_as_streaming_response(self):
        class FakeUpstreamResponse:
            status_code = 404
            headers = {"content-type": "text/html; charset=utf-8"}
            closed = False

            async def aiter_bytes(self, chunk_size=65536):
                yield b"not found"

            async def aclose(self):
                self.closed = True

        class FakeHttpClient:
            def build_request(self, method, url, headers=None):
                return {"method": method, "url": url, "headers": headers or {}}

            async def send(self, request, stream=False, follow_redirects=False):
                return FakeUpstreamResponse()

        fake_main = types.SimpleNamespace(http_client=FakeHttpClient())
        old_main = sys.modules.get("main")
        old_validate = media_proxy._validate_handle_url_or_403

        async def noop_validate(*args, **kwargs):
            return None

        try:
            sys.modules["main"] = fake_main
            media_proxy._validate_handle_url_or_403 = noop_validate
            handle = issue_handle(
                kind="chunk",
                url="https://cdn.example.test/live/expired.ts",
                ttl_seconds=3600,
            )
            response = asyncio.run(media_proxy.media_proxy_chunk(
                handle,
                types.SimpleNamespace(headers={}, method="GET"),
                MediaAccessContext(source="anonymous"),
            ))
        finally:
            media_proxy._validate_handle_url_or_403 = old_validate
            if old_main is not None:
                sys.modules["main"] = old_main
            else:
                sys.modules.pop("main", None)

        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.media_type, "text/html; charset=utf-8")


if __name__ == "__main__":
    unittest.main()
