"""电台真实播放地址抓取器。

这个文件先使用“工厂模式”的轻量写法：
用一个字典把“电台 ID”映射到“对应的异步抓取函数”。
后续新增电台时，只需要新增一个 fetch_xxx 函数，并注册到 STATION_FETCHER_MAP。
"""

import logging
import os
from collections.abc import Awaitable, Callable

import httpx


# 定义抓取函数的类型别名：
# 每个抓取函数都不接收参数，并且会异步返回一个字符串形式的 m3u8 播放地址。
StationFetcher = Callable[[], Awaitable[str]]

# 创建抓取器专用日志记录器。
# 后续 Docker 中可以通过 docker logs 查看真实抓取失败原因。
logger = logging.getLogger("wavebypass.fetchers")


# Hit FM 获取真实 m3u8 地址的接口。
HITFM_API_URL = "https://www.hitoradio.com/newweb/hichannel.php"


# Hit FM 请求头。
# 这些字段来自浏览器抓包，作用是尽量模拟官网 Ajax 请求。
HITFM_HEADERS = {
    "Accept": "*/*",
    "Accept-Language": "zh-CN,zh;q=0.9",
    "Cache-Control": "no-cache",
    "Connection": "keep-alive",
    "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
    "Origin": "https://www.hitoradio.com",
    "Referer": "https://www.hitoradio.com/newweb/onair_n_ajax.php",
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/147.0.0.0 Safari/537.36"
    ),
}


# Hit FM Ajax 表单参数。
# channelID=1 表示当前抓取 Hit FM 主频道。
HITFM_PAYLOAD = {
    "channelID": "1",
    "action": "getLIVEURL",
}


# Hit FM 请求超时时间。
# 这里保持和你原始测试脚本一样的 10 秒，避免后台任务长时间卡死。
HITFM_TIMEOUT = httpx.Timeout(10.0)


def build_hitfm_headers() -> dict[str, str]:
    """构造 Hit FM 请求头。

    Cookie 不硬编码到仓库，避免开源时泄露会话信息。
    如果接口后续必须依赖 Cookie，请在 `.env` 中配置 HITFM_COOKIE。
    """

    # 复制基础请求头，避免直接修改全局常量。
    headers = HITFM_HEADERS.copy()

    # 从环境变量读取 Cookie，例如 PHPSESSID=xxxx。
    hitfm_cookie = os.getenv("HITFM_COOKIE", "").strip()

    # Cookie 不为空时才加入请求头。
    if hitfm_cookie:
        headers["Cookie"] = hitfm_cookie
    else:
        logger.warning("未配置 HITFM_COOKIE，将尝试不带 Cookie 请求 Hit FM。")

    return headers


async def fetch_hitfm() -> str:
    """抓取 Hit FM 的最新 m3u8 地址。

    逻辑来自你的 requests 测试脚本，但改成了 httpx 纯异步写法：
    1. 向 Hit FM 官网 Ajax 接口伪装请求，拿到带 token 的真实 m3u8 地址。
    2. 再用这个真实地址请求 CDN，确认当前服务器 IP 可以拿到播放列表。
    3. CDN 验证成功后，把真实 m3u8 地址返回给后台定时任务保存。
    """

    # 构造带可选 Cookie 的请求头。
    headers = build_hitfm_headers()

    # 第一步：向 Hit FM 官网接口请求最新真实 m3u8 地址。
    async with httpx.AsyncClient(timeout=HITFM_TIMEOUT, follow_redirects=True) as client:
        response = await client.post(HITFM_API_URL, headers=headers, data=HITFM_PAYLOAD)

    # 如果官网接口返回 4xx 或 5xx，这里会抛出 httpx.HTTPStatusError。
    response.raise_for_status()

    # 官网接口直接返回纯文本 URL，所以去掉首尾空白即可。
    real_url = response.text.strip()

    # 基础校验：真实播放地址必须是 http 或 https URL。
    if not real_url.startswith(("http://", "https://")):
        raise ValueError("Hit FM 返回内容不是有效 URL，可能 Cookie 失效或请求被拦截。")

    # 第二步：验证 CDN 是否允许当前服务器 IP 请求 m3u8。
    # verify=False 对应你原始脚本中的 requests.get(..., verify=False)。
    async with httpx.AsyncClient(
        timeout=HITFM_TIMEOUT,
        follow_redirects=True,
        verify=False,
    ) as cdn_client:
        cdn_response = await cdn_client.get(
            real_url,
            headers={"User-Agent": HITFM_HEADERS["User-Agent"]},
        )

    # CDN 返回非 2xx 时，说明 token、IP 或 CDN 规则可能存在问题。
    cdn_response.raise_for_status()

    # 简单确认返回内容不为空，避免把空响应当成可播放地址。
    if not cdn_response.text.strip():
        raise ValueError("Hit FM CDN 返回了空的 m3u8 内容。")

    # 记录前几行内容，方便部署时确认后台确实拿到了播放列表。
    logger.info("Hit FM CDN 验证通过，m3u8 前 5 行：%s", cdn_response.text.splitlines()[:5])

    # 返回带 token 的真实 m3u8 地址，由 main.py 写入 CURRENT_STREAMS。
    return real_url


async def fetch_ufo() -> str:
    """抓取 UFO Radio 的最新 m3u8 地址。

    当前是占位实现，直接返回一个带 token 参数的 mock 地址。
    后续你可以在这里填写真实抓包、解析、签名或跳转跟随逻辑。
    """

    return "https://mock-cdn.example.com/ufo/live/playlist.m3u8?token=mock-ufo-token"


# 电台抓取器注册表。
# key 是前端或 API 使用的电台 ID，value 是负责刷新该电台真实播放地址的异步函数。
STATION_FETCHER_MAP: dict[str, StationFetcher] = {
    "hitfm": fetch_hitfm,
    "ufo": fetch_ufo,
}
