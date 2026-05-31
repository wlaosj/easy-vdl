import os
import sys
import logging
import asyncio
import time
import uuid
import subprocess
from contextlib import redirect_stdout, redirect_stderr
from io import StringIO
from datetime import datetime, timedelta
from typing import Optional, Dict, List
from dataclasses import dataclass
from fastapi import APIRouter, Depends, HTTPException, Request, Body, Query
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session
from pydantic import BaseModel, Field
from urllib.parse import urlparse, unquote, parse_qs
import re
import httpx
import yt_dlp

# 从 dyd.py 导入共享模型和函数
from routers.dyd import VideoInfo, Platform, sanitize_filename, generate_nfo_douyin_xhs, download_thumbnail_async, rename_and_scrape
from sql.models import Task, TaskStatus, SubscriptionVideo, Subscription, User
from sql.database_postgresql import get_db
from routers.auth import get_current_user, get_current_user_or_token
from routers.websocket import broadcast_message
import json

# 配置日志
logging.basicConfig(level=logging.WARNING)
logger = logging.getLogger(__name__)

# 创建APIRouter实例
router = APIRouter()

# 使用统计
usage_stats = {
    "parse_requests": 0,
    "successful_requests": 0,
    "failed_requests": 0,
    "daily_stats": {},
    "last_reset": datetime.now().date().isoformat()
}

# 进度节流状态：按 task_id 记录最近一次真实写库的时间与进度
_xhs_progress_throttle: Dict[str, Dict[str, float]] = {}

# 小红书下载使用浏览器时串行化，避免多任务共享同一 page 导致 Execution context destroyed
_xhs_browser_lock = asyncio.Lock()
_xhs_preheat_lock = asyncio.Lock()
_xhs_last_preheat_ts = 0.0
_XHS_PREHEAT_COOLDOWN_SECONDS = 30.0


class CookieNotConfiguredError(Exception):
    """小红书 Cookie 未配置，需要用户手动粘贴"""
    pass


def _has_valid_xhs_cookie(cookie_path: str = "/app/database/cookie/xiaohongshu_cookie.txt") -> bool:
    """检查磁盘上的 cookie 文件是否含有有效登录态（a1 cookie）"""
    try:
        if os.path.exists(cookie_path):
            with open(cookie_path, "r", encoding="utf-8") as f:
                content = f.read()
                # Netscape 格式（tab 分隔）: "...\ta1\t..."
                # HTTP Header 格式（手动粘贴）: "a1=..."
                return "\ta1\t" in content or "a1=" in content
    except Exception:
        pass
    return False


class RateLimiter:
    def __init__(self, max_requests: int = 30, time_window: int = 60):
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
    urls: List[str] = Field(..., min_items=1, max_items=5)
    concurrent_limit: int = Field(default=2, ge=1, le=5)

class DownloadRequest(BaseModel):
    url: str
    generate_nfo: bool = True  # 是否生成NFO文件，默认开启（仅对手动下载生效）


def _xhs_note_id_from_url(url: str) -> Optional[str]:
    """从小红书链接解析 note_id，如 explore/698810a6000000000e03ec88"""
    if not url:
        return None
    path = urlparse(url).path or url
    parts = path.strip("/").split("/")
    if "explore" in parts:
        i = parts.index("explore")
        if i + 1 < len(parts):
            return parts[i + 1].split("?")[0]
    if len(parts) >= 1 and len(parts[-1]) == 24 and all(c in "0123456789abcdef" for c in parts[-1]):
        return parts[-1].split("?")[0]
    return None


def _get_video_url_from_note_card(note_card: Dict) -> tuple:
    """从 feed 返回的 note_card 提取视频直链。返回 (url_list, from_origin)。
    from_origin=True 表示使用 origin_video_key（理论无水印），False 表示使用 stream（可能带水印）。"""
    if not note_card or note_card.get("type") != "video":
        return [], False
    video_dict = note_card.get("video")
    if not video_dict:
        return [], False
    consumer = video_dict.get("consumer") or video_dict.get("Consumer") or {}
    origin_key = consumer.get("origin_video_key") or consumer.get("originVideoKey") or ""
    if origin_key:
        return [f"https://sns-video-bd.xhscdn.com/{origin_key}"], True
    media = video_dict.get("media") or video_dict.get("Media") or {}
    stream = media.get("stream") or media.get("Stream") or {}
    h264 = stream.get("h264") or stream.get("H264")
    video_arr = []
    if isinstance(h264, list):
        for v in h264:
            u = (v.get("master_url") or v.get("masterUrl")) if isinstance(v, dict) else None
            if u:
                video_arr.append(u)
    return video_arr, False


def _extract_origin_url_from_feed_json(feed_json: Dict) -> Optional[str]:
    """从完整 feed JSON 中提取 origin_video_key 直链。"""
    if not isinstance(feed_json, dict):
        return None
    data = feed_json.get("data") or feed_json
    items = None
    if isinstance(data, dict):
        items = data.get("items")
    if not isinstance(items, list) or not items:
        return None
    first = items[0] or {}
    card = first.get("note_card") or first.get("noteCard") or first
    if not isinstance(card, dict):
        return None
    video_dict = card.get("video")
    if not isinstance(video_dict, dict):
        return None
    direct_origin_key = video_dict.get("origin_video_key") or video_dict.get("originVideoKey")
    if direct_origin_key:
        return f"https://sns-video-bd.xhscdn.com/{direct_origin_key}"
    direct_origin_url = video_dict.get("origin_video_url") or video_dict.get("originVideoUrl") or video_dict.get("origin_url") or video_dict.get("originUrl")
    if isinstance(direct_origin_url, str) and direct_origin_url.startswith("http"):
        return direct_origin_url
    consumer = video_dict.get("consumer") or video_dict.get("Consumer") or {}
    if not isinstance(consumer, dict):
        return None
    origin_key = consumer.get("origin_video_key") or consumer.get("originVideoKey")
    if not origin_key:
        return None
    return f"https://sns-video-bd.xhscdn.com/{origin_key}"


def _summarize_video_fields(feed_json: Dict) -> Dict:
    """提取 note_info_full 的视频字段概要，便于日志排查。"""
    summary: Dict[str, object] = {
        "has_data": False,
        "has_items": False,
        "video_keys": [],
        "consumer_keys": [],
        "media_keys": [],
        "stream_keys": [],
        "h264_len": 0,
        "has_origin_key": False,
        "has_origin_url": False,
    }
    if not isinstance(feed_json, dict):
        return summary
    data = feed_json.get("data") or feed_json
    if isinstance(data, dict):
        summary["has_data"] = True
        items = data.get("items")
    else:
        items = None
    if not isinstance(items, list) or not items:
        return summary
    summary["has_items"] = True
    first = items[0] or {}
    card = first.get("note_card") or first.get("noteCard") or first
    if not isinstance(card, dict):
        return summary
    video_dict = card.get("video")
    if not isinstance(video_dict, dict):
        return summary
    summary["video_keys"] = list(video_dict.keys())[:40]
    if video_dict.get("origin_video_key") or video_dict.get("originVideoKey"):
        summary["has_origin_key"] = True
    origin_url = video_dict.get("origin_video_url") or video_dict.get("originVideoUrl") or video_dict.get("origin_url") or video_dict.get("originUrl")
    if isinstance(origin_url, str) and origin_url.startswith("http"):
        summary["has_origin_url"] = True
    consumer = video_dict.get("consumer") or video_dict.get("Consumer") or {}
    if isinstance(consumer, dict):
        summary["consumer_keys"] = list(consumer.keys())[:40]
        if consumer.get("origin_video_key") or consumer.get("originVideoKey"):
            summary["has_origin_key"] = True
    media = video_dict.get("media") or video_dict.get("Media") or {}
    if isinstance(media, dict):
        summary["media_keys"] = list(media.keys())[:40]
        stream = media.get("stream") or media.get("Stream") or {}
        if isinstance(stream, dict):
            summary["stream_keys"] = list(stream.keys())[:40]
            h264 = stream.get("h264") or stream.get("H264")
            if isinstance(h264, list):
                summary["h264_len"] = len(h264)
    return summary


