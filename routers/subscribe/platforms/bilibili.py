"""
B站平台适配器
"""
from typing import List, Dict, Optional, Any, Callable
from datetime import datetime, timezone
from routers.bilibili import bilibili_api, get_bilibili_favorite_info, get_bilibili_favorite_videos
from .base import PlatformAdapter


class BilibiliAdapter(PlatformAdapter):
    """B站平台适配器"""
    
    @property
    def platform_name(self) -> str:
        return "bilibili"
    
    @property
    def supported_subscription_types(self) -> List[str]:
        return ["user", "favorite", "collection"]
    
    async def get_user_info(
        self,
        user_id: str,
        subscription_type: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        """获取B站用户/收藏夹/合集信息"""
        try:
            if subscription_type == "favorite":
                # 收藏夹订阅
                import os
                cookies_path = "/app/database/cookie/bilibili_cookie.txt"
                fav_data = await get_bilibili_favorite_info(user_id, cookies_path)
                if not fav_data:
                    return None
                return {
                    "nickname": fav_data.get('title', ''),
                    "video_count": fav_data.get('video_count', 0),
                    "signature": f"收藏夹：{fav_data.get('title', '')}",
                }
            elif subscription_type == "collection":
                # 合集订阅
                collection_info = await bilibili_api.fetch_video_collection_info(user_id)
                if not collection_info:
                    return None
                # 参考旧版实现，返回完整信息包括is_collection和owner字段
                # 注意：需要保留完整的collection_info，因为get_collection_videos方法需要访问owner字段
                return {
                    "nickname": collection_info.get('title', ''),
                    "video_count": collection_info.get('videos_count', 0),
                    "signature": f"B站合集: {collection_info.get('title', '')}",
                    "avatar_url": collection_info.get('cover_url', ''),
                    "is_collection": collection_info.get('is_collection', False),  # 关键字段，用于判断是否为合集
                    "collection_title": collection_info.get('collection_title', collection_info.get('title', '')),  # 合集标题
                    "bvid": collection_info.get('bvid', user_id),  # BV号
                    "title": collection_info.get('title', ''),  # 标题
                    "owner": collection_info.get('owner', {}),  # UP主信息，get_collection_videos方法需要
                    "pages": collection_info.get('pages', []),  # 视频列表，用于后续处理
                }
            else:
                # UP主订阅
                up_info = await bilibili_api.fetch_up_info(user_id)
                if not up_info:
                    return None
                return {
                    "nickname": up_info.get('nickname'),
                    "avatar_url": up_info.get('avatar_url', ''),
                    "follower_count": up_info.get('follower_count', 0),
                    "video_count": up_info.get('video_count', 0),
                    "like_count": up_info.get('like_count', 0),
                    "signature": up_info.get('signature', ''),
                    "following_count": up_info.get('following_count', 0),
                }
        except Exception as e:
            from ..common import logger
            logger.error(f"获取B站信息失败: {str(e)}")
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
        """获取B站最新视频
        参考旧版实现：首次添加订阅时使用非增量方法，限制数量为5个
        """
        try:
            if subscription_type == "favorite":
                # 收藏夹：基于ID比较
                import os
                cookies_path = "/app/database/cookie/bilibili_cookie.txt"
                all_fav_videos = await get_bilibili_favorite_videos(
                    user_id,
                    cookies_path,
                    extract_flat=True,
                    max_count=50
                )
                return {
                    "videos": all_fav_videos,
                    "has_more": False
                }
            elif subscription_type == "collection":
                # 合集：
                # - 首次添加订阅（没有 latest_video_id）只拉最近 max_count 条，避免首次全量过重
                # - 增量检查（有 latest_video_id）保持增量逻辑
                async def progress_callback(data):
                    pass

                if not latest_video_id:
                    latest_videos = await bilibili_api.get_collection_videos_queued(
                        user_id,
                        max_count=max_count if max_count and max_count > 0 else 30,
                        progress_callback=progress_callback
                    )
                else:
                    latest_page = 0
                    import re
                    page_match = re.search(r'_p(\d+)$', latest_video_id)
                    if page_match:
                        latest_page = int(page_match.group(1))

                    latest_videos = await bilibili_api.get_collection_videos_incremental_queued(
                        user_id,
                        latest_page=latest_page,
                        latest_video_id=latest_video_id,
                        progress_callback=progress_callback
                    )
                return {
                    "videos": latest_videos or [],
                    "has_more": False
                }
            else:
                # UP主：参考旧版实现
                # 如果latest_video_time为None，说明是首次添加订阅，使用非增量方法并限制数量
                # 如果latest_video_time不为None，说明是更新检查，使用增量方法
                if latest_video_time is None:
                    # 首次添加订阅：使用非增量方法，限制数量（参考旧版：target_count = 5）
                    # 使用get_up_videos_queued方法，传入max_count参数
                    async def progress_callback(data):
                        pass
                    
                    latest_videos = await bilibili_api.get_up_videos_queued(
                        user_id,
                        max_count=max_count if max_count > 0 else 5,  # 默认5个，与旧版一致
                        progress_callback=progress_callback
                    )
                    return {
                        "videos": latest_videos[:max_count] if max_count > 0 else latest_videos[:5],
                        "has_more": False
                    }
                else:
                    # 更新检查：使用增量方法
                    async def progress_callback(data):
                        pass
                    
                    latest_videos = await bilibili_api.get_up_videos_incremental_queued(
                        user_id,
                        latest_video_time=latest_video_time,
                        progress_callback=progress_callback
                    )
                    return {
                        "videos": latest_videos or [],
                        "has_more": False
                    }
        except Exception as e:
            from ..common import logger
            logger.error(f"获取B站最新视频失败: {str(e)}")
            return {"videos": [], "has_more": False}
    
    async def get_all_videos(
        self,
        user_id: str,
        subscription_type: Optional[str] = None,
        progress_callback: Optional[Callable] = None,
        **kwargs
    ) -> List[Dict[str, Any]]:
        """获取B站所有视频"""
        try:
            if subscription_type == "favorite":
                import os
                cookies_path = "/app/database/cookie/bilibili_cookie.txt"
                all_videos = await get_bilibili_favorite_videos(
                    user_id,
                    cookies_path,
                    extract_flat=False,
                    progress_callback=progress_callback
                )
                return all_videos or []
            elif subscription_type == "collection":
                all_videos = await bilibili_api.get_collection_videos(
                    user_id,
                    progress_callback=progress_callback
                )
                return all_videos or []
            else:
                all_videos = await bilibili_api.get_up_videos_queued(
                    user_id,
                    progress_callback=progress_callback
                )
                return all_videos or []
        except Exception as e:
            from ..common import logger
            logger.error(f"获取B站所有视频失败: {str(e)}")
            return []
    
    def normalize_video_data(
        self,
        video: Dict[str, Any],
        subscription_type: Optional[str] = None
    ) -> Dict[str, Any]:
        """标准化B站视频数据"""
        if subscription_type == "favorite":
            # 收藏夹视频
            publish_time_str = video.get("publish_time", "")
            try:
                if publish_time_str:
                    if publish_time_str.endswith("Z"):
                        publish_time_str = publish_time_str.replace("Z", "+00:00")
                    publish_dt = datetime.fromisoformat(publish_time_str)
                else:
                    publish_dt = datetime.now(timezone.utc)
            except Exception:
                publish_dt = datetime.now(timezone.utc)
            
            return {
                "video_id": video.get("video_id", ""),
                "title": video.get("title", ""),
                "url": video.get("url", ""),
                "cover_url": video.get("cover_url", ""),
                "publish_time": publish_dt,
                "is_charging_arc": video.get("is_charging_arc", False),
                "stats": {
                    "duration": video.get("duration", 0),
                    "uploader": video.get("uploader", ""),
                    "uploader_id": video.get("uploader_id", "")
                }
            }
        elif subscription_type == "collection":
            # 合集视频
            publish_time_str = video.get("publish_time", "")
            try:
                publish_dt = datetime.fromisoformat(publish_time_str) if publish_time_str else datetime.now()
            except Exception:
                publish_dt = datetime.now()
            
            return {
                "video_id": video.get("video_id", ""),
                "title": video.get("title", ""),
                "url": video.get("url", ""),
                "cover_url": video.get("cover_url", ""),
                "publish_time": publish_dt,
                "is_charging_arc": video.get("is_charging_arc", False),
                "extra_data": {
                    "section_title": video.get("section_title", ""),
                    "episode_title": video.get("episode_title", ""),
                    "root_bvid": video.get("root_bvid", ""),
                    "root_bvid_title": video.get("root_bvid_title", ""),
                },
                "stats": {
                    "page": video.get("page", 1),
                    "cid": video.get("cid", ""),
                    "duration": video.get("duration", ""),
                    "author": video.get("author", ""),
                    "author_id": video.get("author_id", ""),
                    "section_title": video.get("section_title", ""),
                    "episode_title": video.get("episode_title", ""),
                    "root_bvid": video.get("root_bvid", ""),
                    "root_bvid_title": video.get("root_bvid_title", "")
                }
            }
        else:
            # UP主视频
            publish_time_str = video.get("publish_time_parsed", "")
            try:
                publish_dt = datetime.fromisoformat(publish_time_str) if publish_time_str else datetime.now()
            except Exception:
                publish_dt = datetime.now()
            
            return {
                "video_id": video.get("url", "").split("/")[-1] if video.get("url") else "",
                "title": video.get("title", ""),
                "url": video.get("url", ""),
                "cover_url": video.get("cover_url", ""),
                "publish_time": publish_dt,
                "is_charging_arc": video.get("is_charging_arc", False),
                "stats": {
                    "play_count": video.get("play_count", "0")
                }
            }
    
    def should_skip_video(
        self,
        video: Dict[str, Any],
        skip_bilibili_upower: bool = False
    ) -> bool:
        """B站跳过充电专属视频"""
        if skip_bilibili_upower:
            return video.get("is_charging_arc", False)
        return False
