import re
import os
from typing import Optional
from urllib.parse import parse_qs, urlparse
from alias import Alias, format_name

# 加载频道别名表
_ALIAS_PATH = os.path.join(os.path.dirname(__file__), 'config', 'alias.txt')
_channel_alias = Alias(_ALIAS_PATH)

# ── 正则：从 #EXTINF 行提取属性 ──

# 匹配 key="value" 或 key='value' 形式的属性
_ATTR_RE = re.compile(r'''(\w[\w-]*)=(?:"([^"]*)"|'([^']*)')''')

_STREAM_URL_PREFIXES = ('http://', 'https://', 'rtmp://', 'rtsp://', 'migu://', 'hnntv://', 'nmtv://', 'gzstv://', 'sxbc://', 'xjtv://', 'jstv://', 'sdtv://', 'sdly://', 'douyin://', 'douyu://', 'huya://', 'hbtv://', 'hntv://', 'redbook://', 'tvb://', 'nowtv://', 'tiktok://', 'kuaishou://', 'bilibili://', 'yy://', 'bigo://', 'blued://', 'soop://', 'netease://', 'pandatv://', 'maoer://', 'look://', 'flextv://', 'popkontv://', 'twitcasting://', 'baidu://', 'weibo://', 'kugou://', 'twitch://', 'huajiao://', 'showroom://', 'inke://', 'acfun://', 'haixiu://', 'liveme://', 'zhihu://', 'chzzk://', 'live17://', 'langlive://', 'changliao://', 'jd://', 'faceit://', 'lianjie://', 'sixroom://', 'lehai://', 'huamao://', 'shopee://', 'laixiu://', 'picarto://', 'youtube://', 'adapter://')

# 简单的逐行解析用
_EXTINF_RE = re.compile(r'#EXTINF:([^,]*),(.*)')
_EXTGRP_RE = re.compile(r'#EXTGRP:\s*(.+)')
_YOUTUBE_VIDEO_ID_RE = re.compile(r'^[a-zA-Z0-9_-]{11}$')
_YOUTUBE_CHANNEL_ID_RE = re.compile(r'^UC[a-zA-Z0-9_-]{20,}$')

# 分辨率 / 编码 / 通用线路标注，清洗频道名用。
# 设计要点：
#   - 不含 [48Kk]：它会把编号数字当分辨率删掉（GDTV8→GDTV、HUBEI4→HUBEI）
#   - 4K/8K 用负向先行断言限定（前面不能是字母数字），避免吃 CCTV4K 的数字段
#   - 含咪咕/高码/IPTV/总台等通用噪音（对全部频道通用，不限 CCTV）
_STRIP_RE = re.compile(
    r'[\s]*[\[\(（【]?\s*'
    r'(?:高清|标清|超清|超高清|'
    r'[1-9]\d?[Pp](?:\s*[Ii])?|'      # 1080p, 720i
    r'HEVC|H\.?265|H\.?264|AVC|1080|720|2K|FHD|HD|SD|UHD|'
    r'(?<![0-9A-Za-z])4K|(?<![0-9A-Za-z])8K|'  # 4K/8K 前不能是字母数字
    r'\d{2,3}\s*fps|'            # fps 尾数：4K25、50fps
    r'咪咕|高码|(?<=[\u4e00-\u9fff])IPTV|总台)'
    r'\s*[\]\)）】]?'
    r'|[\-_|/\s]+|频道$|广播电视总台',
    re.IGNORECASE,
)

# 行尾括号源标注：(备用)/(测试)/(纯净) 等。只剥明确的源标注词，
# 不剥 (国内电影)/(外国电影) 这种内容分类。
_SOURCE_TAG_RE = re.compile(r'[（(]\s*(?:备用|测试|纯净|原画|备用源|线路\d*|超清|高清)\s*[)）]$')

# 运营商 / 来源后缀。
# 注意：已移除 '移动'（误伤"深圳移动电视"/"移动戏曲"）、'源'（误伤地名"沂源"/"济源"）。
# '源' 只剥行尾，靠下方 _SOURCE_SUFFIX_RE 的 '源$'。
_PROVIDER_RE = re.compile(
    r'(?:电信|联通|广电|铁通|网通|长宽|鹏博士|官方|线路|备用)',
)

