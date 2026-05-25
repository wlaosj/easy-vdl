import os
import shutil
import asyncio
from fastapi import APIRouter, HTTPException, Depends
from playwright.async_api import async_playwright
import logging
from datetime import datetime, timedelta
import re
from typing import List, Optional, Tuple, Dict, Any
import httpx
import time
import uuid

import random

# 配置日志 - 移除basicConfig，统一由supervisor管理
logger = logging.getLogger(__name__)

# 导入统一浏览器管理器
from .unified_browser_manager import unified_browser
# 导入API参数缓存管理器
from .api_params_cache import api_params_cache
# 导入认证
from routers.auth import get_current_user, require_license_api
from sql.models import User

router = APIRouter(
    prefix="/api/subscribe/douyin",
    tags=["douyin"],
    responses={404: {"description": "Not found"}}
)

def parse_publish_time(time_text: str) -> Tuple[Optional[datetime], str]:
    """解析抖音发布时间文本
    
    Args:
        time_text: 发布时间文本，如"10分钟前"、"1小时前"、"昨天"、"2023-10-01"
        
    Returns:
        (datetime, original_text): 解析后的时间和原始文本
    """
    try:
        now = datetime.now()
        
        # 处理"刚刚"
        if "刚刚" in time_text:
            return now, time_text
            
        # 处理"x分钟前"
        minutes_match = re.match(r"(\d+)\s*分钟前", time_text)
        if minutes_match:
            minutes = int(minutes_match.group(1))
            return now - timedelta(minutes=minutes), time_text
            
        # 处理"x小时前"
        hours_match = re.match(r"(\d+)\s*小时前", time_text)
        if hours_match:
            hours = int(hours_match.group(1))
            return now - timedelta(hours=hours), time_text
            
        # 处理"昨天"
        if "昨天" in time_text:
            yesterday = now - timedelta(days=1)
            time_parts = time_text.replace("昨天", "").strip()
            if time_parts:  # 如果有具体时间
                try:
                    hour, minute = map(int, time_parts.split(":"))
                    return yesterday.replace(hour=hour, minute=minute), time_text
                except:
                    return yesterday, time_text
            return yesterday, time_text
            
        # 处理"x天前"
        days_match = re.match(r"(\d+)\s*天前", time_text)
        if days_match:
            days = int(days_match.group(1))
            return now - timedelta(days=days), time_text
            
        # 处理具体日期 "2023-10-01"
        date_match = re.match(r"(\d{4})-(\d{1,2})-(\d{1,2})", time_text)
        if date_match:
            year, month, day = map(int, date_match.groups())
            return datetime(year, month, day), time_text
            
        # 处理"x月x日"格式
        date_match = re.match(r"(\d{1,2})月(\d{1,2})日", time_text)
        if date_match:
            month, day = map(int, date_match.groups())
            year = now.year
            # 如果月份大于当前月份，说明是去年的日期
            if month > now.month:
                year -= 1
            return datetime(year, month, day), time_text
            
        logger.warning(f"无法解析的时间格式: {time_text}")
        return None, time_text
        
    except Exception as e:
        logger.error(f"解析发布时间失败: {time_text} - {str(e)}")
        return None, time_text

