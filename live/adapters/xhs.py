import logging
from typing import Dict, Any

from .base import BaseAdapter
from ..core import spider

logger = logging.getLogger(__name__)


class XhsAdapter(BaseAdapter):
    """小红书直播适配器"""

    @property
    def platform_name(self) -> str:
        return "xhs"

    def is_match(self, url: str) -> bool:
        # 小红书 Web / App 链接域名判断
        return ("xhslink.com" in url) or ("xiaohongshu.com" in url) or ("app.xhs.cn" in url)

    async def get_room_info(self, url: str, **kwargs) -> Dict[str, Any]:
        """
        使用 core.spider.get_xhs_stream_url 获取直播信息，并标准化返回
        """
        cookies = kwargs.get("cookies")

        try:
            data = await spider.get_xhs_stream_url(url, cookies=cookies)
        except Exception as e:
            logger.error(f"[XhsAdapter] 获取直播间信息失败: {e}")
            # 兜底返回空信息，保持与其他适配器一致结构
            return {
                "anchor_name": "",
                "room_id": "",
                "avatar_url": None,
                "is_live": False,
                "raw_data": {},
            }

        anchor_name = data.get("anchor_name") or ""
        is_live = bool(data.get("is_live"))

        # room_id：优先从 flv_url 里的 live/{room_id}.flv 提取
        room_id = ""
        flv_url = data.get("flv_url") or data.get("record_url")
        if isinstance(flv_url, str) and "live/" in flv_url:
            try:
                room_id = flv_url.split("live/")[1].split(".")[0]
            except Exception:
                room_id = ""

        # 小红书接口当前没有显式头像字段，先返回 None，后续可根据需要扩展
        avatar_url = data.get("avatar_url") or None

        return {
            "anchor_name": anchor_name,
            "room_id": room_id,
            "avatar_url": avatar_url,
            "is_live": is_live,
            "raw_data": data,
        }

    async def get_stream_url(self, url: str, quality: str, **kwargs) -> Dict[str, Any]:
        """
        目前小红书接口未区分多档画质，这里忽略 quality，直接返回解析到的 flv/m3u8。
        """
        cookies = kwargs.get("cookies")

        try:
            data = await spider.get_xhs_stream_url(url, cookies=cookies)
        except Exception as e:
            logger.error(f"[XhsAdapter] 获取流地址失败: {e}")
            raise

        if not data or not data.get("is_live"):
            return {"is_live": False, "url": None}

        # 优先使用 flv，其次 m3u8
        flv_url = data.get("flv_url") or data.get("record_url")
        m3u8_url = data.get("m3u8_url")

        stream_url = flv_url or m3u8_url
        if not stream_url:
            return {"is_live": False, "url": None}

        is_flv = ".flv" in str(stream_url)

        return {
            "url": stream_url,
            "format": "flv" if is_flv else "m3u8",
            "is_live": True,
            "anchor_name": data.get("anchor_name", ""),
        }

