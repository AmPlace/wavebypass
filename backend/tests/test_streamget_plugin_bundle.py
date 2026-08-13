from __future__ import annotations

import asyncio
import importlib
import importlib.util
import json
import shutil
import sys
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest import mock

from plugin_runtime import load_manifest
from plugin_runtime.process import PluginProcess
from plugin_python_runtime import PythonEnvironmentManager
from waveflow_plugin_cli import build_project, lock_dependencies, validate_project
from waveflow_plugin_sdk import PluginError as SDKPluginError, ResolveContext, TVReference


ROOT = Path(__file__).parents[1]
PLUGIN_DIR = ROOT / "bundled_plugins" / "streamget-providers"
ARTIFACT_ROOT = ROOT / "official_plugins" / "dependency_artifacts"
EXPECTED_SCHEMES = {
    "yy", "bigo", "blued", "soop", "netease", "pandatv", "maoer", "look", "flextv", "popkontv",
    "twitcasting", "baidu", "weibo", "kugou", "twitch", "huajiao", "showroom", "inke", "acfun", "zhihu",
    "chzzk", "live17", "langlive", "changliao", "jd", "faceit", "lianjie", "sixroom", "huamao", "shopee",
    "laixiu", "picarto", "bilibili", "douyu", "douyin",
}
EXCLUDED_SCHEMES = {"haixiu", "liveme", "lehai"}
EXPECTED_SCHEME_COUNT = 35


