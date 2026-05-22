"""
订阅模块工具函数
"""
import asyncio
import os
import shutil
import uuid
import json
import time
from datetime import datetime
from contextlib import contextmanager
from typing import Optional, List
from sqlalchemy.orm import Session
from sql.database_postgresql import get_db
from sql.models import Subscription, SubscriptionVideo, Task, TaskStatus
from .common import logger, cancelled_batch_downloads, task_completion_events, task_completion_lock, MAX_DOUYIN_BROWSER_ACTIVE_TASKS, get_platform_anti_crawl_config
from routers.websocket import send_progress_update
from routers.dyd import sanitize_filename
from routers.douyin import parse_collection_url

# 平台页面清理冷却窗口（统一1分钟）：减少频繁重建页面，同时控制资源占用
DOUYIN_PAGE_CLEANUP_COOLDOWN_SECONDS = 1 * 60
_last_douyin_page_cleanup_ts = 0.0
_douyin_cleanup_lock = asyncio.Lock()
# B站页面清理冷却窗口（统一1分钟）
BILIBILI_PAGE_CLEANUP_COOLDOWN_SECONDS = 1 * 60
_last_bilibili_page_cleanup_ts = 0.0
_bilibili_cleanup_lock = asyncio.Lock()
# 小红书页面清理冷却窗口（统一1分钟）
XHS_PAGE_CLEANUP_COOLDOWN_SECONDS = 1 * 60
_last_xhs_page_cleanup_ts = 0.0
_xhs_cleanup_lock = asyncio.Lock()


# ============================================================================
# 基础工具函数
# ============================================================================

async def _is_douyin_collection_url(url: Optional[str]) -> bool:
    """判断给定链接或ID是否为抖音合集
    优先根据明显的路径特征判断；否则尝试通过解析函数判定（兼容短链和直接输入的ID）。
    参考旧版实现，但优化了对用户主页链接的处理，避免产生不必要的错误日志。
    """
    try:
        if not url:
            return False
        
        # 优先检查：如果URL明显是用户主页、单个视频或单个图集格式，直接返回False，避免不必要的解析
        # 这样可以避免对单视频/单主页调用 parse_collection_url 产生错误日志与误判
        if ("/user/" in url or "/video/" in url or "/note/" in url) and "/collection/" not in url:
            # 明确是用户主页、单个视频或图集链接，不是合集
            return False
        
        # 明确包含合集路径
        if "/collection/" in url:
            return True
        
        # 对于短链接，先检查重定向后的URL是否为用户主页/视频/图集（参考旧版逻辑）
        if "v.douyin.com" in url:
            try:
                import httpx
                async with httpx.AsyncClient() as client:
                    response = await client.get(url, follow_redirects=True, timeout=5.0)
                    real_url = str(response.url)
                    # 如果重定向后是用户主页、视频或图集，直接返回False
                    if ("/user/" in real_url or "/video/" in real_url or "/note/" in real_url) and "/collection/" not in real_url:
                        return False
                    # 如果重定向后是合集链接，返回True
                    if "/collection/" in real_url:
                        return True
            except Exception:
                # 短链接解析失败，继续尝试其他方法
                pass
        
        # 如果是纯数字且长度大于10，可能是合集ID
        if url.isdigit() and len(url) > 10:
            try:
                info = await parse_collection_url(url)
                if info and info.get("collection_id"):
                    return True
            except Exception:
                # 解析失败则视为非合集（这是正常的，不需要记录错误）
                pass
        
        # 尝试用合集解析方法解析（内部应处理 v.douyin.com 短链展开和直接ID输入）
        # 注意：只有在无法明确判断的情况下才尝试解析，避免对用户主页链接产生错误日志
        try:
            info = await parse_collection_url(url)
            if info and info.get("collection_id"):
                return True
        except Exception:
            # 解析失败则视为非合集（这是正常的，不需要记录错误）
            return False
        return False
    except Exception:
        return False


async def _cleanup_subscription_pages(platform: str, user_id: str):
    """清理订阅对应的标签页
    
    Args:
        platform: 平台名称
        user_id: 用户ID
    """
    from routers.unified_browser_manager import unified_browser
    
    try:
        # 抖音页面默认复用，按冷却窗口执行清理，降低频繁重建导致的风控概率
        if platform in {"douyin", "douyin_collection"}:
            global _last_douyin_page_cleanup_ts
            now_ts = time.time()
            async with _douyin_cleanup_lock:
                elapsed = now_ts - _last_douyin_page_cleanup_ts
                if elapsed < DOUYIN_PAGE_CLEANUP_COOLDOWN_SECONDS:
                    logger.info(
                        "[DouyinAntiRisk] 跳过抖音标签页清理（冷却中）: elapsed=%.1fs cooldown=%ss",
                        elapsed,
                        DOUYIN_PAGE_CLEANUP_COOLDOWN_SECONDS,
                    )
                    return
                _last_douyin_page_cleanup_ts = now_ts
        elif platform in {"bilibili", "bilibili_collection"}:
            global _last_bilibili_page_cleanup_ts
            now_ts = time.time()
            async with _bilibili_cleanup_lock:
                elapsed = now_ts - _last_bilibili_page_cleanup_ts
                if elapsed < BILIBILI_PAGE_CLEANUP_COOLDOWN_SECONDS:
                    logger.info(
                        "[BilibiliAntiRisk] 跳过B站标签页清理（冷却中）: elapsed=%.1fs cooldown=%ss",
                        elapsed,
                        BILIBILI_PAGE_CLEANUP_COOLDOWN_SECONDS,
                    )
                    return
                _last_bilibili_page_cleanup_ts = now_ts
        elif platform == "xiaohongshu":
            global _last_xhs_page_cleanup_ts
            now_ts = time.time()
            async with _xhs_cleanup_lock:
                elapsed = now_ts - _last_xhs_page_cleanup_ts
                if elapsed < XHS_PAGE_CLEANUP_COOLDOWN_SECONDS:
                    logger.info(
                        "[XhsAntiRisk] 跳过小红书标签页清理（冷却中）: elapsed=%.1fs cooldown=%ss",
                        elapsed,
                        XHS_PAGE_CLEANUP_COOLDOWN_SECONDS,
                    )
                    return
                _last_xhs_page_cleanup_ts = now_ts

        # 根据平台构建页面键名
        page_keys_to_cleanup = []
        
        if platform == "youtube":
            # YouTube 订阅会创建 "youtube:*" 独立页面（频道/播放列表/临时页），
            # 这里统一按前缀清理，避免仅关闭基础页导致残留。
            all_page_keys = list(unified_browser._pages.keys())
            for page_key in all_page_keys:
                if page_key == "youtube" or (page_key.startswith("youtube:") and page_key != "youtube_login"):
                    page_keys_to_cleanup.append(page_key)
        elif platform == "youtube_playlist":
            # YouTube播放列表页面
            page_keys_to_cleanup.append(f"youtube:playlist_{user_id}")
        elif platform == "douyin":
            # 抖音页面（通用键名）
            page_keys_to_cleanup.append("douyin")
        elif platform == "douyin_collection":
            # 抖音合集页面（通用键名）
            page_keys_to_cleanup.append("douyin")
        elif platform == "bilibili":
            # B站页面（通用键名）
            page_keys_to_cleanup.append("bilibili")
        elif platform == "bilibili_collection":
            # B站合集页面（通用键名）
            page_keys_to_cleanup.append("bilibili")
        elif platform == "xiaohongshu":
            # 小红书页面（通用键名）
            page_keys_to_cleanup.append("xiaohongshu")
        
        # 清理对应的标签页
        for page_key in page_keys_to_cleanup:
            try:
                await unified_browser.close_page(page_key)
                logger.info(f"已清理订阅标签页: {page_key}")
            except Exception as e:
                logger.debug(f"清理标签页 {page_key} 失败（可能已关闭）: {str(e)}")
                
    except Exception as e:
        logger.warning(f"清理订阅标签页时出错: {str(e)}")


