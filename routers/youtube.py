import os
import shutil
import asyncio
import hashlib
import json
from fastapi import APIRouter, HTTPException, Depends
from playwright.async_api import async_playwright
import logging
from datetime import datetime, timedelta, timezone
import re
from typing import List, Optional, Tuple, Dict, Any
import httpx
from httpx import RequestError, TimeoutException, HTTPStatusError
import time
import random
import urllib.parse

# 配置日志 - 移除basicConfig，统一由supervisor管理
logger = logging.getLogger(__name__)

# 导入认证
from routers.auth import get_current_user
from sql.models import User

router = APIRouter(
    prefix="/api/subscribe/youtube",
    tags=["youtube"],
    responses={404: {"description": "Not found"}}
)

# 添加错误分类类
class YouTubeAPIError(Exception):
    """YouTube API 错误基类"""
    def __init__(self, error_type: str, message: str, retryable: bool = True, retry_delay: int = 5):
        self.error_type = error_type
        self.message = message
        self.retryable = retryable
        self.retry_delay = retry_delay
        super().__init__(message)

class NetworkError(YouTubeAPIError):
    """网络连接错误"""
    def __init__(self, message: str, retry_delay: int = 5):
        super().__init__("network", message, retryable=True, retry_delay=retry_delay)

class RateLimitError(YouTubeAPIError):
    """API限制错误"""
    def __init__(self, message: str, retry_delay: int = 30):
        super().__init__("rate_limit", message, retryable=True, retry_delay=retry_delay)

class AuthError(YouTubeAPIError):
    """认证错误"""
    def __init__(self, message: str):
        super().__init__("auth", message, retryable=False, retry_delay=0)

class ParseError(YouTubeAPIError):
    """解析错误"""
    def __init__(self, message: str, retryable: bool = True):
        super().__init__("parse", message, retryable=retryable, retry_delay=5)

# 重试配置类
class RetryConfig:
    def __init__(self):
        self.max_retries = 3
        self.retry_delay_base = 2
        self.max_retry_delay = 60
        self.request_timeout = 30

def classify_error(error: Exception) -> YouTubeAPIError:
    """错误分类函数"""
    error_str = str(error).lower()
    
    # 网络相关错误
    if any(keyword in error_str for keyword in ["timeout", "connection", "network", "unreachable"]):
        return NetworkError(f"网络连接错误: {error}", retry_delay=5)
    
    # HTTP状态错误
    if "429" in error_str or "rate limit" in error_str or "quota" in error_str:
        return RateLimitError(f"API限制: {error}", retry_delay=30)
    
    if "401" in error_str or "403" in error_str or "unauthorized" in error_str:
        return AuthError(f"认证错误: {error}")
    
    if "404" in error_str:
        return ParseError(f"资源不存在: {error}", retryable=False)
    
    # 解析错误
    if any(keyword in error_str for keyword in ["parse", "json", "format"]):
        return ParseError(f"数据解析错误: {error}", retryable=True)
    
    # 默认错误
    return YouTubeAPIError("unknown", f"未知错误: {error}", retryable=True, retry_delay=10)

def parse_relative_time(time_text: str) -> str:
    """解析相对时间文本为具体日期
    
    Args:
        time_text: 相对时间文本，如"3天前"、"1周前"等
        
    Returns:
        str: YYYY-MM-DD格式的日期字符串
    """
    try:
        now = datetime.now()
        
        # 处理中文相对时间
        if "分钟前" in time_text:
            minutes = int(time_text.replace("分钟前", ""))
            date = now - timedelta(minutes=minutes)
        elif "小时前" in time_text:
            hours = int(time_text.replace("小时前", ""))
            date = now - timedelta(hours=hours)
        elif "天前" in time_text:
            days = int(time_text.replace("天前", ""))
            date = now - timedelta(days=days)
        elif "周前" in time_text:
            weeks = int(time_text.replace("周前", ""))
            date = now - timedelta(weeks=weeks)
        elif "个月前" in time_text:
            months = int(time_text.replace("个月前", ""))
            date = now - timedelta(days=months*30)  # 近似值
        elif "年前" in time_text:
            years = int(time_text.replace("年前", ""))
            date = now - timedelta(days=years*365)  # 近似值
            
        # 处理英文相对时间
        elif "minute ago" in time_text or "minutes ago" in time_text:
            minutes = int(time_text.split()[0])
            date = now - timedelta(minutes=minutes)
        elif "hour ago" in time_text or "hours ago" in time_text:
            hours = int(time_text.split()[0])
            date = now - timedelta(hours=hours)
        elif "day ago" in time_text or "days ago" in time_text:
            days = int(time_text.split()[0])
            date = now - timedelta(days=days)
        elif "week ago" in time_text or "weeks ago" in time_text:
            weeks = int(time_text.split()[0])
            date = now - timedelta(weeks=weeks)
        elif "month ago" in time_text or "months ago" in time_text:
            months = int(time_text.split()[0])
            date = now - timedelta(days=months*30)  # 近似值
        elif "year ago" in time_text or "years ago" in time_text:
            years = int(time_text.split()[0])
            date = now - timedelta(days=years*365)  # 近似值
        else:
            return time_text
            
        return date.strftime("%Y-%m-%d")
    except Exception as e:
        logger.error(f"解析相对时间失败: {str(e)}")
        return time_text


# ============================================================================
# 工具函数：统计数据提取（避免代码重复）
# ============================================================================

# 订阅者数匹配模式（统一管理）
SUBSCRIBER_PATTERNS = [
    # 中文格式
    (r'(\d+(?:\.\d+)?)亿位订阅者', 100000000),
    (r'(\d+(?:\.\d+)?)万位订阅者', 10000),
    (r'(\d+(?:\.\d+)?)千位订阅者', 1000),
    (r'(\d+)位订阅者', 1),
    (r'(\d+(?:\.\d+)?)亿订阅者', 100000000),
    (r'(\d+(?:\.\d+)?)万订阅者', 10000),
    (r'(\d+(?:\.\d+)?)千订阅者', 1000),
    (r'(\d+)订阅者', 1),
    (r'(\d+(?:\.\d+)?)亿人订阅', 100000000),
    (r'(\d+(?:\.\d+)?)万人订阅', 10000),
    (r'(\d+(?:\.\d+)?)千人订阅', 1000),
    (r'(\d+)人订阅', 1),
    # 英文格式
    (r'(\d+(?:\.\d+)?)M subscribers', 1000000),
    (r'(\d+(?:\.\d+)?)K subscribers', 1000),
    (r'(\d+) subscribers', 1),
    (r'(\d+(?:\.\d+)?)M subscriber', 1000000),
    (r'(\d+(?:\.\d+)?)K subscriber', 1000),
    (r'(\d+) subscriber', 1),
    (r'(\d+(?:\.\d+)?)M subs', 1000000),
    (r'(\d+(?:\.\d+)?)K subs', 1000),
    (r'(\d+) subs', 1),
    # 其他语言
    (r'(\d+(?:\.\d+)?)M abonnés', 1000000),
    (r'(\d+(?:\.\d+)?)K abonnés', 1000),
    (r'(\d+) abonnés', 1),
    (r'(\d+(?:\.\d+)?)M Abonnenten', 1000000),
    (r'(\d+(?:\.\d+)?)K Abonnenten', 1000),
    (r'(\d+) Abonnenten', 1),
    (r'(\d+(?:\.\d+)?)M suscriptores', 1000000),
    (r'(\d+(?:\.\d+)?)K suscriptores', 1000),
    (r'(\d+) suscriptores', 1),
    # 通用格式（兜底）
    (r'(\d+(?:,\d+)*)\s*(?:subscribers?|subs?|abonnés?|Abonnenten?|suscriptores?)', 1),
]

# 视频数匹配模式（统一管理）
VIDEO_PATTERNS = [
    # 中文格式
    (r'(\d+) 个视频', 1),
    (r'(\d+)个视频', 1),
    (r'(\d+) 个影片', 1),
    (r'(\d+)个影片', 1),
    (r'(\d+) 个短视频', 1),
    (r'(\d+)个短视频', 1),
    (r'(\d+) 个内容', 1),
    (r'(\d+)个内容', 1),
    # 英文格式
    (r'(\d+) videos', 1),
    (r'(\d+) video', 1),
    # 其他语言
    (r'(\d+) vidéos', 1),
    (r'(\d+) Videos', 1),
    (r'(\d+) vídeos', 1),
    # 通用格式（兜底）
    (r'(\d+(?:,\d+)*)\s*(?:videos?|vidéos?|Videos?|vídeos?|影片|短视频|内容)', 1),
]


def parse_count_from_text(text: str, patterns: list) -> Optional[int]:
    """从文本中提取数量（订阅者数或视频数）
    
    Args:
        text: 要解析的文本
        patterns: 匹配模式列表，每项为 (正则表达式, 倍数)
        
    Returns:
        提取到的数量，如果未找到则返回 None
    """
    for pattern, multiplier in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            value_str = match.group(1)
            # 处理带逗号的数字
            value_str = value_str.replace(',', '')
            try:
                value = float(value_str) * multiplier
                return int(value)
            except ValueError:
                continue
    return None


# 导入统一浏览器管理器
from .unified_browser_manager import unified_browser
# 导入API参数缓存管理器
from .api_params_cache import api_params_cache

