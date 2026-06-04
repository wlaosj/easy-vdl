# -*- coding: utf-8 -*-
import logging
from typing import Dict, Any

from .base import BaseAdapter
from ..core import spider, stream
from ..core.http_clients.async_http import async_req

logger = logging.getLogger(__name__)


class KuaishouAdapter(BaseAdapter):
    """快手直播适配器"""

    @property
    def platform_name(self) -> str:
        return "kuaishou"

    def is_match(self, url: str) -> bool:
        # 支持的快手直播域名
        url_lower = (url or "").lower()
        return "kuaishou.com" in url_lower or "gifshow.com" in url_lower or "chenzhongtech.com" in url_lower

    async def _resolve_url_and_extract_room_id(self, url: str) -> tuple[str, str]:
        """
        解析短链接/重定向链接，并提取 room_id (eid)
        """
        resolved_url = url
        if "v.kuaishou.com" in url or "gifshow.com" in url:
            try:
                redirected = await async_req(url, redirect_url=True)
                if redirected:
                    resolved_url = redirected
                    logger.info(f"[KuaishouAdapter] 短链 {url} 重定向为 {resolved_url}")
            except Exception as e:
                logger.error(f"[KuaishouAdapter] 转换短链失败 {url}: {e}")

        room_id = ""
        import re
        # 兼容两种常见格式: /u/<eid> 和 /fw/live/<eid>
        match = re.search(r'/(?:u|fw/live)/([^/?#\s]+)', resolved_url)
        if match:
            room_id = match.group(1)
        else:
            # 兜底：如果直接传了 eid
            parts = resolved_url.rstrip('/').split('/')
            if parts:
                room_id = parts[-1].split('?')[0]

        return resolved_url, room_id

    async def get_room_info(self, url: str, **kwargs) -> Dict[str, Any]:
        """获取直播间信息"""
        cookies = kwargs.get("cookies")
        resolved_url, room_id = await self._resolve_url_and_extract_room_id(url)

        async def _fetch(cookie_value) -> dict:
            data = await spider.get_kuaishou_stream_data(resolved_url, cookies=cookie_value)
            return {
                "anchor_name": data.get("anchor_name") or "",
                "room_id": room_id,
                "avatar_url": data.get("avatar_url") or "",
                "is_live": bool(data.get("is_live", False)),
                "raw_data": data
            }

        try:
            # Cookie 优先（无 Cookie 容易被限流，Cookie 请求成功率更高）
            if cookies:
                result = await _fetch(cookies)
                return result
            # 无 Cookie 时直接请求
            result = await _fetch(None)
            return result
        except Exception as e:
            logger.error(f"[KuaishouAdapter] 获取直播间信息失败: {e}")
            # 异常时尝试无 Cookie 兜底
            if cookies:
                try:
                    logger.info("[KuaishouAdapter] Cookie 请求异常，尝试无 Cookie 兜底")
                    return await _fetch(None)
                except:
                    pass
            return {
                "anchor_name": "",
                "room_id": room_id,
                "avatar_url": "",
                "is_live": False,
                "raw_data": {}
            }

    async def get_stream_url(self, url: str, quality: str, **kwargs) -> Dict[str, Any]:
        """获取真实录制流地址"""
        cookies = kwargs.get("cookies")
        resolved_url, room_id = await self._resolve_url_and_extract_room_id(url)

        # 映射画质名称到快手定义的画质代码 (OD: 原画, BD: 蓝光, UHD: 超清, HD: 高清, SD: 标清)
        quality_map = {
            "原画": "OD",
            "蓝光": "BD",
            "超清": "UHD",
            "高清": "HD",
            "标清": "SD"
        }
        k_quality = quality_map.get(quality, "OD")

        async def _fetch(cookie_value) -> dict:
            data = await spider.get_kuaishou_stream_data(resolved_url, cookies=cookie_value)
            if not data or not data.get("is_live"):
                return {"is_live": False, "url": None, "raw_data": data}

            stream_data = await stream.get_kuaishou_stream_url(data, k_quality)
            if not stream_data or not stream_data.get("is_live"):
                return {"is_live": False, "url": None, "raw_data": data}

            stream_url = stream_data.get("flv_url") or stream_data.get("m3u8_url") or stream_data.get("record_url")
            if not stream_url:
                return {"is_live": False, "url": None, "raw_data": data}

            is_flv = ".flv" in str(stream_url)

            return {
                "url": stream_url,
                "format": "flv" if is_flv else "m3u8",
                "is_live": True,
                "anchor_name": stream_data.get("anchor_name", "")
            }

        try:
            # Cookie 优先（无 Cookie 容易被限流，Cookie 请求成功率更高）
            if cookies:
                result = await _fetch(cookies)
            else:
                result = await _fetch(None)
            # Cookie 请求失败时，尝试无 Cookie 兜底
            if not result.get("is_live") and cookies:
                logger.info("[KuaishouAdapter] Cookie 请求未获取到流地址，尝试无 Cookie 兜底")
                result = await _fetch(None)
            return result
        except Exception as e:
            logger.error(f"[KuaishouAdapter] 获取流地址失败: {e}")
            # 异常时尝试无 Cookie 兜底
            if cookies:
                try:
                    logger.info("[KuaishouAdapter] Cookie 请求异常，尝试无 Cookie 兜底")
                    result = await _fetch(None)
                    if result.get("is_live"):
                        return result
                except:
                    pass
            raise
