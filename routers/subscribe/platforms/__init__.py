"""
平台适配器模块

自动注册所有平台适配器，并提供统一的访问接口。
"""
from .base import PlatformAdapter
from .registry import PlatformRegistry, registry
from .douyin import DouyinAdapter
from .instagram import InstagramAdapter
from .youtube import YouTubeAdapter
from .bilibili import BilibiliAdapter
from .tiktok import TikTokAdapter
from .xiaohongshu import XiaohongshuAdapter
from .netease import NetEaseAdapter
from .x import XAdapter

# 初始化适配器并将它们注册到注册表
douyin_adapter = DouyinAdapter()
instagram_adapter = InstagramAdapter()
youtube_adapter = YouTubeAdapter()
bilibili_adapter = BilibiliAdapter()
tiktok_adapter = TikTokAdapter()
xiaohongshu_adapter = XiaohongshuAdapter()
netease_adapter = NetEaseAdapter()
x_adapter = XAdapter()

registry.register(douyin_adapter)
registry.register(instagram_adapter)
registry.register(youtube_adapter)
registry.register(bilibili_adapter)
registry.register(tiktok_adapter)
registry.register(xiaohongshu_adapter)
registry.register(netease_adapter)
registry.register(x_adapter)

# 导出
__all__ = [
    "PlatformAdapter",
    "PlatformRegistry",
    "registry",
    "DouyinAdapter",
    "InstagramAdapter",
    "YouTubeAdapter",
    "BilibiliAdapter",
    "TikTokAdapter",
    "XiaohongshuAdapter",
    "NetEaseAdapter",
    "XAdapter",
]