# 繁简转换：用 zhconv 库（完整准确，替代手维护字表）
try:
    from zhconv import convert as _zh_convert
except ImportError:
    _zh_convert = None


def _to_simplified(s: str) -> str:
    return _zh_convert(s, 'zh-cn') if _zh_convert else s


def _primary_channel_key(primary: str) -> str:
    compact = re.sub(r'[\s\-_]+', '', _to_simplified(primary)).lower()
    if compact in {'cctv4k', 'cctv8k'}:
        return compact
    return format_name(primary)


# 常见来源/线路后缀，去重前先去掉
_SOURCE_SUFFIX_RE = re.compile(
    r'(?:[\s\-_]*(?:MCP|IPTV|直播|官方)|-?(?:源|线路|备用))+$',
    re.IGNORECASE,
)


def clean_channel_display_name(name: str) -> str:
    s = _SOURCE_SUFFIX_RE.sub('', name.strip()).strip()
    return s or name.strip()


def normalize_channel_name(name: str) -> str:
    """清洗频道名，用于去重比较。优先用别名表匹配主名。"""
    # 先去源后缀再匹配 alias
    stripped = clean_channel_display_name(name)
    # 多种尝试：原名 → 去后缀 → format_name
    for candidate in [name, stripped, format_name(stripped), format_name(name)]:
        primary = _channel_alias.get_primary(candidate)
        known_alias = _channel_alias.alias_to_primary.get(candidate) == primary
        if primary and (primary != candidate or known_alias):
            return _primary_channel_key(primary)
    s = _to_simplified(stripped)   # 繁简转换先行，确保后续 _STRIP_RE 能匹配繁体后缀
    # 剥行尾括号源标注：(备用)/(测试)/(纯净)/(原画) 等，但保留 (国内电影) 这种内容分类
    s = _SOURCE_TAG_RE.sub('', s)
    s = _STRIP_RE.sub('', s)
    s = _PROVIDER_RE.sub('', s)
    s = s.lower().strip()
    return s


def _parse_attrs(attr_str: str) -> dict:
    """从 #EXTINF 的属性字符串中提取 key-value。"""
    return {m.group(1).lower(): (m.group(2) or m.group(3)) for m in _ATTR_RE.finditer(attr_str)}


def _is_stream_url(line: str) -> bool:
    return line.strip().startswith(_STREAM_URL_PREFIXES)


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

    # 逐行解析 EXTINF + URL 对，兼容任意属性顺序和中间的空行/扩展注释。
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
            if pending_extinf and pending_extinf.get('group_name') == '其他':
                pending_extinf['group_name'] = current_group or '其他'
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

        if pending_extinf and _is_stream_url(line):
            ch = {
                **pending_extinf,
                'url': line,
                'source_type': detect_source_type(line),
                'adapter': adapter_provider(line),
                'youtube_video_id': parse_youtube_video_id(line),
                'youtube_channel_id': parse_youtube_channel_id(line),
            }
            channels.append(ch)
            pending_extinf = None
            i += 1
            continue

        if line.startswith('#'):
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
        if _is_stream_url(line):
            continue
        parts = line.split(',', 1)
        if len(parts) == 2 and _is_stream_url(parts[1]):
            url = parts[1].strip()
            channels.append({
                'name': parts[0].strip(),
                'url': url,
                'source_type': detect_source_type(url),
                'adapter': adapter_provider(url),
                'youtube_video_id': parse_youtube_video_id(url),
                'youtube_channel_id': parse_youtube_channel_id(url),
                'logo_url': '',
                'group_name': current_group,
                'tvg_id': '',
                'tvg_name': '',
            })

    return channels


def _is_youtube_host(host: str) -> bool:
    return (
        host in {'youtu.be', 'www.youtu.be'}
        or host == 'youtube.com'
        or host.endswith('.youtube.com')
        or host == 'youtube-nocookie.com'
        or host.endswith('.youtube-nocookie.com')
    )


