#!/usr/bin/env python3
"""Official multi-scheme StreamGet Provider Plugin.

The adapter table below is the provider boundary for this Plugin.  It is
deliberately independent from WaveFlow's legacy adapters: the Plugin owns the
StreamGet URL/quality/result conventions and the Core only sees the public TV
Provider contract.
"""
from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from typing import Any, Callable, Mapping
from urllib.parse import urlparse

from streamget import (
    AcfunLiveStream,
    BaiduLiveStream,
    BilibiliLiveStream,
    BigoLiveStream,
    BluedLiveStream,
    ChangliaoLiveStream,
    ChzzkLiveStream,
    DouyuLiveStream,
    FaceitLiveStream,
    FlexTVLiveStream,
    HuajiaoLiveStream,
    HuamaoLiveStream,
    InkeLiveStream,
    JDLiveStream,
    KugouLiveStream,
    LangLiveStream,
    LaixiuLiveStream,
    LianJieLiveStream,
    LookLiveStream,
    MaoerLiveStream,
    NeteaseLiveStream,
    PandaLiveStream,
    PicartoLiveStream,
    PopkonTVLiveStream,
    ShopeeLiveStream,
    ShowRoomLiveStream,
    SixRoomLiveStream,
    SoopLiveStream,
    TwitchLiveStream,
    TwitCastingLiveStream,
    WeiboLiveStream,
    YYLiveStream,
    ZhihuLiveStream,
)
from waveflow_plugin_sdk import (
    InvalidResource,
    PluginApplication,
    PluginError,
    ResolveContext,
    StreamDescriptor,
    TVProvider,
    TVReference,
    TemporaryFailure,
)


TTL_SECONDS = 30 * 60
DIRECT_NETWORK_PERMISSION = "network.direct"


@dataclass(frozen=True)
class ProviderSpec:
    stream_class: type
    url_builder: Callable[[str], str]
    quality: str = "OD"
    play_fields: tuple[str, ...] = ("flv_url", "m3u8_url", "record_url")
    transport: str | None = None
    volatile_url: bool = True
    ttl_seconds: int = TTL_SECONDS
    play_url_selector: Callable[[Mapping[str, Any]], str | None] | None = None


def _url(template: str) -> Callable[[str], str]:
    return lambda room_id: template.format(room_id=room_id)


def _weibo_url(room_id: str) -> str:
    if room_id.startswith("1022:"):
        return f"https://weibo.com/show/{room_id}"
    if room_id.isdigit():
        return f"https://weibo.com/u/{room_id}"
    return f"https://weibo.com/show/{room_id}"


# Douyu returns a primary URL plus optional CDN fallbacks.  Keep this policy
# inside the Plugin rather than importing the legacy adapter: the Plugin must
# remain independently runnable in its isolated StreamGet environment.
_DOUYU_PREFERRED_CDN = "douyucdn2.cn"
_DOUYU_BLOCKED_CDN_HOSTS = {"edgesrv.com"}


def _douyu_cdn_score(url: str) -> int:
    """Lower score means higher priority; -1 is a known-bad endpoint."""
    try:
        host = urlparse(url).hostname or ""
    except Exception:
        return 100
    if any(blocked in host for blocked in _DOUYU_BLOCKED_CDN_HOSTS):
        if ":8443" in url:
            return -1
        return 50
    if _DOUYU_PREFERRED_CDN in host:
        return 0
    return 10


def _select_douyu_cdn(urls: list[str]) -> str | None:
    if not urls:
        return None
    scored = [(url, _douyu_cdn_score(url)) for url in urls]
    candidates = [(url, score) for url, score in scored if score >= 0]
    if not candidates:
        # Preserve legacy last-resort behavior if every advertised endpoint
        # is an edgesrv:8443 URL.
        return urls[0]
    candidates.sort(key=lambda item: item[1])
    return candidates[0][0]


