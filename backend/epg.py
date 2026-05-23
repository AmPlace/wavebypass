"""EPG XMLTV 拉取、解析、匹配、存储"""

import asyncio
import gzip
import json
import logging
import re
import time
from io import BytesIO
from datetime import datetime, timezone
from xml.etree import ElementTree as ET

import httpx

from m3u8_parser import normalize_channel_name, _to_simplified, _channel_alias
from alias import format_name

logger = logging.getLogger("wavebypass.epg")

# 内置默认 EPG 源
DEFAULT_EPG_SOURCES = [
    {"name": "51zmt", "url": "http://epg.51zmt.top:8000/e.xml.gz"},
]

_EPG_REFRESH_INTERVAL = 6 * 3600  # 6 小时


async def fetch_xmltv(client: httpx.AsyncClient, url: str) -> str | None:
    """拉取 XMLTV 文件（支持 .xml / .xml.gz），返回解码后的文本"""
    try:
        resp = await client.get(url, follow_redirects=True, timeout=30)
        resp.raise_for_status()
        data = resp.content
        if url.endswith('.gz') or resp.headers.get('content-type', '').startswith('application/gzip'):
            data = gzip.decompress(data)
        return data.decode('utf-8', errors='replace')
    except Exception as e:
        logger.warning("拉取 EPG 失败 %s: %s", url, e)
        return None


def _parse_iso_time(ts: str) -> str:
    """将 XMLTV 时间（如 20260524120000 +0800）转成 ISO 8601 UTC"""
    try:
        # 去掉空格，处理时区
        ts = ts.strip()
        dt = datetime.strptime(ts, "%Y%m%d%H%M%S %z")
        return dt.astimezone(timezone.utc).isoformat()
    except Exception:
        return ts


def parse_xmltv(xml_text: str) -> tuple[list[dict], list[dict]]:
    """解析 XMLTV，返回 (epg_channels, programmes)"""
    channels: list[dict] = []
    programmes: list[dict] = []

    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as e:
        logger.warning("XMLTV 解析失败: %s", e)
        return channels, programmes

    for ch_elem in root.findall('channel'):
        cid = ch_elem.get('id', '')
        display_names = [dn.text.strip() for dn in ch_elem.findall('display-name') if dn.text]
        if cid and display_names:
            normalized = [normalize_channel_name(dn) for dn in display_names]
            channels.append({
                'channel_id': cid,
                'display_names': json.dumps(display_names, ensure_ascii=False),
                'normalized_names': json.dumps(normalized, ensure_ascii=False),
            })

    for prog in root.findall('programme'):
        start = prog.get('start', '')
        stop = prog.get('stop', '')
        ch_id = prog.get('channel', '')
        title_elem = prog.find('title')
        desc_elem = prog.find('desc')
        title = title_elem.text.strip() if title_elem is not None and title_elem.text else ''
        desc = desc_elem.text.strip() if desc_elem is not None and desc_elem.text else ''
        if ch_id and start and stop and title:
            programmes.append({
                'channel_id': ch_id,
                'start': _parse_iso_time(start),
                'stop': _parse_iso_time(stop),
                'title': title,
                'description': desc,
            })

    logger.info("XMLTV 解析: %d channels, %d programmes", len(channels), len(programmes))
    return channels, programmes


async def store_epg(source_id: int, channels: list[dict], programmes: list[dict]):
    """存储 EPG 数据，按 source_id 替换旧数据"""
    import database as db
    await db.replace_epg_channels(source_id, channels)
    await db.replace_epg_programs(source_id, programmes)


def build_candidates(aggregated: dict) -> list[str]:
    """从聚合频道数据构建匹配候选列表"""
    candidates = []
    # canonical_key
    if aggregated.get('canonical_key'):
        candidates.append(aggregated['canonical_key'])
    # tvg_id
    if aggregated.get('tvg_id'):
        candidates.append(aggregated['tvg_id'])
    # raw_tvg_id from urls
    for u in aggregated.get('urls', []):
        if u.get('raw_tvg_id'):
            candidates.append(u['raw_tvg_id'])
        if u.get('raw_tvg_name'):
            candidates.append(u['raw_tvg_name'])
        if u.get('raw_name'):
            candidates.append(u['raw_name'])
    candidates.append(aggregated.get('name', ''))
    # normalized
    normalized = list(dict.fromkeys(normalize_channel_name(c) for c in candidates if c))
    return [c for c in candidates if c] + normalized