class YouTubeAPI:
    def __init__(self):
        # 使用统一浏览器管理器
        self._browser = unified_browser
        self._platform = "youtube"
        
        # 参数缓存：使用统一的api_params_cache，不再维护自己的内存缓存
        
        # 频道信息缓存
        self._channel_info_cache = {}  # {url: {"data": dict, "timestamp": float}}
        self._channel_info_cache_duration = 21600  # 缓存有效期6小时
        
        # 请求队列管理
        self._request_queue = asyncio.Queue()
        self._worker_task = None
        self._max_concurrent_requests = 10
        self._request_semaphore = asyncio.Semaphore(self._max_concurrent_requests)
        
        # 重试配置
        self.retry_config = RetryConfig()
        
    @property
    def page(self):
        """获取当前页面（向后兼容）"""
        return self._browser._pages.get(self._platform)
    
    @property
    def context(self):
        """获取浏览器上下文"""
        return self._browser.context
    
    async def _request_with_retry(self, request_func, *args, **kwargs):
        """带重试机制的通用请求方法"""
        last_error = None
        
        for retry in range(self.retry_config.max_retries):
            try:
                return await request_func(*args, **kwargs)
            except Exception as e:
                # 分类错误
                classified_error = classify_error(e)
                last_error = classified_error
                
                logger.warning(f"第{retry + 1}次请求失败 ({classified_error.error_type}): {classified_error.message}")
                
                # 如果错误不可重试，直接抛出
                if not classified_error.retryable:
                    logger.error(f"错误不可重试，停止重试: {classified_error.message}")
                    raise classified_error
                
                # 如果是最后一次重试，抛出错误
                if retry == self.retry_config.max_retries - 1:
                    logger.error(f"重试{self.retry_config.max_retries}次后仍然失败: {classified_error.message}")
                    raise classified_error
                
                # 计算重试延迟
                delay = min(
                    classified_error.retry_delay * (self.retry_config.retry_delay_base ** retry),
                    self.retry_config.max_retry_delay
                )
                
                logger.info(f"等待{delay}秒后重试...")
                await asyncio.sleep(delay)
        
        # 这里不应该到达，但为了安全起见
        raise last_error or YouTubeAPIError("unknown", "未知错误")
        
    async def get_cookie(self, force_refresh: bool = False) -> str:
        """
        获取 YouTube cookie
        
        Args:
            force_refresh: 是否强制刷新（访问主页以保活Session）
        """
        try:
            # 确保浏览器已初始化并处于可用状态
            await self._ensure_browser_ready()
            
            # 如果需要强制刷新，则访问一次主页
            if force_refresh:
                try:
                    logger.debug("正在执行Cookie保活刷新：访问YouTube主页...")
                    page = await self.get_base_page()
                    if page:
                        await page.goto("https://www.youtube.com", wait_until="domcontentloaded", timeout=30000)
                        # 等待一小会儿让JS执行
                        await asyncio.sleep(3)
                        logger.debug("YouTube主页访问完成，Session已刷新")
                except Exception as e:
                    logger.warning(f"刷新YouTube Session时出错（不影响获取现有Cookie）: {str(e)}")
                
            cookies = await self.context.cookies()
            if not cookies:
                return ""
                
            # 将 cookies 转换为 Netscape 格式的字符串
            cookie_str = ""
            for cookie in cookies:
                if cookie.get("domain", "").endswith("youtube.com"):
                    name = cookie.get("name", "")
                    value = cookie.get("value", "")
                    if name and value:
                        cookie_str += f"{name}={value}; "
            
            # 🔧 关键修复：获取cookie后更新浏览器活动时间，防止被自动清理关闭
            await self._update_activity()
            logger.debug("YouTube cookie获取完成，已更新浏览器活动时间")
            
            return cookie_str.strip()
        except Exception as e:
            logger.error(f"获取YouTube cookie失败: {str(e)}")
            return ""

    async def export_cookies_netscape(self, force_refresh: bool = False) -> str:
        """
        从 Playwright 浏览器上下文导出 Netscape 格式 cookies（供 yt-dlp 使用）。
        关键点：保留每条 cookie 的真实 domain/path/secure/expires，避免把所有 cookie 强行写成 .youtube.com 导致登录态失效。
        """
        try:
            await self._ensure_browser_ready()

            if force_refresh:
                try:
                    logger.debug("正在执行Cookie保活刷新：访问YouTube主页...")
                    page = await self.get_base_page()
                    if page:
                        await page.goto("https://www.youtube.com", wait_until="domcontentloaded", timeout=30000)
                        await asyncio.sleep(3)
                        logger.debug("YouTube主页访问完成，Session已刷新")
                except Exception as e:
                    logger.warning(f"刷新YouTube Session时出错（不影响导出现有Cookie）: {str(e)}")

            cookies = await self.context.cookies()
            if not cookies:
                return ""

            def _should_keep(domain: str) -> bool:
                d = (domain or "").lstrip(".").lower()
                # YouTube 登录态常同时涉及 youtube.com 与 google.com
                return d.endswith("youtube.com") or d.endswith("google.com")

            lines = []
            for c in cookies:
                domain = (c.get("domain") or "").strip()
                if not _should_keep(domain):
                    continue

                name = (c.get("name") or "").strip()
                value = (c.get("value") or "").strip()
                if not name or not value:
                    continue

                # Netscape cookie file field semantics:
                # domain \t include_subdomains \t path \t secure \t expiry \t name \t value
                dom = domain if domain.startswith(".") else f".{domain}" if domain else ".youtube.com"
                include_subdomains = "TRUE"
                path = c.get("path") or "/"
                secure = "TRUE" if c.get("secure") else "FALSE"
                expires = c.get("expires")
                try:
                    expiry = int(expires) if expires else 0
                except Exception:
                    expiry = 0

                lines.append(f"{dom}\t{include_subdomains}\t{path}\t{secure}\t{expiry}\t{name}\t{value}")

            if not lines:
                return ""

            await self._update_activity()
            header = "# Netscape HTTP Cookie File\n# This file is generated by easy-vdl.  Do not edit.\n\n"
            return header + "\n".join(lines)
        except Exception as e:
            logger.error(f"导出YouTube Netscape cookies失败: {type(e).__name__}: {str(e)}")
            return ""
        
    async def get_base_page(self):
        """获取基础页面（用于获取参数和Cookie）"""
        try:
            # 首先确保浏览器处于可用状态
            await self._ensure_browser_ready()
            
            # 获取或创建名为 "youtube" 的基础页面
            page = await self._browser.get_page(self._platform)
            
            if page:
                return page
            else:
                logger.error("无法获取YouTube基础页面")
                return None
        except Exception as e:
            logger.error(f"获取基础页面失败: {str(e)}")
            return None

    async def _ensure_global_params(self):
        """确保全局参数已缓存且有效"""
        if await self._is_global_params_valid():
            return True
            
        logger.info("全局参数缺失或已过期，正在重新获取...")
        try:
            # 获取基础页面
            page = await self.get_base_page()
            if not page:
                raise Exception("无法获取基础页面")
                
            # 访问YouTube主页获取参数
            try:
                # 检查当前是否已经在YouTube页面
                if "youtube.com" in page.url:
                    logger.debug("当前已在YouTube页面，尝试直接获取参数")
                    params = await self._extract_params_from_page(page)
                    if params.get('key'):
                        await self._cache_youtube_params(params)
                        return True
                
                # 访问主页
                logger.info("访问YouTube主页获取参数...")
                await page.goto(
                    "https://www.youtube.com/?hl=zh-CN&gl=CN",
                    wait_until="domcontentloaded",
                    timeout=30000
                )
                
                # 等待ytcfg加载
                try:
                    await page.wait_for_function("window.ytcfg && window.ytcfg.data_", timeout=5000)
                except Exception:
                    logger.warning("等待ytcfg超时，尝试直接获取")
                
                # 提取参数
                params = await self._extract_params_from_page(page)
                if params.get('key'):
                    await self._cache_youtube_params(params)
                    return True
                else:
                    logger.error("无法从主页提取参数")
                    return False
                    
            except Exception as e:
                logger.error(f"访问页面获取参数失败: {str(e)}")
                return False
                
        except Exception as e:
            logger.error(f"获取全局参数失败: {str(e)}")
            return False

    async def _extract_params_from_page(self, page) -> dict:
        """从页面提取参数"""
        script = """
        () => {
            const params = {};
            try {
                const ytcfg = window.ytcfg && window.ytcfg.data_;
                if (ytcfg) {
                    params.key = ytcfg.INNERTUBE_API_KEY;
                    params.clientVersion = ytcfg.INNERTUBE_CLIENT_VERSION;
                    params.visitorData = ytcfg.VISITOR_DATA;
                    params.clientName = ytcfg.INNERTUBE_CONTEXT_CLIENT_NAME;
                    
                    if (ytcfg.INNERTUBE_CONTEXT) {
                        params.INNERTUBE_CONTEXT = JSON.parse(JSON.stringify(ytcfg.INNERTUBE_CONTEXT));
                    }
                    
                    params.experimentIds = ytcfg.EXPERIMENT_FLAGS;
                    params.deviceExperimentId = ytcfg.DEVICE_ID;
                    params.clickTrackingParams = ytcfg.CSI_PAGE_TYPE;
                    params.rolloutToken = document.cookie.match(/__Secure-ROLLOUT_TOKEN=([^;]+)/)?.[1];
                }
                return params;
            } catch (e) {
                console.error('Error extracting params:', e);
                return params;
            }
        }
        """
        return await page.evaluate(script)

    async def _get_youtube_params(self, page=None) -> dict:
        """获取YouTube API所需的参数（简化版，使用全局缓存）"""
        # 如果传入了page，直接从页面提取参数
        if page:
            return await self._extract_params_from_page(page)
        
        # 否则确保全局参数有效并返回
        await self._ensure_global_params()
        cached = api_params_cache.get(self._platform)
        return cached if cached else {}
        
    def get_browser(self):
        """获取浏览器实例"""
        return self.context if self.context else None
        
    async def _update_activity(self):
        """更新最后活动时间"""
        await self._browser._update_activity()
        
    async def start_worker(self):
        """启动后台工作任务处理队列中的请求"""
        if self._worker_task is None or self._worker_task.done():
            self._worker_task = asyncio.create_task(self._process_queue())
            logger.info("YouTube请求队列处理任务已启动")
        else:
            logger.debug("YouTube请求队列处理任务已在运行")
            
    async def stop_worker(self):
        """停止后台工作任务"""
        if self._worker_task:
            logger.info("正在停止YouTube请求队列处理任务...")
            self._worker_task.cancel()
            try:
                await self._worker_task
            except asyncio.CancelledError:
                pass
            self._worker_task = None
            logger.info("YouTube请求队列处理任务已停止")
        else:
            logger.info("YouTube请求队列处理任务未在运行")
            
    async def _process_queue(self):
        """处理请求队列的后台任务"""
        logger.debug("YouTube请求队列处理任务开始运行")
        while True:
            try:
                # 获取队列中的请求
                logger.debug("等待YouTube请求队列中的请求...")
                request_func, future = await self._request_queue.get()
                logger.debug("收到YouTube请求，开始处理...")
                
                try:
                    async with self._request_semaphore:
                        # 确保浏览器已初始化
                        if not self.context:
                            logger.info("YouTube浏览器未初始化，正在初始化...")
                            success = await self.init_browser()
                            if not success:
                                raise Exception("浏览器初始化失败")
                            logger.info("YouTube浏览器初始化完成")
                                
                        # 执行请求
                        logger.debug("执行YouTube请求...")
                        result = await request_func()
                        future.set_result(result)
                        logger.debug("YouTube请求执行完成")
                        
                except Exception as e:
                    future.set_exception(e)
                    logger.error(f"YouTube处理请求失败: {str(e)}")
                    
                finally:
                    self._request_queue.task_done()
                    logger.debug("YouTube请求队列任务标记为完成")
                    
            except asyncio.CancelledError:
                logger.info("YouTube请求队列处理任务被取消")
                break
            except Exception as e:
                logger.error(f"YouTube处理请求队列时出错: {str(e)}")
                continue
                
    async def enqueue_request(self, request_func):
        """将请求添加到队列并更新活动时间"""
        logger.debug("YouTube请求开始，更新活动时间...")
        await self._update_activity()  # 请求开始时更新
        try:
            future = asyncio.Future()
            # 移除重复的worker启动，避免重复创建进程
            logger.debug("将YouTube请求添加到队列...")
            await self._request_queue.put((request_func, future))
            logger.debug("等待YouTube请求执行结果...")
            result = await future
            logger.debug("YouTube请求执行成功，更新活动时间...")
            await self._update_activity()  # 请求成功时更新
            return result
        except Exception as e:
            logger.error(f"YouTube请求执行失败: {str(e)}")
            raise

    async def init_browser(self):
        """初始化浏览器（使用统一浏览器管理器）"""
        try:
            success = await self._browser.init_browser()
            if success:
                logger.info(f"✅ {self._platform}浏览器上下文初始化成功")
                return True
            else:
                # 记录统一浏览器管理器的状态，方便定位问题
                browser_status = self._browser.get_status()
                logger.error(f"❌ {self._platform}浏览器上下文初始化失败 - 统一浏览器状态: initialized={browser_status.get('initialized')}, active_tasks={browser_status.get('active_tasks')}, login_mode={browser_status.get('login_mode')}")
                return False
        except Exception as e:
            logger.error(f"❌ 浏览器初始化失败: {type(e).__name__}: {str(e)}")
            import traceback
            logger.error(f"完整堆栈:\n{traceback.format_exc()}")
            return False

    async def close_browser(self):
        """关闭浏览器（使用统一浏览器管理器）"""
        try:
            # 关闭基础标签页
            await self._browser.close_page(self._platform)
            logger.info(f"✅ {self._platform}标签页已关闭")
        except Exception as e:
            logger.error(f"❌ 关闭{self._platform}标签页失败: {str(e)}")
        
        # 关闭登录专用标签页
        try:
            await self._browser.close_page(f"{self._platform}_login")
            logger.info(f"✅ {self._platform}_login标签页已关闭")
        except Exception as e:
            logger.debug(f"关闭{self._platform}_login标签页失败（可能不存在）: {str(e)}")

    async def login(self):
        """打开YouTube登录页面等待用户登录"""
        try:
            logger.info("YouTube登录流程启动")
            
            # 只在浏览器未初始化时才初始化
            if not self.context:
                logger.info("浏览器未初始化，正在初始化...")
                success = await self.init_browser()
                if not success:
                    raise Exception("浏览器初始化失败")
                logger.info("浏览器初始化完成")
                self._login_page = None
            
            # 通过统一管理器创建独立的登录标签页
            if not hasattr(self, '_login_page') or not self._login_page:
                logger.info("创建YouTube登录页面...")
                self._login_page = await self._browser.get_page("youtube_login")
                if not self._login_page:
                    raise Exception("创建YouTube登录页面失败")
                self._login_page.set_default_timeout(30000)
                logger.info("YouTube登录页面创建成功")
            else:
                # 检查登录页面是否有效
                try:
                    await self._login_page.evaluate("1")
                    logger.info("使用现有登录页面")
                except Exception:
                    logger.info("登录页面已失效，重新创建...")
                    self._login_page = await self._browser.get_page("youtube_login")
                    if not self._login_page:
                        raise Exception("创建YouTube登录页面失败")
                    self._login_page.set_default_timeout(30000)
                    logger.info("YouTube登录页面重新创建成功")
            
            # 设置页面视口大小
            await self._login_page.set_viewport_size({"width": 1280, "height": 800})
            
            # 访问YouTube主页，让用户自然登录
            logger.info("正在访问YouTube主页...")
            await self._login_page.goto(
                "https://www.youtube.com/?hl=zh-CN",
                wait_until="domcontentloaded",
                timeout=30000
            )
            logger.info("YouTube主页加载完成")
            
            # 等待页面稳定
            await asyncio.sleep(2)
            
            # 检查页面是否已被关闭（用户主动关闭）
            if not self._login_page:
                logger.info("用户已关闭浏览器，登录已取消")
                return {"message": "登录已取消", "cancelled": True}
            
            try:
                if self._login_page.is_closed():
                    logger.info("用户已关闭浏览器，登录已取消")
                    return {"message": "登录已取消", "cancelled": True}
            except Exception as e:
                if "closed" in str(e).lower() or "Target page, context or browser has been closed" in str(e):
                    logger.info("用户已关闭浏览器，登录已取消")
                    return {"message": "登录已取消", "cancelled": True}
            
            try:
                current_url = self._login_page.url
                logger.info(f"当前页面URL: {current_url}")
            except Exception as e:
                if "closed" in str(e).lower() or "Target page, context or browser has been closed" in str(e):
                    logger.info("用户已关闭浏览器，登录已取消")
                    return {"message": "登录已取消", "cancelled": True}
            
            return {"message": "已打开YouTube登录页面", "success": True}
            
        except Exception as e:
            logger.error(f"YouTube登录失败: {str(e)}")
            raise Exception(f"YouTube登录失败: {str(e)}")

    async def clean_browser(self):
        """清理浏览器文件"""
        try:
            logger.info(f"YouTube清理浏览器 - 使用实例ID: {id(self)}")
            
            # 先关闭浏览器
            logger.info("正在关闭浏览器...")
            await self.close_browser()
            logger.info("浏览器关闭完成")
            
            # 获取统一浏览器的数据目录
            user_data_dir = self._browser.user_data_dir
            
            # 检查并删除用户数据目录
            if os.path.exists(user_data_dir):
                try:
                    logger.info(f"正在删除统一浏览器用户数据目录: {user_data_dir}")
                    shutil.rmtree(user_data_dir)
                    logger.info(f"已删除统一浏览器用户数据目录: {user_data_dir}")
                except Exception as e:
                    logger.error(f"删除用户数据目录失败: {str(e)}")
                    raise Exception(f"删除用户数据目录失败: {str(e)}")
            else:
                logger.info("用户数据目录不存在，无需删除")
            
            # 创建新的用户数据目录
            logger.info("正在创建新的用户数据目录...")
            os.makedirs(user_data_dir, exist_ok=True)
            logger.info("已创建新的用户数据目录")
            
            # 清理参数缓存
            logger.info("正在清理参数缓存...")
            await self._clear_params_cache()
            logger.info("参数缓存清理完成")
            
            logger.info("YouTube浏览器文件清理成功")
            return {"message": "浏览器文件清理成功"}
        except Exception as e:
            logger.error(f"YouTube清理浏览器文件失败: {str(e)}")
            raise Exception(f"清理浏览器文件失败: {str(e)}")

    async def get_channel_videos(self, channel_id: str, max_count: int = 20, page_token: str = "", last_video_time: str = "", tab_type: str = "videos", base_timestamp: int = None, start_index: int = 0) -> dict:
        """获取频道视频列表（多标签页版本）
        
        Args:
            channel_id: 频道ID
            max_count: 每页视频数量
            page_token: 分页标记
            last_video_time: 最后视频时间（未使用，保留兼容性）
            tab_type: 标签页类型，可选值: "videos", "shorts", "playlists"
            base_timestamp: Shorts的基准时间戳，用于多页获取时保持顺序
            start_index: Shorts的起始索引，用于多页获取时保持顺序
            
        Returns:
            dict: 包含视频列表的字典
        """
        async def _get_videos(retry_on_auth_fail: bool = True):
            nonlocal base_timestamp, start_index
            await self._update_activity()
            try:
                # 确保浏览器已初始化
                if not self.context:
                    logger.info("浏览器未初始化，正在初始化...")
                    success = await self.init_browser()
                    if not success:
                        raise Exception("浏览器初始化失败")

                # 检查参数缓存是否有效
                cached_params = await self._get_cached_youtube_params(channel_id)
                
                # 判断是否为有效的UC格式ID
                is_uc_id = channel_id.startswith('UC') and len(channel_id) == 24
                
                # 如果参数缺失或者（不是UC ID且没有缓存的映射），则需要刷新页面
                # 注意：由于我们移除了缓存中的real_browse_id，所以对于非UC ID，目前必须刷新页面才能获取真实ID
                need_page_refresh = not cached_params or not is_uc_id
                
                # 为了避免并发访问时频道ID混淆，每个频道使用临时独立页面
                # 如果需要访问页面，创建临时页面；否则使用共享页面即可
                temp_page_key = None  # 记录临时页面key，用于最后清理
                if need_page_refresh:
                    # 创建临时页面：使用频道ID作为唯一标识
                    temp_page_key = f"youtube:temp_{channel_id}_{id(asyncio.current_task())}"
                    page = await self._browser.get_page(temp_page_key)
                else:
                    # 不需要访问页面，使用共享页面获取cookie即可
                    page = await self.get_base_page()
                
                # 防御：get_page/get_base_page 在浏览器/context 被关闭时会返回 None，必须在此处拦截，避免后续 page.context 报 'NoneType' has no attribute 'context'
                if not page:
                    raise Exception("无法获取YouTube页面（浏览器或标签页可能已关闭），请重试")
                
                # 标签页类型映射
                tab_url_map = {
                    "videos": "/videos",
                    "shorts": "/shorts",
                    "playlists": "/playlists"
                }
                
                # 标签页参数映射（base64编码的参数）
                # 实际抓包获取的值
                tab_params_map = {
                    "videos": "EgZ2aWRlb3PyBgQKAjoA",
                    "shorts": "EgZzaG9ydHPyBgUKA5oBAA==",  # 实际值: EgZzaG9ydHPyBgUKA5oBAA==
                    "playlists": "EglwbGF5bGlzdHPyBgQKAkIA"  # 实际值: EglwbGF5bGlzdHPyBgQKAkIA
                }
                
                # 获取对应的URL路径和参数
                url_path = tab_url_map.get(tab_type, "/videos")
                tab_params = tab_params_map.get(tab_type, "EgZ2aWRlb3PyBgQKAjoA")
                
                logger.debug(f"标签页类型: {tab_type}, URL路径: {url_path}, 参数: {tab_params}")
                
                # 如果需要刷新页面，访问频道页面获取参数
                if need_page_refresh:
                    logger.debug(f"访问频道页面获取参数: {channel_id}, 标签页类型: {tab_type}")
                    
                    # 判断是频道ID还是频道名称
                    if channel_id.startswith('UC') and len(channel_id) == 24:
                        # 这是频道ID格式
                        channel_url = f"https://www.youtube.com/channel/{channel_id}{url_path}"
                    else:
                        # 这是频道名称格式，需要添加@前缀
                        if not channel_id.startswith('@'):
                            channel_url = f"https://www.youtube.com/@{channel_id}{url_path}"
                        else:
                            channel_url = f"https://www.youtube.com/{channel_id}{url_path}"
                    
                    # 确保URL包含中文参数
                    if "?" in channel_url:
                        channel_url += "&hl=zh-CN&gl=CN"
                    else:
                        channel_url += "?hl=zh-CN&gl=CN"
                    
                    await page.goto(
                        channel_url,
                        wait_until="domcontentloaded",
                        timeout=45000
                    )
                    
                    # 等待ytcfg加载（减少超时时间）
                    try:
                        await page.wait_for_function("window.ytcfg && window.ytcfg.data_", timeout=8000)  # 从15秒减少到8秒
                        logger.info("ytcfg已加载")
                    except Exception as e:
                        logger.warning(f"等待ytcfg超时: {str(e)}，继续执行")

                    # 获取API所需的参数并缓存
                    params = await self._get_youtube_params()
                    await self._cache_youtube_params(params)
                    logger.info(f"已缓存频道 {channel_id} 的参数")
                    
                else:
                    # 使用缓存的参数
                    params = cached_params
                    logger.info(f"使用频道 {channel_id} 的缓存参数")
                
                logger.debug(f"使用标签页参数: {tab_params}")
                
                # 获取用户cookie
                cookies = await page.context.cookies()
                cookie_str = "; ".join([f"{c['name']}={c['value']}" for c in cookies])

                # 构建请求头（从浏览器实时获取参数）
                # 确保所有请求头值都是ASCII兼容的字符串
                def safe_header_value(value):
                    """确保请求头值是安全的ASCII字符串"""
                    if value is None:
                        return ""
                    # 转换为字符串并确保是ASCII兼容的
                    str_value = str(value)
                    try:
                        # 尝试编码为ASCII，如果失败则使用UTF-8编码后的URL编码
                        str_value.encode('ascii')
                        return str_value
                    except UnicodeEncodeError:
                        # 如果包含非ASCII字符，进行URL编码
                        import urllib.parse
                        return urllib.parse.quote(str_value, safe='')

                # 构建安全的请求头
                headers = {
                    "authority": "www.youtube.com",
                    "accept": "*/*",
                    "accept-language": "zh-CN,zh;q=0.9,en;q=0.8",
                    "content-type": "application/json",
                    "cookie": cookie_str,
                    "origin": "https://www.youtube.com",
                    "referer": f"https://www.youtube.com/@{safe_header_value(channel_id)}{url_path}",
                    "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                    "x-youtube-client-name": safe_header_value(params.get('clientName', "1")),
                    "x-youtube-client-version": safe_header_value(params.get('clientVersion', "")),
                    "x-goog-visitor-id": safe_header_value(params.get('visitorData')),
                    "x-origin": "https://www.youtube.com",
                    "authorization": safe_header_value(params.get('ID_TOKEN', "")) if params.get('ID_TOKEN') else "",
                    "x-goog-authuser": "0",
                    "x-goog-pageid": safe_header_value(params.get('PAGE_CL', '')),
                    "sec-ch-ua": '"Not A Brand";v="99", "Chromium";v="120", "Google Chrome";v="120"',
                    "sec-ch-ua-mobile": "?0",
                    "sec-ch-ua-platform": '"Windows"',
                    "sec-fetch-dest": "empty",
                    "sec-fetch-mode": "cors",
                    "sec-fetch-site": "same-origin"
                }
                
                # 添加SAPISIDHASH如果可用
                if params.get('rolloutToken'):
                    headers["x-goog-pageid"] = safe_header_value(params.get('PAGE_CL', ''))
                    headers["x-goog-authuser"] = "0"
                    headers["authorization"] = f"SAPISIDHASH {safe_header_value(params.get('rolloutToken'))}"

                # 构建请求体（使用实时获取的参数）
                # 获取真实的频道ID
                browse_id = None
                
                # 如果传入的已经是UC格式的频道ID，直接使用
                if channel_id.startswith('UC') and len(channel_id) == 24:
                    browse_id = channel_id
                
                # 如果还没有browse_id，尝试从页面获取（仅在需要刷新页面时有效）
                if not browse_id:
                    try:
                        # 从页面元素获取真实的频道ID
                        channel_info = await page.evaluate("""
                            () => {
                                const metaChannelId = document.querySelector('meta[itemprop="channelId"]')?.content;
                                const ogUrl = document.querySelector('meta[property="og:url"]')?.content;
                                const canonicalUrl = document.querySelector('link[rel="canonical"]')?.href;
                                
                                // 从不同来源尝试获取频道ID
                                let channelId = metaChannelId;
                                
                                if (!channelId && ogUrl) {
                                    const match = ogUrl.match(/channel\/(UC[\w-]{22})/);
                                    if (match) channelId = match[1];
                                }
                                
                                if (!channelId && canonicalUrl) {
                                    const match = canonicalUrl.match(/channel\/(UC[\w-]{22})/);
                                    if (match) channelId = match[1];
                                }
                                
                                return { channelId };
                            }
                        """)
                        
                        if channel_info and channel_info.get('channelId'):
                            browse_id = channel_info['channelId']
                            logger.info(f"获取到真实的频道ID: {browse_id}")
                        else:
                            # 如果无法获取真实ID，使用传入的ID
                            browse_id = channel_id
                            logger.warning(f"无法获取真实的频道ID，使用传入的ID: {browse_id}")
                    except Exception as e:
                        logger.error(f"获取真实频道ID失败: {str(e)}")
                        browse_id = channel_id
                
                # 获取INNERTUBE_CONTEXT
                innertube_context = params.get('INNERTUBE_CONTEXT', {})
                
                # 构建基础请求数据
                data = {
                    "context": {
                        "client": {
                            "hl": "zh-CN",  # 使用中文
                            "gl": "US",  # 保持US，避免API错误
                            "remoteHost": "",
                            "deviceMake": "",
                            "deviceModel": "",
                            "visitorData": params.get('visitorData'),
                            "userAgent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36,gzip(gfe)",
                            "clientName": "WEB",
                            "clientVersion": params.get('clientVersion', ""),
                            "osName": "Windows",
                            "osVersion": "10.0",
                            "originalUrl": f"https://www.youtube.com/@{channel_id}{url_path}",
                            "platform": "DESKTOP",
                            "clientFormFactor": "UNKNOWN_FORM_FACTOR",
                            "userInterfaceTheme": "USER_INTERFACE_THEME_LIGHT",
                            "timeZone": "Asia/Shanghai",
                            "browserName": "Chrome",
                            "browserVersion": "120.0.0.0",
                            "screenWidthPoints": 1280,
                            "screenHeightPoints": 720,
                            "screenPixelDensity": 1,
                            "utcOffsetMinutes": 480
                        },
                        "user": {
                            "lockedSafetyMode": False
                        },
                        "request": {
                            "useSsl": True,
                            "internalExperimentFlags": [],
                            "consistencyTokenJars": []
                        }
                    },
                    "browseId": browse_id,
                    "params": tab_params  # 视频标签页参数
                }
                
                # 添加实验ID和追踪参数
                if params.get('deviceExperimentId'):
                    data['context']['client']['deviceExperimentId'] = params['deviceExperimentId']
                
                if params.get('rolloutToken'):
                    data['context']['client']['rolloutToken'] = params['rolloutToken']
                
                # 添加点击追踪参数
                if params.get('clickTrackingParams'):
                    data['context']['clickTracking'] = {
                        'clickTrackingParams': params['clickTrackingParams']
                    }
                
                # 如果有INNERTUBE_CONTEXT，合并其中的关键参数
                if params.get('INNERTUBE_CONTEXT'):
                    innertube_context = params['INNERTUBE_CONTEXT']
                    if 'client' in innertube_context:
                        # 合并客户端参数，但保留我们的基本设置
                        client_data = innertube_context['client']
                        for key in ['deviceExperimentId', 'experimentsToken', 'visitorData']:
                            if key in client_data:
                                data['context']['client'][key] = client_data[key]
                    
                    # 合并clickTracking参数
                    if 'clickTracking' in innertube_context:
                        data['context']['clickTracking'] = innertube_context['clickTracking']
                
                if page_token:
                    data["continuation"] = page_token

                # 获取API key和其他必要参数
                api_key = params.get('key', '')
                if not api_key:
                    # 如果API key为空，从页面重新获取
                    logger.info("API key为空，从页面重新获取...")
                    key_params = await page.evaluate("""
                        () => {
                            try {
                                const ytcfg = window.ytcfg && window.ytcfg.data_;
                                if (ytcfg) {
                                    return {
                                        key: ytcfg.INNERTUBE_API_KEY,
                                        context: ytcfg.INNERTUBE_CONTEXT,
                                        version: ytcfg.INNERTUBE_CLIENT_VERSION,
                                        id: ytcfg.ID_TOKEN
                                    };
                                }
                            } catch (e) {
                                console.error('Error getting API params:', e);
                            }
                            return {};
                        }
                    """)
                    
                    # 更新所有必要参数
                    api_key = key_params.get('key', '')
                    if key_params.get('context'):
                        data['context'].update(key_params['context'])
                    if key_params.get('version'):
                        data['context']['client']['clientVersion'] = key_params['version']
                    if key_params.get('id'):
                        headers['authorization'] = key_params['id']
                
                # 如果还是没有API key，使用默认值
                if not api_key:
                    api_key = 'AIzaSyAO_FJ2SlqU8Q4STEHLGCilw_Y9_11qcW8'
                    logger.warning(f"使用默认API key: {api_key}")
                
                url = f"https://www.youtube.com/youtubei/v1/browse?key={api_key}&prettyPrint=false"
                
                # 添加调试日志（脱敏处理）
                logger.debug(f"API请求URL: {url}")
                
                # 脱敏处理请求头
                safe_headers = {k: v if k.lower() not in ['cookie', 'authorization'] else f"{v[:20]}...***REDACTED***" 
                               for k, v in headers.items()}
                logger.debug(f"API请求头: {safe_headers}")
                
                # 脱敏处理请求数据中的敏感信息
                safe_data = data.copy()
                if 'context' in safe_data and 'client' in safe_data['context']:
                    client_info = safe_data['context']['client']
                    if 'visitorData' in client_info and client_info['visitorData']:
                        client_info['visitorData'] = f"{client_info['visitorData'][:20]}...***REDACTED***"
                logger.debug(f"API请求数据: {safe_data}")
                
                logger.info(f"频道ID: {channel_id}, browseId: {browse_id}")
                logger.debug(f"visitor_data: {params.get('visitorData', '')[:20]}...***REDACTED***" if params.get('visitorData') else "visitor_data: None")
                logger.debug(f"client_version: {params.get('clientVersion')}")
                logger.debug(f"client_name: {params.get('clientName')}")
                logger.debug(f"api_key: {api_key[:10]}..." if api_key else "api_key: None")
                
                try:
                    async with httpx.AsyncClient(timeout=30.0) as client:
                        response = await client.post(url, json=data, headers=headers)
                        
                        logger.debug(f"API响应状态码: {response.status_code}")
                        logger.debug(f"API响应头: {dict(response.headers)}")
                        
                        if response.status_code != 200:
                            # 检查是否需要刷新参数重试
                            if response.status_code in [401, 403] and retry_on_auth_fail:
                                logger.warning(f"YouTube API返回{response.status_code}，可能是参数失效，尝试刷新参数并重试")
                                # 强制刷新参数
                                await self._force_refresh_params()
                                # 重试一次，不再重复重试
                                return await _get_videos(retry_on_auth_fail=False)
                            
                            try:
                                response_text = await response.aread()
                                if response_text:
                                    error_text = response_text.decode('utf-8')
                                else:
                                    error_text = "无响应内容"
                            except Exception as read_error:
                                error_text = f"读取响应失败: {str(read_error)}"
                            
                            logger.error(f"获取视频列表失败: {response.status_code}, 错误: {error_text}")
                            return None
                            
                        response_data = response.json()
                        logger.debug(f"获取到视频列表响应，响应数据大小: {len(str(response_data))}")
                        
                        # 添加响应数据的调试信息
                        if "contents" in response_data:
                            logger.debug("响应包含contents字段")
                        elif "onResponseReceivedActions" in response_data:
                            logger.debug("找到onResponseReceivedActions字段，使用分页解析方法")
                        elif "continuationContents" in response_data:
                            logger.debug("找到continuationContents字段，使用续页解析方法")
                        else:
                            logger.debug("响应格式: " + str(list(response_data.keys())))
                        
                        # 解析响应数据
                        items = []
                        next_page_token = None
                        
                        # 处理第一页数据
                        if not page_token:
                            # 添加调试日志
                            logger.debug("开始解析响应数据...")
                            logger.debug(f"响应数据结构: {list(response_data.keys())}")
                            
                            # 尝试从不同的响应结构中获取数据
                            if "contents" in response_data:
                                # 处理第一页数据
                                logger.debug("找到contents字段，开始解析...")
                                # 尝试获取标签页内容
                                contents = response_data.get("contents", {})
                                logger.debug(f"contents结构: {list(contents.keys())}")
                                
                                tabs = contents.get("twoColumnBrowseResultsRenderer", {}).get("tabs", [])
                                logger.debug(f"找到 {len(tabs)} 个标签页")
                                
                                for i, tab in enumerate(tabs):
                                    logger.debug(f"处理第 {i+1} 个标签页")
                                    if "tabRenderer" in tab:
                                        tab_renderer = tab["tabRenderer"]
                                        # 获取标题文本
                                        title = tab_renderer.get("title", {})
                                        logger.debug(f"标签页标题结构: {title}")
                                        
                                        # 处理不同的标题格式
                                        title_text = ""
                                        if isinstance(title, str):
                                            title_text = title.lower()
                                        elif isinstance(title, dict):
                                            if "simpleText" in title:
                                                title_text = title["simpleText"].lower()
                                            elif "runs" in title:
                                                runs = title.get("runs", [])
                                                if runs and isinstance(runs[0], dict):
                                                    title_text = runs[0].get("text", "").lower()
                                        
                                        logger.debug(f"标签页标题文本: {title_text}")
                                        
                                        # 根据 tab_type 处理不同的标签页
                                        target_titles_map = {
                                            "videos": ["videos", "视频"],
                                            "shorts": ["shorts", "短剧", "短视频"],
                                            "playlists": ["playlists", "播放列表", "playlist"]
                                        }
                                        target_titles = target_titles_map.get(tab_type, ["videos", "视频"])
                                        
                                        # 对于shorts，也检查是否包含short关键词（更宽松的匹配）
                                        is_matched = title_text in target_titles
                                        if not is_matched and tab_type == "shorts":
                                            is_matched = "short" in title_text
                                        
                                        logger.debug(f"标签页类型: {tab_type}, 标题: {title_text}, 匹配目标: {target_titles}, 是否匹配: {is_matched}")
                                        
                                        if is_matched:
                                            logger.debug(f"找到{tab_type}标签页 [{title_text}]，开始解析内容列表...")
                                            # 找到视频标签页，解析视频列表
                                            content = tab_renderer.get("content", {})
                                            logger.debug(f"标签页内容结构: {list(content.keys())}")
                                            
                                            if "richGridRenderer" in content:
                                                grid = content["richGridRenderer"]
                                                logger.debug(f"richGridRenderer结构: {list(grid.keys())}")
                                                grid_items = grid.get("contents", [])
                                                logger.debug(f"找到 {len(grid_items)} 个内容项")
                                                
                                                # 处理每个内容项
                                                for item in grid_items:
                                                    if "richItemRenderer" in item:
                                                        video_content = item["richItemRenderer"].get("content", {})
                                                        # 检查是否有videoRenderer（普通视频）或lockupViewModel（新版结构）或shortsLockupViewModel（Shorts）
                                                        if "videoRenderer" in video_content:
                                                            items.append(item)
                                                            logger.debug(f"找到视频: {video_content['videoRenderer'].get('videoId')}")
                                                        elif "lockupViewModel" in video_content:
                                                            items.append(item)
                                                            logger.debug(f"找到视频(新版结构): {video_content['lockupViewModel'].get('contentId')}")
                                                        elif "shortsLockupViewModel" in video_content and tab_type == "shorts":
                                                            # Shorts使用shortsLockupViewModel结构
                                                            items.append(item)
                                                            lockup = video_content["shortsLockupViewModel"]
                                                            video_id = lockup.get("onTap", {}).get("innertubeCommand", {}).get("reelWatchEndpoint", {}).get("videoId")
                                                            logger.debug(f"找到Shorts: {video_id}")
                                                    elif "continuationItemRenderer" in item:
                                                        next_page_token = item["continuationItemRenderer"].get("continuationEndpoint", {}).get("continuationCommand", {}).get("token")
                                                        if next_page_token:
                                                            logger.debug(f"找到下一页token: {next_page_token}")
                                                            
                                            elif "sectionListRenderer" in content:
                                                section_items = content["sectionListRenderer"].get("contents", [])
                                                logger.debug(f"找到 {len(section_items)} 个section项")
                                                
                                                # 处理每个section
                                                for section in section_items:
                                                    if "itemSectionRenderer" in section:
                                                        section_contents = section["itemSectionRenderer"].get("contents", [])
                                                        for content_item in section_contents:
                                                            if "gridRenderer" in content_item:
                                                                grid_items = content_item["gridRenderer"].get("items", [])
                                                                for item in grid_items:
                                                                    if "gridVideoRenderer" in item:
                                                                        items.append(item)
                            elif "continuationContents" in response_data:
                                # 处理续页数据
                                logger.info("处理续页数据...")
                                continuation_contents = response_data.get("continuationContents", {})
                                if "richGridContinuation" in continuation_contents:
                                    grid_continuation = continuation_contents["richGridContinuation"]
                                    grid_items = grid_continuation.get("contents", [])
                                    logger.info(f"续页找到 {len(grid_items)} 个内容项")
                                    
                                    # 处理每个内容项
                                    for item in grid_items:
                                        if "richItemRenderer" in item:
                                            video_content = item["richItemRenderer"].get("content", {})
                                            if "videoRenderer" in video_content:
                                                items.append(item)
                                                logger.debug(f"续页找到视频: {video_content['videoRenderer'].get('videoId')}")
                                            elif "lockupViewModel" in video_content:
                                                items.append(item)
                                                logger.debug(f"续页找到视频(新版结构): {video_content['lockupViewModel'].get('contentId')}")
                                        elif "continuationItemRenderer" in item:
                                            next_page_token = item["continuationItemRenderer"].get("continuationEndpoint", {}).get("continuationCommand", {}).get("token")
                                            if next_page_token:
                                                logger.info(f"续页找到下一页token: {next_page_token}")
                            else:
                                logger.warning("未找到有效的响应数据结构")
                                # 尝试其他可能的结构
                                if "richGridRenderer" in response_data.get("contents", {}):
                                    items = response_data["contents"]["richGridRenderer"].get("contents", [])
                                # 尝试从primaryContents获取
                                elif "primaryContents" in response_data:
                                    primary = response_data["primaryContents"]
                                    if "richGridRenderer" in primary:
                                        items = primary["richGridRenderer"].get("contents", [])
                                    elif "sectionListRenderer" in primary:
                                        primary_items = primary["sectionListRenderer"].get("contents", [])
                                        for primary_item in primary_items:
                                            if "itemSectionRenderer" in primary_item:
                                                section_items = primary_item["itemSectionRenderer"].get("contents", [])
                                                for section_item in section_items:
                                                    if "gridRenderer" in section_item:
                                                        items = section_item["gridRenderer"].get("items", [])
                        
                        # 处理后续页数据
                        else:
                            # 尝试从不同的响应结构中获取数据
                            if "onResponseReceivedActions" in response_data:
                                actions = response_data["onResponseReceivedActions"]
                                for action in actions:
                                    if "appendContinuationItemsAction" in action:
                                        items = action["appendContinuationItemsAction"].get("continuationItems", [])
                                        break
                            
                        # 获取下一页token
                        for item in items:
                            if "continuationItemRenderer" in item:
                                continuation_data = item["continuationItemRenderer"]
                                if "continuationEndpoint" in continuation_data:
                                    next_page_token = continuation_data["continuationEndpoint"].get("continuationCommand", {}).get("token")
                                elif "button" in continuation_data:
                                    next_page_token = continuation_data["button"].get("buttonRenderer", {}).get("command", {}).get("continuationCommand", {}).get("token")
                                items.remove(item)
                                break
                        
                        # 提取视频信息（参考抖音方式）
                        videos = []
                        # 为Shorts生成基准时间戳，用于保持顺序（类似抖音点赞）
                        # 如果没有提供，则生成新的；否则使用提供的值（用于多页获取）
                        if base_timestamp is None:
                            base_timestamp = int(datetime.now().timestamp())
                        
                        for index, item in enumerate(items):
                            video_data = None
                            is_shorts = False
                            
                            if "richItemRenderer" in item:
                                content = item["richItemRenderer"].get("content", {})
                                # 检查是否是Shorts
                                if "shortsLockupViewModel" in content and tab_type == "shorts":
                                    is_shorts = True
                                    lockup = content["shortsLockupViewModel"]
                                    reel_endpoint = lockup.get("onTap", {}).get("innertubeCommand", {}).get("reelWatchEndpoint", {})
                                    video_data = {
                                        "videoId": reel_endpoint.get("videoId"),
                                        "title": lockup.get("overlayMetadata", {}).get("primaryText", {}).get("content", "") or lockup.get("accessibilityText", "").split(",")[0],
                                        "viewCountText": {
                                            "simpleText": lockup.get("overlayMetadata", {}).get("secondaryText", {}).get("content", "0")
                                        },
                                        "thumbnail": {
                                            "thumbnails": reel_endpoint.get("thumbnail", {}).get("thumbnails", [])
                                        },
                                        "publishedTimeText": None,  # Shorts通常没有发布时间信息
                                        "descriptionSnippet": None
                                    }
                                elif "lockupViewModel" in content:
                                    # 新版YouTube页面结构（lockupViewModel替代videoRenderer）
                                    lockup = content["lockupViewModel"]
                                    lvm = lockup.get("metadata", {}).get("lockupMetadataViewModel", {})
                                    cm = lvm.get("metadata", {}).get("contentMetadataViewModel", {})
                                    rows = cm.get("metadataRows", [])

                                    # 提取时长
                                    duration = ""
                                    overlays = lockup.get("contentImage", {}).get("thumbnailViewModel", {}).get("overlays", [])
                                    if overlays:
                                        badges = overlays[0].get("thumbnailBottomOverlayViewModel", {}).get("badges", [])
                                        if badges:
                                            duration = badges[0].get("thumbnailBadgeViewModel", {}).get("text", "")

                                    # 提取观看数和发布时间
                                    view_count = ""
                                    published_time = ""
                                    if rows:
                                        parts = rows[0].get("metadataParts", [])
                                        if len(parts) > 0:
                                            view_count = parts[0].get("text", {}).get("content", "")
                                        if len(parts) > 1:
                                            published_time = parts[1].get("text", {}).get("content", "")

                                    # 提取缩略图
                                    image = lockup.get("contentImage", {}).get("thumbnailViewModel", {}).get("image", {})
                                    thumbnails = image.get("sources", [])

                                    video_data = {
                                        "videoId": lockup.get("contentId", ""),
                                        "title": {"runs": [{"text": lvm.get("title", {}).get("content", "")}]},
                                        "lengthText": {"simpleText": duration},
                                        "viewCountText": {"simpleText": view_count},
                                        "publishedTimeText": {"simpleText": published_time},
                                        "thumbnail": {"thumbnails": thumbnails}
                                    }
                                elif "videoRenderer" in content:
                                    video_data = content["videoRenderer"]
                            elif "gridVideoRenderer" in item:
                                # Shorts可能使用gridVideoRenderer
                                video_data = item["gridVideoRenderer"]
                                if tab_type == "shorts":
                                    is_shorts = True
                            
                            if video_data and video_data.get("videoId"):
                                    # 获取发布时间
                                    published_time = ""
                                    try:
                                        if is_shorts:
                                            # Shorts通常没有发布时间信息，使用递减的时间戳保持顺序（类似抖音点赞）
                                            # 使用 start_index + index 以支持多页获取
                                            global_index = start_index + index
                                            timestamp_with_offset = base_timestamp - global_index
                                            published_time = datetime.fromtimestamp(timestamp_with_offset).strftime("%Y-%m-%dT%H:%M:%S")
                                            logger.debug(f"Shorts {video_data.get('videoId')} 使用递减时间戳: {published_time} (global_index={global_index})")
                                        else:
                                            # 1. 尝试获取精确的发布时间戳
                                            published_time = video_data.get("publishedTime", "")
                                            
                                            # 2. 尝试获取发布日期文本
                                            if not published_time:
                                                date_text = video_data.get("dateText", {}).get("simpleText", "")
                                                if date_text:
                                                    try:
                                                        # 处理不同格式的日期文本
                                                        if "年" in date_text and "月" in date_text:
                                                            # 处理中文日期格式
                                                            date_text = date_text.replace("年", "-").replace("月", "-").replace("日", "")
                                                            date_parts = date_text.split("-")
                                                            if len(date_parts) >= 3:
                                                                published_time = f"{date_parts[0]}-{int(date_parts[1]):02d}-{int(date_parts[2]):02d}"
                                                    except Exception as e:
                                                        logger.error(f"解析日期文本失败: {str(e)}")
                                            
                                            # 3. 尝试解析相对时间文本
                                            if not published_time:
                                                relative_time = video_data.get("publishedTimeText", {}).get("simpleText", "")
                                                if relative_time:
                                                    published_time = parse_relative_time(relative_time)
                                                    
                                            # 只保留日期部分
                                            try:
                                                if published_time:
                                                    # 如果是ISO格式，只保留日期部分
                                                    if "T" in published_time:
                                                        published_time = published_time.split("T")[0]
                                                    # 如果已经是日期格式，保持不变
                                                    elif len(published_time.split("-")) == 3:
                                                        pass
                                                    else:
                                                        logger.debug(f"无法解析的时间格式: {published_time}")
                                                        published_time = datetime.now().strftime("%Y-%m-%d")
                                            except Exception as e:
                                                logger.error(f"转换时间格式失败: {str(e)}")
                                                published_time = datetime.now().strftime("%Y-%m-%d")
                                                
                                            logger.debug(f"视频 {video_data.get('videoId')} 的发布时间: {published_time}")
                                        
                                    except Exception as e:
                                        logger.error(f"解析发布时间失败: {str(e)}")
                                        published_time = datetime.now().strftime("%Y-%m-%d")

                                    # 检查是否是旧视频
                                    if not is_shorts:  # Shorts不使用日期比较
                                        try:
                                            video_date = datetime.strptime(published_time, "%Y-%m-%d")
                                            if last_video_time:  # 只有当last_video_time不为空时才比较
                                                try:
                                                    last_date = datetime.strptime(last_video_time, "%Y-%m-%d")
                                                    if video_date < last_date:
                                                        logger.debug(f"找到旧视频 {video_data.get('videoId')}，停止获取更多视频")
                                                        return {
                                                            "items": videos,
                                                            "nextPageToken": None  # 不返回下一页token，强制停止获取
                                                        }
                                                    elif video_date == last_date:
                                                        # 同一天的视频，需要进一步检查视频ID
                                                        logger.debug(f"找到同一天视频 {video_data.get('videoId')}，继续检查")
                                                except Exception as e:
                                                    logger.debug(f"解析last_video_time失败: {str(e)}")
                                        except Exception as e:
                                            logger.debug(f"解析视频日期失败: {str(e)}")

                                    # 提取标题
                                    title = ""
                                    if is_shorts:
                                        title = video_data.get("title", "")
                                    else:
                                        title_obj = video_data.get("title", {})
                                        if isinstance(title_obj, dict):
                                            if "runs" in title_obj and title_obj["runs"]:
                                                title = title_obj["runs"][0].get("text", "")
                                            elif "simpleText" in title_obj:
                                                title = title_obj["simpleText"]
                                        else:
                                            title = str(title_obj) if title_obj else ""
                                    
                                    # 提取描述
                                    description = ""
                                    if not is_shorts:
                                        desc_obj = video_data.get("descriptionSnippet", {})
                                        if isinstance(desc_obj, dict):
                                            if "runs" in desc_obj and desc_obj["runs"]:
                                                description = desc_obj["runs"][0].get("text", "")
                                            elif "simpleText" in desc_obj:
                                                description = desc_obj["simpleText"]
                                    
                                    # 提取缩略图
                                    thumbnail_url = ""
                                    thumbnails = video_data.get("thumbnail", {}).get("thumbnails", [])
                                    if thumbnails:
                                        thumbnail_url = thumbnails[-1].get("url", "")
                                    
                                    # 提取观看次数
                                    view_count = "0"
                                    view_count_text = video_data.get("viewCountText", {})
                                    if isinstance(view_count_text, dict):
                                        view_count_str = view_count_text.get("simpleText", "0")
                                    else:
                                        view_count_str = str(view_count_text) if view_count_text else "0"
                                    if view_count_str:
                                        view_count = view_count_str.split(" ")[0].replace(",", "").replace("次", "")

                                    videos.append({
                                        "id": {
                                            "videoId": video_data.get("videoId")
                                        },
                                        "snippet": {
                                            "title": title,
                                            "description": description,
                                            "thumbnails": {
                                                "high": {
                                                    "url": thumbnail_url
                                                }
                                            },
                                            "publishedAt": published_time
                                        },
                                        "statistics": {
                                            "viewCount": view_count,
                                            "likeCount": "0",  # YouTube不再公开显示点赞数
                                            "commentCount": "0"  # 需要单独请求获取
                                        }
                                    })
                        
                        logger.debug(f"解析完成：找到 {len(items)} 个原始项，提取到 {len(videos)} 个视频")
                        
                        # 如果没有找到视频，记录详细的调试信息
                        if len(videos) == 0:
                            logger.warning(f"未找到任何视频！标签页类型: {tab_type}")
                            logger.warning(f"响应数据结构: {list(response_data.keys()) if response_data else 'None'}")
                            if response_data and "contents" in response_data:
                                contents = response_data.get("contents", {})
                                if "twoColumnBrowseResultsRenderer" in contents:
                                    tabs = contents["twoColumnBrowseResultsRenderer"].get("tabs", [])
                                    logger.warning(f"找到 {len(tabs)} 个标签页")
                                    for i, tab in enumerate(tabs):
                                        if "tabRenderer" in tab:
                                            tab_title = tab["tabRenderer"].get("title", {})
                                            if isinstance(tab_title, dict):
                                                title_text = tab_title.get("simpleText", "") or (tab_title.get("runs", [{}])[0].get("text", "") if tab_title.get("runs") else "")
                                            else:
                                                title_text = str(tab_title)
                                            logger.warning(f"标签页 {i+1}: {title_text}")
                        
                        await self._update_activity()
                        
                        # 构建返回结果，包含真实的频道ID（如果与传入的不同）
                        result = {
                            "items": videos,
                            "nextPageToken": next_page_token
                        }
                        
                        # 如果获取到的真实频道ID与传入的不同，添加到返回结果中
                        if browse_id and browse_id != channel_id and browse_id.startswith('UC') and len(browse_id) == 24:
                            result["real_channel_id"] = browse_id
                            logger.info(f"检测到频道ID更新：{channel_id} → {browse_id}")
                        
                        # 关闭临时页面
                        if temp_page_key:
                            try:
                                await self._browser.close_page(temp_page_key)
                                logger.debug(f"已关闭临时页面: {temp_page_key}")
                            except Exception as close_error:
                                logger.warning(f"关闭临时页面失败: {close_error}")
                        
                        return result
                        
                except httpx.RequestError as req_error:
                    await self._update_activity()
                    logger.warning(f"HTTP请求错误: {type(req_error).__name__}")
                    raise req_error
                except httpx.TimeoutException as timeout_error:
                    await self._update_activity()
                    logger.warning(f"请求超时")
                    raise timeout_error
                except httpx.HTTPStatusError as status_error:
                    await self._update_activity()
                    logger.warning(f"HTTP状态错误: {status_error.response.status_code}")
                    raise status_error
                except Exception as e:
                    await self._update_activity()
                    logger.error(f"获取视频列表失败: {str(e)}")
                    # 发生异常时也要关闭临时页面
                    if temp_page_key:
                        try:
                            await self._browser.close_page(temp_page_key)
                            logger.debug(f"异常时已关闭临时页面: {temp_page_key}")
                        except Exception as close_error:
                            logger.warning(f"异常时关闭临时页面失败: {close_error}")
                    raise e
            except Exception as e:
                await self._update_activity()
                logger.error(f"获取视频列表失败: {str(e)}")
                raise e

        # 使用多标签页执行请求，并应用重试机制
        return await self._request_with_retry(self._execute_with_page, channel_id, _get_videos)

    async def parse_channel_url(self, url: str) -> dict:
        """解析YouTube频道链接或频道ID/handle
        
        Args:
            url: YouTube频道链接、频道ID（如 UCxxxxx）或频道handle（如 @channelname 或 channelname）
            
        Returns:
            dict: 包含频道信息的字典
        """
        try:
            # 检查缓存
            current_time = time.time()
            if url in self._channel_info_cache:
                cache_entry = self._channel_info_cache[url]
                if current_time - cache_entry["timestamp"] < self._channel_info_cache_duration:
                    logger.info(f"使用缓存的频道解析结果: {url}")
                    return cache_entry["data"]
            
            # 确保浏览器已初始化并处于可用状态
            await self._ensure_browser_ready()

            # 原始输入（用于缓存键）
            original_input = url
            
            # 如果输入不是URL，可能是直接输入的频道ID或handle
            if not url.startswith("http"):
                # 检查是否是频道ID格式（UC开头，24个字符）
                if url.startswith("UC") and len(url) == 24:
                    # 频道ID格式
                    url = f"https://www.youtube.com/channel/{url}"
                    logger.info(f"检测到直接输入的频道ID，构建完整URL: {url}")
                elif url.startswith("@"):
                    # 带@符号的handle
                    handle = url.lstrip("@")
                    url = f"https://www.youtube.com/@{handle}"
                    logger.info(f"检测到直接输入的handle（带@），构建完整URL: {url}")
                elif url and not url.startswith("http") and len(url) > 1:
                    # 不带@符号的handle
                    url = f"https://www.youtube.com/@{url}"
                    logger.info(f"检测到直接输入的handle（不带@），构建完整URL: {url}")
                else:
                    raise ValueError(f"无法识别输入格式: {original_input}，请使用：1) 频道链接（如：https://www.youtube.com/@channelname）2) 频道ID（如：UCxxxxx）3) 频道handle（如：@channelname 或 channelname）")
            else:
                # 规范化URL（确保有协议）
                if not url.startswith("http"):
                    url = "https://" + url
            
            # URL解码，处理中文等特殊字符
            decoded_url = urllib.parse.unquote(url)
            logger.info(f"原始输入: {original_input}")
            logger.info(f"处理后的URL: {decoded_url}")
            
            # 从URL中提取频道名称，支持多种格式
            channel_name = None
            
            # 尝试从@符号后提取
            if "@" in decoded_url:
                parts = decoded_url.split("@")
                if len(parts) > 1:
                    channel_part = parts[1]
                    # 移除路径部分
                    if "/" in channel_part:
                        channel_name = channel_part.split("/")[0]
                    else:
                        channel_name = channel_part
            
            # 如果还是没有提取到，尝试其他方法
            if not channel_name:
                # 尝试从URL路径中提取
                if "/channel/" in decoded_url:
                    # 频道ID格式
                    channel_match = re.search(r'/channel/([^/?]+)', decoded_url)
                    if channel_match:
                        channel_name = channel_match.group(1)
                        logger.info(f"从频道ID格式提取到: {channel_name}")
                elif "/c/" in decoded_url:
                    # 自定义URL格式
                    channel_match = re.search(r'/c/([^/?]+)', decoded_url)
                    if channel_match:
                        channel_name = channel_match.group(1)
                        logger.info(f"从自定义URL格式提取到: {channel_name}")
                elif "/user/" in decoded_url:
                    # 用户格式
                    channel_match = re.search(r'/user/([^/?]+)', decoded_url)
                    if channel_match:
                        channel_name = channel_match.group(1)
                        logger.info(f"从用户格式提取到: {channel_name}")
            
            if not channel_name:
                raise ValueError(f"无法从输入中提取频道信息: {original_input}，请使用：1) 频道链接（如：https://www.youtube.com/@channelname）2) 频道ID（如：UCxxxxx）3) 频道handle（如：@channelname 或 channelname）")
            
            logger.info(f"提取到的频道名称: {channel_name}")

            # 🔧 方案1：使用统一管理器创建临时页面，纳入管理和LRU保护
            # 使用特殊的page_key标识这是临时解析页面
            temp_page_key = f"youtube:temp_parse_{channel_name}"
            temp_page = await self._browser.get_page(temp_page_key)
            
            if not temp_page:
                raise Exception("创建临时解析页面失败")
            
            try:
                # 访问频道页面并等待加载
                logger.info(f"访问频道页面: {decoded_url}")
                await temp_page.goto(decoded_url, wait_until="domcontentloaded", timeout=30000)
                
                # 优化：减少等待时间，因为页面通常很快加载
                await asyncio.sleep(1)
                
                # 优化：使用更智能的等待策略
                # 由于页面通常很快加载，我们使用更短的超时时间
                # 即使超时也不影响后续的数据提取
                try:
                    # 等待频道标题加载（减少到0.8秒）
                    await temp_page.wait_for_selector('meta[property="og:title"]', timeout=800)
                except Exception as e:
                    logger.debug(f"等待频道标题超时（正常现象）: {str(e)}")
                
                try:
                    # 等待订阅数加载（减少到0.8秒）
                    await temp_page.wait_for_selector('#subscriber-count', timeout=800)
                except Exception as e:
                    logger.debug(f"等待订阅数超时（正常现象）: {str(e)}")
                
                try:
                    # 等待视频标签加载（减少到0.8秒）
                    await temp_page.wait_for_selector('yt-tab-shape', timeout=800)
                except Exception as e:
                    logger.debug(f"等待视频标签超时（正常现象）: {str(e)}")
                
                # 优化：减少额外等待时间，因为页面已经加载完成
                # 从日志看，即使不等待这些元素，数据提取仍然成功
                await asyncio.sleep(0.2)
                
                # 获取统计数据
                stats = {}
                try:
                    # 使用更简单的方法：从页面文本中直接提取数据
                    page_text = await temp_page.evaluate('() => document.body.textContent')
                    
                    # 使用统一的工具函数提取订阅者数
                    subscriber_count = parse_count_from_text(page_text, SUBSCRIBER_PATTERNS)
                    if subscriber_count:
                        stats['subscriberCount'] = str(subscriber_count)
                        logger.debug(f"找到订阅者数: {subscriber_count}")
                    
                    # 使用统一的工具函数提取视频数
                    video_count = parse_count_from_text(page_text, VIDEO_PATTERNS)
                    if video_count:
                        stats['videoCount'] = str(video_count)
                        logger.debug(f"找到视频数: {video_count}")
                    
                    # 如果通过正则表达式没有找到，尝试从页面元素中获取
                    if not subscriber_count:
                        try:
                            # 尝试从页面元素获取订阅者数
                            sub_element = await temp_page.query_selector('#subscriber-count, [data-subscriber-count], .subscriber-count')
                            if sub_element:
                                sub_text = await sub_element.text_content()
                                if sub_text:
                                    # 清理文本并尝试提取数字
                                    sub_text = sub_text.strip()
                                    sub_match = re.search(r'(\d+(?:\.\d+)?[亿万千MK]?)', sub_text)
                                    if sub_match:
                                        sub_value = sub_match.group(1)
                                        # 转换数字
                                        if '亿' in sub_value:
                                            subscriber_count = int(float(sub_value.replace('亿', '')) * 100000000)
                                        elif '万' in sub_value:
                                            subscriber_count = int(float(sub_value.replace('万', '')) * 10000)
                                        elif '千' in sub_value:
                                            subscriber_count = int(float(sub_value.replace('千', '')) * 1000)
                                        elif 'M' in sub_value:
                                            subscriber_count = int(float(sub_value.replace('M', '')) * 1000000)
                                        elif 'K' in sub_value:
                                            subscriber_count = int(float(sub_value.replace('K', '')) * 1000)
                                        else:
                                            subscriber_count = int(float(sub_value))
                                        
                                        stats['subscriberCount'] = str(subscriber_count)
                                        logger.info(f"从页面元素获取到订阅者数: {subscriber_count}")
                        except Exception as e:
                            logger.debug(f"从页面元素获取订阅者数失败: {str(e)}")
                    
                    if not video_count:
                        try:
                            # 尝试从页面元素获取视频数
                            video_element = await temp_page.query_selector('[data-video-count], .video-count, .videos-count')
                            if video_element:
                                video_text = await video_element.text_content()
                                if video_text:
                                    # 清理文本并尝试提取数字
                                    video_text = video_text.strip()
                                    video_match = re.search(r'(\d+(?:,\d+)*)', video_text)
                                    if video_match:
                                        video_count = int(video_match.group(1).replace(',', ''))
                                        stats['videoCount'] = str(video_count)
                                        logger.debug(f"从页面元素获取到视频数: {video_count}")
                        except Exception as e:
                            logger.debug(f"从页面元素获取视频数失败: {str(e)}")
                    
                    logger.info(f"从页面获取到的统计数据: {json.dumps(stats)}")
                except Exception as e:
                    logger.error(f"获取统计数据失败: {str(e)}")
                
                # 备用方案：如果正则表达式和页面元素都没有获取到数据，尝试其他方法
                if not stats.get('subscriberCount') or not stats.get('videoCount'):
                    try:
                        logger.info("尝试备用方案获取统计数据...")
                        
                        # 方法1：尝试从ytInitialData获取
                        yt_data = await temp_page.evaluate("""
                            () => {
                                try {
                                    if (window.ytInitialData && window.ytInitialData.header) {
                                        const header = window.ytInitialData.header;
                                        const stats = {};
                                        
                                        // 尝试不同的header结构
                                        if (header.c4TabbedHeaderRenderer) {
                                            const renderer = header.c4TabbedHeaderRenderer;
                                            if (renderer.subscriberCountText) {
                                                stats.subscriberCount = renderer.subscriberCountText.simpleText;
                                            }
                                            if (renderer.videosCountText && renderer.videosCountText.runs) {
                                                stats.videoCount = renderer.videosCountText.runs[0].text;
                                            }
                                        } else if (header.c4TabbedHeaderRenderer) {
                                            const renderer = header.c4TabbedHeaderRenderer;
                                            if (renderer.subscriberCountText) {
                                                stats.subscriberCount = renderer.subscriberCountText.simpleText;
                                            }
                                        }
                                        
                                        // 尝试从其他位置获取
                                        if (!stats.subscriberCount) {
                                            const subElements = document.querySelectorAll('[data-subscriber-count], .subscriber-count, #subscriber-count');
                                            for (const el of subElements) {
                                                const text = el.textContent || el.innerText;
                                                if (text && text.match(/\\d+/)) {
                                                    stats.subscriberCount = text.trim();
                                                    break;
                                                }
                                            }
                                        }
                                        
                                        if (!stats.videoCount) {
                                            const videoElements = document.querySelectorAll('[data-video-count], .video-count, .videos-count');
                                            for (const el of videoElements) {
                                                const text = el.textContent || el.innerText;
                                                if (text && text.match(/\\d+/)) {
                                                    stats.videoCount = text.trim();
                                                    break;
                                                }
                                            }
                                        }
                                        
                                        return stats;
                                    }
                                    return {};
                                } catch (e) {
                                    console.error('Error in ytInitialData fallback:', e);
                                    return {};
                                }
                            }
                        """)
                        
                        if yt_data:
                            logger.info(f"从ytInitialData获取到备用数据: {json.dumps(yt_data)}")
                            
                            # 处理订阅者数
                            if yt_data.get('subscriberCount') and not stats.get('subscriberCount'):
                                sub_text = yt_data['subscriberCount']
                                # 尝试解析数字
                                sub_match = re.search(r'(\d+(?:\.\d+)?[亿万千MK]?)', sub_text)
                                if sub_match:
                                    sub_value = sub_match.group(1)
                                    # 转换数字
                                    if '亿' in sub_value:
                                        subscriber_count = int(float(sub_value.replace('亿', '')) * 100000000)
                                    elif '万' in sub_value:
                                        subscriber_count = int(float(sub_value.replace('万', '')) * 10000)
                                    elif '千' in sub_value:
                                        subscriber_count = int(float(sub_value.replace('千', '')) * 1000)
                                    elif 'M' in sub_value:
                                        subscriber_count = int(float(sub_value.replace('M', '')) * 1000000)
                                    elif 'K' in sub_value:
                                        subscriber_count = int(float(sub_value.replace('K', '')) * 1000)
                                    else:
                                        subscriber_count = int(float(sub_value.replace(',', '')))
                                    
                                    stats['subscriberCount'] = str(subscriber_count)
                                    logger.info(f"备用方案获取到订阅者数: {subscriber_count}")
                            
                            # 处理视频数
                            if yt_data.get('videoCount') and not stats.get('videoCount'):
                                video_text = yt_data['videoCount']
                                # 尝试解析数字
                                video_match = re.search(r'(\d+(?:,\d+)*)', video_text)
                                if video_match:
                                    video_count = int(video_match.group(1).replace(',', ''))
                                    stats['videoCount'] = str(video_count)
                                    logger.debug(f"备用方案获取到视频数: {video_count}")
                        
                    except Exception as e:
                        logger.error(f"备用方案获取统计数据失败: {str(e)}")
                
                # 最终检查：如果还是没有获取到数据，记录警告
                if not stats.get('subscriberCount'):
                    logger.warning(f"无法获取频道 {channel_name} 的订阅者数")
                if not stats.get('videoCount'):
                    logger.warning(f"无法获取频道 {channel_name} 的视频数")
                
                # 获取频道基本信息
                try:
                    channel_info = await temp_page.evaluate("""
                        () => {
                            const info = {};
                            try {
                                // 从页面元素获取信息
                                info.title = document.querySelector('meta[property="og:title"]')?.content;
                                info.description = document.querySelector('meta[property="og:description"]')?.content;
                                info.image = document.querySelector('meta[property="og:image"]')?.content;
                            } catch (e) {
                                console.error('Error extracting page info:', e);
                            }
                            return info;
                        }
                    """)
                except Exception as e:
                    logger.error(f"获取频道基本信息失败: {str(e)}")
                    channel_info = {}

                # 添加调试信息
                logger.debug(f"频道 {channel_name} 最终统计数据:")
                logger.debug(f"  订阅者数: {stats.get('subscriberCount', '未获取到')}")
                logger.debug(f"  视频数: {stats.get('videoCount', '未获取到')}")
                logger.debug(f"  频道标题: {channel_info.get('title', '未获取到')}")
                logger.debug(f"  频道描述: {channel_info.get('description', '未获取到')[:100] if channel_info.get('description') else '未获取到'}...")
                logger.debug(f"  频道头像: {channel_info.get('image', '未获取到')}")
                
                # 获取真实的频道ID（从页面元数据或URL中提取）
                channel_id = None
                try:
                    # 尝试从页面元素获取真实的频道ID
                    channel_id_info = await temp_page.evaluate("""
                        () => {
                            const metaChannelId = document.querySelector('meta[itemprop="channelId"]')?.content;
                            const ogUrl = document.querySelector('meta[property="og:url"]')?.content;
                            const canonicalUrl = document.querySelector('link[rel="canonical"]')?.href;
                            
                            let channelId = metaChannelId;
                            
                            if (!channelId && ogUrl) {
                                const match = ogUrl.match(/channel\/(UC[\w-]{22})/);
                                if (match) channelId = match[1];
                            }
                            
                            if (!channelId && canonicalUrl) {
                                const match = canonicalUrl.match(/channel\/(UC[\w-]{22})/);
                                if (match) channelId = match[1];
                            }
                            
                            return { channelId };
                        }
                    """)
                    
                    if channel_id_info and channel_id_info.get('channelId'):
                        channel_id = channel_id_info['channelId']
                        logger.info(f"获取到真实的频道ID: {channel_id}")
                except Exception as e:
                    logger.warning(f"获取频道ID失败: {str(e)}")
                
                # 如果channel_name是频道ID格式（UC开头24位），直接使用
                if not channel_id and channel_name.startswith('UC') and len(channel_name) == 24:
                    channel_id = channel_name
                
                # 构建返回数据
                result = {
                    "channel_id": channel_id or channel_name,  # 优先使用真实频道ID
                    "channel_name": channel_name,  # 保留原始channel_name
                    "name": channel_info.get("title", ""),
                    "nickname": channel_info.get("title", ""),  # 向后兼容
                    "user_id": channel_id or channel_name,  # 向后兼容
                    "signature": channel_info.get("description", ""),
                    "avatar_url": channel_info.get("image", ""),
                    "video_count": int(stats.get("videoCount", "0")) if stats.get("videoCount") else 0,
                    "follower_count": int(stats.get("subscriberCount", "0")) if stats.get("subscriberCount") else 0,
                    "subscriber_count": int(stats.get("subscriberCount", "0")) if stats.get("subscriberCount") else 0,
                    "like_count": 0  # YouTube不直接提供点赞总数
                }
                
                # 保存到缓存
                self._channel_info_cache[url] = {
                    "data": result,
                    "timestamp": time.time()
                }
                logger.info(f"已缓存频道解析结果: {url}")
                
                return result
                
            except Exception as e:
                logger.error(f"解析YouTube频道链接失败: {str(e)}")
                raise HTTPException(status_code=400, detail=f"解析YouTube频道链接失败: {str(e)}")
            finally:
                # 🔧 方案1：使用统一管理器关闭临时页面
                try:
                    await self._browser.close_page(temp_page_key)
                    logger.info(f"临时解析页面 [{temp_page_key}] 已关闭")
                except Exception as e:
                    logger.warning(f"关闭临时页面失败: {str(e)}")
                    
        except Exception as e:
            logger.error(f"解析YouTube频道链接失败: {str(e)}")
            raise HTTPException(status_code=400, detail=f"解析YouTube频道链接失败: {str(e)}")

    async def get_channel_info(self, channel_id: str) -> dict:
        """获取频道信息
        
        Args:
            channel_id: 频道ID
            
        Returns:
            dict: 包含频道信息的字典
        """
        async def _get_info(retry_on_auth_fail: bool = True):
            await self._update_activity()
            try:
                # 确保浏览器已初始化并处于可用状态
                await self._ensure_browser_ready()
                
                # 获取用户cookie
                cookies = await self.context.cookies()
                cookie_str = "; ".join([f"{c['name']}={c['value']}" for c in cookies])

                # 构建请求头
                headers = {
                    "authority": "www.youtube.com",
                    "accept": "*/*",
                    "accept-language": "zh-CN,zh;q=0.9",
                    "cookie": cookie_str,
                    "referer": f"https://www.youtube.com/channel/{channel_id}",
                    "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
                }

                # 构建请求体
                data = {
                    "browseId": channel_id,
                    "context": {
                        "client": {
                            "clientName": "WEB",
                            "clientVersion": "2.20240103.01.00"
                        }
                    }
                }

                url = "https://www.youtube.com/youtubei/v1/browse"
                async with httpx.AsyncClient() as client:
                    response = await client.post(url, json=data, headers=headers)
                    
                    if response.status_code != 200:
                        # 检查是否需要刷新参数重试
                        if response.status_code in [401, 403] and retry_on_auth_fail:
                            logger.warning(f"YouTube API返回{response.status_code}，可能是参数失效，尝试刷新参数并重试")
                            await self._force_refresh_params()
                            return await _get_info(retry_on_auth_fail=False)
                        
                        logger.error(f"获取频道信息失败: {response.status_code}")
                        raise httpx.HTTPStatusError(f"HTTP {response.status_code}", request=None, response=response)
                        
                    data = response.json()
                    logger.info("获取到频道信息")
                    await self._update_activity()
                    return data
            except Exception as e:
                await self._update_activity()
                logger.error(f"获取频道信息失败: {str(e)}")
                raise e

        # 使用多标签页执行请求，并应用重试机制
        return await self._request_with_retry(self._execute_with_page, channel_id, _get_info)

    async def _is_global_params_valid(self) -> bool:
        """检查全局参数缓存是否有效
        
        直接使用api_params_cache统一管理
        """
        cached = api_params_cache.get(self._platform)
        if cached:
            # 检查关键参数是否存在
            required_params = ['visitorData', 'clientVersion', 'clientName', 'key']
            if all(cached.get(param) for param in required_params):
                logger.debug("YouTube参数缓存有效")
                return True
            else:
                logger.warning("缓存缺少关键参数")
                
        return False

    async def _cache_youtube_params(self, params: dict):
        """缓存全局YouTube参数
        
        使用api_params_cache统一管理
        """
        # 创建副本以避免修改原字典
        cache_params = params.copy()
        
        # 移除频道特定的参数，防止污染全局缓存
        keys_to_remove = ['browseId', 'real_browse_id', 'channelId', 'params']
        for key in keys_to_remove:
            if key in cache_params:
                del cache_params[key]
        
        # 保存到统一缓存管理器
        api_params_cache.set(self._platform, cache_params)
        logger.info("已更新全局YouTube参数缓存")

    async def _get_cached_youtube_params(self, channel_id: str = None) -> dict:
        """获取缓存的YouTube参数（channel_id参数保留用于兼容）"""
        if await self._is_global_params_valid():
            cached = api_params_cache.get(self._platform)
            return cached if cached else {}
        return {}

    async def _clear_params_cache(self, channel_id: str = None):
        """清理参数缓存"""
        api_params_cache.invalidate(self._platform)
        logger.info("已清理全局参数缓存")

    async def _force_refresh_params(self, channel_id: str = None):
        """强制刷新参数"""
        await self._clear_params_cache()
        logger.info("已强制刷新全局参数")

    async def get_page(self, channel_id: str):
        """获取或创建频道对应的页面（通过统一管理器）"""
        try:
            # 首先确保浏览器处于可用状态
            await self._ensure_browser_ready()
            
            # 构造页面键：youtube:channel_id
            page_key = f"youtube:{channel_id}"
            
            # 通过统一管理器获取页面
            page = await self._browser.get_page(page_key)
            
            if page:
                logger.debug(f"获取到频道 {channel_id} 的页面（来自统一管理器）")
                return page
            else:
                logger.error(f"统一管理器返回 None，频道 {channel_id} 页面创建失败")
                return None
                    
        except Exception as e:
            logger.error(f"获取页面失败: {str(e)}")
            raise e
    
    async def _is_page_valid(self, page):
        """检查页面是否仍然有效"""
        try:
            await page.evaluate("1")  # 简单测试
            return True
        except Exception as e:
            logger.warning(f"页面有效性检查失败: {str(e)}")
            return False
    
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
            
            # YouTube使用多标签页模式，不需要创建默认页面
            # 每个频道/播放列表会在实际使用时通过 get_page() 创建独立标签页
            # 避免创建不必要的空白标签页
            
            return True
        except Exception as e:
            logger.error(f"确保浏览器就绪失败: {str(e)}")
            # 如果失败，强制重新初始化
            await self._force_reinitialize_browser()
            return True
    
    async def _force_reinitialize_browser(self):
        """强制重新初始化浏览器"""
        # 若正在进行初始化，等待其完成，避免并发重建
        if getattr(self, "_is_initializing", False):
            for _ in range(100):  # 最多等待约5秒
                if self.context:
                    return
                await asyncio.sleep(0.05)
        self._is_initializing = True
        try:
            logger.info("开始强制重新初始化浏览器...")
            
            # 先完整关闭浏览器与Playwright，避免残留进程/文件句柄
            try:
                await self.close_browser()
            except Exception:
                pass
            
            # 清理参数缓存
            await self._clear_params_cache()
            
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
        finally:
            self._is_initializing = False
    
    async def _cleanup_all_pages(self):
        """清理所有YouTube频道页面（通过统一管理器）"""
        try:
            logger.info("清理所有YouTube频道页面...")
            # 统一管理器会自动管理页面清理
            logger.info("所有YouTube频道页面清理完成")
        except Exception as e:
            logger.error(f"清理页面失败: {str(e)}")
    
    async def _queue_request(self, channel_id: str, request_func):
        """将请求加入等待队列"""
        future = asyncio.Future()
        await self.waiting_queue.put((channel_id, request_func, future))
        
        # 启动队列处理任务
        asyncio.create_task(self._process_waiting_queue())
        
        return await future
    
    async def _process_waiting_queue(self):
        """处理等待队列"""
        while not self.waiting_queue.empty():
            # 获取队列中的请求
            channel_id, request_func, future = await self.waiting_queue.get()
            
            try:
                result = await self._execute_with_page(channel_id, request_func)
                future.set_result(result)
            except Exception as e:
                future.set_exception(e)
                logger.error(f"处理等待队列请求失败: {str(e)}")
    
    async def _execute_with_page(self, channel_id: str, request_func):
        """使用指定页面执行请求"""
        return await request_func()

    async def _monitor_playwright_processes(self):
        """监控Playwright进程数量，防止进程泄漏"""
        while True:
            try:
                await asyncio.sleep(300)  # 每5分钟检查一次
                # 使用YouTube平台管理器获取状态（保持向后兼容）
                status = youtube_playwright_manager.get_status()
                if status["current_count"] > status["max_instances"]:
                    logger.warning(f"检测到Playwright进程数量异常: {status['current_count']} > {status['max_instances']}")
                    # 强制清理多余的进程
                    if self._playwright:
                        await self._playwright.stop()
                        self._playwright = None
                    # 释放实例
                    if hasattr(self, '_instance_id'):
                        await youtube_playwright_manager.release_instance(self._instance_id)
                        self._instance_id = None
                    logger.info("已强制清理多余的Playwright进程")
            except Exception as e:
                logger.error(f"监控Playwright进程时出错: {str(e)}")
            except asyncio.CancelledError:
                logger.info("Playwright进程监控任务被取消")
                break

