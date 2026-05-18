import os
import asyncio
import logging
import re
import uuid
from fastapi import APIRouter, HTTPException, Depends
from datetime import datetime, timezone
from typing import List, Optional, Dict, Any, Callable, Awaitable
import httpx
import time

# 配置日志
logger = logging.getLogger(__name__)

# 导入数据库模型
from sql.models import Task, TaskStatus, User
from sql.database_postgresql import get_db
from routers.auth import get_current_user

router = APIRouter(
    prefix="/api/subscribe/tiktok",
    tags=["tiktok"],
    responses={404: {"description": "Not found"}}
)


# ============================================================================
# TikTok API 错误类
# ============================================================================

class TikTokAPIError(Exception):
    """TikTok API 错误基类"""
    def __init__(self, error_type: str, message: str, retryable: bool = True, retry_delay: int = 5):
        self.error_type = error_type
        self.message = message
        self.retryable = retryable
        self.retry_delay = retry_delay
        super().__init__(message)


class NetworkError(TikTokAPIError):
    """网络连接错误"""
    def __init__(self, message: str, retry_delay: int = 5):
        super().__init__("network", message, retryable=True, retry_delay=retry_delay)


class RateLimitError(TikTokAPIError):
    """API限制错误"""
    def __init__(self, message: str, retry_delay: int = 30):
        super().__init__("rate_limit", message, retryable=True, retry_delay=retry_delay)


class ParseError(TikTokAPIError):
    """解析错误"""
    def __init__(self, message: str, retryable: bool = True):
        super().__init__("parse", message, retryable=retryable, retry_delay=5)


# ============================================================================
# TikTok API 类
# ============================================================================

