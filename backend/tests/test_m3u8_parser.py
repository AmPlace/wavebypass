import unittest

from m3u8_parser import (
    adapter_provider,
    detect_source_type,
    parse_youtube_channel_id,
    parse_youtube_video_id,
)


class YoutubeParsingTest(unittest.TestCase):
    def test_live_url_extracts_video_id(self):
        self.assertEqual(
            parse_youtube_video_id("https://www.youtube.com/live/abcDEF123_4?feature=share"),
            "abcDEF123_4",
        )

    def test_youtube_scheme_live_extracts_video_id(self):
        self.assertEqual(parse_youtube_video_id("youtube://live/abcDEF123_4"), "abcDEF123_4")
        self.assertEqual(detect_source_type("youtube://live/abcDEF123_4"), "youtube")

    def test_youtube_scheme_channel_live_extracts_channel_id(self):
        channel_id = "UC12345678901234567890"
        self.assertEqual(parse_youtube_channel_id(f"youtube://channel/{channel_id}/live"), channel_id)
        self.assertEqual(parse_youtube_channel_id(f"youtube://{channel_id}/live"), channel_id)
        self.assertEqual(detect_source_type(f"youtube://channel/{channel_id}/live"), "youtube")

    def test_ytsl_scheme_is_not_supported(self):
        self.assertEqual(adapter_provider("ytsl://abcDEF123_4"), "")
        self.assertEqual(detect_source_type("ytsl://abcDEF123_4"), "hls")


if __name__ == "__main__":
    unittest.main()