async def _cleanup_platform_pages(platform: str):
    """清理平台相关的所有标签页
    
    Args:
        platform: 平台名称
    """
    from routers.unified_browser_manager import unified_browser
    
    try:
        # 获取所有页面键名
        all_page_keys = list(unified_browser._pages.keys())
        cleaned_count = 0
        
        for page_key in all_page_keys:
            should_cleanup = False
            
            # 根据平台判断是否需要清理
            if platform == "youtube":
                # YouTube相关页面：清理基础页面 "youtube" 和带前缀的独立页面 "youtube:xxx"
                if page_key == "youtube" or (page_key.startswith("youtube:") and page_key != "youtube_login"):
                    should_cleanup = True
            elif platform == "youtube_playlist" and page_key.startswith("youtube:playlist_"):
                # YouTube播放列表页面
                should_cleanup = True
            elif platform in ["douyin", "douyin_collection"] and page_key == "douyin":
                # 抖音相关页面
                should_cleanup = True
            elif platform in ["bilibili", "bilibili_collection"] and page_key == "bilibili":
                # B站页面
                should_cleanup = True
            
            if should_cleanup:
                try:
                    await unified_browser.close_page(page_key)
                    cleaned_count += 1
                    logger.debug(f"已清理平台标签页: {page_key}")
                except Exception as e:
                    logger.debug(f"清理标签页 {page_key} 失败（可能已关闭）: {str(e)}")
        
        if cleaned_count > 0:
            logger.info(f"平台 {platform} 批量同步完成，已清理 {cleaned_count} 个标签页")
        else:
            logger.debug(f"平台 {platform} 无需清理标签页")
            
    except Exception as e:
        logger.warning(f"清理平台 {platform} 标签页时出错: {str(e)}")


def get_subscription_download_dir(subscription_id: str, video_title: str) -> str:
    """构建订阅下载的目录路径
    
    Args:
        subscription_id: 订阅ID
        video_title: 视频标题
        
    Returns:
        完整的下载目录路径
    """
    db = next(get_db())
    try:
        # 获取订阅信息。
        subscription = db.query(Subscription).filter(Subscription.id == subscription_id).first()
        if not subscription:
            return None
            
        # 构建目录路径：subscriptions/platform/作者名/
        platform = subscription.platform.lower()
        # 抖音合集、油管合集、B站合集使用与主平台相同的目录结构
        if platform == "douyin_collection":
            platform = "douyin"
        elif platform == "youtube_playlist":
            platform = "youtube"
        elif platform == "bilibili_collection":
            platform = "bilibili"
        author_name = subscription.nickname or "未知作者"
        safe_author_name = (subscription.storage_name or "").strip()

        # 历史数据兼容：缺少 storage_name 时按当前昵称生成一次并固化
        if not safe_author_name:
            safe_author_name = sanitize_filename(author_name)
            if not safe_author_name or safe_author_name.strip('._ ') == '' or safe_author_name == "untitled":
                safe_author_name = f"author_{str(subscription_id)[:8]}"
                logger.warning(
                    f"订阅昵称清洗后为空，使用兜底目录名: subscription_id={subscription_id}, "
                    f"nickname={author_name}, safe_author_name={safe_author_name}"
                )
            try:
                subscription.storage_name = safe_author_name
                db.commit()
                logger.info(
                    f"已为历史订阅固化目录名: subscription_id={subscription_id}, storage_name={safe_author_name}"
                )
            except Exception as e:
                db.rollback()
                logger.warning(f"固化订阅目录名失败，将继续使用临时目录名: {str(e)}")
        
        # 构建作者目录路径（不包含视频标题）
        download_dir = f"/app/downloads/subscriptions/{platform}/{safe_author_name}"
        
        # 确保目录存在
        try:
            if not os.path.exists(download_dir):
                os.makedirs(download_dir, exist_ok=True)
                logger.info(f"已创建订阅下载目录: {download_dir}")
            # 目录已存在时不记录日志，减少重复日志
        except Exception as e:
            logger.error(f"创建订阅下载目录失败: {str(e)}")
            return None
        
        return download_dir
        
    except Exception as e:
        logger.error(f"构建订阅下载目录失败: {str(e)}")
        return None
    finally:
        try:
            db.rollback()
        except Exception:
            pass
        db.close()


@contextmanager
def get_db_context():
    """数据库连接上下文管理器，自动管理连接生命周期"""
    db = next(get_db())
    try:
        yield db
    except Exception:
        db.rollback()
        raise
    finally:
        try:
            db.rollback()  # 确保事务被正确结束
        except Exception:
            pass
        db.close()


# ============================================================================
# 下载相关工具函数
# ============================================================================

async def update_batch_download_progress(db: Session, subscription_id: str, status: str = None, progress: int = None, completed: int = None, failed: int = None):
    """更新批量下载进度
    
    Args:
        db: 数据库会话
        subscription_id: 订阅ID
        status: 下载状态
        progress: 当前进度
        completed: 完成数量
        failed: 失败数量
    """
    try:
        subscription = db.query(Subscription).filter(
            Subscription.id == subscription_id
        ).first()
        
        if not subscription:
            logger.error(f"未找到订阅: {subscription_id}")
            return
            
        if status:
            subscription.batch_download_status = status
        if progress is not None:
            subscription.batch_download_progress = progress
        if completed is not None:
            subscription.batch_download_completed = completed
        if failed is not None:
            subscription.batch_download_failed = failed
            
        db.commit()
        
        # 发送WebSocket更新（包含订阅信息，以便前端显示头像、昵称等）
        websocket_data = {
            "type": "batch_download_progress",
            "status": subscription.batch_download_status,
            "progress": subscription.batch_download_progress,
            "total": subscription.batch_download_total,
            "completed": subscription.batch_download_completed,
            "failed": subscription.batch_download_failed,
            # 包含订阅信息，前端需要这些信息来显示头像、昵称等
            "subscription": {
                "id": subscription.id,
                "nickname": subscription.nickname,
                "platform": subscription.platform,
                "avatar_url": subscription.avatar_url
            }
        }
        # 发送WebSocket更新
        await send_progress_update(subscription_id, websocket_data)
        
    except Exception as e:
        logger.error(f"更新批量下载进度失败: {str(e)}")
        db.rollback()


