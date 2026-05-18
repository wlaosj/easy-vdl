"""
网易云歌单平台适配器

基于 yt-dlp 解析网易云歌单，供订阅系统使用。
"""
from typing import List, Dict, Optional, Any, Callable, Tuple
from datetime import datetime

from .base import PlatformAdapter


class NetEaseAdapter(PlatformAdapter):
    """网易云歌单平台适配器
    
    这里将“歌单”抽象成订阅源，歌单中的每一首歌对应 SubscriptionVideo 中的一条“视频”记录。
    """

    @property
    def platform_name(self) -> str:
        # 与 sql.models.Platform.NETEASE.value 对应
        return "netease"

    @property
    def supported_subscription_types(self) -> List[str]:
        # 目前只支持歌单订阅
        return ["playlist"]

    async def get_user_info(
        self,
        user_id: str,
        subscription_type: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        """获取歌单基础信息
        
        由于网易云没有“博主主页”概念，这里把歌单本身视为订阅对象：
        - nickname: 歌单名称
        - avatar_url: 歌单封面
        - video_count: 歌曲数量
        """
        try:
            from ..common import logger

            playlist_url = f"https://music.163.com/playlist?id={user_id}"

            title, thumbnail = await self._fetch_playlist_meta(playlist_url)
            # video_count 这里不强求（避免为拿封面而解析整个歌单），由外层逻辑自己填
            return {
                "nickname": title or f"网易云歌单 {user_id}",
                "avatar_url": thumbnail or "",
                "video_count": None,
                "follower_count": None,
                "signature": playlist_url,
            }
        except Exception:
            from ..common import logger
            logger.warning("获取网易云歌单信息失败（将继续使用最小信息）", exc_info=True)
            return None

    async def _fetch_playlist_meta(self, playlist_url: str) -> Tuple[str, str]:
        from ..common import logger
        try:
            import re
            import httpx

            headers = {
                "User-Agent": (
                    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
                ),
                "Referer": "https://music.163.com/",
            }
            async with httpx.AsyncClient(follow_redirects=True, timeout=15.0, headers=headers) as client:
                resp = await client.get(playlist_url)
                html = resp.text or ""

            # og:title / og:image 通常最稳定
            title = ""
            thumbnail = ""

            m = re.search(r'<meta\s+property="og:title"\s+content="([^"]+)"', html)
            if m:
                title = m.group(1).strip()

            m = re.search(r'<meta\s+property="og:image"\s+content="([^"]+)"', html)
            if m:
                thumbnail = m.group(1).strip()

            # 兜底：title 标签
            if not title:
                m = re.search(r"<title>([^<]+)</title>", html)
                if m:
                    title = m.group(1).strip()
                    # 常见尾缀清理
                    for suffix in [" - 网易云音乐", "_网易云音乐", "网易云音乐"]:
                        if title.endswith(suffix):
                            title = title[: -len(suffix)].strip()
                            break

            return title, thumbnail
        except Exception as e:
            logger.debug(f"获取网易云歌单 meta 兜底失败: {str(e)}")
            return "", ""

    async def get_latest_videos(
        self,
        user_id: str,
        subscription_type: Optional[str] = None,
        max_count: int = 30,
        latest_video_time: Optional[datetime] = None,
        latest_video_id: Optional[str] = None,
        **kwargs
    ) -> Dict[str, Any]:
        all_videos = await self.get_all_videos(user_id, subscription_type)
        if not all_videos:
            return {"videos": [], "has_more": False}

        return {
            "videos": all_videos[:max_count],
            "has_more": len(all_videos) > max_count,
        }

    async def get_all_videos(
        self,
        user_id: str,
        subscription_type: Optional[str] = None,
        progress_callback: Optional[Callable] = None,
        **kwargs
    ) -> List[Dict[str, Any]]:
        from ..common import logger

        playlist_url = f"https://music.163.com/playlist?id={user_id}"

        try:
            import yt_dlp
        except ImportError:
            logger.error("yt-dlp 未安装，无法解析网易云歌单")
            return []

        # yt-dlp 配置与 routers/netease.parse_netease 中保持一致
        ydl_opts = {
            "quiet": True,
            "no_warnings": True,
            "extract_flat": "in_playlist",
            "no_cache_dir": True,
            "ignoreerrors": True,
            "socket_timeout": 300,
        }

        # 读取网易云 Cookie（如果存在）
        try:
            import os

            netease_cookie_path = "/app/database/cookie/netease_cookie.txt"
            if os.path.exists(netease_cookie_path):
                with open(netease_cookie_path, "r", encoding="utf-8") as f:
                    netease_cookie = f.read().strip()
                    if netease_cookie:
                        ydl_opts["cookiefile"] = netease_cookie_path
                        logger.info("网易云音乐 Cookie 已加载用于歌单解析")
        except Exception as e:
            logger.warning(f"读取网易云音乐 Cookie 失败（不影响主流程）: {str(e)}")

        import asyncio

        try:
            loop = asyncio.get_event_loop()
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = await loop.run_in_executor(None, ydl.extract_info, playlist_url, False)
        except Exception as e:
            logger.error(f"解析网易云歌单失败: {str(e)}")
            return []

        # 歌单封面和标题（有些字段只在顶层 info 上；flat 模式下有时为空）
        playlist_thumbnail = info.get("thumbnail") or info.get("thumbnail_url") or ""
        playlist_title = info.get("title") or f"网易云歌单 {user_id}"

        # 兜底：如果 yt-dlp 没拿到封面/标题，则直接抓歌单页面的 og meta
        if not playlist_thumbnail or not playlist_title or playlist_title == f"网易云歌单 {user_id}":
            fallback_title, fallback_thumb = await self._fetch_playlist_meta(playlist_url)
            if fallback_title and (not playlist_title or playlist_title == f"网易云歌单 {user_id}"):
                playlist_title = fallback_title
            if fallback_thumb and not playlist_thumbnail:
                playlist_thumbnail = fallback_thumb

        entries = info.get("entries") or []

        videos: List[Dict[str, Any]] = []
        for idx, entry in enumerate(entries):
            if not entry:
                continue
            # 如果子条目本身没有缩略图，则回退使用歌单封面
            if playlist_thumbnail and not entry.get("thumbnail") and not entry.get("thumbnail_url"):
                entry["thumbnail"] = playlist_thumbnail
            # 也把歌单标题透传下去，便于后续使用
            if playlist_title and not entry.get("playlist_title"):
                entry["playlist_title"] = playlist_title
            videos.append(entry)

        if progress_callback:
            try:
                await progress_callback(
                    {
                        "type": "sync_progress",
                        "current": len(videos),
                        "message": f"已获取 {len(videos)} 首歌曲",
                    }
                )
            except Exception:
                # 进度回调失败不影响主流程
                pass

        return videos

    def normalize_video_data(
        self,
        video: Dict[str, Any],
        subscription_type: Optional[str] = None
    ) -> Dict[str, Any]:
        from ..common import logger

        # yt-dlp 对网易云的条目通常包含 id、title、url 等字段
        song_id = video.get("id") or video.get("track_id") or ""
        title = video.get("title") or video.get("track") or ""
        url = video.get("url") or ""

        # 如果没有 URL，则根据 id 构造标准歌曲链接
        if not url and song_id:
            url = f"https://music.163.com/song?id={song_id}"

        # 发布时间（如果有 timestamp 字段则使用）
        publish_time = datetime.now()
        timestamp = video.get("timestamp")
        if timestamp:
            try:
                publish_time = datetime.fromtimestamp(timestamp)
            except Exception as e:
                logger.debug(f"网易云歌曲时间解析失败: {timestamp}, 错误: {str(e)}")

        return {
            "video_id": str(song_id),
            "title": title,
            "url": url,
            "cover_url": video.get("thumbnail") or video.get("thumbnail_url") or "",
            "publish_time": publish_time,
            "stats": {
                "view_count": 0,
                "like_count": 0,
                "comment_count": 0,
                "share_count": 0,
            },
        }

    def check_update_logic(
        self,
        latest_video: Dict[str, Any],
        subscription_latest_video_time: Optional[datetime],
        subscription_latest_video_id: Optional[str],
        subscription_type: Optional[str] = None
    ) -> bool:
        latest_video_id = str(latest_video.get("video_id") or latest_video.get("id") or "")
        return not subscription_latest_video_id or latest_video_id != str(subscription_latest_video_id or "")

