import uuid
import json
from fastapi import APIRouter, BackgroundTasks, HTTPException, Depends, Response, Query
from pydantic import BaseModel
import yt_dlp
import os
import shutil
from enum import Enum
from sqlalchemy.orm import Session
from datetime import datetime, timezone, timedelta
import sys
import re
import time
import xml.etree.ElementTree as ET
from xml.dom import minidom
import time
import xml.sax.saxutils as saxutils
import requests
import subprocess
from typing import Optional
from urllib.parse import parse_qs, urlparse
import asyncio
import logging
import gc  # 用于强制垃圾回收
# WebSocket进度更新由批量下载管理器处理，不需要直接导入

# 配置日志
logger = logging.getLogger(__name__)

# 导入共享模型和数据库函数
# sys.path.append('/app') # 这一行在主应用中处理
from sql.models import Task, TaskStatus, SubscriptionVideo, Subscription, User
from sql.database_postgresql import get_db
from routers.auth import get_current_user, get_current_user_optional, get_current_user_or_token
from routers.license import license_manager
from routers.unified_browser_manager import unified_browser

# 创建APIRouter实例
router = APIRouter()

# 使用 Python 默认线程池执行 yt_dlp 的 I/O 密集型操作
# 注意：yt-dlp 主要是 I/O 密集型而非 CPU 密集型，不需要自定义线程池
import time
import asyncio
import logging

logger = logging.getLogger(__name__)

# 全局信号量：限制自动字幕请求的并发，降低429风险
# 仅在需要自动字幕时使用该限流
_AUTO_SUBTITLE_SEMAPHORE = asyncio.Semaphore(5)

_BV_PATTERN = re.compile(r'BV[0-9A-Za-z]{10}')


def _extract_bvid_from_url(url: str) -> Optional[str]:
    if not url:
        return None

    parsed = urlparse(url)
    query = parse_qs(parsed.query)
    query_bvid = query.get("bvid", [])
    if query_bvid and query_bvid[0]:
        return query_bvid[0]

    m = _BV_PATTERN.search(url)
    if m:
        return m.group(0)
    return None


def _extract_bilibili_page_from_url(url: str) -> Optional[str]:
    if not url:
        return None
    try:
        parsed = urlparse(url)
        query = parse_qs(parsed.query)
        page_values = query.get("p", [])
        if not page_values:
            return None
        page = str(page_values[0]).strip()
        if not page:
            return None
        return page
    except Exception:
        return None


def _attach_bilibili_page(url: str, page: Optional[str]) -> str:
    if not url or not page:
        return url
    try:
        parsed = urlparse(url)
        query = parse_qs(parsed.query)
        query["p"] = [page]
        encoded_query = "&".join([f"{k}={v[0]}" for k, v in query.items() if v])
        return parsed._replace(query=encoded_query).geturl()
    except Exception:
        sep = "&" if "?" in url else "?"
        return f"{url}{sep}p={page}"


def _normalize_bilibili_video_url(url: str) -> str:
    if not url or "bilibili.com" not in url:
        return url
    bvid = _extract_bvid_from_url(url)
    if not bvid:
        return url
    page = _extract_bilibili_page_from_url(url)
    normalized = f"https://www.bilibili.com/video/{bvid}"
    return _attach_bilibili_page(normalized, page)


def _resolve_bilibili_url_without_browser(url: str) -> str:
    """轻量解析：只用标准video链接 + API/HTTP，不触发浏览器。"""
    normalized = _normalize_bilibili_video_url(url)
    page = _extract_bilibili_page_from_url(normalized) or _extract_bilibili_page_from_url(url)
    resolved = normalized

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
        ),
        "Referer": "https://www.bilibili.com/",
    }

    try:
        resp = requests.get(normalized, headers=headers, timeout=8, allow_redirects=True)
        if resp.url and "bilibili.com" in resp.url:
            resolved = resp.url
    except Exception:
        pass

    bvid = _extract_bvid_from_url(normalized)
    if not bvid:
        return resolved

    try:
        api_url = f"https://api.bilibili.com/x/web-interface/view?bvid={bvid}"
        api_resp = requests.get(api_url, headers=headers, timeout=8)
        if api_resp.ok:
            data = api_resp.json().get("data") or {}
            redirect_url = data.get("redirect_url")
            if redirect_url and "bilibili.com" in redirect_url:
                resolved = _attach_bilibili_page(redirect_url, page)
    except Exception:
        pass

    return _attach_bilibili_page(resolved, page)


def _need_bilibili_browser_fallback(error_msg: str) -> bool:
    text = (error_msg or "").lower()
    keywords = [
        "unable to extract initial state",
        "unsupported url",
        "unable to extract webpage",
        "unable to download webpage",
        "festival",
    ]
    return any(k in text for k in keywords)


async def _resolve_bilibili_url_via_browser(url: str, task_id: str) -> Optional[str]:
    page_key = f"bilibili:ytd_resolve:{task_id}"
    try:
        async with unified_browser.task_context("bilibili", "ytd_resolve"):
            page = await unified_browser.get_page(page_key, auto_create=True)
            if not page:
                return None
            await page.goto(url, wait_until="domcontentloaded", timeout=25000)
            await page.wait_for_timeout(1200)
            final_url = page.url
            if final_url and "bilibili.com" in final_url:
                return final_url
    except Exception:
        return None
    finally:
        try:
            await unified_browser.close_page(page_key)
        except Exception:
            pass
    return None

def _extract_info_sync(u: str, opts: dict):
    """子进程中执行yt_dlp信息提取，避免阻塞事件循环"""
    import yt_dlp  # 进程内导入，避免主进程模块状态共享
    try:
        with yt_dlp.YoutubeDL(opts) as ydl_info:
            return ydl_info.extract_info(u, download=False)
    except Exception as e:
        # 将异常转换为可序列化的字符串，避免pickle错误
        error_msg = str(e)
        error_type = type(e).__name__
        # 返回错误信息而不是抛出异常
        return {"error": True, "error_type": error_type, "error_message": error_msg}

def _detect_subtitles_sync(video_info: dict):
    """线程池中执行字幕检测，避免阻塞主线程"""
    has_manual_subtitles = False
    has_auto_subtitles = False

    # 语言优先级：中文优先，英文兜底
    zh_priority = ['zh-Hans', 'zh-CN', 'zh', 'zh-Hant', 'zh-TW', 'zh-HK']
    en_priority = ['en', 'en-US', 'en-GB']

    def _select_subtitle_langs(lang_keys):
        """从可用语言中按优先级选出下载语言，提高字幕命中率。"""
        if not lang_keys:
            return []

        available = [k for k in lang_keys if k]
        if not available:
            return []

        selected = []
        lower_to_original = {k.lower(): k for k in available}

        def pick_exact(candidates):
            for code in candidates:
                hit = lower_to_original.get(code.lower())
                if hit and hit not in selected:
                    selected.append(hit)
                    return True
            return False

        # 1) 优先精确匹配 zh / en 常见代码
        pick_exact(zh_priority)
        pick_exact(en_priority)

        # 2) 若无精确匹配，降级为前缀匹配（兼容如 zh-Hans-orig / en-orig）
        if not any(lang.lower().startswith('zh') for lang in selected):
            for key in available:
                if key.lower().startswith('zh'):
                    selected.append(key)
                    break

        if not any(lang.lower().startswith('en') for lang in selected):
            for key in available:
                if key.lower().startswith('en'):
                    selected.append(key)
                    break

        # 3) 若仍未选中，返回空让上层按“无字幕”处理
        return selected

    manual_langs = []
    auto_langs = []

    # 优先检查手动字幕（质量更高，429错误概率较低）
    if 'subtitles' in video_info and video_info['subtitles']:
        manual_langs = _select_subtitle_langs(video_info['subtitles'].keys())
        has_manual_subtitles = len(manual_langs) > 0

    # 若无手动字幕，检测是否存在自动字幕（作为降级）
    if (not has_manual_subtitles) and ('automatic_captions' in video_info) and video_info['automatic_captions']:
        auto_langs = _select_subtitle_langs(video_info['automatic_captions'].keys())
        has_auto_subtitles = len(auto_langs) > 0
    
    return {
        'has_manual_subtitles': has_manual_subtitles,
        'has_auto_subtitles': has_auto_subtitles,
        'manual_langs': manual_langs,
        'auto_langs': auto_langs
    }

async def initialize_ytd_service():
    """初始化YTD服务"""
    # YTD服务使用 no_cache_dir=True 禁用缓存，无需创建缓存目录.
    return True

# --- Pydantic Models ---
class VideoInfoRequest(BaseModel):
    url: str
    youtube_cookie: str = ""
    bilibili_cookie: str = ""
    proxy: Optional[str] = None  # 修改这里，使用Optional允许None值

class DownloadRequest(BaseModel):
    url: str
    format_id: Optional[str] = "bestvideo+bestaudio"  # 默认最高画质，可选
    youtube_cookie: str = ""
    bilibili_cookie: str = ""
    proxy: Optional[str] = None  # 修改这里，使用Optional允许None值
    subtitles: bool = True
    thumbnail: bool = True
    subscription_id: Optional[str] = None  # 添加订阅ID支持

class ProxyTestRequest(BaseModel):
    proxy: str
    test_url: str = "https://httpbin.org/ip"  # 使用更轻量的测试网站

# --- Helper Functions ---
def now_beijing():
    return datetime.now(timezone(timedelta(hours=8)))

def create_task_in_db(db: Session, task_id: str, url: str, proxy: str = None, youtube_cookie: str = None, bilibili_cookie: str = None, format_id: str = None, subscription_id: str = None):
    now = now_beijing()
    # 根据URL判断来源
    source = "youtube" if 'youtube.com' in url or 'youtu.be' in url else ("bilibili" if 'bilibili.com' in url else "unknown")
    
    # 修改cookie处理逻辑，确保空字符串不会被当作有效cookie
    youtube_cookie = youtube_cookie if youtube_cookie and youtube_cookie.strip() else None
    bilibili_cookie = bilibili_cookie if bilibili_cookie and bilibili_cookie.strip() else None
    cookie = youtube_cookie if source == "youtube" else (bilibili_cookie if source == "bilibili" else None)
    
    new_task = Task(
        id=task_id,
        source=source,
        url=url,
        status=TaskStatus.PENDING.value,
        progress=0.0,
        filename=None,
        error_message=None,
        created_at=now,
        updated_at=now,
        proxy=proxy,
        cookie=cookie,
        format_id=format_id,
        subscription_id=subscription_id  # 添加订阅ID支持
    )
    db.add(new_task)
    db.commit()
    db.refresh(new_task)

_progress_throttle_state = {}
_progress_ws_throttle_state = {}
_PROGRESS_WS_MIN_INTERVAL_SEC = 0.5
_PROGRESS_WS_MIN_DELTA = 0.5


def _send_downloads_ws_update(progress_data: dict):
    """统一发送下载进度 WebSocket 消息（线程/协程安全）"""
    try:
        import asyncio
        from routers.websocket import broadcast_message

        async def send_progress_update():
            try:
                await broadcast_message('downloads', progress_data)
            except Exception as e:
                logging.warning(f"发送WebSocket进度更新失败: {str(e)}")

        try:
            loop = asyncio.get_running_loop()
            task = asyncio.create_task(send_progress_update())
            _background_tasks.add(task)
            task.add_done_callback(_background_tasks.discard)
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                loop.run_until_complete(send_progress_update())
            finally:
                loop.close()
    except Exception as e:
        logging.warning(f"WebSocket进度更新失败: {str(e)}")


def update_task_progress(
    task_id: str,
    status,
    progress: float = None,
    filename: str = None,
    error: str = None,
    subscription_id: str = None,
    send_error_notification: bool = True
):
    """更新任务进度和状态（双层节流）

    节流策略：
    - 终态（COMPLETED / ERROR / CANCELLED）永远不过滤，必须写库。
    - 中间态（PENDING / DOWNLOADING / PROCESSING）：
      - 默认至少每2秒才会真正落库一次；
      - 或者进度相比上次变化 >= 3% 时立即落库；
      - DB 节流命中时，允许按轻量阈值直接推送 WS（0.5秒或0.5%）提升前端丝滑度。
    """
    global _progress_throttle_state, _progress_ws_throttle_state

    # 先解析目标状态，便于节流判断
    valid_status = [s.value for s in TaskStatus]
    if isinstance(status, TaskStatus):
        status_str = status.value
    elif isinstance(status, str):
        status_str = status.upper()
        if status_str not in valid_status:
            status_str = TaskStatus.ERROR.value
    else:
        status_str = TaskStatus.ERROR.value

    # 计算安全进度值（用于节流判断，不一定最终写入）
    safe_progress = None
    if progress is not None:
        try:
            safe_progress = float(progress)
            safe_progress = max(0.0, min(100.0, safe_progress))
        except Exception:
            safe_progress = 0.0

    # 对中间态做节流：减少频繁的 DB 写入
    intermediate_statuses = {
        TaskStatus.PENDING.value,
        TaskStatus.DOWNLOADING.value,
        TaskStatus.PROCESSING.value,
    }
    if status_str in intermediate_statuses:
        now_ts = time.time()
        state = _progress_throttle_state.get(task_id)
        last_ts = state["ts"] if state else 0
        last_progress = state["progress"] if state else None

        allow = False
        # 1) 时间阈值：距离上次写库 >= 2 秒
        if now_ts - last_ts >= 2:
            allow = True
        # 2) 进度变化阈值：变化 >= 3%
        elif safe_progress is not None and last_progress is not None:
            if abs(safe_progress - last_progress) >= 3.0:
                allow = True

        if not allow:
            # 方案1：DB 节流命中时，不更新 DB 节流基准，避免“阈值永远达不到”的问题
            # 方案2：增加轻量 WS 节流，提升前端实时感（不落库）
            emit_progress = safe_progress if safe_progress is not None else (last_progress if last_progress is not None else 0.0)
            ws_state = _progress_ws_throttle_state.get(task_id)
            ws_last_ts = ws_state["ts"] if ws_state else 0
            ws_last_progress = ws_state["progress"] if ws_state else None

            ws_allow = False
            if now_ts - ws_last_ts >= _PROGRESS_WS_MIN_INTERVAL_SEC:
                ws_allow = True
            elif ws_last_progress is not None and emit_progress is not None:
                if abs(emit_progress - ws_last_progress) >= _PROGRESS_WS_MIN_DELTA:
                    ws_allow = True

            if ws_allow:
                progress_data = {
                    'type': 'progress_update',
                    'task': {
                        'id': task_id,
                        'progress': emit_progress,
                        'status': status_str,
                        'updated_at': now_beijing().isoformat(),
                    }
                }
                _send_downloads_ws_update(progress_data)
                _progress_ws_throttle_state[task_id] = {
                    "ts": now_ts,
                    "progress": emit_progress,
                }
            return

    # 能走到这里：要么是终态，要么通过了节流条件
    db = next(get_db())
    try:
        task = db.query(Task).filter(Task.id == task_id).first()
        if not task:
            return

        # 保存原有的subscription_id
        original_subscription_id = task.subscription_id

        # 写入状态
        task.status = status_str

        # 写入进度
        if safe_progress is not None:
            task.progress = safe_progress

        # 更新其他字段
        if filename is not None:
            # 对于订阅下载，设置完整的相对路径；对于手动下载，设置完整相对路径
            if subscription_id:
                # 订阅下载：设置完整相对路径，便于联动删除
                relative_path = filename.replace('/app/downloads/', '')
                task.filename = relative_path
            else:
                # 手动下载：设置完整相对路径，便于联动删除
                relative_path = filename.replace('/app/downloads/', '')
                task.filename = relative_path
        if error is not None:
            task.error_message = error
        
        # 确保subscription_id不丢失
        task.subscription_id = subscription_id or original_subscription_id
        task.updated_at = now_beijing()
        
        # 如果是订阅下载，同时更新订阅视频的状态
        if task.subscription_id:
            subscription_video = db.query(SubscriptionVideo).filter(
                SubscriptionVideo.download_task_id == task_id
            ).first()
            if subscription_video:
                if status_str == TaskStatus.COMPLETED.value:
                    subscription_video.downloaded = "true"
                    subscription_video.error_message = None  # 清除错误信息
                    # 通知改为在最终处理（合并+刮削+重命名）完成后统一发送，此处不发送
                        
                elif status_str in [TaskStatus.PENDING.value, TaskStatus.DOWNLOADING.value, TaskStatus.PROCESSING.value]:
                    # 下载开始或进行中时，清除错误信息，但不改变downloaded状态
                    subscription_video.error_message = None
                        
                elif status_str in [TaskStatus.ERROR.value, TaskStatus.CANCELLED.value]:
                    subscription_video.downloaded = "false"
                    subscription_video.error_message = error  # 记录错误信息
                    
                    # 只有在明确要求发送错误通知时才发送
                    if send_error_notification:
                        # 发送下载错误通知
                        try:
                            import aiohttp
                            import asyncio
                        
                            # 在异步函数执行前提取所需的数据，避免Session绑定问题
                            video_title = subscription_video.title
                            video_url = subscription_video.url
                            subscription_id = subscription_video.subscription_id
                            extra_data_str = subscription_video.extra_data
                            
                            # 获取博主信息
                            author_name = "未知"
                            try:
                                # 从订阅信息中获取博主名称
                                subscription = db.query(Subscription).filter(Subscription.id == subscription_id).first()
                                if subscription:
                                    author_name = subscription.nickname or "未知"
                                    logging.info(f"从订阅信息获取到博主名称: {author_name}")
                                else:
                                    logging.warning(f"未找到订阅信息: {subscription_id}")
                                
                                # 如果extra_data中有uploader信息，优先使用
                                if extra_data_str:
                                    import json
                                    try:
                                        extra_data = json.loads(extra_data_str)
                                        logging.info(f"解析extra_data: {extra_data}")
                                        if 'uploader' in extra_data:
                                            author_name = extra_data['uploader']
                                            logging.info(f"从extra_data获取到uploader: {author_name}")
                                    except Exception as e:
                                        logging.warning(f"解析extra_data失败: {str(e)}")
                            except Exception as e:
                                logging.warning(f"获取博主信息失败: {str(e)}")
                            
                            # 异步发送通知
                            async def send_error_notification():
                                try:
                                    # 调用通知接口
                                    notification_url = f"http://unix:/app/sockets/easy-vdl.sock/api/notifications/download-error"
                                    
                                    # 判断平台类型
                                    platform = "YouTube"
                                    if video_url and ('bilibili' in video_url.lower() or 'b23.tv' in video_url.lower()):
                                        platform = "B站"
                                    
                                    # 准备通知数据
                                    notification_data = {
                                        "title": "❌ 订阅下载失败",
                                        "content": f"视频《{video_title}》下载失败！\n\n🏷️ 平台: {platform}\n👤 博主: {author_name}\n🚫 错误信息: {error}\n⏰ 失败时间: {now_beijing().strftime('%Y-%m-%d %H:%M:%S')}",
                                        "user_id": "default",  # 使用默认用户设置
                                        "extra_data": {
                                            "task_id": task_id,
                                            "url": video_url,
                                            "subscription_id": subscription_id
                                        }
                                    }
                                    
                                    # 创建支持 Unix socket 的连接器
                                    connector = aiohttp.UnixConnector(path="/app/sockets/easy-vdl.sock")
                                    
                                    async with aiohttp.ClientSession(connector=connector) as session:
                                        async with session.post("http://localhost/api/notifications/download-error", json=notification_data) as response:
                                            if response.status == 200:
                                                logging.info(f"下载错误通知发送成功: {video_title}")
                                            else:
                                                logging.warning(f"下载错误通知发送失败: {response.status}")
                                except Exception as e:
                                    logging.warning(f"发送下载错误通知异常: {str(e)}")
                            
                            # 检查是否有运行中的事件循环
                            try:
                                loop = asyncio.get_running_loop()
                                task = asyncio.create_task(send_error_notification())
                                _background_tasks.add(task)
                                task.add_done_callback(_background_tasks.discard)
                            except RuntimeError:
                                loop = asyncio.new_event_loop()
                                asyncio.set_event_loop(loop)
                                try:
                                    loop.run_until_complete(send_error_notification())
                                finally:
                                    loop.close()
                                
                        except Exception as e:
                            logging.warning(f"发送下载错误通知失败: {str(e)}")
                            # 不抛出异常，避免影响下载流程
        
        # 提交更改
        db.commit()

        # DB 写库成功后，刷新节流基准
        now_ts = time.time()
        _progress_throttle_state[task_id] = {
            "ts": now_ts,
            "progress": task.progress,
        }
        _progress_ws_throttle_state[task_id] = {
            "ts": now_ts,
            "progress": task.progress,
        }

        # DB 更新后的 WS 推送（全字段）
        should_send_ws = True
        
        if should_send_ws:
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
            _send_downloads_ws_update(progress_data)

        # 终态清理内存节流状态，避免累积
        terminal_statuses = {
            TaskStatus.COMPLETED.value,
            TaskStatus.ERROR.value,
            TaskStatus.CANCELLED.value,
        }
        if status_str in terminal_statuses:
            _progress_throttle_state.pop(task_id, None)
            _progress_ws_throttle_state.pop(task_id, None)

    finally:
        try:
            db.rollback()
        except Exception:
            pass
        db.close()