class DouyinAPI:
    def __init__(self):
        # 使用统一浏览器管理器
        self._browser = unified_browser
        self._platform = "douyin"
        
        # 请求队列管理（保留抖音特有逻辑）
        self._request_queue = asyncio.Queue()
        self._worker_task = None
        self._max_concurrent_requests = 10  # 最多10个并发请求
        self._request_semaphore = asyncio.Semaphore(self._max_concurrent_requests)
        # 队列请求超时保护：避免单个请求卡死导致队列阻塞、任务计数无法回落
        self._request_timeout_seconds = 120
        self._future_wait_timeout_seconds = 180
        
        # API参数缓存：使用统一的api_params_cache
        
    def get_browser(self):
        """获取浏览器实例"""
        return self._browser.context if self._browser.context else None
    
    @property
    def page(self):
        """获取当前页面"""
        return self._browser._pages.get(self._platform)
    
    @property
    def context(self):
        """获取浏览器上下文"""
        return self._browser.context
        
    async def _update_activity(self):
        """更新最后活动时间"""
        await self._browser._update_activity()
                
    async def start_worker(self):
        """启动后台工作任务处理队列中的请求"""
        if self._worker_task is None or self._worker_task.done():
            self._worker_task = asyncio.create_task(self._process_queue())
            logger.info("抖音请求队列处理任务已启动")
        else:
            logger.debug("抖音请求队列处理任务已在运行")
            
    async def stop_worker(self):
        """停止后台工作任务"""
        if self._worker_task:
            logger.info("正在停止抖音请求队列处理任务...")
            self._worker_task.cancel()
            try:
                await self._worker_task
            except asyncio.CancelledError:
                pass
            self._worker_task = None
            logger.info("抖音请求队列处理任务已停止")
        else:
            logger.info("抖音请求队列处理任务未在运行")
            
    async def _process_queue(self):
        """处理请求队列的后台任务"""
        logger.debug("抖音请求队列处理任务开始运行")
        while True:
            try:
                # 获取队列中的请求
                logger.debug("等待抖音请求队列中的请求...")
                request_func, future = await self._request_queue.get()
                logger.debug("收到抖音请求，开始处理...")
                
                try:
                    # 使用信号量控制并发，最多10个并发请求
                    # 这里的并发是指HTTP请求的并发，所有请求共享同一个浏览器实例
                    # 主要消耗的是网络资源，不会显著增加系统负载
                    async with self._request_semaphore:
                        # 确保浏览器已初始化
                        if not self.page:
                            logger.info("抖音浏览器未初始化，正在初始化...")
                            success = await self.init_browser()
                            if not success:
                                raise Exception("浏览器初始化失败")
                            logger.info("抖音浏览器初始化完成")
                                
                        # 执行请求
                        logger.debug("执行抖音请求...")
                        result = await asyncio.wait_for(
                            request_func(),
                            timeout=self._request_timeout_seconds
                        )
                        future.set_result(result)
                        logger.debug("抖音请求执行完成")
                        
                except asyncio.TimeoutError:
                    timeout_msg = f"抖音请求执行超时（>{self._request_timeout_seconds}s）"
                    if not future.done():
                        future.set_exception(TimeoutError(timeout_msg))
                    logger.error(timeout_msg)
                except Exception as e:
                    if not future.done():
                        future.set_exception(e)
                    logger.error(f"抖音处理请求失败: {str(e)}")
                    
                finally:
                    self._request_queue.task_done()
                    logger.debug("抖音请求队列任务标记为完成")
                    
            except asyncio.CancelledError:
                logger.info("抖音请求队列处理任务被取消")
                break
            except Exception as e:
                logger.error(f"抖音处理请求队列时出错: {str(e)}")
                continue
                
    async def enqueue_request(self, request_func):
        """将请求添加到队列并更新活动时间"""
        logger.debug("抖音请求开始，更新活动时间...")
        await self._update_activity()  # 请求开始时更新
        try:
            future = asyncio.Future()
            # 移除重复的worker启动，避免重复创建进程
            logger.debug("将抖音请求添加到队列...")
            await self._request_queue.put((request_func, future))
            logger.debug("等待抖音请求执行结果...")
            result = await asyncio.wait_for(
                future,
                timeout=self._future_wait_timeout_seconds
            )
            logger.debug("抖音请求执行成功，更新活动时间...")
            await self._update_activity()  # 请求成功时更新
            return result
        except asyncio.TimeoutError:
            timeout_msg = (
                f"等待抖音请求结果超时（>{self._future_wait_timeout_seconds}s），"
                "请求已中止并将由后续调度重试"
            )
            logger.error(timeout_msg)
            await self._update_activity()
            raise TimeoutError(timeout_msg)
        except Exception as e:
            logger.error(f"抖音请求执行失败，更新活动时间: {str(e)}")
            await self._update_activity()  # 请求失败时也更新
            raise e

    async def _is_browser_context_valid(self):
        """检查浏览器上下文是否仍然有效"""
        try:
            if not self.context:
                return False
            
            # 尝试获取页面列表来验证上下文是否有效
            pages = self.context.pages
            return True
        except Exception as e:
            logger.warning(f"浏览器上下文有效性检查失败: {str(e)}")
            return False
    
    async def _ensure_browser_ready(self):
        """确保浏览器处于可用状态，如果不可用则重新初始化"""
        try:
            # 情况1：浏览器从未初始化（首次启动）
            if not self.context:
                logger.info("浏览器未初始化，正在初始化...")
                await self.init_browser()
                return True
            
            # 情况2：浏览器上下文曾经有效但现在失效（被关闭/崩溃）
            if not await self._is_browser_context_valid():
                logger.warning("浏览器上下文失效，准备重新初始化...")
                await self._force_reinitialize_browser()
                return True
            
            # 情况3：检查页面是否有效
            if self.page:
                try:
                    await self.page.evaluate("1")  # 简单测试
                    logger.debug("现有页面有效")
                    return True
                except Exception:
                    logger.warning("现有页面无效，准备重新初始化...")
                    await self._force_reinitialize_browser()
                    return True
            
            # 情况4：有上下文但没有页面，初始化页面
            logger.info("没有可用页面，初始化浏览器...")
            await self.init_browser()
            
            return True
        except Exception as e:
            logger.error(f"确保浏览器就绪失败: {str(e)}")
            # 如果失败，强制重新初始化
            await self._force_reinitialize_browser()
            return True
    
    async def _ensure_page_ready(self):
        """确保页面可用，如果页面已关闭则等待重新初始化完成"""
        max_retries = 3
        for attempt in range(max_retries):
            try:
                # 检查页面是否存在且有效
                if self.page and not self.page.is_closed():
                    # 尝试简单的页面操作来验证页面是否真正可用
                    await self.page.evaluate("1")
                    return True
                
                # 页面无效，等待一小段时间后重试（可能正在重新初始化）
                logger.warning(f"页面无效，等待重新初始化... (尝试 {attempt + 1}/{max_retries})")
                await asyncio.sleep(1.0)
                
                # 如果还是没有页面，主动触发初始化
                if not self.page:
                    await self.init_browser()
                    
            except Exception as e:
                logger.warning(f"页面检查失败 (尝试 {attempt + 1}/{max_retries}): {str(e)}")
                await asyncio.sleep(1.0)
        
        # 如果多次重试后仍然失败，抛出异常
        raise Exception("页面初始化失败，无法继续操作")
    
    async def _force_reinitialize_browser(self):
        """强制重新初始化浏览器（使用统一浏览器管理器）"""
        try:
            logger.info("开始强制重新初始化浏览器...")
            
            # 直接关闭标签页，不调用 close_browser()（避免退出登录模式）
            try:
                await self._browser.close_page(self._platform)
                logger.info(f"✅ {self._platform}标签页已关闭")
            except Exception as e:
                logger.debug(f"关闭{self._platform}标签页失败（可能不存在）: {str(e)}")
            
            # 等待一小段时间让资源释放
            await asyncio.sleep(0.5)
            
            # 重新初始化浏览器
            success = await self.init_browser()
            if success:
                logger.info("浏览器重新初始化成功")
            else:
                logger.error("浏览器重新初始化失败")
                raise Exception("浏览器重新初始化失败")
                
        except Exception as e:
            logger.error(f"强制重新初始化浏览器失败: {str(e)}")
            raise e

    async def _simulate_human_behavior(self):
        """模拟真实用户行为，降低验证触发概率"""
        try:
            page = self.page
            if not page:
                return
                
            # 检查页面和鼠标对象是否可用
            if not hasattr(page, 'mouse') or page.mouse is None:
                logger.debug("页面鼠标对象不可用，跳过模拟用户行为")
                return

            # 页面可能在异步期间被关闭，先做一次快速健康检查
            try:
                if page.is_closed():
                    return
            except Exception:
                return
                
            # 1. 随机等待（模拟页面加载思考时间）
            await asyncio.sleep(random.uniform(1.5, 3.5))
            
            # 2. 随机鼠标移动
            for _ in range(random.randint(2, 4)):
                if page is not self.page:
                    return
                x = random.randint(100, 1180)
                y = random.randint(100, 620)
                await page.mouse.move(x, y)
                await asyncio.sleep(random.uniform(0.3, 0.8))
            
            # 3. 模拟滚动行为
            scroll_count = random.randint(1, 3)
            for _ in range(scroll_count):
                if page is not self.page:
                    return
                # 随机滚动距离和方向
                scroll_y = random.randint(200, 800)
                if random.random() < 0.1:  # 10%概率向上滚动
                    scroll_y = -scroll_y
                    
                await page.evaluate(f"window.scrollBy(0, {scroll_y})")
                await asyncio.sleep(random.uniform(0.8, 2.0))
            
            # 4. 随机点击空白区域（模拟用户习惯）
            if random.random() < 0.3:  # 30%概率点击
                if page is not self.page:
                    return
                x = random.randint(200, 1080)
                y = random.randint(200, 520)
                await page.mouse.click(x, y)
                await asyncio.sleep(random.uniform(0.5, 1.0))
            
            # 5. 模拟页面停留时间
            stay_time = random.uniform(2.0, 5.0)
            logger.debug(f"模拟用户停留 {stay_time:.1f} 秒")
            await asyncio.sleep(stay_time)
            
        except Exception as e:
            msg = str(e).lower()
            # 页面在后台被关闭或替换属于可预期竞态，降级为 debug 避免告警刷屏
            if "nonetype" in msg or "closed" in msg or "target page, context or browser has been closed" in msg:
                logger.debug(f"模拟用户行为中断（页面已关闭/切换）: {str(e)}")
                return
            logger.warning(f"模拟用户行为失败: {str(e)}")
            # 行为模拟失败不影响主流程，只记录警告

    async def _simulate_light_behavior(self):
        """轻量的用户行为模拟（用于页面已在抖音时）"""
        try:
            page = self.page
            if not page:
                return
                
            # 1. 短暂等待
            await asyncio.sleep(random.uniform(0.5, 1.5))
            
            # 2. 轻微鼠标移动
            x = random.randint(300, 980)
            y = random.randint(200, 520)
            await page.mouse.move(x, y)
            await asyncio.sleep(random.uniform(0.2, 0.5))
            
            # 3. 偶尔轻微滚动
            if random.random() < 0.5:  # 50%概率滚动
                scroll_y = random.randint(100, 300)
                await page.evaluate(f"window.scrollBy(0, {scroll_y})")
                await asyncio.sleep(random.uniform(0.5, 1.0))
                
        except Exception as e:
            msg = str(e).lower()
            if "nonetype" in msg or "closed" in msg or "target page, context or browser has been closed" in msg:
                logger.debug(f"轻量行为模拟中断（页面已关闭/切换）: {str(e)}")
                return
            logger.warning(f"轻量行为模拟失败: {str(e)}")

    async def init_browser(self):
        """初始化浏览器（使用统一浏览器管理器）"""
        try:
            # 获取或创建抖音的标签页
            page = await self._browser.get_page(self._platform)
            if page:
                logger.info(f"✅ {self._platform}浏览器初始化成功")
                return True
            else:
                logger.error(f"❌ {self._platform}浏览器初始化失败")
                return False
        except Exception as e:
            logger.error(f"❌ 浏览器初始化失败: {str(e)}")
            return False

    async def close_browser(self):
        """关闭浏览器（使用统一浏览器管理器）"""
        try:
            # 关闭抖音的标签页
            await self._browser.close_page(self._platform)
            logger.info(f"✅ {self._platform}标签页已关闭")
        except Exception as e:
            logger.error(f"❌ 关闭{self._platform}标签页失败: {str(e)}")

    # 已删除 _clean_chrome_locks 方法，因为临时目录策略已解决锁文件问题

    def _copy_important_files(self, src_dir: str, dst_dir: str):
        """选择性复制重要的登录相关文件"""
        important_files = [
            'Cookies',
            'Cookies-journal',
            'Login Data',
            'Login Data-journal',
            'Local State',
            'Preferences',
            'Secure Preferences',
            'Web Data',
            'Web Data-journal',
            # 添加更多重要文件以确保登录状态完整
            'Network Action Predictor',
            'Network Action Predictor-journal',
            'TransportSecurity',
            'Trust Tokens',
            'Trust Tokens-journal',
            'Favicons',
            'Favicons-journal',
            'History',
            'History-journal',
            'Shortcuts',
            'Shortcuts-journal',
            'Top Sites',
            'Top Sites-journal',
            'Reporting and NEL',
            'Reporting and NEL-journal',
            'Safe Browsing Cookies',
            'Safe Browsing Cookies-journal',
            'ServerCertificate',
            'ServerCertificate-journal',
            'MediaDeviceSalts',
            'MediaDeviceSalts-journal',
            'passkey_enclave_state',
            'DIPS',
            'DIPS-wal',
            'BrowsingTopicsSiteData',
            'BrowsingTopicsSiteData-journal',
            'BrowsingTopicsState',
            'BookmarkMergedSurfaceOrdering',
            'Affiliation Database',
            'Affiliation Database-journal',
            'Account Web Data',
            'Account Web Data-journal',
            'Login Data For Account',
            'Login Data For Account-journal'
        ]
        
        important_dirs = [
            'Local Storage',
            'Session Storage',
            'IndexedDB',
            'Service Worker',
            # 添加更多重要目录
            'SharedStorage',
            'WebStorage',
            'Site Characteristics Database',
            'Shared Dictionary',
            'PersistentOriginTrials',
            'Feature Engagement Tracker',
            'Segmentation Platform',
            'ClientCertificates',
            'Extension State',
            'Extension Scripts',
            'Extension Rules',
            'Cache',
            'Code Cache',
            'GPUCache',
            'DawnWebGPUCache',
            'DawnGraphiteCache',
            'GraphiteDawnCache',
            'GrShaderCache',
            'ShaderCache',
            'VideoDecodeStats',
            'commerce_subscription_db',
            'discounts_db',
            'chrome_cart_db',
            'BudgetDatabase',
            'AutofillStrikeDatabase',
            'heavy_ad_intervention_opt_out.db',
            'heavy_ad_intervention_opt_out.db-journal',
            'first_party_sets.db',
            'first_party_sets.db-journal',
            'optimization_guide_hint_cache_store',
            'parcel_tracking_db',
            'shared_proto_db',
            'optimization_guide_model_store',
            'Safe Browsing',
            'segmentation_platform',
            'Variations'
        ]
        
        # 确保目标目录存在
        os.makedirs(dst_dir, exist_ok=True)
        
        # 复制重要文件
        for file_name in important_files:
            src_file = os.path.join(src_dir, file_name)
            dst_file = os.path.join(dst_dir, file_name)
            if os.path.exists(src_file):
                try:
                    shutil.copy2(src_file, dst_file)
                    logger.debug(f"已复制文件: {file_name}")
                except Exception as e:
                    logger.warning(f"复制文件失败 {file_name}: {str(e)}")
        
        # 复制重要目录
        for dir_name in important_dirs:
            src_subdir = os.path.join(src_dir, dir_name)
            dst_subdir = os.path.join(dst_dir, dir_name)
            if os.path.exists(src_subdir):
                try:
                    if os.path.exists(dst_subdir):
                        shutil.rmtree(dst_subdir)
                    shutil.copytree(src_subdir, dst_subdir, dirs_exist_ok=True)
                    logger.debug(f"已复制目录: {dir_name}")
                except Exception as e:
                    logger.warning(f"复制目录失败 {dir_name}: {str(e)}")

    async def clean_browser(self):
        """清理浏览器文件（统一浏览器管理器）"""
        try:
            # 先关闭浏览器
            await self.close_browser()
            
            # 获取统一浏览器的数据目录
            user_data_dir = self._browser.user_data_dir
            
            # 检查并删除用户数据目录
            if os.path.exists(user_data_dir):
                try:
                    shutil.rmtree(user_data_dir)
                    logger.info(f"已删除统一浏览器用户数据目录: {user_data_dir}")
                except Exception as e:
                    logger.error(f"删除用户数据目录失败: {str(e)}")
                    raise Exception(f"删除用户数据目录失败: {str(e)}")
            
            # 创建新的用户数据目录
            os.makedirs(user_data_dir, exist_ok=True)
            logger.info("已创建新的用户数据目录")
            
            return {"message": "浏览器文件清理成功"}
        except Exception as e:
            logger.error(f"清理浏览器文件失败: {str(e)}")
            raise Exception(f"清理浏览器文件失败: {str(e)}")

    async def login(self):
        """打开登录页面等待用户登录"""
        try:
            # 登录场景不更新活动时间，让前端管理生命周期
            # 确保浏览器已初始化并处于可用状态
            await self._ensure_browser_ready()
            
            # 确保页面可用（防止在重新初始化过程中使用已关闭的页面）
            try:
                await self._ensure_page_ready()
            except Exception as e:
                # 如果页面初始化失败，可能是用户关闭了浏览器
                logger.info("页面初始化失败，登录已取消")
                return {"message": "登录已取消", "cancelled": True}
                
            # 访问抖音精选页（更轻量，避免直播占用资源）
            try:
                await self.page.goto(
                    "https://www.douyin.com/jingxuan",
                    wait_until="domcontentloaded",
                    timeout=30000
                )
            except Exception as e:
                # 检查是否因为浏览器关闭而失败
                error_msg = str(e).lower()
                if "closed" in error_msg or "Target page, context or browser has been closed" in str(e):
                    logger.info("用户已关闭浏览器，登录已取消")
                    return {"message": "登录已取消", "cancelled": True}
                raise
            
            # 模拟真实用户行为，降低验证触发概率
            await self._simulate_human_behavior()
            
            # 等待页面稳定后检查页面状态
            await asyncio.sleep(2)
            
            # 再次检查页面是否仍然有效（可能是用户主动关闭）
            if not self.page:
                logger.info("用户已关闭浏览器，登录已取消")
                return {"message": "登录已取消", "cancelled": True}
            
            try:
                if self.page.is_closed():
                    logger.info("用户已关闭浏览器，登录已取消")
                    return {"message": "登录已取消", "cancelled": True}
            except Exception as e:
                if "closed" in str(e).lower() or "Target page, context or browser has been closed" in str(e):
                    logger.info("用户已关闭浏览器，登录已取消")
                    return {"message": "登录已取消", "cancelled": True}
            
            return {"message": "登录页面已打开"}
            
        except Exception as e:
            # 检查是否是因为浏览器关闭导致的错误
            error_msg = str(e).lower()
            if "closed" in error_msg or "Target page, context or browser has been closed" in str(e):
                logger.info("用户已关闭浏览器，登录已取消")
                return {"message": "登录已取消", "cancelled": True}
            
            # 真正的错误才记录为ERROR并抛出
            logger.error(f"启动登录失败: {str(e)}")
            raise HTTPException(status_code=500, detail="启动登录失败")

    async def get_user_videos(self, user_id: str, max_count: int = 20, max_cursor: int = 0) -> dict:
        """获取用户视频列表
        
        包含自动兜底机制：当API参数失效时自动刷新并重试
        
        Args:
            user_id: 用户ID
            max_count: 每页视频数量
            max_cursor: 分页游标
            
        Returns:
            dict: 包含视频列表的字典，获取失败时返回None
        """
        async def _get_videos(retry_on_auth_fail: bool = True):
            await self._update_activity()  # 操作开始时更新
            try:
                # 确保浏览器已初始化并处于可用状态
                await self._ensure_browser_ready()

                # 获取用户cookie
                cookies = await self.page.context.cookies()
                cookie_str = "; ".join([f"{c['name']}={c['value']}" for c in cookies])

                # 获取API所需的特殊参数（会自动确保页面已加载抖音网站）
                api_params = await self._get_api_params()

                # 构建请求头
                headers = {
                    "authority": "www.douyin.com",
                    "accept": "application/json, text/plain, */*",
                    "accept-language": "zh-CN,zh;q=0.9",
                    "cookie": cookie_str,
                    "referer": f"https://www.douyin.com/user/{user_id}",
                    "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
                }

                # 添加API特殊参数到headers
                if api_params:
                    headers.update(api_params)

                # 构建API URL参数（尽量贴近网页端抓包参数，提升兼容性）
                params = {
                    "sec_user_id": user_id,
                    "count": max_count,
                    "max_cursor": max_cursor,
                    "aid": "6383",
                    "device_platform": "webapp",
                    "channel": "channel_pc_web",
                    "cookie_enabled": "true",
                    "screen_width": 1920,
                    "screen_height": 1080,
                    "browser_language": "zh-CN",
                    "browser_platform": "Win32",
                    "browser_name": "Chrome",
                    "browser_version": "120.0.0.0",
                    "os_name": "Windows",
                    "os_version": "10",
                    "from_user_page": "1",
                    "need_time_list": "1",
                    "time_list_query": "0",
                    "publish_video_strategy_type": "2",
                    "support_h265": "1",
                    "support_dash": "0",
                    "pc_client_type": "1",
                    "version_name": "29.1.0",
                    "version_code": "290100",
                }
                # 将浏览器提取的签名参数放入 query（避免放在 header 导致无效）
                if api_params:
                    for key in ["msToken", "_signature", "XBogus", "ttwid"]:
                        if key in api_params and api_params[key]:
                            params[key] = api_params[key]
                
                url = "https://www.douyin.com/aweme/v1/web/aweme/post/"
                timeout = httpx.Timeout(20.0, connect=10.0)
                async with httpx.AsyncClient(timeout=timeout) as client:
                    response = await client.get(url, params=params, headers=headers)
                    
                    # 检查是否需要刷新参数重试
                    if response.status_code in [401, 403] and retry_on_auth_fail:
                        logger.warning(f"抖音API返回{response.status_code}，可能是参数失效，尝试刷新参数并重试")
                        await self._get_api_params(force_refresh=True)
                        return await _get_videos(retry_on_auth_fail=False)
                    
                    if response.status_code != 200:
                        logger.warning(f"获取视频列表失败: HTTP {response.status_code}，将在下次检测时重试")
                        return None
                        
                    data = response.json()
                    if not data:
                        logger.debug("API返回空响应")
                        return None
                    aweme_list = data.get('aweme_list') or []
                    logger.debug(f"获取到 {len(aweme_list)} 个视频")
                    logger.debug(f"分页信息: has_more={data.get('has_more')}, max_cursor={data.get('max_cursor')}")
                    await self._update_activity()  # 操作成功时更新
                    return data
            except Exception as e:
                await self._update_activity()  # 操作失败时也更新
                logger.warning(f"获取视频列表暂时失败，将在下次检测时重试")
                logger.debug(f"详细错误: {str(e)}")
                return None

        return await self.enqueue_request(_get_videos)
            
    async def _ensure_douyin_loaded(self):
        """确保页面已加载抖音网站（轻量方式，带重试）"""
        max_retries = 3
        for attempt in range(max_retries):
            try:
                # 确保浏览器就绪
                await self._ensure_browser_ready()
                
                # 确保页面可用（防止在重新初始化过程中使用已关闭的页面）
                await self._ensure_page_ready()
                
                current_url = self.page.url
                if not current_url or "douyin.com" not in current_url:
                    logger.info(f"页面未加载抖音网站，正在访问精选页... (尝试 {attempt + 1}/{max_retries})")
                    await self.page.goto(
                        "https://www.douyin.com/jingxuan",
                        wait_until="domcontentloaded",
                        timeout=30000
                    )
                    # 模拟真实用户行为，降低验证触发概率
                    await self._simulate_human_behavior()
                else:
                    # 即使页面已经在抖音，也偶尔模拟一些用户行为
                    if random.random() < 0.3:  # 30%概率进行轻量行为模拟
                        await self._simulate_light_behavior()
                return  # 成功则返回
            except Exception as e:
                logger.warning(f"确保抖音网站加载失败 (尝试 {attempt + 1}/{max_retries}): {str(e)}")
                if attempt == max_retries - 1:  # 最后一次尝试
                    logger.error(f"确保抖音网站加载最终失败: {str(e)}")
                    raise e
                await asyncio.sleep(2)  # 重试前等待

    async def _get_api_params(self, force_refresh: bool = False) -> dict:
        """获取抖音 API 请求所需的特殊参数
        
        使用api_params_cache统一管理
        
        Args:
            force_refresh: 是否强制刷新缓存
        """
        # 1. 尝试从缓存获取
        if not force_refresh:
            cached = api_params_cache.get(self._platform)
            if cached:
                logger.debug("抖音API参数缓存有效")
                return cached

        # 2. 缓存未命中或强制刷新，从浏览器提取
        try:
            # 确保页面已加载抖音网站
            await self._ensure_douyin_loaded()
            
            # 注入获取参数的 JS 代码
            script = """
            () => {
                const params = {};
                // 获取 X-Bogus 签名
                if (window.byted_acrawler && window.byted_acrawler.sign) {
                    params.XBogus = window.byted_acrawler.sign({ url: window.location.href });
                }
                // 获取 msToken
                params.msToken = localStorage.getItem('msToken') || '';
                // 获取 _signature
                if (window.byted_acrawler && window.byted_acrawler.getSignature) {
                    params._signature = window.byted_acrawler.getSignature();
                }
                // 获取 csrf token
                const matches = document.cookie.match(/ttwid=([^;]+)/);
                if (matches) {
                    params.ttwid = matches[1];
                }
                return params;
            }
            """
            params = await self.page.evaluate(script)
            
            # 3. 保存到统一缓存管理器
            if params:
                api_params_cache.set(self._platform, params)
                logger.info("抖音API参数已缓存")
                
            return params
        except Exception as e:
            logger.error(f"获取API参数失败: {str(e)}")
            # 如果获取失败，尝试使用旧缓存（降级处理）
            cached = api_params_cache.get(self._platform)
            if cached:
                logger.warning("获取新参数失败，使用旧缓存")
                return cached
            return {}

    def _empty_user_stats(self, user_id: str) -> dict:
        return {
            "user_id": user_id,
            "nickname": "",
            "follower_count": 0,
            "following_count": 0,
            "video_count": 0,
            "like_count": 0,
            "signature": "",
            "avatar_url": ""
        }

    @staticmethod
    def _parse_douyin_count(value: Any) -> int:
        """解析抖音页面中的统计数字，如 11.6万、495.6万。"""
        if value is None:
            return 0
        text = str(value).strip().replace(",", "")
        if not text:
            return 0
        match = re.search(r"([\d.]+)\s*([万亿]?)", text)
        if not match:
            return 0
        try:
            number = float(match.group(1))
        except ValueError:
            return 0
        unit = match.group(2)
        if unit == "万":
            number *= 10000
        elif unit == "亿":
            number *= 100000000
        return int(number)

    async def _get_user_stats_from_dom(self, user_id: str) -> dict:
        """从用户主页 DOM 提取资料，作为 profile API 失效时的兜底。"""
        await self._ensure_browser_ready()
        await self._ensure_page_ready()

        profile_url = f"https://www.douyin.com/user/{user_id}"
        logger.info(f"尝试从抖音用户主页DOM提取用户信息: {profile_url}")

        await self.page.goto(profile_url, wait_until="domcontentloaded", timeout=30000)
        await asyncio.sleep(6)

        script = """
        () => {
            const result = {};
            const getText = (el) => (el && (el.innerText || el.textContent) || '').trim();

            const nicknameEl = document.querySelector('h1');
            result.nickname = getText(nicknameEl);

            const images = Array.from(document.querySelectorAll('img')).map((img) => {
                const rect = img.getBoundingClientRect();
                return {
                    el: img,
                    src: img.src || '',
                    alt: img.alt || '',
                    width: rect.width || img.naturalWidth || 0,
                    height: rect.height || img.naturalHeight || 0,
                    x: rect.x || 0,
                    y: rect.y || 0
                };
            });
            const exactAvatarAlt = result.nickname ? `${result.nickname}头像` : '';
            const avatarInfo = images.find((img) => exactAvatarAlt && img.alt === exactAvatarAlt)
                || images.find((img) => result.nickname && img.alt.includes(result.nickname) && img.alt.includes('头像'))
                || images.find((img) => {
                    const looksLikeAvatar = img.src.includes('aweme-avatar') || img.src.includes('avatar');
                    const profileHeaderSize = img.width >= 80 && img.height >= 80;
                    const profileHeaderPosition = img.x < window.innerWidth * 0.45 && img.y < 260;
                    return looksLikeAvatar && profileHeaderSize && profileHeaderPosition;
                });
            const avatarImg = avatarInfo ? avatarInfo.el : null;
            result.avatar_url = avatarImg ? avatarImg.src : '';

            const bodyText = document.body ? document.body.innerText || '' : '';
            const followingMatch = bodyText.match(/关注\\s*\\n?\\s*([\\d.,万亿]+)/);
            const followerMatch = bodyText.match(/粉丝\\s*\\n?\\s*([\\d.,万亿]+)/);
            const likeMatch = bodyText.match(/获赞\\s*\\n?\\s*([\\d.,万亿]+)/);
            const worksMatch = bodyText.match(/作品\\s*\\n?\\s*([\\d.,万亿]+)/);
            result.following_count_text = followingMatch ? followingMatch[1] : '';
            result.follower_count_text = followerMatch ? followerMatch[1] : '';
            result.like_count_text = likeMatch ? likeMatch[1] : '';
            result.video_count_text = worksMatch ? worksMatch[1] : '';

            const metaDesc = document.querySelector('meta[name="description"]');
            result.meta_description = metaDesc ? metaDesc.content || '' : '';

            const candidates = Array.from(document.querySelectorAll('p, div, span'))
                .map((el) => getText(el))
                .filter((text) => text && text.length > 3 && text.length < 200)
                .filter((text) => !/(精选|推荐|搜索|关注|朋友|我的|直播|放映厅|短剧|小游戏|下载|作品|粉丝|获赞|标签|保存|登录|扫码)/.test(text));
            result.signature = candidates[0] || '';
            return result;
        }
        """

        user_data = await self.page.evaluate(script)
        nickname = (user_data or {}).get("nickname", "")
        if not nickname:
            raise Exception("无法从抖音用户主页DOM提取昵称")

        avatar_url = (user_data or {}).get("avatar_url", "")
        logger.info(f"成功从抖音用户主页DOM提取用户信息: nickname={nickname}, avatar={'有' if avatar_url else '无'}")

        return {
            "user_id": user_id,
            "nickname": nickname,
            "follower_count": self._parse_douyin_count(user_data.get("follower_count_text")),
            "following_count": self._parse_douyin_count(user_data.get("following_count_text")),
            "video_count": self._parse_douyin_count(user_data.get("video_count_text")),
            "like_count": self._parse_douyin_count(user_data.get("like_count_text")),
            "signature": user_data.get("signature", ""),
            "avatar_url": avatar_url
        }

    async def get_user_stats(self, user_id: str) -> dict:
        """获取用户统计信息
        
        包含自动兜底机制：当API参数失效时自动刷新并重试
        
        Args:
            user_id: 用户ID
            
        Returns:
            dict: 包含用户统计信息的字典，获取失败时返回None
        """
        async def _request(retry_on_auth_fail: bool = True):
            await self._update_activity()  # 操作开始时更新
            try:
                # 确保浏览器已初始化并处于可用状态
                await self._ensure_browser_ready()

                # 确保页面已加载抖音网站（通过_get_api_params中的_ensure_douyin_loaded处理）

                # 获取用户cookie
                cookies = await self.page.context.cookies()
                cookie_str = "; ".join([f"{c['name']}={c['value']}" for c in cookies])

                # 获取API所需的特殊参数
                api_params = await self._get_api_params()

                # 构建请求头
                headers = {
                    "authority": "www.douyin.com",
                    "accept": "application/json, text/plain, */*",
                    "accept-language": "zh-CN,zh;q=0.9",
                    "cookie": cookie_str,
                    "referer": f"https://www.douyin.com/user/{user_id}",
                    "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
                }
                
                # 添加API特殊参数到headers
                if api_params:
                    headers.update(api_params)

                # 构建API URL参数
                params = {
                    "sec_user_id": user_id,
                    "aid": "6383",
                    "device_platform": "web",
                    "cookie_enabled": "true"
                }

                # 发送请求
                async with httpx.AsyncClient(timeout=10.0) as client:
                    response = await client.get(
                        "https://www.douyin.com/aweme/v1/web/user/profile/other/",
                        params=params,
                        headers=headers
                    )
                    
                    # 检查是否需要刷新参数重试
                    if response.status_code in [401, 403] and retry_on_auth_fail:
                        logger.warning(f"抖音API返回{response.status_code}，可能是参数失效，尝试刷新参数并重试")
                        # 强制刷新参数
                        await self._get_api_params(force_refresh=True)
                        # 重试一次，不再重复重试
                        return await _request(retry_on_auth_fail=False)
                    
                    if not response.content:
                        logger.warning(
                            f"抖音用户资料API返回空响应，改用主页DOM兜底: user_id={user_id}, "
                            f"status={response.status_code}, content_type={response.headers.get('content-type')}"
                        )
                        return await self._get_user_stats_from_dom(user_id)

                    data = response.json()
                    user_info = data.get("user", {})
                    if not user_info.get("nickname"):
                        logger.warning(f"抖音用户资料API未返回昵称，改用主页DOM兜底: user_id={user_id}")
                        return await self._get_user_stats_from_dom(user_id)
                    
                    await self._update_activity()  # 操作成功时更新
                    return {
                        "user_id": user_id,
                        "nickname": user_info.get("nickname", ""),
                        "follower_count": user_info.get("follower_count", 0),
                        "following_count": user_info.get("following_count", 0),
                        "video_count": user_info.get("aweme_count", 0),
                        "like_count": user_info.get("total_favorited", 0),
                        "signature": user_info.get("signature", ""),
                        "avatar_url": user_info.get("avatar_larger", {}).get("url_list", [""])[0]
                    }
            except Exception as e:
                await self._update_activity()  # 操作失败时也更新
                logger.error(f"获取用户统计信息失败: {str(e)}")
                try:
                    return await self._get_user_stats_from_dom(user_id)
                except Exception as dom_error:
                    logger.error(f"从抖音用户主页DOM提取用户信息失败: {str(dom_error)}")
                    return self._empty_user_stats(user_id)
        return await self.enqueue_request(_request)

    async def get_real_user_id(self, url: str) -> str:
        """获取重定向后的真实用户ID
        
        Args:
            url: 用户主页链接，可能包含 'self' 或短链接
            
        Returns:
            str: 真实的用户ID
        """
        try:
            # 确保浏览器已初始化并处于可用状态
            await self._ensure_browser_ready()
            
            # 确保页面可用（防止在重新初始化过程中使用已关闭的页面）
            await self._ensure_page_ready()

            # 访问链接
            logger.info(f"正在访问链接: {url}")
            await self.page.goto(url, wait_until="domcontentloaded")
            
            # 等待重定向完成
            await asyncio.sleep(3)
            
            # 获取当前URL
            current_url = self.page.url
            logger.info(f"重定向后的URL: {current_url}")
            
            # 从URL中提取用户ID
            user_id_match = re.search(r"/user/([^/?]+)", current_url)
            if user_id_match and user_id_match.group(1) != "self":
                user_id = user_id_match.group(1)
                logger.info(f"从重定向URL中提取到用户ID: {user_id}")
                return user_id
            
            # 如果URL中没有，尝试从页面元素获取
            logger.info("尝试从页面元素获取用户ID...")
            user_id = await self.page.evaluate("""
                () => {
                    // 尝试从页面数据中获取
                    const userInfo = document.querySelector('[data-e2e="user-info"]');
                    if (userInfo) {
                        return userInfo.getAttribute('data-user-id');
                    }
                    
                    // 尝试从其他可能的选择器获取
                    const secUserId = document.querySelector('meta[name="sec-user-id"]');
                    if (secUserId) {
                        return secUserId.getAttribute('content');
                    }
                    
                    // 尝试从页面脚本中获取
                    const scripts = document.querySelectorAll('script');
                    for (const script of scripts) {
                        if (script.textContent && script.textContent.includes('sec_user_id')) {
                            const match = script.textContent.match(/sec_user_id["']?\s*:\s*["']([^"']+)["']/);
                            if (match) {
                                return match[1];
                            }
                        }
                    }
                    
                    return null;
                }
            """)
            
            if user_id:
                logger.info(f"从页面元素获取到用户ID: {user_id}")
                return user_id
            
            # 如果还是无法获取，尝试等待更长时间并重新检查
            logger.info("等待更长时间后重新检查...")
            await asyncio.sleep(2)
            
            # 再次获取当前URL
            current_url = self.page.url
            logger.info(f"再次检查重定向后的URL: {current_url}")
            
            user_id_match = re.search(r"/user/([^/?]+)", current_url)
            if user_id_match and user_id_match.group(1) != "self":
                user_id = user_id_match.group(1)
                logger.info(f"重新检查后获取到用户ID: {user_id}")
                return user_id
                
            raise Exception("无法获取真实用户ID，请检查链接是否有效")
            
        except Exception as e:
            logger.error(f"获取真实用户ID失败: {str(e)}")
            raise HTTPException(status_code=400, detail=f"获取用户ID失败: {str(e)}")

    async def get_current_user_info(self) -> dict:
        """获取当前登录用户信息
        
        Returns:
            dict: 包含用户信息的字典，获取失败时返回None
        """
        try:
            # 确保浏览器已初始化并处于可用状态
            await self._ensure_browser_ready()
            
            # 确保页面可用（防止在重新初始化过程中使用已关闭的页面）
            await self._ensure_page_ready()

            # 方法1: 尝试从页面中提取用户信息
            logger.info("从页面中获取登录用户信息...")
            
            # 导航到用户主页
            try:
                await self.page.goto("https://www.douyin.com/user/self", wait_until="domcontentloaded", timeout=15000)
                await asyncio.sleep(5)  # 增加等待时间，确保页面内容完全加载（特别是SPA异步内容）
            except Exception as nav_error:
                logger.warning(f"导航到用户主页失败: {nav_error}")
            
            # 从页面DOM中直接提取用户信息（不依赖API）
            script = """
            () => {
                const result = {};
                
                // 提取昵称
                const nicknameEl = document.querySelector('h1');
                if (nicknameEl) {
                    result.nickname = nicknameEl.textContent.trim();
                }
                
                // 提取关注/粉丝/获赞数
                const statsContainers = document.querySelectorAll('div');
                for (const container of statsContainers) {
                    const text = container.textContent;
                    
                    // 提取关注数
                    const followingMatch = text.match(/关注[\\s\\S]*?(\\d+)/);
                    if (followingMatch && !result.following_count) {
                        result.following_count = parseInt(followingMatch[1]);
                    }
                    
                    // 提取粉丝数
                    const followerMatch = text.match(/粉丝[\\s\\S]*?(\\d+)/);
                    if (followerMatch && !result.follower_count) {
                        result.follower_count = parseInt(followerMatch[1]);
                    }
                    
                    // 提取获赞数
                    const likeMatch = text.match(/获赞[\\s\\S]*?(\\d+)/);
                    if (likeMatch && !result.like_count) {
                        result.like_count = parseInt(likeMatch[1]);
                    }
                }
                
                // 提取抖音号（只保留纯数字部分，过滤掉后面的年龄/地区等冗余文本）
                const paragraphs = document.querySelectorAll('p');
                for (const p of paragraphs) {
                    if (p.textContent.includes('抖音号：')) {
                        const idText = p.textContent.replace('抖音号：', '').trim();
                        const idMatch = idText.match(/^(\d+)/);
                        result.douyin_id = idMatch ? idMatch[1] : idText;
                        break;
                    }
                }
                
                // 提取签名
                const allDivs = document.querySelectorAll('div');
                for (const div of allDivs) {
                    const text = div.textContent.trim();
                    if (text && text.length > 3 && text.length < 200 && 
                        !text.includes('抖音号') && !text.includes('关注') && 
                        !text.includes('粉丝') && !text.includes('获赞') &&
                        !text.includes('作品') && !text.includes('喜欢') &&
                        !text.includes('下载') && !text.includes('保存') &&
                        !text.includes('读屏') && !text.includes('标签')) {
                        result.signature = text;
                        break;
                    }
                }
                
                // 提取头像
                const avatarImg = document.querySelector('img[alt*="头像"]');
                if (avatarImg) {
                    result.avatar_url = avatarImg.src;
                }
                
                // 提取作品数
                const tabs = document.querySelectorAll('[role="tab"]');
                for (const tab of tabs) {
                    if (tab.textContent.includes('作品')) {
                        const match = tab.textContent.match(/(\\d+)/);
                        if (match) {
                            result.video_count = parseInt(match[1]);
                            break;
                        }
                    }
                }
                
                return result;
            }
            """
            
            user_data = await self.page.evaluate(script)
            
            if not user_data or not user_data.get("nickname"):
                raise Exception("无法从页面中提取用户信息")
            
            logger.info(f"成功从DOM提取用户信息: {user_data.get('nickname')}")
            
            # 返回标准格式的用户信息
            # 对数值字段加合理性上限：防止 DOM 解析误匹配到用户 ID 等超大数字导致 DB INTEGER 溢出
            return {
                "user_id": user_data.get("douyin_id", ""),
                "nickname": user_data.get("nickname", ""),
                "follower_count": min(user_data.get("follower_count", 0) or 0, 100_000_000),
                "following_count": min(user_data.get("following_count", 0) or 0, 1_000_000),
                "video_count": min(user_data.get("video_count", 0) or 0, 1_000_000),
                "like_count": min(user_data.get("like_count", 0) or 0, 10_000_000_000),
                "signature": user_data.get("signature", ""),
                "avatar_url": user_data.get("avatar_url", "")
            }
            
            raise Exception("无法获取用户信息，请确保已登录抖音账号")

        except Exception as e:
            # 降级为 WARNING 级别，因为这不是致命错误（不影响视频检查）
            logger.warning(f"获取当前登录用户信息失败: {str(e)}（将使用已有缓存信息）")
            return None  # 返回 None 而不是空字典，便于调用方判断是否成功

    async def _sign_url(self, url: str) -> str:
        """使用浏览器环境对特定URL进行签名 (获取XBogus)"""
        try:
            # 确保有页面可用
            if not self.page:
                return ""
            
            # 注入脚本计算签名
            # 注意：window.byted_acrawler.sign 返回的通常是字符串或包含 XBogus 的对象
            # 根据 _get_api_params 的经验，sign 方法返回的是对象或字符串，我们需要确认
            # 但通常 sign({url: ...}) 返回的是 XBogus 字符串
            script = f"""
            () => {{
                try {{
                    if (window.byted_acrawler && window.byted_acrawler.sign) {{
                        return window.byted_acrawler.sign({{ url: "{url}" }});
                    }}
                }} catch (e) {{
                    return "";
                }}
                return "";
            }}
            """
            result = await self.page.evaluate(script)
            return result
        except Exception as e:
            logger.warning(f"URL签名失败: {str(e)}")
            return ""

    async def get_my_sec_user_id(self) -> str:
        """获取当前登录用户的 sec_user_id (优先DOM提取，失败则尝试拦截API)"""
        try:
            await self._ensure_browser_ready()
            
            # 方法1: 如果当前页面已经是个人主页，且URL包含长ID，直接提取
            # 说明：这里先检查一次当前URL，后面在跳转到 /user/self 之后还会再检查一次
            current_url = self.page.url
            if "/user/MS4" in current_url:
                match = re.search(r"/user/(MS4[^/?]+)", current_url)
                if match:
                    uid = match.group(1)
                    masked_uid = f"{uid[:6]}***{uid[-6:]}" if len(uid) > 12 else "***"
                    logger.info(f"从当前URL提取到用户ID: {masked_uid}")
                    return match.group(1)

            logger.info("正在获取当前用户ID...")
            
            # 定义一个用于捕获 ID 的变量 (用于API拦截兜底)
            captured_uid = {"val": None}
            
            # 定义响应拦截处理函数
            async def handle_response(response):
                if captured_uid["val"]: return
                # 监听获取个人信息的接口
                if "/aweme/v1/web/user/profile/self/" in response.url or "/aweme/v1/web/query/user/" in response.url:
                    try:
                        if "application/json" in response.headers.get("content-type", ""):
                            data = await response.json()
                            # API返回的通常是下划线 sec_uid
                            sec_uid = data.get("user", {}).get("sec_uid") or data.get("user_info", {}).get("sec_uid")
                            if sec_uid:
                                captured_uid["val"] = sec_uid
                    except:
                        pass

            # 注册监听器
            self.page.on("response", handle_response)
            
            try:
                # 访问 /user/self
                # 增加等待，确保页面加载完成（包括可能的重定向）
                await self.page.goto("https://www.douyin.com/user/self", wait_until="domcontentloaded", timeout=15000)
                
                # 方法1.1: 再次从地址栏检查是否已经跳转为带 MS4 的真实主页URL
                try:
                    current_url = self.page.url
                    if "/user/MS4" in current_url:
                        match = re.search(r"/user/(MS4[^/?]+)", current_url)
                        if match:
                            uid = match.group(1)
                            masked_uid = f"{uid[:6]}***{uid[-6:]}" if len(uid) > 12 else "***"
                            logger.info(f"从重定向后的URL提取到用户ID: {masked_uid}")
                            return match.group(1)
                except Exception as e:
                    # 地址栏解析失败不影响后续DOM/API方案，只记录调试日志
                    logger.debug(f"从URL提取用户ID时发生非致命错误: {str(e)}")
                
                # 方法2: 优先尝试从 RENDER_DATA 提取 (修正了键名大小写 secUid)
                script = """
                () => {
                    try {
                        const renderData = document.getElementById('RENDER_DATA');
                        if (renderData) {
                          const json = JSON.parse(decodeURIComponent(renderData.textContent));
                          // 注意：RENDER_DATA 中通常使用驼峰 secUid
                          if (json.app?.user?.info?.secUid) return json.app.user.info.secUid;
                          // 兼容可能的下划线情况
                          if (json.app?.user?.info?.sec_uid) return json.app.user.info.sec_uid;
                        }
                        
                        // 尝试从全局 SSR_DATA 提取
                        if (window._SSR_DATA?.data?.loaderData?.['user-profile']?.user?.secUid) {
                            return window._SSR_DATA.data.loaderData['user-profile'].user.secUid;
                        }
                    } catch(e) {}
                    return null;
                }
                """
                dom_uid = await self.page.evaluate(script)
                if dom_uid:
                     masked_uid = f"{dom_uid[:6]}***{dom_uid[-6:]}" if len(dom_uid) > 12 else "***"
                     logger.info(f"从页面 RENDER_DATA 提取到用户ID: {masked_uid}")
                     return dom_uid

                # 如果 DOM 没拿到，等待 API 拦截结果
                for _ in range(6):
                    if captured_uid["val"]:
                        uid = captured_uid["val"]
                        masked_uid = f"{uid[:6]}***{uid[-6:]}" if len(uid) > 12 else "***"
                        logger.info(f"从API拦截中获取到用户ID: {masked_uid}")
                        return captured_uid["val"]
                    await asyncio.sleep(0.5)
                
            finally:
                self.page.remove_listener("response", handle_response)
            
            # 方法3: 最后的尝试 (正则暴力匹配)
            content = await self.page.content()
            match = re.search(r'MS4wLjABAAAA[a-zA-Z0-9_\-]{30,}', content)
            match = re.search(r'MS4wLjABAAAA[a-zA-Z0-9_\-]{30,}', content)
            if match:
                 uid = match.group(0)
                 masked_uid = f"{uid[:6]}***{uid[-6:]}" if len(uid) > 12 else "***"
                 logger.info(f"通过正则暴力匹配提取到用户ID: {masked_uid}")
                 return match.group(0)

            raise Exception("无法提取当前用户ID，请确认已登录")
            
        except Exception as e:
            logger.error(f"获取当前用户ID失败: {str(e)}")
            return ""

    async def get_favorite_videos(
        self,
        max_count: int = 20,
        max_cursor: int = 0,
        progress_callback=None,
        batch_callback=None,
        sec_user_id: Optional[str] = None,
    ) -> dict:
        """获取当前登录用户的点赞视频列表 (API方式)
        
        Args:
            max_count: 每次获取的最大数量
            max_cursor: 分页游标，0表示首次加载
            progress_callback: 进度回调函数
            batch_callback: 批次处理回调函数 async def(videos: List[dict])
            sec_user_id: 可选，直接指定当前账号的 sec_user_id（优先使用，解析失败时可兜底）
            
        Returns:
            dict: 包含视频列表的字典
        """
        async def _get_favorites(
            retry_on_auth_fail: bool = True,
            retry_on_secuid_fail: bool = True,
            sec_uid_override: Optional[str] = None
        ):
            await self._update_activity()
            try:
                # 1. 基础环境准备。
                await self._ensure_browser_ready()
                
                # 2. 获取当前用户 sec_user_id (点赞API必须)
                resolved_sec_uid = sec_uid_override or (sec_user_id or "")
                if resolved_sec_uid:
                    masked_id = f"{resolved_sec_uid[:6]}***{resolved_sec_uid[-6:]}" if len(resolved_sec_uid) > 12 else "***"
                    logger.info(f"使用缓存sec_user_id: {masked_id}，准备请求点赞API...")
                else:
                    resolved_sec_uid = await self.get_my_sec_user_id()
                if not resolved_sec_uid:
                    logger.error("未获取到当前用户信息，无法获取点赞列表")
                    return None
                
                masked_id = f"{resolved_sec_uid[:6]}***{resolved_sec_uid[-6:]}" if len(resolved_sec_uid) > 12 else "***"
                logger.info(f"获取到当前用户ID: {masked_id}，准备请求点赞API...")

                # 3. 准备API参数
                cookies = await self.page.context.cookies()
                cookie_str = "; ".join([f"{c['name']}={c['value']}" for c in cookies])
                
                # 基础 headers (Cookie必须)
                headers = {
                    "authority": "www.douyin.com",
                    "accept": "application/json, text/plain, */*",
                    "accept-language": "zh-CN,zh;q=0.9",
                    "cookie": cookie_str,
                    "referer": f"https://www.douyin.com/user/{resolved_sec_uid}?showTab=like",
                    "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
                }

                # API 基础 URL
                base_url = "https://www.douyin.com/aweme/v1/web/aweme/favorite/"
                
                all_videos = []
                current_cursor = max_cursor 
                has_more = True
                target_count = max_count
                
                # 如果 max_cursor=1，表示同步模式，尽可能多获取（直到 has_more 为 False）
                # 移除硬编码上限，根据API返回的 has_more 标志来决定是否继续
                is_sync_mode = (max_cursor == 1)
                if is_sync_mode:
                    current_cursor = 0
                    target_count = 100000  # 同步模式设置一个很大的上限作为兜底（防止极端情况），实际依赖 has_more 标志
                
                page_count = 0
                max_pages = 20000  # 最大页数限制（调大上限以覆盖更多分页数据），防止死循环
                callback_failure_streak = 0
                callback_failure_total = 0
                # 回调连续失败保护阈值：避免持续异常导致任务无限空跑
                max_callback_failure_streak = 8
                
                async with httpx.AsyncClient(timeout=15.0) as client:
                    # 同步模式下：只根据 has_more 判断；非同步模式：同时检查数量限制
                    # 同时检查最大页数限制，防止死循环
                    while has_more and (is_sync_mode or len(all_videos) < target_count) and page_count < max_pages:
                        page_count += 1
                        # 4. 构造单次请求参数
                        params = {
                            "device_platform": "webapp",
                            "aid": "6383",
                            "channel": "channel_pc_web",
                            "sec_user_id": resolved_sec_uid,
                            "count": "20", # 建议单页20，过大容易风控
                            "max_cursor": str(current_cursor),
                            "cookie_enabled": "true",
                            "platform": "PC",
                            "downlink": "10",
                            # 添加版本参数模拟真实环境
                            "version_code": "170400",
                            "version_name": "17.4.0",
                        }
                        
                        # 5. 生成签名 (针对带参数的 URL)
                        # 先把 params 拼成 query string
                        query_string = "&".join([f"{k}={v}" for k, v in params.items()])
                        full_url_for_sign = f"{base_url}?{query_string}"
                        
                        # 调用浏览器生成 XBogus
                        xbogus = await self._sign_url(full_url_for_sign)
                        if xbogus:
                            params["XBogus"] = xbogus
                            
                        # 这里的 msToken 最好也从浏览器拿一下最新的，如果没有就用缓存的
                        cached_params = api_params_cache.get(self._platform) or {}
                        if cached_params.get("msToken"):
                             params["msToken"] = cached_params["msToken"]

                        # 6. 发送请求
                        logger.debug(f"请求点赞API (页数: {page_count}, cursor: {current_cursor})...")
                        response = await client.get(base_url, params=params, headers=headers)
                        
                        if response.status_code != 200:
                            logger.warning(f"API请求失败: {response.status_code}")
                            # 如果使用了缓存 sec_user_id，且出现鉴权问题，尝试重新解析 sec_user_id 并重试一次
                            if response.status_code in (401, 403) and sec_user_id and retry_on_secuid_fail:
                                logger.warning("检测到可能的 sec_user_id/登录态不一致，尝试重新解析 sec_user_id 并重试")
                                fresh_sec_uid = await self.get_my_sec_user_id()
                                if fresh_sec_uid:
                                    return await _get_favorites(
                                        retry_on_auth_fail=retry_on_auth_fail,
                                        retry_on_secuid_fail=False,
                                        sec_uid_override=fresh_sec_uid
                                    )
                            # 如果是 403/401 且允许重试，可以尝试刷新 token (暂时略过复杂重试逻辑)
                            break
                            
                        data = response.json()
                        aweme_list = data.get("aweme_list", []) or []
                        
                        if not aweme_list:
                             logger.info("没有获取到更多视频")
                             has_more = False
                             break
                             
                        # 处理视频数据格式
                        batch_items = []
                        for item in aweme_list:
                             # 转换为标准格式
                             video_info = {
                                "aweme_id": item.get("aweme_id"),
                                "desc": item.get("desc", ""),
                                "create_time": item.get("create_time"),
                                "video": {
                                    "cover": item.get("video", {}).get("cover", {}),
                                    "play_addr": item.get("video", {}).get("play_addr", {}),
                                },
                                "statistics": item.get("statistics", {}),
                                "author": item.get("author", {}),
                                # 保留images字段以便区分图集
                                "images": item.get("images")
                             }
                             all_videos.append(video_info)
                             batch_items.append(video_info)
                             
                        # 触发批次回调
                        if batch_callback and batch_items:
                            try:
                                await batch_callback(batch_items)
                                callback_failure_streak = 0
                            except Exception as be:
                                callback_failure_total += 1
                                callback_failure_streak += 1
                                logger.warning(
                                    f"⚠️ 批次回调异常，跳过当前批次并继续: {be} "
                                    f"(连续失败: {callback_failure_streak}/{max_callback_failure_streak}, "
                                    f"累计失败: {callback_failure_total})"
                                )
                                # 仅在连续多次失败时触发保护性终止，避免无限空跑
                                if callback_failure_streak >= max_callback_failure_streak:
                                    logger.error(
                                        f"⚠️ 批次回调连续失败达到阈值({max_callback_failure_streak})，"
                                        "触发保护性终止抓取任务"
                                    )
                                    has_more = False
                                    break

                        # 更新进度
                        if progress_callback:
                             try:
                                 await progress_callback(len(all_videos))
                             except:
                                 pass
                        
                        # 检查分页
                        has_more = bool(data.get("has_more"))
                        current_cursor = data.get("max_cursor", 0)
                        
                        if not is_sync_mode and len(all_videos) >= max_count:
                             break
                        
                        # 智能动态延时防风控策略（优化版）
                        # 平衡风控安全性和同步效率，减少不必要的等待时间
                        
                        # 1. 基础随机间隔 (2~4秒)，更接近真实浏览翻页速度
                        delay = random.uniform(2.0, 4.0)
                        
                        # 2. 阶梯式长短休息机制（优化后）
                        if page_count % 300 == 0:
                            # 每300页(约6000视频) -> "超级休息" (30~60秒)
                            # 模拟长时间中断，如去吃饭、长时间离开
                            # 优化：减少触发频率和延时时间，提高效率
                            extra_delay = random.uniform(30, 60)
                            logger.info(f"已连续请求300页，触发防风控超级休息: {extra_delay:.1f}秒...")
                            delay += extra_delay
                        elif page_count % 100 == 0:
                             # 每100页(约2000视频) -> "大休息" (10~20秒)
                             # 模拟用户长时间停留，或切换应用
                             # 优化：减少触发频率和延时时间
                             extra_delay = random.uniform(10, 20)
                             logger.info(f"已连续请求100页，触发防风控大休息: {extra_delay:.1f}秒...")
                             delay += extra_delay
                        elif page_count % 20 == 0:
                             # 每20页(约400视频) -> "小休息" (2~5秒)
                             # 模拟用户稍作停顿
                             # 优化：减少触发频率和延时时间
                             delay += random.uniform(2.0, 5.0)
                        
                        await asyncio.sleep(delay)
                
                logger.info(f"API获取点赞视频完成，共 {len(all_videos)} 个视频")
                await self._update_activity()
                
                return {
                    "aweme_list": all_videos,
                    "max_cursor": current_cursor,
                    "has_more": has_more
                }

            except Exception as e:
                await self._update_activity()
                logger.error(f"API获取点赞列表失败: {str(e)}")
                return None
        
        return await self.enqueue_request(_get_favorites)

    async def parse_user_profile(self, url: str) -> dict:
        """解析用户主页链接或用户ID
        
        Args:
            url: 用户主页链接（支持标准链接和短链接）或用户ID
            
        Returns:
            dict: 包含用户信息的字典
        """
        try:
            # 检查是否是短链接
            if "v.douyin.com" in url:
                logger.info(f"检测到短链接: {url}")
                # 使用现有的重定向处理逻辑获取真实用户ID
                user_id = await self.get_real_user_id(url)
                logger.info(f"从短链接获取到用户ID: {user_id}")
                return await self.get_user_stats(user_id)
            
            # 处理标准链接
            user_id_match = re.search(r"/user/([^/?]+)", url)
            if user_id_match:
                user_id = user_id_match.group(1)
                # 不支持self链接
                if user_id == "self":
                    raise Exception("不支持 /user/self 格式的链接，请使用包含用户ID的标准主页链接")
                logger.info(f"从链接中提取到用户ID: {user_id}")
                return await self.get_user_stats(user_id)
            
            # 如果既不是短链接，也不是标准链接，则假设是直接输入的用户ID
            # 抖音用户ID通常是长字符串（如 MS4wLjABAAAA...）
            if url and not url.startswith("http") and len(url) > 5:
                logger.info(f"检测到直接输入的用户ID: {url}")
                return await self.get_user_stats(url)
            
            # 如果都不匹配，抛出错误
            raise Exception("无法识别输入格式，请使用：1) 标准主页链接（如：https://www.douyin.com/user/xxx）2) 短链接（如：https://v.douyin.com/xxx）3) 用户ID（如：MS4wLjABAAAA...）")
            
        except Exception as e:
            logger.error(f"解析用户主页链接失败: {str(e)}")
            raise HTTPException(status_code=400, detail=str(e))



