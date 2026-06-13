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


if __name__ == "__main__":
    unittest.main()
