from __future__ import annotations

from dataclasses import dataclass, field
from urllib.parse import urljoin

import httpx

from core.settings_service import get_effective_settings_sync
from ssrf_guard import assert_safe_target_url


@dataclass(frozen=True)
class FetchPolicy:
    allowed_schemes: set[str] = field(default_factory=lambda: {"http", "https"})
    allow_private: bool | None = None
    allow_loopback: bool | None = None
    max_redirects: int = 5
    connect_timeout: float = 10.0
    read_timeout: float = 30.0
    max_response_bytes: int = 50 * 1024 * 1024
    verify_tls: bool = True


def default_policy(**overrides) -> FetchPolicy:
    settings = get_effective_settings_sync()
    values = {
        "allow_private": settings.allow_private,
        "allow_loopback": settings.allow_loopback,
    }
    values.update(overrides)
    return FetchPolicy(**values)


async def fetch_bytes(
    url: str,
    *,
    headers: dict[str, str] | None = None,
    policy: FetchPolicy | None = None,
) -> tuple[str, bytes, httpx.Headers]:
    policy = policy or default_policy()
    current_url = url
    timeout = httpx.Timeout(policy.read_timeout, connect=policy.connect_timeout)
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=False, verify=policy.verify_tls) as client:
        for redirect_count in range(policy.max_redirects + 1):
            await assert_safe_target_url(
                current_url,
                allow_private=policy.allow_private,
                allow_loopback=policy.allow_loopback,
                allowed_schemes=policy.allowed_schemes,
            )
            async with client.stream("GET", current_url, headers=headers or {}) as resp:
                if resp.status_code in {301, 302, 303, 307, 308}:
                    location = resp.headers.get("location")
                    if not location:
                        raise httpx.HTTPError("redirect missing Location")
                    if redirect_count >= policy.max_redirects:
                        raise httpx.HTTPError("too many redirects")
                    current_url = urljoin(current_url, location)
                    continue
                resp.raise_for_status()
                chunks: list[bytes] = []
                total = 0
                async for chunk in resp.aiter_bytes():
                    total += len(chunk)
                    if total > policy.max_response_bytes:
                        raise httpx.HTTPError("response too large")
                    chunks.append(chunk)
                return str(resp.url), b"".join(chunks), resp.headers
    raise httpx.HTTPError("fetch failed")


async def fetch_text(url: str, **kwargs) -> tuple[str, str, httpx.Headers]:
    final_url, data, headers = await fetch_bytes(url, **kwargs)
    return final_url, data.decode("utf-8", errors="replace"), headers