def _douyu_play_url(result: Mapping[str, Any]) -> str | None:
    urls: list[str] = []
    primary_url = result.get("flv_url") or result.get("m3u8_url") or ""
    if isinstance(primary_url, str) and primary_url:
        urls.append(primary_url)
    extra = result.get("extra")
    backup_urls = extra.get("backup_url_list") if isinstance(extra, Mapping) else []
    if isinstance(backup_urls, (list, tuple)):
        urls.extend(url for url in backup_urls if isinstance(url, str) and url)
    return _select_douyu_cdn(urls)


# This is the complete bundle boundary.  Do not add Node-backed StreamGet
# providers here: haixiu/liveme/lehai require ExecJS at runtime and are not
# part of this Plugin.
PROVIDER_SPECS: dict[str, ProviderSpec] = {
    "yy": ProviderSpec(YYLiveStream, _url("https://www.yy.com/{room_id}/{room_id}"),
                       play_fields=("flv_url", "record_url"), transport="http_flv"),
    "bigo": ProviderSpec(BigoLiveStream, _url("https://bigo.tv/{room_id}"),
                         play_fields=("m3u8_url", "record_url"), transport="hls"),
    "blued": ProviderSpec(BluedLiveStream, _url("https://blued.com/live/{room_id}"),
                          play_fields=("m3u8_url", "record_url"), transport="hls"),
    "soop": ProviderSpec(SoopLiveStream, _url("https://play.sooplive.com/{room_id}"),
                         play_fields=("m3u8_url", "record_url"), transport="hls"),
    "netease": ProviderSpec(NeteaseLiveStream, _url("https://cc.163.com/{room_id}"), quality="blueray"),
    "pandatv": ProviderSpec(PandaLiveStream, _url("https://www.pandalive.co.kr/{room_id}")),
    "maoer": ProviderSpec(MaoerLiveStream, _url("https://fm.missevan.com/{room_id}")),
    "look": ProviderSpec(LookLiveStream, _url("https://www.look.163.com/live?id={room_id}&")),
    "flextv": ProviderSpec(FlexTVLiveStream, _url("https://www.ttinglive.com/channels/{room_id}/live")),
    "popkontv": ProviderSpec(PopkonTVLiveStream, _url("https://www.popkontv.com/live/view?castId={room_id}")),
    "twitcasting": ProviderSpec(TwitCastingLiveStream, _url("https://twitcasting.tv/{room_id}")),
    "baidu": ProviderSpec(BaiduLiveStream, _url("https://live.baidu.com/?room_id={room_id}&")),
    "weibo": ProviderSpec(WeiboLiveStream, _weibo_url),
    "kugou": ProviderSpec(KugouLiveStream, _url("https://fanxing.kugou.com/{room_id}")),
    "twitch": ProviderSpec(TwitchLiveStream, _url("https://www.twitch.tv/{room_id}")),
    "huajiao": ProviderSpec(HuajiaoLiveStream, _url("https://www.huajiao.com/l/{room_id}")),
    "showroom": ProviderSpec(ShowRoomLiveStream, _url("https://www.showroom-live.com/room/profile?room_id={room_id}")),
    "inke": ProviderSpec(InkeLiveStream, _url("https://webapi.busi.inke.cn/web/live_share_pc?id={room_id}")),
    "acfun": ProviderSpec(AcfunLiveStream, _url("https://live.acfun.cn/{room_id}")),
    "zhihu": ProviderSpec(ZhihuLiveStream, _url("https://www.zhihu.com/theater/{room_id}")),
    "chzzk": ProviderSpec(ChzzkLiveStream, _url("https://chzzk.naver.com/live/{room_id}")),
    "live17": ProviderSpec(LangLiveStream, _url("https://www.lang.live/{room_id}")),
    "langlive": ProviderSpec(LangLiveStream, _url("https://www.lang.live/{room_id}")),
    "changliao": ProviderSpec(ChangliaoLiveStream, _url("https://wap.tlclw.com/{room_id}")),
    "jd": ProviderSpec(JDLiveStream, _url("https://lives.jd.com/{room_id}")),
    "faceit": ProviderSpec(FaceitLiveStream, _url("https://www.faceit.com/players/{room_id}/stream")),
    "lianjie": ProviderSpec(LianJieLiveStream, _url("https://www.lailianjie.com/{room_id}")),
    "sixroom": ProviderSpec(SixRoomLiveStream, _url("https://v.6.cn/{room_id}")),
    "huamao": ProviderSpec(HuamaoLiveStream, _url("https://www.huamao.com/{room_id}")),
    "shopee": ProviderSpec(ShopeeLiveStream, _url("https://live.shopee.com/{room_id}")),
    "laixiu": ProviderSpec(LaixiuLiveStream, _url("https://www.laixiu.com/{room_id}")),
    "picarto": ProviderSpec(PicartoLiveStream, _url("https://picarto.tv/{room_id}")),
    # Keep the legacy Bilibili semantics: the provider always advertises FLV
    # transport, selects FLV before record_url, and leaves volatile_url at
    # the bridge's legacy false/default value.
    "bilibili": ProviderSpec(
        BilibiliLiveStream,
        _url("https://live.bilibili.com/{room_id}"),
        play_fields=("flv_url", "record_url"),
        transport="http_flv",
        volatile_url=False,
    ),
    "douyu": ProviderSpec(
        DouyuLiveStream,
        _url("https://www.douyu.com/{room_id}"),
        play_url_selector=_douyu_play_url,
        ttl_seconds=0,
    ),
}