# --- Download Logic ---
cancel_flags = {}

# 全局 Task 集合，用于跟踪后台任务，防止内存泄露
_background_tasks = set()

def sanitize_filename(filename, max_length=80):
    """清理文件名，只做最基本的文件系统兼容性处理"""
    try:
        # 确保输入是字符串
        filename = str(filename)
        # 只移除文件系统不允许的字符
        filename = re.sub(r'[\\/:*?"<>|]', '_', filename)
        # 移除控制字符
        filename = re.sub(r'[\x00-\x1f\x7f-\x9f]', '', filename)
        # 移除多余空格和换行
        filename = re.sub(r'\s+', ' ', filename).strip()
        # 限制长度
        if len(filename) > max_length:
            filename = filename[:max_length-3] + '...'
        # 如果文件名为空，返回默认值
        return filename if filename else 'unnamed'
    except Exception as e:
        # 文件名清理失败
        return 'unnamed'

def _truncate_utf8_by_bytes(text: str, max_bytes: int) -> str:
    """按UTF-8字节长度截断字符串，避免文件名超过文件系统字节上限。"""
    if not text:
        return ''
    if max_bytes <= 0:
        return ''
    if len(text.encode('utf-8')) <= max_bytes:
        return text

    out_chars = []
    used = 0
    for ch in text:
        ch_len = len(ch.encode('utf-8'))
        if used + ch_len > max_bytes:
            break
        out_chars.append(ch)
        used += ch_len
    return ''.join(out_chars).rstrip()


def _get_fs_name_max(path: str, default: int = 255) -> int:
    """获取目录所在文件系统单个文件名最大字节长度。"""
    try:
        return int(os.pathconf(path, 'PC_NAME_MAX'))
    except Exception:
        return default


def _fit_filename_base_for_sidecars(base: str, save_dir: str, file_ext: str) -> str:
    """
    让 filename_base 在当前文件系统上安全：
    - base + file_ext
    - base + '.nfo'
    - base + '-poster.jpg'
    - base + '.zh-Hans.srt'
    均不超过 NAME_MAX。
    """
    name_max = _get_fs_name_max(save_dir, 255)
    sidecar_suffixes = [
        file_ext or '.mp4',
        '.nfo',
        '-poster.jpg',
        '.zh-Hans.srt',
    ]
    reserve = max(len(s.encode('utf-8')) for s in sidecar_suffixes)
    base_budget = max(16, name_max - reserve)
    fitted = _truncate_utf8_by_bytes(base, base_budget)
    return fitted if fitted else 'unnamed'


def _get_filename_base_budget(save_dir: str, file_ext: str) -> int:
    """获取 filename_base 的安全字节预算（需预留 sidecar 后缀长度）。"""
    name_max = _get_fs_name_max(save_dir, 255)
    sidecar_suffixes = [
        file_ext or '.mp4',
        '.nfo',
        '-poster.jpg',
        '.zh-Hans.srt',
    ]
    reserve = max(len(s.encode('utf-8')) for s in sidecar_suffixes)
    return max(16, name_max - reserve)

def clean_text(text, max_length=2000):
    import re
    import xml.sax.saxutils as saxutils
    # 去除控制字符和emoji
    text = re.sub(r'[\x00-\x1F\x7F-\x9F]', '', text)
    text = re.sub(r'[\U00010000-\U0010FFFF]', '', text)
    # 分段处理
    lines = text.splitlines()
    filtered_lines = []
    equipment_section = []
    in_equipment = False
    main_tags = []
    for line in lines:
        l = line.strip()
        # 过滤明显广告/联系方式/推广语
        if not l:
            continue
        if re.search(r'(购买链接|Purchase link|优惠码|coupon code|Instagram|微博|微信|QQ群|Facebook|X:|E[- ]?mail|邮箱|联系方式|Thank you for watching|感谢.*观看|Subscriptions and likes|喜欢请关注|点赞|订阅|关注)', l, re.IGNORECASE):
            continue
        if re.match(r'https?://', l):
            continue
        # 设备清单识别
        if re.match(r'\[?Camping Equipment\]?|设备清单', l, re.IGNORECASE):
            in_equipment = True
            equipment_section.append('主要设备:')
            continue
        if in_equipment:
            if l.startswith('-') or ':' in l:
                equipment_section.append(l)
                continue
            else:
                in_equipment = False
                if equipment_section:
                    filtered_lines.extend(equipment_section)
                    equipment_section = []
        # 识别标签（不过滤，保留）
        # 保留亮点/介绍/字幕提示/拍摄声明等
        filtered_lines.append(l)
    # 合成简介
    result = '\n'.join(filtered_lines)
    if equipment_section:
        result += '\n' + '\n'.join(equipment_section)
    # 多余空行和空格
    result = re.sub(r'\n+', '\n', result)
    result = re.sub(r'\s+', ' ', result)
    result = result.strip()
    return saxutils.escape(result[:max_length])

def generate_nfo(video_info, save_dir, filename_base):
    """生成更兼容Emby的NFO文件"""
    # 获取基本信息并清理
    title = clean_text(video_info.get('title', 'Unknown Title'), 200)
    description = clean_text(video_info.get('description', ''), 2000)
    uploader = clean_text(video_info.get('uploader', ''), 100)
    upload_date = video_info.get('upload_date', '')
    view_count = video_info.get('view_count', 0)
    duration = video_info.get('duration', 0)
    tags = video_info.get('tags', [])
    categories = video_info.get('categories', [])
    channel_url = clean_text(video_info.get('channel_url', ''), 200)
    webpage_url = clean_text(video_info.get('webpage_url', ''), 200)

    # 判断视频来源
    extractor = video_info.get('extractor', '').lower()
    is_bilibili = 'bilibili' in extractor or 'bili' in extractor
    platform_name = 'BiliBili' if is_bilibili else 'YouTube'
    
    # 调试信息
    # 生成NFO文件
    # 视频信息字段

    # 格式化日期
    if upload_date and len(upload_date) >= 8:
        formatted_date = f"{upload_date[:4]}-{upload_date[4:6]}-{upload_date[6:8]}"
        year = upload_date[:4]
    else:
        # B站视频可能没有upload_date，尝试从其他字段获取
        if is_bilibili:
            # B站视频通常有upload_time字段
            upload_time = video_info.get('upload_time', '')
            if upload_time and len(upload_time) >= 8:
                formatted_date = f"{upload_time[:4]}-{upload_time[4:6]}-{upload_time[6:8]}"
                year = upload_time[:4]
            else:
                formatted_date = ''
                year = ''
        else:
            formatted_date = ''
            year = ''

    # 格式化时长
    if duration:
        # 确保duration是整数
        duration_int = int(duration)
        hours = duration_int // 3600
        minutes = (duration_int % 3600) // 60
        seconds = duration_int % 60
        if hours > 0:
            runtime = f"{hours}:{minutes:02d}:{seconds:02d}"
        else:
            runtime = f"{minutes}:{seconds:02d}"
    else:
        runtime = ''

    # 只保留1-2个主分类作为genre，优先category，无则tag
    genres = []
    if categories:
        genres.extend([clean_text(c, 50) for c in categories[:2]])
    elif tags:
        genres.extend([clean_text(t, 50) for t in tags[:2]])
    
    # B站视频可能有分区信息
    if is_bilibili and not genres:
        # 尝试从分区字段获取
        partition = video_info.get('partition', '')
        if partition:
            genres.append(clean_text(partition, 50))
    
    genres = list(dict.fromkeys(genres))  # 保持顺序去重

    # 生成NFO内容（空字段不生成节点）
    nfo_content = '<?xml version="1.0" encoding="UTF-8" standalone="yes" ?>\n<movie>\n'
    if title:
        nfo_content += f'  <title>{title}</title>\n  <originaltitle>{title}</originaltitle>\n'
    if year:
        nfo_content += f'  <year>{year}</year>\n'
    if description:
        nfo_content += f'  <plot>{description}</plot>\n'
    if uploader:
        nfo_content += f'  <director>{uploader}</director>\n'
    if formatted_date:
        nfo_content += f'  <premiered>{formatted_date}</premiered>\n'
    nfo_content += f'  <studio>{platform_name}</studio>\n'
    if webpage_url:
        nfo_content += f'  <trailer>{webpage_url}</trailer>\n'
    if runtime:
        nfo_content += f'  <runtime>{runtime}</runtime>\n'
    if view_count:
        nfo_content += f'  <playcount>{view_count}</playcount>\n'
    if uploader:
        nfo_content += f'  <channel>{uploader}</channel>\n'
    if channel_url:
        nfo_content += f'  <channelurl>{channel_url}</channelurl>\n'
    nfo_content += f'  <source>{platform_name}</source>\n'
    for genre in genres:
        nfo_content += f'  <genre>{genre}</genre>\n'
    # 统一引用标准JPG封面
    nfo_content += f'  <thumb>{filename_base}-poster.jpg</thumb>\n'
    nfo_content += '</movie>'

    # 写入NFO文件，utf-8-sig确保无BOM
    nfo_path = os.path.join(save_dir, f'{filename_base}.nfo')
    with open(nfo_path, 'w', encoding='utf-8-sig') as f:
        f.write(nfo_content)
    # 已生成NFO文件

def _extract_episode_from_title(title: str) -> Optional[int]:
    """从标题提取集号（兜底用）。"""
    if not title:
        return None
    patterns = [
        r'第\s*(\d+)\s*集',
        r'S\d+E(\d+)',
        r'E(\d+)',
    ]
    for pattern in patterns:
        m = re.search(pattern, title, re.IGNORECASE)
        if not m:
            continue
        try:
            value = int(m.group(1))
            if value > 0:
                return value
        except Exception:
            continue
    return None


def _format_season_folder_name(season_num: int) -> str:
    """标准季目录命名：Season 01 / Season 02 ..."""
    safe_num = season_num if season_num and season_num > 0 else 1
    return f"Season {safe_num:02d}"


def resolve_bilibili_collection_season_episode(
    task_id: str,
    subscription_id: Optional[str],
    video_info: dict
) -> tuple[int, int]:
    """解析 B站合集的季号与集号（section_title 优先，root_bvid 回退）。"""
    if not task_id:
        return 1, 1

    db = next(get_db())
    try:
        sv = db.query(SubscriptionVideo).filter(
            SubscriptionVideo.download_task_id == task_id
        ).first()
        if not sv and subscription_id:
            sv = db.query(SubscriptionVideo).filter(
                SubscriptionVideo.subscription_id == subscription_id,
                SubscriptionVideo.url == (video_info.get("webpage_url") or video_info.get("original_url") or "")
            ).order_by(SubscriptionVideo.created_at.desc()).first()

        if sv:
            extra = {}
            stats = {}
            try:
                extra = json.loads(sv.extra_data or "{}")
                stats = extra.get("stats") or {}
            except Exception:
                pass

            def _clean_text(value) -> str:
                return str(value or "").strip()

            def _pick_group_fields(src_extra: dict, src_stats: dict) -> tuple[str, str]:
                section = _clean_text(
                    src_stats.get("section_title")
                    or src_extra.get("section_title")
                )
                root_title = _clean_text(
                    src_stats.get("root_bvid_title")
                    or src_extra.get("root_bvid_title")
                )
                root_bvid = _clean_text(
                    src_stats.get("root_bvid")
                    or src_extra.get("root_bvid")
                )
                root_group = root_title or root_bvid
                return section, root_group

            current_section, current_root_group = _pick_group_fields(extra, stats)

            page_num = None
            try:
                page = stats.get("page")
                if page is not None:
                    parsed_page = int(page)
                    if parsed_page > 0:
                        page_num = parsed_page
            except Exception:
                pass

            if subscription_id:
                season_items = []
                all_videos = db.query(SubscriptionVideo).filter(
                    SubscriptionVideo.subscription_id == subscription_id
                ).all()
                for item in all_videos:
                    try:
                        item_extra = json.loads(item.extra_data or "{}")
                    except Exception:
                        item_extra = {}
                    item_stats = item_extra.get("stats") or {}
                    item_section, item_root_group = _pick_group_fields(item_extra, item_stats)
                    item_page = 10**9
                    try:
                        raw_page = item_stats.get("page")
                        if raw_page is not None:
                            parsed = int(raw_page)
                            if parsed > 0:
                                item_page = parsed
                    except Exception:
                        pass
                    season_items.append(
                        (item.id, item_section, item_root_group, item_page, item.created_at)
                    )

                unique_sections = {
                    row[1] for row in season_items if row[1]
                }
                unique_roots = {
                    row[2] for row in season_items if row[2]
                }

                grouping_mode = None
                current_group_key = ""
                if len(unique_sections) >= 2 and current_section:
                    grouping_mode = "section"
                    current_group_key = current_section
                elif len(unique_roots) >= 2 and current_root_group:
                    grouping_mode = "root"
                    current_group_key = current_root_group

                if grouping_mode and current_group_key:
                    if grouping_mode == "section":
                        grouped_rows = [row for row in season_items if row[1]]
                        key_getter = lambda row: row[1]
                    else:
                        grouped_rows = [row for row in season_items if row[2]]
                        key_getter = lambda row: row[2]

                    season_order = {}
                    for row in sorted(grouped_rows, key=lambda r: (r[3], r[4] or datetime.max)):
                        key = key_getter(row)
                        if key not in season_order:
                            season_order[key] = len(season_order) + 1

                    season_num = season_order.get(current_group_key, 1)
                    same_season = [row for row in grouped_rows if key_getter(row) == current_group_key]
                    same_season.sort(key=lambda r: (r[3], r[4] or datetime.max))
                    for idx, row in enumerate(same_season, start=1):
                        if row[0] == sv.id:
                            return season_num, idx

                    if page_num:
                        return season_num, page_num
                    return season_num, 1

            # 分组信息不足：回退单季逻辑
            if page_num:
                return 1, page_num

            try:
                m = re.search(r'_p(\d+)$', sv.video_id or "")
                if m:
                    suffix_page = int(m.group(1))
                    if suffix_page > 0:
                        return 1, suffix_page
            except Exception:
                pass

            title_ep = _extract_episode_from_title(sv.title or "")
            if title_ep:
                return 1, title_ep

        title_ep = _extract_episode_from_title(str(video_info.get("title", "")))
        if title_ep:
            return 1, title_ep
    finally:
        try:
            db.rollback()
        except Exception:
            pass
        db.close()

    return 1, 1


