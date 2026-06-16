"""媒体代理新路由组。

公共入口
========

* ``GET /api/media/channel/{channel_id}/playlist.m3u8`` —— 频道入口；按稳定 ID 解析
  source、签发 signed handle、返回主播放列表。同时承载电台 station_id（共用）。
* ``GET /api/media/channel/{channel_id}/cover`` —— adapter 封面元数据
  （仅 IPTV 频道；电台无意义）。
* ``GET /api/media/proxy/playlist/{handle}`` —— 子 playlist / variant playlist。
* ``GET /api/media/proxy/chunk/{handle}`` —— TS / fMP4 / init / KEY URI。
* ``GET /api/media/proxy/stream/{handle}`` —— MPEG-TS / FLV 直连流。
* ``GET /api/media/proxy/rtsp/{handle}`` —— RTSP→HLS playlist（基于 handle.url 与 compat）。
* ``GET /api/media/proxy/image/{handle}`` —— adapter 封面图（Referer 防盗链白名单兜底）。
* ``POST /api/media/proxy/release/{cache_key}`` —— wide playlist 主动释放（按稳定 cache_key）。

管理员入口
==========

* ``POST /api/admin/probes/url`` —— 仅供管理员手动测试任意 URL 的可达性，
  不流式代理回客户端。

参数与凭证
==========

非匿名访问时 ``access_token=wbm_...`` 仅在「来源是 Media Credential」时被透传到
重写产物的子 URL；管理员 Session 走 HttpOnly Cookie，不会出现在 URL 中。

每个 handle 路由都会再次跑 SSRF 校验（策略可能在签发后变化）。
"""

from __future__ import annotations

import asyncio
import logging
from urllib.parse import urlparse

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from fastapi.responses import RedirectResponse, StreamingResponse

from core.m3u8_rewriter import RewriteContext, rewrite_m3u8
from security.dependencies import (
    MediaAccessContext,
    require_admin,
    resolve_media_access,
)
from security.proxy_context import ProxyContext, get_registry as get_proxy_context_registry
from security.proxy_handles import (
    DEFAULT_TTL_BY_KIND,
    HandleError,
    HandleExpired,
    HandleSignatureError,
    decode_for_kind,
    issue_handle,
)
from ssrf_guard import UnsafeTargetError, assert_safe_target_url


logger = logging.getLogger("media.proxy")

router = APIRouter(tags=["media"])


# ── helpers ────────────────────────────────────────────────────────────────


def _build_rewrite_context(
    *,
    base_url: str,
    src_id: str,
    src_label: str,
    ctx_id: str = "",
    access_ctx: MediaAccessContext,
    rtsp_compat: int = 0,
    proxy_segments: bool = True,
) -> RewriteContext:
    return RewriteContext(
        base_url=base_url,
        src_id=src_id,
        src_label=src_label,
        ctx_id=ctx_id,
        propagated_access_token=access_ctx.propagated_access_token or "",
        proxy_segments=proxy_segments,
        rtsp_compat=rtsp_compat,
    )


def _ctx_to_request_headers(ctx: ProxyContext | None, *, fallback_referer: str = "") -> dict[str, str]:
    """ProxyContext → 上游 HTTP Headers。无 ctx 走默认。"""
    headers: dict[str, str] = {}
    if not ctx:
        return headers
    if ctx.no_ua:
        if ctx.custom_ua:
            headers["User-Agent"] = ctx.custom_ua
    else:
        if ctx.custom_ua:
            headers["User-Agent"] = ctx.custom_ua
    if ctx.referer:
        headers["Referer"] = ctx.referer
    elif fallback_referer:
        headers["Referer"] = fallback_referer
    if ctx.cookie:
        headers["Cookie"] = ctx.cookie
    return headers


async def _validate_handle_url_or_403(handle_url: str, *, allowed_schemes: set[str]) -> None:
    try:
        await assert_safe_target_url(handle_url, allowed_schemes=allowed_schemes)
    except UnsafeTargetError as exc:
        logger.info("handle SSRF reject: %s", exc)
        raise HTTPException(status_code=403, detail=str(exc)) from exc


def _safe_decode(handle: str, *, expected_kind: str) -> "decoded":
    try:
        return decode_for_kind(handle, expected_kind)
    except HandleSignatureError as exc:
        logger.info("handle bad signature: %s", exc)
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except HandleExpired as exc:
        logger.info("handle expired: %s", exc)
        raise HTTPException(status_code=410, detail=str(exc)) from exc
    except HandleError as exc:
        logger.info("handle invalid (kind=%s): %s", expected_kind, exc)
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc


# ── 频道入口（稳定 ID）──────────────────────────────────────────────────


@router.get("/api/media/channel/{channel_key}/playlist.m3u8")
async def media_channel_playlist(
    channel_key: str,
    request: Request,
    access: MediaAccessContext = Depends(resolve_media_access),
):
    """按稳定 ID 解析频道 → 选 best source → 签 handle → 返回主播放列表。

    ``channel_key`` 可以是：

    * 电台 station_id（如 ``cnr_1``）
    * IPTV 聚合频道的 ``canonical_key``

    后端按存在性优先匹配电台。
    """
    import main as _m  # 延迟导入，避开循环

    # 1. 电台优先
    if channel_key in _m.CURRENT_STREAMS or channel_key in _m.STATION_FETCHER_MAP or channel_key in _m.DIRECT_STREAM_STATIONS:
        return await _serve_radio_station_playlist(channel_key, request, access)

    # 2. IPTV 聚合频道（canonical_key）
    return await _serve_iptv_channel_playlist(channel_key, request, access)


async def _serve_radio_station_playlist(
    station_id: str,
    request: Request,
    access: MediaAccessContext,
) -> Response:
    import main as _m

    if _m._is_geo_blocked(station_id, request):
        raise HTTPException(status_code=403, detail="该电台因地域限制不可用。")

    if station_id in _m.DIRECT_STREAM_STATIONS:
        # 这条路径仅给 hls.js / video，不应到这里；指给 .stream
        raise HTTPException(status_code=400, detail="该电台是直连音频流，请使用 stream 入口。")

    real_url = _m.CURRENT_STREAMS.get(station_id)
    if not real_url:
        # 触发刷新一次
        try:
            real_url = await _m.refresh_station_stream_url(station_id)
        except HTTPException:
            raise
    if not real_url:
        raise HTTPException(status_code=503, detail="该电台播放地址尚未准备好。")

    parsed = urlparse(real_url)
    if parsed.scheme.lower() not in ("http", "https"):
        raise HTTPException(status_code=400, detail="电台上游 scheme 不被允许")
    await _validate_handle_url_or_403(real_url, allowed_schemes={"http", "https"})

    # 拉真实 m3u8（使用电台 CDN headers）
    try:
        upstream = await _m.fetch_real_m3u8_text(real_url, station_id)
        upstream.raise_for_status()
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"真实 m3u8 拉取失败: {exc}") from exc

    base_url = str(upstream.url)
    rewrite_ctx = _build_rewrite_context(
        base_url=base_url,
        src_id=f"station:{station_id}",
        src_label=f"station:{station_id}",
        access_ctx=access,
        proxy_segments=True,
    )
    body = rewrite_m3u8(upstream.text, rewrite_ctx)
    return Response(content=body, media_type="application/vnd.apple.mpegurl")


async def _serve_iptv_channel_playlist(
    canonical_key: str,
    request: Request,
    access: MediaAccessContext,
) -> Response:
    import main as _m

    channels, _groups = await _m._get_aggregated_iptv_channels()
    channel = next((ch for ch in channels if ch.get("canonical_key") == canonical_key), None)
    if not channel:
        raise HTTPException(status_code=404, detail="频道不存在")

    sources = _m._sorted_sources([
        s for s in channel.get("urls", []) if _m._is_supported_export_source(s, healthy_only=True)
    ])
    if not sources:
        raise HTTPException(status_code=503, detail="没有可用播放源")

    # 选第一个能播的；逐个尝试以兼容 smart playlist 历史行为
    last_exc: HTTPException | None = None
    for source in sources:
        try:
            return await _serve_iptv_source_playlist(source, canonical_key, access)
        except HTTPException as exc:
            last_exc = exc
            continue
    raise last_exc or HTTPException(status_code=503, detail="所有源均不可用")