async def _ensure_xhs_cookie_file(force_refresh: bool = False) -> bool:
    """确保小红书 cookie 文件存在且可用，必要时从内置浏览器刷新导出。"""
    cookie_path = "/app/database/cookie/xiaohongshu_cookie.txt"
    # 无论是否 force_refresh，先检查磁盘文件是否已有有效 cookie
    if _has_valid_xhs_cookie(cookie_path):
        return True
    if not force_refresh:
        return False

    try:
        from routers.unified_browser_manager import unified_browser
        from routers.xhsapi import xhs_api
        os.makedirs(os.path.dirname(cookie_path), exist_ok=True)
        async with _xhs_browser_lock:
            async with unified_browser.task_context("xiaohongshu", "xhs_cookie_refresh"):
                await xhs_api.init_browser()
                cookie_text = await xhs_api.export_cookies_netscape(force_refresh=True)
        if cookie_text:
            tmp_path = cookie_path + ".tmp"
            with open(tmp_path, "w", encoding="utf-8") as f:
                f.write(cookie_text)
            os.replace(tmp_path, cookie_path)
            return True
    except Exception as e:
        logger.warning("[xiaohongshu] 刷新 cookie 失败: %s", e)
    return False


async def _preheat_xhs_cookie(reason: str = "") -> None:
    """预热小红书 cookie（提前刷新，提高首次解析成功率）。"""
    try:
        async with _xhs_preheat_lock:
            import time
            global _xhs_last_preheat_ts
            now = time.time()
            if now - _xhs_last_preheat_ts < _XHS_PREHEAT_COOLDOWN_SECONDS:
                logger.info(
                    "[xiaohongshu] 预热 cookie 跳过（冷却中 %.1fs）: %s",
                    _XHS_PREHEAT_COOLDOWN_SECONDS - (now - _xhs_last_preheat_ts),
                    reason or "n/a",
                )
                return
            _xhs_last_preheat_ts = now
            if reason:
                logger.info(
                    "[xiaohongshu] 预热 cookie 开始 (cooldown=%.0fs): %s",
                    _XHS_PREHEAT_COOLDOWN_SECONDS,
                    reason,
                )
            await _ensure_xhs_cookie_file(force_refresh=True)
    except Exception as e:
        logger.warning("[xiaohongshu] 预热 cookie 失败（忽略）: %s", e)


def _mask_xsec_token(token: str) -> str:
    """脱敏展示 xsec_token（仅用于日志）"""
    if not token:
        return ""
    if len(token) <= 8:
        return token[:2] + "***"
    return f"{token[:4]}***{token[-4:]}"


XHS_DESKTOP_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)


def _xhs_ydl_headers(url: str) -> dict:
    referer = "https://www.xiaohongshu.com/"
    if url and "xiaohongshu.com" in url:
        referer = url
    return {
        "User-Agent": XHS_DESKTOP_UA,
        "Referer": referer,
        "Origin": "https://www.xiaohongshu.com",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    }


async def _do_refresh_xhs_token(page, note_id: str) -> Optional[str]:
    """在指定页面上导航到笔记页并提取最新的 xsec_token（不自持锁）"""
    try:
        note_page_url = f"https://www.xiaohongshu.com/explore/{note_id}"
        await page.goto(note_page_url, wait_until="networkidle", timeout=20000)
        await asyncio.sleep(0.5)
        current_url = page.url
        parsed = urlparse(current_url)
        qs = parse_qs(parsed.query)
        fresh = (qs.get("xsec_token") or [""])[0].strip()
        if fresh:
            logger.info("[xiaohongshu] 刷新 token 成功 note_id=%s new=%s", note_id, _mask_xsec_token(fresh))
            return fresh
        logger.warning("[xiaohongshu] 刷新 token 为空 note_id=%s url=%s", note_id, current_url)
        return None
    except Exception as e:
        logger.debug("[xiaohongshu] 刷新 token 失败 note_id=%s: %s", note_id, e)
        return None


async def _refresh_xhs_token(note_id: str) -> Optional[str]:
    """打开浏览器导航到笔记页，从 URL 中提取最新的 xsec_token（自持锁）"""
    from routers.unified_browser_manager import unified_browser
    from routers.xhsapi import xhs_api
    try:
        async with _xhs_browser_lock:
            async with unified_browser.task_context("xiaohongshu", "xhs_refresh_token"):
                await xhs_api.init_browser()
                if xhs_api.page:
                    return await _do_refresh_xhs_token(xhs_api.page, note_id)
                return None
    except Exception as e:
        logger.debug("[xiaohongshu] 刷新 token 失败 note_id=%s: %s", note_id, e)
        return None


async def parse_xiaohongshu_with_ytdlp(url: str, allow_token_refresh: bool = True) -> VideoInfo:
    """使用 yt-dlp 解析小红书视频"""
    try:
        logger.debug(f"[xiaohongshu] 开始使用 yt-dlp 解析: {url}")

        # 先检查 cookie 是否存在，不存在则直接抛友好错误
        if not _has_valid_xhs_cookie():
            raise CookieNotConfiguredError(
                "小红书 Cookie 未配置，请前往「设置 → Cookie 管理 → 小红书」粘贴 Netscape 格式的 Cookie"
            )

        info = None
        last_err = None
        for attempt in range(2):
            if attempt == 0:
                await _ensure_xhs_cookie_file(force_refresh=False)
            else:
                await _ensure_xhs_cookie_file(force_refresh=True)

            ydl_opts = {
                'quiet': True,
                'no_warnings': True,
                'extract_flat': False,
                'no_cache_dir': True,  # 禁用缓存目录，避免缓存堆积
                'user_agent': XHS_DESKTOP_UA,
                'http_headers': _xhs_ydl_headers(url),
                'retries': 2,
                'fragment_retries': 2,
                'file_access_retries': 2,
                'socket_timeout': 20,
            }
            
            # 添加小红书Cookie
            xhs_cookie_file = '/app/database/cookie/xiaohongshu_cookie.txt'
            if os.path.exists(xhs_cookie_file):
                with open(xhs_cookie_file, 'r', encoding='utf-8') as f:
                    if f.read().strip():
                        ydl_opts['cookiefile'] = xhs_cookie_file

            try:
                # 在异步环境中运行 yt-dlp（它是同步的）
                loop = asyncio.get_event_loop()
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    info = await loop.run_in_executor(None, ydl.extract_info, url, False)
                if info:
                    break
            except Exception as e:
                last_err = e
                if attempt == 0:
                    err_str = str(e)
                    if "No video formats" in err_str or "403" in err_str or "Forbidden" in err_str:
                        logger.info(
                            "[xiaohongshu] yt-dlp 解析失败，尝试刷新 cookie 后重试 (fail_stage=parse): %s",
                            err_str[:120],
                        )
                        continue
                raise
        if not info and last_err:
            err_str = str(last_err)
            if allow_token_refresh and ("No video formats" in err_str or "403" in err_str or "Forbidden" in err_str):
                note_id = _xhs_note_id_from_url(url)
                if note_id:
                    fresh_token = await _refresh_xhs_token(note_id)
                    if fresh_token:
                        explore_for_ydl = f"https://www.xiaohongshu.com/explore/{note_id}?xsec_token={fresh_token}&xsec_source=pc_feed"
                        return await parse_xiaohongshu_with_ytdlp(explore_for_ydl, allow_token_refresh=False)
            raise last_err

        if not info:
            raise Exception("yt-dlp 解析失败：未获取到视频信息")
        
        # 获取最佳视频URL
        video_url = info.get('url')
        if not video_url:
            # 如果有 formats，选择最佳格式的URL
            formats = info.get('formats', [])
            if formats:
                # 选择最佳视频格式（有视频编码的）
                best_format = None
                for fmt in formats:
                    if fmt.get('vcodec') != 'none' and fmt.get('url'):
                        if not best_format or (fmt.get('height', 0) or 0) > (best_format.get('height', 0) or 0):
                            best_format = fmt
                if best_format:
                    video_url = best_format.get('url')
        
        if not video_url:
            raise Exception("yt-dlp 解析失败：未找到视频URL")
        
        # 获取上传日期
        upload_date = info.get('upload_date')
        create_time = None
        if upload_date:
            try:
                # yt-dlp 的 upload_date 格式通常是 YYYYMMDD
                if len(upload_date) == 8:
                    create_time = f"{upload_date[:4]}-{upload_date[4:6]}-{upload_date[6:8]}"
            except Exception:
                pass
        
        video_info = VideoInfo(
            video_id=info.get('id', str(int(time.time()))),
            platform=Platform.XIAOHONGSHU,
            share_url=url,
            download_url=video_url,
            title=info.get('title', '小红书视频'),
            author=info.get('uploader') or info.get('channel') or '未知作者',
            create_time=create_time,
            thumbnail_url=info.get('thumbnail')
        )
        
        logger.info(f"[xiaohongshu] 解析成功: {video_info.title}")
        return video_info
        
    except Exception as e:
        logger.error(f"[xiaohongshu] yt-dlp 解析失败: {str(e)}")
        raise