def _resolve_bilibili_actor_thumb(video_info: dict, fallback_thumb: str = "") -> str:
    """尽量从多来源提取可用于 NFO actor.thumb 的头像URL。"""
    def _sanitize_thumb(value) -> str:
        raw = str(value or "").strip()
        if not raw:
            return ""
        # 头像 URL 不能走 clean_text（会被链接过滤规则清空）
        if raw.startswith(("http://", "https://")):
            return saxutils.escape(raw[:500])
        return clean_text(raw, 500)

    candidates = [
        fallback_thumb,
        video_info.get("uploader_avatar"),
        video_info.get("author_avatar_url"),
        video_info.get("channel_thumbnail"),
        video_info.get("channel_follower_avatar"),
    ]
    for val in candidates:
        text = _sanitize_thumb(val)
        if text:
            return text
    return ""


def generate_tvshow_nfo_bilibili_collection(
    save_dir: str,
    show_title: str,
    uploader: str = "",
    uploader_thumb: str = ""
):
    """在合集根目录生成 tvshow.nfo。"""
    safe_show_title = clean_text(show_title or "B站合集", 200)
    safe_uploader = clean_text(uploader or "", 100)
    raw_uploader_thumb = str(uploader_thumb or "").strip()
    if raw_uploader_thumb.startswith(("http://", "https://")):
        safe_uploader_thumb = saxutils.escape(raw_uploader_thumb[:500])
    else:
        safe_uploader_thumb = clean_text(raw_uploader_thumb, 500)
    if not safe_uploader_thumb:
        # 兜底使用合集根封面，避免 Jellyfin 演职人员显示默认人像
        safe_uploader_thumb = "poster.jpg"
    year = datetime.now().strftime("%Y")

    content = '<?xml version="1.0" encoding="UTF-8" standalone="yes" ?>\n<tvshow>\n'
    content += f'  <title>{safe_show_title}</title>\n'
    content += f'  <showtitle>{safe_show_title}</showtitle>\n'
    content += f'  <year>{year}</year>\n'
    content += f'  <plot>B站合集：{safe_show_title}</plot>\n'
    if safe_uploader:
        content += f'  <director>{safe_uploader}</director>\n'
    content += '  <studio>BiliBili</studio>\n'
    content += '  <source>BiliBili</source>\n'
    content += '  <genre>合集</genre>\n'
    content += '  <tag>合集</tag>\n'
    content += '  <tag>B站合集</tag>\n'
    content += '  <status>Continuing</status>\n'
    content += '  <displayorder>aired</displayorder>\n'
    content += '  <thumb>poster.jpg</thumb>\n'
    if safe_uploader:
        content += '  <actor>\n'
        content += f'    <name>{safe_uploader}</name>\n'
        content += '    <role>Uploader</role>\n'
        if safe_uploader_thumb:
            content += f'    <thumb>{safe_uploader_thumb}</thumb>\n'
        content += '  </actor>\n'
    content += '</tvshow>'

    tvshow_nfo_path = os.path.join(save_dir, "tvshow.nfo")
    with open(tvshow_nfo_path, "w", encoding="utf-8-sig") as f:
        f.write(content)


def ensure_bilibili_collection_artworks(save_dir: str, episode_poster_path: Optional[str] = None):
    """
    为 Jellyfin/Emby 补齐合集根级封面命名：
    - poster.jpg（剧集总封面）
    - season01-poster.jpg（季封面）
    - folder.jpg（兼容部分皮肤/客户端）
    """
    if not save_dir or not os.path.isdir(save_dir):
        return

    source = None
    if episode_poster_path and os.path.exists(episode_poster_path):
        source = episode_poster_path
    else:
        # 优先取任一分集海报
        for f in os.listdir(save_dir):
            if f.endswith("-poster.jpg"):
                source = os.path.join(save_dir, f)
                break
        # 标准季目录：再尝试季目录中的分集海报
        if not source:
            for f in os.listdir(save_dir):
                season_dir = os.path.join(save_dir, f)
                if not (os.path.isdir(season_dir) and f.lower().startswith("season ")):
                    continue
                for sf in os.listdir(season_dir):
                    if sf.endswith("-poster.jpg"):
                        source = os.path.join(season_dir, sf)
                        break
                if source:
                    break
        # 再兜底任意 jpg
        if not source:
            for f in os.listdir(save_dir):
                if f.lower().endswith(".jpg"):
                    source = os.path.join(save_dir, f)
                    break

    if not source or not os.path.exists(source):
        logger.warning(
            f"[BiliCollection] 根目录封面补齐跳过：未找到可用源图, save_dir={save_dir}, episode_poster_path={episode_poster_path}"
        )
        return

    for target_name in ("poster.jpg", "season01-poster.jpg", "folder.jpg"):
        target_path = os.path.join(save_dir, target_name)
        try:
            if not os.path.exists(target_path):
                shutil.copyfile(source, target_path)
        except Exception as e:
            logger.warning(
                f"[BiliCollection] 根目录封面补齐失败: source={source}, target={target_path}, error={e}"
            )


def _build_premiered_date(video_info: dict) -> str:
    """将 upload_date / timestamp 标准化为 YYYY-MM-DD。"""
    upload_date = str(video_info.get("upload_date") or "").strip()
    if upload_date and len(upload_date) >= 8 and upload_date[:8].isdigit():
        return f"{upload_date[:4]}-{upload_date[4:6]}-{upload_date[6:8]}"

    timestamp = video_info.get("timestamp")
    if timestamp:
        try:
            dt = datetime.fromtimestamp(int(timestamp))
            return dt.strftime("%Y-%m-%d")
        except Exception:
            pass

    return ""


def generate_episode_nfo_bilibili_collection(
    video_info: dict,
    save_dir: str,
    filename_base: str,
    show_title: str,
    season_num: int,
    episode_num: int,
    uploader_thumb: str = ""
):
    """为 B 站合集生成剧集型 episodedetails nfo。"""
    title = clean_text(video_info.get("title", "Unknown Episode"), 200)
    plot = clean_text(video_info.get("description", "") or title, 2000)
    uploader = clean_text(video_info.get("uploader", ""), 100)
    resolved_thumb = _resolve_bilibili_actor_thumb(video_info, uploader_thumb)
    if not resolved_thumb:
        # 兜底使用分集封面
        resolved_thumb = f"{filename_base}-poster.jpg"
    webpage_url = clean_text(video_info.get("webpage_url", ""), 300)
    premiered = _build_premiered_date(video_info)
    safe_show_title = clean_text(show_title or "B站合集", 200)
    season = season_num if season_num and season_num > 0 else 1
    ep = episode_num if episode_num and episode_num > 0 else 1

    content = '<?xml version="1.0" encoding="UTF-8" standalone="yes" ?>\n<episodedetails>\n'
    content += f'  <title>{title}</title>\n'
    content += f'  <showtitle>{safe_show_title}</showtitle>\n'
    content += f'  <season>{season}</season>\n'
    content += f'  <episode>{ep}</episode>\n'
    content += f'  <plot>{plot}</plot>\n'
    if uploader:
        content += f'  <director>{uploader}</director>\n'
    if premiered:
        content += f'  <premiered>{premiered}</premiered>\n'
    content += '  <studio>BiliBili</studio>\n'
    if webpage_url:
        content += f'  <trailer>{webpage_url}</trailer>\n'
    content += '  <source>BiliBili</source>\n'
    content += '  <genre>合集</genre>\n'
    content += '  <tag>合集</tag>\n'
    content += '  <tag>B站合集</tag>\n'
    content += f'  <thumb>{filename_base}-poster.jpg</thumb>\n'
    if uploader:
        content += '  <actor>\n'
        content += f'    <name>{uploader}</name>\n'
        content += '    <role>Uploader</role>\n'
        if resolved_thumb:
            content += f'    <thumb>{resolved_thumb}</thumb>\n'
        content += '  </actor>\n'
    content += '</episodedetails>'

    nfo_path = os.path.join(save_dir, f"{filename_base}.nfo")
    with open(nfo_path, "w", encoding="utf-8-sig") as f:
        f.write(content)


def rename_files_for_bilibili_collection(task_id, video_info, save_dir, file_ext='.mp4', source_dir=None):
    """B站合集：在指定目录中重命名媒体与附属文件。"""
    source_dir = source_dir or save_dir
    try:
        title = str(video_info.get('title', f'Bilibili_Collection_{task_id}'))
        clean_title = sanitize_filename(title)
    except Exception:
        clean_title = f"Video_{task_id[:8]}"

    base_name_candidate = _fit_filename_base_for_sidecars(
        f"{clean_title}_{task_id[:8]}",
        save_dir,
        file_ext
    )

    # 同名递增后缀：flat 模式按文件名冲突处理
    base_budget = _get_filename_base_budget(save_dir, file_ext)
    counter = 0
    while True:
        if counter == 0:
            candidate = base_name_candidate
        else:
            dup_suffix = f" ({counter})"
            candidate_budget = max(8, base_budget - len(dup_suffix.encode('utf-8')))
            truncated_base = _truncate_utf8_by_bytes(base_name_candidate, candidate_budget)
            candidate = f"{truncated_base}{dup_suffix}" if truncated_base else f"Video_{task_id[:8]}{dup_suffix}"

        target_video = os.path.join(save_dir, f'{candidate}{file_ext}')
        if not os.path.exists(target_video):
            break
        counter += 1

    filename_base = candidate

    # 重命名视频文件（支持多格式）
    video_extensions = ['.mp4', '.webm', '.mkv', '.avi', '.mov', '.flv']
    old_video_path = None
    new_video_path = os.path.join(save_dir, f'{filename_base}{file_ext}')
    if file_ext:
        candidate_path = os.path.join(source_dir, f'{task_id}{file_ext}')
        if os.path.exists(candidate_path):
            old_video_path = candidate_path
    if not old_video_path:
        for ext in video_extensions:
            candidate_path = os.path.join(source_dir, f'{task_id}{ext}')
            if os.path.exists(candidate_path):
                old_video_path = candidate_path
                file_ext = ext
                new_video_path = os.path.join(save_dir, f'{filename_base}{file_ext}')
                break
    if old_video_path and os.path.exists(old_video_path):
        os.rename(old_video_path, new_video_path)
        os.utime(new_video_path, (time.time(), time.time()))

    # 重命名字幕文件（flat）
    subtitle_patterns = [
        f'{task_id}.zh.srt',
        f'{task_id}.en.srt',
        f'{task_id}.zh-Hans.srt',
        f'{task_id}.zh-CN.srt',
        f'{task_id}.en-US.srt',
        f'{task_id}.en-GB.srt',
        f'{task_id}.auto.srt',
    ]
    for pattern in subtitle_patterns:
        old_sub_path = os.path.join(source_dir, pattern)
        if not os.path.exists(old_sub_path):
            continue
        lang_code = pattern.replace(f'{task_id}.', '').replace('.srt', '')
        if lang_code.startswith('zh'):
            new_lang = 'zh'
        elif lang_code.startswith('en'):
            new_lang = 'en'
        else:
            new_lang = lang_code
        new_sub_path = os.path.join(save_dir, f'{filename_base}.{new_lang}.srt')
        if not os.path.exists(new_sub_path):
            os.rename(old_sub_path, new_sub_path)
            os.utime(new_sub_path, (time.time(), time.time()))

    for file in os.listdir(source_dir):
        if not (file.startswith(f'{task_id}.') and file.endswith('.srt')):
            continue
        old_sub_path = os.path.join(source_dir, file)
        lang_code = file.replace(f'{task_id}.', '').replace('.srt', '')
        if lang_code.startswith('zh'):
            new_lang = 'zh'
        elif lang_code.startswith('en'):
            new_lang = 'en'
        else:
            new_lang = lang_code
        new_sub_path = os.path.join(save_dir, f'{filename_base}.{new_lang}.srt')
        if not os.path.exists(new_sub_path):
            os.rename(old_sub_path, new_sub_path)
            os.utime(new_sub_path, (time.time(), time.time()))

    # 封面转存为标准 JPG（flat）
    new_thumb_path = os.path.join(save_dir, f'{filename_base}-poster.jpg')
    old_thumb_path_webp = os.path.join(source_dir, f'{task_id}.webp')
    old_thumb_path_png = os.path.join(source_dir, f'{task_id}.png')
    old_thumb_path_jpg = os.path.join(source_dir, f'{task_id}.jpg')

    def _convert_to_jpeg_ffmpeg(src: str, dst: str) -> bool:
        try:
            cmd = ["ffmpeg", "-y", "-i", src, "-frames:v", "1", "-q:v", "2", dst]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=20)
            if result.returncode == 0 and os.path.exists(dst) and os.path.getsize(dst) > 0:
                return True
            fallback_cmd = [
                "ffmpeg", "-y", "-i", src, "-frames:v", "1", "-q:v", "2",
                "-vcodec", "mjpeg", dst
            ]
            fallback = subprocess.run(fallback_cmd, capture_output=True, text=True, timeout=20)
            return fallback.returncode == 0 and os.path.exists(dst) and os.path.getsize(dst) > 0
        except Exception:
            return False

    if os.path.exists(old_thumb_path_webp):
        if _convert_to_jpeg_ffmpeg(old_thumb_path_webp, new_thumb_path):
            try:
                os.remove(old_thumb_path_webp)
            except Exception:
                pass
            os.utime(new_thumb_path, (time.time(), time.time()))
        else:
            os.rename(old_thumb_path_webp, new_thumb_path)
            os.utime(new_thumb_path, (time.time(), time.time()))
    elif os.path.exists(old_thumb_path_png):
        if _convert_to_jpeg_ffmpeg(old_thumb_path_png, new_thumb_path):
            try:
                os.remove(old_thumb_path_png)
            except Exception:
                pass
            os.utime(new_thumb_path, (time.time(), time.time()))
        else:
            os.rename(old_thumb_path_png, new_thumb_path)
            os.utime(new_thumb_path, (time.time(), time.time()))
    elif os.path.exists(old_thumb_path_jpg):
        os.rename(old_thumb_path_jpg, new_thumb_path)
        os.utime(new_thumb_path, (time.time(), time.time()))

    return filename_base

