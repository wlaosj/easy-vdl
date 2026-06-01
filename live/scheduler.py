# -*- coding: utf-8 -*-
"""
直播监控调度器
负责周期性检测直播状态并自动启动/停止录制
"""
import asyncio
import logging
import os
import random
from datetime import datetime
from typing import Dict, Optional
from sqlalchemy.orm import Session
import uuid
from contextlib import contextmanager


logger = logging.getLogger(__name__)

class AsyncBackgroundTasks:
    """模拟 FastAPI BackgroundTasks，用于 asyncio 环境"""
    def add_task(self, func, *args, **kwargs):
        if asyncio.iscoroutinefunction(func):
            asyncio.create_task(func(*args, **kwargs))
        else:
            # 如果是同步函数，则直接运行（或者放入线程池，但这里主要用于发送通知，通常是IO密集或async的）
            # 简单起见，这里假设主要是async函数被调用
            func(*args, **kwargs)

    def add_task_sync(self, func, *args, **kwargs):
        func(*args, **kwargs)



class LiveScheduler:
    """直播监控调度器"""
    
    def __init__(self):
        self.running = False
        self.monitoring_tasks: Dict[str, asyncio.Task] = {}  # subscription_id -> asyncio.Task
        self._db_session_factory = None
        self._keepalive_task = None
        self._license_error_logged = False  # 新增：全局授权错误日志标记
        self._hls_reconnect_attempts: Dict[str, int] = {}  # HLS 断流自动重连已尝试次数（成功重连后清零）
        self._reconnect_window: Dict[str, list] = {}  # [优化] 滑动窗口：记录最近断连时间戳，防止碎片风暴
        self._reconnect_bad_routes: Dict[str, set] = {}  # 每个订阅在重连周期内已失败的流线路
        self._exit_handling_subscriptions = set()  # 防止同一订阅并发处理异常退出
        self._sub_config_cache: Dict[str, dict] = {}  # [优化] 订阅配置内存缓存，减少每轮监控的 DB 查询
        self._offline_streaks: Dict[str, int] = {}  # 连续离线次数（用于抖动过滤）
        self._probe_streaks: Dict[str, int] = {}  # 连续探测失败次数（房间失效时自动停止监控）
        self._last_live_status: Dict[str, bool] = {}  # 订阅最近一次稳定状态缓存
        self._recording_file_sizes: Dict[str, int] = {}  # 订阅ID -> 录制文件上次大小
        self._recording_file_stale_start: Dict[str, float] = {}  # 订阅ID -> 文件停止增长起始时间
        self._last_youtube_cookie_refresh: float = 0  # YouTube Cookie 上次自动刷新时间
    
    def set_db_session_factory(self, factory):
        """设置数据库会话工厂"""
        self._db_session_factory = factory
    
    @contextmanager
    def _db_session(self):
        """数据库会话上下文管理器，自动处理 rollback 和关闭，消除重复的 try/finally/rollback/close 样板代码"""
        db = self._db_session_factory()
        try:
            yield db
        finally:
            try:
                db.rollback()
            except Exception:
                pass
            db.close()
    
    def invalidate_config_cache(self, subscription_id: str = None):
        """失效订阅配置缓存。subscription_id=None 时清空全部缓存。"""
        if subscription_id:
            self._sub_config_cache.pop(subscription_id, None)
        else:
            self._sub_config_cache.clear()
    
    async def start(self):
        """启动调度器"""
        if self.running:
            logger.warning("调度器已经在运行中")
            return
        
        self.running = True
        logger.info("直播调度器启动中...")
        
        
        # 启动时全局清理一次僵尸状态（处理重启导致的内存状态丢失）
        await self._cleanup_all_zombies()
        
        # 启动数据库保活任务，防止连接池因长时间闲置而Reset报错
        self._keepalive_task = asyncio.create_task(self._db_keepalive_loop())
        
        # 加载所有需要监控的订阅
        await self._load_subscriptions()
        
        logger.info(f"直播调度器已启动, 监控 {len(self.monitoring_tasks)} 个直播间")

    async def _db_keepalive_loop(self):
        """数据库连接保活循环"""
        logger.info("启动数据库连接保活任务 (每60秒)")
        while self.running:
            try:
                await asyncio.sleep(60)
                if self._db_session_factory:
                    try:
                        with self._db_session() as db:
                            from sqlalchemy import text
                            db.execute(text("SELECT 1"))
                            db.commit()
                    except Exception as e:
                        logger.debug(f"DB Keepalive error (ignored): {e}")
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Keepalive loop error: {e}")
                await asyncio.sleep(60)
    
    async def stop(self):
        """停止调度器"""
        if not self.running:
            return
        
        self.running = False
        if self._keepalive_task:
            self._keepalive_task.cancel()
            try:
                await self._keepalive_task
            except asyncio.CancelledError:
                pass
            self._keepalive_task = None
            
        logger.info("正在停止直播调度器...")
        
        # 取消所有监控任务
        for subscription_id, task in self.monitoring_tasks.items():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        
        self.monitoring_tasks.clear()
        
        # 停止所有录制
        from .recorder import live_recorder
        await live_recorder.stop_all_recordings()
        
        logger.info("直播调度器已停止")
    
    async def _load_subscriptions(self):
        """从数据库加载所有需要监控的订阅"""
        if not self._db_session_factory:
            logger.warning("数据库会话工厂未设置,跳过加载订阅")
            return
        
        try:
            from sql.models import LiveSubscription
            from sqlalchemy import or_
            
            with self._db_session() as db:
                subscriptions = db.query(LiveSubscription).filter(
                    or_(
                        LiveSubscription.monitor_enabled.is_(None),
                        LiveSubscription.monitor_enabled != "false"
                    )
                ).all()
                
                count = 0
                for sub in subscriptions:
                    room_url = sub.room_url
                    # 存量 YouTube watch?v= 链接自动迁移为频道永久直播页
                    if sub.platform == "youtube":
                        from .adapters.youtube import is_watch_video_url, resolve_channel_live_url
                        if is_watch_video_url(room_url):
                            resolved = await resolve_channel_live_url(room_url)
                            if resolved and resolved != room_url:
                                sub.room_url = resolved
                                db.commit()
                                room_url = resolved

                    # 存量 Twitch /videos/ 录播链接自动迁移为频道直播页
                    if sub.platform == "twitch":
                        from .adapters.twitch import is_vod_url, resolve_channel_url as resolve_twitch_channel_url
                        if is_vod_url(room_url):
                            resolved = await resolve_twitch_channel_url(room_url)
                            if resolved and resolved != room_url:
                                sub.room_url = resolved
                                db.commit()
                                room_url = resolved
                    await self.add_monitor(sub.id, room_url, sub.platform, sub.check_interval)
                    count += 1
                logger.info(f"直播调度器已加载并监控 {count} 个直播间")
        except Exception as e:
            logger.error(f"加载订阅失败: {e}")
    
    async def add_monitor(
        self,
        subscription_id: str,
        room_url: str,
        platform: str,
        check_interval: int = 60
    ):
        """
        添加直播间监控
        
        Args:
            subscription_id: 订阅ID
            room_url: 直播间URL
            platform: 平台
            check_interval: 检测间隔(秒)
        """
        if subscription_id in self.monitoring_tasks:
            logger.debug(f"订阅 {subscription_id} 已在监控中")
            return

        # 调度层兜底保护，避免异常配置导致高频探测。
        try:
            safe_interval = int(check_interval or 60)
        except Exception:
            safe_interval = 60
        safe_interval = max(10, min(600, safe_interval))
        
        # 创建监控任务
        task = asyncio.create_task(
            self._monitor_room(subscription_id, room_url, platform, safe_interval)
        )
        self.monitoring_tasks[subscription_id] = task
        
        logger.debug(f"已添加直播间监控: {subscription_id}, 间隔: {safe_interval}秒")
    
    async def remove_monitor(self, subscription_id: str, stop_recording: bool = True):
        """移除直播间监控"""
        task = self.monitoring_tasks.pop(subscription_id, None)
        self._offline_streaks.pop(subscription_id, None)
        self._last_live_status.pop(subscription_id, None)
        if task:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
            logger.info(f"已移除直播间监控: {subscription_id}")

        if not stop_recording:
            return

        # [新增] 移除监控时同时停止录制，防止僵尸进程
        from .recorder import live_recorder
        if live_recorder.is_recording(subscription_id):
            logger.warning(f"移除监控时检测到正在录制，强制停止: {subscription_id}")
            
            # 解析转码配置
            should_convert = True
            if self._db_session_factory:
                try:
                    from sql.models import LiveSubscription
                    import json
                    with self._db_session() as db:
                        sub = db.query(LiveSubscription).filter(LiveSubscription.id == subscription_id).first()
                        if sub and sub.extra_data:
                            extra = sub.extra_data if isinstance(sub.extra_data, dict) else json.loads(sub.extra_data)
                            should_convert = extra.get('auto_convert_mp4', True)
                except Exception as e:
                    logger.warning(f"获取转码配置失败，将使用默认值(True): {e}")
            
            # 强制停止并根据配置决定是否转码
            await self._stop_auto_recording(subscription_id, convert_to_mp4=should_convert)

    async def trigger_immediate_check(self, subscription_id: str) -> bool:
        """对指定订阅执行一次立即检查；若已开播且开启自动录制则立刻尝试开录。"""
        from .recorder import live_recorder

        if not self._db_session_factory:
            logger.warning(f"立即检查已跳过（DB工厂未设置）: {subscription_id}")
            return False

        try:
            from sql.models import LiveSubscription
            sub_data = None
            with self._db_session() as db:
                sub = db.query(LiveSubscription).filter(
                    LiveSubscription.id == subscription_id
                ).first()
                if sub:
                    sub_data = {
                        "auto_record": getattr(sub, "auto_record", None),
                        "room_url": getattr(sub, "room_url", None) or "",
                        "platform": getattr(sub, "platform", None) or "douyin",
                        "anchor_name": getattr(sub, "anchor_name", None) or "未知",
                        "quality": getattr(sub, "quality", None) or "原画",
                        "split_enabled": getattr(sub, "split_enabled", None),
                        "split_duration": getattr(sub, "split_duration", None),
                        "extra_data": getattr(sub, "extra_data", None),
                    }

            if not sub_data:
                logger.warning(f"立即检查已跳过（订阅不存在）: {subscription_id}")
                return False

            if sub_data.get("auto_record") != "true":
                logger.debug(f"立即检查已跳过（auto_record 未开启）: {subscription_id}")
                return False

            if live_recorder.is_recording(subscription_id):
                logger.debug(f"立即检查已跳过（已在录制）: {subscription_id}")
                return True

            room_url = sub_data.get("room_url", "")
            platform = sub_data.get("platform", "douyin")
            anchor_name = sub_data.get("anchor_name", "未知")
            selected_quality = sub_data.get("quality", "原画")
            segment_time = 0
            generate_subtitle = False

            if sub_data.get("split_enabled") == "true":
                segment_time = sub_data.get("split_duration") or 3600

            danmu_enabled = False
            compat_mode = False
            if sub_data.get("extra_data"):
                try:
                    import json as _json
                    extra_raw = sub_data.get("extra_data")
                    extra = extra_raw if isinstance(extra_raw, dict) else _json.loads(extra_raw or "{}")
                    generate_subtitle = extra.get("generate_subtitle", False)
                    danmu_enabled = extra.get("danmu_enabled", False)
                    compat_mode = extra.get("compat_mode", False)
                    if isinstance(danmu_enabled, str):
                        danmu_enabled = danmu_enabled.strip().lower() not in ("false", "0", "no")
                    if isinstance(compat_mode, str):
                        compat_mode = compat_mode.strip().lower() not in ("false", "0", "no")
                except Exception:
                    pass

            from . import adapters
            adapter = adapters.get_adapter_by_platform(platform) or adapters.get_adapter(room_url)
            if not adapter:
                logger.warning(f"立即检查失败：未找到适配器: {subscription_id}, platform={platform}")
                return False

            cookies = None
            try:
                from routers.cookie_manager import COOKIE_PATHS
                if getattr(adapter, "platform_name", None) and adapter.platform_name in COOKIE_PATHS:
                    cookie_path = COOKIE_PATHS[adapter.platform_name]
                    if cookie_path and os.path.exists(cookie_path):
                        with open(cookie_path, 'r', encoding='utf-8') as f:
                            raw_content = f.read().strip()
                            cookies = self._parse_cookie_content(raw_content) or None
            except Exception as cookie_err:
                logger.warning(f"立即检查读取/解析 Cookie 失败: {subscription_id}, {cookie_err}")

            room_info = await adapter.get_room_info(room_url, cookies=cookies)
            is_live = room_info.get('is_live', False)
            anchor_name = room_info.get('anchor_name') or anchor_name
            room_id = room_info.get('room_id', '')

            await self._update_subscription_status(
                subscription_id,
                is_live,
                anchor_name=anchor_name,
                room_id=room_id
            )

            if not is_live:
                logger.debug(f"立即检查完成：当前未开播: {subscription_id}")
                return False

            stream_data = await adapter.get_stream_url(room_url, selected_quality, cookies=cookies)
            stream_url = (stream_data or {}).get('url')
            if not stream_url:
                logger.warning(f"立即检查完成：开播但未拿到流地址: {subscription_id}")
                return False

            if live_recorder.is_recording(subscription_id):
                return True

            logger.info(f"[{platform}] 批量更新后立即检查命中开播，开始录制: {anchor_name} ({subscription_id})")

            await self._start_auto_recording(
                subscription_id,
                room_url,
                stream_url,
                anchor_name,
                platform,
                room_id=room_id or "",
                quality=selected_quality,
                segment_time=segment_time,
                generate_subtitle=generate_subtitle,
                danmu_enabled=danmu_enabled,
                compat_mode=compat_mode,
                is_merged_notification=True
            )
            return live_recorder.is_recording(subscription_id)
        except Exception as e:
            logger.error(f"立即检查失败: {subscription_id}, 错误: {e}")
            return False
    
    async def _monitor_room(
        self,
        subscription_id: str,
        room_url: str,
        platform: str,
        check_interval: int
    ):
        """
        监控单个直播间
        
        这是一个持续运行的协程,周期性检查直播状态
        支持用户主页链接和短链接
        """
        from .recorder import live_recorder

        from routers.license import license_manager  # 导入授权管理器
        from routers.websocket import broadcast_live_status_update
        from routers.notifications import NotificationService
        from sql.models import NotificationType

        
        logger.debug(f"开始监控直播间: {subscription_id}, URL: {room_url}")

        # 兜底保护：即使外部传入异常间隔，也避免进入高频探测。
        try:
            check_interval = int(check_interval or 60)
        except Exception:
            check_interval = 60
        check_interval = max(10, min(600, check_interval))
        
        first_offline_time = None # [新增] 用于记录下播持续时间
        
        # [优化] 首轮检测随机抖动：将所有任务的首次请求均匀分散在 [0, check_interval) 区间
        # 52 个任务不再同时发起 API 请求，从根本上避免平台限流
        import random
        jitter = random.uniform(0, min(check_interval, 30))  # 最大 30 秒，避免延迟过长
        logger.debug(f"监控任务首轮抖动延迟: {subscription_id}, {jitter:.1f}s")
        await asyncio.sleep(jitter)
        
        while self.running:
            try:
                # 0. 授权检查 (新增)
                if not await license_manager.is_active_for(f"live.scheduler.monitor:{subscription_id}"):
                    # 如果授权无效，检查是否正在录制，如果是则强制停止
                    if live_recorder.is_recording(subscription_id):
                        logger.warning(f"检测到授权失效，强制停止录制: {subscription_id}")
                        await self._stop_auto_recording(subscription_id, convert_to_mp4=True)
                    
                    # 记录日志并长时间休眠（5分钟），避免刷屏
                    
                    # 记录日志并短时间休眠（避免死循环空转），依赖外层循环或短 sleep
                    if not self._license_error_logged:
                        if license_manager.permanently_expired:
                            logger.warning(f"授权已过期（终态），暂停监控直播间。在手动刷新授权前，将不再重复提示。最近受影响: [{subscription_id}]")
                        else:
                            logger.warning(f"授权验证失败，暂停监控直播间。最近受影响: [{subscription_id}]")
                        self._license_error_logged = True
                    
                    # 终态或异常时，所有任务进入休眠以节省资源
                    await asyncio.sleep(60 if license_manager.permanently_expired else 30)
                    continue
                
                # 授权有效，如果是从无效恢复的，重置标记
                if self._license_error_logged:
                    self._license_error_logged = False
                    logger.info("授权已恢复，直播间监控任务继续运转。")

                
                # 1. 获取直播间数据 (通用适配器模式)
                from . import adapters
                
                is_live = False
                stream_url = None
                anchor_name = ""
                room_id = None
                cookies = None
                selected_quality = "原画"
                probe_success = False
                
                try:
                    adapter = adapters.get_adapter_by_platform(platform)
                    if not adapter:
                        # 尝试根据 URL 匹配
                        adapter = adapters.get_adapter(room_url)
                    
                    if adapter:
                        # 尝试获取对应平台的Cookie
                        from routers.cookie_manager import COOKIE_PATHS
                        cookies = None
                        try:
                            # 逻辑优化：统一在调度层进行 Cookie 标准化处理
                            platform_name = adapter.platform_name
                            if platform_name in COOKIE_PATHS:
                                cookie_path = COOKIE_PATHS[platform_name]
                                if os.path.exists(cookie_path):
                                    with open(cookie_path, 'r', encoding='utf-8') as f:
                                        raw_content = f.read().strip()
                                        cookies = self._parse_cookie_content(raw_content)
                                        if not cookies:
                                            cookies = None
                        except Exception as cookie_err:
                            logger.warning(f"读取/解析 {platform} Cookie失败: {cookie_err}")

                        # 录制中跳过 API 轮询降低风控，由文件增长检测判断下播
                        if live_recorder.is_recording(subscription_id):
                            room_info = {"is_live": True, "probe_success": True, "anchor_name": "", "room_id": ""}
                            logger.info(f"[{platform}] 录制中，跳过API探测: {subscription_id}")
                        else:
                            # 获取直播间信息
                            room_info = await adapter.get_room_info(room_url, cookies=cookies)
                        probe_success = bool(room_info.get("probe_success", True))
                        
                        is_live = room_info.get('is_live', False)
                        anchor_name = room_info.get('anchor_name', '')
                        room_id = room_info.get('room_id', '')
                        
                    else:
                        logger.warning(f"未找到适配器: {platform}, 跳过检测")
                        
                except Exception as e:
                    logger.debug(f"获取直播数据失败 ({platform}): {e}")

                platform_key = (platform or "").lower()
                if probe_success:
                    if is_live:
                        self._offline_streaks[subscription_id] = 0
                    else:
                        streak = self._offline_streaks.get(subscription_id, 0) + 1
                        self._offline_streaks[subscription_id] = streak
                        # YouTube 在页面结构波动时容易瞬时误判，要求连续离线 3 轮才真正置离线。
                        offline_threshold = 3 if platform_key == "youtube" else 1
                        if streak < offline_threshold:
                            if self._last_live_status.get(subscription_id, False):
                                logger.debug(
                                    f"[{platform}] 离线判定缓冲中: {subscription_id}, streak={streak}/{offline_threshold}, 暂沿用在线状态"
                                )
                                is_live = True
                else:
                    # YouTube 人机验证时自动刷新 Cookie 重试一次
                    probe_error = (room_info or {}).get("raw_data", {}).get("probe_error_type", "")
                    if platform_key == "youtube" and probe_error == "auth_required":
                        import time as _time
                        if _time.time() - self._last_youtube_cookie_refresh > 300:
                            self._last_youtube_cookie_refresh = _time.time()
                            logger.info(f"YouTube 触发人机验证，自动刷新 Cookie...")
                            try:
                                from routers.youtube import youtube_api
                                cookies = await youtube_api.export_cookies_netscape(force_refresh=True)
                                if cookies and "SAPISID" in cookies:
                                    cookie_path = "/app/database/cookie/youtube_cookie.txt"
                                    os.makedirs(os.path.dirname(cookie_path), exist_ok=True)
                                    with open(cookie_path, 'w') as f:
                                        f.write(cookies)
                                    logger.info("YouTube Cookie 已自动刷新，重试探测...")
                                    retry = await adapter.get_room_info(room_url, cookies=cookies)
                                    if retry.get("probe_success", False):
                                        probe_success = True
                                        is_live = bool(retry.get("is_live", False))
                                        anchor_name = retry.get("anchor_name", "")
                                        room_id = retry.get("room_id", "")
                                        logger.info(f"YouTube Cookie 刷新后探测成功: is_live={is_live}")
                            except Exception as refresh_err:
                                logger.warning(f"YouTube Cookie 自动刷新失败: {refresh_err}")

                    if not probe_success:
                        # 判断是否为明确可判定永久失效的房间
                        probe_error_type = (room_info or {}).get("raw_data", {}).get("probe_error_type", "")
                        is_permanent_failure = (
                            platform == "youtube" and probe_error_type == "permanent_offline"
                        )

                        if platform == "cc" or is_permanent_failure:
                            streak = self._probe_streaks.get(subscription_id, 0) + 1
                            self._probe_streaks[subscription_id] = streak
                            threshold = 3  # CC/YouTube 统一连续 3 次确认后自动停止

                            if streak >= threshold:
                                from sql.database_postgresql import get_db
                                from sql.models import LiveSubscription
                                import json as _json
                                try:
                                    d = next(get_db())
                                    sub = d.query(LiveSubscription).filter(
                                        LiveSubscription.id == subscription_id
                                    ).first()
                                    if sub:
                                        sub.monitor_enabled = "false"
                                        # 在 extra_data 中标记为系统自动停止，用于区分用户手动暂停
                                        extra = {}
                                        try:
                                            if sub.extra_data:
                                                extra = _json.loads(sub.extra_data)
                                        except Exception:
                                            pass
                                        extra["auto_disabled"] = True
                                        sub.extra_data = _json.dumps(extra, ensure_ascii=False)
                                        d.commit()
                                    logger.warning(
                                        f"[{platform}] 房间已永久失效（{probe_error_type}），已自动停止监控: {subscription_id}"
                                    )
                                except Exception as e:
                                    logger.warning(f"停止监控失败: {e}")
                                finally:
                                    try:
                                        d.close()
                                    except Exception:
                                        pass
                            else:
                                if subscription_id in self._last_live_status:
                                    is_live = self._last_live_status[subscription_id]
                                    logger.warning(
                                        f"[{platform}] 探测失败（{streak}/{threshold}），沿用上次状态: {subscription_id}, is_live={is_live}"
                                    )
                                else:
                                    is_live = False
                        else:
                            if subscription_id in self._last_live_status:
                                is_live = self._last_live_status[subscription_id]
                                logger.warning(
                                    f"[{platform}] 状态采集失败，沿用上次状态: {subscription_id}, is_live={is_live}"
                                )
                            else:
                                is_live = False
                if is_live:
                    first_offline_time = None # 重置下播计时
                
                # 2. 更新数据库状态 (包括动态更新 anchor_name 和 room_id)
                await self._update_subscription_status(
                    subscription_id, 
                    is_live, 
                    anchor_name=anchor_name,
                    room_id=room_id
                )
                
                # 3. 判断是否需要开始/停止录制
                is_recording = live_recorder.is_recording(subscription_id)
                # 检测录制进程是否已经挂掉（字典里有任务但 is_recording 为 False）
                is_task_active = subscription_id in live_recorder.recording_tasks
                
                if not is_recording and is_task_active and subscription_id not in self._exit_handling_subscriptions:
                    logger.warning(f"检测到录制进程已异常停止: {subscription_id}, 转交异常退出处理器执行重连策略...")
                    await self._handle_unexpected_exit(subscription_id)
                    is_recording = live_recorder.is_recording(subscription_id)
                    is_task_active = subscription_id in live_recorder.recording_tasks
                
                # [FIX] 如果数据库显示正在录制，但 live_recorder 没有任何任务 (例如重启后)
                # 我们也需要将其重置，否则界面会一直显示“录制中”
                if not is_recording and not is_task_active:
                    # 只有在初次运行或发现状态不一致时才检查数据库，避免每轮都查
                    await self._sync_zombie_record(subscription_id)
                
                if is_live and not is_recording and not is_task_active and subscription_id not in self._exit_handling_subscriptions:
                    # 开播且未在录制
                    logger.debug(f"检测到开播，准备检查录制配置: {subscription_id} ({anchor_name})")
                    
                    # 从数据库读取订阅配置
                    segment_time = 0
                    generate_subtitle = False
                    auto_convert_mp4 = True
                    danmu_enabled = False
                    should_record = False
                    
                    if self._db_session_factory:
                        try:
                            import json
                            
                            # [优化] 使用内存缓存减少 DB 查询，缓存 TTL 120 秒
                            import time as _time
                            cached = self._sub_config_cache.get(subscription_id)
                            if cached and (_time.time() - cached.get('_ts', 0)) < 120:
                                cfg = cached
                            else:
                                from sql.models import LiveSubscription
                                cfg = None
                                with self._db_session() as db:
                                    sub = db.query(LiveSubscription).filter(
                                        LiveSubscription.id == subscription_id
                                    ).first()
                                    if sub:
                                        extra = {}
                                        if sub.extra_data:
                                            if isinstance(sub.extra_data, dict):
                                                extra = sub.extra_data
                                            else:
                                                try:
                                                    extra = json.loads(sub.extra_data)
                                                except:
                                                    extra = {}
                                        cfg = {
                                            'auto_record': sub.auto_record,
                                            'quality': sub.quality or "原画",
                                            'split_enabled': sub.split_enabled,
                                            'split_duration': sub.split_duration,
                                            'generate_subtitle': extra.get('generate_subtitle', False),
                                            'auto_convert_mp4': extra.get('auto_convert_mp4', True),
                                            'danmu_enabled': extra.get('danmu_enabled', False),
                                            '_ts': _time.time(),
                                        }
                                        self._sub_config_cache[subscription_id] = cfg
                            
                            if cfg:
                                if cfg.get('auto_record') != "true":
                                    logger.debug(f"订阅已开播但自动录制未开启，跳过录制: {subscription_id}")
                                    should_record = False
                                else:
                                    should_record = True
                                
                                selected_quality = cfg.get('quality', "原画")
                                if cfg.get('split_enabled') == "true":
                                    segment_time = cfg.get('split_duration') or 3600
                                generate_subtitle = cfg.get('generate_subtitle', False)
                                auto_convert_mp4 = cfg.get('auto_convert_mp4', True)
                                danmu_enabled = cfg.get('danmu_enabled', False)
                                compat_mode = cfg.get('compat_mode', False)
                                if isinstance(danmu_enabled, str):
                                    danmu_enabled = danmu_enabled.strip().lower() not in ("false", "0", "no")
                                if isinstance(compat_mode, str):
                                    compat_mode = compat_mode.strip().lower() not in ("false", "0", "no")
                        except Exception as e:
                            logger.error(f"读取订阅配置失败: {e}")
                    
                    if should_record:
                        try:
                            stream_data = await adapter.get_stream_url(room_url, selected_quality, cookies=cookies)
                            selected_stream_url = (stream_data or {}).get('url')
                            if selected_stream_url:
                                stream_url = selected_stream_url
                            elif selected_quality != "原画":
                                # 目标画质不可用时，回退原画拉流，减少因画质切换导致的漏录。
                                fallback_data = await adapter.get_stream_url(room_url, "原画", cookies=cookies)
                                stream_url = (fallback_data or {}).get('url')
                        except Exception as stream_err:
                            logger.warning(f"获取目标画质流地址失败: {subscription_id}, quality={selected_quality}, err={stream_err}")

                        if not stream_url:
                            logger.warning(f"检测到开播但无法获取可用流地址，跳过本轮录制: {subscription_id}")
                        else:
                            logger.info(f"[{platform}] 检测到 {anchor_name} 开播，开始录制... quality={selected_quality}")
                            await self._start_auto_recording(
                                subscription_id, room_url, stream_url, anchor_name, platform,
                                room_id=room_id or "",
                                quality=selected_quality,
                                segment_time=segment_time,
                                generate_subtitle=generate_subtitle,
                                danmu_enabled=danmu_enabled,
                                compat_mode=compat_mode,
                                is_merged_notification=True # 传入合并通知标志
                            )
                
                elif not is_live and is_recording:
                    # API 说下播，由文件增长检测决定是否真断
                    if first_offline_time is None:
                        first_offline_time = datetime.now()
                    logger.info(f"API检测到下播，等待文件增长检测确认: {subscription_id}")

                # ── 文件增长检测：录制中判断流是否真正结束 ──
                if is_recording:
                    try:
                        task = live_recorder.recording_tasks.get(subscription_id, {})
                        record_path = task.get('output_path', '')
                        if record_path and os.path.exists(record_path):
                            import time as _time
                            current_size = os.path.getsize(record_path)
                            last_size = self._recording_file_sizes.get(subscription_id)
                            self._recording_file_sizes[subscription_id] = current_size

                            if last_size is not None and current_size == last_size:
                                if subscription_id not in self._recording_file_stale_start:
                                    self._recording_file_stale_start[subscription_id] = _time.time()
                                stale_seconds = _time.time() - self._recording_file_stale_start[subscription_id]
                                if stale_seconds >= 30:
                                    logger.warning(f"录制文件 {stale_seconds:.0f}s 无增长，停止录制: {subscription_id}")
                                    await self._stop_auto_recording(subscription_id, convert_to_mp4=True)
                            else:
                                self._recording_file_stale_start.pop(subscription_id, None)
                    except Exception:
                        pass

            except asyncio.CancelledError:
                logger.info(f"监控任务被取消: {subscription_id}")
                break
            except Exception as e:
                logger.error(f"监控直播间出错: {subscription_id}, 错误: {e}")
            
            # 等待下次检查（±20% 随机抖动，避免固定间隔被识别为脚本）
            try:
                jitter = check_interval * random.uniform(0.8, 1.2)
                await asyncio.sleep(jitter)
            except asyncio.CancelledError:
                break
        
        if not self.running:
            logger.debug(f"停止监控直播间: {subscription_id}")
        else:
            logger.info(f"停止监控直播间: {subscription_id}")
    
    async def _update_subscription_status(
        self, 
        subscription_id: str, 
        is_live: bool,
        anchor_name: str = None,
        room_id: str = None
    ):
        """更新订阅状态到数据库 (包括动态更新 anchor_name 和 room_id)"""
        if not self._db_session_factory:
            return
        
        try:
            from sql.models import LiveSubscription, NotificationType
            from routers.notifications import NotificationService
            
            with self._db_session() as db:
                subscription = db.query(LiveSubscription).filter(
                    LiveSubscription.id == subscription_id
                ).first()
                
                if subscription:
                    was_live = subscription.is_live == "true"
                    is_live_now = is_live
                    
                    subscription.is_live = "true" if is_live else "false"
                    subscription.last_check_time = datetime.now()
                    if is_live:
                        subscription.last_live_time = datetime.now()
                    
                    if anchor_name and not subscription.anchor_name:
                        subscription.anchor_name = anchor_name
                        logger.debug(f"更新订阅 {subscription_id} 主播名: {anchor_name}")
                    
                    if room_id and subscription.room_id != room_id:
                        subscription.room_id = room_id
                        logger.debug(f"更新订阅 {subscription_id} room_id: {room_id}")
                    
                    db.commit()
                    self._last_live_status[subscription_id] = is_live

                    from routers.websocket import broadcast_live_status_update
                    await broadcast_live_status_update({
                        "id": subscription_id,
                        "is_live": is_live,
                        "anchor_name": subscription.anchor_name
                    })

                    if is_live_now and not was_live:
                        if subscription.notification_enabled == "true":
                            logger.info(f"触发开播通知: {subscription.anchor_name}")
                            bg_tasks = AsyncBackgroundTasks()
                            
                            avatar_url = subscription.avatar_url
                            display_name = subscription.anchor_name or subscription.room_id or "未知主播"
                            
                            extra_data = {
                                "subscription_id": subscription.id,
                                "room_url": subscription.room_url,
                                "platform": subscription.platform,
                                "cover": None,
                                "user_id": subscription.room_id
                            }
                            
                            try:
                                from sql.models import User
                                with self._db_session() as notification_db:
                                    notification = await NotificationService.create_notification(
                                        db=notification_db,
                                        notification_type=NotificationType.LIVE_START.value if hasattr(NotificationType, 'LIVE_START') else "live_start",
                                        title=f"🔴 {display_name} 开播啦！",
                                        content=f"平台: {subscription.platform}\n时间: {datetime.now().strftime('%H:%M:%S')}\n地址: {subscription.room_url}",
                                        user_id=None,
                                        priority=1,
                                        extra_data=extra_data
                                    )
                                    
                                    admin_user = notification_db.query(User).filter(User.is_admin == "true").first()
                                    if not admin_user:
                                        admin_user = notification_db.query(User).first()
                                    
                                    if admin_user:
                                        notification.user_id = admin_user.id
                                        notification_db.commit()

                                        if subscription.auto_record == "true":
                                            logger.info(f"订阅开启了自动录制，跳过纯开播通知，等待合并发送: {subscription.anchor_name}")
                                        else:
                                            await NotificationService.send_notification(notification_db, notification, bg_tasks)
                                    else:
                                        logger.warning("未找到可接收通知的用户（无用户或管理员），跳过通知发送")
                            except Exception as u_err:
                                logger.error(f"查找通知接收用户失败: {u_err}")
        except Exception as e:
            logger.error(f"更新订阅状态失败: {e}")
    
    
    async def _start_auto_recording(
        self,
        subscription_id: str,
        room_url: str, # [新增] 传入直播间URL用于通知展示
        stream_url: str,
        anchor_name: str,
        platform: str,
        room_id: str = "",
        quality: str = "原画",
        segment_time: int = 0,
        generate_subtitle: bool = False,
        danmu_enabled: bool = False,
        compat_mode: bool = False,  # [新增] 兼容模式
        is_merged_notification: bool = True,  # [新增] 是否为合并通知模式
        send_start_notification: bool = True  # [新增] 重连时不发送开播通知
    ):
        """
        自动开始录制

        Args:
            subscription_id: 订阅ID
            stream_url: 直播流URL
            anchor_name: 主播名称
            platform: 平台
            segment_time: 分段时间(秒), 0表示不分段
            generate_subtitle: 是否生成字幕
            compat_mode: 兼容模式（实时重编码），应对网络丢包导致的花屏
            send_start_notification: 是否发送开播通知（重连时应为False）
        """
        from .recorder import live_recorder
        
        # 生成输出文件路径
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        safe_anchor_name = "".join(c for c in anchor_name if c.isalnum() or c in (' ', '-', '_')).strip()
        if not safe_anchor_name:
            safe_anchor_name = "unknown"
        
        filename = f"{safe_anchor_name}_{timestamp}_{str(uuid.uuid4())[:8]}.ts"
        output_dir = f"/app/downloads/live/{platform}/{safe_anchor_name}"
        os.makedirs(output_dir, exist_ok=True)
        output_path = os.path.join(output_dir, filename)
        
        try:
            # 获取当前事件循环，用于回调
            loop = asyncio.get_running_loop()
            
            def on_process_exit(sub_id):
                """录制进程意外退出时的回调"""
                asyncio.run_coroutine_threadsafe(
                    self._handle_unexpected_exit(sub_id), loop
                )

            # 启动录制 (支持分段和字幕)
            await live_recorder.start_recording(
                subscription_id=subscription_id,
                stream_url=stream_url,
                output_path=output_path,
                quality=quality,
                segment_time=segment_time,
                generate_subtitle=generate_subtitle,
                compat_mode=compat_mode,
                on_exit_callback=on_process_exit,
                platform=platform,
                source_url=room_url,
                room_url=room_url if danmu_enabled else None,
                anchor_name=anchor_name,
                room_id=room_id or ""
            )
            
            # 更新数据库
            await self._update_recording_status(subscription_id, True, output_path)
            
            # 创建录制记录
            await self._create_record(subscription_id, stream_url, output_path, quality=quality)

            # 发送录制开始通知 (支持合并文案)
            # [净化] 去除URL参数以避免Markdown解析错误(如下划线)且保持清爽
            clean_url = room_url.split('?')[0] if room_url else "未知"

            # 重连时不发送开播通知，避免通知风暴
            if send_start_notification:
                if is_merged_notification:
                    # 合并通知文案
                    notify_title = f"📹 {anchor_name} 开播并开始录制！"
                    notify_content = f"平台: {platform}\n任务: 自动录制\n时间: {datetime.now().strftime('%H:%M:%S')}\n地址: {clean_url}"
                else:
                    # 纯录制通知
                    notify_title = f"📹 开始录制: {anchor_name}"
                    notify_content = f"平台: {platform}\n任务: 自动录制\n时间: {datetime.now().strftime('%H:%M:%S')}"

                await self._send_admin_notification(
                    title=notify_title,
                    content=notify_content,
                    extra_data={"subscription_id": subscription_id}
                )

            
        except Exception as e:
            logger.error(f"自动开始录制失败: {subscription_id}, 错误: {e}")
            raise
            
    async def _send_admin_notification(self, title: str, content: str, extra_data: dict = None):
        """发送通知给管理员"""
        if not self._db_session_factory: return
        try:
            from routers.notifications import NotificationService
            from sql.models import User
            
            with self._db_session() as db:
                admin_user = db.query(User).filter(User.is_admin == "true").first()
                if not admin_user:
                    admin_user = db.query(User).first()
                
                if admin_user:
                    bg_tasks = AsyncBackgroundTasks()
                    notification = await NotificationService.create_notification(
                        db=db,
                        notification_type="system",
                        title=title,
                        content=content,
                        user_id=admin_user.id,
                        extra_data=extra_data
                    )
                    await NotificationService.send_notification(db, notification, bg_tasks)
        except Exception as e:
            logger.error(f"发送管理员通知失败: {e}")

    
    async def _stop_auto_recording(self, subscription_id: str, convert_to_mp4: bool = True, send_notification: bool = True):
        """
        自动停止录制
        
        Args:
            subscription_id: 订阅ID
            convert_to_mp4: 是否自动转码为MP4
        """
        from .recorder import live_recorder
        
        try:
            # 查找当前的录制记录ID与平台
            record_id = None
            subscription_platform = ""
            if self._db_session_factory:
                from sql.models import LiveRecord, LiveSubscription
                with self._db_session() as db:
                    record = db.query(LiveRecord).filter(
                        LiveRecord.subscription_id == subscription_id,
                        LiveRecord.status == "recording"
                    ).order_by(LiveRecord.start_time.desc()).first()
                    if record:
                        record_id = record.id

                    sub = db.query(LiveSubscription).filter(
                        LiveSubscription.id == subscription_id
                    ).first()
                    if sub and getattr(sub, "platform", None):
                        subscription_platform = (sub.platform or "").lower()

            # 定义转码完成的回调
            def on_transcode_finished(success, mp4_path):
                if not success or not record_id or not self._db_session_factory:
                    return
                
                logger.info(f"自动转码任务完成，更新数据库记录: {record_id}")
                try:
                    with self._db_session() as db_session:
                        rec = db_session.query(LiveRecord).filter(LiveRecord.id == record_id).first()
                        if rec:
                            rec.converted = "true"
                            rec.converted_path = mp4_path
                            rec.converted_format = "mp4"
                            rec.file_path = mp4_path
                            rec.format = "mp4"
                            if os.path.exists(mp4_path):
                                rec.file_size = os.path.getsize(mp4_path)
                            db_session.commit()
                            logger.info(f"数据库记录已更新为已转码: {record_id}")
                except Exception as ex:
                    logger.error(f"自动化更新转码结果失败: {ex}")

            result = await live_recorder.stop_recording(
                subscription_id, 
                convert_to_mp4=convert_to_mp4,
                delete_original=True,
                on_convert_complete=on_transcode_finished if record_id else None
            )
            
            if result['success']:
                # 更新数据库
                await self._update_recording_status(subscription_id, False, None)
                
                duration = result.get('duration', 0)
                file_size = result.get('file_size', 0)
                is_reconnect_phase = (not convert_to_mp4 and not send_notification)
                # 重连阶段碎片清理策略：抖音更激进，其他平台保持保守阈值
                if subscription_platform == "douyin":
                    should_drop_fragment = is_reconnect_phase and (
                        file_size <= 0 or (duration <= 60 and file_size < 12 * 1024 * 1024)
                    )
                else:
                    should_drop_fragment = is_reconnect_phase and (
                        file_size <= 0 or (duration <= 15 and file_size < 1024 * 1024)
                    )

                if should_drop_fragment and record_id and self._db_session_factory:
                    try:
                        from sql.models import LiveRecord
                        with self._db_session() as db_drop:
                            rec = db_drop.query(LiveRecord).filter(LiveRecord.id == record_id).first()
                            if rec:
                                db_drop.delete(rec)
                                db_drop.commit()
                    except Exception as drop_err:
                        logger.warning(f"删除重连短碎片记录失败: {subscription_id}, {drop_err}")

                    dropped_path = result.get('file_path')
                    if dropped_path and os.path.exists(dropped_path):
                        try:
                            os.remove(dropped_path)
                        except Exception as rm_err:
                            logger.warning(f"删除重连短碎片文件失败: {dropped_path}, {rm_err}")

                    logger.info(
                        f"已清理重连短碎片: {subscription_id}, platform={subscription_platform or 'unknown'}, "
                        f"duration={duration}s, file_size={file_size}B"
                    )
                else:
                    # 更新录制记录
                    await self._update_record(
                        subscription_id,
                        duration=duration,
                        file_size=file_size
                    )

                if send_notification:
                    # [新增] 发送停止录制通知
                    try:
                        duration_sec = result.get('duration', 0)
                        hours, remainder = divmod(duration_sec, 3600)
                        minutes, seconds = divmod(remainder, 60)
                        duration_str = f"{int(hours)}小时{int(minutes)}分{int(seconds)}秒" if hours > 0 else f"{int(minutes)}分{int(seconds)}秒"
                        
                        size_mb = result.get('file_size', 0) / (1024 * 1024)
                        size_str = f"{size_mb:.2f} MB" if size_mb < 1024 else f"{size_mb/1024:.2f} GB"

                        # 获取主播名用于通知标题
                        anchor_name = "未知主播"
                        platform = "unknown"
                        if self._db_session_factory:
                            from sql.models import LiveSubscription
                            with self._db_session() as db_notify:
                                sub_notify = db_notify.query(LiveSubscription).filter(LiveSubscription.id == subscription_id).first()
                                if sub_notify:
                                    anchor_name = sub_notify.anchor_name or sub_notify.room_id
                                    platform = sub_notify.platform

                        await self._send_admin_notification(
                            title=f"⏹ 录制已完成: {anchor_name}",
                            content=f"平台: {platform}\n时长: {duration_str}\n大小: {size_str}\n时间: {datetime.now().strftime('%H:%M:%S')}",
                            extra_data={"subscription_id": subscription_id}
                        )
                    except Exception as notify_e:
                        logger.error(f"发送录制完成通知失败: {notify_e}")

        except Exception as e:
            logger.error(f"自动停止录制失败: {subscription_id}, 错误: {e}")

    async def stop_recording_for_subscription(self, subscription_id: str, convert_to_mp4: bool = True) -> bool:
        """
        对外公开的“停止指定订阅录制”接口。
        供 Telegram Bot / API 等外部调用，避免直接依赖内部私有方法。
        """
        from .recorder import live_recorder

        try:
            is_recording = live_recorder.is_recording(subscription_id)
            is_task_active = subscription_id in live_recorder.recording_tasks

            if not is_recording and not is_task_active:
                logger.info(f"停止录制请求已忽略：当前无活跃录制任务: {subscription_id}")
                await self._update_recording_status(subscription_id, False, None)
                return True

            await self._stop_auto_recording(subscription_id, convert_to_mp4=convert_to_mp4)
            return True
        except Exception as e:
            logger.error(f"公开停止录制接口执行失败: {subscription_id}, 错误: {e}")
            return False


    async def _handle_unexpected_exit(self, subscription_id: str):
        """处理录制进程意外退出 (如直播结束、HLS/FLV 断流或 ffmpeg 崩溃)；支持自动重连。"""
        from .recorder import live_recorder

        if subscription_id in self._exit_handling_subscriptions:
            logger.info(f"忽略重复的退出信号，已有处理进行中: {subscription_id}")
            return
        self._exit_handling_subscriptions.add(subscription_id)

        exit_ctx = live_recorder.get_exit_context(subscription_id)
        exit_reason = exit_ctx.get("reason", "unknown")
        exit_detail = exit_ctx.get("detail", "")

        logger.warning(
            f"接收到录制进程退出信号: {subscription_id}, reason={exit_reason}, "
            f"detail={exit_detail[:120] if exit_detail else '-'}"
        )

        async def do_full_stop():
            await self._stop_auto_recording(subscription_id, convert_to_mp4=True)
            try:
                await self._update_subscription_status(subscription_id, False)
                logger.info(f"录制结束同步更新直播间状态为【关播】: {subscription_id}")
            except Exception as e:
                logger.error(f"录制结束同步更新状态失败: {e}")
            self._hls_reconnect_attempts.pop(subscription_id, None)
            self._reconnect_bad_routes.pop(subscription_id, None)
            live_recorder.clear_exit_context(subscription_id)

        try:
            sub_data = None
            if self._db_session_factory:
                try:
                    from sql.models import LiveSubscription
                    with self._db_session() as db:
                        sub = db.query(LiveSubscription).filter(
                            LiveSubscription.id == subscription_id
                        ).first()
                        if sub:
                            sub_data = {
                                "auto_record": getattr(sub, "auto_record", None),
                                "room_url": getattr(sub, "room_url", None) or "",
                                "platform": getattr(sub, "platform", None) or "douyin",
                                "anchor_name": getattr(sub, "anchor_name", None) or "未知",
                                "quality": getattr(sub, "quality", None) or "原画",
                                "split_enabled": getattr(sub, "split_enabled", None),
                                "split_duration": getattr(sub, "split_duration", None),
                                "extra_data": getattr(sub, "extra_data", None),
                            }
                except Exception as e:
                    logger.warning(f"重连前读取订阅失败: {e}")

            if not sub_data or sub_data.get("auto_record") != "true":
                await do_full_stop()
                return

            room_url = sub_data.get("room_url", "")
            platform = sub_data.get("platform", "douyin")
            anchor_name = sub_data.get("anchor_name", "未知")
            selected_quality = sub_data.get("quality", "原画")
            segment_time = 0
            generate_subtitle = False
            danmu_enabled = False
            compat_mode = False
            if sub_data.get("split_enabled") == "true":
                segment_time = sub_data.get("split_duration") or 3600
            if sub_data.get("extra_data"):
                try:
                    import json as _json
                    extra_raw = sub_data.get("extra_data")
                    extra = extra_raw if isinstance(extra_raw, dict) else _json.loads(extra_raw or "{}")
                    generate_subtitle = extra.get("generate_subtitle", False)
                    danmu_enabled = extra.get("danmu_enabled", False)
                    compat_mode = extra.get("compat_mode", False)
                    if isinstance(danmu_enabled, str):
                        danmu_enabled = danmu_enabled.strip().lower() not in ("false", "0", "no")
                    if isinstance(compat_mode, str):
                        compat_mode = compat_mode.strip().lower() not in ("false", "0", "no")
                except Exception:
                    pass

            recent_run_seconds = None
            running_task = live_recorder.recording_tasks.get(subscription_id)
            if running_task and running_task.get("start_time"):
                try:
                    recent_run_seconds = int((datetime.now() - running_task["start_time"]).total_seconds())
                except Exception:
                    recent_run_seconds = None
            exit_code = None
            if isinstance(exit_detail, str) and "ffmpeg_exit_code=" in exit_detail:
                try:
                    exit_code = int(exit_detail.split("ffmpeg_exit_code=", 1)[1].split()[0].strip())
                except Exception:
                    exit_code = None
            if exit_code is None and running_task:
                try:
                    proc = running_task.get("process")
                    if proc:
                        polled_code = proc.poll()
                        if polled_code is not None:
                            exit_code = int(polled_code)
                except Exception:
                    exit_code = None

            max_reconnect = 2
            reconnect_delay_seconds = 8
            if exit_reason == "transient_hls":
                max_reconnect = 3
                reconnect_delay_seconds = 6
            elif exit_reason == "stream_data_error":
                max_reconnect = 1
                reconnect_delay_seconds = 12
            elif exit_reason == "ffmpeg_error":
                max_reconnect = 1
                reconnect_delay_seconds = 10
            elif exit_reason == "upstream_forbidden":
                # 上游拒绝（如 403）可能是短时鉴权/路由抖动：采用限次+长退避，避免风暴
                max_reconnect = 2
                reconnect_delay_seconds = 15

            # 抖音弱网抖动时，拉长首轮等待并增加预算，降低频繁短段
            if platform == "douyin" and exit_reason in ("transient_hls", "ffmpeg_error", "unknown"):
                max_reconnect = max(max_reconnect, 4)
                reconnect_delay_seconds = max(reconnect_delay_seconds, 10)
                if recent_run_seconds is not None and recent_run_seconds < 120:
                    max_reconnect = max(max_reconnect, 5)
                    reconnect_delay_seconds = max(reconnect_delay_seconds, 15)
            elif platform == "huya" and exit_reason in ("transient_hls", "ffmpeg_error", "unknown"):
                # 虎牙开播初期常见短抖动，放宽重连预算并避免过快重连导致同一路由反复失败
                max_reconnect = max(max_reconnect, 4)
                reconnect_delay_seconds = max(reconnect_delay_seconds, 8)
                if recent_run_seconds is not None and recent_run_seconds < 20:
                    # 开录即秒退时进一步增加预算，给切换 CDN/协议更多机会
                    max_reconnect = max(max_reconnect, 5)
                    reconnect_delay_seconds = max(reconnect_delay_seconds, 10)

            reconnect_round = self._hls_reconnect_attempts.get(subscription_id, 0)

            # [优化] 滑动窗口限流：防止频繁断连-重连产生碎片文件风暴
            now_ts = datetime.now().timestamp()
            window = self._reconnect_window.setdefault(subscription_id, [])
            window.append(now_ts)
            # 保留最近 30 分钟的断连记录
            window[:] = [t for t in window if now_ts - t < 1800]
            if len(window) > 10:
                logger.error(
                    f"30分钟内断连超过 10 次，停止自动重连以防碎片风暴: {subscription_id}"
                )
                self._reconnect_window.pop(subscription_id, None)
                await do_full_stop()
                return

            from . import adapters
            adapter = adapters.get_adapter_by_platform(platform) or adapters.get_adapter(room_url)
            if not adapter:
                await do_full_stop()
                return

            cookies = None
            try:
                from routers.cookie_manager import COOKIE_PATHS
                if getattr(adapter, "platform_name", None) and adapter.platform_name in COOKIE_PATHS:
                    path = COOKIE_PATHS[adapter.platform_name]
                    if path and os.path.exists(path):
                        with open(path, "r", encoding="utf-8") as f:
                            cookies = self._parse_cookie_content(f.read().strip())
            except Exception:
                pass

            restart_attempts = 3 if platform in ("douyin", "huya") else 1
            if platform == "douyin" and exit_reason == "upstream_forbidden":
                # 抖音 403 场景：每轮用“主链路+兜底链路”两次尝试即可
                restart_attempts = 2
            bad_routes = self._reconnect_bad_routes.setdefault(subscription_id, set())

            while reconnect_round < max_reconnect:
                if reconnect_round == 0:
                    delay = reconnect_delay_seconds
                else:
                    # 后续轮次加入抖动，避免多实例在固定 4 秒节奏上同频重连。
                    delay = random.uniform(3, 7)
                await asyncio.sleep(delay)

                reconnect_round += 1
                self._hls_reconnect_attempts[subscription_id] = reconnect_round
                logger.info(
                    f"录制异常，尝试自动重连（第 {reconnect_round}/{max_reconnect} 轮）: "
                    f"{subscription_id}, platform={platform}, reason={exit_reason}"
                )

                # FFmpeg 正常退出(code=0)时，先探测是否已下播。
                # 若已下播则直接完整收尾，避免先走 convert_to_mp4=False 导致漏转码。
                if reconnect_round == 1 and exit_code == 0:
                    try:
                        probe_room_info = await adapter.get_room_info(room_url, cookies=cookies)
                        if not probe_room_info.get("is_live", False):
                            logger.info(f"检测到FFmpeg正常退出且直播已下播，跳过重连并执行完整收尾: {subscription_id}")
                            await do_full_stop()
                            return
                    except Exception as probe_err:
                        logger.warning(f"正常退出后的下播预检查失败，继续重连流程: {subscription_id}, {probe_err}")

                # 重连阶段避免频繁转码和完成通知，降低抖动期的 I/O 压力与通知噪音
                await self._stop_auto_recording(subscription_id, convert_to_mp4=False, send_notification=False)
                # 清理历史残留的 recording 占位记录，避免重连失败后堆积 0B 条目。
                await self._cleanup_orphan_recording_records(
                    subscription_id,
                    keep_latest_running=True,
                    reason="before_reconnect_try"
                )

                restarted = False
                for start_try in range(restart_attempts):
                    selected_route_tag = None
                    try:
                        room_info = await adapter.get_room_info(room_url, cookies=cookies)
                        is_live = room_info.get("is_live", False)
                        if not is_live:
                            await do_full_stop()
                            return

                        anchor_name = room_info.get("anchor_name") or anchor_name
                        stream_kwargs = {"cookies": cookies}
                        if platform == "huya":
                            stream_kwargs.update({
                                "excluded_routes": sorted(bad_routes),
                                "reconnect_round": reconnect_round,
                                "restart_try": start_try,
                            })
                        stream_data = await adapter.get_stream_url(room_url, selected_quality, **stream_kwargs)
                        stream_url = (stream_data or {}).get("url")
                        if not stream_url:
                            raise RuntimeError("stream_url 为空")
                        if platform == "douyin":
                            # 抖音录制策略：先 FLV，再 m3u8 兜底
                            record_fallback_url = (stream_data or {}).get("record_fallback_url")
                            if start_try >= 1 and record_fallback_url:
                                stream_url = record_fallback_url
                                logger.info(
                                    f"[DouyinReconnect] 启用录制兜底链路: sub={subscription_id}, "
                                    f"try={start_try + 1}/{restart_attempts}, format=m3u8"
                                )
                        stream_format = (stream_data or {}).get("format")
                        source_cdn = (stream_data or {}).get("source_cdn")
                        if platform == "huya" and stream_format and source_cdn:
                            selected_route_tag = f"{source_cdn}:{stream_format}"

                        start_result = await self._start_auto_recording(
                            subscription_id, room_url, stream_url, anchor_name, platform,
                            quality=selected_quality,
                            segment_time=segment_time,
                            generate_subtitle=generate_subtitle,
                            danmu_enabled=danmu_enabled,
                            compat_mode=compat_mode,
                            is_merged_notification=False,
                            send_start_notification=False
                        )
                        # _start_auto_recording 内部吞异常，这里显式校验进程状态，避免假成功
                        await asyncio.sleep(1)
                        if not live_recorder.is_recording(subscription_id):
                            raise RuntimeError("重连后录制进程未存活")

                        restarted = True
                        break
                    except Exception as e:
                        if platform == "huya" and selected_route_tag:
                            bad_routes.add(selected_route_tag)
                            logger.info(
                                f"[HuyaReconnect] 标记失败线路: {selected_route_tag}, "
                                f"subscription={subscription_id}, failed_count={len(bad_routes)}"
                            )
                        logger.warning(
                            f"自动重连启动失败（第 {start_try + 1}/{restart_attempts} 次）: "
                            f"{subscription_id}, {e}"
                        )
                        if start_try < restart_attempts - 1:
                            await asyncio.sleep(3)

                if restarted:
                    await self._cleanup_orphan_recording_records(
                        subscription_id,
                        keep_latest_running=True,
                        reason="reconnect_success"
                    )
                    self._hls_reconnect_attempts.pop(subscription_id, None)
                    self._reconnect_bad_routes.pop(subscription_id, None)
                    live_recorder.clear_exit_context(subscription_id)
                    logger.info(f"录制异常重连成功: {subscription_id}")
                    return

                logger.warning(
                    f"自动重连第 {reconnect_round}/{max_reconnect} 轮失败: {subscription_id}, "
                    f"准备继续下一轮"
                )

            logger.error(f"自动重连耗尽，执行完整收尾: {subscription_id}")
            await self._cleanup_orphan_recording_records(
                subscription_id,
                keep_latest_running=True,
                reason="reconnect_exhausted"
            )
            self._reconnect_bad_routes.pop(subscription_id, None)
            await do_full_stop()
        finally:
            self._exit_handling_subscriptions.discard(subscription_id)

    async def _cleanup_orphan_recording_records(
        self,
        subscription_id: str,
        keep_latest_running: bool = True,
        reason: str = "unknown"
    ) -> int:
        """清理重连过程中遗留的 recording 记录，防止历史页面出现多个 0B 占位条目。"""
        if not self._db_session_factory:
            return 0

        try:
            from sql.models import LiveRecord
            from .recorder import live_recorder

            with self._db_session() as db:
                rows = db.query(LiveRecord).filter(
                    LiveRecord.subscription_id == subscription_id,
                    LiveRecord.status == "recording"
                ).order_by(LiveRecord.start_time.desc()).all()

                if not rows:
                    return 0

                keep_id = None
                if keep_latest_running and live_recorder.is_recording(subscription_id):
                    keep_id = rows[0].id

                cleaned = 0
                now = datetime.now()
                for row in rows:
                    if keep_id and row.id == keep_id:
                        continue

                    actual_size = 0
                    if row.file_path and os.path.exists(row.file_path):
                        try:
                            actual_size = os.path.getsize(row.file_path)
                        except Exception:
                            actual_size = 0

                    duration = 0
                    if row.start_time:
                        try:
                            duration = max(0, int((now - row.start_time).total_seconds()))
                        except Exception:
                            duration = 0

                    # 对短时且无有效内容的重连占位记录直接清理。
                    if actual_size <= 0 and duration <= 120:
                        if row.file_path and os.path.exists(row.file_path):
                            try:
                                if os.path.getsize(row.file_path) <= 0:
                                    os.remove(row.file_path)
                            except Exception as rm_err:
                                logger.warning(f"删除重连残留空文件失败: {row.file_path}, {rm_err}")
                        db.delete(row)
                    else:
                        row.status = "stopped"
                        row.end_time = now
                        row.file_size = max(int(row.file_size or 0), int(actual_size))
                        row.duration = max(int(row.duration or 0), int(duration))
                        if not row.error_message:
                            row.error_message = f"系统清理异常重连残留记录({reason})"
                    cleaned += 1

                if cleaned > 0:
                    db.commit()
                    logger.info(
                        f"已清理重连残留 recording 记录: {subscription_id}, count={cleaned}, reason={reason}"
                    )
                return cleaned
        except Exception as e:
            logger.error(f"清理重连残留 recording 记录失败: {subscription_id}, reason={reason}, err={e}")
            return 0

    
    async def _update_recording_status(
        self,
        subscription_id: str,
        is_recording: bool,
        file_path: Optional[str]
    ):
        """更新录制状态到数据库"""
        if not self._db_session_factory:
            return
        
        try:
            from sql.models import LiveSubscription
            
            with self._db_session() as db:
                subscription = db.query(LiveSubscription).filter(
                    LiveSubscription.id == subscription_id
                ).first()
                
                if subscription:
                    subscription.is_recording = "true" if is_recording else "false"
                    db.commit()

                    from routers.websocket import broadcast_live_status_update
                    await broadcast_live_status_update({
                        "id": subscription_id,
                        "is_recording": is_recording,
                        "recording_status": "recording" if is_recording else None
                    })
        except Exception as e:
            logger.error(f"更新录制状态失败: {e}")
    
    async def _create_record(
        self,
        subscription_id: str,
        stream_url: str,
        file_path: str,
        quality: str = "原画"
    ):
        """创建录制记录"""
        if not self._db_session_factory:
            return
        
        try:
            from sql.models import LiveRecord
            
            with self._db_session() as db:
                record = LiveRecord(
                    id=str(uuid.uuid4()),
                    subscription_id=subscription_id,
                    stream_url=stream_url,
                    quality=quality,
                    start_time=datetime.now(),
                    file_path=file_path,
                    file_name=os.path.basename(file_path),
                    format="ts",
                    status="recording"
                )
                db.add(record)
                db.commit()
        except Exception as e:
            logger.error(f"创建录制记录失败: {e}")
    
    async def _update_record(
        self,
        subscription_id: str,
        duration: int,
        file_size: int
    ):
        """更新录制记录"""
        if not self._db_session_factory:
            return
        
        try:
            from sql.models import LiveRecord
            
            with self._db_session() as db:
                record = db.query(LiveRecord).filter(
                    LiveRecord.subscription_id == subscription_id,
                    LiveRecord.status == "recording"
                ).order_by(LiveRecord.start_time.desc()).first()
                
                if record:
                    record.end_time = datetime.now()
                    record.duration = duration
                    record.file_size = file_size
                    record.status = "completed"
                    db.commit()
        except Exception as e:
            logger.error(f"更新录制记录失败: {e}")

    def _parse_cookie_content(self, cookie_str: Optional[str]) -> Optional[str]:
        """
        统一 Cookie 解析逻辑 (从适配器迁移至调度层)
        支持: 标准 HTTP Header 格式 和 Netscape 文件格式
        """
        if not cookie_str:
            return None
            
        cookie_str = cookie_str.strip()
        
        # 1. 检测 Netscape 格式
        if '\t' in cookie_str or cookie_str.startswith('#'):
            try:
                cookies = []
                for line in cookie_str.splitlines():
                    line = line.strip()
                    if not line or line.startswith('#'):
                        continue
                    
                    parts = line.split('\t')
                    if len(parts) >= 7:
                        name = parts[5]
                        value = parts[6]
                        cookies.append(f"{name}={value}")
                
                if cookies:
                    return "; ".join(cookies)
            except Exception:
                pass
        
        # 2. 处理标准格式: 去除换行和 "Cookie:" 前缀
        if cookie_str.lower().startswith("cookie:"):
            cookie_str = cookie_str[7:].strip()
            
        return cookie_str.replace('\n', '').replace('\r', '').strip()

    async def _sync_zombie_record(self, subscription_id: str):
        """同步僵尸记录（处理数据库显示录制中但实际没在录制的情况）"""
        if not self._db_session_factory:
            return
        
        try:
            from sql.models import LiveSubscription, LiveRecord
            with self._db_session() as db:
                sub = db.query(LiveSubscription).filter(LiveSubscription.id == subscription_id).first()
                should_save = False
                if sub and sub.is_recording == "true":
                    logger.warning(f"检测到订阅表僵尸状态，重置为未录制: {subscription_id}")
                    sub.is_recording = "false"
                    should_save = True
                
                zombie_record = db.query(LiveRecord).filter(
                    LiveRecord.subscription_id == subscription_id,
                    LiveRecord.status == "recording"
                ).first()
                
                if zombie_record:
                    logger.warning(f"检测到历史记录僵尸状态，标记为已停止: {zombie_record.id}")
                    zombie_record.status = "stopped"
                    zombie_record.error_message = "系统监测到录制异常中断"
                    
                    try:
                        latest_mtime = 0
                        total_size = 0
                        found_files = False
                        
                        if zombie_record.file_path:
                            file_dir = os.path.dirname(zombie_record.file_path)
                            file_name = os.path.basename(zombie_record.file_path)
                            file_prefix = os.path.splitext(file_name)[0]
                            
                            if os.path.exists(file_dir) and os.path.isdir(file_dir):
                                import glob
                                search_pattern = os.path.join(file_dir, f"{file_prefix}*")
                                
                                for f in glob.glob(search_pattern):
                                    if os.path.isfile(f):
                                        found_files = True
                                        f_size = os.path.getsize(f)
                                        f_mtime = os.path.getmtime(f)
                                        
                                        total_size += f_size
                                        if f_mtime > latest_mtime:
                                            latest_mtime = f_mtime

                        if found_files:
                            zombie_record.file_size = total_size
                            if latest_mtime > 0:
                                if zombie_record.start_time:
                                    try:
                                        start_ts = zombie_record.start_time.timestamp()
                                        zombie_record.duration = max(0, int(latest_mtime - start_ts))
                                    except Exception as e:
                                        logger.warning(f"计算时长失败: {e}")
                                
                                try:
                                    dt = datetime.fromtimestamp(latest_mtime)
                                    if zombie_record.start_time and zombie_record.start_time.tzinfo:
                                        zombie_record.end_time = dt.astimezone(zombie_record.start_time.tzinfo)
                                    else:
                                        zombie_record.end_time = dt
                                except:
                                    zombie_record.end_time = datetime.fromtimestamp(latest_mtime)
                        else:
                            zombie_record.end_time = datetime.now()
                            zombie_record.file_size = 0
                            
                    except Exception as meta_e:
                        logger.warning(f"无法完整更新记录 {zombie_record.id} 的元数据: {meta_e}")
                        zombie_record.end_time = datetime.now()
                    
                    should_save = True
                
                if should_save:
                    db.commit()
        except Exception as e:
            logger.error(f"同步僵尸记录失败: {subscription_id}, 错误: {e}")

    async def _cleanup_all_zombies(self):
        """系统启动时全局清理僵尸状态"""
        if not self._db_session_factory:
            return
        
        logger.info("🧹 正在进行全局录制状态巡检与清理...")
        try:
            from sql.models import LiveSubscription, LiveRecord
            with self._db_session() as db:
                db.query(LiveSubscription).filter(
                    LiveSubscription.is_recording == "true"
                ).update({"is_recording": "false"})
                
                zombie_records = db.query(LiveRecord).filter(
                    LiveRecord.status == "recording"
                ).all()
                
                for record in zombie_records:
                    logger.info(f"正在修复僵尸记录: {record.id} ({record.anchor_name})")
                    record.status = "stopped"
                    record.error_message = "系统重启或录制异常中断"
                    
                    try:
                        latest_mtime = 0
                        total_size = 0
                        found_files = False
                        
                        if record.file_path:
                            file_dir = os.path.dirname(record.file_path)
                            file_name = os.path.basename(record.file_path)
                            file_prefix = os.path.splitext(file_name)[0]
                            
                            if os.path.exists(file_dir) and os.path.isdir(file_dir):
                                import glob
                                search_pattern = os.path.join(file_dir, f"{file_prefix}*")
                                
                                for f in glob.glob(search_pattern):
                                    if os.path.isfile(f):
                                        found_files = True
                                        f_size = os.path.getsize(f)
                                        f_mtime = os.path.getmtime(f)
                                        
                                        total_size += f_size
                                        if f_mtime > latest_mtime:
                                            latest_mtime = f_mtime

                        if found_files:
                            record.file_size = total_size
                            if latest_mtime > 0:
                                if record.start_time:
                                    try:
                                        start_ts = record.start_time.timestamp()
                                        record.duration = max(0, int(latest_mtime - start_ts))
                                    except Exception as e:
                                        logger.warning(f"计算时长失败: {e}")
                                
                                try:
                                    dt = datetime.fromtimestamp(latest_mtime)
                                    if record.start_time and record.start_time.tzinfo:
                                        record.end_time = dt.astimezone(record.start_time.tzinfo)
                                    else:
                                        record.end_time = dt
                                except:
                                    record.end_time = datetime.fromtimestamp(latest_mtime)
                        else:
                            record.end_time = datetime.now()
                            record.file_size = 0
                            
                    except Exception as meta_e:
                        logger.warning(f"修复记录 {record.id} 时计算大小/时长失败: {meta_e}")
                        record.end_time = datetime.now()
                
                db.commit()
                if zombie_records:
                    logger.info(f"✅ 全局状态同步完成: 修正了 {len(zombie_records)} 条挂起记录")
        except Exception as e:
            logger.error(f"全局清理僵尸状态失败: {e}")


# 全局实例
live_scheduler = LiveScheduler()
