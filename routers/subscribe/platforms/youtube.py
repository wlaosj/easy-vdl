"""
YouTube平台适配器
"""
from typing import List, Dict, Optional, Any, Callable
from datetime import datetime
from routers.youtube import youtube_api
from .base import PlatformAdapter


class YouTubeAdapter(PlatformAdapter):
    """YouTube平台适配器"""
    
    @property
    def platform_name(self) -> str:
        return "youtube"
    
    @property
    def supported_subscription_types(self) -> List[str]:
        return ["user", "playlist"]
    
    async def get_user_info(
        self,
        user_id: str,
        subscription_type: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        """获取YouTube频道信息
        支持传入完整URL或user_id/channel_id
        """
        try:
            # 检查传入的是完整URL还是user_id/channel_id
            # 参考旧版实现，直接使用parse_channel_url，它支持多种格式
            if user_id.startswith("http"):
                # 传入的是完整URL，直接使用
                channel_url = user_id
            elif user_id.startswith("UC") and len(user_id) == 24:
                # 频道ID格式
                channel_url = f"https://www.youtube.com/channel/{user_id}"
            else:
                # 假设是handle（可能带@或不带@）
                if user_id.startswith('@'):
                    channel_url = f"https://www.youtube.com/{user_id}"
                else:
                    channel_url = f"https://www.youtube.com/@{user_id}"
            
            channel_info = await youtube_api.parse_channel_url(channel_url)
            
            if not channel_info:
                return None
            
            # 返回完整信息，包括channel_id和user_id（参考旧版实现）
            return {
                "user_id": channel_info.get('user_id') or channel_info.get('channel_id', ''),
                "channel_id": channel_info.get('channel_id', ''),
                "name": channel_info.get('name') or channel_info.get('nickname', ''),
                "nickname": channel_info.get('name') or channel_info.get('nickname', ''),
                "avatar_url": channel_info.get('avatar_url', ''),
                "follower_count": channel_info.get('follower_count', 0),
                "video_count": channel_info.get('video_count', 0),
                "like_count": channel_info.get('like_count', 0),
                "signature": channel_info.get('signature', ''),
            }
        except Exception as e:
            from ..common import logger
            logger.error(f"获取YouTube频道信息失败: {str(e)}")
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
        """获取YouTube最新视频"""
        try:
            tab_type = kwargs.get('youtube_tab_type', 'videos')
            
            if subscription_type == "playlist":
                from routers.youtube import get_playlist_videos
                result = await get_playlist_videos(
                    user_id,
                    max_count=max_count,
                    page_token=""
                )
            else:
                result = await youtube_api.get_channel_videos(
                    user_id,
                    max_count=max_count,
                    tab_type=tab_type
                )
            
            if not result or not result.get("items"):
                return {"videos": [], "has_more": False}
            
            return {
                "videos": result.get("items", []),
                "has_more": bool(result.get("nextPageToken")),
                "nextPageToken": result.get("nextPageToken"),
                "real_channel_id": result.get("real_channel_id")
            }
        except Exception as e:
            from ..common import logger
            logger.error(f"获取YouTube最新视频失败: {str(e)}")
            return {"videos": [], "has_more": False, "error": str(e)}

    async def get_all_videos(
        self,
        user_id: str,
        subscription_type: Optional[str] = None,
        progress_callback: Optional[Callable] = None,
        **kwargs
    ) -> List[Dict[str, Any]]:
        """获取YouTube所有视频"""
        all_videos = []
        
        try:
            tab_type = kwargs.get('youtube_tab_type', 'videos')
            page_token = ""
            
            while True:
                if subscription_type == "playlist":
                    from routers.youtube import get_playlist_videos
                    result = await get_playlist_videos(
                        user_id,
                        max_count=50,
                        page_token=page_token
                    )
                else:
                    result = await youtube_api.get_channel_videos(
                        user_id,
                        max_count=50,
                        tab_type=tab_type,
                        page_token=page_token
                    )
                
                if not result or not result.get("items"):
                    break
                
                all_videos.extend(result.get("items", []))
                
                if progress_callback:
                    await progress_callback({
                        "type": "sync_progress",
                        "current": len(all_videos),
                        "message": f"已获取 {len(all_videos)} 个视频"
                    })
                
                page_token = result.get("nextPageToken")
                if not page_token:
                    break
        except Exception as e:
            from ..common import logger
            logger.error(f"获取YouTube所有视频失败: {str(e)}")
        
        return all_videos
    
    def normalize_video_data(
        self,
        video: Dict[str, Any],
        subscription_type: Optional[str] = None
    ) -> Dict[str, Any]:
        """标准化YouTube视频数据"""
        from ..common import logger
        published_at = video.get("snippet", {}).get("publishedAt")
        video_id = video.get("id", {}).get("videoId")
        try:
            publish_dt = datetime.fromisoformat(published_at.replace('Z', '+00:00')) if published_at else datetime.utcnow()
            logger.debug(
                f"[YT_NORMALIZED_TIME] video_id={video_id} raw_published_at={published_at} "
                f"parsed_publish_dt={publish_dt.isoformat()} fallback=False"
            )
        except Exception:
            publish_dt = datetime.utcnow()
            logger.warning(
                f"[YT_NORMALIZED_TIME][FALLBACK_NOW] video_id={video_id} raw_published_at={published_at} "
                f"parsed_publish_dt={publish_dt.isoformat()} reason=parse_error"
            )
        
        return {
            "video_id": video_id,
            "title": video.get("snippet", {}).get("title", ""),
            "url": f"https://www.youtube.com/watch?v={video_id}",
            "cover_url": video.get("snippet", {}).get("thumbnails", {}).get("high", {}).get("url", ""),
            "publish_time": publish_dt,
            "stats": {}
        }
    
    def check_update_logic(
        self,
        latest_video: Dict[str, Any],
        subscription_latest_video_time: Optional[datetime],
        subscription_latest_video_id: Optional[str],
        subscription_type: Optional[str] = None
    ) -> bool:
        """YouTube更新检测逻辑：基于视频ID"""
        latest_video_id = latest_video.get("id", {}).get("videoId", "")
        return not subscription_latest_video_id or latest_video_id != subscription_latest_video_id
    
    def get_concurrent_limit(self) -> int:
        """YouTube支持并发"""
        return 3