def _youtube_scheme_parts(parsed) -> list[str]:
    return [part for part in [parsed.netloc, *parsed.path.split('/')] if part]


def parse_youtube_video_id(url: str) -> str:
    """Extract an embeddable YouTube video id from common share/live URLs."""
    raw = (url or '').strip()
    if not raw:
        return ''
    try:
        parsed = urlparse(raw)
    except ValueError:
        return ''

    host = (parsed.netloc or '').lower().split('@')[-1].split(':')[0]
    path_parts = [part for part in parsed.path.split('/') if part]
    candidate = ''

    if parsed.scheme.lower() == 'youtube':
        scheme_parts = _youtube_scheme_parts(parsed)
        if len(scheme_parts) == 1:
            candidate = scheme_parts[0]
        elif len(scheme_parts) >= 2 and scheme_parts[0] in {'live', 'embed', 'shorts'}:
            candidate = scheme_parts[1]
    elif host in {'youtu.be', 'www.youtu.be'}:
        candidate = path_parts[0] if path_parts else ''
    elif _is_youtube_host(host):
        query_video_id = parse_qs(parsed.query).get('v', [''])[0]
        if query_video_id:
            candidate = query_video_id
        elif len(path_parts) >= 2 and path_parts[0] in {'live', 'embed', 'shorts'}:
            candidate = path_parts[1]

    if _YOUTUBE_VIDEO_ID_RE.fullmatch(candidate or ''):
        return candidate
    return ''


def parse_youtube_channel_id(url: str) -> str:
    """Extract a YouTube channel id from channel/live URLs when it is explicit."""
    raw = (url or '').strip()
    if not raw:
        return ''
    try:
        parsed = urlparse(raw)
    except ValueError:
        return ''

    scheme = parsed.scheme.lower()
    host = (parsed.netloc or '').lower().split('@')[-1].split(':')[0]
    parts = _youtube_scheme_parts(parsed) if scheme == 'youtube' else [part for part in parsed.path.split('/') if part]

    candidate = ''
    if scheme == 'youtube':
        if parts and _YOUTUBE_CHANNEL_ID_RE.fullmatch(parts[0] or ''):
            candidate = parts[0]
        elif len(parts) >= 2 and parts[0] == 'channel':
            candidate = parts[1]
    elif _is_youtube_host(host):
        if len(parts) >= 2 and parts[0] == 'channel':
            candidate = parts[1]

    if _YOUTUBE_CHANNEL_ID_RE.fullmatch(candidate or ''):
        return candidate
    return ''


def is_youtube_live_channel_url(url: str) -> bool:
    raw = (url or '').strip()
    if not raw:
        return False
    try:
        parsed = urlparse(raw)
    except ValueError:
        return False

    scheme = parsed.scheme.lower()
    host = (parsed.netloc or '').lower().split('@')[-1].split(':')[0]
    parts = _youtube_scheme_parts(parsed) if scheme == 'youtube' else [part for part in parsed.path.split('/') if part]
    if scheme == 'youtube':
        return bool(parts and parts[-1].lower() == 'live')
    if _is_youtube_host(host):
        return bool(parts and parts[-1].lower() == 'live')
    return False


def is_youtube_url(url: str) -> bool:
    try:
        parsed = urlparse((url or '').strip())
        host = (parsed.netloc or '').lower().split('@')[-1].split(':')[0]
    except ValueError:
        return False
    return parsed.scheme.lower() == 'youtube' or _is_youtube_host(host)