async def _async_add_download(video_id: str, quality: str):
    """异步添加下载任务，避免阻塞主事务
    
    Args:
        video_id: 订阅视频ID
        quality: 画质设置
    """
    try:
        # 等待一小段时间，确保主事务已完成
        await asyncio.sleep(0.5)
        
        # 使用新的数据库会话重新获取视频对象
        db = next(get_db())
        fresh_video = None
        
        try:
            # 重新获取视频信息，确保数据是最新的
            video_obj = db.query(SubscriptionVideo).filter(
                SubscriptionVideo.id == video_id
            ).first()
            
            if not video_obj:
                logger.error(f"未找到视频: {video_id}")
                return
                
            if video_obj.downloaded.lower() == "true":
                logger.info(f"视频已被其他任务下载: {video_obj.title}")
                return
                
            # 将对象从会话中分离，以便在会话关闭后使用
            db.expunge(video_obj)
            fresh_video = video_obj
            
        finally:
            try:
                db.rollback()
            except Exception:
                pass
            db.close()
            
        # 在会话关闭后调用下载管理器（避免同时持有两个连接导致死锁或池耗尽）
        if fresh_video:
            from routers.downloader import download_manager
            # 使用订阅保存的画质设置
            await download_manager.add_subscription_download(fresh_video, quality)
            
    except Exception as e:
        logger.error(f"异步添加下载任务失败: {str(e)}")


async def delayed_download(video_id: str, _: Session = None, delay_seconds: int = 60):
    """延迟下载视频
    
    Args:
        video_id: 视频ID
        _: 废弃的数据库会话参数（为保持兼容性）
        delay_seconds: 延迟秒数
    """
    await asyncio.sleep(delay_seconds)
    
    # 使用新的数据库会话
    db = next(get_db())
    try:
        # 重新获取视频信息
        video = db.query(SubscriptionVideo).filter(
            SubscriptionVideo.id == video_id
        ).first()
        
        if not video:
            logger.error(f"未找到视频: {video_id}")
            return
            
        if video.downloaded.lower() == "true":
            logger.info(f"视频已被其他任务下载: {video.title}")
            return
        
        # 从订阅中获取画质设置
        subscription = db.query(Subscription).filter(
            Subscription.id == video.subscription_id
        ).first()
        
        quality = subscription.quality if subscription and subscription.quality else "best"
        
        logger.info(f"开始下载延迟的视频: {video.title}，画质设置: {quality}")
        from routers.downloader import download_manager
        await download_manager.add_subscription_download(video, quality)
        
    except Exception as e:
        logger.error(f"延迟下载失败: {str(e)}")
    finally:
        try:
            db.rollback()
        except Exception:
            pass
        db.close()


# ============================================================================
# 文件操作工具函数
# ============================================================================

async def _force_delete_directory(directory_path: str, max_retries: int = 3):
    """强制删除目录，包含重试机制和文件权限处理"""
    import stat
    
    for attempt in range(max_retries):
        try:
            if not os.path.exists(directory_path):
                return
                
            # 首先尝试正常删除
            shutil.rmtree(directory_path)
            return
            
        except PermissionError as e:
            logger.warning(f"权限错误，尝试修复文件权限 (尝试 {attempt + 1}/{max_retries}): {str(e)}")
            # 修复文件权限
            await _fix_file_permissions(directory_path)
            await asyncio.sleep(1)
            
        except OSError as e:
            if "Directory not empty" in str(e) or "Device or resource busy" in str(e):
                logger.warning(f"目录删除失败，尝试强制删除 (尝试 {attempt + 1}/{max_retries}): {str(e)}")
                # 尝试强制删除
                await _force_delete_files(directory_path)
                await asyncio.sleep(1)
            else:
                raise e
                
        except Exception as e:
            if attempt == max_retries - 1:
                raise e
            logger.warning(f"删除失败，重试中 (尝试 {attempt + 1}/{max_retries}): {str(e)}")
            await asyncio.sleep(2)
    
    # 如果所有重试都失败了，抛出异常
    raise Exception(f"无法删除目录 {directory_path}，已重试 {max_retries} 次")


async def _fix_file_permissions(directory_path: str):
    """修复目录中文件的权限（NAS 兼容模式：777/666）"""
    try:
        for root, dirs, files in os.walk(directory_path):
            # 修复目录权限为 777 (rwxrwxrwx)
            for dir_name in dirs:
                dir_path = os.path.join(root, dir_name)
                try:
                    os.chmod(dir_path, 0o777)
                except:
                    pass
            
            # 修复文件权限为 666 (rw-rw-rw-)
            for file_name in files:
                file_path = os.path.join(root, file_name)
                try:
                    os.chmod(file_path, 0o666)
                except:
                    pass
    except Exception as e:
        logger.warning(f"修复文件权限失败: {str(e)}")


async def _force_delete_files(directory_path: str):
    """强制删除目录中的文件"""
    try:
        for root, dirs, files in os.walk(directory_path, topdown=False):
            # 先删除文件
            for file_name in files:
                file_path = os.path.join(root, file_name)
                try:
                    os.unlink(file_path)
                except:
                    pass
            
            # 再删除目录
            for dir_name in dirs:
                dir_path = os.path.join(root, dir_name)
                try:
                    os.rmdir(dir_path)
                except:
                    pass
        
        # 最后删除根目录
        try:
            os.rmdir(directory_path)
        except:
            pass
            
    except Exception as e:
        logger.warning(f"强制删除文件失败: {str(e)}")


# ============================================================================
# URL和通知工具函数
# ============================================================================

def get_correct_douyin_url(aweme_id: str, item_data: dict) -> str:
    """根据内容类型生成正确的抖音URL（统一版本，保留此定义）
    
    Args:
        aweme_id: 抖音内容ID
        item_data: 抖音API返回的item数据
        
    Returns:
        str: 正确的抖音URL（/note/用于图集，/video/用于视频）
    """
    images = item_data.get('images')
    if images and len(images) > 0:
        return f"https://www.douyin.com/note/{aweme_id}"
    else:
        return f"https://www.douyin.com/video/{aweme_id}"