async def _serve_iptv_source_playlist(
    source: dict,
    canonical_key: str,
    access: MediaAccessContext,
) -> Response:
    """对单一 source 解析 → 拉上游 → 重写。供频道入口和 smart playlist 共用。"""
    import main as _m

    source_type = _m._source_type(source)
    custom_ua = str(source.get("custom_ua") or "")
    referer = str(source.get("referer") or "")
    raw_url = str(source.get("url") or "").strip()
    if not raw_url:
        raise HTTPException(status_code=502, detail="source url 为空")

    # adapter scheme：先 resolve 拿到真实 HTTP/RTSP URL + headers
    if source_type == "adapter":
        try:
            resolved = await _m.resolve_adapter_source(raw_url, _m.http_client)
        except _m.AdapterResolveError as exc:
            raise HTTPException(status_code=exc.status_code, detail=exc.to_payload()) from exc

        resolved_url = str(resolved.get("url") or "").strip()
        if not resolved_url:
            raise HTTPException(status_code=502, detail="adapter 未返回播放地址")
        resolved_st = str(resolved.get("source_type") or "hls").strip().lower()
        headers = resolved.get("headers") if isinstance(resolved.get("headers"), dict) else {}
        ad_ua = str(headers.get("User-Agent") or headers.get("user-agent") or custom_ua)
        ad_ref = str(headers.get("Referer") or headers.get("referer") or referer)
        ad_cookie = str(headers.get("Cookie") or headers.get("cookie") or "")
        no_ua = bool(headers.get("no_ua") or headers.get("No-UA"))
        return await _serve_resolved_source_playlist(
            resolved_url=resolved_url,
            resolved_st=resolved_st,
            custom_ua=ad_ua,
            referer=ad_ref,
            cookie=ad_cookie,
            no_ua=no_ua,
            canonical_key=canonical_key,
            access=access,
        )

    # 直接 source（非 adapter）
    return await _serve_resolved_source_playlist(
        resolved_url=raw_url,
        resolved_st=source_type,
        custom_ua=custom_ua,
        referer=referer,
        cookie="",
        no_ua=False,
        canonical_key=canonical_key,
        access=access,
    )


async def _serve_resolved_source_playlist(
    *,
    resolved_url: str,
    resolved_st: str,
    custom_ua: str,
    referer: str,
    cookie: str,
    no_ua: bool,
    canonical_key: str,
    access: MediaAccessContext,
) -> Response:
    """已经解析到 HTTP/RTSP URL 的 source 的统一入口。"""
    import main as _m

    src_label = f"channel:{canonical_key}"

    # 是否需要建 ProxyContext（动态 header）
    ctx_id = ""
    has_dynamic_headers = bool(custom_ua or referer or cookie)
    if has_dynamic_headers:
        ctx = ProxyContext(
            custom_ua=custom_ua,
            referer=referer,
            cookie=cookie,
            no_ua=no_ua,
            upstream_url=resolved_url,
            source_type=resolved_st,
            source_id=canonical_key,
        )
        ctx_id = get_proxy_context_registry().put(ctx)

    if resolved_st == "rtsp":
        # 直接签 rtsp handle 并 302；让客户端命中 /api/media/proxy/rtsp/{handle}
        if not _m.config_rtsp_proxy_enabled():
            raise HTTPException(status_code=503, detail="RTSP 代理已禁用")
        handle = issue_handle(
            kind="rtsp",
            url=resolved_url,
            src=src_label,
            src_id=canonical_key,
            ctx=ctx_id,
            compat=0,
        )
        token_qs = (
            f"?access_token={access.propagated_access_token}"
            if access.propagated_access_token
            else ""
        )
        return RedirectResponse(f"/api/media/proxy/rtsp/{handle}{token_qs}", status_code=307)

    if resolved_st in {"mpegts", "http_flv"}:
        handle = issue_handle(
            kind="stream",
            url=resolved_url,
            src=src_label,
            src_id=canonical_key,
            ctx=ctx_id,
        )
        suffix = "?stream_type=http_flv" if resolved_st == "http_flv" else ""
        token_qs = (
            f"{'&' if suffix else '?'}access_token={access.propagated_access_token}"
            if access.propagated_access_token
            else ""
        )
        return RedirectResponse(f"/api/media/proxy/stream/{handle}{suffix}{token_qs}", status_code=307)

    # HLS：复用 main.iptv_wide_playlist 的内部实现（通过 cache key + ctx_id）
    return await _m.serve_iptv_wide_playlist_by_source(
        upstream_url=resolved_url,
        ctx_id=ctx_id,
        src_label=src_label,
        canonical_key=canonical_key,
        access=access,
    )


# ── Cover (channel-based) ─────────────────────────────────────────────────