douyin_api = DouyinAPI()

@router.on_event("startup")
async def startup_event():
    """FastAPI启动时初始化抖音API"""
    logger.info("DouyinAPI实例ID: %s", id(douyin_api))
    try:
        # 🟢 浏览器采用懒加载，worker已在main.py中启动
        # 统一浏览器管理器会自动管理清理任务
        logger.info("抖音API初始化完成（浏览器采用懒加载，统一管理）")
    except Exception as e:
        logger.error(f"抖音API启动失败: {str(e)}")
        raise

@router.on_event("shutdown")
async def shutdown_event():
    """FastAPI关闭时清理DouyinAPI"""
    await douyin_api.stop_worker()
    await douyin_api.close_browser()
    logger.info("DouyinAPI已清理")

@router.post("/login")
async def init_login(current_user: User = Depends(get_current_user)):
    """启动抖音登录流程"""
    logger.info(f"Douyin登录 - 使用实例ID: {id(douyin_api)}")
    try:
        result = await douyin_api.login()
        # 检查是否是用户取消登录
        if result.get("cancelled"):
            logger.info("抖音登录已被用户取消")
            return result  # 返回200状态码，表示正常操作
        return result
    except Exception as e:
        logger.error(f"抖音登录流程启动失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"启动登录失败: {str(e)}")

@router.post("/close")
@require_license_api
async def close_browser():
    """关闭抖音浏览器（用于登录窗口关闭）"""
    logger.info(f"Douyin关闭浏览器 - 使用实例ID: {id(douyin_api)}")
    await douyin_api.close_browser()
    return {"message": "浏览器已关闭"} 

@router.post("/clean")
async def clean_browser(current_user: User = Depends(get_current_user)):
    """清理浏览器文件"""
    try:
        return await douyin_api.clean_browser()
    except Exception as e:
        logger.error(f"清理浏览器文件失败: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e)) 

@router.post("/health_check")
async def browser_health_check():
    """检查浏览器健康状态，如果异常则尝试恢复"""
    try:
        logger.info("开始浏览器健康检查...")
        
        # 检查浏览器状态
        is_valid = await douyin_api._is_browser_context_valid()
        if not is_valid:
            logger.warning("浏览器状态异常，尝试恢复...")
            await douyin_api._force_reinitialize_browser()
            return {"status": "recovered", "message": "浏览器已恢复"}
        else:
            logger.info("浏览器状态正常")
            return {"status": "healthy", "message": "浏览器状态正常"}
            
    except Exception as e:
        logger.error(f"浏览器健康检查失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"健康检查失败: {str(e)}")

@router.post("/force_reinit")
async def force_reinitialize_browser(current_user: User = Depends(get_current_user)):
    """强制重新初始化浏览器"""
    try:
        logger.info("强制重新初始化浏览器...")
        await douyin_api._force_reinitialize_browser()
        return {"message": "浏览器重新初始化成功"}
    except Exception as e:
        logger.error(f"强制重新初始化浏览器失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"重新初始化失败: {str(e)}")

# 合集相关API方法
async def parse_collection_url(url: str) -> dict:
    """解析合集URL或合集ID获取合集信息
    
    Args:
        url: 合集URL（支持多种格式）或合集ID
        
    Returns:
        dict: 包含合集ID、标题等信息的字典
    """
    try:
        # 支持多种URL格式
        # https://v.douyin.com/pvYIoo83Ey4/
        # https://www.douyin.com/collection/7407257750834513958
        # 或直接输入合集ID：7407257750834513958
        
        collection_id = None
        collection_title = None
        
        # 处理短链接格式
        if "v.douyin.com" in url:
            # 需要先解析短链接获取真实URL
            async with httpx.AsyncClient() as client:
                response = await client.get(url, follow_redirects=True)
                real_url = str(response.url)
                # 从真实URL中提取合集ID
                match = re.search(r'/collection/(\d+)', real_url)
                if match:
                    collection_id = match.group(1)
        elif "/collection/" in url:
            # 直接处理完整URL
            match = re.search(r'/collection/(\d+)', url)
            if match:
                collection_id = match.group(1)
        else:
            # 如果既不是短链接，也不是标准URL，则假设是直接输入的合集ID
            # 抖音合集ID通常是纯数字（如 7407257750834513958）
            if url and url.isdigit() and len(url) > 10:
                collection_id = url
                logger.info(f"检测到直接输入的合集ID: {collection_id}")
            else:
                # 尝试从URL路径中提取数字作为合集ID（排除查询参数避免误匹配）
                # 先去除查询参数部分
                url_path = url.split('?')[0] if '?' in url else url
                match = re.search(r'(\d{10,})', url_path)
                if match:
                    collection_id = match.group(1)
                    logger.info(f"从输入中提取到合集ID: {collection_id}")
        
        if not collection_id:
            raise ValueError("无法从输入中提取合集ID，请使用：1) 标准合集链接（如：https://www.douyin.com/collection/7407257750834513958）2) 短链接（如：https://v.douyin.com/xxx）3) 合集ID（如：7407257750834513958）")
        
        return {
            "collection_id": collection_id,
            "collection_title": collection_title,
            "url": url if url.startswith("http") else f"https://www.douyin.com/collection/{collection_id}"
        }
        
    except Exception as e:
        logger.error(f"解析合集URL失败: {str(e)}")
        raise ValueError(f"解析合集URL失败: {str(e)}")

async def get_collection_videos(collection_id: str, cursor: int = 0, count: int = 20, with_meta: bool = False) -> dict:
    """获取合集视频列表（基于官方Web API，稳定且可分页）
    
    包含自动兜底机制：当API参数失效时自动刷新并重试

    Args:
        collection_id: 合集ID（mix_id）
        cursor: 起始游标
        count: 每页数量

    Returns:
        dict: { collection_id, collection_title, videos: [...], total_count, has_more, next_cursor }
    """
    try:
        async def _get_collection_videos(retry_on_auth_fail: bool = True):
            # 记录活跃，确保浏览器上下文存活
            await douyin_api._update_activity()

            # 1) 确保浏览器与页面上下文就绪（用于获取 Cookie 与签名参数）
            await douyin_api._ensure_browser_ready()

            # 2) 组装 Cookie 与 API 签名参数
            cookies = await douyin_api.page.context.cookies()
            cookie_str = "; ".join([f"{c['name']}={c['value']}" for c in cookies])
            api_params = await douyin_api._get_api_params()  # 可能返回需要追加的签名头或参数

            # 3) 请求头
            collection_url = f"https://www.douyin.com/collection/{collection_id}"
            headers = {
                "authority": "www-hj.douyin.com",
                "accept": "application/json, text/plain, */*",
                "accept-language": "zh-CN,zh;q=0.9",
                "cookie": cookie_str,
                "referer": collection_url,
                "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            }
            if isinstance(api_params, dict):
                headers.update({k: v for k, v in api_params.items() if isinstance(v, str)})

            # 4) 分页抓取
            api_url = "https://www-hj.douyin.com/aweme/v1/web/mix/aweme/"
            videos: list[dict] = []
            has_more = True
            next_cursor = cursor
            total_count_reported = None
            collection_title = None
            collection_cover = None

            # 防止无限循环，加页数与数量保护
            # 同步模式下提高上限，单次调用最多500页（500页 * 20视频/页 = 10000视频）
            # 注意：同步时外部会循环调用此函数，所以单次调用的上限不影响整体同步
            max_pages = 500  # 提高上限，支持大型合集
            pages = 0

            async with httpx.AsyncClient(timeout=30.0) as client:
                while has_more and pages < max_pages and len(videos) < count:
                    params = {
                        "device_platform": "webapp",
                        "aid": "6383",
                        "channel": "channel_pc_web",
                        "cursor": str(next_cursor),
                        "count": str(min(20, max(1, count))),
                        "mix_id": collection_id,
                        # 以下参数与页面环境一致可提升成功率
                        "update_version_code": "170400",
                        "pc_client_type": "1",
                        "version_code": "170400",
                        "version_name": "17.4.0",
                    }
                    # 将可能需要的签名类参数追加（如果 _get_api_params 提供）
                    if isinstance(api_params, dict):
                        for k in ("msToken", "verifyFp", "fp", "a_bogus", "webid", "uifid"):
                            if k in api_params and api_params[k]:
                                params[k] = api_params[k]

                    # 添加调试日志：打印API请求信息
                    logger.debug(f"抖音合集API请求 - URL: {api_url}")
                    logger.debug(f"抖音合集API请求 - 参数: {params}")
                    
                    resp = await client.get(api_url, params=params, headers=headers)
                    logger.debug(f"抖音合集API响应 - 状态码: {resp.status_code}")
                    
                    # 检查是否需要刷新参数重试
                    if resp.status_code in [401, 403] and retry_on_auth_fail:
                        logger.warning(f"抖音合集API返回{resp.status_code}，可能是参数失效，尝试刷新参数并重试")
                        await douyin_api._get_api_params(force_refresh=True)
                        return await _get_collection_videos(retry_on_auth_fail=False)
                    
                    if resp.status_code != 200:
                        raise HTTPException(status_code=502, detail=f"合集接口响应异常: {resp.status_code}")
                    data = resp.json()

                    # 优先尝试从接口中提取合集标题（不同版本字段名可能不同）
                    if 'collection_title' not in locals() or not collection_title:
                        try:
                            collection_title = (
                                (data.get('mix_info') or {}).get('mix_name')
                                or data.get('mix_name')
                                or (data.get('mix') or {}).get('name')
                            )
                        except Exception:
                            pass

                    # 如果接口返回总数，记录下来（不同版本字段名可能不同）
                    if total_count_reported is None:
                        for key in ("total", "mix_aweme_total", "aweme_total"):
                            if isinstance(data.get(key), int):
                                total_count_reported = int(data.get(key))
                                break

                    aweme_list = data.get("aweme_list", []) or []
                    
                    # 添加调试日志：打印API返回的原始数据结构
                    logger.debug(f"抖音合集API返回数据 - 合集ID: {collection_id}, 视频数量: {len(aweme_list)}")
                    logger.debug(f"API响应顶层字段: {list(data.keys())}")
                    
                    if aweme_list:
                        logger.debug(f"首个视频原始数据结构: {aweme_list[0]}")
                        # 打印所有可能的标题相关字段
                        first_aweme = aweme_list[0]
                        title_fields = {
                            'desc': first_aweme.get('desc'),
                            'title': first_aweme.get('title'),
                            'mix_info': first_aweme.get('mix_info'),
                            'mix': first_aweme.get('mix'),
                            'series_info': first_aweme.get('series_info'),
                            'collection': first_aweme.get('collection'),
                            'aweme_id': first_aweme.get('aweme_id')
                        }
                        logger.debug(f"首个视频标题相关字段: {title_fields}")
                        
                        # 如果有多个视频，也打印第二个视频的标题字段用于对比
                        if len(aweme_list) > 1:
                            second_aweme = aweme_list[1]
                            second_title_fields = {
                                'desc': second_aweme.get('desc'),
                                'title': second_aweme.get('title'),
                                'mix_info': second_aweme.get('mix_info'),
                                'mix': second_aweme.get('mix'),
                                'series_info': second_aweme.get('series_info'),
                                'collection': second_aweme.get('collection'),
                                'aweme_id': second_aweme.get('aweme_id')
                            }
                            logger.debug(f"第二个视频标题相关字段: {second_title_fields}")
                    
                    # 若顶层未取到标题，则尝试从列表项的 mix 信息兜底一次
                    if (not collection_title) and aweme_list:
                        try:
                            for _item in aweme_list:
                                maybe_title = (
                                    ((_item.get("mix_info") or {}).get("mix_name"))
                                    or ((_item.get("mix") or {}).get("name"))
                                )
                                if maybe_title:
                                    collection_title = maybe_title
                                    break
                        except Exception:
                            pass
                    # 标准化为前端/保存所需结构
                    for aweme in aweme_list:
                        aweme_id = aweme.get("aweme_id")
                        if not aweme_id:
                            continue
                        
                        # 尝试从多个字段获取完整标题，优先获取包含"第X集"前缀的完整标题
                        desc = None
                        
                        # 1. 首先尝试从desc字段获取
                        desc = aweme.get("desc")
                        logger.debug(f"视频 {aweme_id} - 原始desc字段: {desc}")
                        
                        # 2. 如果desc不包含"第X集"前缀，尝试从其他字段获取完整标题
                        if not desc or not ("第" in desc and "集" in desc):
                            logger.debug(f"视频 {aweme_id} - desc字段不包含'第X集'前缀，尝试其他字段")
                            
                            # 尝试从mix_info相关字段获取
                            mix_info = aweme.get("mix_info") or {}
                            mix_name = mix_info.get("mix_name")
                            logger.debug(f"视频 {aweme_id} - mix_info.mix_name: {mix_name}")
                            if mix_name and ("第" in mix_name and "集" in mix_name):
                                desc = mix_name
                                logger.debug(f"视频 {aweme_id} - 从mix_info.mix_name获取到完整标题: {desc}")
                            # 尝试从mix字段获取
                            elif aweme.get("mix", {}).get("name"):
                                mix_name = aweme.get("mix", {}).get("name")
                                logger.debug(f"视频 {aweme_id} - mix.name: {mix_name}")
                                if mix_name and ("第" in mix_name and "集" in mix_name):
                                    desc = mix_name
                                    logger.debug(f"视频 {aweme_id} - 从mix.name获取到完整标题: {desc}")
                            # 尝试从其他可能的标题字段获取
                            elif aweme.get("title"):
                                title = aweme.get("title")
                                logger.debug(f"视频 {aweme_id} - title字段: {title}")
                                if title and ("第" in title and "集" in title):
                                    desc = title
                                    logger.debug(f"视频 {aweme_id} - 从title字段获取到完整标题: {desc}")
                            # 尝试从series相关字段获取
                            elif aweme.get("series_info", {}).get("title"):
                                series_title = aweme.get("series_info", {}).get("title")
                                logger.debug(f"视频 {aweme_id} - series_info.title: {series_title}")
                                if series_title and ("第" in series_title and "集" in series_title):
                                    desc = series_title
                                    logger.debug(f"视频 {aweme_id} - 从series_info.title获取到完整标题: {desc}")
                        else:
                            logger.debug(f"视频 {aweme_id} - desc字段已包含完整标题: {desc}")
                        
                        # 3. 如果仍然没有获取到完整标题，尝试根据集数信息生成完整标题
                        if not desc or not ("第" in desc and "集" in desc):
                            # 从mix_info中获取集数信息
                            mix_info = aweme.get("mix_info") or {}
                            statis = mix_info.get("statis", {})
                            current_episode = statis.get("current_episode")
                            
                            if current_episode and desc:
                                # 生成包含集数的完整标题
                                desc = f"第{current_episode}集 | {desc}"
                                logger.debug(f"视频 {aweme_id} - 根据集数信息生成完整标题: {desc}")
                            elif current_episode:
                                # 如果没有desc但有集数信息，生成基本标题
                                desc = f"第{current_episode}集 | 合集视频"
                                logger.debug(f"视频 {aweme_id} - 根据集数信息生成基本标题: {desc}")
                        
                        # 4. 如果仍然没有获取到标题，使用默认值
                        if not desc:
                            desc = f"合集视频 {aweme_id}"
                            logger.warning(f"视频 {aweme_id} - 未能获取到标题，使用默认值: {desc}")
                        
                        logger.debug(f"视频 {aweme_id} - 最终标题: {desc}")
                        cover_url = (
                            (aweme.get("video") or {}).get("cover") or {}
                        ).get("url_list", [None])[0]
                        # 发布时间（秒级时间戳）
                        publish_ts = None
                        try:
                            if aweme.get("create_time") is not None:
                                publish_ts = int(aweme.get("create_time"))
                        except Exception:
                            publish_ts = None
                        # 播放量（可选）
                        play_count = None
                        try:
                            stats = aweme.get("statistics") or {}
                            if stats.get("play_count") is not None:
                                play_count = int(stats.get("play_count"))
                        except Exception:
                            play_count = None

                        videos.append({
                            "video_id": aweme_id,
                            "title": desc,
                            "url": f"https://www.douyin.com/video/{aweme_id}",
                            "cover_url": cover_url,
                            "duration_text": None,
                            "play_count": play_count,
                            "publish_time": publish_ts,
                        })

                    has_more = bool(data.get("has_more"))
                    next_cursor = int(data.get("cursor", 0)) if has_more else next_cursor
                    pages += 1

            # 5) 可选：合集标题/合集封面补充（默认跳过以加速API调用）。
            #    同时若从视频页可获取合集元信息的列表接口（mix/listcollection），优先尝试读取总数。
            if total_count_reported is None:
                try:
                    listcollection_url = "https://www.douyin.com/aweme/v1/web/mix/listcollection/"
                    params_lc = {
                        "device_platform": "webapp",
                        "aid": "6383",
                        "channel": "channel_pc_web",
                        "cursor": "0",
                        "count": "1",
                    }
                    # 该接口通常由视频页触发，这里仅在可用时试探
                    async with httpx.AsyncClient(timeout=10.0) as client2:
                        lc_resp = await client2.get(listcollection_url, params=params_lc, headers=headers)
                        if lc_resp.status_code == 200:
                            lc_data = lc_resp.json() or {}
                            for key in ("total", "mix_total", "collection_total"):
                                if isinstance(lc_data.get(key), int):
                                    total_count_reported = int(lc_data.get(key))
                                    break
                except Exception:
                    pass

            # 无论是否 with_meta，都先用首个视频封面作为合集头像兜底
            if not collection_cover and videos:
                collection_cover = videos[0].get("cover_url")

            # 如果仍未拿到合集标题，尝试通过首个视频的 aweme/detail 读取 mix_info.mix_name
            if not collection_title and videos:
                try:
                    detail_url = "https://www-hj.douyin.com/aweme/v1/web/aweme/detail/"
                    params_detail = {
                        "device_platform": "webapp",
                        "aid": "6383",
                        "channel": "channel_pc_web",
                        "aweme_id": videos[0]["video_id"],
                        "update_version_code": "170400",
                        "pc_client_type": "1",
                        "version_code": "190500",
                        "version_name": "19.5.0",
                    }
                    if isinstance(api_params, dict):
                        for k in ("msToken", "verifyFp", "fp", "a_bogus", "webid", "uifid"):
                            if k in api_params and api_params[k]:
                                params_detail[k] = api_params[k]
                    async with httpx.AsyncClient(timeout=10.0) as client3:
                        d_resp = await client3.get(detail_url, params=params_detail, headers=headers)
                        if d_resp.status_code == 200:
                            d_data = d_resp.json() or {}
                            try:
                                collection_title = (
                                    ((d_data.get("aweme_detail") or {}).get("mix_info") or {}).get("mix_name")
                                    or (d_data.get("mix_info") or {}).get("mix_name")
                                )
                            except Exception:
                                pass
                except Exception:
                    pass

            if with_meta:

                # 轻量尝试从页面读取标题（带超时保护）
                try:
                    await douyin_api._ensure_browser_ready()
                    await douyin_api.page.goto(collection_url, wait_until="domcontentloaded", timeout=10000)
                    # 等待典型标题元素出现
                    try:
                        await douyin_api.page.wait_for_selector('h2, [data-e2e="mix-title"]', timeout=5000)
                    except Exception:
                        pass
                    # 优先从h2/data-e2e读取
                    for sel in ['[data-e2e="mix-title"]', 'h2', 'h1', '[class*="title"]']:
                        try:
                            el = await douyin_api.page.query_selector(sel)
                            if el:
                                txt = (await el.text_content()) or ''
                                txt = txt.strip()
                                if txt:
                                    collection_title = txt
                                    break
                        except Exception:
                            continue
                    # 回退：使用document.title的第一段
                    if not collection_title:
                        try:
                            page_title = await douyin_api.page.title()
                            if page_title:
                                head = page_title.split('-')[0].strip()
                                if head:
                                    collection_title = head
                        except Exception:
                            pass
                except Exception:
                    pass

            await douyin_api._update_activity()
            return {
                "collection_id": collection_id,
                "collection_title": collection_title,
                "videos": videos,
                "total_count": total_count_reported if isinstance(total_count_reported, int) else len(videos),
                "has_more": has_more,
                "next_cursor": next_cursor,
                "collection_cover": collection_cover,
            }

        return await douyin_api.enqueue_request(_get_collection_videos)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取合集视频失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"获取合集视频失败: {str(e)}")

@router.post("/collection/parse")
async def parse_collection_url_endpoint(url: str, current_user: User = Depends(get_current_user)):
    """解析合集URL获取合集信息"""
    try:
        result = await parse_collection_url(url)
        return result
    except Exception as e:
        logger.error(f"解析合集URL失败: {str(e)}")
        raise HTTPException(status_code=400, detail=str(e))

@router.get("/collection/{collection_id}/videos")
async def get_collection_videos_endpoint(collection_id: str, cursor: int = 0, count: int = 20, current_user: User = Depends(get_current_user)):
    """获取合集视频列表"""
    try:
        result = await get_collection_videos(collection_id, cursor, count)
        return result
    except Exception as e:
        logger.error(f"获取合集视频失败: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e)) 
