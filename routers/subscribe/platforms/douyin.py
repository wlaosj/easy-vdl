"""
抖音平台适配器
"""
from typing import List, Dict, Optional, Any, Callable
from datetime import datetime
from routers.douyin import douyin_api, get_collection_videos
from routers.unified_browser_manager import unified_browser
from .base import PlatformAdapter


class DouyinAdapter(PlatformAdapter):
    """抖音平台适配器"""
    
    @property
    def platform_name(self) -> str:
        return "douyin"
    
    @property
    def supported_subscription_types(self) -> List[str]:
        return ["user", "favorite", "collection"]
    
    async def get_user_info(
        self,
        user_id: str,
        subscription_type: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        """获取抖音用户信息
        
        支持传入URL或用户ID，会自动解析并提取用户ID
        """
        try:
            if subscription_type == "favorite":
                # 点赞列表订阅：获取当前登录用户信息
                async with unified_browser.task_context("douyin", "get_current_user_info"):
                    stats = await douyin_api.get_current_user_info()
            else:
                # 普通博主订阅：如果传入的是URL，使用 parse_user_profile 解析（会自动提取用户ID）
                # 如果传入的是用户ID，直接使用 get_user_stats
                if user_id and ("http" in user_id or "v.douyin.com" in user_id):
                    # 传入的是URL，使用 parse_user_profile 解析（参考旧版实现）
                    async with unified_browser.task_context("douyin", "parse_user_profile"):
                        stats = await douyin_api.parse_user_profile(user_id)
                else:
                    # 传入的是用户ID，直接使用 get_user_stats
                    async with unified_browser.task_context("douyin", "get_user_stats"):
                        stats = await douyin_api.get_user_stats(user_id)
            
            if not stats:
                return None
            
            return {
                "user_id": stats.get('user_id'),  # 包含 user_id，与旧版保持一致
                "nickname": stats.get('nickname'),
                "avatar_url": stats.get('avatar_url'),
                "follower_count": stats.get('follower_count'),
                "following_count": stats.get('following_count'),
                "video_count": stats.get('video_count'),
                "like_count": stats.get('like_count'),
                "signature": stats.get('signature'),
            }
        except Exception as e:
            from ..common import logger
            logger.error(f"获取抖音用户信息失败: {str(e)}")
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
        """获取抖音最新视频"""
        try:
            if subscription_type == "favorite":
                # 点赞列表订阅
                cached_sec_user_id = kwargs.get("sec_user_id")
                async with unified_browser.task_context("douyin", "get_favorite_videos"):
                    result = await douyin_api.get_favorite_videos(
                        max_count=max_count,
                        max_cursor=0,
                        sec_user_id=cached_sec_user_id
                    )
            elif subscription_type == "collection":
                # 合集订阅
                page = await get_collection_videos(user_id, cursor=0, count=50, with_meta=False)
                videos_list = page.get("videos", [])
                videos_list = [v for v in videos_list if v.get("publish_time")]
                videos_list.sort(key=lambda x: int(x.get("publish_time", 0)), reverse=True)
                
                return {
                    "videos": videos_list[:max_count],
                    "has_more": page.get("has_more", False),
                    "next_cursor": page.get("next_cursor", 0)
                }
            else:
                # 普通用户视频订阅
                async with unified_browser.task_context("douyin", "get_user_videos"):
                    result = await douyin_api.get_user_videos(
                        user_id,
                        max_count=max_count,
                        max_cursor=0
                    )
            
            if not result:
                return {"videos": [], "has_more": False}
            
            videos_list = result.get("aweme_list", [])
            
            # 对于普通用户视频，按发布时间排序
            if subscription_type != "favorite" and subscription_type != "collection":
                videos_list.sort(key=lambda x: int(x.get("create_time", 0)), reverse=True)
            
            return {
                "videos": videos_list,
                "has_more": result.get("has_more", False),
                "max_cursor": result.get("max_cursor", 0)
            }
        except Exception as e:
            from ..common import logger
            logger.error(f"获取抖音最新视频失败: {str(e)}")
            return {"videos": [], "has_more": False, "error": str(e)}

    async def get_all_videos(
        self,
        user_id: str,
        subscription_type: Optional[str] = None,
        progress_callback: Optional[Callable] = None,
        **kwargs
    ) -> List[Dict[str, Any]]:
        """获取抖音所有视频"""
        all_videos = []
        
        try:
            if subscription_type == "favorite":
                # 点赞列表：分页获取
                async with unified_browser.task_context("douyin", "sync_favorite_videos"):
                    max_cursor = 0
                    while True:
                        result = await douyin_api.get_favorite_videos(
                            max_count=20,
                            max_cursor=max_cursor
                        )
                        if not result or not result.get("aweme_list"):
                            break
                        all_videos.extend(result.get("aweme_list", []))
                        if not result.get("has_more"):
                            break
                        max_cursor = result.get("max_cursor", 0)
                        if progress_callback:
                            await progress_callback({
                                "type": "sync_progress",
                                "current": len(all_videos),
                                "message": f"已获取 {len(all_videos)} 个视频"
                            })
            elif subscription_type == "collection":
                # 合集：分页获取
                cursor = 0
                while True:
                    page = await get_collection_videos(user_id, cursor=cursor, count=50, with_meta=False)
                    videos = page.get("videos", [])
                    if not videos:
                        break
                    all_videos.extend(videos)
                    if not page.get("has_more"):
                        break
                    cursor = page.get("next_cursor", 0)
                    if progress_callback:
                        await progress_callback({
                            "type": "sync_progress",
                            "current": len(all_videos),
                            "message": f"已获取 {len(all_videos)} 个视频"
                        })
            else:
                # 普通用户视频：分页获取
                async with unified_browser.task_context("douyin", "sync_user_videos"):
                    max_cursor = 0
                    while True:
                        result = await douyin_api.get_user_videos(
                            user_id,
                            max_cursor=max_cursor
                        )
                        if not result or not result.get("aweme_list"):
                            break
                        videos = result.get("aweme_list", [])
                        all_videos.extend(videos)
                        if not result.get("has_more") or not result.get("max_cursor"):
                            break
                        max_cursor = result.get("max_cursor", 0)
                        if progress_callback:
                            await progress_callback({
                                "type": "sync_progress",
                                "current": len(all_videos),
                                "message": f"已获取 {len(all_videos)} 个视频"
                            })
        except Exception as e:
            from ..common import logger
            logger.error(f"获取抖音所有视频失败: {str(e)}")
        
        return all_videos
    
    def normalize_video_data(
        self,
        video: Dict[str, Any],
        subscription_type: Optional[str] = None
    ) -> Dict[str, Any]:
        """标准化抖音视频数据"""
        from ..utils import get_correct_douyin_url
        
        if subscription_type == "collection":
            # 合集视频格式
            ts = int(video.get("publish_time", 0) or 0)
            return {
                "video_id": video.get("video_id"),
                "title": video.get("title", ""),
                "url": video.get("url"),
                "cover_url": video.get("cover_url", ""),
                "publish_time": datetime.fromtimestamp(ts) if ts else datetime.utcnow(),
                "stats": {
                    "play_count": video.get("play_count", 0)
                }
            }
        else:
            # 普通视频或点赞视频格式
            aweme_id = video.get("aweme_id")
            return {
                "video_id": aweme_id,
                "title": video.get("desc", ""),
                "url": get_correct_douyin_url(aweme_id, video),
                "cover_url": video.get("video", {}).get("cover", {}).get("url_list", [None])[0],
                "publish_time": datetime.fromtimestamp(int(video.get("create_time", 0))),
                "stats": {
                    "digg_count": video.get("statistics", {}).get("digg_count", 0),
                    "comment_count": video.get("statistics", {}).get("comment_count", 0),
                    "share_count": video.get("statistics", {}).get("share_count", 0)
                }
            }
    
    def check_update_logic(
        self,
        latest_video: Dict[str, Any],
        subscription_latest_video_time: Optional[datetime],
        subscription_latest_video_id: Optional[str],
        subscription_type: Optional[str] = None
    ) -> bool:
        """抖音更新检测逻辑"""
        if subscription_type == "favorite":
            # 点赞列表：基于视频ID检测
            latest_video_id = latest_video.get("aweme_id", "")
            return not subscription_latest_video_id or latest_video_id != subscription_latest_video_id
        else:
            # 普通用户视频：基于发布时间检测
            latest_publish_time = datetime.fromtimestamp(int(latest_video.get("create_time", 0)))
            return not subscription_latest_video_time or latest_publish_time > subscription_latest_video_time