class TikTokAPI:
    """TikTok API 封装类（基于 yt-dlp）"""
    
    def __init__(self):
        self.ytdl_available = self._check_ytdl()
        
    def _check_ytdl(self) -> bool:
        """检查 yt-dlp 是否可用"""
        try:
            import yt_dlp
            return True
        except ImportError:
            logger.warning("yt-dlp 未安装，TikTok 功能将不可用")
            return False
    
    async def get_user_info(self, user_url: str) -> Dict[str, Any]:
        """获取 TikTok 用户信息
        
        Args:
            user_url: TikTok 用户主页 URL（如 https://www.tiktok.com/@username）或用户名（如 @username 或 username）
            
        Returns:
            Dict: 用户信息字典
        """
        if not self.ytdl_available:
            raise TikTokAPIError("dependency", "yt-dlp 未安装", retryable=False)
        
        try:
            import yt_dlp
            
            # 提取用户名并构建完整URL
            username = self._extract_username(user_url)
            if not username:
                raise ParseError(f"无法从输入中提取用户名: {user_url}")
            
            # 统一将域名转换为小写，解决 yt-dlp 不支持大写域名的问题
            if user_url.startswith("http"):
                from urllib.parse import urlparse, urlunparse
                try:
                    parsed = urlparse(user_url)
                    user_url = urlunparse(parsed._replace(netloc=parsed.netloc.lower()))
                except Exception:
                    user_url = user_url.lower()
            
            # 如果输入不是完整URL，构建完整URL
            if not user_url.startswith("http"):
                user_url = f"https://www.tiktok.com/@{username}"
                logger.info(f"检测到直接输入的用户名，构建完整URL: {user_url}")
            
            # 使用 yt-dlp 获取用户信息
            ydl_opts = {
                'quiet': True,
                'no_warnings': True,
                'extract_flat': True,  # 只提取元数据，不下载
                'playlist_items': '1',  # 只获取第一个视频用于提取用户信息
            }
            
            # 读取 TikTok Cookie（如果存在）
            try:
                tiktok_cookie_file = '/app/database/cookie/tiktok_cookie.txt'
                if os.path.exists(tiktok_cookie_file):
                    with open(tiktok_cookie_file, 'r', encoding='utf-8') as f:
                        tiktok_cookie = f.read().strip()
                        if tiktok_cookie:
                            ydl_opts['cookiefile'] = tiktok_cookie_file
                            logger.info("TikTok Cookie 已加载用于获取用户信息")
            except Exception as e:
                logger.warning(f"读取 TikTok Cookie 失败: {str(e)}")
                # Cookie 读取失败不影响主流程
            
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = await asyncio.to_thread(ydl.extract_info, user_url, download=False)
                
                if not info:
                    raise ParseError(f"无法获取用户信息: {user_url}")
                
                # 提取头像：尝试从第一个视频的缩略图获取
                avatar_url = ''
                entries = info.get('entries', [])
                if entries and len(entries) > 0:
                    first_video = entries[0]
                    thumbnails = first_video.get('thumbnails', [])
                    if thumbnails:
                        # 优先使用 cover 或 originCover
                        for thumb in thumbnails:
                            if thumb.get('id') in ['cover', 'originCover']:
                                avatar_url = thumb.get('url', '')
                                break
                        # 如果没找到，使用第一个缩略图
                        if not avatar_url and len(thumbnails) > 0:
                            avatar_url = thumbnails[0].get('url', '')
                
                # 提取用户信息
                user_info = {
                    'user_id': username,
                    'nickname': info.get('title', username),  # 使用 title 作为昵称
                    'avatar_url': avatar_url,  # 使用第一个视频的缩略图作为头像
                    'signature': '',  # yt-dlp 不提供用户签名
                    'follower_count': None,  # yt-dlp 不提供粉丝数
                    'video_count': info.get('playlist_count', 0),
                }
                
                logger.info(f"成功获取 TikTok 用户信息: {username}")
                return user_info
                
        except Exception as e:
            logger.error(f"获取 TikTok 用户信息失败: {str(e)}")
            raise ParseError(f"获取用户信息失败: {str(e)}")
    
    async def get_user_videos(
        self,
        user_url: str,
        max_count: Optional[int] = 30,
        cursor: Optional[str] = None,
        progress_callback: Optional[Callable[[Dict[str, Any]], Awaitable[None]]] = None
    ) -> Dict[str, Any]:
        """获取 TikTok 用户视频列表
        
        Args:
            user_url: TikTok 用户主页 URL 或用户名（如 @username 或 username）
            max_count: 最大获取数量，None表示全量分页抓取
            cursor: 分页游标（暂不支持）
            progress_callback: 分页抓取进度回调（可选）
            
        Returns:
            Dict: 包含视频列表和分页信息
        """
        if not self.ytdl_available:
            raise TikTokAPIError("dependency", "yt-dlp 未安装", retryable=False)
        
        try:
            import yt_dlp
            
            username = self._extract_username(user_url)
            if not username:
                raise ParseError(f"无法从输入中提取用户名: {user_url}")
            
            # 统一将域名转换为小写
            if user_url.startswith("http"):
                from urllib.parse import urlparse, urlunparse
                try:
                    parsed = urlparse(user_url)
                    user_url = urlunparse(parsed._replace(netloc=parsed.netloc.lower()))
                except Exception:
                    user_url = user_url.lower()
            
            # 如果输入不是完整URL，构建完整URL
            if not user_url.startswith("http"):
                user_url = f"https://www.tiktok.com/@{username}"
                logger.info(f"检测到直接输入的用户名，构建完整URL: {user_url}")
            
            # 使用 yt-dlp 获取视频列表
            ydl_opts_base = {
                'quiet': True,
                'no_warnings': True,
                'extract_flat': 'in_playlist',  # 获取完整元数据（包括缩略图）
                'socket_timeout': 45,  # 分页长任务适当放宽超时
                'retries': 3,
            }
            
            # 读取 TikTok Cookie（如果存在）
            try:
                tiktok_cookie_file = '/app/database/cookie/tiktok_cookie.txt'
                if os.path.exists(tiktok_cookie_file):
                    with open(tiktok_cookie_file, 'r', encoding='utf-8') as f:
                        tiktok_cookie = f.read().strip()
                        if tiktok_cookie:
                            ydl_opts_base['cookiefile'] = tiktok_cookie_file
                            logger.info("TikTok Cookie 已加载用于获取视频列表")
            except Exception as e:
                logger.warning(f"读取 TikTok Cookie 失败: {str(e)}")
                # Cookie 读取失败不影响主流程

            def _entry_to_video_info(entry: Dict[str, Any]) -> Optional[Dict[str, Any]]:
                if not entry:
                    return None

                # 提取缩略图 URL
                cover_url = ''
                thumbnails = entry.get('thumbnails', [])
                if thumbnails:
                    # 优先使用 cover 或 originCover
                    for thumb in thumbnails:
                        if thumb.get('id') in ['cover', 'originCover']:
                            cover_url = thumb.get('url', '')
                            break
                    # 如果没找到，使用第一个缩略图
                    if not cover_url and len(thumbnails) > 0:
                        cover_url = thumbnails[0].get('url', '')

                # 如果 thumbnails 数组为空，尝试 thumbnail 字段
                if not cover_url:
                    cover_url = entry.get('thumbnail', '')

                # 使用时间戳（秒）
                create_time = entry.get('timestamp', 0)

                return {
                    'video_id': entry.get('id', ''),
                    'title': entry.get('title', ''),
                    'cover_url': cover_url,
                    'video_url': entry.get('url', ''),
                    'duration': entry.get('duration', 0),
                    'view_count': entry.get('view_count', 0),
                    'like_count': entry.get('like_count', 0),
                    'comment_count': entry.get('comment_count', 0),
                    'share_count': entry.get('repost_count', 0),
                    'create_time': create_time,
                    'description': entry.get('description', ''),
                }

            async def _extract_info_with_retry(
                ydl_opts: Dict[str, Any],
                page_desc: str,
                max_attempts: int = 3,
                fatal: bool = False,
            ) -> Optional[Dict[str, Any]]:
                last_error = None
                for attempt in range(1, max_attempts + 1):
                    try:
                        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                            return await asyncio.to_thread(ydl.extract_info, user_url, download=False)
                    except Exception as e:
                        last_error = e
                        if attempt < max_attempts:
                            wait_seconds = min(2 ** (attempt - 1), 5)
                            logger.warning(
                                f"TikTok抓取失败，准备重试: user={username}, {page_desc}, "
                                f"attempt={attempt}/{max_attempts}, wait={wait_seconds}s, error={str(e)}"
                            )
                            await asyncio.sleep(wait_seconds)
                        else:
                            logger.error(
                                f"TikTok抓取重试耗尽: user={username}, {page_desc}, "
                                f"attempt={attempt}/{max_attempts}, error={str(e)}"
                            )

                if fatal:
                    raise ParseError(f"TikTok抓取失败({page_desc}): {str(last_error)}")
                return None

            # 有数量限制时沿用一次性提取，减少请求次数
            if max_count is not None and max_count > 0:
                ydl_opts = dict(ydl_opts_base)
                ydl_opts['playlistend'] = max_count
                info = await _extract_info_with_retry(ydl_opts, "one-shot", max_attempts=3, fatal=True)

                if not info or 'entries' not in info:
                    raise ParseError(f"无法获取视频列表: {user_url}")

                videos = []
                for entry in info['entries']:
                    video_info = _entry_to_video_info(entry)
                    if video_info:
                        videos.append(video_info)

                result = {
                    'videos': videos,
                    'has_more': len(videos) >= max_count,
                    'cursor': None,  # yt-dlp 不支持游标分页
                }
                logger.info(f"成功获取 TikTok 用户 {username} 的 {len(videos)} 个视频")
                return result

            # 无数量限制时使用区间分页提取，避免大账号被单次提取截断
            page_size = 100
            start = 1
            videos = []
            seen_ids = set()
            expected_total = None
            consecutive_empty_pages = 0
            max_empty_pages = 2
            start_logged = False
            page_fetch_failed = False

            while True:
                end = start + page_size - 1
                page_opts = dict(ydl_opts_base)
                page_opts['playlist_items'] = f"{start}-{end}"
                page_desc = f"区间={start}-{end}"
                info = await _extract_info_with_retry(page_opts, page_desc, max_attempts=3, fatal=False)

                if not info:
                    page_fetch_failed = True
                    if not videos:
                        raise ParseError(f"TikTok分页抓取失败且无可用结果: user={username}, {page_desc}")
                    logger.warning(
                        f"TikTok分页抓取中断，返回已获取结果: user={username}, {page_desc}, 已获取={len(videos)}"
                    )
                    break

                if not start_logged:
                    expected_total = info.get('playlist_count')
                    logger.info(
                        f"TikTok分页抓取开始: user={username}, 预估总数={expected_total or '未知'}, 每页={page_size}"
                    )
                    start_logged = True

                entries = info.get('entries', []) or []
                page_new = 0
                for entry in entries:
                    video_info = _entry_to_video_info(entry)
                    if not video_info:
                        continue
                    vid = video_info.get('video_id') or ""
                    if not vid or vid in seen_ids:
                        continue
                    seen_ids.add(vid)
                    videos.append(video_info)
                    page_new += 1

                if page_new == 0:
                    consecutive_empty_pages += 1
                else:
                    consecutive_empty_pages = 0

                logger.info(
                    f"TikTok分页抓取: user={username}, 区间={start}-{end}, 本页新增={page_new}, 累计={len(videos)}"
                )

                if page_new > 0 and progress_callback:
                    try:
                        await progress_callback({
                            "type": "sync_progress",
                            "status": "syncing",
                            "message": f"正在全量同步TikTok视频... 已获取 {len(videos)} 条",
                            "count": len(videos)
                        })
                    except Exception as e:
                        logger.debug(f"TikTok分页进度回调失败: {str(e)}")

                if consecutive_empty_pages >= max_empty_pages:
                    break
                if expected_total and len(videos) >= int(expected_total):
                    break
                if len(entries) < page_size:
                    break

                start += page_size

            if page_fetch_failed:
                logger.warning(f"TikTok分页抓取因请求失败提前结束: user={username}, 当前累计={len(videos)}")
            elif expected_total and len(videos) < int(expected_total):
                logger.warning(
                    f"TikTok分页抓取可能不完整: user={username}, 预估={expected_total}, 实际={len(videos)}"
                )
            else:
                logger.info(f"TikTok分页抓取完成: user={username}, 共{len(videos)}条")

            return {
                'videos': videos,
                'has_more': False,
                'cursor': None,  # yt-dlp 不支持游标分页
            }
                
        except Exception as e:
            logger.error(f"获取 TikTok 视频列表失败: {str(e)}")
            raise ParseError(f"获取视频列表失败: {str(e)}")
    
    def _extract_username(self, url: str) -> Optional[str]:
        """从 URL 或直接输入中提取用户名
        
        Args:
            url: TikTok URL 或用户名（如 @username 或 username）
            
        Returns:
            str: 用户名，如果提取失败返回 None
        """
        # 支持的输入格式：
        # 1. 标准URL：https://www.tiktok.com/@username
        # 2. 带视频的URL：https://www.tiktok.com/@username/video/123456
        # 3. 直接输入用户名（带@）：@username
        # 4. 直接输入用户名（不带@）：username
        
        # 如果输入不是URL，可能是直接输入的用户名
        if not url.startswith("http"):
            # 移除开头的@符号（如果有）
            username = url.lstrip('@')
            # 验证用户名格式（TikTok用户名通常只包含字母、数字、下划线和点）
            if username and re.match(r'^[a-zA-Z0-9._]+$', username):
                logger.info(f"检测到直接输入的用户名: {username}")
                return username
            else:
                return None
        
        # 将URL中的域名部分统一转换为小写，解决大小写敏感问题
        original_url = url
        if url.startswith("http"):
            # 只处理域名部分，保留路径的大小写（路径有时对大小写敏感）
            from urllib.parse import urlparse, urlunparse
            try:
                parsed = urlparse(url)
                url = urlunparse(parsed._replace(netloc=parsed.netloc.lower()))
            except Exception:
                url = url.lower()
        
        # 从URL中提取用户名
        patterns = [
            r'tiktok\.com/@([^/\?]+)',
            r'@([a-zA-Z0-9._]+)',
        ]
        
        for pattern in patterns:
            match = re.search(pattern, url)
            if match:
                return match.group(1)
        
        # 如果从格式化后的URL没匹配到，尝试从原始URL匹配（作为兜底）
        for pattern in patterns:
            match = re.search(pattern, original_url)
            if match:
                return match.group(1)
        
        return None
    
    def _parse_upload_date(self, date_str: Optional[str]) -> int:
        """解析上传日期为时间戳
        
        Args:
            date_str: 日期字符串，格式如 "20231201"
            
        Returns:
            int: Unix 时间戳（秒）
        """
        if not date_str:
            return 0
        
        try:
            # yt-dlp 返回的日期格式：YYYYMMDD
            dt = datetime.strptime(date_str, "%Y%m%d")
            return int(dt.replace(tzinfo=timezone.utc).timestamp())
        except Exception as e:
            logger.warning(f"解析日期失败: {date_str}, {str(e)}")
            return 0