def match_epg_channel(aggregated: dict, epg_channels: list[dict]) -> dict:
    """
    7 步匹配聚合频道到 EPG channel。
    返回: { epg_channel_id, match_type, confidence, match_status, match_detail }
    """
    candidates = build_candidates(aggregated)
    canonical = aggregated.get('canonical_key', '')
    raw_urls = aggregated.get('urls', [])

    # 构建 EPG 索引：{channel_id: {display_names, normalized_names}}
    epg_index: dict[str, dict] = {}
    for ec in epg_channels:
        epg_index[ec['channel_id']] = {
            'display_names': json.loads(ec.get('display_names', '[]')),
            'normalized_names': json.loads(ec.get('normalized_names', '[]')),
        }

    tried = []
    detail = {'candidates_tried': candidates[:10], 'scores': {}}

    # Step 2: canonical_key 精确匹配 EPG channel_id
    if canonical:
        tried.append(('canonical_key', canonical))
        if canonical in epg_index:
            detail['matched_by'] = 'canonical_key'
            detail['matched_value'] = canonical
            return {'epg_channel_id': canonical, 'match_type': 'canonical_key', 'confidence': 100, 'match_status': 'matched', 'match_detail': json.dumps(detail, ensure_ascii=False)}

    # Step 3: raw_tvg_id 精确匹配
    raw_ids = list(dict.fromkeys(u.get('raw_tvg_id', '') for u in raw_urls if u.get('raw_tvg_id')))
    hits = set()
    for rid in raw_ids:
        tried.append(('raw_tvg_id', rid))
        if rid in epg_index:
            hits.add(rid)
    if len(hits) == 1:
        hid = hits.pop()
        detail['matched_by'] = 'raw_tvg_id'
        detail['matched_value'] = hid
        return {'epg_channel_id': hid, 'match_type': 'raw_tvg_id', 'confidence': 95, 'match_status': 'matched', 'match_detail': json.dumps(detail, ensure_ascii=False)}
    if len(hits) > 1:
        detail['ambiguous_hits'] = list(hits)
        return {'epg_channel_id': '', 'match_type': '', 'confidence': 0, 'match_status': 'ambiguous', 'match_detail': json.dumps(detail, ensure_ascii=False)}

    # Step 4: raw_tvg_name / raw_name / display_name 精确匹配 EPG display-names
    name_candidates = list(dict.fromkeys(
        u.get('raw_tvg_name', '') or u.get('raw_name', '') or ''
        for u in raw_urls
    ))
    name_candidates.append(aggregated.get('name', ''))
    for nc in name_candidates:
        if not nc:
            continue
        tried.append(('name_exact', nc))
        for cid, info in epg_index.items():
            if nc in info['display_names']:
                detail['matched_by'] = 'name_exact'
                detail['matched_value'] = nc
                return {'epg_channel_id': cid, 'match_type': 'name_exact', 'confidence': 90, 'match_status': 'matched', 'match_detail': json.dumps(detail, ensure_ascii=False)}

    # Step 5: normalized candidates 匹配
    norm_candidates = list(dict.fromkeys(normalize_channel_name(c) for c in candidates if c))
    for nc in norm_candidates:
        tried.append(('normalized', nc))
        # 匹配 normalized_names
        for cid, info in epg_index.items():
            if nc in info['normalized_names']:
                detail['matched_by'] = 'normalized'
                detail['matched_value'] = nc
                return {'epg_channel_id': cid, 'match_type': 'normalized', 'confidence': 70, 'match_status': 'matched', 'match_detail': json.dumps(detail, ensure_ascii=False)}
        # 匹配 EPG channel_id 本身（也是 normalized 形式的）
        for cid in epg_index:
            if normalize_channel_name(cid) == nc:
                detail['matched_by'] = 'normalized_channel_id'
                detail['matched_value'] = cid
                return {'epg_channel_id': cid, 'match_type': 'normalized', 'confidence': 70, 'match_status': 'matched', 'match_detail': json.dumps(detail, ensure_ascii=False)}

    # Step 6: alias 表兜底
    for c in candidates:
        if not c:
            continue
        alias_result = _channel_alias.get_primary(c)
        if alias_result and alias_result != c:
            tried.append(('alias', alias_result))
            for cid, info in epg_index.items():
                if alias_result in info['normalized_names'] or normalize_channel_name(cid) == normalize_channel_name(alias_result):
                    detail['matched_by'] = 'alias'
                    detail['matched_value'] = alias_result
                    return {'epg_channel_id': cid, 'match_type': 'alias', 'confidence': 60, 'match_status': 'matched', 'match_detail': json.dumps(detail, ensure_ascii=False)}

    # Step 7: 未匹配
    detail['tried'] = tried[:20]
    return {'epg_channel_id': '', 'match_type': '', 'confidence': 0, 'match_status': 'unmatched', 'match_detail': json.dumps(detail, ensure_ascii=False)}


