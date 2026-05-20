import asyncio
import logging
import random
from datetime import datetime, timedelta
from typing import Dict, Optional
from sqlalchemy.orm import Session
from sql.database_postgresql import get_db
from sql.models import Subscription, SubscriptionStatus
from .license import license_manager  # 导入 license_manager 实例
from .websocket import send_progress_update  # 订阅进度/结果推送

# 配置日志
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class SubscriptionScheduler:
    def __init__(self):
        self.running = False
        self.tasks: Dict[str, asyncio.Task] = {}
        self._check_task: Optional[asyncio.Task] = None
        self._housekeeping_task: Optional[asyncio.Task] = None
        # 全局并发限流，避免同时运行过多订阅检查任务占满数据库连接
        # 当前策略：连接池基础/溢出合计20，订阅检查并发设置为10，仍预留容量给API与下载任务
        self._semaphore = asyncio.Semaphore(10)
        # 抖音风控较敏感：对检查更新增加平台级串行与最小间隔节流
        self._platform_check_semaphores: Dict[str, asyncio.Semaphore] = {
            "douyin": asyncio.Semaphore(1),
            "douyin_collection": asyncio.Semaphore(1),
            "bilibili": asyncio.Semaphore(1),
            "bilibili_collection": asyncio.Semaphore(1),
            "xiaohongshu": asyncio.Semaphore(1),
            "instagram": asyncio.Semaphore(1),
        }
        self._platform_min_check_gap_seconds: Dict[str, float] = {
            "douyin": 8.0,
            "douyin_collection": 8.0,
            "bilibili": 3.0,
            "bilibili_collection": 3.0,
            "xiaohongshu": 6.0,
            "instagram": 60.0,
        }
        self._platform_last_check_started_at: Dict[str, float] = {}
        self._platform_gate_lock = asyncio.Lock()
        self._license_error_logged = False  # 新增：记录是否已打印过授权错误日志

    async def _apply_platform_check_pacing(self, platform: Optional[str]):
        """对指定平台应用最小检查间隔节流（无平台/未配置平台则跳过）。"""
        if not platform:
            return

        min_gap = self._platform_min_check_gap_seconds.get(platform)
        if not min_gap:
            return

        wait_seconds = 0.0
        async with self._platform_gate_lock:
            now_ts = datetime.now().timestamp()
            last_started_at = self._platform_last_check_started_at.get(platform)
            if last_started_at is not None:
                elapsed = now_ts - last_started_at
                wait_seconds = max(0.0, min_gap - elapsed)

        if wait_seconds > 0:
            if platform in {"douyin", "douyin_collection"}:
                anti_risk_tag = "DouyinAntiRisk"
            elif platform in {"bilibili", "bilibili_collection"}:
                anti_risk_tag = "BilibiliAntiRisk"
            elif platform in {"xiaohongshu"}:
                anti_risk_tag = "XhsAntiRisk"
            elif platform in {"instagram"}:
                anti_risk_tag = "InstagramAntiRisk"
            else:
                anti_risk_tag = "PlatformAntiRisk"
            logger.info(
                "[%s] 平台检查节流等待: platform=%s wait=%.2fs min_gap=%.2fs",
                anti_risk_tag,
                platform,
                wait_seconds,
                min_gap,
            )
            await asyncio.sleep(wait_seconds)

        async with self._platform_gate_lock:
            self._platform_last_check_started_at[platform] = datetime.now().timestamp()
        
    async def start(self):
        """启动调度器"""
        if self.running:
            return
            
        self.running = True
        self._check_task = asyncio.create_task(self._check_loop())
        # 轻量后台保洁：定期移除已完成/已取消的任务句柄
        async def _housekeeping_loop():
            while self.running:
                try:
                    await asyncio.sleep(180)  # 每3分钟清理一次
                    try:
                        # 移除已完成或已取消的任务引用
                        done_ids = [sid for sid, t in self.tasks.items() if t.done() or t.cancelled()]
                        for sid in done_ids:
                            self.tasks.pop(sid, None)
                    except Exception:
                        pass
                except asyncio.CancelledError:
                    break
                except Exception:
                    # 静默容错
                    pass
        self._housekeeping_task = asyncio.create_task(_housekeeping_loop())
        logger.debug("订阅调度器已启动")
        
    async def stop(self):
        """停止调度器"""
        self.running = False
        if self._check_task:
            self._check_task.cancel()
            try:
                await self._check_task
            except asyncio.CancelledError:
                pass
            self._check_task = None
        if self._housekeeping_task:
            self._housekeeping_task.cancel()
            self._housekeeping_task = None
            
        # 取消所有检查任务
        for task in self.tasks.values():
            task.cancel()
        await asyncio.gather(*self.tasks.values(), return_exceptions=True)
        self.tasks.clear()
        
        logger.info("订阅调度器已停止")
        
    async def _check_loop(self):
        """主检查循环"""
        while self.running:
            try:
                # 首先检查授权状态
                is_licensed = await license_manager.is_active_for("scheduler.check_loop")
                if not is_licensed:
                    if not self._license_error_logged:
                        if license_manager.permanently_expired:
                            logger.warning("授权已失效（终态），暂停订阅检查。在手动刷新授权前，将不再重复提示。")
                        else:
                            logger.warning("授权验证失败，暂时暂停订阅检查。")
                        self._license_error_logged = True
                    
                    await asyncio.sleep(60)
                    continue
                
                # 授权恢复，重置日志标记
                if self._license_error_logged:
                    logger.info("授权已恢复，继续执行订阅检查计划。")
                    self._license_error_logged = False

                # 获取所有需要检查的订阅
                db = next(get_db())
                try:
                    subscriptions = db.query(Subscription).filter(
                        Subscription.status != SubscriptionStatus.PAUSED.value
                    ).all()
                    
                    for subscription in subscriptions:
                        subscription_id = subscription.id
                        
                        # 如果任务已存在且正在运行，跳过
                        if subscription_id in self.tasks and not self.tasks[subscription_id].done():
                            continue
                        
                        # 如果正在同步视频，跳过检查更新（避免数据库连接冲突）
                        if subscription.sync_status == "syncing":
                            continue
                            
                        # 检查是否需要更新（含抖动）
                        last_check = subscription.last_check or datetime.min
                        update_interval = float(subscription.update_interval)
                        # 关闭抖动：直接使用配置的检查间隔
                        effective_interval = update_interval
                        if (datetime.now() - last_check) > timedelta(seconds=effective_interval):
                            # 创建新的检查任务（受并发限流保护）
                            task = asyncio.create_task(self._limited_check(subscription_id))
                            self.tasks[subscription_id] = task
                            
                finally:
                    try:
                        db.rollback()
                    except Exception:
                        pass
                    db.close()
                    
            except Exception as e:
                logger.error(f"检查循环出错: {str(e)}")
                
            # 等待一分钟后继续检查
            await asyncio.sleep(60)
            
    async def _check_subscription(self, subscription_id: str, cleanup_page: bool = True):
        """检查单个订阅的更新
        
        重要：此方法不再传递 db session 给 check_subscription_update，
        因为浏览器操作可能耗时很长（分钟级），期间持有 session 会导致
        idle-in-transaction timeout 问题。check_subscription_update 会
        自己管理 session 生命周期。
        """
        try:
            # 再次检查授权状态
            is_licensed = await license_manager.is_active_for(f"scheduler.check_subscription:{subscription_id}")
            if not is_licensed:
                logger.warning(f"授权已过期，跳过订阅[{subscription_id}]的检查")
                return

            # 延迟导入以避免与 subscribe.py 的循环依赖
            from .subscribe.sync import check_subscription_update  # noqa: WPS433
            from sql.database_postgresql import get_session
            
            # 使用独立的短生命周期 session 进行检测
            # check_subscription_update 内部会在需要时获取 session，
            # 在进行耗时浏览器操作前会提交/关闭 session
            db = get_session()
            try:
                platform = None
                sub = db.query(Subscription).filter(Subscription.id == subscription_id).first()
                if sub:
                    platform = sub.platform

                # 调用检测更新函数，通知功能已经集成在函数内部
                platform_semaphore = self._platform_check_semaphores.get(platform) if platform else None
                if platform_semaphore:
                    async with platform_semaphore:
                        await self._apply_platform_check_pacing(platform)
                        result = await check_subscription_update(subscription_id, db, cleanup_page=cleanup_page)
                else:
                    result = await check_subscription_update(subscription_id, db, cleanup_page=cleanup_page)
                logger.debug(f"自动检测订阅[{subscription_id}]完成: {result.get('message', '')}")
                # 统一向订阅 WebSocket 推送检测结果，让前端卡片显示“有/无更新”
                try:
                    await send_progress_update(subscription_id, {
                        "type": "check_result",
                        "status": "completed",
                        "has_update": result.get("has_update", False),
                        "new_videos_count": result.get("new_videos_count", 0),
                        "message": result.get("message", "")
                    })
                except Exception as push_err:
                    logger.warning(f"推送检测结果到WebSocket失败: {push_err}")
            except Exception as e:
                logger.error(f"检测订阅[{subscription_id}]时发生错误: {str(e)}")
                try:
                    db.rollback()
                except Exception:
                    pass
                raise
            finally:
                try:
                    # 确保 session 正确关闭，无论成功还是失败
                    db.rollback()  # 回滚任何未提交的事务
                except Exception:
                    pass
                try:
                    db.close()
                except Exception:
                    pass
                
        except Exception as e:
            logger.error(f"检查订阅[{subscription_id}]失败: {str(e)}")
            
        # 清理完成的任务
        if subscription_id in self.tasks:
            del self.tasks[subscription_id]

    async def _limited_check(self, subscription_id: str, cleanup_page: bool = True):
        """在全局并发限流下运行检查任务（带随机错峰延迟）"""
        # 随机错峰延迟：0-10秒，避免大量订阅同时触发导致资源集中
        delay = random.uniform(0, 10)
        await asyncio.sleep(delay)
        
        async with self._semaphore:
            await self._check_subscription(subscription_id, cleanup_page=cleanup_page)

# 创建全局调度器实例
scheduler = SubscriptionScheduler() 