def rename_files_for_emby(task_id, video_info, save_dir, file_ext='.mp4'):
    """重命名文件为Emby/Jellyfin友好格式，每个视频创建独立文件夹
    
    Args:
        task_id: 任务ID
        video_info: 视频信息字典
        save_dir: 保存目录
        file_ext: 文件扩展名（如 .mp4, .webm, .mkv等），默认为 .mp4
    """
    try:
        # 获取视频标题和年份
        title = str(video_info.get('title', f'YouTube_Video_{task_id}'))
        # 保留原始标题，不做额外清理
        upload_date = str(video_info.get('upload_date', ''))
        year = upload_date[:4] if upload_date and len(upload_date) >= 4 else ''
        clean_title = sanitize_filename(title)
        if year:
            filename_base = f"{clean_title} ({year})"
        else:
            filename_base = clean_title
    except Exception as e:
        # 标题处理失败
        filename_base = f"Video_{task_id}"
    base_budget = _get_filename_base_budget(save_dir, file_ext)
    filename_base = _truncate_utf8_by_bytes(filename_base, base_budget) or 'unnamed'

    # 同名递增后缀：若目标文件夹已存在，则依次尝试 标题(1)、标题(2)...
    base_name_candidate = filename_base
    counter = 0
    while True:
        if counter == 0:
            candidate = base_name_candidate
        else:
            dup_suffix = f" ({counter})"
            candidate_budget = max(8, base_budget - len(dup_suffix.encode('utf-8')))
            truncated_base = _truncate_utf8_by_bytes(base_name_candidate, candidate_budget)
            candidate = f"{truncated_base}{dup_suffix}" if truncated_base else f"Video_{task_id[:8]}{dup_suffix}"

        if not os.path.exists(os.path.join(save_dir, candidate)):
            break
        counter += 1

    filename_base = candidate

    # 创建视频专属文件夹
    video_folder = os.path.join(save_dir, filename_base)
    os.makedirs(video_folder, exist_ok=True)
    
    # 重命名视频文件到专属文件夹（支持多种格式）
    video_extensions = ['.mp4', '.webm', '.mkv', '.avi', '.mov', '.flv']
    old_video_path = None
    new_video_path = os.path.join(video_folder, f'{filename_base}{file_ext}')
    
    # 如果指定了扩展名，优先使用
    if file_ext:
        candidate_path = os.path.join(save_dir, f'{task_id}{file_ext}')
        if os.path.exists(candidate_path):
            old_video_path = candidate_path
    else:
        # 否则查找所有可能的格式
        for ext in video_extensions:
            candidate_path = os.path.join(save_dir, f'{task_id}{ext}')
            if os.path.exists(candidate_path):
                old_video_path = candidate_path
                file_ext = ext
                new_video_path = os.path.join(video_folder, f'{filename_base}{file_ext}')
                break
    
    if old_video_path and os.path.exists(old_video_path):
        os.rename(old_video_path, new_video_path)
        # 视频文件已重命名
        os.utime(new_video_path, (time.time(), time.time()))
        logger.debug(f"[rename_files_for_emby] 重命名视频文件: {old_video_path} -> {new_video_path}")
    
    # 重命名字幕文件到专属文件夹（只有在实际下载了字幕时才执行）
    subtitle_files_found = 0
    # 动态查找所有可能的字幕文件
    subtitle_patterns = [
        f'{task_id}.zh.srt',
        f'{task_id}.en.srt',
        f'{task_id}.zh-Hans.srt',
        f'{task_id}.zh-CN.srt',
        f'{task_id}.en-US.srt',
        f'{task_id}.en-GB.srt',
        f'{task_id}.auto.srt',  # 自动生成的字幕
    ]
    
    for pattern in subtitle_patterns:
        old_sub_path = os.path.join(save_dir, pattern)
        if os.path.exists(old_sub_path):
            subtitle_files_found += 1
            # 提取语言代码
            lang_code = pattern.replace(f'{task_id}.', '').replace('.srt', '')
            # 简化语言代码
            if lang_code.startswith('zh'):
                new_lang = 'zh'
            elif lang_code.startswith('en'):
                new_lang = 'en'
            else:
                new_lang = lang_code
            
            new_sub_path = os.path.join(video_folder, f'{filename_base}.{new_lang}.srt')
            if not os.path.exists(new_sub_path):  # 避免重复
                os.rename(old_sub_path, new_sub_path)
                # 字幕文件已重命名
                os.utime(new_sub_path, (time.time(), time.time()))
    
    # 额外检查：查找任何以task_id开头的.srt文件
    for file in os.listdir(save_dir):
        if file.startswith(f'{task_id}.') and file.endswith('.srt'):
            subtitle_files_found += 1
            old_sub_path = os.path.join(save_dir, file)
            # 提取语言代码
            lang_code = file.replace(f'{task_id}.', '').replace('.srt', '')
            # 简化语言代码
            if lang_code.startswith('zh'):
                new_lang = 'zh'
            elif lang_code.startswith('en'):
                new_lang = 'en'
            else:
                new_lang = lang_code
            
            new_sub_path = os.path.join(video_folder, f'{filename_base}.{new_lang}.srt')
            if not os.path.exists(new_sub_path):  # 避免重复
                os.rename(old_sub_path, new_sub_path)
                # 字幕文件已重命名
                os.utime(new_sub_path, (time.time(), time.time()))
    
    if subtitle_files_found == 0:
        # 未发现字幕文件，跳过字幕重命名
        pass
    else:
        # 字幕文件已重命名
        pass
    
    # 重命名/转换封面文件到专属文件夹（统一标准JPG）
    new_thumb_path = os.path.join(video_folder, f'{filename_base}-poster.jpg')
    old_thumb_path_webp = os.path.join(save_dir, f'{task_id}.webp')
    old_thumb_path_png = os.path.join(save_dir, f'{task_id}.png')
    old_thumb_path_jpg = os.path.join(save_dir, f'{task_id}.jpg')

    def _convert_to_jpeg_ffmpeg(src: str, dst: str) -> bool:
        try:
            # 兼容 FFmpeg 6.x：优先简化命令，失败再回退 mjpeg
            cmd = [
                "ffmpeg", "-y", "-i", src,
                "-frames:v", "1", "-q:v", "2",
                dst
            ]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=20)
            if result.returncode == 0 and os.path.exists(dst) and os.path.getsize(dst) > 0:
                return True
            fallback_cmd = [
                "ffmpeg", "-y", "-i", src,
                "-frames:v", "1", "-q:v", "2",
                "-vcodec", "mjpeg",
                dst
            ]
            fallback = subprocess.run(fallback_cmd, capture_output=True, text=True, timeout=20)
            return fallback.returncode == 0 and os.path.exists(dst) and os.path.getsize(dst) > 0
        except Exception as e:
            # FFmpeg图片转JPEG失败
            return False

    # 1) 优先处理 webp/png → 转换为 JPG
    if os.path.exists(old_thumb_path_webp):
        if _convert_to_jpeg_ffmpeg(old_thumb_path_webp, new_thumb_path):
            try:
                os.remove(old_thumb_path_webp)
            except Exception:
                pass
            # 封面已转换为标准JPG
            os.utime(new_thumb_path, (time.time(), time.time()))
        else:
            # 转换失败则兜底重命名
            os.rename(old_thumb_path_webp, new_thumb_path)
            os.utime(new_thumb_path, (time.time(), time.time()))
    elif os.path.exists(old_thumb_path_png):
        if _convert_to_jpeg_ffmpeg(old_thumb_path_png, new_thumb_path):
            try:
                os.remove(old_thumb_path_png)
            except Exception:
                pass
            # 封面已转换为标准JPG
            os.utime(new_thumb_path, (time.time(), time.time()))
        else:
            os.rename(old_thumb_path_png, new_thumb_path)
            os.utime(new_thumb_path, (time.time(), time.time()))
    # 2) 直接处理 jpg → 移动
    elif os.path.exists(old_thumb_path_jpg):
        os.rename(old_thumb_path_jpg, new_thumb_path)
        # 封面文件已重命名
        os.utime(new_thumb_path, (time.time(), time.time()))
    
    return filename_base