# 下载标志
xhs_cancel_flags = {}

def now_beijing():
    from datetime import timezone
    return datetime.now(timezone(timedelta(hours=8)))

def update_xhs_task_progress(
    task_id: str,
    status: TaskStatus,
    progress: float = None,
    error: str = None,
    filename: str = None
):
    """更新任务进度（带节流）

    中间态（PENDING / DOWNLOADING / PROCESSING）：
      - 至少每 2 秒才真正写库一次；
      - 或者进度较上次变化 ≥ 3% 时立即写库；
    终态（COMPLETED / ERROR / CANCELLED）每次必写，确保最终状态准确。
    """
    global _xhs_progress_throttle

    try:
        status_str = status.value
        intermediate_statuses = {
            TaskStatus.PENDING.value,
            TaskStatus.DOWNLOADING.value,
            TaskStatus.PROCESSING.value,
        }

        # 预处理进度值用于节流判断
        safe_progress = None
        if progress is not None:
            try:
                safe_progress = float(progress)
                safe_progress = max(0.0, min(100.0, safe_progress))
            except Exception:
                safe_progress = None

        # 中间态节流：减少高频 DB 写入和 WS 推送
        if status_str in intermediate_statuses:
            now_ts = time.time()
            state = _xhs_progress_throttle.get(task_id)
            last_ts = state["ts"] if state else 0
            last_progress = state["progress"] if state else None

            allow = False
            if now_ts - last_ts >= 2:
                allow = True
            elif safe_progress is not None and last_progress is not None:
                if abs(safe_progress - last_progress) >= 3.0:
                    allow = True

            if not allow:
                # 仅更新内存中的最后状态，跳过实际 DB 写入
                _xhs_progress_throttle[task_id] = {
                    "ts": now_ts,
                    "progress": safe_progress if safe_progress is not None else last_progress,
                }
                return

        db = next(get_db())
        try:
            task = db.query(Task).filter(Task.id == task_id).first()
            if task:
                old_status = task.status

                task.status = status_str
                if safe_progress is not None:
                    task.progress = safe_progress
                if error:
                    task.error_message = error
                if filename:
                    task.filename = filename
                task.updated_at = datetime.now()

                # 终态时同步订阅视频状态
                if status in [TaskStatus.COMPLETED, TaskStatus.ERROR]:
                    video = db.query(SubscriptionVideo).filter(
                        SubscriptionVideo.download_task_id == task_id
                    ).first()
                    if video:
                        if status == TaskStatus.COMPLETED:
                            video.downloaded = "true"
                            video.error_message = None
                        else:
                            video.downloaded = "false"
                            video.error_message = error

                db.commit()

                # 记录真实写库时间与进度
                _xhs_progress_throttle[task_id] = {
                    "ts": time.time(),
                    "progress": task.progress,
                }

                # 仅记录关键日志：任务开始/结束等重要状态
                should_log = False
                if old_status != status_str:
                    if status in [
                        TaskStatus.DOWNLOADING,
                        TaskStatus.COMPLETED,
                        TaskStatus.ERROR,
                        TaskStatus.CANCELLED,
                    ]:
                        should_log = True

                if should_log:
                    error_info = f", 错误: {error}" if error else ""
                    logger.info(
                        f"[xiaohongshu] 任务 {task_id} 状态: {status_str}, 进度: "
                        f"{task.progress if task.progress is not None else 'N/A'}{error_info}"
                    )
                else:
                    logger.debug(
                        f"[xiaohongshu] 任务 {task_id} 进度: "
                        f"{task.progress if task.progress is not None else 'N/A'}"
                    )

                # WebSocket 进度更新
                progress_payload = {
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
                        'subscription_id': task.subscription_id,
                    }
                }

                async def send_progress_update(payload):
                    try:
                        await broadcast_message('downloads', payload)
                    except Exception as e:
                        logger.warning(f"[xiaohongshu] 发送WebSocket进度更新失败: {str(e)}")

                try:
                    try:
                        loop = asyncio.get_running_loop()
                        asyncio.create_task(send_progress_update(progress_payload))
                    except RuntimeError:
                        loop = asyncio.new_event_loop()
                        asyncio.set_event_loop(loop)
                        try:
                            loop.run_until_complete(send_progress_update(progress_payload))
                        finally:
                            loop.close()
                except Exception as e:
                    logger.warning(f"[xiaohongshu] WebSocket进度更新失败: {str(e)}")
            else:
                logger.warning(f"[xiaohongshu] 未找到任务: {task_id}")
        except Exception as e:
            db.rollback()
            logger.error(f"[xiaohongshu] 更新任务进度失败: {str(e)}")
        finally:
            try:
                db.rollback()
            except Exception:
                pass
            db.close()
    except Exception as e:
        logger.error(f"[xiaohongshu] 更新任务进度时发生错误: {str(e)}")

async def xhs_download_video_logic(task_id: str, url: str, custom_download_dir: str = None, generate_nfo: bool = True, retry_once: bool = False):
    """小红书视频下载的主要逻辑（使用 yt-dlp）"""
    import asyncio
    import aiohttp
    import threading
    
    TASK_TIMEOUT = 600  # 任务总超时10分钟
    db = next(get_db())
    try:
        result = await asyncio.wait_for(
            _do_xhs_download_video_task(task_id, url, custom_download_dir, db, generate_nfo, retry_once=retry_once),
            timeout=TASK_TIMEOUT
        )
        return result
    except asyncio.TimeoutError:
        logger.error(f"[xiaohongshu] 任务超时{TASK_TIMEOUT}秒: {task_id}")
        update_xhs_task_progress(task_id, TaskStatus.ERROR, error=f"任务超时{TASK_TIMEOUT}秒")
        return False
    except Exception as e:
        logger.error(f"[xiaohongshu] 下载任务失败: {str(e)}")
        update_xhs_task_progress(task_id, TaskStatus.ERROR, error=str(e))
        return False
    finally:
        # 尝试强制归还系统内存 (Linux glibc)
        try:
            import ctypes
            libc = ctypes.CDLL("libc.so.6")
            libc.malloc_trim(0)
        except Exception:
            pass
        try:
            db.rollback()
        except Exception:
            pass
        db.close()

