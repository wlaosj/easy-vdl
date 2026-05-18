"""
TikTok平台适配器
"""
from typing import List, Dict, Optional, Any, Callable
from datetime import datetime
from routers.tiktok import tiktok_api
from ..utils import generate_profile_url
from .base import PlatformAdapter


class TikTokAdapter(PlatformAdapter):
    """TikTok平台适配器"""
    
    @property
    def platform_name(self) -> str:
        return "tiktok"
    
    @property
    def supported_subscription_types(self) -> List[str]:
        return ["user"]
    
    async def get_user_info(
        self,
        user_id: str,
        subscription_type: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        """获取TikTok用户信息"""
        try:
            # 如果传入的已经是URL，直接使用；否则生成URL
            if user_id and user_id.startswith("http"):
                profile_url = user_id
            else:
                profile_url = generate_profile_url("tiktok", user_id)
                
            user_info = await tiktok_api.get_user_info(profile_url)
            
            if not user_info:
                return None
            
            return {
                "nickname": user_info.get('nickname'),
                "avatar_url": user_info.get('avatar_url'),
                "follower_count": user_info.get('follower_count'),
                "video_count": user_info.get('video_count', 0),
                "signature": user_info.get('signature', ''),
            }
        except Exception as e:
            from ..common import logger
            logger.error(f"获取TikTok用户信息失败: {str(e)}")
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
        """获取TikTok最新视频"""
        try:
            user_url = f"https://www.tiktok.com/@{user_id}"
            videos_result = await tiktok_api.get_user_videos(
                user_url,
                max_count=max_count
            )
            
            if not videos_result or not videos_result.get("videos"):
                return {"videos": [], "has_more": False}
            
            return {
                "videos": videos_result.get("videos", []),
                "has_more": False
            }
        except Exception as e:
            from ..common import logger
            logger.error(f"获取TikTok最新视频失败: {str(e)}")
            return {"videos": [], "has_more": False}
    
    async def get_all_videos(
        self,
        user_id: str,
        subscription_type: Optional[str] = None,
        progress_callback: Optional[Callable] = None,
        **kwargs
    ) -> List[Dict[str, Any]]:
        """获取TikTok所有视频"""
        try:
            user_url = f"https://www.tiktok.com/@{user_id}"
            videos_result = await tiktok_api.get_user_videos(
                user_url,
                max_count=None  # 全量同步走分页抓取，避免大账号被单次提取截断
            )
            
            if progress_callback:
                videos = videos_result.get("videos", [])
                await progress_callback({
                    "type": "sync_progress",
                    "current": len(videos),
                    "message": f"已获取 {len(videos)} 个视频"
                })
            
            return videos_result.get("videos", [])
        except Exception as e:
            from ..common import logger
            logger.error(f"获取TikTok所有视频失败: {str(e)}")
            return []
    
    def normalize_video_data(
        self,
        video: Dict[str, Any],
        subscription_type: Optional[str] = None
    ) -> Dict[str, Any]:
        """标准化TikTok视频数据"""
        create_time = video.get("create_time", 0)
        publish_time = datetime.fromtimestamp(create_time) if create_time and create_time > 0 else datetime.now()
        
        # 优先使用 video_url，如果没有则尝试构造（兼容全量同步 logic）
        video_url = video.get("video_url", "")
        video_id = video.get("video_id", "")
        
        # 如果没有 URL 但有 ID，尝试构造
        if not video_url and video_id:
            # 注意：这里构造时可能缺少用户名，但 yt-dlp 通常能通过 ID 下载
            # 或者我们可以通过某种方式获取用户名，但在 normalize_video_data 中通常只传 video 字典
            # 全量同步中有 user_id 可用，这里没有。
            # 不过 tiktok_api 中的 entry.get('url') 通常是完整的，如果它返回了。
            pass

        return {
            "video_id": video_id,
            "title": video.get("title", ""),
            "url": video_url or video.get("url", ""), # 保持向后兼容或尝试多种可能
            "cover_url": video.get("cover_url", ""),
            "publish_time": publish_time,
            "stats": {
                "view_count": video.get("view_count", 0),
                "like_count": video.get("like_count", 0),
                "comment_count": video.get("comment_count", 0),
                "share_count": video.get("share_count", 0)
            }
        }
    
    def check_update_logic(
        self,
        latest_video: Dict[str, Any],
        subscription_latest_video_time: Optional[datetime],
        subscription_latest_video_id: Optional[str],
        subscription_type: Optional[str] = None
    ) -> bool:
        """TikTok更新检测逻辑：基于视频ID"""
        latest_video_id = latest_video.get("video_id", "")
        return not subscription_latest_video_id or latest_video_id != subscription_latest_video_id
