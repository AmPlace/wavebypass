from __future__ import annotations

import asyncio
import json
import unittest

from plugin_runtime import (
    LifecycleState, MemoryCapabilityStubs, PermissionGate, PermissionPolicy, PluginError,
    PluginInstance, PluginRegistry, encode_frame, read_frame, validate_manifest,
    validate_stream_descriptor,
)


def manifest_data(*, scheme="synthetic", version="1.0.0", permissions=None, core_range=">=0.1.0 <1.0.0"):
    return {
        "manifest_version": 1, "publisher_id": "org.waveflow", "plugin_id": "synthetic",
        "display_name": "Synthetic", "version": version, "plugin_api_version": "1.0",
        "core_version_range": core_range,
        "provider_contracts": [
            {"contract": "tv_provider", "contract_version": "1.0", "features": ["resolve_stream"]},
            {"contract": "radio_provider", "contract_version": "1.0", "features": ["catalog", "resolve_stream"]},
        ],
        "owned_schemes": [{"scheme": scheme, "contract": "tv_provider"}],
        "capabilities": ["tv.resolve_stream", "radio.catalog", "radio.resolve_stream"],
        "permissions": permissions or {},
        "runtime": {"type": "subprocess", "ipc": "stdio_framed_json_v1"},
        "artifacts": [{"os": "linux", "arch": "x86_64", "runtime": "native",
                       "entrypoint": "synthetic-plugin", "sha256": "0" * 64, "size_bytes": 1,
                       "signature": {"algorithm": "ed25519", "key_id": "fixture", "value": "fixture"}}],
        "dependencies": [], "state_schema_version": 1,
    }


def descriptor(transport="hls"):
    return {"descriptor_version": "1.0", "transport": transport,
            "url": "" if transport == "probe_only" else "https://example.invalid/live",
            "headers": {}, "credential_refs": [], "ttl_seconds": 10, "expires_at": None,
            "volatile_url": True, "requires_proxy": False, "warnings": []}


class ManifestValidationTest(unittest.TestCase):
    def test_valid_manifest_and_stable_identity(self):
        manifest = validate_manifest(manifest_data())
        self.assertEqual(manifest.identity, "org.waveflow/synthetic")
        self.assertEqual(manifest.version, "1.0.0")

    def test_malformed_incompatible_and_duplicate_scheme(self):
        cases = []
        missing = manifest_data(); missing.pop("plugin_id"); cases.append((missing, "INVALID_PLUGIN_RESPONSE"))
        bad_api = manifest_data(); bad_api["plugin_api_version"] = "2.0"; cases.append((bad_api, "PLUGIN_INCOMPATIBLE"))
        bad_core = manifest_data(core_range=">=2.0.0 <3.0.0"); cases.append((bad_core, "PLUGIN_INCOMPATIBLE"))
        bad_semver = manifest_data(); bad_semver["version"] = "latest"; cases.append((bad_semver, "INVALID_PLUGIN_RESPONSE"))
        bad_range = manifest_data(); bad_range["core_version_range"] = "^0.1"; cases.append((bad_range, "INVALID_PLUGIN_RESPONSE"))
        duplicate = manifest_data(); duplicate["owned_schemes"].append(dict(duplicate["owned_schemes"][0])); cases.append((duplicate, "SCHEME_CONFLICT"))
        bad_permission = manifest_data(); bad_permission["permissions"] = "all"; cases.append((bad_permission, "INVALID_PLUGIN_RESPONSE"))
        bad_runtime = manifest_data(); bad_runtime["runtime"] = {"type": "python"}; cases.append((bad_runtime, "PLUGIN_INCOMPATIBLE"))
        for data, code in cases:
            with self.subTest(code=code):
                with self.assertRaises(PluginError) as raised:
                    validate_manifest(data)
                self.assertEqual(raised.exception.code, code)


