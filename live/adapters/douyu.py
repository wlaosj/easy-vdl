import asyncio
import logging
import re
from typing import Any, Dict, Optional

import httpx

from .base import BaseAdapter

logger = logging.getLogger(__name__)

try:
    from streamget import DouyuLiveStream
except Exception:  # pragma: no cover
    DouyuLiveStream = None


class DouyuAdapter(BaseAdapter):
    """斗鱼直播适配器（基于 streamget）。"""
    MAX_RETRIES = 2
    RETRY_DELAY_SEC = 0.4

    @property
    def platform_name(self) -> str:
        return "douyu"

    def is_match(self, url: str) -> bool:
        return "douyu.com" in url.lower()

    async def get_room_info(self, url: str, **kwargs) -> Dict[str, Any]:
        if DouyuLiveStream is None:
            raise Exception("streamget 未正确安装，无法解析斗鱼直播")

        live = DouyuLiveStream()
        room_dict = {}
        last_error = None
        candidates = self._candidate_urls(url)

        for candidate in candidates:
            for attempt in range(1, self.MAX_RETRIES + 1):
                try:
                    room_data = await asyncio.wait_for(live.fetch_web_stream_data(candidate), timeout=30.0)
                    room_dict = self._to_dict(room_data)
                    if room_dict:
                        break
                except Exception as e:
                    last_error = e
                    logger.warning(
                        f"[DouyuAdapter] 获取直播间信息失败: attempt={attempt}/{self.MAX_RETRIES}, "
                        f"url={candidate}, error={type(e).__name__}: {e}"
                    )
                    if attempt < self.MAX_RETRIES:
                        await asyncio.sleep(self.RETRY_DELAY_SEC)
            if room_dict:
                break

        if not room_dict:
            raise Exception(f"streamget 获取直播间信息失败: {type(last_error).__name__}: {last_error}")

        anchor_name = (
            room_dict.get("anchor_name")
            or room_dict.get("nickname")
            or room_dict.get("room_nickname")
            or ""
        )
        room_id = str(
            room_dict.get("room_id")
            or room_dict.get("rid")
            or room_dict.get("roomid")
            or ""
        )
        if not room_id:
            room_id = self._extract_room_id(url) or ""

        avatar_url = self._extract_avatar_from_room_dict(room_dict)
        if not avatar_url and room_id:
            avatar_url = await self._fetch_avatar_from_betard(room_id)

        is_live = bool(
            room_dict.get("is_live")
            or room_dict.get("live_status")
            or room_dict.get("show_status")
            or room_dict.get("status") == 2
        )

        return {
            "anchor_name": anchor_name,
            "room_id": room_id,
            "avatar_url": avatar_url or "",
            "is_live": is_live,
            "title": room_dict.get("title", ""),
            "raw_data": room_dict,
        }

    async def get_stream_url(self, url: str, quality: str, **kwargs) -> Dict[str, Any]:
        if DouyuLiveStream is None:
            raise Exception("streamget 未正确安装，无法解析斗鱼直播")

        quality_map = {
            "原画": "OD",
            "蓝光": "BD",
            "超清": "UHD",
            "高清": "HD",
            "标清": "SD",
            "流畅": "LD",
        }
        quality_code = quality_map.get(quality, "OD")

        live = DouyuLiveStream()
        stream_data = {}
        last_error = None
        candidates = self._candidate_urls(url)

        for candidate in candidates:
            for attempt in range(1, self.MAX_RETRIES + 1):
                try:
                    web_data = await asyncio.wait_for(live.fetch_web_stream_data(candidate), timeout=30.0)
                    stream_obj = await asyncio.wait_for(live.fetch_stream_url(web_data, quality_code), timeout=30.0)
                    stream_data = self._to_dict(stream_obj)
                    if stream_data:
                        break
                except Exception as e:
                    last_error = e
                    logger.warning(
                        f"[DouyuAdapter] 获取流地址失败: attempt={attempt}/{self.MAX_RETRIES}, "
                        f"url={candidate}, quality={quality_code}, error={type(e).__name__}: {e}"
                    )
                    if attempt < self.MAX_RETRIES:
                        await asyncio.sleep(self.RETRY_DELAY_SEC)
            if stream_data:
                break

        if not stream_data:
            raise Exception(f"streamget 获取流地址失败: {type(last_error).__name__}: {last_error}")

        is_live = bool(stream_data.get("is_live"))
        if not is_live:
            return {"is_live": False, "url": None}

        flv_url = stream_data.get("flv_url")
        m3u8_url = stream_data.get("m3u8_url")

        record_url = flv_url or m3u8_url
        play_url = flv_url or m3u8_url
        if not record_url:
            return {"is_live": False, "url": None}

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

    def _extract_room_id(self, url: str) -> Optional[str]:
        if not url:
            return None

        rid_match = re.search(r"(?:\?|&)rid=([A-Za-z0-9_]+)", url)
        if rid_match:
            return rid_match.group(1)

        url_without_query = url.split("?")[0].rstrip("/")
        match = re.search(r"douyu\.com/([A-Za-z0-9_]+)$", url_without_query)
        if match:
            return match.group(1)
        return None

    def _normalize_room_url(self, url: str) -> str:
        rid = self._extract_room_id(url)
        if rid:
            return f"https://www.douyu.com/{rid}"
        return (url or "").split("#")[0]

    def _candidate_urls(self, raw_url: str):
        normalized = self._normalize_room_url(raw_url)
        raw = (raw_url or "").split("#")[0]
        urls = []
        for item in [normalized, raw]:
            if item and item not in urls:
                urls.append(item)
        return urls

    def _to_dict(self, data: Any) -> Dict[str, Any]:
        if data is None:
            return {}
        if isinstance(data, dict):
            return data
        if hasattr(data, "to_dict") and callable(data.to_dict):
            return data.to_dict()
        if hasattr(data, "model_dump") and callable(data.model_dump):
            return data.model_dump()
        if hasattr(data, "__dict__"):
            return {
                k: v
                for k, v in data.__dict__.items()
                if not k.startswith("_")
            }
        return {}

    def _extract_avatar_from_room_dict(self, room_dict: Dict[str, Any]) -> str:
        if not room_dict:
            return ""

        avatar = room_dict.get("avatar")
        if isinstance(avatar, dict):
            for key in ("big", "middle", "small"):
                value = avatar.get(key)
                if isinstance(value, str) and value:
                    return value
        if isinstance(avatar, str) and avatar:
            return avatar

        for key in (
            "avatar_url",
            "owner_avatar",
            "avatar_mid",
            "avatar_small",
            "head_pic",
            "room_pic",
            "coverSrc",
            "room_src",
        ):
            value = room_dict.get(key)
            if isinstance(value, str) and value:
                if value.startswith(("http://", "https://")):
                    return value
                if key in ("room_pic", "coverSrc", "room_src"):
                    return f"https://rpic.douyucdn.cn/{value.lstrip('/')}"
        return ""

    async def _fetch_avatar_from_betard(self, room_id: str) -> str:
        api = f"https://www.douyu.com/betard/{room_id}"
        try:
            async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
                resp = await client.get(api)
                resp.raise_for_status()
                data = resp.json() if resp.content else {}
            room = data.get("room", {}) if isinstance(data, dict) else {}
            avatar_url = self._extract_avatar_from_room_dict(room)
            if avatar_url:
                return avatar_url
            logger.warning(f"[DouyuAdapter] betard 返回中未找到头像字段, room_id={room_id}")
            return ""
        except Exception as e:
            logger.warning(f"[DouyuAdapter] betard 获取头像失败, room_id={room_id}, error={type(e).__name__}: {e}")
            return ""