@router.get("/api/media/channel/{canonical_key}/cover")
async def media_channel_cover(
    canonical_key: str,
    request: Request,
):
    """返回该频道 adapter 类源的封面元数据（cover_url/avatar_url 已经是 image handle）。

    使用轻量 CoverCache：
    - 频道索引缓存 60s，不每次全量聚合；
    - Adapter fetch 受 Semaphore(4) 限制；
    - 同一 key 的并发请求合并为一次执行；
    - 非 adapter 频道直接返回 logo_url 兜底并缓存。
    """
    from core.cover_cache import get_cover_cache

    cache = get_cover_cache()
    channel = await cache.get_channel(canonical_key)
    if not channel:
        raise HTTPException(status_code=404, detail="频道不存在")

    sources = channel.get("urls", []) or []
    import main as _m
    adapter_source = next((s for s in sources if _m._source_type(s) == "adapter"), None)
    adapter_url = adapter_source["url"] if adapter_source else None

    return await cache.get_or_fetch(
        canonical_key=canonical_key,
        adapter_source_url=adapter_url,
        logo_url=channel.get("logo_url") or "",
        channel_name=channel.get("name") or "",
    )


# ── Handle 路由（playlist / chunk / stream / rtsp / image）────────────────


@router.get("/api/media/proxy/playlist/{handle}")
async def media_proxy_playlist(
    handle: str,
    access: MediaAccessContext = Depends(resolve_media_access),
):
    import main as _m

    payload = _safe_decode(handle, expected_kind="playlist")
    await _validate_handle_url_or_403(payload.url, allowed_schemes={"http", "https"})

    ctx = get_proxy_context_registry().get(payload.ctx) if payload.ctx else None
    headers = _ctx_to_request_headers(ctx)

    try:
        upstream = await _m.http_client.get(
            payload.url, follow_redirects=True, timeout=8, headers=headers
        )
        upstream.raise_for_status()
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"拉取 M3U8 失败: {exc}") from exc

    base_url = str(upstream.url)
    rewrite_ctx = _build_rewrite_context(
        base_url=base_url,
        src_id=payload.src_id,
        src_label=payload.src,
        ctx_id=payload.ctx,
        access_ctx=access,
        proxy_segments=True,
    )
    body = rewrite_m3u8(upstream.text, rewrite_ctx)
    return Response(
        content=body,
        media_type="application/vnd.apple.mpegurl",
        headers={"Cache-Control": "no-cache, no-store, must-revalidate"},
    )


@router.get("/api/media/proxy/chunk/{handle}")
async def media_proxy_chunk(
    handle: str,
    _: MediaAccessContext = Depends(resolve_media_access),
):
    import main as _m

    payload = _safe_decode(handle, expected_kind="chunk")
    await _validate_handle_url_or_403(payload.url, allowed_schemes={"http", "https"})

    ctx = get_proxy_context_registry().get(payload.ctx) if payload.ctx else None
    headers = _ctx_to_request_headers(ctx, fallback_referer="")
    if not ctx and "User-Agent" not in headers:
        headers["User-Agent"] = (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 Chrome/130.0.0.0 Safari/537.36"
        )

    try:
        upstream = await _m.http_client.get(
            payload.url, follow_redirects=True, headers=headers
        )
        upstream.raise_for_status()
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"拉取分片失败: {exc}") from exc

    content_type = upstream.headers.get("content-type", "")
    if not content_type or content_type == "application/octet-stream":
        path = urlparse(payload.url).path
        ext = path.rsplit(".", 1)[-1].lower() if "." in path else ""
        content_type = {
            "ts": "video/MP2T",
            "m4s": "video/mp4",
            "mp4": "video/mp4",
            "fmp4": "video/mp4",
            "m4v": "video/mp4",
            "aac": "audio/aac",
            "mp3": "audio/mpeg",
        }.get(ext, "application/octet-stream")
    return Response(content=upstream.content, media_type=content_type)


@router.get("/api/media/proxy/stream/{handle}")
async def media_proxy_stream(
    handle: str,
    request: Request,
    stream_type: str = "",
    _: MediaAccessContext = Depends(resolve_media_access),
):
    import main as _m

    payload = _safe_decode(handle, expected_kind="stream")
    await _validate_handle_url_or_403(payload.url, allowed_schemes={"http", "https"})

    ctx = get_proxy_context_registry().get(payload.ctx) if payload.ctx else None
    parsed = urlparse(payload.url)
    upstream_headers = {
        "User-Agent": (ctx.custom_ua if ctx else "") or _m.CDN_REQUEST_HEADERS["User-Agent"],
        "Accept": "*/*",
        "Connection": "keep-alive",
        "Referer": (ctx.referer if ctx and ctx.referer else f"{parsed.scheme}://{parsed.netloc}/"),
    }
    if ctx and ctx.cookie:
        upstream_headers["Cookie"] = ctx.cookie

    return await _m.serve_iptv_proxy_stream_response(
        request=request,
        target_url=payload.url,
        upstream_headers=upstream_headers,
        stream_type=stream_type,
    )