async def download_video_logic(task_id: str, url: str, format_id: str = "bestvideo+bestaudio", youtube_cookie: str = None, bilibili_cookie: str = None, proxy: str = None, subtitles: bool = True, thumbnail: bool = True, download_dir: str = None, subscription_id: str = None):
    import asyncio
    import aiohttp
    import threading
    
    downloaded_filename = None
    temp_files = set()  # 用于跟踪所有临时文件
    max_retries = 3  # 最大重试次数
    retry_delay = 5  # 重试间隔（秒）
    
    # 智能重试配置
    def should_retry_error(error_msg: str) -> bool:
        """智能判断是否应该重试错误"""
        error_lower = error_msg.lower()
        
        # 不应该重试的错误类型
        no_retry_errors = [
            'sign in to confirm you\'re not a bot',  # YouTube反爬虫
            'video unavailable',                     # 视频不可用
            'private video',                         # 私有视频
            'deleted video',                         # 已删除视频
            'copyright',                             # 版权问题
            'age restricted',                        # 年龄限制
            'country restricted',                     # 地区限制
            'account terminated',                     # 账户终止
            'channel suspended',                      # 频道暂停
            'quota exceeded',                        # 配额超限
            'authentication required',                # 需要认证
            'login required',                        # 需要登录
            'premium required',                      # 需要会员
        ]
        
        for no_retry in no_retry_errors:
            if no_retry in error_lower:
                return False
        
        # 应该重试的错误类型
        retry_errors = [
            'network',                               # 网络错误
            'timeout',                               # 超时
            'connection',                            # 连接错误
            'ssl',                                   # SSL错误
            'temporary',                             # 临时错误
            'rate limit',                            # 限流（短暂）
            'server error',                          # 服务器错误
            'unexpected eof',                        # 意外EOF
        ]
        
        for retry in retry_errors:
            if retry in error_lower:
                return True
        
        # 默认重试（保守策略）
        return False

    # 如果传入的是 SubscriptionVideo 对象，提取必要信息
    if isinstance(url, SubscriptionVideo):
        video = url
        url = video.url
        task_id = video.download_task_id or task_id
        # subscription_id 参数优先级高于视频对象中的subscription_id
        if not subscription_id:
            subscription_id = video.subscription_id
    
    # 根据url判断类型（用于其他逻辑，不再用于代理判断）
    is_youtube = 'youtube.com' in url or 'youtu.be' in url
    is_bilibili = 'bilibili.com' in url
    working_url = url
    if is_bilibili:
        resolved_url = _resolve_bilibili_url_without_browser(url)
        if resolved_url != url:
            logger.debug(f"[YTDL] B站链接轻量解析: {url} -> {resolved_url}")
        working_url = resolved_url
    # 移除代理逻辑，完全依赖系统代理
    
    # 直接从txt文件读取cookie
    youtube_cookie = None
    bilibili_cookie = None
    
    try:
        youtube_cookie_file = '/app/database/cookie/youtube_cookie.txt'
        if os.path.exists(youtube_cookie_file):
            with open(youtube_cookie_file, 'r', encoding='utf-8') as f:
                youtube_cookie = f.read().strip()
                if youtube_cookie:
                    # 从文件读取到YouTube Cookie
                    pass
                else:
                    youtube_cookie = None
    except Exception as e:
        # 读取YouTube Cookie文件失败
        youtube_cookie = None
    
    try:
        bilibili_cookie_file = '/app/database/cookie/bilibili_cookie.txt'
        if os.path.exists(bilibili_cookie_file):
            with open(bilibili_cookie_file, 'r', encoding='utf-8') as f:
                bilibili_cookie = f.read().strip()
                if bilibili_cookie:
                    # 从文件读取到B站Cookie
                    pass
                else:
                    bilibili_cookie = None
    except Exception as e:
        # 读取B站Cookie文件失败
        bilibili_cookie = None
    
    # 根据平台选择对应的cookie
    actual_cookie = youtube_cookie if is_youtube else (bilibili_cookie if is_bilibili else None)
    
    def log_ts(msg):
        # YTDL日志（调试模式，默认关闭）
        logger.debug(f"[YTDL] {msg}")

    # 处理下载目录
    if download_dir:
        base_dir = download_dir
    elif subscription_id:
        # 订阅下载：需要构建订阅目录
        from routers.subscribe import get_subscription_download_dir
        # 获取任务信息以获取标题
        db = next(get_db())
        try:
            task = db.query(Task).filter(Task.id == task_id).first()
            title = task.title if task else "未知视频"
            base_dir = get_subscription_download_dir(subscription_id, title)
            if not base_dir:
                # 如果获取订阅目录失败，使用默认目录
                base_dir = '/app/downloads/youtube' if is_youtube else '/app/downloads/bilibili'
        finally:
            try:
                db.rollback()
            except Exception:
                pass
            db.close()
    else:
        # 手动下载：使用默认目录
        base_dir = '/app/downloads/youtube' if is_youtube else '/app/downloads/bilibili'
    
    # 确保目录存在
    os.makedirs(base_dir, exist_ok=True)
    log_ts(f"使用下载目录: {base_dir}")

    def progress_hook(d):
        nonlocal downloaded_filename, temp_files
        if task_id in cancel_flags and cancel_flags[task_id]:
            raise yt_dlp.utils.DownloadError("Download canceled by user")

        if d['status'] == 'downloading':
            # 记录临时文件
            if 'filename' in d:
                temp_files.add(d['filename'])
                if d['filename'].endswith('.part'):
                    temp_files.add(d['filename'][:-5])  # 添加不带.part的文件名
            try:
                if '_percent_str' in d:
                    progress_str = d['_percent_str']
                    progress = float(progress_str.replace('%', '').strip())
                elif 'downloaded_bytes' in d and 'total_bytes' in d:
                    progress = (d['downloaded_bytes'] / d['total_bytes']) * 100
                elif 'downloaded_bytes' in d and 'total_bytes_estimate' in d:
                    progress = (d['downloaded_bytes'] / d['total_bytes_estimate']) * 100
                else:
                    progress = 0.0
                # 限制进度值在0-100之间，并保留一位小数
                progress = round(max(0.0, min(100.0, progress)), 1)
                # 时间节流：每300ms更新一次，让进度条更丝滑
                import time
                current_time = time.time()
                if not hasattr(progress_hook, 'last_update_time') or (current_time - progress_hook.last_update_time) >= 0.3:
                    update_task_progress(task_id, TaskStatus.DOWNLOADING, progress=progress, subscription_id=subscription_id)
                    progress_hook.last_update_time = current_time
            except (ValueError, TypeError, ZeroDivisionError):
                pass
        elif d['status'] == 'finished':
            filename = d.get('filename')
            temp_files.add(filename)
            # 记录最终视频文件（支持多种格式：mp4, webm, mkv等）
            if filename:
                # 检查是否是视频文件（排除临时文件和中间文件）
                video_extensions = ['.mp4', '.webm', '.mkv', '.avi', '.mov', '.flv']
                is_video_file = any(filename.endswith(ext) for ext in video_extensions)
                # 排除中间文件（带格式ID的文件）
                is_intermediate = '.f' in os.path.basename(filename) and any(char.isdigit() for char in os.path.basename(filename))
                
                if is_video_file and not is_intermediate:
                    downloaded_filename = filename
                    log_ts(f"✅ 检测到下载完成的视频文件: {filename}")
                    # 对于订阅下载和手动下载，都传递完整路径，便于联动删除
                    relative_path = filename.replace('/app/downloads/', '')
                    update_task_progress(task_id, TaskStatus.DOWNLOADING, progress=95.0, subscription_id=subscription_id)
                else:
                    update_task_progress(task_id, TaskStatus.DOWNLOADING, progress=95.0, subscription_id=subscription_id)
        elif d['status'] == 'processing':
            # 合并阶段
            update_task_progress(task_id, TaskStatus.PROCESSING, progress=98.0, subscription_id=subscription_id)

    # 输出文件名唯一化
    outtmpl = f'{base_dir}/{task_id}.%(ext)s'

    # 支持format_id为"视频+音频"格式（如137+140），自动合并为mp4
    
    # 预检查：快速检测明显的反爬虫错误
    def quick_anti_bot_check(url: str) -> bool:
        """快速检测是否可能触发反爬虫"""
        # 检查URL是否包含敏感参数
        sensitive_patterns = [
            'list=',      # 播放列表
            'index=',     # 索引参数
            'start=',     # 开始时间
            'end=',       # 结束时间
        ]
        
        for pattern in sensitive_patterns:
            if pattern in url:
                return True
        
        return False
    
    # 保留可能触发反爬虫场景的轻微延迟（仅在检测触发时）
    if quick_anti_bot_check(url):
        log_ts("检测到可能触发反爬虫的URL，添加额外延迟")
        await asyncio.sleep(2)  # 添加2秒延迟（非阻塞）
    if '+' in format_id:
        ydl_opts = {
            'format': format_id,  # 形如137+140
            'outtmpl': outtmpl,
            'progress_hooks': [progress_hook],
            'noprogress': True,
            'noplaylist': True,
            'merge_output_format': 'mp4',  # 强制合并为mp4
            'overwrites': True,  # 强制覆盖已存在的文件
            'no-mtime': True,    # 新增，确保mtime为下载时间
            'no_cache_dir': True,  # 禁用缓存目录，避免缓存堆积
            'retries': 2 if is_youtube else max_retries,  # YouTube减少重试次数，避免429错误
            'fragment_retries': 2 if is_youtube else max_retries,  # YouTube减少分片重试
            'skip_unavailable_fragments': True if is_youtube else False,  # YouTube跳过不可用分片
            'socket_timeout': 15 if is_youtube else 30,  # YouTube减少超时时间
            'quiet': True,  # 关闭yt-dlp的详细输出
            'no_warnings': True,  # 关闭yt-dlp的警告输出
            # YouTube反爬虫优化
            'sleep_interval': 1 if is_youtube else None,  # YouTube请求间隔1秒
            'max_sleep_interval': 5 if is_youtube else None,  # YouTube最大间隔5秒
            'sleep_interval_subtitles': 1 if is_youtube else None,  # YouTube字幕请求间隔
            'concurrent_fragment_downloads': 3 if is_youtube else 1,  # YouTube适度增加并发到3个线程
        }
    else:
        ydl_opts = {
            'format': format_id,
            'outtmpl': outtmpl,
            'progress_hooks': [progress_hook],
            'noprogress': True,
            'noplaylist': True,
            'overwrites': True,  # 强制覆盖已存在的文件
            'no-mtime': True,    # 新增，确保mtime为下载时间
            'no_cache_dir': True,  # 禁用缓存目录，避免缓存堆积
            'retries': 2 if is_youtube else max_retries,  # YouTube减少重试次数，避免429错误
            'fragment_retries': 2 if is_youtube else max_retries,  # YouTube减少分片重试
            'skip_unavailable_fragments': True if is_youtube else False,  # YouTube跳过不可用分片
            'socket_timeout': 15 if is_youtube else 30,  # YouTube减少超时时间
            'quiet': True,  # 关闭yt-dlp的详细输出
            'no_warnings': True,  # 关闭yt-dlp的警告输出
            # YouTube反爬虫优化
            'sleep_interval': 1 if is_youtube else None,  # YouTube请求间隔1秒
            'max_sleep_interval': 5 if is_youtube else None,  # YouTube最大间隔5秒
            'sleep_interval_subtitles': 1 if is_youtube else None,  # YouTube字幕请求间隔
            'concurrent_fragment_downloads': 3 if is_youtube else 1,  # YouTube适度增加并发到3个线程
        }
    
    # 为 YouTube 添加远程组件支持（yt-dlp 2025.11.12+ 需要）
    # 注意：remote_components 必须在创建 YoutubeDL 对象之前设置
    if is_youtube:
        ydl_opts['remote_components'] = ['ejs:github']
        # 音频语言优先级：在 format_id 中加入语言过滤链 中文 > 英文 > 默认
        # yt-dlp 原生支持 [language=xx] 谓词，无匹配时自动降级到下一项
        current_format = ydl_opts.get('format', format_id)
        if '+' in current_format:
            video_part, audio_part = current_format.rsplit('+', 1)
            ydl_opts['format'] = (
                f"{video_part}+{audio_part}[language=zh]/"
                f"{video_part}+{audio_part}[language=en]/"
                f"{current_format}"
            )
            log_ts(f"✅ 已为 YouTube 启用音频语言优先级: zh > en > default (format: {ydl_opts['format']})")
        else:
            log_ts(f"✅ 已为 YouTube 启用远程组件支持 (format_id: {format_id})")
    
    # 检查cookie
    if actual_cookie:
        # 直接使用保存的cookie文件路径
        if is_youtube:
            ydl_opts['cookiefile'] = '/app/database/cookie/youtube_cookie.txt'
            # 本次下载使用了YouTube的cookie文件
        elif is_bilibili:
            ydl_opts['cookiefile'] = '/app/database/cookie/bilibili_cookie.txt'
            # 本次下载使用了B站的cookie文件
    else:
        # 本次下载未使用cookie
        pass
    
    # 移除代理检查，完全依赖系统代理
    # 代理配置完全依赖系统环境变量
    # 字幕和封面
    pass
    if subtitles:
        # 字幕下载已启用
        pass
    else:
        # 本次下载不包含字幕
        pass
    if thumbnail:
        ydl_opts['writethumbnail'] = True
        # 本次下载包含封面
    else:
        # 本次下载不包含封面
        pass

    # 添加整体重试逻辑
    for retry_count in range(max_retries):
        try:
            log_ts(f"收到下载请求: task_id={task_id}, url={url}")
            if retry_count > 0:
                log_ts(f"第 {retry_count + 1} 次尝试下载...")
            update_task_progress(task_id, TaskStatus.DOWNLOADING, progress=0.0)
            
            log_ts("开始获取视频详细信息...")
            update_task_progress(task_id, TaskStatus.DOWNLOADING, progress=0.1)
            
            # 创建异步任务获取视频信息
            async def get_video_info_async(target_url: str):
                loop = asyncio.get_event_loop()
                ydl_info_opts = {'noplaylist': True, 'quiet': True, 'no_warnings': True}
                # 为 YouTube 启用远程组件支持（获取视频信息时也需要）
                if is_youtube:
                    ydl_info_opts['remote_components'] = ['ejs:github']
                    log_ts("✅ 获取视频信息时已启用远程组件支持")
                if actual_cookie:
                    if is_youtube:
                        ydl_info_opts['cookiefile'] = '/app/database/cookie/youtube_cookie.txt'
                    elif is_bilibili:
                        ydl_info_opts['cookiefile'] = '/app/database/cookie/bilibili_cookie.txt'
                # 使用默认线程池执行 I/O 密集型的视频信息提取
                # None 表示使用 Python 默认的 ThreadPoolExecutor
                return await loop.run_in_executor(None, _extract_info_sync, target_url, ydl_info_opts)
            
            info_start = datetime.now()
            try:
                video_info = await get_video_info_async(working_url)
                
                # 检查是否返回了错误信息
                if isinstance(video_info, dict) and video_info.get("error"):
                    error_msg = video_info.get("error_message", "未知错误")
                    error_type = video_info.get("error_type", "Exception")
                    raise Exception(f"{error_type}: {error_msg}")
            except Exception as e:
                error_msg = str(e)
                
                # 检查是否是 cookie 文件格式错误（可能是并发读取导致的临时性错误）
                if "does not look like a Netscape format cookies file" in error_msg:
                    log_ts("检测到 cookie 格式错误（获取信息阶段），可能是并发读取导致，等待1秒后重试...")
                    
                    # 等待1秒，让文件系统缓存稳定
                    await asyncio.sleep(1)
                    
                    # 重新尝试获取视频信息
                    try:
                        log_ts("重新获取视频信息（cookie 重试）...")
                        video_info = await get_video_info_async(working_url)
                        
                        # 再次检查是否返回了错误信息
                        if isinstance(video_info, dict) and video_info.get("error"):
                            error_msg = video_info.get("error_message", "未知错误")
                            error_type = video_info.get("error_type", "Exception")
                            raise Exception(f"{error_type}: {error_msg}")
                        
                        log_ts("✅ 视频信息获取成功（重试成功）")
                    except Exception as retry_e:
                        logger.error(f"重试获取视频信息仍然失败: {str(retry_e)}")
                        raise retry_e
                elif is_bilibili and _need_bilibili_browser_fallback(error_msg):
                    log_ts("B站信息提取失败，触发浏览器兜底解析真实链接后重试...")
                    fallback_url = await _resolve_bilibili_url_via_browser(working_url, task_id)
                    if fallback_url and fallback_url != working_url:
                        log_ts(f"浏览器兜底解析成功: {working_url} -> {fallback_url}")
                        working_url = fallback_url
                        video_info = await get_video_info_async(working_url)
                        if isinstance(video_info, dict) and video_info.get("error"):
                            error_msg = video_info.get("error_message", "未知错误")
                            error_type = video_info.get("error_type", "Exception")
                            raise Exception(f"{error_type}: {error_msg}")
                    else:
                        log_ts("浏览器兜底解析未获得新链接，维持原错误")
                        raise
                else:
                    # 其他错误直接抛出
                    raise
            
            # 继续处理获取到的视频信息
            try:
                
                # 检查非高级用户是否尝试下载8K视频（双重保险）
                is_licensed = await license_manager.verify()
                if not is_licensed and is_youtube:
                    # 检查 format_id 是否会导致8K下载
                    def check_8k_download(format_id, video_info):
                        """检查 format_id 是否会导致8K下载"""
                        format_id_str = str(format_id)
                        
                        # 检查 format_id 字符串中是否包含8K相关的选择器
                        if '4320' in format_id_str or 'height<=4320' in format_id_str or 'height>2160' in format_id_str:
                            return True
                        
                        # 对于 "best" 或 "bestvideo+bestaudio"，检查视频的最高分辨率
                        if format_id in ['best', 'bestvideo+bestaudio']:
                            formats = video_info.get('formats', [])
                            if formats:
                                max_height = 0
                                for fmt in formats:
                                    height = fmt.get('height', 0)
                                    if height and height > max_height:
                                        max_height = height
                                if max_height > 2160:
                                    return True
                        
                        # 检查具体的格式ID是否对应8K格式
                        # format_id 可能是 "137+140" 这样的组合，需要检查每个部分
                        format_parts = format_id_str.split('+')
                        formats = video_info.get('formats', [])
                        
                        # 创建格式ID到高度的映射
                        format_height_map = {}
                        for fmt in formats:
                            fmt_id = str(fmt.get('format_id', ''))
                            height = fmt.get('height', 0)
                            if height:
                                format_height_map[fmt_id] = height
                        
                        # 检查 format_id 的每个部分是否对应8K格式
                        for part in format_parts:
                            part = part.strip()
                            if part in format_height_map:
                                if format_height_map[part] > 2160:
                                    return True
                        
                        return False
                    
                    if check_8k_download(format_id, video_info):
                        error_msg = "8K视频下载是高级用户的特性，请升级为高级用户后使用"
                        logger.warning(f"[YTDL] 非高级用户尝试下载8K视频被阻止: {format_id}")
                        update_task_progress(task_id, TaskStatus.ERROR, progress=0.0, error=error_msg)
                        raise ValueError(error_msg)
                
                # 异步检查字幕可用性（如果启用了字幕下载）
                if subtitles:
                    # 将字幕检测放到线程池中，避免阻塞主线程
                    async def detect_subtitles_async():
                        loop = asyncio.get_event_loop()
                        return await loop.run_in_executor(None, _detect_subtitles_sync, video_info)
                    
                    subtitle_result = await detect_subtitles_async()
                    has_manual_subtitles = subtitle_result['has_manual_subtitles']
                    has_auto_subtitles = subtitle_result['has_auto_subtitles']
                    manual_langs = subtitle_result.get('manual_langs', []) or []
                    auto_langs = subtitle_result.get('auto_langs', []) or []

                    # 标记：是否启用自动字幕（用于下载阶段的并发限流）
                    use_auto_subtitles = False

                    if has_manual_subtitles:
                        # 手动字幕优先
                        ydl_opts['writesubtitles'] = True
                        ydl_opts['writeautomaticsub'] = False
                        ydl_opts['subtitleslangs'] = manual_langs
                        ydl_opts['subtitlesformat'] = 'srt'
                    elif has_auto_subtitles:
                        # 无手动 → 尝试自动字幕（带限流，遇429立刻放弃，后续代码已处理）
                        ydl_opts['writesubtitles'] = False
                        ydl_opts['writeautomaticsub'] = True
                        ydl_opts['subtitleslangs'] = auto_langs
                        ydl_opts['subtitlesformat'] = 'srt'
                        use_auto_subtitles = True
                    else:
                        # 没有任何字幕
                        ydl_opts.pop('writesubtitles', None)
                        ydl_opts['writeautomaticsub'] = False
                        ydl_opts.pop('subtitleslangs', None)
                        ydl_opts.pop('subtitlesformat', None)
                
                # B站视频特殊处理
                if is_bilibili:
                    try:
                        # 确保获取到标题
                        if not video_info.get('title'):
                            # 尝试从formats中获取标题
                            for f in video_info.get('formats', []):
                                if f.get('title'):
                                    video_info['title'] = f['title']
                                    break
                        # 如果还是没有标题，尝试从BV号解析
                        if not video_info.get('title'):
                            bv_match = re.search(r'BV\w{10}', working_url)
                            if bv_match:
                                video_info['title'] = f'Bilibili_{bv_match.group(0)}'
                    except Exception as e:
                        # B站标题处理失败
                        pass
                        
                    # 记录原始URL
                    video_info['webpage_url'] = working_url
                    video_info['original_url'] = url
                    
                    # 设置平台信息
                    video_info['extractor'] = 'BiliBili'
                    video_info['extractor_key'] = 'BiliBili'
                
                info_end = datetime.now()
                log_ts(f"视频信息获取完毕，耗时: {(info_end-info_start).total_seconds():.2f}s")
                
                # 验证可用的格式列表（调试用）
                if is_youtube and video_info.get('formats'):
                    available_formats = video_info.get('formats', [])
                    available_heights = set()
                    video_only_formats = []
                    audio_only_formats = []
                    combined_formats = []
                    
                    for fmt in available_formats:
                        fmt_id = fmt.get('format_id', '')
                        height = fmt.get('height')
                        vcodec = fmt.get('vcodec', 'none')
                        acodec = fmt.get('acodec', 'none')
                        has_video = vcodec != 'none'
                        has_audio = acodec != 'none'
                        
                        if height:
                            available_heights.add(height)
                        
                        if has_video and not has_audio:
                            video_only_formats.append((fmt_id, height))
                        elif has_audio and not has_video:
                            audio_only_formats.append((fmt_id, height))
                        elif has_video and has_audio:
                            combined_formats.append((fmt_id, height))
                    
                    if available_heights:
                        max_height = max(available_heights)
                        log_ts(f"📊 可用分辨率: {sorted(available_heights, reverse=True)[:5]} (最高: {max_height}p)")
                        log_ts(f"🎯 目标格式: {format_id}")
                        log_ts(f"📹 视频流格式数: {len(video_only_formats)}, 音频流格式数: {len(audio_only_formats)}, 组合格式数: {len(combined_formats)}")
                        
                        # 智能格式选择：如果使用 'best' 但视频有更高分辨率，自动优化格式选择
                        if format_id == 'best' and max_height > 1080:
                            # 检查是否有分离的视频流（通常4K/8K是分离的）
                            if video_only_formats:
                                # 找到最高分辨率的视频流
                                max_video_height = max([h for _, h in video_only_formats if h], default=0)
                                if max_video_height > 1080:
                                    # 自动转换为 bestvideo+bestaudio 以获得最高分辨率
                                    format_id = 'bestvideo+bestaudio'
                                    ydl_opts['format'] = format_id
                                    log_ts(f"🚀 自动优化: 检测到 {max_video_height}p 视频流，已将 'best' 转换为 'bestvideo+bestaudio'")
                                else:
                                    log_ts(f"⚠️ 警告: 视频有 {max_height}p 分辨率，但 'best' 格式可能不会选择最高分辨率")
                            else:
                                log_ts(f"⚠️ 警告: 视频有 {max_height}p 分辨率，但 'best' 格式可能不会选择最高分辨率")
                        elif format_id == 'best' and max_height <= 1080:
                            log_ts(f"✅ 视频最高分辨率 {max_height}p，'best' 格式应该可以正常选择")
                
                update_task_progress(task_id, TaskStatus.DOWNLOADING, progress=0.2)
            except Exception as e:
                logger.error(f"处理视频信息失败: {str(e)}")
                raise
            
            log_ts(f"开始下载视频... (format_id: {format_id})")
            update_task_progress(task_id, TaskStatus.DOWNLOADING, progress=0.3)
            
            # 创建异步任务下载视频
            async def download_video_async():
                loop = asyncio.get_event_loop()
                
                def _download():
                    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                        return ydl.download([working_url])
                
                return await loop.run_in_executor(None, _download)
            
            dl_start = datetime.now()
            try:
                # 若启用了自动字幕，则使用全局信号量限流，降低429风险
                if 'writeautomaticsub' in ydl_opts and ydl_opts.get('writeautomaticsub'):
                    async with _AUTO_SUBTITLE_SEMAPHORE:
                        await download_video_async()
                else:
                    await download_video_async()
                dl_end = datetime.now()
                log_ts(f"视频下载完成，耗时: {(dl_end-dl_start).total_seconds():.2f}s")
                update_task_progress(task_id, TaskStatus.DOWNLOADING, progress=0.9)
            except Exception as e:
                error_msg = str(e)
                
                # 检查是否是格式不可用错误，尝试格式降级（优先检查，因为这是预期的降级流程）
                if any(error_pattern in error_msg.lower() for error_pattern in [
                    "requested format is not available",
                    "no suitable formats found", 
                    "format not available",
                    "no formats found",
                    "unable to extract formats",
                    "format selection failed"
                ]):
                    # 使用WARNING级别，说明这是预期的降级流程，不是真正的错误
                    logger.warning(f"初始格式不可用，将自动降级: {error_msg}")
                    log_ts(f"⚠️ 初始格式 '{format_id}' 不可用，开始格式降级策略...")
                    
                    # 定义格式降级序列
                    fallback_formats = []
                    
                    # 判断平台类型
                    is_bilibili = 'bilibili.com' in url
                    is_youtube = 'youtube.com' in url or 'youtu.be' in url
                    
                    if is_bilibili:
                        # B站格式降级策略
                        fallback_formats = [
                            "bestvideo[height<=4320]+bestaudio/best[height<=4320]",  # 尝试8K/4K
                            "bestvideo[height<=2160]+bestaudio/best[height<=2160]",  # 尝试4K/2K
                            "bestvideo[height<=1080]+bestaudio/best[height<=1080]",  # 限制1080p
                            "bestvideo[height<=720]+bestaudio/best[height<=720]",   # 限制720p
                            "best[height<=1080]",                                   # 单流1080p
                            "best[height<=720]",                                    # 单流720p
                            "best",                                                 # 任何最佳格式
                            "worst"                                                 # 最后的选择
                        ]
                        logger.debug("🎯 [B站] 使用格式降级策略，将依次尝试8种格式")
                    elif is_youtube:
                        # YouTube格式降级策略
                        fallback_formats = [
                            "bestvideo[height<=1440]+bestaudio/best[height<=1440]", # 限制1440p
                            "bestvideo[height<=1080]+bestaudio/best[height<=1080]", # 限制1080p
                            "bestvideo[height<=720]+bestaudio/best[height<=720]",   # 限制720p
                            "best[height<=1080]",                                   # 单流1080p
                            "best[height<=720]",                                    # 单流720p
                            "best",                                                 # 任何最佳格式
                            "worst"                                                 # 最后的选择
                        ]
                        logger.debug("🎯 [YouTube] 使用格式降级策略，将依次尝试7种格式")
                    else:
                        # 其他平台格式降级策略
                        fallback_formats = [
                            "bestvideo[height<=1440]+bestaudio/best[height<=1440]", # 限制1440p
                            "bestvideo[height<=1080]+bestaudio/best[height<=1080]", # 限制1080p
                            "bestvideo[height<=720]+bestaudio/best[height<=720]",   # 限制720p
                            "best[height<=1080]",                                   # 单流1080p
                            "best[height<=720]",                                    # 单流720p
                            "best",                                                 # 任何最佳格式
                            "worst"                                                 # 最后的选择
                        ]
                        logger.debug("🎯 [其他平台] 使用格式降级策略，将依次尝试7种格式")
                    
                    # 尝试每个降级格式
                    format_retry_success = False
                    for i, fallback_format in enumerate(fallback_formats):
                        try:
                            logger.debug(f"📉 [{i+1}/{len(fallback_formats)}] 尝试格式: {fallback_format}")
                            
                            # 更新ydl_opts中的格式
                            ydl_opts['format'] = fallback_format
                            
                            # 重新创建下载函数
                            async def download_video_fallback():
                                loop = asyncio.get_event_loop()
                                def _download_fallback():
                                    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                                        return ydl.download([working_url])
                                return await loop.run_in_executor(None, _download_fallback)
                            
                            # 尝试下载
                            await download_video_fallback()
                            dl_end = datetime.now()
                            logger.info(f"✅ 格式降级成功！最终使用格式: {fallback_format}")
                            logger.info(f"✅ 视频下载完成（通过格式降级），耗时: {(dl_end-dl_start).total_seconds():.2f}s")
                            update_task_progress(task_id, TaskStatus.DOWNLOADING, progress=0.9)
                            format_retry_success = True
                            break
                            
                        except Exception as fallback_error:
                            fallback_error_msg = str(fallback_error)
                            # 只记录debug级别，避免日志过多
                            log_ts(f"❌ 格式 {i+1} 失败: {fallback_error_msg[:100]}")
                            
                            # 如果是最后一个格式也失败了，记录详细错误
                            if i == len(fallback_formats) - 1:
                                logger.error(f"所有降级格式都失败了，最后错误: {fallback_error_msg}")
                            continue
                    
                    # 如果所有降级格式都失败了，抛出原始错误
                    if not format_retry_success:
                        logger.error("💥 所有格式降级策略都失败了，无法下载视频")
                        raise e
                
                # 检查是否是 cookie 文件格式错误（可能是并发读取导致的临时性错误）
                elif "does not look like a Netscape format cookies file" in error_msg:
                    logger.warning(f"检测到 cookie 格式错误，可能是并发读取导致: {error_msg}")
                    log_ts("等待1秒后重试...")
                    
                    # 等待1秒，让文件系统缓存稳定
                    await asyncio.sleep(1)
                    
                    # 重新尝试下载
                    try:
                        logger.debug("重新下载视频（cookie 重试）...")
                        await download_video_async()
                        dl_end = datetime.now()
                        logger.info(f"✅ 视频下载完成（cookie重试成功），耗时: {(dl_end-dl_start).total_seconds():.2f}s")
                        update_task_progress(task_id, TaskStatus.DOWNLOADING, progress=0.9)
                    except Exception as retry_e:
                        logger.error(f"重试下载仍然失败: {str(retry_e)}")
                        raise retry_e
                # 检查是否是字幕相关的429错误
                elif "429" in error_msg and ("subtitle" in error_msg.lower() or "caption" in error_msg.lower()):
                    logger.warning(f"检测到字幕下载429错误: {error_msg}")
                    logger.debug("尝试重新下载视频（不包含字幕）")
                    
                    # 移除字幕相关选项
                    ydl_opts.pop('writesubtitles', None)
                    ydl_opts.pop('writeautomaticsub', None)
                    ydl_opts.pop('subtitleslangs', None)
                    ydl_opts.pop('subtitlesformat', None)
                    
                    # 重新尝试下载（不包含字幕）
                    try:
                        await download_video_async()
                        dl_end = datetime.now()
                        logger.info(f"✅ 视频下载完成（跳过字幕），耗时: {(dl_end-dl_start).total_seconds():.2f}s")
                        update_task_progress(task_id, TaskStatus.DOWNLOADING, progress=0.9)
                    except Exception as retry_error:
                        logger.error(f"重新下载视频失败: {str(retry_error)}")
                        raise retry_error
                
                else:
                    # 其他类型的错误，记录为ERROR
                    if "sign in to confirm you" in error_msg.lower() or "not a bot" in error_msg.lower():
                        # 这是YouTube风控/人机验证，单纯重试/降级格式无效
                        friendly = (
                            "YouTube 触发人机验证（not a bot）。"
                            "请在系统内打开 YouTube 登录页面完成登录后再重试，或更新 YouTube Cookie。"
                        )
                        logger.error(f"{friendly} 原始错误: {error_msg}")
                        update_task_progress(task_id, TaskStatus.ERROR, progress=0.0, error=friendly)
                        raise
                    logger.error(f"下载视频失败: {error_msg}")
                    raise
            
            # 检查下载完成的文件（支持多种格式）
            video_extensions = ['.mp4', '.webm', '.mkv', '.avi', '.mov', '.flv']
            final_video_file = None
            
            # 优先使用 progress_hook 中记录的文件名
            if downloaded_filename and os.path.exists(downloaded_filename):
                final_video_file = downloaded_filename
                log_ts(f"✅ 使用 progress_hook 记录的文件: {final_video_file}")
            else:
                # 查找实际存在的视频文件
                for ext in video_extensions:
                    candidate = f'{base_dir}/{task_id}{ext}'
                    if os.path.exists(candidate):
                        final_video_file = candidate
                        log_ts(f"✅ 找到下载完成的视频文件: {final_video_file}")
                        break
                
                # 如果还是找不到，列出目录中的所有文件
                if not final_video_file:
                    try:
                        files_in_dir = os.listdir(base_dir)
                        video_files = [f for f in files_in_dir if any(f.endswith(ext) for ext in video_extensions) and task_id in f]
                        if video_files:
                            final_video_file = os.path.join(base_dir, video_files[0])
                            log_ts(f"✅ 在目录中找到视频文件: {final_video_file}")
                        else:
                            log_ts(f"⚠️ 目录中的文件: {files_in_dir[:10]}")
                    except Exception as e:
                        log_ts(f"⚠️ 无法列出目录文件: {str(e)}")
            
            if final_video_file and os.path.exists(final_video_file):
                log_ts(f"✅ 开始处理下载完成的视频文件: {final_video_file}")
                # 获取文件扩展名
                file_ext = os.path.splitext(final_video_file)[1]
                
                log_ts("开始自动刮削...")
                scrape_start = datetime.now()
                filename_base = None
                is_bilibili_collection_mode = False
                try:
                    # 获取视频标题用于显示
                    title = str(video_info.get('title', ''))
                    if not title:
                        title = f"Video_{task_id}"

                    relative_base_dir = base_dir.replace('/app/downloads/', '')

                    # 仅 B 站合集走剧集目录结构（Season xx）+ 剧集NFO
                    collection_title = ""
                    collection_uploader = video_info.get('uploader') or video_info.get('author') or ""
                    collection_uploader_thumb = ""
                    collection_season = 1
                    collection_episode = 1
                    bilibili_collection_season_folder = _format_season_folder_name(1)
                    if is_bilibili and subscription_id:
                        meta_db = next(get_db())
                        try:
                            sub = meta_db.query(Subscription).filter(Subscription.id == subscription_id).first()
                            if sub and (sub.platform or "").lower() == "bilibili_collection":
                                is_bilibili_collection_mode = True
                                collection_title = (sub.nickname or sub.collection_title or "").strip()
                                collection_uploader_thumb = (sub.avatar_url or "").strip()
                                if not collection_title:
                                    collection_title = "B站合集"
                                collection_season, collection_episode = resolve_bilibili_collection_season_episode(
                                    task_id=task_id,
                                    subscription_id=subscription_id,
                                    video_info=video_info
                                )
                                bilibili_collection_season_folder = _format_season_folder_name(collection_season)
                        finally:
                            try:
                                meta_db.rollback()
                            except Exception:
                                pass
                            meta_db.close()

                    # 重命名文件（传入文件扩展名）
                    if is_bilibili_collection_mode:
                        video_folder = os.path.join(base_dir, bilibili_collection_season_folder)
                        os.makedirs(video_folder, exist_ok=True)
                        filename_base = rename_files_for_bilibili_collection(
                            task_id,
                            video_info,
                            video_folder,
                            file_ext,
                            source_dir=base_dir
                        )
                    else:
                        filename_base = rename_files_for_emby(task_id, video_info, base_dir, file_ext)
                        video_folder = os.path.join(base_dir, filename_base)
                    
                    # 生成NFO文件
                    try:
                        if is_bilibili_collection_mode:
                            show_title = collection_title or "B站合集"
                            generate_episode_nfo_bilibili_collection(
                                video_info=video_info,
                                save_dir=video_folder,
                                filename_base=filename_base,
                                show_title=show_title,
                                season_num=collection_season,
                                episode_num=collection_episode,
                                uploader_thumb=collection_uploader_thumb
                            )
                            generate_tvshow_nfo_bilibili_collection(
                                save_dir=base_dir,
                                show_title=show_title,
                                uploader=collection_uploader,
                                uploader_thumb=collection_uploader_thumb
                            )
                        else:
                            generate_nfo(video_info, video_folder, filename_base)
                    except Exception as nfo_error:
                        # NFO文件生成失败
                        # 继续执行，不因为NFO生成失败而中断整个流程
                        pass

                    # 更新任务状态，使用视频标题作为显示名称
                    display_name = f"{title}{file_ext}"  # 使用实际文件扩展名
                    # 构建完整的相对路径，便于联动删除
                    if is_bilibili_collection_mode:
                        file_path = f'{relative_base_dir}/{bilibili_collection_season_folder}/{filename_base}{file_ext}'
                    elif subscription_id:
                        # 订阅下载：构建完整的相对路径
                        file_path = f'{relative_base_dir}/{filename_base}/{filename_base}{file_ext}'
                    else:
                        # 手动下载：构建完整的相对路径，确保与订阅下载格式一致
                        file_path = f'{relative_base_dir}/{filename_base}/{filename_base}{file_ext}'
                    
                    update_task_progress(
                        task_id, 
                        TaskStatus.COMPLETED, 
                        progress=100.0, 
                        filename=file_path,
                        subscription_id=subscription_id
                    )
                    
                    # 更新任务的标题
                    db = next(get_db())
                    try:
                        task = db.query(Task).filter(Task.id == task_id).first()
                        if task:
                            task.title = title
                            db.commit()
                        
                        # 发送“下载完成”通知
                        try:
                            # 1. 基础数据准备
                            n_video_title = title
                            n_video_url = url
                            n_platform = "YouTube"
                            if n_video_url and ("bilibili" in n_video_url.lower() or "b23.tv" in n_video_url.lower()):
                                n_platform = "B站"
                            
                            n_author_name = video_info.get('uploader') or video_info.get('author') or "手动下载"
                            n_type_label = "手动下载"

                            # 2. 如果是订阅下载，尝试获取更详细的信息
                            if subscription_id:
                                n_type_label = "订阅下载"
                                try:
                                    video_db = db.query(SubscriptionVideo).filter(SubscriptionVideo.download_task_id == task_id).first()
                                    if video_db:
                                        n_video_title = video_db.title or n_video_title
                                        sub_rec = db.query(Subscription).filter(Subscription.id == video_db.subscription_id).first()
                                        if sub_rec:
                                            n_author_name = sub_rec.nickname or n_author_name
                                except Exception as _e:
                                    logging.warning(f"获取订阅详情失败: {str(_e)}")

                            # 3. 获取封面图
                            extra_data = {}
                            try:
                                # 获取本地封面图路径
                                poster_filename = f"{filename_base}-poster.jpg"
                                if is_bilibili_collection_mode:
                                    video_folder = os.path.join(base_dir, bilibili_collection_season_folder)
                                    poster_path = os.path.join(video_folder, poster_filename)
                                else:
                                    video_folder = os.path.join(base_dir, filename_base)
                                    poster_path = os.path.join(video_folder, poster_filename)
                                
                                # 检查文件是否存在
                                if os.path.exists(poster_path):
                                    # 构造相对路径供通知服务使用
                                    if is_bilibili_collection_mode:
                                        relative_poster_path = f"{relative_base_dir}/{bilibili_collection_season_folder}/{poster_filename}"
                                    else:
                                        relative_poster_path = f"{relative_base_dir}/{filename_base}/{poster_filename}"
                                    if not relative_poster_path.startswith('/'):
                                        relative_poster_path = f"/downloads/{relative_poster_path}"
                                    extra_data["cover"] = relative_poster_path
                                    logging.debug(f"[YTDL] 通知将包含海报: {relative_poster_path}")
                                else:
                                    # 兜底：尝试找文件夹下的任意jpg
                                    for f in os.listdir(video_folder):
                                        if f.endswith('.jpg') and (filename_base in f or 'poster' in f or 'cover' in f):
                                            if is_bilibili_collection_mode:
                                                relative_f_path = f"{relative_base_dir}/{bilibili_collection_season_folder}/{f}"
                                            else:
                                                relative_f_path = f"{relative_base_dir}/{filename_base}/{f}"
                                            if not relative_f_path.startswith('/'):
                                                relative_f_path = f"/downloads/{relative_f_path}"
                                            extra_data["cover"] = relative_f_path
                                            break
                            except Exception as _e:
                                logging.warning(f"查找海报路径失败: {str(_e)}")

                            if subscription_id:
                                extra_data["subscription_id"] = subscription_id

                            # 4. 构造通知内容
                            notification_data = {
                                "title": f"🎉 {n_type_label}完成 ({n_platform})",
                                "content": f"视频《{n_video_title}》下载完成！\n\n🏷️ 来源: {n_platform}\n👤 博主: {n_author_name}\n⏰ 完成时间: {now_beijing().strftime('%Y-%m-%d %H:%M:%S')}",
                                "user_id": "default",
                                "extra_data": extra_data
                            }

                            # 4. 异步线程发送
                            def send_completed_notification():
                                try:
                                    async def do_send():
                                        connector = aiohttp.UnixConnector(path="/app/sockets/easy-vdl.sock")
                                        async with aiohttp.ClientSession(connector=connector) as session:
                                            await session.post("http://localhost/api/notifications/download-completed", json=notification_data)
                                    
                                    loop = asyncio.new_event_loop()
                                    asyncio.set_event_loop(loop)
                                    try:
                                        loop.run_until_complete(do_send())
                                    finally:
                                        loop.close()
                                except Exception as _e:
                                    logging.warning(f"发送完成通知异常: {str(_e)}")

                            threading.Thread(target=send_completed_notification, daemon=True).start()
                        except Exception as _e:
                            logging.warning(f"准备下载完成通知失败: {str(_e)}")
                    finally:
                        try:
                            db.rollback()
                        except Exception:
                            pass
                        db.close()

                    # B站封面兜底：主动下载thumbnail为-poster.jpg
                    if is_bilibili:
                        if is_bilibili_collection_mode:
                            video_folder = os.path.join(base_dir, bilibili_collection_season_folder)
                            poster_path = os.path.join(video_folder, f'{filename_base}-poster.jpg')
                        else:
                            video_folder = os.path.join(base_dir, filename_base)
                            poster_path = os.path.join(video_folder, f'{filename_base}-poster.jpg')
                        # 只在本地没有-poster.jpg时才下载
                        if not os.path.exists(poster_path):
                            # 获取thumbnail字段
                            thumb_url = video_info.get('thumbnail')
                            # 兜底：如果有thumbnails列表，取最大分辨率
                            if (not thumb_url or thumb_url.strip() == '') and 'thumbnails' in video_info and video_info['thumbnails']:
                                thumb_url = video_info['thumbnails'][-1].get('url', '')
                            # 兜底：新版yt-dlp的pic字段
                            if (not thumb_url or thumb_url.strip() == '') and 'pic' in video_info:
                                thumb_url = video_info['pic']
                            # 兜底：B站favicon
                            if (not thumb_url or thumb_url.strip() == '') and 'webpage_url' in video_info and 'bilibili' in video_info['webpage_url']:
                                thumb_url = 'https://www.bilibili.com/favicon.ico'
                            # 只处理http/https外链
                            if thumb_url and thumb_url.startswith('http'):
                                try:
                                    import requests
                                    resp = requests.get(thumb_url, timeout=10)
                                    if resp.status_code == 200:
                                        with open(poster_path, 'wb') as f:
                                            f.write(resp.content)
                                        # B站封面已保存
                                except Exception as e:
                                    # B站封面下载失败
                                    pass
                        # 合集模式：为 tvshow.nfo 提供根级封面（首次生成即可）
                        if is_bilibili_collection_mode:
                            ensure_bilibili_collection_artworks(base_dir, poster_path)

                except Exception as e:
                    print(f"[YTDL] 自动刮削失败: {str(e)}")
                    # 如果刮削失败，至少保证原始文件可访问
                    # 兜底也用重命名后的路径
                    relative_base_dir = base_dir.replace('/app/downloads/', '')
                    if filename_base:
                        if is_bilibili_collection_mode:
                            file_path = f'{relative_base_dir}/{bilibili_collection_season_folder}/{filename_base}.mp4'
                        elif subscription_id:
                            # 订阅下载：构建完整的相对路径
                            file_path = f'{relative_base_dir}/{filename_base}/{filename_base}.mp4'
                        else:
                            # 手动下载：构建完整的相对路径，确保与订阅下载格式一致
                            file_path = f'{relative_base_dir}/{filename_base}/{filename_base}.mp4'
                    else:
                        file_path = f'{task_id}.mp4'
                    update_task_progress(task_id, TaskStatus.COMPLETED, progress=100.0, filename=file_path, subscription_id=subscription_id)
                    # 即使刮削失败，只要最终完成，也发送一次“下载完成”通知
                    try:
                        n_video_title = title if 'title' in locals() else f"Video_{task_id}"
                        n_video_url = url
                        n_platform = "YouTube"
                        if n_video_url and ("bilibili" in n_video_url.lower() or "b23.tv" in n_video_url.lower()):
                            n_platform = "B站"
                        
                        n_author_name = video_info.get('uploader') or video_info.get('author') or "手动下载"
                        n_type_label = "手动下载"

                        if subscription_id:
                            n_type_label = "订阅下载"
                            try:
                                video_db = db.query(SubscriptionVideo).filter(SubscriptionVideo.download_task_id == task_id).first()
                                if video_db:
                                    n_video_title = video_db.title or n_video_title
                                    sub_rec = db.query(Subscription).filter(Subscription.id == video_db.subscription_id).first()
                                    if sub_rec:
                                        n_author_name = sub_rec.nickname or n_author_name
                            except: pass

                        # 获取封面图
                        extra_data = {}
                        try:
                            if is_bilibili_collection_mode:
                                video_folder = os.path.join(base_dir, bilibili_collection_season_folder)
                            else:
                                video_folder = os.path.join(base_dir, filename_base)
                            if os.path.exists(video_folder):
                                poster_filename = f"{filename_base}-poster.jpg"
                                poster_path = os.path.join(video_folder, poster_filename)
                                if os.path.exists(poster_path):
                                    if is_bilibili_collection_mode:
                                        relative_poster_path = f"{relative_base_dir}/{bilibili_collection_season_folder}/{poster_filename}"
                                    else:
                                        relative_poster_path = f"{relative_base_dir}/{filename_base}/{poster_filename}"
                                    if not relative_poster_path.startswith('/'):
                                        relative_poster_path = f"/downloads/{relative_poster_path}"
                                    extra_data["cover"] = relative_poster_path
                        except: pass

                        if subscription_id:
                            extra_data["subscription_id"] = subscription_id

                        notification_data = {
                            "title": f"🎉 {n_type_label}完成 ({n_platform})",
                            "content": f"视频《{n_video_title}》下载完成！(注意：刮削可能未完全完成)\n\n🏷️ 来源: {n_platform}\n👤 博主: {n_author_name}\n⏰ 完成时间: {now_beijing().strftime('%Y-%m-%d %H:%M:%S')}",
                            "user_id": "default",
                            "extra_data": extra_data
                        }

                        def send_completed_notification():
                            try:
                                async def do_send():
                                    connector = aiohttp.UnixConnector(path="/app/sockets/easy-vdl.sock")
                                    async with aiohttp.ClientSession(connector=connector) as session:
                                        await session.post("http://localhost/api/notifications/download-completed", json=notification_data)
                                
                                loop = asyncio.new_event_loop()
                                asyncio.set_event_loop(loop)
                                try:
                                    loop.run_until_complete(do_send())
                                finally:
                                    loop.close()
                            except: pass

                        threading.Thread(target=send_completed_notification, daemon=True).start()
                    except: pass
                scrape_end = datetime.now()
                finished_name = filename_base if filename_base else task_id
                log_ts(f"自动刮削完成: {finished_name}，耗时: {(scrape_end-scrape_start).total_seconds():.2f}s")
                break  # 下载成功，跳出重试循环
            else:
                # 文件不存在，可能是还在合并中，等待一下再检查
                if retry_count < max_retries - 1:
                    log_ts(f"⚠️ 未找到下载完成的视频文件，可能还在合并中，等待 {retry_delay} 秒后重试...")
                    log_ts(f"📁 查找目录: {base_dir}")
                    log_ts(f"🔍 查找模式: {task_id}.* (支持: {', '.join(video_extensions)})")
                    # 列出目录中的文件以便调试
                    try:
                        if os.path.exists(base_dir):
                            files_in_dir = os.listdir(base_dir)
                            log_ts(f"📋 目录中的文件: {files_in_dir[:20]}")
                        else:
                            log_ts(f"❌ 目录不存在: {base_dir}")
                    except Exception as e:
                        log_ts(f"⚠️ 无法列出目录文件: {str(e)}")
                    await asyncio.sleep(retry_delay)
                    continue
                else:
                    log_ts(f"❌ 多次重试后仍未找到下载完成的视频文件")
                    update_task_progress(task_id, TaskStatus.ERROR, error="下载文件不存在", subscription_id=subscription_id, send_error_notification=True)
        except yt_dlp.utils.DownloadError as e:
            if "canceled by user" in str(e):
                # 清理所有临时文件
                for filename in temp_files:
                    try:
                        # 检查并删除.part文件
                        part_file = filename + '.part'
                        if os.path.exists(part_file):
                            os.remove(part_file)
                            print(f"已删除临时文件: {part_file}")
                        
                        # 检查并删除原文件
                        if os.path.exists(filename):
                            os.remove(filename)
                            print(f"已删除文件: {filename}")
                    except PermissionError as e:
                        print(f"没有权限删除文件: {filename}, 错误: {str(e)}")
                    except OSError as e:
                        print(f"删除文件失败: {filename}, 错误: {str(e)}")
                    except Exception as e:
                        print(f"删除文件时发生未知错误: {filename}, 错误: {str(e)}")
                
                update_task_progress(task_id, TaskStatus.CANCELLED, error="Download canceled by user.")
                break  # 用户取消，不再重试
            else:
                error_msg = str(e)
                
                # 智能判断是否应该重试
                if should_retry_error(error_msg):
                    if retry_count < max_retries - 1:
                        # 指数退避重试
                        actual_delay = retry_delay * (2 ** retry_count)
                        log_ts(f"可重试错误: {error_msg}，{actual_delay}秒后重试... (重试 {retry_count + 1}/{max_retries})")
                        
                        # 检查是否是字幕相关的429错误
                        if "429" in error_msg and ("subtitle" in error_msg.lower() or "caption" in error_msg.lower()):
                            log_ts("检测到字幕下载429错误，在重试时跳过字幕下载")
                            # 移除字幕相关选项，避免下次重试时再次遇到429错误
                            ydl_opts.pop('writesubtitles', None)
                            ydl_opts.pop('writeautomaticsub', None)
                            ydl_opts.pop('subtitleslangs', None)
                            ydl_opts.pop('subtitlesformat', None)
                        
                        await asyncio.sleep(actual_delay)
                        continue
                    else:
                        log_ts(f"达到最大重试次数，标记为错误: {error_msg}")
                        update_task_progress(task_id, TaskStatus.ERROR, error=error_msg, subscription_id=subscription_id, send_error_notification=True)
                else:
                    # 不可重试的错误，立即失败
                    log_ts(f"不可重试错误，立即失败: {error_msg}")
                    update_task_progress(task_id, TaskStatus.ERROR, error=error_msg, subscription_id=subscription_id, send_error_notification=True)
                    # 更新订阅视频的错误信息
                    if subscription_id:
                        try:
                            db = next(get_db())
                            video = db.query(SubscriptionVideo).filter(
                                SubscriptionVideo.download_task_id == task_id
                            ).first()
                            if video:
                                video.downloaded = "false"
                                video.error_message = error_msg
                                db.commit()
                        except Exception as db_error:
                            logger.error(f"更新订阅视频错误信息失败: {str(db_error)}")
                        finally:
                            try:
                                db.rollback()
                            except Exception:
                                pass
                            db.close()
                    break  # 不可重试错误，立即退出重试循环
        except Exception as e:
            error_msg = str(e)
            
            # 智能判断是否应该重试
            if should_retry_error(error_msg):
                if retry_count < max_retries - 1:
                    # 指数退避重试
                    actual_delay = retry_delay * (2 ** retry_count)
                    log_ts(f"可重试异常: {error_msg}，{actual_delay}秒后重试... (重试 {retry_count + 1}/{max_retries})")
                    await asyncio.sleep(actual_delay)
                    continue
                else:
                    log_ts(f"达到最大重试次数，标记为错误: {error_msg}")
                    update_task_progress(task_id, TaskStatus.ERROR, error=error_msg, subscription_id=subscription_id, send_error_notification=True)
            else:
                # 不可重试的异常，立即失败
                log_ts(f"不可重试异常，立即失败: {error_msg}")
                update_task_progress(task_id, TaskStatus.ERROR, error=error_msg, subscription_id=subscription_id, send_error_notification=True)
                # 更新订阅视频的错误信息
                if subscription_id:
                    try:
                        db = next(get_db())
                        video = db.query(SubscriptionVideo).filter(
                            SubscriptionVideo.download_task_id == task_id
                        ).first()
                        if video:
                            video.downloaded = "false"
                            video.error_message = error_msg
                            db.commit()
                    except Exception as db_error:
                        logger.error(f"更新订阅视频错误信息失败: {str(db_error)}")
                    finally:
                        try:
                            db.rollback()
                        except Exception:
                            pass
                        db.close()
                break  # 不可重试异常，立即退出重试循环
        finally:
            # 清理取消标志
            if task_id in cancel_flags:
                del cancel_flags[task_id]
            
            # 显式释放大对象，防止内存泄露
            try:
                if 'video_info' in locals():
                    del video_info
                if 'temp_files' in locals():
                    temp_files.clear()
                if 'ydl_opts' in locals():
                    ydl_opts.clear()
                # 强制垃圾回收，立即释放内存
                gc.collect()
                
                # 尝试强制归还系统内存 (Linux glibc)
                try:
                    import ctypes
                    libc = ctypes.CDLL("libc.so.6")
                    libc.malloc_trim(0)
                except Exception:
                    pass
            except:
                pass


