# -*- coding: utf-8 -*-
import logging
import json
from typing import Dict, Any, Optional
from .base import BaseAdapter
from ..core.http_clients.async_http import async_req

logger = logging.getLogger(__name__)

class CCAdapter(BaseAdapter):
    """网易CC直播平台适配器"""
    
    @property
    def platform_name(self) -> str:
        return "cc"
        
    def is_match(self, url: str) -> bool:
        return "cc.163.com" in url

    async def get_room_info(self, url: str, **kwargs) -> Dict[str, Any]:
        """
        获取直播间信息
        """
        room_id = self._extract_room_id(url)
        if not room_id:
            logger.warning(f"[CCAdapter] 无法从 URL 提取 Room ID: {url}")
            return {
                "anchor_name": "",
                "room_id": "",
                "avatar_url": None,
                "is_live": False,
                "raw_data": {}
            }
            
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        }
        
        try:
            # 1. 第一步：获取 channel_id
            api_1 = f"https://api.cc.163.com/v1/activitylives/anchor/lives?anchor_ccid={room_id}"
            res_str1 = await async_req(api_1, headers=headers)
            if not res_str1:
                raise ValueError("API 1 返回数据为空")
                
            res_data1 = json.loads(res_str1)
            room_meta = res_data1.get("data", {}).get(room_id, {})
            channel_id = room_meta.get("channel_id")
            
            if not channel_id:
                logger.warning(f"[CCAdapter] 未能解析到 CuteID {room_id} 的 channel_id")
                return {
                    "anchor_name": room_meta.get("nickname", ""),
                    "room_id": room_id,
                    "avatar_url": None,
                    "is_live": False,
                    "raw_data": {}
                }
                
            # 2. 第二步：获取真实直播详情
            api_2 = f"https://cc.163.com/live/channel/?channelids={channel_id}&anchor_ccid={room_id}"
            res_str2 = await async_req(api_2, headers=headers)
            if not res_str2:
                raise ValueError("API 2 返回数据为空")
                
            res_data2 = json.loads(res_str2)
            lives = res_data2.get("data", [])
            if not lives:
                logger.warning(f"[CCAdapter] 频道 {channel_id} 没有有效的直播间数据")
                return {
                    "anchor_name": room_meta.get("nickname", ""),
                    "room_id": room_id,
                    "avatar_url": None,
                    "is_live": False,
                    "raw_data": {}
                }
                
            room_info = lives[0]
            is_live = room_info.get("status") == 1
            
            return {
                "anchor_name": room_info.get("nickname", "") or room_meta.get("nickname", ""),
                "room_id": room_id,
                "avatar_url": room_info.get("purl") or None,
                "is_live": is_live,
                "raw_data": room_info
            }
        except Exception as e:
            logger.error(f"[CCAdapter] 获取网易CC直播间 {room_id} 信息失败: {e}")
            return {
                "anchor_name": "",
                "room_id": room_id,
                "avatar_url": None,
                "is_live": False,
                "raw_data": {}
            }

    async def get_stream_url(self, url: str, quality: str, **kwargs) -> Dict[str, Any]:
        """
        获取录制流地址 (优先使用 HTTP-FLV)
        """
        info = await self.get_room_info(url, **kwargs)
        if not info.get("is_live"):
            return {
                "url": None,
                "format": "flv",
                "is_live": False,
                "anchor_name": info.get("anchor_name", "")
            }
            
        room_info = info["raw_data"]
        
        # 1. 优先使用 quickplay 里的高质量 FLV 线路
        quickplay = room_info.get("quickplay") or {}
        resolution_data = quickplay.get("resolution", {})
        
        selected_url = None
        
        if resolution_data:
            # 映射画质选择
            quality_map = {
                "原画": "blueray",
                "蓝光": "blueray",
                "超清": "ultra",
                "高清": "high",
                "标准": "standard"
            }
            target_res = quality_map.get(quality, "blueray")
            
            # 如果目标清晰度不存在，则按优先级选择最高画质
            res_info = resolution_data.get(target_res)
            if not res_info:
                for q in ["blueray", "ultra", "high", "standard"]:
                    if q in resolution_data:
                        res_info = resolution_data[q]
                        break
                        
            if not res_info and resolution_data:
                res_info = list(resolution_data.values())[0]
                
            if res_info:
                cdn_urls = res_info.get("cdn", {})
                priority = quickplay.get("priority", ["wy", "ali", "tx", "hs", "ks"])
                
                # 按照网易官方推荐优先级匹配 CDN 流
                for cdn_name in priority:
                    if cdn_name in cdn_urls:
                        selected_url = cdn_urls[cdn_name]
                        logger.info(f"[CCAdapter] 成功选取网易CC流: CDN={cdn_name}, 目标清晰度={target_res}")
                        break
                        
                if not selected_url and cdn_urls:
                    selected_url = list(cdn_urls.values())[0]
                    
        # 2. 如果 quickplay 没有匹配到地址，兜底使用默认 m3u8 地址
        if not selected_url:
            selected_url = room_info.get("m3u8")
            logger.info("[CCAdapter] 未能提取到 FLV 清晰度流，回退到默认 M3U8 流地址")
            
        if not selected_url:
            return {
                "url": None,
                "format": "flv",
                "is_live": False,
                "anchor_name": info.get("anchor_name", "")
            }
            
        # 探测流类型是 flv 还是 m3u8
        is_m3u8 = ".m3u8" in selected_url.split("?")[0].lower()
        
        return {
            "url": selected_url,
            "format": "m3u8" if is_m3u8 else "flv",
            "is_live": True,
            "anchor_name": info.get("anchor_name", "")
        }

    def _extract_room_id(self, url: str) -> str:
        """
        提取 CC 房间 ID / 昵称号
        支持:
        - https://cc.163.com/241095246/
        - https://cc.163.com/241095246
        """
        try:
            parts = [p for p in url.split("/") if p.strip()]
            if parts:
                room_part = parts[-1].split("?")[0]
                return room_part
        except Exception as e:
            logger.error(f"[CCAdapter] 解析 Room ID 失败: {e}")
        return ""
