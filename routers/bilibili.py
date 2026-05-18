import os
import asyncio
import logging
import json
import re
import time
import shutil
from datetime import datetime, timedelta, timezone
import uuid
from fastapi import APIRouter, HTTPException, Query, Depends, Request
from typing import List, Optional, Literal, Dict, Any, Callable, Awaitable
import httpx
import hashlib
import time as time_module
import random
from urllib.parse import urlencode
from playwright.async_api import async_playwright
from sqlalchemy.orm import Session
from sql.database_postgresql import get_db
from sql.models import (
    Subscription, SubscriptionVideo,
    SubscriptionCreate, SubscriptionUpdate, SubscriptionResponse,
    SubscriptionVideoResponse, Platform, SubscriptionStatus, TaskStatus, Task, User
)
from routers.auth import get_current_user, require_license_api
from .downloader import download_manager
from .ytd import download_video_logic as bilibili_download_logic
from pydantic import BaseModel, Field
from .websocket import send_progress_update, manager

# 配置日志
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# 导入统一浏览器管理器
from .unified_browser_manager import unified_browser
# 导入API参数缓存管理器
from .api_params_cache import api_params_cache

# 创建APIRouter实例（统一前缀，与前端调用一致）
router = APIRouter(prefix="/api/subscribe/bilibili", tags=["bilibili"])

