from __future__ import annotations

import asyncio
import importlib.util
import json
import shutil
import sys
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

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
    "laixiu", "picarto",
}
EXCLUDED_SCHEMES = {"haixiu", "liveme", "lehai"}


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
        self.assertEqual({scheme for scheme, _contract in manifest.owned_schemes}, EXPECTED_SCHEMES)
        self.assertTrue(EXPECTED_SCHEMES.isdisjoint(EXCLUDED_SCHEMES))
        self.assertEqual(set(manifest.permissions), {"network"})
        self.assertTrue(manifest.permissions["network"]["direct"])
        self.assertNotIn("managed", manifest.permissions["network"])
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
            expected_transport = spec.transport or "http_flv"
            self.assertEqual((descriptor.url, descriptor.transport), (expected_url, expected_transport), scheme)
            self.assertEqual((descriptor.ttl_seconds, descriptor.volatile_url, descriptor.requires_proxy),
                             (1800, True, False), scheme)
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