class StreamGetProvider(TVProvider):
    """Resolve one normalized TV reference with the StreamGet API."""

    def __init__(self, specs: Mapping[str, ProviderSpec] = PROVIDER_SPECS):
        self._specs = specs

    async def _fetch(self, spec: ProviderSpec, url: str) -> dict[str, Any]:
        live = spec.stream_class(cookies="")
        data = await live.fetch_web_stream_data(url)
        stream_obj = await live.fetch_stream_url(data, spec.quality)
        decoded = json.loads(stream_obj.to_json())
        if not isinstance(decoded, dict):
            raise ValueError("StreamGet returned a non-object result")
        return decoded

    def resolve_stream(self, reference: TVReference, context: ResolveContext) -> StreamDescriptor:
        context.raise_if_cancelled()
        spec = self._specs.get(reference.scheme)
        room_id = reference.resource_id.strip("/")
        if spec is None or not room_id:
            raise InvalidResource("StreamGet resource is not supported")

        try:
            result = asyncio.run(self._fetch(spec, spec.url_builder(room_id)))
        except PluginError:
            raise
        except Exception:
            raise TemporaryFailure("StreamGet upstream resolution failed") from None
        context.raise_if_cancelled()

        if not result.get("is_live"):
            raise PluginError("NOT_LIVE", "StreamGet resource is not live", retryable=False)

        if spec.play_url_selector is not None:
            play_url = spec.play_url_selector(result)
        else:
            play_url = next(
                (result.get(field) for field in spec.play_fields
                 if isinstance(result.get(field), str) and result.get(field)),
                None,
            )
        if not play_url:
            raise TemporaryFailure("StreamGet returned no playable URL")
        transport = spec.transport or ("http_flv" if result.get("flv_url") else "hls")
        return StreamDescriptor(
            url=play_url,
            transport=transport,
            headers={},
            ttl_seconds=spec.ttl_seconds,
            expires_at=None,
            volatile_url=spec.volatile_url,
            requires_proxy=False,
        )


def main() -> None:
    identity, version = PluginApplication.identity_args("org.waveflow/streamget-providers")
    app = PluginApplication(identity=identity, version=version, permissions=["network"])
    provider = StreamGetProvider()
    for scheme in PROVIDER_SPECS:
        app.register_tv(scheme, provider)
    app.run()


if __name__ == "__main__":
    main()