class BilibiliAPI:
    """B站API类，用于获取UP主信息和视频列表"""
    
    def __init__(self):
        # 使用统一浏览器管理器
        self._browser = unified_browser
        self._platform = "bilibili"
        
        # HTTP客户端：WBI签名相关参数使用统一的api_params_cache
        self._http: Optional[httpx.AsyncClient] = None
        
        # 请求队列管理
        self._request_queue = asyncio.Queue()
        self._worker_task = None
        self._max_concurrent_requests = 10
        self._request_semaphore = asyncio.Semaphore(self._max_concurrent_requests)
        
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
    
    async def init_browser(self):
        """初始化浏览器（使用统一浏览器管理器）"""
        try:
            # 只初始化浏览器上下文，不创建标签页（登录时会创建专用的登录标签页）
            success = await self._browser.init_browser()
            if success:
                logger.info(f"✅ {self._platform}浏览器初始化成功")
                return True
            else:
                logger.error(f"❌ {self._platform}浏览器初始化失败")
                return False
        except Exception as e:
            logger.error(f"❌ 浏览器初始化失败: {str(e)}")
            return False
    
    async def _is_browser_healthy(self):
        """检查浏览器是否健康可用"""
        try:
            # 🔧 修复：B站使用统一浏览器管理器，通过 context property 获取上下文
            # 不再检查 self._playwright（不存在）
            
            # 检查上下文是否存在
            if not self.context:
                logger.debug("浏览器上下文不存在")
                return False
            
            # 检查B站页面是否存在且有效
            if not self.page:
                logger.debug("B站页面不存在")
                return False
            
            # 尝试在B站页面上执行简单操作验证可用性
            try:
                await self.page.evaluate("1")
                logger.debug("浏览器健康检查通过")
                return True
            except Exception as e:
                logger.debug(f"页面操作测试失败: {str(e)}")
                return False

        except Exception as e:
            logger.debug(f"浏览器健康检查异常: {str(e)}")
            return False
    
    async def _ensure_browser(self, require_page: bool = True):
        """
        确保浏览器处于可用状态
        
        Args:
            require_page: 是否需要确保页面已创建（获取Cookie时不需要）
        """
        try:
            # 1. 检查浏览器上下文是否健康
            is_context_healthy = False
            try:
                if self.context and len(self.context.pages) > 0:
                    is_context_healthy = True
            except Exception:
                pass
                
            if not is_context_healthy:
                logger.info("浏览器上下文异常，正在重新初始化...")
                # 仅初始化浏览器上下文，不强制创建B站页面
                success = await self._browser.init_browser()
                if not success:
                    raise Exception("浏览器重新初始化失败")
            
            # 2. 如果不需要页面，到此为止（获取Cookie场景）
            if not require_page:
                return True
            
            # 3. 确保有可用页面（常规场景）
            if not self.page:
                logger.info("没有可用页面，初始化B站页面...")
                success = await self.init_browser()
                if not success:
                    raise Exception("页面初始化失败")

            # 4. 页面健康检查
            try:
                await self.page.evaluate("1")
                return True
            except Exception:
                logger.debug("页面响应异常，重新初始化...")
                await self.init_browser()
                return True
                
        except Exception as e:
            logger.error(f"确保浏览器可用失败: {str(e)}")
            return False

    async def get_cookie(self, force_refresh: bool = False) -> str:
        """
        获取 B站 cookie
        
        Args:
            force_refresh: 是否强制刷新（访问主页以保活Session）
        """
        try:
            # 确保浏览器已初始化
            # 如果需要强制刷新，则必须确保有页面
            await self._ensure_browser(require_page=force_refresh)
            
            # 如果需要强制刷新，则访问一次主页
            if force_refresh:
                try:
                    logger.info("正在执行Cookie保活刷新：访问B站主页...")
                    # 🔧 关键修复：显式获取或创建页面
                    # init_browser只初始化上下文，不创建页面，导致self.page为空
                    # 这里必须调用get_page来确保页面存在
                    if not self.page:
                        await self._browser.get_page(self._platform)
                        
                    if self.page:
                        await self.page.goto("https://www.bilibili.com", wait_until="domcontentloaded", timeout=30000)
                        # 等待一小会儿让JS执行
                        await asyncio.sleep(3)
                        logger.info("B站主页访问完成，Session已刷新")
                except Exception as e:
                    logger.warning(f"刷新B站 Session时出错（不影响获取现有Cookie）: {str(e)}")
            
            # 直接从上下文获取Cookie
            cookies = await self.context.cookies()
            if not cookies:
                return ""
                
            # 将 cookies 转换为 Netscape 格式的字符串
            cookie_str = ""
            for cookie in cookies:
                if cookie.get("domain", "").endswith("bilibili.com"):
                    name = cookie.get("name", "")
                    value = cookie.get("value", "")
                    if name and value:
                        cookie_str += f"{name}={value}; "
            
            # 🔧 关键修复：获取cookie后更新浏览器活动时间，防止被自动清理关闭
            await self._update_activity()
            logger.debug("B站 cookie获取完成，已更新浏览器活动时间")
            
            return cookie_str.strip()
        except Exception as e:
            logger.error(f"获取B站 cookie失败: {str(e)}")
            return ""
    
    async def export_cookies_netscape(self, force_refresh: bool = False) -> str:
        """
        从 Playwright 上下文导出 Netscape 格式的 B 站 cookies（保留真实 domain/path/secure/expires）。
        """
        try:
            # 确保浏览器/页面可用；force_refresh 时会访问主页刷新 session
            await self._ensure_browser(require_page=force_refresh)
            
            if force_refresh:
                try:
                    logger.info("正在执行Cookie保活刷新：访问B站主页...")
                    if not self.page:
                        await self._browser.get_page(self._platform)
                    if self.page:
                        await self.page.goto("https://www.bilibili.com", wait_until="domcontentloaded", timeout=30000)
                        await asyncio.sleep(3)
                        logger.info("B站主页访问完成，Session已刷新")
                except Exception as e:
                    logger.warning(f"刷新B站 Session时出错（不影响导出现有Cookie）: {str(e)}")
            
            cookies = await self.context.cookies()
            if not cookies:
                return ""
            
            def _keep(domain: str) -> bool:
                d = (domain or "").lstrip(".").lower()
                return d.endswith("bilibili.com")
            
            lines = []
            for c in cookies:
                domain = (c.get("domain") or "").strip()
                if not _keep(domain):
                    continue
                
                name = (c.get("name") or "").strip()
                value = (c.get("value") or "").strip()
                if not name or not value:
                    continue
                
                dom = domain if domain.startswith(".") else f".{domain}" if domain else ".bilibili.com"
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
            logger.error(f"导出B站 Netscape cookies失败: {type(e).__name__}: {str(e)}")
            return ""
    
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
    
    async def _ensure_http(self, update_cookie: bool = True):
        """确保HTTP客户端已初始化，并可选地更新Cookie
        
        Args:
            update_cookie: 是否从浏览器更新Cookie。如果浏览器未初始化，会跳过更新。
        """
        if self._http is None:
            self._http = httpx.AsyncClient(headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
                "Referer": "https://space.bilibili.com/"
            }, timeout=20)
        
        # 🔧 关键修复：从浏览器获取Cookie并设置到HTTP客户端
        # 这对于通过B站风控校验至关重要
        if update_cookie:
            try:
                # 尝试获取Cookie（get_cookie内部会确保浏览器已初始化）
                cookie_str = await self.get_cookie()
                if cookie_str:
                    # 更新HTTP客户端的Cookie头
                    self._http.headers.update({"Cookie": cookie_str})
                    logger.debug(f"已更新HTTP客户端Cookie（长度: {len(cookie_str)}）")
                else:
                    logger.warning("从浏览器获取的Cookie为空，API请求可能被风控拦截")
            except Exception as e:
                logger.warning(f"更新HTTP客户端Cookie失败: {str(e)}，API请求可能被风控拦截")

    async def _sleep_jitter(self):
        """在发起 API 请求前增加随机抖动延时，降低被限频风险"""
        try:
            await asyncio.sleep(random.uniform(0.8, 1.8))
        except Exception:
            # 即使发生异常也不影响主流程
            pass

    # --- WBI 签名 ---
    @staticmethod
    def _mixin_key(enc_key: str) -> str:
        mixin_key_enc_tab = [46, 47, 18, 2, 53, 8, 23, 32, 15, 50, 10, 31, 58, 3, 45, 35, 27, 43, 5, 49, 33, 9, 42, 19, 29, 28, 14, 39, 12, 38, 41, 13, 37, 48, 7, 16, 24, 55, 40, 61, 26, 17, 0, 1, 60, 51, 30, 4, 22, 25, 54, 21, 56, 59, 6, 63, 57, 62, 11, 36, 20, 34, 44, 52]
        return ''.join([enc_key[i] for i in mixin_key_enc_tab])[:32]

    async def _refresh_wbi_keys(self):
        """刷新WBI签名密钥
        
        使用api_params_cache统一管理
        """
        # 1. 尝试从缓存获取
        cached = api_params_cache.get(self._platform)
        if cached and cached.get('wbi_img_key') and cached.get('wbi_sub_key'):
            logger.debug("B站WBI密钥缓存有效")
            return cached['wbi_img_key'], cached['wbi_sub_key']
        
        # 2. 缓存不存在或已过期，从API获取新密钥
        logger.info("正在获取B站WBI密钥...")
        await self._ensure_http(update_cookie=True)
        await self._sleep_jitter()
        resp = await self._http.get("https://api.bilibili.com/x/web-interface/nav")
        resp.raise_for_status()
        data = resp.json()
        img_url = data.get('data', {}).get('wbi_img', {}).get('img_url', '')
        sub_url = data.get('data', {}).get('wbi_img', {}).get('sub_url', '')
        wbi_img_key = img_url.rsplit('/', 1)[-1].split('.')[0]
        wbi_sub_key = sub_url.rsplit('/', 1)[-1].split('.')[0]
        
        # 3. 保存到统一缓存管理器
        if wbi_img_key and wbi_sub_key:
            api_params_cache.set(self._platform, {
                'wbi_img_key': wbi_img_key,
                'wbi_sub_key': wbi_sub_key
            })
            logger.info("B站WBI密钥已缓存")
            return wbi_img_key, wbi_sub_key
        
        raise Exception("获取B站WBI密钥失败")

    async def _sign_wbi(self, params: dict) -> dict:
        wbi_img_key, wbi_sub_key = await self._refresh_wbi_keys()
        assert wbi_img_key and wbi_sub_key
        mixin_key = self._mixin_key(wbi_img_key + wbi_sub_key)
        # 添加 wts（秒）并对键排序
        params = dict(params)
        params['wts'] = int(time_module.time())
        # 过滤特殊字符
        def filter_chars(s: str) -> str:
            for ch in "!'()*":
                s = s.replace(ch, '')
            return s
        params = {k: filter_chars(str(v)) for k, v in params.items()}
        query = urlencode(sorted(params.items()))
        w_rid = hashlib.md5((query + mixin_key).encode('utf-8')).hexdigest()
        params['w_rid'] = w_rid
        return params

    # --- 真实API：获取UP信息 ---
    async def _fetch_up_info(self, mid: str) -> dict:
        """获取UP主信息（使用浏览器自动化方式）"""
        try:
            # 确保浏览器已初始化并处于可用状态
            if not self.context or not self._is_browser_healthy():
                logger.info("浏览器未初始化或状态异常，正在重新初始化...")
                success = await self.init_browser()
                if not success:
                    raise Exception("浏览器初始化失败")
                logger.info("浏览器重新初始化完成")
            
            # 确保有可用页面
            if not self.page:
                logger.info("没有可用页面，重新初始化浏览器...")
                await self.init_browser()
            
            # 访问UP主空间页面
            space_url = f"https://space.bilibili.com/{mid}"
            logger.info(f"正在访问UP主空间获取信息: {space_url}")
            
            await self.page.goto(space_url, wait_until="domcontentloaded", timeout=30000)
            await asyncio.sleep(2)  # 等待页面加载
            
            # 通过浏览器执行JavaScript获取UP主信息
            up_info = await self.page.evaluate("""
                () => {
                    const info = {};
                    
                    // 获取昵称 - 使用更精确的选择器
                    const nicknameElement = document.querySelector('.nickname, h1, [class*="nickname"]');
                    info.nickname = nicknameElement ? nicknameElement.textContent.trim() : '';
                    
                    // 获取统计数据 - 使用更精确的定位方式
                    const findCountByLabel = (labelText) => {
                        // 查找包含指定标签文本的文本节点
                        const walker = document.createTreeWalker(
                            document.body,
                            NodeFilter.SHOW_TEXT,
                            null,
                            false
                        );
                        
                        let node;
                        while (node = walker.nextNode()) {
                            const text = node.textContent.trim();
                            if (text === labelText) {
                                // 找到标签文本，查找相邻的数值
                                const parent = node.parentElement;
                                if (parent) {
                                    // 查找父元素中的其他文本节点
                                    const siblings = Array.from(parent.childNodes).filter(n => n.nodeType === Node.TEXT_NODE);
                                    for (const sibling of siblings) {
                                        const siblingText = sibling.textContent.trim();
                                        if (siblingText && (siblingText.match(/^[\d,]+$/) || siblingText.includes('万'))) {
                                            return siblingText;
                                        }
                                    }
                                    
                                    // 如果父元素没有，查找父元素的兄弟元素
                                    if (parent.nextElementSibling) {
                                        const nextText = parent.nextElementSibling.textContent.trim();
                                        if (nextText && (nextText.match(/^[\d,]+$/) || nextText.includes('万'))) {
                                            return nextText;
                                        }
                                    }
                                }
                            }
                        }
                        return '';
                    };
                    
                    // 获取各项统计数据
                    info.following_count = findCountByLabel('关注数');
                    info.follower_count = findCountByLabel('粉丝数');
                    info.like_count = findCountByLabel('获赞数');
                    info.play_count = findCountByLabel('播放数');
                    
                    // 获取视频数 - 使用更精确的CSS选择器
                    const findVideoCount = () => {
                        // 首先尝试使用CSS选择器找到视频区域
                        const videoSection = document.querySelector('.section-wrap__header');
                        if (videoSection) {
                            // 查找包含"视频"文本的元素
                            const videoLabel = Array.from(videoSection.querySelectorAll('*')).find(el => 
                                el.textContent && el.textContent.trim() === '视频'
                            );
                            
                            if (videoLabel) {
                                const parent = videoLabel.parentElement;
                                if (parent) {
                                    // 使用正则表达式匹配 "视频·数字" 的格式
                                    const textContent = parent.textContent;
                                    const match = textContent.match(/视频[·\s]*(\d+)/);
                                    if (match) {
                                        return match[1];
                                    }
                                    
                                    // 如果正则匹配失败，尝试查找兄弟元素
                                    const siblings = Array.from(parent.childNodes);
                                    for (const sibling of siblings) {
                                        if (sibling.nodeType === Node.TEXT_NODE) {
                                            const text = sibling.textContent.trim();
                                            if (text && text.match(/^\d+$/)) {
                                                return text;
                                            }
                                        }
                                    }
                                }
                            }
                        }
                        
                        // 备用方法：使用更宽泛的搜索
                        const allElements = document.querySelectorAll('*');
                        for (const el of allElements) {
                            if (el.textContent && el.textContent.includes('视频')) {
                                const text = el.textContent;
                                const match = text.match(/视频[·\s]*(\d+)/);
                                if (match) {
                                    return match[1];
                                }
                            }
                        }
                        
                        return '';
                    };
                    
                    info.video_count = findVideoCount();
                    
                    // 获取头像 - 精确定位UP主头像
                    const findAvatar = () => {
                        // 方法1: 精确定位UP主头像 - 查找在昵称前面的头像
                        const nicknameElement = document.querySelector('.nickname, h1, [class*="nickname"]');
                        if (nicknameElement) {
                            // 从昵称元素开始向上查找头像
                            let currentElement = nicknameElement;
                            let searchDepth = 0;
                            const maxSearchDepth = 10; // 最大搜索深度
                            
                            while (currentElement && searchDepth < maxSearchDepth) {
                                // 查找当前元素或其父元素中的头像
                                const avatarImg = currentElement.querySelector('img[src*="hdslb.com/bfs/face/"]');
                                if (avatarImg) {
                                    return avatarImg.src;
                                }
                                
                                // 查找兄弟元素中的头像
                                const siblingAvatar = currentElement.previousElementSibling?.querySelector('img[src*="hdslb.com/bfs/face/"]');
                                if (siblingAvatar) {
                                    return siblingAvatar.src;
                                }
                                
                                // 向上查找父元素
                                currentElement = currentElement.parentElement;
                                searchDepth++;
                            }
                        }
                        
                        // 方法2: 使用更精确的CSS选择器查找UP主头像
                        const upAvatarSelectors = [
                            '.h-avatar img',
                            '.user-avatar img', 
                            '.avatar img',
                            '[class*="avatar"] img',
                            'picture img[src*="hdslb.com/bfs/face/"]'
                        ];
                        
                        for (const selector of upAvatarSelectors) {
                            const avatarImg = document.querySelector(selector);
                            if (avatarImg && avatarImg.src && avatarImg.src.includes('hdslb.com/bfs/face/')) {
                                // 验证这个头像是否在页面顶部区域（UP主信息区域）
                                const rect = avatarImg.getBoundingClientRect();
                                if (rect.top < 300 && rect.width > 50 && rect.height > 50) {
                                    return avatarImg.src;
                                }
                            }
                        }
                        
                        // 方法3: 备用方案 - 查找页面顶部区域的B站头像
                        const allImages = document.querySelectorAll('img[src*="hdslb.com/bfs/face/"]');
                        for (const img of allImages) {
                            const rect = img.getBoundingClientRect();
                            // 确保头像在页面顶部区域且尺寸合适
                            if (rect.top < 300 && rect.width > 50 && rect.height > 50) {
                                return img.src;
                            }
                        }
                        
                        return '';
                    };
                    
                    info.avatar_url = findAvatar();
                    
                    // 获取个性签名 - 使用多种方法查找
                    const findSignature = () => {
                        // 方法1: 优先使用 .pure-text 选择器（最准确）
                        const pureTextElement = document.querySelector('.pure-text');
                        if (pureTextElement && pureTextElement.textContent.trim()) {
                            const text = pureTextElement.textContent.trim();
                            // 确保获取到的是有效签名
                            if (text.length > 10 && text.length < 500 && 
                                !text.includes('console.log') && 
                                !text.includes('白屏检测')) {
                                return text;
                            }
                        }
                        
                        // 方法2: 查找 .sign.header-sign .pure-text 组合选择器
                        const signPureText = document.querySelector('.sign.header-sign .pure-text');
                        if (signPureText && signPureText.textContent.trim()) {
                            const text = signPureText.textContent.trim();
                            if (text.length > 10 && text.length < 500 && 
                                !text.includes('console.log') && 
                                !text.includes('白屏检测')) {
                                return text;
                            }
                        }
                        
                        // 方法3: 使用传统CSS选择器作为备用
                        const signatureSelectors = [
                            '.user-signature',
                            '.signature', 
                            '.sign .pure-text',
                            '.upinfo-detail__bottom .pure-text'
                        ];
                        
                        for (const selector of signatureSelectors) {
                            const element = document.querySelector(selector);
                            if (element && element.textContent.trim()) {
                                const text = element.textContent.trim();
                                if (text.length > 10 && text.length < 500 && 
                                    !text.includes('console.log') && 
                                    !text.includes('白屏检测') && 
                                    !text.includes('关注') && 
                                    !text.includes('粉丝')) {
                                    return text;
                                }
                            }
                        }
                        
                        // 方法4: 查找包含"官方账号"的小元素（更精确）
                        const allElements = document.querySelectorAll('*');
                        for (const element of allElements) {
                            if (element.textContent && element.textContent.includes('官方账号')) {
                                const text = element.textContent.trim();
                                // 确保是纯净的签名文本，不包含页面其他内容
                                if (text.length > 10 && text.length < 200 && 
                                    !text.includes('console.log') && 
                                    !text.includes('白屏检测') && 
                                    !text.includes('关注') && 
                                    !text.includes('粉丝') && 
                                    !text.includes('播放') && 
                                    !text.includes('视频') && 
                                    !text.includes('代表作') &&
                                    text.startsWith('飞牛fnOS官方账号')) {
                                    return text;
                                }
                            }
                        }
                        
                        // 方法5: 查找个性签名输入框（针对登录用户）
                        const signatureInputs = document.querySelectorAll('input[type="text"], textarea, [role="textbox"]');
                        for (const input of signatureInputs) {
                            // 检查是否是个性签名输入框（通过placeholder或附近文本判断）
                            const placeholder = input.getAttribute('placeholder') || '';
                            const ariaLabel = input.getAttribute('aria-label') || '';
                            
                            if (placeholder.includes('编辑个性签名') || ariaLabel.includes('编辑个性签名') || 
                                input.textContent && input.textContent.includes('编辑个性签名')) {
                                
                                const text = input.textContent ? input.textContent.trim() : input.value ? input.value.trim() : '';
                                
                                // 如果包含"编辑个性签名"前缀，去掉它
                                let signature = text.replace('编辑个性签名', '').trim();
                                
                                if (signature && signature.length > 5 && signature.length < 500) {
                                    return signature;
                                }
                            }
                            
                            // 特殊处理：直接查找包含个性签名内容的textbox
                            if (input.textContent && input.textContent.includes('折腾使我快乐') && 
                                !input.textContent.includes('编辑我的公告') && 
                                !input.textContent.includes('公告')) {
                                
                                const text = input.textContent.trim();
                                if (text.length > 5 && text.length < 500) {
                                    return text;
                                }
                            }
                        }
                        
                        // 方法6: 查找包含"折腾使我快乐"等关键词的元素（通用签名）
                        const commonKeywords = ['折腾使我快乐', '个人简介', '签名', '简介'];
                        for (const keyword of commonKeywords) {
                            for (const element of allElements) {
                                if (element.textContent && element.textContent.includes(keyword)) {
                                    const text = element.textContent.trim();
                                    // 确保是纯净的签名文本，不包含页面其他内容
                                    if (text.length > 10 && text.length < 500 && 
                                        !text.includes('console.log') && 
                                        !text.includes('白屏检测') && 
                                        !text.includes('关注') && 
                                        !text.includes('粉丝') && 
                                        !text.includes('播放') && 
                                        !text.includes('视频') && 
                                        !text.includes('代表作')) {
                                        return text;
                                    }
                                }
                            }
                        }
                        
                        // 方法7: 查找公告区域（最后备用方案）
                        const announcementSelectors = [
                            '.announcement',
                            '.notice',
                            '[class*="announcement"]',
                            '[class*="notice"]'
                        ];
                        
                        for (const selector of announcementSelectors) {
                            const element = document.querySelector(selector);
                            if (element && element.textContent.trim()) {
                                const text = element.textContent.trim();
                                // 过滤掉编辑相关的文本
                                if (text.length > 10 && text.length < 500 && 
                                    !text.includes('console.log') && 
                                    !text.includes('白屏检测') && 
                                    !text.includes('编辑我的公告') && 
                                    !text.includes('0/150') &&
                                    !text.includes('关注') && 
                                    !text.includes('粉丝') && 
                                    !text.includes('播放') && 
                                    !text.includes('视频')) {
                                    return text;
                                }
                            }
                        }
                        
                        return '';
                    };
                    
                    info.signature = findSignature();
                    
                    return info;
                }
            """)
            
            # 提取并处理数据
            nickname = up_info.get('nickname', '')
            signature = up_info.get('signature', '')
            avatar_url = up_info.get('avatar_url', '')
            following_count = self._extract_number(up_info.get('following_count', ''))
            follower_count = self._extract_number(up_info.get('follower_count', ''))
            like_count = self._extract_number(up_info.get('like_count', ''))
            play_count = self._extract_number(up_info.get('play_count', ''))
            video_count = self._extract_number(up_info.get('video_count', ''))
            
            logger.info(f"成功获取UP主信息: {nickname}, 粉丝数: {follower_count}, 视频数: {video_count}")
            
            return {
                'user_id': str(mid),
                'nickname': nickname,
                'signature': signature,
                'avatar_url': avatar_url,
                'following_count': following_count,
                'follower_count': follower_count,
                'like_count': like_count,
                'play_count': play_count,
                'video_count': video_count
            }
            
        except Exception as e:
            logger.error(f"通过浏览器获取UP主信息失败: {str(e)}")
            # 如果浏览器方式失败，尝试API方式（备用方案）
            try:
                return await self._fetch_up_info_api(mid)
            except Exception as api_error:
                logger.error(f"API方式也失败: {str(api_error)}")
                raise Exception(f"获取UP主信息失败: {str(e)}")
    
    async def _fetch_up_info(self, mid: str) -> dict:
        """获取UP主信息（仅使用API方式）"""
        try:
            logger.info(f"使用API方式获取UP主 {mid} 的信息")
            return await self._fetch_up_info_api(mid)
        except Exception as api_error:
            logger.error(f"API方式获取UP主信息失败: {str(api_error)}")
            raise Exception(f"获取UP主信息失败: {str(api_error)}")
    
    async def fetch_up_info(self, mid: str) -> dict:
        """通过队列获取UP主信息（对外接口）"""
        async def _fetch():
            return await self._fetch_up_info(mid)
        return await self.enqueue_request(_fetch)
    
    async def _fetch_up_info_api(self, mid: str) -> dict:
        """通过API获取UP主信息（主要方式）- 优化版本"""
        try:
            await self._ensure_http()
            
            # 更新设备指纹参数，使用抓包得到的最新值
            device_params = {
                'dm_img_list': '[]',
                'dm_img_str': 'V2ViR0wgMS4wIChPcGVuR0wgRVMgMi4wIENocm9taXVtKQ',
                'dm_cover_img_str': 'QU5HTEUgKEludGVsLCBJbnRlbChSKSBVSEQgR3JhcGhpY3MgKDB4MDAwMEE3OEIpIERpcmVjdDNEMTEgdnNfNV8wIHBzXzVfMCwgRDNEMTEpR29vZ2xlIEluYy4gKEludGVsKQ',
                'dm_img_inter': '{"ds":[],"wh":[4437,4014,55],"of":[510,1020,510]}'  # 更新为抓包得到的最新值
            }
            
            # 基础信息（昵称、签名、头像）
            base_params = await self._sign_wbi({
                'mid': mid,
                'token': '',
                'platform': 'web',
                'web_location': '1550101',  # UP主信息API使用1550101，与抓包结果一致
                **device_params
            })
            
            logger.info(f"正在获取UP主 {mid} 的基础信息...")
            await self._sleep_jitter()
            info_resp = await self._http.get("https://api.bilibili.com/x/space/wbi/acc/info", params=base_params)
            info_resp.raise_for_status()
            info_data = info_resp.json()
            
            # 检查签名错误并重试
            if info_data.get('code') == -352:
                logger.warning("UP主基础信息返回-352签名错误，可能是WBI密钥失效，刷新密钥后重试")
                api_params_cache.invalidate(self._platform)
                await self._refresh_wbi_keys()
                base_params = await self._sign_wbi({
                    'mid': mid,
                    'token': '',
                    'platform': 'web',
                    'web_location': '1550101',
                    **device_params
                })
                await self._sleep_jitter()
                info_resp = await self._http.get("https://api.bilibili.com/x/space/wbi/acc/info", params=base_params)
                info_resp.raise_for_status()
                info_data = info_resp.json()
            
            if info_data.get('code') != 0:
                logger.warning(f"UP主基础信息API返回错误: {info_data.get('message', 'Unknown error')}")
                info = {}
            else:
                info = info_data.get('data', {})
                logger.info(f"成功获取UP主 {mid} 基础信息")

            # 粉丝数
            logger.info(f"正在获取UP主 {mid} 的粉丝数...")
            await self._sleep_jitter()
            follow_resp = await self._http.get("https://api.bilibili.com/x/relation/stat", params={
                "vmid": mid, 
                "web_location": "333.1387",
                **device_params
            })
            follow_resp.raise_for_status()
            follow_data = follow_resp.json()
            
            if follow_data.get('code') != 0:
                logger.warning(f"粉丝数API返回错误: {follow_data.get('message', 'Unknown error')}")
                follower_count = 0
            else:
                follower_count = follow_data.get('data', {}).get('follower', 0)
                logger.info(f"成功获取UP主 {mid} 粉丝数: {follower_count}")

            # 视频数
            logger.info(f"正在获取UP主 {mid} 的视频数...")
            await self._sleep_jitter()
            navnum_resp = await self._http.get("https://api.bilibili.com/x/space/navnum", params={
                "mid": mid, 
                "web_location": "333.1387",
                **device_params
            })
            navnum_resp.raise_for_status()
            navnum_data = navnum_resp.json()
            
            if navnum_data.get('code') != 0:
                logger.warning(f"视频数API返回错误: {navnum_data.get('message', 'Unknown error')}")
                video_count = 0
            else:
                video_count = navnum_data.get('data', {}).get('video', 0)
                logger.info(f"成功获取UP主 {mid} 视频数: {video_count}")

            # 获赞、播放等 - 主要API
            logger.info(f"正在获取UP主 {mid} 的统计信息...")
            await self._sleep_jitter()
            upstat_resp = await self._http.get("https://api.bilibili.com/x/space/upstat", params={
                "mid": mid, 
                "web_location": "333.1387",
                **device_params
            })
            upstat_resp.raise_for_status()
            upstat_data = upstat_resp.json()
            
            like_count = 0
            if upstat_data.get('code') != 0:
                logger.warning(f"UP主统计信息API返回错误: {upstat_data.get('message', 'Unknown error')}")
            else:
                upstat = upstat_data.get('data', {})
                if upstat:  # 检查data字段是否为空
                    like_count = upstat.get('likes', 0)
                    logger.info(f"成功获取UP主 {mid} 点赞数: {like_count}")
                else:
                    logger.warning(f"UP主统计信息API返回空数据，尝试备用方案...")
                    # 备用方案：尝试从页面解析获取点赞数
                    like_count = await self._get_like_count_fallback(mid)

            result = {
                "user_id": str(mid),
                "nickname": info.get('name', ''),
                "signature": info.get('sign', ''),
                "avatar_url": info.get('face', ''),
                "video_count": int(video_count or 0),
                "follower_count": int(follower_count or 0),
                "like_count": int(like_count or 0),
            }
            
            # 数据完整性检查
            missing_fields = []
            if not result["nickname"]:
                missing_fields.append("昵称")
            if result["video_count"] == 0:
                missing_fields.append("视频数")
            if result["follower_count"] == 0:
                missing_fields.append("粉丝数")
            if result["like_count"] == 0:
                missing_fields.append("点赞数")
                
            if missing_fields:
                logger.warning(f"UP主 {mid} 信息获取不完整，缺失字段: {', '.join(missing_fields)}")
            else:
                logger.info(f"UP主 {mid} 信息获取完整")
                
            logger.info(f"API方式成功获取UP主 {mid} 信息: {result}")
            return result
            
        except Exception as e:
            logger.error(f"API方式获取UP主信息失败: {str(e)}")
            raise e
    
    async def _get_like_count_fallback(self, mid: str) -> int:
        """备用方案：尝试从页面解析获取点赞数"""
        try:
            logger.info(f"尝试备用方案获取UP主 {mid} 的点赞数...")
            
            # 尝试从页面解析获取点赞数
            space_url = f"https://space.bilibili.com/{mid}"
            
            # 使用浏览器获取页面内容
            if not self.context or not await self._is_browser_healthy():
                logger.info("浏览器未初始化或状态异常，正在重新初始化...")
                success = await self.init_browser()
                if not success:
                    logger.warning("浏览器初始化失败，无法使用备用方案")
                    return 0
            
            # 确保有可用页面
            if not self.page:
                logger.info("没有可用页面，重新初始化浏览器...")
                await self.init_browser()
            
            # 访问UP主空间页面
            await self.page.goto(space_url, wait_until="domcontentloaded", timeout=30000)
            await asyncio.sleep(3)  # 增加等待时间，确保页面完全加载
            
            # 尝试从页面解析点赞数
            like_count = await self.page.evaluate("""
                () => {
                    // 方案1: 从title属性中精确提取点赞数（最高优先级）
                    const elements = document.querySelectorAll('*[title]');
                    for (const element of elements) {
                        const title = element.getAttribute('title');
                        if (title && title.includes('累计获赞')) {
                            // 提取精确数值：截至2025.8.23, 视频、动态、专栏累计获赞1,071,789
                            const match = title.match(/累计获赞([\\d,]+)/);
                            if (match) {
                                const likeCount = parseInt(match[1].replace(/,/g, ''));
                                if (likeCount > 0) {
                                    return likeCount;
                                }
                            }
                        }
                    }
                    
                    // 方案1.5: 直接查找获赞数元素（B站特定选择器）
                    const likeElements = document.querySelectorAll('div, span, a');
                    for (const element of likeElements) {
                        const text = element.textContent;
                        if (text && text.includes('获赞数')) {
                            // 查找相邻的数值元素
                            const parent = element.parentElement;
                            if (parent) {
                                const allText = parent.textContent;
                                const match = allText.match(/获赞数\\s*([\\d.]+万?)/);
                                if (match) {
                                    const value = match[1];
                                    if (value.includes('万')) {
                                        return Math.floor(parseFloat(value.replace('万', '')) * 10000);
                                    } else {
                                        return parseInt(value.replace(/,/g, ''));
                                    }
                                }
                            }
                        }
                    }
                    
                    // 方案2: 查找包含"获赞数"的文本
                    const walker = document.createTreeWalker(
                        document.body,
                        NodeFilter.SHOW_TEXT,
                        null,
                        false
                    );
                    
                    let node;
                    while (node = walker.nextNode()) {
                        const text = node.textContent.trim();
                        if (text.includes('获赞') || text.includes('点赞')) {
                            // 查找相邻的数值
                            const parent = node.parentElement;
                            if (parent) {
                                const siblings = Array.from(parent.childNodes).filter(n => n.nodeType === Node.TEXT_NODE);
                                for (const sibling of siblings) {
                                    const siblingText = sibling.textContent.trim();
                                    if (siblingText && (siblingText.match(/^[\\d,]+万?$/) || siblingText.includes('万'))) {
                                        // 解析数值
                                        if (siblingText.includes('万')) {
                                            const num = parseFloat(siblingText.replace('万', '')) * 10000;
                                            return Math.floor(num);
                                        } else {
                                            return parseInt(siblingText.replace(/,/g, ''));
                                        }
                                    }
                                }
                            }
                        }
                    }
                    
                    // 方案3: 直接查找包含"万"的数字文本
                    const allTexts = [];
                    const textWalker = document.createTreeWalker(
                        document.body,
                        NodeFilter.SHOW_TEXT,
                        null,
                        false
                    );
                    
                    while (node = textWalker.nextNode()) {
                        const text = node.textContent.trim();
                        if (text && (text.includes('万') || text.match(/^[\\d,]+$/))) {
                            allTexts.push(text);
                        }
                    }
                    
                    // 查找可能的点赞数（通常是较大的数字）
                    for (const text of allTexts) {
                        if (text.includes('万') && text.includes('获赞')) {
                            const match = text.match(/(\\d+(?:\\.\\d+)?)万/);
                            if (match) {
                                return Math.floor(parseFloat(match[1]) * 10000);
                            }
                        }
                    }
                    
                    // 方案4: 查找所有包含"万"的数字，取最大的（但排除播放数）
                    let maxCount = 0;
                    for (const text of allTexts) {
                        if (text.includes('万') && !text.includes('播放')) {
                            const match = text.match(/(\\d+(?:\\.\\d+)?)万/);
                            if (match) {
                                const count = Math.floor(parseFloat(match[1]) * 10000);
                                // 点赞数通常在10万到1000万之间
                                if (count > maxCount && count >= 100000 && count <= 10000000) {
                                    maxCount = count;
                                }
                            }
                        }
                    }
                    
                    // 方案5: 最后尝试，查找所有数字并分析
                    if (maxCount === 0) {
                        const allNumbers = [];
                        for (const text of allTexts) {
                            const numbers = text.match(/[\\d,]+/g);
                            if (numbers) {
                                for (const num of numbers) {
                                    const cleanNum = parseInt(num.replace(/,/g, ''));
                                    if (cleanNum >= 100000 && cleanNum <= 10000000) {
                                        allNumbers.push(cleanNum);
                                    }
                                }
                            }
                        }
                        
                        if (allNumbers.length > 0) {
                            // 取中间值，避免取到播放数
                            allNumbers.sort((a, b) => a - b);
                            const midIndex = Math.floor(allNumbers.length / 2);
                            return allNumbers[midIndex];
                        }
                    }
                    
                    return maxCount;
                }
            """)
            
            if like_count > 0:
                logger.info(f"备用方案成功获取UP主 {mid} 点赞数: {like_count}")
                return like_count
            else:
                # 尝试获取更多调试信息
                debug_info = await self.page.evaluate("""
                    () => {
                        const debug = {};
                        
                        // 检查title属性
                        const titleElements = document.querySelectorAll('*[title]');
                        debug.titleElements = [];
                        for (const element of titleElements) {
                            const title = element.getAttribute('title');
                            if (title && title.includes('获赞')) {
                                debug.titleElements.push(title);
                            }
                        }
                        
                        // 检查包含"获赞"的文本
                        const texts = [];
                        const walker = document.createTreeWalker(
                            document.body,
                            NodeFilter.SHOW_TEXT,
                            null,
                            false
                        );
                        
                        let node;
                        while (node = walker.nextNode()) {
                            const text = node.textContent.trim();
                            if (text && (text.includes('获赞') || text.includes('点赞'))) {
                                texts.push(text);
                            }
                        }
                        debug.likeTexts = texts;
                        
                        // 检查所有包含"万"的文本
                        const wanTexts = [];
                        const wanWalker = document.createTreeWalker(
                            document.body,
                            NodeFilter.SHOW_TEXT,
                            null,
                            false
                        );
                        
                        while (node = wanWalker.nextNode()) {
                            const text = node.textContent.trim();
                            if (text && text.includes('万')) {
                                wanTexts.push(text);
                            }
                        }
                        debug.wanTexts = wanTexts;
                        
                        return debug;
                    }
                """)
                
                logger.warning(f"备用方案未能获取到UP主 {mid} 的点赞数")
                logger.debug(f"调试信息: {debug_info}")
                return 0
                
        except Exception as e:
            logger.error(f"备用方案获取点赞数失败: {str(e)}")
            return 0
    
    async def _get_up_videos_api(self, up_id: str, max_count: int = 5, progress_callback=None, retry_on_sign_fail: bool = True) -> List[dict]:
        """使用API方式获取UP主视频列表
        
        包含自动兜底机制：当WBI签名失效时自动刷新并重试
        
        Args:
            up_id: UP主ID
            max_count: 最大获取数量，-1表示获取所有
            progress_callback: 进度回调函数
            retry_on_sign_fail: 是否在签名失败时重试
        
        Returns:
            List[dict]: 视频列表
        """
        try:
            await self._ensure_http()
            
            # 检查是否需要分页获取所有视频
            if max_count == -1:
                logger.info("检测到需要获取所有分页视频，开始分页处理...")
                return await self._get_up_videos_api_paginated(up_id, max_count, progress_callback)
            
            # 单页获取
            params = {
                'mid': up_id,
                'ps': max_count if max_count > 0 else 40,  # 使用40作为默认值，与抓包结果一致
                'tid': 0,
                'pn': 1,
                'keyword': '',
                'order': 'pubdate',
                'platform': 'web',
                'web_location': '333.1387',  # 使用抓包得到的web_location
                # 添加设备指纹参数，避免风控，使用抓包得到的最新值
                'dm_img_list': '[]',
                'dm_img_str': 'V2ViR0wgMS4wIChPcGVuR0wgRVMgMi4wIENocm9taXVtKQ',
                'dm_cover_img_str': 'QU5HTEUgKEludGVsLCBJbnRlbChSKSBVSEQgR3JhcGhpY3MgKDB4MDAwMEE3OEIpIERpcmVjdDNEMTEgdnNfNV8wIHBzXzVfMCwgRDNEMTEpR29vZ2xlIEluYy4gKEludGVsKQ',
                'dm_img_inter': '{"ds":[],"wh":[4551,4052,93],"of":[486,972,486]}'  # 更新为抓包得到的最新值
            }
            
            # 签名参数
            signed_params = await self._sign_wbi(params)
            
            # 发送开始状态
            if progress_callback:
                await progress_callback({
                    "type": "page_progress",
                    "status": "syncing",
                    "message": "开始获取视频列表...",
                    "current_page": 1,
                    "total_pages": 1,
                    "count": 0
                })
            
            # 获取视频列表
            await self._sleep_jitter()
            response = await self._http.get("https://api.bilibili.com/x/space/wbi/arc/search", params=signed_params)
            response.raise_for_status()
            data = response.json()
            
            # 检查是否需要刷新WBI密钥重试
            if data.get('code') == -352 and retry_on_sign_fail:
                logger.warning("B站API返回-352签名错误，可能是WBI密钥失效，尝试刷新并重试")
                # 清理缓存，强制重新获取
                api_params_cache.invalidate(self._platform)
                # 重试一次，不再重复重试
                return await self._get_up_videos_api(up_id, max_count, progress_callback, retry_on_sign_fail=False)
            
            if data.get('code') != 0:
                raise Exception(f"API返回错误: {data.get('message', 'Unknown error')}")
            
            videos = []
            video_list = data.get('data', {}).get('list', {}).get('vlist', [])
            
            for video in video_list:
                videos.append({
                    "url": f"https://www.bilibili.com/video/{video.get('bvid', '')}",
                    "title": video.get('title', ''),
                    "cover_url": video.get('pic', ''),
                    "play_count": video.get('play', 0),
                    "duration": self._format_duration(video.get('length', '')),
                    "publish_time_parsed": datetime.fromtimestamp(video.get('created', 0)).strftime('%Y-%m-%d %H:%M:%S'),
                    "video_id": video.get('bvid', ''),
                    "publish_time": datetime.fromtimestamp(video.get('created', 0)).isoformat(),
                    "is_charging_arc": video.get('is_charging_arc', False)
                })
            
            # 发送完成状态
            if progress_callback:
                await progress_callback({
                    "type": "page_progress",
                    "status": "syncing",
                    "message": f"获取完成，共 {len(videos)} 个视频",
                    "current_page": 1,
                    "total_pages": 1,
                    "count": len(videos)
                })
            
            logger.debug(f"API方式成功获取到 {len(videos)} 个视频")
            return videos
            
        except Exception as e:
            logger.error(f"API方式获取视频列表失败: {str(e)}")
            
            # 发送错误状态
            if progress_callback:
                await progress_callback({
                    "type": "page_progress",
                    "status": "error",
                    "message": f"获取失败: {str(e)}",
                    "current_page": 0,
                    "total_pages": 0,
                    "count": 0
                })
            
            raise e
    
    async def _get_up_videos_api_paginated(self, up_id: str, max_count: int = -1, progress_callback=None) -> List[dict]:
        """支持分页的API视频列表获取"""
        try:
            await self._ensure_http()
            
            all_videos = []
            page = 1
            page_size = 40  # B站API每页最大40个，与抓包结果一致
            
            logger.info(f"开始分页获取UP主 {up_id} 的所有视频")
            
            # 发送开始状态
            if progress_callback:
                await progress_callback({
                    "type": "page_progress",
                    "status": "syncing",
                    "message": "开始分页获取视频列表...",
                    "current_page": 1,
                    "total_pages": 0,  # 暂时不知道总页数
                    "count": 0
                })
            
            while True:
                params = {
                    'mid': up_id,
                    'ps': page_size,
                    'pn': page,
                    'tid': 0,
                    'keyword': '',
                    'order': 'pubdate',
                    'platform': 'web',
                    'web_location': '333.1387',
                    # 添加设备指纹参数，避免风控，使用抓包得到的最新值
                    'dm_img_list': '[]',
                    'dm_img_str': 'V2ViR0wgMS4wIChPcGVuR0wgRVMgMi4wIENocm9taXVtKQ',
                    'dm_cover_img_str': 'QU5HTEUgKEludGVsLCBJbnRlbChSKSBVSEQgR3JhcGhpY3MgKDB4MDAwMEE3OEIpIERpcmVjdDNEMTEgdnNfNV8wIHBzXzVfMCwgRDNEMTEpR29vZ2xlIEluYy4gKEludGVsKQ',
                    'dm_img_inter': '{"ds":[],"wh":[4551,4052,93],"of":[486,972,486]}'  # 更新为抓包得到的最新值
                }
                
                signed_params = await self._sign_wbi(params)
                
                logger.info(f"正在获取第 {page} 页视频...")
                
                # 发送分页进度更新
                if progress_callback:
                    await progress_callback({
                        "type": "page_progress",
                        "status": "syncing",
                        "message": f"正在获取第 {page} 页视频...",
                        "current_page": page,
                        "total_pages": 0,  # 暂时不知道总页数
                        "count": len(all_videos)
                    })
                
                await self._sleep_jitter()
                response = await self._http.get("https://api.bilibili.com/x/space/wbi/arc/search", params=signed_params)
                response.raise_for_status()
                data = response.json()
                
                # 检查签名错误并重试（分页方法）
                if data.get('code') == -352:
                    logger.warning(f"第{page}页返回-352签名错误，可能是WBI密钥失效，刷新密钥后重试")
                    api_params_cache.invalidate(self._platform)
                    await self._refresh_wbi_keys()
                    signed_params = await self._sign_wbi(params)
                    await self._sleep_jitter()
                    response = await self._http.get("https://api.bilibili.com/x/space/wbi/arc/search", params=signed_params)
                    response.raise_for_status()
                    data = response.json()
                
                if data.get('code') != 0:
                    raise Exception(f"API返回错误: {data.get('message', 'Unknown error')}")
                
                video_list = data.get('data', {}).get('list', {}).get('vlist', [])
                if not video_list:
                    logger.debug(f"第 {page} 页没有更多视频，分页获取完成")
                    break
                
                page_videos = []
                for video in video_list:
                    page_videos.append({
                        "url": f"https://www.bilibili.com/video/{video.get('bvid', '')}",
                        "title": video.get('title', ''),
                        "cover_url": video.get('pic', ''),
                        "play_count": video.get('play', 0),
                        "duration": self._format_duration(video.get('length', '')),
                        "publish_time_parsed": datetime.fromtimestamp(video.get('created', 0)).strftime('%Y-%m-%d %H:%M:%S'),
                        "video_id": video.get('bvid', ''),
                        "publish_time": datetime.fromtimestamp(video.get('created', 0)).isoformat(),
                        "is_charging_arc": video.get('is_charging_arc', False)
                    })
                
                all_videos.extend(page_videos)
                logger.debug(f"第 {page} 页获取到 {len(page_videos)} 个视频，累计 {len(all_videos)} 个")
                
                # 发送实时进度更新
                if progress_callback:
                    await progress_callback({
                        "type": "page_progress",
                        "status": "syncing",
                        "message": f"第 {page} 页获取完成，累计 {len(all_videos)} 个视频",
                        "current_page": page,
                        "total_pages": 0,  # 暂时不知道总页数
                        "count": len(all_videos)
                    })
                
                # 检查是否达到最大数量
                if max_count > 0 and len(all_videos) >= max_count:
                    all_videos = all_videos[:max_count]
                    logger.info(f"已达到最大数量限制 {max_count}，停止分页获取")
                    
                    # 发送最终进度更新
                    if progress_callback:
                        await progress_callback({
                            "type": "page_progress",
                            "status": "syncing",
                            "message": f"已达到最大数量限制 {max_count}，获取完成",
                            "current_page": page,
                            "total_pages": page,
                            "count": len(all_videos)
                        })
                    break
                
                page += 1
                
                # 添加短暂延迟，避免请求过快
                await asyncio.sleep(0.5)
            
            logger.info(f"分页获取完成，总共获取到 {len(all_videos)} 个视频")
            
            # 发送完成状态
            if progress_callback:
                await progress_callback({
                    "type": "page_progress",
                    "status": "syncing",
                    "message": f"分页获取完成，总共 {len(all_videos)} 个视频",
                    "current_page": page - 1,
                    "total_pages": page - 1,
                    "count": len(all_videos)
                })
            
            return all_videos
            
        except Exception as e:
            logger.error(f"API分页获取视频列表失败: {str(e)}")
            
            # 发送错误状态
            if progress_callback:
                await progress_callback({
                    "type": "page_progress",
                    "status": "error",
                    "message": f"获取失败: {str(e)}",
                    "current_page": 0,
                    "total_pages": 0,
                    "count": 0
                })
            
            raise e
    
    async def _get_up_videos_api_incremental(self, up_id: str, latest_video_time=None, progress_callback=None) -> List[dict]:
        """API方式的增量获取新视频"""
        try:
            await self._ensure_http()
            
            new_videos = []
            page = 1
            page_size = 40
            
            logger.info(f"开始API方式增量获取UP主 {up_id} 的新视频，基准时间: {latest_video_time}")
            
            # 发送开始状态
            if progress_callback:
                await progress_callback({
                    "type": "check_progress",
                    "status": "starting",
                    "message": "开始API方式检查新视频...",
                    "current": 0,
                    "total": 0
                })
            
            while True:
                params = {
                    'mid': up_id,
                    'ps': page_size,
                    'pn': page,
                    'tid': 0,
                    'keyword': '',
                    'order': 'pubdate',
                    'platform': 'web',
                    'web_location': '333.1387',
                    # 添加设备指纹参数，避免风控，使用抓包得到的最新值
                    'dm_img_list': '[]',
                    'dm_img_str': 'V2ViR0wgMS4wIChPcGVuR0wgRVMgMi4wIENocm9taXVtKQ',
                    'dm_cover_img_str': 'QU5HTEUgKEludGVsLCBJbnRlbChSKSBVSEQgR3JhcGhpY3MgKDB4MDAwMEE3OEIpIERpcmVjdDNEMTEgdnNfNV8wIHBzXzVfMCwgRDNEMTEpR29vZ2xlIEluYy4gKEludGVsKQ',
                    'dm_img_inter': '{"ds":[],"wh":[4551,4052,93],"of":[486,972,486]}'  # 更新为抓包得到的最新值
                }
                
                signed_params = await self._sign_wbi(params)
                
                logger.info(f"正在获取第 {page} 页视频进行增量检查...")
                
                # 发送进度更新
                if progress_callback:
                    await progress_callback({
                        "type": "check_progress",
                        "status": "checking",
                        "message": f"正在检查第 {page} 页视频...",
                        "current": page,
                        "total": 0
                    })
                
                await self._sleep_jitter()
                response = await self._http.get("https://api.bilibili.com/x/space/wbi/arc/search", params=signed_params)
                response.raise_for_status()
                data = response.json()
                
                # 检查签名错误并重试（增量方法）
                if data.get('code') == -352:
                    logger.warning(f"第{page}页增量检查返回-352签名错误，可能是WBI密钥失效，刷新密钥后重试")
                    api_params_cache.invalidate(self._platform)
                    await self._refresh_wbi_keys()
                    signed_params = await self._sign_wbi(params)
                    await self._sleep_jitter()
                    response = await self._http.get("https://api.bilibili.com/x/space/wbi/arc/search", params=signed_params)
                    response.raise_for_status()
                    data = response.json()
                
                if data.get('code') != 0:
                    raise Exception(f"API返回错误: {data.get('message', 'Unknown error')}")
                
                video_list = data.get('data', {}).get('list', {}).get('vlist', [])
                if not video_list:
                    logger.info(f"第 {page} 页没有更多视频，增量检查完成")
                    break
                
                page_new_videos = 0
                for video in video_list:
                    video_time = datetime.fromtimestamp(video.get('created', 0))
                    
                    # 与基准时间比较
                    if latest_video_time:
                        # 确保基准时间也是naive datetime
                        if latest_video_time.tzinfo is not None:
                            latest_video_time = latest_video_time.replace(tzinfo=None)
                        
                        if video_time <= latest_video_time:
                            logger.info(f"第 {page} 页视频时间 {video_time} 不比基准时间 {latest_video_time} 更新，停止检查")
                            return new_videos
                    
                    # 添加新视频
                    new_videos.append({
                        "url": f"https://www.bilibili.com/video/{video.get('bvid', '')}",
                        "title": video.get('title', ''),
                        "cover_url": video.get('pic', ''),
                        "play_count": video.get('play', 0),
                        "duration": self._format_duration(video.get('length', '')),
                        "publish_time_parsed": video_time.strftime('%Y-%m-%d %H:%M:%S'),
                        "video_id": video.get('bvid', ''),
                        "publish_time": video_time.isoformat(),
                        "is_charging_arc": video.get('is_charging_arc', False)
                    })
                    page_new_videos += 1
                
                logger.info(f"第 {page} 页发现 {page_new_videos} 个新视频，累计 {len(new_videos)} 个")
                
                page += 1
                
                # 添加短暂延迟，避免请求过快
                await asyncio.sleep(0.5)
            
            logger.info(f"API增量获取完成，总共发现 {len(new_videos)} 个新视频")
            return new_videos
            
        except Exception as e:
            logger.error(f"API增量获取视频列表失败: {str(e)}")
            raise e
    
    def _format_duration(self, duration_str: str) -> str:
        """格式化时长字符串"""
        try:
            if not duration_str:
                return "00:00"
            
            # 如果已经是 MM:SS 或 HH:MM:SS 格式，直接返回
            if ':' in duration_str:
                return duration_str
            
            # 如果是秒数，转换为 MM:SS 格式
            if duration_str.isdigit():
                total_seconds = int(duration_str)
                minutes = total_seconds // 60
                seconds = total_seconds % 60
                if minutes >= 60:
                    hours = minutes // 60
                    minutes = minutes % 60
                    return f"{hours:02d}:{minutes:02d}:{seconds:02d}"
                else:
                    return f"{minutes:02d}:{seconds:02d}"
            
            return duration_str
        except Exception:
            return "00:00"
    
    def _extract_number(self, text: str) -> int:
        """从文本中提取数字"""
        try:
            if not text:
                return 0
            # 移除所有非数字字符，只保留数字
            import re
            numbers = re.findall(r'\d+', text)
            if numbers:
                return int(''.join(numbers))
            return 0
        except Exception:
            return 0

    async def login(self):
        """打开登录页面等待用户登录"""
        try:
            logger.info("B站登录流程启动")
            
            # 只在浏览器未初始化时才初始化（避免创建多余的基础页面）
            if not self.context:
                logger.info("浏览器未初始化，正在初始化...")
                success = await self.init_browser()
                if not success:
                    raise Exception("浏览器初始化失败")
                logger.info("浏览器初始化完成")
                # 重置登录页面引用
                self._login_page = None
            
            # 通过统一管理器创建独立的登录标签页
            if not hasattr(self, '_login_page') or not self._login_page:
                logger.info("创建B站登录页面...")
                self._login_page = await self._browser.get_page("bilibili_login")
                if not self._login_page:
                    raise Exception("创建B站登录页面失败")
                self._login_page.set_default_timeout(30000)
                logger.info("B站登录页面创建成功")
            else:
                # 检查登录页面是否有效
                try:
                    await self._login_page.evaluate("1")
                    logger.info("使用现有登录页面")
                except Exception:
                    logger.info("登录页面已失效，重新创建...")
                    self._login_page = await self._browser.get_page("bilibili_login")
                    if not self._login_page:
                        raise Exception("创建B站登录页面失败")
                    self._login_page.set_default_timeout(30000)
                    logger.info("B站登录页面重新创建成功")
            
            # 设置页面视口大小
            await self._login_page.set_viewport_size({"width": 1280, "height": 800})
            
            # 访问B站主页，让用户自然登录
            logger.info("正在访问B站主页...")
            await self._login_page.goto(
                "https://www.bilibili.com/",
                wait_until="domcontentloaded",
                timeout=30000
            )
            logger.info("B站主页加载完成")
            
            # 等待页面稳定
            await asyncio.sleep(2)
            
            # 检查当前URL（先检查页面是否仍然有效，可能是用户主动关闭）
            if not self._login_page:
                logger.info("用户已关闭浏览器，登录已取消")
                return {"message": "登录已取消", "cancelled": True}
            
            # 检查页面是否已被关闭
            try:
                if self._login_page.is_closed():
                    logger.info("用户已关闭浏览器，登录已取消")
                    return {"message": "登录已取消", "cancelled": True}
            except Exception as e:
                # 如果检查is_closed()也失败，说明页面已无效（用户可能已关闭）
                if "closed" in str(e).lower() or "Target page, context or browser has been closed" in str(e):
                    logger.info("用户已关闭浏览器，登录已取消")
                    return {"message": "登录已取消", "cancelled": True}
                # 其他异常继续抛出
            
            try:
                current_url = self._login_page.url
                logger.info(f"当前页面URL: {current_url}")
            except Exception as e:
                # 如果页面已经被关闭（用户主动关闭），返回取消状态
                if "closed" in str(e).lower() or "Target page, context or browser has been closed" in str(e) or "'NoneType' object has no attribute 'url'" in str(e):
                    logger.info("用户已关闭浏览器，登录已取消")
                    return {"message": "登录已取消", "cancelled": True}
                # 其他异常继续抛出
            
            # 如果用户未登录，页面可能会显示登录按钮
            if "login" in current_url or "passport" in current_url:
                logger.info("检测到需要登录，当前在登录页面")
            else:
                logger.info("页面加载完成，等待用户操作")
            
            return {"message": "登录页面已打开"}
            
        except Exception as e:
            # 检查是否是因为浏览器关闭导致的错误
            error_msg = str(e).lower()
            if "closed" in error_msg or "Target page, context or browser has been closed" in str(e):
                logger.info("用户已关闭浏览器，登录已取消")
                return {"message": "登录已取消", "cancelled": True}
            
            # 真正的错误才记录为ERROR并抛出
            logger.error(f"启动登录失败: {str(e)}")
            raise Exception(f"启动登录失败: {str(e)}")
    
    async def clean_browser(self):
        """清理浏览器文件"""
        try:
            logger.info("B站清理浏览器")
            
            # 先关闭浏览器
            logger.info("正在关闭浏览器...")
            await self.close_browser()
            logger.info("浏览器关闭完成")
            
            # 获取统一浏览器的数据目录
            user_data_dir = self._browser.user_data_dir
            
            # 清理持久化数据目录（这会删除所有登录状态、cookies等）
            if os.path.exists(user_data_dir):
                try:
                    logger.info(f"正在删除统一浏览器持久化数据目录: {user_data_dir}")
                    import shutil
                    shutil.rmtree(user_data_dir)
                    logger.info(f"已删除统一浏览器持久化数据目录: {user_data_dir}")
                except Exception as e:
                    logger.error(f"删除持久化数据目录失败: {str(e)}")
                    raise Exception(f"删除持久化数据目录失败: {str(e)}")
            else:
                logger.info("持久化数据目录不存在，无需删除")
            
            logger.info("B站浏览器文件清理成功")
            return {"message": "浏览器文件清理成功"}
        except Exception as e:
            logger.error(f"B站清理浏览器文件失败: {str(e)}")
            raise Exception(f"清理浏览器文件失败: {str(e)}")
    
    def _clean_bilibili_url(self, url: str) -> str:
        """清理B站URL，只保留核心BV号"""
        # 提取BV号
        bv_match = re.search(r'bilibili\.com/video/(BV[\w]+)', url)
        if bv_match:
            bvid = bv_match.group(1)
            return f"https://www.bilibili.com/video/{bvid}"
        return url
    
    async def parse_url(self, url: str) -> dict:
        """解析B站链接，支持UP主链接和视频合集链接"""
        try:
            # 清理URL
            clean_url = self._clean_bilibili_url(url)
            
            # 检查是否为视频链接
            bv_match = re.search(r'bilibili\.com/video/(BV[\w]+)', clean_url)
            if bv_match:
                bvid = bv_match.group(1)
                return await self.parse_video_url(bvid)
            
            # 检查是否为UP主链接
            up_id_match = re.search(r'space\.bilibili\.com/(\d+)', url)
            if up_id_match:
                mid = up_id_match.group(1)
                up_info = await self.fetch_up_info(mid)
                return up_info
            
            raise Exception("无法识别的B站链接格式")
        except Exception as e:
            logger.error(f"解析B站链接失败: {str(e)}")
            raise HTTPException(status_code=400, detail=f"解析B站链接失败: {str(e)}")
    
    async def parse_up_url(self, url: str) -> dict:
        """解析B站UP主链接，获取UP主信息（使用官方API替代占位抓取）"""
        try:
            up_id_match = re.search(r'space\.bilibili\.com/(\d+)', url)
            if not up_id_match:
                raise Exception("无法从URL中提取UP主ID")
            mid = up_id_match.group(1)
            up_info = await self.fetch_up_info(mid)  # 使用队列方法
            return up_info
        except Exception as e:
            logger.error(f"解析B站UP主链接失败: {str(e)}")
            raise HTTPException(status_code=400, detail=f"解析B站UP主链接失败: {str(e)}")
    
    async def parse_video_url(self, bvid: str) -> dict:
        """解析B站视频链接，获取视频/合集信息"""
        try:
            logger.info(f"解析B站视频: {bvid}")
            video_info = await self.fetch_video_collection_info(bvid)
            return video_info
        except Exception as e:
            logger.error(f"解析B站视频链接失败: {str(e)}")
            raise HTTPException(status_code=400, detail=f"解析B站视频链接失败: {str(e)}")
    
    async def fetch_video_collection_info(
        self,
        bvid: str,
        max_items: int = None,
        stop_at_video_id: str = None
    ) -> dict:
        """获取B站视频/合集信息"""
        try:
            # 确保HTTP客户端已初始化（包含Cookie支持）
            await self._ensure_http()
            
            # 使用B站官方API获取视频信息
            api_url = f"https://api.bilibili.com/x/web-interface/view?bvid={bvid}"
            
            # 使用带有Cookie的HTTP客户端（通过_ensure_http初始化）
            # 添加必要的请求头
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
                "Referer": "https://www.bilibili.com/"
            }
            
            # 使用self._http（已包含Cookie）发送请求
            response = await self._http.get(api_url, headers=headers, timeout=20)
            response.raise_for_status()
            data = response.json()
            
            if data.get('code') != 0:
                error_message = data.get('message', '未知错误')
                # 如果是"啥都木有"错误，可能是视频不存在、被删除或需要登录
                if error_message == "啥都木有":
                    raise Exception(f"B站API返回错误: {error_message}（可能原因：视频不存在、被删除或需要登录Cookie）")
                raise Exception(f"B站API返回错误: {error_message}")
            
            video_data = data.get('data')
            if not video_data:
                raise Exception("B站API返回数据为空，可能视频不存在或已被删除")
            
            # 判断是否为合集（多P视频或UGC合集）
            is_multi_part = video_data.get('videos', 1) > 1  # 多P视频
            ugc_season = video_data.get('ugc_season')  # UGC合集
            is_collection = is_multi_part or (ugc_season is not None)
            
            # 获取页面信息
            if ugc_season:
                # UGC合集：遍历全部 section/episode，并兼容 episode 下二级 pages
                pages = []
                global_page = 1
                sections = ugc_season.get('sections', []) or []
                should_stop = False

                for section in sections:
                    if should_stop:
                        break
                    section_title = section.get('title', '')
                    episodes = section.get('episodes', []) or []

                    for episode in episodes:
                        if should_stop:
                            break
                        episode_title = episode.get('title', '')
                        episode_arc = episode.get('arc', {}) or {}
                        episode_bvid = episode.get('bvid', '')
                        episode_pages = episode.get('pages', []) or []

                        if episode_pages:
                            # 二级列表：将 episode.pages 展开为可同步的视频条目
                            page_count = len(episode_pages)
                            for ep_page in episode_pages:
                                candidate_sub_page = ep_page.get('page', 1)
                                candidate_video_id = f"{episode_bvid}_p{candidate_sub_page}" if page_count > 1 else episode_bvid
                                page_info = {
                                    'page': global_page,  # 保留全局顺序，兼容增量逻辑
                                    'part': ep_page.get('part') or episode_title or f'P{global_page}',
                                    'duration': ep_page.get('duration', episode_arc.get('duration', 0)),
                                    'cid': ep_page.get('cid', episode.get('cid', '')),
                                    'aid': episode.get('aid', ''),
                                    'bvid': episode_bvid,
                                    'arc': episode_arc,  # 保留完整arc信息，包含发布时间
                                    'sub_page': ep_page.get('page', 1),
                                    'page_count': page_count,
                                    'episode_title': episode_title,
                                    'section_title': section_title
                                }
                                pages.append(page_info)
                                global_page += 1
                                if stop_at_video_id and candidate_video_id == stop_at_video_id:
                                    should_stop = True
                                    break
                                if max_items and len(pages) >= max_items:
                                    should_stop = True
                                    break
                        else:
                            # 一级列表（无二级pages）保持原有行为
                            page_obj = episode.get('page', {}) or {}
                            candidate_sub_page = page_obj.get('page', 1)
                            candidate_video_id = f"{episode_bvid}_p{candidate_sub_page}" if candidate_sub_page > 1 else episode_bvid
                            page_info = {
                                'page': global_page,
                                'part': page_obj.get('part') or episode_title or f'P{global_page}',
                                'duration': page_obj.get('duration', episode_arc.get('duration', 0)),
                                'cid': page_obj.get('cid', episode.get('cid', '')),
                                'aid': episode.get('aid', ''),
                                'bvid': episode_bvid,
                                'arc': episode_arc,
                                'sub_page': page_obj.get('page', 1),
                                'page_count': 1,
                                'episode_title': episode_title,
                                'section_title': section_title
                            }
                            pages.append(page_info)
                            global_page += 1
                            if stop_at_video_id and candidate_video_id == stop_at_video_id:
                                should_stop = True
                                break
                            if max_items and len(pages) >= max_items:
                                should_stop = True
                                break
            else:
                # 多P视频：使用原有的pages信息
                pages = video_data.get('pages', [])
                if max_items:
                    pages = pages[:max_items]
            
            # 获取UP主信息
            owner = video_data.get('owner', {})
            
            # 转换时间戳为ISO格式字符串
            publish_timestamp = video_data.get('pubdate', 0)
            if publish_timestamp:
                publish_time = datetime.fromtimestamp(publish_timestamp).isoformat()
            else:
                publish_time = datetime.now().isoformat()
            
            # 计算视频总数
            if ugc_season:
                videos_count = len(pages)  # UGC合集的视频数量
                collection_title = ugc_season.get('title', '')
            else:
                videos_count = video_data.get('videos', 1)  # 多P视频的分P数量
                collection_title = video_data.get('title', '')
            
            # 获取充电专属状态
            is_upower_exclusive = video_data.get('is_upower_exclusive', False)
            
            result = {
                'bvid': bvid,
                'title': video_data.get('title', ''),
                'description': video_data.get('desc', ''),
                'cover_url': video_data.get('pic', ''),
                'duration': video_data.get('duration', 0),
                'publish_time': publish_time,
                'is_collection': is_collection,
                'videos_count': videos_count,
                'pages': pages,
                'owner': {
                    'mid': owner.get('mid', ''),
                    'name': owner.get('name', ''),
                    'face': owner.get('face', '')
                },
                'platform': 'bilibili_collection' if is_collection else 'bilibili',
                'url': f"https://www.bilibili.com/video/{bvid}",
                'collection_title': collection_title,
                'ugc_season_id': ugc_season.get('id') if ugc_season else None,
                'is_charging_arc': is_upower_exclusive
            }
            
            logger.info(f"获取B站视频信息成功: {result['title']} ({'合集' if is_collection else '单个视频'})")
            return result
                
        except Exception as e:
            logger.error(f"获取B站视频信息失败: {str(e)}")
            raise Exception(f"获取视频信息失败: {str(e)}")
    
    async def get_up_videos(self, up_id: str, max_count: int = 5, progress_callback=None) -> List[dict]:
        """获取UP主视频列表（仅使用API方式）"""
        try:
            logger.info(f"使用API方式获取UP主 {up_id} 的视频列表")
            return await self._get_up_videos_api(up_id, max_count, progress_callback)
        except Exception as api_error:
            logger.error(f"API方式获取视频列表失败: {str(api_error)}")
            raise HTTPException(status_code=400, detail=f"获取B站UP主视频列表失败: {str(api_error)}")
    
    async def get_collection_videos(
        self,
        bvid: str,
        max_count: int = None,
        progress_callback=None,
        stop_at_video_id: str = None
    ) -> List[dict]:
        """获取合集中的视频列表"""
        try:
            logger.info(f"获取B站合集视频列表: {bvid}")
            start_time = asyncio.get_event_loop().time()
            
            # 获取合集信息
            collection_info = await self.fetch_video_collection_info(
                bvid,
                max_items=max_count,
                stop_at_video_id=stop_at_video_id
            )
            pages = collection_info.get('pages', [])
            
            if not collection_info.get('is_collection', False):
                logger.warning(f"视频 {bvid} 不是合集，只有1个视频")
            
            # 限制获取数量（兜底，fetch 已处理大部分场景）
            if max_count:
                pages = pages[:max_count]
            
            logger.info(f"开始处理 {len(pages)} 个视频...")
            videos = []
            bvid_title_cache = {bvid: collection_info.get('title', '')}

            async def _get_root_bvid_title(target_bvid: str) -> str:
                if not target_bvid:
                    return ""
                if target_bvid in bvid_title_cache:
                    return bvid_title_cache[target_bvid]
                title = ""
                try:
                    api_url = f"https://api.bilibili.com/x/web-interface/view?bvid={target_bvid}"
                    headers = {
                        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
                        "Referer": "https://www.bilibili.com/"
                    }
                    response = await self._http.get(api_url, headers=headers, timeout=20)
                    response.raise_for_status()
                    data = response.json() or {}
                    if data.get("code") == 0:
                        title = ((data.get("data") or {}).get("title") or "").strip()
                except Exception as e:
                    logger.debug(f"获取根BV标题失败: bvid={target_bvid}, error={str(e)}")
                bvid_title_cache[target_bvid] = title
                return title

            for i, page in enumerate(pages):
                try:
                    # 每10个视频输出一次进度
                    if i % 10 == 0:
                        logger.info(f"正在处理第 {i+1}/{len(pages)} 个视频...")
                    
                    # 格式化时长
                    duration_seconds = page.get('duration', 0)
                    duration_str = self._format_duration(duration_seconds)
                    
                    # 构建视频信息
                    # 兼容：
                    # 1) 普通多P：bvid + ?p
                    # 2) UGC合集一级：独立bvid
                    # 3) UGC合集二级pages：独立bvid + ?p
                    source_bvid = page.get('bvid') or bvid
                    sub_page = page.get('sub_page')
                    page_count = page.get('page_count', 1)
                    root_bvid = source_bvid
                    root_bvid_title = await _get_root_bvid_title(root_bvid)

                    if sub_page and page_count > 1:
                        video_url = f"https://www.bilibili.com/video/{source_bvid}?p={sub_page}"
                        video_id = f"{source_bvid}_p{sub_page}"
                    elif source_bvid == bvid:
                        root_page = page.get('page', 1)
                        video_url = f"https://www.bilibili.com/video/{source_bvid}?p={root_page}"
                        video_id = f"{source_bvid}_p{root_page}"
                    else:
                        video_url = f"https://www.bilibili.com/video/{source_bvid}"
                        video_id = source_bvid
                    
                    # 获取视频的发布时间
                    if page.get('arc') and page['arc'].get('pubdate'):
                        # UGC合集：每个视频有独立的发布时间
                        video_publish_time = datetime.fromtimestamp(page['arc']['pubdate']).isoformat()
                    else:
                        # 多P视频：使用合集的发布时间
                        video_publish_time = collection_info.get('publish_time', datetime.now().isoformat())
                    
                    video_info = {
                        "url": video_url,
                        "title": page.get('part', f"P{page['page']}"),
                        "cover_url": collection_info.get('cover_url', ''),
                        "duration": duration_str,
                        "duration_seconds": duration_seconds,
                        "video_id": video_id,
                        "page": page['page'],
                        "cid": page.get('cid', ''),
                        "publish_time": video_publish_time,
                        "is_charging_arc": page.get('arc', {}).get('is_charging_arc', collection_info.get('is_charging_arc', False)),
                        "author": collection_info['owner']['name'],
                        "author_id": str(collection_info['owner']['mid']),
                        "section_title": page.get('section_title', ''),
                        "episode_title": page.get('episode_title', ''),
                        "root_bvid": root_bvid,
                        "root_bvid_title": root_bvid_title
                    }
                    
                    videos.append(video_info)

                    # 增量模式：遇到基准视频后立即停止（包含基准本身，便于上层定位锚点）
                    if stop_at_video_id and video_id == stop_at_video_id:
                        break
                    
                    # 进度回调
                    if progress_callback:
                        try:
                            progress = (i + 1) / len(pages) * 100
                            await progress_callback({
                                "type": "page_progress",
                                "message": f"处理第 {i+1}/{len(pages)} 个视频",
                                "current_page": i + 1,
                                "total_pages": len(pages),
                                "count": i + 1
                            })
                        except Exception as callback_error:
                            logger.debug(f"进度回调失败: {str(callback_error)}")
                    
                    # 每处理5个视频让出控制权，防止阻塞
                    if i % 5 == 0:
                        await asyncio.sleep(0.01)
                        
                        # 检查是否超时（最大处理时间5分钟）
                        current_time = asyncio.get_event_loop().time()
                        if current_time - start_time > 300:  # 5分钟
                            logger.warning(f"合集处理超时，已处理 {i+1}/{len(pages)} 个视频")
                            break
                        
                except Exception as e:
                    logger.warning(f"处理第 {page['page']} 个视频失败: {str(e)}")
                    continue
            
            logger.info(f"获取B站合集视频列表成功: {len(videos)} 个视频")
            return videos
            
        except Exception as e:
            logger.error(f"获取B站合集视频列表失败: {str(e)}")
            raise Exception(f"获取合集视频列表失败: {str(e)}")
    
    async def get_collection_videos_queued(self, bvid: str, max_count: int = None, progress_callback=None) -> List[dict]:
        """通过队列获取合集视频列表（对外接口）"""
        async def _get_collection_videos():
            return await self.get_collection_videos(bvid, max_count, progress_callback)
        return await self.enqueue_request(_get_collection_videos)
    
    async def get_collection_videos_incremental(
        self,
        bvid: str,
        latest_page: int = 0,
        latest_video_id: str = None,
        progress_callback=None
    ) -> List[dict]:
        """增量获取合集新增视频"""
        try:
            logger.info(
                f"增量获取B站合集新视频: {bvid}, 最新页码: {latest_page}, "
                f"最新视频ID: {latest_video_id or 'None'}"
            )
            
            # 获取到基准ID前的所有视频（包含基准，用于后续切片）
            all_videos = await self.get_collection_videos(
                bvid,
                progress_callback=progress_callback,
                stop_at_video_id=latest_video_id if latest_video_id else None
            )

            # 优先以 latest_video_id 为锚点做增量（兼容一级/二级列表）
            if latest_video_id:
                matched_index = next(
                    (idx for idx, v in enumerate(all_videos) if v.get('video_id') == latest_video_id),
                    None
                )
                if matched_index is not None:
                    new_videos = all_videos[:matched_index]
                    logger.info(
                        f"按视频ID锚点增量成功: latest_video_id={latest_video_id}, "
                        f"锚点位置={matched_index + 1}/{len(all_videos)}"
                    )
                    logger.info(f"找到 {len(new_videos)} 个新视频")
                    return new_videos
                logger.warning(
                    f"未在当前合集列表中命中 latest_video_id={latest_video_id}，"
                    f"回退到页码增量逻辑"
                )

            # 兼容旧逻辑：当没有可用视频ID锚点时回退页码过滤
            new_videos = [v for v in all_videos if v['page'] > latest_page]
            
            logger.info(f"找到 {len(new_videos)} 个新视频")
            return new_videos
            
        except Exception as e:
            logger.error(f"增量获取合集视频失败: {str(e)}")
            raise Exception(f"增量获取合集视频失败: {str(e)}")
    
    async def get_collection_videos_incremental_queued(
        self,
        bvid: str,
        latest_page: int = 0,
        latest_video_id: str = None,
        progress_callback=None
    ) -> List[dict]:
        """通过队列增量获取合集新视频（对外接口）"""
        async def _get_incremental():
            return await self.get_collection_videos_incremental(
                bvid,
                latest_page=latest_page,
                latest_video_id=latest_video_id,
                progress_callback=progress_callback
            )
        return await self.enqueue_request(_get_incremental)

    async def get_up_videos_queued(self, up_id: str, max_count: int = 5, progress_callback=None) -> List[dict]:
        """通过队列获取UP主视频列表（对外接口）"""
        async def _get_videos():
            return await self.get_up_videos(up_id, max_count, progress_callback)
        return await self.enqueue_request(_get_videos)
    
    async def get_up_videos_incremental(self, up_id: str, latest_video_time=None, progress_callback=None) -> List[dict]:
        """增量获取UP主新视频列表（仅使用API方式）"""
        try:
            logger.info(f"使用API方式增量获取UP主 {up_id} 的新视频列表")
            return await self._get_up_videos_api_incremental(up_id, latest_video_time, progress_callback)
        except Exception as api_error:
            logger.error(f"API方式增量获取失败: {str(api_error)}")
            raise Exception(f"增量获取视频失败: {str(api_error)}")
    
    async def get_up_videos_incremental_queued(self, up_id: str, latest_video_time=None, progress_callback=None) -> List[dict]:
        """通过队列增量获取UP主新视频列表（对外接口）"""
        async def _get_incremental():
            return await self.get_up_videos_incremental(up_id, latest_video_time, progress_callback)
        return await self.enqueue_request(_get_incremental)
    
    async def _get_nth_video(self, index: int) -> dict:
        """已弃用：浏览器解析逻辑移除。"""
        return None
    
    async def _get_accurate_publish_time(self, video_id: str) -> str:
        """已弃用：浏览器解析逻辑移除。"""
        return None

    async def _get_single_page_videos(self, max_count: int, up_id: str = None) -> List[dict]:
        """获取单页视频列表（原有逻辑）"""
        try:
            # 等待页面加载完成
            await self.page.wait_for_selector('a[href*="/video/"]', timeout=10000)
            
            # 获取基础视频信息
            videos_data = await self.page.evaluate(f"""
                () => {{
                    const maxCount = {max_count};
                    const videoItems = document.querySelectorAll('a[href*="/video/"]');
                    const videos = [];
                    const uniqueVideos = new Map();
                    let processedCount = 0;
                    
                    for (let i = 0; i < videoItems.length && processedCount < maxCount; i++) {{
                        try {{
                            const item = videoItems[i];
                            const videoUrl = item.href;
                            
                            // 提取BV号
                            const bvidMatch = videoUrl.match(/\\/video\\/(BV[\\w]+)/);
                            if (!bvidMatch) continue;
                            const bvid = bvidMatch[1];
                            
                            // 检查是否已处理过
                            if (uniqueVideos.has(bvid)) continue;
                            
                            // 获取视频标题
                            let title = '';
                            const titleElement = item.querySelector('img[alt]');
                            if (titleElement && titleElement.alt) {{
                                title = titleElement.alt.trim();
                            }} else {{
                                title = item.textContent.trim();
                            }}
                            
                            // 获取封面URL
                            let coverUrl = '';
                            const imgElement = item.querySelector('img[src]');
                            if (imgElement && imgElement.src) {{
                                coverUrl = imgElement.src;
                            }}
                            
                            // 获取统计信息（播放量、点赞数、时长）
                            let rawText = '';
                            const textElements = item.querySelectorAll('*');
                            for (const el of textElements) {{
                                const text = el.textContent || '';
                                if (text.includes('万') || text.includes(':') || /\\d+/.test(text)) {{
                                    rawText += text + ' ';
                                }}
                            }}
                            
                            // 解析统计信息：格式如 "3.9万6611:48稍后再看"
                            // 播放量（开头的数字+万）
                            let playCount = '0';
                            const playMatch = rawText.match(/^([\\d.]+万?)/);
                            if (playMatch) {{
                                playCount = playMatch[1];
                            }}
                            
                            // 时长（格式如 "11:48"）
                            let duration = '';
                            const durationMatch = rawText.match(/(\\d{{1,2}}:\\d{{2}})/);
                            if (durationMatch) {{
                                duration = durationMatch[1];
                            }}
                            
                            // 发布时间 - 查找视频项下方的日期元素
                            let publishTime = '';
                            
                            // 方法1：查找视频项下方的日期文本（格式如 "08-20"）
                            const videoItemContainer = item.closest('*[class*="video"]') || item.parentElement;
                            if (videoItemContainer) {{
                                // 查找包含日期的元素，通常在视频项下方
                                const dateElements = videoItemContainer.querySelectorAll('*');
                                for (const el of dateElements) {{
                                    const text = el.textContent || '';
                                    // 匹配 MM-DD 格式的日期
                                    const dateMatch = text.match(/^(\\d{{2}}-\\d{{2}})$/);
                                    if (dateMatch) {{
                                        publishTime = dateMatch[1];
                                        break;
                                    }}
                                }}
                            }}
                            
                            // 方法2：如果方法1失败，尝试查找包含日期的兄弟元素
                            if (!publishTime) {{
                                const siblingElements = item.parentElement?.querySelectorAll('*') || [];
                                for (const el of siblingElements) {{
                                    const text = el.textContent || '';
                                    const dateMatch = text.match(/^(\\d{{2}}-\\d{{2}})$/);
                                    if (dateMatch) {{
                                        publishTime = dateMatch[1];
                                        break;
                                    }}
                                }}
                            }}
                            
                            // 方法3：直接查找页面中所有 MM-DD 格式的日期
                            if (!publishTime) {{
                                const allElements = document.querySelectorAll('*');
                                for (const el of allElements) {{
                                    const text = el.textContent || '';
                                    const dateMatch = text.match(/^(\\d{{2}}-\\d{{2}})$/);
                                    if (dateMatch) {{
                                        // 检查这个日期是否在视频项附近
                                        const rect1 = item.getBoundingClientRect();
                                        const rect2 = el.getBoundingClientRect();
                                        const distance = Math.sqrt(
                                            Math.pow(rect1.left - rect2.left, 2) + 
                                            Math.pow(rect1.top - rect2.top, 2)
                                        );
                                        // 如果距离小于200px，认为是这个视频的日期
                                        if (distance < 200) {{
                                            publishTime = dateMatch[1];
                                            break;
                                        }}
                                    }}
                                }}
                            }}
                            
                            const videoData = {{
                                title: title,
                                url: videoUrl.startsWith('//') ? 'https:' + videoUrl : videoUrl,
                                cover_url: coverUrl,
                                duration: duration,
                                play_count: playCount,
                                publish_time: publishTime,
                                bvid: bvid,
                                raw_text: rawText.slice(0, 100) // 调试信息
                            }};
                            
                            uniqueVideos.set(bvid, videoData);
                            videos.push(videoData);
                            processedCount++;
                            
                            // 达到最大数量后停止
                            if (processedCount >= maxCount) {{
                                console.log(`已达到最大数量 ${{maxCount}}，停止处理`);
                                break;
                            }}
                            
                        }} catch (e) {{
                            console.warn('解析视频项失败:', e);
                        }}
                    }}
                    
                    console.log(`解析到 ${{videos.length}} 个唯一视频（限制 ${{maxCount}} 个）`);
                    return videos;
                }}
            """)
            
            # 获取到基础视频列表后，只处理前max_count个视频的详细发布时间
            if videos_data:
                # 限制只处理前max_count个视频
                videos_to_process = videos_data[:max_count]
                logger.debug(f"获取到 {len(videos_data)} 个视频，将处理前 {len(videos_to_process)} 个视频的详细发布时间...")
                
                for i, video in enumerate(videos_to_process):
                    try:
                        # 访问视频详情页获取准确发布时间
                        video_detail_url = f"https://www.bilibili.com/video/{video['bvid']}"
                        logger.info(f"正在获取第 {i+1}/{len(videos_to_process)} 个视频的详细发布时间: {video_detail_url}")
                        
                        await self.page.goto(video_detail_url, wait_until="domcontentloaded", timeout=15000)
                        await asyncio.sleep(1)  # 等待页面加载
                        
                        # 从详情页获取准确发布时间
                        detail_publish_time = await self.page.evaluate("""
                            () => {
                                // 查找包含完整发布时间的元素
                                const timeElements = document.querySelectorAll('*');
                                for (const el of timeElements) {
                                    const text = el.textContent || '';
                                    // 匹配 YYYY-MM-DD HH:MM:SS 格式的完整时间
                                    const fullTimeMatch = text.match(/^(\\d{4}-\\d{1,2}-\\d{1,2}\\s+\\d{1,2}:\\d{2}:\\d{2})$/);
                                    if (fullTimeMatch) {
                                        return fullTimeMatch[1];
                                    }
                                }
                                return '';
                            }
                        """)
                        
                        if detail_publish_time:
                            logger.info(f"获取到准确发布时间: {detail_publish_time}")
                            video['publish_time'] = detail_publish_time
                        else:
                            logger.warning(f"未找到准确发布时间，使用原始时间: {video['publish_time']}")
                        
                    except Exception as e:
                        logger.warning(f"获取视频 {video['bvid']} 详细发布时间失败: {str(e)}")
                        continue
                
                # 返回UP主视频页面，继续后续处理
                await self.page.goto(f"https://space.bilibili.com/{up_id}/upload/video", wait_until="domcontentloaded", timeout=15000)
                await asyncio.sleep(1)
            
            if not videos_data:
                logger.warning("未通过页面解析获取到视频，尝试API方式")
                # 如果页面解析失败，回退到API方式
                return await self._get_up_videos_api(up_id, max_count)
            
            # 处理获取到的视频数据
            processed_videos = []
            for video in videos_data[:max_count]:
                try:
                    # 解析发布时间
                    publish_time_parsed = self._parse_publish_time(video.get('publish_time', ''))
                    
                    # 从URL中提取BV号作为video_id
                    video_id = ''
                    if video.get('url'):
                        bvid_match = re.search(r'/video/(BV[\w]+)', video.get('url'))
                        if bvid_match:
                            video_id = bvid_match.group(1)
                    
                    processed_video = {
                        'video_id': video_id,
                        'title': video.get('title', ''),
                        'url': video.get('url', ''),
                        'cover_url': video.get('cover_url', ''),
                        'publish_time_parsed': publish_time_parsed,
                        'play_count': video.get('play_count', '0'),
                        'duration': video.get('duration', '')
                    }
                    processed_videos.append(processed_video)
                except Exception as e:
                    logger.warning(f"处理视频数据失败: {str(e)}")
                    continue
            
            logger.debug(f"通过浏览器获取到 {len(processed_videos)} 个视频")
            return processed_videos
            
        except Exception as e:
            logger.error(f"获取单页视频失败: {str(e)}")
            raise

    async def _get_all_paginated_videos(self, up_id: str, progress_callback=None) -> List[dict]:
        """分页获取所有视频"""
        try:
            all_videos = []
            current_page = 1
            
            logger.info("开始分页获取所有视频...")
            
            # 如果有进度回调，发送开始状态
            if progress_callback:
                await progress_callback({
                    "type": "page_progress",
                    "status": "starting",
                    "message": "开始分页获取视频...",
                    "current_page": 0,
                    "total_pages": 0,
                    "count": 0
                })
            
            # 首先获取第一页，并尝试获取总页数信息
            first_page_url = f"https://space.bilibili.com/{up_id}/upload/video"
            await self.page.goto(first_page_url, wait_until="domcontentloaded", timeout=15000)
            await asyncio.sleep(2)
            
            # 尝试获取总页数信息和实际视频总数
            total_pages = await self._get_total_pages()
            total_video_count = await self._get_total_video_count()
            
            if total_pages:
                logger.info(f"检测到总页数: {total_pages}")
            else:
                logger.warning("无法获取总页数，将使用智能停止条件")
                
            if total_video_count:
                logger.info(f"检测到页面显示的视频总数: {total_video_count}")
            else:
                logger.warning("无法获取页面显示的视频总数")
            
            # 发送总页数信息
            if progress_callback:
                await progress_callback({
                    "type": "page_progress",
                    "status": "info",
                    "message": f"检测到总页数: {total_pages or '未知'}, 视频总数: {total_video_count or '未知'}",
                    "current_page": 0,
                    "total_pages": total_pages or 0,
                    "count": 0
                })
            
            # 处理第一页
            page_videos = await self._get_current_page_videos()
            if page_videos:
                all_videos.extend(page_videos)
                logger.debug(f"第 1 页获取到 {len(page_videos)} 个视频，总计 {len(all_videos)} 个")
                
                # 发送第一页完成进度
                if progress_callback:
                    await progress_callback({
                        "type": "page_progress",
                        "status": "syncing",
                        "message": f"第 1 页完成，获取到 {len(page_videos)} 个视频",
                        "current_page": 1,
                        "total_pages": total_pages or 0,
                        "count": len(all_videos)
                    })
            
            # 继续处理后续页面
            current_page = 2
            while True:
                # 如果有总页数信息，检查是否超过
                if total_pages and current_page > total_pages:
                    logger.info(f"已达到总页数 {total_pages}，分页完成")
                    break
                
                # 如果有实际视频总数信息，检查是否已经获取足够
                if total_video_count and len(all_videos) >= total_video_count:
                    logger.info(f"已获取到足够的视频数量: {len(all_videos)} >= {total_video_count}，分页完成")
                    break
                
                logger.info(f"正在处理第 {current_page} 页...")
                
                # 发送当前页处理状态
                if progress_callback:
                    await progress_callback({
                        "type": "page_progress",
                        "status": "syncing",
                        "message": f"正在处理第 {current_page} 页...",
                        "current_page": current_page,
                        "total_pages": total_pages or 0,
                        "count": len(all_videos)
                    })
                
                # 修复：使用页面导航而不是URL参数，避免B站API的重复数据问题
                # 点击下一页按钮而不是构建URL
                try:
                    # 查找并点击下一页按钮
                    next_page_clicked = await self.page.evaluate("""
                        () => {
                            const nextBtn = Array.from(document.querySelectorAll('button')).find(btn => 
                                btn.textContent && btn.textContent.includes('下一页')
                            );
                            if (nextBtn && !nextBtn.disabled && nextBtn.offsetParent !== null) {
                                nextBtn.click();
                                return true;
                            }
                            return false;
                        }
                    """)
                    
                    if not next_page_clicked:
                        logger.info("没有下一页按钮，分页完成")
                        break
                    
                    # 等待页面加载
                    await asyncio.sleep(2)
                    
                    # 验证页面是否真的切换了
                    current_page_text = await self.page.evaluate("""
                        () => {
                            const activeButton = Array.from(document.querySelectorAll('button')).find(btn => 
                                btn.classList.contains('active') || 
                                btn.classList.contains('current') ||
                                btn.style.backgroundColor !== ''
                            );
                            return activeButton ? activeButton.textContent.trim() : null;
                        }
                    """)
                    
                    if current_page_text and current_page_text.isdigit():
                        actual_page = int(current_page_text)
                        if actual_page != current_page:
                            logger.warning(f"页面切换异常：期望第{current_page}页，实际第{actual_page}页")
                            # 如果页面切换异常，停止分页
                            break
                    
                except Exception as e:
                    logger.warning(f"点击下一页失败: {str(e)}")
                    break
                
                # 获取当前页面的视频
                page_videos = await self._get_current_page_videos()
                
                if not page_videos:
                    logger.info(f"第 {current_page} 页没有视频，停止分页")
                    break
                
                # 检查是否有重复视频（通过BV号比较）
                new_videos = []
                existing_bvids = {video.get('video_id') for video in all_videos if video.get('video_id')}
                
                for video in page_videos:
                    video_id = video.get('video_id')
                    if video_id and video_id not in existing_bvids:
                        new_videos.append(video)
                        existing_bvids.add(video_id)
                    elif not video_id:
                        # 没有video_id的视频也保留
                        new_videos.append(video)
                
                if not new_videos:
                    logger.info(f"第 {current_page} 页所有视频都是重复的，停止分页")
                    break
                
                # 只添加新的非重复视频
                all_videos.extend(new_videos)
                logger.debug(f"第 {current_page} 页获取到 {len(page_videos)} 个视频，新增 {len(new_videos)} 个，总计 {len(all_videos)} 个")
                
                # 发送当前页完成进度
                if progress_callback:
                    await progress_callback({
                        "type": "page_progress",
                        "status": "syncing",
                        "message": f"第 {current_page} 页完成，新增 {len(new_videos)} 个视频",
                        "current_page": current_page,
                        "total_pages": total_pages or 0,
                        "count": len(all_videos)
                    })
                
                # 如果没有总页数信息，使用智能停止条件
                if not total_pages:
                    # 检查是否还有下一页按钮
                    has_next_page = await self._check_has_next_page()
                    if not has_next_page:
                        logger.info("没有下一页按钮，分页完成")
                        break
                
                current_page += 1
                
                # 防止无限循环（设置合理的最大页数限制）
                if current_page > 10:  # 降低最大页数限制，因为B站通常不会超过10页
                    logger.warning("达到最大页数限制(10)，停止分页")
                    break
            
            logger.info(f"分页获取完成，总共获取到 {len(all_videos)} 个视频")
            
            # 发送分页完成状态
            if progress_callback:
                await progress_callback({
                    "type": "page_progress",
                    "status": "completed",
                    "message": f"分页获取完成，共 {len(all_videos)} 个视频",
                    "current_page": current_page - 1,
                    "total_pages": total_pages or 0,
                    "count": len(all_videos)
                })
            
            # 新增：检查是否有重复视频
            video_ids = [video.get('video_id') for video in all_videos if video.get('video_id')]
            unique_video_ids = set(video_ids)
            if len(video_ids) != len(unique_video_ids):
                logger.warning(f"检测到重复视频！总视频数: {len(video_ids)}, 唯一视频数: {len(unique_video_ids)}")
                # 去重处理
                seen_ids = set()
                unique_videos = []
                for video in all_videos:
                    video_id = video.get('video_id')
                    if video_id and video_id not in seen_ids:
                        seen_ids.add(video_id)
                        unique_videos.append(video)
                    elif not video_id:
                        # 没有video_id的视频也保留
                        unique_videos.append(video)
                
                logger.info(f"去重后视频数量: {len(unique_videos)}")
                all_videos = unique_videos
                
                # 发送去重完成状态
                if progress_callback:
                    await progress_callback({
                        "type": "page_progress",
                        "status": "deduplicating",
                        "message": f"去重完成，最终视频数量: {len(all_videos)}",
                        "current_page": current_page - 1,
                        "total_pages": total_pages or 0,
                        "count": len(all_videos)
                    })
            
            # 新增：获取所有视频的准确发布时间
            logger.info("开始获取所有视频的准确发布时间...")
            logger.info(f"all_videos列表长度: {len(all_videos)}")
            logger.info(f"all_videos前3个元素: {all_videos[:3] if len(all_videos) >= 3 else all_videos}")
            
            # 发送开始获取发布时间状态
            if progress_callback:
                await progress_callback({
                    "type": "time_progress",
                    "status": "starting",
                    "message": "开始获取视频准确发布时间...",
                    "current": 0,
                    "total": len(all_videos)
                })
            
            success_count = 0
            failed_count = 0
            
            for i, video in enumerate(all_videos):
                logger.info(f"开始处理第 {i+1}/{len(all_videos)} 个视频: {video.get('video_id', 'unknown')}")
                
                # 每处理1个视频发送一次进度更新
                if progress_callback:
                    await progress_callback({
                        "type": "time_progress",
                        "status": "syncing",
                        "message": f"正在获取发布时间... ({i + 1}/{len(all_videos)})",
                        "current": i + 1,
                        "total": len(all_videos)
                    })
                
                try:
                    # 获取BV号，优先使用video_id字段，如果没有则尝试从URL中提取
                    bvid = video.get('video_id')
                    if not bvid and video.get('url'):
                        import re
                        bvid_match = re.search(r'/video/(BV[\w]+)', video.get('url'))
                        if bvid_match:
                            bvid = bvid_match.group(1)
                    
                    if bvid:
                        # 访问视频详情页获取准确发布时间
                        video_detail_url = f"https://www.bilibili.com/video/{bvid}"
                        logger.info(f"正在获取第 {i+1}/{len(all_videos)} 个视频的详细发布时间: {video_detail_url}")
                        
                        # 确保浏览器状态正常
                        if not self.page or self.page.is_closed():
                            logger.error("页面已关闭，重新初始化浏览器")
                            await self._ensure_browser()
                        
                        await self.page.goto(video_detail_url, wait_until="domcontentloaded", timeout=15000)
                        await asyncio.sleep(1)  # 等待页面加载
                        
                        # 从详情页获取准确发布时间
                        try:
                            detail_publish_time = await self.page.evaluate("""
                                () => {
                                    // 查找包含完整发布时间的元素
                                    const timeElements = document.querySelectorAll('*');
                                    for (const el of timeElements) {
                                        const text = el.textContent || '';
                                        // 匹配 YYYY-MM-DD HH:MM:SS 格式的完整时间
                                        const fullTimeMatch = text.match(/^(\\d{4}-\\d{1,2}-\\d{1,2}\\s+\\d{1,2}:\\d{2}:\\d{2})$/);
                                        if (fullTimeMatch) {
                                            return fullTimeMatch[1];
                                        }
                                    }
                                    return '';
                                }
                            """)
                            
                            if detail_publish_time:
                                logger.info(f"获取到准确发布时间: {detail_publish_time}")
                                # 更新视频的发布时间字段
                                video['publish_time'] = detail_publish_time
                                # 同时更新publish_time_parsed字段以保持一致性
                                video['publish_time_parsed'] = detail_publish_time
                                success_count += 1
                            else:
                                logger.warning(f"未找到准确发布时间，使用原始时间: {video.get('publish_time_parsed', 'unknown')}")
                                failed_count += 1
                        except Exception as js_error:
                            logger.warning(f"JavaScript执行失败: {str(js_error)}，使用原始时间")
                            failed_count += 1
                        
                        # 每处理10个视频后休息一下，避免过于频繁的请求
                        if (i + 1) % 10 == 0:
                            logger.info(f"已处理 {i + 1}/{len(all_videos)} 个视频，休息2秒...")
                            await asyncio.sleep(2)
                    else:
                        logger.warning(f"视频 {i+1} 没有有效的BV号，跳过")
                        failed_count += 1
                        
                except Exception as e:
                    logger.warning(f"获取视频 {video.get('video_id', 'unknown')} 详细发布时间失败: {str(e)}")
                    failed_count += 1
                    continue
            
            logger.info(f"准确发布时间获取完成: 成功 {success_count} 个，失败 {failed_count} 个")
            
            # 发送发布时间获取完成状态
            if progress_callback:
                await progress_callback({
                    "type": "time_progress",
                    "status": "completed",
                    "message": f"发布时间获取完成: 成功 {success_count} 个，失败 {failed_count} 个",
                    "current": len(all_videos),
                    "total": len(all_videos)
                })
            
            # 返回UP主视频页面，继续后续处理
            try:
                await self.page.goto(f"https://space.bilibili.com/{up_id}/upload/video", wait_until="domcontentloaded", timeout=15000)
                await asyncio.sleep(1)
            except Exception as e:
                logger.warning(f"返回UP主页面失败: {str(e)}")
            
            return all_videos
            
        except Exception as e:
            logger.error(f"分页获取视频失败: {str(e)}")
            raise

    async def _get_current_page_videos(self) -> List[dict]:
        """获取当前页面的视频列表"""
        try:
            # 等待页面加载完成
            await self.page.wait_for_selector('a[href*="/video/"]', timeout=10000)
            
            # 获取当前页面的视频信息
            videos_data = await self.page.evaluate("""
                () => {
                    // 修复：只选择主要的视频卡片链接，避免重复选择
                    // 使用更精确的选择器，只选择包含视频信息的卡片容器
                    const videoCards = document.querySelectorAll('*[class*="video"]');
                    const videos = [];
                    const uniqueVideos = new Map();
                    
                    for (let i = 0; i < videoCards.length; i++) {
                        try {
                            const card = videoCards[i];
                            
                            // 在卡片中查找视频链接
                            const videoLink = card.querySelector('a[href*="/video/"]');
                            if (!videoLink) continue;
                            
                            const videoUrl = videoLink.href;
                            
                            // 提取BV号
                            const bvidMatch = videoUrl.match(/\\/video\\/(BV[\\w]+)/);
                            if (!bvidMatch) continue;
                            const bvid = bvidMatch[1];
                            
                            // 检查是否已处理过
                            if (uniqueVideos.has(bvid)) continue;
                            
                            // 获取视频标题
                            let title = '';
                            const titleElement = card.querySelector('img[alt]');
                            if (titleElement && titleElement.alt) {
                                title = titleElement.alt.trim();
                            } else {
                                // 尝试从链接文本获取标题
                                const linkText = videoLink.textContent.trim();
                                if (linkText) {
                                    title = linkText;
                                }
                            }
                            
                            // 获取封面URL
                            let coverUrl = '';
                            const imgElement = card.querySelector('img[src]');
                            if (imgElement && imgElement.src) {
                                coverUrl = imgElement.src;
                            }
                            
                            // 获取统计信息（播放量、点赞数、时长）
                            let rawText = '';
                            const textElements = card.querySelectorAll('*');
                            for (const el of textElements) {
                                const text = el.textContent || '';
                                if (text.includes('万') || text.includes(':') || /\\d+/.test(text)) {
                                    rawText += text + ' ';
                                }
                            }
                            
                            // 解析统计信息
                            let playCount = '0';
                            const playMatch = rawText.match(/^([\\d.]+万?)/);
                            if (playMatch) {
                                playCount = playMatch[1];
                            }
                            
                            let duration = '';
                            const durationMatch = rawText.match(/(\\d{1,2}:\\d{2})/);
                            if (durationMatch) {
                                duration = durationMatch[1];
                            }
                            
                            // 获取发布时间
                            let publishTime = '';
                            const dateElements = card.querySelectorAll('*');
                            for (const el of dateElements) {
                                const text = el.textContent || '';
                                const dateMatch = text.match(/^(\\d{2}-\\d{2})$/);
                                if (dateMatch) {
                                    publishTime = dateMatch[1];
                                    break;
                                }
                            }
                            
                            const videoData = {
                                title: title,
                                url: videoUrl.startsWith('//') ? 'https:' + videoUrl : videoUrl,
                                cover_url: coverUrl,
                                duration: duration,
                                play_count: playCount,
                                publish_time: publishTime,
                                bvid: bvid
                            };
                            
                            uniqueVideos.set(bvid, videoData);
                            videos.push(videoData);
                            
                        } catch (e) {
                            console.warn('解析视频项失败:', e);
                        }
                    }
                    
                    return videos;
                }
            """)
            
            # 处理视频数据
            processed_videos = []
            for video in videos_data:
                try:
                    # 解析发布时间
                    publish_time_parsed = self._parse_publish_time(video.get('publish_time', ''))
                    
                    # 从URL中提取BV号作为video_id
                    video_id = ''
                    if video.get('url'):
                        bvid_match = re.search(r'/video/(BV[\w]+)', video.get('url'))
                        if bvid_match:
                            video_id = bvid_match.group(1)
                    
                    processed_video = {
                        'video_id': video_id,
                        'title': video.get('title', ''),
                        'url': video.get('url', ''),
                        'cover_url': video.get('cover_url', ''),
                        'publish_time_parsed': publish_time_parsed,
                        'play_count': video.get('play_count', '0'),
                        'duration': video.get('duration', '')
                    }
                    processed_videos.append(processed_video)
                except Exception as e:
                    logger.warning(f"处理视频数据失败: {str(e)}")
                    continue
            
            return processed_videos
            
        except Exception as e:
            logger.error(f"获取当前页面视频失败: {str(e)}")
            return []

    async def _get_total_pages(self) -> Optional[int]:
        """获取总页数"""
        try:
            # 等待页面加载完成
            await self.page.wait_for_selector('button', timeout=5000)
            
            # 尝试从页面文本中提取总页数信息
            total_pages = await self.page.evaluate("""
                () => {
                    // 查找包含"共 X 页 / Y 个"的文本
                    const pageInfoText = Array.from(document.querySelectorAll('*')).find(el => {
                        const text = el.textContent || '';
                        return text.includes('共') && text.includes('页') && text.includes('个');
                    });
                    
                    if (pageInfoText) {
                        const match = pageInfoText.textContent.match(/共\\s*(\\d+)\\s*页/);
                        if (match) {
                            return parseInt(match[1]);
                        }
                    }
                    
                    // 如果没有找到，尝试从页码按钮中获取最大页码
                    const pageButtons = Array.from(document.querySelectorAll('button')).filter(btn => 
                        btn.textContent && /^\\d+$/.test(btn.textContent.trim())
                    );
                    
                    if (pageButtons.length > 0) {
                        const maxPageNum = Math.max(...pageButtons.map(btn => parseInt(btn.textContent.trim())));
                        return maxPageNum;
                    }
                    
                    return null;
                }
            """)
            
            if total_pages:
                logger.info(f"成功获取总页数: {total_pages}")
                return total_pages
            else:
                logger.warning("无法获取总页数")
                return None
                
        except Exception as e:
            logger.warning(f"获取总页数失败: {str(e)}")
            return None

    async def _check_has_next_page(self) -> bool:
        """检查是否有下一页"""
        try:
            # 检查分页导航中是否有"下一页"按钮且可点击
            has_next = await self.page.evaluate("""
                () => {
                    const nextBtn = Array.from(document.querySelectorAll('button')).find(btn => 
                        btn.textContent && btn.textContent.includes('下一页')
                    );
                    return nextBtn && !nextBtn.disabled && nextBtn.offsetParent !== null;
                }
            """)
            
            if has_next:
                logger.info("检测到下一页按钮")
                return True
            
            # 检查是否有更多页码按钮
            has_more_pages = await self.page.evaluate("""
                () => {
                    const pageButtons = Array.from(document.querySelectorAll('button')).filter(btn => 
                        btn.textContent && /^\\d+$/.test(btn.textContent.trim())
                    );
                    const currentPage = pageButtons.find(btn => 
                        btn.classList.contains('active') || 
                        btn.classList.contains('current') ||
                        btn.style.backgroundColor !== ''
                    );
                    
                    if (currentPage) {
                        const currentPageNum = parseInt(currentPage.textContent.trim());
                        const maxPageNum = Math.max(...pageButtons.map(btn => parseInt(btn.textContent.trim())));
                        return currentPageNum < maxPageNum;
                    }
                    
                    return false;
                }
            """)
            
            return has_more_pages
            
        except Exception as e:
            logger.warning(f"检查下一页失败: {str(e)}")
            return False
    
    def _parse_publish_time(self, time_text: str) -> str:
        """解析B站发布时间文本"""
        try:
            if not time_text:
                return datetime.now().isoformat()
                
            now = datetime.now()
            
            # 处理"刚刚"
            if "刚刚" in time_text:
                return now.isoformat()
                
            # 处理"x分钟前"
            minutes_match = re.match(r"(\d+)\s*分钟前", time_text)
            if minutes_match:
                minutes = int(minutes_match.group(1))
                return (now - timedelta(minutes=minutes)).isoformat()
                
            # 处理"x小时前"
            hours_match = re.match(r"(\d+)\s*小时前", time_text)
            if hours_match:
                hours = int(hours_match.group(1))
                return (now - timedelta(hours=hours)).isoformat()
                
            # 处理"昨天"
            if "昨天" in time_text:
                yesterday = now - timedelta(days=1)
                return yesterday.isoformat()
                
            # 处理"x天前"
            days_match = re.match(r"(\d+)\s*天前", time_text)
            if days_match:
                days = int(days_match.group(1))
                return (now - timedelta(days=days)).isoformat()
                
            # 处理B站特有的 MM-DD 格式（如 "08-20"）
            date_match = re.match(r"(\d{1,2})-(\d{1,2})", time_text)
            if date_match:
                month, day = map(int, date_match.groups())
                
                # 智能判断年份：
                # 1. 如果月份大于当前月份，肯定是去年的
                # 2. 如果月份等于当前月份，且日期大于当前日期，也是去年的
                # 3. 如果月份小于等于当前月份，且日期小于等于当前日期，是今年的
                # 4. 如果月份小于当前月份，且日期大于当前日期，需要进一步判断
                year = now.year
                
                if month > now.month:
                    # 月份大于当前月份，肯定是去年的
                    year = year - 1
                elif month == now.month and day > now.day:
                    # 同月但日期大于今天，是去年的
                    year = year - 1
                elif month < now.month:
                    # 月份小于当前月份，可能是去年的
                    # 这里需要更智能的判断：如果月份差距很大（比如现在是8月，看到1月），很可能是去年的
                    if now.month - month > 6:
                        year = year - 1
                
                try:
                    return datetime(year, month, day).isoformat()
                except ValueError:
                    # 如果日期无效（如2月30日），返回当前时间
                    logger.warning(f"无效的日期: {month}-{day}")
                    return now.isoformat()
                
            # 处理完整时间格式 "2025-08-20 20:00:00"
            full_time_match = re.match(r"(\d{4})-(\d{1,2})-(\d{1,2})\s+(\d{1,2}):(\d{1,2}):(\d{1,2})", time_text)
            if full_time_match:
                year, month, day, hour, minute, second = map(int, full_time_match.groups())
                return datetime(year, month, day, hour, minute, second).isoformat()
                
            # 处理具体日期 "2023-12-29"
            date_match = re.match(r"(\d{4})-(\d{1,2})-(\d{1,2})", time_text)
            if date_match:
                year, month, day = map(int, date_match.groups())
                return datetime(year, month, day).isoformat()
                
            # 如果无法解析，返回当前时间
            logger.warning(f"无法解析的时间格式: {time_text}")
            return now.isoformat()
            
        except Exception as e:
            logger.error(f"解析发布时间失败: {time_text} - {str(e)}")
            return datetime.now().isoformat()

    async def _get_total_video_count(self) -> Optional[int]:
        """获取页面显示的实际视频总数"""
        try:
            # 等待页面加载完成
            await self.page.wait_for_selector('*', timeout=5000)
            
            # 从页面文本中提取总视频数
            total_count = await self.page.evaluate("""
                () => {
                    // 查找包含"共 X 页 / Y 个"的文本
                    const pageInfoText = Array.from(document.querySelectorAll('*')).find(el => {
                        const text = el.textContent || '';
                        return text.includes('共') && text.includes('页') && text.includes('个');
                    });
                    
                    if (pageInfoText) {
                        const match = pageInfoText.textContent.match(/共\\s*\\d+\\s*页\\s*\\/\\s*(\\d+)\\s*个/);
                        if (match) {
                            return parseInt(match[1]);
                        }
                    }
                    
                    // 如果没有找到，尝试从其他位置获取
                    const allText = document.body.textContent || '';
                    const videoCountMatch = allText.match(/(\\d+)\\s*个视频/);
                    if (videoCountMatch) {
                        return parseInt(videoCountMatch[1]);
                    }
                    
                    return null;
                }
            """)
            
            if total_count:
                logger.info(f"成功获取页面显示的视频总数: {total_count}")
                return total_count
            else:
                logger.warning("无法获取页面显示的视频总数")
                return None
                
        except Exception as e:
            logger.warning(f"获取页面显示的视频总数失败: {str(e)}")
            return None

    async def start_worker(self):
        """启动后台工作任务处理队列中的请求"""
        if self._worker_task is None or self._worker_task.done():
            self._worker_task = asyncio.create_task(self._process_queue())
            logger.info("B站请求队列处理任务已启动")
        else:
            logger.debug("B站请求队列处理任务已在运行")
            
    async def stop_worker(self):
        """停止后台工作任务"""
        if self._worker_task:
            logger.info("正在停止B站请求队列处理任务...")
            self._worker_task.cancel()
            try:
                await self._worker_task
            except asyncio.CancelledError:
                pass
            self._worker_task = None
            logger.info("B站请求队列处理任务已停止")
        else:
            logger.info("B站请求队列处理任务未在运行")
            
    async def _process_queue(self):
        """处理请求队列的后台任务"""
        logger.debug("B站请求队列处理任务开始运行")
        while True:
            try:
                # 获取队列中的请求
                logger.debug("等待B站请求队列中的请求...")
                request_func, future = await self._request_queue.get()
                logger.debug("收到B站请求，开始处理...")
                
                try:
                    # 使用信号量控制并发，最多10个并发请求
                    async with self._request_semaphore:
                        # 确保浏览器已初始化
                        if not self.page:
                            logger.info("B站浏览器未初始化，正在初始化...")
                            success = await self.init_browser()
                            if not success:
                                raise Exception("浏览器初始化失败")
                            logger.info("B站浏览器初始化完成")
                                
                        # 执行请求
                        logger.debug("执行B站请求...")
                        result = await request_func()
                        future.set_result(result)
                        logger.debug("B站请求执行完成")
                        
                except Exception as e:
                    future.set_exception(e)
                    logger.error(f"B站处理请求失败: {str(e)}")
                    
                finally:
                    self._request_queue.task_done()
                    logger.debug("B站请求队列任务标记为完成")
                    
            except asyncio.CancelledError:
                logger.info("B站请求队列处理任务被取消")
                break
            except Exception as e:
                logger.error(f"B站处理请求队列时出错: {str(e)}")
                continue
                
    async def enqueue_request(self, request_func):
        """将请求添加到队列并更新活动时间"""
        logger.debug("B站请求开始，更新活动时间...")
        await self._update_activity()  # 请求开始时更新
        try:
            future = asyncio.Future()
            # 移除重复的worker启动，避免重复创建进程
            logger.debug("将B站请求添加到队列...")
            await self._request_queue.put((request_func, future))
            logger.debug("等待B站请求执行结果...")
            result = await future
            logger.debug("B站请求执行成功，更新活动时间...")
            await self._update_activity()  # 请求成功时更新
            return result
        except Exception as e:
            logger.error(f"B站请求执行失败，更新活动时间: {str(e)}")
            await self._update_activity()  # 请求失败时也更新
            raise e

    async def _monitor_playwright_processes(self):
        """监控Playwright进程数量，防止进程泄漏"""
        while True:
            try:
                await asyncio.sleep(300)  # 每5分钟检查一次
                # 使用统一管理器获取状态（保持向后兼容）
                status = bilibili_playwright_manager.get_status()
                if status["current_count"] > status["max_instances"]:
                    logger.warning(f"检测到Playwright进程数量异常: {status['current_count']} > {status['max_instances']}")
                    # 强制清理多余的进程
                    if self._playwright:
                        await self._playwright.stop()
                        self._playwright = None
                    # 释放实例
                    if hasattr(self, '_instance_id') and self._instance_id:
                        await bilibili_playwright_manager.release_instance(self._instance_id)
                        self._instance_id = None
                    logger.info("已强制清理多余的Playwright进程")
            except Exception as e:
                logger.error(f"监控Playwright进程时出错: {str(e)}")
            except asyncio.CancelledError:
                logger.info("Playwright进程监控任务被取消")
                break

