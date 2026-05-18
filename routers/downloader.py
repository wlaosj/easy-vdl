import asyncio
import logging
import os
import uuid
from datetime import datetime
from typing import Dict, Optional, List, Deque, Tuple
from collections import deque
from sqlalchemy.orm import Session
from sql.database_postgresql import get_db, get_session
from sql.models import Subscription, SubscriptionVideo, TaskStatus, Task, GlobalConfig
from .dyd import VideoExtractor, dyd_download_video_logic, dyd_cancel_flags
import random
import time
import concurrent.futures
import aiohttp
import subprocess
import json

# 配置日志 - 移除basicConfig，统一由supervisor管理
logger = logging.getLogger(__name__)

class DownloadManager:
    def __init__(self, max_concurrent_downloads: int = 10):  # 设置并发数为10个
        self.running = False
        self.tasks: Dict[str, asyncio.Task] = {}
        self.download_queue: Deque[Tuple[str, str]] = deque()  # (video_id, subscription_id)
        self.max_concurrent_downloads = max_concurrent_downloads
        self._check_task: Optional[asyncio.Task] = None
        self._sync_task: Optional[asyncio.Task] = None
        self._housekeeping_task: Optional[asyncio.Task] = None
        self._last_download_time = 0  # 记录上次下载时间
        self.retry_count: Dict[str, int] = {}  # 记录重试次数
        self.MAX_RETRIES = 3  # 最大重试次数
        # 注意：配置加载延迟到 start() 方法中，因为此时数据库可能尚未初始化
    
    def _load_config_from_db(self):
        """从数据库加载下载并发数配置"""
        try:
            db = get_session()
            try:
                config_obj = db.query(GlobalConfig).filter_by(key='max_concurrent_downloads').first()
                if config_obj and config_obj.value:
                    old_value = self.max_concurrent_downloads
                    self.max_concurrent_downloads = int(config_obj.value)
                    logger.info(f"从数据库加载下载并发数配置: {old_value} -> {self.max_concurrent_downloads}")
                else:
                    logger.info(f"数据库中没有下载并发数配置，使用当前值: {self.max_concurrent_downloads}")
            except Exception as e:
                logger.warning(f"从数据库加载下载并发数配置失败，使用当前值 {self.max_concurrent_downloads}: {e}")
            finally:
                try:
                    db.rollback()
                except Exception:
                    pass
                db.close()
        except Exception as e:
            # 如果数据库未初始化，这是正常的，会在 start() 时重试
            error_msg = str(e).lower()
            if "未初始化" in error_msg or "not initialized" in error_msg or "database" in error_msg:
                logger.debug(f"数据库尚未初始化，将在启动时加载配置: {e}")
            else:
                logger.warning(f"加载下载并发数配置时出错，使用当前值 {self.max_concurrent_downloads}: {e}")
    
    def update_max_concurrent_downloads(self, new_value: int):
        """动态更新最大并发下载数"""
        if new_value < 1 or new_value > 30:
            raise ValueError("下载并发数必须在1-30之间")
        old_value = self.max_concurrent_downloads
        self.max_concurrent_downloads = new_value
        logger.info(f"下载并发数已从 {old_value} 更新为 {new_value}")
        
    async def start(self):
        """启动下载管理器"""
        if self.running:
            return
        
        # 在启动时加载配置（此时数据库已经初始化）
        self._load_config_from_db()
            
        self.running = True
        self._check_task = asyncio.create_task(self._process_queue())
        self._sync_task = asyncio.create_task(self._sync_download_status())
        # 轻量后台保洁：周期性清理已完成任务引用，避免内存滞留
        async def _housekeeping_loop():
            while self.running:
                try:
                    await asyncio.sleep(120)  # 每2分钟清理一次
                    try:
                        self._cleanup_tasks()
                    except Exception:
                        pass
                except asyncio.CancelledError:
                    break
                except Exception:
                    # 静默容错，绝不影响业务
                    pass
        self._housekeeping_task = asyncio.create_task(_housekeeping_loop())
        logger.info(f"下载管理器已启动，当前并发数: {self.max_concurrent_downloads}")
        
    async def stop(self):
        """停止下载管理器"""
        if not self.running:
            return
            
        self.running = False
        if self._check_task:
            self._check_task.cancel()
        if self._sync_task:
            self._sync_task.cancel()
        if self._housekeeping_task:
            self._housekeeping_task.cancel()
            self._housekeeping_task = None
            
        # 取消所有下载任务
        for task in self.tasks.values():
            task.cancel()
        self.tasks.clear()
        self.download_queue.clear()
        
    async def add_subscription_download(self, video: SubscriptionVideo, quality: str = "bestvideo+bestaudio", _: Session = None) -> str:
        """添加订阅视频到下载队列
        
        Args:
            video: 订阅视频对象
            _: 废弃的数据库会话参数（为保持兼容性）
            
        Returns:
            task_id: 下载任务ID
        """
        # 添加日志：记录接收到的video.subscription_id
        logger.debug(f"[add_subscription_download] 接收到video.subscription_id: {video.subscription_id}")
        
        max_retries = 3
        retry_delay = 1.0  # 初始重试延迟1秒
        
        for attempt in range(max_retries):
            db = get_session()
            try:
                # 创建新的任务ID
                task_id = str(uuid.uuid4())
                
                # 创建新任务
                now = datetime.now()
                # 优先根据订阅平台确定 source，避免 URL 异常导致 unknown
                source = None
                if video.subscription_id:
                    try:
                        sub = db.query(Subscription).filter(Subscription.id == video.subscription_id).first()
                        if sub and sub.platform:
                            platform = (sub.platform or "").lower()
                            if platform in ["douyin_collection"]:
                                source = "douyin"
                            elif platform in ["youtube_playlist"]:
                                source = "youtube"
                            elif platform in ["douyin", "youtube", "bilibili", "xiaohongshu", "tiktok", "netease", "x", "instagram"]:
                                source = platform
                    except Exception:
                        source = None

                if not source:
                    # 根据URL确定source（兜底）
                    if video.url.startswith("https://www.youtube.com") or video.url.startswith("https://youtu.be"):
                        source = "youtube"
                    elif video.url.startswith("https://www.tiktok.com") or video.url.startswith("https://vt.tiktok.com"):
                        source = "tiktok"
                    elif video.url.startswith("https://www.bilibili.com") or video.url.startswith("https://b23.tv"):
                        source = "bilibili"
                    elif video.url.startswith("https://www.douyin.com") or video.url.startswith("https://v.douyin.com"):
                        source = "douyin"
                    elif video.url.startswith("https://www.xiaohongshu.com") or video.url.startswith("https://xhslink.com"):
                        source = "xiaohongshu"
                    elif "music.163.com" in (video.url or ""):
                        source = "netease"
                    elif "x.com" in (video.url or "") or "twitter.com" in (video.url or ""):
                        source = "x"
                    elif "instagram.com" in (video.url or "") or "cdninstagram.com" in (video.url or ""):
                        source = "instagram"
                    else:
                        source = "unknown"
                
                new_task = Task(
                    id=task_id,
                    source=source,
                    url=video.url,
                    title=video.title,
                    status=TaskStatus.PENDING.value,
                    progress=0.0,
                    created_at=now,
                    updated_at=now,
                    subscription_id=video.subscription_id,  # 保存订阅ID
                    format_id=quality if source in ["youtube", "bilibili"] else None  # 使用指定的画质
                )
                
                # 添加日志：记录创建任务时的subscription_id和format_id
                logger.debug(f"[add_subscription_download] 创建任务时设置subscription_id: {new_task.subscription_id}, format_id: {new_task.format_id}")
                
                db.add(new_task)
                
                # 更新视频的下载任务ID和错误信息
                video = db.merge(video)  # 将视频对象关联到新会话
                video.download_task_id = task_id
                video.error_message = None  # 清除之前的错误信息
                
                db.commit()  # 立即提交以保存任务记录
                
                # 添加日志：记录提交后的subscription_id
                db.refresh(new_task)
                logger.debug(f"[add_subscription_download] 提交后task.subscription_id: {new_task.subscription_id}")
                
                logger.debug(f"创建新的下载任务: {task_id}, subscription_id: {video.subscription_id}")
                
                # === 优化：同步添加到下载队列，确保任务成功加入队列 ===
                # 直接添加到队列，避免异步任务失败导致任务丢失
                try:
                    self.download_queue.append((task_id, video.subscription_id))
                    logger.debug(f"已添加订阅下载任务到队列: {task_id}, subscription_id: {video.subscription_id}, 标题: {video.title}")
                except Exception as queue_error:
                    logger.error(f"添加任务到队列失败: {task_id}, 错误: {str(queue_error)}")
                    # 即使队列添加失败，任务已创建，可以稍后手动重试
                    # 但这里我们尝试再次添加
                    try:
                        await asyncio.sleep(0.1)
                        self.download_queue.append((task_id, video.subscription_id))
                        logger.info(f"重试添加任务到队列成功: {task_id}")
                    except Exception as retry_error:
                        logger.error(f"重试添加任务到队列仍然失败: {task_id}, 错误: {str(retry_error)}")
                        # 任务已创建，但未加入队列，需要后续处理
                
                return task_id
                
            except Exception as e:
                logger.error(f"添加下载任务失败 (尝试 {attempt + 1}/{max_retries}): {str(e)}")
                db.rollback()
                
                # 如果是数据库锁定错误且还有重试机会，则等待后重试
                if "database is locked" in str(e) and attempt < max_retries - 1:
                    logger.warning(f"数据库被锁定，等待 {retry_delay} 秒后重试...")
                    await asyncio.sleep(retry_delay)
                    retry_delay *= 2  # 指数退避
                    continue
                else:
                    # 最后一次尝试或其他错误，抛出异常
                    raise
            finally:
                try:
                    db.rollback()
                except Exception:
                    pass
                db.close()
        
    async def add_download_task(self, task_data: str | Dict) -> str:
        """添加通用下载任务
        
        Args:
            task_data: 任务数据字典或任务ID
            
        Returns:
            task_id: 下载任务ID
        """
        if isinstance(task_data, str):
            # 如果传入的是任务ID，直接添加到队列
            self.download_queue.append((task_data, None))  # 使用None表示非订阅下载
            logger.info(f"已添加下载任务: {task_data}")
            return task_data
            
        db = get_session()
        try:
            task_id = str(uuid.uuid4())
            
            # 创建下载任务记录
            now = datetime.now()
            new_task = Task(
                id=task_id,
                source=task_data.get('source', 'others'),  # 使用source字段作为来源
                url=task_data['url'],
                original_url=task_data['url'],  # 保存原始URL
                title=task_data.get('title', '未知标题'),
                status=TaskStatus.PENDING.value,
                progress=0.0,
                created_at=now,
                updated_at=now,
                cookie=task_data.get('cookie'),  # cookie字段
                format_id=task_data.get('format_id'),  # 格式ID
                proxy=None,  # 代理设置为空
                filename=None  # 文件名初始为空
            )
            
            db.add(new_task)
            db.commit()
            
            # 将任务添加到下载队列
            self.download_queue.append((task_id, None))  # 使用None表示非订阅下载
            logger.info(f"已添加下载任务: {task_id}")

            # 广播任务状态
            from routers.websocket import broadcast_message
            await broadcast_message('downloads', {
                'type': 'progress_update',
                'task': {
                    'id': task_id,
                    'url': new_task.url,
                    'source': new_task.source,
                    'title': new_task.title,
                    'status': new_task.status,
                    'progress': new_task.progress,
                    'filename': new_task.filename,
                    'created_at': new_task.created_at.isoformat() if new_task.created_at else None,
                    'updated_at': new_task.updated_at.isoformat() if new_task.updated_at else None
                }
            })
            
            return task_id
            
        except Exception as e:
            logger.error(f"添加下载任务失败: {str(e)}")
            try:
                db.rollback()
            except Exception:
                pass
            db.close()
            raise
        finally:
            try:
                db.rollback()
            except Exception:
                pass
            db.close()
            
    async def get_download_status(self, task_id: str) -> Optional[TaskStatus]:
        """获取下载任务状态"""
        if task_id in self.tasks:
            task = self.tasks[task_id]
            if task.done():
                try:
                    await task
                    return TaskStatus.COMPLETED
                except Exception:
                    return TaskStatus.ERROR
            return TaskStatus.DOWNLOADING
        
        # 检查是否在队列中等待
        for video_id, subscription_id in self.download_queue:
            db = get_session()
            try:
                video = db.query(SubscriptionVideo).filter(
                    SubscriptionVideo.id == video_id,
                    SubscriptionVideo.subscription_id == subscription_id
                ).first()
                if video and video.download_task_id == task_id:
                    return TaskStatus.PENDING
            finally:
                try:
                    db.rollback()
                except Exception:
                    pass
                db.close()
                
        return None

    async def _process_queue(self):
        """处理下载队列"""
        while self.running:
            try:
                # 检查当前运行的任务数
                running_tasks = len([t for t in self.tasks.values() if not t.done()])
                
                # 如果达到最大并发数，等待一段时间
                if running_tasks >= self.max_concurrent_downloads:
                    await asyncio.sleep(1)
                    continue
                
                # 清理已完成或失败的任务，释放资源
                completed_tasks = []
                for task_id, task in list(self.tasks.items()):
                    if task.done():
                        try:
                            # 尝试获取结果，捕获异常
                            await task
                        except Exception as e:
                            logger.warning(f"任务 {task_id} 执行失败: {e}")
                        finally:
                            completed_tasks.append(task_id)
                
                # 移除已完成的任务
                for task_id in completed_tasks:
                    del self.tasks[task_id]
                    logger.debug(f"清理已完成的任务: {task_id}")
                
                # 重新计算运行中的任务数
                running_tasks = len([t for t in self.tasks.values() if not t.done()])
                    
                # 如果队列为空，等待
                if not self.download_queue:
                    await asyncio.sleep(1)
                    continue
                    
                # 从队列中获取任务
                task_id, subscription_id = self.download_queue.popleft()
                logger.debug(f"开始处理队列中的任务: {task_id}, subscription_id: {subscription_id}")
 
                try:
                    # 启动错峰，平滑准备阶段，避免瞬时拥挤（不影响总体并发下载）
                    try:
                        await asyncio.sleep(random.uniform(0.2, 0.4))
                    except Exception:
                        pass
                    # 获取数据库会话
                    db = get_session()
                    
                    # 获取任务信息
                    task = db.query(Task).filter(Task.id == task_id).first()
                    
                    if not task:
                        logger.error(f"未找到任务: {task_id}")
                        continue
                        
                    # 检查任务是否已被取消
                    if task.status == TaskStatus.CANCELLED.value:
                        logger.info(f"任务已被取消: {task.title}")
                        continue
                    
                    # 更新任务状态为下载中
                    task.status = TaskStatus.DOWNLOADING.value
                    task.updated_at = datetime.now()
                    db.commit()

                    # 广播任务状态 - 包含完整的任务信息
                    from routers.websocket import broadcast_message
                    await broadcast_message('downloads', {
                        'type': 'progress_update',
                        'task': {
                            'id': task_id,
                            'status': TaskStatus.DOWNLOADING.value,
                            'progress': task.progress,
                            'updated_at': task.updated_at.isoformat(),
                            'filename': task.filename,
                            'source': task.source,
                            'title': task.title,
                            'url': task.url,
                            'original_url': task.original_url,
                            'subscription_id': task.subscription_id,
                            'created_at': task.created_at.isoformat() if task.created_at else None
                        }
                    })
                    
                    # 创建下载任务
                    logger.debug(f"准备创建下载任务: {task_id}, source: {task.source}, subscription_id: {task.subscription_id}")
                    if task.source == "youtube":
                        # YouTube 视频使用专门的下载逻辑
                        from routers.ytd import download_video_logic as youtube_download_logic
                        logger.debug(f"使用YouTube下载逻辑, subscription_id: {task.subscription_id}, format_id: {task.format_id}")
                        if task.subscription_id:
                            # 订阅下载：需要构建订阅目录
                            from routers.subscribe import get_subscription_download_dir
                            custom_download_dir = get_subscription_download_dir(task.subscription_id, task.title)
                            if custom_download_dir:
                                # 使用订阅目录
                                download_task = asyncio.create_task(youtube_download_logic(
                                    task_id=task_id,
                                    url=task.url,
                                    format_id=task.format_id or "bestvideo+bestaudio",
                                    youtube_cookie=task.cookie,
                                    bilibili_cookie="",
                                    proxy=None,
                                    subtitles=True,
                                    thumbnail=True,
                                    download_dir=custom_download_dir,
                                    subscription_id=task.subscription_id  # 使用任务中的订阅ID
                                ))
                            else:
                                # 如果获取订阅目录失败，使用默认目录
                                download_task = asyncio.create_task(youtube_download_logic(
                                    task_id=task_id,
                                    url=task.url,
                                    format_id=task.format_id or "bestvideo+bestaudio",
                                    youtube_cookie=task.cookie,
                                    bilibili_cookie="",
                                    proxy=None,
                                    subtitles=True,
                                    thumbnail=True,
                                    subscription_id=subscription_id  # 传递订阅ID
                                ))
                        else:
                            # 手动下载：使用默认目录
                            download_task = asyncio.create_task(youtube_download_logic(
                                task_id=task_id,
                                url=task.url,
                                format_id=task.format_id or "bestvideo+bestaudio",
                                youtube_cookie=task.cookie,
                                bilibili_cookie="",
                                proxy=None,
                                subtitles=True,
                                thumbnail=True,
                                subscription_id=task.subscription_id  # 修复：添加订阅ID参数
                            ))
                    elif task.source == "douyin":
                        # 抖音视频使用专门的下载逻辑
                        if subscription_id:
                            # 订阅下载：需要构建订阅目录
                            from routers.subscribe import get_subscription_download_dir
                            custom_download_dir = get_subscription_download_dir(subscription_id, task.title)
                            download_task = asyncio.create_task(dyd_download_video_logic(task_id, task.url, custom_download_dir))
                        else:
                            # 手动下载：使用默认目录
                            download_task = asyncio.create_task(dyd_download_video_logic(task_id, task.url))
                    elif task.source == "bilibili":
                        # B站视频使用yt-dlp下载逻辑
                        from routers.ytd import download_video_logic as bilibili_download_logic
                        if subscription_id:
                            # 订阅下载：需要构建订阅目录
                            from routers.subscribe import get_subscription_download_dir
                            custom_download_dir = get_subscription_download_dir(subscription_id, task.title)
                            download_task = asyncio.create_task(bilibili_download_logic(
                                task_id=task_id,
                                url=task.url,
                                format_id=task.format_id or "bestvideo+bestaudio",
                                youtube_cookie="",
                                bilibili_cookie=task.cookie,
                                proxy=None,
                                subtitles=True,
                                thumbnail=True,
                                download_dir=custom_download_dir,
                                subscription_id=task.subscription_id
                            ))
                        else:
                            # 手动下载：使用默认目录
                            download_task = asyncio.create_task(bilibili_download_logic(
                                task_id=task_id,
                                url=task.url,
                                format_id=task.format_id or "bestvideo+bestaudio",
                                youtube_cookie="",
                                bilibili_cookie=task.cookie,
                                proxy=None,
                                subtitles=True,
                                thumbnail=True,
                                subscription_id=task.subscription_id
                            ))
                    elif task.source == "tiktok":
                        # TikTok视频使用专门的下载逻辑
                        from routers.tiktok import tiktok_download_video_logic
                        if subscription_id:
                            # 订阅下载：需要构建订阅目录
                            from routers.subscribe import get_subscription_download_dir
                            custom_download_dir = get_subscription_download_dir(subscription_id, task.title)
                            download_task = asyncio.create_task(tiktok_download_video_logic(
                                task_id=task_id,
                                url=task.url,
                                download_dir=custom_download_dir,
                                subscription_id=task.subscription_id
                            ))
                        else:
                            # 手动下载：使用默认目录
                            download_task = asyncio.create_task(tiktok_download_video_logic(
                                task_id=task_id,
                                url=task.url,
                                subscription_id=task.subscription_id
                            ))
                    elif task.source == "xiaohongshu":
                        # 小红书视频使用专门的下载逻辑
                        from routers.xiaohongshu import xhs_download_video_logic
                        if subscription_id:
                            # 订阅下载：需要构建订阅目录
                            from routers.subscribe import get_subscription_download_dir
                            custom_download_dir = get_subscription_download_dir(subscription_id, task.title)
                            download_task = asyncio.create_task(xhs_download_video_logic(task_id, task.url, custom_download_dir))
                        else:
                            # 手动下载：使用默认目录
                            download_task = asyncio.create_task(xhs_download_video_logic(task_id, task.url))
                    elif task.source == "netease":
                        # 网易云音乐使用专门的下载逻辑
                        from routers.netease import netease_download_logic
                        if subscription_id:
                            # 订阅下载：需要构建订阅目录
                            from routers.subscribe import get_subscription_download_dir
                            custom_download_dir = get_subscription_download_dir(subscription_id, task.title)
                            download_task = asyncio.create_task(netease_download_logic(
                                task_id=task_id,
                                url=task.url,
                                format_id=task.format_id,
                                download_dir=custom_download_dir,
                                subscription_id=task.subscription_id
                            ))
                        else:
                            # 手动下载：使用默认目录
                            download_task = asyncio.create_task(netease_download_logic(
                                task_id=task_id,
                                url=task.url,
                                format_id=task.format_id,
                                subscription_id=task.subscription_id
                            ))
                    elif task.source == "x":
                        # X 视频使用独立下载逻辑（支持订阅目录）
                        from routers.x_downloader import x_download_task
                        if subscription_id:
                            from routers.subscribe import get_subscription_download_dir
                            custom_download_dir = get_subscription_download_dir(subscription_id, task.title)
                            download_task = asyncio.create_task(x_download_task(
                                task_id=task_id,
                                url=task.url,
                                format_id=task.format_id,
                                headers=None,
                                download_dir=custom_download_dir
                            ))
                        else:
                            download_task = asyncio.create_task(x_download_task(
                                task_id=task_id,
                                url=task.url,
                                format_id=task.format_id,
                                headers=None
                            ))
                    elif task.source == "instagram":
                        from routers.instagram import instagram_download_task
                        if subscription_id:
                            from routers.subscribe import get_subscription_download_dir
                            custom_download_dir = get_subscription_download_dir(subscription_id, task.title)
                            download_task = asyncio.create_task(instagram_download_task(
                                task_id=task_id,
                                url=task.url,
                                download_dir=custom_download_dir
                            ))
                        else:
                            download_task = asyncio.create_task(instagram_download_task(
                                task_id=task_id,
                                url=task.url
                            ))
                    else:
                        # 其他类型视频使用yt-dlp下载
                        from routers.wnxt import ytdlp_download_task
                        download_task = asyncio.create_task(ytdlp_download_task(
                            task_id=task_id,
                            url=task.url,
                            format_id=task.format_id
                            # Cookie不再传递，ytdlp_download_task会自动从文件读取
                        ))
                    
                    self.tasks[task_id] = download_task
                    self._last_download_time = time.time()
                    
                except Exception as e:
                    logger.error(f"处理下载任务时出错: {str(e)}")
                    try:
                        db.rollback()
                    except Exception:
                        pass
                    db.close()
                finally:
                    try:
                        db.rollback()
                    except Exception:
                        pass
                    db.close()
                    
            except Exception as e:
                logger.error(f"下载队列处理出错: {str(e)}")
                await asyncio.sleep(1)  # 发生错误时等待一段时间再继续
                
    async def _download_video(self, video_id: str, subscription_id: str):
        """下载单个视频"""
        try:
            # 初始化重试计数
            if video_id not in self.retry_count:
                self.retry_count[video_id] = 0
                
            while self.retry_count[video_id] < self.MAX_RETRIES:
                db = get_session()
                try:
                    # 获取视频信息
                    video = db.query(SubscriptionVideo).filter(
                        SubscriptionVideo.id == video_id,
                        SubscriptionVideo.subscription_id == subscription_id
                    ).first()
                    
                    if not video:
                        logger.error(f"未找到视频: {video_id}")
                        return
                        
                    # 检查任务是否已被取消
                    if video.download_task_id:
                        task = db.query(Task).filter(Task.id == video.download_task_id).first()
                        if task and task.status == TaskStatus.CANCELLED.value:
                            logger.info(f"任务已被取消: {video.title}")
                            return
                    
                    # 下载视频
                    result = await dyd_download_video_logic(video, db)
                    
                    if result:
                        # 下载成功，清除重试计数
                        self.retry_count.pop(video_id, None)
                        return
                        
                    # 下载失败，增加重试计数
                    self.retry_count[video_id] += 1
                    await asyncio.sleep(random.uniform(3, 5))  # 失败后等待3-5秒再重试
                    
                except Exception as e:
                    logger.error(f"下载视频时出错: {str(e)}")
                    self.retry_count[video_id] += 1
                    await asyncio.sleep(random.uniform(3, 5))
                finally:
                    try:
                        db.rollback()
                    except Exception:
                        pass
                    db.close()
                    
            logger.error(f"视频 {video_id} 下载失败，已达到最大重试次数")
            
        except Exception as e:
            logger.error(f"下载视频过程中出错: {str(e)}")
        finally:
            # 清理重试计数
            self.retry_count.pop(video_id, None)
            
    def _cleanup_tasks(self):
        """清理已完成的任务"""
        done_tasks = [vid for vid, task in self.tasks.items() if task.done()]
        for vid in done_tasks:
            self.tasks.pop(vid, None)
            self.retry_count.pop(vid, None)

    async def _add_to_queue(self, task_id: str, subscription_id: str, title: str):
        """异步添加任务到下载队列
        
        Args:
            task_id: 任务ID
            subscription_id: 订阅ID
            title: 视频标题
        """
        db = get_session()
        try:
            self.download_queue.append((task_id, subscription_id))
            logger.debug(f"视频已加入下载队列: {title} (Task ID: {task_id})")
        finally:
            try:
                db.rollback()
            except Exception:
                pass
            db.close()

    async def _sync_download_status(self):
        """同步下载状态到数据库"""
        while self.running:
            try:
                # 使用新的数据库会话
                db = get_session()
                try:
                    # 获取所有未完成的下载任务，但排除已取消和失败的任务
                    videos = db.query(SubscriptionVideo).join(
                        Task, SubscriptionVideo.download_task_id == Task.id
                    ).filter(
                        SubscriptionVideo.download_task_id.isnot(None),
                        SubscriptionVideo.downloaded == "false",
                        Task.status.in_([
                            TaskStatus.PENDING.value,
                            TaskStatus.DOWNLOADING.value,
                            TaskStatus.PROCESSING.value
                        ])
                    ).all()
                    
                    for video in videos:
                        task_id = video.download_task_id
                        if task_id in self.tasks:
                            task = self.tasks[task_id]
                            if task.done():
                                try:
                                    result = task.result()
                                    # 检查任务是否真的成功完成，而不是被取消
                                    if result is not None and result is not False:
                                        # 在更新状态前，先检查数据库中的任务状态
                                        db_task = db.query(Task).filter(Task.id == task_id).first()
                                        if db_task and db_task.status not in [TaskStatus.CANCELLED.value, TaskStatus.ERROR.value]:
                                            video.downloaded = "true"
                                            db.commit()
                                        else:
                                            # 任务已被取消或失败，不更新视频状态
                                            logger.warning(f"任务 {task_id} 状态为 {db_task.status if db_task else 'unknown'}，跳过状态更新")
                                    else:
                                        # 任务被取消或失败
                                        video.downloaded = "false"
                                        video.error_message = "Task cancelled or failed"
                                        db.commit()
                                except Exception as e:
                                    logger.error(f"下载任务失败: {str(e)}")
                                    video.downloaded = "false"
                                    video.error_message = str(e)  # 记录错误信息
                                    db.commit()
                                    
                finally:
                    try:
                        db.rollback()
                    except Exception:
                        pass
                    db.close()
                    
                await asyncio.sleep(10)  # 【性能优化】降低同步频率：每10秒同步一次，减少数据库压力
                
            except Exception as e:
                logger.error(f"同步下载状态失败: {str(e)}")
                await asyncio.sleep(5)  # 出错后等待5秒再继续

