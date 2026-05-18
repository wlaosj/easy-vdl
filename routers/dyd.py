import os
import sys
import logging
import base64
import traceback
import time
from fastapi import APIRouter, Depends, HTTPException, Request, Body, Query, Response, BackgroundTasks
from fastapi.responses import JSONResponse, StreamingResponse
from sqlalchemy.orm import Session
from sqlalchemy import text
from playwright.async_api import async_playwright
import httpx
import asyncio
from datetime import datetime, timezone, timedelta
import uuid
from typing import Optional, Dict, List, Tuple
from pydantic import BaseModel, Field
import aiosqlite
from loguru import logger
from urllib.parse import urlparse, parse_qs, urlencode, quote, unquote
import json
import re
import shutil

from .api_params_cache import api_params_cache
try:
    # 可选：用于在缓存失效时主动刷新抖音签名参数（不会强依赖）
    from .douyin import douyin_api  # type: ignore
except Exception:  # pragma: no cover
    douyin_api = None

# 导入 ab_sign 用于生成 a_bogus 签名（参考直播订阅的实现）
try:
    from live.core.ab_sign import ab_sign
except Exception:
    ab_sign = None

def extract_episode_number(title: str) -> int:
    """从视频标题中提取集数"""
    if not title:
        # 标题为空，返回1
        return 1
    
    # 集数提取调试信息已精简
    
    # 中文数字到阿拉伯数字的映射
    chinese_digits = {
        '零': 0, '一': 1, '二': 2, '三': 3, '四': 4, '五': 5,
        '六': 6, '七': 7, '八': 8, '九': 9, '十': 10,
        '十一': 11, '十二': 12, '十三': 13, '十四': 14, '十五': 15,
        '十六': 16, '十七': 17, '十八': 18, '十九': 19, '二十': 20,
        '二十一': 21, '二十二': 22, '二十三': 23, '二十四': 24, '二十五': 25,
        '二十六': 26, '二十七': 27, '二十八': 28, '二十九': 29, '三十': 30,
        '三十一': 31, '三十二': 32, '三十三': 33, '三十四': 34, '三十五': 35,
        '三十六': 36, '三十七': 37, '三十八': 38, '三十九': 39, '四十': 40,
        '四十一': 41, '四十二': 42, '四十三': 43, '四十四': 44, '四十五': 45,
        '四十六': 46, '四十七': 47, '四十八': 48, '四十九': 49, '五十': 50
    }
    
    # 常见的集数模式
    patterns = [
        r'第(\d+)集',           # 第1集、第25集
        r'第(\d+)集[｜|]',       # 第1集｜或第1集|
        r'第(\d+)集[^0-9]',      # 第1集后面不是数字
        r'Episode\s*(\d+)',     # Episode 1
        r'E(\d+)',              # E01
        r'S\d+E(\d+)',          # S01E01
        r'(\d+)x\d+',           # 1x01
        r'第(\d+)话',           # 第1话
        r'第(\d+)章',           # 第1章
        r'(\d+)\s*集',          # 1集
        # 添加更宽泛的匹配模式
        r'第(\d+)[集话章]',      # 第1集/话/章
        r'(\d+)[集话章]',        # 1集/话/章
    ]
    
    # 添加中文数字匹配模式
    chinese_patterns = [
        r'第([一二三四五六七八九十]+)集',  # 第三十七集
        r'第([一二三四五六七八九十]+)集[｜|]',  # 第三十七集｜
        r'第([一二三四五六七八九十]+)集[^一二三四五六七八九十]',  # 第三十七集后面不是中文数字
        r'第([一二三四五六七八九十]+)话',  # 第三十七话
        r'第([一二三四五六七八九十]+)章',  # 第三十七章
        r'([一二三四五六七八九十]+)[集话章]',  # 三十七集/话/章
    ]
    
    # 先尝试阿拉伯数字模式
    for i, pattern in enumerate(patterns):
        match = re.search(pattern, title, re.IGNORECASE)
        if match:
            try:
                episode_num = int(match.group(1))
                if episode_num > 0:  # 确保集数大于0
                    # 阿拉伯数字模式匹配成功
                    return episode_num
            except (ValueError, IndexError):
                # 阿拉伯数字模式匹配但转换失败
                continue
        else:
            # 阿拉伯数字模式不匹配
            pass
    
    # 再尝试中文数字模式
    for i, pattern in enumerate(chinese_patterns):
        match = re.search(pattern, title, re.IGNORECASE)
        if match:
            try:
                chinese_num = match.group(1)
                if chinese_num in chinese_digits:
                    episode_num = chinese_digits[chinese_num]
                    if episode_num > 0:  # 确保集数大于0
                        # 中文数字模式匹配成功
                        return episode_num
                else:
                    # 中文数字模式匹配但数字不在映射表中
                    pass
            except (ValueError, IndexError):
                # 中文数字模式匹配但转换失败
                continue
        else:
            # 中文数字模式不匹配
            pass
    
    # 如果都没匹配到，返回1
    # 所有模式都不匹配，返回1
    return 1
from sqlalchemy import create_engine, Column, String, DateTime, Text, Float
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from enum import Enum
from fastapi.exceptions import RequestValidationError
import traceback
import sys
import re
import random
from dataclasses import dataclass
from concurrent.futures import ThreadPoolExecutor
import time
import aiohttp
import shutil
import subprocess
import psutil
from .websocket import send_progress_update, broadcast_message  # 添加这行导入

## 已移除 PIL 相关逻辑，避免对 Pillow 的依赖

def convert_to_jpeg_ffmpeg(source_path: str, dest_path: str) -> bool:
    """使用FFmpeg将任意图片转换为标准JPEG，避免Pillow依赖"""
    try:
        # 不要强制写入 bt709/color_range 元数据，避免部分来源图（如 webp/p3）在展示时偏色。
        # 先走“最少干预”的 JPEG 转换，仅固定像素格式与编码器。
        cmd = [
            "ffmpeg", "-y",
            "-i", source_path,
            "-vf", "format=yuvj420p",
            "-vcodec", "mjpeg",
            "-frames:v", "1",
            "-q:v", "2",
            dest_path
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=20)
        if result.returncode == 0 and os.path.exists(dest_path) and os.path.getsize(dest_path) > 0:
            return True

        # 兜底：放宽像素格式限制，让 ffmpeg 自行选择，兼容更多异常输入图。
        fallback_cmd = [
            "ffmpeg", "-y",
            "-i", source_path,
            "-frames:v", "1",
            "-q:v", "2",
            "-vcodec", "mjpeg",
            dest_path
        ]
        fallback = subprocess.run(fallback_cmd, capture_output=True, text=True, timeout=20)
        return fallback.returncode == 0 and os.path.exists(dest_path) and os.path.getsize(dest_path) > 0
    except Exception as e:
        logger.error(f"[thumbnail] FFmpeg图片转JPEG失败: {str(e)}")
        return False

# 导入共享模型和数据库函数
# sys.path.append('/app') # 这一行在主应用中处理
from sql.models import Task, TaskStatus, Subscription, SubscriptionVideo, User
from sql.database_postgresql import get_db, Base
from routers.auth import get_current_user, get_current_user_optional, get_current_user_or_token

# 配置日志
logging.basicConfig(level=logging.WARNING)

# 统一loguru等级为WARNING，避免INFO级别噪声
try:
    logger.remove()
    logger.add(sys.stderr, level="WARNING")
except Exception:
    pass
logger = logging.getLogger(__name__)

# 创建APIRouter实例
router = APIRouter()

class BrowserManager:
    def __init__(self):
        self.playwright = None
        self.browser = None
        self._lock = asyncio.Lock()
        self._close_task = None
        self._cleanup_task = None  # 后台自动清理任务
        self._last_activity_time = None  # 新增：最后活动时间
        self._active_tasks = 0  # 新增：活跃任务计数
        self.IDLE_TIMEOUT = 60  # 空闲超时60秒
        self.FORCE_CLEANUP_TIMEOUT = 300  # 强制清理超时5分钟（防止计数不平衡导致浏览器永不关闭）
        
        # DYD专用进程标记（通过自定义启动参数注入，不使用user-data-dir以避免Playwright限制）
        self._proc_marker = "/app/database/chrome/tmp/dyd_work"
        
    async def get_browser(self):
        """按需获取浏览器实例"""
        async with self._lock:
            current_time = time.time()
            
            # 更新活动时间
            self._last_activity_time = current_time
            
            # 如果存在关闭任务，取消它
            if self._close_task and not self._close_task.done():
                self._close_task.cancel()
                self._close_task = None
                
            if not self.browser:
                logger.info("初始化新的浏览器实例（Google Chrome）...")
                try:
                    if not self.playwright:
                        self.playwright = await async_playwright().start()
                        logger.info("DYD Playwright实例已创建")
                    
                    self.browser = await self.playwright.chromium.launch(
                        headless=True,
                        channel="chrome",
                        args=[
                            '--no-sandbox',
                            '--disable-setuid-sandbox',
                            '--disable-dev-shm-usage',
                            '--disable-accelerated-2d-canvas',
                            '--disable-gpu',
                            '--disable-web-security',
                            '--remote-debugging-port=9223',  # DYD独立CDP端口
                            f'--dyd-process-marker={self._proc_marker}'
                        ]
                    )
                    logger.info("Google Chrome 浏览器实例初始化成功")
                except Exception as e:
                    logger.error(f"浏览器初始化失败: {str(e)}")
                    raise
            return self.browser
            
    async def schedule_close(self, delay: int = 300):
        """计划关闭浏览器，默认延迟300秒"""
        if self._close_task and not self._close_task.done():
            self._close_task.cancel()
        self._close_task = asyncio.create_task(self._delayed_close(delay))
        
    async def _delayed_close(self, delay: int):
        """延迟关闭浏览器"""
        try:
            await asyncio.sleep(delay)
            await self._cleanup()
        except asyncio.CancelledError:
            logger.debug("取消延迟关闭")
        except Exception as e:
            logger.error(f"延迟关闭出错: {str(e)}")
            
    async def _cleanup(self):
        """清理浏览器资源"""
        try:
            if self.browser:
                await self.browser.close()
                self.browser = None
                logger.info("浏览器实例已关闭")
            if self.playwright:
                await self.playwright.stop()
                self.playwright = None
                logger.info("Playwright已停止")
                
                # 强制清理Chrome进程（防止Playwright清理不彻底）
                await self._force_cleanup_chrome_processes()
        except Exception as e:
            logger.error(f"清理资源失败: {str(e)}")
            
    async def _force_cleanup_chrome_processes(self):
        """强制清理Chrome进程（仅DYD实例，按进程标记匹配）"""
        try:
            import asyncio
            # 仅按DYD的自定义进程标记进行精准匹配，避免影响其它平台
            marker = getattr(self, '_proc_marker', None) or 'dyd_work'
            cleanup_commands = [
                ['pkill', '-f', marker],
                ['pkill', '-9', '-f', marker]
            ]
            
            for cmd in cleanup_commands:
                try:
                    result = await asyncio.create_subprocess_exec(
                        *cmd,
                        stdout=asyncio.subprocess.PIPE,
                        stderr=asyncio.subprocess.PIPE
                    )
                    await result.wait()
                except Exception as e:
                    logger.debug(f"清理命令失败: {' '.join(cmd)} - {str(e)}")
            
            # 等待进程完全清理
            await asyncio.sleep(1)
            logger.info("强制清理Chrome进程完成（仅DYD）")
        except Exception as e:
            logger.warning(f"强制清理Chrome进程失败: {str(e)}")
            
    async def close(self):
        """立即关闭浏览器"""
        await self._cleanup()
        
    async def start_task(self, max_active_tasks: int = 5):
        """开始任务时调用
        
        Args:
            max_active_tasks: 最大活跃任务数，超过此值会等待
        """
        # 如果超过上限，等待直到有可用槽位
        while True:
            async with self._lock:
                if self._active_tasks < max_active_tasks:
                    old_active_tasks = self._active_tasks
                    self._active_tasks += 1
                    self._last_activity_time = time.time()
                    # 取消之前的关闭任务
                    if self._close_task and not self._close_task.done():
                        self._close_task.cancel()
                        self._close_task = None
                    logger.debug(f"任务开始，活跃任务数: {old_active_tasks} -> {self._active_tasks}")
                    break
                else:
                    # 超过上限，等待释放
                    logger.debug(f"浏览器活跃任务数 ({self._active_tasks}) 已达上限 ({max_active_tasks})，等待释放...")
            # 在锁外等待，避免阻塞其他任务
            await asyncio.sleep(1)
            
    async def end_task(self):
        """任务结束时调用"""
        async with self._lock:
            old_active_tasks = self._active_tasks
            self._active_tasks = max(0, self._active_tasks - 1)
            self._last_activity_time = time.time()
            logger.debug(f"任务结束，活跃任务数: {old_active_tasks} -> {self._active_tasks}")
            
            # 如果没有活跃任务，启动空闲超时检查
            if self._active_tasks == 0:
                logger.debug("没有活跃任务，开始空闲超时检查")
                await self._check_idle_timeout()
            else:
                logger.debug(f"仍有{self._active_tasks}个活跃任务，跳过空闲超时检查")
                
    async def _check_idle_timeout(self):
        """检查空闲超时"""
        logger.debug(f"检查空闲超时 - 浏览器: {self.browser is not None}, 最后活动时间: {self._last_activity_time}")
        
        if self.browser and self._last_activity_time:
            current_time = time.time()
            idle_time = current_time - self._last_activity_time
            
            if idle_time >= self.IDLE_TIMEOUT:
                logger.debug(f"浏览器空闲{self.IDLE_TIMEOUT}秒，准备关闭")
                await self._cleanup()
            else:
                # 计算剩余空闲时间
                remaining_time = self.IDLE_TIMEOUT - idle_time
                logger.debug(f"浏览器空闲{idle_time:.1f}秒，{remaining_time:.1f}秒后关闭")
                await self.schedule_close(remaining_time)
        else:
            logger.debug("浏览器已关闭或无活动时间，跳过空闲超时检查")
    
    async def start_cleanup_task(self):
        """启动后台自动清理任务"""
        if self._cleanup_task is None:
            self._cleanup_task = asyncio.create_task(self._auto_cleanup())
            logger.debug("DYD浏览器后台自动清理任务已启动")
    
    async def stop_cleanup_task(self):
        """停止后台自动清理任务"""
        if self._cleanup_task:
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                pass
            self._cleanup_task = None
            logger.debug("DYD浏览器后台自动清理任务已停止")
    
    async def _auto_cleanup(self):
        """后台自动清理任务（防止计数不平衡导致浏览器永不关闭）"""
        logger.debug("DYD浏览器后台自动清理任务开始运行")
        while True:
            try:
                await asyncio.sleep(30)  # 每30秒检查一次
                
                # 如果浏览器未初始化，跳过检查
                if not self.browser:
                    continue
                
                # 如果没有活动时间记录，跳过检查
                if not self._last_activity_time:
                    continue
                
                current_time = time.time()
                idle_time = current_time - self._last_activity_time
                
                # 正常空闲超时（计数为0且空闲超过60秒）
                if self._active_tasks == 0 and idle_time >= self.IDLE_TIMEOUT:
                    logger.debug(f"[auto_cleanup] 浏览器空闲{idle_time:.1f}秒，准备关闭")
                    await self._cleanup()
                    continue
                
                # 强制超时（5分钟无活动，即使计数不为0）
                # 说明计数已经不平衡，任务实际已结束
                if idle_time >= self.FORCE_CLEANUP_TIMEOUT:
                    logger.warning(f"[auto_cleanup] 浏览器空闲{idle_time:.1f}秒但仍有{self._active_tasks}个任务计数，强制清理并重置计数")
                    self._active_tasks = 0  # 重置计数
                    await self._cleanup()
                    
            except asyncio.CancelledError:
                logger.debug("DYD浏览器后台自动清理任务被取消")
                break
            except Exception as e:
                logger.error(f"DYD浏览器后台自动清理任务出错: {str(e)}")

# 抖音平台浏览器活跃任务数上限（所有抖音播主共享，避免浏览器资源过载）
MAX_DOUYIN_BROWSER_ACTIVE_TASKS = 5

# 创建全局浏览器管理器实例
browser_manager = BrowserManager()

@dataclass
class VideoInfo:
    """视频信息数据类"""
    video_id: str
    platform: str
    share_url: str
    download_url: Optional[str] = None
    title: Optional[str] = None
    author: Optional[str] = None
    create_time: Optional[str] = None
    quality: Optional[str] = None
    thumbnail_url: Optional[str] = None  # 添加缩略图URL字段
    # 图集相关字段
    is_gallery: bool = False  # 是否为图集
    image_urls: List[str] = None  # 图集图片URL列表（兼容旧格式）
    gallery_count: int = 0  # 图集图片数量
    media_items: Optional[List[dict]] = None  # 混合媒体项列表（新格式，支持image+video）
    # 背景音乐相关字段
    music_url: Optional[str] = None  # 背景音乐URL
    music_title: Optional[str] = None  # 背景音乐标题
    music_url: Optional[str] = None  # 背景音乐URL
    music_title: Optional[str] = None  # 背景音乐标题
    music_author: Optional[str] = None  # 背景音乐作者
    author_avatar_url: Optional[str] = None  # 作者头像URL


class Platform(str, Enum):
    """支持的平台枚举"""
    DOUYIN = "douyin"
    DOUYIN_GALLERY = "douyin"  # 抖音图集（统一到douyin平台）
    XIAOHONGSHU = "xiaohongshu"
    BILIBILI = "bilibili"
    KUAISHOU = "kuaishou"
    WEIBO = "weibo"
    XIGUA = "xigua"
    YOUTUBE = "youtube"
    UNKNOWN = "unknown"

# 抖音User-Agent池 - 用于反风控，随机选择不同的User-Agent
DOUYIN_MOBILE_USER_AGENTS = [
    'Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1',
    'Mozilla/5.0 (iPhone; CPU iPhone OS 16_6 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.6 Mobile/15E148 Safari/604.1',
    'Mozilla/5.0 (iPhone; CPU iPhone OS 15_7 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/15.7 Mobile/15E148 Safari/604.1',
    'Mozilla/5.0 (iPhone; CPU iPhone OS 14_7_1 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/14.7.1 Mobile/15E148 Safari/604.1',
    'Mozilla/5.0 (iPhone; CPU iPhone OS 13_2_3 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/13.0.3 Mobile/15E148 Safari/604.1',
]

DOUYIN_DESKTOP_USER_AGENTS = [
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36',
]

def get_random_mobile_user_agent() -> str:
    """随机获取手机版User-Agent"""
    import random
    return random.choice(DOUYIN_MOBILE_USER_AGENTS)

def get_random_desktop_user_agent() -> str:
    """随机获取桌面版User-Agent"""
    import random
    return random.choice(DOUYIN_DESKTOP_USER_AGENTS)

def get_random_mobile_viewport() -> dict:
    """随机获取手机版Viewport配置"""
    import random
    # iPhone不同型号的常见尺寸
    viewports = [
        {'width': 375, 'height': 667, 'device_scale_factor': 2},   # iPhone SE/6/7/8
        {'width': 390, 'height': 844, 'device_scale_factor': 3},   # iPhone 12/13 mini
        {'width': 393, 'height': 852, 'device_scale_factor': 3},   # iPhone 14/15
        {'width': 414, 'height': 896, 'device_scale_factor': 2},   # iPhone 11 Pro Max
        {'width': 428, 'height': 926, 'device_scale_factor': 3},  # iPhone 14 Pro Max
    ]
    return random.choice(viewports)

def get_random_desktop_viewport() -> dict:
    """随机获取桌面版Viewport配置"""
    import random
    # 常见桌面分辨率，小幅随机化
    width = random.randint(1920, 1920)  # 保持1920，避免布局问题
    height = random.randint(1080, 1088)  # 小幅随机化高度
    return {
        'width': width,
        'height': height,
        'device_scale_factor': 1
    }

class Cache:
    def __init__(self, expire_minutes=5, max_size=1000):
        self.data = {}  # 存储缓存数据
        self.expire_time = {}  # 存储过期时间
        self.access_time = {}  # 存储最后访问时间
        self.expire_minutes = expire_minutes
        self.max_size = max_size  # 最大缓存条目数
        self.cache_requests = 0  # 已有缓存时的请求次数
        self.cache_hits = 0  # 已有缓存时的命中次数
        
    def get(self, key: str) -> Optional[str]:
        """获取缓存的数据，如果已过期则返回None"""
        now = datetime.now()
        if key in self.data:
            if now < self.expire_time[key]:
                # 更新访问时间
                self.access_time[key] = now
                # 命中已存在的缓存
                self.cache_requests += 1
                self.cache_hits += 1
                return self.data[key]
            else:
                # 数据已过期，计入请求次数
                self.cache_requests += 1
                return None
        # 数据不存在，不计入统计
        return None
        
    def set(self, key: str, value: str):
        """设置缓存数据"""
        # 如果达到大小限制，清理最旧的数据
        if len(self.data) >= self.max_size:
            self._remove_oldest()
            
        self.data[key] = value
        self.expire_time[key] = datetime.now() + timedelta(minutes=self.expire_minutes)
        self.access_time[key] = datetime.now()
        
    def _remove_oldest(self):
        """移除最久未使用的数据"""
        if not self.access_time:
            return
            
        # 找到最久未访问的key
        oldest_key = min(self.access_time.items(), key=lambda x: x[1])[0]
        
        # 从所有字典中删除该key
        del self.data[oldest_key]
        del self.expire_time[oldest_key]
        del self.access_time[oldest_key]
        
    def clear_expired(self):
        """清理过期的缓存"""
        now = datetime.now()
        expired_keys = [k for k, v in self.expire_time.items() if now >= v]
        for k in expired_keys:
            del self.data[k]
            del self.expire_time[k]
            del self.access_time[k]
            
    def get_stats(self) -> Dict[str, int]:
        """获取缓存统计信息"""
        now = datetime.now()
        # 只计算已有缓存的请求的命中率
        hit_rate = (self.cache_hits / self.cache_requests * 100) if self.cache_requests > 0 else 0
        
        return {
            'total_items': len(self.data),
            'max_size': self.max_size,
            'expired_items': len([k for k, v in self.expire_time.items() if now >= v]),
            'active_items': len([k for k, v in self.expire_time.items() if now < v]),
            'cache_requests': self.cache_requests,
            'cache_hits': self.cache_hits,
            'hit_rate': round(hit_rate, 2)  # 保留两位小数
        }

    def remove_by_value(self, value: str):
        """根据值移除缓存项"""
        keys_to_remove = [k for k, v in self.data.items() if v == value]
        for k in keys_to_remove:
            if k in self.data:
                del self.data[k]
            if k in self.expire_time:
                del self.expire_time[k]
            if k in self.access_time:
                del self.access_time[k]
        if keys_to_remove:
             logger.debug(f"清除全局URL缓存: {len(keys_to_remove)}个条目")

# 全局缓存实例
global_url_cache = Cache(expire_minutes=1440, max_size=1000)  # 缓存1天

