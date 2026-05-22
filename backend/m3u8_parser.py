import re
import os
from typing import Optional
from alias import Alias, format_name

# 加载频道别名表
_ALIAS_PATH = os.path.join(os.path.dirname(__file__), 'config', 'alias.txt')
_channel_alias = Alias(_ALIAS_PATH)

# ── 正则：从 #EXTINF 行提取属性 ──

# 匹配 key="value" 或 key='value' 形式的属性
_ATTR_RE = re.compile(r'''(\w[\w-]*)=(?:"([^"]*)"|'([^']*)')''')

# 匹配 #EXTINF 行中的显示名（最后一个逗号之后的部分）
_NAME_RE = re.compile(r',\s*(.+?)\s*$')

# 完整的 M3U 行解析：#EXTINF + 属性 + 名字，紧接着 URL 行
_M3U_ENTRY_RE = re.compile(
    r'#EXTINF:-?[0-9]*\s*(.*?)\s*,\s*(.+?)\s*\n'
    r'(?:(?:[ \t]*\r?\n)*|(?:#EXTVLCOPT:[^\r\n]*(?:\r?\n|$))*)'
    r'((?:https?|rtmp|rtsp)://\S+)',
    re.MULTILINE | re.DOTALL,
)

# 简单的逐行解析用
_EXTINF_RE = re.compile(r'#EXTINF:(.+?),(.+)')
_EXTGRP_RE = re.compile(r'#EXTGRP:\s*(.+)')

# 分辨率 / 编码标签，清洗频道名用
_STRIP_RE = re.compile(
    r'[\s]*[\[\(（【]?\s*'
    r'(?:高清|标清|超清|超高清|[48Kk]|[1-9]\d?[Pp](?:\s*[Ii])?|'
    r'HEVC|H\.?265|H\.?264|AVC|1080|720|4K|2K|FHD|HD|SD|UHD)'
    r'\s*[\]\)）】]?'
    r'|[\-_|/\s]+',
    re.IGNORECASE,
)

# 运营商 / 来源后缀
_PROVIDER_RE = re.compile(
    r'(?:电信|联通|移动|广电|铁通|网通|长宽|鹏博士|官方|源|线路|备用)',
)

# 繁简映射（常用字）
_T2S = {
    '樂':'乐','聲':'声','網':'网','廣':'广','聯':'联','華':'华','國':'国',
    '東':'东','電':'电','視':'视','經':'经','發':'发','動':'动','學':'学',
    '機':'机','區':'区','車':'车','產':'产','業':'业','問':'问','開':'开',
    '長':'长','報':'报','點':'点','號':'号','團':'团','場':'场','處':'处',
    '間':'间','書':'书','術':'术','議':'议','記':'记','設':'设','計':'计',
    '話':'话','題':'题','調':'调','論':'论','辦':'办','營':'营','環':'环',
    '競':'竞','衛':'卫','實':'实','總':'总','統':'统','義':'义','資':'资',
    '運':'运','選':'选','達':'达','進':'进','鄉':'乡','錢':'钱','鐵':'铁',
    '門':'门','陽':'阳','雲':'云','飛':'飞','魚':'鱼','馬':'马','風':'风',
    '齊':'齐','龍':'龙',
}

# 分组名噪音：清洗时去掉的通用后缀/前缀
_GROUP_NOISE = re.compile(
    r'(?:频道|频道$|-MCP$|[-_]\d+$)'  # 频道、-MCP、数字后缀
    r'|[\[\(（【]\s*(?:高清|标清|超清|4K|HD|SD|FHD|UHD|HEVC|H\.?265|H\.?264)\s*[\]\)）】]'  # 分辨率标签
    r'|^[\s\-_]+|[\s\-_]+$'  # 首尾空白/分隔符
)


def normalize_group_name(name: str) -> str:
    """通用分组名归一化：去噪音 + 繁简转换 + 去分隔符"""
    if not name:
        return '其他'
    s = name.strip()
    s = _GROUP_NOISE.sub('', s)
    s = ''.join(_T2S.get(c, c) for c in s)
    s = re.sub(r'[\s\-_|/]+', '', s)
    return s if s else '其他'


def _to_simplified(s: str) -> str:
    return ''.join(_T2S.get(c, c) for c in s)


# 常见源后缀，去重前先去掉
_SOURCE_SUFFIX_RE = re.compile(r'-?(?:MCP|mcp|源|线路|备用|直播|官方)$')