youtube_api = YouTubeAPI()

@router.on_event("startup")
async def startup_event():
    """FastAPI启动时初始化YouTube API"""
    logger.info("YouTubeAPI启动 - 实例ID: %s", id(youtube_api))
    try:
        # 浏览器采用懒加载，worker已在main.py中启动
        # 统一浏览器管理器会自动管理清理任务
        logger.info("YouTubeAPI初始化完成（浏览器采用懒加载，统一管理）")
    except Exception as e:
        logger.error(f"YouTubeAPI启动失败: {str(e)}")
        raise

@router.on_event("shutdown")
async def shutdown_event():
    """FastAPI关闭时清理YouTubeAPI"""
    logger.info(f"YouTubeAPI关闭 - 实例ID: {id(youtube_api)}")
    try:
        await youtube_api.stop_worker()
        logger.info("YouTubeAPI工作任务已停止")
        await youtube_api.close_browser()
        logger.info("YouTubeAPI浏览器已关闭")
        logger.info("YouTubeAPI清理完成")
    except Exception as e:
        logger.error(f"YouTubeAPI关闭失败: {str(e)}")
        raise

@router.post("/login")
async def init_login(current_user: User = Depends(get_current_user)):
    """启动YouTube登录流程"""
    logger.info(f"YouTube登录 - 使用实例ID: {id(youtube_api)}")
    try:
        result = await youtube_api.login()
        # 检查是否是用户取消登录
        if result.get("cancelled"):
            logger.info("YouTube登录已被用户取消")
            return result  # 返回200状态码，表示正常操作
        logger.info("YouTube登录流程启动成功")
        return result
    except Exception as e:
        logger.error(f"YouTube登录流程启动失败: {str(e)}")
        raise

