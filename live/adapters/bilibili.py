import logging
import asyncio
from typing import Dict, Any, Optional
from .base import BaseAdapter
from ..core import spider

logger = logging.getLogger(__name__)

class BilibiliAdapter(BaseAdapter):
    """B站平台适配器"""
    
    @property
    def platform_name(self) -> str:
        return "bilibili"
        
    def is_match(self, url: str) -> bool:
        return "bilibili.com" in url

    async def get_room_info(self, url: str, **kwargs) -> Dict[str, Any]:
        """获取直播间信息"""
        # [优化] 获取基础信息（如是否开播）时不使用 Cookie
        # 1. 避免因 Cookie 风控导致高频轮询失败
        # 2. 公开 API (room_init) 不需要 Cookie 也能工作
        # 注意：cookies 仅在 get_stream_url 获取原画流时使用
        
        try:
            # 不传 cookies
            info = await spider.get_bilibili_room_info(url)
            
            return {
                "anchor_name": info.get('anchor_name', ''),
                "room_id": str(info.get('room_id', '')),  # 确保 ID 是字符串
                "avatar_url": info.get('avatar_url', ''),
                "is_live": info.get('live_status', False),
                "raw_data": info
            }
        except Exception as e:
            logger.error(f"Bilibili获取信息失败: {e}")
            return {
                "anchor_name": "",
                "room_id": "", 
                "is_live": False,
                "raw_data": {}
            }

    async def get_stream_url(self, url: str, quality: str, **kwargs) -> Dict[str, Any]:
        """获取真实流地址"""
        # Cookie 已由 Scheduler 统一清洗为标准 HTTP 格式
        cookies = kwargs.get('cookies')
        
        # 1. 映射画质
        quality_map = {
            "原画": "10000",
            "4K": "20000",
            "蓝光": "400",
            "超清": "250",
            "高清": "150"
        }
        qn = quality_map.get(quality, "10000")
        
        try:
            stream_url = None
            try:
                # 优先尝试使用传入的 Cookie (Scheduler 保证了格式正确)
                stream_url = await spider.get_bilibili_stream_data(url, qn=qn, cookies=cookies)
            except Exception as e:
                # 如果带 Cookie 还是报错（如账号失效、风控），自动降级为游客模式重试
                if cookies:
                    logger.warning(f"[BilibiliAdapter] 使用标准化 Cookie 访问失败 ({e})，自动切换至游客模式...")
                    stream_url = await spider.get_bilibili_stream_data(url, qn=qn, cookies=None)
                else:
                    raise e
            
            if not stream_url:
                return {"is_live": False, "url": None}
            
            # 检测真实格式
            is_flv = ".flv" in stream_url
            
            return {
                "url": stream_url,
                "format": "flv" if is_flv else "m3u8",
                "is_live": True,
                "anchor_name": "" 
            }
            
        except Exception as e:
            logger.error(f"[BilibiliAdapter] 获取流地址失败: {e}")
            raise