# 创建B站API实例
bilibili_api = BilibiliAPI()

@router.on_event("startup")
async def startup_event():
    """FastAPI启动时初始化B站API"""
    logger.info("B站API启动")
    try:
        # 🟢 浏览器采用懒加载，worker已在main.py中启动
        # 统一浏览器管理器会自动管理清理任务
        logger.info("B站API初始化完成（浏览器采用懒加载，统一管理）")
    except Exception as e:
        logger.error(f"B站API启动失败: {str(e)}")
        raise

@router.on_event("shutdown")
async def shutdown_event():
    """FastAPI关闭时清理B站API"""
    logger.info("B站API关闭")
    try:
        # 🟢 停止工作线程
        await bilibili_api.stop_worker()
        await bilibili_api.close_browser()
        logger.info("B站API清理完成")
    except Exception as e:
        logger.error(f"B站API关闭失败: {str(e)}")

@router.post("/parse_up")
async def parse_bilibili_url(url: str, current_user: User = Depends(get_current_user)):
    """解析B站链接（支持UP主链接和视频合集链接）"""
    try:
        result = await bilibili_api.parse_url(url)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/up_videos/{up_id}")
async def get_up_videos(up_id: str, max_count: int = Query(default=5, description="获取视频数量，默认5个"), current_user: User = Depends(get_current_user)):
    """获取UP主的视频列表（首次订阅建议5个，后续可增加）"""
    try:
        videos = await bilibili_api.get_up_videos(up_id, max_count)
        return {"videos": videos}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/collection_videos/{bvid}")
