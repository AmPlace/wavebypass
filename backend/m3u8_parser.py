import re
from typing import Optional

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


def _to_simplified(s: str) -> str:
    return ''.join(_T2S.get(c, c) for c in s)


def normalize_channel_name(name: str) -> str:
    """清洗频道名，用于去重比较。"""
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
            'group_name': attrs.get('group-title', ''),
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
                'group_name': attrs.get('group-title', '') or current_group,
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

    return channels


def deduplicate_channels(channels: list[dict]) -> list[dict]:
    """
    按清洗后的频道名去重，同名频道保留第一个。
    """
    seen: dict[str, int] = {}
    result: list[dict] = []
    for ch in channels:
        key = normalize_channel_name(ch['name'])
        if key in seen:
            continue
        seen[key] = len(result)
        result.append(ch)
    return result
