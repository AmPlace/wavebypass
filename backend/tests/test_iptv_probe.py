import unittest

import iptv_probe
from iptv_probe import (
    _empty_result,
    _enrich_with_ffprobe,
    _ffmpeg_input_timeout_args,
    _parse_ffmpeg_output,
    probe_channel_source,
)


class IptvProbeFfmpegArgsTest(unittest.TestCase):
    def test_rtsp_uses_rtsp_demuxer_timeout(self):
        self.assertEqual(_ffmpeg_input_timeout_args("rtsp://example/live", 7.0), ["-timeout", "7000000"])

    def test_http_uses_protocol_read_timeout(self):
        self.assertEqual(_ffmpeg_input_timeout_args("https://example/live.m3u8", 7.0), ["-rw_timeout", "7000000"])

    def test_ffmpeg_banner_parses_quality_fields(self):
        output = """
Input #0, rtsp, from 'rtsp://example/live':
  Duration: N/A, start: 0.000000, bitrate: 2048 kb/s
  Stream #0:0: Video: h264 (Main), yuv420p, 1920x1080, 25 fps, 25 tbr, 90k tbn
  Stream #0:1: Audio: aac, 48000 Hz, stereo, fltp, 128 kb/s
"""

        parsed = _parse_ffmpeg_output(output)

        self.assertEqual(parsed["resolution"], "1920x1080")
        self.assertEqual(parsed["video_codec"], "h264")
        self.assertEqual(parsed["audio_codec"], "aac")
        self.assertEqual(parsed["fps"], 25)
        self.assertEqual(parsed["speed_mbps"], 0.25)


class IptvProbeRealtimeStreamTest(unittest.IsolatedAsyncioTestCase):
    async def test_rtsp_does_not_run_duplicate_ffmpeg_fallback(self):
        calls = 0
        original_probe = iptv_probe._probe_with_ffmpeg

        async def fake_probe(url, headers, *, reason):
            nonlocal calls
            calls += 1
            return _empty_result(probe_status="offline", probe_method="ffmpeg", last_error="no_stream")

        iptv_probe._probe_with_ffmpeg = fake_probe
        try:
            result = await probe_channel_source({"url": "rtsp://example/live", "source_type": "rtsp"}, None)
        finally:
            iptv_probe._probe_with_ffmpeg = original_probe

        self.assertEqual(result["probe_status"], "offline")
        self.assertEqual(calls, 1)

    async def test_ffmpeg_online_result_skips_ffprobe_enrichment(self):
        original_probe_media_info = iptv_probe._probe_media_info

        async def fail_probe_media_info(url, headers):
            raise AssertionError("ffprobe should not run after ffmpeg already validated the stream")

        iptv_probe._probe_media_info = fail_probe_media_info
        try:
            result = await _enrich_with_ffprobe(
                _empty_result(probe_status="online", probe_method="ffmpeg", video_codec="h264"),
                "rtsp://example/live",
                {},
            )
        finally:
            iptv_probe._probe_media_info = original_probe_media_info

        self.assertEqual(result["probe_status"], "online")
        self.assertEqual(result["video_codec"], "h264")

    async def test_youtube_probe_resolves_before_stream_probe(self):
        resolved_targets = []
        probed_urls = []
        original_resolve = iptv_probe.resolve_adapter_source
        original_probe_hls = iptv_probe._probe_hls
        original_enrich = iptv_probe._enrich_with_ffprobe

        async def fake_resolve(target_url, client):
            resolved_targets.append(target_url)
            return {
                "adapter": "youtube",
                "source_type": "hls",
                "url": "https://example.com/live.m3u8",
                "headers": {},
                "ttl": 120,
            }

        async def fake_probe_hls(client, url, headers):
            probed_urls.append(url)
            return _empty_result(probe_status="online", live_status="live", probe_method="http_segment")

        async def fake_enrich(result, url, headers):
            return result

        iptv_probe.resolve_adapter_source = fake_resolve
        iptv_probe._probe_hls = fake_probe_hls
        iptv_probe._enrich_with_ffprobe = fake_enrich
        try:
            result = await probe_channel_source(
                {"url": "https://www.youtube.com/live/abcDEF123_4", "source_type": "youtube"},
                None,
            )
        finally:
            iptv_probe.resolve_adapter_source = original_resolve
            iptv_probe._probe_hls = original_probe_hls
            iptv_probe._enrich_with_ffprobe = original_enrich

        self.assertEqual(result["probe_status"], "online")
        self.assertTrue(resolved_targets[0].startswith("youtube://resolve?url="))
        self.assertEqual(probed_urls, ["https://example.com/live.m3u8"])


if __name__ == "__main__":
    unittest.main()