async def get_collection_videos(bvid: str, max_count: int = Query(default=None, description="获取视频数量，默认获取全部"), current_user: User = Depends(get_current_user)):
    """获取B站合集的视频列表"""
    try:
        videos = await bilibili_api.get_collection_videos_queued(bvid, max_count)
        return {"videos": videos}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/health_check")
async def browser_health_check():
    """检查浏览器健康状态"""
    try:
        if bilibili_api.page:
            # 简单测试页面是否可用
            await bilibili_api.page.evaluate("1")
            return {"status": "healthy", "message": "B站浏览器状态正常"}
        else:
            return {"status": "unhealthy", "message": "B站浏览器未初始化"}
    except Exception as e:
        return {"status": "unhealthy", "message": f"B站浏览器状态异常: {str(e)}"}

@router.post("/close")
@require_license_api
async def close_browser():
    """关闭B站浏览器（用于登录窗口关闭）"""
    logger.info("B站关闭浏览器请求收到")
    await bilibili_api.close_browser()
    return {"message": "浏览器已关闭"}

@router.post("/force_reinit")
async def force_reinitialize_browser(current_user: User = Depends(get_current_user)):
    """强制重新初始化B站浏览器"""
    try:
        await bilibili_api.close_browser()
        success = await bilibili_api.init_browser()
        if success:
            return {"message": "B站浏览器重新初始化成功"}
        else:
            raise Exception("浏览器重新初始化失败")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"重新初始化失败: {str(e)}")