def generate_profile_url(platform: str, user_id: str) -> Optional[str]:
    """根据平台和用户ID生成博主主页URL"""
    if platform == "douyin":
        return f"https://www.douyin.com/user/{user_id}"
    elif platform == "douyin_collection":
        # 合集主页
        return f"https://www.douyin.com/collection/{user_id}"
    elif platform == "youtube":
        if user_id.startswith('@'):
            # 已经是 @handle 格式
            return f"https://www.youtube.com/{user_id}"
        elif user_id.startswith('UC') or user_id.startswith('UU'):
            # 频道ID格式（UCxxxxx 或 UUxxxxx），使用 /channel/ 路径
            return f"https://www.youtube.com/channel/{user_id}"
        else:
            # 其他情况，假设是 handle，添加 @
            return f"https://www.youtube.com/@{user_id}"
    elif platform == "youtube_playlist":
        # YouTube 播放列表主页
        return f"https://www.youtube.com/playlist?list={user_id}"
    elif platform == "bilibili":
        return f"https://space.bilibili.com/{user_id}"
    elif platform == "bilibili_collection":
        # B站合集主页（使用BV号）
        return f"https://www.bilibili.com/video/{user_id}"
    elif platform == "tiktok":
        # TikTok用户主页
        return f"https://www.tiktok.com/@{user_id}"
    elif platform == "instagram":
        return f"https://www.instagram.com/{str(user_id).lstrip('@')}/"
    elif platform == "xiaohongshu":
        # 小红书用户主页
        return f"https://www.xiaohongshu.com/user/profile/{user_id}"
    elif platform == "netease":
        # 网易云歌单主页（使用歌单ID）
        return f"https://music.163.com/playlist?id={user_id}"
    elif platform == "x":
        # X 主页
        handle = user_id.lstrip("@")
        return f"https://x.com/{handle}"
    else:
        return None


def _expected_dev_secret() -> str:
    """开发密钥"""
    return datetime.now().strftime('%Y%m%d')


async def send_subscription_check_notification(
    subscription_id: str,
    user_id: str,
    nickname: str,
    platform: str,
    success: bool,
    new_videos_count: int = 0,
    error_message: str = None
):
    """发送订阅检测通知（使用独立数据库会话，避免ORM对象绑定问题）"""
    try:
        # 使用原始字段，避免访问已分离的 ORM 对象
        sub_platform = platform
        sub_nickname = nickname or ""
        sub_user_id = user_id
        sub_id = subscription_id

        # 获取平台名称
        platform_names = {
            "douyin": "抖音",
            "instagram": "Instagram",
            "youtube": "YouTube", 
            "bilibili": "B站",
            "x": "X"
        }
        platform_name = platform_names.get(sub_platform, sub_platform)
        
        # 获取统计数据（总是使用独立会话，避免传入的会话已关闭）
        total_videos_count = 0
        downloaded_videos_count = 0
        local_db = None
        try:
            # 总是创建新的数据库会话，避免使用可能已关闭的会话
            local_db = next(get_db())
            total_videos_count = local_db.query(SubscriptionVideo).filter(
                SubscriptionVideo.subscription_id == sub_id
            ).count()
            downloaded_videos_count = local_db.query(SubscriptionVideo).join(
                Task, SubscriptionVideo.download_task_id == Task.id
            ).filter(
                SubscriptionVideo.subscription_id == sub_id,
                Task.status == TaskStatus.COMPLETED.value
            ).count()
        except Exception as e:
            logger.warning(f"获取订阅统计数据失败: {str(e)}")
            # 使用默认值，不影响通知发送
        finally:
            if local_db:
                try:
                    local_db.rollback()
                except Exception:
                    pass
                local_db.close()
        
        current_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        
        from sql.models import NotificationType
        
        if success:
            # 根据是否有新视频选择不同的通知类型
            if new_videos_count > 0:
                # 发现新视频通知
                title = f"🎉 发现新视频 - {sub_nickname}"
                content = f"""🎬 博主：{sub_nickname}
🏷️ 平台：{platform_name}
🎉 检测结果：发现 {new_videos_count} 个新视频
📈 总视频数：{total_videos_count} 个
📥 已下载：{downloaded_videos_count} 个
⏰ 检测时间：{current_time}"""
                
                notification_type = NotificationType.SUBSCRIPTION_CHECK_NEW_VIDEOS.value
            else:
                # 未发现新视频通知
                title = f"✅ 订阅检测完成 - {sub_nickname}"
                content = f"""🎬 博主：{sub_nickname}
🏷️ 平台：{platform_name}
✅ 检测结果：未发现新视频
📈 总视频数：{total_videos_count} 个
📥 已下载：{downloaded_videos_count} 个
⏰ 检测时间：{current_time}"""
                
                notification_type = NotificationType.SUBSCRIPTION_CHECK_NO_NEW_VIDEOS.value
        else:
            # 失败通知
            title = f"❌ 订阅检测失败 - {sub_nickname}"
            content = f"""🎬 博主：{sub_nickname}
🏷️ 平台：{platform_name}
❌ 检测结果：失败
🚫 错误信息：{error_message or '未知错误'}
⏰ 失败时间：{current_time}"""
            
            notification_type = NotificationType.SUBSCRIPTION_CHECK_FAILED.value
        
        # 准备通知数据
        notification_data = {
            "title": title,
            "content": content,
            "user_id": sub_user_id,
            "extra_data": {
                "user_id": sub_user_id,  # 博主ID，用于获取头像
                "platform": platform,
                "nickname": sub_nickname
            }
        }
        
        # 异步发送通知
        try:
            import aiohttp
            
            try:
                # 使用当前事件循环直接发送，不再创建新的事件循环
                connector = aiohttp.UnixConnector(path="/app/sockets/easy-vdl.sock")
                async with aiohttp.ClientSession(connector=connector) as session:
                    # 使用专门的订阅检测通知端点
                    endpoint = "http://localhost/api/notifications/subscription-check"
                    # 添加通知类型
                    notification_data["type"] = notification_type
                    async with session.post(endpoint, json=notification_data) as response:
                        if response.status == 200:
                            logger.info(f"订阅检测通知发送成功: {sub_nickname}")
                        else:
                            logger.warning(f"订阅检测通知发送失败: {response.status}")
            except Exception as e:
                logger.warning(f"发送订阅检测通知异常: {str(e)}")
                
        except Exception as e:
            logger.warning(f"发送订阅检测通知失败: {str(e)}")
            
    except Exception as e:
        logger.error(f"准备订阅检测通知失败: {str(e)}")


# ============================================================================
# 下载队列处理函数
# ============================================================================