# --- API Endpoints ---
@router.get("/api/ytd/")
async def root():
    return {"message": "Welcome to ytd-service"}

@router.get("/api/ytd/health")
async def health_check():
    return {"status": "ok", "service": "ytd-service"}

# 确保下载目录存在 (后续统一处理)
# @router.on_event("startup")
# async def startup_event():
#     # 创建youtube下载目录
#     youtube_dir = "/app/downloads/youtube"
#     os.makedirs(youtube_dir, exist_ok=True)
#     print(f"确保YouTube下载目录存在: {youtube_dir}")

@router.post("/api/ytd/info")
async def get_video_info(request: VideoInfoRequest, current_user: User = Depends(get_current_user)):
    try:
        ydl_opts = {'noplaylist': True, 'quiet': True, 'no_cache_dir': True}
        target_url = request.url
        
        # 只有YouTube链接才使用代理
        is_youtube = 'youtube.com' in request.url or 'youtu.be' in request.url
        is_bilibili = 'bilibili.com' in request.url
        if is_bilibili:
            target_url = _resolve_bilibili_url_without_browser(request.url)
            if target_url != request.url:
                logger.debug(f"[YTDL-INFO] B站链接轻量解析: {request.url} -> {target_url}")
        
        # 移除代理处理，完全依赖系统代理
        # 代理配置完全依赖系统环境变量
        
        # 直接从txt文件读取cookie
        youtube_cookie = None
        bilibili_cookie = None
        
        try:
            youtube_cookie_file = '/app/database/cookie/youtube_cookie.txt'
            if os.path.exists(youtube_cookie_file):
                with open(youtube_cookie_file, 'r', encoding='utf-8') as f:
                    youtube_cookie = f.read().strip()
                    if youtube_cookie:
                        # 从文件读取到YouTube Cookie
                        pass
                    else:
                        youtube_cookie = None
        except Exception as e:
            # 读取YouTube Cookie文件失败
            youtube_cookie = None
        
        try:
            bilibili_cookie_file = '/app/database/cookie/bilibili_cookie.txt'
            if os.path.exists(bilibili_cookie_file):
                with open(bilibili_cookie_file, 'r', encoding='utf-8') as f:
                    bilibili_cookie = f.read().strip()
                    if bilibili_cookie:
                        # 从文件读取到B站Cookie
                        pass
                    else:
                        bilibili_cookie = None
        except Exception as e:
            # 读取B站Cookie文件失败
            bilibili_cookie = None
        
        actual_cookie = youtube_cookie if is_youtube else (bilibili_cookie if is_bilibili else None)
        
        if actual_cookie:
            # 直接使用保存的cookie文件路径
            if is_youtube:
                ydl_opts['cookiefile'] = '/app/database/cookie/youtube_cookie.txt'
                logger.debug(f"[YTDL] 获取视频信息时使用了YouTube的cookie文件")
            elif is_bilibili:
                ydl_opts['cookiefile'] = '/app/database/cookie/bilibili_cookie.txt'
                logger.debug(f"[YTDL] 获取视频信息时使用了B站的cookie文件")
        
        # 为 YouTube 添加远程组件支持（yt-dlp 2025.11.12+ 需要）
        # 注意：remote_components 需要在顶层选项中设置
        if is_youtube:
            ydl_opts['remote_components'] = ['ejs:github']
        
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            try:
                info = ydl.extract_info(target_url, download=False)
            except Exception as e:
                if is_bilibili and _need_bilibili_browser_fallback(str(e)):
                    browser_url = await _resolve_bilibili_url_via_browser(
                        target_url,
                        task_id=f"info_{uuid.uuid4().hex[:8]}"
                    )
                    if browser_url and browser_url != target_url:
                        logger.debug(f"[YTDL-INFO] 浏览器兜底解析: {target_url} -> {browser_url}")
                        target_url = browser_url
                        info = ydl.extract_info(target_url, download=False)
                    else:
                        raise
                else:
                    raise
            formats = []
            
            # 收集所有格式信息
            all_formats = info.get('formats', [])
            logger.debug(f"[YTDL] 获取到总格式数量: {len(all_formats)}")
            
            # 分离视频和音频格式
            video_formats = []
            audio_formats = []
            
            for f in all_formats:
                has_video = f.get('vcodec') != 'none'
                has_audio = f.get('acodec') != 'none'
                
                logger.debug(f"[YTDL] 检查格式: ID={f.get('format_id')}, 分辨率={f.get('resolution')}, 视频={has_video}, 音频={has_audio}, URL={bool(f.get('url'))}, DRM={f.get('drm')}, 协议={f.get('protocol')}")
                
                # 跳过DRM保护的格式
                if f.get('drm') or f.get('has_drm'):
                    logger.debug(f"[YTDL] 跳过DRM格式: {f.get('format_id')}")
                    continue
                
                # 跳过没有URL的格式（通常是SABR流媒体）
                if not f.get('url'):
                    logger.debug(f"[YTDL] 跳过无URL格式: {f.get('format_id')}")
                    continue
                
                # 跳过fragment格式（通常不稳定）
                if f.get('fragments') or 'hls' in str(f.get('protocol', '')).lower():
                    logger.debug(f"[YTDL] 跳过fragment格式: {f.get('format_id')}")
                    continue
                
                if has_video and not has_audio:
                    # 纯视频格式
                    resolution = f.get('resolution', '0x0')
                    try:
                        height = int(resolution.split('x')[1]) if 'x' in resolution else 0
                        logger.debug(f"[YTDL] 视频格式: ID={f.get('format_id')}, 分辨率={resolution}, 高度={height}")
                        if height >= 240:  # 降低到240p以上，确保更多格式可用
                            video_formats.append(f)
                            logger.debug(f"[YTDL] 添加视频格式: {f.get('format_id')}")
                        else:
                            logger.debug(f"[YTDL] 跳过低分辨率视频: {f.get('format_id')}, 高度={height}")
                    except Exception as e:
                        logger.debug(f"[YTDL] 解析分辨率失败: {f.get('format_id')}, 错误={e}")
                        pass
                elif has_audio and not has_video:
                    # 纯音频格式
                    audio_formats.append(f)
                    logger.debug(f"[YTDL] 添加音频格式: {f.get('format_id')}")
                elif has_video and has_audio:
                    # 既有视频又有音频的格式（完整格式）
                    resolution = f.get('resolution', '0x0')
                    try:
                        height = int(resolution.split('x')[1]) if 'x' in resolution else 0
                        logger.debug(f"[YTDL] 完整格式: ID={f.get('format_id')}, 分辨率={resolution}, 高度={height}")
                        if height >= 240:  # 降低到240p以上，确保更多格式可用
                            # 直接添加到formats列表，不需要合成
                            format_info = {
                                'format_id': f.get('format_id'),
                                'ext': f.get('ext', 'mp4'),
                                'resolution': f.get('resolution'),
                                'format_note': f.get('format_note'),
                                'filesize': f.get('filesize'),
                                'fps': f.get('fps'),
                                'vcodec': f.get('vcodec'),
                                'acodec': f.get('acodec'),
                                'type': 'complete',
                                'quality': f.get('format_note') or f.get('resolution'),
                                'mergeAudio': False,
                                'videoFormatId': f.get('format_id'),
                                'audioFormatId': f.get('format_id'),
                                'videoExt': f.get('ext'),
                                'audioExt': f.get('ext'),
                                'requires_license': height > 2160  # 8K格式需要高级权限
                            }
                            # 计算文件大小
                            if format_info['filesize']:
                                if format_info['filesize'] > 1024 * 1024 * 1024:  # 大于1GB
                                    format_info['filesize_str'] = f"{format_info['filesize'] / (1024 * 1024 * 1024):.1f} GB"
                                elif format_info['filesize'] > 1024 * 1024:  # 大于1MB
                                    format_info['filesize_str'] = f"{format_info['filesize'] / (1024 * 1024):.1f} MB"
                                else:
                                    format_info['filesize_str'] = f"{format_info['filesize'] / 1024:.1f} KB"
                            else:
                                # 根据分辨率估算文件大小
                                resolution = f.get('resolution', '0x0')
                                try:
                                    height = int(resolution.split('x')[1]) if 'x' in resolution else 0
                                    if height >= 1080:
                                        format_info['filesize_str'] = "约 15-25 MB"
                                    elif height >= 720:
                                        format_info['filesize_str'] = "约 8-15 MB"
                                    elif height >= 480:
                                        format_info['filesize_str'] = "约 4-8 MB"
                                    elif height >= 360:
                                        format_info['filesize_str'] = "约 2-4 MB"
                                    elif height >= 240:
                                        format_info['filesize_str'] = "约 1-3 MB"
                                    else:
                                        format_info['filesize_str'] = "大小未知"
                                except:
                                    format_info['filesize_str'] = "大小未知"
                            
                            formats.append(format_info)
                            logger.debug(f"[YTDL] 添加完整格式: {f.get('format_id')}")
                        else:
                            logger.debug(f"[YTDL] 跳过低分辨率完整格式: {f.get('format_id')}, 高度={height}")
                    except Exception as e:
                        logger.debug(f"[YTDL] 解析完整格式分辨率失败: {f.get('format_id')}, 错误={e}")
                        pass
            
            # 按质量排序视频格式
            video_formats.sort(key=lambda x: int(x.get('resolution', '0x0').split('x')[1]) if 'x' in x.get('resolution', '0x0') else 0, reverse=True)
            logger.debug(f"[YTDL] 筛选后视频格式数量: {len(video_formats)}")
            logger.debug(f"[YTDL] 筛选后音频格式数量: {len(audio_formats)}")
            
            # 选择最佳音频格式（语言优先：中文 > 英文 > 其他，同语言内 m4a > aac > 其他）
            best_audio = None
            if audio_formats:
                audio_formats.sort(key=lambda x: (
                    0 if (x.get('language') or '').lower().startswith('zh') else
                    1 if (x.get('language') or '').lower().startswith('en') else
                    2,
                    x.get('ext') != 'm4a',   # m4a优先
                    x.get('ext') != 'aac',   # 然后aac
                    -(x.get('filesize') or 0)   # 文件大小降序
                ))
                best_audio = audio_formats[0]
                logger.debug(f"[YTDL] 选择最佳音频格式: {best_audio.get('format_id')}, 扩展名={best_audio.get('ext')}, 语言={best_audio.get('language', 'unknown')}")
            else:
                print("[YTDL] 警告: 没有找到可用的音频格式")
            
            # 生成合成格式选项（为所有视频格式生成合成选项）
            if len(video_formats) > 0 and best_audio:
                logger.debug(f"[YTDL] 开始生成合成格式，视频格式数量: {len(video_formats)}")
                for video_f in video_formats:
                    # 创建合成格式
                    # 检查是否为8K格式（高度>2160）
                    resolution = video_f.get('resolution', '0x0')
                    try:
                        height = int(resolution.split('x')[1]) if 'x' in resolution else 0
                    except:
                        height = 0
                    
                    format_info = {
                        'format_id': f"{video_f.get('format_id')}+{best_audio.get('format_id')}",
                        'ext': 'mp4',
                        'resolution': video_f.get('resolution'),
                        'format_note': video_f.get('format_note'),
                        'filesize': (video_f.get('filesize', 0) + best_audio.get('filesize', 0)) if video_f.get('filesize') and best_audio.get('filesize') else None,
                        'fps': video_f.get('fps'),
                        'vcodec': video_f.get('vcodec'),
                        'acodec': best_audio.get('acodec'),
                        'type': 'complete',
                        'quality': f"{video_f.get('format_note') or video_f.get('resolution')} + 音频合成",
                        'mergeAudio': True,
                        'videoFormatId': video_f.get('format_id'),
                        'audioFormatId': best_audio.get('format_id'),
                        'videoExt': video_f.get('ext'),
                        'audioExt': best_audio.get('ext'),
                        'requires_license': height > 2160  # 8K格式需要高级权限
                    }
                    logger.debug(f"[YTDL] 生成合成格式: {format_info['format_id']}, 分辨率={format_info['resolution']}")
                    
                    # 计算文件大小
                    if format_info['filesize']:
                        if format_info['filesize'] > 1024 * 1024 * 1024:  # 大于1GB
                            format_info['filesize_str'] = f"{format_info['filesize'] / (1024 * 1024 * 1024):.1f} GB"
                        elif format_info['filesize'] > 1024 * 1024:  # 大于1MB
                            format_info['filesize_str'] = f"{format_info['filesize'] / (1024 * 1024):.1f} MB"
                        else:
                            format_info['filesize_str'] = f"{format_info['filesize'] / 1024:.1f} KB"
                    else:
                        # 根据分辨率估算文件大小
                        resolution = video_f.get('resolution', '0x0')
                        try:
                            height = int(resolution.split('x')[1]) if 'x' in resolution else 0
                            if height >= 1080:
                                format_info['filesize_str'] = "约 15-25 MB"
                            elif height >= 720:
                                format_info['filesize_str'] = "约 8-15 MB"
                            elif height >= 480:
                                format_info['filesize_str'] = "约 4-8 MB"
                            elif height >= 360:
                                format_info['filesize_str'] = "约 2-4 MB"
                            elif height >= 240:
                                format_info['filesize_str'] = "约 1-3 MB"
                            else:
                                format_info['filesize_str'] = "大小未知"
                        except:
                            format_info['filesize_str'] = "大小未知"
                    
                    formats.append(format_info)
            else:
                if len(video_formats) == 0:
                    logger.debug(f"[YTDL] 跳过合成格式生成，没有可用的视频格式")
                elif not best_audio:
                    logger.debug(f"[YTDL] 跳过合成格式生成，没有可用的音频格式")
                else:
                    logger.debug(f"[YTDL] 跳过合成格式生成，未知原因")
                    
            # 按分辨率排序（降序）
            formats.sort(key=lambda x: int(x.get('resolution', '0x0').split('x')[1]) if 'x' in x.get('resolution', '0x0') else 0, reverse=True)
            logger.debug(f"[YTDL] 最终生成的格式数量: {len(formats)}")
            if len(formats) == 0:
                logger.warning("[YTDL] 警告: 没有生成任何可下载格式！")
                # 调试信息（debug级别）
                logger.debug(f"[YTDL] 视频格式列表: {[f.get('format_id') for f in video_formats]}")
                logger.debug(f"[YTDL] 音频格式列表: {[f.get('format_id') for f in audio_formats]}")
            
            # B站封面兜底逻辑
            thumbnail = info.get('thumbnail')
            # 兜底：如果有 thumbnails 列表，取最大分辨率
            if (not thumbnail or thumbnail.strip() == '') and 'thumbnails' in info and info['thumbnails']:
                thumbnail = info['thumbnails'][-1].get('url', '')

            # B站特殊兜底
            if (not thumbnail or thumbnail.strip() == '') and 'bilibili.com' in info.get('webpage_url', ''):
                # 尝试从 info['pic'] 字段获取（yt-dlp新版可能有）
                thumbnail = info.get('pic', '')
                # 如果还没有，返回一个默认B站 LOGO
                if not thumbnail:
                    thumbnail = 'https://www.bilibili.com/favicon.ico'
            
            return {
                "title": info.get('title'),
                "duration": info.get('duration'),
                "uploader": info.get('uploader'),
                "formats": formats,
                "thumbnail": thumbnail,  # 优先用兜底
                "webpage_url": info.get('webpage_url')
            }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/api/ytd/download")