@router.post("/close")
async def close_browser(current_user: User = Depends(get_current_user)):
    """关闭YouTube浏览器"""
    logger.info(f"YouTube关闭浏览器 - 使用实例ID: {id(youtube_api)}")
    try:
        await youtube_api.close_browser()
        logger.info("YouTube浏览器关闭成功")
        return {"message": "浏览器已关闭"}
    except Exception as e:
        logger.error(f"YouTube浏览器关闭失败: {str(e)}")
        raise 

@router.post("/clean")
async def clean_browser(current_user: User = Depends(get_current_user)):
    """清理浏览器文件"""
    try:
        logger.info(f"YouTube清理浏览器 - 使用实例ID: {id(youtube_api)}")
        result = await youtube_api.clean_browser()
        logger.info("YouTube浏览器清理成功")
        return result
    except Exception as e:
        logger.error(f"YouTube浏览器清理失败: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/health_check")
async def browser_health_check():
    """检查浏览器健康状态，如果异常则尝试恢复"""
    try:
        logger.info("开始YouTube浏览器健康检查...")
        
        # 检查浏览器状态
        is_valid = await youtube_api._is_browser_context_valid()
        if not is_valid:
            logger.warning("YouTube浏览器状态异常，尝试恢复...")
            await youtube_api._force_reinitialize_browser()
            return {"status": "recovered", "message": "YouTube浏览器已恢复"}
        else:
            logger.info("YouTube浏览器状态正常")
            return {"status": "healthy", "message": "YouTube浏览器状态正常"}
            
    except Exception as e:
        logger.error(f"YouTube浏览器健康检查失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"健康检查失败: {str(e)}")

@router.post("/force_reinit")
async def force_reinitialize_browser(current_user: User = Depends(get_current_user)):
    """强制重新初始化YouTube浏览器"""
    try:
        logger.info("强制重新初始化YouTube浏览器...")
        await youtube_api._force_reinitialize_browser()
        return {"message": "YouTube浏览器重新初始化成功"}
    except Exception as e:
        logger.error(f"强制重新初始化YouTube浏览器失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"重新初始化失败: {str(e)}")

@router.get("/playwright_status")
async def get_playwright_status(current_user: User = Depends(get_current_user)):
    """获取Playwright实例管理器状态"""
    try:
        # 获取全局状态（包含所有平台）
        global_status = playwright_manager.get_status()
        # 也获取YouTube平台状态（向后兼容）
        youtube_status = youtube_playwright_manager.get_status()
        return {
            "message": "Playwright实例状态",
            "youtube_status": youtube_status,  # 平台级状态（向后兼容）
            "global_status": global_status  # 全局状态（新功能）
        }
    except Exception as e:
        logger.error(f"获取Playwright状态失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"获取状态失败: {str(e)}")

@router.post("/reset_playwright_count")
async def reset_playwright_count(current_user: User = Depends(get_current_user)):
    """重置Playwright实例计数（紧急修复用）"""
    try:
        logger.warning("手动重置Playwright实例计数...")
        # 这里可以添加重置逻辑
        return {"message": "重置成功"}
    except Exception as e:
        logger.error(f"重置失败: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/parse-channel")
async def parse_channel_endpoint(request: dict, current_user: User = Depends(get_current_user)):
    """解析YouTube频道链接并返回频道信息
    
    Body:
        {
            "url": "https://www.youtube.com/@channelname"
        }
    """
    try:
        url = request.get("url")
        if not url:
            raise HTTPException(status_code=400, detail="缺少url参数")
        
        result = await youtube_api.parse_channel_url(url)
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"解析频道链接失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"解析频道链接失败: {str(e)}")

@router.get("/playlists")
async def get_channel_playlists(channel_id: str, current_user: User = Depends(get_current_user)):
    """获取频道的所有播放列表
    
    Args:
        channel_id: 频道ID（UC开头24位）或频道名称（@开头）
    """
    try:
        async def _get_playlists():
            await youtube_api._update_activity()
            try:
                # 确保浏览器已初始化
                if not youtube_api.context:
                    logger.info("浏览器未初始化，正在初始化...")
                    success = await youtube_api.init_browser()
                    if not success:
                        raise Exception("浏览器初始化失败")
                
                # 获取或创建频道对应的页面
                page = await youtube_api.get_page(channel_id)
                
                # 构建播放列表页面URL
                if channel_id.startswith('UC') and len(channel_id) == 24:
                    # 频道ID格式
                    playlists_url = f"https://www.youtube.com/channel/{channel_id}/playlists"
                else:
                    # 频道名称格式
                    if not channel_id.startswith('@'):
                        playlists_url = f"https://www.youtube.com/@{channel_id}/playlists"
                    else:
                        playlists_url = f"https://www.youtube.com/{channel_id}/playlists"
                
                # 添加中文参数
                if "?" in playlists_url:
                    playlists_url += "&hl=zh-CN&gl=CN"
                else:
                    playlists_url += "?hl=zh-CN&gl=CN"
                
                logger.info(f"访问播放列表页面: {playlists_url}")
                await page.goto(playlists_url, wait_until="domcontentloaded", timeout=45000)
                await asyncio.sleep(3)
                
                # 等待页面加载
                try:
                    await page.wait_for_function("window.ytcfg && window.ytcfg.data_", timeout=15000)
                    logger.info("ytcfg已加载")
                except Exception as e:
                    logger.warning(f"等待ytcfg超时: {str(e)}")
                
                # 等待播放列表列表加载
                try:
                    await page.wait_for_selector('ytd-grid-playlist-renderer, ytd-playlist-video-list-renderer', timeout=15000)
                    logger.debug("播放列表列表已加载")
                except Exception as e:
                    logger.debug(f"等待播放列表列表超时: {str(e)}")
                
                # 从页面提取播放列表信息
                playlists = await page.evaluate("""
                    () => {
                        const items = [];
                        
                        // 方法1：从DOM元素提取
                        const playlistElements = document.querySelectorAll('ytd-grid-playlist-renderer, ytd-playlist-video-list-renderer');
                        
                        playlistElements.forEach(el => {
                            try {
                                const titleEl = el.querySelector('#video-title, a#video-title, ytd-playlist-video-list-renderer #video-title');
                                const linkEl = el.querySelector('a[href*="list="]') || titleEl?.closest('a');
                                const countEl = el.querySelector('#video-count, .video-count, [class*="count"]');
                                
                                if (linkEl && linkEl.href) {
                                    const match = linkEl.href.match(/[?&]list=([^&]+)/);
                                    if (match) {
                                        const title = titleEl?.textContent?.trim() || '';
                                        const countText = countEl?.textContent?.trim() || '0';
                                        const countMatch = countText.match(/(\d+)/);
                                        const videoCount = countMatch ? parseInt(countMatch[1]) : 0;
                                        
                                        items.push({
                                            playlist_id: match[1],
                                            title: title,
                                            video_count: videoCount,
                                            url: linkEl.href
                                        });
                                    }
                                }
                            } catch (e) {
                                console.error('Error extracting playlist:', e);
                            }
                        });
                        
                        // 方法2：如果方法1没有获取到，尝试从ytInitialData提取
                        if (items.length === 0 && window.ytInitialData) {
                            try {
                                const tabs = window.ytInitialData.contents?.twoColumnBrowseResultsRenderer?.tabs || [];
                                for (const tab of tabs) {
                                    if (tab.tabRenderer) {
                                        const title = (tab.tabRenderer.title?.simpleText || 
                                                      tab.tabRenderer.title?.runs?.[0]?.text || 
                                                      tab.tabRenderer.title || '').toLowerCase();
                                        if (title.includes('playlist') || title.includes('播放列表')) {
                                            const tabContent = tab.tabRenderer.content;
                                            
                                            // 尝试从sectionListRenderer提取（新结构使用lockupViewModel）
                                            if (tabContent?.sectionListRenderer?.contents) {
                                                for (const section of tabContent.sectionListRenderer.contents) {
                                                    if (section?.itemSectionRenderer?.contents?.[0]?.gridRenderer) {
                                                        const gridRenderer = section.itemSectionRenderer.contents[0].gridRenderer;
                                                        
                                                        if (gridRenderer.items) {
                                                            for (const item of gridRenderer.items) {
                                                                // 检查lockupViewModel结构（新结构）
                                                                if (item.lockupViewModel) {
                                                                    const lockup = item.lockupViewModel;
                                                                    const playlistId = lockup.contentId;
                                                                    
                                                                    if (playlistId && playlistId.startsWith('PL')) {
                                                                        let title = '';
                                                                        let videoCount = 0;
                                                                        
                                                                        if (lockup.metadata?.lockupMetadataViewModel) {
                                                                            const metadata = lockup.metadata.lockupMetadataViewModel;
                                                                            title = metadata.title?.content || 
                                                                                   metadata.primaryText?.content || '';
                                                                            
                                                                            // 尝试从metadata.metadata中提取视频数量
                                                                            if (metadata.metadata) {
                                                                                const countText = metadata.metadata.secondaryText?.content ||
                                                                                               metadata.metadata.subtitle?.content ||
                                                                                               '0';
                                                                                const countMatch = countText.match(/(\d+)/);
                                                                                videoCount = countMatch ? parseInt(countMatch[1]) : 0;
                                                                            }
                                                                        }
                                                                        
                                                                        // 避免重复
                                                                        if (!items.find(i => i.playlist_id === playlistId)) {
                                                                            items.push({
                                                                                playlist_id: playlistId,
                                                                                title: title,
                                                                                video_count: videoCount,
                                                                                url: `https://www.youtube.com/playlist?list=${playlistId}`
                                                                            });
                                                                        }
                                                                    }
                                                                }
                                                                
                                                                // 检查gridPlaylistRenderer结构（旧结构，向后兼容）
                                                                if (item.gridPlaylistRenderer) {
                                                                    const playlistRenderer = item.gridPlaylistRenderer;
                                                                    const playlistId = playlistRenderer.playlistId;
                                                                    const plTitle = playlistRenderer.title?.runs?.[0]?.text || playlistRenderer.title?.simpleText || '';
                                                                    const videoCount = playlistRenderer.videoCountShortText?.simpleText || '0';
                                                                    const countMatch = videoCount.match(/(\d+)/);
                                                                    const count = countMatch ? parseInt(countMatch[1]) : 0;
                                                                    
                                                                    if (playlistId && !items.find(i => i.playlist_id === playlistId)) {
                                                                        items.push({
                                                                            playlist_id: playlistId,
                                                                            title: plTitle,
                                                                            video_count: count,
                                                                            url: `https://www.youtube.com/playlist?list=${playlistId}`
                                                                        });
                                                                    }
                                                                }
                                                            }
                                                        }
                                                    }
                                                }
                                            }
                                            
                                            // 尝试从richGridRenderer提取（向后兼容）
                                            if (tabContent?.richGridRenderer?.contents) {
                                                for (const item of tabContent.richGridRenderer.contents) {
                                                    if (item.richItemRenderer?.content?.gridPlaylistRenderer) {
                                                        const pl = item.richItemRenderer.content.gridPlaylistRenderer;
                                                        const playlistId = pl.playlistId;
                                                        const plTitle = pl.title?.runs?.[0]?.text || pl.title?.simpleText || '';
                                                        const videoCount = pl.videoCountShortText?.simpleText || '0';
                                                        const countMatch = videoCount.match(/(\d+)/);
                                                        const count = countMatch ? parseInt(countMatch[1]) : 0;
                                                        
                                                        if (playlistId && !items.find(i => i.playlist_id === playlistId)) {
                                                            items.push({
                                                                playlist_id: playlistId,
                                                                title: plTitle,
                                                                video_count: count,
                                                                url: `https://www.youtube.com/playlist?list=${playlistId}`
                                                            });
                                                        }
                                                    }
                                                }
                                            }
                                            
                                            break;
                                        }
                                    }
                                }
                            } catch (e) {
                                console.error('Error extracting from ytInitialData:', e);
                            }
                        }
                        
                        // 方法3：如果从ytInitialData没有获取到视频数量，尝试从DOM补充
                        if (items.length > 0) {
                            try {
                                const linkElements = document.querySelectorAll('a[href*="list="]');
                                linkElements.forEach(linkEl => {
                                    const match = linkEl.href.match(/[?&]list=([^&]+)/);
                                    if (match) {
                                        const playlistId = match[1];
                                        const item = items.find(i => i.playlist_id === playlistId);
                                        
                                        if (item) {
                                            // 尝试从DOM获取视频数量（使用更通用的方法）
                                            const containers = [
                                                linkEl.closest('ytd-grid-playlist-renderer'),
                                                linkEl.closest('[class*="playlist"]'),
                                                linkEl.closest('ytd-playlist-video-list-renderer'),
                                                linkEl.parentElement?.parentElement,
                                                linkEl.closest('yt-lockup-view-model')
                                            ].filter(Boolean);
                                            
                                            for (const container of containers) {
                                                // 方法1：查找包含"个视频"的文本
                                                const allText = container.textContent || '';
                                                const countMatch = allText.match(/(\d+)\s*个视频/);
                                                if (countMatch) {
                                                    item.video_count = parseInt(countMatch[1]);
                                                    break;
                                                }
                                                
                                                // 方法2：查找特定的count元素
                                                const countEl = container.querySelector('[class*="count"], [id*="count"]');
                                                if (countEl) {
                                                    const countText = countEl.textContent?.trim() || '0';
                                                    const match = countText.match(/(\d+)/);
                                                    if (match) {
                                                        item.video_count = parseInt(match[1]);
                                                        break;
                                                    }
                                                }
                                            }
                                            
                                            // 补充标题（如果缺失）
                                            if (!item.title) {
                                                for (const container of containers) {
                                                    const titleEl = container.querySelector('h3, #video-title, a[href*="list="]');
                                                    if (titleEl) {
                                                        const titleText = titleEl.textContent?.trim();
                                                        // 排除包含"个视频"的文本
                                                        if (titleText && !titleText.match(/\d+\s*个视频/)) {
                                                            item.title = titleText;
                                                            break;
                                                        }
                                                    }
                                                }
                                            }
                                        }
                                    }
                                });
                            } catch (e) {
                                console.error('Error supplementing from DOM:', e);
                            }
                        }
                        
                        return items;
                    }
                """)
                
                logger.info(f"获取到 {len(playlists)} 个播放列表")
                await youtube_api._update_activity()
                return {"playlists": playlists}
                
            except Exception as e:
                await youtube_api._update_activity()
                logger.error(f"获取播放列表失败: {str(e)}")
                raise e
        
        return await youtube_api.enqueue_request(_get_playlists)
        
    except Exception as e:
        logger.error(f"获取播放列表失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"获取播放列表失败: {str(e)}")

@router.get("/playlist/{playlist_id}/videos")
async def get_playlist_videos(playlist_id: str, max_count: int = 20, page_token: str = "", current_user: User = Depends(get_current_user)):
    """获取播放列表的视频列表
    
    Args:
        playlist_id: 播放列表ID（以PL开头）
        max_count: 每页视频数量
        page_token: 分页标记
    """
    try:
        async def _get_playlist_videos(retry_on_auth_fail: bool = True):
            await youtube_api._update_activity()
            try:
                # 确保浏览器已初始化
                if not youtube_api.context:
                    logger.info("浏览器未初始化，正在初始化...")
                    success = await youtube_api.init_browser()
                    if not success:
                        raise Exception("浏览器初始化失败")
                
                # 🔧 添加播放列表参数缓存机制
                playlist_cache_key = f"playlist_{playlist_id}"
                
                # 检查参数缓存是否有效
                cached_params = await youtube_api._get_cached_youtube_params(playlist_cache_key)
                need_page_refresh = not cached_params
                
                if need_page_refresh:
                    logger.debug(f"播放列表参数缓存无效，需要访问页面: {playlist_id}")
                    
                    # 获取或创建页面
                    page = await youtube_api.get_page(f"playlist_{playlist_id}")
                    
                    # 访问播放列表页面
                    playlist_url = f"https://www.youtube.com/playlist?list={playlist_id}"
                    logger.info(f"访问播放列表页面: {playlist_url}")
                    await page.goto(playlist_url, wait_until="domcontentloaded", timeout=30000)
                    await asyncio.sleep(2)
                    
                    # 等待页面加载
                    try:
                        await page.wait_for_function("window.ytcfg && window.ytcfg.data_", timeout=15000)
                    except Exception as e:
                        logger.warning(f"等待ytcfg超时: {str(e)}")
                    
                    # 获取API参数并缓存
                    params = await youtube_api._get_youtube_params(page)
                    await youtube_api._cache_youtube_params(params)
                    logger.info(f"已缓存播放列表 {playlist_id} 的参数")
                    
                    # 获取页面上下文用于cookie
                    page_context = page
                else:
                    # 使用缓存的参数，无需刷新页面
                    params = cached_params
                    logger.info(f"使用播放列表 {playlist_id} 的缓存参数，跳过页面访问")
                    
                    # 仍需要页面来获取cookie，但不刷新
                    page_context = await youtube_api.get_page(f"playlist_{playlist_id}")
                    
                    # 定义playlist_url用于后续请求头
                    playlist_url = f"https://www.youtube.com/playlist?list={playlist_id}"
                
                # 获取cookie
                cookies = await page_context.context.cookies()
                cookie_str = "; ".join([f"{c['name']}={c['value']}" for c in cookies])
                
                # 构建请求头
                def safe_header_value(value):
                    if value is None:
                        return ""
                    str_value = str(value)
                    try:
                        str_value.encode('ascii')
                        return str_value
                    except UnicodeEncodeError:
                        import urllib.parse
                        return urllib.parse.quote(str_value, safe='')
                
                headers = {
                    "authority": "www.youtube.com",
                    "accept": "*/*",
                    "accept-language": "zh-CN,zh;q=0.9,en;q=0.8",
                    "content-type": "application/json",
                    "cookie": cookie_str,
                    "origin": "https://www.youtube.com",
                    "referer": playlist_url,
                    "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                    "x-youtube-client-name": safe_header_value(params.get('clientName', "1")),
                    "x-youtube-client-version": safe_header_value(params.get('clientVersion', "")),
                    "x-goog-visitor-id": safe_header_value(params.get('visitorData')),
                    "x-origin": "https://www.youtube.com",
                    "authorization": safe_header_value(params.get('ID_TOKEN', "")) if params.get('ID_TOKEN') else "",
                    "x-goog-authuser": "0",
                    "x-goog-pageid": safe_header_value(params.get('PAGE_CL', '')),
                    "sec-ch-ua": '"Not A Brand";v="99", "Chromium";v="120", "Google Chrome";v="120"',
                    "sec-ch-ua-mobile": "?0",
                    "sec-ch-ua-platform": '"Windows"',
                    "sec-fetch-dest": "empty",
                    "sec-fetch-mode": "cors",
                    "sec-fetch-site": "same-origin"
                }
                
                # 构建请求体 - 使用播放列表浏览ID
                default_context = {
                    "client": {
                        "hl": "zh-CN",
                        "gl": "US",
                        "visitorData": params.get('visitorData'),
                        "userAgent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36,gzip(gfe)",
                        "clientName": "WEB",
                        "clientVersion": params.get('clientVersion', ""),
                        "osName": "Windows",
                        "osVersion": "10.0",
                        "originalUrl": playlist_url,
                        "platform": "DESKTOP",
                        "clientFormFactor": "UNKNOWN_FORM_FACTOR",
                        "userInterfaceTheme": "USER_INTERFACE_THEME_LIGHT",
                        "timeZone": "Asia/Shanghai",
                        "browserName": "Chrome",
                        "browserVersion": "120.0.0.0",
                        "screenWidthPoints": 1280,
                        "screenHeightPoints": 720,
                        "screenPixelDensity": 1,
                        "utcOffsetMinutes": 480
                    },
                    "user": {
                        "lockedSafetyMode": False
                    },
                    "request": {
                        "useSsl": True,
                        "internalExperimentFlags": [],
                        "consistencyTokenJars": []
                    }
                }

                # 合并INNERTUBE_CONTEXT，确保与网页请求保持一致
                innertube_context = params.get('INNERTUBE_CONTEXT')
                if innertube_context:
                    # 深拷贝，避免后续修改影响缓存
                    import copy
                    merged_context = copy.deepcopy(innertube_context)
                    merged_context.setdefault("client", {}).update({
                        "originalUrl": playlist_url,
                        "timeZone": "Asia/Shanghai",
                        "browserName": "Chrome",
                        "browserVersion": "120.0.0.0"
                    })
                    merged_context["client"].setdefault("visitorData", params.get('visitorData'))
                    merged_context["client"].setdefault("hl", "zh-CN")
                    merged_context["client"].setdefault("gl", "US")
                    # clickTracking 也需要保留
                    if "clickTracking" not in merged_context and params.get("clickTrackingParams"):
                        merged_context["clickTracking"] = {
                            "clickTrackingParams": params["clickTrackingParams"]
                        }
                    context_payload = merged_context
                else:
                    context_payload = default_context

                data = {
                    "context": context_payload,
                    "browseId": f"VL{playlist_id}"  # 播放列表浏览ID格式：VL + playlist_id
                }
                
                # 添加分页
                if page_token:
                    logger.debug(f"使用 continuation 获取播放列表，token 前20字符: {str(page_token)[:20]}...")
                    # 续页请求只需要 continuation，不再使用 browseId
                    data = {
                        "context": context_payload,
                        "continuation": page_token
                    }
                else:
                    logger.debug(f"获取播放列表首屏: VL{playlist_id}")
                
                # 获取API key
                api_key = params.get('key', 'AIzaSyAO_FJ2SlqU8Q4STEHLGCilw_Y9_11qcW8')
                url = f"https://www.youtube.com/youtubei/v1/browse?key={api_key}&prettyPrint=false"
                
                async with httpx.AsyncClient(timeout=30.0) as client:
                    response = await client.post(url, json=data, headers=headers)
                    
                    # 检查是否需要刷新参数重试
                    if response.status_code in [401, 403] and retry_on_auth_fail:
                        logger.warning(f"YouTube播放列表API返回{response.status_code}，可能是参数失效，尝试刷新参数并重试")
                        await youtube_api._force_refresh_params()
                        return await _get_playlist_videos(retry_on_auth_fail=False)
                    
                    if response.status_code != 200:
                        logger.error(f"获取播放列表视频失败: {response.status_code}")
                        return None
                    
                    response_data = response.json()
                    top_level_keys = list(response_data.keys())
                    logger.debug(f"播放列表API响应顶层键: {top_level_keys}")
                    logger.debug(f"是否包含 contents: {bool(response_data.get('contents'))}, continuationContents: {bool(response_data.get('continuationContents'))}, onResponseReceivedActions: {bool(response_data.get('onResponseReceivedActions'))}")
                    
                    def extract_text(data):
                        if not data:
                            return ""
                        if isinstance(data, str):
                            return data
                        if isinstance(data, dict):
                            if "simpleText" in data:
                                return data["simpleText"]
                            if "text" in data:
                                return data["text"]
                            if "content" in data and isinstance(data["content"], str):
                                return data["content"]
                            if "runs" in data:
                                return "".join(run.get("text", "") for run in data["runs"])
                        if isinstance(data, list):
                            return "".join(extract_text(item) for item in data)
                        return ""
                    
                    playlist_info = {
                        "id": playlist_id,
                        "title": None,
                        "description": None,
                        "ownerText": None,
                        "channelId": None,
                        "videoCount": None,
                        "thumbnail": None
                    }
                    
                    metadata_renderer = response_data.get("metadata", {}).get("playlistMetadataRenderer", {})
                    if metadata_renderer:
                        playlist_info["title"] = metadata_renderer.get("title") or playlist_info["title"]
                        playlist_info["description"] = metadata_renderer.get("description") or playlist_info["description"]
                    
                    header_renderer = response_data.get("header", {}).get("playlistHeaderRenderer", {})
                    if header_renderer:
                        header_title = extract_text(header_renderer.get("title"))
                        if header_title:
                            playlist_info["title"] = header_title
                        
                        owner_text = extract_text(header_renderer.get("ownerText"))
                        if owner_text:
                            playlist_info["ownerText"] = owner_text
                        
                        channel_id = header_renderer.get("ownerEndpoint", {}).get("browseEndpoint", {}).get("browseId")
                        if channel_id:
                            playlist_info["channelId"] = channel_id
                        
                        thumbnails = header_renderer.get("thumbnail", {}).get("thumbnails", [])
                        if thumbnails:
                            playlist_info["thumbnail"] = thumbnails[-1].get("url") or playlist_info["thumbnail"]
                        
                        stats = header_renderer.get("stats", [])
                        num_videos_text = extract_text(header_renderer.get("numVideosText"))
                        stats_texts = [extract_text(stat) for stat in stats]
                        if num_videos_text:
                            stats_texts.insert(0, num_videos_text)
                        for text in stats_texts:
                            if not text:
                                continue
                            normalized = text.replace(",", "")
                            match = re.search(r"\d+", normalized)
                            if match and ("video" in normalized.lower() or "视频" in normalized):
                                playlist_info["videoCount"] = int(match.group())
                                break
                    
                    # 解析响应数据
                    items = []
                    next_page_token = None

                    def extract_continuation_token(entry) -> Optional[str]:
                        """统一解析continuationItemRenderer/button中的token"""
                        if not entry:
                            return None
                        
                        continuation_endpoint = entry.get("continuationEndpoint", {})
                        
                        # 检查 commandExecutorCommand 结构（用于播放列表分页）
                        if "commandExecutorCommand" in continuation_endpoint:
                            commands = continuation_endpoint["commandExecutorCommand"].get("commands", [])
                            for cmd in commands:
                                if "continuationCommand" in cmd:
                                    token = cmd["continuationCommand"].get("token")
                                    if token:
                                        logger.debug(f"从 commandExecutorCommand 中提取到token")
                                        return token
                        
                        # 原有逻辑：直接从 continuationCommand 获取
                        continuation = continuation_endpoint.get("continuationCommand", {})
                        token = continuation.get("token") or continuation.get("continuation")
                        if token:
                            return token
                        
                        # 从 buttonRenderer 获取
                        button = entry.get("buttonRenderer") or entry.get("button")
                        if button:
                            cmd = button.get("command") or button.get("navigationEndpoint") or {}
                            continuation_cmd = cmd.get("continuationCommand") or {}
                            token = continuation_cmd.get("token") or continuation_cmd.get("continuation")
                            if token:
                                return token
                        
                        return None

                    def add_items_from_list(entry_list):
                        nonlocal next_page_token
                        if not entry_list:
                            return
                        for entry in entry_list:
                            if "playlistVideoRenderer" in entry:
                                items.append(entry)
                            elif "playlistPanelVideoRenderer" in entry:
                                items.append({"playlistVideoRenderer": entry["playlistPanelVideoRenderer"]})
                            elif "continuationItemRenderer" in entry:
                                token = extract_continuation_token(entry["continuationItemRenderer"])
                                if token:
                                    next_page_token = token
                                    logger.debug(f"从 continuationItemRenderer 中提取到分页token: {token[:30]}...")
                            elif "buttonRenderer" in entry:
                                token = extract_continuation_token(entry)
                                if token:
                                    next_page_token = token
                                    logger.debug(f"从 buttonRenderer 中提取到分页token: {token[:30]}...")

                    def extract_token_from_continuations(continuations: List[Dict[str, Any]]) -> Optional[str]:
                        """兼容多种 continuations 结构"""
                        for cont in continuations or []:
                            next_data = cont.get("nextContinuationData")
                            if next_data and next_data.get("continuation"):
                                return next_data.get("continuation")
                            command = cont.get("continuationCommand") or cont.get("command")
                            if command:
                                token = (
                                    command.get("token")
                                    or command.get("continuation")
                                )
                                if token and isinstance(token, str) and len(token) > 10:
                                    return token
                        return None

                    def handle_renderer(renderer: Dict[str, Any]):
                        nonlocal next_page_token
                        if not renderer:
                            return
                        contents_list = renderer.get("contents", [])
                        continuations_list = renderer.get("continuations", [])
                        logger.debug(f"handle_renderer: contents数量={len(contents_list)}, continuations数量={len(continuations_list)}")
                        add_items_from_list(contents_list)
                        token = extract_token_from_continuations(continuations_list)
                        if token:
                            next_page_token = token
                            logger.debug(f"从 continuations 中提取到分页token: {token[:30]}...")
                        elif continuations_list:
                            logger.debug(f"continuations 中未找到有效token，continuations结构: {[list(c.keys()) for c in continuations_list]}")
                    
                    # 提取视频列表（首屏）
                    if "contents" in response_data:
                        logger.debug(f"播放列表API响应结构: {list(response_data.get('contents', {}).keys())}")
                        contents = response_data.get("contents", {})
                        playlist_video_list = None
                        
                        # 方法1: 从twoColumnBrowseResultsRenderer.tabs查找（播放列表浏览页面）
                        if "twoColumnBrowseResultsRenderer" in contents:
                            browse = contents["twoColumnBrowseResultsRenderer"]
                            if browse.get("tabs"):
                                for tab in browse["tabs"]:
                                    if tab.get("tabRenderer", {}).get("content", {}).get("playlistVideoListRenderer"):
                                        playlist_video_list = tab["tabRenderer"]["content"]["playlistVideoListRenderer"]
                                        break
                                    # 也检查sectionListRenderer
                                    tab_content = tab.get("tabRenderer", {}).get("content", {})
                                    if tab_content.get("sectionListRenderer"):
                                        sections = tab_content["sectionListRenderer"].get("contents", [])
                                        for section in sections:
                                            if section.get("itemSectionRenderer", {}).get("contents"):
                                                for item in section["itemSectionRenderer"]["contents"]:
                                                    if item.get("playlistVideoListRenderer"):
                                                        playlist_video_list = item["playlistVideoListRenderer"]
                                                        break
                                                if playlist_video_list:
                                                    break
                                        if playlist_video_list:
                                            break
                        
                        # 方法2: 直接从contents查找playlistVideoListRenderer
                        if not playlist_video_list and "playlistVideoListRenderer" in contents:
                            playlist_video_list = contents["playlistVideoListRenderer"]
                        
                        # 方法3: 从twoColumnWatchNextResults查找（观看页面）
                        if not playlist_video_list:
                            watch_next = contents.get("twoColumnWatchNextResults", {})
                            playlist_renderer = watch_next.get("playlist", {}).get("playlist", {})
                            if playlist_renderer and "contents" in playlist_renderer:
                                playlist_video_list = playlist_renderer
                        
                        if playlist_video_list:
                            handle_renderer(playlist_video_list)

                    # 提取视频列表（续页 onResponseReceivedActions）
                    if "onResponseReceivedActions" in response_data:
                        actions = response_data.get("onResponseReceivedActions", [])
                        for action in actions:
                            append = action.get("appendContinuationItemsAction") or action.get("reloadContinuationItemsCommand")
                            if not append:
                                continue
                            add_items_from_list(append.get("continuationItems", []))
                            if not next_page_token:
                                token = extract_token_from_continuations(append.get("continuations", []))
                                if token:
                                    next_page_token = token
                                    logger.debug(f"从 appendContinuationItemsAction 中提取到分页token: {token[:30]}...")

                    # 提取视频列表（续页 continuationContents.playlistVideoListContinuation）
                    continuation_contents = response_data.get("continuationContents", {})
                    playlist_continuation = continuation_contents.get("playlistVideoListContinuation")
                    if playlist_continuation:
                        if isinstance(playlist_continuation, list):
                            # 兼容数组形式
                            for continuation_entry in playlist_continuation:
                                add_items_from_list(continuation_entry.get("contents", []))
                                token = extract_token_from_continuations(continuation_entry.get("continuations", []))
                                if token:
                                    next_page_token = token
                                    logger.debug(f"从 continuationContents(list) 中提取到分页token: {token[:30]}...")
                        elif isinstance(playlist_continuation, dict):
                            add_items_from_list(playlist_continuation.get("contents", []))
                            token = extract_token_from_continuations(playlist_continuation.get("continuations", []))
                            if token:
                                next_page_token = token
                                logger.debug(f"从 continuationContents(dict) 中提取到分页token: {token[:30]}...")
                    
                    # 提取视频信息
                    videos = []
                    for item in items:
                        video_renderer = item.get("playlistVideoRenderer", {})
                        video_id = video_renderer.get("videoId")
                        if video_id:
                            snippet = video_renderer.get("title", {})
                            title = ""
                            if isinstance(snippet, dict):
                                if "runs" in snippet:
                                    title = "".join([run.get("text", "") for run in snippet["runs"]])
                                elif "simpleText" in snippet:
                                    title = snippet["simpleText"]
                            else:
                                title = str(snippet)
                            
                            thumbnails = video_renderer.get("thumbnail", {}).get("thumbnails", [])
                            thumbnail_url = thumbnails[-1].get("url", "") if thumbnails else ""
                            
                            # 获取发布时间
                            published_time = ""
                            try:
                                # 从videoInfo中提取发布时间文本
                                video_info = video_renderer.get("videoInfo", {})
                                if video_info and "runs" in video_info and len(video_info["runs"]) >= 3:
                                    # videoInfo.runs[0] = 观看次数, runs[1] = "•", runs[2] = 发布时间
                                    relative_time_text = video_info["runs"][2].get("text", "")
                                    if relative_time_text:
                                        published_time = parse_relative_time(relative_time_text)
                                        logger.debug(f"播放列表视频 {video_id} 发布时间: {relative_time_text} -> {published_time}")
                                
                                # 如果没有获取到，使用当前日期
                                if not published_time:
                                    published_time = datetime.now().strftime("%Y-%m-%d")
                                    logger.debug(f"播放列表视频 {video_id} 未找到发布时间，使用当前日期")
                            except Exception as e:
                                logger.error(f"解析播放列表视频发布时间失败: {str(e)}")
                                published_time = datetime.now().strftime("%Y-%m-%d")
                            
                            videos.append({
                                "id": {"videoId": video_id},
                                "snippet": {
                                    "title": title,
                                    "thumbnails": {
                                        "high": {"url": thumbnail_url}
                                    },
                                    "publishedAt": published_time
                                }
                            })
                    
                    logger.debug(f"解析播放列表视频: 找到 {len(items)} 个原始项，提取到 {len(videos)} 个视频，next_page_token={next_page_token[:30] + '...' if next_page_token else None}")
                    
                    # 添加详细的调试信息
                    if not next_page_token and len(items) >= 100:
                        logger.debug(f"单次获取达 {len(items)} 个视频且无后续分页，确认为列表末尾或API限制")

                    # 如果仍未获取到分页token，尝试直接从页面DOM中读取
                    if not next_page_token:
                        try:
                            dom_token = await page.evaluate("""
                                () => {
                                    const el = document.querySelector('ytd-continuation-item-renderer');
                                    if (!el) return null;
                                    const data = el.data || el.__data || el.continuationItemRenderer || {};
                                    const endpoint = data.continuationEndpoint || {};
                                    const command = endpoint.continuationCommand || {};
                                    return command.token || command.continuation || null;
                                }
                            """)
                            if dom_token:
                                next_page_token = dom_token
                                logger.debug(f"从DOM continuationItemRenderer中补充分页token: {dom_token[:50]}...")
                            else:
                                logger.debug("DOM中未找到 continuationItemRenderer token")
                        except Exception as dom_error:
                            logger.debug(f"从DOM获取分页token失败: {dom_error}")
                    
                    if next_page_token:
                        logger.debug(f"播放列表存在续页，token 前20字符: {str(next_page_token)[:20]}...")
                    
                    if len(videos) == 0:
                        logger.warning(f"未找到任何播放列表视频，响应结构: {list(response_data.keys()) if response_data else 'None'}")
                        if response_data and "contents" in response_data:
                            contents = response_data["contents"]
                            logger.warning(f"contents结构: {list(contents.keys())}")
                    
                    await youtube_api._update_activity()
                    return {
                        "items": videos,
                        "nextPageToken": next_page_token,
                        "playlist": playlist_info
                    }
                    
            except Exception as e:
                await youtube_api._update_activity()
                logger.error(f"获取播放列表视频失败: {str(e)}")
                raise e
        
        return await youtube_api.enqueue_request(_get_playlist_videos)
        
    except Exception as e:
        logger.error(f"获取播放列表视频失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"获取播放列表视频失败: {str(e)}")