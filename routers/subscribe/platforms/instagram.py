"""
Instagram 平台适配器
"""
import asyncio
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional

from routers import instagram as instagram_api
from .base import PlatformAdapter


class InstagramAdapter(PlatformAdapter):
    """Instagram 博主图像/视频订阅适配器"""

    @property
    def platform_name(self) -> str:
        return "instagram"

    @property
    def supported_subscription_types(self) -> List[str]:
        return ["user"]

    async def get_user_info(
        self,
        user_id: str,
        subscription_type: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        try:
            return await instagram_api.get_user_info(user_id)
        except Exception as e:
            from ..common import logger
            logger.error(f"获取 Instagram 用户信息失败: {str(e)}")
            return {"__error__": str(e)}

    async def get_latest_videos(
        self,
        user_id: str,
        subscription_type: Optional[str] = None,
        max_count: int = 30,
        latest_video_time: Optional[datetime] = None,
        latest_video_id: Optional[str] = None,
        **kwargs
    ) -> Dict[str, Any]:
        try:
            items = await instagram_api.get_user_medias(user_id, max_count or 30)
            return {"videos": items, "has_more": False}
        except Exception as e:
            from ..common import logger
            logger.error(f"获取 Instagram 最新媒体失败: {str(e)}")
            return {"videos": [], "has_more": False, "error": str(e)}

    async def get_all_videos(
        self,
        user_id: str,
        subscription_type: Optional[str] = None,
        progress_callback: Optional[Callable] = None,
        **kwargs
    ) -> List[Dict[str, Any]]:
        try:
            count = int(kwargs.get("max_count") or 200)
            items = await instagram_api.get_user_medias(user_id, count)
            if progress_callback:
                await progress_callback({
                    "type": "sync_progress",
                    "current": len(items),
                    "message": f"已获取 {len(items)} 个 Instagram 媒体"
                })
            return items
        except Exception as e:
            from ..common import logger
            logger.error(f"获取 Instagram 全量媒体失败: {str(e)}")
            return []

    async def iter_all_videos(
        self,
        user_id: str,
        subscription_type: Optional[str] = None,
        page_size: int = 50,
        max_count: Optional[int] = None,
        progress_callback: Optional[Callable] = None,
        batch_callback: Optional[Callable] = None,
        **kwargs
    ) -> List[Dict[str, Any]]:
        try:
            resolved_user_id = await instagram_api.get_user_id(user_id)
            all_items: List[Dict[str, Any]] = []
            end_cursor = ""
            page_no = 0
            target_total = int(max_count) if max_count else None

            while True:
                page_no += 1
                page = await instagram_api.get_user_medias_page(
                    resolved_user_id,
                    count=page_size,
                    end_cursor=end_cursor
                )
                batch_items = page.get("items", []) or []
                end_cursor = page.get("next_cursor") or ""
                post_count = page.get("post_count", 0) or 0

                if not batch_items:
                    break

                if target_total is not None and len(all_items) + len(batch_items) > target_total:
                    batch_items = batch_items[: max(0, target_total - len(all_items))]

                all_items.extend(batch_items)

                if progress_callback:
                    await progress_callback({
                        "type": "sync_progress",
                        "current": len(all_items),
                        "page": page_no,
                        "post_count": post_count,
                        "message": f"已获取第 {page_no} 页 Instagram 媒体，累计 {len(all_items)} 条"
                    })

                if batch_callback:
                    await batch_callback(batch_items)

                if target_total is not None and len(all_items) >= target_total:
                    break
                if not end_cursor:
                    break

                await asyncio.sleep(instagram_api.full_sync_page_delay_seconds(page_no))

            return all_items
        except Exception as e:
            from ..common import logger
            logger.error(f"分页获取 Instagram 全量媒体失败: {str(e)}")
            if instagram_api.is_instagram_risk_error(str(e)):
                raise
            return []

    def normalize_video_data(
        self,
        video: Dict[str, Any],
        subscription_type: Optional[str] = None
    ) -> Dict[str, Any]:
        return instagram_api.normalize_media_item(video)

    def check_update_logic(
        self,
        latest_video: Dict[str, Any],
        subscription_latest_video_time: Optional[datetime],
        subscription_latest_video_id: Optional[str],
        subscription_type: Optional[str] = None
    ) -> bool:
        normalized = self.normalize_video_data(latest_video, subscription_type)
        latest_video_id = normalized.get("video_id", "")
        return not subscription_latest_video_id or latest_video_id != subscription_latest_video_id