async def _do_xhs_download_gallery_task(
    task_id: str, url: str, subscription_video: SubscriptionVideo, custom_download_dir: str, db
) -> bool:
    """小红书图集下载：从 feed 取 image_list，逐张 HTTP 下载到目录。"""
    import asyncio
    import aiohttp
    import threading
    note_id = _xhs_note_id_from_url(url)
    try:
        extra = json.loads((subscription_video.extra_data or "{}"))
    except (json.JSONDecodeError, TypeError) as e:
        logger.warning("[xiaohongshu] 图集下载解析 extra_data 失败: %s, extra_data=%s", e, subscription_video.extra_data)
        extra = {}
    xsec_token = (extra.get("xsec_token") or "").strip()
    # 如果 extra_data 中没有 token，尝试从 URL 中提取
    if not xsec_token and url:
        try:
            parsed = urlparse(url)
            qs = parse_qs(parsed.query)
            url_token = (qs.get("xsec_token") or [""])[0].strip()
            if url_token:
                xsec_token = url_token
                logger.debug("[xiaohongshu] 从 URL 中提取到 xsec_token")
        except Exception as e:
            logger.debug("[xiaohongshu] 从 URL 提取 xsec_token 失败: %s", e)
    if not note_id or not xsec_token:
        error_msg = f"图集下载缺少必要参数: note_id={'有' if note_id else '无'}, xsec_token={'有' if xsec_token else '无'}"
        logger.error("[xiaohongshu] %s, url=%s", error_msg, url)
        update_xhs_task_progress(task_id, TaskStatus.ERROR, error=error_msg)
        return False
    try:
        update_xhs_task_progress(task_id, TaskStatus.DOWNLOADING, progress=0.0)
        from routers.unified_browser_manager import unified_browser
        from routers.xhsapi import xhs_api
        async with _xhs_browser_lock:
            async with unified_browser.task_context("xiaohongshu", "xhs_download_gallery"):
                await xhs_api.init_browser()
                sub = db.query(Subscription).filter(Subscription.id == subscription_video.subscription_id).first()
                profile_url = getattr(sub, "profile_url", None) or "" if sub else ""
                
                # 优化：直接使用创作者主页（与同步阶段一致），避免多次页面跳转导致超时
                if profile_url and "xsec_token" in profile_url and xhs_api.page:
                    logger.info("[xiaohongshu] 图集下载访问创作者主页建立会话 note_id=%s", note_id)
                    try:
                        # 使用 domcontentloaded 替代 networkidle，减少超时风险（与同步阶段一致）
                        await xhs_api.page.goto(profile_url, wait_until="domcontentloaded", timeout=60000)
                        await xhs_api._simulate_human_behavior()
                        await asyncio.sleep(0.8)
                        
                    except Exception as e:
                        logger.warning("[xiaohongshu] 图集下载访问创作者主页失败 note_id=%s: %s", note_id, e)
                
                token_for_feed = xsec_token
                # 传递 profile_url 用于设置正确的 Referer（与同步阶段一致）
                note_card = await xhs_api.get_note_detail_by_feed(note_id, token_for_feed, "pc_feed", profile_url)
        if not note_card or note_card.get("type") == "video":
            update_xhs_task_progress(task_id, TaskStatus.ERROR, error="未获取到图集详情或该笔记为视频")
            return False
        image_list = note_card.get("image_list") or note_card.get("imageList") or []
        if not isinstance(image_list, list) or len(image_list) == 0:
            update_xhs_task_progress(task_id, TaskStatus.ERROR, error="图集无图片列表")
            return False
        # 记录接口返回的首图/封面地址，用于任务列表缩略图（优先使用现场静态图，而不是本地抽帧）
        poster_url = None
        try:
            if image_list and isinstance(image_list[0], dict):
                poster_url = (
                    image_list[0].get("url")
                    or image_list[0].get("url_default")
                    or image_list[0].get("thumbnail")
                )
            if not poster_url:
                cover = note_card.get("cover") or note_card.get("Cover")
                if isinstance(cover, dict):
                    poster_url = (
                        cover.get("url")
                        or cover.get("url_default")
                        or cover.get("thumbnail")
                    )
            if isinstance(poster_url, str):
                poster_url = poster_url.strip()
            else:
                poster_url = None
        except Exception:
            poster_url = None
        # 调试：记录第一条图片的所有字段，用于排查动态图字段
        if image_list and isinstance(image_list[0], dict):
            sample_img = image_list[0]
            logger.debug("[xiaohongshu] 图集首张图片字段: %s", list(sample_img.keys()))
            # 记录所有可能的URL字段
            url_fields = {k: v for k, v in sample_img.items() if "url" in k.lower()}
            if url_fields:
                logger.debug("[xiaohongshu] 图集首张图片URL相关字段: %s", url_fields)

        def _find_media_url(node):
            """在任意嵌套结构中寻找第一个 http(s) 媒体 URL，用于 live_photo/stream 提取动图视频地址。"""
            if isinstance(node, str):
                if node.startswith("http"):
                    return node
                return None
            if isinstance(node, dict):
                for v in node.values():
                    u = _find_media_url(v)
                    if u:
                        return u
            if isinstance(node, list):
                for v in node:
                    u = _find_media_url(v)
                    if u:
                        return u
            return None

        for img in image_list:
            if isinstance(img, dict):
                # 先从 stream / live_photo 等结构里递归找动图/视频地址（live photo 一般是短视频）
                animated_url = _find_media_url(img.get("stream")) or _find_media_url(img.get("live_photo"))
                # 再尝试若干可能字段
                if not animated_url:
                    animated_url = (
                        img.get("animated_url")
                        or img.get("live_url")
                        or img.get("url_animated")
                        or img.get("gif_url")
                        or img.get("url_live")
                        or img.get("animated")
                        or img.get("live")
                    )
                if animated_url:
                    img["url"] = animated_url
                    img["is_animated"] = True
                    logger.debug(
                        "[xiaohongshu] 检测到动态图URL: %s",
                        animated_url[:160] if isinstance(animated_url, str) else str(animated_url)[:160],
                    )
                else:
                    img["url"] = img.get("url") or img.get("url_default")
                    img["is_animated"] = False
                    # 检查URL中是否包含动态图标识
                    url_str = img["url"] or ""
                    if isinstance(url_str, str) and (
                        "animated" in url_str.lower()
                        or "live" in url_str.lower()
                        or url_str.lower().endswith(".gif")
                    ):
                        img["is_animated"] = True
                        logger.debug("[xiaohongshu] 从URL判断为动态图: %s", url_str[:160])
        title = (subscription_video.title or "").strip() or note_card.get("title") or note_card.get("desc") or f"图集_{note_id}"
        # 统一添加后缀 (Task ID 前8位)，确保唯一性并防止同名覆盖
        clean_title = sanitize_filename(title[:80] if title else note_id)
        filename_base = f"{clean_title}_{task_id[:8]}"
        download_dir = custom_download_dir
        os.makedirs(download_dir, exist_ok=True)
        gallery_folder = os.path.join(download_dir, filename_base)
        os.makedirs(gallery_folder, exist_ok=True)
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36",
            "Referer": "https://www.xiaohongshu.com/",
        }
        downloaded = 0
        async with httpx.AsyncClient(follow_redirects=True, timeout=30) as client:
            for i, img in enumerate(image_list):
                if not isinstance(img, dict):
                    continue
                u = (img.get("url") or img.get("url_default") or "").strip()
                if not u:
                    continue
                try:
                    resp = await client.get(u, headers=headers)
                    resp.raise_for_status()
                    # 根据是否为动态图以及实际类型决定文件扩展名
                    is_animated = img.get("is_animated", False)
                    content_type = resp.headers.get("content-type", "").lower()
                    url_lower = u.lower()

                    if is_animated:
                        # 动态图优先按视频处理：真实为 mp4 流时直接保存为 .mp4，便于播放器识别
                        if "video" in content_type or url_lower.endswith(".mp4") or ".mp4?" in url_lower:
                            ext = "mp4"
                        elif "gif" in content_type or url_lower.endswith(".gif") or "animated" in url_lower:
                            ext = "gif"
                        elif "webp" in content_type or url_lower.endswith(".webp"):
                            ext = "webp"
                        else:
                            ext = "jpg"
                    else:
                        # 非动态图保持原有逻辑
                        if "gif" in content_type or url_lower.endswith(".gif") or "animated" in url_lower:
                            ext = "gif"
                        elif "webp" in content_type or url_lower.endswith(".webp"):
                            ext = "webp"
                        else:
                            ext = "jpg"
                    save_path = os.path.join(gallery_folder, f"{i:04d}.{ext}")
                    with open(save_path, "wb") as f:
                        f.write(resp.content)
                    downloaded += 1
                except Exception as e:
                    logger.warning("[xiaohongshu] 图集图片 %s 下载失败: %s", i, e)
                progress = ((i + 1) / len(image_list)) * 100.0
                update_xhs_task_progress(task_id, TaskStatus.DOWNLOADING, progress=progress)
            # 如果没有任何 jpg 且接口提供了封面图，则额外下载一张封面图供任务列表/通知使用
            try:
                if downloaded > 0 and poster_url:
                    poster_jpg = os.path.join(gallery_folder, "0000.jpg")
                    has_jpg = any(
                        name.lower().endswith(".jpg")
                        for name in os.listdir(gallery_folder)
                    )
                    if not os.path.exists(poster_jpg) and not has_jpg:
                        await download_thumbnail_async(poster_url, poster_jpg)
            except Exception as e:
                logger.debug("[xiaohongshu] 下载图集封面图失败: %s", e)
        if downloaded == 0:
            update_xhs_task_progress(task_id, TaskStatus.ERROR, error="图集图片全部下载失败")
            return False
        relative_path = custom_download_dir.replace("/app/downloads/", "")
        filename_path = f"{relative_path}/{filename_base}/"
        update_xhs_task_progress(task_id, TaskStatus.COMPLETED, progress=100.0, filename=filename_path)
        video = db.query(SubscriptionVideo).filter(SubscriptionVideo.download_task_id == task_id).first()
        if video:
            video.downloaded = "true"
            db.commit()
        try:
            db_notify = next(get_db())
            try:
                sub_rec = db_notify.query(Subscription).filter(Subscription.id == subscription_video.subscription_id).first()
                n_author = f"订阅博主: {sub_rec.nickname or '未知'}" if sub_rec else "手动下载"
                poster_path = os.path.join(gallery_folder, "0000.jpg")
                if not os.path.exists(poster_path) and downloaded > 0:
                    first_jpg = next((os.path.join(gallery_folder, f) for f in os.listdir(gallery_folder) if f.endswith(".jpg")), None)
                    poster_path = first_jpg or poster_path
                extra_data = {}
                if os.path.exists(poster_path) and custom_download_dir:
                    rel = custom_download_dir.replace("/app/downloads/", "")
                    extra_data["cover"] = f"/downloads/{rel}/{filename_base}/{os.path.basename(poster_path)}"
                if subscription_video and getattr(subscription_video, "subscription_id", None):
                    extra_data["subscription_id"] = subscription_video.subscription_id
                notification_data = {
                    "title": "🎉 下载完成 (小红书)",
                    "content": f"图集《{title[:50] if title else note_id}》下载完成，共 {downloaded} 张\n\n🏷️ 来源: 小红书\n👤 {n_author}",
                    "user_id": "default",
                    "extra_data": extra_data,
                }
                def _send():
                    try:
                        async def _run():
                            connector = aiohttp.UnixConnector(path="/app/sockets/easy-vdl.sock")
                            async with aiohttp.ClientSession(connector=connector) as session:
                                await session.post("http://localhost/api/notifications/download-completed", json=notification_data)
                        loop = asyncio.new_event_loop()
                        asyncio.set_event_loop(loop)
                        loop.run_until_complete(_run())
                        loop.close()
                    except Exception:
                        pass
                threading.Thread(target=_send, daemon=True).start()
            finally:
                db_notify.close()
        except Exception as e:
            logger.warning("[xiaohongshu] 图集下载完成通知异常: %s", e)
        logger.info("[xiaohongshu] 图集下载完成 note_id=%s 共 %s 张", note_id, downloaded)
        return True
    except Exception as e:
        logger.exception("[xiaohongshu] 图集下载异常")
        update_xhs_task_progress(task_id, TaskStatus.ERROR, error=str(e)[:200])
        video = db.query(SubscriptionVideo).filter(SubscriptionVideo.download_task_id == task_id).first()
        if video:
            video.downloaded = "false"
            video.error_message = str(e)
            db.commit()
        return False