def normalize_channel_name(name: str) -> str:
    """清洗频道名，用于去重比较。优先用别名表匹配主名。"""
    # 先去源后缀再匹配 alias
    stripped = _SOURCE_SUFFIX_RE.sub('', name.strip())
    # 多种尝试：原名 → 去后缀 → format_name
    for candidate in [name, stripped, format_name(stripped), format_name(name)]:
        primary = _channel_alias.get_primary(candidate)
        if primary and primary != candidate:
            return format_name(primary)
    s = name.strip()
    s = _STRIP_RE.sub('', s)
    s = _PROVIDER_RE.sub('', s)
    s = _to_simplified(s)
    s = s.lower().strip()
    return s


def _parse_attrs(attr_str: str) -> dict:
    """从 #EXTINF 的属性字符串中提取 key-value。"""
    return {m.group(1): (m.group(2) or m.group(3)) for m in _ATTR_RE.finditer(attr_str)}


def parse_m3u(text: str) -> list[dict]:
    """
    解析 M3U/M3U8 扩展格式，返回频道列表。

    每个频道 dict:
        name      - 显示名
        url       - 流地址
        logo_url  - 台标 (tvg-logo)
        group_name- 分组 (group-title / #EXTGRP)
        tvg_id    - EPG ID (tvg-id)
        tvg_name  - EPG 名 (tvg-name)
    """
    channels: list[dict] = []

    # 优先用正则整体匹配（处理 EXTINF 和 URL 在相邻行的情况）
    for m in _M3U_ENTRY_RE.finditer(text):
        attr_str, name, url = m.group(1), m.group(2).strip(), m.group(3).strip()
        attrs = _parse_attrs(attr_str)
        channels.append({
            'name': name,
            'url': url,
            'logo_url': attrs.get('tvg-logo', ''),
            'group_name': attrs.get('group-title', '') or '其他',
            'tvg_id': attrs.get('tvg-id', ''),
            'tvg_name': attrs.get('tvg-name', ''),
        })

    if channels:
        return channels

    # 回退：逐行解析（兼容格式不规范的文件）
    lines = text.splitlines()
    i = 0
    current_group = ''
    pending_extinf: Optional[dict] = None

    while i < len(lines):
        line = lines[i].strip()

        if not line or line.startswith('#EXTM3U'):
            i += 1
            continue

        grp_m = _EXTGRP_RE.match(line)
        if grp_m:
            current_group = grp_m.group(1).strip()
            i += 1
            continue

        inf_m = _EXTINF_RE.match(line)
        if inf_m:
            attr_str, name = inf_m.group(1), inf_m.group(2).strip()
            attrs = _parse_attrs(attr_str)
            pending_extinf = {
                'name': name,
                'logo_url': attrs.get('tvg-logo', ''),
                'group_name': attrs.get('group-title', '') or current_group or '其他',
                'tvg_id': attrs.get('tvg-id', ''),
                'tvg_name': attrs.get('tvg-name', ''),
            }
            i += 1
            continue

        if pending_extinf and line.startswith(('http://', 'https://', 'rtmp://', 'rtsp://')):
            ch = {**pending_extinf, 'url': line}
            channels.append(ch)
            pending_extinf = None
            i += 1
            continue

        pending_extinf = None
        i += 1

    if channels:
        return channels

    # 回退：txt 格式（频道名,URL / 分类,#genre#）
    lines = text.splitlines()
    current_group = '其他'
    for line in lines:
        line = line.strip()
        if not line:
            continue
        if '#genre#' in line:
            current_group = line.split(',')[0].strip() or '其他'
            continue
        if line.startswith(('http://', 'https://', 'rtmp://', 'rtsp://')):
            continue
        parts = line.split(',', 1)
        if len(parts) == 2 and parts[1].strip().startswith(('http://', 'https://', 'rtmp://', 'rtsp://')):
            channels.append({
                'name': parts[0].strip(),
                'url': parts[1].strip(),
                'logo_url': '',
                'group_name': current_group,
                'tvg_id': '',
                'tvg_name': '',
            })

    return channels


def deduplicate_channels(channels: list[dict]) -> list[dict]:
    """
    同名频道保留所有 URL，每个 URL 作为独立记录。
    跨源合并由聚合端点（aggregated_channels）处理。
    """
    return channels