class VideoExtractor:
    """视频提取器基类"""
    def __init__(self):
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36',
            'Accept': '*/*',
            'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
            'Accept-Encoding': 'gzip, deflate, br'
        }
        self.browser_timeout = 30
        self.page_timeout = 30  # 页面操作超时30秒
        self.element_timeout = 30  # 元素等待超时30秒
        self.extract_timeout = 120  # 整体解析超时2分钟
        self._url_cache = global_url_cache
        
    async def __aenter__(self):
        return self
        
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.cleanup()
        await browser_manager.end_task()
        
    async def cleanup(self):
        """清理所有资源"""
        try:
            # 清理当前页面相关资源
            if hasattr(self, '_current_page') and self._current_page:
                await self._current_page.close()
                self._current_page = None
                
            if hasattr(self, 'browser_context') and self.browser_context:
                await self.browser_context.close()
                self.browser_context = None
                
        except Exception as e:
            logger.error(f"清理资源时出错: {str(e)}")
            
    def detect_platform(self, url: str) -> Platform:
        """检测URL所属平台（仅支持抖音）"""
        url_lower = url.lower().strip()
        
        # 特殊检测抖音图集 - 只有包含/note/的才是图集
        if 'douyin.com' in url_lower and '/note/' in url_lower:
            logger.debug(f"[detect_platform] 检测到抖音图集链接: {url}")
            return Platform.DOUYIN_GALLERY
        # 抖音视频链接 - 明确排除图集
        elif 'douyin.com' in url_lower and '/video/' in url_lower:
            logger.debug(f"[detect_platform] 检测到抖音视频链接: {url}")
            return Platform.DOUYIN

        elif 'douyin.com' in url_lower or 'iesdouyin.com' in url_lower or 'tiktok.com' in url_lower:
            return Platform.DOUYIN
        
        # 其他平台（保留但不处理）
        domain_patterns = {
            Platform.BILIBILI: [r'bilibili\.com', r'b23\.tv'],
            Platform.KUAISHOU: [r'kuaishou\.com', r'gifshow\.com', r'chenzhongtech\.com'],
            Platform.WEIBO: [r'weibo\.com', r'weibo\.cn'],
            Platform.XIGUA: [r'ixigua\.com'],
            Platform.YOUTUBE: [r'youtube\.com', r'youtu\.be']
        }
        
        for platform, patterns in domain_patterns.items():
            for pattern in patterns:
                if re.search(pattern, url_lower):
                    return platform
        
        # 平台检测未命中，返回unknown
        return Platform.UNKNOWN
        
    async def _extract_douyin_url_from_html(self, html: str) -> Optional[str]:
        """从抖音HTML源码中用正则提取视频直链"""
        try:
            # 1. 新版抖音PC页面 window.__INIT_PROPS__ 结构
            m = re.search(r'"playAddr":"(https:[^"\\]+)"', html)
            if m:
                return m.group(1).replace('\u002F', '/').replace('\u0026', '&')
            # 2. 旧版抖音PC页面 <script id="RENDER_DATA"> 结构
            m = re.search(r'"playAddr":\s*"(https:[^"\\]+)"', html)
            if m:
                return m.group(1).replace('\u002F', '/').replace('\u0026', '&')
            # 3. 兜底查找 https://...mp4
            m = re.search(r'(https://[^\s"\\]+\.mp4)', html)
            if m:
                return m.group(1)
        except Exception as e:
            logger.warning(f"抖音HTML正则提取失败: {str(e)}")
        return None
        
    async def extract(self, url: str, task_id: str = None, save_dir: str = None, for_share: bool = False) -> VideoInfo:
        """提取视频信息（公共接口，失败后自动重试1次）
        
        Args:
            url: 视频URL
            task_id: 任务ID
            save_dir: 保存目录
            for_share: 是否用于分享（如果为True，则只提取基本信息）
        """
        max_retries = 2
        last_error = None
        
        for attempt in range(max_retries):
            try:
                logger.debug(f"[extract] 第{attempt + 1}次尝试解析: {url}")
                
                # === 关键修复：对抖音短链接先获取重定向URL ===
                processed_url = url
                platform = self.detect_platform(url)
                
                # 如果是抖音短链接（v.douyin.com 且不包含 /note/ 或 /video/）
                if platform == Platform.DOUYIN and 'v.douyin.com' in url.lower() and '/note/' not in url.lower() and '/video/' not in url.lower():
                    try:
                        logger.debug(f"[extract] 检测到抖音短链接，获取重定向URL...")
                        import httpx
                        async with httpx.AsyncClient(follow_redirects=True, timeout=10.0) as client:
                            response = await client.head(url)
                            processed_url = str(response.url)
                            logger.debug(f"[extract] 短链接重定向到: {processed_url}")
                            # 重新检测平台类型
                            platform = self.detect_platform(processed_url)
                            logger.debug(f"[extract] 重新检测平台: {platform}")

                    except Exception as e:
                        logger.warning(f"[extract] 获取短链接重定向失败: {str(e)}，继续使用原URL")
                        processed_url = url
                
                # 等待一段时间再重试（指数退避）
                if attempt > 0:
                    wait_time = 2 ** attempt  # 2秒, 4秒
                    logger.debug(f"[extract] 等待 {wait_time} 秒后重试（指数退避）")
                    await asyncio.sleep(wait_time)

                
                return await self._do_extract(processed_url, task_id, save_dir, for_share)
            except Exception as e:
                last_error = e
                logger.warning(f"[extract] 尝试{attempt + 1}/{max_retries}失败: {str(e)}")
                if attempt < max_retries - 1:
                    continue  # 继续重试
        
        # 所有重试都失败了
        logger.error(f"提取失败（已重试{max_retries}次）: {str(last_error)}")
        raise last_error

    async def _do_extract(self, url: str, task_id: str = None, save_dir: str = None, for_share: bool = False) -> VideoInfo:
        """执行实际的解析逻辑"""
        try:
            # 备注：browser_manager.start_task() 已在外层 extract() 中统一处理，此处不再重复增加计数
            
            # 使用统一浏览器管理器获取页面进行解析
            platform = self.detect_platform(url)
            logger.debug(f"检测到平台: {platform}")

            # 开始提取URL
            # 平台枚举值
            
            # 新的抖音处理逻辑：根据URL类型选择处理方式
            if platform == Platform.DOUYIN:
                if '/note/' in url.lower():
                    # 先尝试按图集处理
                    # 检测到抖音/note/链接，先尝试图集提取
                    gallery_info = await self._extract_douyin_gallery(url)
                    if gallery_info:
                        # 检查是动态图集还是静态图集
                        is_dynamic = gallery_info.get('is_dynamic', False)
                        video_urls = gallery_info.get('video_urls', [])
                        image_urls = gallery_info.get('image_urls', [])
                        
                        if is_dynamic and len(video_urls) > 0:
                            # 动态图集（视频轮播）
                            logger.debug(f"[extract] 检测到动态图集，共 {len(video_urls)} 个视频")
                            return VideoInfo(
                                video_id=gallery_info['note_id'],
                                platform=Platform.DOUYIN_GALLERY,
                                share_url=url,
                                download_url=None,  # 图集没有单个视频下载链接
                                title=gallery_info['title'],
                                author=gallery_info['author'],
                                create_time=gallery_info.get('create_time'),
                                thumbnail_url=gallery_info.get('cover_url'),  # 使用封面图作为缩略图
                                is_gallery=True,
                                image_urls=video_urls,  # 动态图集：使用video_urls存储（兼容旧逻辑）
                                gallery_count=len(video_urls),
                                media_items=gallery_info.get('media_items'),  # 新增：混合媒体项列表
                                music_url=gallery_info.get('music_url'),
                                music_title=gallery_info.get('music_title'),
                                music_author=gallery_info.get('music_author'),
                                author_avatar_url=gallery_info.get('author_avatar_url')

                            )
                        elif len(image_urls) > 0:
                            # 静态图集（图片轮播）
                            logger.debug(f"[extract] 检测到静态图集，共 {len(image_urls)} 张图片")
                            return VideoInfo(
                                video_id=gallery_info['note_id'],
                                platform=Platform.DOUYIN_GALLERY,
                                share_url=url,
                                download_url=None,  # 图集没有视频下载链接
                                title=gallery_info['title'],
                                author=gallery_info['author'],
                                create_time=gallery_info.get('create_time'),
                                thumbnail_url=gallery_info.get('cover_url'),  # 使用封面图作为缩略图
                                is_gallery=True,
                                image_urls=image_urls,  # 静态图集：使用image_urls（兼容旧逻辑）
                                gallery_count=len(image_urls),
                                media_items=gallery_info.get('media_items'),  # 新增：混合媒体项列表
                                music_url=gallery_info.get('music_url'),
                                music_title=gallery_info.get('music_title'),
                                music_author=gallery_info.get('music_author'),
                                author_avatar_url=gallery_info.get('author_avatar_url')

                            )
                    else:
                        # 图集提取返回None，说明是视频类型的/note/链接，继续按视频处理
                        logger.debug("[extract] /note/链接包含视频，继续按视频处理")
                        pass
                elif '/video/' in url.lower():
                    # 检测到抖音视频链接，按视频处理
                    # 优化：优先尝试直接通过API获取 play_addr.uri（避免浏览器 page.goto 卡死/超时）
                    logger.debug(f"[extract] 检测到抖音/video/链接，优先尝试httpx直连API: {url}")
                    try:
                        fast_video_info = await self._try_extract_douyin_video_via_httpx(url, task_id=task_id, save_dir=save_dir, for_share=for_share)
                        if fast_video_info:
                            logger.debug(f"[extract] httpx直连成功，跳过浏览器加载")
                            return fast_video_info
                        else:
                            logger.debug(f"[extract] httpx直连未成功，回退到浏览器解析")
                    except Exception as _e:
                        # 失败则回退到浏览器解析
                        logger.warning(f"[extract] httpx直连抖音aweme/detail异常，回退浏览器解析: {str(_e)}")
            
            # 修复：添加await获取浏览器实例
            browser = await browser_manager.get_browser()
            t0 = time.time()
            # 创建 context 前
            
            try:
                # 抖音根据URL类型选择UA：/note/链接使用桌面版，其他使用手机版
                is_note_url = '/note/' in url.lower()
                
                if is_note_url:
                    # /note/链接使用桌面版UA（随机化User-Agent和Viewport）
                    desktop_viewport = get_random_desktop_viewport()
                    context = await browser.new_context(
                        user_agent=get_random_desktop_user_agent(),
                        viewport={'width': desktop_viewport['width'], 'height': desktop_viewport['height']},
                        device_scale_factor=desktop_viewport['device_scale_factor'],
                        locale='zh-CN',
                        timezone_id='Asia/Shanghai',
                        is_mobile=False,
                        has_touch=False,
                        color_scheme='light',
                        extra_http_headers={
                            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
                            'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
                            'Connection': 'keep-alive',
                            'Upgrade-Insecure-Requests': '1',
                            'Referer': 'https://www.douyin.com/'
                        }
                    )
                else:
                    # 其他链接使用手机版UA（随机化User-Agent和Viewport）
                    mobile_viewport = get_random_mobile_viewport()
                    context = await browser.new_context(
                        user_agent=get_random_mobile_user_agent(),
                        viewport={'width': mobile_viewport['width'], 'height': mobile_viewport['height']},
                        device_scale_factor=mobile_viewport['device_scale_factor'],
                        locale='zh-CN',
                        timezone_id='Asia/Shanghai',
                        is_mobile=True,
                        has_touch=True,
                        color_scheme='light',
                        extra_http_headers={
                            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,video/mp4,*/*;q=0.8',
                            'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
                            'Connection': 'keep-alive',
                            'Upgrade-Insecure-Requests': '1',
                        }
                    )
                
                t1 = time.time() # Corrected placement
                # 创建 context 后，创建 page 前
                page = await context.new_page()
                # 创建 page 后，设置 headers 前

                # 注意：小红书相关代码已移除，使用 xiaohongshu.py

                # 监听video_id（原有逻辑保留）
                video_id_holder = {'id': None}
                def handle_video_id(request):
                    url = request.url
                    if 'video_id=' in url:
                        import re
                        m = re.search(r'video_id=([a-zA-Z0-9]+)', url)
                        if m:
                            video_id_holder['id'] = m.group(1)
                            # 捕获到 video_id
                page.on("request", handle_video_id)

                # 监听 aweme 详情接口响应，直接解析 play_addr.uri 作为 video_id 兜底
                async def _handle_aweme_detail_response(response):
                    try:
                        rurl = response.url or ""
                        if "/aweme/v1/web/aweme/detail/" in rurl and response.status == 200:
                            text = await response.text()
                            import json as _json
                            data = None
                            try:
                                data = _json.loads(text)
                            except Exception:
                                data = None
                            if isinstance(data, dict):
                                video = (data.get('aweme_detail') or {}).get('video') or {}
                                uri = (video.get('play_addr') or {}).get('uri') or (video.get('download_addr') or {}).get('uri')
                                if uri and not video_id_holder.get('id'):
                                    # 以 detail_uri 形式保存，后续走官方直链
                                    video_id_holder['detail_uri'] = uri
                                    # 响应捕获到 video_id
                    except Exception:
                        pass
                page.on("response", _handle_aweme_detail_response)

                try:
                    await self._set_platform_headers(page, platform)
                    t2 = time.time()
                    logger.debug(f"[extract] 正在访问URL: {url}")

                
                    # === 反风控优化1：访问前随机延迟 ===
                    import random
                    pre_delay = random.uniform(0.5, 1.5)  # 抖音平台：0.5-1.5秒（回调以平衡效率和稳定性）
                    await asyncio.sleep(pre_delay)
                    
                    try:
                        await page.goto(url, wait_until='domcontentloaded', timeout=30000)
                        # goto 后，等待 video_id
                    except Exception as e:
                        logger.error(f"[extract] 页面加载失败: {str(e)}")
                        raise e

                    # === 反风控优化2：模拟真人浏览行为 ===
                    wait_time = random.uniform(2.5, 4.5)  # 抖音平台：2.5-4.5秒（回调以平衡效率和稳定性）
                    await asyncio.sleep(wait_time * 0.3)  # 先等待一部分时间
                    try:
                        # 轻微向下滚动，模拟真人查看内容
                        await page.evaluate("window.scrollBy(0, Math.random() * 300 + 100)")
                    except:
                        pass
                    await asyncio.sleep(wait_time * 0.7)  # 等待剩余时间

                    # --- 原有video_id/正则/兜底逻辑保留 ---
                    # 新增：对于/note/链接（桌面版），直接从video元素提取currentSrc
                    if platform == Platform.DOUYIN and is_note_url and not (video_id_holder['id'] or video_id_holder.get('detail_uri')):
                        try:
                            video_src = await page.evaluate("""
                                () => {
                                    const videos = document.querySelectorAll('video');
                                    for (const video of videos) {
                                        if (video.currentSrc && video.currentSrc.includes('douyinvod.com')) {
                                            return video.currentSrc;
                                        }
                                    }
                                    return null;
                                }
                            """)
                            if video_src:
                                # 直接使用video元素的src作为下载链接
                                video_id_holder['direct_video_url'] = video_src
                                logger.debug(f"[extract] 从video元素提取到直链: {video_src[:100]}...")
                        except Exception as e:
                            logger.warning(f"[extract] 从video元素提取失败: {str(e)}")
                    
                    # 优先：直接尝试从HTML解析 play_addr/download_addr 的 uri（HTML优先）
                    if platform == Platform.DOUYIN and not (video_id_holder['id'] or video_id_holder.get('detail_uri') or video_id_holder.get('direct_video_url')):
                        try:
                            html_for_uri = await page.content()
                            import re
                            m_play = re.search(r'"play_addr"\s*:\s*\{[^}]*?"uri"\s*:\s*"([a-zA-Z0-9_]+)"', html_for_uri)
                            uri = m_play.group(1) if m_play else None
                            if not uri:
                                m_down = re.search(r'"download_addr"\s*:\s*\{[^}]*?"uri"\s*:\s*"([a-zA-Z0-9_]+)"', html_for_uri)
                                uri = m_down.group(1) if m_down else None
                            if uri:
                                video_id_holder['detail_uri'] = uri
                                # HTML解析捕获到 video_id
                        except Exception:
                            pass

                    # 若HTML未命中，再等待 video_id 或 detail_uri 出现，最多等15秒（监听响应等）
                    if not (video_id_holder['id'] or video_id_holder.get('detail_uri') or video_id_holder.get('direct_video_url')):
                        wait_start = time.time()
                        max_wait = 15  # 最多等15秒（从3秒→10秒→15秒，在高并发时给予更充足的等待时间）
                        while time.time() - wait_start < max_wait:
                            if video_id_holder['id'] or video_id_holder.get('detail_uri') or video_id_holder.get('direct_video_url'):
                                break
                            await asyncio.sleep(0.1)
                        # video_id 等待完成

                    video_url = None
                    
                    # 最优先：如果有direct_video_url（从video元素提取），直接使用
                    if platform == Platform.DOUYIN and video_id_holder.get('direct_video_url'):
                        video_url = video_id_holder['direct_video_url']
                        logger.debug(f"[extract] 使用video元素直链: {video_url[:100]}...")
                        title = await self._get_video_title(page, platform)
                        author = await self._get_video_author(page, platform)
                        thumbnail = await self._get_video_thumbnail(page, platform, None, video_url, task_id=task_id, save_dir=save_dir, for_share=for_share)
                        video_info = VideoInfo(
                            video_id=str(int(time.time())),
                            platform=platform,
                            share_url=url,
                            download_url=video_url,
                            title=title,
                            author=author,
                            thumbnail_url=thumbnail
                        )
                        logger.debug("[extract] video元素直链流程完成")
                        return video_info
                    
                    # 次优先：抖音 video_id 直链
                    if platform == Platform.DOUYIN and (video_id_holder['id'] or video_id_holder.get('detail_uri')):
                        douyin_start = time.time()
                        # 进入抖音 video_id 直链流程
                        vid_for_api = video_id_holder['id'] or video_id_holder.get('detail_uri')
                        video_url = await self._get_douyin_no_watermark_url(vid_for_api)
                        # 抖音 video_id 直链流程完成
                        if video_url:
                            logger.debug(f"[extract] 抖音官方接口直链: {video_url}")

                            title = await self._get_video_title(page, platform)
                            author = await self._get_video_author(page, platform)
                            thumbnail = await self._get_video_thumbnail(page, platform, video_id_holder.get('id'), video_url, task_id=task_id, save_dir=save_dir, for_share=for_share)
                            video_info = VideoInfo(
                                video_id=str(int(time.time())),
                                platform=platform,
                                share_url=url,
                                download_url=video_url,
                                title=title,
                                author=author,
                                thumbnail_url=thumbnail
                            )
                            logger.debug("[extract] 抖音 video_id 直链流程完成")
                            # 总耗时

                            return video_info

                    # 兜底：如果没有捕获到 video_id，尝试正则提取
                    logger.debug("[extract] 进入正则/兜底流程")

                    html = await page.content()
                    
                    # 抖音提取方法
                    if platform == Platform.DOUYIN:
                        video_url = await self._extract_douyin_url_from_html(html)
                    else:
                        # 其他平台使用抖音提取方法（兜底）
                        video_url = await self._extract_douyin_url_from_html(html)
                    
                    logger.debug(f"[extract] 正则提取结果: {video_url}")

                    
                    if video_url:
                        # 验证URL有效性（抖音）
                        def is_valid_video_url(u):
                            u = u.lower()
                            if not any(ext in u for ext in ['.mp4', '.m3u8', '.ts', '.flv', '.webm']):
                                return False
                            if any(x in u for x in ['client.mp4', 'static', 'eden-cn', 'download/douyin_pc_client', 'douyin_pc_client.mp4']):
                                return False
                            if 'video' in u or 'aweme' in u or 'play' in u or 'stream' in u or 'sns-video' in u:
                                return True
                            return False
                        is_valid = is_valid_video_url(video_url)
                        
                        if is_valid:
                            logger.debug(f"[extract] 正则流程命中: {video_url}")
                            
                            title = await self._get_video_title(page, platform)

                            author = await self._get_video_author(page, platform)
                            thumbnail = await self._get_video_thumbnail(page, platform, video_id_holder.get('id'), video_url, task_id=task_id, save_dir=save_dir, for_share=for_share)
                            video_info = VideoInfo(
                                video_id=str(int(time.time())),
                                platform=platform,
                                share_url=url,
                                download_url=video_url,
                                title=title,
                                author=author,
                                thumbnail_url=thumbnail
                            )
                            logger.debug("[extract] 正则流程完成")
                            return video_info

                        else:
                            logger.warning(f"[extract] 提取的URL无效: {video_url}")
                            video_url = None

                    if not video_url:
                        logger.info("[extract] 所有流程均未捕获到视频数据")
                        raise Exception("无法提取视频信息，请确认链接格式是否正确")

                finally:
                    logger.debug("[extract] 关闭 page/context 前")
                    await page.close()
                    await context.close()
                    logger.debug("[extract] 关闭 page/context 后")

            finally:
                # 任务完成后不再安排关闭浏览器，浏览器生命周期由主应用管理
                pass
        except Exception as e:
            logger.error(f"解析失败: {str(e)}")
            raise

    async def _try_extract_douyin_video_via_httpx(self, url: str, task_id: str = None, save_dir: str = None, for_share: bool = False) -> Optional[VideoInfo]:
        """抖音视频（/video/{aweme_id}）优先走 httpx 直连 aweme/detail 获取 uri。

        返回 VideoInfo 则表示成功；返回 None 表示不适用或未成功（上层会回退到浏览器解析）。
        """
        try:
            parsed = urlparse(url)
            m = re.search(r"/video/(\d+)", parsed.path or "")
            if not m:
                logger.debug(f"[extract] httpx路径：URL格式不匹配，跳过: {url}")
                return None
            aweme_id = m.group(1)
            logger.debug(f"[extract] httpx路径：提取到aweme_id={aweme_id}")

        except Exception as e:
            logger.debug(f"[extract] httpx路径：提取aweme_id失败: {str(e)}")
            return None

        # 1) 组装请求参数（尽量贴近网页端）
        params: Dict[str, Any] = {
            "device_platform": "webapp",
            "aid": "6383",
            "channel": "channel_pc_web",
            "aweme_id": aweme_id,
            "pc_client_type": "1",
            "version_code": "190500",
            "version_name": "19.5.0",
            "update_version_code": "170400",
        }

        # 2) 尝试带上缓存的签名/令牌参数（不强制）
        cached = api_params_cache.get("douyin")
        has_cached_params = False
        if isinstance(cached, dict):
            has_cached_params = True
            param_count = 0
            for k in ("msToken", "verifyFp", "fp", "a_bogus", "webid", "uifid", "XBogus", "_signature", "ttwid"):
                v = cached.get(k)
                if isinstance(v, str) and v:
                    # 兼容不同命名：有些接口要 XBogus / X-Bogus
                    if k == "XBogus":
                        params["X-Bogus"] = v
                    else:
                        params[k] = v
                    param_count += 1
            logger.debug(f"[extract] httpx路径：从缓存加载了{param_count}个签名参数")
        else:
            logger.debug(f"[extract] httpx路径：未找到缓存的签名参数")


        # 3) 尝试从douyin_api获取完整cookies（如果可用）
        cookie_str = None
        if douyin_api is not None:
            try:
                # 确保浏览器已初始化（但不访问具体视频页）
                await douyin_api._ensure_browser_ready()
                cookies = await douyin_api.page.context.cookies()
                cookie_str = "; ".join([f"{c['name']}={c['value']}" for c in cookies])
                logger.debug(f"[extract] httpx路径：从douyin_api获取到{len(cookies)}个cookies")
            except Exception as e:
                logger.debug(f"[extract] httpx路径：获取cookies失败: {str(e)}")


        # 4) 构造 headers（重点：Referer + UA + cookies）
        user_agent = get_random_desktop_user_agent()
        headers: Dict[str, str] = {
            "accept": "application/json, text/plain, */*",
            "accept-language": "zh-CN,zh;q=0.9",
            "referer": url,
            "user-agent": user_agent,
            "connection": "keep-alive",
        }
        
        # 优先使用完整cookies，否则只用ttwid
        if cookie_str:
            headers["cookie"] = cookie_str
        else:
            ttwid = params.get("ttwid")
            if isinstance(ttwid, str) and ttwid:
                headers["cookie"] = f"ttwid={ttwid}"
                logger.debug(f"[extract] httpx路径：仅使用ttwid作为cookie")

        # 5) 依次尝试不同 host（部分环境下 www-hj 更稳）
        detail_urls = [
            "https://www.douyin.com/aweme/v1/web/aweme/detail/",
            "https://www-hj.douyin.com/aweme/v1/web/aweme/detail/",
        ]

        async def _request_detail() -> Optional[dict]:
            async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
                for detail_url in detail_urls:
                    try:
                        logger.debug(f"[extract] httpx路径：尝试请求 {detail_url}")
                        
                        # 如果缓存中没有 a_bogus 且 ab_sign 可用，尝试生成签名（参考直播订阅的实现）
                        request_params = params.copy()
                        if "a_bogus" not in request_params and ab_sign is not None:
                            try:
                                # 构建查询参数字符串用于签名（参考直播订阅：先构建URL，再签名）
                                from urllib.parse import urlencode, urlparse
                                query_str = urlencode(request_params, doseq=True)
                                # 生成 a_bogus 签名
                                generated_a_bogus = ab_sign(query_str, user_agent)
                                request_params["a_bogus"] = generated_a_bogus
                                logger.debug(f"[extract] httpx路径：使用ab_sign生成了a_bogus签名")
                            except Exception as e:
                                logger.debug(f"[extract] httpx路径：生成a_bogus签名失败: {str(e)}")

                        
                        resp = await client.get(detail_url, params=request_params, headers=headers)
                        logger.debug(f"[extract] httpx路径：{detail_url} 返回状态码 {resp.status_code}")

                        
                        if resp.status_code != 200:
                            try:
                                error_text = resp.text[:200] if resp.text else ""
                                logger.warning(f"[extract] httpx路径：{detail_url} 返回非200状态码，响应: {error_text}")
                            except:
                                pass
                            continue
                            
                        # 先判断 content-type 和响应体长度，避免 200 但返回 HTML/空内容导致 JSONDecodeError
                        content_type = (resp.headers.get("content-type") or "").lower()
                        body_text = ""
                        body_length = 0
                        try:
                            body_text = resp.text or ""
                            body_length = len(body_text)
                        except Exception as e:
                            logger.warning(f"[extract] httpx路径：{detail_url} 读取响应体失败: {str(e)}")
                            continue
                        
                        # 记录响应体长度和content-type
                        logger.debug(f"[extract] httpx路径：{detail_url} content-type={content_type or 'unknown'}, 响应体长度={body_length}字节")
                        
                        # 如果响应体为空，直接跳过
                        if body_length == 0:
                            logger.warning(f"[extract] httpx路径：{detail_url} 响应体为空（content-type={content_type or 'unknown'}），可能被抖音拦截")
                            continue

                        if "application/json" not in content_type:
                            # 抖音常见：200 + text/html（风控页/验证页）或空响应
                            body_preview = body_text[:200]
                            if body_preview.strip().startswith("<"):
                                logger.warning(f"[extract] httpx路径：{detail_url} content-type={content_type or 'unknown'}，疑似返回HTML风控页: {body_preview}")
                            elif body_preview.strip() == "":
                                logger.warning(f"[extract] httpx路径：{detail_url} content-type={content_type or 'unknown'}，响应为空（可能被拦截/挑战）")
                            else:
                                logger.warning(f"[extract] httpx路径：{detail_url} content-type={content_type or 'unknown'}，非JSON响应: {body_preview}")
                            continue

                        try:
                            data = resp.json() or {}
                        except Exception as je:
                            body_preview = body_text[:200]
                            logger.warning(f"[extract] httpx路径：{detail_url} JSON解析失败: {type(je).__name__}: {str(je)[:120]}，content-type={content_type or 'unknown'}，响应体长度={body_length}字节，前200字节: {body_preview}")
                            continue

                        if isinstance(data, dict):
                            # 检查是否有aweme_detail字段
                            if data.get("aweme_detail") is not None:
                                logger.debug(f"[extract] httpx路径：{detail_url} 成功获取到aweme_detail")
                                return data
                            else:

                                # 检查是否有错误信息
                                status_code = data.get("status_code")
                                status_msg = data.get("status_msg", "")
                                logger.warning(f"[extract] httpx路径：{detail_url} 响应中无aweme_detail，status_code={status_code}, status_msg={str(status_msg)[:100]}")
                    except Exception as e:
                        error_type = type(e).__name__
                        if "Timeout" in error_type or "timeout" in str(e).lower():
                            logger.warning(f"[extract] httpx路径：{detail_url} 请求超时")
                        else:
                            logger.warning(f"[extract] httpx路径：{detail_url} 请求异常 ({error_type}): {str(e)[:200]}")
                        continue
            return None

        data = await _request_detail()

        # 6) 若失败且可用 douyin_api，则尝试刷新一次参数（只刷新签名参数；不访问具体 video 页）
        if not data and douyin_api is not None:
            logger.debug(f"[extract] httpx路径：首次请求失败，尝试刷新API参数后重试")
            try:
                refreshed = await douyin_api._get_api_params(force_refresh=True)

                if isinstance(refreshed, dict):
                    api_params_cache.set("douyin", refreshed)
                    logger.debug(f"[extract] httpx路径：API参数已刷新")

                    
                    # 重新获取cookies
                    try:
                        cookies = await douyin_api.page.context.cookies()
                        cookie_str = "; ".join([f"{c['name']}={c['value']}" for c in cookies])
                        headers["cookie"] = cookie_str
                        logger.debug(f"[extract] httpx路径：重新获取到{len(cookies)}个cookies")
                    except Exception as e:
                        logger.debug(f"[extract] httpx路径：重新获取cookies失败: {str(e)}")

                    
                    # 重新带参数再试一次
                    cached2 = api_params_cache.get("douyin")
                    if isinstance(cached2, dict):
                        for k in ("msToken", "verifyFp", "fp", "a_bogus", "webid", "uifid", "XBogus", "_signature", "ttwid"):
                            v = cached2.get(k)
                            if isinstance(v, str) and v:
                                if k == "XBogus":
                                    params["X-Bogus"] = v
                                else:
                                    params[k] = v
                data = await _request_detail()
            except Exception as e:
                logger.warning(f"[extract] httpx路径：刷新参数后重试失败: {str(e)}")
                data = None

        if not data:
            logger.debug(f"[extract] httpx路径：所有尝试均失败，返回None（将回退到浏览器解析）")
            return None


        aweme_detail = (data.get("aweme_detail") or {}) if isinstance(data, dict) else {}
        video = (aweme_detail.get("video") or {}) if isinstance(aweme_detail, dict) else {}
        author_info = (aweme_detail.get("author") or {}) if isinstance(aweme_detail, dict) else {}

        uri = None
        try:
            uri = (video.get("play_addr") or {}).get("uri") or (video.get("download_addr") or {}).get("uri")
        except Exception:
            uri = None
        if not uri:
            logger.warning(f"[extract] httpx路径：未能从响应中提取到play_addr.uri或download_addr.uri")
            return None

        logger.debug(f"[extract] httpx路径：成功提取到uri={str(uri)[:20]}...")


        # 获取无水印直链（与原逻辑一致）
        download_url = await self._get_douyin_no_watermark_url(uri)
        if not download_url:
            logger.warning(f"[extract] httpx路径：获取无水印直链失败")
            return None

        title = aweme_detail.get("desc") if isinstance(aweme_detail, dict) else None
        author = author_info.get("nickname") if isinstance(author_info, dict) else None
        
        # 提取作者头像 - 优先获取高清图
        author_avatar_url = None
        try:
            # 优先顺序: avatar_larger > avatar_medium > avatar_thumb
            avatar_keys = ["avatar_larger", "avatar_medium", "avatar_thumb"]
            for key in avatar_keys:
                avatar_obj = author_info.get(key) or {}
                avatar_urls = avatar_obj.get("url_list") or []
                if avatar_urls:
                    author_avatar_url = avatar_urls[0]
                    # 如果URL包含100x100，尝试替换为1080x1080以获得更高清图片
                    if author_avatar_url and "100x100" in author_avatar_url:
                         author_avatar_url = author_avatar_url.replace("100x100", "1080x1080")
                    break
        except Exception:
            pass


        # 优先使用 detail 返回的 cover（更准确），否则用现有 thumbnail 推断
        thumbnail_url = None
        try:
            cover = (video.get("cover") or {})
            url_list = cover.get("url_list") or []
            if isinstance(url_list, list) and url_list:
                thumbnail_url = url_list[0]
        except Exception:
            thumbnail_url = None
        if not thumbnail_url:
            thumbnail_url = await self._get_video_thumbnail(
                page=None,
                platform=Platform.DOUYIN,
                video_id=uri,
                download_url=download_url,
                task_id=task_id,
                save_dir=save_dir,
                for_share=for_share,
            )

        logger.debug(f"[extract] httpx直连aweme/detail成功，跳过浏览器加载")
        logger.debug(f"[extract] 详细结果: aweme_id={aweme_id}, uri={str(uri)[:16]}...")
        return VideoInfo(


            video_id=aweme_id,
            platform=Platform.DOUYIN,
            share_url=url,
            download_url=download_url,
            title=title,
            author=author,
            thumbnail_url=thumbnail_url,
            author_avatar_url=author_avatar_url,
        )


    async def _get_douyin_no_watermark_url(self, video_id: str) -> str:
        """通过抖音官方接口获取无水印视频直链"""
        # 先检查缓存
        cached_url = self._url_cache.get(video_id)
        if cached_url:
            logger.debug(f"[douyin_api] 命中缓存: {video_id}")
            return cached_url

            
        # 如果缓存未命中，执行原有的获取逻辑
        apis = [
            f'https://aweme.snssdk.com/aweme/v1/play/?video_id={video_id}&ratio=1080p&line=1',
            f'https://aweme.snssdk.com/aweme/v1/play/?video_id={video_id}&ratio=1080p&line=0',
            f'https://aweme.snssdk.com/aweme/v1/play/?video_id={video_id}&ratio=720p&line=1',
            f'https://aweme.snssdk.com/aweme/v1/play/?video_id={video_id}&ratio=720p&line=0',
            f'https://aweme.snssdk.com/aweme/v1/play/?video_id={video_id}&ratio=540p&line=2',
        ]
        
        headers = {
            'User-Agent': get_random_mobile_user_agent(),  # 使用随机User-Agent
            'Accept': '*/*',
            'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
            'Referer': 'https://www.douyin.com/',
            'Connection': 'keep-alive',
            'Range': 'bytes=0-1',  # 只请求开头1个字节，验证可访问性
        }

        async def validate_url(api_url: str) -> Optional[str]:
            """验证单个API URL的可用性"""
            try:
                async with httpx.AsyncClient(follow_redirects=True, timeout=5.0) as client:
                    # 先用 HEAD 请求快速验证
                    try:
                        head_resp = await client.head(
                            api_url,
                            headers=headers,
                            timeout=5.0
                        )
                        if head_resp.status_code in [200, 206]:
                            # HEAD请求成功
                            return api_url
                    except Exception:
                        pass  # HEAD 失败就用 GET 试试

                    # HEAD 失败的话用 GET 请求重试
                    resp = await client.get(
                        api_url,
                        headers=headers,
                        timeout=5.0
                    )
                    if resp.status_code in [200, 206]:
                        logger.debug(f"[douyin_api] GET请求成功: {api_url}")
                        return api_url

                    
            except Exception as e:
                logger.debug(f"[douyin_api] 接口探测跳过: {api_url} - {str(e)}")
            return None

        # 最多重试2次
        for attempt in range(2):
            try:
                # 尝试验证API
                # 并发验证所有API
                tasks = [validate_url(api) for api in apis]
                results = await asyncio.gather(*tasks)
                
                # 返回第一个可用的URL
                for url in results:
                    if url:
                        logger.debug(f"[douyin_api] 找到可用API: {url}")
                        # 缓存成功的结果
                        self._url_cache.set(video_id, url)
                        return url

                        
                logger.warning(f"[douyin_api] 第{attempt + 1}次尝试所有API都失败")
                if attempt < 1:  # 如果不是最后一次重试
                    await asyncio.sleep(1)  # 等待1秒后重试
                    
            except Exception as e:
                logger.error(f"[douyin_api] 第{attempt + 1}次尝试发生错误: {str(e)}")
                if attempt < 1:
                    await asyncio.sleep(1)
                    
        logger.error("[douyin_api] 所有重试都失败")
        return None
        
    async def _extract_douyin_gallery(self, url: str) -> Optional[Dict]:
        """提取抖音图集信息"""
        try:
            logger.debug(f"[gallery] 开始提取抖音图集: {url}")
            
            # 获取浏览器实例
            browser = await browser_manager.get_browser()
            # 图集提取使用桌面版UA（随机化User-Agent和Viewport）
            desktop_viewport = get_random_desktop_viewport()
            context = await browser.new_context(
                user_agent=get_random_desktop_user_agent(),
                viewport={'width': desktop_viewport['width'], 'height': desktop_viewport['height']},
                device_scale_factor=desktop_viewport['device_scale_factor'],
                locale='zh-CN',
                timezone_id='Asia/Shanghai',
                is_mobile=False,
                has_touch=False,
                color_scheme='light',
                extra_http_headers={
                    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
                    'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
                    'Connection': 'keep-alive',
                    'Upgrade-Insecure-Requests': '1',
                    'Referer': 'https://www.douyin.com/'
                }
            )
            
            page = await context.new_page()
            
            try:
                # 访问图集页面
                await page.goto(url, wait_until="domcontentloaded", timeout=self.page_timeout * 1000)
                import random
                # 动态图集需要更长的等待时间，确保图片元素完全加载
                await asyncio.sleep(random.uniform(3.0, 5.0))  # 增加等待时间，确保动态图集图片加载完成
                
                # 等待图片加载完成（动态图集可能需要滚动或交互才能加载）
                try:
                    await page.wait_for_selector('img', timeout=5000)
                except:
                    pass  # 如果超时，继续执行
                
                # 先尝试提取图集信息（支持动态图集-视频轮播 & 静态图集）
                # 提取图集信息
                gallery_info = await page.evaluate("""
                    () => {
                        const result = {
                            note_id: '',
                            title: '',
                            author: '',
                            create_time: '',
                            cover_url: '',
                            image_urls: [],
                            video_urls: [],  // 新增：动态图集的视频URL列表
                            is_dynamic: false,  // 新增：标识是否为动态图集（视频轮播）
                            author_avatar_url: '' // 新增：作者头像URL
                        };

                        
                        // 提取note_id
                        const noteMatch = window.location.pathname.match(/\/note\/(\d+)/);
                        if (noteMatch) {
                            result.note_id = noteMatch[1];
                        }
                        
                        // ========== 增强提取：从 self.__pace_f 脚本中提取完整信息 ==========
                        try {
                            const paceScripts = Array.from(document.querySelectorAll('script'))
                                .filter(s => s.text.includes('self.__pace_f.push') && s.text.includes('awemeId'));
                            
                            if (paceScripts.length > 0) {
                                const fullText = paceScripts.map(s => s.text).join('\\n');
                                
                                // 提取 desc (标题)
                                const descMatch = fullText.match(/\\\\"desc\\\\":\\\\"(.*?)\\\\"/);
                                if (descMatch && descMatch[1]) {
                                    result.title = descMatch[1].replace(/\\\\u0026/g, '&').replace(/\\\\/g, '');
                                }
                                
                                // 提取 nickname (作者)
                                const nicknameMatch = fullText.match(/\\\\"nickname\\\\":\\\\"(.*?)\\\\"/);
                                if (nicknameMatch && nicknameMatch[1]) {
                                    result.author = nicknameMatch[1].replace(/\\\\u0026/g, '&').replace(/\\\\/g, '');
                                }

                                // 提取 create_time
                                const createTimeMatch = fullText.match(/\\\\"create_time\\\\":(\d+)/);
                                if (createTimeMatch && createTimeMatch[1]) {
                                    try {
                                        const timestamp = parseInt(createTimeMatch[1]);
                                        const date = new Date(timestamp * 1000);
                                        result.create_time = date.toISOString().replace('T', ' ').substring(0, 19);
                                    } catch (e) {}
                                }
                            }
                        } catch (e) {
                            console.error('Pace script extraction failed:', e);
                        }

                        // 如果脚本提取失败，使用 DOM 选择器兜底
                        if (!result.title) {
                            const titleSelectors = [
                                'h1', '.title', '.note-title', '[data-e2e="note-title"]', '.video-title'
                            ];
                            for (const selector of titleSelectors) {
                                const element = document.querySelector(selector);
                                if (element && element.textContent.trim()) {
                                    result.title = element.textContent.trim();
                                    break;
                                }
                            }
                        }
                        
                        // ========== 提取混合图集(静态图+动态视频)和背景音乐 ==========
                        const mediaItems = [];
                        const seenUris = new Set();
                        let musicUrl = null;
                        let musicTitle = null;
                        let musicAuthor = null;
                        
                        try {
                            const paceScripts = Array.from(document.querySelectorAll('script'))
                                .filter(s => s.text.includes('self.__pace_f.push') && s.text.includes('awemeId'));
                            
                            if (paceScripts.length > 0) {
                                const fullText = paceScripts.map(s => s.text).join('\\n');
                                
                                // ===== 1. 提取 images 数组 (使用简单的字符串查找) =====
                                let imagesStart = fullText.indexOf('\\\\"images\\\\":[');
                                if (imagesStart === -1) {
                                    imagesStart = fullText.indexOf('"images":[');
                                }
                                
                                if (imagesStart !== -1) {
                                    // 找到数组的起始 '['
                                    const arrayStart = fullText.indexOf('[', imagesStart);
                                    
                                    // 使用括号计数找到数组结束
                                    let bracketCount = 0;
                                    let imagesEnd = -1;
                                    for (let i = arrayStart; i < fullText.length; i++) {
                                        if (fullText[i] === '[') bracketCount++;
                                        else if (fullText[i] === ']') {
                                            bracketCount--;
                                            if (bracketCount === 0) {
                                                imagesEnd = i;
                                                break;
                                            }
                                        }
                                    }
                                    
                                    if (imagesEnd !== -1) {
                                        const imagesArrayStr = fullText.substring(arrayStart, imagesEnd + 1);
                                        console.log('Extracted images array, length:', imagesArrayStr.length);
                                        
                                        // 使用更准确的方式解析每个item：匹配大括号
                                        let pos = 0;
                                        let itemIndex = 0;
                                        
                                        while (true) {
                                            // 查找下一个对象的开始
                                            const itemStart = imagesArrayStr.indexOf('{', pos);
                                            if (itemStart === -1) break;
                                            
                                            // 使用括号计数找到对象结束
                                            let braceCount = 0;
                                            let itemEnd = -1;
                                            for (let i = itemStart; i < imagesArrayStr.length; i++) {
                                                if (imagesArrayStr[i] === '{') braceCount++;
                                                else if (imagesArrayStr[i] === '}') {
                                                    braceCount--;
                                                    if (braceCount === 0) {
                                                        itemEnd = i + 1;
                                                        break;
                                                    }
                                                }
                                            }
                                            
                                            if (itemEnd === -1) break;
                                            
                                            // 提取完整的item字符串
                                            const itemStr = imagesArrayStr.substring(itemStart, itemEnd);
                                            
                                            // 判断类型
                                            const hasVideo = itemStr.includes('playAddr') || itemStr.includes('play_addr');
                                            const type = hasVideo ? 'video' : 'image';
                                            
                                            // 提取URL
                                            let url = null;
                                            let uri = null;
                                            
                                            if (hasVideo) {
                                                // 查找 douyinvod.com URL
                                                const vodPos = itemStr.indexOf('douyinvod.com');
                                                if (vodPos !== -1) {
                                                    // 向前查找https
                                                    let urlStart = itemStr.lastIndexOf('https', vodPos);
                                                    if (urlStart !== -1) {
                                                        // 向后查找结束位置 - 使用更智能的检测
                                                        let urlEnd = vodPos + 500; // 默认较长的长度
                                                        
                                                        // 查找可能的URL结束符
                                                        for (let i = vodPos + 13; i < itemStr.length && i < vodPos + 1000; i++) {
                                                            const char = itemStr[i];
                                                            const nextChar = itemStr[i + 1];
                                                            
                                                            // URL结束的标志：引号、逗号、空格、反斜杠+引号等
                                                            if (char === '"' || 
                                                                char === ',' || 
                                                                char === ' ' ||
                                                                char === '}' ||
                                                                char === ']' ||
                                                                (char === '\\\\' && (nextChar === '"' || nextChar === '\\\\'))) {
                                                                urlEnd = i;
                                                                break;
                                                            }
                                                        }
                                                        
                                                        url = itemStr.substring(urlStart, urlEnd)
                                                            .replace(/\\\\u0026/g, '&')
                                                            .replace(/\\\\/g, '');
                                                        
                                                        const tosPos = url.indexOf('/video/tos/');
                                                        if (tosPos !== -1) {
                                                            const qPos = url.indexOf('?', tosPos);
                                                            uri = qPos !== -1 ? url.substring(tosPos, qPos) : url.substring(tosPos);
                                                        } else {
                                                            uri = url;
                                                        }
                                                    }
                                                }
                                            } else {
                                                // 查找 douyinpic.com URL
                                                const picPos = itemStr.indexOf('douyinpic.com');
                                                if (picPos !== -1) {
                                                    let urlStart = itemStr.lastIndexOf('https', picPos);
                                                    if (urlStart !== -1) {
                                                        // 向后查找结束位置 - 使用更智能的检测
                                                        let urlEnd = picPos + 500;
                                                        
                                                        for (let i = picPos + 13; i < itemStr.length && i < picPos + 1000; i++) {
                                                            const char = itemStr[i];
                                                            const nextChar = itemStr[i + 1];
                                                            
                                                            if (char === '"' || 
                                                                char === ',' || 
                                                                char === ' ' ||
                                                                char === '}' ||
                                                                char === ']' ||
                                                                (char === '\\\\' && (nextChar === '"' || nextChar === '\\\\'))) {
                                                                urlEnd = i;
                                                                break;
                                                            }
                                                        }
                                                        
                                                        url = itemStr.substring(urlStart, urlEnd)
                                                            .replace(/\\\\u0026/g, '&')
                                                            .replace(/\\\\/g, '');
                                                        uri = url;
                                                    }
                                                }
                                            }
                                            
                                            if (url && uri && !seenUris.has(uri)) {
                                                seenUris.add(uri);
                                                mediaItems.push({
                                                    index: mediaItems.length + 1,
                                                    type: type,
                                                    url: url
                                                });
                                                console.log(`Item ${itemIndex + 1}: type=${type}, url length=${url.length}`);
                                            }
                                            
                                            // 移动到下一个item
                                            pos = itemEnd;
                                            itemIndex++;
                                        }
                                    }
                                }
                                
                                // ===== 2. 提取 music 对象 =====
                                let musicStart = fullText.indexOf('\\\\"music\\\\":{');
                                if (musicStart === -1) {
                                    musicStart = fullText.indexOf('"music":{');
                                }
                                
                                if (musicStart !== -1) {
                                    const objStart = fullText.indexOf('{', musicStart);
                                    let braceCount = 0;
                                    let musicEnd = -1;
                                    for (let i = objStart; i < fullText.length; i++) {
                                        if (fullText[i] === '{') braceCount++;
                                        else if (fullText[i] === '}') {
                                            braceCount--;
                                            if (braceCount === 0) {
                                                musicEnd = i;
                                                break;
                                            }
                                        }
                                    }
                                    
                                    if (musicEnd !== -1) {
                                        const musicObjStr = fullText.substring(objStart, musicEnd + 1);
                                        
                                        // 提取标题
                                        const titlePos = musicObjStr.indexOf('title');
                                        if (titlePos !== -1) {
                                            const start = musicObjStr.indexOf('"', titlePos + 5) + 1;
                                            const end = musicObjStr.indexOf('"', start);
                                            if (end !== -1) {
                                                musicTitle = musicObjStr.substring(start, end);
                                            }
                                        }
                                        
                                        // 提取作者
                                        const authorPos = musicObjStr.indexOf('author');
                                        if (authorPos !== -1) {
                                            const start = musicObjStr.indexOf('"', authorPos + 6) + 1;
                                            const end = musicObjStr.indexOf('"', start);
                                            if (end !== -1) {
                                                musicAuthor = musicObjStr.substring(start, end);
                                            }
                                        }
                                        
                                        // 提取音频URL
                                        const mp3Pos = musicObjStr.indexOf('.mp3');
                                        if (mp3Pos !== -1) {
                                            let urlStart = musicObjStr.lastIndexOf('https', mp3Pos);
                                            if (urlStart !== -1) {
                                                // 向后查找结束位置
                                                let urlEnd = mp3Pos + 4;
                                                for (let i = mp3Pos + 4; i < musicObjStr.length && i < mp3Pos + 500; i++) {
                                                    const char = musicObjStr[i];
                                                    const nextChar = musicObjStr[i + 1];
                                                    
                                                    if (char === '"' || 
                                                        char === ',' ||
                                                        char === ' ' ||
                                                        char === '}' ||
                                                        (char === '\\\\' && (nextChar === '"' || nextChar === '\\\\'))) {
                                                        urlEnd = i;
                                                        break;
                                                    }
                                                }
                                                musicUrl = musicObjStr.substring(urlStart, urlEnd)
                                                    .replace(/\\\\u0026/g, '&')
                                                    .replace(/\\\\/g, '');
                                            }
                                        }
                                        
                                        if (musicUrl) {
                                            console.log('Extracted music:', musicTitle, '-', musicAuthor);
                                        }
                                    }
                                }
                            }
                            
                            console.log('Extracted', mediaItems.length, 'media items:', 
                                mediaItems.filter(m => m.type === 'video').length, 'videos +', 
                                mediaItems.filter(m => m.type === 'image').length, 'images');
                            
                        } catch (e) {
                            console.log('Extraction error:', e.message);
                        }
                        
                        // 兼容旧格式
                        const videoUrls = mediaItems.filter(m => m.type === 'video').map(m => m.url);
                        const imageUrls = mediaItems.filter(m => m.type === 'image').map(m => m.url);
                        
                        result.media_items = mediaItems;
                        result.video_urls = videoUrls;
                        result.image_urls = imageUrls;
                        result.is_dynamic = videoUrls.length > 0;
                        result.music_url = musicUrl;
                        result.music_title = musicTitle;
                        result.music_author = musicAuthor;

                        // DOM Fallback: 如果JS提取失败，尝试从DOM中提取
                        // 1. 尝试 [data-e2e="live-avatar"] img (针对图集/Note页面)
                        if (!result.author_avatar_url) {
                            try {
                                const avatarImg = document.querySelector('[data-e2e="live-avatar"] img') ||
                                                  document.querySelector('[data-e2e="user-avatar"] img') || 
                                                  document.querySelector('.avatar-component img') ||
                                                  document.querySelector('.author-avatar img') ||
                                                  Array.from(document.querySelectorAll('img')).find(img => img.src && img.src.includes('aweme-avatar'));
                                                  
                                if (avatarImg && avatarImg.src) {
                                    result.author_avatar_url = avatarImg.src;
                                }
                            } catch (e) {}
                        }
                        
                        // 强制提升分辨率：如果获取到的头像包含 100x100，替换为 1080x1080
                        if (result.author_avatar_url && result.author_avatar_url.includes('100x100')) {
                             result.author_avatar_url = result.author_avatar_url.replace('100x100', '1080x1080');
                        }

                        
                        if (mediaItems.length > 0) {
                            result.cover_url = mediaItems[0].url;
                        }
                        
                        return result;
                    }
                """)
                
                logger.debug(f"[gallery] 提取到图集信息: {gallery_info}")
                
                # 验证提取结果
                if not gallery_info['note_id']:
                    logger.error("[gallery] 无法提取note_id")
                    return None
                
                # 优先检查是否为动态图集(视频轮播)
                if gallery_info.get('video_urls') and len(gallery_info['video_urls']) > 0:
                    logger.debug(f"[gallery] 成功提取到动态图集，共 {len(gallery_info['video_urls'])} 个视频")
                    return gallery_info
                
                # 其次检查是否为静态图集
                if gallery_info['image_urls'] and len(gallery_info['image_urls']) > 0:
                    logger.debug(f"[gallery] 成功提取到静态图集，共 {len(gallery_info['image_urls'])} 张图片")
                    return gallery_info
                
                # 如果没有提取到图片，检查是否包含真正的视频
                has_video = await page.evaluate("""
                    () => {
                        const videos = document.querySelectorAll('video');
                        // 检查是否有真正的视频内容（更严格的检测）
                        for (const video of videos) {
                            const src = video.currentSrc || video.src;
                            if (src && 
                                (src.includes('douyinvod.com') || 
                                 (src.includes('.mp4') && !src.includes('.mp3') && !src.includes('static')))) {
                                // 额外检查：确保video元素有实际的视频尺寸
                                if (video.videoWidth > 0 && video.videoHeight > 0) {
                                    return true;
                                }
                            }
                        }
                        return false;
                    }
                """)
                
                if has_video:
                    logger.debug(f"[gallery] 未提取到图片且检测到视频，按视频处理: {url}")
                    return None  # 返回None让系统按视频处理
                else:
                    logger.error("[gallery] 无法提取图片URL，且未检测到视频")
                    return None
                
            finally:
                logger.debug("[gallery] 关闭 page/context 前")
                await page.close()
                await context.close()
                logger.debug("[gallery] 关闭 page/context 后")
                
        except Exception as e:
            logger.error(f"[gallery] 提取抖音图集失败: {str(e)}")
            return None
        
    async def _set_platform_headers(self, page, platform: Platform):
        """设置平台特定的请求头（仅抖音）"""
        headers = {
            Platform.DOUYIN: {'Referer': 'https://www.douyin.com/'},
            Platform.DOUYIN_GALLERY: {'Referer': 'https://www.douyin.com/'},  # 图集使用相同的Referer
        }
        
        if platform in headers:
            await page.set_extra_http_headers(headers[platform])
            
    async def _get_video_title(self, page, platform: Platform) -> str:
        """获取视频标题（仅抖音）"""
        try:
            import re
            # 默认的页面标题获取逻辑
            page_title = await page.title()
            if page_title and page_title.strip():
                clean_title = page_title.strip()
                return re.sub(r'[<>:"/\\|?*]', '_', clean_title)[:100]
        except Exception as e:
            logger.warning(f"获取标题失败: {str(e)}")
        return None

    async def _get_video_author(self, page, platform: Platform) -> str:
        """获取视频作者"""
        try:
            if platform == Platform.DOUYIN:
                # 1. 尝试从API获取作者信息
                try:
                    html = await page.content()
                    # 从页面内容中提取video_id
                    video_id_match = re.search(r'"aweme_id"\s*:\s*"(\d+)"', html)
                    if video_id_match:
                        video_id = video_id_match.group(1)
                        # 构建API请求
                        api_url = f"https://www.douyin.com/aweme/v1/web/aweme/detail/?device_platform=webapp&aid=6383&channel=channel_pc_web&aweme_id={video_id}"
                        async with httpx.AsyncClient() as client:
                            response = await client.get(api_url)
                            if response.status_code == 200:
                                data = response.json()
                                author_info = data.get('aweme_detail', {}).get('author', {})
                                if author_info.get('nickname'):
                                    logger.debug(f"[extract] 通过API获取作者成功: {author_info['nickname']}")
                                    return author_info['nickname']
                except Exception as e:
                    logger.debug(f"[extract] 通过API获取作者失败: {str(e)}")

                # 2. 尝试从页面源码中提取作者信息
                try:
                    # 调试：输出页面源码中所有可能的作者信息
                    # 开始提取作者信息
                    
                    # 查找所有可能的作者相关字段
                    debug_patterns = [
                        r'"nickname":\s*"([^"]+)"',
                        r'"userName":\s*"([^"]+)"',
                        r'"author":\s*"([^"]+)"',
                        r'"creator":\s*"([^"]+)"',
                        r'"user":\s*{[^}]*"nickname":\s*"([^"]+)"[^}]*}',
                        r'"user":\s*{[^}]*"userName":\s*"([^"]+)"[^}]*}',
                    ]
                    
                    # 页面源码中的作者相关信息
                    for pattern in debug_patterns:
                        matches = re.findall(pattern, html, re.DOTALL)
                        if matches:
                            # 模式匹配结果
                            pass
                    
                except Exception as e:
                    logger.debug(f"[extract] 从页面源码提取作者失败: {str(e)}")

                # 3. 最后尝试从DOM元素获取
                try:
                    selectors = [
                        '[data-e2e="user-name"]',
                        '.author-name',
                        '.nickname',
                        '.user-info .name'
                    ]
                    for selector in selectors:
                        element = await page.query_selector(selector)
                        if element:
                            text = await element.text_content()
                            if text and text.strip():
                                author = text.strip()
                                # 通过DOM元素获取作者成功
                                return author
                except Exception as e:
                    logger.debug(f"[extract] 从DOM获取作者失败: {str(e)}")

                logger.warning("[extract] 所有方式获取作者均失败")
            else:
                selectors = {
                    Platform.BILIBILI: '.up-name, .username',
                    Platform.KUAISHOU: '.profile-user-name, .author',
                    Platform.WEIBO: '.username, .author',
                    Platform.XIGUA: '.author-name, .username',
                    Platform.YOUTUBE: '.channel-name, .owner'
                }
                selector = selectors.get(platform, '.author, .username')
                author_element = await page.query_selector(selector)
                if author_element:
                    text = await author_element.text_content()
                    if text and text.strip():
                        logger.debug(f"[extract] 获取{platform}平台作者成功: {text.strip()}")
                        return text.strip()

        except Exception as e:
            logger.warning(f"[extract] 获取作者失败: {str(e)}")
        return None
        
    async def _get_video_thumbnail(self, page, platform: Platform, video_id: str = None, download_url: str = None, task_id: str = None, save_dir: str = None, for_share: bool = False) -> str:
        """获取视频缩略图URL（仅抖音）"""
        try:
            # 如果没有 video_id，尝试从 download_url 中提取
            if platform == Platform.DOUYIN and not video_id and download_url:
                # download_url 格式: https://aweme.snssdk.com/aweme/v1/play/?video_id=v1e00fgi0000d4ikj4vog65k8gp65vo0&...
                import re
                m = re.search(r'video_id=([a-zA-Z0-9_]+)', download_url)
                if m:
                    video_id = m.group(1)
                    logger.debug(f"[thumbnail] 从下载链接提取 video_id: {video_id}")
            
            if platform == Platform.DOUYIN and video_id:
                # 抖音缩略图URL格式 - 多种尝试
                thumbnail_urls = [
                    f"https://p3-sign.douyinpic.com/tos-cn-p-0015/{video_id}~tplv-dy-360p.jpeg",
                    f"https://p16-sign.douyinpic.com/tos-cn-p-0015/{video_id}~tplv-dy-360p.jpeg",
                    f"https://p3-sign.douyinpic.com/tos-cn-p-0015/{video_id}~tplv-dy-720p.jpeg",
                    f"https://p16-sign.douyinpic.com/tos-cn-p-0015/{video_id}~tplv-dy-720p.jpeg",
                    f"https://p3-sign.douyinpic.com/tos-cn-p-0015/{video_id}~tplv-dy-1080p.jpeg",
                    f"https://p16-sign.douyinpic.com/tos-cn-p-0015/{video_id}~tplv-dy-1080p.jpeg",
                    # 备用格式
                    f"https://p3-sign.douyinpic.com/tos-cn-p-0015/{video_id}~tplv-dy-360p.webp",
                    f"https://p16-sign.douyinpic.com/tos-cn-p-0015/{video_id}~tplv-dy-360p.webp",
                ]
                
                # 抖音缩略图请求头
                headers = {
                    'User-Agent': get_random_mobile_user_agent(),  # 使用随机User-Agent
                    'Accept': 'image/webp,image/apng,image/*,*/*;q=0.8',
                    'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
                    'Referer': 'https://www.douyin.com/',
                    'Connection': 'keep-alive',
                }
                
                # 验证缩略图URL是否有效
                async with httpx.AsyncClient() as client:
                    for thumbnail_url in thumbnail_urls:
                        try:
                            response = await client.head(thumbnail_url, headers=headers, timeout=3)
                            if response.status_code == 200:
                                logger.debug(f"[thumbnail] 成功获取缩略图: {safe_log_url(thumbnail_url)}")
                                return thumbnail_url
                        except Exception as e:
                            logger.debug(f"[thumbnail] 尝试失败 {safe_log_url(thumbnail_url)}: {str(e)}")
                            continue
                            
            # 如果通过video_id获取失败，尝试从页面中提取缩略图
            if platform == Platform.DOUYIN:
                try:
                    # 尝试从页面提取缩略图
                    # 抖音视频缩略图选择器
                    thumbnail_selectors = [
                        'video[poster]',
                        'img[src*="douyinpic"]',
                        'img[src*="douyin"]',
                        '.video-poster img',
                        '[data-e2e="video-poster"] img',
                        '.video-cover img',
                        '.cover img',
                        'img[alt*="视频"]',
                        'img[alt*="封面"]'
                    ]
                    
                    for selector in thumbnail_selectors:
                        try:
                            element = await page.query_selector(selector)
                            if element:
                                if selector == 'video[poster]':
                                    thumbnail_url = await element.get_attribute('poster')
                                else:
                                    thumbnail_url = await element.get_attribute('src')
                                
                                if thumbnail_url and ('douyinpic' in thumbnail_url or 'douyin' in thumbnail_url):
                                    # 从页面提取到缩略图
                                    return thumbnail_url
                        except Exception as e:
                            logger.debug(f"[thumbnail] 选择器 {selector} 失败: {str(e)}")
                            continue
                            
                    # 如果还是没找到，尝试从页面截图作为缩略图
                    logger.debug("[thumbnail] 尝试页面截图作为缩略图")
                    try:
                        # 截取页面的一部分作为缩略图
                        screenshot = await page.screenshot(
                            clip={'x': 0, 'y': 0, 'width': 300, 'height': 200},
                            type='jpeg',
                            quality=80
                        )
                        # 这里可以保存截图到本地或上传到图床
                        # 暂时返回None，后续可以实现本地存储
                        logger.debug("[thumbnail] 页面截图成功，但暂未实现存储")
                    except Exception as e:
                        logger.debug(f"[thumbnail] 页面截图失败: {str(e)}")
                        
                except Exception as e:
                    logger.warning(f"[thumbnail] 从页面提取缩略图失败: {str(e)}")
        except Exception as e:
            logger.warning(f"[thumbnail] 获取缩略图失败: {str(e)}")
        return None

    async def _quick_ffmpeg_screenshot(self, video_url: str, timeout: int = 5) -> str:
        """快速截帧并返回Base64编码的图片数据"""
        import tempfile
        import base64
        import subprocess
        import time
        
        try:
            logger.debug(f"[thumbnail] 开始快速截帧: {video_url}")
            
            # 使用临时文件
            with tempfile.NamedTemporaryFile(suffix='.jpg', delete=True) as temp_file:
                # 尝试多个时间点的截帧
                time_points = [0.5, 1, 2, 3]  # 多个时间点
                
                for time_point in time_points:
                    try:
                        # ffmpeg命令：从视频URL截取指定时间点的帧
                        cmd = [
                            "ffmpeg", "-y",  # 覆盖输出文件
                            "-ss", str(time_point),  # 从指定秒开始
                            "-i", video_url, # 输入视频URL
                            "-frames:v", "1", # 只截取1帧
                            "-q:v", "2",     # 高质量
                            "-f", "image2",  # 强制输出格式
                            "-vcodec", "mjpeg",  # 使用mjpeg编码器
                            "-pix_fmt", "yuv420p",  # 标准像素格式
                            "-colorspace", "bt709",  # 标准色彩空间
                            "-v", "error",   # 只显示错误信息
                            temp_file.name   # 输出到临时文件
                        ]
                        
                        logger.debug(f"[thumbnail] 尝试时间点 {time_point}s，ffmpeg命令: {' '.join(cmd)}")
                        
                        # 执行ffmpeg命令，设置超时
                        start_time = time.time()
                        result = subprocess.run(
                            cmd, 
                            capture_output=True, 
                            text=True, 
                            timeout=timeout
                        )
                        elapsed_time = time.time() - start_time
                        
                        if result.returncode == 0:
                            # 检查临时文件是否存在且有内容
                            if os.path.exists(temp_file.name) and os.path.getsize(temp_file.name) > 0:
                                # 读取文件并转换为Base64
                                with open(temp_file.name, "rb") as f:
                                    image_data = f.read()
                                    base64_data = base64.b64encode(image_data).decode('utf-8')
                                    thumbnail_url = f"data:image/jpeg;base64,{base64_data}"
                                    
                                logger.debug(f"[thumbnail] 截帧成功，时间点: {time_point}s，耗时: {elapsed_time:.2f}s，文件大小: {len(image_data)} bytes，Base64长度: {len(base64_data)}")
                                return thumbnail_url
                            else:
                                logger.warning(f"[thumbnail] 时间点 {time_point}s 的临时文件为空或不存在")
                                continue
                        else:
                            logger.warning(f"[thumbnail] 时间点 {time_point}s ffmpeg执行失败: {result.stderr}")
                            continue
                            
                    except subprocess.TimeoutExpired:
                        logger.warning(f"[thumbnail] 时间点 {time_point}s ffmpeg截帧超时 ({timeout}s)")
                        continue
                    except Exception as e:
                        logger.warning(f"[thumbnail] 时间点 {time_point}s ffmpeg截帧异常: {str(e)}")
                        continue
                
                # 如果所有时间点都失败，尝试使用更简单的命令
                try:
                    logger.debug("[thumbnail] 尝试使用简化命令截帧")
                    simple_cmd = [
                        "ffmpeg", "-y",
                        "-i", video_url,
                        "-vframes", "1",
                        "-q:v", "2",
                        temp_file.name
                    ]
                    
                    result = subprocess.run(
                        simple_cmd, 
                        capture_output=True, 
                        text=True, 
                        timeout=timeout
                    )
                    
                    if result.returncode == 0 and os.path.exists(temp_file.name) and os.path.getsize(temp_file.name) > 0:
                        with open(temp_file.name, "rb") as f:
                            image_data = f.read()
                            base64_data = base64.b64encode(image_data).decode('utf-8')
                            thumbnail_url = f"data:image/jpeg;base64,{base64_data}"
                            
                        logger.debug(f"[thumbnail] 简化命令截帧成功，文件大小: {len(image_data)} bytes")
                        return thumbnail_url
                        
                except Exception as e:
                    logger.warning(f"[thumbnail] 简化命令截帧失败: {str(e)}")
                
                # 所有方法都失败
                raise Exception("所有截帧方法都失败")
                    
        except Exception as e:
            logger.error(f"[thumbnail] ffmpeg截帧最终失败: {str(e)}")
            raise Exception(f"ffmpeg截帧失败: {str(e)}")
        
    async def _validate_video_url(self, url: str) -> bool:
        """验证视频URL是否有效"""
        try:
            if not url or not isinstance(url, str):
                return False
                
            async with httpx.AsyncClient() as client:
                response = await client.head(url, follow_redirects=True)
                
                if response.status_code != 200:
                    return False
                    
                content_type = response.headers.get("content-type", "").lower()
                content_length = response.headers.get("content-length", "0")
                
                if not any(t in content_type for t in ["video", "application/octet-stream"]):
                    return False
                    
                if not content_length.isdigit() or int(content_length) < 102400:  # 至少100KB
                    return False
                    
            return True
                
        except Exception as e:
            logger.warning(f"URL验证失败: {str(e)}")
            return False

    async def _validate_image_url(self, url: str, try_get: bool = False) -> bool:
        """验证图片URL是否有效（返回200且为image类型），HEAD失败可选用GET再试"""
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.head(url, timeout=5)
                if resp.status_code == 200 and resp.headers.get('content-type', '').startswith('image/'):
                    return True
                if try_get:
                    resp = await client.get(url, timeout=5)
                    if resp.status_code == 200 and resp.headers.get('content-type', '').startswith('image/'):
                        return True
        except Exception:
            pass
        return False

# 配置日志记录 (暂时保留，后续统一)
# logging.basicConfig(
#     level=logging.INFO,
#     format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
#     handlers=[
#         logging.FileHandler('/app/logs/dyd.log'),
#         logging.StreamHandler()
#     ]
# )
# logger = logging.getLogger(__name__)

# 数据库设置 (暂时保留，后续统一)
# DATABASE_URL = "sqlite:////app/database/tasks.db"
# engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
# SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
# Base = declarative_base()

# 创建数据库表 (暂时保留，后续统一)
# Base.metadata.create_all(bind=engine)

# 使用统计
usage_stats = {
    "parse_requests": 0,
    "successful_requests": 0,
    "failed_requests": 0,
    "daily_stats": {},
    "last_reset": datetime.now().date().isoformat()
}

class RateLimiter:
    def __init__(self, max_requests: int = 30, time_window: int = 60):  # 提升到30个请求/分钟
        self.max_requests = max_requests
        self.time_window = time_window
        self.requests = []

    async def can_make_request(self) -> bool:
        now = datetime.now()
        self.requests = [req_time for req_time in self.requests 
                        if (now - req_time).total_seconds() < self.time_window]
        
        if len(self.requests) < self.max_requests:
            self.requests.append(now)
            return True
        return False

    def get_remaining_requests(self) -> int:
        now = datetime.now()
        self.requests = [req_time for req_time in self.requests 
                        if (now - req_time).total_seconds() < self.time_window]
        return self.max_requests - len(self.requests)

# 创建限流器实例
rate_limiter = RateLimiter()

class VideoRequest(BaseModel):
    url: str

class BatchVideoRequest(BaseModel):
    urls: List[str] = Field(..., min_items=1, max_items=5)  # 限制批量数量为5个
    concurrent_limit: int = Field(default=2, ge=1, le=5)  # 并发限制提升到最多5个

class DownloadRequest(BaseModel):
    url: str
    generate_nfo: bool = True  # 是否生成NFO文件，默认开启（仅对手动下载生效）

# --- Douyin下载任务管理 ---
dyd_cancel_flags = {}

def now_beijing():
    return datetime.now(timezone(timedelta(hours=8)))

# 进度回写
def update_dyd_task_progress(task_id: str, status: TaskStatus, progress: float = None, error: str = None, filename: str = None):
    """更新任务进度"""
    import os  # 在函数开头导入，避免作用域问题
    try:
        db = next(get_db())
        try:
            # 更新任务状态
            task = db.query(Task).filter(Task.id == task_id).first()
            if task:
                task.status = status.value
                if progress is not None:
                    task.progress = float(progress)
                if error:
                    task.error_message = error
                if filename:
                    task.filename = filename
                task.updated_at = datetime.now()
                
                # 如果任务完成或失败，更新订阅视频状态
                if status in [TaskStatus.COMPLETED, TaskStatus.ERROR]:
                    video = db.query(SubscriptionVideo).filter(
                        SubscriptionVideo.download_task_id == task_id
                    ).first()
                    if video:
                        if status == TaskStatus.COMPLETED:
                            video.downloaded = "true"
                            video.error_message = None
                        else:
                            video.downloaded = "false"  # 确保下载失败时设置为false
                            video.error_message = error
                
                db.commit()
                # 仅在非下载状态，或者下载刚开始时打印日志，避免刷屏
                should_log = status != TaskStatus.DOWNLOADING or (progress is not None and progress <= 0.1)
                if should_log:
                    logger.info(f"已更新任务 {task_id} 状态: {status.value}, 进度: {progress}")
                
                # 如果任务完成或失败，记录详细信息并发送通知
                if status in [TaskStatus.COMPLETED, TaskStatus.ERROR]:
                    # 1. 尝试获取关联的订阅视频信息（用于丰富通知内容）
                    video = db.query(SubscriptionVideo).filter(
                        SubscriptionVideo.download_task_id == task_id
                    ).first()
                    
                    # 2. 准备基础数据
                    try:
                        db.refresh(task)  # 强制从数据库刷新，获取解析后的最新标题和文件名
                    except Exception as e:
                        logger.warning(f"刷新任务数据失败: {e}")

                    video_title = task.title or "未知视频"
                    author_name = "手动下载"
                    platform_name = task.source or "抖音"
                    current_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                    
                    # 3. 如果是订阅任务，丰富信息
                    if video:
                        video_title = video.title or video_title # 优先使用订阅记录中的标题
                        try:
                            # 标记订阅视频状态
                            if status == TaskStatus.COMPLETED:
                                video.downloaded = "true"
                                video.error_message = None
                                logger.info(f"任务 {task_id} 完成，视频 {video.title} 标记为已下载")
                            else:
                                video.downloaded = "false"
                                video.error_message = error
                                logger.info(f"任务 {task_id} 失败，视频 {video.title} 错误信息: {error}")
                            
                            # 获取作者名
                            subscription = db.query(Subscription).filter(Subscription.id == video.subscription_id).first()
                            if subscription:
                                author_name = f"订阅博主: {subscription.nickname or '未知'}"
                            
                            if video.extra_data:
                                import json
                                try:
                                    extra_data = json.loads(video.extra_data)
                                    if 'author' in extra_data:
                                        author_name = f"订阅博主: {extra_data['author']}"
                                except:
                                    pass
                        except Exception as e:
                            logger.warning(f"获取订阅详细信息失败: {e}")
                    
                    # 4. 兜底标题优化：如果标题还是URL且有文件名，则使用文件名
                    if video_title.startswith('http') and task.filename:
                        video_title = os.path.splitext(task.filename)[0]
                    elif not video_title or video_title == "未知视频":
                        if task.filename:
                            video_title = os.path.splitext(task.filename)[0]
                    
                    # 4. 发送通知
                    try:
                        import aiohttp
                        import asyncio
                        import threading
                        
                        # 构造通知内容
                        is_gallery_task = False
                        if status == TaskStatus.COMPLETED:
                            if task.filename:
                                try:
                                    check_path = f"/app/downloads/{task.filename}" if not task.filename.startswith('/') else task.filename
                                    is_gallery_task = os.path.isdir(check_path)
                                except Exception:
                                    is_gallery_task = False
                            n_title = f"🎉 下载完成 ({platform_name})"
                            if is_gallery_task:
                                n_content = f"图集《{video_title}》下载完成！\n\n🏷️ 来源: {platform_name}\n👤 {author_name}\n⏰ 完成时间: {current_time}"
                            else:
                                n_content = f"视频《{video_title}》下载完成！\n\n🏷️ 来源: {platform_name}\n👤 {author_name}\n⏰ 完成时间: {current_time}"
                            endpoint = "download-completed"
                        else:
                            n_title = f"❌ 下载失败 ({platform_name})"
                            n_content = f"视频《{video_title}》下载失败！\n\n🏷️ 来源: {platform_name}\n👤 {author_name}\n🚫 错误信息: {error}\n⏰ 失败时间: {current_time}"
                            endpoint = "download-error"
                            
                        # 构建封面图URL和图集媒体列表（用于Telegram显示/发送）
                        cover_url = None
                        gallery_path_url = None
                        gallery_items = []
                        if status == TaskStatus.COMPLETED and task.filename:
                            # 构建完整文件路径
                            final_path = f"/app/downloads/{task.filename}" if not task.filename.startswith('/') else task.filename

                            if os.path.isdir(final_path):
                                gallery_dir = final_path
                            else:
                                gallery_dir = os.path.dirname(final_path)

                            # 图集目录路径（给 bot/通知侧做相册发送）
                            try:
                                rel_gallery_path = os.path.relpath(gallery_dir, '/app/downloads')
                                gallery_path_url = f"/downloads/{quote(rel_gallery_path)}"
                            except Exception:
                                gallery_path_url = None

                            # 扫描目录内媒体文件，供 Telegram sendMediaGroup 使用
                            try:
                                media_exts = {'.jpg', '.jpeg', '.png', '.webp', '.bmp', '.mp4', '.mov', '.m4v', '.webm'}
                                for name in sorted(os.listdir(gallery_dir)):
                                    item_path = os.path.join(gallery_dir, name)
                                    if not os.path.isfile(item_path):
                                        continue
                                    _, ext = os.path.splitext(name.lower())
                                    if ext not in media_exts:
                                        continue
                                    rel_item_path = os.path.relpath(item_path, '/app/downloads')
                                    gallery_items.append(f"/downloads/{quote(rel_item_path)}")
                            except Exception as e:
                                logger.warning(f"扫描图集媒体失败: {e}")

                            # 尝试查找封面图
                            video_dir = gallery_dir
                            video_basename = os.path.splitext(os.path.basename(final_path.rstrip('/')))[0]
                            
                            # 可能的封面图文件名
                            possible_covers = [
                                f"{video_basename}-poster.jpg",
                                f"{video_basename}.jpg",
                                "poster.jpg",
                                "cover.jpg"
                            ]
                            
                            for cover_name in possible_covers:
                                cover_path = os.path.join(video_dir, cover_name)
                                if os.path.exists(cover_path):
                                    # 转换为相对于 downloads 目录的路径
                                    rel_path = os.path.relpath(cover_path, '/app/downloads')
                                    # 构建可访问的URL（需要URL编码）
                                    cover_url = f"/downloads/{quote(rel_path)}"
                                    logger.debug(f"找到封面图: {cover_url}")
                                    break
                        
                        notification_data = {
                            "title": n_title,
                            "content": n_content,
                            "user_id": "default"
                        }
                        
                        # 构建 extra_data：保持原有封面字段，同时补齐图集字段
                        extra_data = {}
                        if cover_url:
                            extra_data.update({
                                "cover": cover_url,
                                "cover_url": cover_url,
                                "poster": cover_url
                            })
                        if gallery_path_url:
                            extra_data["gallery_path"] = gallery_path_url
                        if gallery_items:
                            # 同时写入多种兼容字段，兼容通知层和 bot 解析
                            extra_data["gallery"] = gallery_items
                            extra_data["gallery_urls"] = gallery_items
                            extra_data["media_urls"] = gallery_items
                            extra_data["image_urls"] = gallery_items
                            extra_data["media_items"] = gallery_items
                        if getattr(task, "id", None):
                            extra_data["task_id"] = task.id
                        if getattr(task, "url", None):
                            extra_data["url"] = task.url
                        if getattr(task, "subscription_id", None):
                            extra_data["subscription_id"] = task.subscription_id

                        if extra_data:
                            notification_data["extra_data"] = extra_data
                        
                        def send_notification_thread():
                            try:
                                async def send_notification():
                                    try:
                                        connector = aiohttp.UnixConnector(path="/app/sockets/easy-vdl.sock")
                                        async with aiohttp.ClientSession(connector=connector) as session:
                                            async with session.post(f"http://localhost/api/notifications/{endpoint}", json=notification_data) as response:
                                                if response.status == 200:
                                                    logger.info(f"通知发送成功: {video_title}")
                                                else:
                                                    logger.warning(f"通知发送失败: {response.status}")
                                    except Exception as e:
                                        logger.warning(f"发送通知异常: {str(e)}")
                                
                                loop = asyncio.new_event_loop()
                                asyncio.set_event_loop(loop)
                                try:
                                    loop.run_until_complete(send_notification())
                                finally:
                                    loop.close()
                            except Exception as e:
                                logger.warning(f"发送通知线程执行失败: {str(e)}")
                        
                        thread = threading.Thread(target=send_notification_thread)
                        thread.daemon = True
                        thread.start()
                                
                    except Exception as e:
                        logger.warning(f"启动通知线程失败: {str(e)}")
                

                # 添加WebSocket进度更新
                try:
                    import asyncio
                    from routers.websocket import broadcast_message
                    
                    # 构造进度更新数据 - 包含完整字段
                    progress_data = {
                        'type': 'progress_update',
                        'task': {
                            'id': task_id,
                            'progress': task.progress,
                            'status': task.status,
                            'updated_at': task.updated_at.isoformat() if task.updated_at else None,
                            'filename': task.filename,
                            'source': task.source,
                            'title': task.title,
                            'url': task.url,
                            'original_url': task.original_url,
                            'subscription_id': task.subscription_id,
                            'error_message': task.error_message,
                            'created_at': task.created_at.isoformat() if task.created_at else None
                        }
                    }
                    
                    # 异步发送WebSocket更新
                    async def send_progress_update():
                        try:
                            await broadcast_message('downloads', progress_data)
                        except Exception as e:
                            logger.warning(f"发送WebSocket进度更新失败: {str(e)}")
                    
                    # 检查是否有运行中的事件循环
                    try:
                        loop = asyncio.get_running_loop()
                        # 如果当前事件循环正在运行，使用create_task
                        asyncio.create_task(send_progress_update())
                    except RuntimeError:
                        # 如果没有运行中的事件循环，创建新的事件循环
                        loop = asyncio.new_event_loop()
                        asyncio.set_event_loop(loop)
                        try:
                            loop.run_until_complete(send_progress_update())
                        finally:
                            loop.close()
                            
                except Exception as e:
                    logger.warning(f"WebSocket进度更新失败: {str(e)}")
                    # 不抛出异常，避免影响下载流程
            else:
                logger.warning(f"未找到任务: {task_id}")
        except Exception as e:
            db.rollback()
            logger.error(f"更新任务进度失败: {str(e)}")
        finally:
            try:
                db.rollback()
            except Exception:
                pass
            db.close()
    except Exception as e:
        logger.error(f"更新任务进度时发生错误: {str(e)}")

def sanitize_filename(filename, max_length=80):
    """清理文件名，只做最基本的文件系统兼容性处理"""
    if filename is None:
        filename = ""
    filename = str(filename)
    # 移除BOM和不可见字符
    filename = filename.replace('\ufeff', '')
    # 移除其它常见不可见字符（如零宽空格、emoji 变体选择符等）
    filename = re.sub(r'[\u200b\u200c\u200d\uFEFF\uFE0E\uFE0F]', '', filename)
    # 移除不间断空格（\u00A0）
    filename = filename.replace('\u00A0', ' ')
    # 移除表情符号和特殊Unicode字符
    filename = re.sub(r'[\U0001F600-\U0001F64F\U0001F300-\U0001F5FF\U0001F680-\U0001F6FF\U0001F1E0-\U0001F1FF\U00002600-\U000027BF\U0001F900-\U0001F9FF]', '', filename)
    # 移除HTML实体（如&nbsp;）
    filename = re.sub(r'&nbsp;', ' ', filename)
    # 移除文件系统不允许的字符和特殊字符（包括%符号，可能导致FFmpeg路径问题）
    filename = re.sub(r'[\\/:*?"<>|#%]', '_', filename)
    # 移除多余空格和换行
    filename = re.sub(r'\s+', ' ', filename).strip()
    # 避免出现仅由点/下划线组成的“不可读名称”
    if not filename or filename.strip('._ ') == '':
        filename = "untitled"
    # 限制长度
    if len(filename) > max_length:
        filename = filename[:max_length-3] + '...'
    return filename

def generate_nfo_douyin_xhs(video_info, save_dir, filename_base):
    title = video_info.title or 'Unknown Title'
    author = video_info.author or 'Unknown'
    platform = video_info.platform or 'unknown'
    share_url = video_info.share_url or ''
    description = ''  # 可扩展：如有简介字段可补充
    create_time = video_info.create_time or ''
    # 年份处理
    year = ''
    if create_time:
        try:
            dt = datetime.strptime(create_time[:10], '%Y-%m-%d')
            year = dt.strftime('%Y')
        except Exception:
            year = create_time[:4] if len(create_time) >= 4 else ''
    nfo_content = f'''<?xml version="1.0" encoding="UTF-8" standalone="yes" ?>
<movie>
  <title>{title}</title>
  <originaltitle>{title}</originaltitle>
  <year>{year}</year>
  <plot>{description}</plot>
  <director>{author}</director>
  <premiered>{create_time}</premiered>
  <studio>{platform}</studio>
  <trailer>{share_url}</trailer>
  <source>{platform}</source>
  <thumb>{filename_base}-poster.jpg</thumb>
  <actor>
    <name>{author}</name>
    <role>Uploader</role>
    <thumb>{video_info.author_avatar_url or ''}</thumb>
  </actor>
</movie>

'''
    nfo_path = os.path.join(save_dir, f'{filename_base}.nfo')
    with open(nfo_path, 'w', encoding='utf-8') as f:
        f.write(nfo_content)
            # 已生成NFO文件

def generate_nfo_gallery(video_info, save_dir, filename_base, nfo_filename=None, thumb_filename=None):

    """为图集生成NFO文件"""
    title = video_info.title or 'Unknown Gallery'
    author = video_info.author or 'Unknown'
    platform = video_info.platform or 'unknown'
    share_url = video_info.share_url or ''
    description = f'图集包含 {video_info.gallery_count} 张图片'  # 图集描述
    create_time = video_info.create_time or ''
    
    # 年份处理
    year = ''
    if create_time:
        try:
            dt = datetime.strptime(create_time[:10], '%Y-%m-%d')
            year = dt.strftime('%Y')
        except Exception:
            year = create_time[:4] if len(create_time) >= 4 else ''
    
    # 允许指定缩略图和输出文件名，用于为每个分段视频生成独立NFO
    thumb_file = thumb_filename or f'{filename_base}_001.jpg'
    output_nfo = nfo_filename or f'{filename_base}.nfo'
    
    # 获取文件名（不含扩展名），作为title后缀
    part_suffix = ""
    if nfo_filename:
        # 尝试从文件名提取序号，如 xxx_002.nfo -> "(2)"
        import re
        match = re.search(r'_(\d+)\.nfo$', nfo_filename)
        if match:
             part_suffix = f" ({int(match.group(1))})"

    nfo_content = f'''<?xml version="1.0" encoding="UTF-8" standalone="yes" ?>

<movie>
  <title>{title}{part_suffix}</title>
  <originaltitle>{title}</originaltitle>
  <year>{year}</year>
  <plot>{description}</plot>
  <director>{author}</director>
  <premiered>{create_time}</premiered>
  <studio>{platform}</studio>
  <trailer>{share_url}</trailer>
  <source>{platform}</source>
  <genre>图集</genre>
  <tag>图集</tag>
  <tag>图片</tag>
  <thumb>{thumb_file}</thumb>
  <actor>
    <name>{author}</name>

    <role>Uploader</role>
    <thumb>{video_info.author_avatar_url or ''}</thumb>
  </actor>
</movie>

'''
    nfo_path = os.path.join(save_dir, output_nfo)
    with open(nfo_path, 'w', encoding='utf-8') as f:
        f.write(nfo_content)
    # 已生成图集NFO文件


def generate_nfo_douyin_collection(video_info, save_dir, filename_base, collection_name=None, episode_number=None):
    """为抖音合集生成电视剧格式的NFO文件"""
    title = video_info.title or 'Unknown Episode'
    author = video_info.author or 'Unknown'
    platform = video_info.platform or 'unknown'
    share_url = video_info.share_url or ''
    description = video_info.title or ''  # 使用视频标题作为描述
    create_time = video_info.create_time or ''
    
    # 年份处理
    year = ''
    if create_time:
        try:
            dt = datetime.strptime(create_time[:10], '%Y-%m-%d')
            year = dt.strftime('%Y')
        except Exception:
            year = create_time[:4] if len(create_time) >= 4 else ''
    
    # 使用合集名称作为showtitle，如果没有则使用作者名
    showtitle = collection_name or author or 'Unknown Collection'
    
    # 集数处理，如果没有提供则默认为1
    episode_num = episode_number or 1
    
    # 生成剧集NFO文件
    episode_nfo_content = f'''<?xml version="1.0" encoding="UTF-8" standalone="yes" ?>
<episodedetails>
  <title>{title}</title>
  <showtitle>{showtitle}</showtitle>
  <season>1</season>
  <episode>{episode_num}</episode>
  <plot>{description}</plot>
  <director>{author}</director>
  <premiered>{create_time}</premiered>
  <studio>{platform}</studio>
  <trailer>{share_url}</trailer>
  <source>{platform}</source>
  <genre>合集</genre>
  <tag>合集</tag>
  <tag>抖音合集</tag>
  <thumb>{filename_base}-poster.jpg</thumb>
  <actor>
    <name>{author}</name>
    <role>Uploader</role>
    <thumb>{video_info.author_avatar_url or ''}</thumb>
  </actor>
</episodedetails>

'''
    episode_nfo_path = os.path.join(save_dir, f'{filename_base}.nfo')
    with open(episode_nfo_path, 'w', encoding='utf-8') as f:
        f.write(episode_nfo_content)
    
    # 生成tvshow.nfo文件到合集根目录（如果不存在）
    # 现在合集视频直接保存在根目录，所以save_dir就是合集根目录
    tvshow_nfo_path = os.path.join(save_dir, 'tvshow.nfo')
    if not os.path.exists(tvshow_nfo_path):
        tvshow_nfo_content = f'''<?xml version="1.0" encoding="UTF-8" standalone="yes" ?>
<tvshow>
  <title>{showtitle}</title>
  <showtitle>{showtitle}</showtitle>
  <year>{year}</year>
  <plot>抖音合集：{showtitle}</plot>
  <director>{author}</director>
  <studio>{platform}</studio>
  <source>{platform}</source>
  <genre>合集</genre>
  <tag>合集</tag>
  <tag>抖音合集</tag>
  <status>Continuing</status>
  <displayorder>aired</displayorder>
  <displayorder>aired</displayorder>
  <thumb>poster.jpg</thumb>
  <actor>
    <name>{author}</name>
    <role>Uploader</role>
    <thumb>{video_info.author_avatar_url or ''}</thumb>
  </actor>
</tvshow>

'''
        with open(tvshow_nfo_path, 'w', encoding='utf-8') as f:
            f.write(tvshow_nfo_content)
        # 已生成tvshow.nfo文件到合集根目录
    
    # 合集视频现在直接保存在根目录，不需要创建符号链接
    
    # 已生成合集NFO文件

def ensure_douyin_collection_artworks(save_dir: str, episode_poster_path: Optional[str] = None):
    """
    为抖音合集补齐根级封面命名，提升 Jellyfin/Emby 兼容性：
    - poster.jpg
    - season01-poster.jpg
    - folder.jpg
    """
    if not save_dir or not os.path.isdir(save_dir):
        return

    source = None
    if episode_poster_path and os.path.exists(episode_poster_path):
        source = episode_poster_path
    else:
        for name in os.listdir(save_dir):
            if name.endswith("-poster.jpg"):
                source = os.path.join(save_dir, name)
                break
        if not source:
            for name in os.listdir(save_dir):
                if name.lower().endswith(".jpg"):
                    source = os.path.join(save_dir, name)
                    break

    if not source or not os.path.exists(source):
        logger.warning(
            f"[thumbnail] 抖音合集根级封面补齐跳过：未找到可用源图 save_dir={save_dir}, episode_poster_path={episode_poster_path}"
        )
        return

    for target_name in ("poster.jpg", "season01-poster.jpg", "folder.jpg"):
        target_path = os.path.join(save_dir, target_name)
        try:
            if not os.path.exists(target_path):
                shutil.copyfile(source, target_path)
        except Exception as e:
            logger.warning(
                f"[thumbnail] 抖音合集根级封面补齐失败: source={source}, target={target_path}, error={e}"
            )

def create_symlinks_for_jellyfin(collection_root_dir, filename_base):
    """为Jellyfin创建符号链接，让合集能够被识别为电视剧"""
    try:
        # 获取合集根目录（上一级目录）
        collection_dir = os.path.dirname(collection_root_dir)
        
        # 当前视频文件夹路径
        video_folder = collection_root_dir
        
        # 要创建符号链接的文件
        files_to_link = [
            f'{filename_base}.mp4',
            f'{filename_base}.nfo',
            f'{filename_base}-poster.jpg'
        ]
        
        for file_name in files_to_link:
            source_path = os.path.join(video_folder, file_name)
            link_path = os.path.join(collection_dir, file_name)
            
            # 检查源文件是否存在
            if os.path.exists(source_path):
                # 如果符号链接已存在，先删除
                if os.path.exists(link_path) or os.path.islink(link_path):
                    try:
                        os.remove(link_path)
                    except Exception as e:
                        # 删除旧符号链接失败
                        pass
                
                # 创建符号链接
                try:
                    if os.name == 'nt':  # Windows
                        # Windows需要管理员权限创建符号链接，使用相对路径
                        relative_source = os.path.relpath(source_path, collection_dir)
                        os.symlink(relative_source, link_path)
                    else:  # Linux/Unix
                        os.symlink(source_path, link_path)
                    # 已创建符号链接
                except Exception as e:
                    # 创建符号链接失败
                    # 如果符号链接创建失败，尝试复制文件
                    try:
                        import shutil
                        shutil.copy2(source_path, link_path)
                        # 符号链接失败，已复制文件
                    except Exception as copy_error:
                        # 复制文件也失败
                        pass
            else:
                # 源文件不存在，跳过符号链接
                pass
                
    except Exception as e:
        # 创建符号链接过程中出错
        pass

async def download_thumbnail_async(thumbnail_url: str, thumbnail_path: str) -> bool:
    """异步下载缩略图"""
    try:
        # 检查是否为Base64格式的缩略图
        if thumbnail_url.startswith('data:image/'):
            # 处理Base64格式的缩略图
            # 提取Base64数据部分
            mime_type = ""
            if "," in thumbnail_url:
                header, base64_data = thumbnail_url.split(",", 1)
                mime_type = header.split(";")[0].replace("data:", "").strip().lower()
            else:
                base64_data = thumbnail_url
            # 解码Base64数据
            image_data = base64.b64decode(base64_data)
            if mime_type in {"image/jpeg", "image/jpg"}:
                with open(thumbnail_path, 'wb') as f:
                    f.write(image_data)
                return os.path.exists(thumbnail_path) and os.path.getsize(thumbnail_path) > 0
            # 保存到临时文件，统一用ffmpeg转为标准jpg
            tmp_path = thumbnail_path + ".tmp"
            with open(tmp_path, 'wb') as f:
                f.write(image_data)
            ok = convert_to_jpeg_ffmpeg(tmp_path, thumbnail_path)
            try:
                os.remove(tmp_path)
            except Exception:
                pass
            return ok
        else:
            # 处理URL格式的缩略图
            async with httpx.AsyncClient() as client:
                response = await client.get(thumbnail_url, timeout=10)
                if response.status_code == 200:
                    content_type = (response.headers.get("content-type") or "").lower()
                    url_lower = thumbnail_url.lower()
                    if "image/jpeg" in content_type or "image/jpg" in content_type or url_lower.endswith((".jpg", ".jpeg")):
                        with open(thumbnail_path, 'wb') as f:
                            f.write(response.content)
                        return os.path.exists(thumbnail_path) and os.path.getsize(thumbnail_path) > 0
                    tmp_path = thumbnail_path + ".tmp"
                    with open(tmp_path, 'wb') as f:
                        f.write(response.content)
                    ok = convert_to_jpeg_ffmpeg(tmp_path, thumbnail_path)
                    try:
                        os.remove(tmp_path)
                    except Exception:
                        pass
                    return ok
    except Exception as e:
        # 保存缩略图失败
        return False

def rename_and_scrape(task_id, video_info, save_dir, subscription_info=None, generate_nfo: bool = True):
    title = video_info.title or f'{video_info.platform}_{task_id}'
    # 保留原始标题，不做额外清理
    create_time = video_info.create_time or ''
    # 年份处理
    year = ''
    if create_time:
        try:
            dt = datetime.strptime(create_time[:10], '%Y-%m-%d')
            year = dt.strftime('%Y')
        except Exception:
            year = create_time[:4] if len(create_time) >= 4 else ''
    clean_title = sanitize_filename(title)

    
    # 统一使用 Task ID 前8位作为后缀，确保唯一性并防止同名覆盖
    # 取消使用时间戳后缀，避免文件名过长且在并发时仍可能有风险
    filename_base = f"{clean_title}_{task_id[:8]}"
    
    # 根据订阅类型决定文件保存位置
    if subscription_info and subscription_info.get('platform') == 'douyin_collection':
        # 合集订阅：直接保存到根目录，不创建子文件夹
        video_folder = save_dir  # 直接使用根目录
        # 合集视频直接保存到根目录
    else:
        # 博主订阅：创建视频专属文件夹
        video_folder = os.path.join(save_dir, filename_base)
        os.makedirs(video_folder, exist_ok=True)
        # 博主视频保存到专属文件夹
    
    # 重命名视频文件
    old_video_path = os.path.join(save_dir, f'{task_id}.mp4')
    new_video_path = os.path.join(video_folder, f'{filename_base}.mp4')
    if os.path.exists(old_video_path):
        os.rename(old_video_path, new_video_path)
        # 视频文件已重命名
    
    # 根据订阅类型和generate_nfo参数决定是否生成NFO
    # 订阅下载：始终生成NFO（不受generate_nfo参数影响）
    # 手动下载：根据generate_nfo参数决定是否生成NFO
    should_generate_nfo = subscription_info is not None or generate_nfo
    
    if should_generate_nfo:
        if subscription_info and subscription_info.get('platform') == 'douyin_collection':
            # 合集订阅：使用电视剧格式
            collection_name = subscription_info.get('nickname', 'Unknown Collection')
            # 从视频标题中提取集数
            video_title = video_info.title or ''
            # 调试信息已精简
            episode_number = extract_episode_number(video_title)
            generate_nfo_douyin_collection(video_info, video_folder, filename_base, collection_name, episode_number)
            # 已生成合集NFO文件
        else:
            # 博主订阅或手动下载：使用电影格式
            generate_nfo_douyin_xhs(video_info, video_folder, filename_base)
            # 已生成博主NFO文件
    
    # 移动封面图片并重命名
    old_thumb_path = os.path.join(save_dir, f'{task_id}-poster.jpg')
    new_thumb_path = os.path.join(video_folder, f'{filename_base}-poster.jpg')
    if os.path.exists(old_thumb_path):
        try:
            os.rename(old_thumb_path, new_thumb_path)
            # 封面图片已移动
        except Exception as e:
            # 移动封面图片失败
            pass
    
    return filename_base

def rename_and_scrape_gallery(task_id, video_info, save_dir):
    """为图集重命名和生成NFO文件"""
    # 优先使用视频标题
    if video_info.title and video_info.title.strip():
        title = video_info.title.strip()
    else:
        title = f'{video_info.platform}_gallery_{task_id}'
    create_time = video_info.create_time or ''
    
    # 年份处理
    year = ''
    if create_time:
        try:
            dt = datetime.strptime(create_time[:10], '%Y-%m-%d')
            year = dt.strftime('%Y')
        except Exception:
            year = create_time[:4] if len(create_time) >= 4 else ''
    
    clean_title = sanitize_filename(title)
    
    # 使用发布时间确保唯一性，如果没有发布时间则使用当前时间
    if create_time:
        try:
            # 解析发布时间
            publish_dt = datetime.strptime(create_time[:10], '%Y-%m-%d')
            timestamp = publish_dt.strftime('%Y%m%d')
            # 如果同一天有多个图集，添加小时分钟秒
            if len(create_time) >= 19:  # 有完整时间信息
                publish_dt_full = datetime.strptime(create_time[:19], '%Y-%m-%d %H:%M:%S')
                timestamp = publish_dt_full.strftime('%Y%m%d_%H%M%S')
            else:
                # 只有日期，添加当前时间作为后缀
                current_time = datetime.now().strftime('%H%M%S')
                timestamp = f"{timestamp}_{current_time}"
        except Exception:
            # 解析失败，使用当前时间
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    else:
        # 没有发布时间，使用当前时间
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    
    filename_base = f"{clean_title}_{timestamp}"
    
    # 创建图集专属文件夹
    gallery_folder = os.path.join(save_dir, filename_base)
    os.makedirs(gallery_folder, exist_ok=True)
    
    # 生成图集主NFO
    generate_nfo_gallery(video_info, gallery_folder, filename_base)
    
    return filename_base

def scan_and_generate_gallery_nfos(video_info, gallery_folder, filename_base):
    """扫描图集文件夹并为每个视频生成NFO"""
    # 策略更新：扫描文件夹下所有 .mp4 文件，为每个视频文件生成对应的 NFO
    mp4_files = sorted([f for f in os.listdir(gallery_folder) if f.lower().endswith('.mp4')])
    
    if mp4_files:
        # 如果是动态图集（有视频），为每个视频生成NFO
        logger.debug(f"[gallery] 检测到动态图集包含 {len(mp4_files)} 个视频，正在为每个视频生成NFO")
        
        # 寻找封面图：优先使用 _001.jpg，否则使用 poster.jpg
        poster_file = f'{filename_base}_001.jpg'
        if not os.path.exists(os.path.join(gallery_folder, poster_file)):
             if os.path.exists(os.path.join(gallery_folder, 'poster.jpg')):
                 poster_file = 'poster.jpg'
             elif os.path.exists(os.path.join(gallery_folder, f'{filename_base}-poster.jpg')):
                 poster_file = f'{filename_base}-poster.jpg'
        
        for mp4_file in mp4_files:
            video_base = os.path.splitext(mp4_file)[0]
            nfo_name = f"{video_base}.nfo"
            # 调用 generate_nfo_gallery 并不限制 thumb，让它使用通用的封面或不指定（Jellyfin会自动找同名jpg或poster）
            # 这里我们显式传入找到的封面图，保证有图
            generate_nfo_gallery(video_info, gallery_folder, filename_base, nfo_filename=nfo_name, thumb_filename=poster_file)



# 后台下载逻辑
async def dyd_download_video_logic(task_id: str, url: str, custom_download_dir: str = None, generate_nfo: bool = True):
    """下载视频的主要逻辑"""
    TASK_TIMEOUT = 10800  # 任务总超时提升至 3 小时，适配大文件和长视频下载（6GB+文件在1MB/s速度下需要约114分钟）
    save_path = None
    save_path = None
    # db = next(get_db())  # 移除：不再传递长连接 session，避免长时间下载导致 idle-in-transaction timeout

    # --- 关键修复：防止小红书任务被误路由到 DYD/抖音解析 ---
    # 某些场景下（例如订阅任务失败后从通用重试入口触发），会直接调用 dyd_download_video_logic，
    # 这会让小红书链接走到抖音专用的解析流程里，出现「小红书重试跑到抖音解析」的现象。
    # 这里统一拦截小红书链接，直接转交给 xiaohongshu 专用下载逻辑处理。
    try:
        url_lower = url.lower() if isinstance(url, str) else ""
    except Exception:
        url_lower = ""
    if "xiaohongshu.com" in url_lower or "xhslink.com" in url_lower:
        try:
            # 延迟导入以避免循环依赖在模块加载阶段触发
            from routers.xiaohongshu import xhs_download_video_logic as _xhs_download_video_logic
        except Exception:
            # 如果导入失败，直接报错而不是继续走抖音解析
            logger.error("检测到小红书链接，但导入 xiaohongshu 模块失败，无法重定向到小红书下载逻辑")
            raise

        logger.info(f"[dyd] 检测到小红书链接，重定向到小红书下载逻辑: task_id={task_id}")

        # 尝试纠正 Task.source，避免在前端/通知中被误认为抖音任务
        try:
            db_fix = next(get_db())
            try:
                task_obj = db_fix.query(Task).filter(Task.id == task_id).first()
                if task_obj and task_obj.source != "xiaohongshu":
                    task_obj.source = "xiaohongshu"
                    db_fix.commit()
            finally:
                try:
                    db_fix.rollback()
                except Exception:
                    pass
                db_fix.close()
        except Exception as e:
            logger.debug(f"[dyd] 修正 Task.source 为 xiaohongshu 失败（忽略不影响下载）: {e}")

        # 直接交给小红书下载逻辑处理（其内部会负责进度回写与通知）
        return await _xhs_download_video_logic(task_id, url, custom_download_dir, generate_nfo)

    try:
        try:
            # 使用asyncio.wait_for包装整个任务，添加任务级别超时
            result = await asyncio.wait_for(
                _do_download_video_task(task_id, url, custom_download_dir, generate_nfo),
                timeout=TASK_TIMEOUT
            )
            return result
        except asyncio.TimeoutError:
            logger.error(f"任务超时{TASK_TIMEOUT}秒: {task_id} (由于超过1小时未完成而被强制停止)")
            update_dyd_task_progress(task_id, TaskStatus.ERROR, error=f"任务处理超时（限时{TASK_TIMEOUT}秒）")
            return False
        except Exception as e:
            logger.error(f"下载任务失败: {str(e)}")
            update_dyd_task_progress(task_id, TaskStatus.ERROR, error=str(e))
            return False
        finally:
            # 统一在这里结束任务，确保护理任务计数减一
            await browser_manager.end_task()
    finally:
        # 尝试强制归还系统内存 (Linux glibc)
        try:
            import ctypes
            libc = ctypes.CDLL("libc.so.6")
            libc.malloc_trim(0)
        except Exception:
            pass
        # 移除：db session 已在 _do_download_video_task 内部通过短连接管理
        # try:
        #     db.rollback()
        # except Exception:
        #     pass
        # db.close()

async def _do_download_video_task(task_id: str, url: str, custom_download_dir: str, generate_nfo: bool = True):
    """执行实际的下载任务逻辑"""
    save_path = None
    try:
        # 开始任务，更新活动时间
        await browser_manager.start_task(max_active_tasks=MAX_DOUYIN_BROWSER_ACTIVE_TASKS)
        
        # 如果传入的是 SubscriptionVideo 对象，提取必要信息
        if isinstance(url, SubscriptionVideo):
            video = url
            url = video.url
            task_id = video.download_task_id or task_id

        update_dyd_task_progress(task_id, TaskStatus.DOWNLOADING, progress=0.0)
        
        # 1. 优先使用缓存的解析结果
        cached_video_info = get_cached_parse_result(url)
        if cached_video_info and (cached_video_info.download_url or cached_video_info.is_gallery):
            logger.debug(f"使用缓存的解析结果进行下载: {url}")
            video_info = cached_video_info
        else:
            # 2. 缓存不存在或已过期，重新解析
            logger.debug(f"缓存不存在或已过期，重新解析: {url}")
            extractor = VideoExtractor()

            video_info = await extractor.extract(url, task_id=task_id, save_dir=None)
            if not video_info or (not video_info.download_url and not video_info.is_gallery):
                update_dyd_task_progress(task_id, TaskStatus.ERROR, error="无法获取视频直链或图集信息")
                return False
            # 缓存新的解析结果
            cache_parse_result(url, video_info)
            
        # 3. 如果是订阅下载，尝试从数据库获取发布时间和完整标题
        if custom_download_dir:  # 订阅下载
            # 创建临时 session
            db = next(get_db())
            try:
                subscription_video = db.query(SubscriptionVideo).filter(
                    SubscriptionVideo.download_task_id == task_id
                ).first()
                if subscription_video:
                    # 优先使用数据库中的完整标题（包含集数信息）
                    if subscription_video.title and subscription_video.title.strip():
                        # 截断到50字符，避免文件夹名过长
                        title = subscription_video.title.strip()
                        # 清理换行符和非法字符
                        title = re.sub(r'[\r\n]+', ' ', title)  # 换行符替换为空格
                        title = re.sub(r'[<>:"/\\|?*]', '_', title)[:50]
                        logger.debug(f"使用数据库中的标题: {title}")
                        video_info.title = title
                    
                    # 将数据库中的发布时间设置到VideoInfo中
                    if subscription_video.publish_time:
                        publish_time_str = subscription_video.publish_time.strftime('%Y-%m-%d %H:%M:%S')
                        video_info.create_time = publish_time_str
                        logger.debug(f"从数据库获取发布时间: {publish_time_str}")
            finally:
                db.close()
        
        # 4. 处理图集下载
        if video_info.is_gallery:
            logger.info(f"开始下载图集，共{len(video_info.image_urls)}张图片")
            return await dyd_download_gallery_logic(task_id, video_info, custom_download_dir)
            
        video_url = video_info.download_url
        
        # 5. 下载视频
        platform = video_info.platform.value if video_info.platform else "unknown"
        filename = task_id
        
        # 使用自定义下载目录或默认目录
        if custom_download_dir:
            download_dir = custom_download_dir
        else:
            platform_dir = platform.lower()
            # 注意：小红书已移至 xiaohongshu.py，这里只处理抖音
            if platform_dir != "douyin":
                platform_dir = "others"
            download_dir = f"/app/downloads/{platform_dir}"
        
        os.makedirs(download_dir, exist_ok=True)
        save_path = f"{download_dir}/{filename}.mp4"
        
        # 根据平台设置下载请求头
        download_headers = {
            'User-Agent': get_random_mobile_user_agent(),  # 使用随机User-Agent
            'Accept': '*/*',
            'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
            'Connection': 'keep-alive',
        }
        
        # 抖音视频需要特定的Referer
        if platform == 'douyin':
            download_headers['Referer'] = 'https://www.douyin.com/'


        # --- 使用 yt-dlp 接管下载（单线程模式，兼容性更好）---
        logger.info(f"[yt-dlp] 准备通过 yt-dlp 下载（单线程模式）")
        
        # 构造 yt-dlp 命令
        # 注意：禁用并发分片下载以提高兼容性，避免触发CDN反爬机制
        # --retries 10 : 增加重试次数
        # --fragment-retries 10 : 分片重试
        # --socket-timeout 300 : 增加套接字超时时间（5分钟），适合大文件下载
        ytdlp_cmd = [
            "yt-dlp",
            video_url,
            "-o", save_path,
            "--user-agent", download_headers.get('User-Agent', ''),
            "--add-header", f"Referer:{download_headers.get('Referer', '')}",
            "--retries", "10",
            "--fragment-retries", "10",
            "--socket-timeout", "300",  # 增加超时时间，适合大文件下载
            "--newline",              # 强制换行输出便于解析进度
            "--no-playlist",
            "--no-mtime"
        ]

        # 针对抖音直链，通常不需要合并流，但增加强制选项确保 mp4 格式
        ytdlp_cmd.extend(["--merge-output-format", "mp4"])

        download_success = False
        max_ytdlp_attempts = 5  # 增加重试次数到 5 次（1 次首次 + 4 次重试），适合大文件下载
        retry_delay_seconds = 10  # 增加重试延迟到 10 秒，给服务器更多恢复时间
        last_stderr_msg = ""

        try:
            for attempt in range(max_ytdlp_attempts):
                if attempt > 0:
                    logger.info(f"[yt-dlp] 第 {attempt + 1}/{max_ytdlp_attempts} 次尝试，{retry_delay_seconds} 秒后重试...")
                    await asyncio.sleep(retry_delay_seconds)

                # 使用异步子进程运行 yt-dlp
                process = await asyncio.create_subprocess_exec(
                    *ytdlp_cmd,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE
                )

                last_progress_update = 0

                # 实时读取标准输出以解析进度
                while True:
                    line_bytes = await process.stdout.readline()
                    if not line_bytes:
                        break

                    line = line_bytes.decode('utf-8', errors='ignore').strip()

                    # 检查任务是否取消
                    if dyd_cancel_flags.get(task_id):
                        try:
                            process.terminate()
                        except:
                            pass
                        update_dyd_task_progress(task_id, TaskStatus.CANCELLED, error="用户已取消下载")
                        return False

                    # 正则解析进度信息：例如 [download]  12.5% of 100.00MiB at ...
                    progress_match = re.search(r'\[download\]\s+([\d.]+)%', line)
                    if progress_match:
                        try:
                            progress_val = float(progress_match.group(1))
                            # 限制更新频率，提高性能
                            current_time = time.time()
                            if current_time - last_progress_update >= 5.0:
                                update_dyd_task_progress(task_id, TaskStatus.DOWNLOADING, progress=progress_val)
                                last_progress_update = current_time
                        except:
                            pass

                    # 如果有错误信息
                    if "ERROR:" in line:
                        logger.error(f"[yt-dlp-error] {line}")

                # 等待进程结束
                stdout, stderr = await process.communicate()
                last_stderr_msg = stderr.decode('utf-8', errors='ignore')

                if process.returncode == 0 and os.path.exists(save_path):
                    file_size = os.path.getsize(save_path)
                    if file_size > 1024:
                        logger.info(f"[yt-dlp] 下载完成，文件大小: {file_size/1024/1024:.2f} MB")
                        download_success = True
                        break
                    else:
                        logger.error(f"[yt-dlp] 下载文件过小，可能失败")
                else:
                    logger.error(f"[yt-dlp] 进程退出码: {process.returncode}, 错误信息: {last_stderr_msg}")

                # 判断是否值得重试：典型瞬时错误（无数据块、超时、连接问题、下载不完整等）
                if attempt < max_ytdlp_attempts - 1:
                    retryable = (
                        "Did not get any data blocks" in last_stderr_msg
                        or "data blocks" in last_stderr_msg
                        or "Timeout" in last_stderr_msg
                        or "Connection" in last_stderr_msg
                        or "reset" in last_stderr_msg.lower()
                        or "refused" in last_stderr_msg.lower()
                        or "Downloaded" in last_stderr_msg and "expected" in last_stderr_msg and "bytes" in last_stderr_msg  # 下载不完整错误
                        or "Giving up after" in last_stderr_msg  # 重试后放弃的错误
                    )
                    if retryable:
                        logger.warning(f"[yt-dlp] 本次失败可重试，将进行第 {attempt + 2} 次尝试。错误信息: {last_stderr_msg[:300]}")
                    else:
                        raise Exception(f"yt-dlp 下载失败: {last_stderr_msg[:200]}")
                else:
                    raise Exception(f"yt-dlp 下载失败（已重试 {max_ytdlp_attempts} 次）: {last_stderr_msg[:200]}")

        except Exception as e:
            logger.error(f"[yt-dlp] 执行异常: {str(e)}")
            # 这里不再进行 httpx 重试，因为 yt-dlp 已经内置了内部重试
            update_dyd_task_progress(task_id, TaskStatus.ERROR, error=f"多线程下载失败: {str(e)}")
            # 下载失败，清除缓存以强制下次重新解析
            stale_url = video_info.download_url if video_info else None
            invalidate_parse_cache(url, stale_url)
            return False
        
        if not download_success:
             stale_url = video_info.download_url if video_info else None
             invalidate_parse_cache(url, stale_url)
             return False
        
        # 3. 下载完成后自动刮削和重命名
        # 获取订阅信息用于NFO生成
        subscription_info = None
        if custom_download_dir:  # 订阅下载
            # 创建临时 session
            db = next(get_db())
            try:
                subscription_video = db.query(SubscriptionVideo).filter(
                    SubscriptionVideo.download_task_id == task_id
                ).first()
                if subscription_video:
                    subscription = db.query(Subscription).filter(
                        Subscription.id == subscription_video.subscription_id
                    ).first()
                    if subscription:
                        subscription_info = {
                            'platform': subscription.platform,
                            'nickname': subscription.nickname
                        }
            finally:
                db.close()
        
        # 订阅下载始终生成NFO，手动下载根据generate_nfo参数决定
        # 如果custom_download_dir存在，说明是订阅下载，generate_nfo参数会被忽略（始终生成）
        filename_base = rename_and_scrape(task_id, video_info, download_dir, subscription_info, generate_nfo)
        
        # 下载缩略图
        logger.debug(f"[thumbnail] 检查缩略图URL: {video_info.thumbnail_url}")
        if video_info.thumbnail_url:

            # 合集扁平化：缩略图直接保存到根目录
            if subscription_info and subscription_info.get('platform') == 'douyin_collection':
                thumbnail_path = os.path.join(download_dir, f'{filename_base}-poster.jpg')
            else:
                thumbnail_path = os.path.join(download_dir, filename_base, f'{filename_base}-poster.jpg')
            logger.debug(f"[thumbnail] 开始下载缩略图到: {thumbnail_path}")

            await download_thumbnail_async(video_info.thumbnail_url, thumbnail_path)

            # 为抖音合集补齐根级封面（poster/season/folder）
            if subscription_info and subscription_info.get('platform') == 'douyin_collection':
                ensure_douyin_collection_artworks(download_dir, thumbnail_path)
        
        # 更新任务状态为完成
        # 构建完整的文件路径
        if custom_download_dir:
            # 订阅下载：使用完整路径
            relative_path = custom_download_dir.replace('/app/downloads/', '')
            # 合集扁平化：文件直接在根目录
            if subscription_info and subscription_info.get('platform') == 'douyin_collection':
                filename_path = f'{relative_path}/{filename_base}.mp4'
            else:
                filename_path = f'{relative_path}/{filename_base}/{filename_base}.mp4'
        else:
            # 手动下载：使用相对路径，需要包含平台前缀
            platform_dir = platform.lower()
            # 注意：小红书已移至 xiaohongshu.py，这里只处理抖音
            if platform_dir != "douyin":
                platform_dir = "others"
            filename_path = f'{platform_dir}/{filename_base}/{filename_base}.mp4'
        
        update_dyd_task_progress(task_id, TaskStatus.COMPLETED, progress=100.0, filename=filename_path)
        
        # 更新订阅视频的下载状态
        db = next(get_db())
        try:
            video = db.query(SubscriptionVideo).filter(
                SubscriptionVideo.download_task_id == task_id
            ).first()
            if video:
                video.downloaded = "true"  # 使用字符串而不是布尔值
                db.commit()
        except:
            db.rollback()
        finally:
            db.close()
            
        return True
        
    except Exception as e:
        logger.error(f"下载视频失败: {str(e)}")
        # 如果下载过程中出错，清理临时文件
        if save_path and os.path.exists(save_path):
            try:
                os.remove(save_path)
            except Exception as e:
                logger.error(f"删除临时文件失败: {str(e)}")
        
        # 更新订阅视频的下载状态为失败
        db = next(get_db())
        try:
            video = db.query(SubscriptionVideo).filter(
                SubscriptionVideo.download_task_id == task_id
            ).first()
            if video:
                video.downloaded = "false"  # 确保下载失败时设置为false
                video.error_message = str(e)  # 记录错误信息
                db.commit()
        except:
            db.rollback()
        finally:
            db.close()
        
        update_dyd_task_progress(task_id, TaskStatus.ERROR, error=str(e))
        return False
    finally:
        # 结束任务，更新活动时间
        await browser_manager.end_task()

@router.post("/api/dyd/download")
async def dyd_server_download(request: DownloadRequest, current_user: User = Depends(get_current_user_or_token), db: Session = Depends(get_db)):
    """抖音视频下载接口（小红书请使用 /api/xhs/download）"""
    url = request.url
    generate_nfo = request.generate_nfo  # 获取NFO生成参数
    if not url:
        raise HTTPException(status_code=400, detail="url不能为空")
    url_lower = url.lower().strip()
    
    # 检测小红书链接，提示使用正确的接口
    if 'xiaohongshu.com' in url_lower or 'xhslink.com' in url_lower:
        raise HTTPException(status_code=400, detail="小红书链接请使用 /api/xhs/download 接口")
    
    # 仅处理抖音链接
    if 'douyin.com' in url_lower or 'iesdouyin.com' in url_lower:
        source_value = 'douyin'
    else:
        extractor = VideoExtractor()
        platform = extractor.detect_platform(url)
        if platform == Platform.XIAOHONGSHU:
            raise HTTPException(status_code=400, detail="小红书链接请使用 /api/xhs/download 接口")
        source_value = str(platform.value).strip().lower()
    
    task_id = str(uuid.uuid4())
    now = now_beijing()
    task = Task(
        id=task_id,
        source=source_value,
        url=url,
        status=TaskStatus.PENDING.value,
        progress=0.0,
        created_at=now,
        updated_at=now
    )
    db.add(task)
    db.commit()
    dyd_cancel_flags[task_id] = False

    asyncio.create_task(dyd_download_video_logic(task_id, url, None, generate_nfo))

    return {"status": "success", "taskId": task_id}

@router.post("/api/dyd/cancel/{task_id}")
async def dyd_cancel_download(task_id: str, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    task = db.query(Task).filter(Task.id == task_id).first()
    if not task or task.status in [TaskStatus.COMPLETED.value, TaskStatus.ERROR.value, TaskStatus.CANCELLED.value]:
        raise HTTPException(status_code=404, detail="任务不存在或已完成，无法取消。")
    
    # 设置取消标志
    dyd_cancel_flags[task_id] = True
    
    # 清理已下载的文件（如果存在）
    if task.filename:
        # 尝试在子目录中查找文件
        file_found = False
        # 注意：小红书已移至 xiaohongshu.py，但保留兼容性检查
        for platform_dir in ["douyin", "xiaohongshu", "others"]:
            # 检查是否是新格式的文件夹结构
            if '/' in task.filename:
                # 新格式：文件夹/文件名
                folder_name = task.filename.split('/')[0]
                file_path = os.path.join("/app/downloads", platform_dir, task.filename)
                folder_path = os.path.join("/app/downloads", platform_dir, folder_name)
                
                # 删除整个文件夹
                if os.path.exists(folder_path):
                    try:
                        import shutil
                        shutil.rmtree(folder_path)
                        print(f"已删除取消任务的文件夹: {folder_path}")
                        file_found = True
                        break
                    except Exception as e:
                        print(f"删除文件夹失败: {folder_path}, 错误: {str(e)}")
            else:
                # 旧格式：直接文件名
                file_path = os.path.join("/app/downloads", platform_dir, task.filename)
                if os.path.exists(file_path):
                    try:
                        os.remove(file_path)
                        print(f"已删除取消任务的临时文件: {file_path}")
                        file_found = True
                        break
                    except Exception as e:
                        print(f"删除临时文件失败: {file_path}, 错误: {str(e)}")
        
        # 如果没找到，尝试在根目录查找（兼容旧文件）
        if not file_found:
            if '/' in task.filename:
                # 新格式：文件夹/文件名
                folder_name = task.filename.split('/')[0]
                folder_path = os.path.join("/app/downloads", folder_name)
                if os.path.exists(folder_path):
                    try:
                        import shutil
                        shutil.rmtree(folder_path)
                        print(f"已删除取消任务的文件夹: {folder_path}")
                    except Exception as e:
                        print(f"删除文件夹失败: {folder_path}, 错误: {str(e)}")
            else:
                # 旧格式：直接文件名
                file_path = os.path.join("/app/downloads", task.filename)
                if os.path.exists(file_path):
                    try:
                        os.remove(file_path)
                        print(f"已删除取消任务的临时文件: {file_path}")
                    except Exception as e:
                        print(f"删除临时文件失败: {file_path}, 错误: {str(e)}")
                else:
                    print(f"临时文件不存在: {task.filename}")
    
    # 更新任务状态为已取消
    update_dyd_task_progress(task_id, TaskStatus.CANCELLED, error="Download canceled by user.")
    
    return {"message": "Cancellation request sent and temporary files cleaned."}

def process_douyin_url(url: str) -> str:
    """处理抖音链接格式"""
    try:
        parsed_url = urlparse(url)
        
        # 处理图集链接，直接返回原链接
        if '/note/' in parsed_url.path:
            return url
        
        # 处理搜索页面链接，提取modal_id
        if '/jingxuan/search/' in parsed_url.path or 'modal_id' in parse_qs(parsed_url.query):
            modal_id = parse_qs(parsed_url.query).get('modal_id', [None])[0]
            if modal_id:
                return f"https://www.douyin.com/video/{modal_id}"
        
        # 处理分享链接，提取视频ID
        if '/share/' in parsed_url.path:
            share_id = parsed_url.path.split('/')[-1]
            if share_id and share_id.isdigit():
                return f"https://www.douyin.com/video/{share_id}"
        
        # 处理短链接
        if parsed_url.netloc == 'v.douyin.com':
            # 短链接需要访问后获取重定向地址
            return url
        
        # 处理标准视频链接
        if '/video/' in parsed_url.path:
            return url
        
        # 其他情况返回原链接
        return url
    except Exception as e:
        logger.error(f'URL处理错误: {str(e)}')
        return url

def extract_video_url(input_url: str) -> dict:
    """提取视频链接并判断平台"""
    # 清理输入，移除多余空格
    input_url = input_url.strip()
    
    # 匹配抖音链接的正则表达式 - 增强版
    douyin_regex = r'https?://v\.douyin\.com/[a-zA-Z0-9]+/?'
    douyin_full_regex = r'https?://www\.douyin\.com/[^\s]+'
    douyin_share_regex = r'https?://v\.douyin\.com/[a-zA-Z0-9]+/?[^\s]*'
    
    # 匹配抖音图集链接的正则表达式
    douyin_gallery_regex = r'https?://www\.douyin\.com/note/[a-zA-Z0-9]+[^\s]*'
    
    # 匹配小红书链接的正则表达式 - 增强版
    xhs_regex = r'https?://(?:www\.)?xiaohongshu\.com/[^\s]+'
    xhs_discovery_regex = r'https?://(?:www\.)?xiaohongshu\.com/discovery/item/[a-zA-Z0-9]+[^\s]*'
    xhs_explore_regex = r'https?://(?:www\.)?xiaohongshu\.com/explore/[a-zA-Z0-9]+[^\s]*'
    xhslink_regex = r'https?://xhslink\.com/[a-zA-Z0-9]+[^\s]*'
    
    # 优先检测抖音图集
    if re.search(douyin_gallery_regex, input_url):
        logger.debug(f"从文本中提取到抖音图集链接: {input_url}")
        return {"url": input_url, "platform": "douyin"}
    
    # 从文本中提取所有可能的小红书链接
    all_xhs_urls = re.findall(xhs_discovery_regex, input_url) or re.findall(xhs_explore_regex, input_url) or re.findall(xhslink_regex, input_url)
    
    if all_xhs_urls:
        # 返回第一个找到的小红书链接
        extracted_url = all_xhs_urls[0]
        logger.debug(f"从文本中提取到小红书链接: {extracted_url}")
        return {"url": extracted_url, "platform": "xiaohongshu"}
    
    # 从文本中提取所有可能的抖音链接
    all_douyin_urls = re.findall(douyin_share_regex, input_url)
    
    if all_douyin_urls:
        # 返回第一个找到的抖音链接
        extracted_url = all_douyin_urls[0]
        logger.debug(f"从文本中提取到抖音链接: {extracted_url}")
        return {"url": extracted_url, "platform": "douyin"}
    
    # 检查是否包含标准抖音链接
    if re.search(douyin_regex, input_url) or re.search(douyin_full_regex, input_url):
        return {"url": input_url, "platform": "douyin"}
    
    # 检查是否包含小红书链接
    if re.search(xhs_regex, input_url):
        return {"url": input_url, "platform": "xiaohongshu"}
    
    # 如果是纯数字，假设是抖音短链接
    if input_url.strip().isdigit():
        return {"url": f"https://v.douyin.com/{input_url}", "platform": "douyin"}
    
    # 其他情况
    if 'douyin.com' in input_url:
        return {"url": input_url, "platform": "douyin"}
    elif 'xiaohongshu.com' in input_url or 'xhslink.com' in input_url:
        return {"url": input_url, "platform": "xiaohongshu"}
    
    return {"url": input_url, "platform": "unknown"}

async def validate_video_url(video_url: str) -> bool:
    """验证视频地址有效性"""
    try:
        # 检查 URL 格式
        if not video_url or not video_url.startswith('http'):
            return False

        # 忽略预览视频和静态资源
        if any(pattern in video_url.lower() for pattern in [
            'uuu_265.mp4',
            'douyin-pc-web',
            'douyinstatic.com'
        ]):
            return False

        # 检查是否是视频文件
        video_extensions = ['.mp4', '.m3u8', '.flv']
        has_video_extension = any(ext in video_url.lower() for ext in video_extensions)

        # 检查是否是来自已知的视频CDN
        is_from_cdn = any(cdn in video_url.lower() for cdn in [
            'douyinvod.com',
            'snssdk.com',
            'amemv.com',
            'tiktokv.com',
            'pull-flv-',
            'pull-hls-'
        ])

        # 如果既不是视频扩展名也不是来自CDN，返回False
        if not has_video_extension and not is_from_cdn:
            return False

        # 发送 HEAD 请求验证文件存在
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.head(
                    video_url,
                    headers={
                        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36',
                        'Accept': '*/*',
                        'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
                        'Accept-Encoding': 'gzip, deflate, br',
                        'Range': 'bytes=0-',
                        'Referer': 'https://www.douyin.com/',
                        'Origin': 'https://www.douyin.com'
                    },
                    timeout=5.0,
                    follow_redirects=True
                )
                
                # 检查状态码
                if resp.status_code not in [200, 206]:
                    return False
                    
                # 检查content-type
                content_type = resp.headers.get('content-type', '').lower()
                if not content_type:
                    return False
                    
                return 'video' in content_type or 'application/octet-stream' in content_type
                           
        except Exception as e:
            logger.warning(f'HEAD 请求验证失败: {str(e)}')
            return False

    except Exception as e:
        logger.error(f'URL验证错误: {str(e)}')
        return False

# 注意：小红书链接处理已移至 xiaohongshu.py
def process_xiaohongshu_url(url: str) -> str:
    """小红书链接处理（已移至 xiaohongshu.py，此函数保留以兼容旧代码）"""
    return url

# 添加解析结果缓存
parse_cache = {}

class ParseResult:
    def __init__(self, video_info, timestamp):
        self.video_info = video_info
        self.timestamp = timestamp
        self.expires_at = timestamp + timedelta(hours=6)  # 6小时有效期
    
    def is_valid(self):
        return datetime.now() < self.expires_at

def cache_parse_result(url: str, video_info: VideoInfo):
    """缓存解析结果"""
    parse_cache[url] = ParseResult(video_info, datetime.now())
    logger.debug(f"已缓存解析结果: {url}")

def invalidate_parse_cache(url: str, stale_video_url: str = None):
    """失效解析结果缓存"""
    if url in parse_cache:
        del parse_cache[url]
        logger.info(f"下载失败，已自动清除解析缓存: {url}")
    
    if stale_video_url:
        try:
            global_url_cache.remove_by_value(stale_video_url)
        except Exception as e:
            logger.warning(f"清除全局URL缓存失败: {e}")

def get_cached_parse_result(url: str) -> Optional[VideoInfo]:
    """获取缓存的解析结果"""
    if url in parse_cache:
        cached = parse_cache[url]
        if cached.is_valid():
            logger.debug(f"使用缓存的解析结果: {url}")
            return cached.video_info
        else:
            # 清理过期缓存
            del parse_cache[url]
            logger.debug(f"缓存已过期，清理: {url}")
    return None

# 修改解析接口，添加缓存
@router.post("/api/dyd/parse")
async def parse_video(
    video_request: VideoRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """通用视频解析API"""
    body = await request.body()
    logger.debug(f"收到原始请求数据: {body.decode(errors='ignore')}")
    if not await rate_limiter.can_make_request():
        raise HTTPException(
            status_code=429,
            detail={
                "message": "请求过于频繁，请稍后再试",
                "retry_after": rate_limiter.time_window
            }
        )
    try:
        # 开始任务，更新活动时间
        await browser_manager.start_task(max_active_tasks=MAX_DOUYIN_BROWSER_ACTIVE_TASKS)
        
        url = video_request.url.strip()
        if not url:
            raise HTTPException(status_code=400, detail="URL不能为空")
        
        # 检测小红书链接，提示使用正确的接口
        if 'xiaohongshu.com' in url.lower() or 'xhslink.com' in url.lower():
            raise HTTPException(status_code=400, detail="小红书链接请使用 /api/xhs/parse 接口")
        
        # 预处理抖音链接，兼容/jingxuan/search/xxx等
        if 'douyin.com' in url:
            url = process_douyin_url(url)
        
        # 检查缓存
        cached_result = get_cached_parse_result(url)
        if cached_result:
            # 根据类型返回不同的响应格式
            if cached_result.is_gallery:
                # 图集缓存结果
                response_data = {
                    "status": "success",
                    "platform": cached_result.platform,
                    "type": "gallery",
                    "image_count": cached_result.gallery_count,
                    "image_urls": cached_result.image_urls,
                    "original_url": cached_result.share_url,
                    "cached": True
                }
                if cached_result.title:
                    response_data["title"] = cached_result.title
                if cached_result.author:
                    response_data["author"] = cached_result.author
                if cached_result.thumbnail_url:
                    response_data["thumbnail_url"] = cached_result.thumbnail_url
                if cached_result.create_time:
                    response_data["create_time"] = cached_result.create_time
            else:
                # 视频缓存结果
                response_data = {
                    "status": "success",
                    "platform": cached_result.platform,
                    "type": "video",
                    "video_url": cached_result.download_url,
                    "original_url": cached_result.share_url,
                    "cached": True
                }
                if cached_result.title:
                    response_data["title"] = cached_result.title
                if cached_result.author:
                    response_data["author"] = cached_result.author
                if cached_result.thumbnail_url:
                    response_data["thumbnail_url"] = cached_result.thumbnail_url
            
            # 安全地记录日志，避免显示Base64数据
            safe_response_data = response_data.copy()
            if 'thumbnail_url' in safe_response_data and safe_response_data['thumbnail_url']:
                safe_response_data['thumbnail_url'] = safe_log_url(safe_response_data['thumbnail_url'])
            logger.debug(f"返回缓存解析结果: {safe_response_data}")
            return response_data
        
        # 重新解析
        async with VideoExtractor() as extractor:
            video_info = await extractor.extract(url, for_share=True)
        
        # 检查是否为图集
        if video_info.is_gallery:
            # 图集解析结果
            response_data = {
                "status": "success",
                "platform": video_info.platform,
                "type": "gallery",
                "image_count": video_info.gallery_count,
                "image_urls": video_info.image_urls,
                "original_url": video_info.share_url,
                "cached": False
            }
            if video_info.title:
                response_data["title"] = video_info.title
            if video_info.author:
                response_data["author"] = video_info.author
            if video_info.thumbnail_url:
                response_data["thumbnail_url"] = video_info.thumbnail_url
            if video_info.create_time:
                response_data["create_time"] = video_info.create_time
        elif not video_info.download_url:
            raise HTTPException(status_code=400, detail="无法获取视频下载地址")
        else:
            # 视频解析结果
            response_data = {
                "status": "success",
                "platform": video_info.platform,
                "type": "video",
                "video_url": video_info.download_url,
                "original_url": video_info.share_url,
                "cached": False
            }
            if video_info.title:
                response_data["title"] = video_info.title
            if video_info.author:
                response_data["author"] = video_info.author
            if video_info.thumbnail_url:
                response_data["thumbnail_url"] = video_info.thumbnail_url
        
        # 缓存解析结果
        cache_parse_result(url, video_info)
        
        # 安全地记录日志，避免显示Base64数据
        safe_response_data = response_data.copy()
        if 'thumbnail_url' in safe_response_data and safe_response_data['thumbnail_url']:
            safe_response_data['thumbnail_url'] = safe_log_url(safe_response_data['thumbnail_url'])
        logger.debug(f"解析成功: {safe_response_data}")
        return response_data
    except HTTPException as he:
        usage_stats["failed_requests"] += 1
        today = datetime.now().date().isoformat()
        if today not in usage_stats["daily_stats"]:
            usage_stats["daily_stats"][today] = {"success": 0, "failed": 0}
        usage_stats["daily_stats"][today]["failed"] += 1
        logger.error(f"HTTP错误: {he.detail}")
        raise he
    except Exception as e:
        usage_stats["failed_requests"] += 1
        today = datetime.now().date().isoformat()
        if today not in usage_stats["daily_stats"]:
            usage_stats["daily_stats"][today] = {"success": 0, "failed": 0}
        usage_stats["daily_stats"][today]["failed"] += 1
        logger.error(f"解析失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"解析失败: {str(e)}")
    finally:
        # 结束任务，更新活动时间
        await browser_manager.end_task()

@router.get("/api/dyd/health")
async def health_check(db: Session = Depends(get_db)):
    """健康检查端点（轻量级数据库连接检测）"""
    try:
        # 只测试数据库连接，不做额外查询
        db.execute(text("SELECT 1"))
        
        return {
            "status": "ok", 
            "service": "dyd-service",
            "database": "connected"
        }
    except Exception as e:
        logger.error(f"数据库健康检查失败: {str(e)}")
        return {
            "status": "error",
            "service": "dyd-service", 
            "database": "disconnected",
            "error": str(e)
        }

@router.get("/api/dyd/stats")
async def get_stats(current_user: User = Depends(get_current_user)):
    """获取使用统计"""
    return usage_stats

@router.get("/api/dyd/cache-stats")
async def get_cache_stats(current_user: User = Depends(get_current_user)):
    """获取缓存统计信息"""
    cache_size = len(parse_cache)
    valid_cache_count = sum(1 for cached in parse_cache.values() if cached.is_valid())
    expired_cache_count = cache_size - valid_cache_count
    
    # 清理过期缓存
    expired_keys = [key for key, cached in parse_cache.items() if not cached.is_valid()]
    for key in expired_keys:
        del parse_cache[key]
    
    return {
        "total_cache_size": cache_size,
        "valid_cache_count": valid_cache_count,
        "expired_cache_count": expired_cache_count,
        "cache_hit_rate": f"{valid_cache_count}/{cache_size}" if cache_size > 0 else "0/0"
    }

@router.get("/api/dyd/proxy-download")
async def proxy_download(
    current_user: User = Depends(get_current_user),
    url: str = Query(...),
    filename: str = Query('douyin')
):
    # 智能判断Referer
    if 'xiaohongshu' in url or 'xhscdn.com' in url:
        referer = 'https://www.xiaohongshu.com/'
    elif 'douyin' in url:
        referer = 'https://www.douyin.com/'
    else:
        referer = 'https://www.douyin.com/'  # 默认
    headers = {
        'User-Agent': 'Mozilla/5.0 (iPhone; CPU iPhone OS 13_2_3 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/13.0.3 Mobile/15E148 Safari/604.1',
        'Referer': referer,
    }
    async with httpx.AsyncClient(follow_redirects=True, timeout=60) as client:
        resp = await client.get(url, headers=headers)
        safe_filename = re.sub(r'[<>:"/\\|?*]', '_', filename)[:80]
        ascii_filename = safe_filename.encode('ascii', 'ignore').decode('ascii') or 'douyin'
        disposition = (
            f"attachment; filename={ascii_filename}.mp4; filename*=UTF-8''{quote(safe_filename)}.mp4"
        )
        return StreamingResponse(
            resp.aiter_bytes(),
            media_type=resp.headers.get("content-type", "video/mp4"),
            headers={
                "Content-Disposition": disposition
            }
        )

@router.post("/api/dyd/parse-batch")
async def parse_video_batch(
    batch_request: BatchVideoRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    body = await request.body()
    logger.info(f"收到批量解析请求: {len(batch_request.urls)}个链接")
    if not await rate_limiter.can_make_request():
        raise HTTPException(
            status_code=429,
            detail={
                "message": "请求过于频繁，请稍后再试",
                "retry_after": rate_limiter.time_window
            }
        )
    try:
        # 开始任务，更新活动时间
        await browser_manager.start_task(max_active_tasks=MAX_DOUYIN_BROWSER_ACTIVE_TASKS)
        
        urls = [url.strip() for url in batch_request.urls if url.strip()]
        if not urls:
            raise HTTPException(status_code=400, detail="没有有效的URL")
        if len(urls) > 50:
            raise HTTPException(status_code=400, detail="批量解析最多支持50个链接")
        
        # 检查是否包含小红书链接
        xhs_urls = [url for url in urls if 'xiaohongshu.com' in url.lower() or 'xhslink.com' in url.lower()]
        if xhs_urls:
            raise HTTPException(status_code=400, detail="批量解析中包含小红书链接，请使用 /api/xhs/parse-batch 接口")
        
        semaphore = asyncio.Semaphore(batch_request.concurrent_limit)
        async def process_single_url(url: str) -> dict:
            # 预处理抖音链接，兼容/jingxuan/search/xxx等
            if 'douyin.com' in url:
                url = process_douyin_url(url)
            async with semaphore:
                try:
                    async with VideoExtractor() as extractor:
                        video_info = await extractor.extract(url, for_share=True)
                    
                    # 检查是否为图集
                    if video_info.is_gallery:
                        return {
                            "url": url,
                            "success": True,
                            "platform": video_info.platform,
                            "type": "gallery",
                            "image_count": video_info.gallery_count,
                            "image_urls": video_info.image_urls,
                            "original_url": video_info.share_url,
                            "title": video_info.title,
                            "author": video_info.author,
                            "thumbnail_url": video_info.thumbnail_url,
                            "create_time": video_info.create_time
                        }
                    elif not video_info.download_url:
                        return {
                            "url": url,
                            "success": False,
                            "error": "无法获取视频下载地址"
                        }
                    else:
                        return {
                            "url": url,
                            "success": True,
                            "platform": video_info.platform,
                            "type": "video",
                            "video_url": video_info.download_url,
                            "original_url": video_info.share_url,
                            "title": video_info.title,
                            "author": video_info.author,
                            "thumbnail_url": video_info.thumbnail_url
                        }
                except Exception as e:
                    logger.error(f"处理URL失败 {url}: {str(e)}")
                    return {
                        "url": url,
                        "success": False,
                        "error": str(e)
                    }
        tasks = [process_single_url(url) for url in urls]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        processed_results = []
        success_count = 0
        error_count = 0
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                error_count += 1
                processed_results.append({
                    "url": urls[i],
                    "success": False,
                    "error": str(result)
                })
            elif result.get("success"):
                success_count += 1
                processed_results.append(result)
            else:
                error_count += 1
                processed_results.append(result)
        # 修复 KeyError: 'success_requests'，兼容旧字段名
        if "success_requests" not in usage_stats:
            # 兼容旧字段名 successful_requests
            if "successful_requests" in usage_stats:
                usage_stats["success_requests"] = usage_stats["successful_requests"]
            else:
                usage_stats["success_requests"] = 0
        if "failed_requests" not in usage_stats:
            if "failed_requests" in usage_stats:
                pass  # 已有
            else:
                usage_stats["failed_requests"] = 0
        usage_stats["success_requests"] += success_count
        usage_stats["failed_requests"] += error_count
        today = datetime.now().date().isoformat()
        if today not in usage_stats["daily_stats"]:
            usage_stats["daily_stats"][today] = {"success": 0, "failed": 0}
        usage_stats["daily_stats"][today]["success"] += success_count
        usage_stats["daily_stats"][today]["failed"] += error_count
        return {
            "status": "success",
            "results": processed_results,
            "success_count": success_count,
            "error_count": error_count
        }
    except HTTPException as he:
        logger.error(f"HTTP错误: {he.detail}")
        raise he
    except Exception as e:
        logger.error(f"批量解析失败: {str(e)}\n{traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=f"批量解析失败: {str(e)}")
    finally:
        # 结束任务，更新活动时间
        await browser_manager.end_task()

@router.get("/api/dyd/proxy-image")
async def proxy_image(
    current_user: Optional[User] = Depends(get_current_user_optional),
    url: str = Query(..., description="图片URL"),
    platform: str = Query(..., description="平台类型"),
    request: Request = None
):
    """代理图片接口，用于获取小红书等平台的图片"""
    try:
        # 安全验证：检查URL是否来自允许的域名
        allowed_domains = [
            # 小红书域名
            'sns-webpic-qc.xhscdn.com',  # 小红书图片
            'sns-avatar-qc.xhscdn.com',  # 小红书头像
            'sns-img-qc.xhscdn.com',     # 小红书图片
            'sns-img-bd.xhscdn.com',     # 小红书图片
            'sns-img-hw.xhscdn.com',     # 小红书图片
            'picasso-static.xiaohongshu.com',  # 小红书静态资源
            # 抖音域名
            'p3-sign.douyinpic.com',     # 抖音
            'p3-pc-sign.douyinpic.com',  # 抖音PC端图片
            'p9-pc-sign.douyinpic.com',  # 抖音PC端图片
            'p11-sign.douyinpic.com',    # 抖音
            'p16-sign.douyinpic.com',    # 抖音
            'p26-sign.douyinpic.com',    # 抖音
            'p9-sign.douyinpic.com',     # 抖音
            # YouTube域名
            'img.youtube.com',           # YouTube
            'i.ytimg.com',               # YouTube
            'yt3.ggpht.com',             # YouTube
            # 允许社区默认封面图片
            'images.pexels.com',
        ]
        
        parsed_url = urlparse(url)
        if parsed_url.netloc not in allowed_domains:
            logger.warning(f"不支持的图片域名: {parsed_url.netloc}, URL: {url}")
            raise HTTPException(status_code=400, detail=f"不支持的图片域名: {parsed_url.netloc}")
        
        # 检查URL格式
        if not url.startswith(('http://', 'https://')):
            raise HTTPException(status_code=400, detail="无效的图片URL")
        
        # 获取客户端IP进行频率限制
        client_ip = "unknown"
        try:
            if request and request.client:
                client_ip = request.client.host
            elif request and hasattr(request, 'headers'):
                # 尝试从代理头获取真实IP
                client_ip = request.headers.get('x-forwarded-for', 
                            request.headers.get('x-real-ip', 'unknown')).split(',')[0].strip()
        except Exception as e:
            logger.warning(f"获取客户端IP失败: {e}")
            client_ip = "unknown"
        
        # 简单的频率限制（每分钟最多30次图片请求）
        current_time = int(time.time() / 60)
        key = f"proxy_image:{client_ip}:{current_time}"
        
        if not hasattr(proxy_image, 'request_counts'):
            proxy_image.request_counts = {}
        
        if key not in proxy_image.request_counts:
            proxy_image.request_counts[key] = 0
        
        proxy_image.request_counts[key] += 1
        
        if proxy_image.request_counts[key] > 30:
            raise HTTPException(status_code=429, detail="图片请求过于频繁")
        
        # 清理过期的记录
        current_minute = int(time.time() / 60)
        expired_keys = [k for k in proxy_image.request_counts.keys() 
                       if int(k.split(':')[-1]) < current_minute - 1]
        for k in expired_keys:
            del proxy_image.request_counts[k]
        
        # 设置不同平台的请求头
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36',
            'Accept': 'image/webp,image/apng,image/*,*/*;q=0.8',
            'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
            'Accept-Encoding': 'gzip, deflate, br',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1',
        }
        
        # 为不同平台设置特定的Referer
        if platform == 'xiaohongshu':
            headers['Referer'] = 'https://www.xiaohongshu.com/'
        elif platform in ['douyin']:
            headers['Referer'] = 'https://www.douyin.com/'
        elif platform == 'youtube':
            headers['Referer'] = 'https://www.youtube.com/'
        
        logger.debug(f"代理图片请求: {url} (平台: {platform})")
        
        async with httpx.AsyncClient() as client:
            response = await client.get(url, headers=headers, timeout=10, follow_redirects=True)
            
            if response.status_code == 200:
                # 获取图片的Content-Type
                content_type = response.headers.get('content-type', 'image/jpeg')
                
                # 验证返回的是图片
                if not content_type.startswith('image/'):
                    logger.warning(f"返回的不是图片文件: {content_type}, URL: {url}")
                    raise HTTPException(status_code=400, detail="返回的不是图片文件")
                
                logger.debug(f"图片代理成功: {url} -> {content_type}")
                
                # 返回图片数据
                return StreamingResponse(
                    iter([response.content]),
                    media_type=content_type,
                    headers={
                        'Cache-Control': 'public, max-age=3600',  # 缓存1小时
                        'Access-Control-Allow-Origin': '*'
                    }
                )
            elif response.status_code == 403:
                # 403 Forbidden - 通常是签名过期或反爬虫机制
                logger.warning(f"图片获取被拒绝 (403): {url}, 可能原因: 签名过期或反爬虫机制")
                # 返回一个透明的1x1像素PNG占位图，避免前端显示错误
                placeholder_png = base64.b64decode(
                    'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=='
                )
                return StreamingResponse(
                    iter([placeholder_png]),
                    media_type='image/png',
                    headers={
                        'Cache-Control': 'no-cache',
                        'Access-Control-Allow-Origin': '*'
                    }
                )
            else:
                logger.error(f"图片获取失败: {response.status_code}, URL: {url}")
                # 对于其他错误，也返回占位图而不是抛出异常
                placeholder_png = base64.b64decode(
                    'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=='
                )
                return StreamingResponse(
                    iter([placeholder_png]),
                    media_type='image/png',
                    headers={
                        'Cache-Control': 'no-cache',
                        'Access-Control-Allow-Origin': '*'
                    }
                )
                
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"代理图片失败: {str(e)}, URL: {url}")
        raise HTTPException(status_code=500, detail=f"图片代理失败: {str(e)}")

# 全局异常处理 (暂时保留，后续统一)
# @router.exception_handler(Exception)
# async def global_exception_handler(request: Request, exc: Exception):
#     logger.error(f"全局错误处理: {str(exc)}")
#     logger.error(traceback.format_exc())
#     return JSONResponse(
#         status_code=500,
#         content={"detail": str(exc)}
#     )

# @router.exception_handler(RequestValidationError)
# async def validation_exception_handler(request: Request, exc: RequestValidationError):
#     logger.error(f"参数校验失败: {exc.errors()}")
#     logger.error(f"请求体: {await request.body()}")
#     return JSONResponse(
#         status_code=422,
#         content={"detail": exc.errors()}
#     )

# 启动/关闭事件 (暂时保留，后续统一)
# @router.on_event("startup")
# async def startup_event():
#     """启动时不再初始化浏览器，改为按需启动"""
#     pass

# @router.on_event("shutdown")
# async def shutdown_event():
#     """关闭时清理资源"""
#     await browser_manager.close()

@router.post("/api/dyd/clear-cache")
async def clear_cache(current_user: User = Depends(get_current_user)):
    """清理所有缓存"""
    global parse_cache
    cache_size = len(parse_cache)
    parse_cache.clear()
    logger.info(f"已清理 {cache_size} 个缓存项")
    return {
        "message": f"已清理 {cache_size} 个缓存项",
        "cleared_count": cache_size
    }

def safe_log_url(url: str, max_length: int = 100) -> str:
    """安全地显示URL，避免显示Base64数据"""
    if not url:
        return "None"
    
    # 如果是Base64数据URL，只显示前缀
    if url.startswith('data:image/'):
        return f"data:image/... (Base64数据，长度: {len(url)} bytes)"
    
    # 如果是普通URL，限制长度
    if len(url) > max_length:
        return url[:max_length] + "..."
    
    return url

# 修改相关的日志显示

@router.post("/api/dyd/test-extract")
async def test_extract_url(request: Request, current_user: User = Depends(get_current_user)):
    """测试链接提取功能"""
    try:
        data = await request.json()
        input_text = data.get("text", "")
        
        # 使用增强的提取函数
        result = extract_video_url(input_text)
        
        return {
            "status": "success",
            "input_text": input_text,
            "extracted_url": result["url"],
            "platform": result["platform"],
            "extraction_success": result["url"] != input_text
        }
    except Exception as e:
        logger.error(f"链接提取测试失败: {str(e)}")
        return {
            "status": "error",
            "error": str(e)
        }

async def dyd_download_gallery_logic(task_id: str, video_info: VideoInfo, custom_download_dir: str = None):
    """下载图集的主要逻辑"""
    TASK_TIMEOUT = 600  # 任务总超时10分钟
    db = next(get_db())  # 创建新的数据库会话
    try:
        # 使用asyncio.wait_for包装整个任务，添加任务级别超时
        result = await asyncio.wait_for(
            _do_download_gallery_task(task_id, video_info, custom_download_dir, db),
            timeout=TASK_TIMEOUT
        )
        return result
    except asyncio.TimeoutError:
        logger.error(f"图集下载任务超时{TASK_TIMEOUT}秒: {task_id}")
        update_dyd_task_progress(task_id, TaskStatus.ERROR, error=f"图集下载任务超时{TASK_TIMEOUT}秒")
        return False
    except Exception as e:
        logger.error(f"图集下载任务失败: {str(e)}")
        update_dyd_task_progress(task_id, TaskStatus.ERROR, error=str(e))
        return False
    finally:
        try:
            db.rollback()
        except Exception:
            pass
        db.close()  # 确保关闭数据库会话

async def _do_download_gallery_task(task_id: str, video_info: VideoInfo, custom_download_dir: str, db):
    """执行实际的图集下载任务逻辑"""
    try:
        update_dyd_task_progress(task_id, TaskStatus.DOWNLOADING, progress=0.0)
        
        # 确定下载目录
        platform = video_info.platform.value if video_info.platform else "unknown"
        if custom_download_dir:
            download_dir = custom_download_dir
        else:
            platform_dir = platform.lower()
            if platform_dir not in ["douyin", "xiaohongshu"]:
                platform_dir = "others"
            download_dir = f"/app/downloads/{platform_dir}"
        
        os.makedirs(download_dir, exist_ok=True)
        
        # 创建图集文件夹
        filename_base = rename_and_scrape_gallery(task_id, video_info, download_dir)
        gallery_folder = os.path.join(download_dir, filename_base)
        os.makedirs(gallery_folder, exist_ok=True)
        
        # 下载图集内容(可能是视频或图片，或混合)
        # 优先使用 media_items（支持混合类型），兼容 image_urls（旧格式）
        media_items = getattr(video_info, 'media_items', None)
        
        if media_items and len(media_items) > 0:
            # 新格式：使用 media_items，每个item都有type和url
            total_items = len(media_items)
            has_videos = any(item.get('type') == 'video' for item in media_items)
            has_images = any(item.get('type') == 'image' for item in media_items)
            
            if has_videos and has_images:
                gallery_type = "混合图集(图片+视频)"
            elif has_videos:
                gallery_type = "动态图集(视频)"
            else:
                gallery_type = "静态图集(图片)"
        else:
            # 旧格式：兼容 image_urls
            total_items = len(video_info.image_urls)
            media_items = []
            
            # 判断类型
            is_dynamic_gallery = False
            if total_items > 0:
                first_url = video_info.image_urls[0]
                is_dynamic_gallery = 'douyinvod.com' in first_url
            
            gallery_type = "动态图集(视频)" if is_dynamic_gallery else "静态图集(图片)"
            
            # 将 image_urls 转换为 media_items 格式
            for i, url in enumerate(video_info.image_urls):
                item_type = 'video' if 'douyinvod.com' in url else 'image'
                media_items.append({
                    'index': i + 1,
                    'type': item_type,
                    'url': url
                })
        
        downloaded_items = 0
        logger.info(f"[gallery] 开始下载{gallery_type}，共{total_items}项")
        
        # 设置请求头
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/139.0.0.0 Safari/537.36',
            'Accept': 'image/webp,image/apng,image/svg+xml,image/*,video/*,*/*;q=0.8',
            'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
            'Accept-Encoding': 'gzip, deflate, br',
            'Connection': 'keep-alive',
            'Referer': 'https://www.douyin.com/',
            'Sec-Fetch-Dest': 'document',
            'Sec-Fetch-Mode': 'no-cors',
            'Sec-Fetch-Site': 'cross-site',
            'Sec-Ch-Ua': '"Not_A Brand";v="8", "Chromium";v="139", "Google Chrome";v="139"',
            'Sec-Ch-Ua-Mobile': '?0',
            'Sec-Ch-Ua-Platform': '"Windows"',
        }
        
        async with httpx.AsyncClient(follow_redirects=True, timeout=60) as client:
            for i, media_item in enumerate(media_items):
                if dyd_cancel_flags.get(task_id):
                    update_dyd_task_progress(task_id, TaskStatus.CANCELLED, error="Download canceled by user.")
                    return False
                
                try:
                    # 从 media_item 获取类型和URL
                    item_type = media_item.get('type', 'unknown')
                    media_url = media_item.get('url', '')
                    
                    # 如果没有明确类型，通过域名判断
                    if item_type == 'unknown':
                        item_type = 'video' if 'douyinvod.com' in media_url else 'image'
                    
                    # 调试：输出URL信息
                    logger.info(f"[gallery] 准备下载 {i+1}/{total_items}, URL长度: {len(media_url)}, 类型: {item_type}")
                    logger.debug(f"[gallery] 完整URL: {media_url[:200]}...")
                    
                    # 构建文件名
                    if item_type == 'video':
                        # 动态视频：保存为MP4
                        media_filename = f"{filename_base}_{i+1:03d}.mp4"
                        media_path = os.path.join(gallery_folder, media_filename)
                        
                        # 下载视频文件
                        response = await client.get(media_url, headers=headers, timeout=60)
                        if response.status_code == 200:
                            with open(media_path, "wb") as f:
                                f.write(response.content)
                            downloaded_items += 1
                            logger.info(f"[gallery] 下载视频 {i+1}/{total_items}: {media_filename}")
                        else:
                            logger.error(f"[gallery] 下载视频失败 {i+1}/{total_items}: HTTP {response.status_code}")
                            logger.debug(f"[gallery] 响应头: {dict(response.headers)}")
                            logger.debug(f"[gallery] URL: {media_url[:150]}...")
                    else:
                        # 静态图片：保存为JPG
                        media_filename = f"{filename_base}_{i+1:03d}.jpg"
                        media_path = os.path.join(gallery_folder, media_filename)
                        
                        # 下载图片 -> 先保存临时文件，再用FFmpeg转为标准JPG
                        response = await client.get(media_url, headers=headers, timeout=30)
                        if response.status_code == 200:
                            tmp_path = media_path + ".tmp"
                            with open(tmp_path, "wb") as f:
                                f.write(response.content)
                            if convert_to_jpeg_ffmpeg(tmp_path, media_path):
                                downloaded_items += 1
                                logger.info(f"[gallery] 下载并转换图片 {i+1}/{total_items}: {media_filename}")
                            else:
                                logger.error(f"[gallery] 转换图片失败 {i+1}/{total_items}: {media_filename}")
                            try:
                                os.remove(tmp_path)
                            except Exception:
                                pass
                        else:
                            logger.error(f"[gallery] 下载图片失败 {i+1}/{total_items}: HTTP {response.status_code}")
                            logger.debug(f"[gallery] 响应头: {dict(response.headers)}")
                            logger.debug(f"[gallery] URL: {media_url[:150]}...")
                        
                except Exception as e:
                    logger.error(f"[gallery] 下载媒体文件 {i+1}/{total_items} 出错: {str(e)}")
                
                # 更新进度
                progress = (downloaded_items / total_items) * 100
                update_dyd_task_progress(task_id, TaskStatus.DOWNLOADING, progress=progress)
        
        # 图集不需要生成缩略图，第一张图片天然可以作为封面
        # 移除缩略图生成逻辑，节省存储空间和处理时间
        
        # 更新任务状态为完成
        if custom_download_dir:
            # 订阅下载：使用完整路径
            relative_path = custom_download_dir.replace('/app/downloads/', '')
            filename_path = f'{relative_path}/{filename_base}/'
        else:
            # 手动下载：使用相对路径，需要包含平台前缀
            platform_dir = platform.lower()
            # 注意：小红书已移至 xiaohongshu.py，这里只处理抖音
            if platform_dir != "douyin":
                platform_dir = "others"
            filename_path = f'{platform_dir}/{filename_base}/'
        
        # 下载背景音乐(如果有)
        if video_info.music_url:
            try:
                music_filename = f"{filename_base}_bgm.mp3"
                music_path = os.path.join(gallery_folder, music_filename)
                
                logger.info(f"[gallery] 开始下载背景音乐: {video_info.music_title or 'Unknown'}")
                
                async with httpx.AsyncClient(follow_redirects=True, timeout=60) as client:
                    response = await client.get(video_info.music_url, headers=headers, timeout=60)
                    response.raise_for_status()
                    
                    with open(music_path, 'wb') as f:
                        f.write(response.content)
                    
                    logger.info(f"[gallery] 背景音乐下载完成: {music_filename}")
                    
            except Exception as e:
                logger.warning(f"[gallery] 背景音乐下载失败: {str(e)}")
            
        # 为图集生成一个 poster.jpg 作为预览图
        try:
            # 找到下载的第一张图片或视频截图（目前图集第一项通常是图片或视频）
            first_item_path = None
            for ext in ['.jpg', '.png', '.mp4']:
                pattern = os.path.join(gallery_folder, f"{filename_base}_001{ext}")
                if os.path.exists(pattern):
                    first_item_path = pattern
                    break
            
            if first_item_path:
                poster_path = os.path.join(gallery_folder, "poster.jpg")
                if first_item_path.endswith('.mp4'):
                    # 如果第一项是视频，使用 FFmpeg 截取第一帧
                    import subprocess
                    cmd = [
                        'ffmpeg', '-y', '-i', first_item_path,
                        '-ss', '00:00:00.000', '-vframes', '1',
                        poster_path
                    ]
                    subprocess.run(cmd, capture_output=True)
                else:
                    # 如果是图片，直接复制/硬链接
                    import shutil
                    shutil.copy2(first_item_path, poster_path)
                logger.info(f"[gallery] 已生成图集封面图: {poster_path}")
        except Exception as e:
            logger.warning(f"[gallery] 生成图集封面失败: {e}")

        # --- 关键修复：所有文件下载完毕后，扫描并生成各视频的 NFO ---
        try:
            scan_and_generate_gallery_nfos(video_info, gallery_folder, filename_base)
        except Exception as e:
            logger.error(f"[gallery] 扫描生成NFO失败: {e}")


        # 最后更新任务状态为完成，触发通知
        if custom_download_dir:
            relative_path = custom_download_dir.replace('/app/downloads/', '')
            filename_path = f'{relative_path}/{filename_base}/'
        else:
            platform_dir = platform.lower()
            if platform_dir != "douyin":
                platform_dir = "others"
            filename_path = f'{platform_dir}/{filename_base}/'
        
        update_dyd_task_progress(task_id, TaskStatus.COMPLETED, progress=100.0, filename=filename_path)
        logger.info(f"[gallery] 图集下载和处理全部完成，共下载 {downloaded_items}/{total_items} 项")
        return True
        
    except Exception as e:
        logger.error(f"下载图集失败: {str(e)}")
        
        # 更新订阅视频的下载状态为失败
        video = db.query(SubscriptionVideo).filter(
            SubscriptionVideo.download_task_id == task_id
        ).first()
        if video:
            video.downloaded = "false"
            video.error_message = str(e)
            db.commit()
        
        update_dyd_task_progress(task_id, TaskStatus.ERROR, error=str(e))
        # 下载失败，清除缓存
        if video_info and video_info.share_url:
            invalidate_parse_cache(video_info.share_url)
        return False
    finally:
        # 图集逻辑复用外层下载任务的并发槽位，不在此处重复释放
        pass
        