async def _do_xhs_download_video_task(task_id: str, url: str, custom_download_dir: str, db, generate_nfo: bool = True, retry_once: bool = False):
    """执行实际的小红书下载任务逻辑"""
    import asyncio
    import aiohttp
    import threading
    
    try:
        update_xhs_task_progress(task_id, TaskStatus.DOWNLOADING, progress=0.0)
        
        subscription_video = None
        if custom_download_dir:
            subscription_video = db.query(SubscriptionVideo).filter(
                SubscriptionVideo.download_task_id == task_id
            ).first()
            # 图集走单独逻辑：取 image_list 逐张下载
            if subscription_video:
                extra = json.loads((subscription_video.extra_data or "{}"))
                if extra.get("type") == "normal":
                    return await _do_xhs_download_gallery_task(
                        task_id, url, subscription_video, custom_download_dir, db
                    )

        video_info = None
        used_api_fallback = False
        url_for_ydl = url
        stream_fallback_url = None
        stream_fallback_note_card = None
        stream_fallback_title = None
        stream_fallback_note_id = None
        stream_fallback_subscription = False
        stream_fallback_publish_time = None
        stream_fallback_author = None
        stream_fallback_thumb = None
        preheated_cookie = False

        # 订阅任务：为了稳定性，直接使用 feed 直链兜底（优先默认播放流，可能带水印，但成功率更高）
        if custom_download_dir and subscription_video:
            note_id = _xhs_note_id_from_url(url)
            try:
                extra = json.loads((subscription_video.extra_data or "{}"))
            except (json.JSONDecodeError, TypeError):
                extra = {}
            xsec_token = (extra.get("xsec_token") or "").strip()
            
            if not re.match(r'[a-f0-9]{24}', note_id):
                raise ValueError(f"Invalid note_id format: {note_id}")

            # 尝试从 URL 中提取 xsec_token 如果参数缺失
            if not xsec_token and "xsec_token=" in url:
                try:
                    parsed = urlparse(url)
                    qs = parse_qs(parsed.query)
                    xsec_token = (qs.get("xsec_token") or [""])[0]
                    logger.info(f"[xiaohongshu] 从URL补全 xsec_token: {xsec_token}")
                except: pass

            if not xsec_token:
                 # 再尝试去数据库找一下完整的 URL
                try:
                    db_sess = next(get_db())
                    task_rec = db_sess.query(Task).filter(Task.id == task_id).first()
                    if task_rec and task_rec.url and "xsec_token=" in task_rec.url:
                         parsed = urlparse(task_rec.url)
                         qs = parse_qs(parsed.query)
                         xsec_token = (qs.get("xsec_token") or [""])[0]
                         logger.info(f"[xiaohongshu] 从任务URL补全 xsec_token: {xsec_token}")
                    db_sess.close()
                except: pass

            if not note_id or not xsec_token:
                raise Exception(f"订阅视频缺少必要参数: note_id={'有' if note_id else '无'}, xsec_token={'有' if xsec_token else '无'}")

            # 视频订阅：跳过 Feed API（origin_video_key 已无法获取），直接使用 yt-dlp
            token_for_feed = xsec_token
            url_for_ydl = f"https://www.xiaohongshu.com/explore/{note_id}?xsec_token={token_for_feed}&xsec_source=pc_feed"
            logger.info("[xiaohongshu] 订阅视频跳过 Feed API，直接使用 ytdlp note_id=%s", note_id)

        # 手动下载：跳过 Feed API（origin_video_key 已无法获取），直接使用 yt-dlp
        if not used_api_fallback and not (custom_download_dir and subscription_video):
            note_id = _xhs_note_id_from_url(url)
            xsec_token = ""
            if "xsec_token=" in url:
                try:
                    parsed = urlparse(url)
                    qs = parse_qs(parsed.query)
                    xsec_token = (qs.get("xsec_token") or [""])[0].strip()
                except Exception:
                    xsec_token = ""
            if note_id and xsec_token:
                url_for_ydl = f"https://www.xiaohongshu.com/explore/{note_id}?xsec_token={xsec_token}&xsec_source=pc_feed"
                logger.info("[xiaohongshu] 手动下载跳过 Feed API，直接使用 ytdlp note_id=%s", note_id)

        # 手动下载（或非常早期的订阅数据缺少 extra_data）才使用 yt-dlp + 浏览器刷新 token 逻辑
        if not used_api_fallback:
            try:
                if not preheated_cookie:
                    await _preheat_xhs_cookie("ytdlp-first-attempt")
                    preheated_cookie = True
                video_info = await parse_xiaohongshu_with_ytdlp(url_for_ydl)
            except Exception as parse_err:
                err_str = str(parse_err)
                if "No video formats" in err_str and custom_download_dir and subscription_video:
                    await _ensure_xhs_cookie_file(force_refresh=True)
                    note_id = _xhs_note_id_from_url(url)
                    extra = json.loads((subscription_video.extra_data or "{}"))
                    xsec_token = (extra.get("xsec_token") or "").strip()
                    if note_id and xsec_token:
                        from routers.unified_browser_manager import unified_browser
                        from routers.xhsapi import xhs_api
                        try:
                            # 串行化：多任务共享同一 page，同时 goto 会触发 Execution context destroyed
                            async with _xhs_browser_lock:
                                async with unified_browser.task_context("xiaohongshu", "xhs_download_feed"):
                                    await xhs_api.init_browser()
                                    # 如果磁盘 cookie 已过时，从浏览器导出最新 cookie 覆盖文件，确保 a1 新鲜
                                    if not _has_valid_xhs_cookie():
                                        try:
                                            cookie_text = await xhs_api.export_cookies_netscape(force_refresh=True)
                                            if cookie_text:
                                                xhs_cookie_path = "/app/database/cookie/xiaohongshu_cookie.txt"
                                                os.makedirs(os.path.dirname(xhs_cookie_path), exist_ok=True)
                                                tmp_path = xhs_cookie_path + ".tmp"
                                                with open(tmp_path, "w", encoding="utf-8") as f:
                                                    f.write(cookie_text)
                                                os.replace(tmp_path, xhs_cookie_path)
                                        except Exception as e:
                                            logger.debug("[xiaohongshu] 订阅下载导出 cookie 失败（忽略）: %s", e)
                                    profile_url = None
                                    sub = db.query(Subscription).filter(Subscription.id == subscription_video.subscription_id).first()
                                    if sub:
                                        profile_url = getattr(sub, "profile_url", None) or ""
                                    if profile_url and "xsec_token" in profile_url and xhs_api.page:
                                        await xhs_api.page.goto(profile_url, wait_until="networkidle", timeout=20000)
                                        await asyncio.sleep(0.6)
                                        logger.debug("[xiaohongshu] 已打开订阅 profile 建立会话 note_id=%s", note_id)
                                    if xhs_api.page and not video_info:
                                        fresh_token = await _do_refresh_xhs_token(xhs_api.page, note_id)
                                        if fresh_token:
                                            explore_for_ydl = f"https://www.xiaohongshu.com/explore/{note_id}?xsec_token={fresh_token}&xsec_source=pc_feed"
                                            if not preheated_cookie:
                                                await _preheat_xhs_cookie("ytdlp-refresh-token")
                                                preheated_cookie = True
                                            video_info = await parse_xiaohongshu_with_ytdlp(explore_for_ydl)
                                            if video_info:
                                                url_for_ydl = explore_for_ydl
                                                logger.info("[xiaohongshu] 已用浏览器访问笔记页获取当前 token，yt-dlp 解析成功（无水印） note_id=%s", note_id)
                        except Exception as api_err:
                            logger.warning("[xiaohongshu] feed 直链兜底异常: %s", api_err)
                elif "No video formats" in err_str and not (custom_download_dir and subscription_video):
                    note_id = _xhs_note_id_from_url(url)
                    if note_id:
                        fresh_token = await _refresh_xhs_token(note_id)
                        if fresh_token:
                            if not preheated_cookie:
                                await _preheat_xhs_cookie("ytdlp-refresh-token-manual")
                                preheated_cookie = True
                            explore_for_ydl = f"https://www.xiaohongshu.com/explore/{note_id}?xsec_token={fresh_token}&xsec_source=pc_feed"
                            video_info = await parse_xiaohongshu_with_ytdlp(explore_for_ydl)
                            if video_info:
                                url_for_ydl = explore_for_ydl
                                logger.info("[xiaohongshu] 手动下载已用浏览器访问笔记页获取当前 token，yt-dlp 解析成功（无水印） note_id=%s", note_id)
                if not used_api_fallback and not video_info and stream_fallback_url and stream_fallback_note_card:
                    try:
                        if stream_fallback_subscription:
                            download_dir = custom_download_dir
                        else:
                            download_dir = "/app/downloads/xiaohongshu"
                        os.makedirs(download_dir, exist_ok=True)
                        save_path = f"{download_dir}/{task_id}.mp4"
                        async with httpx.AsyncClient() as client:
                            resp = await client.get(stream_fallback_url, timeout=60.0)
                            resp.raise_for_status()
                            with open(save_path, "wb") as f:
                                f.write(resp.content)

                        note_card = stream_fallback_note_card
                        video_info = VideoInfo(
                            video_id=stream_fallback_note_id or "",
                            platform=Platform.XIAOHONGSHU,
                            share_url=url,
                            download_url=stream_fallback_url,
                            title=(stream_fallback_title or "小红书视频")[:200],
                            author=(stream_fallback_author or "未知作者")[:100],
                            create_time=stream_fallback_publish_time.strftime("%Y-%m-%d %H:%M:%S") if stream_fallback_publish_time else None,
                            thumbnail_url=stream_fallback_thumb,
                        )
                        used_api_fallback = True
                        logger.info("[xiaohongshu] ytdlp 失败，回退 stream 直链下载（可能有水印）: %s", (stream_fallback_title or stream_fallback_note_id or "")[:50])
                    except Exception as fallback_err:
                        logger.warning("[xiaohongshu] stream 直链回退失败: %s", fallback_err)
                if not used_api_fallback and not video_info:
                    raise parse_err

        if not video_info:
            update_xhs_task_progress(task_id, TaskStatus.ERROR, error="无法解析视频信息")
            return False

        if custom_download_dir and subscription_video and not used_api_fallback:
            if subscription_video.title and subscription_video.title.strip():
                logger.debug(f"[xiaohongshu] 使用数据库中的完整标题: {subscription_video.title}")
                video_info.title = subscription_video.title.strip()
            if subscription_video.publish_time:
                video_info.create_time = subscription_video.publish_time.strftime('%Y-%m-%d %H:%M:%S')
                logger.debug(f"[xiaohongshu] 从数据库获取发布时间: {video_info.create_time}")

        if custom_download_dir:
            download_dir = custom_download_dir
        else:
            download_dir = "/app/downloads/xiaohongshu"
        os.makedirs(download_dir, exist_ok=True)
        filename = task_id
        save_path = f"{download_dir}/{filename}.mp4"

        if not used_api_fallback:
            # 使用 yt-dlp 直接下载（显式传入 URL，避免 run_in_executor 闭包在线程中未拿到浏览器刷新后的 url_for_ydl）
            download_url = url_for_ydl
            if download_url != url:
                logger.info("[xiaohongshu] 使用浏览器刷新后的链接进行 yt-dlp 下载 note_id=%s", video_info.video_id if video_info else "")
            ydl_opts = {
                'format': 'best',
                'quiet': True,
                'no_warnings': True,
                'noprogress': True,
                'outtmpl': save_path.replace('.mp4', '.%(ext)s'),
                'merge_output_format': 'mp4',
                'no_cache_dir': True,
                'user_agent': XHS_DESKTOP_UA,
                'http_headers': _xhs_ydl_headers(download_url),
                'retries': 2,
                'fragment_retries': 2,
                'file_access_retries': 2,
                'socket_timeout': 20,
            }
            
            # 添加小红书Cookie
            xhs_cookie_file = '/app/database/cookie/xiaohongshu_cookie.txt'
            if os.path.exists(xhs_cookie_file):
                with open(xhs_cookie_file, 'r', encoding='utf-8') as f:
                    if f.read().strip():
                        ydl_opts['cookiefile'] = xhs_cookie_file

            progress_state = {"last_update_time": 0}
            def progress_hook(d):
                if d['status'] == 'downloading':
                    try:
                        total = d.get('total_bytes') or d.get('total_bytes_estimate', 0)
                        downloaded = d.get('downloaded_bytes', 0)
                        if total > 0:
                            progress = (downloaded / total) * 100
                            now_ts = time.time()
                            if (now_ts - progress_state["last_update_time"]) >= 0.3:
                                update_xhs_task_progress(task_id, TaskStatus.DOWNLOADING, progress=progress)
                                progress_state["last_update_time"] = now_ts
                    except Exception:
                        pass
                elif d['status'] == 'finished':
                    update_xhs_task_progress(task_id, TaskStatus.DOWNLOADING, progress=100.0)
            ydl_opts['progress_hooks'] = [progress_hook]
            if xhs_cancel_flags.get(task_id):
                update_xhs_task_progress(task_id, TaskStatus.CANCELLED, error="Download canceled by user.")
                return False
            def download_with_suppressed_output(url_to_download):
                with redirect_stdout(StringIO()), redirect_stderr(StringIO()):
                    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                        ydl.download([url_to_download])

            def _mask_xhs_url(u: str) -> str:
                try:
                    parsed = urlparse(u)
                    qs = parse_qs(parsed.query)
                    token = (qs.get("xsec_token") or [""])[0]
                    if token:
                        qs["xsec_token"] = [_mask_xsec_token(token)]
                    query = "&".join(
                        f"{k}={v[0]}" if v else f"{k}="
                        for k, v in qs.items()
                    )
                    return parsed._replace(query=query).geturl()
                except Exception:
                    return u

            async def _try_download_once(url_to_download: str):
                loop = asyncio.get_event_loop()
                await loop.run_in_executor(None, lambda: download_with_suppressed_output(url_to_download))

            try:
                logger.info(
                    "[xiaohongshu] 下载阶段首次下载URL: %s",
                    _mask_xhs_url(download_url),
                )
                await _try_download_once(download_url)
            except Exception as e:
                err_str = str(e)
                if "No video formats" in err_str:
                    logger.warning(
                        "[xiaohongshu] 下载阶段 No video formats，刷新 cookie 后重试下载 (fail_stage=download, task_id=%s): %s",
                        task_id,
                        err_str[:120],
                    )
                    await _ensure_xhs_cookie_file(force_refresh=True)
                    try:
                        logger.info(
                            "[xiaohongshu] 下载阶段 cookie 重试下载URL (fail_stage=download, task_id=%s): %s",
                            task_id,
                            _mask_xhs_url(download_url),
                        )
                        await _try_download_once(download_url)
                        logger.info(
                            "[xiaohongshu] 下载阶段 cookie 刷新后重试下载成功 (task_id=%s)",
                            task_id,
                        )
                    except Exception as e2:
                        err2 = str(e2)
                        if "No video formats" in err2:
                            logger.warning(
                                "[xiaohongshu] 下载阶段 cookie 刷新后仍 No video formats，准备刷新 token 再试 (fail_stage=download, task_id=%s): %s",
                                task_id,
                                err2[:120],
                            )
                            # 尝试刷新 token 后再下载一次，尽量对齐手动重试逻辑
                            fresh_token = ""
                            note_id = _xhs_note_id_from_url(url)
                            if note_id:
                                try:
                                    from routers.unified_browser_manager import unified_browser
                                    from routers.xhsapi import xhs_api
                                    async with _xhs_browser_lock:
                                        async with unified_browser.task_context("xiaohongshu", "xhs_refresh_token_download"):
                                            await xhs_api.init_browser()
                                            if xhs_api.page:
                                                fresh_token = await _do_refresh_xhs_token(xhs_api.page, note_id)
                                except Exception as token_err:
                                    logger.debug("[xiaohongshu] 下载阶段浏览器取 token 失败: %s", token_err)

                            if fresh_token:
                                logger.info(
                                    "[xiaohongshu] 下载阶段刷新 token 成功 (fail_stage=token_refresh, task_id=%s) note_id=%s new=%s",
                                    task_id,
                                    note_id,
                                    _mask_xsec_token(fresh_token),
                                )
                                download_url = f"https://www.xiaohongshu.com/explore/{note_id}?xsec_token={fresh_token}&xsec_source=pc_feed"
                                await _ensure_xhs_cookie_file(force_refresh=True)
                                try:
                                    logger.info(
                                        "[xiaohongshu] 下载阶段 token 重试下载URL (fail_stage=token_refresh, task_id=%s): %s",
                                        task_id,
                                        _mask_xhs_url(download_url),
                                    )
                                    await _try_download_once(download_url)
                                    logger.info(
                                        "[xiaohongshu] 下载阶段 token 刷新后重试下载成功 (task_id=%s) note_id=%s",
                                        task_id,
                                        note_id,
                                    )
                                except Exception as e3:
                                    logger.warning(
                                        "[xiaohongshu] 下载阶段 token 刷新后仍失败 (fail_stage=token_refresh, task_id=%s) note_id=%s: %s",
                                        task_id,
                                        note_id,
                                        str(e3)[:120],
                                    )
                                    raise
                            else:
                                raise e2
                        else:
                            raise
                else:
                    raise
            if xhs_cancel_flags.get(task_id):
                if os.path.exists(save_path):
                    try:
                        os.remove(save_path)
                    except Exception:
                        pass
                update_xhs_task_progress(task_id, TaskStatus.CANCELLED, error="Download canceled by user.")
                return False

        # 检查下载的文件（yt-dlp 或 API 直链写入）
        video_path = None
        for ext in ['mp4', 'webm', 'mkv', 'avi', 'mov']:
            test_path = save_path.replace('.mp4', f'.{ext}')
            if os.path.exists(test_path):
                video_path = test_path
                if ext != 'mp4':
                    os.rename(test_path, save_path)
                break
        # 兜底：处理 yt-dlp 输出为 unknown_video 或其它非预期扩展名
        if not video_path:
            try:
                import glob
                candidates = sorted(glob.glob(save_path.replace('.mp4', '.*')))
                for candidate in candidates:
                    if candidate.endswith(('.part', '.temp', '.ytdl')):
                        continue
                    if os.path.exists(candidate) and os.path.getsize(candidate) > 0:
                        video_path = candidate
                        # 统一重命名为 .mp4 以匹配后续流程
                        if candidate != save_path:
                            os.rename(candidate, save_path)
                        break
            except Exception:
                pass
        if not video_path and not os.path.exists(save_path):
            update_xhs_task_progress(task_id, TaskStatus.ERROR, error="下载文件未找到")
            return False

        # 重命名和刮削（订阅时复用前面已查的 subscription_video）
        subscription_info = None
        if custom_download_dir and subscription_video:
            subscription = db.query(Subscription).filter(
                Subscription.id == subscription_video.subscription_id
            ).first()
            if subscription:
                subscription_info = {
                    'platform': subscription.platform,
                    'nickname': subscription.nickname
                }
        
        # 订阅下载始终生成NFO，手动下载根据generate_nfo参数决定
        # 如果custom_download_dir存在，说明是订阅下载，generate_nfo参数会被忽略（始终生成）
        filename_base = rename_and_scrape(task_id, video_info, download_dir, subscription_info, generate_nfo)
        
        # 下载缩略图
        if video_info.thumbnail_url:
            thumbnail_path = os.path.join(download_dir, filename_base, f'{filename_base}-poster.jpg')
            await download_thumbnail_async(video_info.thumbnail_url, thumbnail_path)
        
        # 构建最终文件路径
        if custom_download_dir:
            relative_path = custom_download_dir.replace('/app/downloads/', '')
            filename_path = f'{relative_path}/{filename_base}/{filename_base}.mp4'
        else:
            filename_path = f'xiaohongshu/{filename_base}/{filename_base}.mp4'
        
        update_xhs_task_progress(task_id, TaskStatus.COMPLETED, progress=100.0, filename=filename_path)
        
        # 更新订阅视频状态
        video = db.query(SubscriptionVideo).filter(
            SubscriptionVideo.download_task_id == task_id
        ).first()
        if video:
            video.downloaded = "true"
            db.commit()
        
        # 下载完成发送通知逻辑
        try:
            db_notify = next(get_db())
            try:
                task_notify = db_notify.query(Task).filter(Task.id == task_id).first()
                if task_notify:
                    db_notify.refresh(task_notify)
                
                # 1. 准备基础数据
                n_video_title = task_notify.title if task_notify and task_notify.title and not task_notify.title.startswith('http') else (video_info.title if video_info else "未知视频")
                n_author_name = "手动下载"
                n_platform_name = "小红书"
                n_current_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                
                # 2. 如果是订阅下载，丰富信息
                n_subscription_id = None
                if custom_download_dir:
                    video_rec = db_notify.query(SubscriptionVideo).filter(SubscriptionVideo.download_task_id == task_id).first()
                    if video_rec:
                        n_subscription_id = video_rec.subscription_id
                        sub_rec = db_notify.query(Subscription).filter(Subscription.id == video_rec.subscription_id).first()
                        if sub_rec:
                            n_author_name = f"订阅博主: {sub_rec.nickname or '未知'}"
                
                # 3. 获取封面图
                extra_data = {}
                try:
                    # 查找本地封面图
                    poster_path = os.path.join(download_dir, filename_base, f'{filename_base}-poster.jpg')
                    if os.path.exists(poster_path):
                        # 构造相对路径供通知服务使用
                        if custom_download_dir:
                            relative_path = custom_download_dir.replace('/app/downloads/', '')
                            relative_poster_path = f"{relative_path}/{filename_base}/{filename_base}-poster.jpg"
                        else:
                            relative_poster_path = f"xiaohongshu/{filename_base}/{filename_base}-poster.jpg"
                        
                        if not relative_poster_path.startswith('/'):
                            relative_poster_path = f"/downloads/{relative_poster_path}"
                        
                        extra_data["cover"] = relative_poster_path
                        logger.debug(f"[xiaohongshu] 通知将包含海报: {relative_poster_path}")
                except Exception as _e:
                    logger.warning(f"[xiaohongshu] 查找海报路径失败: {str(_e)}")

                if n_subscription_id:
                    extra_data["subscription_id"] = n_subscription_id

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
        except Exception as notify_err:
            logger.warning(f"[xiaohongshu] 通知处理异常: {notify_err}")
            
        return True
        
    except Exception as e:
        err_str = str(e)
        if (not retry_once) and ("No video formats" in err_str):
            logger.warning(
                "[xiaohongshu] 下载失败触发兜底重试 (task_id=%s, note_url=%s): %s",
                task_id,
                url,
                err_str[:120],
            )
            try:
                update_xhs_task_progress(task_id, TaskStatus.DOWNLOADING, progress=0.0)
            except Exception:
                pass
            await asyncio.sleep(5)
            return await xhs_download_video_logic(
                task_id,
                url,
                custom_download_dir,
                generate_nfo,
                retry_once=True
            )
        if "No video formats" in err_str and custom_download_dir:
            logger.warning("[xiaohongshu] 下载失败（多为库内链接 token 已过期，可重试或等下次同步）: %s", err_str[:200])
        else:
            logger.error("[xiaohongshu] 下载视频失败: %s", err_str)
        
        # 发送失败通知
        try:
            def send_fail_notify():
                try:
                    async def send():
                        connector = aiohttp.UnixConnector(path="/app/sockets/easy-vdl.sock")
                        async with aiohttp.ClientSession(connector=connector) as session:
                             await session.post("http://localhost/api/notifications/download-error", json={
                                "title": "❌ 下载失败 (小红书)",
                                "content": f"小红书下载出错\n🚫 错误: {str(e)[:200]}\n🆔 任务: {task_id}",
                                "user_id": "default",
                                "extra_data": {
                                    "task_id": task_id,
                                    "url": url,
                                    "subscription_id": (subscription_video.subscription_id if subscription_video else None)
                                }
                            })
                    loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(loop)
                    loop.run_until_complete(send())
                except: pass
            threading.Thread(target=send_fail_notify, daemon=True).start()
        except: pass

        # 更新订阅视频状态为失败
        video = db.query(SubscriptionVideo).filter(
            SubscriptionVideo.download_task_id == task_id
        ).first()
        if video:
            video.downloaded = "false"
            video.error_message = str(e)
            db.commit()
        
        update_xhs_task_progress(task_id, TaskStatus.ERROR, error=str(e))
        return False