@router.post("/login")
async def init_login(current_user: User = Depends(get_current_user)):
    """启动B站登录流程"""
    logger.info("B站登录流程启动")
    try:
        result = await bilibili_api.login()
        # 检查是否是用户取消登录
        if result.get("cancelled"):
            logger.info("B站登录已被用户取消")
            return result  # 返回200状态码，表示正常操作
        logger.info("B站登录流程启动成功")
        return result
    except Exception as e:
        logger.error(f"B站登录流程启动失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"启动登录失败: {str(e)}")

@router.post("/close")
async def close_browser(current_user: User = Depends(get_current_user)):
    """关闭B站浏览器"""
    logger.info("B站关闭浏览器")
    try:
        await bilibili_api.close_browser()
        logger.info("B站浏览器关闭成功")
        return {"message": "浏览器已关闭"}
    except Exception as e:
        logger.error(f"B站浏览器关闭失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"关闭浏览器失败: {str(e)}")

@router.post("/clean")
async def clean_browser(current_user: User = Depends(get_current_user)):
    """清理B站浏览器文件"""
    try:
        logger.info("B站清理浏览器")
        result = await bilibili_api.clean_browser()
        logger.info("B站浏览器清理成功")
        return result
    except Exception as e:
        logger.error(f"B站浏览器清理失败: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

# 🟢 新增队列操作接口
@router.get("/up_info/{up_id}")
async def get_up_info_queued(up_id: str, current_user: User = Depends(get_current_user)):
    """通过队列获取UP主信息"""
    try:
        result = await bilibili_api.fetch_up_info(up_id)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/up_videos_queued/{up_id}")
async def get_up_videos_queued(up_id: str, max_count: int = Query(default=5, description="获取视频数量，默认5个"), current_user: User = Depends(get_current_user)):
    """通过队列获取UP主的视频列表"""
    try:
        videos = await bilibili_api.get_up_videos_queued(up_id, max_count)
        return {"videos": videos}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/up_videos_incremental_queued/{up_id}")
async def get_up_videos_incremental_queued(
    up_id: str, 
    latest_video_time: Optional[str] = Query(default=None, description="最新视频时间"),
    current_user: User = Depends(get_current_user)
):
    """通过队列增量获取UP主新视频列表"""
    try:
        # 解析时间参数
        parsed_time = None
        if latest_video_time:
            try:
                parsed_time = datetime.fromisoformat(latest_video_time)
            except ValueError:
                raise HTTPException(status_code=400, detail="时间格式错误，请使用ISO格式")
        
        videos = await bilibili_api.get_up_videos_incremental_queued(up_id, parsed_time)
        return {"videos": videos}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/queue_status")
async def get_queue_status(current_user: User = Depends(get_current_user)):
    """获取队列状态信息"""
    try:
        status = {
            "queue_size": bilibili_api._request_queue.qsize(),
            "worker_running": bilibili_api._worker_task is not None,
            "cleanup_running": bilibili_api._cleanup_task is not None,
            "browser_healthy": await bilibili_api._is_browser_healthy() if bilibili_api.context else False,
            "last_activity": bilibili_api._last_activity,
            "max_concurrent": bilibili_api._max_concurrent_requests
        }
        return status
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# ============================================================================
# B站收藏夹订阅相关函数
# ============================================================================

def parse_bilibili_favorite_url(url: str) -> dict:
    """
    解析B站收藏夹URL，提取收藏夹ID
    
    支持的URL格式：
    1. https://www.bilibili.com/medialist/play/ml473071500
    2. https://space.bilibili.com/416291500/favlist?fid=473071500&ftype=create
    3. https://space.bilibili.com/416291500/favlist?fid=473071500
    4. 直接提供收藏夹ID：473071500
    
    Args:
        url: 收藏夹URL或ID
        
    Returns:
        dict: 包含fav_id和fav_url的字典
    """
    import re
    
    logger.debug(f"解析B站收藏夹URL: {url}")
    
    # 如果直接是纯数字，认为是收藏夹ID
    if url.isdigit():
        fav_id = url
        fav_url = f"https://www.bilibili.com/medialist/play/ml{fav_id}"
        logger.debug(f"识别为纯数字ID，收藏夹ID: {fav_id}")
        return {
            "fav_id": fav_id,
            "fav_url": fav_url
        }
    
    # 格式1: https://www.bilibili.com/medialist/play/ml473071500
    match = re.search(r'medialist/play/ml(\d+)', url)
    if match:
        fav_id = match.group(1)
        fav_url = f"https://www.bilibili.com/medialist/play/ml{fav_id}"
        logger.debug(f"匹配格式1 (medialist/play/ml)，收藏夹ID: {fav_id}")
        return {
            "fav_id": fav_id,
            "fav_url": fav_url
        }
    
    # 格式2和3: https://space.bilibili.com/.../favlist?fid=473071500
    # 优先匹配 fid= 参数，这是最准确的收藏夹ID
    match = re.search(r'[?&]fid=(\d+)', url)
    if match:
        fav_id = match.group(1)
        fav_url = f"https://www.bilibili.com/medialist/play/ml{fav_id}"
        logger.debug(f"匹配格式2/3 (fid参数)，收藏夹ID: {fav_id}")
        return {
            "fav_id": fav_id,
            "fav_url": fav_url
        }
    
    # 如果都无法匹配，尝试从URL中提取可能的数字ID（最后的手段，可能不准确）
    match = re.search(r'/(\d+)(?:[/?]|$)', url)
    if match:
        fav_id = match.group(1)
        fav_url = f"https://www.bilibili.com/medialist/play/ml{fav_id}"
        logger.warning(f"使用fallback模式提取ID，可能是用户ID而非收藏夹ID: {fav_id}，原始URL: {url}")
        return {
            "fav_id": fav_id,
            "fav_url": fav_url
        }
    
    raise ValueError(f"无法从URL中提取收藏夹ID，请确保URL包含收藏夹ID（fid参数）或使用正确的格式: {url}")

async def get_bilibili_favorite_info(fav_id: str, cookies_path: str = None) -> dict:
    """
    使用yt-dlp获取B站收藏夹基本信息
    
    Args:
        fav_id: 收藏夹ID
        cookies_path: cookies文件路径，默认为None（使用默认路径）
        
    Returns:
        dict: 包含收藏夹基本信息的字典
    """
    import yt_dlp
    import os
    from concurrent.futures import ThreadPoolExecutor
    
    fav_url = f"https://www.bilibili.com/medialist/play/ml{fav_id}"
    
    # 确定cookies文件路径
    if cookies_path is None:
        cookies_path = "/app/database/cookie/bilibili_cookie.txt"
    
    # 配置yt-dlp选项
    ydl_opts = {
        "quiet": True,
        "no_warnings": True,
        "extract_flat": True,  # 只获取列表，不获取详细信息，快速
        "socket_timeout": 30,
        "retries": 3,
    }
    
    # 如果cookies文件存在，使用cookies
    if cookies_path and os.path.exists(cookies_path):
        ydl_opts["cookiefile"] = cookies_path
        logger.debug(f"使用B站cookies文件: {cookies_path}")
    
    def _extract_info():
        """同步执行yt-dlp信息提取"""
        try:
            logger.debug(f"使用yt-dlp提取收藏夹信息，URL: {fav_url}, 收藏夹ID: {fav_id}")
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(fav_url, download=False)
                logger.debug(f"yt-dlp提取成功，标题: {info.get('title', '未知')}, 视频数: {len(info.get('entries', []))}")
                return info
        except yt_dlp.utils.DownloadError as e:
            error_msg = str(e)
            # 检查是否是访问权限问题
            if "Could not access playlist" in error_msg or "播单数据为空" in error_msg:
                logger.error(f"无法访问收藏夹 {fav_id}，可能是私有收藏夹或需要登录。错误: {error_msg}")
                raise ValueError(f"无法访问收藏夹（ID: {fav_id}）。可能是：1) 收藏夹是私有的，2) Cookie权限不足，3) 收藏夹不存在或已被删除。请检查Cookie是否有效，以及收藏夹是否为公开状态。")
            raise ValueError(f"yt-dlp提取失败: {error_msg}")
        except Exception as e:
            logger.error(f"yt-dlp提取收藏夹信息时发生未知错误: {str(e)}")
            raise ValueError(f"yt-dlp提取失败: {str(e)}")
    
    try:
        # 使用线程池异步执行yt-dlp
        loop = asyncio.get_event_loop()
        info = await loop.run_in_executor(None, _extract_info)
        
        if not info:
            raise ValueError("无法获取收藏夹信息，收藏夹可能不存在或无法访问")
        
        # 提取收藏夹信息
        fav_title = info.get('title', f'收藏夹_{fav_id}')
        entries = info.get('entries', [])
        video_count = len(entries) if entries else 0
        
        # 尝试从第一个视频获取封面作为收藏夹头像
        avatar_url = ""
        if entries and len(entries) > 0:
            first_entry = entries[0]
            if first_entry:
                # extract_flat=True时，可能没有thumbnail，先尝试从当前结果获取
                avatar_url = first_entry.get('thumbnail', '') or ''
                if isinstance(first_entry.get('thumbnails'), list) and first_entry.get('thumbnails'):
                    avatar_url = avatar_url or first_entry.get('thumbnails', [{}])[0].get('url', '')
                
                # 如果没有缩略图，尝试获取第一个视频的详细信息
                if not avatar_url:
                    try:
                        # 获取第一个视频的ID或URL
                        first_video_id = first_entry.get('id', '') or first_entry.get('url', '') or first_entry.get('webpage_url', '')
                        if first_video_id:
                            # 构建完整URL（如果是BV号或相对路径）
                            if isinstance(first_video_id, str):
                                if first_video_id.startswith('BV'):
                                    first_video_url = f"https://www.bilibili.com/video/{first_video_id}"
                                elif first_video_id.startswith('http'):
                                    first_video_url = first_video_id
                                elif first_video_id.startswith('/'):
                                    first_video_url = f"https://www.bilibili.com{first_video_id}"
                                else:
                                    first_video_url = f"https://www.bilibili.com/video/{first_video_id}"
                                
                                # 使用非extract_flat模式获取第一个视频的详细信息
                                detailed_opts = ydl_opts.copy()
                                detailed_opts["extract_flat"] = False
                                
                                with yt_dlp.YoutubeDL(detailed_opts) as ydl:
                                    video_info = ydl.extract_info(first_video_url, download=False)
                                    if video_info:
                                        avatar_url = video_info.get('thumbnail', '')
                                        if not avatar_url and isinstance(video_info.get('thumbnails'), list) and video_info.get('thumbnails'):
                                            avatar_url = video_info.get('thumbnails', [{}])[0].get('url', '')
                    except Exception as e:
                        logger.debug(f"获取第一个视频封面失败，将使用空头像: {str(e)}")
        
        logger.info(f"成功获取收藏夹信息: {fav_title} (ID: {fav_id}, 视频数: {video_count}, 头像: {'有' if avatar_url else '无'})")
        
        return {
            "success": True,
            "fav_id": fav_id,
            "fav_url": fav_url,
            "title": fav_title,
            "video_count": video_count,
            "avatar_url": avatar_url,  # 第一个视频的封面作为头像
            "entries": entries  # 包含视频列表（简化信息）
        }
    except ValueError as ve:
        # 重新抛出ValueError，保持错误信息
        raise ve
    except Exception as e:
        logger.error(f"获取B站收藏夹信息失败 (收藏夹ID: {fav_id}): {str(e)}")
        raise ValueError(f"获取收藏夹信息失败: {str(e)}")

async def get_bilibili_favorite_videos(
    fav_id: str,
    cookies_path: str = None,
    extract_flat: bool = False,
    max_count: int = None,
    progress_callback: Optional[Callable[[Dict[str, Any]], Awaitable[None]]] = None
) -> list:
    """
    使用yt-dlp获取B站收藏夹视频列表
    
    Args:
        fav_id: 收藏夹ID
        cookies_path: cookies文件路径，默认为None（使用默认路径）
        extract_flat: 是否只获取列表信息（True=快速，只获取ID和URL；False=获取详细信息）
        max_count: 最大获取数量，None表示获取全部
        progress_callback: 分页抓取进度回调（可选）
        
    Returns:
        list: 视频列表
    """
    import yt_dlp
    import os
    
    fav_url = f"https://www.bilibili.com/medialist/play/ml{fav_id}"
    
    # 确定cookies文件路径
    if cookies_path is None:
        cookies_path = "/app/database/cookie/bilibili_cookie.txt"
    
    # 配置yt-dlp基础选项
    ydl_opts_base = {
        "quiet": True,
        "no_warnings": True,
        "extract_flat": extract_flat,
        "socket_timeout": 30,
        "retries": 3,
    }
    
    # 如果cookies文件存在，使用cookies
    if cookies_path and os.path.exists(cookies_path):
        ydl_opts_base["cookiefile"] = cookies_path
    
    def _entry_to_video(entry: dict) -> dict:
        """将yt-dlp entry转换为统一视频结构"""
        if not entry:
            return {}
        video = {
            "video_id": entry.get("id", ""),  # BV号
            "title": entry.get("title") or entry.get("fulltitle", ""),
            "url": entry.get("webpage_url") or entry.get("url", ""),
            "cover_url": entry.get("thumbnail", ""),
        }
        if not extract_flat:
            upload_date = entry.get("upload_date", "")
            if upload_date:
                try:
                    if len(upload_date) == 8:
                        formatted_date = f"{upload_date[:4]}-{upload_date[4:6]}-{upload_date[6:8]}"
                        from datetime import datetime
                        video["publish_time"] = datetime.strptime(formatted_date, "%Y-%m-%d").isoformat() + "+00:00"
                    else:
                        video["publish_time"] = upload_date
                except Exception:
                    video["publish_time"] = upload_date
            else:
                video["publish_time"] = ""
            video["duration"] = entry.get("duration", 0)
            video["uploader"] = entry.get("uploader", "")
            video["uploader_id"] = entry.get("uploader_id", "")
        else:
            video["publish_time"] = ""
            video["duration"] = 0
            video["uploader"] = ""
            video["uploader_id"] = ""
        return video
    
    def _extract_info(ydl_opts: dict):
        """同步执行yt-dlp信息提取"""
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                return ydl.extract_info(fav_url, download=False)
        except Exception as e:
            raise ValueError(f"yt-dlp提取失败: {str(e)}")

    async def _extract_info_with_retry(
        ydl_opts: dict,
        page_desc: str,
        max_attempts: int = 3,
        fatal: bool = False,
    ):
        last_error = None
        for attempt in range(1, max_attempts + 1):
            try:
                return await asyncio.to_thread(_extract_info, ydl_opts)
            except Exception as e:
                last_error = e
                if attempt < max_attempts:
                    wait_seconds = min(2 ** (attempt - 1), 5)
                    logger.warning(
                        f"B站收藏夹抓取失败，准备重试: fav_id={fav_id}, {page_desc}, "
                        f"attempt={attempt}/{max_attempts}, wait={wait_seconds}s, error={str(e)}"
                    )
                    await asyncio.sleep(wait_seconds)
                else:
                    logger.error(
                        f"B站收藏夹抓取重试耗尽: fav_id={fav_id}, {page_desc}, "
                        f"attempt={attempt}/{max_attempts}, error={str(e)}"
                    )

        if fatal:
            raise ValueError(f"B站收藏夹抓取失败({page_desc}): {str(last_error)}")
        return None
    
    try:
        # 有数量限制时沿用一次性提取，减少请求次数
        if max_count is not None and max_count > 0:
            opts = dict(ydl_opts_base)
            opts["playlistend"] = max_count
            info = await _extract_info_with_retry(opts, "one-shot", max_attempts=3, fatal=True)
            if not info:
                return []
            entries = info.get("entries", [])
            return [_entry_to_video(entry) for entry in entries if entry]
        
        # 无数量限制时使用分页提取，避免大收藏夹被单次提取截断
        page_size = 100
        start = 1
        videos = []
        seen_ids = set()
        expected_total = None
        consecutive_empty_pages = 0
        max_empty_pages = 2
        page_fetch_failed = False
        
        while True:
            end = start + page_size - 1
            page_opts = dict(ydl_opts_base)
            page_opts["playlist_items"] = f"{start}-{end}"
            page_desc = f"区间={start}-{end}"
            info = await _extract_info_with_retry(page_opts, page_desc, max_attempts=3, fatal=False)
            if not info:
                page_fetch_failed = True
                if not videos:
                    raise ValueError(f"B站收藏夹分页抓取失败且无可用结果: fav_id={fav_id}, {page_desc}")
                logger.warning(
                    f"B站收藏夹分页抓取中断，返回已获取结果: fav_id={fav_id}, {page_desc}, 已获取={len(videos)}"
                )
                break
            
            if expected_total is None:
                expected_total = info.get("playlist_count")
                logger.info(f"B站收藏夹分页抓取开始: fav_id={fav_id}, 预估总数={expected_total or '未知'}, 每页={page_size}")
            
            entries = info.get("entries", []) or []
            page_new = 0
            for entry in entries:
                if not entry:
                    continue
                vid = entry.get("id") or ""
                if not vid or vid in seen_ids:
                    continue
                seen_ids.add(vid)
                videos.append(_entry_to_video(entry))
                page_new += 1
            
            if page_new == 0:
                consecutive_empty_pages += 1
            else:
                consecutive_empty_pages = 0
            
            logger.info(f"B站收藏夹分页抓取: fav_id={fav_id}, 区间={start}-{end}, 本页新增={page_new}, 累计={len(videos)}")

            if page_new > 0 and progress_callback:
                try:
                    await progress_callback({
                        "type": "sync_progress",
                        "status": "syncing",
                        "message": f"正在获取B站收藏夹视频列表... 已获取 {len(videos)} 条",
                        "count": len(videos)
                    })
                except Exception as e:
                    logger.debug(f"B站收藏夹分页进度回调失败: {str(e)}")
            
            # 终止条件：连续空页、达到预估总数、最后一页不足page_size
            if consecutive_empty_pages >= max_empty_pages:
                break
            if expected_total and len(videos) >= int(expected_total):
                break
            if len(entries) < page_size:
                break
            
            start += page_size
        
        if page_fetch_failed:
            logger.warning(f"B站收藏夹分页抓取因请求失败提前结束: fav_id={fav_id}, 当前累计={len(videos)}")
        elif expected_total and len(videos) < int(expected_total):
            logger.warning(
                f"B站收藏夹分页抓取可能不完整: fav_id={fav_id}, 预估={expected_total}, 实际={len(videos)}"
            )
        else:
            logger.info(f"B站收藏夹分页抓取完成: fav_id={fav_id}, 共{len(videos)}条")
        
        return videos
    except Exception as e:
        logger.error(f"获取B站收藏夹视频列表失败: {str(e)}")
        raise ValueError(f"获取收藏夹视频列表失败: {str(e)}")
