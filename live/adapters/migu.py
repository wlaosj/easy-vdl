import logging
from typing import Dict, Any

from .base import BaseAdapter
from ..core import spider

logger = logging.getLogger(__name__)


class MiguAdapter(BaseAdapter):
    """咪咕直播适配器。"""

    @property
    def platform_name(self) -> str:
        return "migu"

    def is_match(self, url: str) -> bool:
        return "miguvideo.com" in (url or "").lower()

    async def get_room_info(self, url: str, **kwargs) -> Dict[str, Any]:
        stream_data = await spider.get_migu_stream_url(url, kwargs.get("proxy"), kwargs.get("cookies"))
        anchor_name = stream_data.get("anchor_name", "")
        room_id = self._extract_room_id(url)
        avatar_url = stream_data.get("avatar_url", "")
        is_live = bool(stream_data.get("is_live"))

        return {
            "anchor_name": anchor_name,
            "room_id": room_id,
            "avatar_url": avatar_url,
            "is_live": is_live,
            "raw_data": stream_data,
        }

    async def get_stream_url(self, url: str, quality: str, **kwargs) -> Dict[str, Any]:
        stream_data = await spider.get_migu_stream_url(url, kwargs.get("proxy"), kwargs.get("cookies"))
        if not stream_data.get("is_live"):
            return {"is_live": False, "url": None}

        record_url = stream_data.get("record_url") or stream_data.get("m3u8_url") or stream_data.get("flv_url")
        if not record_url:
            logger.warning("[MiguAdapter] 未获取到可用录制地址")
            return {"is_live": False, "url": None}

        play_url = stream_data.get("flv_url") or stream_data.get("m3u8_url") or record_url

        record_format = "flv" if ".flv" in str(record_url).lower() else "m3u8"
        play_format = "flv" if ".flv" in str(play_url).lower() else "m3u8"

        return {
            "url": record_url,
            "format": record_format,
            "play_url": play_url,
            "play_format": play_format,
            "is_live": True,
            "anchor_name": stream_data.get("anchor_name", ""),
        }

    def _extract_room_id(self, url: str) -> str:
        if not url:
            return ""
        return url.split("?")[0].rstrip("/").split("/")[-1]
