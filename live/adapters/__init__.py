from typing import Optional
from .base import BaseAdapter
from .douyin import DouyinAdapter
from .douyu import DouyuAdapter
from .bilibili import BilibiliAdapter
from .huya import HuyaAdapter
from .xhs import XhsAdapter
from .youtube import YoutubeAdapter
from .migu import MiguAdapter
from .kuaishou import KuaishouAdapter
from .cc import CCAdapter
from .twitch import TwitchAdapter


# 注册所有适配器
_ADAPTERS = [
    DouyinAdapter(),
    DouyuAdapter(),
    BilibiliAdapter(),
    HuyaAdapter(),
    XhsAdapter(),
    YoutubeAdapter(),
    MiguAdapter(),
    KuaishouAdapter(),
    CCAdapter(),
    TwitchAdapter(),
]

def get_adapter(url: str) -> Optional[BaseAdapter]:
    """根据URL获取合适的适配器"""
    for adapter in _ADAPTERS:
        if adapter.is_match(url):
            return adapter
    return None

def get_adapter_by_platform(platform: str) -> Optional[BaseAdapter]:
    """根据平台名称获取适配器"""
    for adapter in _ADAPTERS:
        if adapter.platform_name == platform:
            return adapter
    return None