@router.post("/api/xhs/download")
async def xhs_server_download(request: DownloadRequest, current_user: User = Depends(get_current_user_or_token), db: Session = Depends(get_db)):
    """小红书视频下载接口"""
    url = request.url
    generate_nfo = request.generate_nfo  # 获取NFO生成参数
    if not url:
        raise HTTPException(status_code=400, detail="url不能为空")
    
    task_id = str(uuid.uuid4())
    now = now_beijing()
    task = Task(
        id=task_id,
        source='xiaohongshu',
        url=url,
        status=TaskStatus.PENDING.value,
        progress=0.0,
        created_at=now,
        updated_at=now
    )
    db.add(task)
    db.commit()
    xhs_cancel_flags[task_id] = False

    asyncio.create_task(xhs_download_video_logic(task_id, url, None, generate_nfo))

    return {"status": "success", "taskId": task_id}

@router.post("/api/xhs/parse")
async def xhs_parse_video(
    video_request: VideoRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """小红书视频解析API（使用 yt-dlp）"""
    body = await request.body()
    logger.debug(f"[xiaohongshu] 收到解析请求: {video_request.url}")
    
    if not await rate_limiter.can_make_request():
        raise HTTPException(
            status_code=429,
            detail={
                "message": "请求过于频繁，请稍后再试",
                "retry_after": rate_limiter.time_window
            }
        )
    
    try:
        url = video_request.url.strip()
        if not url:
            raise HTTPException(status_code=400, detail="URL不能为空")
        
        # 使用 yt-dlp 解析
        try:
            video_info = await parse_xiaohongshu_with_ytdlp(url)
        except CookieNotConfiguredError as e:
            raise HTTPException(
                status_code=400,
                detail={
                    "status": "error",
                    "code": "COOKIE_NOT_CONFIGURED",
                    "message": str(e),
                    "redirect": "/settings?tab=cookie"
                }
            )

        response_data = {
            "status": "success",
            "platform": video_info.platform,
            "type": "video",
            "video_url": video_info.download_url,
            "original_url": video_info.share_url
        }
        if video_info.title:
            response_data["title"] = video_info.title
        if video_info.author:
            response_data["author"] = video_info.author
        if video_info.thumbnail_url:
            response_data["thumbnail_url"] = video_info.thumbnail_url
        
        usage_stats["successful_requests"] += 1
        today = datetime.now().date().isoformat()
        if today not in usage_stats["daily_stats"]:
            usage_stats["daily_stats"][today] = {"success": 0, "failed": 0}
        usage_stats["daily_stats"][today]["success"] += 1
        
        logger.info(f"[xiaohongshu] 解析成功: {video_info.title if video_info.title else '未知标题'}")
        return response_data
        
    except HTTPException as he:
        usage_stats["failed_requests"] += 1
        today = datetime.now().date().isoformat()
        if today not in usage_stats["daily_stats"]:
            usage_stats["daily_stats"][today] = {"success": 0, "failed": 0}
        usage_stats["daily_stats"][today]["failed"] += 1
        logger.error(f"[xiaohongshu] HTTP错误: {he.detail}")
        raise he
    except Exception as e:
        usage_stats["failed_requests"] += 1
        today = datetime.now().date().isoformat()
        if today not in usage_stats["daily_stats"]:
            usage_stats["daily_stats"][today] = {"success": 0, "failed": 0}
        usage_stats["daily_stats"][today]["failed"] += 1
        logger.error(f"[xiaohongshu] 解析失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"解析失败: {str(e)}")

@router.post("/api/xhs/note_info_full")
async def xhs_note_info_full(
    video_request: VideoRequest,
    current_user: User = Depends(get_current_user)
):
    """获取小红书笔记完整 JSON（feed 原始返回）"""
    if not await rate_limiter.can_make_request():
        raise HTTPException(
            status_code=429,
            detail={
                "message": "请求过于频繁，请稍后再试",
                "retry_after": rate_limiter.time_window
            }
        )

    url = (video_request.url or "").strip()
    if not url:
        raise HTTPException(status_code=400, detail="URL不能为空")

    from routers.xhsapi import xhs_api
    from routers.unified_browser_manager import unified_browser

    try:
        async with _xhs_browser_lock:
            async with unified_browser.task_context("xiaohongshu", "xhs_note_info_full"):
                await xhs_api.init_browser()
                data = await xhs_api.get_note_info_full(url)
        return {"status": "success", "data": data}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.warning("[xiaohongshu] note_info_full 失败: %s", e)
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/api/xhs/health")
async def xhs_health_check():
    """健康检查端点"""
    return {"status": "ok", "service": "xiaohongshu-service"}

@router.get("/api/xhs/stats")
async def xhs_get_stats(current_user: User = Depends(get_current_user)):
    """获取使用统计"""
    return usage_stats


@router.post("/api/xhs/cancel/{task_id}")
async def xhs_cancel_download(task_id: str, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """取消下载任务"""
    task = db.query(Task).filter(Task.id == task_id).first()
    if not task or task.status in [TaskStatus.COMPLETED.value, TaskStatus.ERROR.value, TaskStatus.CANCELLED.value]:
        raise HTTPException(status_code=404, detail="任务不存在或已完成，无法取消。")
    
    # 设置取消标志
    xhs_cancel_flags[task_id] = True
    
    # 更新任务状态为已取消
    update_xhs_task_progress(task_id, TaskStatus.CANCELLED, error="Download canceled by user.")
    
    return {"message": "Cancellation request sent."}