async def start_download(request: DownloadRequest, background_tasks: BackgroundTasks, current_user: User = Depends(get_current_user_or_token), db: Session = Depends(get_db)):
    task_id = str(uuid.uuid4())
    try:
        create_task_in_db(db, task_id, request.url, request.proxy, request.youtube_cookie, request.bilibili_cookie, request.format_id, request.subscription_id)
    finally:
        try:
            db.rollback()
        except Exception:
            pass
        db.close()
    
    cancel_flags[task_id] = False
    # 如果未指定 format_id，使用默认最高画质
    format_id = request.format_id or "bestvideo+bestaudio"
    background_tasks.add_task(
        download_video_logic,
        task_id,
        request.url,
        format_id,
        request.youtube_cookie,
        request.bilibili_cookie,
        request.proxy,
        request.subtitles,
        request.thumbnail,
        download_dir=None, # 移除download_dir参数，由download_video_logic内部处理
        subscription_id=request.subscription_id # 传递订阅ID
    )
    return {"message": "Download started", "task_id": task_id}

@router.post("/api/ytd/cancel/{task_id}")
async def cancel_download(task_id: str, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    try:
        task = db.query(Task).filter(Task.id == task_id).first()
        if not task or task.status in [TaskStatus.COMPLETED, TaskStatus.ERROR, TaskStatus.CANCELLED]:
             raise HTTPException(status_code=404, detail="任务不存在或已完成，无法取消。")
        
        # 设置取消标志
        cancel_flags[task_id] = True
        
        # 清理已下载的文件（如果存在）
        if task.filename:
            # 检查是否是新格式的文件夹结构
            if '/' in task.filename:
                # 新格式的文件夹/文件名
                folder_name = task.filename.split('/')[0]
                folder_path = os.path.join("/app/downloads/youtube", folder_name)
                
                # 删除整个文件夹
                if os.path.exists(folder_path):
                    try:
                        import shutil
                        shutil.rmtree(folder_path)
                        print(f"已删除取消任务的文件夹: {folder_path}")
                    except Exception as e:
                        print(f"删除文件夹失败: {folder_path}, 错误: {str(e)}")
            else:
                # 旧格式：直接文件名
                file_path = os.path.join("/app/downloads/youtube", task.filename)
                part_file = file_path + '.part'
                
                if not os.path.exists(file_path):
                    # 如果没找到，尝试在根目录查找（兼容旧文件）
                    file_path = os.path.join("/app/downloads", task.filename)
                    part_file = file_path + '.part'
                
                # 删除.part文件
                if os.path.exists(part_file):
                    try:
                        os.remove(part_file)
                        print(f"已删除临时文件: {part_file}")
                    except Exception as e:
                        print(f"删除临时文件失败: {part_file}, 错误: {str(e)}")
                
                # 删除原文件
                if os.path.exists(file_path):
                    try:
                        os.remove(file_path)
                        print(f"已删除文件: {file_path}")
                    except Exception as e:
                        print(f"删除文件失败: {file_path}, 错误: {str(e)}")
                
                # 如果都不存在，记录日志
                if not os.path.exists(file_path) and not os.path.exists(part_file):
                    print(f"未找到任何相关文件: {task.filename}")
        
        # 更新任务状态为已取消
        update_task_progress(task_id, TaskStatus.CANCELLED, error="Download canceled by user.")
        
        return {"message": "Cancellation request sent and temporary files cleaned."}
    finally:
        try:
            db.rollback()
        except Exception:
            pass
        db.close()

@router.post("/api/ytd/resume/{task_id}")
async def resume_download(task_id: str, background_tasks: BackgroundTasks, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    task = db.query(Task).filter(Task.id == task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    
    # 检查cookie文件是否存在
    youtube_cookie_exists = os.path.exists('/app/database/cookie/youtube_cookie.txt')
    bilibili_cookie_exists = os.path.exists('/app/database/cookie/bilibili_cookie.txt')
    
    if youtube_cookie_exists:
        print(f"[YTDL] 恢复下载时检测到YouTube Cookie文件")
    if bilibili_cookie_exists:
        print(f"[YTDL] 恢复下载时检测到B站Cookie文件")
    
    # 重新开始下载，传递空字符串，让函数内部从文件读取
    background_tasks.add_task(
        download_video_logic,
        task_id,
        task.url,
        task.format_id,
        '',  # 传递空字符串，让函数内部从文件读取
        '',  # 传递空字符串，让函数内部从文件读取
        task.proxy,
        True,  # subtitles
        True   # thumbnail
    )
    
    return {"message": "Download resumed", "task_id": task_id}

# 代理测试功能
async def test_proxy_connection(proxy_url: str, test_url: str = "https://httpbin.org/ip"):
    """测试代理连接"""
    import time
    import asyncio
    import requests
    from concurrent.futures import ThreadPoolExecutor
    
    start_time = time.time()
    
    def test_proxy_sync(test_target_url):
        """同步测试代理连接"""
        try:
            # 设置代理配置
            proxies = {
                "http": proxy_url,
                "https": proxy_url,
            }
            
            # 设置超时时间 - HTTP/HTTPS代理
            timeout = (5, 15)   # HTTP代理：连接5秒，读取15秒
            
            # 发送测试请求
            response = requests.get(test_target_url, proxies=proxies, timeout=timeout)
            
            return {
                "success": True,
                "status_code": response.status_code,
                "message": "代理连接成功",
                "test_url": test_target_url
            }
            
        except requests.exceptions.ConnectTimeout:
            return {
                "success": False,
                "error": "连接超时 - 代理服务器无响应"
            }
        except requests.exceptions.ReadTimeout:
            return {
                "success": False,
                "error": "读取超时 - 代理服务器响应过慢，请检查网络连接"
            }
        except requests.exceptions.ProxyError as e:
            return {
                "success": False,
                "error": f"代理错误: {str(e)}"
            }
        except requests.exceptions.RequestException as e:
            error_msg = str(e)
            if "Read timed out" in error_msg:
                return {
                    "success": False,
                    "error": "读取超时 - 代理服务器响应过慢，请检查网络连接"
                }
            else:
                return {
                    "success": False,
                    "error": f"请求错误: {error_msg}"
                }
        except Exception as e:
            return {
                "success": False,
                "error": f"未知错误: {str(e)}"
            }
    
    try:
        # 在线程池中运行同步请求
        loop = asyncio.get_event_loop()
        with ThreadPoolExecutor() as executor:
            # 先尝试轻量测试
            result = await loop.run_in_executor(executor, test_proxy_sync, "https://httpbin.org/ip")
            
            # 如果轻量测试成功，再尝试YouTube测试
            if result["success"]:
                # 对于HTTP代理，额外测试YouTube连接
                youtube_result = await loop.run_in_executor(executor, test_proxy_sync, "https://www.youtube.com")
                if youtube_result["success"]:
                    result["message"] = "代理连接成功（已通过YouTube测试）"
                    result["youtube_test"] = True
                else:
                    result["message"] = "基础连接成功，但YouTube访问较慢"
                    result["youtube_test"] = False
                    result["youtube_error"] = youtube_result.get("error", "未知错误")
        
        # 计算响应时间
        end_time = time.time()
        response_time = int((end_time - start_time) * 1000)
        
        # 添加响应时间到结果
        result["response_time"] = response_time
        
        return result
        
    except Exception as e:
        return {
            "success": False,
            "response_time": int((time.time() - start_time) * 1000),
            "error": f"测试执行错误: {str(e)}"
        }

@router.post("/api/ytd/test-proxy")
async def test_proxy(request: ProxyTestRequest, current_user: User = Depends(get_current_user)):
    """测试代理连接"""
    try:
        result = await test_proxy_connection(request.proxy, request.test_url)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"代理测试失败: {str(e)}")

@router.get("/api/ytd/proxy-bili-cover")
def proxy_bili_cover(current_user: Optional[User] = Depends(get_current_user_optional), url: str = Query(...), cookie: str = Query(None)):
    headers = {
        'Referer': 'https://www.bilibili.com/',
        'User-Agent': 'Mozilla/5.0'
    }
    cookies = {}
    if cookie:
        for kv in cookie.split(';'):
            if '=' in kv:
                k, v = kv.strip().split('=', 1)
                cookies[k] = v
    resp = requests.get(url, headers=headers, cookies=cookies, timeout=10)
    return Response(content=resp.content, media_type=resp.headers.get('Content-Type', 'image/jpeg'))
