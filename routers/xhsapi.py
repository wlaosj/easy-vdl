import os
import shutil
import asyncio
import json
import logging
import random
import re
import httpx
from urllib.parse import urlparse, parse_qs
from typing import List, Optional, Dict, Any
from datetime import datetime, timedelta
from fastapi import APIRouter, HTTPException, Depends
from routers.unified_browser_manager import unified_browser
from routers.auth import require_license_api
from .api_params_cache import api_params_cache

# 配置日志
logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/subscribe/xiaohongshu",
    tags=["xiaohongshu"],
    responses={404: {"description": "Not found"}}
)

class XiaohongshuAPI:
    def __init__(self):
        # 使用统一浏览器管理器
        self._browser = unified_browser
        self._platform = "xiaohongshu"
        # 请求队列管理（保留特有逻辑）
        self._request_queue = asyncio.Queue()
        self._worker_task = None
        self._max_concurrent_requests = 1  # 小红书单标签页签名模式，强制单并发
        self._request_semaphore = asyncio.Semaphore(self._max_concurrent_requests)
        self._lock = asyncio.Lock()  # 全局操作锁，保护单一 Page 实例
        self._last_user_info_error = ""

    @property
    def last_user_info_error(self) -> str:
        return self._last_user_info_error

    def _parse_count(self, value: Any) -> int:
        """解析小红书计数字符串，兼容 10+ / 1千+ / 1.2万+ / 3k 等格式。"""
        if value is None:
            return 0
        if isinstance(value, (int, float)):
            return int(value)

        s = str(value).strip().replace(",", "")
        if not s:
            return 0
        if s.endswith("+"):
            s = s[:-1].strip()
        if not s:
            return 0

        match = re.match(r"^(\d+(?:\.\d+)?)([万千kKwW]?)$", s)
        if match:
            num = float(match.group(1))
            unit = match.group(2)
            multiplier = {
                "": 1,
                "千": 1000,
                "万": 10000,
                "k": 1000,
                "K": 1000,
                "w": 10000,
                "W": 10000,
            }.get(unit, 1)
            return int(num * multiplier)

        # 兜底：提取数字部分，避免因异常格式导致整个订阅失败
        digits = re.findall(r"\d+(?:\.\d+)?", s)
        if digits:
            try:
                return int(float(digits[0]))
            except Exception:
                return 0
        return 0

    @property
    def page(self):
        """获取当前页面"""
        return self._browser._pages.get(self._platform)
    
    @property
    def context(self):
        """获取浏览器上下文"""
        return self._browser.context

    async def init_browser(self):
        """初始化浏览器（使用统一浏览器管理器）"""
        try:
            # 获取或创建小红书的标签页
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

    async def _ensure_page_ready(self):
        """确保页面可用"""
        if not self.page or self.page.is_closed():
            success = await self.init_browser()
            if not success:
               raise Exception("浏览器初始化失败")
        
        try:
            # 检查当前URL，如果不是小红书域名，则跳转
            # 注意：小红书某些页面可能跳转到验证码页，需要处理
            if "xiaohongshu.com" not in self.page.url:
                await self.page.goto("https://www.xiaohongshu.com/explore", wait_until="domcontentloaded")
                await asyncio.sleep(2)
        except Exception as e:
            logger.warning(f"页面检查/跳转失败: {str(e)}")
            # 尝试重新初始化
            await self.init_browser()

    async def _simulate_human_behavior(self):
        """模拟真实用户行为，降低验证触发概率"""
        try:
            if not self.page:
                return
            # 1. 随机等待，略微提速
            await asyncio.sleep(random.uniform(0.3, 1.0))
            # 2. 随机鼠标移动
            try:
                if self.page.mouse:
                    x = random.randint(100, 800)
                    y = random.randint(100, 600)
                    await self.page.mouse.move(x, y)
            except: pass
        except: pass

    async def _build_xhs_cookie_string(self) -> str:
        """从浏览器上下文拼接完整 cookie 字符串（含 HttpOnly）"""
        try:
            cookies = await self.context.cookies()
        except Exception:
            cookies = []
        parts = []
        for c in cookies or []:
            domain = c.get("domain", "")
            if "xiaohongshu.com" not in domain:
                continue
            name = c.get("name")
            value = c.get("value")
            if name and value is not None:
                parts.append(f"{name}={value}")
        return "; ".join(parts)

    async def _try_user_posted_spider(
        self,
        user_id: str,
        cursor: str,
        xsec_token: str,
        xsec_source: str,
        creator_url_with_token: str,
    ) -> Optional[Dict]:
        """使用 Spider_XHS 的 JS 签名方案请求 user_posted，成功则返回结果，失败返回 None"""
        try:
            from . import xhs_spider_signer as spider_signer
        except Exception as e:
            logger.debug("Spider signer 未加载，跳过: %s", e)
            return None

        image_formats = "jpg,webp,avif"
        params = {
            "num": "30",
            "cursor": str(cursor or ""),
            "user_id": user_id,
            "image_formats": image_formats,
            "xsec_token": xsec_token,
            "xsec_source": xsec_source,
        }
        try:
            cookies_str = await self._build_xhs_cookie_string()
            if not cookies_str or "a1=" not in cookies_str:
                logger.warning("Spider signer 需要完整 cookie（含 a1），当前 cookie 不完整")
                return None

            splice_api = spider_signer.splice_str("/api/sns/web/v1/user_posted", params)
            headers, cookies, _ = spider_signer.generate_request_params(cookies_str, splice_api, "", "GET")
            headers["referer"] = creator_url_with_token or "https://www.xiaohongshu.com/"
            headers["origin"] = "https://www.xiaohongshu.com"
            headers["accept"] = "application/json, text/plain, */*"
            full_url = "https://edith.xiaohongshu.com" + splice_api

            async with httpx.AsyncClient(timeout=20.0) as client:
                resp = await client.get(full_url, headers=headers, cookies=cookies)
            if resp.status_code != 200:
                logger.warning("Spider signer user_posted 返回 %s", resp.status_code)
                if resp.status_code == 461:
                    self._last_user_info_error = '小红书登录状态可能已失效，请先在"账号登录"中重新登录小红书后再试。'
                return None

            data = resp.json()
            return {"__raw__": data}
        except Exception as e:
            logger.warning("Spider signer user_posted 失败: %s", e)
            return None

    async def _try_feed_spider(
        self,
        note_id: str,
        xsec_token: str,
        xsec_source: str,
        referer_url: str,
    ) -> Optional[Dict]:
        """使用 Spider_XHS 的 JS 签名方案请求 feed，成功则返回 note_card"""
        try:
            from . import xhs_spider_signer as spider_signer
        except Exception as e:
            logger.debug("Spider signer 未加载，跳过 feed: %s", e)
            return None

        body = {
            "source_note_id": note_id,
            "image_formats": ["jpg", "webp", "avif"],
            "extra": {"need_body_topic": 1},
            "xsec_source": xsec_source,
            "xsec_token": xsec_token,
        }
        try:
            cookies_str = await self._build_xhs_cookie_string()
            if not cookies_str or "a1=" not in cookies_str:
                logger.warning("Spider signer feed 需要完整 cookie（含 a1），当前 cookie 不完整")
                return None

            headers, cookies, data = spider_signer.generate_request_params(
                cookies_str,
                "/api/sns/web/v1/feed",
                body,
                "POST",
            )
            headers["referer"] = referer_url or "https://www.xiaohongshu.com/"
            headers["origin"] = "https://www.xiaohongshu.com"
            headers["accept"] = "application/json, text/plain, */*"

            async with httpx.AsyncClient(timeout=20.0) as client:
                resp = await client.post(
                    "https://edith.xiaohongshu.com/api/sns/web/v1/feed",
                    headers=headers,
                    cookies=cookies,
                    content=data,
                )
            if resp.status_code != 200:
                logger.info("[feed下载][spider] 请求失败 status=%s, note_id=%s", resp.status_code, note_id)
                return None
            data_feed = resp.json()
            items = (data_feed.get("data") or {}).get("items") or data_feed.get("items") or []
            if not items:
                return None
            card = items[0].get("note_card") or items[0].get("noteCard") or items[0]
            return card if isinstance(card, dict) else None
        except Exception as e:
            logger.warning("Spider signer feed 失败: %s", e)
            return None

    async def get_note_info_full(self, url: str) -> Dict:
        """通过 feed 接口获取完整笔记 JSON（Spider 签名）。"""
        raw_url = (url or "").strip()
        if not raw_url:
            raise ValueError("URL不能为空")

        await self._ensure_page_ready()

        parsed = urlparse(raw_url)
        path = parsed.path or ""
        parts = [p for p in path.split("/") if p]
        note_id = ""
        if "explore" in parts:
            i = parts.index("explore")
            if i + 1 < len(parts):
                note_id = parts[i + 1]
        elif "discovery" in parts and "item" in parts:
            i = parts.index("item")
            if i + 1 < len(parts):
                note_id = parts[i + 1]
        if not note_id and parts:
            note_id = parts[-1]
        note_id = (note_id or "").split("?")[0]
        if not note_id:
            raise ValueError("无法解析 note_id")

        q = parse_qs(parsed.query or "")
        xsec_token = (q.get("xsec_token") or [""])[0] or ""
        xsec_source = (q.get("xsec_source") or ["pc_feed"])[0] or "pc_feed"
        if not xsec_token.strip():
            raise ValueError("链接中未解析到 xsec_token")

        try:
            from . import xhs_spider_signer as spider_signer
        except Exception as e:
            raise RuntimeError("Spider signer 未加载，无法请求 feed") from e

        body = {
            "source_note_id": note_id,
            "image_formats": ["jpg", "webp", "avif"],
            "extra": {"need_body_topic": 1},
            "xsec_source": xsec_source,
            "xsec_token": xsec_token,
        }

        cookies_str = await self._build_xhs_cookie_string()
        if not cookies_str or "a1=" not in cookies_str:
            raise RuntimeError("Spider signer 需要完整 cookie（含 a1），当前 cookie 不完整")

        headers, cookies, data = spider_signer.generate_request_params(
            cookies_str,
            "/api/sns/web/v1/feed",
            body,
            "POST",
        )
        headers["referer"] = raw_url if "xiaohongshu.com" in raw_url else "https://www.xiaohongshu.com/"
        headers["origin"] = "https://www.xiaohongshu.com"
        headers["accept"] = "application/json, text/plain, */*"

        async with httpx.AsyncClient(timeout=20.0) as client:
            resp = await client.post(
                "https://edith.xiaohongshu.com/api/sns/web/v1/feed",
                headers=headers,
                cookies=cookies,
                content=data,
            )
        if resp.status_code != 200:
            raise RuntimeError(f"feed 请求失败 status={resp.status_code}")
        return resp.json()

    async def _try_og_video(self, note_id: str) -> Optional[str]:
        """尝试从笔记 HTML 中提取 og:video 直链（可能无水印）"""
        try:
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Referer": "https://www.xiaohongshu.com/",
            }
            async with httpx.AsyncClient(timeout=20.0) as client:
                resp = await client.get(f"https://www.xiaohongshu.com/explore/{note_id}", headers=headers)
            if resp.status_code != 200:
                return None
            text = resp.text or ""
            m = re.search(r'<meta name=\"og:video\" content=\"(.*?)\">', text)
            if m:
                return m.group(1)
            return None
        except Exception as e:
            logger.debug("[og:video] 提取失败 note_id=%s: %s", note_id, e)
            return None

    async def login(self):
        """打开登录页面等待用户登录"""
        try:
            await self.init_browser()
            await self.page.goto("https://www.xiaohongshu.com/explore", wait_until="domcontentloaded")
            return {"message": "登录页面已打开，请在浏览器中扫码登录"}
        except Exception as e:
            logger.error(f"打开登录页面失败: {str(e)}")
            raise HTTPException(status_code=500, detail=f"打开登录页面失败: {str(e)}")

    async def export_cookies_netscape(self, force_refresh: bool = False) -> str:
        """导出Netscape格式的Cookie"""
        async with self._lock:
            if not self.page:
                success = await self.init_browser()
                if not success:
                    raise Exception("浏览器初始化失败")
            
            if force_refresh:
                try:
                    await self.page.goto("https://www.xiaohongshu.com/explore", wait_until="domcontentloaded")
                    await asyncio.sleep(3)
                    await self._simulate_human_behavior()
                except Exception as e:
                    logger.warning(f"刷新页面失败: {str(e)}")
            
            # 获取所有cookie
            cookies = await self.context.cookies()
            if not cookies:
                raise Exception("未获取到任何Cookie")
                
            # 过滤小红书相关的cookie
            xhs_cookies = [c for c in cookies if 'xiaohongshu.com' in c['domain']]
            if not xhs_cookies:
                raise Exception("未获取到小红书Cookie")
                
            # 生成Netscape格式
            lines = [
                "# Netscape HTTP Cookie File",
                "# https://curl.haxx.se/rfc/cookie_spec.html",
                "# This is a generated file!  Do not edit.",
                ""
            ]
            
            for c in xhs_cookies:
                domain = c['domain']
                flag = "TRUE" if domain.startswith('.') else "FALSE"
                path = c['path']
                secure = "TRUE" if c.get('secure') else "FALSE"
                expiration = str(int(c.get('expires', 0)))
                name = c['name']
                value = c['value']
                
                line = f"{domain}\t{flag}\t{path}\t{secure}\t{expiration}\t{name}\t{value}"
                lines.append(line)
                
            return "\n".join(lines) + "\n"

    async def get_user_info(self, user_id: str) -> Optional[Dict]:
        """获取用户信息。user_id 可为纯 user_id（24 位 hex）或创作者主页完整 URL（含 xsec_token）；不要传笔记链接。"""
        async with self._lock:
            try:
                self._last_user_info_error = ""
                await self._ensure_page_ready()
                raw = (user_id or "").strip()
                # 笔记链接：拒绝，避免拼成 /user/profile/https://...
                if raw and "/explore/" in raw and "xiaohongshu.com" in raw:
                    logger.warning("请使用创作者主页链接，不要使用笔记链接")
                    self._last_user_info_error = "请使用创作者主页链接（含 xsec_token），不要使用笔记链接。"
                    return None
                # 已是创作者主页完整 URL：直接使用，不要再拼一层
                if raw.startswith("http") and "/user/profile/" in raw:
                    url = raw
                    user_id_from_path = raw.split("/user/profile/")[1].split("?")[0]
                else:
                    user_id_from_path = user_id
                    url = f"https://www.xiaohongshu.com/user/profile/{user_id}"
                await self.page.goto(url, wait_until="domcontentloaded", timeout=60000)
                await self._simulate_human_behavior()
                
                # 从 window.__INITIAL_STATE__.user.userPageData 提取创作者信息
                script = """
                () => {
                    try {
                        const state = window.__INITIAL_STATE__;
                        if (state && state.user && state.user.userPageData) {
                            const data = state.user.userPageData;
                            const unref = (val) => (val && typeof val === 'object' && '_value' in val) ? val._value : val;
                            return unref(data);
                        }
                        
                        // 备选：从 DOM 解析
                        const nickname = document.querySelector('.user-name')?.innerText;
                        const desc = document.querySelector('.user-desc')?.innerText;
                        const avatar = document.querySelector('.user-image img')?.src;
                        const interactions = Array.from(document.querySelectorAll('.user-interactions .count')).map(el => el.innerText);
                        
                        if (nickname) {
                            return { 
                                nickname, 
                                desc, 
                                avatar, 
                                userId: window.location.pathname.split('/').pop(),
                                interactions: [
                                    { type: 'follows', count: interactions[0] || 0 },
                                    { type: 'fans', count: interactions[1] || 0 },
                                    { type: 'interaction', count: interactions[2] || 0 }
                                ]
                            };
                        }
                        return null;
                    } catch (e) {
                        return null;
                    }
                }
                """
                user_data = await self.page.evaluate(script)
                
                # 记录提取的数据用于调试
                current_url = self.page.url
                logger.info(f"get_user_info - 当前URL: {current_url}")
                logger.info(f"get_user_info - 提取的user_data: {user_data}")
                
                if user_data:
                    # 提取统计数据
                    follower_count = 0
                    following_count = 0
                    like_count = 0
                    
                    interactions = user_data.get("interactions", [])
                    for item in interactions:
                        if item.get("type") == "fans":
                            follower_count = self._parse_count(item.get("count", 0))
                        elif item.get("type") == "follows":
                            following_count = self._parse_count(item.get("count", 0))
                        elif item.get("type") == "interaction":
                            like_count = self._parse_count(item.get("count", 0))

                    # 兼容两种数据结构：顶层字段 或 basicInfo 嵌套（小红书新接口返回格式）
                    basic_info = user_data.get("basicInfo") or {}
                    nickname = (user_data.get("nickname") or basic_info.get("nickname") or "未知用户")
                    avatar = (user_data.get("avatar") or user_data.get("images") or 
                            basic_info.get("avatar") or basic_info.get("images") or basic_info.get("imageb") or "")
                    if isinstance(avatar, str) and avatar:
                        avatar = avatar.split("?")[0]  # 去掉URL参数
                    desc = user_data.get("desc") or basic_info.get("desc") or ""
                    user_id_val = user_data.get("userId") or basic_info.get("userId") or user_id_from_path or user_id

                    return {
                        "user_id": user_id_val,
                        "nickname": nickname,
                        "avatar_url": avatar or "",
                        "signature": desc,
                        "video_count": 0,  # 小红书未直接提供
                        "follower_count": follower_count,
                        "following_count": following_count,
                        "like_count": like_count
                    }
                
                # 无用户数据时，尽量识别是否是登录失效
                login_state = await self.page.evaluate("""
                () => {
                    const href = window.location.href || '';
                    const cookie = document.cookie || '';
                    const hasWebSession = cookie.includes('web_session=');
                    const loginHint =
                        href.includes('/login') ||
                        href.includes('/captcha') ||
                        !!document.querySelector('input[type="password"], .login-container, .login-panel, [class*="login-panel"]');
                    return { href, hasWebSession, loginHint };
                }
                """)
                if (login_state or {}).get("loginHint") or not (login_state or {}).get("hasWebSession"):
                    self._last_user_info_error = "小红书登录状态可能已失效，请先在“账号登录”中重新登录小红书后再试。"
                else:
                    self._last_user_info_error = "无法获取小红书用户信息，请检查链接是否正确或稍后重试。"
                return None
                
            except Exception as e:
                logger.error(f"获取用户信息失败: {str(e)}")
                if not self._last_user_info_error:
                    self._last_user_info_error = f"无法获取小红书用户信息: {str(e)}"
                return None

    async def get_user_notes(self, user_id: str, cursor: str = "", creator_url_with_token: Optional[str] = None) -> Dict:
        """获取用户笔记列表。仅使用 Spider_XHS 签名请求 user_posted。"""
        if not creator_url_with_token or "xsec_token" not in (creator_url_with_token or ""):
            logger.warning("小红书笔记拉取需要带 xsec_token 的创作者链接，请从浏览器地址栏复制完整链接后添加订阅")
            return {"notes": [], "has_more": False, "error": "请使用带 xsec_token 的创作者链接添加订阅"}

        async def _do_request():
            try:
                from urllib.parse import urlparse, parse_qs, quote
                await self._ensure_page_ready()
                q = parse_qs(urlparse(creator_url_with_token).query)
                xsec_token = (q.get("xsec_token") or [""])[0] or ""
                xsec_source = (q.get("xsec_source") or ["pc_feed"])[0] or "pc_feed"
                image_formats = "jpg,webp,avif"
                if not xsec_token.strip():
                    return {"notes": [], "has_more": False, "error": "链接中未解析到 xsec_token"}

                def _extract_notes(data: Dict) -> Dict:
                    logger.debug(
                        "user_posted 响应顶层: keys=%s, success=%s, code=%s, msg=%s",
                        list(data.keys()),
                        data.get("success"),
                        data.get("code"),
                        data.get("msg"),
                    )
                    if data.get("success"):
                        payload = data.get("data", {})
                    elif data.get("code") == 0:
                        payload = data.get("data", {})
                    else:
                        payload = {}
                    logger.debug("user_posted data 内层: keys=%s", list(payload.keys()) if isinstance(payload, dict) else type(payload).__name__)
                    raw_notes = payload.get("notes", []) or []
                    if len(raw_notes) == 0 and isinstance(payload, dict):
                        logger.info(
                            "user_posted 返回 0 条笔记，便于排查: success=%s, code=%s, has_more=%s, cursor=%s",
                            data.get("success"),
                            data.get("code"),
                            payload.get("has_more"),
                            payload.get("cursor"),
                        )
                    # 笔记发布时间：API 可能用 time / last_update_time / create_time 等，优先用真实发布时间
                    def _note_ts(n):
                        t = n.get("time") or n.get("last_update_time") or n.get("create_time") or n.get("timestamp")
                        t = t or n.get("lastUpdateTime") or n.get("createTime")
                        if t is None and isinstance(n.get("note_card"), dict):
                            nc = n["note_card"]
                            t = nc.get("time") or nc.get("last_update_time") or nc.get("create_time")
                        return t
                    if raw_notes and logger.isEnabledFor(logging.DEBUG):
                        logger.debug("user_posted 首条笔记 keys: %s, time=%s", list(raw_notes[0].keys()), _note_ts(raw_notes[0]))
                    def _pick_cover_url(cover) -> str:
                        """从 cover 结构中提取可用封面链接（兼容 url 为空的场景）。"""
                        if not isinstance(cover, dict):
                            return ""
                        candidates = []
                        # 1) 直接 url
                        if cover.get("url"):
                            candidates.append(cover.get("url"))
                        # 2) 默认/预览 url
                        if cover.get("url_default"):
                            candidates.append(cover.get("url_default"))
                        if cover.get("url_pre"):
                            candidates.append(cover.get("url_pre"))
                        # 3) info_list 兜底
                        info_list = cover.get("info_list") if isinstance(cover.get("info_list"), list) else []
                        for item in info_list:
                            if isinstance(item, dict) and item.get("url"):
                                candidates.append(item.get("url"))
                        for u in candidates:
                            if isinstance(u, str) and u.strip():
                                # 统一为 https，避免前端混合内容/代理问题
                                return u.replace("http://", "https://", 1)
                        return ""

                    notes = []
                    for note in raw_notes:
                        ts = _note_ts(note)
                        nid = note.get("note_id") or note.get("id")
                        if not nid:
                            logger.debug("跳过无效笔记（无ID）: %s", note)
                            continue
                        cover_url = ""
                        cover = note.get("cover") if isinstance(note.get("cover"), dict) else None
                        if cover:
                            cover_url = _pick_cover_url(cover)
                        notes.append({
                            "note_id": nid,
                            "title": note.get("display_title") or note.get("title", ""),
                            "type": note.get("type"),
                            "cover_url": cover_url,
                            "liked_count": note.get("interact_info", {}).get("liked_count", 0),
                            "time": ts,
                            "publish_time": ts,
                            "xsec_token": (note.get("xsec_token") or "").strip() or None,
                        })
                    logger.info("通过主动 API 获取 %s 条笔记", len(notes))
                    return {"notes": notes, "cursor": payload.get("cursor", ""), "has_more": payload.get("has_more", False)}

                # 仅使用 Spider_XHS 签名链路（更接近线上请求）
                spider_result = await self._try_user_posted_spider(
                    user_id=user_id,
                    cursor=cursor,
                    xsec_token=xsec_token,
                    xsec_source=xsec_source,
                    creator_url_with_token=creator_url_with_token,
                )
                if spider_result and "__raw__" in spider_result:
                    return _extract_notes(spider_result["__raw__"])
                return {"notes": [], "has_more": False, "error": "Spider 签名请求失败"}
            except Exception as e:
                logger.error("获取用户笔记失败: %s", str(e), exc_info=True)
                return {"notes": [], "has_more": False, "error": str(e)}

        # 超时/网络类错误时重试，最多 3 次（1 次首次 + 2 次重试）
        max_attempts = 3
        retry_delay_seconds = 4
        for attempt in range(max_attempts):
            async with self._lock:  # 每次重试请求都要获取锁
                result = await _do_request()
            err = result.get("error") or ""
            # 无错误，或错误不可重试（如链接无效、签名失败），直接返回
            if not err:
                return result
            err_lower = err.lower()
            retryable = "timeout" in err_lower or "exceeded" in err_lower or "network" in err_lower or "reset" in err_lower
            if not retryable or attempt >= max_attempts - 1:
                return result
            logger.warning("获取用户笔记失败（可重试），%s 秒后第 %s/%s 次重试: %s", retry_delay_seconds, attempt + 2, max_attempts, err[:120])
            await asyncio.sleep(retry_delay_seconds)
        return result

    async def get_note_detail_by_feed(self, note_id: str, xsec_token: str, xsec_source: str = "pc_feed", profile_url: Optional[str] = None) -> Optional[Dict]:
        """通过 feed 接口获取笔记详情（用于下载时取直链）。外部独立调用时需加锁。
        
        Args:
            note_id: 笔记ID
            xsec_token: xsec_token
            xsec_source: xsec_source，默认 "pc_feed"
            profile_url: 创作者主页URL（可选），如果提供，将使用它作为页面准备和Referer，与同步阶段保持一致
        """
        # 注意：内部已在 get_user_notes 全局锁中调用的逻辑不能重复获取 self._lock，否则死锁。
        # 这里判断是否需要加锁：如果是在 fetch_note_time 中被 gather，应该已经持有外部锁。
        # 但目前 get_user_notes 内部是直接实现的 feed 逻辑，没调这个方法。
        async with self._lock:
            # 下载阶段调用频率控制：在全局串行锁内再加入一个轻微随机延迟，进一步降低 need 接口调用节奏
            await asyncio.sleep(random.uniform(0.8, 1.5))
            return await self._do_get_note_detail_by_feed(note_id, xsec_token, xsec_source, profile_url)

    async def _do_get_note_detail_by_feed(self, note_id: str, xsec_token: str, xsec_source: str = "pc_feed", profile_url: Optional[str] = None) -> Optional[Dict]:
        """内部实现，不带锁
        
        Args:
            note_id: 笔记ID
            xsec_token: xsec_token
            xsec_source: xsec_source，默认 "pc_feed"
            profile_url: 创作者主页URL（可选），如果提供，将优先使用它进行页面准备
        """
        if not note_id or not (xsec_token or "").strip():
            return None
        if not self.page:
            logger.warning("[xhsapi] get_note_detail_by_feed 需要先 init_browser")
            return None
            
        # [Spider优先] 仅使用 Spider_XHS 签名方案请求 feed
        referer_url = profile_url if profile_url and "xsec_token" in profile_url else self.page.url
        spider_card = await self._try_feed_spider(note_id, xsec_token.strip(), xsec_source, referer_url)
        if spider_card:
            logger.info("[feed下载][spider] 请求成功 note_id=%s", note_id)
            return spider_card
        return None

    async def get_note_info_from_page(self, note_id: str, xsec_token: str) -> Optional[Dict]:
        """复刻 yt-dlp：打开笔记页，从 window.__INITIAL_STATE__ 解析 note。"""
        async with self._lock:
            if not note_id or not (xsec_token or "").strip() or not self.page:
                return None
            xsec_token = xsec_token.strip()
            note_url = f"https://www.xiaohongshu.com/discovery/item/{note_id}?xsec_token={xsec_token}&xsec_source=pc_feed"
            try:
                await self.page.goto(note_url, wait_until="domcontentloaded", timeout=60000)
                await asyncio.sleep(0.8)
                raw = await self.page.evaluate("""() => {
                    const s = window.__INITIAL_STATE__;
                    if (!s) return null;
                    try { return JSON.stringify(s, (k,v) => v === undefined ? null : v); } catch(e) { return null; }
                }""")
                if not raw:
                    logger.debug("get_note_info_from_page 未取到 __INITIAL_STATE__ note_id=%s", note_id)
                    return None
                state = json.loads(raw)
                detail_map = (state.get("note") or {}).get("noteDetailMap") or {}
                note_info = detail_map.get(note_id, {}).get("note") if isinstance(detail_map, dict) else None
                if note_info and isinstance(note_info, dict):
                    logger.debug("get_note_info_from_page 成功 note_id=%s", note_id)
                    return note_info
                return None
            except Exception as e:
                logger.debug("get_note_info_from_page 失败 note_id=%s: %s", note_id, e)
                return None

    async def close_browser(self):
        """关闭浏览器页面（仅关闭当前平台的标签页，不关闭整个浏览器以避免其他平台登录态丢失）"""
        try:
            # 只关闭当前平台的标签页，与抖音/B站/YouTube保持一致
            await self._browser.close_page(self._platform)
            return True
        except Exception as e:
            logger.error(f"关闭浏览器失败: {str(e)}")
            return False

# 全局实例
xhs_api = XiaohongshuAPI()

@router.post("/login")
@require_license_api
async def login():
    """初始化登录"""
    # 🔧 登录需要VNC交互，切换到有头模式
    await unified_browser.switch_to_headed()
    return await xhs_api.login()

@router.post("/close")
@require_license_api
async def close():
    """关闭浏览器"""
    await xhs_api.close_browser()
    return {"message": "浏览器已关闭"}
