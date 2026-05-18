import os
import shutil
import logging
import subprocess
import asyncio
import urllib.parse
import math
import time
import signal
import threading
from functools import lru_cache
from typing import Any, Dict, List, Optional, Set
from fastapi import APIRouter, Depends, HTTPException, Query, Body, BackgroundTasks, Request, Response
from fastapi.responses import JSONResponse, StreamingResponse, Response as FastAPIResponse
from sqlalchemy.orm import Session
from datetime import datetime, timezone, timedelta
import uuid
from sqlalchemy import text, func, or_
import json
import httpx

from sql import models
from sql.database_postgresql import get_db, get_session
from routers.auth import get_current_user, get_current_user_mixed
from sql.models import User

# 配置日志
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


# 创建APIRouter实例
router = APIRouter()


def should_use_original_start_stream(safe_start: float, request_range: Optional[str]) -> bool:
    """
    original 流决策规则：
    - safe_start > 0：优先服务端 start 起播（高于 Range）
    - safe_start <= 0：走常规 Range 文件流
    """
    try:
        start_value = float(safe_start or 0.0)
    except (TypeError, ValueError):
        start_value = 0.0
    return start_value > 0.0


def _resolve_download_abs_path(relative_path: str) -> tuple[str, str]:
    """将下载目录相对路径解析为绝对路径，并阻止路径越界。"""
    base_dir = "/app/downloads"
    decoded = urllib.parse.unquote(str(relative_path or ""))
    normalized = os.path.normpath(decoded).replace("\\", "/").lstrip("/")
    if not normalized or normalized.startswith(".."):
        raise HTTPException(status_code=400, detail="无效的文件路径")

    base_real = os.path.realpath(base_dir)
    abs_path = os.path.realpath(os.path.join(base_real, normalized))
    if abs_path != base_real and not abs_path.startswith(base_real + os.sep):
        raise HTTPException(status_code=400, detail="无效的文件路径")
    return abs_path, normalized


def _guess_subtitle_lang_from_suffix(suffix: str) -> str:
    if not suffix:
        return "und"
    token = suffix.strip().replace("_", "-").split(".")[0].split("-")[0].lower()
    if not token:
        return "und"
    if token in {"sub", "subtitle", "captions", "caption", "auto", "default"}:
        return "und"
    return token


def _read_text_with_fallback(path: str) -> str:
    encodings = ("utf-8-sig", "utf-8", "gb18030", "cp936", "latin-1")
    for encoding in encodings:
        try:
            with open(path, "r", encoding=encoding, errors="strict") as f:
                return f.read()
        except UnicodeDecodeError:
            continue
        except Exception:
            break
    with open(path, "r", encoding="utf-8", errors="ignore") as f:
        return f.read()


