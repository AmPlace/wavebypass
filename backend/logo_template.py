"""频道 logo 模板：把"主名 → CDN logo URL"集中维护，一份配置覆盖 alias 的所有变体。

设计要点（和现有去重 / 合并管线的关系）：
- 完全不参与 canonical_key 计算。聚合管线先按 canonical_key 合并完之后，
  本模块只是给已经合并好的频道"贴一张更好看的 logo"，不影响去重 / 分组 /
  EPG 绑定 / 播放路径。
- 配置里写主名（如 "CCTV-1" / "湖南卫视"），加载时复用 m3u8_parser 的
  normalize_channel_name() 算成 canonical_key。这样配置里写一行，alias.txt
  里登记过的所有变体（CCTV-01咪咕 / CCTV1HD / CCTV-1综合ᴴᴰ …）都会命中同
  一张图，无需为每个写法单独配。
- 加载分两层：本地 JSON（随项目走，离线可用）→ 启动后异步拉远程一次覆盖到
  内存（拉失败就维持本地，不重试，不写盘）。

TODO(future settings page): 等设置页落地后，把以下项暴露为可配置：
  - 远程 URL（当前硬编码 https://logo.waveflow.tv/logos.json）
  - 是否启用远程拉取 / 拉取超时 / 是否定时刷新
  - 手动触发刷新接口
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from typing import Any

import httpx

from m3u8_parser import normalize_channel_name


logger = logging.getLogger(__name__)


# 远程模板地址：先硬编码，后续接入设置页后改成读配置项。
LOGO_TEMPLATE_REMOTE_URL = "https://logo.waveflow.tv/logos.json"
# 远程拉取超时；失败就维持本地兜底，不重试。
LOGO_TEMPLATE_REMOTE_TIMEOUT = 8.0


class LogoTemplate:
    """主名 → logo URL 映射；canonical_key 命中即返回。

    线程安全性：read 路径只是 dict.get，GIL 下原子；远程刷新走 _replace_table()
    一次性整表替换，读端不会读到半份数据。
    """

    def __init__(self, local_path: str | None = None):
        self._table: dict[str, str] = {}
        self._cdn_base: str = ""
        self._loaded_source: str = "empty"  # "local" / "remote" / "empty"
        if local_path and os.path.exists(local_path):
            try:
                with open(local_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                self._table = self._build_table(data)
                self._cdn_base = self._extract_cdn_base(data)
                self._loaded_source = "local"
                logger.info(
                    "logo template 本地加载完成: %d 条, cdn_base=%s",
                    len(self._table), self._cdn_base or "(none)",
                )
            except Exception as exc:
                logger.warning("logo template 本地加载失败 (维持空表): %s", exc)

    # ── 公共查询 API ────────────────────────────────────────────────
    def lookup(self, canonical_key: str) -> str:
        if not canonical_key:
            return ""
        return self._table.get(canonical_key, "")

    @property
    def size(self) -> int:
        return len(self._table)

    @property
    def loaded_source(self) -> str:
        return self._loaded_source

    # ── 远程刷新 ───────────────────────────────────────────────────
    async def refresh_from_remote(
        self,
        client: httpx.AsyncClient,
        url: str = LOGO_TEMPLATE_REMOTE_URL,
        timeout: float = LOGO_TEMPLATE_REMOTE_TIMEOUT,
    ) -> bool:
        """启动后调一次。失败就维持当前内存表，按用户要求不重试。"""
        try:
            resp = await client.get(url, timeout=timeout, follow_redirects=True)
            resp.raise_for_status()
            data = resp.json()
        except Exception as exc:
            logger.info(
                "logo template 远程拉取失败 (维持本地 %d 条): %s",
                len(self._table), exc,
            )
            return False

        try:
            new_table = self._build_table(data)
        except Exception as exc:
            logger.warning("logo template 远程数据解析失败: %s", exc)
            return False

        if not new_table:
            logger.info("logo template 远程返回空表，跳过覆盖")
            return False

        self._table = new_table
        self._cdn_base = self._extract_cdn_base(data)
        self._loaded_source = "remote"
        logger.info(
            "logo template 远程加载完成: %d 条, cdn_base=%s",
            len(self._table), self._cdn_base or "(none)",
        )
        return True

    # ── 内部 ───────────────────────────────────────────────────────
    @staticmethod
    def _extract_cdn_base(data: dict[str, Any]) -> str:
        return str((data or {}).get("_cdn_base") or "").rstrip("/")

    @classmethod
    def _build_table(cls, data: dict[str, Any]) -> dict[str, str]:
        if not isinstance(data, dict):
            raise ValueError("logos.json 顶层必须是对象")
        cdn_base = cls._extract_cdn_base(data)
        channels = (data or {}).get("channels") or {}
        if not isinstance(channels, dict):
            raise ValueError("logos.json.channels 必须是对象")

        table: dict[str, str] = {}
        for primary, fname in channels.items():
            if not primary or not isinstance(fname, str) or not fname.strip():
                continue
            key = normalize_channel_name(primary)
            if not key:
                continue
            value = fname.strip()
            if not (value.startswith("http://") or value.startswith("https://") or value.startswith("//")):
                if not cdn_base:
                    # 没配 cdn_base 又给的相对路径：跳过，避免拼出错 URL。
                    continue
                value = f"{cdn_base}/{value.lstrip('/')}"
            table[key] = value
        return table


# ── 全局实例 ────────────────────────────────────────────────────────
_local_path = os.path.join(os.path.dirname(__file__), "config", "logos.json")
logo_template = LogoTemplate(_local_path)


async def refresh_logo_template_from_remote(client: httpx.AsyncClient) -> None:
    """供 lifespan 调用的 wrapper；与 asyncio.create_task 兼容。"""
    await logo_template.refresh_from_remote(client)