@router.get("/api/media/proxy/rtsp/{handle}")
async def media_proxy_rtsp(
    handle: str,
    _: MediaAccessContext = Depends(resolve_media_access),
):
    import main as _m

    payload = _safe_decode(handle, expected_kind="rtsp")
    # rtsp 校验同步路径
    parsed = urlparse(payload.url)
    if parsed.scheme.lower() != "rtsp":
        raise HTTPException(status_code=400, detail="rtsp handle scheme 不匹配")
    if not parsed.hostname:
        raise HTTPException(status_code=400, detail="rtsp handle host 缺失")
    try:
        from ssrf_guard import assert_safe_host_ips
        assert_safe_host_ips(parsed.hostname)
    except UnsafeTargetError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc

    ctx = get_proxy_context_registry().get(payload.ctx) if payload.ctx else None
    custom_ua = ctx.custom_ua if ctx else ""

    return await _m.serve_rtsp_playlist_response(
        target_url=payload.url,
        custom_ua=custom_ua,
        compat=bool(payload.compat),
    )


@router.get("/api/media/proxy/image/{handle}")
async def media_proxy_image(
    handle: str,
    request: Request,
):
    """封面图片 handle。仅供匿名/受限来源访问；不接受 chunk/playlist URL。"""
    import main as _m

    # 封面图允许匿名（与原 require_browse_access 一致），但仍要保护：
    # 这里要求至少能浏览。
    from security.dependencies import require_browse_access as _rb
    await _rb(request)

    payload = _safe_decode(handle, expected_kind="image")
    await _validate_handle_url_or_403(payload.url, allowed_schemes={"http", "https"})

    referer = _m._cover_img_referer_for(payload.url)
    if not referer:
        raise HTTPException(status_code=403, detail="该域名不在封面代理白名单中")

    try:
        upstream = await _m.http_client.get(
            payload.url,
            headers={"User-Agent": "Mozilla/5.0", "Referer": referer},
            follow_redirects=True,
        )
        upstream.raise_for_status()
    except Exception:
        raise HTTPException(status_code=502, detail="封面图片获取失败")

    return Response(
        content=upstream.content,
        media_type=upstream.headers.get("content-type", "image/jpeg"),
        headers={
            "Cache-Control": "public, max-age=86400",
            "Access-Control-Allow-Origin": "*",
        },
    )


# ── 释放（按稳定 cache key）────────────────────────────────────────────


@router.post("/api/media/proxy/release/{cache_key}")
async def media_proxy_release(
    cache_key: str,
    _: MediaAccessContext = Depends(resolve_media_access),
):
    import main as _m
    released = _m.release_iptv_wide_playlist_by_key(cache_key)
    return {"released": released}


# ── 管理员 URL probe ──────────────────────────────────────────────────────


@router.post("/api/admin/probes/url")
async def admin_probe_url(
    payload: dict,
    _admin: dict = Depends(require_admin),
):
    """管理员手动测试任意 URL 的可达性。

    限制：

    * 仅 ``http``/``https``；
    * SSRF 校验；
    * 仅返回 status/headers 摘要，不流式回客户端；
    * 上游响应大小限制 2 MiB（封面/简短 m3u8 足够）。
    """
    import main as _m

    url = str((payload or {}).get("url") or "").strip()
    if not url:
        raise HTTPException(status_code=400, detail="url 不能为空")
    try:
        await assert_safe_target_url(url, allowed_schemes={"http", "https"})
    except UnsafeTargetError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc

    try:
        upstream = await _m.http_client.get(
            url,
            follow_redirects=True,
            timeout=8.0,
            headers={"User-Agent": _m.CDN_REQUEST_HEADERS["User-Agent"]},
        )
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"探测失败: {exc}") from exc

    body_preview = upstream.content[: 2 * 1024]
    try:
        text_preview = body_preview.decode("utf-8", errors="replace")
    except Exception:
        text_preview = ""
    return {
        "ok": True,
        "status": upstream.status_code,
        "final_url": str(upstream.url),
        "content_type": upstream.headers.get("content-type", ""),
        "content_length": int(upstream.headers.get("content-length") or 0),
        "preview": text_preview,
    }
