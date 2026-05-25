"""
小红书平台适配器
"""
from typing import List, Dict, Optional, Any, Callable
from datetime import datetime
from routers.xhsapi import xhs_api
from .base import PlatformAdapter
from ..common import logger

class XiaohongshuAdapter(PlatformAdapter):
    """小红书平台适配器"""
    
    @property
    def platform_name(self) -> str:
        return "xiaohongshu"
    
    @property
    def supported_subscription_types(self) -> List[str]:
        return ["user"]  # 目前仅支持用户订阅
    
    async def get_user_info(
        self,
        user_id: str,
        subscription_type: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        """获取小红书用户信息。笔记链接（含 /explore/）直接返回 None。"""
        try:
            # 笔记链接不能当创作者主页用，避免拼成 /user/profile/https://.../explore/...
            if "xiaohongshu.com" in user_id and "/explore/" in user_id:
                logger.warning("检测到笔记链接，请使用创作者主页链接添加订阅")
                return None
            # 创作者主页 URL 或纯 user_id 直接传给 xhsapi
            # 调用 API 获取信息
            info = await xhs_api.get_user_info(user_id)
            if not info:
                if xhs_api.last_user_info_error:
                    return {"__error__": xhs_api.last_user_info_error}
                return None
            
            return info
        except Exception as e:
            logger.error(f"获取小红书用户信息失败: {str(e)}")
            return None
    
    async def get_latest_videos(
        self,
        user_id: str,
        subscription_type: Optional[str] = None,
        max_count: int = 30,
        latest_video_time: Optional[datetime] = None,
        latest_video_id: Optional[str] = None,
        profile_url: Optional[str] = None,
        **kwargs
    ) -> Dict[str, Any]:
        """获取最新笔记。必须传入带 xsec_token 的 profile_url（创作者主页完整链接）。"""
        try:
            creator_url = (profile_url or kwargs.get("profile_url")) if (profile_url or kwargs.get("profile_url")) and "xsec_token" in (profile_url or kwargs.get("profile_url") or "") else None
            result = await xhs_api.get_user_notes(user_id, cursor="", creator_url_with_token=creator_url)
            notes = result.get("notes", [])
            has_more = result.get("has_more", False)
            cursor = result.get("cursor", "")
            return {"videos": notes[:max_count], "has_more": has_more, "max_cursor": cursor}
        except Exception as e:
            logger.error(f"获取小红书最新笔记失败: {str(e)}")
            return {"videos": [], "has_more": False, "error": str(e)}
            
    async def get_all_videos(
        self,
        user_id: str,
        subscription_type: Optional[str] = None,
        progress_callback: Optional[Callable] = None,
        profile_url: Optional[str] = None,
        **kwargs
    ) -> List[Dict[str, Any]]:
        """获取所有笔记（全量同步）。若传入带 xsec_token 的 profile_url，将优先用主动 API。"""
        all_notes = []
        cursor = ""
        creator_url = (profile_url or kwargs.get("profile_url")) if (profile_url or kwargs.get("profile_url")) and "xsec_token" in (profile_url or kwargs.get("profile_url") or "") else None
        
        try:
            while True:
                result = await xhs_api.get_user_notes(user_id, cursor=cursor, creator_url_with_token=creator_url)
                notes = result.get("notes", [])
                
                if not notes:
                    break
                    
                all_notes.extend(notes)
                
                if progress_callback:
                    await progress_callback({
                        "type": "sync_progress",
                        "current": len(all_notes),
                        "message": f"已获取 {len(all_notes)} 条笔记"
                    })
                
                if not result.get("has_more"):
                    break
                    
                cursor = result.get("cursor", "")
                if not cursor:
                    break
                    
                # 避免请求过快
                import asyncio
                await asyncio.sleep(2)
                
        except Exception as e:
            logger.error(f"获取小红书所有笔记失败: {str(e)}")
        
        return all_notes

    def normalize_video_data(
        self,
        video: Dict[str, Any],
        subscription_type: Optional[str] = None
    ) -> Dict[str, Any]:
        """标准化笔记数据"""
        
        # 处理时间戳
        publish_time = None
        ts = video.get("time") or video.get("create_time") or video.get("publish_time")
        if ts:
            try:
                # 可能是毫秒或秒
                if len(str(ts)) > 10:
                    publish_time = datetime.fromtimestamp(int(ts) / 1000)
                else:
                    publish_time = datetime.fromtimestamp(int(ts))
            except: pass
            
        note_id = video.get("note_id") or video.get("noteId") or video.get("id")
        xsec_token = (video.get("xsec_token") or "").strip()
        # 带 xsec_token 的 explore 链接可直接被 yt-dlp 解析（无水印），优先存该格式
        if xsec_token:
            base_url = f"https://www.xiaohongshu.com/explore/{note_id}?xsec_token={xsec_token}&xsec_source=pc_feed"
        else:
            base_url = f"https://www.xiaohongshu.com/explore/{note_id}"
        return {
            "video_id": note_id,
            "title": video.get("display_title") or video.get("title", "") or "无标题",
            "url": base_url,
            "cover_url": video.get("cover_url") or video.get("cover", {}).get("url"),
            "publish_time": publish_time,
            "stats": {
                "digg_count": video.get("liked_count", 0),
                "comment_count": 0, # 列表页通常没这个数据
                "share_count": 0
            },
            "extra_data": {
                "type": video.get("type", "normal"),  # video 或 normal(图文)
                "xsec_token": video.get("xsec_token") or None,  # 用于下载时拼带 token 的 URL 或 feed 取直链
            }
        }

    def check_update_logic(
        self,
        latest_video: Dict[str, Any],
        subscription_latest_video_time: Optional[datetime],
        subscription_latest_video_id: Optional[str],
        subscription_type: Optional[str] = None
    ) -> bool:
        """更新检测逻辑"""
        # 基于 ID 检测（小红书笔记ID非递增，但最新列表第一个通常是最新的）
        # 也可以结合时间判断
        
        current_id = latest_video.get("note_id") or latest_video.get("id")
        
        if not subscription_latest_video_id:
            return True
            
        return current_id != subscription_latest_video_id
