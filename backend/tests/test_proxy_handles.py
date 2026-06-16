"""test_proxy_handles

Unit tests for security.proxy_handles (sign / verify / kind / version / expiry / SSRF-recheck).
"""
import os
import sys
import time
import unittest

os.environ["WAVEFLOW_PROXY_HANDLE_SECRET"] = "test-handle-secret-32bytes!!!"  # noqa: F541
os.environ.setdefault("WAVEFLOW_MODE", "nas")
os.environ["WAVEFLOW_DB_PATH"] = ":memory:"
# 清掉可能被其他测试缓存的模块，避免 LRU cache 跨测试污染
for mod in list(sys.modules):
    if mod.startswith("core") or mod in ("database", "security.secrets", "security.proxy_handles"):
        del sys.modules[mod]

# 强行清掉 DeploymentConfig LRU cache（如果还被其他测试的模块引用）
try:
    from core.config import get_deployment_config
    get_deployment_config.cache_clear()
except Exception:
    pass

from security.secrets import derive_key, PROXY_HANDLE_PURPOSE
from security.proxy_handles import (
    HandleError,
    HandleExpired,
    HandleFormatError,
    HandleKindMismatch,
    HandleSignatureError,
    HandleVersionError,
    decode_for_kind,
    issue_handle,
)


class ProxyHandleTest(unittest.TestCase):
    def setUp(self):
        # Re-set env var that may have been popped by other tests' tearDown
        os.environ["WAVEFLOW_PROXY_HANDLE_SECRET"] = "test-handle-secret-32bytes!!!"

    def test_issue_and_decode_roundtrip(self):
        handle = issue_handle(kind="chunk", url="https://cdn.example.com/seg.ts", ttl_seconds=3600)
        payload = decode_for_kind(handle, "chunk")
        self.assertEqual(payload.kind, "chunk")
        self.assertEqual(payload.url, "https://cdn.example.com/seg.ts")
        self.assertTrue(payload.exp > int(time.time()) + 3500)

    def test_tampered_payload_fails(self):
        import json, base64, hmac
        # Manually construct a valid-looking payload so JSON parses, but HMAC fails
        key = derive_key(PROXY_HANDLE_PURPOSE)
        # Build payload with one character changed in URL (not in JSON structure)
        bad_payload = json.dumps({
            "v": 1, "kind": "chunk",
            "url": "https://cdn.example.com/BAD_SEG.ts",
            "exp": int(time.time()) + 3600
        }, separators=(",", ":")).encode()
        # Sign with wrong key → will fail HMAC
        wrong_key = key[:-1] + b'\x00'
        sig = hmac.new(wrong_key, bad_payload, "sha256").digest()
        handle = base64.urlsafe_b64encode(bad_payload).rstrip(b"=").decode() + "." + base64.urlsafe_b64encode(sig).rstrip(b"=").decode()
        with self.assertRaises(HandleSignatureError):
            decode_for_kind(handle, "chunk")

    def test_tampered_sig_fails(self):
        handle = issue_handle(kind="chunk", url="https://cdn.example.com/b.ts")
        parts = handle.rsplit(".", 1)
        tampered = parts[0] + ".aGVsbG8gd29ybGQ"
        with self.assertRaises(HandleSignatureError):
            decode_for_kind(tampered, "chunk")

    def test_expired_handle_fails(self):
        handle = issue_handle(kind="chunk", url="https://cdn.example.com/old.ts", ttl_seconds=1)
        time.sleep(1.1)
        with self.assertRaises(HandleExpired):
            decode_for_kind(handle, "chunk")

    def test_kind_mismatch_fails(self):
        handle = issue_handle(kind="playlist", url="https://cdn.example.com/p.m3u8")
        with self.assertRaises(HandleKindMismatch):
            decode_for_kind(handle, "chunk")

    def test_invalid_base64_fails(self):
        with self.assertRaises(HandleFormatError):
            decode_for_kind("!!!not-base64!!!.!!", "chunk")

    def test_empty_handle_fails(self):
        with self.assertRaises(HandleFormatError):
            decode_for_kind("", "chunk")

    def test_no_signature_segment_fails(self):
        with self.assertRaises(HandleFormatError):
            decode_for_kind("abcde", "chunk")

    def test_version_rejection(self):
        # manual too-low version
        import json, base64, hmac
        bad_payload = json.dumps({"v": 0, "kind": "chunk", "url": "https://x.com/a.ts", "exp": int(time.time()) + 9999}).encode()
        key = derive_key(PROXY_HANDLE_PURPOSE)
        sig = hmac.new(key, bad_payload, "sha256").digest()
        bad_handle = base64.urlsafe_b64encode(bad_payload).rstrip(b"=").decode() + "." + base64.urlsafe_b64encode(sig).rstrip(b"=").decode()
        with self.assertRaises(HandleVersionError):
            decode_for_kind(bad_handle, "chunk")

    def test_image_handle_cannot_be_used_as_chunk(self):
        handle = issue_handle(kind="image", url="https://cdn.example.com/cover.jpg")
        with self.assertRaises(HandleKindMismatch):
            decode_for_kind(handle, "chunk")


if __name__ == "__main__":
    unittest.main()