def _load_plugin_module():
    spec = importlib.util.spec_from_file_location("streamget_bundle_plugin", PLUGIN_DIR / "plugin.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class _FakeStream:
    calls: list[tuple[str, str]] = []
    result: dict = {}
    failure: Exception | None = None

    def __init__(self, *, cookies: str):
        self.cookies = cookies

    async def fetch_web_stream_data(self, url: str):
        if self.failure:
            raise self.failure
        self.calls.append((url, "fetch_web_stream_data"))
        return {"url": url}

    async def fetch_stream_url(self, data, quality: str):
        self.calls.append((data["url"], quality))
        return self

    def to_json(self) -> str:
        return json.dumps(self.result)


def _fake_class(result: dict, *, failure: Exception | None = None):
    class Fake(_FakeStream):
        calls = []
        pass

    Fake.result = result
    Fake.failure = failure
    return Fake


class StreamGetBundleContractTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = _load_plugin_module()

    def test_manifest_and_project_are_exactly_the_bundle_boundary(self):
        manifest = load_manifest(PLUGIN_DIR / "manifest.json")
        self.assertEqual(manifest.identity, "org.waveflow/streamget-providers")
        self.assertEqual(len(EXPECTED_SCHEMES), EXPECTED_SCHEME_COUNT)
        self.assertEqual({scheme for scheme, _contract in manifest.owned_schemes}, EXPECTED_SCHEMES)
        self.assertTrue(EXPECTED_SCHEMES.isdisjoint(EXCLUDED_SCHEMES))
        self.assertEqual(set(manifest.permissions), {"network"})
        self.assertTrue(manifest.permissions["network"]["direct"])
        self.assertNotIn("managed", manifest.permissions["network"])
        self.assertTrue({
            "live.bilibili.com", "api.live.bilibili.com", "www.douyu.com",
            "playweb.douyucdn.cn", "wxapp.douyucdn.cn", "douyucdn2.cn", "live.douyin.com",
        }.issubset(set(manifest.permissions["network"]["allowed_hosts"])))
        self.assertEqual(len(manifest.runtime["dependency_lock"]["artifacts"]), 21)
        self.assertEqual(set(self.module.PROVIDER_SPECS), EXPECTED_SCHEMES)
        source = (PLUGIN_DIR / "plugin.py").read_text(encoding="utf-8")
        for forbidden in ("backend.", "httpx", "requests", "aiohttp", "curl_cffi"):
            self.assertNotIn(forbidden, source)
        self.assertTrue(validate_project(PLUGIN_DIR)["valid"])

    def test_all_schemes_have_deterministic_url_quality_and_descriptor_parity(self):
        expected_urls = {
            "yy": "https://www.yy.com/room-42/room-42", "bigo": "https://bigo.tv/room-42",
            "blued": "https://blued.com/live/room-42", "soop": "https://play.sooplive.com/room-42",
            "netease": "https://cc.163.com/room-42", "pandatv": "https://www.pandalive.co.kr/room-42",
            "maoer": "https://fm.missevan.com/room-42", "look": "https://www.look.163.com/live?id=room-42&",
            "flextv": "https://www.ttinglive.com/channels/room-42/live",
            "popkontv": "https://www.popkontv.com/live/view?castId=room-42",
            "twitcasting": "https://twitcasting.tv/room-42", "baidu": "https://live.baidu.com/?room_id=room-42&",
            "weibo": "https://weibo.com/show/room-42", "kugou": "https://fanxing.kugou.com/room-42",
            "twitch": "https://www.twitch.tv/room-42", "huajiao": "https://www.huajiao.com/l/room-42",
            "showroom": "https://www.showroom-live.com/room/profile?room_id=room-42",
            "inke": "https://webapi.busi.inke.cn/web/live_share_pc?id=room-42",
            "acfun": "https://live.acfun.cn/room-42", "zhihu": "https://www.zhihu.com/theater/room-42",
            "chzzk": "https://chzzk.naver.com/live/room-42", "live17": "https://www.lang.live/room-42",
            "langlive": "https://www.lang.live/room-42", "changliao": "https://wap.tlclw.com/room-42",
            "jd": "https://lives.jd.com/room-42", "faceit": "https://www.faceit.com/players/room-42/stream",
            "lianjie": "https://www.lailianjie.com/room-42", "sixroom": "https://v.6.cn/room-42",
            "huamao": "https://www.huamao.com/room-42", "shopee": "https://live.shopee.com/room-42",
            "laixiu": "https://www.laixiu.com/room-42", "picarto": "https://picarto.tv/room-42",
            "bilibili": "https://live.bilibili.com/room-42",
            "douyu": "https://www.douyu.com/room-42", "douyin": "https://live.douyin.com/room-42",
        }
        for scheme in sorted(EXPECTED_SCHEMES):
            fields = {"is_live": True, "flv_url": f"https://media.test/{scheme}.flv",
                      "m3u8_url": f"https://media.test/{scheme}.m3u8",
                      "record_url": f"https://media.test/{scheme}.record"}
            fake = _fake_class(fields)
            specs = {key: replace(value, stream_class=fake) for key, value in self.module.PROVIDER_SPECS.items()}
            provider = self.module.StreamGetProvider(specs)
            context = ResolveContext("fixture", 9999999999999, {}, None)
            descriptor = provider.resolve_stream(TVReference(scheme, "room-42"), context)
            spec = self.module.PROVIDER_SPECS[scheme]
            expected_url = next(fields[key] for key in spec.play_fields)
            expected_transport = spec.transport or (
                spec.transport_selector(fields, expected_url)
                if spec.transport_selector is not None else "http_flv"
            )
            self.assertEqual((descriptor.url, descriptor.transport), (expected_url, expected_transport), scheme)
            self.assertEqual((descriptor.ttl_seconds, descriptor.volatile_url, descriptor.requires_proxy),
                             (spec.ttl_seconds, spec.volatile_url, False), scheme)
            self.assertEqual(fake.calls, [(expected_urls[scheme], "fetch_web_stream_data"),
                                           (expected_urls[scheme], spec.quality)], scheme)

    def test_weibo_mapping_and_stable_failure_taxonomy(self):
        fields = {"is_live": True, "flv_url": "https://media.test/live.flv", "m3u8_url": "", "record_url": ""}
        fake = _fake_class(fields)
        specs = {key: replace(value, stream_class=fake) for key, value in self.module.PROVIDER_SPECS.items()}
        provider = self.module.StreamGetProvider(specs)
        context = ResolveContext("fixture", 9999999999999, {}, None)
        provider.resolve_stream(TVReference("weibo", "1022:room"), context)
        provider.resolve_stream(TVReference("weibo", "12345"), context)
        provider.resolve_stream(TVReference("weibo", "alias"), context)
        self.assertEqual([call[0] for call in fake.calls[::2]], [
            "https://weibo.com/show/1022:room", "https://weibo.com/u/12345", "https://weibo.com/show/alias",
        ])

        with self.assertRaises(SDKPluginError) as invalid:
            provider.resolve_stream(TVReference("weibo", ""), context)
        self.assertEqual(invalid.exception.code, "RESOURCE_NOT_FOUND")

        not_live = self.module.StreamGetProvider({"weibo": replace(self.module.PROVIDER_SPECS["weibo"],
            stream_class=_fake_class({"is_live": False}))})
        with self.assertRaises(SDKPluginError) as offline:
            not_live.resolve_stream(TVReference("weibo", "room"), context)
        self.assertEqual((offline.exception.code, offline.exception.retryable), ("NOT_LIVE", False))

        malformed = self.module.StreamGetProvider({"weibo": replace(self.module.PROVIDER_SPECS["weibo"],
            stream_class=_fake_class({"is_live": True, "flv_url": "", "m3u8_url": "", "record_url": ""}))})
        with self.assertRaises(SDKPluginError) as no_url:
            malformed.resolve_stream(TVReference("weibo", "room"), context)
        self.assertEqual(no_url.exception.code, "TEMPORARY_UPSTREAM_FAILURE")

        broken = self.module.StreamGetProvider({"weibo": replace(self.module.PROVIDER_SPECS["weibo"],
            stream_class=_fake_class({}, failure=RuntimeError("upstream")))})
        with self.assertRaises(SDKPluginError) as upstream:
            broken.resolve_stream(TVReference("weibo", "room"), context)
        self.assertEqual(upstream.exception.code, "TEMPORARY_UPSTREAM_FAILURE")

    def test_bilibili_preserves_legacy_play_selection_and_error_taxonomy(self):
        fields = {
            "is_live": True,
            "flv_url": "https://media.test/bilibili.flv",
            "m3u8_url": "https://media.test/bilibili.m3u8",
            "record_url": "https://media.test/bilibili.record",
        }
        fake = _fake_class(fields)
        spec = replace(self.module.PROVIDER_SPECS["bilibili"], stream_class=fake)
        provider = self.module.StreamGetProvider({"bilibili": spec})
        context = ResolveContext("fixture", 9999999999999, {}, None)
        descriptor = provider.resolve_stream(TVReference("bilibili", "room-42"), context)
        self.assertEqual(
            (descriptor.url, descriptor.transport, descriptor.ttl_seconds,
             descriptor.volatile_url, descriptor.requires_proxy),
            ("https://media.test/bilibili.flv", "http_flv", 1800, False, False),
        )
        self.assertEqual(fake.calls, [
            ("https://live.bilibili.com/room-42", "fetch_web_stream_data"),
            ("https://live.bilibili.com/room-42", "OD"),
        ])

        record_only = _fake_class({"is_live": True, "flv_url": "", "record_url": "https://media.test/record"})
        record_provider = self.module.StreamGetProvider({"bilibili": replace(spec, stream_class=record_only)})
        record = record_provider.resolve_stream(TVReference("bilibili", "room-42"), context)
        self.assertEqual(record.url, "https://media.test/record")

        for reference, expected in ((TVReference("bilibili", ""), "RESOURCE_NOT_FOUND"),
                                    (TVReference("bilibili", "room-42"), "NOT_LIVE")):
            test_provider = self.module.StreamGetProvider({
                "bilibili": replace(spec, stream_class=_fake_class(
                    {"is_live": False} if expected == "NOT_LIVE" else fields,
                )),
            })
            with self.assertRaises(SDKPluginError) as error:
                test_provider.resolve_stream(reference, context)
            self.assertEqual(error.exception.code, expected)

        malformed = self.module.StreamGetProvider({
            "bilibili": replace(spec, stream_class=_fake_class({"is_live": True, "flv_url": "", "record_url": ""})),
        })
        with self.assertRaises(SDKPluginError) as no_url:
            malformed.resolve_stream(TVReference("bilibili", "room-42"), context)
        self.assertEqual(no_url.exception.code, "TEMPORARY_UPSTREAM_FAILURE")

    def test_bilibili_descriptor_matches_legacy_golden_fixture(self):
        """Compare the public descriptor fields, not provider-specific metadata."""
        legacy = importlib.import_module("adapters.bilibili")
        from adapters import AdapterRequest
        from provider_resolver import parse_tv_reference

        direct = parse_tv_reference("bilibili://room-42")
        compat = parse_tv_reference("adapter://bilibili/room-42")
        self.assertEqual((direct.scheme, direct.resource_id), ("bilibili", "room-42"))
        self.assertEqual((compat.scheme, compat.resource_id), ("bilibili", "room-42"))

        fields = {
            "is_live": True,
            "flv_url": "https://media.test/bilibili.flv",
            "record_url": "https://media.test/bilibili.record",
            "anchor_name": "fixture-anchor",
        }
        fake = _fake_class(fields)
        with mock.patch.object(legacy, "BilibiliLiveStream", fake):
            legacy_result = asyncio.run(legacy.resolve_bilibili(
                AdapterRequest("bilibili://room-42", "bilibili", "room-42", {}), None,
            ))

        provider = self.module.StreamGetProvider({
            "bilibili": replace(self.module.PROVIDER_SPECS["bilibili"], stream_class=fake),
        })
        descriptor = provider.resolve_stream(
            TVReference("bilibili", "room-42"), ResolveContext("fixture", 9999999999999, {}, None),
        )
        plugin_result = {
            "url": descriptor.url,
            "source_type": descriptor.transport,
            "direct_playable": descriptor.direct_playable,
            "requires_proxy": descriptor.requires_proxy,
            "headers": descriptor.headers,
            "ttl": descriptor.ttl_seconds,
            "expires_at": descriptor.expires_at,
            # The legacy adapter omits this field and the Core bridge exposes
            # the omitted/default semantic as false.
            "volatile_url": descriptor.volatile_url,
        }
        legacy_result["volatile_url"] = bool(legacy_result.get("volatile_url"))
        self.assertEqual(
            {key: legacy_result[key] for key in plugin_result},
            plugin_result,
        )
        self.assertEqual(fake.calls, [
            ("https://live.bilibili.com/room-42", "fetch_web_stream_data"),
            ("https://live.bilibili.com/room-42", "OD"),
            ("https://live.bilibili.com/room-42", "fetch_web_stream_data"),
            ("https://live.bilibili.com/room-42", "OD"),
        ])

    def test_douyu_preserves_cdn_selection_and_descriptor_golden_fixture(self):
        fields = {
            "is_live": True,
            "flv_url": "https://ws-h5.douyucdn2.cn/live/primary.flv",
            "m3u8_url": "https://backup.example/live.m3u8",
            "extra": {"backup_url_list": [
                "https://edge.edgesrv.com:8443/live.flv",
                "https://backup.example/live.flv",
                "https://cdn.douyucdn2.cn/live/backup.flv",
            ]},
            "anchor_name": "fixture-anchor",
        }
        fake = _fake_class(fields)
        provider = self.module.StreamGetProvider({
            "douyu": replace(self.module.PROVIDER_SPECS["douyu"], stream_class=fake),
        })
        descriptor = provider.resolve_stream(
            TVReference("douyu", "/room-42/"),
            ResolveContext("fixture", 9999999999999, {}, None),
        )
        self.assertEqual(
            (descriptor.url, descriptor.transport, descriptor.ttl_seconds,
             descriptor.volatile_url, descriptor.requires_proxy),
            ("https://ws-h5.douyucdn2.cn/live/primary.flv", "http_flv", 0, True, False),
        )
        self.assertEqual(fake.calls, [
            ("https://www.douyu.com/room-42", "fetch_web_stream_data"),
            ("https://www.douyu.com/room-42", "OD"),
        ])

        # A non-primary preferred CDN still wins over ordinary fallbacks and
        # edgesrv:8443, while the stable fallback order remains deterministic.
        fallback = _fake_class({
            "is_live": True,
            "flv_url": "https://edge.edgesrv.com:8443/live.flv",
            "extra": {"backup_url_list": [
                "https://backup.example/live.flv",
                "https://cdn.douyucdn2.cn/live/backup.flv",
            ]},
        })
        fallback_provider = self.module.StreamGetProvider({
            "douyu": replace(self.module.PROVIDER_SPECS["douyu"], stream_class=fallback),
        })
        fallback_descriptor = fallback_provider.resolve_stream(
            TVReference("douyu", "room-42"),
            ResolveContext("fixture", 9999999999999, {}, None),
        )
        self.assertEqual(fallback_descriptor.url, "https://cdn.douyucdn2.cn/live/backup.flv")

        hls = _fake_class({
            "is_live": True,
            "flv_url": "",
            "m3u8_url": "https://backup.example/live.m3u8",
            "extra": {"backup_url_list": ["https://cdn.douyucdn2.cn/live/backup.m3u8"]},
        })
        hls_provider = self.module.StreamGetProvider({
            "douyu": replace(self.module.PROVIDER_SPECS["douyu"], stream_class=hls),
        })
        hls_descriptor = hls_provider.resolve_stream(
            TVReference("douyu", "room-42"),
            ResolveContext("fixture", 9999999999999, {}, None),
        )
        self.assertEqual((hls_descriptor.url, hls_descriptor.transport),
                         ("https://cdn.douyucdn2.cn/live/backup.m3u8", "hls"))

        all_blocked = _fake_class({
            "is_live": True,
            "flv_url": "https://edge.edgesrv.com:8443/live.flv",
            "extra": {"backup_url_list": ["https://edge2.edgesrv.com:8443/live.flv"]},
        })
        all_blocked_provider = self.module.StreamGetProvider({
            "douyu": replace(self.module.PROVIDER_SPECS["douyu"], stream_class=all_blocked),
        })
        self.assertEqual(
            all_blocked_provider.resolve_stream(
                TVReference("douyu", "room-42"),
                ResolveContext("fixture", 9999999999999, {}, None),
            ).url,
            "https://edge.edgesrv.com:8443/live.flv",
        )

        for result, expected in (
            ({"is_live": False}, "NOT_LIVE"),
            ({"is_live": True, "flv_url": "", "m3u8_url": "", "extra": {}},
             "TEMPORARY_UPSTREAM_FAILURE"),
        ):
            error_provider = self.module.StreamGetProvider({
                "douyu": replace(self.module.PROVIDER_SPECS["douyu"], stream_class=_fake_class(result)),
            })
            with self.assertRaises(SDKPluginError) as error:
                error_provider.resolve_stream(
                    TVReference("douyu", "room-42"),
                    ResolveContext("fixture", 9999999999999, {}, None),
                )
            self.assertEqual(error.exception.code, expected)

        broken = self.module.StreamGetProvider({
            "douyu": replace(self.module.PROVIDER_SPECS["douyu"],
                             stream_class=_fake_class({}, failure=RuntimeError("upstream"))),
        })
        with self.assertRaises(SDKPluginError) as upstream:
            broken.resolve_stream(
                TVReference("douyu", "room-42"),
                ResolveContext("fixture", 9999999999999, {}, None),
            )
        self.assertEqual(upstream.exception.code, "TEMPORARY_UPSTREAM_FAILURE")

    def test_douyu_descriptor_matches_legacy_golden_fixture_without_importing_legacy(self):
        legacy = importlib.import_module("adapters.douyu")
        from adapters import AdapterRequest

        fields = {
            "is_live": True,
            "flv_url": "https://edge.edgesrv.com:8443/live.flv",
            "m3u8_url": "https://backup.example/live.m3u8",
            "extra": {"backup_url_list": [
                "https://backup.example/live.flv",
                "https://cdn.douyucdn2.cn/live/backup.flv",
            ]},
        }

        class LegacyFake(_FakeStream):
            calls = []
            result = fields

            def __init__(self):
                super().__init__(cookies="")

        with mock.patch.object(legacy, "DouyuLiveStream", LegacyFake):
            legacy_result = asyncio.run(legacy.resolve_douyu(
                AdapterRequest("douyu://room-42", "douyu", "room-42", {}), None,
            ))

        plugin_fake = _fake_class(fields)
        provider = self.module.StreamGetProvider({
            "douyu": replace(self.module.PROVIDER_SPECS["douyu"], stream_class=plugin_fake),
        })
        descriptor = provider.resolve_stream(
            TVReference("douyu", "room-42"),
            ResolveContext("fixture", 9999999999999, {}, None),
        )
        plugin_result = {
            "url": descriptor.url,
            "source_type": descriptor.transport,
            "direct_playable": descriptor.direct_playable,
            "requires_proxy": descriptor.requires_proxy,
            "headers": descriptor.headers,
            "ttl": descriptor.ttl_seconds,
            "expires_at": descriptor.expires_at,
            "volatile_url": descriptor.volatile_url,
        }
        self.assertEqual({key: legacy_result[key] for key in plugin_result}, plugin_result)
        source = (PLUGIN_DIR / "plugin.py").read_text(encoding="utf-8")
        self.assertNotIn("adapters.douyu", source)
        self.assertNotIn("backend.adapters.douyu", source)

    def test_douyin_matches_legacy_hls_flv_cookie_and_error_golden_fixture(self):
        legacy = importlib.import_module("adapters.douyin")
        from adapters import AdapterRequest
        from streamget import DouyinLiveStream

        fields = {
            "is_live": True,
            "m3u8_url": "https://media.test/douyin.m3u8",
            "flv_url": "https://media.test/douyin.flv",
            "anchor_name": "fixture-anchor",
        }

        def fake_class(result: dict, *, failure: Exception | None = None):
            class Fake(_FakeStream):
                calls = []
                instances = []

                def __init__(self, proxy_addr=None, cookies=None, stream_orientation=1):
                    self.proxy_addr = proxy_addr
                    self.cookies = cookies
                    self.stream_orientation = stream_orientation
                    type(self).instances.append(self)

            Fake.result = result
            Fake.failure = failure
            return Fake

        legacy_fake = fake_class(fields)
        with mock.patch.object(legacy, "DouyinLiveStream", legacy_fake):
            legacy_result = asyncio.run(legacy.resolve_douyin(
                AdapterRequest("douyin://room-42", "douyin", "room-42", {}), None,
            ))

        plugin_fake = fake_class(fields)
        provider = self.module.StreamGetProvider({
            "douyin": replace(self.module.PROVIDER_SPECS["douyin"], stream_class=plugin_fake),
        })
        descriptor = provider.resolve_stream(
            TVReference("douyin", "/room-42/"),
            ResolveContext("fixture", 9999999999999, {}, None),
        )
        plugin_result = {
            "url": descriptor.url,
            "source_type": descriptor.transport,
            "direct_playable": descriptor.direct_playable,
            "requires_proxy": descriptor.requires_proxy,
            "headers": descriptor.headers,
            "ttl": descriptor.ttl_seconds,
            "expires_at": descriptor.expires_at,
            "volatile_url": descriptor.volatile_url,
        }
        legacy_result["volatile_url"] = bool(legacy_result.get("volatile_url"))
        self.assertEqual({key: legacy_result[key] for key in plugin_result}, plugin_result)
        self.assertEqual(legacy_fake.instances[0].cookies, None)
        self.assertEqual(plugin_fake.instances[0].cookies, "")
        self.assertEqual(legacy_fake.calls, [
            ("https://live.douyin.com/room-42", "fetch_web_stream_data"),
            ("https://live.douyin.com/room-42", "OD"),
        ])
        self.assertEqual(plugin_fake.calls, legacy_fake.calls)

        # Passing an empty cookie string preserves StreamGet's own default
        # cookie/header behavior; the Plugin does not inject provider headers.
        self.assertEqual(
            DouyinLiveStream().pc_headers,
            DouyinLiveStream(cookies="").pc_headers,
        )
        self.assertEqual(
            DouyinLiveStream().mobile_headers,
            DouyinLiveStream(cookies="").mobile_headers,
        )
        self.assertEqual(DouyinLiveStream().pc_headers["referer"], "https://live.douyin.com/")

        flv_only = self.module.StreamGetProvider({
            "douyin": replace(self.module.PROVIDER_SPECS["douyin"], stream_class=fake_class({
                "is_live": True,
                "m3u8_url": "",
                "flv_url": "https://media.test/douyin.flv",
            })),
        })
        flv_descriptor = flv_only.resolve_stream(
            TVReference("douyin", "room-42"),
            ResolveContext("fixture", 9999999999999, {}, None),
        )
        self.assertEqual((flv_descriptor.url, flv_descriptor.transport),
                         ("https://media.test/douyin.flv", "http_flv"))

        for result, expected in (
            ({"is_live": False}, "NOT_LIVE"),
            ({"is_live": True, "m3u8_url": "", "flv_url": ""},
             "TEMPORARY_UPSTREAM_FAILURE"),
        ):
            error_provider = self.module.StreamGetProvider({
                "douyin": replace(self.module.PROVIDER_SPECS["douyin"], stream_class=fake_class(result)),
            })
            with self.assertRaises(SDKPluginError) as error:
                error_provider.resolve_stream(
                    TVReference("douyin", "room-42"),
                    ResolveContext("fixture", 9999999999999, {}, None),
                )
            self.assertEqual(error.exception.code, expected)

        broken = self.module.StreamGetProvider({
            "douyin": replace(self.module.PROVIDER_SPECS["douyin"],
                              stream_class=fake_class({}, failure=RuntimeError("upstream"))),
        })
        with self.assertRaises(SDKPluginError) as upstream:
            broken.resolve_stream(
                TVReference("douyin", "room-42"),
                ResolveContext("fixture", 9999999999999, {}, None),
            )
        self.assertEqual(upstream.exception.code, "TEMPORARY_UPSTREAM_FAILURE")

        with self.assertRaises(SDKPluginError) as invalid:
            provider.resolve_stream(
                TVReference("douyin", ""),
                ResolveContext("fixture", 9999999999999, {}, None),
            )
        self.assertEqual(invalid.exception.code, "RESOURCE_NOT_FOUND")

        source = (PLUGIN_DIR / "plugin.py").read_text(encoding="utf-8")
        self.assertNotIn("adapters.douyin", source)
        self.assertNotIn("backend.adapters.douyin", source)

    def test_cli_lock_treats_py2_py3_wheels_as_python3_compatible(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            requirements = root / "requirements.in"
            requirements.write_text("six==1.17.0\n", encoding="utf-8")
            wheels = root / "wheels"
            wheels.mkdir()
            source = ARTIFACT_ROOT / "pyexecjs" / "six-1.17.0-py2.py3-none-any.whl"
            shutil.copyfile(source, wheels / source.name)
            lock = lock_dependencies(requirements, root / "lock.json", wheel_dir=wheels)
            self.assertEqual(lock["artifacts"][0]["python_tag"], "py3")
            self.assertEqual(lock["artifacts"][0]["abi_tag"], "none")
            self.assertEqual(lock["artifacts"][0]["platform_tag"], "any")


class StreamGetBundleRuntimeTest(unittest.IsolatedAsyncioTestCase):
    async def test_clean_isolated_environment_imports_dependencies_and_runs_plugin_health(self):
        manifest = load_manifest(PLUGIN_DIR / "manifest.json")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project = root / "project"
            project.mkdir()
            for filename in ("plugin.py", "manifest.json", "dependency-lock.json"):
                shutil.copyfile(PLUGIN_DIR / filename, project / filename)
            build = build_project(project, output=root / "streamget-providers.pyz")
            references = {}
            for item in manifest.runtime["dependency_lock"]["artifacts"]:
                if item["filename"].startswith(("pyexecjs-", "six-")):
                    path = ARTIFACT_ROOT / "pyexecjs" / item["filename"]
                else:
                    path = ARTIFACT_ROOT / "streamget-providers" / item["filename"]
                references[item["sha256"]] = path
                self.assertTrue(path.is_file(), item["filename"])

            manager = PythonEnvironmentManager(root / "plugin-store")
            environment = await manager.prepare(manifest, references)
            self.assertTrue(environment.path.is_relative_to(manager.root))
            self.assertIn("include-system-site-packages = false",
                          (environment.path / "pyvenv.cfg").read_text(encoding="utf-8").lower())
            probe = await asyncio.create_subprocess_exec(
                str(environment.python), "-I", "-c",
                "import execjs, shutil, streamget, sys; print(execjs.__file__); print(streamget.__version__); print(sys.prefix != sys.base_prefix); print(shutil.which('node') is None)",
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
                env={"PATH": "/usr/bin:/bin", "PYTHONNOUSERSITE": "1"},
            )
            stdout, stderr = await probe.communicate()
            self.assertEqual(probe.returncode, 0, stderr.decode())
            lines = stdout.decode().splitlines()
            self.assertIn(str(environment.path), lines[0])
            self.assertEqual(lines[1], "4.0.10")
            self.assertEqual(lines[2], "True")
            self.assertEqual(lines[3], "True")

            process = PluginProcess(
                (str(environment.python), str(build["artifact"]), "--identity", manifest.identity,
                 "--version", manifest.version),
                "streamget-runtime-smoke",
                environment={"PATH": "/usr/bin:/bin", "LANG": "C"},
            )
            await process.start()
            try:
                hello = await process.call("runtime.hello", {})
                process.negotiate_protocol(hello["protocol_version"])
                health = await process.call("runtime.health", {})
                self.assertEqual(hello["plugin"], manifest.identity)
                self.assertEqual({item["scheme"] for item in hello["owned_schemes"]}, EXPECTED_SCHEMES)
                self.assertEqual(hello["permissions"], ["network"])
                self.assertTrue(health["healthy"])
            finally:
                await process.call("runtime.shutdown", {})
                await process.stop()


if __name__ == "__main__":
    unittest.main()
