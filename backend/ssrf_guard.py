"""SSRF 防护：校验服务端代拉的目标 URL 是否安全。

设计要点：
- 「硬黑名单」段（云元数据/链路本地/unspecified）永远挡，无论 ALLOW_PRIVATE 如何设置。
  这些地址没有任何合法流媒体用途，是公共代理探测元数据偷凭证的核心目标。
- RFC1918 私网段由 WAVEFLOW_ALLOW_PRIVATE 控制（默认放行），匹配 IPTV 内网源场景
  （RTSP 摄像头、自建 IPTV 网关、组播）。
- DNS 解析后再判断 IP（防 DNS rebinding：攻击者用首次解析返回公网、二次解析返回内网的域名绕过）。
"""

from __future__ import annotations

import asyncio
import ipaddress
import socket
from urllib.parse import urlparse

from core.settings_service import get_effective_settings, get_effective_settings_sync


# 永远挡的网络段（即使 ALLOW_PRIVATE=true 也不放行）
_HARD_BLOCKED_NETWORKS = (
    ipaddress.ip_network("169.254.0.0/16"),   # 链路本地，含 AWS/GCP/Azure 元数据 169.254.169.254
    ipaddress.ip_network("fe80::/10"),         # IPv6 链路本地
    ipaddress.ip_network("0.0.0.0/8"),         # IPv4 unspecified
    ipaddress.ip_network("::/128"),            # IPv6 unspecified
)


class UnsafeTargetError(ValueError):
    """目标 URL 不安全（命中黑名单或被策略拦截）。"""


def _is_hard_blocked(ip: ipaddress._BaseAddress) -> bool:
    return any(ip in net for net in _HARD_BLOCKED_NETWORKS)


def _is_loopback(ip: ipaddress._BaseAddress) -> bool:
    return ip.is_loopback


def _is_private(ip: ipaddress._BaseAddress) -> bool:
    return (
        ip.is_private
        or ip.is_link_local
        or ip.is_reserved
        or ip.is_unspecified
        or ip.is_multicast
    )


def _is_private_hostname(host: str) -> bool:
    value = (host or "").strip().lower().strip("[]")
    return value in {"localhost", "localhost.localdomain"} or value.endswith(".localhost")


def _is_private_ip_literal(value: str) -> bool:
    try:
        ip = ipaddress.ip_address(value)
    except ValueError:
        return False
    return _is_private(ip)


async def resolve_host(host: str) -> list[str]:
    """同步 DNS 解析包到 to_thread，避免阻塞事件循环。"""

    def _resolve() -> list[str]:
        infos = socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)
        return list({info[4][0] for info in infos})

    return await asyncio.to_thread(_resolve)


async def assert_safe_target_url(
    url: str,
    *,
    allow_private: bool | None = None,
    allow_loopback: bool | None = None,
    allowed_schemes: set[str] | None = None,
) -> None:
    """校验目标 URL 是否安全可代理。不安全抛 UnsafeTargetError。

    allow_private=None 时使用全局 ALLOW_PRIVATE；显式传值可覆盖（market 模块按源配置走）。
    """
    settings = await get_effective_settings()
    schemes = allowed_schemes or {"http", "https"}
    parsed = urlparse((url or "").strip())
    if parsed.scheme.lower() not in schemes:
        raise UnsafeTargetError("URL scheme 不被允许")
    host = parsed.hostname
    if not host:
        raise UnsafeTargetError("缺少 hostname")
    if parsed.username or parsed.password:
        raise UnsafeTargetError("URL 不允许包含用户名或密码")

    effective_allow_private = settings.allow_private if allow_private is None else bool(allow_private)
    effective_allow_loopback = settings.allow_loopback if allow_loopback is None else bool(allow_loopback)

    # 1. 字面量预检（IP 直填或 localhost 主机名）
    if _is_private_hostname(host) or _is_private_ip_literal(host):
        if _is_private_hostname(host) and not effective_allow_loopback:
            raise UnsafeTargetError("安全策略已阻止本机地址")
        if not effective_allow_private:
            raise UnsafeTargetError("安全策略已阻止内网或本机地址")
        # 字面量是私网但允许私网：仍要确认不是硬黑名单段（元数据）
        try:
            ip = ipaddress.ip_address(host.strip("[]"))
            if _is_hard_blocked(ip):
                raise UnsafeTargetError("禁止访问元数据/链路本地地址")
        except ValueError:
            pass  # 是主机名不是 IP，交给下面的 DNS 解析

    # 2. DNS 解析后二次校验（防 rebinding）
    try:
        ips = [ipaddress.ip_address(x) for x in await resolve_host(host)]
    except OSError as exc:
        raise UnsafeTargetError(f"域名解析失败: {exc}") from exc
    if not ips:
        raise UnsafeTargetError("域名没有可用解析结果")

    for ip in ips:
        if _is_hard_blocked(ip):
            raise UnsafeTargetError("禁止访问元数据/链路本地地址")

    if not effective_allow_loopback:
        for ip in ips:
            if _is_loopback(ip):
                raise UnsafeTargetError("安全策略已阻止本机地址")

    if not effective_allow_private:
        for ip in ips:
            if _is_private(ip):
                raise UnsafeTargetError("安全策略已阻止解析到内网或本机地址")


def resolve_target_ips_sync(host: str) -> list[ipaddress._BaseAddress]:
    """同步解析并返回 IP 对象列表，供 RTSP（rtsp scheme）等同步路径复用。"""
    infos = socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)
    return [ipaddress.ip_address(info[4][0]) for info in infos]


def assert_safe_host_ips(
    host: str,
    *,
    allow_private: bool | None = None,
    allow_loopback: bool | None = None,
) -> None:
    """同步版校验：给定 hostname，解析后判断。供 RTSP/同步上下文使用。"""
    if not host:
        raise UnsafeTargetError("缺少 hostname")
    settings = get_effective_settings_sync()
    effective_allow_private = settings.allow_private if allow_private is None else bool(allow_private)
    effective_allow_loopback = settings.allow_loopback if allow_loopback is None else bool(allow_loopback)

    if _is_private_hostname(host) or _is_private_ip_literal(host):
        if _is_private_hostname(host) and not effective_allow_loopback:
            raise UnsafeTargetError("安全策略已阻止本机地址")
        if not effective_allow_private:
            raise UnsafeTargetError("安全策略已阻止内网或本机地址")
        try:
            ip = ipaddress.ip_address(host.strip("[]"))
            if _is_hard_blocked(ip):
                raise UnsafeTargetError("禁止访问元数据/链路本地地址")
        except ValueError:
            pass

    try:
        ips = resolve_target_ips_sync(host)
    except OSError as exc:
        raise UnsafeTargetError(f"域名解析失败: {exc}") from exc
    if not ips:
        raise UnsafeTargetError("域名没有可用解析结果")

    for ip in ips:
        if _is_hard_blocked(ip):
            raise UnsafeTargetError("禁止访问元数据/链路本地地址")
    if not effective_allow_loopback:
        for ip in ips:
            if _is_loopback(ip):
                raise UnsafeTargetError("安全策略已阻止本机地址")
    if not effective_allow_private:
        for ip in ips:
            if _is_private(ip):
                raise UnsafeTargetError("安全策略已阻止解析到内网或本机地址")