# ============================================================================
# 全局 API 实例
# ============================================================================

tiktok_api = TikTokAPI()


# ============================================================================
# API 端点
# ============================================================================

@router.get("/user/info")
async def get_tiktok_user_info(url: str, current_user: User = Depends(get_current_user)):
    """获取 TikTok 用户信息
    
    Args:
        url: TikTok 用户主页 URL
        
    Returns:
        Dict: 用户信息
    """
    try:
        user_info = await tiktok_api.get_user_info(url)
        return {
            "success": True,
            "data": user_info
        }
    except TikTokAPIError as e:
        logger.error(f"获取 TikTok 用户信息失败: {e.message}")
        raise HTTPException(status_code=400, detail=e.message)
    except Exception as e:
        logger.error(f"获取 TikTok 用户信息异常: {str(e)}")
        raise HTTPException(status_code=500, detail=f"服务器错误: {str(e)}")


@router.get("/user/videos")
async def get_tiktok_user_videos(
    url: str,
    max_count: int = 30,
    cursor: Optional[str] = None,
    current_user: User = Depends(get_current_user)
):
    """获取 TikTok 用户视频列表
    
    Args:
        url: TikTok 用户主页 URL
        max_count: 最大获取数量
        cursor: 分页游标
        
    Returns:
        Dict: 视频列表和分页信息
    """
    try:
        result = await tiktok_api.get_user_videos(url, max_count, cursor)
        return {
            "success": True,
            "data": result
        }
    except TikTokAPIError as e:
        logger.error(f"获取 TikTok 视频列表失败: {e.message}")
        raise HTTPException(status_code=400, detail=e.message)
    except Exception as e:
        logger.error(f"获取 TikTok 视频列表异常: {str(e)}")
        raise HTTPException(status_code=500, detail=f"服务器错误: {str(e)}")


@router.post("/test")
async def test_tiktok_connection(url: str, current_user: User = Depends(get_current_user)):
    """测试 TikTok 连接
    
    Args:
        url: TikTok 用户主页 URL
        
    Returns:
        Dict: 测试结果
    """
    try:
        # 测试获取用户信息
        user_info = await tiktok_api.get_user_info(url)
        
        # 测试获取视频列表（只获取1个）
        videos_result = await tiktok_api.get_user_videos(url, max_count=1)
        
        return {
            "success": True,
            "message": "TikTok 连接测试成功",
            "data": {
                "user_info": user_info,
                "video_count": len(videos_result.get('videos', []))
            }
        }
    except TikTokAPIError as e:
        logger.error(f"TikTok 连接测试失败: {e.message}")
        return {
            "success": False,
            "message": e.message,
            "error_type": e.error_type
        }
    except Exception as e:
        logger.error(f"TikTok 连接测试异常: {str(e)}")
        return {
            "success": False,
            "message": f"测试异常: {str(e)}",
            "error_type": "unknown"
        }


# ============================================================================
# TikTok 下载逻辑
# ============================================================================

