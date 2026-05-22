import os
import re

# 繁简映射
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

_SUB_PATTERN = re.compile(
    r'[\-\_]|'
    r'\(.*?\)|（.*?）|\[.*?\]|「.*?」|'
    r'\s+|\|.*?\|｜|'
    r'频道|高清|标清|超清|4K|8K|HD|SD|FHD|UHD|HEVC|H\.?265|H\.?264|'
    r'中央|电视台|电信|联通|移动|广电'
)

_REPLACE_DICT = {'plus': '+', 'PLUS': '+', '＋': '+'}


def format_name(name: str) -> str:
    s = ''.join(_T2S.get(c, c) for c in name)
    s = _SUB_PATTERN.sub('', s)
    for old, new in _REPLACE_DICT.items():
        s = s.replace(old, new)
    return s.lower()


class Alias:
    def __init__(self, alias_path: str = None):
        self.primary_to_aliases: dict[str, set[str]] = {}
        self.alias_to_primary: dict[str, str] = {}
        self.pattern_to_primary: list[tuple[re.Pattern, str]] = []

        if alias_path and os.path.exists(alias_path):
            with open(alias_path, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith('#') or ',' not in line:
                        continue
                    parts = [p.strip() for p in line.split(',')]
                    primary = parts[0]
                    aliases = set(parts[1:])
                    aliases.add(format_name(primary))
                    self.primary_to_aliases[primary] = aliases
                    for alias in aliases:
                        self.alias_to_primary[alias] = primary
                        if alias.startswith('re:'):
                            try:
                                pattern = re.compile(alias[3:])
                                self.pattern_to_primary.append((pattern, primary))
                            except re.error:
                                pass
                    self.alias_to_primary[primary] = primary

    def get_primary(self, name: str) -> str:
        primary = self.alias_to_primary.get(name)
        if primary:
            return primary
        for pattern, p in self.pattern_to_primary:
            if pattern.search(name):
                return p
        fmt = format_name(name)
        return self.alias_to_primary.get(fmt, name)
