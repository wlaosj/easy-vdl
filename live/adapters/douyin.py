import logging
import asyncio
import re
from typing import Dict, Any, Optional
from .base import BaseAdapter
from ..core import spider, stream

logger = logging.getLogger(__name__)

class DouyinAdapter(BaseAdapter):
    """抖音平台适配器"""
    
    @property
    def platform_name(self) -> str:
        return "douyin"
        
    def is_match(self, url: str) -> bool:
        return "douyin.com" in url

    async def get_room_info(self, url: str, **kwargs) -> Dict[str, Any]:
        """获取直播间信息"""
        # 提取 cookies (暂未使用，因为 spider 内部有硬编码)
        # [优化] 强制不通过 kwargs 传入 Cookie，避免污染或风控
        cookies = None
        
        # 判断 API 类型
        is_app_api = 'v.douyin.com' in url or '/user/' in url or 'amemv.com' in url
        
        logger.debug(f"[DouyinAdapter] URL类型判断: is_app_api={is_app_api}, URL={url}")
        
        # 获取原始数据 (带超时保护)
        try:
            if is_app_api:
                room_data = await asyncio.wait_for(
                    spider.get_douyin_app_stream_data(url, cookies=cookies),
                    timeout=30.0
                )
            else:
                room_data = await asyncio.wait_for(
                    spider.get_douyin_web_stream_data(url, cookies=cookies),
                    timeout=30.0
                )
        except asyncio.TimeoutError:
            raise Exception("获取抖音直播间信息超时，请重试")
            
        # 提取标准化信息
        anchor_name = room_data.get('anchor_name', '')
        avatar_url = None
        
        # 1. 主播名称提取 (支持 Web 和 App 接口数据结构)
        if not anchor_name:
            owner = room_data.get('owner', {})
            anchor_name = owner.get('nickname', '')
            
        # 2. 头像提取逻辑 (兼容多种嵌套格式)
        # 优先级: user.avatar_thumb > owner.avatar_thumb > room_data.avatar_thumb
        user_data = room_data.get('user', {}) or room_data.get('owner', {})
        avatar_dict = user_data.get('avatar_thumb', {}) or user_data.get('avatar_medium', {}) or user_data.get('avatar_larger', {})
        
        # 深度兜底
        if not avatar_dict:
            avatar_dict = room_data.get('avatar_thumb', {}) or room_data.get('avatar_medium', {})
            
        if avatar_dict and isinstance(avatar_dict, dict):
            url_list = avatar_dict.get('url_list', [])
            if url_list and len(url_list) > 0:
                avatar_url = url_list[0]
                
        # 3. 房间ID提取
        room_id = str(room_data.get('id_str', '')) or str(room_data.get('id', ''))
        if not room_id:
            owner = room_data.get('owner', {})
            room_id = str(owner.get('web_rid', '')) or str(owner.get('id_str', ''))
            
        # 兜底：如果 API 没返回 room_id，尝试从 URL 提取
        if not room_id or room_id == "None" or room_id == "0":
            extracted_id = self._extract_room_id_from_url(url)
            if extracted_id:
                room_id = extracted_id
                logger.info(f"[DouyinAdapter] 从 URL 成功提取 Room ID: {room_id}")
            
        is_live = room_data.get('status') == 2
        
        logger.debug(f"[DouyinAdapter] 提取结果: anchor={anchor_name}, room_id={room_id}, is_live={is_live}")
        
        return {
            "anchor_name": anchor_name,
            "room_id": room_id,
            "avatar_url": avatar_url,
            "is_live": is_live,
            "raw_data": room_data
        }

    async def get_stream_url(self, url: str, quality: str, **kwargs) -> Dict[str, Any]:
        """获取真实流地址"""
        # 1. 重新获取一次信息以确保拿到最新的流数据
        # (因为 spider 需要重新请求才能拿到实时的流地址)
        info = await self.get_room_info(url, **kwargs)
        room_data = info['raw_data']
        
        if not info['is_live']:
            return {"is_live": False, "url": None}
            
        # 2. 映射画质
        quality_map = {
            "原画": "OD",
            "蓝光": "BD", 
            "超清": "UHD",
            "高清": "HD"
        }
        quality_code = quality_map.get(quality, "OD")
        
        # 3. 解析流
        stream_info = await stream.get_douyin_stream_url(
            room_data,
            quality_code,
            None  # proxy
        )
        
        if not stream_info.get('is_live'):
             return {"is_live": False, "url": None}
             
        # 录制建议链路：优先使用 flv_url（FLV 直连流配合 FFmpeg 的 reconnect 机制更稳定）
        record_url = stream_info.get('flv_url') or stream_info.get('record_url')
        record_format = "flv" if ".flv" in str(record_url) else "m3u8"
        record_fallback_url = stream_info.get('m3u8_url') if record_format == "flv" else stream_info.get('flv_url')
        record_fallback_format = "m3u8" if record_format == "flv" else "flv"

        # 播放建议链路：优先使用 flv，提升浏览器实时播放兼容性
        play_url = stream_info.get('flv_url') or record_url
        play_format = "flv" if ".flv" in str(play_url) else "m3u8"
        fallback_url = stream_info.get('m3u8_url') if play_format == "flv" else stream_info.get('flv_url')
        fallback_format = "m3u8" if play_format == "flv" else "flv"

        return {
            "url": record_url,
            "format": record_format,
            "record_fallback_url": record_fallback_url,
            "record_fallback_format": record_fallback_format if record_fallback_url else None,
            "play_url": play_url,
            "play_format": play_format,
            "flv_url": stream_info.get('flv_url'),
            "m3u8_url": stream_info.get('m3u8_url'),
            "play_fallback_url": fallback_url,
            "play_fallback_format": fallback_format if fallback_url else None,
            "is_live": True,
            "anchor_name": stream_info.get('anchor_name')
        }
        
    def _extract_room_id_from_url(self, url: str) -> Optional[str]:
        """辅助方法：从URL提取ID"""
        try:
            url_without_query = url.split('?')[0]
            if 'live.douyin.com/' in url_without_query:
                return url_without_query.split('live.douyin.com/')[-1]
            elif '/root/live/' in url_without_query:
                return url_without_query.split('/root/live/')[-1].split('/')[0]
            elif '/live/' in url_without_query:
                return url_without_query.split('/live/')[-1].split('/')[0]
            else:
                match = re.search(r'/(\d+)(?:\?|$)', url_without_query)
                if match:
                    return match.group(1)
        except Exception:
            pass
        return None
