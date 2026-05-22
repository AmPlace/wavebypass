import os
import re
from alias import format_name

# 只去技术噪音，不做语义归类
_GROUP_NOISE = re.compile(
    r'[-_\s]*(?:4K|HD|高清|超清|标清|FHD|UHD)$'
    r'|[-_](?:MCP|IPTV|直播)$'
    r'|频道$',
    re.IGNORECASE,
)


class ChannelTemplate:
    """频道模板：name → category 的映射，用于分类归一化"""

    def __init__(self, template_path: str = None):
        # {格式化后的频道名: 分类}
        self.name_to_category: dict[str, str] = {}
        # {分类: [频道名列表]}
        self.category_to_names: dict[str, list[str]] = {}

        if template_path and os.path.exists(template_path):
            self._load(template_path)

    def _load(self, path: str):
        current_cat = '其他'
        with open(path, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                if '#genre#' in line:
                    # 去掉 emoji 前缀，取分类名
                    cat = re.sub(r'^[^一-鿿\w]+', '', line.split(',')[0]).strip()
                    current_cat = cat or '其他'
                    continue
                name = line.strip()
                if name and not name.startswith('#'):
                    key = format_name(name)
                    self.name_to_category[key] = current_cat
                    self.category_to_names.setdefault(current_cat, []).append(name)

    def match(self, channel_name: str) -> str | None:
        """匹配频道名到模板分类，返回分类名或 None"""
        key = format_name(channel_name)
        return self.name_to_category.get(key)

    def get_all_categories(self) -> list[str]:
        return list(self.category_to_names.keys())

    def get_category_names(self, category: str) -> list[str]:
        return self.category_to_names.get(category, [])


# 全局实例
_template_path = os.path.join(os.path.dirname(__file__), 'config', 'template.txt')
channel_template = ChannelTemplate(_template_path)


def normalize_group_name(name: str) -> str:
    """只去技术噪音，不做语义归类"""
    if not name:
        return '其他'
    s = name.strip()
    s = _GROUP_NOISE.sub('', s)
    s = s.strip()
    return s if s else '其他'