def adapter_provider(url: str) -> str:
    value = (url or '').strip()
    try:
        parsed = urlparse(value)
    except ValueError:
        return ''
    scheme = parsed.scheme.lower()
    if scheme == 'migu':
        return 'migu'
    if scheme == 'hnntv':
        return 'hnntv'
    if scheme == 'nmtv':
        return 'nmtv'
    if scheme == 'gzstv':
        return 'gzstv'
    if scheme == 'sxbc':
        return 'sxbc'
    if scheme == 'xjtv':
        return 'xjtv'
    if scheme == 'jstv':
        return 'jstv'
    if scheme == 'sdtv':
        return 'sdtv'
    if scheme == 'sdly':
        return 'sdly'
    if scheme == 'douyin':
        return 'douyin'
    if scheme == 'douyu':
        return 'douyu'
    if scheme == 'huya':
        return 'huya'
    if scheme == 'hbtv':
        return 'hbtv'
    if scheme == 'hntv':
        return 'hntv'
    if scheme == 'tvb':
        return 'tvb'
    if scheme == 'nowtv':
        return 'nowtv'
    if scheme == 'redbook':
        return 'redbook'
    if scheme == 'tiktok':
        return 'tiktok'
    if scheme == 'kuaishou':
        return 'kuaishou'
    if scheme == 'bilibili':
        return 'bilibili'
    if scheme == 'yy':
        return 'yy'
    if scheme == 'bigo':
        return 'bigo'
    if scheme == 'blued':
        return 'blued'
    if scheme == 'soop':
        return 'soop'
    if scheme == 'netease':
        return 'netease'
    if scheme == 'pandatv':
        return 'pandatv'
    if scheme == 'maoer':
        return 'maoer'
    if scheme == 'look':
        return 'look'
    if scheme == 'flextv':
        return 'flextv'
    if scheme == 'popkontv':
        return 'popkontv'
    if scheme == 'twitcasting':
        return 'twitcasting'
    if scheme == 'baidu':
        return 'baidu'
    if scheme == 'weibo':
        return 'weibo'
    if scheme == 'kugou':
        return 'kugou'
    if scheme == 'twitch':
        return 'twitch'
    if scheme == 'huajiao':
        return 'huajiao'
    if scheme == 'showroom':
        return 'showroom'
    if scheme == 'inke':
        return 'inke'
    if scheme == 'acfun':
        return 'acfun'
    if scheme == 'haixiu':
        return 'haixiu'
    if scheme == 'liveme':
        return 'liveme'
    if scheme == 'zhihu':
        return 'zhihu'
    if scheme == 'chzzk':
        return 'chzzk'
    if scheme == 'live17':
        return 'live17'
    if scheme == 'langlive':
        return 'langlive'
    if scheme == 'changliao':
        return 'changliao'
    if scheme == 'jd':
        return 'jd'
    if scheme == 'faceit':
        return 'faceit'
    if scheme == 'lianjie':
        return 'lianjie'
    if scheme == 'sixroom':
        return 'sixroom'
    if scheme == 'lehai':
        return 'lehai'
    if scheme == 'huamao':
        return 'huamao'
    if scheme == 'shopee':
        return 'shopee'
    if scheme == 'laixiu':
        return 'laixiu'
    if scheme == 'picarto':
        return 'picarto'
    if scheme == 'youtube':
        return 'youtube'
    if scheme == 'adapter':
        return (parsed.netloc or '').lower().split('@')[-1].split(':')[0]
    return ''


def detect_source_type(url: str) -> str:
    value = (url or '').strip().lower()
    if parse_youtube_video_id(url):
        return 'youtube'
    if is_youtube_url(url):
        if parse_youtube_channel_id(url) or is_youtube_live_channel_url(url):
            return 'youtube'
        return 'unsupported_youtube_url'
    if adapter_provider(url):
        return 'adapter'
    if value.startswith('rtsp://'):
        return 'rtsp'
    if '/rtp/' in value or '/udp/' in value or '%2frtp%2f' in value or '%2fudp%2f' in value:
        return 'mpegts'
    if (
        value.endswith(('.ts', '.m2ts', '.mts'))
        or '.ts?' in value
        or '.m2ts?' in value
        or '.mts?' in value
    ):
        return 'mpegts'
    if value.endswith('.flv') or '.flv?' in value:
        return 'http_flv'
    return 'hls'


def deduplicate_channels(channels: list[dict]) -> list[dict]:
    """
    同名频道保留所有 URL，每个 URL 作为独立记录。
    跨源合并由聚合端点（aggregated_channels）处理。
    """
    return channels