async def download_task(task_id: str, url: str, headers: dict = None):
    """服务端下载实现"""
    db = get_session()
    try:
        # 生成基于时间的文件名
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        base_filename = f"video_{timestamp}"
        filename = f"others/{base_filename}/{base_filename}.mp4"
        
        # 确保下载目录存在
        download_dir = os.path.join('/app/downloads/others')
        os.makedirs(os.path.join(download_dir, base_filename), exist_ok=True)
        
        # 更新任务的文件名
        db.query(Task).filter(Task.id == task_id).update({
            'filename': filename,
            'updated_at': datetime.now()
        })
        db.commit()

        # 准备请求头
        request_headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': '*/*',
            'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
            'Accept-Encoding': 'gzip, deflate, br'
        }
        
        # 合并传入的请求头
        if headers:
            request_headers.update(headers)

        # 在线程池中执行下载
        loop = asyncio.get_event_loop()
        with concurrent.futures.ThreadPoolExecutor() as pool:
            try:
                # 使用aiohttp进行下载
                async with aiohttp.ClientSession() as session:
                    async with session.get(url, headers=request_headers, ssl=False) as response:
                        if not response.ok:
                            raise Exception(f"下载失败: HTTP {response.status}")

                        # 获取总大小
                        total_size = int(response.headers.get('content-length', 0))
                        
                        # 准备文件路径
                        file_path = os.path.join(download_dir, base_filename, f"{base_filename}.mp4")
                        
                        # 分块下载并更新进度
                        chunk_size = 8192  # 8KB
                        downloaded_size = 0
                        last_progress_time = time.time()
                        last_progress = 0

                        with open(file_path, 'wb') as f:
                            async for chunk in response.content.iter_chunked(chunk_size):
                                if chunk:
                                    f.write(chunk)
                                    downloaded_size += len(chunk)
                                    
                                    # 计算进度
                                    if total_size > 0:
                                        progress = (downloaded_size / total_size) * 100
                                        current_time = time.time()
                                        
                                        # 限制更新频率 - 优化：减少更新频率以降低数据库压力
                                        if current_time - last_progress_time >= 5 and abs(progress - last_progress) >= 5:
                                            # 更新数据库进度
                                            db.query(Task).filter(Task.id == task_id).update({
                                                'progress': progress,
                                                'updated_at': datetime.now()
                                            })
                                            db.commit()
                                            
                                            # 广播进度 - 获取完整任务信息
                                            from routers.websocket import broadcast_message
                                            task_obj = db.query(Task).filter(Task.id == task_id).first()
                                            if task_obj:
                                                await broadcast_message('downloads', {
                                                    'type': 'progress_update',
                                                    'task': {
                                                        'id': task_id,
                                                        'progress': progress,
                                                        'status': TaskStatus.DOWNLOADING.value,
                                                        'updated_at': datetime.now().isoformat(),
                                                        'filename': task_obj.filename,
                                                        'source': task_obj.source,
                                                        'title': task_obj.title,
                                                        'url': task_obj.url,
                                                        'subscription_id': task_obj.subscription_id
                                                    }
                                                })
                                            
                                            last_progress_time = current_time
                                            last_progress = progress

                # 下载完成后，尝试生成缩略图
                try:
                    # 使用ffmpeg从视频中提取缩略图
                    poster_path = os.path.join(download_dir, base_filename, f"{base_filename}-poster.jpg")
                    cmd = [
                        "ffmpeg", "-y", "-i", file_path,
                        "-ss", "00:00:01", "-vframes", "1",
                        "-q:v", "2", poster_path
                    ]
                    result = await loop.run_in_executor(pool, lambda: subprocess.run(cmd, capture_output=True, text=True))
                    if result.returncode == 0:
                        logging.info(f"成功生成缩略图: {poster_path}")
                except Exception as e:
                    logging.error(f"生成缩略图失败: {str(e)}")

                # 更新任务状态为完成
                db.query(Task).filter(Task.id == task_id).update({
                    'status': TaskStatus.COMPLETED.value,
                    'progress': 100.0,
                    'updated_at': datetime.now()
                })
                db.commit()

                # 广播完成状态 - 获取完整任务信息
                from routers.websocket import broadcast_message
                task_obj = db.query(Task).filter(Task.id == task_id).first()
                if task_obj:
                    await broadcast_message('downloads', {
                        'type': 'progress_update',
                        'task': {
                            'id': task_id,
                            'progress': 100.0,
                            'status': TaskStatus.COMPLETED.value,
                            'updated_at': datetime.now().isoformat(),
                            'filename': task_obj.filename,
                            'source': task_obj.source,
                            'title': task_obj.title,
                            'url': task_obj.url,
                            'subscription_id': task_obj.subscription_id
                        }
                    })

            except Exception as e:
                logging.error(f"下载失败: {str(e)}")
                # 更新任务状态为错误
                db.query(Task).filter(Task.id == task_id).update({
                    'status': TaskStatus.ERROR.value,
                    'error_message': str(e),
                    'updated_at': datetime.now()
                })
                db.commit()
                raise
    finally:
        try:
            db.rollback()
        except Exception:
            pass
        db.close()

async def process_task(self, task: Task):
    """处理下载任务"""
    try:
        # 更新任务状态
        db = get_session()
        try:
            db.query(Task).filter(Task.id == task.id).update({
                'status': TaskStatus.DOWNLOADING.value,
                'updated_at': datetime.now()
            })
            db.commit()
            
            # 广播状态更新 - 包含完整任务信息
            from routers.websocket import broadcast_message
            task_obj = db.query(Task).filter(Task.id == task.id).first()
            if task_obj:
                await broadcast_message('downloads', {
                    'type': 'status_update',
                    'task': {
                        'id': task.id,
                        'status': TaskStatus.DOWNLOADING.value,
                        'updated_at': datetime.now().isoformat(),
                        'filename': task_obj.filename,
                        'source': task_obj.source,
                        'title': task_obj.title,
                        'url': task_obj.url,
                        'subscription_id': task_obj.subscription_id
                    }
                })
        finally:
            try:
                db.rollback()
            except Exception:
                pass
            db.close()
            
        # 解析请求头
        headers = {}
        if task.headers:
            try:
                headers = json.loads(task.headers)
            except:
                logging.warning(f"解析请求头失败: {task.headers}")
        
        if task.source == 'others':  # 智能嗅探下载
            await download_task(
                task_id=task.id,
                url=task.url,
                headers=headers
            )
        elif task.source == 'x':  # X 独立下载逻辑
            from routers.x_downloader import x_download_task
            await x_download_task(
                task_id=task.id,
                url=task.url,
                format_id=task.format_id,
                headers=headers
            )
        else:  # yt-dlp下载
            from routers.wnxt import ytdlp_download_task
            await ytdlp_download_task(
                task_id=task.id,
                url=task.url,
                format_id=task.format_id,
                headers=headers
                # Cookie不再传递，ytdlp_download_task会自动从文件读取
            )
            
    except Exception as e:
        logging.error(f"任务处理失败: {str(e)}")
        db = get_session()
        try:
            db.query(Task).filter(Task.id == task.id).update({
                'status': TaskStatus.ERROR.value,
                'error_message': str(e),
                'updated_at': datetime.now()
            })
            db.commit()
            
            # 广播错误状态
            from routers.websocket import broadcast_message
            await broadcast_message('downloads', {
                'type': 'status_update',
                'task': {
                    'id': task.id,
                    'status': TaskStatus.ERROR.value,
                    'error_message': str(e),
                    'updated_at': datetime.now().isoformat()
                }
            })
        finally:
            try:
                db.rollback()
            except Exception:
                pass
            db.close()

# 创建全局下载管理器实例
download_manager = DownloadManager()