async def tiktok_download_video_logic(
    task_id: str,
    url: str,
    download_dir: Optional[str] = None,
    subscription_id: Optional[str] = None
) -> bool:
    """TikTok 视频下载逻辑（使用 yt-dlp）"""
    import asyncio
    import aiohttp
    import threading
    
    # 统一将域名转换为小写，处理大小写敏感问题
    if url.startswith("http"):
        from urllib.parse import urlparse, urlunparse
        try:
            parsed = urlparse(url)
            url = urlunparse(parsed._replace(netloc=parsed.netloc.lower()))
        except Exception:
            url = url.lower()
            
    try:
        import yt_dlp
    except ImportError:
        logger.error("yt-dlp 未安装")
        _update_task_status(task_id, TaskStatus.ERROR, error_message="yt-dlp 未安装")
        return False
    
    # 确定下载目录
    if download_dir:
        base_dir = download_dir
    elif subscription_id:
        # 订阅下载：构建订阅目录
        from routers.subscribe import get_subscription_download_dir
        db = next(get_db())
        try:
            task = db.query(Task).filter(Task.id == task_id).first()
            title = task.title if task else "未知视频"
            base_dir = get_subscription_download_dir(subscription_id, title)
            if not base_dir:
                base_dir = '/app/downloads/tiktok'
        finally:
            try:
                db.rollback()
            except Exception:
                pass
            db.close()
    else:
        # 手动下载：使用默认目录
        base_dir = '/app/downloads/tiktok'
    
    # 确保目录存在
    os.makedirs(base_dir, exist_ok=True)
    
    # 输出文件模板
    outtmpl = f'{base_dir}/{task_id}.%(ext)s'
    
    # 进度回调
    def progress_hook(d):
        if d['status'] == 'downloading':
            try:
                if '_percent_str' in d:
                    progress_str = d['_percent_str']
                    if progress_str: # Add check for None or empty string
                        progress = float(progress_str.replace('%', '').strip())
                    else:
                        progress = 0.0
                elif 'downloaded_bytes' in d and 'total_bytes' in d:
                    progress = (d['downloaded_bytes'] / d['total_bytes']) * 100
                elif 'downloaded_bytes' in d and 'total_bytes_estimate' in d:
                    progress = (d['downloaded_bytes'] / d['total_bytes_estimate']) * 100
                else:
                    progress = 0.0
                
                progress = round(max(0.0, min(100.0, progress)), 1)
                
                # 时间节流：每300ms更新一次，让进度条更丝滑
                import time
                current_time = time.time()
                if not hasattr(progress_hook, 'last_update_time') or (current_time - progress_hook.last_update_time) >= 0.3:
                    _update_task_status(task_id, TaskStatus.DOWNLOADING, progress=progress)
                    progress_hook.last_update_time = current_time
            except (ValueError, TypeError, ZeroDivisionError):
                pass
        elif d['status'] == 'finished':
            _update_task_status(task_id, TaskStatus.DOWNLOADING, progress=95.0)
        elif d['status'] == 'processing':
            _update_task_status(task_id, TaskStatus.PROCESSING, progress=98.0)
    
    # yt-dlp 配置
    ydl_opts = {
        'format': 'best',  # TikTok 使用 best 格式（最高画质）
        'outtmpl': outtmpl,
        'progress_hooks': [progress_hook],
        'noprogress': True,
        'noplaylist': True,
        'overwrites': True,
        'no-mtime': True,
        'no_cache_dir': True,
        'retries': 3,
        'fragment_retries': 3,
        'socket_timeout': 30,
        'quiet': True,
        'no_warnings': True,
        'writethumbnail': True,  # 下载封面
        'writesubtitles': True,  # 下载字幕（如果有）
        'subtitleslangs': ['zh-Hans', 'zh-CN', 'zh', 'en'],  # 字幕语言优先级
    }
    
    # 读取 TikTok Cookie（如果存在）
    try:
        tiktok_cookie_file = '/app/database/cookie/tiktok_cookie.txt'
        if os.path.exists(tiktok_cookie_file):
            with open(tiktok_cookie_file, 'r', encoding='utf-8') as f:
                tiktok_cookie = f.read().strip()
                if tiktok_cookie:
                    ydl_opts['cookiefile'] = tiktok_cookie_file
                    logger.info("TikTok Cookie 已加载用于视频下载")
    except Exception as e:
        logger.warning(f"读取 TikTok Cookie 失败: {str(e)}")
        # Cookie 读取失败不影响主流程
    
    try:
        logger.info(f"开始下载 TikTok 视频: task_id={task_id}, url={url}")
        _update_task_status(task_id, TaskStatus.DOWNLOADING, progress=0.0)
        
        # 使用 yt-dlp 下载
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            # 在线程池中执行下载，避免阻塞
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(None, ydl.download, [url])
        
        # 下载完成
        logger.info(f"TikTok 视频下载完成: task_id={task_id}")
        
        # 查找下载的文件（视频、音频、图片）
        downloaded_file = None
        downloaded_audio = None
        downloaded_images = []
        
        for file in os.listdir(base_dir):
            if file.startswith(task_id):
                file_path = os.path.join(base_dir, file)
                if file.endswith(('.mp4', '.webm', '.mkv')):
                    downloaded_file = file_path
                elif file.endswith(('.mp3', '.m4a', '.aac', '.wav')):
                    downloaded_audio = file_path
                elif file.lower().endswith(('.webp', '.jpg', '.jpeg', '.png', '.image')):
                    downloaded_images.append(file_path)
        
        # 判断内容类型：视频 or 图片轮播
        is_image_slideshow = downloaded_file is None and (downloaded_audio or downloaded_images)
        
        if downloaded_file or is_image_slideshow:
            # 获取文件扩展名
            import subprocess
            import time
            from .dyd import sanitize_filename
            file_ext = os.path.splitext(downloaded_file)[1] if downloaded_file else None
            
            # 获取视频信息（用于生成 NFO）
            db = next(get_db())
            try:
                task_record = db.query(Task).filter(Task.id == task_id).first()
                video_title = task_record.title if task_record else task_id
            finally:
                try:
                    db.rollback()
                except Exception:
                    pass
                db.close()
            
            # 清理标题，用于文件夹名和文件名
            safe_title = sanitize_filename(video_title)
            
            # 统一添加后缀 (Task ID 前8位)，确保唯一性并防止同名覆盖
            # 这也同时解决了空标题的问题，因为 suffix 永远不为空
            safe_title = f"{safe_title}_{task_id[:8]}"
            
            # 创建内容专属文件夹：base_dir/标题_ID/
            content_folder = os.path.join(base_dir, safe_title)
            os.makedirs(content_folder, exist_ok=True)
            
            # 处理不同类型的内容
            if is_image_slideshow:
                logger.info(f"检测到图片轮播内容: task_id={task_id}, 音频: {'有' if downloaded_audio else '无'}, 图片: {len(downloaded_images)}张")
                
                # 移动音频文件
                if downloaded_audio:
                    audio_ext = os.path.splitext(downloaded_audio)[1]
                    final_audio = os.path.join(content_folder, f"{safe_title}{audio_ext}")
                    os.rename(downloaded_audio, final_audio)
                    logger.info(f"音频文件已保存: {final_audio}")
                
                # 移动和重命名图片文件
                for i, image_path in enumerate(downloaded_images, 1):
                    image_ext = os.path.splitext(image_path)[1]
                    final_image = os.path.join(content_folder, f"{safe_title}_image_{i:02d}{image_ext}")
                    os.rename(image_path, final_image)
                    logger.info(f"图片 {i} 已保存: {final_image}")
                
                # 设置主文件为音频文件或第一张图片
                main_file = final_audio if downloaded_audio else (os.path.join(content_folder, f"{safe_title}_image_01{os.path.splitext(downloaded_images[0])[1]}") if downloaded_images else None)
            else:
                # 传统视频文件处理
                final_file = os.path.join(content_folder, f"{safe_title}{file_ext}")
                os.rename(downloaded_file, final_file)
                main_file = final_file
            
            # 处理缩略图：转换为标准 JPG 格式（{filename_base}-poster.jpg）
            poster_path = os.path.join(content_folder, f"{safe_title}-poster.jpg")
            thumbnail_converted = False
            
            # 对于图片轮播，使用第一张图片作为封面
            if is_image_slideshow and downloaded_images:
                # 使用第一张图片作为封面
                first_image = os.path.join(content_folder, f"{safe_title}_image_01{os.path.splitext(downloaded_images[0])[1]}")
                if os.path.exists(first_image):
                    import shutil
                    shutil.copy2(first_image, poster_path)
                    thumbnail_converted = True
                    logger.info(f"使用第一张图片作为封面: {poster_path}")
            else:
                # 查找所有以 task_id 开头的图片文件（传统视频的缩略图）
                for aux_file in os.listdir(base_dir):
                    if aux_file.startswith(task_id) and aux_file.lower().endswith(('.webp', '.jpg', '.jpeg', '.png', '.image')):
                        old_thumb = os.path.join(base_dir, aux_file)
                        try:
                            thumb_ext = os.path.splitext(aux_file)[1].lower()
                            # 使用 ffmpeg 转换为标准 JPG
                            if thumb_ext in ['.webp', '.png', '.image']:
                                # 兼容 FFmpeg 6.x：优先用简化命令，失败再回退 mjpeg
                                cmd = [
                                    "ffmpeg", "-y", "-i", old_thumb,
                                    "-frames:v", "1", "-q:v", "2",
                                    poster_path
                                ]
                                result = subprocess.run(cmd, capture_output=True, timeout=20)
                                if result.returncode != 0 or not os.path.exists(poster_path):
                                    fallback_cmd = [
                                        "ffmpeg", "-y", "-i", old_thumb,
                                        "-frames:v", "1", "-q:v", "2",
                                        "-vcodec", "mjpeg",
                                        poster_path
                                    ]
                                    result = subprocess.run(fallback_cmd, capture_output=True, timeout=20)
                                if result.returncode == 0 and os.path.exists(poster_path):
                                    os.remove(old_thumb)
                                    thumbnail_converted = True
                                    logger.info(f"缩略图已转换为 JPG: {poster_path}")
                                else:
                                    # 转换失败，直接重命名
                                    os.rename(old_thumb, poster_path)
                                    thumbnail_converted = True
                                    logger.info(f"缩略图已移动（转换失败，直接重命名）: {poster_path}")
                            else:
                                # JPG 格式直接重命名
                                os.rename(old_thumb, poster_path)
                                thumbnail_converted = True
                                logger.info(f"缩略图已移动: {poster_path}")
                            
                            if thumbnail_converted:
                                os.utime(poster_path, (time.time(), time.time()))
                                break
                        except Exception as e:
                            logger.warning(f"处理缩略图失败: {aux_file}, {str(e)}")
            
            # 处理字幕文件
            for aux_file in os.listdir(base_dir):
                if aux_file.startswith(task_id) and aux_file.endswith(('.srt', '.vtt', '.ass')):
                    try:
                        aux_path = os.path.join(base_dir, aux_file)
                        # 提取语言代码（如 .zh-Hans.srt）
                        parts = aux_file.replace(task_id, '').split('.')
                        if len(parts) >= 3:  # 如：.zh-Hans.srt
                            lang_code = parts[1]
                            ext = parts[-1]
                            new_sub_name = f"{safe_title}.{lang_code}.{ext}"
                        else:
                            new_sub_name = aux_file.replace(task_id, safe_title)
                        new_sub_path = os.path.join(video_folder, new_sub_name)
                        os.rename(aux_path, new_sub_path)
                        os.utime(new_sub_path, (time.time(), time.time()))
                    except Exception as e:
                        logger.warning(f"处理字幕文件失败: {aux_file}, {str(e)}")
            
            # 生成 NFO 文件（Emby/Jellyfin 元数据）
            try:
                # 使用 yt-dlp 获取详细视频信息
                nfo_ydl_opts = {'quiet': True, 'no_warnings': True}
                
                # 为 NFO 生成也添加 Cookie 支持
                try:
                    tiktok_cookie_file = '/app/database/cookie/tiktok_cookie.txt'
                    if os.path.exists(tiktok_cookie_file):
                        with open(tiktok_cookie_file, 'r', encoding='utf-8') as f:
                            tiktok_cookie = f.read().strip()
                            if tiktok_cookie:
                                nfo_ydl_opts['cookiefile'] = tiktok_cookie_file
                except Exception as e:
                    logger.warning(f"NFO 生成读取 TikTok Cookie 失败: {str(e)}")
                
                with yt_dlp.YoutubeDL(nfo_ydl_opts) as ydl:
                    info = ydl.extract_info(url, download=False)
                
                # 生成 NFO 内容
                nfo_content = '<?xml version="1.0" encoding="UTF-8" standalone="yes" ?>\n<movie>\n'
                nfo_content += f'  <title>{video_title}</title>\n'
                nfo_content += f'  <originaltitle>{video_title}</originaltitle>\n'
                
                # 添加描述
                description = info.get('description', '')
                if description:
                    nfo_content += f'  <plot>{description}</plot>\n'
                
                # 添加上传者信息
                uploader = info.get('uploader', info.get('creator', ''))
                if uploader:
                    nfo_content += f'  <director>{uploader}</director>\n'
                    nfo_content += f'  <channel>{uploader}</channel>\n'
                
                # 添加上传时间
                upload_date = info.get('upload_date')
                if upload_date:
                    formatted_date = f"{upload_date[:4]}-{upload_date[4:6]}-{upload_date[6:8]}"
                    nfo_content += f'  <premiered>{formatted_date}</premiered>\n'
                    nfo_content += f'  <year>{upload_date[:4]}</year>\n'
                
                # 添加时长
                duration = info.get('duration')
                if duration:
                    nfo_content += f'  <runtime>{int(duration // 60)}</runtime>\n'
                
                # 添加观看次数
                view_count = info.get('view_count')
                if view_count:
                    nfo_content += f'  <playcount>{view_count}</playcount>\n'
                
                # 添加平台信息
                nfo_content += '  <studio>TikTok</studio>\n'
                nfo_content += '  <source>TikTok</source>\n'
                nfo_content += f'  <trailer>{url}</trailer>\n'
                nfo_content += '  <genre>短视频</genre>\n'
                
                # 引用 poster.jpg
                if thumbnail_converted:
                    nfo_content += f'  <thumb>{safe_title}-poster.jpg</thumb>\n'
                
                nfo_content += '</movie>'
                
                # 写入 NFO 文件
                nfo_path = os.path.join(content_folder, f"{safe_title}.nfo")
                with open(nfo_path, 'w', encoding='utf-8-sig') as f:
                    f.write(nfo_content)
                
                logger.info(f"已生成 NFO 文件: {nfo_path}")
            except Exception as e:
                logger.warning(f"生成 NFO 文件失败: {str(e)}")
            
            # 更新任务状态为完成
            if main_file:
                relative_path = main_file.replace('/app/downloads/', '')
                _update_task_status(
                    task_id,
                    TaskStatus.COMPLETED,
                    progress=100.0,
                    filename=relative_path
                )
            else:
                # 如果没有主文件，使用文件夹路径
                relative_path = content_folder.replace('/app/downloads/', '')
                _update_task_status(
                    task_id,
                    TaskStatus.COMPLETED,
                    progress=100.0,
                    filename=relative_path
                )
            
            # 下载完成发送通知逻辑
            try:
                import aiohttp
                import asyncio
                import threading
                
                db_notify = next(get_db())
                try:
                    task_notify = db_notify.query(Task).filter(Task.id == task_id).first()
                    if task_notify:
                        db_notify.refresh(task_notify)
                        
                    # 1. 准备基础数据
                    n_video_title = task_notify.title if task_notify and task_notify.title and not task_notify.title.startswith('http') else (os.path.basename(main_file) if main_file else "未知视频")
                    n_author_name = "手动下载"
                    n_platform_name = "TikTok"
                    n_current_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                    
                    # 2. 如果是订阅下载，丰富信息
                    if subscription_id:
                        from sql.models import SubscriptionVideo, Subscription
                        video_rec = db_notify.query(SubscriptionVideo).filter(SubscriptionVideo.download_task_id == task_id).first()
                        if video_rec:
                            video_rec.downloaded = 'true'
                            n_video_title = video_rec.title or n_video_title
                            sub_rec = db_notify.query(Subscription).filter(Subscription.id == subscription_id).first()
                            if sub_rec:
                                n_author_name = f"订阅博主: {sub_rec.nickname or '未知'}"
                        db_notify.commit()
                    
                    # 3. 获取封面图
                    extra_data = {}
                    try:
                        # 查找本地生成的海报
                        poster_filename = f"{safe_title}-poster.jpg"
                        poster_full_path = os.path.join(content_folder, poster_filename)
                        if os.path.exists(poster_full_path):
                            # 构造相对路径供通知服务使用
                            relative_poster_path = f"/downloads/{content_folder.replace('/app/downloads/', '')}/{poster_filename}"
                            extra_data["cover"] = relative_poster_path
                            logger.info(f"TikTok 通知将包含海报: {relative_poster_path}")
                    except Exception as _e:
                        logger.warning(f"TikTok 查找海报路径失败: {str(_e)}")

                    if subscription_id:
                        extra_data["subscription_id"] = subscription_id

                    # 4. 构造并发送通知
                    notification_data = {
                        "title": f"🎉 下载完成 ({n_platform_name})",
                        "content": f"内容《{n_video_title}》下载完成！\n\n🏷️ 来源: {n_platform_name}\n👤 {n_author_name}\n⏰ 完成时间: {n_current_time}",
                        "user_id": "default",
                        "extra_data": extra_data
                    }
                    
                    def send_notification_thread():
                        try:
                            async def send_notification():
                                try:
                                    connector = aiohttp.UnixConnector(path="/app/sockets/easy-vdl.sock")
                                    async with aiohttp.ClientSession(connector=connector) as session:
                                        await session.post("http://localhost/api/notifications/download-completed", json=notification_data)
                                except: pass
                            
                            loop = asyncio.new_event_loop()
                            asyncio.set_event_loop(loop)
                            try:
                                loop.run_until_complete(send_notification())
                            finally:
                                loop.close()
                        except: pass
                    
                    threading.Thread(target=send_notification_thread, daemon=True).start()
                finally:
                    db_notify.close()
            except Exception as e:
                logger.warning(f"TikTok 通知处理异常: {e}")
            
            # 强制归还系统内存 (Linux glibc)
            try:
                import ctypes
                libc = ctypes.CDLL("libc.so.6")
                libc.malloc_trim(0)
            except Exception:
                pass
            
            return True
        else:
            logger.error(f"未找到下载的文件: task_id={task_id}")
            _update_task_status(task_id, TaskStatus.ERROR, error_message="未找到下载的文件")
            
            # 发送失败通知
            try:
                import aiohttp
                import asyncio
                import threading
                def send_error_notify():
                    try:
                        async def send():
                            connector = aiohttp.UnixConnector(path="/app/sockets/easy-vdl.sock")
                            async with aiohttp.ClientSession(connector=connector) as session:
                                await session.post("http://localhost/api/notifications/download-error", json={
                                    "title": "❌ 下载失败 (TikTok)",
                                    "content": f"TikTok 视频下载失败：未找到文件\n🆔 任务: {task_id}",
                                    "user_id": "default",
                                    "extra_data": {
                                        "task_id": task_id,
                                        "url": url,
                                        "subscription_id": subscription_id
                                    }
                                })
                        loop = asyncio.new_event_loop()
                        asyncio.set_event_loop(loop)
                        loop.run_until_complete(send())
                    except: pass
                threading.Thread(target=send_error_notify, daemon=True).start()
            except: pass
            
            return False
            
    except Exception as e:
        logger.error(f"TikTok 视频下载失败: task_id={task_id}, error={str(e)}")
        
        # 发送失败通知
        try:
            import threading
            import aiohttp
            import asyncio
            def send_fail_notify():
                try:
                    async def send():
                        connector = aiohttp.UnixConnector(path="/app/sockets/easy-vdl.sock")
                        async with aiohttp.ClientSession(connector=connector) as session:
                             await session.post("http://localhost/api/notifications/download-error", json={
                                "title": "❌ 下载失败 (TikTok)",
                                "content": f"TikTok 视频下载出错\n🚫 错误: {str(e)[:200]}\n🆔 任务: {task_id}",
                                "user_id": "default",
                                "extra_data": {
                                    "task_id": task_id,
                                    "url": url,
                                    "subscription_id": subscription_id
                                }
                            })
                    loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(loop)
                    loop.run_until_complete(send())
                except: pass
            threading.Thread(target=send_fail_notify, daemon=True).start()
        except: pass
        
        # 检查是否是 Cookie 文件格式错误（可能是并发读取导致的临时性错误）
        error_msg = str(e)
        if "does not look like a Netscape format cookies file" in error_msg:
            logger.info(f"检测到 TikTok Cookie 格式错误，可能是并发读取导致，等待1秒后重试: task_id={task_id}")
            
            # 等待1秒，让文件系统缓存稳定
            await asyncio.sleep(1)
            
            # 重新尝试下载
            try:
                logger.info(f"重新下载 TikTok 视频（Cookie 重试）: task_id={task_id}")
                
                # 重新配置 yt-dlp（重新读取 Cookie）
                retry_ydl_opts = {
                    'format': 'best',
                    'outtmpl': outtmpl,
                    'progress_hooks': [progress_hook],
                    'noprogress': True,
                    'noplaylist': True,
                    'overwrites': True,
                    'no-mtime': True,
                    'no_cache_dir': True,
                    'retries': 3,
                    'fragment_retries': 3,
                    'socket_timeout': 30,
                    'quiet': True,
                    'no_warnings': True,
                    'writethumbnail': True,
                    'writesubtitles': True,
                    'subtitleslangs': ['zh-Hans', 'zh-CN', 'zh', 'en'],
                }
                
                # 重新读取 Cookie
                try:
                    tiktok_cookie_file = '/app/database/cookie/tiktok_cookie.txt'
                    if os.path.exists(tiktok_cookie_file):
                        with open(tiktok_cookie_file, 'r', encoding='utf-8') as f:
                            tiktok_cookie = f.read().strip()
                            if tiktok_cookie:
                                retry_ydl_opts['cookiefile'] = tiktok_cookie_file
                                logger.info("TikTok Cookie 已重新加载用于重试")
                except Exception as cookie_e:
                    logger.warning(f"重试时读取 TikTok Cookie 失败: {str(cookie_e)}")
                
                with yt_dlp.YoutubeDL(retry_ydl_opts) as ydl:
                    loop = asyncio.get_event_loop()
                    await loop.run_in_executor(None, ydl.download, [url])
                
                logger.info(f"TikTok 视频重试下载完成: task_id={task_id}")
                
                # 使用现有的文件处理逻辑
                # 查找下载的文件（视频、音频、图片）
                downloaded_file = None
                downloaded_audio = None
                downloaded_images = []
                
                for file in os.listdir(base_dir):
                    if file.startswith(task_id):
                        file_path = os.path.join(base_dir, file)
                        if file.endswith(('.mp4', '.webm', '.mkv')):
                            downloaded_file = file_path
                        elif file.endswith(('.mp3', '.m4a', '.aac', '.wav')):
                            downloaded_audio = file_path
                        elif file.lower().endswith(('.webp', '.jpg', '.jpeg', '.png', '.image')):
                            downloaded_images.append(file_path)
                
                # 判断内容类型：视频 or 图片轮播
                is_image_slideshow = downloaded_file is None and (downloaded_audio or downloaded_images)
                
                if downloaded_file or is_image_slideshow:
                    # 获取视频信息
                    db = next(get_db())
                    try:
                        task_record = db.query(Task).filter(Task.id == task_id).first()
                        video_title = task_record.title if task_record else task_id
                    finally:
                        try:
                            db.rollback()
                        except Exception:
                            pass
                        db.close()
                    
                    from .dyd import sanitize_filename
                    safe_title = sanitize_filename(video_title)
                    
                    # 创建内容专属文件夹
                    content_folder = os.path.join(base_dir, safe_title)
                    os.makedirs(content_folder, exist_ok=True)
                    
                    # 处理文件（简化版本，只处理主要文件）
                    main_file = None
                    if downloaded_file:
                        file_ext = os.path.splitext(downloaded_file)[1]
                        final_file = os.path.join(content_folder, f"{safe_title}{file_ext}")
                        os.rename(downloaded_file, final_file)
                        main_file = final_file
                    elif downloaded_audio:
                        audio_ext = os.path.splitext(downloaded_audio)[1]
                        final_audio = os.path.join(content_folder, f"{safe_title}{audio_ext}")
                        os.rename(downloaded_audio, final_audio)
                        main_file = final_audio
                    
                    if main_file:
                        relative_path = main_file.replace('/app/downloads/', '')
                        _update_task_status(task_id, TaskStatus.COMPLETED, progress=100.0, filename=relative_path)
                        logger.info(f"TikTok Cookie 重试成功完成: task_id={task_id}")
                        return True
                    else:
                        logger.warning(f"TikTok Cookie 重试未找到有效文件: task_id={task_id}")
                        _update_task_status(task_id, TaskStatus.ERROR, error_message="Cookie 重试未找到有效文件")
                        return False
                else:
                    logger.warning(f"TikTok Cookie 重试未找到下载文件: task_id={task_id}")
                    _update_task_status(task_id, TaskStatus.ERROR, error_message="Cookie 重试未找到下载文件")
                    return False
                    
            except Exception as retry_e:
                logger.error(f"TikTok Cookie 重试仍然失败: task_id={task_id}, error={str(retry_e)}")
                # 继续执行降级处理
        
        # 降级处理：尝试使用音频格式重新下载（适用于图片轮播内容）
        logger.info(f"尝试降级处理: task_id={task_id}, 使用音频格式重新下载")
        try:
            # 降级的yt-dlp配置：专门下载音频和缩略图
            fallback_ydl_opts = {
                'format': 'bestaudio',  # 只下载音频
                'outtmpl': outtmpl,
                'progress_hooks': [progress_hook],
                'noprogress': True,
                'noplaylist': True,
                'overwrites': True,
                'no-mtime': True,
                'no_cache_dir': True,
                'retries': 3,
                'fragment_retries': 3,
                'socket_timeout': 30,
                'quiet': True,
                'no_warnings': True,
                'writethumbnail': True,  # 下载封面
                'writeallthumnails': True,  # 下载所有缩略图（图片轮播）
                'extract_flat': False,  # 确保提取完整信息
            }
            
            # 为降级处理也添加 Cookie 支持
            try:
                tiktok_cookie_file = '/app/database/cookie/tiktok_cookie.txt'
                if os.path.exists(tiktok_cookie_file):
                    with open(tiktok_cookie_file, 'r', encoding='utf-8') as f:
                        tiktok_cookie = f.read().strip()
                        if tiktok_cookie:
                            fallback_ydl_opts['cookiefile'] = tiktok_cookie_file
                            logger.info("TikTok Cookie 已加载用于降级处理")
            except Exception as e:
                logger.warning(f"降级处理读取 TikTok Cookie 失败: {str(e)}")
                # Cookie 读取失败不影响主流程
            
            # 使用降级配置重新下载
            with yt_dlp.YoutubeDL(fallback_ydl_opts) as ydl:
                loop = asyncio.get_event_loop()
                await loop.run_in_executor(None, ydl.download, [url])
            
            logger.info(f"降级处理下载完成: task_id={task_id}")
            
            # 查找下载的文件（音频或图片）
            downloaded_audio = None
            downloaded_images = []
            
            for file in os.listdir(base_dir):
                if file.startswith(task_id):
                    file_path = os.path.join(base_dir, file)
                    if file.endswith(('.mp3', '.m4a', '.aac', '.wav')):
                        downloaded_audio = file_path
                    elif file.lower().endswith(('.webp', '.jpg', '.jpeg', '.png', '.image')):
                        downloaded_images.append(file_path)
            
            if downloaded_audio or downloaded_images:
                logger.info(f"降级处理成功: task_id={task_id}, 音频: {'有' if downloaded_audio else '无'}, 图片: {len(downloaded_images)}张")
                
                # 处理下载的文件（使用现有的文件处理逻辑）
                # 获取视频信息
                db = next(get_db())
                try:
                    task_record = db.query(Task).filter(Task.id == task_id).first()
                    video_title = task_record.title if task_record else task_id
                finally:
                    try:
                        db.rollback()
                    except Exception:
                        pass
                    db.close()
                
                from .dyd import sanitize_filename
                safe_title = sanitize_filename(video_title)
                
                # 创建内容专属文件夹
                content_folder = os.path.join(base_dir, safe_title)
                os.makedirs(content_folder, exist_ok=True)
                
                # 移动音频文件
                if downloaded_audio:
                    audio_ext = os.path.splitext(downloaded_audio)[1]
                    final_audio = os.path.join(content_folder, f"{safe_title}{audio_ext}")
                    os.rename(downloaded_audio, final_audio)
                    logger.info(f"音频文件已保存: {final_audio}")
                
                # 移动图片文件
                for i, image_path in enumerate(downloaded_images, 1):
                    image_ext = os.path.splitext(image_path)[1]
                    final_image = os.path.join(content_folder, f"{safe_title}_image_{i:02d}{image_ext}")
                    os.rename(image_path, final_image)
                    logger.info(f"图片 {i} 已保存: {final_image}")
                
                # 生成封面（使用第一张图片或音频文件）
                poster_path = os.path.join(content_folder, f"{safe_title}-poster.jpg")
                if downloaded_images:
                    # 使用第一张图片作为封面
                    first_image = os.path.join(content_folder, f"{safe_title}_image_01{os.path.splitext(downloaded_images[0])[1]}")
                    if os.path.exists(first_image):
                        import shutil
                        shutil.copy2(first_image, poster_path)
                        logger.info(f"使用第一张图片作为封面: {poster_path}")
                
                # 设置主文件路径（用于任务状态更新）
                main_file = final_audio if downloaded_audio else (os.path.join(content_folder, f"{safe_title}_image_01{os.path.splitext(downloaded_images[0])[1]}") if downloaded_images else None)
                
                if main_file:
                    relative_path = main_file.replace('/app/downloads/', '')
                    _update_task_status(task_id, TaskStatus.COMPLETED, progress=100.0, filename=relative_path)
                    logger.info(f"降级处理完成: task_id={task_id}, 主文件: {relative_path}")
                    return True
                else:
                    logger.warning(f"降级处理未找到有效文件: task_id={task_id}")
                    _update_task_status(task_id, TaskStatus.ERROR, error_message=f"原始下载失败: {str(e)}，降级处理未找到有效文件")
                    return False
            else:
                logger.warning(f"降级处理也未找到文件: task_id={task_id}")
                _update_task_status(task_id, TaskStatus.ERROR, error_message=f"原始下载失败: {str(e)}，降级处理也未找到文件")
                return False
                
        except Exception as fallback_error:
            logger.error(f"降级处理异常: task_id={task_id}, error={str(fallback_error)}")
            _update_task_status(task_id, TaskStatus.ERROR, error_message=f"原始下载失败: {str(e)}，降级处理异常: {str(fallback_error)}")
            return False


