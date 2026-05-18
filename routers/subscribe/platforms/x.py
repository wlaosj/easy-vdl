"""
X(Twitter) 平台适配器（点赞视频订阅）
"""
from typing import List, Dict, Optional, Any, Callable
from datetime import datetime

from services import x_graphql
from .base import PlatformAdapter


class XAdapter(PlatformAdapter):
    """X 平台适配器（仅点赞视频订阅）"""

    @property
    def platform_name(self) -> str:
        return "x"

    @property
    def supported_subscription_types(self) -> List[str]:
        return ["favorite"]

    async def get_user_info(
        self,
        user_id: str,
        subscription_type: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        try:
            screen_name = x_graphql.parse_screen_name(user_id)
            if not screen_name:
                return None
            info = x_graphql.fetch_user_info(screen_name)
            if not info:
                return None
            return {
                "user_id": info.screen_name,  # 保持使用 screen_name 作为订阅主键
                "nickname": info.nickname,
                "avatar_url": info.avatar_url,
                "follower_count": info.follower_count,
                "following_count": info.following_count,
                "video_count": info.video_count,
                "signature": info.signature,
            }
        except Exception as e:
            from ..common import logger
            logger.error(f"获取X用户信息失败: {str(e)}")
            return None

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
            screen_name = x_graphql.parse_screen_name(user_id)
            if not screen_name:
                return {"videos": [], "has_more": False}
            max_pages = kwargs.get("max_pages")
            items = x_graphql.fetch_liked_items(
                screen_name,
                max_items=max_count,
                stop_at_id=latest_video_id,
                max_pages=max_pages
            )
            return {
                "videos": items,
                "has_more": False
            }
        except Exception as e:
            from ..common import logger
            logger.error(f"获取X点赞列表失败: {str(e)}")
            return {"videos": [], "has_more": False}

    async def get_all_videos(
        self,
        user_id: str,
        subscription_type: Optional[str] = None,
        progress_callback: Optional[Callable] = None,
        **kwargs
    ) -> List[Dict[str, Any]]:
        try:
            screen_name = x_graphql.parse_screen_name(user_id)
            if not screen_name:
                return []
            max_count = kwargs.get("max_count", 500)
            items = x_graphql.fetch_liked_items(
                screen_name,
                max_items=max_count
            )
            if progress_callback:
                await progress_callback({
                    "type": "sync_progress",
                    "current": len(items),
                    "message": f"已获取 {len(items)} 条点赞视频"
                })
            return items
        except Exception as e:
            from ..common import logger
            logger.error(f"获取X点赞全量失败: {str(e)}")
            return []

    def normalize_video_data(
        self,
        video: Dict[str, Any],
        subscription_type: Optional[str] = None
    ) -> Dict[str, Any]:
        publish_time = video.get("publish_time")
        if isinstance(publish_time, str):
            try:
                publish_time = datetime.fromisoformat(publish_time.replace("Z", "+00:00"))
            except Exception:
                publish_time = datetime.now()
        elif not isinstance(publish_time, datetime):
            publish_time = datetime.now()

        return {
            "video_id": video.get("video_id", ""),
            "title": video.get("title", "") or "",
            "url": video.get("url", "") or "",
            "cover_url": video.get("cover_url", "") or "",
            "publish_time": publish_time,
            "stats": {
                "view_count": 0,
                "like_count": 0,
                "comment_count": 0,
                "share_count": 0
            }
        }

    def check_update_logic(
        self,
        latest_video: Dict[str, Any],
        subscription_latest_video_time: Optional[datetime],
        subscription_latest_video_id: Optional[str],
        subscription_type: Optional[str] = None
    ) -> bool:
        latest_video_id = latest_video.get("video_id", "")
        return not subscription_latest_video_id or latest_video_id != subscription_latest_video_id
