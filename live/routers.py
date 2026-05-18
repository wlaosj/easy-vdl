# -*- coding: utf-8 -*-
"""
直播录制API路由
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import or_, and_, func
from sqlalchemy.orm import Session
from datetime import datetime, timedelta
from typing import Optional, List
import uuid
import os
import logging
import json
import asyncio
import time
import httpx
from pathlib import Path
from pydantic import BaseModel, Field
from urllib.parse import urlsplit

from routers.auth import require_license_api, get_current_user_or_token
from sql.database_postgresql import get_session
from sql.models import LiveSubscription, LiveRecord, User
from .recorder import live_recorder
from .scheduler import live_scheduler
from . import adapters 

logger = logging.getLogger(__name__)

router = APIRouter()

MAX_BATCH_ADD_SUBSCRIPTIONS = 300
BATCH_ADD_CONCURRENCY = 5
ROOM_INFO_TIMEOUT_SECONDS = 12


def _apply_transcode_success_to_record(rec: LiveRecord, mp4_path: str) -> None:
    """Keep record paths coherent after TS -> MP4 conversion."""
    if not rec or not mp4_path:
        return
    rec.converted = "true"
    rec.converted_path = mp4_path
    rec.converted_format = "mp4"
    rec.file_path = mp4_path
    rec.format = "mp4"
    if os.path.exists(mp4_path):
        rec.file_size = os.path.getsize(mp4_path)


class LiveBatchAddItem(BaseModel):
    room_url: str = Field(..., description="直播间链接")
    platform: Optional[str] = Field(None, description="平台（可选，默认自动识别）")
    quality: Optional[str] = Field(None, description="画质")
    auto_record: Optional[bool] = Field(None, description="开播自动录制")
    monitor_enabled: Optional[bool] = Field(None, description="周期检测")
    check_interval: Optional[int] = Field(None, description="检测间隔（秒）")
    notification_enabled: Optional[bool] = Field(None, description="开播/录制通知")
    danmu_enabled: Optional[bool] = Field(None, description="录制弹幕（可选）")


class LiveBatchAddRequest(BaseModel):
    subscriptions: List[LiveBatchAddItem] = Field(default_factory=list)

def _normalize_room_url(raw_url: Optional[str]) -> str:
    """最小化规范化：去空白、去尖括号、去末尾斜杠（避免误杀短链参数）"""
    if not raw_url:
        return ""
    url = str(raw_url).strip()
    if url.startswith("<") and url.endswith(">") and len(url) > 2:
        url = url[1:-1].strip()
    # 仅去掉末尾斜杠（避免影响短链/参数）
    if url.endswith("/") and len(url) > 1:
        url = url.rstrip("/")
    return url


def _resolve_record_end_time(record: LiveRecord) -> Optional[datetime]:
    """推导录制记录结束时间：优先 end_time，其次 start_time + duration；录制中用当前时间。"""
    if record.end_time:
        return record.end_time
    if str(record.status or "").lower() == "recording" and record.start_time:
        # 录制中的时间轴片段使用当前时间作为动态结束时间
        if record.start_time.tzinfo is not None and record.start_time.tzinfo.utcoffset(record.start_time) is not None:
            return datetime.now(record.start_time.tzinfo)
        return datetime.now()
    if record.start_time and record.duration and record.duration > 0:
        return record.start_time + timedelta(seconds=int(record.duration))
    return record.start_time


def _resolve_record_playable_path(record: LiveRecord) -> tuple[Optional[str], Optional[str]]:
    """返回可播放路径与格式（时间轴当前支持 mp4/ts）。优先校验文件存在性。"""
    converted_path = (record.converted_path or "").strip() if record.converted_path else ""
    original_path = (record.file_path or "").strip() if record.file_path else ""
    original_format = (record.format or "").lower() if record.format else ""

    # 构建候选路径列表：(路径, 格式, 是否必须存在)
    candidates = []

    if record.converted == "true" and converted_path and converted_path.lower().endswith(".mp4"):
        candidates.append((converted_path, "mp4"))

    if original_path:
        is_mp4 = original_format == "mp4" or original_path.lower().endswith(".mp4")
        is_ts = original_format == "ts" or original_path.lower().endswith(".ts")
        if is_mp4:
            candidates.append((original_path, "mp4"))
        elif is_ts:
            candidates.append((original_path, "ts"))

    # 转码后但文件不存在的降级：尝试对应路径的另一格式
    if converted_path and original_path:
        # converted 路径不可达 → 尝试原始 TS
        if record.converted == "true" and not os.path.exists(converted_path):
            if original_path.lower().endswith(".ts") and os.path.exists(original_path):
                candidates.insert(0, (original_path, "ts"))
        # 原始 TS 不可达 → 尝试同级目录下的 MP4
        if original_path.lower().endswith(".ts") and not os.path.exists(original_path):
            mp4_fallback = original_path.rsplit('.', 1)[0] + '.mp4'
            if os.path.exists(mp4_fallback):
                candidates.insert(0, (mp4_fallback, "mp4"))

    for path, fmt in candidates:
        if os.path.exists(path):
            return path, fmt

    return None, None


def _align_datetime_pair(left: datetime, right: datetime) -> tuple[datetime, datetime]:
    """
    对齐两个 datetime 的时区语义，避免 aware/naive 直接比较时报错。
    规则：
    - 两者同为 aware 或同为 naive：原样返回
    - 一个 aware 一个 naive：将 naive 视作与 aware 同时区
    """
    left_aware = left.tzinfo is not None and left.tzinfo.utcoffset(left) is not None
    right_aware = right.tzinfo is not None and right.tzinfo.utcoffset(right) is not None
    if left_aware == right_aware:
        return left, right
    if left_aware and not right_aware:
        return left, right.replace(tzinfo=left.tzinfo)
    return left.replace(tzinfo=right.tzinfo), right


def _resolve_danmu_path(file_path: Optional[str]) -> Optional[str]:
    if not file_path:
        return None
    path = str(file_path)
    if path.endswith(".danmu.jsonl"):
        return path
    if "." in path:
        base = path.rsplit(".", 1)[0]
    else:
        base = path
    return f"{base}.danmu.jsonl"


def _resolve_danmu_index_path(danmu_path: str) -> str:
    if danmu_path.endswith(".danmu.idx.jsonl"):
        return danmu_path
    if danmu_path.endswith(".danmu.jsonl"):
        base = danmu_path[:-len(".danmu.jsonl")]
        return f"{base}.danmu.idx.jsonl"
    base = danmu_path.rsplit(".", 1)[0]
    return f"{base}.danmu.idx.jsonl"


def _resolve_highlights_record_id(file_path: str) -> str:
    stem = Path(file_path).stem
    parts = stem.rsplit("_", 1)
    if len(parts) == 2 and parts[1]:
        return parts[1]
    return stem


def _resolve_highlights_artifact_dir(file_path: str) -> str:
    video_path = Path(file_path)
    record_id = _resolve_highlights_record_id(file_path)
    return str(video_path.parent / "_highlights" / record_id)


def _resolve_manual_clip_dir(file_path: str) -> str:
    video_path = Path(file_path)
    record_id = _resolve_highlights_record_id(file_path)
    return str(video_path.parent / "_manual_clips" / record_id)


def _resolve_highlights_analysis_path(file_path: str) -> str:
    return str(Path(_resolve_highlights_artifact_dir(file_path)) / "highlights.v1.json")


def _resolve_highlights_task_status_path(file_path: str) -> str:
    return str(Path(_resolve_highlights_artifact_dir(file_path)) / "task_status.v1.json")


def _normalize_highlights_task_status(raw: Optional[str]) -> str:
    status = str(raw or "").strip().lower()
    if not status:
        return "none"
    if status in {"queued", "running", "success", "failed"}:
        return status
    return "failed"


def _load_highlights_task_status(file_path: str) -> Optional[dict]:
    task_path = _resolve_highlights_task_status_path(file_path)
    if not os.path.exists(task_path):
        return None
    try:
        with open(task_path, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:
        return None


def _resolve_highlights_state(file_path: Optional[str], converted_path: Optional[str]) -> dict:
    """解析某条录制记录的高光分析状态，供录制列表快速标记。"""
    candidates: List[str] = []
    for p in (file_path, converted_path):
        if not p:
            continue
        pp = str(p).strip()
        if pp and pp not in candidates:
            candidates.append(pp)

    # 只要任一路径已有分析结果文件，就视为“已分析”
    for base_path in candidates:
        try:
            if os.path.exists(_resolve_highlights_analysis_path(base_path)):
                return {
                    "has_highlights_analysis": True,
                    "highlights_status": "success",
                }
        except Exception:
            continue

    # 没有结果文件时，回退读取任务状态（分析中/失败/成功）
    latest_mtime = 0.0
    latest_status = "none"
    for base_path in candidates:
        try:
            task_path = _resolve_highlights_task_status_path(base_path)
            if not os.path.exists(task_path):
                continue
            mtime = os.path.getmtime(task_path)
            task = _load_highlights_task_status(base_path) or {}
            status = _normalize_highlights_task_status(str(task.get("status") or ""))
            if mtime >= latest_mtime:
                latest_mtime = mtime
                latest_status = status or "none"
        except Exception:
            continue

    if latest_status == "success":
        return {
            "has_highlights_analysis": True,
            "highlights_status": "success",
        }
    if latest_status in {"running", "queued"}:
        return {
            "has_highlights_analysis": False,
            "highlights_status": "running",
        }
    if latest_status == "failed":
        return {
            "has_highlights_analysis": False,
            "highlights_status": "failed",
        }
    return {
        "has_highlights_analysis": False,
        "highlights_status": "none",
    }


def _resolve_manual_clips_state(file_path: Optional[str], converted_path: Optional[str]) -> dict:
    """解析某条录制记录的手动切片状态，供录制列表快速标记。"""
    candidates: List[str] = []
    for p in (file_path, converted_path):
        if not p:
            continue
        pp = str(p).strip()
        if pp and pp not in candidates:
            candidates.append(pp)

    clip_count = 0
    seen_dirs = set()
    for base_path in candidates:
        try:
            clip_dir = Path(_resolve_manual_clip_dir(base_path))
            real_dir = str(clip_dir.resolve())
            if real_dir in seen_dirs:
                continue
            seen_dirs.add(real_dir)
            if not clip_dir.exists() or not clip_dir.is_dir():
                continue
            for item in clip_dir.iterdir():
                if item.is_file() and item.suffix.lower() in {".mp4", ".mkv", ".mov"}:
                    clip_count += 1
        except Exception:
            continue

    return {
        "has_manual_clips": clip_count > 0,
        "manual_clip_count": clip_count,
    }


def _find_danmu_seek_offset(idx_path: str, start_ts: float) -> int:
    if not idx_path or not os.path.exists(idx_path):
        return 0
    offset = 0
    try:
        with open(idx_path, "r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    item = json.loads(line)
                except Exception:
                    continue
                minute_ts = item.get("minute_ts")
                if minute_ts is None:
                    continue
                if float(minute_ts) <= start_ts:
                    offset = int(item.get("offset", 0))
                else:
                    break
    except Exception:
        return 0
    return max(0, offset)


def _read_danmu_range(danmu_path: str, start_ts: float, end_ts: float, limit: int = 2000) -> List[dict]:
    if not danmu_path or not os.path.exists(danmu_path):
        return []
    idx_path = _resolve_danmu_index_path(danmu_path)
    offset = _find_danmu_seek_offset(idx_path, start_ts)
    results = []
    try:
        with open(danmu_path, "r", encoding="utf-8") as fh:
            if offset > 0:
                try:
                    fh.seek(offset)
                except Exception:
                    pass
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    item = json.loads(line)
                except Exception:
                    continue
                ts = item.get("ts")
                if ts is None:
                    continue
                try:
                    ts_val = float(ts)
                except Exception:
                    continue
                if ts_val < start_ts:
                    continue
                if ts_val > end_ts:
                    break
                results.append(item)
                if len(results) >= limit:
                    break
    except Exception:
        return results
    return results


# ==================== 订阅管理 ====================

def _parse_bool(value: Optional[object], default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).lower() in ('true', '1', 'yes', 'on')


async def _create_live_subscription(
    *,
    room_url: str,
    platform: str,
    quality: str,
    auto_record_bool: bool,
    monitor_enabled_bool: bool,
    check_interval: int,
    notification_enabled_bool: bool,
    danmu_enabled_bool: bool,
    db: Session
):
    logger.info(f"收到添加直播间订阅请求: room_url={room_url}, platform={platform}")

    # 1. 优先尝试根据 URL 自动识别适配器
    # 前端可能会传入默认值(如 'douyin')，导致平台误判，所以优先信任 URL 匹配结果
    adapter = adapters.get_adapter(room_url)

    if adapter:
        if platform != adapter.platform_name:
            logger.info(f"根据URL自动修正平台: {platform} -> {adapter.platform_name}")
            platform = adapter.platform_name
    else:
        # 2. 如果无法识别，尝试使用参数指定的平台
        adapter = adapters.get_adapter_by_platform(platform)

        # 3. 再次检查：如果是默认值 douyin 但 URL 包含其他特征 (兜底逻辑)
        if adapter and adapter.platform_name == 'douyin':
            if 'bilibili.com' in room_url:
                bili_adapter = adapters.get_adapter_by_platform('bilibili')
                if bili_adapter:
                    adapter = bili_adapter
                    platform = 'bilibili'

    if not adapter:
        raise HTTPException(status_code=400, detail=f"不支持的平台: {platform} 或 无法识别的URL")

    # 2. 验证检测间隔
    if check_interval < 10 or check_interval > 600:
        raise HTTPException(status_code=400, detail="检测间隔必须在10-600秒之间")

    # 3. 检查是否已存在 (使用 room_url)
    existing = db.query(LiveSubscription).filter(
        LiveSubscription.platform == platform,
        LiveSubscription.room_url == room_url
    ).first()

    if existing:
        return {
            "success": False,
            "message": "该直播间已订阅",
            "data": {"id": existing.id, "anchor_name": existing.anchor_name}
        }

    logger.info(f"使用适配器 [{platform}] 获取直播间信息")

    # 4. 获取直播间信息 (统一接口调用)
    try:
        info = await asyncio.wait_for(
            adapter.get_room_info(room_url),
            timeout=ROOM_INFO_TIMEOUT_SECONDS
        )
    except asyncio.TimeoutError:
        raise HTTPException(status_code=400, detail="获取直播间信息超时，请稍后重试")
    except Exception as e:
        logger.error(f"获取直播间信息失败: {e}", exc_info=True)
        raise HTTPException(status_code=400, detail=f"获取直播间信息失败: {str(e)}")

    anchor_name = info['anchor_name']
    room_id = info['room_id']
    avatar_url = info['avatar_url']
    is_live = info['is_live']

    # 5. 校验提取结果 (参考旧版 logic)
    if not anchor_name and not room_id:
        logger.warning(f"无法获取直播间有效信息，取消订阅创建: {room_url}")
        return {
            "success": False,
            "message": "无法获取直播间有效信息（主播名和房间ID均为空），请检查链接是否正确或主播是否已激活直播功能",
            "data": None
        }

    # 6. 再次检查 room_id 是否已存在 (防止同一主播不同链接)
    if room_id:
        existing_by_id = db.query(LiveSubscription).filter(
            LiveSubscription.platform == platform,
            LiveSubscription.room_id == room_id
        ).first()
        if existing_by_id:
            return {
                "success": False,
                "message": "该直播间已订阅 (相同 room_id)",
                "data": {"id": existing_by_id.id, "anchor_name": existing_by_id.anchor_name}
            }

    # 7. 创建订阅
    subscription = LiveSubscription(
        id=str(uuid.uuid4()),
        platform=platform,
        room_url=room_url,
        room_id=room_id,
        anchor_name=anchor_name,
        avatar_url=avatar_url,
        quality=quality,
        auto_record="true" if auto_record_bool else "false",
        monitor_enabled="true" if monitor_enabled_bool else "false",
        check_interval=check_interval,
        notification_enabled="true" if notification_enabled_bool else "false",
        is_live="true" if is_live else "false",
        is_recording="false",
        extra_data=json.dumps({
            "danmu_enabled": bool(danmu_enabled_bool),
        }),
        created_at=datetime.now(),
        updated_at=datetime.now()
    )

    db.add(subscription)
    db.commit()
    db.refresh(subscription)

    # 添加监控调度，用于检测状态和发送通知；允许保留订阅但暂停周期检测。
    if monitor_enabled_bool:
        await live_scheduler.add_monitor(
            subscription.id,
            room_url,
            platform,
            check_interval
        )

    immediate_started = False
    if monitor_enabled_bool and auto_record_bool:
        try:
            immediate_started = await live_scheduler.trigger_immediate_check(subscription.id)
        except Exception as immediate_err:
            logger.warning(
                f"新增订阅后立即检查失败（将由常规轮询继续接管）: {subscription.id}, {immediate_err}"
            )

    return {
        "success": True,
        "message": f"订阅添加成功: {anchor_name or '未知主播'}",
        "data": {
            "id": subscription.id,
            "anchor_name": anchor_name,
            "room_id": room_id,
            "is_live": is_live,
            "monitor_enabled": subscription.monitor_enabled,
            "immediate_checked": auto_record_bool,
            "immediate_started": immediate_started
        }
    }

@router.get("/subscriptions")
@require_license_api
async def get_live_subscriptions(
    platform: Optional[str] = None,
    current_user: User = Depends(get_current_user_or_token),
    db: Session = Depends(get_session)
):
    """获取所有直播订阅"""
    query = db.query(LiveSubscription)
    
    if platform:
        query = query.filter(LiveSubscription.platform == platform)
    
    subscriptions = query.order_by(LiveSubscription.created_at.desc()).all()
    
    # 添加实时录制状态
    result = []
    for sub in subscriptions:
        sub_dict = {
            "id": sub.id,
            "platform": sub.platform,
            "room_url": sub.room_url,
            "room_id": sub.room_id,
            "anchor_name": sub.anchor_name,
            "avatar_url": sub.avatar_url,
            "quality": sub.quality,
            "auto_record": sub.auto_record,
            "monitor_enabled": getattr(sub, "monitor_enabled", None) or "true",
            "check_interval": sub.check_interval,
            "is_live": sub.is_live,
            "is_recording": "true" if live_recorder.is_recording(sub.id) else "false",
            "last_check_time": sub.last_check_time.isoformat() if sub.last_check_time else None,
            "last_live_time": sub.last_live_time.isoformat() if sub.last_live_time else None,
            "notification_enabled": sub.notification_enabled,
            "created_at": sub.created_at.isoformat() if sub.created_at else None,
        }
        
        # 如果正在录制,添加录制状态
        recording_status = live_recorder.get_recording_status(sub.id)
        if recording_status:
            sub_dict["recording_status"] = recording_status
        
        result.append(sub_dict)
    
    return {"success": True, "data": result}


@router.post("/subscriptions")
@require_license_api
async def add_live_subscription(
    room_url: str = Query(...),
    platform: str = Query("douyin"),
    quality: str = Query("原画"),
    auto_record: str = Query("false"),
    monitor_enabled: str = Query("true"),
    check_interval: int = Query(60),
    notification_enabled: str = Query("true"),
    danmu_enabled: str = Query("false"),
    current_user: User = Depends(get_current_user_or_token),
    db: Session = Depends(get_session)
):
    """添加直播间订阅"""
    # 转换布尔值字符串
    auto_record_bool = _parse_bool(auto_record, False)
    monitor_enabled_bool = _parse_bool(monitor_enabled, True)
    notification_enabled_bool = _parse_bool(notification_enabled, True)
    danmu_enabled_bool = _parse_bool(danmu_enabled, False)

    try:
        return await _create_live_subscription(
            room_url=room_url,
            platform=platform,
            quality=quality,
            auto_record_bool=auto_record_bool,
            monitor_enabled_bool=monitor_enabled_bool,
            check_interval=check_interval,
            notification_enabled_bool=notification_enabled_bool,
            danmu_enabled_bool=danmu_enabled_bool,
            db=db
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"添加订阅异常: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"系统错误: {str(e)}")


@router.post("/subscriptions/batch")
@require_license_api
async def batch_add_live_subscriptions(
    payload: LiveBatchAddRequest,
    current_user: User = Depends(get_current_user_or_token),
    db: Session = Depends(get_session)
):
    """批量添加直播间订阅"""
    subscriptions = payload.subscriptions or []
    if not subscriptions:
        raise HTTPException(status_code=400, detail="未提供有效的订阅列表")
    if len(subscriptions) > MAX_BATCH_ADD_SUBSCRIPTIONS:
        raise HTTPException(
            status_code=400,
            detail=f"批量添加一次最多支持 {MAX_BATCH_ADD_SUBSCRIPTIONS} 条"
        )

    success_items = []
    error_items = []
    seen_urls = set()
    valid_items = []

    for index, item in enumerate(subscriptions):
        room_url = _normalize_room_url(item.room_url)
        if not room_url:
            error_items.append({
                "index": index,
                "room_url": item.room_url,
                "message": "直播间链接不能为空"
            })
            continue

        if room_url in seen_urls:
            error_items.append({
                "index": index,
                "room_url": room_url,
                "message": "批量请求内重复链接，已跳过"
            })
            continue
        seen_urls.add(room_url)

        valid_items.append((index, item, room_url))

    async def process_item(index: int, item: LiveBatchAddItem, room_url: str):
        platform = (item.platform or "douyin").strip() if item.platform else "douyin"
        quality = (item.quality or "原画").strip() if item.quality else "原画"
        auto_record_bool = _parse_bool(item.auto_record, False)
        monitor_enabled_bool = _parse_bool(item.monitor_enabled, True)
        notification_enabled_bool = _parse_bool(item.notification_enabled, True)
        danmu_enabled_bool = _parse_bool(item.danmu_enabled, False)
        check_interval = item.check_interval if item.check_interval is not None else 60

        db_local = get_session()
        try:
            result = await _create_live_subscription(
                room_url=room_url,
                platform=platform,
                quality=quality,
                auto_record_bool=auto_record_bool,
                monitor_enabled_bool=monitor_enabled_bool,
                check_interval=check_interval,
                notification_enabled_bool=notification_enabled_bool,
                danmu_enabled_bool=danmu_enabled_bool,
                db=db_local
            )
            if result.get("success"):
                success_items.append({
                    "index": index,
                    "room_url": room_url,
                    "message": result.get("message"),
                    "data": result.get("data")
                })
            else:
                error_items.append({
                    "index": index,
                    "room_url": room_url,
                    "message": result.get("message") or "添加失败"
                })
        except HTTPException as e:
            error_items.append({
                "index": index,
                "room_url": room_url,
                "message": str(e.detail)
            })
        except Exception as e:
            logger.error(f"批量添加订阅异常: {room_url}, {e}", exc_info=True)
            error_items.append({
                "index": index,
                "room_url": room_url,
                "message": f"系统错误: {str(e)}"
            })
        finally:
            try:
                db_local.close()
            except Exception:
                pass

    queue = asyncio.Queue()
    for item in valid_items:
        queue.put_nowait(item)

    async def worker():
        while True:
            try:
                index, item, room_url = queue.get_nowait()
            except asyncio.QueueEmpty:
                return
            try:
                await process_item(index, item, room_url)
            finally:
                queue.task_done()

    worker_count = min(BATCH_ADD_CONCURRENCY, len(valid_items)) if valid_items else 0
    if worker_count > 0:
        workers = [asyncio.create_task(worker()) for _ in range(worker_count)]
        await asyncio.gather(*workers)

    success_items.sort(key=lambda x: x.get("index", 0))
    error_items.sort(key=lambda x: x.get("index", 0))

    return {
        "success": True,
        "total": len(subscriptions),
        "success_count": len(success_items),
        "error_count": len(error_items),
        "successes": success_items,
        "errors": error_items
    }


@router.put("/subscriptions/bulk-config")
@require_license_api
async def bulk_update_subscription_config(
    ids: str = Query(...),
    auto_record: Optional[str] = Query(None),
    monitor_enabled: Optional[str] = Query(None),
    quality: Optional[str] = Query(None),
    notification_enabled: Optional[str] = Query(None),
    split_enabled: Optional[str] = Query(None),
    split_duration: Optional[int] = Query(None),
    generate_subtitle: Optional[str] = Query(None),
    auto_convert_mp4: Optional[str] = Query(None),
    danmu_enabled: Optional[str] = Query(None),
    compat_mode: Optional[str] = Query(None),
    db: Session = Depends(get_session)
):
    """批量更新订阅配置"""
    id_list = [i.strip() for i in ids.split(",") if i.strip()]
    if not id_list:
        raise HTTPException(status_code=400, detail="未提供有效的ID列表")
        
    subs = db.query(LiveSubscription).filter(LiveSubscription.id.in_(id_list)).all()
    subscriptions_to_activate = []    # auto_record 从 false -> true 的订阅，用于立即检查
    subscriptions_to_pause_monitor = []
    subscriptions_to_resume_monitor = []

    count = 0
    for sub in subs:
        if quality is not None:
            sub.quality = quality

        if auto_record is not None:
            old_auto_record = (sub.auto_record == "true")
            new_auto_record = str(auto_record).lower() in ('true', '1', 'yes', 'on')
            sub.auto_record = "true" if new_auto_record else "false"
            if new_auto_record and not old_auto_record:
                subscriptions_to_activate.append({
                    "id": sub.id,
                    "room_url": sub.room_url,
                    "platform": sub.platform,
                    "check_interval": sub.check_interval or 60,
                })

        if monitor_enabled is not None:
            old_monitor_enabled = (getattr(sub, "monitor_enabled", "true") != "false")
            new_monitor_enabled = str(monitor_enabled).lower() in ('true', '1', 'yes', 'on')
            sub.monitor_enabled = "true" if new_monitor_enabled else "false"
            if new_monitor_enabled and not old_monitor_enabled:
                subscriptions_to_resume_monitor.append({
                    "id": sub.id,
                    "room_url": sub.room_url,
                    "platform": sub.platform,
                    "check_interval": sub.check_interval or 60,
                })
            elif (not new_monitor_enabled) and old_monitor_enabled:
                subscriptions_to_pause_monitor.append(sub.id)

        if notification_enabled is not None:
            sub.notification_enabled = "true" if str(notification_enabled).lower() in ('true', '1', 'yes', 'on') else "false"

        if split_enabled is not None:
            sub.split_enabled = "true" if str(split_enabled).lower() in ('true', '1', 'yes', 'on') else "false"

        if split_duration is not None:
            sub.split_duration = max(300, min(86400, split_duration))

        extra = {}
        if sub.extra_data:
            try:
                extra = json.loads(sub.extra_data) if isinstance(sub.extra_data, str) else sub.extra_data
                if not isinstance(extra, dict):
                    extra = {}
            except Exception:
                extra = {}

        if generate_subtitle is not None:
            extra['generate_subtitle'] = str(generate_subtitle).lower() == "true"

        if auto_convert_mp4 is not None:
            extra['auto_convert_mp4'] = str(auto_convert_mp4).lower() == "true"
        if danmu_enabled is not None:
            extra['danmu_enabled'] = str(danmu_enabled).lower() == "true"
        if compat_mode is not None:
            extra['compat_mode'] = str(compat_mode).lower() == "true"

        if generate_subtitle is not None or auto_convert_mp4 is not None or danmu_enabled is not None or compat_mode is not None:
            sub.extra_data = json.dumps(extra)

        sub.updated_at = datetime.now()
        count += 1

    db.commit()

    # [优化] 配置变更后失效内存缓存
    for sub in subs:
        live_scheduler.invalidate_config_cache(sub.id)

    paused_monitor_count = 0
    if subscriptions_to_pause_monitor:
        logger.info(f"批量更新后准备暂停 {len(subscriptions_to_pause_monitor)} 个订阅的周期检测")

        async def _safe_pause_monitor(sub_id: str) -> bool:
            try:
                await live_scheduler.remove_monitor(sub_id, stop_recording=False)
                return True
            except Exception as e:
                logger.error(f"批量更新后暂停周期检测失败: {sub_id}, {e}")
                return False

        pause_results = await asyncio.gather(*[_safe_pause_monitor(sub_id) for sub_id in subscriptions_to_pause_monitor])
        paused_monitor_count = sum(1 for ok in pause_results if ok)

    activated_count = 0
    monitor_resume_items = subscriptions_to_resume_monitor
    auto_activate_items = [
        item for item in subscriptions_to_activate
        if item["id"] not in set(subscriptions_to_pause_monitor)
        and (
            monitor_enabled is None
            or str(monitor_enabled).lower() in ('true', '1', 'yes', 'on')
        )
    ]
    if monitor_resume_items:
        logger.info(f"批量更新后准备恢复 {len(monitor_resume_items)} 个订阅的周期检测")

        async def _safe_resume_monitor(item: dict) -> bool:
            try:
                await live_scheduler.add_monitor(
                    item["id"],
                    item["room_url"],
                    item["platform"],
                    item["check_interval"]
                )
                return True
            except Exception as e:
                logger.error(f"批量更新后恢复周期检测失败: {item.get('id')}, {e}")
                return False

        await asyncio.gather(*[_safe_resume_monitor(item) for item in monitor_resume_items])

    if auto_activate_items:
        logger.info(f"批量更新后准备立即检查 {len(auto_activate_items)} 个新开启自动录制的订阅")

        async def _safe_activate(item: dict) -> bool:
            try:
                await live_scheduler.add_monitor(
                    item["id"],
                    item["room_url"],
                    item["platform"],
                    item["check_interval"]
                )
                return await live_scheduler.trigger_immediate_check(item["id"])
            except Exception as e:
                logger.error(f"批量更新后立即检查失败: {item.get('id')}, {e}")
                return False

        results = await asyncio.gather(*[_safe_activate(item) for item in auto_activate_items])
        activated_count = sum(1 for ok in results if ok)

    logger.info(
        f"批量更新{count}个直播订阅配置成功, 立即触发录制 {activated_count} 个, "
        f"暂停周期检测 {paused_monitor_count} 个"
    )
    return {
        "success": True,
        "message": f"成功批量更新 {count} 个直播订阅",
        "immediate_checked": len(subscriptions_to_activate),
        "immediate_started": activated_count,
        "monitor_paused": paused_monitor_count,
    }


@router.delete("/subscriptions/bulk")
@require_license_api
async def bulk_delete_live_subscriptions(
    ids: str = Query(...),
    db: Session = Depends(get_session)
):
    """批量删除直播订阅"""
    id_list = [i.strip() for i in ids.split(",") if i.strip()]
    if not id_list:
        raise HTTPException(status_code=400, detail="未提供有效的ID列表")

    subs = db.query(LiveSubscription).filter(LiveSubscription.id.in_(id_list)).all()
    if not subs:
        raise HTTPException(status_code=404, detail="未找到匹配的订阅")

    count = 0
    for sub in subs:
        should_convert = True
        try:
            if sub.extra_data:
                extra = sub.extra_data if isinstance(sub.extra_data, dict) else json.loads(sub.extra_data)
                should_convert = extra.get('auto_convert_mp4', True)
        except Exception:
            pass

        if live_recorder.is_recording(sub.id):
            await live_recorder.stop_recording(sub.id, convert_to_mp4=should_convert)

        await live_scheduler.remove_monitor(sub.id)
        db.query(LiveRecord).filter(LiveRecord.subscription_id == sub.id).delete()
        db.delete(sub)
        count += 1

    db.commit()
    logger.info(f"批量删除{count}个直播订阅成功")
    return {"success": True, "message": f"成功批量删除 {count} 个直播订阅"}


@router.put("/subscriptions/{sub_id}")
@require_license_api
async def update_live_subscription(
    sub_id: str,
    quality: Optional[str] = Query(None),
    auto_record: Optional[str] = Query(None),
    monitor_enabled: Optional[str] = Query(None),
    check_interval: Optional[int] = Query(None),
    notification_enabled: Optional[str] = Query(None),
    db: Session = Depends(get_session)
):
    """更新直播订阅设置"""
    subscription = db.query(LiveSubscription).filter(LiveSubscription.id == sub_id).first()
    if not subscription:
        raise HTTPException(status_code=404, detail="订阅不存在")
    
    auto_record_bool = None
    monitor_enabled_bool = None
    notification_enabled_bool = None
    if auto_record is not None:
        auto_record_bool = str(auto_record).lower() in ('true', '1', 'yes', 'on')
    if monitor_enabled is not None:
        monitor_enabled_bool = str(monitor_enabled).lower() in ('true', '1', 'yes', 'on')
    if notification_enabled is not None:
        notification_enabled_bool = str(notification_enabled).lower() in ('true', '1', 'yes', 'on')
    
    if quality is not None:
        subscription.quality = quality
    
    if auto_record_bool is not None:
        subscription.auto_record = "true" if auto_record_bool else "false"

    if monitor_enabled_bool is not None:
        old_monitor_enabled = getattr(subscription, "monitor_enabled", "true") != "false"
        subscription.monitor_enabled = "true" if monitor_enabled_bool else "false"
        if monitor_enabled_bool and not old_monitor_enabled:
            await live_scheduler.add_monitor(
                subscription.id, subscription.room_url, subscription.platform, subscription.check_interval
            )
        elif not monitor_enabled_bool and old_monitor_enabled:
            await live_scheduler.remove_monitor(subscription.id, stop_recording=False)
    
    if check_interval is not None:
        if check_interval < 10 or check_interval > 600:
            raise HTTPException(status_code=400, detail="检测间隔必须在10-600秒之间")
        subscription.check_interval = check_interval
    
    if notification_enabled_bool is not None:
        subscription.notification_enabled = "true" if notification_enabled_bool else "false"
    
    subscription.updated_at = datetime.now()
    db.commit()
    # [优化] 配置变更后失效内存缓存
    live_scheduler.invalidate_config_cache(sub_id)
    return {"success": True, "message": "更新成功"}


@router.delete("/subscriptions/{sub_id}")
@require_license_api
async def delete_live_subscription(sub_id: str, db: Session = Depends(get_session)):
    """删除直播订阅"""
    subscription = db.query(LiveSubscription).filter(LiveSubscription.id == sub_id).first()
    if not subscription:
        raise HTTPException(status_code=404, detail="订阅不存在")
    
    # 解析转码配置
    should_convert = True
    try:
        if subscription.extra_data:
            extra = subscription.extra_data if isinstance(subscription.extra_data, dict) else json.loads(subscription.extra_data)
            should_convert = extra.get('auto_convert_mp4', True)
    except:
        pass

    if live_recorder.is_recording(sub_id):
        await live_recorder.stop_recording(sub_id, convert_to_mp4=should_convert)
    
    await live_scheduler.remove_monitor(sub_id)
    
    # 清理关联的历史记录 (保留文件)
    db.query(LiveRecord).filter(LiveRecord.subscription_id == sub_id).delete()
    
    db.delete(subscription)
    db.commit()
    return {"success": True, "message": "删除成功"}


# ==================== 直播状态 ====================

@router.get("/status")
@require_license_api
async def get_live_status(
    current_user: User = Depends(get_current_user_or_token),
    db: Session = Depends(get_session)
):
    """获取所有直播间的实时状态"""
    subscriptions = db.query(LiveSubscription).all()
    status_list = []
    for sub in subscriptions:
        is_recording = live_recorder.is_recording(sub.id)
        recording_status = live_recorder.get_recording_status(sub.id) if is_recording else None
        status_list.append({
            "id": sub.id,
            "anchor_name": sub.anchor_name,
            "platform": sub.platform,
            "is_live": sub.is_live == "true",
            "is_recording": is_recording,
            "recording_status": recording_status,
            "last_check_time": sub.last_check_time.isoformat() if sub.last_check_time else None
        })
    return {"success": True, "data": status_list}


@router.post("/status/refresh/{sub_id}")
@require_license_api
async def refresh_live_status(
    sub_id: str,
    current_user: User = Depends(get_current_user_or_token),
    db: Session = Depends(get_session)
):
    """刷新单个直播间状态"""
    subscription = db.query(LiveSubscription).filter(LiveSubscription.id == sub_id).first()
    if not subscription:
        raise HTTPException(status_code=404, detail="订阅不存在")
    
    try:
        adapter = adapters.get_adapter_by_platform(subscription.platform)
        if not adapter:
            raise Exception(f"找不到平台适配器: {subscription.platform}")

        # 使用适配器获取最新信息
        info = await adapter.get_room_info(subscription.room_url)
        
        subscription.is_live = "true" if info['is_live'] else "false"
        subscription.anchor_name = info['anchor_name'] or subscription.anchor_name
        if info['avatar_url']:
            subscription.avatar_url = info['avatar_url']
            
        subscription.last_check_time = datetime.now()
        if info['is_live']:
            subscription.last_live_time = datetime.now()
            
        db.commit()
        
        return {
            "success": True,
            "data": {
                "is_live": info['is_live'],
                "anchor_name": subscription.anchor_name
            }
        }
    except Exception as e:
        logger.error(f"刷新状态失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"刷新状态失败: {str(e)}")


# ==================== 录制控制 ====================

@router.post("/record/start/{sub_id}")
@require_license_api
async def start_recording(
    sub_id: str,
    current_user: User = Depends(get_current_user_or_token),
    db: Session = Depends(get_session)
):
    """手动开始录制"""
    subscription = db.query(LiveSubscription).filter(LiveSubscription.id == sub_id).first()
    if not subscription:
        raise HTTPException(status_code=404, detail="订阅不存在")
    
    if live_recorder.is_recording(sub_id):
        raise HTTPException(status_code=400, detail="该直播间正在录制中")
    
    try:
        adapter = adapters.get_adapter_by_platform(subscription.platform)
        if not adapter:
            raise Exception(f"找不到平台适配器: {subscription.platform}")

        resolved_room_id = getattr(subscription, "room_id", None) or ""
        try:
            room_info = await adapter.get_room_info(subscription.room_url)
            if room_info:
                fetched_room_id = room_info.get("room_id") or ""
                if fetched_room_id and fetched_room_id != resolved_room_id:
                    resolved_room_id = fetched_room_id
                    subscription.room_id = fetched_room_id
                fetched_anchor = room_info.get("anchor_name") or ""
                if fetched_anchor and fetched_anchor != subscription.anchor_name:
                    subscription.anchor_name = fetched_anchor
        except Exception as room_err:
            logger.debug(f"手动录制获取 room_id 失败，继续使用缓存值: {room_err}")

        # 使用适配器获取流地址
        stream_data = await adapter.get_stream_url(subscription.room_url, subscription.quality)
        
        if not stream_data.get('is_live'):
            raise HTTPException(status_code=400, detail="主播未开播或无法获取流")
            
        stream_url = stream_data.get('url')
        if not stream_url:
             raise HTTPException(status_code=400, detail="无法解析出有效的直播流地址")

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"启动录制前获取流失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"获取直播流失败: {str(e)}")
    
    # 生成输出文件路径
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    safe_anchor_name = "".join(c for c in subscription.anchor_name if c.isalnum() or c in (' ', '-', '_')).strip() or "unknown"
    
    filename = f"{safe_anchor_name}_{timestamp}.ts"
    output_dir = f"/app/downloads/live/{subscription.platform}/{safe_anchor_name}"
    os.makedirs(output_dir, exist_ok=True)
    output_path = os.path.join(output_dir, filename)
    
    # 高级配置解析
    segment_time = 0
    generate_subtitle = False
    danmu_enabled = False
    compat_mode = False

    if subscription.split_enabled == "true":
        segment_time = subscription.split_duration or 3600

    if subscription.extra_data:
        try:
            extra = subscription.extra_data if isinstance(subscription.extra_data, dict) else json.loads(subscription.extra_data)
            generate_subtitle = extra.get('generate_subtitle', False)
            danmu_enabled = extra.get('danmu_enabled', False)
            compat_mode = extra.get('compat_mode', False)
            if isinstance(danmu_enabled, str):
                danmu_enabled = danmu_enabled.strip().lower() not in ("false", "0", "no")
            if isinstance(compat_mode, str):
                compat_mode = compat_mode.strip().lower() not in ("false", "0", "no")
        except:
            pass

    # 为避免触发 remove_monitor 中的“强制停止录制”逻辑，
    # 先重建监控任务，再启动录制。此时尚未有录制进程，remove_monitor 不会误杀刚启动的录制。
    await live_scheduler.remove_monitor(sub_id)
    await live_scheduler.add_monitor(sub_id, subscription.room_url, subscription.platform, subscription.check_interval or 60)

    # 启动录制
    loop = asyncio.get_running_loop()

    def on_process_exit(subscription_id: str):
        asyncio.run_coroutine_threadsafe(
            live_scheduler._handle_unexpected_exit(subscription_id), loop
        )

    try:
        await live_recorder.start_recording(
            subscription_id=sub_id,
            stream_url=stream_url,
            output_path=output_path,
            quality=subscription.quality,
            segment_time=int(segment_time),
            generate_subtitle=generate_subtitle,
            compat_mode=compat_mode,
            on_exit_callback=on_process_exit,
            platform=subscription.platform,
            source_url=subscription.room_url,
            room_url=subscription.room_url if danmu_enabled else None,
            anchor_name=subscription.anchor_name,
            room_id=resolved_room_id or ""
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"启动录制进程失败: {str(e)}")
    
    # 更新状态
    subscription.is_recording = "true"
    subscription.auto_record = "true"
    subscription.last_live_time = datetime.now()
    
    # 创建记录
    record = LiveRecord(
        id=str(uuid.uuid4()),
        subscription_id=sub_id,
        stream_url=stream_url,
        quality=subscription.quality,
        start_time=datetime.now(),
        file_path=output_path,
        file_name=filename,
        format="ts",
        status="recording"
    )
    db.add(record)
    db.commit()
    
    return {"success": True, "message": "录制已开始", "data": {"record_id": record.id}}


@router.post("/record/stop/{sub_id}")
@require_license_api
async def stop_recording(
    sub_id: str,
    current_user: User = Depends(get_current_user_or_token),
    db: Session = Depends(get_session)
):
    """手动停止录制"""
    subscription = db.query(LiveSubscription).filter(LiveSubscription.id == sub_id).first()
    if not subscription:
        raise HTTPException(status_code=404, detail="订阅不存在")
    
    if not live_recorder.is_recording(sub_id):
        raise HTTPException(status_code=400, detail="该直播间未在录制")
    
    convert_to_mp4 = True
    if subscription.extra_data:
        try:
            extra = subscription.extra_data if isinstance(subscription.extra_data, dict) else json.loads(subscription.extra_data)
            convert_to_mp4 = extra.get('auto_convert_mp4', True)
        except:
            pass
        
    # 获取记录ID用于回调
    record_id = None
    record = db.query(LiveRecord).filter(LiveRecord.subscription_id == sub_id, LiveRecord.status == "recording").order_by(LiveRecord.start_time.desc()).first()
    if record: record_id = record.id

    def on_transcode_finished(success, mp4_path):
        if not success or not record_id: return
        db_session = None
        try:
            db_session = get_session()
            rec = db_session.query(LiveRecord).filter(LiveRecord.id == record_id).first()
            if rec:
                _apply_transcode_success_to_record(rec, mp4_path)
                db_session.commit()
                logger.info(f"手动停止录制转码完成，数据库记录已更新为MP4: {record_id}")
        except Exception as e:
            logger.error(f"手动停止录制转码回调更新数据库失败: {e}")
            if db_session:
                try:
                    db_session.rollback()
                except Exception:
                    pass
        finally:
            if db_session:
                db_session.close()

    result = await live_recorder.stop_recording(
        sub_id, 
        convert_to_mp4=convert_to_mp4,
        on_convert_complete=on_transcode_finished if record_id else None
    )
    
    if not result['success']:
        raise HTTPException(status_code=500, detail=result.get('message', '停止录制失败'))
    
    subscription.is_recording = "false"
    subscription.auto_record = "false"
    # 仅停止当前录制，不影响周期检测任务。
    # 直播间状态刷新是否继续，统一由 monitor_enabled 控制。
    
    if record:
        record.end_time = datetime.now()
        record.duration = result['duration']
        record.file_size = result['file_size']
        record.status = "completed"
    
    db.commit()
    return {"success": True, "message": "录制已停止", "data": result}


@router.get("/record/status/{sub_id}")
@require_license_api
async def get_recording_status(
    sub_id: str,
    current_user: User = Depends(get_current_user_or_token)
):
    status = live_recorder.get_recording_status(sub_id)
    if not status: return {"success": True, "data": {"is_recording": False}}
    return {"success": True, "data": {"is_recording": True, **status}}


@router.get("/play/{sub_id}")
@require_license_api
async def get_play_url(sub_id: str, db: Session = Depends(get_session)):
    """获取直播流播放地址"""
    subscription = db.query(LiveSubscription).filter(LiveSubscription.id == sub_id).first()
    if not subscription:
        raise HTTPException(status_code=404, detail="订阅不存在")
    
    try:
        adapter = adapters.get_adapter_by_platform(subscription.platform)
        if not adapter:
            return {"success": False, "message": "不支持的平台"}

        stream_data = await adapter.get_stream_url(subscription.room_url, "OD")  # 默认原画播放
        
        if not stream_data.get('is_live'):
             return {"success": False, "message": "主播当前未开播"}
             
        # 实时播放优先使用适配器给出的播放链路（与录制链路解耦）
        url = stream_data.get('play_url') or stream_data.get('url')
        if not url:
             return {"success": False, "message": "无法获取有效播放地址"}

        # ---------------- 同源代理策略（解决 CORS / 混合内容问题）----------------
        # 1. 对于小红书等存在严格 CORS 限制的平台，前端直接请求真实 CDN 会被浏览器拦截。
        # 2. 当 UI 通过 HTTPS 访问而上游流地址是 HTTP 时，浏览器会因为「混合内容」而阻止加载。
        #
        # 这两类情况统一通过后端同源代理解决：前端始终访问 /api/live/play/proxy/{sub_id}，
        # 由服务器侧拉取真实流并转发给浏览器。
        play_format = stream_data.get('play_format') or stream_data.get('format', 'flv')
        fallback_url = stream_data.get('play_fallback_url')
        fallback_format = stream_data.get('play_fallback_format')
        if not fallback_url:
            if play_format == "flv":
                fallback_url = stream_data.get("m3u8_url")
                fallback_format = "m3u8" if fallback_url else None
            elif play_format == "m3u8":
                fallback_url = stream_data.get("flv_url")
                fallback_format = "flv" if fallback_url else None
        if fallback_url and str(fallback_url) == str(url):
            fallback_url, fallback_format = None, None
        url_str = str(url).lower()

        needs_proxy = False
        if subscription.platform in ("xhs", "bilibili"):
            # 小红书：始终使用代理，避免 CORS 问题
            # B站：部分直播流要求特定请求头，浏览器直连常见 403，统一走代理更稳定
            needs_proxy = True
        elif url_str.startswith("http://"):
            # 当页面通过 HTTPS 访问而上游流是 HTTP 时，会触发浏览器混合内容拦截，这里强制走代理
            needs_proxy = True

        if needs_proxy:
            proxy_url = f"/api/live/play/proxy/{sub_id}"
            return {
                "success": True,
                "data": {
                    "url": proxy_url,
                    # 代理输出使用适配器建议的播放格式（通常为 flv），以便前端选择合适的播放器
                    "format": play_format,
                    "fallback_url": fallback_url,
                    "fallback_format": fallback_format,
                    "is_live": True
                }
            }

        # 其他平台 / 情况：沿用直连地址
        return {
            "success": True,
            "data": {
                "url": url,
                "format": play_format,
                "fallback_url": fallback_url,
                "fallback_format": fallback_format,
                "is_live": True
            }
        }
    except Exception as e:
        logger.error(f"获取播放地址失败: {e}")
        return {"success": False, "message": f"播放失败: {str(e)}"}


@router.get("/play/proxy/{sub_id}")
@require_license_api
async def proxy_live_stream(sub_id: str, db: Session = Depends(get_session)):
    """
    直播流代理：解决部分平台（如小红书）CDN 不允许浏览器跨域直连的问题。
    由后端拉取真实流并以同源 StreamingResponse 转发给前端。
    """
    subscription = db.query(LiveSubscription).filter(LiveSubscription.id == sub_id).first()
    if not subscription:
        raise HTTPException(status_code=404, detail="订阅不存在")

    try:
        adapter = adapters.get_adapter_by_platform(subscription.platform)
        if not adapter:
            raise HTTPException(status_code=400, detail="不支持的平台")

        # 重新获取一遍最新流地址，确保直播仍然在线
        stream_data = await adapter.get_stream_url(subscription.room_url, "原画")
        if not stream_data.get("is_live"):
            raise HTTPException(status_code=400, detail="主播当前未开播")

        # 代理时优先使用播放链路（例如抖音的 flv_url），确保与前端播放器格式匹配
        upstream_url = stream_data.get("play_url") or stream_data.get("url")
        if not upstream_url:
            raise HTTPException(status_code=400, detail="无法获取有效直播流地址")

        is_flv = ".flv" in str(upstream_url).lower()
        media_type = "video/x-flv" if is_flv else "application/octet-stream"
        request_headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                          "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
            "Accept": "*/*",
        }
        if subscription.platform == "bilibili":
            bilibili_referer = (subscription.room_url or "https://live.bilibili.com/").split("#", 1)[0]
            request_headers.update({
                "Referer": bilibili_referer,
                "Origin": "https://live.bilibili.com",
            })

        async def iter_stream():
            # 通过 httpx 异步流式转发上游内容
            async with httpx.AsyncClient(timeout=None, follow_redirects=True) as client:
                async with client.stream("GET", upstream_url, headers=request_headers) as resp:
                    if resp.status_code >= 400:
                        parsed = urlsplit(str(upstream_url))
                        logger.warning(
                            "[LiveProxy] 上游拒绝拉流: platform=%s sub_id=%s status=%s format=%s host=%s path=%s",
                            subscription.platform,
                            sub_id,
                            resp.status_code,
                            "flv" if is_flv else "unknown",
                            parsed.netloc,
                            parsed.path,
                        )
                        return
                    async for chunk in resp.aiter_bytes(chunk_size=64 * 1024):
                        yield chunk

        return StreamingResponse(
            iter_stream(),
            media_type=media_type,
            headers={
                "Cache-Control": "no-store",
            },
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"代理直播流失败 ({subscription.platform}): {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"代理直播流失败: {str(e)}")



@router.get("/timeline/{sub_id}")
@require_license_api
async def get_live_timeline(
    sub_id: str,
    date_str: Optional[str] = Query(None, alias="date"),
    db: Session = Depends(get_session)
):
    """获取指定日期的录制时间轴数据"""
    from datetime import datetime, timedelta
    
    subscription = db.query(LiveSubscription).filter(LiveSubscription.id == sub_id).first()
    if not subscription:
        raise HTTPException(status_code=404, detail="订阅不存在")
    
    timeline_statuses = ["recording", "completed", "stopped", "converting", "failed"]
    query = db.query(LiveRecord).filter(
        LiveRecord.subscription_id == sub_id,
        LiveRecord.status.in_(timeline_statuses)
    )
    day_window = None
    
    if date_str:
        try:
            target_date = datetime.strptime(date_str, "%Y-%m-%d").date()
            start_of_day = datetime.combine(target_date, datetime.min.time())
            end_of_day = start_of_day + timedelta(days=1)
            day_window = (start_of_day, end_of_day)
        except ValueError:
            pass
            
    records = query.order_by(LiveRecord.start_time.asc()).all()
    
    # 构建时间轴片段（支持 MP4/TS）
    timeline = []
    base_dir = "/app/downloads/"
    skipped_non_playable = 0
    status_counter = {}
    for r in records:
        # 优先使用转码后的 MP4，其次允许原生 MP4/TS 文件。
        play_path, play_format = _resolve_record_playable_path(r)

        if not play_path:
            skipped_non_playable += 1
            continue

        record_start = r.start_time
        if not record_start:
            continue

        record_end = _resolve_record_end_time(r)
        if not record_end:
            continue
        comp_record_end, comp_record_start = _align_datetime_pair(record_end, record_start)
        if comp_record_end < comp_record_start:
            record_end = record_start

        clip_start = record_start
        clip_end = record_end
        if day_window:
            day_start, day_end = day_window
            comp_record_start, comp_day_end = _align_datetime_pair(record_start, day_end)
            comp_record_end, comp_day_start = _align_datetime_pair(record_end, day_start)
            if comp_record_start >= comp_day_end or comp_record_end <= comp_day_start:
                continue
            comp_start_left, comp_start_right = _align_datetime_pair(record_start, day_start)
            clip_start = record_start if comp_start_left >= comp_start_right else day_start
            comp_end_left, comp_end_right = _align_datetime_pair(record_end, day_end)
            clip_end = record_end if comp_end_left <= comp_end_right else day_end

        comp_clip_end, comp_clip_start = _align_datetime_pair(clip_end, clip_start)
        clip_duration = int(max(0, (comp_clip_end - comp_clip_start).total_seconds()))
        if clip_duration <= 0:
            continue

        comp_clip_start, comp_record_start = _align_datetime_pair(clip_start, record_start)
        start_offset_seconds = max(0, int((comp_clip_start - comp_record_start).total_seconds()))
            
        # 转换为相对路径供前端 /api/video/stream 播放
        rel_path = play_path
        if play_path.startswith(base_dir):
            rel_path = play_path[len(base_dir):]
        
        if rel_path.startswith('/'):
            rel_path = rel_path[1:]
            
        import urllib.parse
        encoded_path = urllib.parse.quote(rel_path)
            
        play_url = f"/api/video/stream?filename={encoded_path}&quality=original"
        if start_offset_seconds > 0 and play_format == "mp4":
            play_url += f"&start={start_offset_seconds}"

        timeline.append({
            "id": r.id,
            "start_time": clip_start.isoformat(),
            "end_time": clip_end.isoformat(),
            "duration": clip_duration,
            "start_offset": start_offset_seconds,
            "file_size": r.file_size or 0,
            "quality": r.quality,
            "format": play_format,
            "status": str(r.status or "").lower() or "unknown",
            "play_url": play_url,
            "file_path": play_path
        })
        status_key = str(r.status or "").lower() or "unknown"
        status_counter[status_key] = status_counter.get(status_key, 0) + 1

    timeline.sort(key=lambda item: item.get("start_time") or "")

    return {
        "success": True,
        "data": timeline,
        "meta": {
            "skipped_non_playable": skipped_non_playable,
            # 兼容旧前端字段名
            "skipped_non_mp4": skipped_non_playable,
            "total_records": len(records),
            "status_counts": status_counter
        }
    }


@router.get("/timeline/{sub_id}/dates")
@require_license_api
async def get_live_timeline_dates(
    sub_id: str,
    db: Session = Depends(get_session)
):
    """获取指定订阅可用于时间轴播放的日期列表（仅统计可播放 MP4/TS）"""
    subscription = db.query(LiveSubscription).filter(LiveSubscription.id == sub_id).first()
    if not subscription:
        raise HTTPException(status_code=404, detail="订阅不存在")

    timeline_statuses = ["recording", "completed", "stopped", "converting", "failed"]
    rows = db.query(
        LiveRecord.start_time,
        LiveRecord.end_time,
        LiveRecord.duration,
        LiveRecord.converted,
        LiveRecord.converted_path,
        LiveRecord.file_path,
        LiveRecord.format,
        LiveRecord.status
    ).filter(
        LiveRecord.subscription_id == sub_id,
        LiveRecord.status.in_(timeline_statuses),
    ).order_by(LiveRecord.start_time.asc()).all()

    date_counter = {}
    for row in rows:
        start_time = getattr(row, "start_time", None)
        if not start_time:
            continue

        # 与 /timeline 保持一致：仅统计可播放 mp4/ts
        row_converted = getattr(row, "converted", None)
        row_converted_path = getattr(row, "converted_path", None)
        row_file_path = getattr(row, "file_path", None)
        row_format = getattr(row, "format", None)
        row_format_lower = str(row_format or "").lower()
        row_file_path_lower = str(row_file_path or "").lower()

        playable = False
        if row_converted == "true" and row_converted_path and str(row_converted_path).lower().endswith(".mp4"):
            playable = True
        elif row_file_path and (
            row_file_path_lower.endswith(".mp4")
            or row_file_path_lower.endswith(".ts")
            or row_format_lower in {"mp4", "ts"}
        ):
            playable = True
        if not playable:
            continue

        row_status = str(getattr(row, "status", "") or "").lower()
        end_time = getattr(row, "end_time", None)
        duration = getattr(row, "duration", None) or 0
        if row_status == "recording" and not end_time:
            if start_time.tzinfo is not None and start_time.tzinfo.utcoffset(start_time) is not None:
                end_time = datetime.now(start_time.tzinfo)
            else:
                end_time = datetime.now()
        if not end_time and duration and duration > 0:
            end_time = start_time + timedelta(seconds=int(duration))
        if not end_time:
            end_time = start_time
        else:
            comp_end_time, comp_start_time = _align_datetime_pair(end_time, start_time)
            if comp_end_time < comp_start_time:
                end_time = start_time

        day_cursor = start_time.date()
        last_day = end_time.date()
        while day_cursor <= last_day:
            day_start = datetime.combine(day_cursor, datetime.min.time())
            day_end = day_start + timedelta(days=1)
            comp_start_time, comp_day_end = _align_datetime_pair(start_time, day_end)
            comp_end_time, comp_day_start = _align_datetime_pair(end_time, day_start)
            if comp_start_time < comp_day_end and comp_end_time > comp_day_start:
                date_key = day_cursor.isoformat()
                date_counter[date_key] = date_counter.get(date_key, 0) + 1
            day_cursor = day_cursor + timedelta(days=1)

    dates = [
        {"date": day, "count": date_counter[day]}
        for day in sorted(date_counter.keys())
    ]

    return {
        "success": True,
        "data": dates,
        "total_days": len(dates)
    }

# ==================== 录制历史 ====================

@router.get("/records")
@require_license_api
async def get_records(
    subscription_id: Optional[str] = None,
    status: Optional[str] = None,
    page: int = 1,
    page_size: int = 20,
    db: Session = Depends(get_session)
):
    """获取录制历史"""
    query = db.query(LiveRecord)
    
    if subscription_id:
        query = query.filter(LiveRecord.subscription_id == subscription_id)
    if status:
        query = query.filter(LiveRecord.status == status)
        
    total = query.count()
    records = query.order_by(LiveRecord.start_time.desc()).offset((page - 1) * page_size).limit(page_size).all()
    
    result = []
    for r in records:
        # 关联查询主播名 (如果记录里没有snapshot)
        sub_name = r.anchor_name
        sub_avatar = None
        sub_platform = None
        danmu_enabled = False
        has_danmu_file = False
        highlights_state = _resolve_highlights_state(r.file_path, r.converted_path)
        manual_clips_state = _resolve_manual_clips_state(r.file_path, r.converted_path)
        
        # 尝试查询关联订阅以获取头像
        # 优化：如果是同一批次，可以改为 eager loading 或 cache，这里简单处理
        sub = db.query(LiveSubscription).filter(LiveSubscription.id == r.subscription_id).first()
        if sub: 
            if not sub_name: sub_name = sub.anchor_name
            sub_avatar = sub.avatar_url
            sub_platform = sub.platform
            try:
                extra_data = json.loads(sub.extra_data or "{}")
                danmu_enabled = bool(extra_data.get("danmu_enabled", False))
            except Exception:
                danmu_enabled = False

        danmu_path = _resolve_danmu_path(r.file_path)
        if danmu_path and os.path.exists(danmu_path):
            has_danmu_file = True
            
        result.append({
            "id": r.id,
            "subscription_id": r.subscription_id,
            "platform": sub_platform,
            "anchor_name": sub_name,
            "avatar_url": sub_avatar,
            "live_title": r.live_title,
            "start_time": r.start_time.isoformat() if r.start_time else None,
            "end_time": r.end_time.isoformat() if r.end_time else None,
            "duration": r.duration,
            "file_size": r.file_size,
            "file_path": r.file_path,
            "status": r.status,
            "error_message": r.error_message,
            "remark": r.remark,
            "converted": r.converted,
            "converted_path": r.converted_path,
            "danmu_enabled": danmu_enabled,
            "has_danmu_file": has_danmu_file,
            "danmu_path": danmu_path,
            "has_highlights_analysis": bool(highlights_state.get("has_highlights_analysis")),
            "highlights_status": str(highlights_state.get("highlights_status") or "none"),
            "has_manual_clips": bool(manual_clips_state.get("has_manual_clips")),
            "manual_clip_count": int(manual_clips_state.get("manual_clip_count") or 0),
        })
        
    # 计算正在录制中的数量 (用于前端提示)
    # 注意：这里需要重新从 base query 计算，不受 status 参数影响太多（或者是用户就是想看特定status的？）
    # 为了简化，我们计算当前筛选条件下的 recording 数量。
    # 如果用户筛选 status='completed'，那 recording_count 自然为 0，这逻辑是通的。
    # 但如果用户要在"清空所有"时看到有多少正在录制，通常是在无 status 筛选下。
    
    # 我们基于当前的 subscription_id 筛选条件来计算 recording 数量，忽略 status 参数（因为清空操作通常也是忽略 status 只是排除 recording）
    # 或者为了准确性，我们在清空弹窗需要的上下文里，是希望知道"本来会被删除但被保留的录制中任务"
    
    count_query = db.query(LiveRecord)
    if subscription_id:
        count_query = count_query.filter(LiveRecord.subscription_id == subscription_id)
        
    recording_count = count_query.filter(LiveRecord.status == 'recording').count()
    
    return {
        "success": True,
        "data": result,
        "total": total,
        "page": page,
        "page_size": page_size,
        "recording_count": recording_count  # [新增] 返回正在录制的数量
    }


@router.get("/records/timeline-availability")
@require_license_api
async def get_timeline_availability(
    ids: Optional[str] = None,
    db: Session = Depends(get_session)
):
    """批量获取订阅是否有可用于时间轴播放的 MP4/TS 历史"""
    sub_ids = [i.strip() for i in (ids or "").split(",") if i.strip()]

    timeline_statuses = ["recording", "completed", "stopped", "converting", "failed"]
    query = db.query(
        LiveRecord.subscription_id.label("subscription_id"),
        func.count(LiveRecord.id).label("count")
    ).filter(
        LiveRecord.status.in_(timeline_statuses),
        LiveRecord.subscription_id.isnot(None),
        or_(
            and_(
                LiveRecord.converted == "true",
                LiveRecord.converted_path.isnot(None),
                LiveRecord.converted_path.ilike("%.mp4")
            ),
            LiveRecord.file_path.ilike("%.mp4"),
            LiveRecord.file_path.ilike("%.ts"),
            LiveRecord.format.ilike("ts")
        )
    )

    if sub_ids:
        query = query.filter(LiveRecord.subscription_id.in_(sub_ids))

    rows = query.group_by(LiveRecord.subscription_id).all()
    data = {}
    for row in rows:
        sid = row.subscription_id
        cnt = int(row.count or 0)
        data[sid] = {
            "available": cnt > 0,
            "count": cnt
        }

    if sub_ids:
        for sid in sub_ids:
            if sid not in data:
                data[sid] = {"available": False, "count": 0}

    return {"success": True, "data": data}

@router.put("/records/{record_id}/remark")
@require_license_api
async def update_record_remark(
    record_id: str,
    remark: Optional[str] = Query(None),
    db: Session = Depends(get_session)
):
    """更新录制记录备注"""
    record = db.query(LiveRecord).filter(LiveRecord.id == record_id).first()
    if not record:
        raise HTTPException(status_code=404, detail="记录不存在")

    normalized_remark = (remark or "").strip()
    if len(normalized_remark) > 500:
        raise HTTPException(status_code=400, detail="备注最多500个字符")

    record.remark = normalized_remark if normalized_remark else None
    record.updated_at = datetime.now()
    db.commit()

    return {
        "success": True,
        "message": "备注已更新",
        "data": {
            "id": record.id,
            "remark": record.remark
        }
    }

@router.delete("/records/clear")
@require_license_api
async def clear_all_records(
    delete_files: bool = False,
    subscription_id: Optional[str] = None,
    db: Session = Depends(get_session)
):
    """清空所有记录"""
    # 排除正在录制中的记录
    query = db.query(LiveRecord).filter(LiveRecord.status != 'recording')
    
    if subscription_id:
        query = query.filter(LiveRecord.subscription_id == subscription_id)
        
    records = query.all()
    
    if delete_files:
        for r in records:
            try:
                # 1. 删除主文件
                if r.file_path and os.path.exists(r.file_path):
                    os.remove(r.file_path)
                
                # 2. 删除转码文件
                if r.converted_path and os.path.exists(r.converted_path):
                    os.remove(r.converted_path)

                # 3. 删除关联的字幕文件 (.srt) 及分段文件
                if r.file_path:
                    base_path = os.path.splitext(r.file_path)[0]
                    srt_path = base_path + ".srt"
                    danmu_path = base_path + ".danmu.jsonl"
                    danmu_idx_path = base_path + ".danmu.idx.jsonl"
                    if os.path.exists(srt_path):
                        os.remove(srt_path)
                    if os.path.exists(danmu_path):
                        os.remove(danmu_path)
                    if os.path.exists(danmu_idx_path):
                        os.remove(danmu_idx_path)

                    # 尝试清理分段文件
                    directory = os.path.dirname(r.file_path)
                    filename = os.path.basename(r.file_path)
                    file_prefix = os.path.splitext(filename)[0]
                    
                    if os.path.exists(directory):
                        for f in os.listdir(directory):
                            # 匹配前缀 (忽略自己)
                            if f.startswith(file_prefix) and f != filename:
                                if f.endswith(('.ts', '.mp4', '.srt', '.json', '.jsonl', '.flv')):
                                        full_path = os.path.join(directory, f)
                                        try:
                                            os.remove(full_path)
                                        except: pass
            except Exception as e:
                logger.error(f"清空历史时删除文件失败 {r.id}: {e}")
            
    # 执行数据库删除
    # 注意：如果使用了 filter，query.delete() 会删除匹配的行
    query.delete(synchronize_session=False)
    db.commit()
    
    msg = "已清空指定主播的非录制中记录" if subscription_id else "已清空所有非录制中记录"
    return {"success": True, "message": msg}

@router.delete("/records/{record_id}")
@require_license_api
async def delete_record(
    record_id: str,
    delete_file: bool = False,
    db: Session = Depends(get_session)
):
    """删除录制记录"""
    record = db.query(LiveRecord).filter(LiveRecord.id == record_id).first()
    if not record:
        raise HTTPException(status_code=404, detail="记录不存在")
        
    if delete_file:
        try:
            # 1. 删除主文件
            if record.file_path and os.path.exists(record.file_path):
                os.remove(record.file_path)
                logger.info(f"已删除录制文件: {record.file_path}")

            # 2. 删除转码文件
            if record.converted_path and os.path.exists(record.converted_path):
                os.remove(record.converted_path)
                logger.info(f"已删除转码文件: {record.converted_path}")
            
            # 3. [增强] 删除关联的字幕文件 (.srt) 与弹幕文件
            # 假设字幕文件和录像文件同名但后缀不同
            base_path = os.path.splitext(record.file_path)[0]
            srt_path = base_path + ".srt"
            danmu_path = base_path + ".danmu.jsonl"
            danmu_idx_path = base_path + ".danmu.idx.jsonl"
            if os.path.exists(srt_path):
                os.remove(srt_path)
                logger.info(f"已删除关联字幕: {srt_path}")
            if os.path.exists(danmu_path):
                os.remove(danmu_path)
                logger.info(f"已删除关联弹幕: {danmu_path}")
            if os.path.exists(danmu_idx_path):
                os.remove(danmu_idx_path)
                logger.info(f"已删除关联弹幕索引: {danmu_idx_path}")
                
            # 4. [增强] 尝试清理分段文件 (如果有)
            # 分段文件通常格式为: filename-001.ts, filename-002.ts
            # 或者如果是 mp4 分段，逻辑类似。
            # 我们可以扫描目录下以前缀 matching 的文件
            if record.file_path:
                directory = os.path.dirname(record.file_path)
                filename = os.path.basename(record.file_path)
                # 简单的分段识别逻辑：文件名前缀匹配，且在同一目录下
                # 注意：这需要非常小心，避免误删。
                # 只有当文件名包含时间戳等唯一标识时才比较安全。我们的文件名格式是 {anchor}_{timestamp}.ts
                # 所以前缀匹配是安全的。
                file_prefix = os.path.splitext(filename)[0]
                
                if os.path.exists(directory):
                    for f in os.listdir(directory):
                        # 匹配前缀 (忽略自己)
                        if f.startswith(file_prefix) and f != filename:
                             # 确保只删除相关后缀的文件
                             if f.endswith(('.ts', '.mp4', '.srt', '.json', '.jsonl', '.flv')):
                                 full_path = os.path.join(directory, f)
                                 try:
                                     os.remove(full_path)
                                     logger.info(f"已删除关联分段/文件: {f}")
                                 except: pass

        except Exception as e:
            logger.error(f"删除文件失败: {e}")
            
    db.delete(record)
    db.commit()
    return {"success": True, "message": "删除成功"}


# ==================== 统计信息 ====================

# 统计数据内存缓存 (初始 0)
_stats_data = {
    "total_size": 0,
    "last_update_ts": 0
}

async def _update_live_folder_size_task():
    """后台异步任务：定期使用系统命令获取文件夹大小"""
    import subprocess
    live_path = "/app/downloads/live"
    
    logger.info("已启动直播文件夹大小后台监控任务")
    while True:
        try:
            if os.path.exists(live_path):
                # 使用 Linux du 命令获取字节总数 (-s 汇总, -b 以字节为单位)
                # 这种方式比 Python 递归扫描快几十倍，因为它直接走系统调用
                process = await asyncio.create_subprocess_exec(
                    'du', '-sb', live_path,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE
                )
                stdout, stderr = await process.communicate()
                
                if process.returncode == 0:
                    output = stdout.decode().strip()
                    if output:
                        # 输出格式通常为: "字节数 \t 路径"
                        size_str = output.split()[0]
                        _stats_data["total_size"] = int(size_str)
                        _stats_data["last_update_ts"] = time.time()
                        logger.debug(f"后台统计更新成功: {_stats_data['total_size']} 字节")
            
        except Exception as e:
            logger.error(f"后台更新文件夹大小出错: {e}")
            
        # 每 900 秒（15分钟）更新一次真实磁盘占用，最大程度减少随机 I/O
        await asyncio.sleep(900)

# 在模块加载时启动后台任务
@router.on_event("startup")
async def startup_stats_monitor():
    asyncio.create_task(_update_live_folder_size_task())

@router.get("/stats")
@require_license_api
async def get_live_stats(db: Session = Depends(get_session)):
    """获取直播统计信息 (极速响应版)"""
    try:
        from datetime import date
        today_start = datetime.combine(date.today(), datetime.min.time())
        
        # 数据库查询操作很快
        # 数据库查询操作很快
        total_msg = db.query(LiveSubscription).count()
        live_count = db.query(LiveSubscription).filter(LiveSubscription.is_live == "true").count()
        today_records = db.query(LiveRecord).filter(LiveRecord.start_time >= today_start).count()
        recording_count = len(live_recorder.get_all_recording_ids())
        
        # 磁盘占用直接从内存返回，响应时间 < 1ms
        return {
            "success": True,
            "data": {
                "total_subscriptions": total_msg,
                "live_count": live_count,
                "recording_count": recording_count,
                "today_records": today_records,
                "total_size": _stats_data["total_size"]
            },
            "info": {
                "last_update_ts": _stats_data["last_update_ts"]
            }
        }
    except Exception as e:
        logger.error(f"获取统计失败: {e}")
        return {"success": False, "message": str(e)}


# ==================== 分段录制配置 ====================

@router.put("/subscriptions/{sub_id}/segment")
@require_license_api
async def update_segment_config(
    sub_id: str,
    enabled: str = Query("false"),
    duration: int = Query(3600),
    db: Session = Depends(get_session)
):
    """更新订阅的分段录制配置"""
    sub = db.query(LiveSubscription).filter(LiveSubscription.id == sub_id).first()
    if not sub: raise HTTPException(status_code=404, detail="订阅不存在")
    
    sub.split_enabled = enabled.lower()
    sub.split_duration = max(300, min(86400, duration))
    db.commit()
    
    return {
        "success": True, 
        "message": "分段配置已更新",
        "data": {
            "split_enabled": sub.split_enabled,
            "split_duration": sub.split_duration
        }
    }


# ==================== 字幕生成配置 ====================

@router.put("/subscriptions/{sub_id}/subtitle")
@require_license_api
async def update_subtitle_config(
    sub_id: str,
    enabled: str = Query("false"),
    db: Session = Depends(get_session)
):
    """更新订阅的字幕生成配置"""
    sub = db.query(LiveSubscription).filter(LiveSubscription.id == sub_id).first()
    if not sub: raise HTTPException(status_code=404, detail="订阅不存在")
    
    import json
    extra = json.loads(sub.extra_data) if sub.extra_data else {}
    if isinstance(sub.extra_data, dict): extra = sub.extra_data
    
    extra['generate_subtitle'] = enabled.lower() == "true"
    sub.extra_data = json.dumps(extra)
    db.commit()
    
    return {
        "success": True, 
        "message": "字幕配置已更新", 
        "data": {"generate_subtitle": extra['generate_subtitle']}
    }


# ==================== 视频转码 ====================

def _build_manual_transcode_callback(record_id: str, loop):
    """构建手动转码完成回调，统一更新数据库和前端状态。"""
    def on_transcode_finished(success, mp4_path):
        db_session = None
        try:
            db_session = get_session()
            rec = db_session.query(LiveRecord).filter(LiveRecord.id == record_id).first()
            if not rec:
                return

            if success:
                _apply_transcode_success_to_record(rec, mp4_path)
                rec.status = "completed"
                try:
                    from routers.websocket import broadcast_live_status_update
                    asyncio.run_coroutine_threadsafe(
                        broadcast_live_status_update({
                            "id": record_id,
                            "status": "completed",
                            "converted": "true",
                            "converted_path": mp4_path,
                            "file_path": mp4_path,
                            "format": "mp4",
                            "file_size": rec.file_size,
                            "type": "record_update"
                        }),
                        loop
                    )
                except Exception as ws_err:
                    logger.warning(f"转码完成广播失败: {ws_err}")
            else:
                if rec.status == "converting":
                    rec.status = "failed"
            db_session.commit()
        except Exception as e:
            logger.error(f"转码回调更新数据库失败: {e}")
            if db_session:
                try:
                    db_session.rollback()
                except Exception:
                    pass
        finally:
            if db_session:
                db_session.close()
    return on_transcode_finished


async def _enqueue_record_transcode_task(record: LiveRecord, delete_original: bool, loop) -> bool:
    """统一将录制历史条目加入转码队列，返回是否成功入队。"""
    if not record.file_path:
        raise HTTPException(status_code=400, detail="录制路径为空")

    output_dir = os.path.dirname(record.file_path)
    prefix = os.path.basename(record.file_path).rsplit('.', 1)[0]
    import glob
    segment_files = glob.glob(os.path.join(output_dir, f"{prefix}_[0-9]*.ts"))
    is_segmented = len(segment_files) > 0

    if not is_segmented and not os.path.exists(record.file_path):
        raise HTTPException(status_code=400, detail="源文件不存在")

    task = {
        'subscription_id': record.subscription_id or f"record:{record.id}",
        'output_path': record.file_path,
        'delete_original': delete_original,
        'on_complete': _build_manual_transcode_callback(record.id, loop),
        'type': 'merge' if is_segmented else 'convert',
        'enqueued_at': datetime.now(),
        'task_key': f"record:{record.id}"
    }
    return await live_recorder._enqueue_transcode_task(task)


@router.post("/convert/{record_id}")
@require_license_api
async def convert_to_mp4(
    record_id: str,
    delete_original: bool = True,
    db: Session = Depends(get_session)
):
    """手动转码"""
    record = db.query(LiveRecord).filter(LiveRecord.id == record_id).first()
    if not record:
        raise HTTPException(status_code=404, detail="记录不存在")

    if record.converted == "true":
        return {"success": True, "message": "该记录已完成转码"}

    if record.status == "converting":
        return {"success": True, "message": "该记录正在转码中"}

    loop = asyncio.get_running_loop()
    enqueued = await _enqueue_record_transcode_task(record, delete_original, loop)
    if not enqueued:
        record.status = "converting"
        db.commit()
        return {"success": True, "message": "该记录已在转码队列中"}

    record.status = "converting"
    db.commit()
    return {"success": True, "message": "转码任务已加入队列"}

@router.post("/convert-batch")
@require_license_api
async def batch_convert_to_mp4(
    record_ids: list[str] = Query(...),
    delete_original: bool = True,
    db: Session = Depends(get_session)
):
    """批量转码"""
    count = 0
    skipped = 0
    already_converting = 0
    already_queued = 0
    loop = asyncio.get_running_loop()
    
    for rid in record_ids:
        record = db.query(LiveRecord).filter(LiveRecord.id == rid).first()
        if not record or not record.file_path:
            skipped += 1
            continue
            
        if record.converted == "true":
            skipped += 1
            continue

        if record.status == "converting":
            already_converting += 1
            continue

        try:
            enqueued = await _enqueue_record_transcode_task(record, delete_original, loop)
        except HTTPException:
            skipped += 1
            continue
        except Exception as e:
            logger.error(f"批量转码入队失败: {rid}, 错误: {e}")
            skipped += 1
            continue

        record.status = "converting"
        if enqueued:
            count += 1
        else:
            already_queued += 1
    
    db.commit()
    return {
        "success": True,
        "message": f"已提交 {count} 个转码任务，已在转码中 {already_converting} 个，已在队列中 {already_queued} 个，跳过 {skipped} 个"
    }


@router.post("/convert-unconverted")
@require_license_api
async def convert_unconverted_to_mp4(
    subscription_id: Optional[str] = Query(None),
    delete_original: bool = True,
    db: Session = Depends(get_session)
):
    """一键转码全部未转码记录（可按订阅过滤）"""
    loop = asyncio.get_running_loop()
    count = 0
    skipped = 0
    already_converting = 0
    already_queued = 0

    query = db.query(LiveRecord).filter(
        or_(LiveRecord.converted.is_(None), LiveRecord.converted != "true"),
        LiveRecord.status.in_(["completed", "stopped", "failed"])
    )
    if subscription_id:
        query = query.filter(LiveRecord.subscription_id == subscription_id)

    records = query.order_by(LiveRecord.start_time.desc()).all()
    target_total = len(records)

    for record in records:
        if not record.file_path or not str(record.file_path).lower().endswith('.ts'):
            skipped += 1
            continue

        if record.status == "converting":
            already_converting += 1
            continue

        try:
            enqueued = await _enqueue_record_transcode_task(record, delete_original, loop)
        except HTTPException:
            skipped += 1
            continue
        except Exception as e:
            logger.error(f"全量转码入队失败: {record.id}, 错误: {e}")
            skipped += 1
            continue

        record.status = "converting"
        if enqueued:
            count += 1
        else:
            already_queued += 1

    db.commit()
    return {
        "success": True,
        "message": f"共匹配 {target_total} 条，已提交 {count} 个转码任务，已在转码中 {already_converting} 个，已在队列中 {already_queued} 个，跳过 {skipped} 个"
    }


@router.get("/convert-unconverted/count")
@require_license_api
async def get_unconverted_count(
    subscription_id: Optional[str] = Query(None),
    db: Session = Depends(get_session)
):
    """获取待转码记录数量（可按订阅过滤）"""
    query = db.query(LiveRecord).filter(
        or_(LiveRecord.converted.is_(None), LiveRecord.converted != "true"),
        LiveRecord.status.in_(["completed", "stopped", "failed"]),
        LiveRecord.file_path.isnot(None),
        LiveRecord.file_path.ilike('%.ts')
    )
    if subscription_id:
        query = query.filter(LiveRecord.subscription_id == subscription_id)

    count = query.count()
    return {
        "success": True,
        "data": {
            "count": count,
            "subscription_id": subscription_id
        }
    }


# ==================== 高级配置 ====================

@router.get("/subscriptions/{sub_id}/config")
@require_license_api
async def get_subscription_config(sub_id: str, db: Session = Depends(get_session)):
    """获取订阅的完整录制配置"""
    sub = db.query(LiveSubscription).filter(LiveSubscription.id == sub_id).first()
    if not sub: raise HTTPException(status_code=404)
    
    # 解析 extra_data
    extra = {}
    if sub.extra_data:
        try:
            extra = json.loads(sub.extra_data) if isinstance(sub.extra_data, str) else sub.extra_data
            if not isinstance(extra, dict): extra = {}
        except: 
            extra = {}
            
    # 【重要】保持与旧版API一致，返回字符串 "true"/"false" 而非布尔值
    # 前端可能依赖字符串值进行显示判断
    return {
        "success": True,
        "data": {
            "quality": sub.quality,
            "auto_record": sub.auto_record, # 返回原始字符串
            "monitor_enabled": getattr(sub, "monitor_enabled", None) or "true",
            "check_interval": sub.check_interval,
            "output_format": sub.output_format,
            "split_enabled": sub.split_enabled, # 返回原始字符串
            "split_duration": sub.split_duration,
            "max_duration": sub.max_duration,
            "notification_enabled": sub.notification_enabled,
            "proxy": sub.proxy,
            "generate_subtitle": extra.get('generate_subtitle', False),
            "auto_convert_mp4": extra.get('auto_convert_mp4', True),
            "danmu_enabled": extra.get('danmu_enabled', False)
        }
    }


@router.put("/subscriptions/{sub_id}/config")
@require_license_api
async def update_subscription_config(
    sub_id: str,
    quality: Optional[str] = Query(None),
    auto_record: Optional[str] = Query(None),
    monitor_enabled: Optional[str] = Query(None),
    check_interval: Optional[int] = Query(None),
    output_format: Optional[str] = Query(None),
    split_enabled: Optional[str] = Query(None),
    split_duration: Optional[int] = Query(None),
    max_duration: Optional[int] = Query(None),
    generate_subtitle: Optional[str] = Query(None),
    auto_convert_mp4: Optional[str] = Query(None),
    danmu_enabled: Optional[str] = Query(None),
    compat_mode: Optional[str] = Query(None),
    notification_enabled: Optional[str] = Query(None),
    db: Session = Depends(get_session)
):
    """更新订阅的录制配置"""
    sub = db.query(LiveSubscription).filter(LiveSubscription.id == sub_id).first()
    if not sub: raise HTTPException(status_code=404, detail="订阅不存在")
    
    prev_auto_record = (sub.auto_record or "").lower()
    prev_monitor_enabled = (getattr(sub, "monitor_enabled", "true") or "true").lower()
    
    # 更新基础配置
    if quality is not None:
        sub.quality = quality
    if auto_record is not None:
        sub.auto_record = auto_record.lower()
    if monitor_enabled is not None:
        sub.monitor_enabled = "true" if monitor_enabled.lower() in ('true', '1', 'yes', 'on') else "false"
    if check_interval is not None:
        sub.check_interval = max(10, min(3600, check_interval))
    if output_format is not None:
        sub.output_format = output_format
        
    if notification_enabled is not None:
        sub.notification_enabled = "true" if notification_enabled.lower() in ('true', '1', 'yes', 'on') else "false"
        
    if split_enabled is not None:
        sub.split_enabled = split_enabled.lower()
    if split_duration is not None:
        sub.split_duration = max(300, min(86400, split_duration))
    if max_duration is not None:
        sub.max_duration = max_duration if max_duration > 0 else None
        
    # 更新扩展配置
    import json
    extra = {}
    if sub.extra_data:
        try:
            extra = json.loads(sub.extra_data) if isinstance(sub.extra_data, str) else sub.extra_data
            if not isinstance(extra, dict): extra = {}
        except: extra = {}
        
    if generate_subtitle is not None:
        extra['generate_subtitle'] = str(generate_subtitle).lower() == "true"
    if auto_convert_mp4 is not None:
        extra['auto_convert_mp4'] = str(auto_convert_mp4).lower() == "true"
    if danmu_enabled is not None:
        extra['danmu_enabled'] = str(danmu_enabled).lower() == "true"
    if compat_mode is not None:
        extra['compat_mode'] = str(compat_mode).lower() == "true"
        
    sub.extra_data = json.dumps(extra)
    sub.updated_at = datetime.now()
    db.commit()
    
    logger.info(f"更新订阅配置: {sub.anchor_name}")
    
    # 【重要】动态更新监控状态 (参考旧版逻辑)
    try:
        # 获取当前录制状态
        is_recording = live_recorder.is_recording(sub_id)
        
        if is_recording:
            # 情况1: 正在录制中
            # 修改参数不要停止当前的录像操作，因此不重启监控任务
            if (getattr(sub, "monitor_enabled", "true") or "true").lower() == "false":
                await live_scheduler.remove_monitor(sub_id, stop_recording=False)
                logger.info(f"订阅 {sub_id} 正在录制中，已暂停周期检测但保留当前录制")
            else:
                logger.info(f"订阅 {sub_id} 正在录制中，跳过调度器更新以保持录制连贯性")
        else:
            if (getattr(sub, "monitor_enabled", "true") or "true").lower() == "false":
                await live_scheduler.remove_monitor(sub_id, stop_recording=False)
                logger.info(f"已暂停周期检测: {sub.anchor_name}")
            else:
                await live_scheduler.remove_monitor(sub_id, stop_recording=False)
                await live_scheduler.add_monitor(
                    sub.id,
                    sub.room_url,
                    sub.platform,
                    sub.check_interval
                )
                logger.info(f"已更新监控: {sub.anchor_name}, 间隔={sub.check_interval}")

            # 如果刚开启自动录制，立即触发一次检测
            monitor_now_enabled = (getattr(sub, "monitor_enabled", "true") or "true").lower() != "false"
            if (
                monitor_now_enabled
                and prev_monitor_enabled == "false"
                and (sub.auto_record or "").lower() == "true"
            ) or (
                monitor_now_enabled
                and prev_auto_record != "true"
                and (sub.auto_record or "").lower() == "true"
            ):
                try:
                    await live_scheduler.trigger_immediate_check(sub.id)
                except Exception as immediate_err:
                    logger.warning(
                        f"单个订阅更新后立即检查失败（将由常规轮询接管）: {sub.id}, {immediate_err}"
                    )
                
    except Exception as e:
        logger.error(f"更新调度器状态失败: {e}")
        
    return {"success": True, "message": "配置已更新"}