_tiktok_progress_throttle: Dict[str, Dict[str, float]] = {}


def _update_task_status(
    task_id: str,
    status: TaskStatus,
    progress: Optional[float] = None,
    filename: Optional[str] = None,
    error_message: Optional[str] = None
):
    """更新任务状态（带节流）

    中间态（PENDING / DOWNLOADING / PROCESSING）根据时间+进度变化进行节流，
    终态（COMPLETED / ERROR / CANCELLED）每次必写。
    """
    global _tiktok_progress_throttle

    status_str = status.value
    intermediate_statuses = {
        TaskStatus.PENDING.value,
        TaskStatus.DOWNLOADING.value,
        TaskStatus.PROCESSING.value,
    }

    safe_progress = None
    if progress is not None:
        try:
            safe_progress = float(progress)
            safe_progress = max(0.0, min(100.0, safe_progress))
        except Exception:
            safe_progress = None

    # 对中间态进行节流
    if status_str in intermediate_statuses:
        now_ts = time.time()
        state = _tiktok_progress_throttle.get(task_id)
        last_ts = state["ts"] if state else 0
        last_progress = state["progress"] if state else None

        allow = False
        if now_ts - last_ts >= 2:
            allow = True
        elif safe_progress is not None and last_progress is not None:
            if abs(safe_progress - last_progress) >= 3.0:
                allow = True

        if not allow:
            _tiktok_progress_throttle[task_id] = {
                "ts": now_ts,
                "progress": safe_progress if safe_progress is not None else last_progress,
            }
            return

    db = next(get_db())
    try:
        task = db.query(Task).filter(Task.id == task_id).first()
        if task:
            task.status = status_str
            task.updated_at = datetime.now()

            if safe_progress is not None:
                task.progress = safe_progress

            if filename:
                task.filename = filename

            if error_message:
                task.error_message = error_message

            db.commit()

            # 记录真实写库时间与进度
            _tiktok_progress_throttle[task_id] = {
                "ts": time.time(),
                "progress": task.progress,
            }

            # 广播任务状态更新
            try:
                import asyncio
                from routers.websocket import broadcast_message

                progress_data = {
                    'type': 'progress_update',
                    'task': {
                        'id': task_id,
                        'status': status_str,
                        'progress': task.progress,
                        'updated_at': task.updated_at.isoformat(),
                        'filename': task.filename,
                        'source': task.source,
                        'title': task.title,
                        'url': task.url,
                        'subscription_id': task.subscription_id
                    }
                }

                async def send_progress_update():
                    try:
                        await broadcast_message('downloads', progress_data)
                    except Exception as e:
                        logger.warning(f"发送WebSocket进度更新失败: {str(e)}")

                try:
                    loop = asyncio.get_running_loop()
                    asyncio.create_task(send_progress_update())
                except RuntimeError:
                    loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(loop)
                    try:
                        loop.run_until_complete(send_progress_update())
                    finally:
                        loop.close()

            except Exception as e:
                logger.warning(f"WebSocket进度更新失败: {str(e)}")
    except Exception as e:
        logger.error(f"更新任务状态失败: {str(e)}")
        db.rollback()
    finally:
        try:
            db.rollback()
        except Exception:
            pass
        db.close()