async def process_download_queue(subscription_id: str, videos: List[SubscriptionVideo], quality: str = "best", batch_size: int = 1, progress_callback = None):
    """处理下载队列（优化版：改进数据库连接管理、事件驱动、日志优化）"""
    from routers.downloader import download_manager
    try:
        # 保存所有视频的ID，用于后续重新加载
        video_ids = [video.id for video in videos]
        total_videos = len(video_ids)
        total_batches = (total_videos + batch_size - 1) // batch_size
        completed = 0
        failed = 0
        
        logger.info(f"批量下载启动: 任务数={total_videos}, 批次={total_batches}, 并发={batch_size}")
        
        # 使用上下文管理器初始化订阅状态
        with get_db_context() as db:
            subscription = db.query(Subscription).filter(
                Subscription.id == subscription_id
            ).first()
            
            if not subscription:
                raise Exception(f"未找到订阅: {subscription_id}")
            
            # 获取平台反风控配置
            platform = subscription.platform.lower()
            anti_crawl_config = get_platform_anti_crawl_config(platform)
            stagger_delay_min, stagger_delay_max = anti_crawl_config["stagger_delay"]
            batch_interval = anti_crawl_config["batch_interval"]
            
            logger.info(f"[{platform}] 反风控: 延迟{stagger_delay_min}-{stagger_delay_max}s, 间隔{batch_interval}s")
                
            subscription.batch_download_status = "downloading"
            subscription.batch_download_total = total_videos
            subscription.batch_download_progress = 0
            subscription.batch_download_completed = 0
            subscription.batch_download_failed = 0
            subscription.batch_download_start_time = datetime.now()
            db.commit()
        
        # 立即推送初始状态
        try:
            await send_progress_update(subscription_id, {
                "type": "batch_download_progress",
                "status": "downloading",
                "progress": 0,
                "total": total_videos,
                "completed": 0,
                "failed": 0
            })
        except Exception as e:
            logger.warning(f"推送初始状态失败: {str(e)}")
            
        if progress_callback:
            asyncio.create_task(progress_callback(0, 0, total_videos))
        
        # 按批次处理视频
        for batch_index in range(total_batches):
            # 检查是否已取消
            if subscription_id in cancelled_batch_downloads:
                logger.info(f"批量下载已取消: {subscription_id}")
                # 使用上下文管理器更新最终状态
                with get_db_context() as db:
                    subscription = db.query(Subscription).filter(
                        Subscription.id == subscription_id
                    ).first()
                    if subscription:
                        subscription.batch_download_status = "cancelled"
                        db.commit()
                        # 发送取消状态
                        await send_progress_update(subscription_id, {
                            "type": "batch_download_progress",
                            "status": "cancelled",
                            "progress": subscription.batch_download_progress,
                            "total": subscription.batch_download_total,
                            "completed": subscription.batch_download_completed,
                            "failed": subscription.batch_download_failed
                        })
                cancelled_batch_downloads.discard(subscription_id)
                return

            # 使用上下文管理器处理每个批次
            try:
                # 检查全局下载并发状态，避免队列积压 (移出DB事务)
                while True:
                    running_tasks = len([t for t in download_manager.tasks.values() if not t.done()])
                    queue_length = len(download_manager.download_queue)
                    available_slots = download_manager.max_concurrent_downloads - running_tasks
                    
                    if available_slots < batch_size:
                        if batch_index == 0:
                            logger.debug(f"并发已满(运行{running_tasks},队列{queue_length}),等待...")
                        await asyncio.sleep(5)
                        if subscription_id in cancelled_batch_downloads:
                            return
                    else:
                        if batch_index == 0:
                            logger.debug(f"并发正常(运行{running_tasks},可用{available_slots})")
                        break
                
                # 对于抖音平台，额外检查浏览器活跃任务数 (移出DB事务)
                if platform in ["douyin", "douyin_collection"]:
                    while True:
                        from routers.dyd import browser_manager
                        browser_active_count = browser_manager._active_tasks
                        if browser_active_count >= MAX_DOUYIN_BROWSER_ACTIVE_TASKS:
                            if batch_index == 0:
                                logger.debug(f"抖音浏览器任务数({browser_active_count})达上限,等待...")
                            await asyncio.sleep(5)
                            if subscription_id in cancelled_batch_downloads:
                                return
                        else:
                            break

                with get_db_context() as db:
                    start_idx = batch_index * batch_size
                    end_idx = min(start_idx + batch_size, total_videos)
                    batch_video_ids = video_ids[start_idx:end_idx]
                    
                    # 重新加载当前批次的视频对象
                    current_batch = db.query(SubscriptionVideo).filter(
                        SubscriptionVideo.id.in_(batch_video_ids)
                    ).all()
                    
                    if batch_index == 0 or batch_index == total_batches - 1:
                        logger.info(f"处理批次 {batch_index + 1}/{total_batches} ({len(current_batch)}个任务)")

                    # 创建当前批次的下载任务
                    download_tasks = []
                    failed_to_create = []
                    for idx, video in enumerate(current_batch):
                        if video.downloaded.lower() == "true":
                            logger.debug(f"跳过已下载: {video.title}")
                            continue
                        
                        # 对于抖音平台，每个任务创建前再次检查浏览器活跃任务数
                        if platform in ["douyin", "douyin_collection"]:
                            while True:
                                from routers.dyd import browser_manager
                                browser_active_count = browser_manager._active_tasks
                                if browser_active_count >= MAX_DOUYIN_BROWSER_ACTIVE_TASKS:
                                    logger.debug(f"抖音浏览器任务数({browser_active_count})达上限,等待...")
                                    await asyncio.sleep(5)
                                    if subscription_id in cancelled_batch_downloads:
                                        return
                                else:
                                    break
                        
                        try:
                            # 使用下载管理器创建任务
                            task_id = await download_manager.add_subscription_download(video, quality, db)
                            
                            # 注册任务完成事件
                            async with task_completion_lock:
                                task_completion_events[task_id] = asyncio.Event()
                            
                            # 任务已由 download_manager 内部保障入队，此处不再重复校验
                            pass
                            
                            download_tasks.append(task_id)
                            if batch_index == 0 or len(download_tasks) % 10 == 0:
                                logger.debug(f"创建任务: {video.title[:30]}... (ID:{task_id})")
                        except Exception as e:
                            logger.error(f"创建任务失败: {video.title[:30]}..., 错误: {str(e)}")
                            failed_to_create.append({"video": video, "error": str(e)})
                            continue
                        
                        # 错峰启动，避免瞬时并发触发风控
                        if idx < len(current_batch) - 1:
                            import random
                            delay = random.uniform(stagger_delay_min, stagger_delay_max)
                            if idx == 0:
                                logger.debug(f"错峰启动: 延迟{delay:.1f}s")
                            await asyncio.sleep(delay)
                    
                    # 记录创建失败的任务数量
                    if failed_to_create:
                        logger.warning(f"批次 {batch_index + 1} 中有 {len(failed_to_create)} 个任务创建失败，已记录但不会重试")
                        failed += len(failed_to_create)
                    
                    db.commit()
                    
                    # 在进入等待循环前立即检查取消（提高响应速度）
                    if subscription_id in cancelled_batch_downloads:
                        logger.info(f"检测到取消请求，跳过批次 {batch_index + 1} 的等待")
                        # 执行取消逻辑（与循环内的逻辑相同）
                        removed_count = 0
                        for task_id in download_tasks:
                            if (task_id, subscription_id) in download_manager.download_queue:
                                try:
                                    download_manager.download_queue.remove((task_id, subscription_id))
                                    removed_count += 1
                                except ValueError:
                                    pass
                        
                        with get_db_context() as cancel_db:
                            # 优化：使用批量查询替代循环查询
                            task_statuses = cancel_db.query(Task).filter(Task.id.in_(download_tasks)).all()
                            task_status_dict = {ts.id: ts for ts in task_statuses}
                            
                            # 批量查询相关视频
                            videos = cancel_db.query(SubscriptionVideo).filter(
                                SubscriptionVideo.download_task_id.in_(download_tasks)
                            ).all()
                            video_dict = {v.download_task_id: v for v in videos}
                            
                            for task_id in download_tasks:
                                task_status = task_status_dict.get(task_id)
                                # 只标记 PENDING 的任务为取消，DOWNLOADING 的任务继续下载
                                if task_status and task_status.status == TaskStatus.PENDING.value:
                                    task_status.status = TaskStatus.CANCELLED.value
                                    task_status.error_message = "用户取消批量下载"
                                    video = video_dict.get(task_id)
                                    if video:
                                        video.downloaded = "false"
                                        video.download_task_id = None
                            cancel_db.commit()
                        
                        with get_db_context() as final_db:
                            subscription = final_db.query(Subscription).filter(
                                Subscription.id == subscription_id
                            ).first()
                            if subscription:
                                subscription.batch_download_status = "cancelled"
                                final_db.commit()
                                await send_progress_update(subscription_id, {
                                    "type": "batch_download_progress",
                                    "status": "cancelled",
                                    "progress": subscription.batch_download_progress,
                                    "total": subscription.batch_download_total,
                                    "completed": subscription.batch_download_completed,
                                    "failed": subscription.batch_download_failed,
                                    "message": "批量下载已取消"
                                })
                        
                        cancelled_batch_downloads.discard(subscription_id)
                        logger.info(f"批量下载取消完成: {subscription_id}")
                        return
                    
                    # 智能等待当前批次的任务完成（优化版：减少轮询）
                    if batch_index == 0 or batch_index == total_batches - 1:
                        logger.info(f"等待批次 {batch_index + 1} 的 {len(download_tasks)} 个任务完成...")
                    max_wait_time = 1800  # 30分钟
                    start_wait_time = time.time()
                    last_progress_time = start_wait_time
                    last_push_time = start_wait_time
                    reported_final_status = set()
                    last_pushed_completed = completed
                    last_pushed_failed = failed
                    # 优化：增加检查间隔到2秒，减少数据库查询频率（前端通过WebSocket推送，无需高频轮询）
                    check_interval = 2  # 从1秒增加到2秒，减少50%的数据库查询
                    
                    while True:
                        # === 优先检查是否已取消（方案1：增强型软取消） ===
                        if subscription_id in cancelled_batch_downloads:
                            logger.info(f"检测到取消请求，停止等待当前批次 {batch_index + 1}")
                            
                            # 从下载队列中移除当前批次未开始的任务
                            removed_count = 0
                            for task_id in download_tasks:
                                if (task_id, subscription_id) in download_manager.download_queue:
                                    try:
                                        download_manager.download_queue.remove((task_id, subscription_id))
                                        removed_count += 1
                                        logger.debug(f"从队列移除任务: {task_id[:8]}...")
                                    except ValueError:
                                        pass  # 任务可能已被处理
                            
                            if removed_count > 0:
                                logger.info(f"已从队列移除 {removed_count} 个未开始的任务")
                            
                            # 标记剩余未完成的任务为取消（只标记 PENDING 的，DOWNLOADING 的继续下载）
                            # 优化：使用批量查询
                            with get_db_context() as cancel_db:
                                # 批量查询所有任务状态
                                task_statuses = cancel_db.query(Task).filter(Task.id.in_(download_tasks)).all()
                                task_status_dict = {ts.id: ts for ts in task_statuses}
                                
                                # 批量查询所有相关视频
                                videos = cancel_db.query(SubscriptionVideo).filter(
                                    SubscriptionVideo.download_task_id.in_(download_tasks)
                                ).all()
                                video_dict = {v.download_task_id: v for v in videos}
                                
                                for task_id in download_tasks:
                                    task_status = task_status_dict.get(task_id)
                                    # 只标记 PENDING 的任务为取消，DOWNLOADING 的任务继续下载
                                    if task_status and task_status.status == TaskStatus.PENDING.value:
                                        task_status.status = TaskStatus.CANCELLED.value
                                        task_status.error_message = "用户取消批量下载"
                                        
                                        # 更新对应的视频状态
                                        video = video_dict.get(task_id)
                                        if video:
                                            video.downloaded = "false"
                                            video.download_task_id = None
                                
                                cancel_db.commit()
                            
                            # 更新订阅状态为已取消
                            with get_db_context() as final_db:
                                subscription = final_db.query(Subscription).filter(
                                    Subscription.id == subscription_id
                                ).first()
                                if subscription:
                                    subscription.batch_download_status = "cancelled"
                                    final_db.commit()
                                    
                                    # 发送取消完成状态
                                    await send_progress_update(subscription_id, {
                                        "type": "batch_download_progress",
                                        "status": "cancelled",
                                        "progress": subscription.batch_download_progress,
                                        "total": subscription.batch_download_total,
                                        "completed": subscription.batch_download_completed,
                                        "failed": subscription.batch_download_failed,
                                        "message": "批量下载已取消"
                                    })
                            
                            # 从取消集合中移除
                            cancelled_batch_downloads.discard(subscription_id)
                            logger.info(f"批量下载取消完成: {subscription_id}")
                            return  # 立即退出
                        
                        # 使用上下文管理器检查状态
                        # 优化：使用批量查询替代循环查询，减少数据库查询次数
                        with get_db_context() as temp_db:
                            
                            # 批量查询所有任务状态（1次查询替代15次查询）
                            task_statuses = temp_db.query(Task).filter(Task.id.in_(download_tasks)).all()
                            task_status_dict = {ts.id: ts for ts in task_statuses}
                            
                            # 检查当前批次的所有任务状态
                            batch_completed = 0
                            batch_failed = 0
                            batch_pending = 0
                            batch_stuck = 0
                            
                            for task_id in download_tasks:
                                task_status = task_status_dict.get(task_id)
                                if task_status:
                                    if task_status.status == TaskStatus.ERROR.value:
                                        batch_failed += 1
                                        if task_id not in reported_final_status:
                                            logger.debug(f"任务 {task_id[:8]}... 失败")
                                            reported_final_status.add(task_id)
                                    elif task_status.status == TaskStatus.COMPLETED.value:
                                        batch_completed += 1
                                        if task_id not in reported_final_status:
                                            logger.debug(f"任务 {task_id[:8]}... 成功")
                                            reported_final_status.add(task_id)
                                    elif task_status.status == TaskStatus.CANCELLED.value:
                                        batch_failed += 1
                                        if task_id not in reported_final_status:
                                            logger.debug(f"任务 {task_id[:8]}... 取消")
                                            reported_final_status.add(task_id)
                                    elif task_status.status in [TaskStatus.PENDING.value, TaskStatus.DOWNLOADING.value, TaskStatus.PROCESSING.value]:
                                        if task_status.updated_at:
                                            time_since_update = (datetime.now() - task_status.updated_at).total_seconds()
                                            if time_since_update > 600:  # 10分钟
                                                batch_stuck += 1
                                                if batch_stuck == 1:  # 只在第一个卡住任务时打印
                                                    logger.warning(f"检测到卡住任务，{time_since_update:.0f}秒未更新")
                                            else:
                                                batch_pending += 1
                                        else:
                                            batch_pending += 1
                                    else:
                                        logger.warning(f"任务状态未知: {task_status.status}")
                                        batch_pending += 1
                                else:
                                    # 任务不存在时，检查是否在队列中或正在执行
                                    task_in_queue = (task_id, subscription_id) in download_manager.download_queue
                                    task_running = task_id in download_manager.tasks and not download_manager.tasks[task_id].done()
                                    
                                    if task_in_queue or task_running:
                                        logger.debug(f"任务 {task_id[:8]}... 在队列或运行中")
                                        batch_pending += 1
                                    else:
                                        logger.warning(f"任务 {task_id[:8]}... 不存在")
                                        batch_failed += 1
                        
                        # 计算当前总进度
                        current_completed = completed + batch_completed
                        current_failed = failed + batch_failed
                        current_time = time.time()
                        
                        # 实时推送进度更新：每当有任务完成或每10秒推送一次（减少推送频率）
                        should_push = False
                        if (current_completed != last_pushed_completed or current_failed != last_pushed_failed):
                            should_push = True
                        elif current_time - last_push_time >= 5:  # 恢复为5秒心跳推送，确保及时性
                            should_push = True
                        
                        if should_push:
                            try:
                                current_processed = min(end_idx, start_idx + batch_completed + batch_failed)
                                progress = int((current_processed / total_videos) * 100) if total_videos > 0 else 0
                                
                                # 使用上下文管理器更新进度
                                with get_db_context() as progress_db:
                                    await update_batch_download_progress(
                                        progress_db,
                                        subscription_id,
                                        progress=progress,
                                        completed=current_completed,
                                        failed=current_failed
                                    )
                                
                                last_pushed_completed = current_completed
                                last_pushed_failed = current_failed
                                last_push_time = current_time
                                
                                if progress_callback:
                                    asyncio.create_task(progress_callback(current_completed, current_failed, total_videos))
                            except Exception as e:
                                logger.error(f"更新进度失败: {str(e)}")
                        
                        # 如果所有任务都完成了，退出等待
                        if batch_pending == 0:
                            if batch_index == 0 or batch_index == total_batches - 1:
                                logger.info(f"批次 {batch_index + 1} 完成")
                            break
                        
                        
                        # 卡住任务清理逻辑（优化版：更谨慎判断）
                        if batch_stuck > len(download_tasks) * 0.8 and (current_time - start_wait_time) > 900:  # 15分钟
                            logger.warning(f"批次 {batch_index + 1} 超过80%任务卡住，开始清理")
                            
                            confirmed_stuck = 0
                            with get_db_context() as cleanup_db:
                                # 优化：使用批量查询替代循环查询（查询所有任务，保持与原始逻辑一致）
                                task_statuses = cleanup_db.query(Task).filter(Task.id.in_(download_tasks)).all()
                                task_status_dict = {ts.id: ts for ts in task_statuses}
                                
                                # 找出需要清理的卡住任务ID
                                stuck_task_ids = []
                                for task_status in task_statuses:
                                    if task_status.status in [TaskStatus.PENDING.value, TaskStatus.DOWNLOADING.value, TaskStatus.PROCESSING.value]:
                                        if task_status.updated_at:
                                            time_since_update = (datetime.now() - task_status.updated_at).total_seconds()
                                            if time_since_update > 600:
                                                stuck_task_ids.append(task_status.id)
                                
                                # 批量查询相关视频
                                if stuck_task_ids:
                                    videos = cleanup_db.query(SubscriptionVideo).filter(
                                        SubscriptionVideo.download_task_id.in_(stuck_task_ids)
                                    ).all()
                                    video_dict = {v.download_task_id: v for v in videos}
                                else:
                                    video_dict = {}
                                
                                # 处理卡住的任务
                                for task_id in download_tasks:
                                    task_status = task_status_dict.get(task_id)
                                    if task_status and task_status.status in [TaskStatus.PENDING.value, TaskStatus.DOWNLOADING.value, TaskStatus.PROCESSING.value]:
                                        if task_status.updated_at:
                                            time_since_update = (datetime.now() - task_status.updated_at).total_seconds()
                                            if time_since_update > 600:
                                                task_running = task_id in download_manager.tasks and not download_manager.tasks[task_id].done()
                                                if not task_running:
                                                    logger.debug(f"清理卡住任务: {task_status.title[:30]}...")
                                                task_status.status = TaskStatus.ERROR.value
                                                task_status.error_message = f"任务卡住超时({time_since_update:.0f}秒无更新)"
                                                
                                                video = video_dict.get(task_id)
                                                if video:
                                                    video.downloaded = "false"
                                                    video.download_task_id = None
                                                    video.error_message = "下载任务卡住，已重置"
                                                    confirmed_stuck += 1
                                
                                cleanup_db.commit()
                            
                            if confirmed_stuck > 0:
                                batch_failed += confirmed_stuck
                                batch_pending -= confirmed_stuck
                                logger.info(f"批次 {batch_index + 1} 清理了 {confirmed_stuck} 个卡住任务")
                                
                                if batch_pending > 0:
                                    logger.debug(f"还有 {batch_pending} 个任务在执行，继续等待")
                                    batch_stuck = 0
                                    continue
                            break
                        
                        # 超时处理（优化版）
                        if current_time - start_wait_time > max_wait_time:
                            logger.warning(f"批次 {batch_index + 1} 等待超时({max_wait_time}秒)")
                            
                            stuck_tasks_count = 0
                            with get_db_context() as cleanup_db:
                                # 优化：使用批量查询替代循环查询（查询所有任务，保持与原始逻辑一致）
                                task_statuses = cleanup_db.query(Task).filter(Task.id.in_(download_tasks)).all()
                                task_status_dict = {ts.id: ts for ts in task_statuses}
                                
                                # 找出超时任务
                                stuck_task_ids = []
                                for task_status in task_statuses:
                                    if task_status.status in [TaskStatus.PENDING.value, TaskStatus.DOWNLOADING.value, TaskStatus.PROCESSING.value]:
                                        if task_status.updated_at:
                                            time_since_update = (datetime.now() - task_status.updated_at).total_seconds()
                                            if time_since_update > 600:
                                                stuck_task_ids.append(task_status.id)
                                
                                # 批量查询相关视频
                                if stuck_task_ids:
                                    videos = cleanup_db.query(SubscriptionVideo).filter(
                                        SubscriptionVideo.download_task_id.in_(stuck_task_ids)
                                    ).all()
                                    video_dict = {v.download_task_id: v for v in videos}
                                    
                                    for task_id in stuck_task_ids:
                                        task_status = task_status_dict.get(task_id)
                                        if task_status:
                                            time_since_update = (datetime.now() - task_status.updated_at).total_seconds()
                                            stuck_tasks_count += 1
                                            logger.debug(f"清理超时任务: {task_status.title[:30]}...")
                                            task_status.status = TaskStatus.ERROR.value
                                            task_status.error_message = f"任务超时({time_since_update:.0f}秒无更新)"
                                            
                                            video = video_dict.get(task_id)
                                            if video:
                                                video.downloaded = "false"
                                                video.download_task_id = None
                                                video.error_message = "下载任务超时，已重置"
                                
                                if stuck_tasks_count > 0:
                                    cleanup_db.commit()
                            
                            if stuck_tasks_count > 0:
                                logger.info(f"批次 {batch_index + 1} 清理了 {stuck_tasks_count} 个超时任务")
                                batch_failed += stuck_tasks_count
                                batch_pending -= stuck_tasks_count
                                
                                if batch_pending > 0:
                                    logger.debug(f"还有 {batch_pending} 个任务在执行，继续等待")
                                    start_wait_time = time.time()
                                    max_wait_time = 1800
                                    continue
                            break
                        
                        # 等待间隔（从2秒增加到3秒，减少数据库查询）
                        await asyncio.sleep(check_interval)
                        
                        # 每60秒输出一次进度日志（从30秒改为60秒）
                        if current_time - last_progress_time >= 60:
                            elapsed_time = current_time - start_wait_time
                            logger.info(f"批次 {batch_index + 1} 进度: 完成={batch_completed}, 失败={batch_failed}, 等待={batch_pending}, 已等待={elapsed_time:.0f}s")
                            last_progress_time = current_time
                    
                    completed += batch_completed
                    failed += batch_failed
                    
                    # 批次完成时更新进度
                    progress = int((end_idx / total_videos) * 100)
                    try:
                        await update_batch_download_progress(
                            db,
                            subscription_id,
                            progress=progress,
                            completed=completed,
                            failed=failed
                        )
                    except Exception as e:
                        logger.error(f"更新进度失败: {str(e)}")
                    
                    # 批次间间隔控制
                    if batch_index < total_batches - 1:
                        if batch_index == 0 or batch_index == total_batches - 2:
                            logger.info(f"批次 {batch_index + 1}/{total_batches} 完成，暂停{batch_interval}s")
                        await asyncio.sleep(batch_interval)
                
            except Exception as e:
                logger.error(f"处理批次 {batch_index + 1} 时出错: {str(e)}")
                # === 优化：异常时只标记未创建任务为失败，已创建的任务继续跟踪 ===
                
                # 安全计算批次大小（如果current_batch未定义）
                start_idx_calc = batch_index * batch_size
                end_idx_calc = min(start_idx_calc + batch_size, total_videos)
                expected_batch_count = end_idx_calc - start_idx_calc
                
                batch_count_safe = len(current_batch) if 'current_batch' in locals() else expected_batch_count
                created_tasks_count = len(download_tasks) if 'download_tasks' in locals() else 0
                not_created_count = batch_count_safe - created_tasks_count
                
                if not_created_count > 0:
                    logger.warning(f"批次 {batch_index + 1} 有 {not_created_count} 个任务未创建，标记为失败")
                    failed += not_created_count
                
                # 如果已有任务创建，继续等待这些任务完成
                if created_tasks_count > 0:
                    logger.info(f"批次 {batch_index + 1} 有 {created_tasks_count} 个任务已创建，继续等待完成...")
                    # 继续执行等待逻辑（如果等待逻辑还未执行）
                    # 注意：这里不break，让后续的等待逻辑继续执行（如果存在）
                    # 但如果异常发生在等待逻辑中，这里不会继续执行
                else:
                    # 如果没有任务创建，直接标记整个批次为失败
                    # 注意：not_created_count 已经包含在 failed 中了，这里不需要再次累加
                    logger.warning(f"批次 {batch_index + 1} 没有任务创建，整个批次标记为失败")
            finally:
                # 确保连接一定被关闭
                try:
                    db.rollback()  # 确保事务被正确结束
                except Exception as e:
                    # 只忽略"no transaction"警告，其他错误需要记录
                    if "no transaction" not in str(e).lower():
                        logger.warning(f"批次连接rollback异常: {e}")
                
                db.close()
        
        # 更新最终状态
        final_status = "completed" if failed == 0 else "error"
        with get_db_context() as db:
            try:
                await update_batch_download_progress(
                    db,
                    subscription_id,
                    status=final_status,
                    progress=100,
                    completed=completed,
                    failed=failed
                )
            except Exception as e:
                logger.error(f"更新最终状态失败: {str(e)}")
                
        if progress_callback:
            asyncio.create_task(progress_callback(completed, failed, total_videos, finished=True, error=None))
            
    except Exception as e:
        logger.error(f"批量下载异常: {str(e)}")
        # 使用上下文管理器更新状态
        try:
            with get_db_context() as db:
                # 检查是否已取消（取消优先于错误）
                if subscription_id in cancelled_batch_downloads:
                    subscription = db.query(Subscription).filter(
                        Subscription.id == subscription_id
                    ).first()
                    if subscription and subscription.batch_download_status != "cancelled":
                        # 如果状态还不是 cancelled，更新为 cancelled
                        subscription.batch_download_status = "cancelled"
                        db.commit()
                        await send_progress_update(subscription_id, {
                            "type": "batch_download_progress",
                            "status": "cancelled",
                            "progress": subscription.batch_download_progress,
                            "total": subscription.batch_download_total,
                            "completed": subscription.batch_download_completed,
                            "failed": subscription.batch_download_failed,
                            "message": "批量下载已取消"
                        })
                    cancelled_batch_downloads.discard(subscription_id)
                else:
                    # 没有取消，更新为错误状态
                    await update_batch_download_progress(
                        db,
                        subscription_id,
                        status="error",
                        completed=completed if 'completed' in locals() else 0,
                        failed=failed if 'failed' in locals() else 0
                    )
        except Exception as progress_error:
            logger.error(f"更新状态失败: {str(progress_error)}")
            
        if progress_callback:
            asyncio.create_task(progress_callback(completed if 'completed' in locals() else 0, failed if 'failed' in locals() else 0, total_videos if 'total_videos' in locals() else 0, finished=True, error=e))