def _srt_to_webvtt(content: str) -> str:
    text = str(content or "").replace("\r\n", "\n").replace("\r", "\n")
    stripped = text.lstrip("\ufeff").strip()
    if stripped.startswith("WEBVTT"):
        return text if text.startswith("WEBVTT") else f"WEBVTT\n\n{text}"

    # 解析 SRT 为结构化 cue 列表
    def _ts_to_sec(ts: str) -> float:
        """将 SRT 时间戳（hh:mm:ss,mmm）转换为秒。"""
        ts = ts.replace(",", ".")
        parts = ts.split(":")
        if len(parts) == 3:
            return int(parts[0]) * 3600 + int(parts[1]) * 60 + float(parts[2])
        return 0.0

    def _sec_to_vtt(sec: float) -> str:
        """将秒数转换为 VTT 时间戳（hh:mm:ss.mmm）。"""
        h = int(sec // 3600)
        m = int((sec % 3600) // 60)
        s = sec % 60
        return f"{h:02d}:{m:02d}:{s:06.3f}"

    # 按空行分割 SRT 块
    blocks = []
    current_block: List[str] = []
    for line in text.split("\n"):
        raw = line.rstrip("\n")
        if raw.strip() == "" and current_block:
            blocks.append(current_block)
            current_block = []
        elif raw.strip():
            current_block.append(raw)
    if current_block:
        blocks.append(current_block)

    cues: List[dict] = []
    for block in blocks:
        if len(block) < 2:
            continue
        timecode_line = None
        text_lines: List[str] = []
        for line in block:
            if "-->" in line:
                timecode_line = line
            elif line.strip().isdigit():
                continue
            else:
                text_lines.append(line)
        if not timecode_line or not text_lines:
            continue
        parts = timecode_line.split("-->")
        if len(parts) != 2:
            continue
        start_sec = _ts_to_sec(parts[0].strip())
        end_sec = _ts_to_sec(parts[1].strip())
        cues.append({"start": start_sec, "end": end_sec, "text": "\n".join(text_lines)})

    # 修剪重叠：后一个 cue 开始前，前一个 cue 必须结束
    for i in range(1, len(cues)):
        prev = cues[i - 1]
        curr = cues[i]
        if curr["start"] < prev["end"]:
            prev["end"] = curr["start"]

    # 输出 VTT
    out_lines: List[str] = ["WEBVTT", ""]
    for cue in cues:
        out_lines.append(f"{_sec_to_vtt(cue['start'])} --> {_sec_to_vtt(cue['end'])} line:82% position:50% align:center")
        out_lines.append(cue["text"])
        out_lines.append("")
    return "\n".join(out_lines).strip() + "\n"


def _apply_default_vtt_cue_position(content: str) -> str:
    """统一所有 VTT cue 到底部居中位置，避免 YouTube 多音轨/多说话者重叠。"""
    text = str(content or "").replace("\r\n", "\n").replace("\r", "\n")
    lines = text.split("\n")
    out: List[str] = []
    for raw in lines:
        line = raw
        if "-->" in raw:
            # 清除所有已有的 line:/position:/align:，统一到底部居中
            base = raw.split(" line:")[0].split(" position:")[0].split(" align:")[0]
            line = f"{base} line:82% position:50% align:center"
        out.append(line)
    return "\n".join(out)

# 缓存视频时长，减少重复 ffprobe 调用的开销（缓存键为绝对路径）
@lru_cache(maxsize=1024)
def _probe_video_duration_cached(abs_file_path: str) -> Optional[float]:
    """使用 ffprobe 获取视频时长，结果会缓存以避免重复计算。"""
    try:
        if not abs_file_path:
            return None
        probe_cmd = [
            "ffprobe", "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            abs_file_path
        ]
        result = subprocess.run(
            probe_cmd,
            capture_output=True,
            text=True,
            timeout=5
        )
        if result.returncode != 0:
            logger.warning(f"ffprobe 获取视频时长失败 (返回码: {result.returncode}): {result.stderr.strip() or result.stdout.strip()}")
            return None
        raw_value = (result.stdout or "").strip()
        if not raw_value:
            return None
        try:
            duration = float(raw_value)
            if duration <= 0:
                return None
            return duration
        except ValueError:
            logger.warning(f"解析视频时长失败，输出值: {raw_value}")
            return None
    except subprocess.TimeoutExpired:
        logger.warning(f"ffprobe 获取视频时长超时: {abs_file_path}")
        return None
    except Exception as exc:
        logger.error(f"获取视频时长时出现异常: {exc}")
        return None


@lru_cache(maxsize=1024)
def _probe_video_metadata_cached(abs_file_path: str) -> Dict[str, Any]:
    """使用 ffprobe 获取视频元数据（时长、分辨率、码率），结果缓存。"""
    meta: Dict[str, Any] = {
        "duration": None,
        "width": None,
        "height": None,
        "video_bitrate": None,
        "audio_bitrate": None,
        "format_bitrate": None
    }
    try:
        if not abs_file_path:
            return meta

        probe_cmd = [
            "ffprobe", "-v", "error",
            "-show_entries", "format=duration,bit_rate:stream=codec_type,width,height,bit_rate",
            "-of", "json",
            abs_file_path
        ]
        result = subprocess.run(
            probe_cmd,
            capture_output=True,
            text=True,
            timeout=8
        )
        if result.returncode != 0:
            logger.warning(f"ffprobe 获取视频元数据失败 (返回码: {result.returncode}): {result.stderr.strip() or result.stdout.strip()}")
            return meta

        payload = json.loads(result.stdout or "{}")
        format_info = payload.get("format") or {}
        streams = payload.get("streams") or []

        def _to_float(value: Any) -> Optional[float]:
            try:
                if value is None:
                    return None
                number = float(value)
                if not math.isfinite(number) or number <= 0:
                    return None
                return number
            except Exception:
                return None

        def _to_int(value: Any) -> Optional[int]:
            try:
                if value is None:
                    return None
                number = int(float(value))
                if number <= 0:
                    return None
                return number
            except Exception:
                return None

        meta["duration"] = _to_float(format_info.get("duration"))
        format_bitrate = _to_int(format_info.get("bit_rate"))
        if format_bitrate:
            meta["format_bitrate"] = format_bitrate

        video_stream = next((s for s in streams if (s.get("codec_type") or "").lower() == "video"), None)
        if video_stream:
            meta["width"] = _to_int(video_stream.get("width"))
            meta["height"] = _to_int(video_stream.get("height"))
            video_bitrate = _to_int(video_stream.get("bit_rate"))
            if video_bitrate:
                meta["video_bitrate"] = video_bitrate

        audio_stream = next((s for s in streams if (s.get("codec_type") or "").lower() == "audio"), None)
        if audio_stream:
            audio_bitrate = _to_int(audio_stream.get("bit_rate"))
            if audio_bitrate:
                meta["audio_bitrate"] = audio_bitrate

        return meta
    except subprocess.TimeoutExpired:
        logger.warning(f"ffprobe 获取视频元数据超时: {abs_file_path}")
        return meta
    except Exception as exc:
        logger.error(f"获取视频元数据时出现异常: {exc}")
        return meta


def _parse_ffprobe_frame_rate(rate_str: Any) -> Optional[float]:
    """解析 ffprobe 返回的帧率字段（如 60000/1001 或 30）。"""
    try:
        raw = str(rate_str or "").strip()
        if not raw or raw in {"0", "0/0"}:
            return None
        if "/" in raw:
            num_str, den_str = raw.split("/", 1)
            num = float(num_str)
            den = float(den_str)
            if den == 0:
                return None
            fps = num / den
        else:
            fps = float(raw)
        if not math.isfinite(fps) or fps <= 0:
            return None
        return fps
    except Exception:
        return None


def _parse_ffprobe_bit_depth(bits_per_raw_sample: Any, pix_fmt: Any) -> Optional[int]:
    """
    从 ffprobe 字段推断位深：
    1) 优先 bits_per_raw_sample；
    2) 回退到 pix_fmt 中的 p10/p12/p16 标记。
    """
    try:
        if bits_per_raw_sample is not None:
            value = int(float(bits_per_raw_sample))
            if value > 0:
                return value
    except Exception:
        pass

    fmt = str(pix_fmt or "").strip().lower()
    if not fmt:
        return None

    for marker, depth in (("p16", 16), ("p14", 14), ("p12", 12), ("p10", 10), ("p9", 9), ("p8", 8)):
        if marker in fmt:
            return depth
    if fmt.endswith("p") or "nv12" in fmt or "yuyv" in fmt or "uyvy" in fmt:
        return 8
    return None


@lru_cache(maxsize=1024)
def _probe_stream_profile_cached(abs_file_path: str) -> Dict[str, Any]:
    """
    获取流播放所需的核心探测信息（宽高/FPS/是否有音频/视频编码/像素格式等）。
    通过单次 ffprobe 返回，避免每次请求重复 2~3 次探测。
    """
    profile: Dict[str, Any] = {
        "width": None,
        "height": None,
        "fps": None,
        "has_audio": False,
        "video_codec": None,
        "pix_fmt": None,
        "video_profile": None,
        "bit_depth": None
    }
    try:
        if not abs_file_path:
            return profile

        probe_cmd = [
            "ffprobe", "-v", "error",
            "-show_entries", "stream=codec_type,codec_name,profile,pix_fmt,bits_per_raw_sample,width,height,avg_frame_rate",
            "-of", "json",
            abs_file_path
        ]
        result = subprocess.run(
            probe_cmd,
            capture_output=True,
            text=True,
            timeout=8
        )
        if result.returncode != 0:
            logger.warning(
                "ffprobe 获取播放探测信息失败 (返回码: %s): %s",
                result.returncode,
                (result.stderr.strip() or result.stdout.strip())
            )
            return profile

        payload = json.loads(result.stdout or "{}")
        streams = payload.get("streams") or []
        for stream in streams:
            codec_type = (stream.get("codec_type") or "").lower()
            if codec_type == "audio":
                profile["has_audio"] = True
                continue
            if codec_type != "video":
                continue
            if profile["width"] is None:
                try:
                    width = int(float(stream.get("width")))
                    if width > 0:
                        profile["width"] = width
                except Exception:
                    pass
            if profile["height"] is None:
                try:
                    height = int(float(stream.get("height")))
                    if height > 0:
                        profile["height"] = height
                except Exception:
                    pass
            if profile["fps"] is None:
                profile["fps"] = _parse_ffprobe_frame_rate(stream.get("avg_frame_rate"))
            if profile["video_codec"] is None:
                codec_name = (stream.get("codec_name") or "").strip().lower()
                if codec_name:
                    profile["video_codec"] = codec_name
            if profile["pix_fmt"] is None:
                pix_fmt = (stream.get("pix_fmt") or "").strip().lower()
                if pix_fmt:
                    profile["pix_fmt"] = pix_fmt
            if profile["video_profile"] is None:
                video_profile = (stream.get("profile") or "").strip()
                if video_profile:
                    profile["video_profile"] = video_profile
            if profile["bit_depth"] is None:
                bit_depth = _parse_ffprobe_bit_depth(
                    stream.get("bits_per_raw_sample"),
                    stream.get("pix_fmt")
                )
                if bit_depth and bit_depth > 0:
                    profile["bit_depth"] = bit_depth
            # 不能在拿到视频参数后提前退出，否则可能错过后续音频流，
            # 导致 has_audio 误判为 False，进而转码被错误地加上 -an。
        return profile
    except subprocess.TimeoutExpired:
        logger.warning(f"ffprobe 获取播放探测信息超时: {abs_file_path}")
        return profile
    except Exception as exc:
        logger.error(f"获取播放探测信息时出现异常: {exc}")
        return profile

# --- 任务管理 API ---

def now_beijing():
    """获取当前北京时间（东八区，带时区）"""
    return datetime.now(timezone(timedelta(hours=8)))


def _normalize_task_source(source: str | None, url: str | None) -> str:
    """规范化任务来源，必要时根据 URL 兜底推断平台。"""
    src = (source or "").lower().strip()
    if src in ['youtube', 'bilibili', 'douyin', 'xiaohongshu', 'tiktok', 'instagram', 'netease', 'x', 'others', 'unknown']:
        return src
    url = url or ""
    if url.startswith("https://www.youtube.com") or url.startswith("https://youtu.be"):
        return "youtube"
    if url.startswith("https://www.bilibili.com") or url.startswith("https://b23.tv"):
        return "bilibili"
    if url.startswith("https://www.douyin.com") or url.startswith("https://v.douyin.com"):
        return "douyin"
    if url.startswith("https://www.xiaohongshu.com") or url.startswith("https://xhslink.com"):
        return "xiaohongshu"
    if url.startswith("https://www.tiktok.com") or url.startswith("https://vt.tiktok.com"):
        return "tiktok"
    if "instagram.com" in url or "cdninstagram.com" in url:
        return "instagram"
    if url.startswith("https://music.163.com"):
        return "netease"
    if "x.com" in url or "twitter.com" in url:
        return "x"
    return "others"


def _proxy_avatar_url(platform: str, url: Optional[str]) -> Optional[str]:
    """将 Instagram 等有跨域限制的 CDN 头像 URL 转为后端代理 URL"""
    if not url:
        return url
    _INSTAGRAM_CDN_DOMAINS = ("scontent-nrt", "scontent-", "cdninstagram.com")
    if platform == "instagram" and any(domain in url for domain in _INSTAGRAM_CDN_DOMAINS):
        return f"/api/system/avatar-proxy?url={urllib.parse.quote(url)}"
    return url


@router.get("/api/tasks/")
def get_all_tasks(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    status: str = Query(None, description="任务状态过滤：DOWNLOADING, PROCESSING, COMPLETED, ERROR, CANCELLED, PENDING"),
    subscription_id: str = Query(None, description="按订阅ID筛选任务"),
    author_name: str = Query(None, description="按博主名称筛选任务"),
    platform: str = Query(None, description="按平台筛选：youtube/bilibili/douyin/xiaohongshu/tiktok/instagram/netease/x/others"),
    manual_only: bool = Query(False, description="仅手动下载（订阅ID为空）"),
    orphan_only: bool = Query(False, description="仅文件缺失的孤儿任务"),
    query_str: str = Query(None, alias="query", description="搜索关键词：标题、文件名、URL或博主")
):
    """分页获取下载任务，支持状态、订阅ID和博主名称过滤"""
    try:
        query = db.query(models.Task).order_by(models.Task.created_at.desc())
        
        # 如果指定了状态过滤，添加过滤条件
        if status and status != 'all':
            status_lower = status.lower()
            if status_lower == 'active':
                # 活跃状态：排队中、下载中或处理中
                query = query.filter(models.Task.status.in_(['PENDING', 'DOWNLOADING', 'PROCESSING']))
            elif status_lower == 'completed':
                query = query.filter(models.Task.status == 'COMPLETED')
            elif status_lower == 'error':
                query = query.filter(models.Task.status == 'ERROR')
            elif status_lower == 'cancelled':
                query = query.filter(models.Task.status == 'CANCELLED')
            elif status in ['DOWNLOADING', 'PROCESSING', 'COMPLETED', 'ERROR', 'CANCELLED', 'PENDING']:
                # 直接状态过滤（大写状态值）
                query = query.filter(models.Task.status == status)
        
        # 如果指定了订阅ID过滤，添加过滤条件
        if subscription_id:
            query = query.filter(models.Task.subscription_id == subscription_id)
        
        # 手动下载筛选：订阅ID为空
        if manual_only:
            query = query.filter(models.Task.subscription_id.is_(None))

        # 平台筛选：按 source 字段（保持 unknown 作为独立平台选项）
        if platform:
            p = platform.lower()
            if p in ['youtube', 'bilibili', 'douyin', 'xiaohongshu', 'tiktok', 'instagram', 'netease', 'x', 'unknown', 'others']:
                query = query.filter(models.Task.source == p)

        # 如果指定了博主名称过滤，通过订阅ID关联查询
        if author_name:
            # 先查找匹配的订阅
            subscriptions = db.query(models.Subscription).filter(
                models.Subscription.nickname.ilike(f"%{author_name}%")
            ).all()
            if subscriptions:
                subscription_ids = [sub.id for sub in subscriptions]
                query = query.filter(models.Task.subscription_id.in_(subscription_ids))
            else:
                # 如果没有找到匹配的订阅，返回空结果
                return {"total": 0, "tasks": []}
        
        # 全局关键词搜索 (标题/文件名/URL/博主名)
        if query_str:
            search_pattern = f"%{query_str}%"
            # 使用 left outer join 以确保包含没有订阅信息的手动任务
            query = query.outerjoin(models.Subscription, models.Task.subscription_id == models.Subscription.id)
            query = query.filter(
                or_(
                    models.Task.title.ilike(search_pattern),
                    models.Task.filename.ilike(search_pattern),
                    models.Task.url.ilike(search_pattern),
                    models.Subscription.nickname.ilike(search_pattern)
                )
            )
        
        if orphan_only:
            # 先取全集合，检查文件存在性后再分页
            all_candidates = query.all()
            orphan_tasks = []
            base_dir = "/app/downloads"
            for t in all_candidates:
                try:
                    if t.filename:
                        file_path = os.path.join(base_dir, t.filename)
                        if not os.path.exists(file_path):
                            orphan_tasks.append(t)
                except Exception:
                    # 忽略异常
                    continue
            total = len(orphan_tasks)
            tasks = orphan_tasks[offset: offset + limit]
        else:
            # 常规路径：数据库分页
            db_total = query.count()
            tasks = query.offset(offset).limit(limit).all()
            total = db_total
        
        def determine_task_type_display(subscription: models.Subscription, task_url: str = None) -> str:
            try:
                # 首先判断是否为图集（通过 URL 判断）
                if task_url and '/note/' in task_url:
                    platform = (subscription.platform or "").lower()
                    if platform in ["douyin", "douyin_collection"]:
                        return "订阅抖音图集"
                    elif platform == "xiaohongshu":
                        return "订阅小红书图集"
                    else:
                        return "订阅图集"
                
                platform = (subscription.platform or "").lower()
                tab_type = (subscription.youtube_tab_type or "").lower() if hasattr(subscription, "youtube_tab_type") else ""
                if platform == "douyin_collection":
                    return "订阅抖音合集"
                if platform == "douyin":
                    # 区分抖音博主订阅和抖音点赞订阅
                    subscription_type = getattr(subscription, 'subscription_type', None)
                    if subscription_type == "favorite":
                        return "订阅抖音点赞"
                    return "订阅抖音博主"
                if platform == "youtube_playlist" or (platform == "youtube" and tab_type == "playlists"):
                    return "订阅油管合集"
                if platform == "bilibili_collection":
                    return "订阅B站合集"
                if platform == "bilibili":
                    # 区分B站博主订阅和B站收藏订阅
                    subscription_type = getattr(subscription, 'subscription_type', None)
                    if subscription_type == "favorite":
                        return "订阅B站收藏"
                    return "订阅B站博主"
                if platform == "youtube":
                    if tab_type == "shorts":
                        return "订阅油管短视频"
                    return "订阅油管博主"
                if platform == "tiktok":
                    return "订阅TikTok博主"
                if platform == "xiaohongshu":
                    return "订阅小红书博主"
                return "订阅博主"
            except Exception:
                return "订阅博主"

        # 【性能优化】批量查询所有相关的订阅信息，避免N+1查询
        subscription_ids = [t.subscription_id for t in tasks if t.subscription_id]
        subscriptions_dict = {}
        if subscription_ids:
            subscriptions = db.query(models.Subscription).filter(
                models.Subscription.id.in_(subscription_ids)
            ).all()
            subscriptions_dict = {sub.id: sub for sub in subscriptions}
        
        valid_tasks = []
        # 【性能优化】收集所有需要更新的任务，最后统一commit，避免循环中频繁commit
        tasks_to_update = []
        for task in tasks:
            try:
                # 获取关联的订阅信息（博主信息）- 使用批量查询的结果
                author_info = None
                subscription = None
                if task.subscription_id:
                    subscription = subscriptions_dict.get(task.subscription_id)
                    if subscription:
                        # 对于抖音合集，显示平台为douyin；其他平台保持原样
                        if subscription.platform == 'douyin_collection':
                            processed_platform = 'douyin'
                        else:
                            processed_platform = subscription.platform
                        is_collection = subscription.platform in ['douyin_collection', 'bilibili_collection', 'youtube_playlist'] or \
                            (subscription.platform == 'youtube' and (subscription.youtube_tab_type or '').lower() == 'playlists')
                        author_info = {
                            "nickname": subscription.nickname or "未知博主",
                            "platform": processed_platform,
                            "subscription_id": subscription.id,
                            "is_collection": is_collection,  # 添加是否为合集的标识
                            "youtube_tab_type": getattr(subscription, 'youtube_tab_type', None),
                            "subscription_type": getattr(subscription, 'subscription_type', None)  # 添加订阅类型（用于区分B站收藏等）
                        }
                
                # 确定任务类型显示
                task_type_display = "手动"
                if task.subscription_id and subscription:
                    task_type_display = determine_task_type_display(subscription, task.url)
                elif task.url and '/note/' in task.url:
                    # 手动下载的图集任务
                    source = (task.source or "").lower()
                    if source == "douyin":
                        task_type_display = "手动抖音图集"
                    elif source == "xiaohongshu":
                        task_type_display = "手动小红书图集"
                    else:
                        task_type_display = "手动图集"
                
                normalized_source = None
                if subscription and subscription.platform:
                    sub_platform = (subscription.platform or "").lower()
                    if sub_platform == "douyin_collection":
                        normalized_source = "douyin"
                    elif sub_platform == "youtube_playlist":
                        normalized_source = "youtube"
                    elif sub_platform == "bilibili_collection":
                        normalized_source = "bilibili"
                    elif sub_platform in ['youtube', 'bilibili', 'douyin', 'xiaohongshu', 'tiktok', 'instagram', 'netease', 'x', 'others', 'unknown']:
                        normalized_source = sub_platform

                if not normalized_source:
                    normalized_source = _normalize_task_source(getattr(task, "source", None), getattr(task, "url", None))
                task_dict = {
                    "id": task.id if task.id else str(uuid.uuid4()),
                    "source": normalized_source,
                    "url": task.url if task.url else "",
                    "original_url": getattr(task, 'original_url', None),
                    "status": models.TaskStatus.from_str(str(task.status)).value,
                    "progress": float(max(0.0, min(100.0, task.progress if isinstance(task.progress, (int, float)) else 0.0))),
                    "filename": task.filename,
                    "error_message": task.error_message,
                    "created_at": task.created_at if task.created_at else now_beijing(),
                    "updated_at": task.updated_at if task.updated_at else now_beijing(),
                    "subscription_id": getattr(task, 'subscription_id', None),  # 添加订阅ID字段
                    "author_info": author_info,  # 添加博主信息
                    "task_type_display": task_type_display  # 添加任务类型显示
                }
                task_data = models.TaskBase.model_validate(task_dict)
                valid_tasks.append(task_data)
                # 收集需要更新的任务，稍后批量commit
                if task_dict["status"] != task.status or task_dict["progress"] != task.progress or task.source != normalized_source:
                    task.status = task_dict["status"]
                    task.progress = task_dict["progress"]
                    task.source = normalized_source
                    tasks_to_update.append(task)
            except Exception as e:
                # logger.error(f"任务数据验证失败: {task.__dict__}, 错误: {str(e)}") # 日志统一处理
                try:
                    # 【性能优化】使用批量查询的subscriptions_dict，避免重复查询
                    author_info = None
                    subscription = None
                    if hasattr(task, 'subscription_id') and task.subscription_id:
                        subscription = subscriptions_dict.get(task.subscription_id)
                        if subscription:
                            # 对于抖音合集，显示平台为douyin；其他平台保持原样
                            if subscription.platform == 'douyin_collection':
                                processed_platform = 'douyin'
                            else:
                                processed_platform = subscription.platform
                            is_collection = subscription.platform in ['douyin_collection', 'bilibili_collection', 'youtube_playlist'] or \
                                (subscription.platform == 'youtube' and (subscription.youtube_tab_type or '').lower() == 'playlists')
                            author_info = {
                                "nickname": subscription.nickname or "未知博主",
                                "platform": processed_platform,
                                "subscription_id": subscription.id,
                                "is_collection": is_collection,
                                "youtube_tab_type": getattr(subscription, 'youtube_tab_type', None),
                                "subscription_type": getattr(subscription, 'subscription_type', None)
                            }
                    
                    # 确定任务类型显示
                    task_type_display = "手动"
                    if hasattr(task, 'subscription_id') and task.subscription_id and subscription:
                        task_type_display = determine_task_type_display(subscription, task.url if hasattr(task, 'url') else None)
                    elif hasattr(task, 'url') and task.url and '/note/' in task.url:
                        # 手动下载的图集任务
                        source = (task.source if hasattr(task, 'source') else "").lower()
                        if source == "douyin":
                            task_type_display = "手动抖音图集"
                        elif source == "xiaohongshu":
                            task_type_display = "手动小红书图集"
                        else:
                            task_type_display = "手动图集"
                    
                    normalized_source = None
                    if subscription and subscription.platform:
                        sub_platform = (subscription.platform or "").lower()
                        if sub_platform == "douyin_collection":
                            normalized_source = "douyin"
                        elif sub_platform == "youtube_playlist":
                            normalized_source = "youtube"
                        elif sub_platform == "bilibili_collection":
                            normalized_source = "bilibili"
                        elif sub_platform in ['youtube', 'bilibili', 'douyin', 'xiaohongshu', 'tiktok', 'instagram', 'netease', 'x', 'others', 'unknown']:
                            normalized_source = sub_platform
                    if not normalized_source:
                        normalized_source = _normalize_task_source(getattr(task, "source", None), getattr(task, "url", None))
                    error_task = models.TaskBase.model_validate({
                        "id": task.id if hasattr(task, 'id') and task.id else str(uuid.uuid4()),
                        "source": normalized_source or "unknown",
                        "url": task.url if hasattr(task, 'url') and task.url else "",
                        "original_url": getattr(task, 'original_url', None),
                        "status": models.TaskStatus.ERROR.value,
                        "progress": 0.0,
                        "filename": None,
                        "error_message": "任务数据损坏",
                        "created_at": task.created_at if hasattr(task, 'created_at') and task.created_at else now_beijing(),
                        "updated_at": task.updated_at if hasattr(task, 'updated_at') and task.updated_at else now_beijing(),
                        "subscription_id": getattr(task, 'subscription_id', None),  # 添加订阅ID字段
                        "author_info": author_info,  # 添加博主信息
                        "task_type_display": task_type_display  # 添加任务类型显示
                    })
                    valid_tasks.append(error_task)
                    task.status = models.TaskStatus.ERROR.value
                    task.progress = 0.0
                    task.error_message = "任务数据损坏"
                    tasks_to_update.append(task)
                except Exception as e2:
                    # logger.error(f"修复任务数据失败: {str(e2)}") # 日志统一处理
                    continue
        
        # 【性能优化】批量commit所有需要更新的任务
        if tasks_to_update:
            for task in tasks_to_update:
                db.add(task)
            db.commit()
        
        return {"total": total, "tasks": [t.dict() for t in valid_tasks]}
    except Exception as e:
        # logger.error(f"获取任务列表失败: {str(e)}") # 日志统一处理
        raise HTTPException(status_code=500, detail=f"获取任务列表失败: {str(e)}")

@router.get("/api/tasks/{task_id}", response_model=models.TaskBase)
def get_task(task_id: str, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """获取单个下载任务"""
    try:
        task = db.query(models.Task).filter(models.Task.id == task_id).first()
        if task is None:
            raise HTTPException(status_code=404, detail="任务不存在")
        return task
    except Exception as e:
        if isinstance(e, HTTPException):
            raise e
        raise HTTPException(status_code=500, detail=f"获取任务失败: {str(e)}")


def _set_download_cancel_flag(task_id: str, source: str):
    """
    为正在进行的下载任务设置取消标志。
    注意：这里只负责发出“取消信号”，真正的下载协程会在各自模块里轮询该标志并退出。
    """
    try:
        # 导入平台特定的取消标志
        if source in ["youtube", "bilibili"]:
            from .ytd import cancel_flags as ytd_cancel_flags
            ytd_cancel_flags[task_id] = True
            logger.info(f"设置取消标志 [油管/B站]: {task_id[:8]}...")
        elif source == "douyin":
            from .dyd import dyd_cancel_flags
            dyd_cancel_flags[task_id] = True
            logger.info(f"设置取消标志 [抖音]: {task_id[:8]}...")
        elif source == "xiaohongshu":
            # 小红书也使用抖音的下载逻辑
            from .dyd import dyd_cancel_flags
            dyd_cancel_flags[task_id] = True
            logger.info(f"设置取消标志 [小红书]: {task_id[:8]}...")
        elif source == "tiktok":
            from .tiktok import cancel_flags as tiktok_cancel_flags
            tiktok_cancel_flags[task_id] = True
            logger.info(f"设置取消标志 [TikTok]: {task_id[:8]}...")
        else:
            # 其他平台暂时只删除数据库记录，不做额外处理
            logger.info(f"平台 {source} 无运行时取消标志，跳过运行时标记，仅更新数据库状态")
    except ImportError as e:
        logger.warning(f"导入取消标志失败: {str(e)}")

@router.delete("/api/tasks/{task_id}/")
def delete_task(task_id: str, delete_file: bool = Query(True), delete_related: bool = Query(True), current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """删除任务记录，默认同时删除关联的文件和订阅数据"""
    try:
        task = db.query(models.Task).filter(models.Task.id == task_id).first()
        if task is None:
            raise HTTPException(status_code=404, detail="任务不存在")

        # 如果任务正在下载，先发送取消信号，让下载进程有机会停止
        if task.status == models.TaskStatus.DOWNLOADING.value:
            _set_download_cancel_flag(task_id, task.source)
            # 等待一小段时间，让下载协程轮询到取消标志
            import time
            time.sleep(0.5)

        deleted_files = []
        file_errors = []
        try:
            cleanup_res = cleanup_task_before_delete(task, delete_output=delete_file, delete_temp=True)
            for path in cleanup_res["output"] + cleanup_res["temp"]:
                if path not in deleted_files:
                    deleted_files.append(path)
        except Exception as cleanup_exc:
            file_errors.append(f"任务文件清理失败: {str(cleanup_exc)}")
            logger.error(f"删除任务前清理失败: task_id={task_id}, error={cleanup_exc}")
        
        # 更新关联视频的下载状态（默认启用）
        if delete_related:
            videos = db.query(models.SubscriptionVideo).filter(
                models.SubscriptionVideo.download_task_id == task_id
            ).all()
            # 同一个任务可能被多条记录引用，必须全量重置避免脏状态残留
            for video in videos:
                video.downloaded = "false"
                video.download_task_id = None
                video.error_message = None

        # 删除任务记录
        db.delete(task)
        db.commit()

        # 构建返回消息
        message = "任务删除成功"
        if deleted_files:
            message += f"，已删除 {len(deleted_files)} 个文件"
        if file_errors:
            message += f"，但有 {len(file_errors)} 个文件删除失败"
            return JSONResponse(status_code=200, content={
                "message": message,
                "deleted_files": deleted_files,
                "file_errors": file_errors
            })

        return {"message": message, "deleted_files": deleted_files}
    except Exception as e:
        if isinstance(e, HTTPException):
            raise e
        raise HTTPException(status_code=500, detail=f"删除任务失败: {str(e)}")

@router.post("/api/tasks/{task_id}/retry")
def retry_task(task_id: str, background_tasks: BackgroundTasks, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """重新下载失败或已取消的任务"""
    try:
        return retry_task_internal(task_id, db, background_tasks.add_task)
    except Exception as e:
        if isinstance(e, HTTPException):
            raise e
        raise HTTPException(status_code=500, detail=f"重新下载任务失败: {str(e)}")


def retry_task_internal(task_id: str, db: Session, enqueue_task) -> dict:
    """重试任务核心逻辑，供下载中心与 Telegram Bot 复用。"""
    task = db.query(models.Task).filter(models.Task.id == task_id).first()
    if task is None:
        raise HTTPException(status_code=404, detail="任务不存在")

    if task.status not in [models.TaskStatus.ERROR, models.TaskStatus.CANCELLED]:
        raise HTTPException(status_code=400, detail="只能重新下载失败或已取消的任务")

    cleanup_res = cleanup_task_before_retry(task, mode="temp_only")
    if cleanup_res["temp"]:
        logger.info(f"重试前清理临时残留完成: task_id={task_id}, count={len(cleanup_res['temp'])}")

    task.status = models.TaskStatus.PENDING
    task.progress = 0
    task.error_message = None
    task.filename = None
    db.commit()

    if task.subscription_id:
        subscription_video = db.query(models.SubscriptionVideo).filter(
            models.SubscriptionVideo.subscription_id == task.subscription_id,
            models.SubscriptionVideo.url == task.url
        ).first()
        if subscription_video:
            subscription_video.error_message = None
            subscription_video.download_task_id = task_id
            db.commit()

        from .ytd import update_task_progress
        update_task_progress(task_id, models.TaskStatus.PENDING, progress=0.0, subscription_id=task.subscription_id)

    from .ytd import download_video_logic
    from .dyd import dyd_download_video_logic
    from .wnxt import ytdlp_download_task

    if task.source == "youtube" or "youtube.com" in task.url or "youtu.be" in task.url:
        youtube_cookie = task.cookie if task.source == "youtube" else None
        bilibili_cookie = task.cookie if task.source == "bilibili" else None
        enqueue_task(
            download_video_logic,
            task_id,
            task.url,
            task.format_id or "bestvideo+bestaudio",
            youtube_cookie,
            bilibili_cookie,
            task.proxy,
            True,
            True,
            None,
            getattr(task, 'subscription_id', None)
        )
    elif task.source == "bilibili" or "bilibili.com" in task.url:
        youtube_cookie = task.cookie if task.source == "youtube" else None
        bilibili_cookie = task.cookie if task.source == "bilibili" else None
        enqueue_task(
            download_video_logic,
            task_id,
            task.url,
            task.format_id or "bestvideo+bestaudio",
            youtube_cookie,
            bilibili_cookie,
            task.proxy,
            True,
            True,
            None,
            getattr(task, 'subscription_id', None)
        )
    elif task.source == "douyin" or "douyin.com" in task.url or "v.douyin.com" in task.url:
        if hasattr(task, 'subscription_id') and task.subscription_id:
            from .subscribe import get_subscription_download_dir
            custom_dir = get_subscription_download_dir(task.subscription_id, task.title or "未知视频")
            enqueue_task(dyd_download_video_logic, task_id, task.url, custom_dir)
        else:
            enqueue_task(dyd_download_video_logic, task_id, task.url)
    elif task.source == "xiaohongshu" or "xiaohongshu.com" in task.url:
        if hasattr(task, 'subscription_id') and task.subscription_id:
            from .subscribe import get_subscription_download_dir
            custom_dir = get_subscription_download_dir(task.subscription_id, task.title or "未知视频")
            enqueue_task(dyd_download_video_logic, task_id, task.url, custom_dir)
        else:
            enqueue_task(dyd_download_video_logic, task_id, task.url)
    elif task.source == "tiktok" or "tiktok.com" in task.url or "vt.tiktok.com" in task.url:
        from .tiktok import tiktok_download_video_logic
        if hasattr(task, 'subscription_id') and task.subscription_id:
            enqueue_task(tiktok_download_video_logic, task_id, task.url, task.subscription_id)
        else:
            enqueue_task(tiktok_download_video_logic, task_id, task.url, None)
    elif task.source == "instagram" or "instagram.com" in task.url or "cdninstagram.com" in task.url:
        from .instagram import instagram_download_task
        if hasattr(task, 'subscription_id') and task.subscription_id:
            from .subscribe import get_subscription_download_dir
            custom_dir = get_subscription_download_dir(task.subscription_id, task.title or "Instagram")
            enqueue_task(instagram_download_task, task_id, task.url, custom_dir, task.subscription_id)
        else:
            enqueue_task(instagram_download_task, task_id, task.url, None, None)
    elif task.source == "x" or "twitter.com" in task.url or "x.com" in task.url:
        from .x_downloader import x_download_task
        if hasattr(task, 'subscription_id') and task.subscription_id:
            from .subscribe import get_subscription_download_dir
            custom_dir = get_subscription_download_dir(task.subscription_id, task.title or "未知视频")
            enqueue_task(
                x_download_task,
                task_id,
                task.url,
                task.format_id,
                None,
                custom_dir
            )
        else:
            enqueue_task(
                x_download_task,
                task_id,
                task.url,
                task.format_id,
                None
            )
    else:
        enqueue_task(ytdlp_download_task, task_id, task.url, task.format_id, task.cookie)

    return {"message": "任务已重新开始下载", "task_id": task_id}


def _cleanup_task_output_artifacts(task_filename: Optional[str]) -> List[str]:
    """清理旧成品文件/目录（包含扁平目录下同基名 sidecar）。"""
    deleted_files: List[str] = []
    if not task_filename:
        return deleted_files

    base_dir = "/app/downloads"
    if not os.path.isdir(base_dir):
        return deleted_files

    rel_path = os.path.normpath(str(task_filename).strip()).lstrip("/")
    if not rel_path:
        return deleted_files
    if rel_path.startswith(".."):
        logger.warning(f"拒绝清理疑似越界路径: task_filename={task_filename}")
        return deleted_files

    base_real = os.path.realpath(base_dir)
    abs_path = os.path.realpath(os.path.join(base_dir, rel_path))
    if not (abs_path == base_real or abs_path.startswith(base_real + os.sep)):
        logger.warning(f"拒绝清理越界路径: task_filename={task_filename}, resolved={abs_path}")
        return deleted_files
    if os.path.isdir(abs_path):
        try:
            shutil.rmtree(abs_path, ignore_errors=True)
            deleted_files.append(rel_path.rstrip("/") + "/")
        except Exception as exc:
            logger.warning(f"删除旧目录失败: path={abs_path}, err={exc}")
        return deleted_files

    parent_dir = os.path.dirname(abs_path)
    stem = os.path.splitext(os.path.basename(abs_path))[0]
    if not os.path.isdir(parent_dir):
        return deleted_files

    def _resolve_manual_clip_dir_for_file() -> str:
        parts = stem.rsplit("_", 1)
        record_id = parts[1] if len(parts) == 2 and parts[1] else stem
        return os.path.join(parent_dir, "_manual_clips", record_id)

    def _cleanup_manual_clips_for_file() -> None:
        clip_dir = _resolve_manual_clip_dir_for_file()
        try:
            real_clip_dir = os.path.realpath(clip_dir)
            if not real_clip_dir.startswith(base_real + os.sep):
                logger.warning(f"拒绝清理越界手动切片目录: path={clip_dir}")
                return
            if not os.path.isdir(real_clip_dir):
                return
            shutil.rmtree(real_clip_dir, ignore_errors=True)
            rel_clip_dir = os.path.relpath(real_clip_dir, base_dir).replace("\\", "/").rstrip("/") + "/"
            deleted_files.append(rel_clip_dir)

            manual_root = os.path.dirname(real_clip_dir)
            if os.path.isdir(manual_root) and not os.listdir(manual_root):
                os.rmdir(manual_root)
                rel_manual_root = os.path.relpath(manual_root, base_dir).replace("\\", "/").rstrip("/") + "/"
                deleted_files.append(rel_manual_root)
        except Exception as exc:
            logger.warning(f"删除手动切片目录失败: path={clip_dir}, err={exc}")

    _cleanup_manual_clips_for_file()

    def _cleanup_instagram_post_dir_if_only_meta() -> bool:
        rel_parent = os.path.relpath(parent_dir, base_dir).replace("\\", "/")
        parts = [p for p in rel_parent.split("/") if p]
        if len(parts) != 4 or parts[0] != "subscriptions" or parts[1] != "instagram":
            return False

        media_exts = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".mp4", ".mov", ".m4v", ".webm"}
        meta_exact = {"poster.jpg", "folder.jpg", "fanart.jpg"}
        meta_exts = {".nfo", ".srt", ".ass", ".vtt", ".lrc"}

        has_media = False
        only_meta = True
        try:
            entries_to_check = os.listdir(parent_dir)
        except Exception:
            return False

        for entry in entries_to_check:
            entry_path = os.path.join(parent_dir, entry)
            if os.path.isdir(entry_path):
                only_meta = False
                break

            entry_lower = entry.lower()
            _, ext = os.path.splitext(entry_lower)
            if ext in media_exts and entry_lower not in meta_exact:
                has_media = True
                only_meta = False
                break

            if entry_lower in meta_exact or ext in meta_exts:
                continue

            only_meta = False
            break

        if has_media or not only_meta:
            return False

        try:
            shutil.rmtree(parent_dir, ignore_errors=True)
            deleted_files.append(os.path.relpath(parent_dir, base_dir).rstrip("/") + "/")
            return True
        except Exception as exc:
            logger.warning(f"删除 Instagram 空壳帖子目录失败: path={parent_dir}, err={exc}")
            return False

    sidecar_image_exts = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".gif", ".image"}
    sidecar_meta_exts = {".nfo"}
    sidecar_subtitle_exts = {".srt", ".ass", ".vtt"}
    sidecar_lyric_exts = {".lrc"}
    sidecar_tag_keywords = {"poster", "thumb", "thumbnail", "fanart", "landscape", "banner", "clearlogo", "folder"}

    def _is_same_video_sidecar(file_name: str) -> bool:
        base_name, ext = os.path.splitext(file_name)
        ext = ext.lower()
        base_lower = base_name.lower()
        stem_lower = stem.lower()
        if base_lower == stem_lower and ext in (sidecar_image_exts | sidecar_meta_exts | sidecar_subtitle_exts | sidecar_lyric_exts):
            return True
        if ext in sidecar_lyric_exts and (
            base_lower.startswith(f"{stem_lower}.") or base_lower.startswith(f"{stem_lower}-")
        ):
            return True
        if not base_lower.startswith(stem_lower):
            return False
        if ext not in (sidecar_image_exts | sidecar_meta_exts):
            return False
        suffix = base_lower[len(stem_lower):]
        if not suffix or suffix[0] not in "-_.":
            return False
        suffix_tokens = set(
            suffix[1:].replace("_", "-").replace(".", "-").split("-")
        )
        return any(tag in suffix_tokens for tag in sidecar_tag_keywords)

    if os.path.isfile(abs_path):
        try:
            os.remove(abs_path)
            deleted_files.append(rel_path)
        except Exception as exc:
            logger.warning(f"删除旧文件失败: path={abs_path}, err={exc}")

    for entry in os.listdir(parent_dir):
        sidecar_path = os.path.join(parent_dir, entry)
        if not os.path.isfile(sidecar_path):
            continue
        if not _is_same_video_sidecar(entry):
            continue
        try:
            os.remove(sidecar_path)
            deleted_files.append(os.path.relpath(sidecar_path, base_dir))
        except Exception as exc:
            logger.warning(f"删除旧 sidecar 失败: path={sidecar_path}, err={exc}")

    parent_name = os.path.basename(parent_dir)
    entries = os.listdir(parent_dir)
    if not entries:
        try:
            os.rmdir(parent_dir)
            deleted_files.append(os.path.relpath(parent_dir, base_dir).rstrip("/") + "/")
        except Exception as exc:
            logger.warning(f"删除空目录失败: path={parent_dir}, err={exc}")
        return deleted_files

    if _cleanup_instagram_post_dir_if_only_meta():
        return deleted_files

    fixed_names = {
        "tvshow.nfo",
        "poster.jpg",
        "fanart.jpg",
        "folder.jpg",
        "season01-poster.jpg",
        "season-all-poster.jpg",
    }
    only_related_files = all(
        (entry in fixed_names) or entry.startswith(stem)
        for entry in entries
    )
    has_subdir = any(os.path.isdir(os.path.join(parent_dir, entry)) for entry in entries)
    parent_looks_like_video_dir = (parent_name == stem) or parent_name.startswith(f"{stem}_")

    if only_related_files and not has_subdir and parent_looks_like_video_dir:
        try:
            shutil.rmtree(parent_dir, ignore_errors=True)
            deleted_files.append(os.path.relpath(parent_dir, base_dir).rstrip("/") + "/")
        except Exception as exc:
            logger.warning(f"删除旧视频目录失败: path={parent_dir}, err={exc}")

    return deleted_files


def _cleanup_flat_collection_parent_if_only_meta(task_filename: Optional[str]) -> List[str]:
    """
    收尾清理“扁平合集”目录：
    - 仅在 subscriptions/{bilibili|douyin}/{author} 这一层目录生效
    - 仅当目录里只剩合集元数据/封面文件时才删除整个目录
    """
    deleted_files: List[str] = []
    if not task_filename:
        return deleted_files

    base_dir = "/app/downloads"
    if not os.path.isdir(base_dir):
        return deleted_files

    rel_path = os.path.normpath(str(task_filename).strip()).lstrip("/")
    if not rel_path or rel_path.startswith(".."):
        return deleted_files

    base_real = os.path.realpath(base_dir)
    abs_path = os.path.realpath(os.path.join(base_real, rel_path))
    if abs_path != base_real and not abs_path.startswith(base_real + os.sep):
        return deleted_files

    parent_dir = os.path.dirname(abs_path)
    if not os.path.isdir(parent_dir):
        return deleted_files

    rel_parent = os.path.relpath(parent_dir, base_real).replace("\\", "/")
    parts = [p for p in rel_parent.split("/") if p]
    # 仅处理 subscriptions/{bilibili|douyin}/{author} 根目录
    if len(parts) != 3 or parts[0] != "subscriptions" or parts[1] not in {"bilibili", "douyin"}:
        return deleted_files

    allowed_exact = {
        "tvshow.nfo",
        "poster.jpg",
        "fanart.jpg",
        "folder.jpg",
        "season01-poster.jpg",
        "season-all-poster.jpg",
    }

    try:
        entries = os.listdir(parent_dir)
    except Exception:
        return deleted_files

    if not entries:
        return deleted_files

    for entry in entries:
        full_path = os.path.join(parent_dir, entry)
        if os.path.isdir(full_path):
            return deleted_files

        entry_lower = entry.lower()
        if entry_lower in allowed_exact:
            continue
        # 兼容未来可能出现的 seasonXX-poster.jpg
        if entry_lower.startswith("season") and entry_lower.endswith("-poster.jpg"):
            continue
        return deleted_files

    try:
        shutil.rmtree(parent_dir, ignore_errors=True)
        deleted_files.append(rel_parent.rstrip("/") + "/")
        logger.info(f"删除前已清理合集空壳目录: {rel_parent}")
    except Exception as exc:
        logger.warning(f"删除合集空壳目录失败: path={parent_dir}, err={exc}")

    return deleted_files


def cleanup_task_before_retry(task: Optional[models.Task], mode: str = "temp_only") -> Dict[str, List[str]]:
    """统一重试前清理入口。
    mode:
      - temp_only: 仅清理 task_id 相关临时残留
      - full_output: 清理旧成品 + task_id 临时残留
    """
    if task is None:
        return {"output": [], "temp": []}

    output_deleted: List[str] = []
    if mode == "full_output":
        output_deleted = _cleanup_task_output_artifacts(getattr(task, "filename", None))

    temp_deleted = cleanup_task_retry_artifacts(task.id, getattr(task, "filename", None))

    if output_deleted:
        logger.info(f"重试前已清理旧成品: task_id={task.id}, count={len(output_deleted)}")
    if temp_deleted:
        logger.info(f"重试前已清理临时残留: task_id={task.id}, count={len(temp_deleted)}")

    return {"output": output_deleted, "temp": temp_deleted}


def cleanup_task_before_delete(
    task: Optional[models.Task],
    delete_output: bool = True,
    delete_temp: bool = True
) -> Dict[str, List[str]]:
    """统一删除任务前清理入口。"""
    if task is None:
        return {"output": [], "temp": []}

    output_deleted: List[str] = []
    if delete_output:
        output_deleted = _cleanup_task_output_artifacts(getattr(task, "filename", None))
        # 扁平合集目录收尾清理（仅在仅剩元数据文件时删除目录）
        collection_tail_deleted = _cleanup_flat_collection_parent_if_only_meta(getattr(task, "filename", None))
        for path in collection_tail_deleted:
            if path not in output_deleted:
                output_deleted.append(path)

    temp_deleted: List[str] = []
    if delete_temp:
        temp_deleted = cleanup_task_retry_artifacts(task.id, getattr(task, "filename", None))

    if output_deleted:
        logger.info(f"删除前已清理旧成品: task_id={task.id}, count={len(output_deleted)}")
    if temp_deleted:
        logger.info(f"删除前已清理临时残留: task_id={task.id}, count={len(temp_deleted)}")

    return {"output": output_deleted, "temp": temp_deleted}


def cleanup_task_retry_artifacts(task_id: str, task_filename: Optional[str] = None) -> List[str]:
    """重试前清理任务残留的临时文件，避免旧文件干扰新一轮下载。"""
    deleted_files: List[str] = []
    if not task_id:
        return deleted_files

    search_base = "/app/downloads"
    if not os.path.isdir(search_base):
        return deleted_files

    candidate_paths = []
    if task_filename:
        normalized = str(task_filename).lstrip("/")
        abs_path = os.path.join(search_base, normalized)
        candidate_paths.append(abs_path)

        dir_name = os.path.dirname(abs_path)
        base_name = os.path.basename(abs_path)
        sidecar_suffixes = [".part", ".tmp", ".temp", ".ytdl", ".aria2"]
        for suffix in sidecar_suffixes:
            candidate_paths.append(abs_path + suffix)
            if base_name:
                candidate_paths.append(os.path.join(dir_name, f".{base_name}{suffix}"))

    for path in candidate_paths:
        try:
            if not os.path.exists(path) or not os.path.isfile(path):
                continue
            # candidate_paths 由当前任务文件名派生，属于同任务旁路残留，允许直接清理
            os.remove(path)
            deleted_files.append(os.path.relpath(path, search_base))
        except Exception as exc:
            logger.warning(f"重试前删除候选临时文件失败: path={path}, err={exc}")

    try:
        for root, _, files in os.walk(search_base):
            for file_name in files:
                if not (file_name.startswith(task_id) or file_name.startswith(f".{task_id}")):
                    continue
                full_path = os.path.join(root, file_name)
                rel_path = os.path.relpath(full_path, search_base)
                if rel_path in deleted_files:
                    continue
                try:
                    os.remove(full_path)
                    deleted_files.append(rel_path)
                except Exception as exc:
                    logger.warning(f"重试前删除残留文件失败: path={full_path}, err={exc}")
    except Exception as exc:
        logger.warning(f"重试前扫描临时文件失败: task_id={task_id}, err={exc}")

    return deleted_files

@router.get("/api/tasks/{task_id}/download-gallery")
def download_gallery_as_zip(
    task_id: str, 
    current_user: User = Depends(get_current_user), 
    db: Session = Depends(get_db)
):
    """将图集任务的所有图片打包成 ZIP 文件下载"""
    import zipfile
    import tempfile
    from pathlib import Path
    
    try:
        # 获取任务信息
        task = db.query(models.Task).filter(models.Task.id == task_id).first()
        if task is None:
            raise HTTPException(status_code=404, detail="任务不存在")
        
        if not task.filename:
            raise HTTPException(status_code=400, detail="任务没有关联的文件")
        
        # 构建完整路径
        base_dir = "/app/downloads"
        # task.filename 对于图集来说通常是 "platform/foldername/" 格式
        gallery_path = os.path.join(base_dir, task.filename.strip('/'))
        
        logger.info(f"[打包下载] 任务ID: {task_id}, filename: {task.filename}, 完整路径: {gallery_path}")
        
        # 检查路径是否存在
        if not os.path.exists(gallery_path):
            logger.error(f"[打包下载] 路径不存在: {gallery_path}")
            raise HTTPException(status_code=404, detail=f"图集目录不存在: {gallery_path}")
        
        # 如果是文件而不是目录，使用父目录
        if os.path.isfile(gallery_path):
            logger.info(f"[打包下载] 检测到文件而非目录，使用父目录")
            gallery_path = os.path.dirname(gallery_path)
        
        # 收集所有图片、视频和音频文件（包括背景音乐）
        media_extensions = {
            # 图片
            '.jpg', '.jpeg', '.png', '.gif', '.webp', '.bmp', '.svg',
            # 视频
            '.mp4', '.avi', '.mov', '.mkv', '.flv', '.webm',
            # 音频（背景音乐）
            '.mp3', '.flac', '.m4a', '.wav', '.aac', '.ogg'
        }
        media_files = []
        
        logger.info(f"[打包下载] 开始扫描目录: {gallery_path}")
        for root, dirs, files in os.walk(gallery_path):
            for file in files:
                file_ext = Path(file).suffix.lower()
                if file_ext in media_extensions:
                    full_path = os.path.join(root, file)
                    media_files.append(full_path)
                    logger.debug(f"[打包下载] 找到媒体文件: {file}")
        
        if not media_files:
            logger.error(f"[打包下载] 未找到媒体文件，目录: {gallery_path}")
            logger.info(f"[打包下载] 目录内容: {os.listdir(gallery_path) if os.path.isdir(gallery_path) else '不是目录'}")
            raise HTTPException(status_code=404, detail="图集中没有找到媒体文件")
        
        logger.info(f"[打包下载] 找到 {len(media_files)} 个媒体文件")
        
        # 创建临时 ZIP 文件
        temp_zip = tempfile.NamedTemporaryFile(delete=False, suffix='.zip')
        temp_zip_path = temp_zip.name
        temp_zip.close()
        
        try:
            # 打包媒体文件
            with zipfile.ZipFile(temp_zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
                for media_file in media_files:
                    # 计算相对路径，保持目录结构
                    arcname = os.path.relpath(media_file, gallery_path)
                    zipf.write(media_file, arcname)
                    logger.debug(f"[打包下载] 添加到ZIP: {arcname}")
            
            logger.info(f"[打包下载] ZIP文件创建成功，大小: {os.path.getsize(temp_zip_path)} bytes")
            
            # 生成下载文件名（使用任务标题或文件夹名）
            if task.title:
                zip_filename = f"{task.title}.zip"
            else:
                zip_filename = f"{os.path.basename(gallery_path)}.zip"
            
            # 清理文件名中的非法字符
            zip_filename = "".join(c for c in zip_filename if c.isalnum() or c in (' ', '-', '_', '.', '（', '）', '【', '】'))
            
            logger.info(f"[打包下载] 准备发送文件: {zip_filename}")
            
            # 返回 ZIP 文件流
            def iterfile():
                with open(temp_zip_path, 'rb') as f:
                    yield from f
                # 读取完成后删除临时文件
                os.unlink(temp_zip_path)
                logger.info(f"[打包下载] 临时文件已删除: {temp_zip_path}")
            
            return StreamingResponse(
                iterfile(),
                media_type='application/zip',
                headers={
                    'Content-Disposition': f'attachment; filename="{urllib.parse.quote(zip_filename)}"'
                }
            )
        except Exception as e:
            # 清理临时文件
            if os.path.exists(temp_zip_path):
                os.unlink(temp_zip_path)
            raise e
            
    except Exception as e:
        if isinstance(e, HTTPException):
            raise e
        logger.error(f"打包下载图集失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"打包下载失败: {str(e)}")




# 批量操作口令（开发用途，按当天日期动态生成，格式YYYYMMDD）
def _expected_dev_secret() -> str:
    return datetime.now().strftime('%Y%m%d')

@router.delete("/api/tasks/clear")
def clear_all_tasks(
    request: Request,
    current_user: User = Depends(get_current_user),
    delete_files: bool = Query(True), 
    subscription_id: Optional[str] = Query(None, description="按订阅ID筛选"),
    status: Optional[str] = Query(None, description="按状态筛选"),
    platform: Optional[str] = Query(None, description="按平台筛选：youtube/bilibili/douyin/tiktok/instagram/xiaohongshu/netease/x/unknown/others"),
    manual_only: bool = Query(False, description="仅手动下载（订阅ID为空）"),
    orphan_only: bool = Query(False, description="仅文件缺失的孤儿任务"),
    query_str: Optional[str] = Query(None, alias="query", description="搜索关键词：标题、文件名、URL或博主"),
    db: Session = Depends(get_db)
):
    """清空下载任务，支持按条件筛选，默认同时删除关联的文件"""
    try:
        # 服务端校验口令（当天日期）- 所有清空操作都需要密码验证
        secret = request.headers.get('X-Admin-Secret', '')
        if secret != _expected_dev_secret():
            raise HTTPException(status_code=403, detail="Forbidden")
        
        # 收到任务清空请求
        
        deleted_files = []
        file_errors = []
        
        # 构建查询条件
        query = db.query(models.Task)
        
        # 支持按订阅ID、状态、平台、仅手动多条件筛选
        if subscription_id:
            # 按订阅ID筛选
            # 按订阅ID筛选
            query = query.filter(models.Task.subscription_id == subscription_id)
        else:
            # 非订阅ID场景可按仅手动筛选
            if manual_only:
                # 按仅手动筛选
                query = query.filter(models.Task.subscription_id.is_(None))
        
        if status and status != 'all':
            # 按状态筛选 - 支持 active 语义，其他状态不区分大小写匹配
            # 按状态筛选

            # 调试：查看数据库中所有任务的状态值
            all_tasks = db.query(models.Task).all()
            status_counts = {}
            for task in all_tasks:
                task_status = task.status or 'NULL'
                status_counts[task_status] = status_counts.get(task_status, 0) + 1

            # 数据库中所有任务的状态统计
            # 正在查找状态为指定值的任务

            status_lower = status.lower()
            # active 表示进行中（排队中、下载中或处理中）
            if status_lower == 'active':
                query = query.filter(models.Task.status.in_(['PENDING', 'DOWNLOADING', 'PROCESSING']))
            elif status_lower == 'completed':
                query = query.filter(models.Task.status == 'COMPLETED')
            elif status_lower == 'error':
                query = query.filter(models.Task.status == 'ERROR')
            elif status_lower == 'cancelled':
                query = query.filter(models.Task.status == 'CANCELLED')
            else:
                # 使用不区分大小写的查询（兼容大写状态值）
                query = query.filter(func.lower(models.Task.status) == status_lower)

        if platform:
            p = (platform or '').lower()
            allowed_platforms = ['youtube', 'bilibili', 'douyin', 'tiktok', 'instagram', 'xiaohongshu', 'netease', 'x', 'unknown', 'others']
            if p not in allowed_platforms:
                raise HTTPException(status_code=400, detail=f"不支持的平台筛选: {p}")
            # 按平台筛选
            query = query.filter(models.Task.source == p)

        # 关键词筛选（与任务列表接口语义保持一致）
        if query_str:
            search_pattern = f"%{query_str}%"
            query = query.outerjoin(models.Subscription, models.Task.subscription_id == models.Subscription.id)
            query = query.filter(
                or_(
                    models.Task.title.ilike(search_pattern),
                    models.Task.filename.ilike(search_pattern),
                    models.Task.url.ilike(search_pattern),
                    models.Subscription.nickname.ilike(search_pattern),
                )
            )
        
        if not subscription_id and not status and not platform and not manual_only:
            # 无筛选条件，将清空所有任务
            pass
        
        # 获取符合条件的任务
        if orphan_only:
            base_dir = "/app/downloads"
            candidates = query.all()
            tasks_to_delete = []
            for task in candidates:
                try:
                    if task.filename and not os.path.exists(os.path.join(base_dir, task.filename)):
                        tasks_to_delete.append(task)
                except Exception:
                    continue
        else:
            tasks_to_delete = query.all()

        logger.info(f"找到 {len(tasks_to_delete)} 个符合条件的任务")

        # 在批量删除前，对正在下载的任务先发送取消信号，避免“边下边删”造成资源浪费
        cancelled_count = 0
        for task in tasks_to_delete:
            if task.status == models.TaskStatus.DOWNLOADING.value:
                _set_download_cancel_flag(task.id, task.source)
                cancelled_count += 1

        # 只在确实有进行中任务时，等待一小段时间让下载协程感知到取消标志
        if cancelled_count > 0:
            logger.info(f"批量清空下载任务前，已为 {cancelled_count} 个进行中任务发送取消信号")
            import time
            time.sleep(0.5)
        
        # 统一删除逻辑：批量删除时也复用公共清理函数
        # 行为对齐单条删除：
        # - delete_files=True  => 删除成品 + 清理临时残留
        # - delete_files=False => 仅清理临时残留
        for task in tasks_to_delete:
            try:
                cleanup_res = cleanup_task_before_delete(
                    task,
                    # 仅孤儿批量删除也执行输出清理，行为与单条删除保持一致：
                    # 主文件缺失时仍可清理同视频副产物与空目录/条件目录
                    delete_output=delete_files,
                    delete_temp=True
                )
                for path in cleanup_res["output"] + cleanup_res["temp"]:
                    if path not in deleted_files:
                        deleted_files.append(path)
            except Exception as cleanup_exc:
                file_errors.append(f"任务 {task.id} 文件清理失败: {str(cleanup_exc)}")
                logger.error(f"批量删除前清理失败: task_id={task.id}, error={cleanup_exc}")
        
        # 获取要删除的任务ID列表
        task_ids_to_delete = [task.id for task in tasks_to_delete]
        
        # 重置相关视频的下载状态
        if task_ids_to_delete:
            videos = db.query(models.SubscriptionVideo).filter(
                models.SubscriptionVideo.download_task_id.in_(task_ids_to_delete)
            ).all()
            
            for video in videos:
                video.downloaded = "false"
                video.download_task_id = None
                video.error_message = None  # 清理错误信息，确保状态完全重置
                # 重置视频下载状态
        
        # 删除符合条件的任务
        if orphan_only:
            # 仅孤儿：限制删除范围为孤儿任务集合
            orphan_ids = [task.id for task in tasks_to_delete]
            if orphan_ids:
                num_deleted = db.query(models.Task).filter(models.Task.id.in_(orphan_ids)).delete(synchronize_session=False)
            else:
                num_deleted = 0
            db.commit()
        else:
            num_deleted = query.delete(synchronize_session=False)
            db.commit()
        
        # 构建返回消息 - 支持多条件筛选
        message_parts = []
        
        if subscription_id and status and status != 'all':
            # 同时按博主和状态筛选
            status_text = {'active': '进行中', 'completed': '已完成', 'error': '失败'}.get(status, status)
            message_parts.append(f"已清空指定博主的{status_text}下载任务")
        elif subscription_id:
            # 只按博主筛选
            message_parts.append("已清空指定博主的所有下载任务")
        elif (platform or manual_only) and (status and status != 'all'):
            # 平台/仅手动 + 状态
            status_text = {'active': '进行中', 'completed': '已完成', 'error': '失败'}.get(status, status)
            scope_text = []
            if platform:
                scope_text.append(f"平台:{platform}")
            if manual_only:
                scope_text.append("仅手动")
            scope_desc = '，'.join(scope_text) if scope_text else '筛选范围'
            message_parts.append(f"已清空{scope_desc}下的{status_text}下载任务")
        elif platform or manual_only:
            # 只按平台或仅手动筛选
            scope_text = []
            if platform:
                scope_text.append(f"平台:{platform}")
            if manual_only:
                scope_text.append("仅手动")
            scope_desc = '，'.join(scope_text) if scope_text else '筛选范围'
            message_parts.append(f"已清空{scope_desc}的所有下载任务")
        elif status and status != 'all':
            # 只按状态筛选
            status_text = {'active': '进行中', 'completed': '已完成', 'error': '失败'}.get(status, status)
            message_parts.append(f"已清空所有{status_text}的下载任务")
        else:
            # 无筛选条件
            message_parts.append("已清空所有下载任务")
        
        message = f"{message_parts[0]}，共删除 {num_deleted} 条记录"
            
        if deleted_files:
            message += f"，已删除 {len(deleted_files)} 个文件"
        if file_errors:
            message += f"，但有 {len(file_errors)} 个文件删除失败"
            return JSONResponse(status_code=200, content={
                "message": message,
                "deleted_tasks": num_deleted,
                "deleted_files": deleted_files,
                "file_errors": file_errors
            })
        
        return {"message": message, "deleted_tasks": num_deleted, "deleted_files": deleted_files}
    except Exception as e:
        if isinstance(e, HTTPException):
            raise e
        db.rollback()
        raise HTTPException(status_code=500, detail=f"清空任务失败: {str(e)}")

@router.get("/api/global-config/")
def get_global_config(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """获取全局代理和Cookie"""
    
    # 从配置文件读取代理配置
    proxy_config = {}
    config_file = "/app/database/proxy_config.env"
    
    try:
        if os.path.exists(config_file):
            with open(config_file, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith('#') and '=' in line:
                        key, value = line.split('=', 1)
                        proxy_config[key.strip()] = value.strip().strip('"')
    except Exception as e:
        print(f"读取代理配置文件失败: {e}")
        # 如果读取配置文件失败，回退到数据库读取
        proxy = db.query(models.GlobalConfig).filter_by(key='proxy').first()
        global_proxy_enabled = db.query(models.GlobalConfig).filter_by(key='global_proxy_enabled').first()
        no_proxy = db.query(models.GlobalConfig).filter_by(key='no_proxy').first()
        
        return {
            "proxy": proxy.value if proxy else None,
            "youtube_cookie": None,
            "bilibili_cookie": None,
            "global_proxy_enabled": global_proxy_enabled.value == "True" if global_proxy_enabled else False,
            "no_proxy": no_proxy.value if no_proxy else "localhost,127.0.0.1,*.local"
        }
    
    # 从文件读取Cookie配置
    youtube_cookie = None
    bilibili_cookie = None
    tiktok_cookie = None
    netease_cookie = None
    wnxt_cookie = None
    
    try:
        # 读取YouTube Cookie
        youtube_cookie_file = "/app/database/cookie/youtube_cookie.txt"
        if os.path.exists(youtube_cookie_file):
            with open(youtube_cookie_file, 'r', encoding='utf-8') as f:
                youtube_cookie = f.read().strip()
    except Exception as e:
        print(f"读取YouTube Cookie文件失败: {e}")
        # 回退到数据库读取
        original_fps = None
        try:
            obj = db.query(models.GlobalConfig).filter_by(key='youtube_cookie').first()
            if obj:
                youtube_cookie = obj.value
        except Exception:
            pass
    
    try:
        # 读取B站Cookie
        bilibili_cookie_file = "/app/database/cookie/bilibili_cookie.txt"
        if os.path.exists(bilibili_cookie_file):
            with open(bilibili_cookie_file, 'r', encoding='utf-8') as f:
                bilibili_cookie = f.read().strip()
    except Exception as e:
        print(f"读取B站Cookie文件失败: {e}")
        # 回退到数据库读取
        try:
            obj = db.query(models.GlobalConfig).filter_by(key='bilibili_cookie').first()
            if obj:
                bilibili_cookie = obj.value
        except Exception:
            pass
    
    try:
        # 读取TikTok Cookie
        tiktok_cookie_file = "/app/database/cookie/tiktok_cookie.txt"
        if os.path.exists(tiktok_cookie_file):
            with open(tiktok_cookie_file, 'r', encoding='utf-8') as f:
                tiktok_cookie = f.read().strip()
    except Exception as e:
        print(f"读取TikTok Cookie文件失败: {e}")
        # 回退到数据库读取
        try:
            obj = db.query(models.GlobalConfig).filter_by(key='tiktok_cookie').first()
            if obj:
                tiktok_cookie = obj.value
        except Exception:
            pass
    
    try:
        # 读取网易云音乐 Cookie
        netease_cookie_file = "/app/database/cookie/netease_cookie.txt"
        if os.path.exists(netease_cookie_file):
            with open(netease_cookie_file, 'r', encoding='utf-8') as f:
                netease_cookie = f.read().strip()
    except Exception as e:
        print(f"读取网易云音乐 Cookie文件失败: {e}")
        # 回退到数据库读取
        try:
            obj = db.query(models.GlobalConfig).filter_by(key='netease_cookie').first()
            if obj:
                netease_cookie = obj.value
        except Exception:
            pass
    
    try:
        # 读取万能嗅探Cookie
        wnxt_cookie_file = "/app/database/cookie/wnxt_cookie.txt"
        if os.path.exists(wnxt_cookie_file):
            with open(wnxt_cookie_file, 'r', encoding='utf-8') as f:
                wnxt_cookie = f.read().strip()
    except Exception as e:
        print(f"读取万能嗅探Cookie文件失败: {e}")
        # 回退到数据库读取
        try:
            obj = db.query(models.GlobalConfig).filter_by(key='wnxt_cookie').first()
            if obj:
                wnxt_cookie = obj.value
        except Exception:
            pass
    
    # 读取下载并发数配置
    max_concurrent_downloads = 10  # 默认值
    try:
        config_obj = db.query(models.GlobalConfig).filter_by(key='max_concurrent_downloads').first()
        if config_obj and config_obj.value:
            max_concurrent_downloads = int(config_obj.value)
    except Exception as e:
        print(f"读取下载并发数配置失败: {e}")

    return {
        "proxy": proxy_config.get('PROXY_URL', ''),
        "youtube_cookie": youtube_cookie,
        "bilibili_cookie": bilibili_cookie,
        "tiktok_cookie": tiktok_cookie,
        "netease_cookie": netease_cookie,
        "wnxt_cookie": wnxt_cookie,
        "global_proxy_enabled": proxy_config.get('GLOBAL_PROXY_ENABLED', 'false').lower() == 'true',
        "no_proxy": proxy_config.get('NO_PROXY_LIST', 'localhost,127.0.0.1,*.local'),
        "max_concurrent_downloads": max_concurrent_downloads,
    }

@router.post("/api/global-config/")
def set_global_config(
    current_user: User = Depends(get_current_user),
    proxy: str = Body(None),
    youtube_cookie: str = Body(None),
    bilibili_cookie: str = Body(None),
    wnxt_cookie: str = Body(None),
    global_proxy_enabled: bool = Body(None),
    no_proxy: str = Body(None),
    max_concurrent_downloads: int = Body(None),
    db: Session = Depends(get_db)
):
    """保存全局代理和Cookie"""
    
    # 处理代理配置 - 保存到配置文件
    if proxy is not None or global_proxy_enabled is not None or no_proxy is not None:
        try:
            # 读取现有配置文件
            config_file = "/app/database/proxy_config.env"
            config_lines = []
            
            if os.path.exists(config_file):
                with open(config_file, 'r', encoding='utf-8') as f:
                    config_lines = f.readlines()
            
            # 更新配置值
            config_dict = {}
            for line in config_lines:
                line = line.strip()
                if line and not line.startswith('#') and '=' in line:
                    key, value = line.split('=', 1)
                    config_dict[key.strip()] = value.strip().strip('"')
            
            # 更新代理相关配置
            if proxy is not None:
                config_dict['PROXY_URL'] = proxy
            if global_proxy_enabled is not None:
                config_dict['GLOBAL_PROXY_ENABLED'] = str(global_proxy_enabled).lower()
            if no_proxy is not None:
                config_dict['NO_PROXY_LIST'] = no_proxy
            
            # 写入配置文件
            with open(config_file, 'w', encoding='utf-8') as f:
                f.write("# Easy-VDL 代理配置文件\n")
                f.write("# 在数据库启动前，Docker容器会读取此文件来设置代理环境变量\n\n")
                f.write(f'PROXY_URL="{config_dict.get("PROXY_URL", "")}"\n')
                f.write(f'GLOBAL_PROXY_ENABLED="{config_dict.get("GLOBAL_PROXY_ENABLED", "false")}"\n')
                f.write(f'NO_PROXY_LIST="{config_dict.get("NO_PROXY_LIST", "localhost,127.0.0.1,*.local")}"\n')
            
            print(f"代理配置已保存到配置文件，将在下次重启后生效")
            
        except Exception as e:
            print(f"保存代理配置到配置文件失败: {e}")
            # 如果保存配置文件失败，回退到数据库保存
            for key, value in [("proxy", proxy), ("global_proxy_enabled", str(global_proxy_enabled) if global_proxy_enabled is not None else None), ("no_proxy", no_proxy)]:
                if value is not None:
                    obj = db.query(models.GlobalConfig).filter_by(key=key).first()
                    if obj:
                        obj.value = value
                    else:
                        obj = models.GlobalConfig(key=key, value=value)
                        db.add(obj)
            db.commit()
            print(f"代理配置已回退保存到数据库")
    
    # 处理Cookie配置 - 通过cookie_manager保存（避免绕过自动更新机制）
    try:
        # 保存YouTube Cookie
        if youtube_cookie is not None:
            from .cookie_manager import save_youtube_cookie
            from pydantic import BaseModel
            
            class CookieRequest(BaseModel):
                cookie_content: str
            
            request = CookieRequest(cookie_content=youtube_cookie)
            save_youtube_cookie(request, db)
            print(f"YouTube Cookie已通过cookie_manager保存")
        
        # 保存B站Cookie
        if bilibili_cookie is not None:
            from .cookie_manager import save_bilibili_cookie
            from pydantic import BaseModel
            
            class CookieRequest(BaseModel):
                cookie_content: str
            
            request = CookieRequest(cookie_content=bilibili_cookie)
            save_bilibili_cookie(request, db)
            print(f"B站Cookie已通过cookie_manager保存")
        
        # 保存万能嗅探Cookie（保持原有逻辑，因为wnxt没有自动更新机制）
        if wnxt_cookie is not None:
            wnxt_cookie_file = "/app/database/cookie/wnxt_cookie.txt"
            with open(wnxt_cookie_file, 'w', encoding='utf-8') as f:
                f.write(wnxt_cookie)
            print(f"万能嗅探Cookie已保存到文件: {wnxt_cookie_file}")
            
    except Exception as e:
        print(f"保存Cookie到文件失败: {e}")
        # 如果保存文件失败，回退到数据库保存
        if youtube_cookie is not None:
            obj = db.query(models.GlobalConfig).filter_by(key='youtube_cookie').first()
            if obj:
                obj.value = youtube_cookie
            else:
                obj = models.GlobalConfig(key='youtube_cookie', value=youtube_cookie)
                db.add(obj)
        
        if bilibili_cookie is not None:
            obj = db.query(models.GlobalConfig).filter_by(key='bilibili_cookie').first()
            if obj:
                obj.value = bilibili_cookie
            else:
                obj = models.GlobalConfig(key='bilibili_cookie', value=bilibili_cookie)
                db.add(obj)
        
        if wnxt_cookie is not None:
            obj = db.query(models.GlobalConfig).filter_by(key='wnxt_cookie').first()
            if obj:
                obj.value = wnxt_cookie
            else:
                obj = models.GlobalConfig(key='wnxt_cookie', value=wnxt_cookie)
                db.add(obj)
        
        if youtube_cookie is not None or bilibili_cookie is not None or wnxt_cookie is not None:
            db.commit()
            print(f"Cookie已回退保存到数据库")
    
    # 处理下载并发数配置
    if max_concurrent_downloads is not None:
        try:
            # 验证并发数范围（1-30）
            if max_concurrent_downloads < 1 or max_concurrent_downloads > 30:
                raise HTTPException(status_code=400, detail="下载并发数必须在1-30之间")
            
            # 保存到数据库
            config_obj = db.query(models.GlobalConfig).filter_by(key='max_concurrent_downloads').first()
            if config_obj:
                config_obj.value = str(max_concurrent_downloads)
            else:
                config_obj = models.GlobalConfig(key='max_concurrent_downloads', value=str(max_concurrent_downloads))
                db.add(config_obj)
            db.commit()
            
            # 更新DownloadManager的并发数
            from routers.downloader import download_manager
            download_manager.update_max_concurrent_downloads(max_concurrent_downloads)
            print(f"下载并发数已更新为: {max_concurrent_downloads}")
            
        except Exception as e:
            print(f"保存下载并发数配置失败: {e}")
            db.rollback()
            raise HTTPException(status_code=500, detail=f"保存下载并发数配置失败: {str(e)}")

    return {"message": "全局配置已保存"}


@router.post("/api/global-config/clear")
def clear_global_config_selective(clear_keys: list = Body(..., embed=True), current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """清除指定的全局配置项"""
    if not clear_keys:
        raise HTTPException(status_code=400, detail="必须指定要清除的配置项")
    
    # 验证清除的键是否有效
    valid_keys = [
        "proxy", "youtube_cookie", "bilibili_cookie", "wnxt_cookie", "global_proxy_enabled", "no_proxy",
    ]
    invalid_keys = [key for key in clear_keys if key not in valid_keys]
    if invalid_keys:
        raise HTTPException(status_code=400, detail=f"无效的配置项: {', '.join(invalid_keys)}")
    
    # 清除指定的配置项
    deleted_count = 0
    
    # 处理代理配置清除 - 更新配置文件
    proxy_keys_to_clear = [key for key in clear_keys if key in ["proxy", "global_proxy_enabled", "no_proxy"]]
    if proxy_keys_to_clear:
        try:
            config_file = "/app/database/proxy_config.env"
            config_lines = []
            
            if os.path.exists(config_file):
                with open(config_file, 'r', encoding='utf-8') as f:
                    config_lines = f.readlines()
            
            # 更新配置值
            config_dict = {}
            for line in config_lines:
                line = line.strip()
                if line and not line.startswith('#') and '=' in line:
                    key, value = line.split('=', 1)
                    config_dict[key.strip()] = value.strip().strip('"')
            
            # 清除指定的代理配置
            for key in proxy_keys_to_clear:
                if key == "proxy":
                    config_dict['PROXY_URL'] = ""
                    # 如果清除代理URL，也应该关闭代理开关
                    config_dict['GLOBAL_PROXY_ENABLED'] = "false"
                elif key == "global_proxy_enabled":
                    config_dict['GLOBAL_PROXY_ENABLED'] = "false"
                elif key == "no_proxy":
                    config_dict['NO_PROXY_LIST'] = "localhost,127.0.0.1,*.local"
            
            # 写入配置文件
            with open(config_file, 'w', encoding='utf-8') as f:
                f.write("# Easy-VDL 代理配置文件\n")
                f.write("# 在数据库启动前，Docker容器会读取此文件来设置代理环境变量\n\n")
                f.write(f'PROXY_URL="{config_dict.get("PROXY_URL", "")}"\n')
                f.write(f'GLOBAL_PROXY_ENABLED="{config_dict.get("GLOBAL_PROXY_ENABLED", "false")}"\n')
                f.write(f'NO_PROXY_LIST="{config_dict.get("NO_PROXY_LIST", "localhost,127.0.0.1,*.local")}"\n')
            
            deleted_count += len(proxy_keys_to_clear)
            print(f"代理配置已从配置文件清除")
            
        except Exception as e:
            print(f"清除代理配置文件失败: {e}")
            # 如果清除配置文件失败，回退到数据库清除
            for clear_key in proxy_keys_to_clear:
                result = db.query(models.GlobalConfig).filter_by(key=clear_key).delete(synchronize_session=False)
                if result > 0:
                    deleted_count += 1
    
    # 处理Cookie配置清除 - 从文件清除
    cookie_keys_to_clear = [key for key in clear_keys if key in ["youtube_cookie", "bilibili_cookie", "wnxt_cookie"]]
    for clear_key in cookie_keys_to_clear:
        try:
            if clear_key == "youtube_cookie":
                cookie_file = "/app/database/cookie/youtube_cookie.txt"
            elif clear_key == "bilibili_cookie":
                cookie_file = "/app/database/cookie/bilibili_cookie.txt"
            elif clear_key == "wnxt_cookie":
                cookie_file = "/app/database/cookie/wnxt_cookie.txt"
            
            if os.path.exists(cookie_file):
                os.remove(cookie_file)
                deleted_count += 1
                print(f"{clear_key} Cookie文件已删除: {cookie_file}")
        except Exception as e:
            print(f"删除{clear_key} Cookie文件失败: {e}")
            # 如果删除文件失败，回退到数据库清除
            try:
                result = db.query(models.GlobalConfig).filter_by(key=clear_key).first()
                if result:
                    db.delete(result)
                    deleted_count += 1
            except Exception:
                pass

    if deleted_count > 0:
        db.commit()
        return {"message": f"已清除 {deleted_count} 个配置项: {', '.join(clear_keys)}"}
    else:
        return {"message": "指定的配置项不存在或已被清除"}

@router.delete("/api/global-config/")
def clear_global_config(key: str = None, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """清除全局代理和Cookie（兼容旧版本）"""
    
    # 处理代理配置清除 - 更新配置文件
    if key in ["proxy", "global_proxy_enabled", "no_proxy"] or key is None:
        try:
            config_file = "/app/database/proxy_config.env"
            config_lines = []
            
            if os.path.exists(config_file):
                with open(config_file, 'r', encoding='utf-8') as f:
                    config_lines = f.readlines()
            
            # 更新配置值
            config_dict = {}
            for line in config_lines:
                line = line.strip()
                if line and not line.startswith('#') and '=' in line:
                    key_name, value = line.split('=', 1)
                    config_dict[key_name.strip()] = value.strip().strip('"')
            
            # 清除指定的代理配置
            if key == "proxy" or key is None:
                config_dict['PROXY_URL'] = ""
                # 如果清除代理URL，也应该关闭代理开关
                config_dict['GLOBAL_PROXY_ENABLED'] = "false"
            if key == "global_proxy_enabled" or key is None:
                config_dict['GLOBAL_PROXY_ENABLED'] = "false"
            if key == "no_proxy" or key is None:
                config_dict['NO_PROXY_LIST'] = "localhost,127.0.0.1,*.local"
            
            # 写入配置文件
            with open(config_file, 'w', encoding='utf-8') as f:
                f.write("# Easy-VDL 代理配置文件\n")
                f.write("# 在数据库启动前，Docker容器会读取此文件来设置代理环境变量\n\n")
                f.write(f'PROXY_URL="{config_dict.get("PROXY_URL", "")}"\n')
                f.write(f'GLOBAL_PROXY_ENABLED="{config_dict.get("GLOBAL_PROXY_ENABLED", "false")}"\n')
                f.write(f'NO_PROXY_LIST="{config_dict.get("NO_PROXY_LIST", "localhost,127.0.0.1,*.local")}"\n')
            
            print(f"代理配置已从配置文件清除")
            
        except Exception as e:
            print(f"清除代理配置文件失败: {e}")
            # 如果清除配置文件失败，回退到数据库清除
            pass
    
    # 处理Cookie配置清除 - 从文件清除
    if key in ["youtube_cookie", "bilibili_cookie", "wnxt_cookie"] or key is None:
        try:
            if key == "youtube_cookie" or key is None:
                youtube_cookie_file = "/app/database/cookie/youtube_cookie.txt"
                if os.path.exists(youtube_cookie_file):
                    os.remove(youtube_cookie_file)
                    print(f"YouTube Cookie文件已删除: {youtube_cookie_file}")
            
            if key == "bilibili_cookie" or key is None:
                bilibili_cookie_file = "/app/database/cookie/bilibili_cookie.txt"
                if os.path.exists(bilibili_cookie_file):
                    os.remove(bilibili_cookie_file)
                    print(f"B站Cookie文件已删除: {bilibili_cookie_file}")
            
            if key == "wnxt_cookie" or key is None:
                wnxt_cookie_file = "/app/database/cookie/wnxt_cookie.txt"
                if os.path.exists(wnxt_cookie_file):
                    os.remove(wnxt_cookie_file)
                    print(f"万能嗅探Cookie文件已删除: {wnxt_cookie_file}")
                    
        except Exception as e:
            print(f"删除Cookie文件失败: {e}")
    
    # 原有的数据库清除逻辑
    query = db.query(models.GlobalConfig)
    if key in [
        "proxy", "youtube_cookie", "bilibili_cookie", "wnxt_cookie", "global_proxy_enabled", "no_proxy",
    ]:
        query = query.filter(models.GlobalConfig.key == key)
    else:
        query = query.filter(models.GlobalConfig.key.in_([
            "proxy", "youtube_cookie", "bilibili_cookie", "wnxt_cookie", "global_proxy_enabled", "no_proxy",
        ]))
    query.delete(synchronize_session=False)
    db.commit()
    
    if key == "proxy":
        return {"message": "全局代理已清除"}
    elif key == "youtube_cookie":
        return {"message": "YouTube Cookie已清除"}
    elif key == "bilibili_cookie":
        return {"message": "B站Cookie已清除"}
    elif key == "wnxt_cookie":
        return {"message": "万能嗅探Cookie已清除"}
    elif key == "global_proxy_enabled":
        return {"message": "全局代理启用状态已清除"}
    elif key == "no_proxy":
        return {"message": "代理排除列表已清除"}
    else:
        return {"message": "全局配置已清除"}

@router.get("/api/files/{filename:path}/nfo")
def get_nfo_file(filename: str, platform: str = None):
    raise HTTPException(status_code=410, detail="该接口已移除，前端已使用 File Browser")

@router.post("/api/files/{filename:path}/nfo")
def save_nfo_file(filename: str, content: str = Body(..., embed=True), platform: str = None):
    raise HTTPException(status_code=410, detail="该接口已移除，前端已使用 File Browser")

@router.post("/api/files/delete-platform")
def delete_platform_files(platform: str = Body(..., embed=True), delete_type: str = Body("platform", embed=True), delete_related_tasks: bool = Body(True, embed=True), db: Session = Depends(get_db)):
    raise HTTPException(status_code=410, detail="该接口已移除，前端已使用 File Browser")


# --- 新增：按订阅博主筛选相关API ---

@router.get("/api/tasks/authors/")
def get_task_authors(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0)
):
    """获取所有已下载过视频的博主列表，用于筛选下载任务"""
    try:
        # 查询所有有订阅ID的任务，并关联订阅表获取博主信息
        query = db.query(
            models.Subscription.nickname,
            models.Subscription.platform,
            models.Subscription.youtube_tab_type,
            models.Subscription.subscription_type,
            models.Subscription.id.label('subscription_id'),
            func.count(models.Task.id).label('task_count')
        ).join(
            models.Task, 
            models.Subscription.id == models.Task.subscription_id
        ).filter(
            models.Task.subscription_id.isnot(None)  # 只查询有订阅ID的任务
        ).group_by(
            models.Subscription.nickname,
            models.Subscription.platform,
            models.Subscription.youtube_tab_type,
            models.Subscription.subscription_type,
            models.Subscription.id
        ).order_by(
            func.count(models.Task.id).desc()  # 按任务数量降序排列
        )
        
        # 获取总数
        total = query.count()
        
        # 分页查询
        authors = query.offset(offset).limit(limit).all()
        
        # 构建返回数据
        author_list = []
        for author in authors:
            # 将合集类型映射为主平台类型
            platform_mapping = {
                'douyin_collection': 'douyin',
                'youtube_playlist': 'youtube',
                'bilibili_collection': 'bilibili'
            }
            mapped_platform = platform_mapping.get(author.platform, author.platform)
            
            # 构建显示名称，特殊订阅类型需要标注
            nickname = author.nickname or "未知博主"
            subscription_type = getattr(author, 'subscription_type', 'user')
            
            if author.platform == 'youtube' and author.youtube_tab_type == 'shorts':
                # YouTube Shorts
                display_name = f"{nickname} (youtube-shorts) - {author.task_count}个任务"
            elif author.platform == 'douyin' and subscription_type == 'favorite':
                # 抖音点赞列表
                display_name = f"{nickname} (douyin-favorite) - {author.task_count}个任务"
            else:
                # 普通订阅
                display_name = f"{nickname} ({mapped_platform}) - {author.task_count}个任务"
            
            author_info = {
                "nickname": nickname,
                "platform": mapped_platform,
                "subscription_id": author.subscription_id,
                "task_count": author.task_count,
                "display_name": display_name
            }
            author_list.append(author_info)
        
        return {
            "total": total,
            "authors": author_list,
            "pagination": {
                "limit": limit,
                "offset": offset,
                "has_more": offset + limit < total
            }
        }
        
    except Exception as e:
        logger.error(f"获取博主列表失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"获取博主列表失败: {str(e)}")


@router.get("/api/tasks/authors/{subscription_id}/stats")
def get_author_task_stats(
    subscription_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """获取指定博主的下载任务统计信息"""
    try:
        # 获取订阅信息
        subscription = db.query(models.Subscription).filter(
            models.Subscription.id == subscription_id
        ).first()
        
        if not subscription:
            raise HTTPException(status_code=404, detail="订阅不存在")
        
        # 统计该博主的各种状态任务数量
        task_stats = db.query(
            models.Task.status,
            func.count(models.Task.id).label('count')
        ).filter(
            models.Task.subscription_id == subscription_id
        ).group_by(models.Task.status).all()
        
        # 构建统计结果
        stats = {
            "total": 0,
            "completed": 0,
            "downloading": 0,
            "error": 0,
            "cancelled": 0,
            "pending": 0
        }
        
        for stat in task_stats:
            count = stat.count
            stats["total"] += count
            if stat.status in stats:
                stats[stat.status.lower()] = count
        
        # 获取最近的任务
        recent_tasks = db.query(models.Task).filter(
            models.Task.subscription_id == subscription_id
        ).order_by(models.Task.created_at.desc()).limit(5).all()
        
        recent_task_list = []
        for task in recent_tasks:
            recent_task_list.append({
                "id": task.id,
                "title": task.title or "未知标题",
                "status": task.status,
                "progress": task.progress,
                "created_at": task.created_at.isoformat() if task.created_at else None,
                "filename": task.filename
            })
        
        return {
            "subscription": {
                "id": subscription.id,
                "nickname": subscription.nickname,
                "platform": 'douyin' if subscription.platform == 'douyin_collection' else subscription.platform,
                "avatar_url": _proxy_avatar_url(subscription.platform, subscription.avatar_url)
            },
            "stats": stats,
            "recent_tasks": recent_task_list
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取博主任务统计失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"获取博主任务统计失败: {str(e)}")


@router.get("/api/tasks/search/")
def search_tasks_by_author(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    author_name: str = Query(..., description="博主名称（支持模糊搜索）"),
    status: str = Query(None, description="任务状态过滤"),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0)
):
    """根据博主名称搜索下载任务"""
    try:
        # 先查找匹配的订阅
        subscriptions = db.query(models.Subscription).filter(
            models.Subscription.nickname.ilike(f"%{author_name}%")
        ).all()
        
        if not subscriptions:
            return {"total": 0, "tasks": [], "message": f"未找到名称包含 '{author_name}' 的博主"}
        
        subscription_ids = [sub.id for sub in subscriptions]
        
        # 构建任务查询
        query = db.query(models.Task).filter(
            models.Task.subscription_id.in_(subscription_ids)
        ).order_by(models.Task.created_at.desc())
        
        # 如果指定了状态过滤，添加过滤条件
        if status and status != 'all':
            if status == 'active':
                query = query.filter(models.Task.status.in_(['PENDING', 'DOWNLOADING', 'PROCESSING']))
            elif status == 'completed':
                query = query.filter(models.Task.status == 'COMPLETED')
            elif status == 'error':
                query = query.filter(models.Task.status == 'ERROR')
            elif status in ['DOWNLOADING', 'PROCESSING', 'COMPLETED', 'ERROR', 'CANCELLED', 'PENDING']:
                query = query.filter(models.Task.status == status)
        
        # 获取总数
        total = query.count()
        
        # 分页查询
        tasks = query.offset(offset).limit(limit).all()
        
        # 构建返回数据
        task_list = []
        for task in tasks:
            # 获取关联的订阅信息
            subscription = db.query(models.Subscription).filter(
                models.Subscription.id == task.subscription_id
            ).first()
            
            task_info = {
                "id": task.id,
                "source": task.source,
                "url": task.url,
                "title": task.title,
                "status": task.status,
                "progress": task.progress,
                "filename": task.filename,
                "error_message": task.error_message,
                "created_at": task.created_at.isoformat() if task.created_at else None,
                "updated_at": task.updated_at.isoformat() if task.updated_at else None,
                "subscription_id": task.subscription_id,
                "author_info": {
                    "nickname": subscription.nickname if subscription else "未知博主",
                    "platform": ('douyin' if subscription.platform == 'douyin_collection' else subscription.platform) if subscription else "unknown"
                } if subscription else None
            }
            task_list.append(task_info)
        
        return {
            "total": total,
            "tasks": task_list,
            "search_info": {
                "author_name": author_name,
                "matched_subscriptions": len(subscriptions),
                "subscription_details": [
                    {
                        "id": sub.id,
                        "nickname": sub.nickname,
                        "platform": sub.platform
                    } for sub in subscriptions
                ]
            },
            "pagination": {
                "limit": limit,
                "offset": offset,
                "has_more": offset + limit < total
            }
        }
        
    except Exception as e:
        logger.error(f"搜索博主任务失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"搜索博主任务失败: {str(e)}")

@router.get("/api/gallery-thumbnail/")
async def get_gallery_thumbnail(
    current_user: User = Depends(get_current_user),
    platform: str = Query(..., description="平台名称"),
    folder_path: str = Query(..., description="文件夹路径"),
    subscription: bool = Query(False, description="是否为订阅下载"),
    video_filename: str = Query(None, description="视频文件名（用于查找对应的缩略图）")
):
    """获取图集缩略图，返回第一张可用的图片"""
    try:
        # 兼容URL编码的folder_path（前端会对每个段做encodeURIComponent）
        try:
            import urllib.parse
            folder_path = urllib.parse.unquote(folder_path)
        except Exception:
            pass

        # 构建完整的文件夹路径
        if subscription:
            # 订阅下载：/app/downloads/subscriptions/{platform}/{author}/{folder}
            full_path = os.path.join("/app/downloads/subscriptions", platform, folder_path)
        else:
            # 手动下载：/app/downloads/{platform}/{folder}
            full_path = os.path.join("/app/downloads", platform, folder_path)
        
        
        if not os.path.exists(full_path):
            raise HTTPException(status_code=404, detail="文件夹不存在")
        
        if not os.path.isdir(full_path):
            raise HTTPException(status_code=400, detail="路径不是文件夹")
        
        # 支持的图片格式，按优先级排序
        image_extensions = ['.jpg', '.jpeg', '.png', '.webp']
        
        # 查找图片文件
        image_files = []
        poster_files = []  # 专门查找poster文件
        specific_poster_files = []  # 查找与视频文件名匹配的poster文件
        
        for file in os.listdir(full_path):
            file_path = os.path.join(full_path, file)
            if os.path.isfile(file_path):
                _, ext = os.path.splitext(file.lower())
                if ext in image_extensions:
                    # 如果提供了视频文件名，优先查找匹配的poster文件
                    if video_filename and 'poster' in file.lower():
                        # 提取视频文件名（去掉扩展名）
                        video_base = os.path.splitext(video_filename)[0]
                        # 检查poster文件名是否包含视频文件名
                        if video_base in file:
                            specific_poster_files.append((file, ext))
                        else:
                            poster_files.append((file, ext))
                    elif 'poster' in file.lower():
                        poster_files.append((file, ext))
                    else:
                        image_files.append((file, ext))
        
        # 按扩展名优先级排序
        def get_priority(ext):
            try:
                return image_extensions.index(ext)
            except ValueError:
                return len(image_extensions)
        
        # 优先级：特定视频的poster文件 > 其他poster文件 > 其他图片文件
        all_files = specific_poster_files + poster_files + image_files
        all_files.sort(key=lambda x: get_priority(x[1]))
        
        if not all_files:
            raise HTTPException(status_code=404, detail="文件夹中没有找到图片文件")
        
        # 选择第一张图片
        selected_file, selected_ext = all_files[0]
        
        # 构建相对路径
        if subscription:
            relative_path = f"subscriptions/{platform}/{folder_path}/{selected_file}"
        else:
            relative_path = f"{platform}/{folder_path}/{selected_file}"
        
        
        return {
            "success": True,
            "thumbnail_path": relative_path,
            "filename": selected_file,
            "extension": selected_ext,
            "total_images": len(image_files)
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取图集缩略图失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"获取缩略图失败: {str(e)}")

@router.get("/api/gallery-files/")
async def get_gallery_files(
    current_user: User = Depends(get_current_user),
    platform: str = Query(..., description="平台名称"),
    folder_path: str = Query(..., description="文件夹路径"),
    subscription: bool = Query(False, description="是否为订阅下载")
):
    """获取图集目录下的所有媒体文件（图片、视频、背景音乐）"""
    try:
        # 兼容URL编码的folder_path
        try:
            import urllib.parse
            folder_path = urllib.parse.unquote(folder_path)
        except Exception:
            pass

        # 构建完整的文件夹路径
        if subscription:
            folder_full_path = os.path.join("/app/downloads/subscriptions", platform, folder_path)
        else:
            folder_full_path = os.path.join("/app/downloads", platform, folder_path)
        
        if not os.path.exists(folder_full_path) or not os.path.isdir(folder_full_path):
            raise HTTPException(status_code=404, detail="文件夹不存在或不是目录")
        
        media_files = []
        bgm_file = None
        
        # 扩展名定义
        image_exts = ['.jpg', '.jpeg', '.png', '.webp', '.gif']
        video_exts = ['.mp4', '.mkv', '.mov', '.webm', '.flv']
        audio_exts = ['.mp3', '.flac', '.wav', '.m4a', '.aac']
        
        # 扫描文件
        files = sorted(os.listdir(folder_full_path))
        for file in files:
            file_path = os.path.join(folder_full_path, file)
            if not os.path.isfile(file_path):
                continue
                
            _, ext = os.path.splitext(file.lower())
            
            # 构建相对路径（用于前端访问）
            if subscription:
                rel_url = f"subscriptions/{platform}/{folder_path}/{file}"
            else:
                rel_url = f"{platform}/{folder_path}/{file}"
                
            if ext in image_exts:
                if 'poster' in file.lower(): continue # 跳过缩略图
                media_files.append({"type": "image", "url": f"/downloads/{rel_url}", "name": file})
            elif ext in video_exts:
                media_files.append({"type": "video", "url": f"/downloads/{rel_url}", "name": file})
            elif ext in audio_exts:
                # 抖音图集通常把BGM命名为 bgm.mp3 或 music.mp3
                if file.lower().startswith(('bgm', 'music')):
                    bgm_file = {"type": "audio", "url": f"/downloads/{rel_url}", "name": file}
                else:
                    # 如果没有明确的BGM，也将第一个音频视为音频文件（或者作为列表展示）
                    if not bgm_file:
                        bgm_file = {"type": "audio", "url": f"/downloads/{rel_url}", "name": file}

        return {
            "success": True,
            "folder": folder_path,
            "media_items": media_files,
            "bgm": bgm_file
        }
    except Exception as e:
        logger.error(f"获取图集文件列表失败: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/api/random-player/videos")
def get_random_player_videos(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    platform: str = Query(None, description="平台筛选：youtube/bilibili/douyin/xiaohongshu/tiktok/instagram/x/netease/others/all"),
    manual_only: bool = Query(False, description="仅返回手动任务（非订阅任务）"),
    subscription_only: bool = Query(False, description="仅返回订阅任务"),
    author_name: str = Query(None, description="按博主名称筛选"),
    subscription_id: str = Query(None, description="按订阅ID筛选"),
    task_id: str = Query(None, description="指定任务ID，优先返回该任务（即使不在前1000条中）"),
    order_by: str = Query("random", description="排序方式：random/asc/desc"),
    limit: int = Query(500, ge=1, le=1000, description="返回视频数量")
):
    """获取随机播放器的视频列表（仅返回已完成的视频任务）"""
    try:
        # 如果指定了 task_id，先尝试直接查询该任务
        target_task = None
        if task_id:
            target_task = db.query(models.Task).filter(
                models.Task.id == task_id,
                models.Task.status == models.TaskStatus.COMPLETED.value,
                models.Task.filename.isnot(None)
            ).first()
        
        # 查询已完成的任务
        query = db.query(models.Task).filter(
            models.Task.status == models.TaskStatus.COMPLETED.value,
            models.Task.filename.isnot(None)
        )
        
        # 手动任务筛选（排除订阅任务）
        if manual_only:
            query = query.filter(
                models.Task.subscription_id.is_(None),
                ~models.Task.filename.like('subscriptions/%')
            )
        elif subscription_only:
            query = query.filter(
                or_(
                    models.Task.subscription_id.isnot(None),
                    models.Task.filename.like('subscriptions/%')
                )
            )

        # 平台筛选
        if platform and platform != 'all':
            if platform == 'netease':
                # 兼容历史数据：部分网易云任务 source 可能不规范，但文件路径仍在 netease 目录下
                query = query.filter(
                    or_(
                        models.Task.source == 'netease',
                        models.Task.filename.like('netease/%')
                    )
                )
            elif platform == 'douyin':
                # 抖音兼容：手动任务可能使用 douyin_collection 作为 source
                query = query.filter(
                    or_(
                        models.Task.source == 'douyin',
                        models.Task.source == 'douyin_collection'
                    )
                )
            else:
                query = query.filter(models.Task.source == platform)

        # 博主筛选（订阅博主昵称 + 手动任务作者 + 路径兜底）
        if author_name:
            pattern = f"%{author_name.strip()}%"
            matched_subscriptions = db.query(models.Subscription.id).filter(
                models.Subscription.nickname.ilike(pattern)
            )
            query = query.filter(
                or_(
                    models.Task.author.ilike(pattern),
                    models.Task.subscription_id.in_(matched_subscriptions),
                    models.Task.filename.ilike(f"%/{author_name.strip()}/%")
                )
            )
        
        # 订阅筛选和排序
        if subscription_id:
            query = query.filter(models.Task.subscription_id == subscription_id)
            # 如果有订阅ID，通过 SubscriptionVideo 关联按发布时间排序
            if order_by in ['asc', 'desc']:
                # 关联 SubscriptionVideo 表
                query = query.join(
                    models.SubscriptionVideo,
                    models.SubscriptionVideo.download_task_id == models.Task.id
                )
                if order_by == 'asc':
                    query = query.order_by(models.SubscriptionVideo.publish_time.asc().nulls_last())
                else:  # desc
                    query = query.order_by(models.SubscriptionVideo.publish_time.desc().nulls_last())
            else:  # random
                query = query.order_by(func.random())
        else:
            # 没有订阅ID时，按任务创建时间排序或随机
            if order_by == 'asc':
                query = query.order_by(models.Task.created_at.asc())
            elif order_by == 'desc':
                query = query.order_by(models.Task.created_at.desc())
            else:  # random
                query = query.order_by(func.random())
        
        # 如果指定了 task_id 且找到了目标任务，从查询中排除它（避免重复）
        if task_id and target_task:
            query = query.filter(models.Task.id != task_id)
        
        # 限制数量（如果指定了 task_id 且找到了目标任务，减少 limit 以保持总数不变）
        actual_limit = limit - 1 if (task_id and target_task) else limit
        tasks = query.limit(actual_limit).all()
        
        # 如果指定了 task_id 且找到了目标任务，将其添加到列表开头（确保通过 task_id 跳转时一定能找到）
        if task_id and target_task:
            tasks = [target_task] + tasks
        
        # 【性能优化】批量获取订阅信息，避免循环中的N+1查询
        subscription_ids = {t.subscription_id for t in tasks if t.subscription_id}
        subscription_map = {}
        if subscription_ids:
            subscriptions = db.query(models.Subscription).filter(
                models.Subscription.id.in_(subscription_ids)
            ).all()
            subscription_map = {sub.id: sub for sub in subscriptions}

        # 构建返回数据
        video_list = []
        base_dir = "/app/downloads"
        
        for task in tasks:
            # 确保文件存在
            if not task.filename:
                continue
                
            # 【极致性能优化】移除所有文件系统IO检查
            # 1. 信任DB状态：不再检查文件是否存在 (os.path.exists)
            # 2. 移除缩略图搜索：不再遍历查找缩略图，将缩略图路径推断交给前端
            # 这将消除 500+ 次系统调用，显著降低延迟
            
            thumbnail_path = None
            
            # 获取作者信息 (从内存字典获取，不再查询DB)
            author_info = None
            if task.subscription_id:
                subscription = subscription_map.get(task.subscription_id)
                if subscription:
                    author_info = {
                        "nickname": subscription.nickname or "未知作者",
                        "platform": 'douyin' if subscription.platform == 'douyin_collection' else subscription.platform,
                        "avatar_url": _proxy_avatar_url(subscription.platform, subscription.avatar_url),
                        "id": subscription.id
                    }

            # 手动任务的历史数据里，title/author 可能为空，尝试从文件路径回填展示信息
            display_title = (task.title or "").strip()
            author_name = (task.author or "").strip()
            filename_str = str(task.filename or "")
            if filename_str:
                try:
                    parts = [p for p in filename_str.split('/') if p]

                    # 回填作者：netease/作者/文件 以及 通用 平台/作者/文件
                    if not author_name:
                        if len(parts) >= 2 and parts[0] == "netease" and parts[1]:
                            author_name = parts[1].strip()
                        elif len(parts) >= 3 and parts[0] != "subscriptions" and parts[1]:
                            author_name = parts[1].strip()

                    # 回填标题：使用文件名（去扩展名）
                    if not display_title:
                        base_name = os.path.basename(filename_str.rstrip('/'))
                        if base_name:
                            name_without_ext, _ = os.path.splitext(base_name)
                            display_title = (name_without_ext or base_name).strip()
                except Exception:
                    pass
            
            video_info = {
                "id": task.id,
                "title": display_title or "未知标题",
                "filename": task.filename,
                "thumbnail": thumbnail_path,
                "platform": task.source,
                "source": task.source,
                "subscription_id": task.subscription_id,
                "author": author_info,
                "author_name": author_name or "未知作者",
                "created_at": task.created_at.isoformat() if task.created_at else None,
                "url": task.url
            }
            video_list.append(video_info)
        
        return {
            "success": True,
            "total": len(video_list),
            "videos": video_list,
            "filter": {
                "platform": platform or "all",
                "manual_only": manual_only,
                "subscription_only": subscription_only,
                "author_name": author_name,
                "subscription_id": subscription_id,
                "order_by": order_by
            }
        }
        
    except Exception as e:
        logger.error(f"获取随机播放视频列表失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"获取视频列表失败: {str(e)}")


@router.get("/api/video/metadata")
def get_video_metadata(
    current_user: User = Depends(get_current_user),
    filename: str = Query(..., description="视频文件路径（相对于 /app/downloads/）")
):
    """
    获取视频基础元数据（时长、分辨率、码率）。
    """
    base_dir = "/app/downloads"
    try:
        decoded_filename = urllib.parse.unquote(filename)
        file_path = os.path.join(base_dir, decoded_filename)
        if not os.path.exists(file_path):
            logger.warning(f"请求元数据的视频文件不存在: {file_path}")
            raise HTTPException(status_code=404, detail="视频文件不存在")
        abs_file_path = os.path.abspath(file_path)
        metadata = _probe_video_metadata_cached(abs_file_path)
        duration = metadata.get("duration")
        if duration is None:
            # 向后兼容：兜底使用旧的时长探测逻辑
            duration = _probe_video_duration_cached(abs_file_path)
        if duration is None:
            logger.warning(f"无法获取视频时长: {abs_file_path}")
            return {
                "success": False,
                "duration": None,
                "width": metadata.get("width"),
                "height": metadata.get("height"),
                "video_bitrate": metadata.get("video_bitrate"),
                "audio_bitrate": metadata.get("audio_bitrate"),
                "format_bitrate": metadata.get("format_bitrate")
            }
        return {
            "success": True,
            "duration": duration,
            "width": metadata.get("width"),
            "height": metadata.get("height"),
            "video_bitrate": metadata.get("video_bitrate"),
            "audio_bitrate": metadata.get("audio_bitrate"),
            "format_bitrate": metadata.get("format_bitrate")
        }
    except HTTPException:
        raise
    except Exception as exc:
        logger.error(f"获取视频元数据失败: {exc}")
        return {
            "success": False,
            "duration": None,
            "width": None,
            "height": None,
            "video_bitrate": None,
            "audio_bitrate": None,
            "format_bitrate": None
        }


@router.get("/api/video/subtitles")
def get_video_subtitles(
    current_user: User = Depends(get_current_user),
    filename: str = Query(..., description="视频文件路径（相对于 /app/downloads/）")
):
    """扫描与视频同目录的 sidecar 字幕文件（动态返回，不做语言硬编码）。"""
    try:
        abs_video_path, _ = _resolve_download_abs_path(filename)
        if not os.path.exists(abs_video_path) or os.path.isdir(abs_video_path):
            return {"success": True, "subtitles": []}

        folder = os.path.dirname(abs_video_path)
        stem = os.path.splitext(os.path.basename(abs_video_path))[0]
        if not os.path.isdir(folder) or not stem:
            return {"success": True, "subtitles": []}

        base_dir = os.path.realpath("/app/downloads")
        subtitle_items: List[Dict[str, Any]] = []

        for name in sorted(os.listdir(folder)):
            full_path = os.path.join(folder, name)
            if not os.path.isfile(full_path):
                continue

            base_name, ext = os.path.splitext(name)
            ext_lower = ext.lower()
            if ext_lower not in {".srt", ".vtt"}:
                continue

            suffix = ""
            if base_name == stem:
                suffix = ""
            elif base_name.startswith(f"{stem}."):
                suffix = base_name[len(stem) + 1 :]
            elif base_name.startswith(f"{stem}-"):
                suffix = base_name[len(stem) + 1 :]
            elif base_name.startswith(f"{stem}_"):
                suffix = base_name[len(stem) + 1 :]
            else:
                continue

            rel_sub_path = os.path.relpath(os.path.realpath(full_path), base_dir).replace("\\", "/")
            suffix_label = suffix.replace("_", "-").strip()
            lang = _guess_subtitle_lang_from_suffix(suffix_label)
            label = suffix_label if suffix_label else "默认字幕"
            subtitle_items.append(
                {
                    "id": f"{base_name}{ext_lower}",
                    "label": label,
                    "lang": lang,
                    "format": ext_lower.lstrip("."),
                    "path": rel_sub_path,
                }
            )

        if not subtitle_items:
            return {"success": True, "subtitles": []}

        default_index = 0
        for i, item in enumerate(subtitle_items):
            lang = str(item.get("lang", "")).lower()
            if lang.startswith("zh"):
                default_index = i
                break
        subtitle_items[default_index]["is_default"] = True
        for i, item in enumerate(subtitle_items):
            if i != default_index:
                item["is_default"] = False

        return {"success": True, "subtitles": subtitle_items}
    except HTTPException:
        raise
    except Exception as exc:
        logger.error(f"获取视频字幕列表失败: {exc}")
        return {"success": True, "subtitles": []}


@router.get("/api/video/subtitle/stream")
def stream_subtitle_file(
    current_user: User = Depends(get_current_user_mixed),
    path: str = Query(..., description="字幕文件相对路径（相对于 /app/downloads/）")
):
    """字幕流接口：统一输出 WebVTT，提升浏览器兼容性。"""
    try:
        abs_path, _ = _resolve_download_abs_path(path)
        if not os.path.exists(abs_path) or not os.path.isfile(abs_path):
            raise HTTPException(status_code=404, detail="字幕文件不存在")

        ext = os.path.splitext(abs_path)[1].lower()
        if ext not in {".srt", ".vtt"}:
            raise HTTPException(status_code=415, detail="暂不支持该字幕格式")

        text = _read_text_with_fallback(abs_path)
        content = _srt_to_webvtt(text) if ext == ".srt" else text
        content = _apply_default_vtt_cue_position(content)
        if not content.lstrip("\ufeff").startswith("WEBVTT"):
            content = f"WEBVTT\n\n{content}"

        return FastAPIResponse(
            content=content,
            media_type="text/vtt; charset=utf-8",
            headers={
                "Cache-Control": "public, max-age=120",
                "Content-Disposition": "inline",
            },
        )
    except HTTPException:
        raise
    except Exception as exc:
        logger.error(f"字幕流输出失败: {exc}")
        raise HTTPException(status_code=500, detail="字幕读取失败")


# --- 视频转码播放功能 ---

def _env_flag(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return str(raw).strip().lower() in {"1", "true", "yes", "on"}


_TRANSCODE_SETTINGS_KEY = "video_transcode_settings"
_transcode_settings_cache: Optional[Dict[str, Any]] = None
_ffmpeg_caps_cache: Optional[Dict[str, bool]] = None
_ffmpeg_caps_cache_ts: float = 0.0
_ffmpeg_caps_cache_lock = threading.Lock()


def _ffmpeg_caps_cache_ttl_seconds() -> int:
    raw = os.getenv("EASY_VDL_FFMPEG_CAPS_CACHE_SECONDS", "60")
    try:
        value = int(str(raw).strip())
    except Exception:
        value = 60
    return max(0, value)


def _invalidate_ffmpeg_caps_cache() -> None:
    global _ffmpeg_caps_cache, _ffmpeg_caps_cache_ts
    with _ffmpeg_caps_cache_lock:
        _ffmpeg_caps_cache = None
        _ffmpeg_caps_cache_ts = 0.0


_VIDEO_CODEC_ALIASES = {
    "h265": "hevc",
    "x264": "h264",
    "x265": "hevc"
}
_DEFAULT_HW_DECODE_CODECS = ["h264", "hevc"]
_DEFAULT_OUTPUT_VIDEO_CODEC = "h264"
_VALID_OUTPUT_VIDEO_CODECS = {"auto", "h264", "hevc", "av1"}


def _normalize_video_codec_name(value: Any) -> str:
    codec = str(value or "").strip().lower()
    return _VIDEO_CODEC_ALIASES.get(codec, codec)


def _normalize_output_video_codec(value: Any, default: str = _DEFAULT_OUTPUT_VIDEO_CODEC) -> str:
    codec = _normalize_video_codec_name(value or default)
    if codec not in _VALID_OUTPUT_VIDEO_CODECS:
        return default
    return codec


def _env_codec_list(name: str, default: List[str]) -> List[str]:
    raw = os.getenv(name)
    if raw is None:
        return list(default)
    items = [part.strip() for part in str(raw).split(",")]
    normalized: List[str] = []
    seen: Set[str] = set()
    for item in items:
        codec = _normalize_video_codec_name(item)
        if not codec or codec in seen:
            continue
        seen.add(codec)
        normalized.append(codec)
    return normalized or list(default)


def _normalize_hw_decode_codec_list(value: Any, default: List[str]) -> List[str]:
    if value is None:
        return list(default)

    source_items: List[Any]
    if isinstance(value, str):
        source_items = [part.strip() for part in value.split(",")]
    elif isinstance(value, (list, tuple, set)):
        source_items = list(value)
    else:
        return list(default)

    normalized: List[str] = []
    seen: Set[str] = set()
    for item in source_items:
        codec = _normalize_video_codec_name(item)
        if not codec or codec in seen:
            continue
        seen.add(codec)
        normalized.append(codec)
    return normalized or list(default)


def _default_transcode_settings() -> Dict[str, Any]:
    return {
        "mode": "auto",  # auto / manual / cpu_only
        "selected_profile_id": "",
        "selected_hwaccel": "",
        "selected_vendor": "",
        "output_video_codec": _normalize_output_video_codec(
            os.getenv("EASY_VDL_OUTPUT_VIDEO_CODEC", _DEFAULT_OUTPUT_VIDEO_CODEC)
        ),
        "allow_fallback_to_other_hardware": True,
        "allow_fallback_to_cpu": True,
        "enable_hw_decode": _env_flag("EASY_VDL_ENABLE_HW_DECODE", False),
        "hardware_decoding_codecs": _env_codec_list("EASY_VDL_HW_DECODE_CODECS", _DEFAULT_HW_DECODE_CODECS),
        "prefer_native_hw_decoder": _env_flag("EASY_VDL_PREFER_NATIVE_HW_DECODER", True),
        "enable_intel_low_power_h264": _env_flag("EASY_VDL_INTEL_LOW_POWER_H264", False),
        "enable_intel_low_power_hevc": _env_flag("EASY_VDL_INTEL_LOW_POWER_HEVC", False),
        # Intel QSV 硬件提帧策略（仅 QSV 路径生效）
        # off / 30to60 / 60to120
        "intel_qsv_frame_interpolation_mode": str(
            os.getenv("EASY_VDL_INTEL_QSV_FRAME_INTERPOLATION_MODE", "off")
        ).strip().lower()
    }


def _to_bool(value: Any, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return default


def _normalize_transcode_settings(raw: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    defaults = _default_transcode_settings()
    if not isinstance(raw, dict):
        return defaults

    mode = str(raw.get("mode") or defaults["mode"]).strip().lower()
    if mode not in {"auto", "manual", "cpu_only"}:
        mode = defaults["mode"]
    interpolation_mode = str(
        raw.get("intel_qsv_frame_interpolation_mode")
        or defaults["intel_qsv_frame_interpolation_mode"]
    ).strip().lower()
    if interpolation_mode not in {"off", "30to60", "60to120"}:
        interpolation_mode = "off"

    return {
        "mode": mode,
        "selected_profile_id": str(raw.get("selected_profile_id") or "").strip(),
        "selected_hwaccel": str(raw.get("selected_hwaccel") or "").strip().lower(),
        "selected_vendor": str(raw.get("selected_vendor") or "").strip().lower(),
        "output_video_codec": _normalize_output_video_codec(
            raw.get("output_video_codec"),
            defaults["output_video_codec"]
        ),
        "allow_fallback_to_other_hardware": _to_bool(
            raw.get("allow_fallback_to_other_hardware"),
            defaults["allow_fallback_to_other_hardware"]
        ),
        "allow_fallback_to_cpu": _to_bool(
            raw.get("allow_fallback_to_cpu"),
            defaults["allow_fallback_to_cpu"]
        ),
        "enable_hw_decode": _to_bool(raw.get("enable_hw_decode"), defaults["enable_hw_decode"]),
        "hardware_decoding_codecs": _normalize_hw_decode_codec_list(
            raw.get("hardware_decoding_codecs"),
            defaults["hardware_decoding_codecs"]
        ),
        "prefer_native_hw_decoder": _to_bool(
            raw.get("prefer_native_hw_decoder"),
            defaults["prefer_native_hw_decoder"]
        ),
        "enable_intel_low_power_h264": _to_bool(
            raw.get("enable_intel_low_power_h264"),
            defaults["enable_intel_low_power_h264"]
        ),
        "enable_intel_low_power_hevc": _to_bool(
            raw.get("enable_intel_low_power_hevc"),
            defaults["enable_intel_low_power_hevc"]
        ),
        "intel_qsv_frame_interpolation_mode": interpolation_mode
    }


def get_transcode_settings(force_reload: bool = False) -> Dict[str, Any]:
    global _transcode_settings_cache
    if _transcode_settings_cache is not None and not force_reload:
        return dict(_transcode_settings_cache)

    settings = _default_transcode_settings()
    db = None
    try:
        db = get_session()
        row = db.query(models.GlobalConfig).filter_by(key=_TRANSCODE_SETTINGS_KEY).first()
        if row and row.value:
            parsed = json.loads(row.value)
            settings = _normalize_transcode_settings(parsed)
    except Exception as exc:
        logger.debug(f"读取转码设置失败，使用默认值: {exc}")
    finally:
        if db:
            db.close()

    _transcode_settings_cache = settings
    return dict(settings)


def save_transcode_settings(updates: Dict[str, Any]) -> Dict[str, Any]:
    global _transcode_settings_cache
    base = get_transcode_settings(force_reload=True)
    merged = dict(base)
    if isinstance(updates, dict):
        merged.update(updates)
    normalized = _normalize_transcode_settings(merged)
    if str(normalized.get("mode") or "").lower() == "manual":
        selected_profile_id = str(normalized.get("selected_profile_id") or "").strip()
        if selected_profile_id:
            detected_profiles = get_detected_hardware_acceleration_profiles(force_refresh=False)
            selected_profile = next(
                (item for item in detected_profiles if item.get("profile_id") == selected_profile_id),
                None
            )
            if selected_profile:
                normalized["selected_hwaccel"] = str(selected_profile.get("hwaccel") or "").strip().lower()
                normalized["selected_vendor"] = str(selected_profile.get("vendor") or "").strip().lower()
            else:
                normalized["selected_hwaccel"] = ""
                normalized["selected_vendor"] = ""

    db = None
    try:
        db = get_session()
        row = db.query(models.GlobalConfig).filter_by(key=_TRANSCODE_SETTINGS_KEY).first()
        payload = json.dumps(normalized, ensure_ascii=False)
        if row:
            row.value = payload
        else:
            row = models.GlobalConfig(key=_TRANSCODE_SETTINGS_KEY, value=payload)
            db.add(row)
        db.commit()
        _transcode_settings_cache = normalized
        invalidate_hardware_acceleration_cache()
        return dict(normalized)
    except Exception:
        if db:
            db.rollback()
        raise
    finally:
        if db:
            db.close()


def _ffmpeg_probe_env() -> Dict[str, str]:
    env = os.environ.copy()
    env["LC_ALL"] = "C.UTF-8"
    env["LANG"] = "C.UTF-8"
    return env


def _ffmpeg_text_query(args: List[str], timeout: int = 5) -> str:
    try:
        result = subprocess.run(
            ["ffmpeg", "-hide_banner"] + args,
            capture_output=True,
            text=True,
            timeout=timeout,
            env=_ffmpeg_probe_env()
        )
        return f"{result.stdout or ''}\n{result.stderr or ''}".lower()
    except Exception:
        return ""


def _probe_ffmpeg_capabilities(force_refresh: bool = False) -> Dict[str, bool]:
    global _ffmpeg_caps_cache, _ffmpeg_caps_cache_ts
    ttl = _ffmpeg_caps_cache_ttl_seconds()
    now = time.time()
    if not force_refresh and ttl > 0:
        with _ffmpeg_caps_cache_lock:
            if _ffmpeg_caps_cache is not None and (now - _ffmpeg_caps_cache_ts) < ttl:
                return dict(_ffmpeg_caps_cache)

    hwaccels = _ffmpeg_text_query(["-hwaccels"])
    encoders = _ffmpeg_text_query(["-encoders"])
    decoders = _ffmpeg_text_query(["-decoders"])
    filters = _ffmpeg_text_query(["-filters"])
    result = {
        "qsv_hwaccel": "qsv" in hwaccels,
        "vaapi_hwaccel": "vaapi" in hwaccels,
        "cuda_hwaccel": "cuda" in hwaccels,
        "h264_qsv_encoder": "h264_qsv" in encoders,
        "hevc_qsv_encoder": "hevc_qsv" in encoders,
        "av1_qsv_encoder": "av1_qsv" in encoders,
        "h264_vaapi_encoder": "h264_vaapi" in encoders,
        "hevc_vaapi_encoder": "hevc_vaapi" in encoders,
        "av1_vaapi_encoder": "av1_vaapi" in encoders,
        "h264_nvenc_encoder": "h264_nvenc" in encoders,
        "hevc_nvenc_encoder": "hevc_nvenc" in encoders,
        "av1_nvenc_encoder": "av1_nvenc" in encoders,
        "libx264_encoder": "libx264" in encoders,
        "libx265_encoder": "libx265" in encoders,
        "libsvtav1_encoder": "libsvtav1" in encoders,
        "vpp_qsv_filter": "vpp_qsv" in filters,
        "scale_vaapi_filter": "scale_vaapi" in filters,
        "scale_cuda_filter": "scale_cuda" in filters,
        "hwupload_cuda_filter": "hwupload_cuda" in filters,
        # 仅用于后续选择是否优先原生硬解
        "h264_qsv_decoder": "h264_qsv" in decoders,
        "h264_vaapi_decoder": "h264_vaapi" in decoders,
        "h264_cuvid_decoder": "h264_cuvid" in decoders or "h264_nvdec" in decoders
    }
    if ttl > 0:
        with _ffmpeg_caps_cache_lock:
            _ffmpeg_caps_cache = dict(result)
            _ffmpeg_caps_cache_ts = now
    return result


def _build_supported_hw_encoders(hwaccel: str, caps: Dict[str, bool]) -> List[str]:
    mapping = {
        "qsv": [
            ("h264_qsv_encoder", "h264_qsv"),
            ("hevc_qsv_encoder", "hevc_qsv"),
            ("av1_qsv_encoder", "av1_qsv")
        ],
        "vaapi": [
            ("h264_vaapi_encoder", "h264_vaapi"),
            ("hevc_vaapi_encoder", "hevc_vaapi"),
            ("av1_vaapi_encoder", "av1_vaapi")
        ],
        "nvenc": [
            ("h264_nvenc_encoder", "h264_nvenc"),
            ("hevc_nvenc_encoder", "hevc_nvenc"),
            ("av1_nvenc_encoder", "av1_nvenc")
        ]
    }
    candidates = mapping.get(str(hwaccel or "").lower(), [])
    return [encoder for cap_key, encoder in candidates if caps.get(cap_key)]


def _list_dri_video_devices() -> List[str]:
    devices: List[str] = []
    dri_dir = "/dev/dri"
    if not os.path.isdir(dri_dir):
        return devices
    try:
        entries = sorted(os.listdir(dri_dir))
        # 优先使用 renderD*（推荐的无头渲染节点），避免 card* 造成重复探测
        render_nodes = [os.path.join(dri_dir, e) for e in entries if e.startswith("renderD")]
        if render_nodes:
            devices.extend(render_nodes)
        else:
            card_nodes = [os.path.join(dri_dir, e) for e in entries if e.startswith("card")]
            devices.extend(card_nodes)
    except Exception:
        pass
    return [d for d in devices if os.path.exists(d)]


def _probe_vaapi_driver(device: str) -> str:
    try:
        cmd = [
            "ffmpeg", "-v", "verbose", "-hide_banner",
            "-init_hw_device", f"vaapi=probe:{device}",
            "-f", "lavfi", "-i", "color=c=black:s=64x64:d=0.1",
            "-frames:v", "1", "-f", "null", "-"
        ]
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=5,
            env=_ffmpeg_probe_env()
        )
        output = f"{result.stdout or ''}\n{result.stderr or ''}"
        if "Intel iHD driver" in output:
            return "iHD"
        if "Intel i965 driver" in output:
            return "i965"
        if "Mesa Gallium driver" in output:
            return "mesa"
    except Exception:
        pass
    return "unknown"


def _test_qsv_profile(device: str, init_mode: str, supported_encoders: List[str]) -> Optional[Dict[str, Any]]:
    init_args: List[str] = []
    if init_mode == "direct":
        init_args = ["-init_hw_device", f"qsv=hw:{device}", "-filter_hw_device", "hw"]
    else:
        # 参考 Jellyfin：Linux 优先从 VAAPI 设备派生 QSV 设备
        init_args = [
            "-init_hw_device", f"vaapi=va:{device}",
            "-init_hw_device", "qsv=hw@va",
            "-filter_hw_device", "hw"
        ]

    test_cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error"] + init_args + [
        "-f", "lavfi", "-i", "color=c=black:s=320x180:d=0.5",
        "-vf", "hwupload=extra_hw_frames=32,vpp_qsv=w=160:h=90:format=nv12",
        "-c:v", "h264_qsv",
        "-frames:v", "1",
        "-f", "null", "-"
    ]
    try:
        result = subprocess.run(
            test_cmd,
            capture_output=True,
            text=True,
            timeout=6,
            env=_ffmpeg_probe_env()
        )
        if result.returncode == 0:
            return {
                "hwaccel": "qsv",
                "encoder": "h264_qsv",
                "supported_encoders": supported_encoders,
                "vendor": "intel",
                "device": device,
                "init_mode": init_mode,
                "init_args": init_args,
                "driver": "intel",
                "rank": 100 if init_mode == "derived_vaapi" else 95
            }
    except Exception:
        pass
    return None


def _test_vaapi_profile(
    device: str,
    supported_encoders: List[str],
    force_driver: Optional[str] = None
) -> Optional[Dict[str, Any]]:
    init_args = ["-init_hw_device", f"vaapi=va:{device}", "-filter_hw_device", "va"]
    env = _ffmpeg_probe_env()
    if force_driver:
        env["LIBVA_DRIVER_NAME"] = force_driver

    test_cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error"] + init_args + [
        "-f", "lavfi", "-i", "color=c=black:s=320x180:d=0.5",
        "-vf", "format=nv12,hwupload,scale_vaapi=160:90",
        "-c:v", "h264_vaapi",
        "-frames:v", "1",
        "-f", "null", "-"
    ]
    try:
        result = subprocess.run(
            test_cmd,
            capture_output=True,
            text=True,
            timeout=6,
            env=env
        )
        if result.returncode == 0:
            return {
                "hwaccel": "vaapi",
                "encoder": "h264_vaapi",
                "supported_encoders": supported_encoders,
                "vendor": "unknown",
                "device": device,
                "init_mode": "vaapi",
                "init_args": init_args,
                "driver": force_driver or "auto",
                "env_overrides": {"LIBVA_DRIVER_NAME": force_driver} if force_driver else {},
                "rank": 80 if force_driver == "iHD" else 70 if force_driver == "i965" else 60
            }
    except Exception:
        pass
    return None


def _has_nvidia_runtime() -> bool:
    try:
        if shutil.which("nvidia-smi"):
            return True
        if os.path.exists("/proc/driver/nvidia/version"):
            return True
        return False
    except Exception:
        return False


def _list_nvidia_gpu_candidates() -> List[Dict[str, Any]]:
    if not shutil.which("nvidia-smi"):
        return [{"gpu_index": 0, "gpu_name": "NVIDIA GPU"}]

    cmd = [
        "nvidia-smi",
        "--query-gpu=index,name",
        "--format=csv,noheader,nounits"
    ]
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=4
        )
        if result.returncode != 0:
            return [{"gpu_index": 0, "gpu_name": "NVIDIA GPU"}]
        gpus: List[Dict[str, Any]] = []
        for line in (result.stdout or "").splitlines():
            parts = [x.strip() for x in line.split(",", 1)]
            if len(parts) < 2:
                continue
            try:
                gpu_index = int(parts[0])
            except Exception:
                continue
            gpus.append({"gpu_index": gpu_index, "gpu_name": parts[1]})
        return gpus or [{"gpu_index": 0, "gpu_name": "NVIDIA GPU"}]
    except Exception:
        return [{"gpu_index": 0, "gpu_name": "NVIDIA GPU"}]


def _sanitize_profile_token(value: Any) -> str:
    raw = str(value or "").strip().lower()
    return "".join(ch if ch.isalnum() or ch in {"_", "-", "."} else "_" for ch in raw)


def _build_profile_id(profile: Dict[str, Any]) -> str:
    parts = [
        _sanitize_profile_token(profile.get("hwaccel")),
        _sanitize_profile_token(profile.get("encoder")),
        _sanitize_profile_token(profile.get("device")),
        _sanitize_profile_token(profile.get("init_mode")),
        _sanitize_profile_token(profile.get("driver"))
    ]
    gpu_index = profile.get("gpu_index")
    if gpu_index is not None:
        parts.append(f"gpu{_sanitize_profile_token(gpu_index)}")
    return "__".join([p for p in parts if p]) or "unknown_profile"


def _annotate_profile(profile: Dict[str, Any], rank_boost: int = 0) -> Dict[str, Any]:
    normalized = dict(profile)
    normalized["hwaccel"] = str(normalized.get("hwaccel") or "").lower()
    normalized["vendor"] = str(normalized.get("vendor") or "unknown").lower()
    normalized["profile_id"] = _build_profile_id(normalized)
    base_rank = int(normalized.get("rank", 0))
    normalized["rank"] = base_rank + int(rank_boost)
    display_backend = normalized["hwaccel"].upper() if normalized["hwaccel"] else "HW"
    display_device = normalized.get("gpu_name") or normalized.get("device") or "auto"
    normalized["display_name"] = f"{display_backend} · {display_device}"
    return normalized


def _test_nvenc_profile(
    supports_cuda_filters: bool,
    supported_encoders: List[str],
    gpu_index: int = 0,
    gpu_name: Optional[str] = None
) -> Optional[Dict[str, Any]]:
    test_cmd = [
        "ffmpeg", "-hide_banner", "-loglevel", "error",
        "-f", "lavfi", "-i", "color=c=black:s=320x180:d=0.5",
        "-c:v", "h264_nvenc",
        "-gpu", str(gpu_index),
        "-frames:v", "1",
        "-f", "null", "-"
    ]
    try:
        result = subprocess.run(
            test_cmd,
            capture_output=True,
            text=True,
            timeout=6,
            env=_ffmpeg_probe_env()
        )
        if result.returncode == 0:
            return {
                "hwaccel": "nvenc",
                "encoder": "h264_nvenc",
                "supported_encoders": supported_encoders,
                "vendor": "nvidia",
                "device": f"gpu{gpu_index}",
                "gpu_index": gpu_index,
                "gpu_name": gpu_name or f"NVIDIA GPU {gpu_index}",
                "init_mode": "cuda",
                "init_args": [],
                "driver": "nvidia",
                "supports_cuda_filters": supports_cuda_filters,
                "rank": 90
            }
    except Exception:
        pass
    return None


def detect_hardware_acceleration_profiles() -> List[Dict[str, Any]]:
    """
    检测可用硬件转码配置（参考 Jellyfin 思路）：
    1) 先探测 ffmpeg 能力矩阵；
    2) 枚举 /dev/dri 节点；
    3) 对 QSV/VAAPI 执行真实转码探针并排序返回候选列表。
    """
    profiles: List[Dict[str, Any]] = []
    seen_profile_ids: Set[str] = set()

    def _append_profile(profile: Optional[Dict[str, Any]], rank_boost: int = 0) -> None:
        if not profile:
            return
        normalized = _annotate_profile(profile, rank_boost=rank_boost)
        profile_id = normalized.get("profile_id")
        if not profile_id or profile_id in seen_profile_ids:
            return
        seen_profile_ids.add(profile_id)
        profiles.append(normalized)

    try:
        caps = _probe_ffmpeg_capabilities()
        devices = _list_dri_video_devices()

        # QSV：按设备逐个探测，优先 VAAPI 派生模式，再尝试 direct 模式
        if (
            devices
            and caps["qsv_hwaccel"]
            and caps["h264_qsv_encoder"]
            and caps["vpp_qsv_filter"]
        ):
            qsv_supported_encoders = _build_supported_hw_encoders("qsv", caps)
            for device in devices:
                profile = _test_qsv_profile(device, "derived_vaapi", qsv_supported_encoders)
                if not profile:
                    profile = _test_qsv_profile(device, "direct", qsv_supported_encoders)
                _append_profile(profile)

        # VAAPI：按 iHD -> i965 -> auto 顺序尝试，提升不同代际核显兼容性
        if (
            devices
            and caps["vaapi_hwaccel"]
            and caps["h264_vaapi_encoder"]
            and caps["scale_vaapi_filter"]
        ):
            vaapi_supported_encoders = _build_supported_hw_encoders("vaapi", caps)
            seen_devices = set()
            for device in devices:
                if device in seen_devices:
                    continue
                seen_devices.add(device)
                detected_driver = _probe_vaapi_driver(device)
                driver_order: List[Optional[str]]
                if detected_driver == "iHD":
                    driver_order = ["iHD", None]
                elif detected_driver == "i965":
                    driver_order = ["i965", None]
                else:
                    driver_order = ["iHD", "i965", None]
                for driver in driver_order:
                    profile = _test_vaapi_profile(
                        device,
                        supported_encoders=vaapi_supported_encoders,
                        force_driver=driver
                    )
                    if profile:
                        if detected_driver in {"iHD", "i965"}:
                            profile["vendor"] = "intel"
                        elif detected_driver == "mesa":
                            profile["vendor"] = "amd"
                            profile["rank"] = max(profile.get("rank", 60), 78)
                            env_overrides = dict(profile.get("env_overrides", {}))
                            # 参考 Jellyfin 成熟策略：在 AMD 上关闭 EFC 以避免不稳定行为
                            env_overrides["AMD_DEBUG"] = "noefc"
                            profile["env_overrides"] = env_overrides
                        else:
                            profile["vendor"] = "unknown"
                        _append_profile(profile)
                        break

        # NVIDIA：支持多显卡逐卡探测与选择
        if (
            caps["h264_nvenc_encoder"]
            and _has_nvidia_runtime()
        ):
            supports_cuda_filters = caps["scale_cuda_filter"] and caps["hwupload_cuda_filter"]
            nvenc_supported_encoders = _build_supported_hw_encoders("nvenc", caps)
            gpu_candidates = _list_nvidia_gpu_candidates()
            for idx, gpu in enumerate(gpu_candidates):
                nv_profile = _test_nvenc_profile(
                    supports_cuda_filters=supports_cuda_filters,
                    supported_encoders=nvenc_supported_encoders,
                    gpu_index=int(gpu.get("gpu_index", 0)),
                    gpu_name=str(gpu.get("gpu_name") or f"NVIDIA GPU {idx}")
                )
                _append_profile(nv_profile, rank_boost=max(0, 3 - idx))

    except Exception as e:
        logger.debug(f"硬件加速配置探测失败: {str(e)}")

    profiles.sort(
        key=lambda x: (
            int(x.get("rank", 0)),
            str(x.get("vendor") or ""),
            str(x.get("hwaccel") or "")
        ),
        reverse=True
    )
    return profiles


def detect_hardware_acceleration():
    """检测首选硬件加速类型（兼容旧调用，返回首选项）。"""
    profiles = get_hardware_acceleration_profiles()
    if profiles:
        best = profiles[0]
        logger.info(
            "检测到硬件加速支持: %s (%s, device=%s, mode=%s)",
            best.get("hwaccel"),
            best.get("encoder"),
            best.get("device"),
            best.get("init_mode")
        )
        _set_last_transcoder(
            best.get("hwaccel"),
            best.get("encoder"),
            None,
            None,
            vendor=best.get("vendor"),
            profile_id=best.get("profile_id"),
            gpu_index=best.get("gpu_index"),
            device=best.get("device")
        )
        return best.get("hwaccel"), best.get("encoder")

    logger.info("未检测到硬件加速支持，将使用 CPU 编码")
    _set_last_transcoder("cpu", "libx264", None, None, vendor=None, profile_id=None, gpu_index=None, device=None)
    return None, None


# 缓存硬件加速检测结果
_hwaccel_cache = None
_encoder_cache = None
_hwaccel_profiles_cache: Optional[List[Dict[str, Any]]] = None

_last_hwaccel_used: Optional[str] = None
_last_encoder_used: Optional[str] = None
_last_transcoder_fps: Optional[float] = None
_last_transcoder_speed: Optional[float] = None
_last_transcoder_vendor: Optional[str] = None
_last_transcoder_profile_id: Optional[str] = None
_last_transcoder_gpu_index: Optional[int] = None
_last_transcoder_device: Optional[str] = None
_last_frame_interpolation_active: bool = False
_last_frame_interpolation_mode: str = "off"
_last_frame_interpolation_target_fps: Optional[int] = None
_last_transcoder_digest: Optional[tuple] = None

def _set_last_transcoder(
    hardware: Optional[str],
    encoder: Optional[str],
    fps: Optional[float] = None,
    speed: Optional[float] = None,
    vendor: Optional[str] = None,
    profile_id: Optional[str] = None,
    gpu_index: Optional[Any] = None,
    device: Optional[str] = None,
    frame_interpolation_active: bool = False,
    frame_interpolation_mode: str = "off",
    frame_interpolation_target_fps: Optional[int] = None
) -> None:
    global _last_hwaccel_used, _last_encoder_used, _last_transcoder_fps, _last_transcoder_speed
    global _last_transcoder_vendor, _last_transcoder_profile_id, _last_transcoder_gpu_index, _last_transcoder_device
    global _last_frame_interpolation_active, _last_frame_interpolation_mode, _last_frame_interpolation_target_fps
    global _last_transcoder_digest
    _last_hwaccel_used = hardware
    _last_encoder_used = encoder
    _last_transcoder_fps = fps
    _last_transcoder_speed = speed
    normalized_vendor = str(vendor or "").strip().lower() or None
    normalized_profile_id = str(profile_id or "").strip() or None
    normalized_device = str(device or "").strip() or None
    normalized_gpu_index: Optional[int] = None
    try:
        if gpu_index is not None and str(gpu_index).strip() != "":
            normalized_gpu_index = int(gpu_index)
    except Exception:
        normalized_gpu_index = None
    _last_transcoder_vendor = normalized_vendor
    _last_transcoder_profile_id = normalized_profile_id
    _last_transcoder_gpu_index = normalized_gpu_index
    _last_transcoder_device = normalized_device
    normalized_fi_mode = str(frame_interpolation_mode or "off").strip().lower()
    if normalized_fi_mode not in {"off", "30to60", "60to120"}:
        normalized_fi_mode = "off"
    normalized_fi_target: Optional[int] = None
    try:
        if frame_interpolation_target_fps is not None:
            parsed_target = int(frame_interpolation_target_fps)
            if parsed_target > 0:
                normalized_fi_target = parsed_target
    except Exception:
        normalized_fi_target = None
    normalized_fi_active = bool(frame_interpolation_active and normalized_fi_target)
    if not normalized_fi_active:
        normalized_fi_mode = "off"
        normalized_fi_target = None

    _last_frame_interpolation_active = normalized_fi_active
    _last_frame_interpolation_mode = normalized_fi_mode
    _last_frame_interpolation_target_fps = normalized_fi_target

    digest = (
        hardware,
        encoder,
        None if fps is None else round(fps, 2),
        None if speed is None else round(speed, 3),
        normalized_vendor,
        normalized_profile_id,
        normalized_gpu_index,
        normalized_device,
        normalized_fi_active,
        normalized_fi_mode,
        normalized_fi_target
    )
    prev_digest = _last_transcoder_digest
    _last_transcoder_digest = digest
    if prev_digest == digest:
        return
    
    # 异步发送 WebSocket 更新
    try:
        import asyncio
        from .websocket import broadcast_transcode_update
        
        # 获取当前转码器信息
        transcoder_info = _get_last_transcoder(include_label=True)
        
        # 尝试发送 WebSocket 更新
        try:
            # 获取当前事件循环
            loop = asyncio.get_running_loop()
            # 在事件循环中创建任务
            loop.create_task(broadcast_transcode_update(transcoder_info))
        except RuntimeError:
            # 如果没有运行的事件循环，在后台线程中处理
            import threading
            
            def send_update_in_thread():
                try:
                    # 创建新的事件循环
                    new_loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(new_loop)
                    try:
                        new_loop.run_until_complete(broadcast_transcode_update(transcoder_info))
                    finally:
                        new_loop.close()
                except Exception as e:
                    logger.debug(f"后台发送转码状态更新失败: {e}")
            
            # 启动后台线程
            thread = threading.Thread(target=send_update_in_thread, daemon=True)
            thread.start()
            
    except Exception as e:
        logger.debug(f"发送转码状态更新时出错: {e}")

def _get_last_transcoder(include_label: bool = True) -> dict:
    hardware = _last_hwaccel_used or "cpu"
    encoder = _last_encoder_used or ("libx264" if hardware == "cpu" else None)
    fps = _last_transcoder_fps
    speed = _last_transcoder_speed
    vendor = _last_transcoder_vendor
    profile_id = _last_transcoder_profile_id
    gpu_index = _last_transcoder_gpu_index
    device = _last_transcoder_device
    fi_active = bool(_last_frame_interpolation_active)
    fi_mode = str(_last_frame_interpolation_mode or "off").lower()
    fi_target_fps = _last_frame_interpolation_target_fps
    if hardware != "cpu" and not encoder:
        hwaccel, cached_encoder = get_hardware_acceleration()
        if hwaccel:
            hardware = hwaccel
        if cached_encoder:
            encoder = cached_encoder
    if hardware == "cpu" and encoder is None:
        encoder = "libx264"
    label_map = {
        "qsv": "QSV",
        "vaapi": "VAAPI",
        "nvenc": "NVENC",
        "cpu": "CPU"
    }
    result = {
        "hardware": hardware,
        "encoder": encoder,
        "fps": fps,
        "speed": speed,
        "vendor": vendor,
        "profile_id": profile_id,
        "gpu_index": gpu_index,
        "device": device,
        "frame_interpolation_active": fi_active,
        "frame_interpolation_mode": fi_mode,
        "frame_interpolation_target_fps": fi_target_fps
    }
    if include_label:
        parts = [label_map.get(hardware, hardware.upper())]
        if encoder:
            parts.append(encoder)
        if speed is not None:
            parts.append(f"{speed:.2f}x")
        if fps is not None:
            parts.append(f"{fps:.2f}fps")
        result["label"] = " · ".join(parts)
    return result

def invalidate_hardware_acceleration_cache() -> None:
    global _hwaccel_cache, _encoder_cache, _hwaccel_profiles_cache
    _hwaccel_cache = None
    _encoder_cache = None
    _hwaccel_profiles_cache = None
    _invalidate_ffmpeg_caps_cache()


def _resolve_effective_hw_profiles(
    detected_profiles: List[Dict[str, Any]],
    settings: Dict[str, Any]
) -> List[Dict[str, Any]]:
    if not detected_profiles:
        return []

    mode = str(settings.get("mode") or "auto").lower()
    if mode == "cpu_only":
        return []

    profiles = list(detected_profiles)
    if mode != "manual":
        return profiles

    selected_profile_id = str(settings.get("selected_profile_id") or "").strip()
    selected_hwaccel = str(settings.get("selected_hwaccel") or "").strip().lower()
    selected_vendor = str(settings.get("selected_vendor") or "").strip().lower()
    allow_other = bool(settings.get("allow_fallback_to_other_hardware", True))

    selected: Optional[Dict[str, Any]] = None
    if selected_profile_id:
        selected = next((p for p in profiles if p.get("profile_id") == selected_profile_id), None)
        # 显式选了 profile_id 时，不再回退到 hwaccel/vendor 旧字段，避免锁到错误 GPU。
        if selected is None:
            return profiles if allow_other else []

    if selected is None and selected_hwaccel:
        selected = next(
            (
                p for p in profiles
                if str(p.get("hwaccel") or "").lower() == selected_hwaccel
                and (not selected_vendor or str(p.get("vendor") or "").lower() == selected_vendor)
            ),
            None
        )

    if selected is None and selected_vendor:
        selected = next((p for p in profiles if str(p.get("vendor") or "").lower() == selected_vendor), None)

    if selected is None:
        return profiles if allow_other else []

    if not allow_other:
        return [selected]
    selected_id = selected.get("profile_id")
    remainder = [p for p in profiles if p.get("profile_id") != selected_id]
    selected_hwaccel = str(selected.get("hwaccel") or "").lower()
    # 回退顺序优先尝试“不同后端”，避免 qsv 失败后再次命中另一个 qsv 配置。
    # 这样即使当前仅支持一次回退，也更容易切到 vaapi/cpu 成功。
    remainder_diff_backend = [
        p for p in remainder
        if str(p.get("hwaccel") or "").lower() != selected_hwaccel
    ]
    remainder_same_backend = [
        p for p in remainder
        if str(p.get("hwaccel") or "").lower() == selected_hwaccel
    ]
    return [selected] + remainder_diff_backend + remainder_same_backend


def get_detected_hardware_acceleration_profiles(force_refresh: bool = False) -> List[Dict[str, Any]]:
    global _hwaccel_profiles_cache
    if force_refresh:
        invalidate_hardware_acceleration_cache()
    if _hwaccel_profiles_cache is None:
        _hwaccel_profiles_cache = detect_hardware_acceleration_profiles()
    return list(_hwaccel_profiles_cache or [])


def get_hardware_acceleration():
    """获取硬件加速配置（按设置中心策略后的首选项，带缓存）"""
    global _hwaccel_cache, _encoder_cache
    if _hwaccel_cache is None:
        profiles = get_hardware_acceleration_profiles()
        if profiles:
            best = profiles[0]
            _hwaccel_cache = best.get("hwaccel")
            _encoder_cache = best.get("encoder")
        else:
            _hwaccel_cache, _encoder_cache = (None, None)
    return _hwaccel_cache, _encoder_cache


def get_hardware_acceleration_profiles():
    """获取策略生效后的硬件加速候选配置（带缓存）。"""
    detected_profiles = get_detected_hardware_acceleration_profiles(force_refresh=False)
    settings = get_transcode_settings(force_reload=False)
    return _resolve_effective_hw_profiles(detected_profiles, settings)


def refresh_hardware_acceleration_profiles() -> List[Dict[str, Any]]:
    invalidate_hardware_acceleration_cache()
    return get_hardware_acceleration_profiles()


def _hw_decode_breaker_window_seconds() -> int:
    raw = os.getenv("EASY_VDL_HW_DECODE_BREAKER_SECONDS", "300")
    try:
        value = int(str(raw).strip())
    except Exception:
        value = 300
    return max(30, value)


_hw_decode_breaker_until: Dict[str, float] = {}
_hw_decode_breaker_lock = threading.Lock()
_qsv_encoder_breaker_until: Dict[str, float] = {}
_qsv_encoder_breaker_lock = threading.Lock()

_stream_ffmpeg_registry_lock = asyncio.Lock()
_stream_ffmpeg_registry: Dict[str, Dict[str, Any]] = {}


async def _terminate_subprocess_tree(proc: Any, term_timeout: float = 2.0, kill_timeout: float = 1.0) -> None:
    if not proc or getattr(proc, "returncode", None) is not None:
        return
    try:
        used_group_term = False
        if hasattr(os, "killpg") and getattr(proc, "pid", None):
            try:
                os.killpg(proc.pid, signal.SIGTERM)
                used_group_term = True
            except ProcessLookupError:
                used_group_term = True
        if not used_group_term:
            proc.terminate()
    except BaseException:
        pass

    exited = False
    try:
        await asyncio.wait_for(asyncio.shield(proc.wait()), timeout=term_timeout)
        exited = True
    except Exception:
        exited = False

    if exited or getattr(proc, "returncode", None) is not None:
        return

    try:
        used_group_kill = False
        if hasattr(os, "killpg") and getattr(proc, "pid", None):
            try:
                os.killpg(proc.pid, signal.SIGKILL)
                used_group_kill = True
            except ProcessLookupError:
                used_group_kill = True
        if not used_group_kill:
            proc.kill()
        await asyncio.wait_for(asyncio.shield(proc.wait()), timeout=kill_timeout)
    except Exception:
        pass


async def _register_stream_ffmpeg_request(stream_key: str, owner_token: str, start_time: float) -> None:
    stale_proc = None
    stale_owner = ""
    stale_global: List[Dict[str, Any]] = []
    async with _stream_ffmpeg_registry_lock:
        prev = _stream_ffmpeg_registry.get(stream_key)
        if prev:
            stale_proc = prev.get("process")
            stale_owner = str(prev.get("owner") or "")
        _stream_ffmpeg_registry[stream_key] = {
            "owner": owner_token,
            "process": None,
            "created_at": time.monotonic(),
            "last_chunk_at": None,
            "last_touch_at": time.monotonic()
        }
        for existing_key, info in _stream_ffmpeg_registry.items():
            if existing_key == stream_key:
                continue
            existing_owner = str(info.get("owner") or "")
            if not existing_owner or existing_owner == owner_token:
                continue
            existing_proc = info.get("process")
            if not existing_proc or getattr(existing_proc, "returncode", None) is not None:
                continue
            stale_global.append(
                {
                    "key": existing_key,
                    "owner": existing_owner,
                    "proc": existing_proc,
                    "reason": "strict_single_newest_wins"
                }
            )

    if stale_proc and getattr(stale_proc, "returncode", None) is None:
        logger.info(
            "检测到同键转码新请求，终止旧 ffmpeg: key=%s, old_owner=%s, start=%.3f, pid=%s",
            stream_key,
            stale_owner[:8] if stale_owner else "unknown",
            start_time,
            getattr(stale_proc, "pid", "unknown")
        )
        await _terminate_subprocess_tree(stale_proc)
    for stale in stale_global:
        stale_proc_item = stale.get("proc")
        if not stale_proc_item or getattr(stale_proc_item, "returncode", None) is not None:
            continue
        logger.info(
            "单转码模式启用，终止旧 ffmpeg: key=%s, old_key=%s, old_owner=%s, reason=%s, pid=%s",
            stream_key,
            stale.get("key"),
            str(stale.get("owner") or "")[:8] or "unknown",
            stale.get("reason"),
            getattr(stale_proc_item, "pid", "unknown")
        )
        await _terminate_subprocess_tree(stale_proc_item)


async def _is_stream_ffmpeg_owner(stream_key: str, owner_token: str) -> bool:
    async with _stream_ffmpeg_registry_lock:
        current = _stream_ffmpeg_registry.get(stream_key)
        if not current:
            return False
        return str(current.get("owner") or "") == owner_token


async def _bind_stream_ffmpeg_process(stream_key: str, owner_token: str, proc: Any) -> bool:
    async with _stream_ffmpeg_registry_lock:
        current = _stream_ffmpeg_registry.get(stream_key)
        if not current or str(current.get("owner") or "") != owner_token:
            return False
        current["process"] = proc
        current["last_touch_at"] = time.monotonic()
        return True


async def _touch_stream_ffmpeg_session(stream_key: str, owner_token: str, has_chunk: bool = False) -> None:
    now = time.monotonic()
    async with _stream_ffmpeg_registry_lock:
        current = _stream_ffmpeg_registry.get(stream_key)
        if not current or str(current.get("owner") or "") != owner_token:
            return
        current["last_touch_at"] = now
        if has_chunk:
            current["last_chunk_at"] = now


async def _unregister_stream_ffmpeg_request(stream_key: str, owner_token: str) -> None:
    async with _stream_ffmpeg_registry_lock:
        current = _stream_ffmpeg_registry.get(stream_key)
        if current and str(current.get("owner") or "") == owner_token:
            _stream_ffmpeg_registry.pop(stream_key, None)


def _build_hw_decode_breaker_key(
    decode_backend: str,
    codec: str,
    pix_fmt: Optional[str],
    bit_depth: Optional[int],
    video_profile: Optional[str]
) -> str:
    backend = str(decode_backend or "unknown").strip().lower()
    codec_value = _normalize_video_codec_name(codec or "unknown")
    pix_value = str(pix_fmt or "unknown").strip().lower() or "unknown"
    depth_value = str(int(bit_depth)) if isinstance(bit_depth, int) and bit_depth > 0 else "unknown"
    profile_value = str(video_profile or "unknown").strip().lower() or "unknown"
    return "|".join([backend, codec_value, pix_value, depth_value, profile_value])


def _is_hw_decode_breaker_active(key: str) -> bool:
    if not key:
        return False
    now = time.monotonic()
    with _hw_decode_breaker_lock:
        expires_at = _hw_decode_breaker_until.get(key)
        if expires_at is None:
            return False
        if expires_at <= now:
            _hw_decode_breaker_until.pop(key, None)
            return False
        return True


def _trip_hw_decode_breaker(key: str, reason: str = "") -> None:
    if not key:
        return
    ttl = _hw_decode_breaker_window_seconds()
    expires_at = time.monotonic() + ttl
    with _hw_decode_breaker_lock:
        _hw_decode_breaker_until[key] = expires_at
    logger.warning(
        "触发硬解熔断，%s 秒内回退软解: key=%s, reason=%s",
        ttl,
        key,
        reason or "unknown"
    )


def _looks_like_hw_decode_failure(stderr_text: str) -> bool:
    text = str(stderr_text or "").lower()
    if not text:
        return False
    keywords = [
        "hwaccel",
        "no device available",
        "device setup failed",
        "failed to initialise",
        "failed to initialize",
        "error creating a hwdevice",
        "error creating a device",
        "decoder init failed",
        "could not find a valid device",
        "vaapi",
        "qsv",
        "cuvid",
        "nvdec",
        "cuda",
        "unsupported pix_fmt"
    ]
    return any(word in text for word in keywords)


def _qsv_encoder_breaker_window_seconds() -> int:
    raw = os.getenv("EASY_VDL_QSV_ENCODER_BREAKER_SECONDS", "600")
    try:
        value = int(str(raw).strip())
    except Exception:
        value = 600
    return max(60, value)


def _build_qsv_encoder_breaker_key(profile_id: Any, encoder: Any) -> str:
    profile_part = str(profile_id or "unknown_profile").strip().lower() or "unknown_profile"
    encoder_part = str(encoder or "unknown_encoder").strip().lower() or "unknown_encoder"
    return f"{profile_part}|{encoder_part}"


def _is_qsv_encoder_breaker_active(key: str) -> bool:
    if not key:
        return False
    now = time.monotonic()
    with _qsv_encoder_breaker_lock:
        expires_at = _qsv_encoder_breaker_until.get(key)
        if expires_at is None:
            return False
        if expires_at <= now:
            _qsv_encoder_breaker_until.pop(key, None)
            return False
        return True


def _trip_qsv_encoder_breaker(key: str, reason: str = "") -> None:
    if not key:
        return
    ttl = _qsv_encoder_breaker_window_seconds()
    with _qsv_encoder_breaker_lock:
        _qsv_encoder_breaker_until[key] = time.monotonic() + ttl
    logger.warning(
        "触发 QSV 编码熔断，%s 秒内优先跳过该 QSV 编码组合: key=%s, reason=%s",
        ttl,
        key,
        reason or "unknown"
    )


def _looks_like_qsv_encoder_unsupported(stderr_text: str) -> bool:
    text = str(stderr_text or "").lower()
    if not text:
        return False
    return (
        "selected ratecontrol mode is unsupported" in text
        or "parameters are not supported by the qsv runtime" in text
    )


@router.get("/api/video/stream")
async def stream_video_transcoded(
    current_user: User = Depends(get_current_user_mixed),
    filename: str = Query(..., description="视频文件路径（相对于 /app/downloads/）"),
    quality: str = Query("720p", description="转码质量：original/720p/480p/360p"),
    start: float = Query(0.0, description="从指定秒数开始播放（original 与转码都支持）"),
    container: str = Query("auto", description="封装输出模式：auto/source/mp4（仅 original 生效）"),
    request: Request = None
):
    """
    转码播放视频（支持硬件加速，节省外网流量）
    
    - original: 原画质（无偏移时走文件流；有偏移时服务端从指定时间点起播）
    - 720p: 720p 转码（适合外网播放）
    - 480p: 480p 转码（节省流量）
    - 360p: 360p 转码（最低流量）
    """
    try:
        base_dir = "/app/downloads"
        
        # URL 解码文件名（FastAPI 可能已经解码，但为了安全再次解码）
        decoded_filename = urllib.parse.unquote(filename)
        file_path = os.path.join(base_dir, decoded_filename)
        
        # 检查文件是否存在
        if not os.path.exists(file_path):
            logger.warning(f"视频文件不存在: {file_path}")
            # 尝试列出目录内容以便调试
            dir_path = os.path.dirname(file_path)
            if os.path.exists(dir_path):
                try:
                    files_in_dir = os.listdir(dir_path)[:5]  # 只列出前5个文件
                    logger.warning(f"目录 {dir_path} 中的文件: {files_in_dir}")
                except:
                    pass
            # 确保错误消息是 ASCII 安全的
            safe_detail = f"视频文件不存在: {os.path.basename(decoded_filename).encode('ascii', 'ignore').decode() or 'unknown'}"
            raise HTTPException(status_code=404, detail=safe_detail)

        # 图集目录被当作视频文件请求时，返回可读错误，避免 IsADirectoryError 噪音
        if os.path.isdir(file_path):
            logger.warning(f"请求的视频路径为目录（图集）: {file_path}")
            safe_detail = "目标为图集目录，请在播放中心使用图集预览或打包下载"
            raise HTTPException(status_code=400, detail=safe_detail)
        
        safe_start = 0.0
        if start is not None:
            try:
                safe_start = float(start)
            except (TypeError, ValueError):
                safe_start = 0.0
            if not math.isfinite(safe_start) or safe_start < 0:
                safe_start = 0.0
            elif safe_start > 0:
                abs_path = os.path.abspath(file_path)
                original_duration = await asyncio.to_thread(_probe_video_duration_cached, abs_path)
                if original_duration and safe_start >= original_duration:
                    safe_start = max(original_duration - 0.5, 0.0)

        # 记录调试信息
        logger.info(
            f"转码请求: filename={filename}, decoded={decoded_filename}, path={file_path}, "
            f"quality={quality}, start={safe_start:.3f}, container={container}"
        )

        def _build_safe_content_disposition(file_name: str) -> str:
            safe_filename = os.path.basename(file_name)
            fallback_filename = safe_filename.encode('ascii', 'ignore').decode() or 'video.mp4'
            encoded_filename = urllib.parse.quote(safe_filename, safe='')
            try:
                value = f'inline; filename="{fallback_filename}"; filename*=UTF-8\'\'{encoded_filename}'
                value.encode('ascii')
                return value
            except UnicodeEncodeError:
                return f'inline; filename*=UTF-8\'\'{encoded_filename}'

        def _parse_range_header(header_value: Optional[str], file_size: int) -> Optional[tuple[int, int]]:
            if not header_value:
                return None
            if not header_value.startswith("bytes="):
                raise HTTPException(status_code=416, detail="无效的 Range 请求")

            # 仅处理单段 Range，浏览器 seek 场景已足够
            range_spec = header_value[len("bytes="):].split(",", 1)[0].strip()
            if "-" not in range_spec:
                raise HTTPException(status_code=416, detail="无效的 Range 请求")

            start_str, end_str = range_spec.split("-", 1)
            if not start_str and not end_str:
                raise HTTPException(status_code=416, detail="无效的 Range 请求")

            if start_str:
                try:
                    start_byte = int(start_str)
                except ValueError:
                    raise HTTPException(status_code=416, detail="无效的 Range 请求")
                if start_byte < 0:
                    raise HTTPException(status_code=416, detail="无效的 Range 请求")
                if end_str:
                    try:
                        end_byte = int(end_str)
                    except ValueError:
                        raise HTTPException(status_code=416, detail="无效的 Range 请求")
                else:
                    end_byte = file_size - 1
            else:
                # bytes=-N：最后 N 字节
                try:
                    suffix_len = int(end_str)
                except ValueError:
                    raise HTTPException(status_code=416, detail="无效的 Range 请求")
                if suffix_len <= 0:
                    raise HTTPException(status_code=416, detail="无效的 Range 请求")
                suffix_len = min(suffix_len, file_size)
                start_byte = file_size - suffix_len
                end_byte = file_size - 1

            if start_byte >= file_size:
                raise HTTPException(status_code=416, detail="Range 超出文件大小")
            end_byte = min(end_byte, file_size - 1)
            if start_byte > end_byte:
                raise HTTPException(status_code=416, detail="无效的 Range 请求")
            return start_byte, end_byte

        def _stream_file_with_range(path: str, request_range: Optional[str]) -> StreamingResponse:
            file_size = os.path.getsize(path)
            content_disposition = _build_safe_content_disposition(decoded_filename)
            ext = os.path.splitext(path)[1].lower()
            if ext == ".ts":
                media_type = "video/mp2t"
            else:
                media_type = "video/mp4"

            if file_size <= 0:
                empty = FastAPIResponse(content=b"", media_type=media_type)
                empty.headers["Accept-Ranges"] = "bytes"
                empty.headers["Content-Disposition"] = content_disposition
                empty.headers["Content-Length"] = "0"
                return empty

            try:
                parsed_range = _parse_range_header(request_range, file_size)
            except HTTPException as ex:
                headers = {
                    "Accept-Ranges": "bytes",
                    "Content-Range": f"bytes */{file_size}",
                    "Content-Disposition": content_disposition
                }
                raise HTTPException(status_code=ex.status_code, detail=ex.detail, headers=headers)

            if parsed_range:
                range_start, range_end = parsed_range
                status_code = 206
            else:
                range_start, range_end = 0, file_size - 1
                status_code = 200

            # TS 原始流通常由播放器频繁小范围拉取，适度增大块大小可减少 I/O 抖动与卡顿。
            # MP4 保持较小块以控制首包延迟。
            chunk_size = 512 * 1024 if ext == ".ts" else 64 * 1024
            content_length = range_end - range_start + 1

            def file_generator():
                with open(path, "rb") as f:
                    f.seek(range_start)
                    remaining = content_length
                    while remaining > 0:
                        chunk = f.read(min(chunk_size, remaining))
                        if not chunk:
                            break
                        remaining -= len(chunk)
                        yield chunk

            response = StreamingResponse(file_generator(), media_type=media_type, status_code=status_code)
            response.headers["Accept-Ranges"] = "bytes"
            response.headers["Content-Disposition"] = content_disposition
            response.headers["Content-Length"] = str(content_length)
            if parsed_range:
                response.headers["Content-Range"] = f"bytes {range_start}-{range_end}/{file_size}"
            return response

        def _stream_original_with_start(
            path: str,
            start_time: float,
            req: Optional[Request],
            force_aac_adtstoasc: bool = False
        ) -> StreamingResponse:
            """original 模式下通过 ffmpeg 从指定时间点起播，避免前端 local seek 回零。"""
            safe_filename = os.path.basename(decoded_filename)
            fallback_filename = safe_filename.encode('ascii', 'ignore').decode() or 'video.mp4'
            encoded_filename = urllib.parse.quote(safe_filename, safe='')
            try:
                content_disposition = f'inline; filename="{fallback_filename}"; filename*=UTF-8\'\'{encoded_filename}'
                content_disposition.encode('ascii')
            except UnicodeEncodeError:
                content_disposition = f'inline; filename*=UTF-8\'\'{encoded_filename}'

            ffmpeg_cmd = [
                "ffmpeg",
                "-hide_banner",
                "-ss",
                f"{max(start_time, 0.0):.3f}",
                "-i",
                path,
                "-c",
                "copy",
                "-movflags",
                "+frag_keyframe+empty_moov",
            ]
            if force_aac_adtstoasc:
                ffmpeg_cmd.extend(["-bsf:a", "aac_adtstoasc"])
            ffmpeg_cmd.extend([
                "-f",
                "mp4",
                "-"
            ])

            async def generate():
                process = None
                stderr_lines: List[str] = []
                stderr_task = None
                disconnect_task = None
                terminate_lock = asyncio.Lock()
                termination_logged = False
                terminated_for_disconnect = False
                terminated_for_timeout = False
                last_output_at = time.monotonic()
                try:
                    idle_timeout_seconds = float(os.getenv("EASY_VDL_ORIGINAL_START_IDLE_TIMEOUT", "5"))
                except Exception:
                    idle_timeout_seconds = 5.0
                idle_timeout_seconds = max(3.0, min(120.0, idle_timeout_seconds))

                async def terminate_process_if_running(reason: str) -> None:
                    nonlocal terminated_for_disconnect, terminated_for_timeout, termination_logged
                    async with terminate_lock:
                        proc = process
                        if proc and proc.returncode is None:
                            if reason and not termination_logged:
                                logger.info(
                                    f"终止 original 起播 ffmpeg 进程: reason={reason}, start={start_time:.3f}, pid={getattr(proc, 'pid', 'unknown')}"
                                )
                                termination_logged = True

                            try:
                                used_group_term = False
                                if hasattr(os, "killpg") and getattr(proc, "pid", None):
                                    try:
                                        os.killpg(proc.pid, signal.SIGTERM)
                                        used_group_term = True
                                    except ProcessLookupError:
                                        used_group_term = True
                                if not used_group_term:
                                    proc.terminate()
                            except BaseException as term_err:
                                logger.warning(f"发送 SIGTERM 失败，准备升级 SIGKILL: {term_err}")

                            exited = False
                            try:
                                await asyncio.wait_for(asyncio.shield(proc.wait()), timeout=2)
                                exited = True
                            except asyncio.TimeoutError:
                                exited = False
                            except BaseException as wait_err:
                                logger.warning(f"等待 ffmpeg 退出异常，准备升级 SIGKILL: {wait_err}")

                            if not exited and proc.returncode is None:
                                try:
                                    used_group_kill = False
                                    if hasattr(os, "killpg") and getattr(proc, "pid", None):
                                        try:
                                            os.killpg(proc.pid, signal.SIGKILL)
                                            used_group_kill = True
                                        except ProcessLookupError:
                                            used_group_kill = True
                                    if not used_group_kill:
                                        proc.kill()
                                    await asyncio.wait_for(asyncio.shield(proc.wait()), timeout=1)
                                except asyncio.TimeoutError:
                                    logger.warning(
                                        f"强制终止 original 起播 ffmpeg 超时: start={start_time:.3f}, pid={getattr(proc, 'pid', 'unknown')}"
                                    )
                                except BaseException as kill_err:
                                    logger.warning(
                                        f"强制终止 original 起播 ffmpeg 异常: start={start_time:.3f}, pid={getattr(proc, 'pid', 'unknown')}, err={kill_err}"
                                    )
                    if reason and "disconnect" in reason:
                        terminated_for_disconnect = True
                    if reason and "timeout" in reason:
                        terminated_for_timeout = True

                try:
                    env = os.environ.copy()
                    env['LC_ALL'] = 'C.UTF-8'
                    env['LANG'] = 'C.UTF-8'
                    process = await asyncio.create_subprocess_exec(
                        *ffmpeg_cmd,
                        stdout=asyncio.subprocess.PIPE,
                        stderr=asyncio.subprocess.PIPE,
                        env=env,
                        start_new_session=True
                    )

                    async def read_stderr(proc):
                        try:
                            while True:
                                line = await proc.stderr.readline()
                                if not line:
                                    break
                                text = line.decode('utf-8', errors='ignore').strip()
                                if text:
                                    stderr_lines.append(text)
                        except Exception:
                            pass

                    async def watch_disconnect():
                        if not req:
                            return
                        try:
                            while True:
                                await asyncio.sleep(0.25)
                                if await req.is_disconnected():
                                    await asyncio.shield(terminate_process_if_running("client_disconnect"))
                                    break
                        except asyncio.CancelledError:
                            raise
                        except Exception:
                            pass

                    stderr_task = asyncio.create_task(read_stderr(process))
                    disconnect_task = asyncio.create_task(watch_disconnect())

                    try:
                        while True:
                            if req:
                                try:
                                    if await req.is_disconnected():
                                        await asyncio.shield(terminate_process_if_running("client_disconnect"))
                                        break
                                except Exception:
                                    pass
                            try:
                                chunk = await asyncio.wait_for(process.stdout.read(8192), timeout=1.0)
                            except asyncio.TimeoutError:
                                if process and process.returncode is not None:
                                    break
                                if (time.monotonic() - last_output_at) >= idle_timeout_seconds:
                                    await asyncio.shield(terminate_process_if_running("no_output_timeout"))
                                    break
                                continue
                            if not chunk:
                                break
                            last_output_at = time.monotonic()
                            yield chunk
                    except (GeneratorExit, ConnectionError, BrokenPipeError, OSError, asyncio.CancelledError):
                        await asyncio.shield(terminate_process_if_running("stream_cancelled_or_disconnected"))
                        if stderr_task and not stderr_task.done():
                            stderr_task.cancel()
                        if disconnect_task and not disconnect_task.done():
                            disconnect_task.cancel()
                        raise

                    return_code = await process.wait()
                    if stderr_task:
                        try:
                            await asyncio.wait_for(stderr_task, timeout=2)
                        except asyncio.TimeoutError:
                            stderr_task.cancel()
                    if disconnect_task and not disconnect_task.done():
                        disconnect_task.cancel()

                    if return_code != 0 and not terminated_for_disconnect and not terminated_for_timeout:
                        error_text = '\n'.join(stderr_lines[-10:])
                        logger.error(f"original 起播偏移失败 (返回码: {return_code}): {error_text[:500]}")
                        raise Exception(f"ffmpeg original start failed (code={return_code})")
                finally:
                    if disconnect_task and not disconnect_task.done():
                        disconnect_task.cancel()
                    if stderr_task and not stderr_task.done():
                        stderr_task.cancel()
                    if process and process.returncode is None:
                        await asyncio.shield(terminate_process_if_running("generator_finally_cleanup"))

            response = StreamingResponse(generate(), media_type="video/mp4")
            response.headers["Content-Disposition"] = content_disposition
            response.headers["Cache-Control"] = "no-cache"
            response.headers["X-Video-Start"] = f"{start_time:.3f}"
            return response

        # original 分支优先级：
        # 1) safe_start > 0: 强制按服务端 start 起播（优先级高于 Range）
        # 2) safe_start <= 0: 走常规 Range 文件流
        # 这样可以避免浏览器默认 Range=bytes=0- 导致恢复时回到起点。
        if quality == "original":
            request_range = request.headers.get("range") if request else None
            ext = os.path.splitext(file_path)[1].lower()
            force_mp4_container = str(container or "auto").lower() == "mp4"
            if ext == ".ts" and force_mp4_container:
                # TS 原画下改用服务端无损 remux 到 fMP4，前端走原生 video 更稳定。
                return _stream_original_with_start(
                    file_path,
                    safe_start,
                    request,
                    force_aac_adtstoasc=True
                )
            if should_use_original_start_stream(safe_start, request_range):
                return _stream_original_with_start(
                    file_path,
                    safe_start,
                    request,
                    force_aac_adtstoasc=(ext == ".ts")
                )
            return _stream_file_with_range(file_path, request_range)
        
        # 解析 Range 请求头（支持断点续播）
        range_header = request.headers.get("range") if request else None
        start = 0
        end = None
        
        if range_header:
            try:
                range_match = range_header.replace("bytes=", "").split("-")
                start = int(range_match[0]) if range_match[0] else 0
                end = int(range_match[1]) if range_match[1] else None
            except:
                pass
        
        # 获取转码决策所需探测信息（单次 ffprobe + 缓存 + 线程池，避免阻塞事件循环）
        abs_path = os.path.abspath(file_path)
        request_user_id = str(getattr(current_user, "id", "anonymous") or "anonymous")
        stream_ffmpeg_key = (
            f"{request_user_id}|"
            f"{abs_path}|"
            f"{quality}|"
            f"{safe_start:.3f}|"
            f"{str(container or 'auto').lower()}"
        )
        probe_profile = await asyncio.to_thread(_probe_stream_profile_cached, abs_path)
        original_width = int(probe_profile.get("width") or 1920)
        original_height = int(probe_profile.get("height") or 1080)
        original_fps = probe_profile.get("fps")
        has_audio = bool(probe_profile.get("has_audio"))
        video_codec = probe_profile.get("video_codec")
        video_pix_fmt = str(probe_profile.get("pix_fmt") or "").strip().lower()
        video_profile_name = str(probe_profile.get("video_profile") or "").strip()
        probe_bit_depth = probe_profile.get("bit_depth")
        bit_depth: Optional[int] = None
        try:
            if probe_bit_depth is not None:
                parsed_depth = int(probe_bit_depth)
                if parsed_depth > 0:
                    bit_depth = parsed_depth
        except Exception:
            bit_depth = None

        transcode_settings = await asyncio.to_thread(get_transcode_settings)
        # 获取硬件加速候选配置（按设置中心策略排序）
        hw_profiles = await asyncio.to_thread(get_hardware_acceleration_profiles)
        has_qsv_profile = any(str((p or {}).get("hwaccel") or "").lower() == "qsv" for p in (hw_profiles or []))
        # 参考 Jellyfin 的策略：QSV 编码可优先采用系统原生硬解（Linux 下通常是 VAAPI）
        prefer_native_hw_decoder = bool(transcode_settings.get("prefer_native_hw_decoder", True))
        # 默认仍保持稳定优先：不启用全链路硬解，按需可手动开启
        enable_hw_decode = bool(transcode_settings.get("enable_hw_decode", False))
        hw_decode_codec_whitelist = {
            _normalize_video_codec_name(codec)
            for codec in (transcode_settings.get("hardware_decoding_codecs") or [])
            if str(codec or "").strip()
        }
        if not hw_decode_codec_whitelist:
            hw_decode_codec_whitelist = set(_DEFAULT_HW_DECODE_CODECS)
        # Intel 低功耗编码（默认关闭，避免在不支持设备上触发参数兼容问题）
        enable_intel_low_power_h264 = bool(transcode_settings.get("enable_intel_low_power_h264", False))
        enable_intel_low_power_hevc = bool(transcode_settings.get("enable_intel_low_power_hevc", False))
        intel_qsv_frame_interpolation_mode = str(
            transcode_settings.get("intel_qsv_frame_interpolation_mode") or "off"
        ).strip().lower()
        if intel_qsv_frame_interpolation_mode not in {"off", "30to60", "60to120"}:
            intel_qsv_frame_interpolation_mode = "off"
        allow_fallback_to_cpu = bool(transcode_settings.get("allow_fallback_to_cpu", True))
        transcode_mode = str(transcode_settings.get("mode") or "auto")
        fallback_max_out_time_seconds = max(
            0.5,
            float(os.getenv("EASY_VDL_HW_FALLBACK_MAX_OUT_TIME_SECONDS", "8"))
        )
        fallback_max_chunks = max(
            1,
            int(os.getenv("EASY_VDL_HW_FALLBACK_MAX_CHUNKS", "64"))
        )
        configured_output_codec = _normalize_output_video_codec(
            transcode_settings.get("output_video_codec"),
            _DEFAULT_OUTPUT_VIDEO_CODEC
        )
        runtime_caps = await asyncio.to_thread(_probe_ffmpeg_capabilities)
        
        # QSV 支持的硬件解码格式（不包括 AV1，因为大多数 Intel GPU 不支持 AV1 硬解）
        qsv_supported_codecs = {'h264', 'hevc', 'h265', 'mpeg2video', 'vp8', 'vp9', 'vc1', 'mjpeg'}
        # VAAPI 支持的格式
        vaapi_supported_codecs = {'h264', 'hevc', 'h265', 'mpeg2video', 'vp8', 'vp9', 'vc1'}
        # CUDA/NVDEC 常见支持格式（用于是否启用硬解策略判定）
        cuda_supported_codecs = {'h264', 'hevc', 'h265', 'mpeg2video', 'vp8', 'vp9', 'vc1', 'av1', 'mjpeg'}
        
        normalized_video_codec = _normalize_video_codec_name(video_codec)
        software_encoder_map = {
            "h264": ("libx264", bool(runtime_caps.get("libx264_encoder"))),
            "hevc": ("libx265", bool(runtime_caps.get("libx265_encoder"))),
            "av1": ("libsvtav1", bool(runtime_caps.get("libsvtav1_encoder")))
        }

        def _resolve_target_video_codec() -> str:
            if configured_output_codec != "auto":
                return configured_output_codec
            if normalized_video_codec in {"h264", "hevc", "av1"}:
                return normalized_video_codec
            return "h264"

        target_video_codec = _resolve_target_video_codec()

        def _resolve_hw_encoder_for_codec(hwaccel: Optional[str], codec: str) -> Optional[str]:
            hw = str(hwaccel or "").lower()
            codec_value = _normalize_video_codec_name(codec)
            if codec_value not in {"h264", "hevc", "av1"}:
                return None
            suffix_map = {
                "qsv": "_qsv",
                "vaapi": "_vaapi",
                "nvenc": "_nvenc"
            }
            suffix = suffix_map.get(hw)
            if not suffix:
                return None
            return f"{codec_value}{suffix}"

        def _select_video_encoder(profile: Optional[Dict[str, Any]], codec: str) -> str:
            codec_value = _normalize_video_codec_name(codec)
            if codec_value not in {"h264", "hevc", "av1"}:
                codec_value = "h264"
            if profile:
                hwaccel = str(profile.get("hwaccel") or "").lower()
                preferred_hw_encoder = _resolve_hw_encoder_for_codec(hwaccel, codec_value)
                supported_encoders = {
                    str(item or "").strip().lower()
                    for item in (profile.get("supported_encoders") or [])
                    if str(item or "").strip()
                }
                legacy_encoder = str(profile.get("encoder") or "").strip().lower()
                if legacy_encoder:
                    supported_encoders.add(legacy_encoder)
                if preferred_hw_encoder and preferred_hw_encoder in supported_encoders:
                    return preferred_hw_encoder
                if legacy_encoder and codec_value == "h264":
                    return legacy_encoder
            software_encoder, available = software_encoder_map.get(codec_value, ("libx264", True))
            if available:
                return software_encoder
            return "libx264"

        def _resolve_decode_backend(profile: Optional[Dict[str, Any]]) -> str:
            backend = str((profile or {}).get("hwaccel") or "").lower()
            if backend == "qsv":
                return "vaapi" if prefer_native_hw_decoder else "qsv"
            return backend

        def _evaluate_hw_decode(profile: Optional[Dict[str, Any]]) -> Dict[str, Any]:
            decision: Dict[str, Any] = {
                "enabled": False,
                "reason": "disabled",
                "decode_backend": "",
                "breaker_key": None
            }
            if not enable_hw_decode:
                return decision
            if not profile:
                decision["reason"] = "cpu_profile"
                return decision
            if not normalized_video_codec:
                decision["reason"] = "unknown_codec"
                return decision
            if normalized_video_codec not in hw_decode_codec_whitelist:
                decision["reason"] = "codec_not_whitelisted"
                return decision

            backend = str(profile.get("hwaccel") or "").lower()
            decode_backend = _resolve_decode_backend(profile)
            decision["decode_backend"] = decode_backend

            if backend == "qsv":
                # QSV 编码时，若偏好原生解码则走 VAAPI 解码能力，否则走 QSV 解码能力
                decode_caps = vaapi_supported_codecs if prefer_native_hw_decoder else qsv_supported_codecs
            elif backend == "vaapi":
                decode_caps = vaapi_supported_codecs
            elif backend == "nvenc":
                decode_caps = cuda_supported_codecs
            else:
                decision["reason"] = "unknown_backend"
                return decision

            decode_caps = {_normalize_video_codec_name(codec) for codec in decode_caps}
            if normalized_video_codec not in decode_caps:
                decision["reason"] = "codec_not_supported_by_backend"
                return decision

            pix_fmt_lower = str(video_pix_fmt or "").lower()
            profile_lower = str(video_profile_name or "").lower()
            if normalized_video_codec == "h264":
                # H.264 的 4:2:2/4:4:4 与高位深在多数消费级硬解路径兼容性较差，强制回退软解。
                if (
                    (bit_depth is not None and bit_depth > 8)
                    or any(tag in pix_fmt_lower for tag in ["422", "444", "p10", "p12", "p16"])
                    or any(tag in profile_lower for tag in ["4:2:2", "4:4:4", "high 10", "high 4:2:2", "high 4:4:4"])
                ):
                    decision["reason"] = "h264_high_depth_or_chroma"
                    return decision

            if backend == "nvenc" and not bool(profile.get("supports_cuda_filters", False)):
                decision["reason"] = "nvenc_without_cuda_filters"
                return decision

            breaker_key = _build_hw_decode_breaker_key(
                decode_backend=decode_backend,
                codec=normalized_video_codec,
                pix_fmt=video_pix_fmt or None,
                bit_depth=bit_depth,
                video_profile=video_profile_name or None
            )
            decision["breaker_key"] = breaker_key
            if _is_hw_decode_breaker_active(breaker_key):
                decision["reason"] = "breaker_active"
                return decision

            decision["enabled"] = True
            decision["reason"] = "ok"
            return decision
        
        # 根据质量设置目标分辨率
        quality_map = {
            "1080p": (1920, 1080),
            "720p": (1280, 720),
            "480p": (854, 480),
            "360p": (640, 360)
        }
        
        if quality not in quality_map:
            quality = "720p"
        
        target_width, target_height = quality_map[quality]
        
        # 如果原视频分辨率已经小于目标分辨率，不转码
        interpolation_requested = (
            quality != "original"
            and intel_qsv_frame_interpolation_mode in {"30to60", "60to120"}
            and has_qsv_profile
        )
        if original_height <= target_height and safe_start <= 0.0 and not interpolation_requested:
            logger.info(f"原视频分辨率 {original_height}p 已小于目标 {target_height}p，跳过转码")
            request_range = request.headers.get("range") if request else None
            return _stream_file_with_range(file_path, request_range)
        
        # 构建 ffmpeg 命令的函数（支持回退到 CPU）
        def build_ffmpeg_cmd(profile: Optional[Dict[str, Any]], start_time: float = 0.0):
            cmd = ["ffmpeg", "-hide_banner"]
            cmd.extend(["-progress", "pipe:2"])
            cmd.extend(["-stats_period", "0.5"])

            if start_time and start_time > 0:
                cmd.extend(["-ss", f"{max(start_time, 0.0):.3f}"])
            
            current_hwaccel = profile.get("hwaccel") if profile else None
            current_encoder = profile.get("encoder") if profile else None
            supports_cuda_filters = bool(profile.get("supports_cuda_filters", False)) if profile else False
            nv_gpu_index = profile.get("gpu_index") if profile else None
            decode_decision = _evaluate_hw_decode(profile)
            use_hw_decode = bool(decode_decision.get("enabled"))
            decode_backend = str(decode_decision.get("decode_backend") or _resolve_decode_backend(profile))

            # 稳定性优先：当前环境下 VAAPI 硬解桥接到 QSV 编码易触发滤镜链不兼容
            # (Impossible to convert between formats / auto_scaler_0)。
            # 这里强制回退为软解 + QSV 编码，避免手动 QSV 频繁失败。
            if use_hw_decode and current_hwaccel == "qsv" and decode_backend == "vaapi":
                use_hw_decode = False
                decode_decision = dict(decode_decision or {})
                decode_decision["enabled"] = False
                decode_decision["reason"] = "qsv_vaapi_bridge_disabled"
                logger.info("QSV 编码禁用 VAAPI->QSV 硬解桥接，回退软解 + QSV 编码")
            if enable_hw_decode and profile and not use_hw_decode and normalized_video_codec:
                logger.info(
                    "硬解未启用，自动回退软解: backend=%s, decode_backend=%s, codec=%s, reason=%s",
                    current_hwaccel,
                    decode_backend,
                    normalized_video_codec,
                    decode_decision.get("reason")
                )

            if profile:
                cmd.extend(profile.get("init_args", []))
                if use_hw_decode and current_hwaccel == "qsv":
                    # 参考 Jellyfin：QSV 编码可优先走系统原生硬解路径（Linux 下通常是 VAAPI）
                    if decode_backend == "vaapi":
                        cmd.extend(["-hwaccel", "vaapi", "-hwaccel_output_format", "vaapi"])
                    else:
                        cmd.extend(["-hwaccel", "qsv", "-hwaccel_output_format", "qsv"])
                elif use_hw_decode and current_hwaccel == "vaapi":
                    cmd.extend(["-hwaccel", "vaapi", "-hwaccel_output_format", "vaapi"])
                elif use_hw_decode and current_hwaccel == "nvenc":
                    # 参考 Jellyfin 的成熟实践：N 卡优先使用 CUDA/NVDEC 解码
                    cmd.extend(["-hwaccel", "cuda", "-hwaccel_output_format", "cuda"])
                    if nv_gpu_index is not None:
                        cmd.extend(["-hwaccel_device", str(nv_gpu_index)])
            
            # 输入文件
            cmd.extend(["-i", file_path])
            # 显式映射第一路视频与音频，避免流索引错乱
            cmd.extend(["-map", "0:v:0"])
            # 音轨使用可选映射，避免探测误判导致整段被 -an 静音。
            cmd.extend(["-map", "0:a:0?"])
            
            # 视频编码参数
            video_encoder = _select_video_encoder(profile, target_video_codec)
            cmd.extend(["-c:v", video_encoder])
            qsv_interpolation_fps: Optional[int] = None
            
            # 添加分辨率缩放（优化：保持原始比例并强制偶数对齐，防止 QSV 绿条）
            if target_width and target_height:
                # 定位拉伸问题关键：width_expr 必须与 height_expr 保持同比例缩放
                # 如果 target_height 大于原片 ih，height_expr 会被 min() 限制在 ih，但 width_expr 之前未同步限制，导致横向拉伸。
                height_val_expr = f"min({target_height}\,ih)"
                width_expr = f"trunc(min({target_width}\,iw*({height_val_expr}/ih))/8)*8"
                height_expr = f"trunc({height_val_expr}/8)*8"
                can_use_qsv_interpolation = (
                    profile is not None
                    and str(current_hwaccel or "").lower() == "qsv"
                    and original_fps is not None
                    and target_height <= 1080
                )
                if can_use_qsv_interpolation and intel_qsv_frame_interpolation_mode == "30to60":
                    if 24.0 <= float(original_fps) <= 31.0:
                        qsv_interpolation_fps = 60
                elif can_use_qsv_interpolation and intel_qsv_frame_interpolation_mode == "60to120":
                    if 50.0 <= float(original_fps) <= 61.0:
                        qsv_interpolation_fps = 120
                qsv_interpolation_part = f":framerate={qsv_interpolation_fps}" if qsv_interpolation_fps else ""
                if qsv_interpolation_fps:
                    logger.info(
                        "启用 Intel QSV 硬件提帧: mode=%s, source_fps=%.3f, target_fps=%s, quality=%s",
                        intel_qsv_frame_interpolation_mode,
                        float(original_fps),
                        qsv_interpolation_fps,
                        quality
                    )

                if profile and current_hwaccel == "qsv":
                    if use_hw_decode:
                        # 全链路 QSV：使用 vpp_qsv 配合 32 像素对齐
                        # vpp_qsv 是全链路模式下唯一能正确处理 QSV Surface 的滤镜
                        # 配合 32 像素对齐可以完美解决画面绿条/错位问题
                        vfilter = (
                            f"vpp_qsv=w={width_expr}:h={height_expr}{qsv_interpolation_part}:format=nv12,setsar=1"
                        )
                        cmd.extend(["-vf", vfilter])
                    else:
                        # 混合模式
                        # 显式 format=nv12，避免 auto_scaler 在 QSV hwupload 前插入不支持转换。
                        vfilter = (
                            "format=nv12,hwupload=extra_hw_frames=64,"
                            f"vpp_qsv=w={width_expr}:h={height_expr}{qsv_interpolation_part}:format=nv12,setsar=1"
                        )
                        cmd.extend(["-vf", vfilter])
                elif profile and current_hwaccel == "vaapi":
                    if use_hw_decode:
                        # VAAPI 全链路
                        vfilter = f"scale_vaapi=w={width_expr}:h={height_expr},setsar=1"
                        cmd.extend(["-vf", vfilter])
                    else:
                        # 混合模式
                        vfilter = f"format=nv12,hwupload,scale_vaapi=w={width_expr}:h={height_expr},setsar=1"
                        cmd.extend(["-vf", vfilter])
                elif profile and current_hwaccel == "nvenc":
                    if supports_cuda_filters and use_hw_decode:
                        vfilter = f"scale_cuda=w={width_expr}:h={height_expr}:format=nv12,setsar=1"
                        cmd.extend(["-vf", vfilter])
                    elif supports_cuda_filters:
                        vfilter = f"format=nv12,hwupload_cuda,scale_cuda=w={width_expr}:h={height_expr}:format=nv12,setsar=1"
                        cmd.extend(["-vf", vfilter])
                    else:
                        # 无 CUDA 滤镜能力时，回退软滤镜 + NVENC 硬编
                        vfilter = f"scale={width_expr}:{height_expr},format=yuv420p"
                        cmd.extend(["-vf", vfilter])
                else:
                    # 纯软件路径
                    vfilter = f"scale={width_expr}:{height_expr},format=yuv420p"
                    cmd.extend(["-vf", vfilter])
            
            # 编码器特定参数
            if profile and current_hwaccel == "qsv" and video_encoder in {"h264_qsv", "hevc_qsv", "av1_qsv"}:
                # QSV 在不同 i915/libmfx 组合下 RC 兼容差异很大。
                # 默认采用 Jellyfin 风格 VBR 组合（质量/速度均衡较好），并保留兼容回退模式。
                # 注意：QSV + low_power 在部分平台会直接触发 “Selected ratecontrol mode is unsupported”，
                # 因此这里强制不附加 -low_power。
                qsv_bitrate_k_map = {
                    "1080p": 5000,
                    "720p": 2800,
                    "480p": 1600,
                    "360p": 1000
                }
                bitrate_k = int(qsv_bitrate_k_map.get(quality, 2800))
                if video_encoder == "h264_qsv":
                    bitrate_k = max(bitrate_k, 1000)

                cmd.extend(["-preset", "veryfast"])
                qsv_rc_mode = str(os.getenv("EASY_VDL_QSV_RC_MODE", "jellyfin_vbr")).strip().lower()
                if qsv_rc_mode in {"jellyfin_vbr", "vbr"}:
                    if video_encoder in {"h264_qsv", "hevc_qsv"}:
                        cmd.extend(["-mbbrc", "1"])
                    cmd.extend([
                        "-b:v", f"{bitrate_k}k",
                        "-maxrate", f"{bitrate_k + 1}k",
                        "-rc_init_occupancy", f"{bitrate_k * 2}k",
                        "-bufsize", f"{bitrate_k * 4}k"
                    ])
                else:
                    cmd.extend([
                        "-b:v", f"{bitrate_k}k",
                        "-maxrate", f"{bitrate_k}k",
                        "-bufsize", f"{bitrate_k * 2}k"
                    ])
            elif profile and current_hwaccel == "vaapi" and video_encoder in {"h264_vaapi", "hevc_vaapi", "av1_vaapi"}:
                cmd.extend(["-qp", "23", "-compression_level", "1"])
                if video_encoder == "h264_vaapi" and enable_intel_low_power_h264:
                    cmd.extend(["-low_power", "1"])
                if video_encoder == "hevc_vaapi" and enable_intel_low_power_hevc:
                    cmd.extend(["-low_power", "1"])
            elif profile and current_hwaccel == "nvenc" and video_encoder in {"h264_nvenc", "hevc_nvenc", "av1_nvenc"}:
                cmd.extend(["-cq", "23", "-preset", "p5", "-rc", "vbr"])
                if nv_gpu_index is not None:
                    cmd.extend(["-gpu", str(nv_gpu_index)])
            elif video_encoder == "libx265":
                cmd.extend(["-preset", "fast", "-crf", "28"])
            elif video_encoder == "libsvtav1":
                cmd.extend(["-crf", "30", "-preset", "8"])
            else:
                cmd.extend(["-preset", "fast", "-crf", "23"])
            
            # 音频和其他参数
            cmd.extend(["-c:a", "aac", "-b:a", "128k"])
            
            # 注意：流式输出到 stdout 时不能使用 faststart（需要随机访问）
            # 使用 frag_keyframe+empty_moov 来支持流式播放
            cmd.extend(["-movflags", "+frag_keyframe+empty_moov", "-f", "mp4", "-"])
            env_updates = profile.get("env_overrides", {}) if profile else {}
            interpolation_state = {
                "active": bool(qsv_interpolation_fps),
                "mode": (
                    intel_qsv_frame_interpolation_mode
                    if qsv_interpolation_fps and intel_qsv_frame_interpolation_mode in {"30to60", "60to120"}
                    else "off"
                ),
                "target_fps": qsv_interpolation_fps
            }
            return cmd, video_encoder, env_updates, decode_decision, interpolation_state

        def _qsv_breaker_key_for_profile(profile: Optional[Dict[str, Any]]) -> str:
            if not profile:
                return ""
            if str(profile.get("hwaccel") or "").lower() != "qsv":
                return ""
            encoder = _select_video_encoder(profile, target_video_codec)
            return _build_qsv_encoder_breaker_key(profile.get("profile_id"), encoder)
        
        # 构建尝试队列：硬件候选依次尝试，可按策略决定是否回退 CPU
        attempt_profiles: List[Optional[Dict[str, Any]]] = list(hw_profiles)
        if allow_fallback_to_cpu or not attempt_profiles:
            attempt_profiles.append(None)
        non_qsv = [
            p for p in attempt_profiles
            if not (p and str(p.get("hwaccel") or "").lower() == "qsv")
        ]
        qsv_profiles = [
            p for p in attempt_profiles
            if p and str(p.get("hwaccel") or "").lower() == "qsv"
        ]
        qsv_active = [
            p for p in qsv_profiles
            if _is_qsv_encoder_breaker_active(_qsv_breaker_key_for_profile(p))
        ]
        qsv_inactive = [p for p in qsv_profiles if p not in qsv_active]
        if qsv_active and (non_qsv or qsv_inactive):
            attempt_profiles = non_qsv + qsv_inactive + qsv_active
            logger.info(
                "QSV 编码熔断生效：%s 个组合已降级到尝试队列末尾",
                len(qsv_active)
            )
        logger.info(
            "转码策略生效: mode=%s, output_codec=%s(target=%s), hw_profiles=%s, attempt_order=%s, allow_fallback_to_cpu=%s",
            transcode_mode,
            configured_output_codec,
            target_video_codec,
            [p.get("profile_id") for p in hw_profiles],
            [p.get("profile_id") if p else "cpu" for p in attempt_profiles],
            allow_fallback_to_cpu
        )
        ffmpeg_cmd, initial_video_encoder, initial_env_updates, initial_decode_decision, initial_interpolation_state = build_ffmpeg_cmd(
            profile=attempt_profiles[0],
            start_time=safe_start
        )
        
        # 处理 Range 请求
        if range_header and start > 0:
            # 对于转码，Range 请求比较复杂，这里简化处理
            # 实际应用中可能需要分段转码
            pass
        
        async def generate():
            """异步生成转码后的视频流（支持硬件加速失败时多级回退）"""
            process = None
            attempt_index = 0
            current_profile = attempt_profiles[attempt_index]
            current_cmd = ffmpeg_cmd
            current_video_encoder = initial_video_encoder
            current_env_updates = initial_env_updates
            current_decode_decision = initial_decode_decision
            current_interpolation_state = initial_interpolation_state
            last_progress_fps: Optional[float] = None
            last_speed_multiple: Optional[float] = None
            current_frame_count: Optional[int] = None
            frame_at_last_measure: Optional[int] = None
            time_at_last_measure: Optional[float] = None
            owner_token = uuid.uuid4().hex

            def _current_hardware_tag() -> str:
                if current_profile:
                    return current_profile.get("hwaccel", "cpu")
                return "cpu"

            def _current_qsv_breaker_key() -> str:
                if not current_profile:
                    return ""
                if str(_current_hardware_tag()).lower() != "qsv":
                    return ""
                return _build_qsv_encoder_breaker_key(
                    current_profile.get("profile_id"),
                    current_video_encoder
                )

            def _push_transcode_update() -> None:
                effective_fps: Optional[float]
                if last_speed_multiple is not None and original_fps is not None:
                    effective_fps = last_speed_multiple * original_fps
                elif last_progress_fps is not None:
                    effective_fps = last_progress_fps
                else:
                    effective_fps = original_fps
                _set_last_transcoder(
                    _current_hardware_tag(),
                    current_video_encoder,
                    effective_fps,
                    last_speed_multiple,
                    vendor=(current_profile.get("vendor") if current_profile else None),
                    profile_id=(current_profile.get("profile_id") if current_profile else None),
                    gpu_index=(current_profile.get("gpu_index") if current_profile else None),
                    device=(current_profile.get("device") if current_profile else None),
                    frame_interpolation_active=bool(current_interpolation_state.get("active")),
                    frame_interpolation_mode=str(current_interpolation_state.get("mode") or "off"),
                    frame_interpolation_target_fps=current_interpolation_state.get("target_fps")
                )

            def _maybe_trip_hw_decode_breaker(stderr_text: str, output_chunks: int) -> None:
                if output_chunks != 0:
                    return
                if not bool(current_decode_decision.get("enabled")):
                    return
                breaker_key = str(current_decode_decision.get("breaker_key") or "")
                if not breaker_key:
                    return
                if not _looks_like_hw_decode_failure(stderr_text):
                    return
                _trip_hw_decode_breaker(
                    breaker_key,
                    reason=(
                        f"profile={current_profile.get('profile_id') if current_profile else 'cpu'}, "
                        f"hw={_current_hardware_tag()}, codec={normalized_video_codec or 'unknown'}"
                    )
                )

            def _maybe_trip_qsv_encoder_breaker(stderr_text: str, output_chunks: int) -> None:
                if output_chunks != 0:
                    return
                if str(_current_hardware_tag()).lower() != "qsv":
                    return
                if not _looks_like_qsv_encoder_unsupported(stderr_text):
                    return
                breaker_key = _current_qsv_breaker_key()
                _trip_qsv_encoder_breaker(
                    key=breaker_key,
                    reason=f"profile={current_profile.get('profile_id') if current_profile else 'cpu'}"
                )

            def _should_try_next_profile(output_chunks: int, stderr_text: str, max_out_time_seconds: float) -> bool:
                if attempt_index >= len(attempt_profiles) - 1:
                    return False
                if output_chunks == 0:
                    return True
                if output_chunks <= fallback_max_chunks and max_out_time_seconds <= fallback_max_out_time_seconds:
                    return True
                if (
                    _looks_like_hw_decode_failure(stderr_text)
                    and max_out_time_seconds <= max(fallback_max_out_time_seconds * 2, 12.0)
                ):
                    return True
                return False

            def _looks_like_expected_interrupt(return_code: int, stderr_text: str) -> bool:
                text = str(stderr_text or "").lower()
                if return_code in (-15, -9, 143):
                    return True
                if return_code == 255 and (
                    "received signal 15" in text
                    or "exiting normally" in text
                    or "immediate exit requested" in text
                ):
                    return True
                return False

            try:
                await _register_stream_ffmpeg_request(stream_ffmpeg_key, owner_token, safe_start)
                await _touch_stream_ffmpeg_session(stream_ffmpeg_key, owner_token, has_chunk=False)
                while True:
                    if not await _is_stream_ffmpeg_owner(stream_ffmpeg_key, owner_token):
                        logger.info(
                            "转码请求已被新请求替换，停止旧转码: key=%s, start=%.3f",
                            stream_ffmpeg_key,
                            safe_start
                        )
                        break

                    max_out_time_seconds: float = 0.0
                    last_progress_fps = None
                    last_speed_multiple = None
                    current_frame_count = None
                    frame_at_last_measure = None
                    time_at_last_measure = None
                    _push_transcode_update()

                    env = os.environ.copy()
                    env['LC_ALL'] = 'C.UTF-8'
                    env['LANG'] = 'C.UTF-8'
                    env.update(current_env_updates)

                    logger.info(
                        "开始转码: %s... (共%s个参数, attempt=%s/%s, profile=%s)",
                        ' '.join(current_cmd[:5]),
                        len(current_cmd),
                        attempt_index + 1,
                        len(attempt_profiles),
                        current_profile.get("profile_id") if current_profile else "cpu"
                    )

                    process = await asyncio.create_subprocess_exec(
                        *current_cmd,
                        stdout=asyncio.subprocess.PIPE,
                        stderr=asyncio.subprocess.PIPE,
                        env=env,
                        start_new_session=True
                    )
                    if not await _bind_stream_ffmpeg_process(stream_ffmpeg_key, owner_token, process):
                        logger.info(
                            "转码进程启动后发现请求已过期，终止进程: key=%s, pid=%s",
                            stream_ffmpeg_key,
                            getattr(process, "pid", "unknown")
                        )
                        await _terminate_subprocess_tree(process)
                        process = None
                        break

                    stderr_lines: List[str] = []
                    stderr_task: Optional[asyncio.Task] = None

                    async def read_stderr(proc):
                        nonlocal last_progress_fps, last_speed_multiple, current_frame_count, frame_at_last_measure, time_at_last_measure, max_out_time_seconds
                        try:
                            while True:
                                line = await proc.stderr.readline()
                                if not line:
                                    break
                                line_text = line.decode('utf-8', errors='ignore').strip()
                                if not line_text:
                                    continue
                                lower_line = line_text.lower()
                                if line_text.startswith('frame='):
                                    try:
                                        current_frame_count = int(line_text.split('=', 1)[1])
                                    except (ValueError, TypeError):
                                        current_frame_count = None
                                    continue
                                if line_text.startswith('out_time='):
                                    try:
                                        time_str = line_text.split('=', 1)[1]
                                        if time_str:
                                            h, m, s = time_str.split(':')
                                            current_time_seconds = int(h) * 3600 + int(m) * 60 + float(s)
                                            if current_time_seconds > max_out_time_seconds:
                                                max_out_time_seconds = current_time_seconds
                                            if (
                                                current_frame_count is not None
                                                and frame_at_last_measure is not None
                                                and time_at_last_measure is not None
                                            ):
                                                delta_frames = current_frame_count - frame_at_last_measure
                                                delta_time = current_time_seconds - time_at_last_measure
                                                if delta_frames >= 0 and delta_time > 0:
                                                    last_progress_fps = delta_frames / delta_time
                                                    _push_transcode_update()
                                            if current_frame_count is not None:
                                                frame_at_last_measure = current_frame_count
                                            time_at_last_measure = current_time_seconds
                                    except Exception:
                                        pass
                                    continue
                                if line_text.startswith('speed='):
                                    try:
                                        speed_value = line_text.split('=', 1)[1]
                                        if speed_value.upper() != 'N/A':
                                            if speed_value.endswith('x'):
                                                speed_value = speed_value[:-1]
                                            last_speed_multiple = float(speed_value)
                                            _push_transcode_update()
                                    except Exception:
                                        pass
                                    continue
                                if line_text.startswith('progress='):
                                    continue
                                stderr_lines.append(line_text)
                                if 'error' in lower_line or 'failed' in lower_line:
                                    if (
                                        "immediate exit requested" in lower_line
                                        or "error muxing a packet" in lower_line
                                        or "error closing file" in lower_line
                                        or "error writing trailer" in lower_line
                                        or "error closing progress log" in lower_line
                                    ):
                                        logger.info(f"ffmpeg stderr: {line_text[:200]}")
                                    else:
                                        logger.warning(f"ffmpeg stderr: {line_text[:200]}")
                        except Exception:
                            pass

                    stderr_task = asyncio.create_task(read_stderr(process))
                    chunk_count = 0
                    return_code = 0
                    try:
                        while True:
                            chunk = await process.stdout.read(8192)
                            if not chunk:
                                break
                            chunk_count += 1
                            await _touch_stream_ffmpeg_session(stream_ffmpeg_key, owner_token, has_chunk=True)
                            yield chunk
                    except (GeneratorExit, ConnectionError, BrokenPipeError, OSError) as e:
                        logger.info(f"客户端断开连接，终止转码进程: {str(e)}")
                        if process and process.returncode is None:
                            await _terminate_subprocess_tree(process)
                        if stderr_task and not stderr_task.done():
                            stderr_task.cancel()
                        raise
                    finally:
                        if process and process.returncode is None:
                            await _terminate_subprocess_tree(process)

                        if process is None:
                            return_code = 0
                        else:
                            return_code = await process.wait()
                        try:
                            if stderr_task:
                                await asyncio.wait_for(stderr_task, timeout=2)
                        except asyncio.TimeoutError:
                            if stderr_task:
                                stderr_task.cancel()
                        process = None

                    if not await _is_stream_ffmpeg_owner(stream_ffmpeg_key, owner_token):
                        logger.info(
                            "转码请求执行期间被新请求替换，停止回退链路: key=%s, start=%.3f",
                            stream_ffmpeg_key,
                            safe_start
                        )
                        break
                    await _touch_stream_ffmpeg_session(stream_ffmpeg_key, owner_token, has_chunk=False)

                    if return_code == 0:
                        if attempt_index == 0:
                            logger.info(f"转码完成: 共传输 {chunk_count} 个数据块")
                        else:
                            logger.info(f"回退方案转码完成: 共传输 {chunk_count} 个数据块")
                        _push_transcode_update()
                        break

                    stderr_text = '\n'.join(stderr_lines[-10:])
                    if _looks_like_expected_interrupt(return_code, stderr_text):
                        logger.info(
                            "ffmpeg 转码被中断（通常为切换播放/新请求抢占）: return_code=%s, chunks=%s",
                            return_code,
                            chunk_count
                        )
                        break

                    logger.error(f"ffmpeg 转码失败 (返回码: {return_code}): {stderr_text[:500]}")
                    _maybe_trip_hw_decode_breaker(stderr_text, chunk_count)
                    _maybe_trip_qsv_encoder_breaker(stderr_text, chunk_count)

                    if not _should_try_next_profile(chunk_count, stderr_text, max_out_time_seconds):
                        raise Exception(f"ffmpeg 转码失败 (返回码: {return_code})")

                    current_hw = _current_hardware_tag()
                    logger.warning(
                        "转码方案失败 (%s)，尝试回退到下一方案: chunks=%s, out_time=%.3fs",
                        current_hw,
                        chunk_count,
                        max_out_time_seconds
                    )
                    failed_hw = str(_current_hardware_tag() or "").lower()
                    next_index = attempt_index + 1
                    for idx in range(attempt_index + 1, len(attempt_profiles)):
                        cand = attempt_profiles[idx]
                        cand_hw = str(cand.get("hwaccel") if cand else "cpu").lower()
                        if cand_hw != failed_hw:
                            next_index = idx
                            break
                    if next_index <= attempt_index or next_index >= len(attempt_profiles):
                        raise Exception(f"ffmpeg 转码失败 (返回码: {return_code})")

                    attempt_index = next_index
                    current_profile = attempt_profiles[attempt_index]
                    current_cmd, current_video_encoder, current_env_updates, current_decode_decision, current_interpolation_state = build_ffmpeg_cmd(
                        profile=current_profile,
                        start_time=safe_start
                    )
                    next_hw = _current_hardware_tag()
                    logger.info(
                        "切换转码方案: %s，命令前缀: %s... (attempt=%s/%s)",
                        next_hw,
                        ' '.join(current_cmd[:5]),
                        attempt_index + 1,
                        len(attempt_profiles)
                    )
            except Exception as e:
                error_msg = str(e)
                logger.error(f"转码过程出错: {error_msg}")
                if process and process.returncode is None:
                    await _terminate_subprocess_tree(process, term_timeout=5.0, kill_timeout=2.0)
                raise
            finally:
                if process and process.returncode is None:
                    await _terminate_subprocess_tree(process)
                await _unregister_stream_ffmpeg_request(stream_ffmpeg_key, owner_token)
        
        # 安全地处理文件名（用于 Content-Disposition header）
        safe_filename = os.path.basename(decoded_filename)
        # 创建 ASCII 安全的 fallback 文件名
        fallback_filename = safe_filename.encode('ascii', 'ignore').decode() or 'video.mp4'
        # 对文件名进行 URL 编码以支持中文
        encoded_filename = urllib.parse.quote(safe_filename, safe='')
        
        # 构建 Content-Disposition header，确保完全 ASCII 安全
        # 只使用 filename* 参数，避免 latin-1 编码问题
        # 使用 ASCII 安全的字符串构建，确保所有字符都是 ASCII
        try:
            # 确保 content_disposition 字符串完全 ASCII 安全
            content_disposition = f'inline; filename="{fallback_filename}"; filename*=UTF-8\'\'{encoded_filename}'
            # 验证字符串是否完全 ASCII
            content_disposition.encode('ascii')
        except UnicodeEncodeError:
            # 如果包含非 ASCII 字符，只使用 filename*
            content_disposition = f'inline; filename*=UTF-8\'\'{encoded_filename}'
        
        # 创建响应对象，手动设置 header 以避免编码问题
        response = StreamingResponse(
            generate(),
            media_type="video/mp4"
        )
        response.headers["Accept-Ranges"] = "bytes"
        response.headers["Content-Disposition"] = content_disposition
        response.headers["Cache-Control"] = "no-cache"
        response.headers["X-Video-Start"] = f"{safe_start:.3f}"
        
        return response
        
    except HTTPException:
        raise
    except UnicodeEncodeError as e:
        # 专门处理编码错误
        logger.error(f"转码播放编码错误: {str(e)}")
        logger.error(f"错误位置: filename={filename}, decoded={decoded_filename if 'decoded_filename' in locals() else 'N/A'}")
        raise HTTPException(status_code=500, detail="转码播放失败: 文件名编码错误")
    except Exception as e:
        error_msg = str(e)
        # 确保错误消息是 ASCII 安全的，避免编码问题
        safe_error_msg = error_msg.encode('ascii', 'ignore').decode() or '转码播放失败'
        logger.error(f"转码播放失败: {error_msg}")
        import traceback
        logger.error(f"错误堆栈: {traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=safe_error_msg)


@router.get("/api/video/encoder")
async def get_video_encoder(current_user: User = Depends(get_current_user)):
    """
    获取最近一次成功转码使用的编解码方式，用于前端展示。
    """
    return _get_last_transcoder()


# 播放记录相关API
@router.get("/api/playback/record/{subscription_id}", response_model=models.PlaybackRecordResponse)
def get_playback_record(
    subscription_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """获取播放记录"""
    try:
        record = db.query(models.PlaybackRecord).filter(
            models.PlaybackRecord.subscription_id == subscription_id
        ).first()
        
        if not record:
            # 如果不存在，返回默认记录
            return {
                "subscription_id": subscription_id,
                "current_index": 0,
                "playback_mode": "asc",
                "video_progress": {},
                "last_updated": datetime.now(timezone(timedelta(hours=8)))
            }
        
        # 解析 video_progress JSON
        video_progress = {}
        if record.video_progress:
            try:
                video_progress = json.loads(record.video_progress)
            except:
                video_progress = {}
        
        return {
            "subscription_id": record.subscription_id,
            "current_index": record.current_index,
            "playback_mode": record.playback_mode,
            "video_progress": video_progress,
            "last_updated": record.last_updated
        }
    except Exception as e:
        logger.error(f"获取播放记录失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"获取播放记录失败: {str(e)}")


@router.post("/api/playback/record", response_model=models.PlaybackRecordResponse)
def create_playback_record(
    record: models.PlaybackRecordCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """创建播放记录"""
    try:
        # 检查是否已存在
        existing = db.query(models.PlaybackRecord).filter(
            models.PlaybackRecord.subscription_id == record.subscription_id
        ).first()
        
        if existing:
            raise HTTPException(status_code=400, detail="播放记录已存在，请使用更新接口")
        
        # 创建新记录
        new_record = models.PlaybackRecord(
            subscription_id=record.subscription_id,
            current_index=record.current_index,
            playback_mode=record.playback_mode,
            video_progress=json.dumps(record.video_progress or {}),
            last_updated=datetime.now(timezone(timedelta(hours=8)))
        )
        
        db.add(new_record)
        db.commit()
        db.refresh(new_record)
        
        video_progress = {}
        if new_record.video_progress:
            try:
                video_progress = json.loads(new_record.video_progress)
            except:
                video_progress = {}
        
        return {
            "subscription_id": new_record.subscription_id,
            "current_index": new_record.current_index,
            "playback_mode": new_record.playback_mode,
            "video_progress": video_progress,
            "last_updated": new_record.last_updated
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"创建播放记录失败: {str(e)}")
        db.rollback()
        raise HTTPException(status_code=500, detail=f"创建播放记录失败: {str(e)}")


@router.put("/api/playback/record/{subscription_id}", response_model=models.PlaybackRecordResponse)
def update_playback_record(
    subscription_id: str,
    record_update: models.PlaybackRecordUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """更新播放记录"""
    try:
        record = db.query(models.PlaybackRecord).filter(
            models.PlaybackRecord.subscription_id == subscription_id
        ).first()
        
        if not record:
            # 如果不存在，创建新记录
            record = models.PlaybackRecord(
                subscription_id=subscription_id,
                current_index=record_update.current_index or 0,
                playback_mode=record_update.playback_mode or "asc",
                video_progress=json.dumps(record_update.video_progress or {}),
                last_updated=datetime.now(timezone(timedelta(hours=8)))
            )
            db.add(record)
        else:
            # 更新现有记录
            if record_update.current_index is not None:
                record.current_index = record_update.current_index
            if record_update.playback_mode is not None:
                record.playback_mode = record_update.playback_mode
            if record_update.video_progress is not None:
                # 合并现有的进度和新进度
                existing_progress = {}
                if record.video_progress:
                    try:
                        existing_progress = json.loads(record.video_progress)
                    except:
                        existing_progress = {}
                existing_progress.update(record_update.video_progress)
                record.video_progress = json.dumps(existing_progress)
            record.last_updated = datetime.now(timezone(timedelta(hours=8)))
        
        db.commit()
        db.refresh(record)
        
        video_progress = {}
        if record.video_progress:
            try:
                video_progress = json.loads(record.video_progress)
            except:
                video_progress = {}
        
        return {
            "subscription_id": record.subscription_id,
            "current_index": record.current_index,
            "playback_mode": record.playback_mode,
            "video_progress": video_progress,
            "last_updated": record.last_updated
        }
    except Exception as e:
        logger.error(f"更新播放记录失败: {str(e)}")
        db.rollback()
        raise HTTPException(status_code=500, detail=f"更新播放记录失败: {str(e)}")
