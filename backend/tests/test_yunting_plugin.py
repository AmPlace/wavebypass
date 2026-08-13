from __future__ import annotations

import unittest

from plugin_runtime import PluginError
from waveflow_plugin_sdk import ResolveContext

from bundled_plugins.yunting.plugin import PROVINCES, Provider


class _Response:
    status = 200

    def __init__(self, body):
        self.body = body


class _Capabilities:
    def __init__(self, records_by_province, *, fail=False):
        self.records_by_province = records_by_province
        self.fail = fail
        self.calls = []

    def managed_http(self, url, *, query, headers, response_mode, timeout):
        self.calls.append((url, dict(query), dict(headers), response_mode, timeout))
        if self.fail:
            raise PluginError("TEMPORARY_UPSTREAM_FAILURE", "fixture upstream unavailable")
        province = str(query["provinceCode"])
        return _Response({"data": self.records_by_province.get(province, [])})


def _context(capabilities):
    return ResolveContext("test-yunting", 0, {}, capabilities, lambda: False)


def _records():
    return {
        province: [{
            "contentId": f"cid-{province}",
            "title": f"Station {province}",
            "subtitle": f"Programme {province}",
            "playUrlLow": f"http://audio.example/{province}.m3u8",
            "picUrl": f"https://image.example/{province}.png",
        }]
        for province in PROVINCES
    }


class YuntingPluginTest(unittest.TestCase):
    def test_catalog_is_stable_and_bounded_across_all_provinces(self):
        capabilities = _Capabilities(_records())
        catalog = Provider().catalog({}, _context(capabilities))
        self.assertEqual(len(catalog["stations"]), len(PROVINCES))
        self.assertEqual({item["station_ref"]["provider_station_id"] for item in catalog["stations"]},
                         {f"cid-{province}" for province in PROVINCES})
        self.assertEqual(len(capabilities.calls), len(PROVINCES))
        first = catalog["stations"][0]
        self.assertEqual(first["playback_config"]["province_code"], first["metadata"]["province_code"])
        self.assertEqual(first["ttl_seconds"], 7200)
        self.assertTrue(all(call[2]["sign"] for call in capabilities.calls))

    def test_resolve_normalizes_legacy_url_and_keeps_direct_semantics(self):
        capabilities = _Capabilities(_records())
        reference = __import__("waveflow_plugin_sdk", fromlist=["RadioReference"]).RadioReference(
            "yunting", "cid-340000", {"province_code": "340000"},
        )
        descriptor = Provider().resolve_stream(reference, _context(capabilities))
        self.assertEqual(descriptor.url, "https://audio.example/340000.m3u8")
        self.assertEqual(descriptor.transport, "audio_http")
        self.assertEqual(descriptor.ttl_seconds, 3600)
        self.assertTrue(descriptor.volatile_url)
        self.assertFalse(descriptor.requires_proxy)

    def test_programme_is_current_label_snapshot_not_invented_schedule(self):
        capabilities = _Capabilities(_records())
        reference = __import__("waveflow_plugin_sdk", fromlist=["RadioReference"]).RadioReference(
            "yunting", "cid-110000", {"province_code": "110000"},
        )
        snapshot = Provider().programme(reference, _context(capabilities))
        self.assertEqual(snapshot["station_ref"]["provider_station_id"], "cid-110000")
        self.assertEqual(len(snapshot["programmes"]), 1)
        item = snapshot["programmes"][0]
        self.assertEqual(item["title"], "Programme 110000")
        self.assertNotIn("start", item)
        self.assertNotIn("end", item)

    def test_all_upstream_failures_are_reported_without_empty_success(self):
        with self.assertRaises(PluginError) as raised:
            Provider().catalog({}, _context(_Capabilities({}, fail=True)))
        self.assertEqual(raised.exception.code, "TEMPORARY_UPSTREAM_FAILURE")


if __name__ == "__main__":
    unittest.main()