class ProtocolCodecTest(unittest.IsolatedAsyncioTestCase):
    async def _reader(self, data: bytes, chunks: tuple[int, ...] = ()):
        reader = asyncio.StreamReader()
        if not chunks:
            reader.feed_data(data)
        else:
            offset = 0
            for size in chunks:
                reader.feed_data(data[offset:offset + size]); offset += size
            reader.feed_data(data[offset:])
        reader.feed_eof()
        return reader

    async def test_partial_and_multiple_frames(self):
        first = encode_frame({"n": 1}); second = encode_frame({"n": 2})
        reader = await self._reader(first + second, (1, 2, 3, 5, 8))
        self.assertEqual(await read_frame(reader), {"n": 1})
        self.assertEqual(await read_frame(reader), {"n": 2})

    async def test_malformed_truncated_invalid_and_oversized_frames(self):
        bad_frames = [
            b"Bad\r\n\r\n{}",
            b"Content-Length: nope\r\nContent-Type: application/json; charset=utf-8\r\n\r\n{}",
            b"Content-Length: 5\r\nContent-Type: application/json; charset=utf-8\r\n\r\n{}",
            b"Content-Length: 2\r\nContent-Type: application/json; charset=utf-8\r\n\r\n\xff\xff",
            b"Content-Length: 1048577\r\nContent-Type: application/json; charset=utf-8\r\n\r\n",
        ]
        for frame in bad_frames:
            with self.subTest(frame=frame[:20]):
                with self.assertRaises(PluginError):
                    await read_frame(await self._reader(frame))
        with self.assertRaises(PluginError):
            encode_frame({"body": "x" * (1024 * 1024)})


class ValidationPermissionRegistryTest(unittest.TestCase):
    def test_all_stream_transports_and_secret_header_rejection(self):
        for transport in ("hls", "dash", "http_flv", "mpegts", "audio_http", "probe_only"):
            self.assertEqual(validate_stream_descriptor(descriptor(transport))["transport"], transport)
        rtsp = descriptor("rtsp"); rtsp["url"] = "rtsp://example.invalid/live"
        self.assertEqual(validate_stream_descriptor(rtsp)["transport"], "rtsp")
        rich = descriptor("dash")
        rich.update({"quality_variants": [{"name": "best"}], "drm": {"scheme": "widevine"},
                     "encryption": {"method": "aes-128"}, "provider_diagnostics": {"id": "safe"}})
        validate_stream_descriptor(rich)
        bad = descriptor(); bad["headers"] = {"Cookie": "redacted"}
        with self.assertRaises(PluginError) as raised:
            validate_stream_descriptor(bad)
        self.assertEqual(raised.exception.code, "INVALID_PLUGIN_RESPONSE")

    def test_permission_allow_deny_and_memory_stubs(self):
        manifest = validate_manifest(manifest_data(permissions={"cache": {}, "subprocess": {}}))
        gate = PermissionGate(manifest, PermissionPolicy(frozenset({"cache"})))
        gate.require("cache")
        with self.assertRaises(PluginError) as denied:
            gate.require("subprocess")
        self.assertEqual(denied.exception.code, "CAPABILITY_DENIED")
        with self.assertRaises(PluginError):
            gate.require("undeclared")
        stubs = MemoryCapabilityStubs(gate)
        stubs.cache_set("key", "value")
        self.assertEqual(stubs.cache_get("key"), "value")

    def test_registry_conflict_unhealthy_and_lifecycle_transitions(self):
        registry = PluginRegistry()
        first = PluginInstance("first", validate_manifest(manifest_data()))
        second = PluginInstance("second", validate_manifest(manifest_data(version="1.1.0")))
        registry.install(first); registry.install(second)
        first.transition(LifecycleState.STARTING); first.transition(LifecycleState.HANDSHAKING); registry.activate(first)
        second.transition(LifecycleState.STARTING); second.transition(LifecycleState.HANDSHAKING)
        with self.assertRaises(PluginError) as conflict:
            registry.activate(second)
        self.assertEqual(conflict.exception.code, "SCHEME_CONFLICT")
        registry.mark_unhealthy(first)
        with self.assertRaises(PluginError) as missing:
            registry.route("synthetic")
        self.assertEqual(missing.exception.code, "SCHEME_UNOWNED")
        with self.assertRaises(PluginError):
            first.transition(LifecycleState.HEALTHY_ACTIVE)