async def run_epg_matching():
    """对所有聚合频道运行 EPG 匹配，结果写入 channel_epg_map"""
    import database as db
    from main import aggregated_channels  # 避免循环导入

    # 拉取聚合频道
    result = await aggregated_channels()
    channels = result['channels']

    # 获取所有已启用的 EPG 源
    sources = await db.get_epg_sources()
    active_sources = [s for s in sources if s['enabled']]

    if not active_sources:
        logger.warning("无启用的 EPG 源，跳过匹配")
        return

    # 收集所有 EPG channels
    all_epg_channels = []
    for src in active_sources:
        epg_chs = await db.get_epg_channels(src['id'])
        all_epg_channels.extend(epg_chs)

    if not all_epg_channels:
        logger.warning("无 EPG 频道数据，跳过匹配")
        return

    matched = 0
    unmatched = 0
    locked_skipped = 0

    for ch in channels:
        key = ch.get('canonical_key', '')
        if not key:
            continue

        # 检查是否已锁定
        existing = await db.get_channel_epg_map(key)
        if existing and existing.get('locked'):
            locked_skipped += 1
            continue

        # 执行匹配
        epg_result = match_epg_channel(ch, all_epg_channels)
        if existing and existing.get('match_status') == 'locked':
            continue  # 已锁定不覆盖

        epg_source_id = None
        if epg_result['epg_channel_id']:
            # 找到对应的 source_id
            for ec in all_epg_channels:
                if ec['channel_id'] == epg_result['epg_channel_id']:
                    epg_source_id = ec['source_id']
                    break

        await db.upsert_channel_epg_map(
            key,
            epg_source_id=epg_source_id,
            epg_channel_id=epg_result['epg_channel_id'],
            match_type=epg_result['match_type'],
            confidence=epg_result['confidence'],
            match_status=epg_result['match_status'],
            match_detail=epg_result['match_detail'],
            locked=existing.get('locked', 0) if existing else 0,
        )
        if epg_result['match_status'] == 'matched':
            matched += 1
        else:
            unmatched += 1

    logger.info("EPG 匹配完成: %d matched, %d unmatched, %d locked skipped", matched, unmatched, locked_skipped)


async def refresh_epg_sources(client: httpx.AsyncClient | None = None):
    """拉取所有启用的 EPG 源，解析并存储"""
    import database as db

    if client is None:
        client = httpx.AsyncClient(timeout=30.0, follow_redirects=True)

    sources = await db.get_epg_sources()
    active = [s for s in sources if s['enabled']]

    if not active:
        # 初始化默认 EPG 源
        for ds in DEFAULT_EPG_SOURCES:
            try:
                await db.add_epg_source(ds['name'], ds['url'])
            except Exception:
                pass
        sources = await db.get_epg_sources()
        active = [s for s in sources if s['enabled']]

    for src in active:
        logger.info("刷新 EPG 源: %s", src['url'])
        try:
            xml_text = await fetch_xmltv(client, src['url'])
            if not xml_text:
                await db.update_epg_source(src['id'], last_status='fetch_failed')
                continue

            channels, programmes = parse_xmltv(xml_text)
            if not channels:
                await db.update_epg_source(src['id'], last_status='parse_empty')
                continue

            await store_epg(src['id'], channels, programmes)
            now = datetime.now(timezone.utc).isoformat()
            await db.update_epg_source(src['id'], last_fetched_at=now, last_status='ok')
            logger.info("EPG 源 %s 刷新完成: %d channels, %d programmes", src['url'], len(channels), len(programmes))
        except Exception as e:
            logger.exception("EPG 源 %s 刷新异常: %s", src['url'], e)
            await db.update_epg_source(src['id'], last_status=str(e)[:200])

    # 匹配
    await run_epg_matching()
