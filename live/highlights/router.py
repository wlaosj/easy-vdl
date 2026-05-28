# -*- coding: utf-8 -*-
"""AI 高光切片 V1 API。"""

import asyncio
import hashlib
import json
import logging
import os
import re
import subprocess
import threading
import uuid
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import ValidationError
from sqlalchemy.orm import Session

from routers.auth import get_current_user_or_token, require_lifetime_license_api
from routers.websocket import broadcast_message
from sql.database_postgresql import get_session
from sql.models import LiveRecord, User, LiveSubscription
import concurrent.futures
import time

from .llm import (
    _validate_chat_config,
    maybe_enrich_segments_with_llm,
    maybe_scout_segments_with_l1,
    resolve_chat_config_for_source,
    resolve_chat_config_from_model_config,
)
from .asr import build_asr_config, transcribe_segments
from .pipeline import (
    build_segments_from_danmu_file,
    collect_segment_comments_from_danmu_file,
    iter_danmu_events_stream,
    probe_first_event_ts,
)
from .schemas import (
    AnalyzeRequest,
    AnalyzeResponse,
    AnalyzeTaskStatusResponse,
    AnalyzeTaskSubmitResponse,
    BundleRequest,
    CleanupResponse,
    ExportRequest,
    ExportResponse,
    HighlightSegment,
    ManualClipCleanupResponse,
    ManualClipItem,
    ManualClipListResponse,
    ManualExportRequest,
    ManualExportResponse,
    SegmentDanmuItem,
    SegmentDanmuResponse,
    StreamerCleanupResponse,
)
from .request_utils import apply_story_fallback, normalize_analyze_request
from .storage import (
    clear_record_artifacts,
    export_segments,
    load_analysis,
    load_segment_danmu,
    resolve_analysis_path,
    resolve_artifact_dir,
    resolve_danmu_path,
    resolve_manual_clip_dir,
    resolve_record_id,
    resolve_segment_danmu_path,
    resolve_storyline_json_path,
    resolve_storyline_srt_path,
    resolve_task_status_path,
    save_analysis,
    save_segment_danmu,
)
from .storage import load_task_status, save_task_status
from .storage import export_story_assets
from .task_status import (
    TASK_ACTIVE_STATUSES,
    TASK_STATUS_CANCELLED,
    TASK_STATUS_FAILED,
    TASK_STATUS_QUEUED,
    TASK_STATUS_RUNNING,
    TASK_STATUS_SUCCESS,
    normalize_task_status,
)

logger = logging.getLogger(__name__)

router = APIRouter()

_ANALYZE_TASKS: Dict[str, Dict] = {}
_TASKS_LOCK = threading.Lock()
_TASK_STALE_SECONDS = 1800
_RECORD_STATUS_WS_CHANNEL = "live_highlights_records"
_TIMELINE_BASE_WARN_DIFF_SECONDS = 45
_TIMELINE_BASE_FALLBACK_DIFF_SECONDS = 6 * 3600
_STRICT_LLM_MIN_DECISION_SCORE = 0.45
_STRICT_LLM_STRONG_DECISION_SCORE = 0.62
_STRICT_HARD_NEGATIVE_REASONS = {"tech_issue", "shopping_query", "greeting", "spam", "off_topic"}


class AnalysisCancelled(Exception):
    """Raised when an async highlight analysis task is cancelled by the user."""


def _now_iso() -> str:
    return datetime.now().isoformat()


def _ws_channel(record_id: str) -> str:
    return f"live_highlights:{record_id}"


def _analysis_base_path(record: LiveRecord, source_video_path: str) -> str:
    return source_video_path or record.file_path or record.converted_path or ""


def _record_path_candidates(record: LiveRecord, source_video_path: Optional[str] = None) -> List[str]:
    paths: List[str] = []
    for path in (source_video_path, record.file_path, record.converted_path):
        text = str(path or "").strip()
        if text and text not in paths:
            paths.append(text)
    return paths


def _pick_existing_artifact_base_path(record: LiveRecord, source_video_path: Optional[str] = None) -> str:
    for base_path in _record_path_candidates(record, source_video_path):
        if os.path.exists(resolve_analysis_path(base_path)) or os.path.exists(resolve_task_status_path(base_path)):
            return base_path
    paths = _record_path_candidates(record, source_video_path)
    return paths[0] if paths else ""


def _path_exists_file(path: str) -> bool:
    return bool(path and os.path.isfile(path))


def _append_unique_path(paths: List[str], path: Any) -> None:
    text = str(path or "").strip()
    if text and text not in paths:
        paths.append(text)


def _resolve_danmu_range_paths(record: LiveRecord) -> Tuple[str, str]:
    """Resolve an existing video path and danmu path for editor preview.

    Older/manual transcode flows may leave record.file_path pointing at a
    deleted TS while converted_path and highlight artifacts point at the MP4.
    """
    video_candidates: List[str] = []
    danmu_candidates: List[str] = []

    for path in (record.file_path, record.converted_path):
        _append_unique_path(video_candidates, path)
        if path:
            _append_unique_path(danmu_candidates, resolve_danmu_path(str(path)))

    analysis_base_path = _pick_existing_artifact_base_path(record)
    payload = load_analysis(analysis_base_path) if analysis_base_path else None
    if payload:
        _append_unique_path(video_candidates, payload.get("video_path"))
        _append_unique_path(danmu_candidates, payload.get("danmu_path"))
        video_path = str(payload.get("video_path") or "").strip()
        if video_path:
            _append_unique_path(danmu_candidates, resolve_danmu_path(video_path))

    existing_video = next((path for path in video_candidates if _path_exists_file(path)), "")
    existing_danmu = next((path for path in danmu_candidates if _path_exists_file(path)), "")

    if not existing_video:
        logger.warning(
            "highlights.danmu_range.video_missing record_id=%s candidates=%s",
            getattr(record, "id", ""),
            video_candidates,
        )
        raise HTTPException(status_code=404, detail="录制文件不存在")

    if not existing_danmu:
        logger.warning(
            "highlights.danmu_range.danmu_missing record_id=%s video_path=%s candidates=%s",
            getattr(record, "id", ""),
            existing_video,
            danmu_candidates,
        )
        raise HTTPException(status_code=404, detail="弹幕文件不存在")

    return existing_video, existing_danmu


def _resolve_timeline_base_ts(record: LiveRecord, danmu_path: str) -> Optional[float]:
    """优先使用弹幕首条时间作为时间轴基准，必要时告警并回退。"""
    record_start_ts: Optional[float] = None
    if record.start_time:
        try:
            record_start_ts = float(record.start_time.timestamp())
        except Exception:
            record_start_ts = None

    danmu_first_ts = probe_first_event_ts(danmu_path)
    if danmu_first_ts is None:
        if record_start_ts is not None:
            logger.info(
                "highlights.timeline_base source=record_start record_ts=%.3f reason=danmu_first_missing",
                record_start_ts,
            )
        return record_start_ts

    if record_start_ts is not None:
        diff = float(danmu_first_ts) - float(record_start_ts)
        abs_diff = abs(diff)
        if abs_diff > _TIMELINE_BASE_WARN_DIFF_SECONDS:
            logger.warning(
                "highlights.timeline_base.diff record_ts=%.3f danmu_first_ts=%.3f diff_sec=%.3f",
                record_start_ts,
                danmu_first_ts,
                diff,
            )
        if abs_diff > _TIMELINE_BASE_FALLBACK_DIFF_SECONDS:
            logger.warning(
                "highlights.timeline_base.fallback source=record_start reason=diff_too_large diff_sec=%.3f threshold=%.1f",
                diff,
                float(_TIMELINE_BASE_FALLBACK_DIFF_SECONDS),
            )
            return record_start_ts

    logger.info(
        "highlights.timeline_base source=danmu_first danmu_first_ts=%.3f record_ts=%s",
        float(danmu_first_ts),
        ("%.3f" % record_start_ts) if record_start_ts is not None else "none",
    )
    return float(danmu_first_ts)




_SEGMENT_DANMU_MAX_EVENTS = 220


def _extract_text_direct(obj: dict) -> str:
    content = obj.get("content")
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, dict):
        for key in ("text", "content", "message", "msg"):
            val = content.get(key)
            if isinstance(val, str) and val.strip():
                return val.strip()
    for key in ("text", "message", "msg"):
        val = obj.get(key)
        if isinstance(val, str) and val.strip():
            return val.strip()
    return ""


def _extract_uid_direct(obj: dict) -> str:
    user = obj.get("user")
    if isinstance(user, dict):
        for key in ("id", "uid", "sec_uid", "short_id", "nickname"):
            val = user.get(key)
            if val is not None:
                s = str(val).strip()
                if s:
                    return s
    return "anonymous"


def _sample_events_evenly(items: List[Dict], limit: int) -> List[Dict]:
    if limit <= 0 or len(items) <= limit:
        return list(items)
    if limit == 1:
        return [items[-1]]
    step = (len(items) - 1) / float(limit - 1)
    sampled: List[Dict] = []
    for i in range(limit):
        sampled.append(items[int(round(i * step))])
    return sampled


def _extract_segment_danmu_entries(
    *,
    segment: Dict,
    events: List,
    base_ts: float,
    danmu_delay_compensation_seconds: int = 0,
    max_events: int = _SEGMENT_DANMU_MAX_EVENTS,
) -> Dict:
    start_sec = float(segment.get("start_sec") or 0.0)
    end_sec = float(segment.get("end_sec") or 0.0)
    if end_sec < start_sec:
        start_sec, end_sec = end_sec, start_sec
    abs_start = base_ts + start_sec
    abs_end = base_ts + end_sec

    rows: List[Dict] = []
    delay = float(max(0, int(danmu_delay_compensation_seconds or 0)))
    for ev in events:
        ts = float(getattr(ev, "ts", 0.0) or 0.0)
        effective_ts = ts - delay
        if effective_ts < abs_start:
            continue
        if effective_ts > abs_end:
            break
        rows.append(
            {
                "event_type": str(getattr(ev, "event_type", "") or "chat"),
                "sec": round(effective_ts - base_ts, 3),
                "offset_sec": round(effective_ts - abs_start, 3),
                "uid": str(getattr(ev, "uid", "") or ""),
                "text": str(getattr(ev, "text", "") or ""),
            }
        )

    total_events = len(rows)
    sampled = _sample_events_evenly(rows, max_events)
    truncated = total_events > len(sampled)
    return {
        "segment_id": str(segment.get("id") or ""),
        "start_sec": round(start_sec, 3),
        "end_sec": round(end_sec, 3),
        "total_events": total_events,
        "included_events": len(sampled),
        "truncated": truncated,
        "events": sampled,
    }


def _build_segment_danmu_snapshot(
    *,
    record_id: str,
    source_video_path: str,
    danmu_path: str,
    analyzed_at: str,
    segments: List[Dict],
    events: List,
    timeline_base_ts: Optional[float],
    danmu_delay_compensation_seconds: int = 0,
    max_events: int = _SEGMENT_DANMU_MAX_EVENTS,
) -> Dict:
    if events:
        base_ts = float(timeline_base_ts) if timeline_base_ts is not None else float(getattr(events[0], "ts", 0.0) or 0.0)
    else:
        base_ts = float(timeline_base_ts) if timeline_base_ts is not None else 0.0

    items = [
        _extract_segment_danmu_entries(
            segment=seg,
            events=events,
            base_ts=base_ts,
            danmu_delay_compensation_seconds=danmu_delay_compensation_seconds,
            max_events=max_events,
        )
        for seg in segments
    ]
    return {
        "record_id": record_id,
        "video_path": source_video_path,
        "danmu_path": danmu_path,
        "analyzed_at": analyzed_at,
        "base_ts": base_ts,
        "max_events_per_segment": int(max_events),
        "segments": items,
    }


def _build_segment_danmu_snapshot_from_file(
    *,
    record_id: str,
    source_video_path: str,
    danmu_path: str,
    analyzed_at: str,
    segments: List[Dict],
    timeline_base_ts: Optional[float],
    danmu_delay_compensation_seconds: int = 0,
    max_events: int = _SEGMENT_DANMU_MAX_EVENTS,
) -> Dict:
    base_ts = float(timeline_base_ts) if timeline_base_ts is not None else probe_first_event_ts(danmu_path)
    if base_ts is None:
        base_ts = 0.0

    windows = []
    for seg in segments:
        start_sec = float(seg.get("start_sec") or 0.0)
        end_sec = float(seg.get("end_sec") or 0.0)
        if end_sec < start_sec:
            start_sec, end_sec = end_sec, start_sec
        seg_id = str(seg.get("id") or "")
        if not seg_id:
            continue
        windows.append(
            {
                "segment_id": seg_id,
                "start_sec": round(start_sec, 3),
                "end_sec": round(end_sec, 3),
                "abs_start": base_ts + start_sec,
                "abs_end": base_ts + end_sec,
            }
        )
    windows.sort(key=lambda x: x["abs_start"])

    holder: Dict[str, Dict] = {
        w["segment_id"]: {
            "segment_id": w["segment_id"],
            "start_sec": w["start_sec"],
            "end_sec": w["end_sec"],
            "rows": [],
        }
        for w in windows
    }

    active: List[int] = []
    ptr = 0
    delay = float(max(0, int(danmu_delay_compensation_seconds or 0)))

    for ev in iter_danmu_events_stream(danmu_path):
        ts = float(getattr(ev, "ts", 0.0) or 0.0)
        effective_ts = ts - delay
        while ptr < len(windows) and windows[ptr]["abs_start"] <= effective_ts:
            active.append(ptr)
            ptr += 1
        if not active:
            continue

        next_active: List[int] = []
        for idx in active:
            win = windows[idx]
            if effective_ts > float(win["abs_end"]):
                continue
            next_active.append(idx)
            if effective_ts < float(win["abs_start"]):
                continue
            slot = holder.get(str(win["segment_id"]))
            if slot is None:
                continue
            slot["rows"].append(
                {
                    "event_type": str(getattr(ev, "event_type", "") or "chat"),
                    "sec": round(effective_ts - base_ts, 3),
                    "offset_sec": round(effective_ts - float(win["abs_start"]), 3),
                    "uid": str(getattr(ev, "uid", "") or ""),
                    "text": str(getattr(ev, "text", "") or ""),
                }
            )
        active = next_active
        if ptr >= len(windows) and not active:
            break

    items: List[Dict] = []
    for win in windows:
        seg_id = str(win["segment_id"])
        rows = list((holder.get(seg_id) or {}).get("rows") or [])
        sampled = _sample_events_evenly(rows, max_events)
        items.append(
            {
                "segment_id": seg_id,
                "start_sec": float(win["start_sec"]),
                "end_sec": float(win["end_sec"]),
                "total_events": len(rows),
                "included_events": len(sampled),
                "truncated": len(rows) > len(sampled),
                "events": sampled,
            }
        )

    return {
        "record_id": record_id,
        "video_path": source_video_path,
        "danmu_path": danmu_path,
        "analyzed_at": analyzed_at,
        "base_ts": float(base_ts),
        "danmu_delay_compensation_seconds": int(delay),
        "max_events_per_segment": int(max_events),
        "segments": items,
    }


def _is_stale_task(task: Dict) -> bool:
    status = str(task.get("status") or "")
    if status not in TASK_ACTIVE_STATUSES:
        return False
    updated_at = str(task.get("updated_at") or "").strip()
    if not updated_at:
        return True
    try:
        dt = datetime.fromisoformat(updated_at)
    except Exception:
        return True
    age = (datetime.now() - dt).total_seconds()
    return age > _TASK_STALE_SECONDS


def _must_get_record(record_id: str, db: Session) -> LiveRecord:
    record = db.query(LiveRecord).filter(LiveRecord.id == record_id).first()
    if not record:
        raise HTTPException(status_code=404, detail="录制记录不存在")
    return record


def _resolve_source_video_path(record: LiveRecord) -> str:
    """优先使用存在的原始文件，其次回退已转码文件。"""
    candidates = []
    if record.file_path:
        candidates.append(record.file_path)
    if record.converted_path:
        candidates.append(record.converted_path)

    for path in candidates:
        if path and os.path.exists(path):
            return path
    raise HTTPException(status_code=400, detail="录制文件不存在，无法分析")


def _sanitize_filename_component(value: str) -> str:
    text = str(value or "").strip()
    if not text:
        return "bundle"
    text = re.sub(r"\s+", "_", text)
    text = re.sub(r'[\\/:*?"<>|]+', "_", text)
    text = re.sub(r"_+", "_", text).strip("._")
    return text[:40] or "bundle"


def _add_file_to_zip(zf: zipfile.ZipFile, abs_path: str, arcname: str) -> bool:
    path = Path(abs_path)
    if not path.exists() or not path.is_file():
        return False
    zf.write(str(path), arcname=arcname)
    return True


def _build_bundle_zip(
    *,
    zip_path: str,
    selected_with_clip: List[dict],
    segment_danmu_path: str,
    storyline_json_path: str,
    manifest: Dict,
) -> int:
    """在线程中执行 ZIP 打包，导出按片段独立子目录结构。"""
    danmu_by_seg: Dict[str, Dict] = {}
    if segment_danmu_path and Path(segment_danmu_path).is_file():
        try:
            with open(segment_danmu_path, "r", encoding="utf-8") as fh:
                danmu_all = json.load(fh)
            for item in (danmu_all.get("segments") or []):
                sid = str(item.get("segment_id") or "")
                if sid:
                    danmu_by_seg[sid] = item
        except Exception:
            pass

    story_by_seg: Dict[str, Dict] = {}
    _storyline_path = str(storyline_json_path or "")
    if _storyline_path and Path(_storyline_path).is_file():
        try:
            with open(_storyline_path, "r", encoding="utf-8") as fh:
                story_all = json.load(fh)
            for item in (story_all.get("segments") or []):
                sid = str(item.get("id") or "")
                if sid:
                    story_by_seg[sid] = item
        except Exception:
            pass

    added_count = 0
    manifest_segments: List[Dict[str, str]] = []

    with zipfile.ZipFile(str(zip_path), "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for idx, seg in enumerate(selected_with_clip, start=1):
            clip_path = str(seg.get("clip_path") or "")
            full_seg_id = str(seg.get("id") or "")
            seg_id_short = full_seg_id[:8]
            dir_name = f"clip_{idx:02d}_{seg_id_short or 'seg'}"

            manifest_segments.append({
                "dir": dir_name,
                "segment_id": full_seg_id,
                "title": str(seg.get("title") or ""),
            })

            if _add_file_to_zip(zf, clip_path, f"{dir_name}/clip.mp4"):
                added_count += 1

            seg_danmu = danmu_by_seg.get(full_seg_id)
            if seg_danmu:
                zf.writestr(
                    f"{dir_name}/danmu.json",
                    json.dumps(seg_danmu, ensure_ascii=False, indent=2),
                )
                added_count += 1

            seg_story = story_by_seg.get(full_seg_id)
            if seg_story:
                zf.writestr(
                    f"{dir_name}/storyline.json",
                    json.dumps(seg_story, ensure_ascii=False, indent=2),
                )
                added_count += 1

        manifest["segments"] = manifest_segments
        zf.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
        added_count += 1

    return added_count


def _task_snapshot(task_id: str) -> Optional[Dict]:
    with _TASKS_LOCK:
        task = _ANALYZE_TASKS.get(task_id)
        return dict(task) if task else None


def _task_update(task_id: str, persist: bool = True, **kwargs) -> Optional[Dict]:
    with _TASKS_LOCK:
        task = _ANALYZE_TASKS.get(task_id)
        if not task:
            return None
        if task.get("cancel_requested") and task.get("status") == TASK_STATUS_CANCELLED:
            kwargs = {
                key: value
                for key, value in kwargs.items()
                if key in {"cancel_requested", "status", "message", "error", "progress"}
            }
        task.update(kwargs)
        task["updated_at"] = _now_iso()
        snapshot = dict(task)
    if snapshot.get("cancel_requested") and snapshot.get("status") == TASK_STATUS_CANCELLED:
        persist = False
    if persist:
        base_path = snapshot.get("analysis_base_path")
        if base_path:
            save_task_status(base_path, snapshot)
    return snapshot


def _task_store(task: Dict, persist: bool = True) -> Dict:
    snapshot = dict(task)
    with _TASKS_LOCK:
        _ANALYZE_TASKS[snapshot["task_id"]] = snapshot
    if persist and snapshot.get("analysis_base_path"):
        save_task_status(snapshot["analysis_base_path"], snapshot)
    return snapshot


def _reconcile_persisted_task(analysis_base_path: str, task: Optional[Dict]) -> Optional[Dict]:
    """修正落盘任务状态，避免服务重启后前端长期卡在 running。"""
    if not task:
        return None
    snapshot = dict(task)
    status = normalize_task_status(str(snapshot.get("status") or TASK_STATUS_FAILED))
    snapshot["status"] = status
    if status not in TASK_ACTIVE_STATUSES:
        return snapshot

    task_id = str(snapshot.get("task_id") or "")
    memory_task = _task_snapshot(task_id) if task_id else None
    if memory_task and str(memory_task.get("status") or "") in TASK_ACTIVE_STATUSES:
        return memory_task

    stale = _is_stale_task(snapshot)
    snapshot["status"] = TASK_STATUS_FAILED
    snapshot["progress"] = 100
    snapshot["updated_at"] = _now_iso()
    if stale:
        snapshot["message"] = "上次任务超时未完成，已自动结束"
        snapshot["error"] = "stale_task"
    else:
        snapshot["message"] = "任务因服务重启或中断已结束，请重试"
        snapshot["error"] = "orphan_task"
    save_task_status(analysis_base_path, snapshot)
    logger.warning(
        "highlights.analyze.reconcile_orphan_task record_id=%s task_id=%s stale=%s",
        snapshot.get("record_id"),
        task_id,
        stale,
    )
    return snapshot


def _find_running_task(record_id: str) -> Optional[Dict]:
    with _TASKS_LOCK:
        for task in _ANALYZE_TASKS.values():
            if task.get("record_id") == record_id and task.get("status") in TASK_ACTIVE_STATUSES:
                return dict(task)
    return None


def _is_task_cancel_requested(task_id: str) -> bool:
    task = _task_snapshot(task_id)
    return bool(task and (task.get("cancel_requested") or task.get("status") == TASK_STATUS_CANCELLED))


def _raise_if_task_cancelled(task_id: str) -> None:
    if _is_task_cancel_requested(task_id):
        raise AnalysisCancelled("分析已被用户终止")


def _drop_record_tasks(record_id: str) -> int:
    removed = 0
    with _TASKS_LOCK:
        target_ids = [task_id for task_id, task in _ANALYZE_TASKS.items() if task.get("record_id") == record_id]
        for task_id in target_ids:
            _ANALYZE_TASKS.pop(task_id, None)
            removed += 1
    return removed


def _cleanup_record_artifacts(record: LiveRecord) -> Dict[str, int]:
    base_paths: List[str] = []
    if record.file_path:
        base_paths.append(record.file_path)
    if record.converted_path and record.converted_path not in base_paths:
        base_paths.append(record.converted_path)

    removed_files = 0
    removed_dirs = 0
    freed_bytes = 0
    cleanup_errors: List[str] = []

    for base_path in base_paths:
        try:
            stats = clear_record_artifacts(base_path)
            removed_files += int(stats.get("removed_files") or 0)
            removed_dirs += int(stats.get("removed_dirs") or 0)
            freed_bytes += int(stats.get("freed_bytes") or 0)
        except Exception as exc:
            cleanup_errors.append(str(exc))

    if cleanup_errors:
        logger.warning("highlights.cleanup.failed record_id=%s errors=%s", record.id, cleanup_errors[:2])
        raise HTTPException(status_code=500, detail="清理失败，请检查目录权限后重试")

    return {
        "removed_files": removed_files,
        "removed_dirs": removed_dirs,
        "freed_bytes": freed_bytes,
    }


async def _broadcast_task(task: Dict, event_type: str) -> None:
    payload = {
        "type": event_type,
        "task_id": task.get("task_id"),
        "record_id": task.get("record_id"),
        "stream_type": task.get("stream_type") or "",
        "story_enabled": bool(task.get("story_enabled") or False),
        "status": task.get("status"),
        "progress": int(task.get("progress") or 0),
        "message": task.get("message") or "",
        "segment_count": int(task.get("segment_count") or 0),
        "analyzed_at": task.get("analyzed_at") or "",
        "error": task.get("error"),
        "updated_at": task.get("updated_at") or _now_iso(),
    }
    await broadcast_message(_ws_channel(str(task.get("record_id") or "")), payload)


async def _broadcast_record_status(
    *,
    record_id: str,
    highlights_status: str,
    has_highlights_analysis: Optional[bool] = None,
) -> None:
    if not record_id:
        return
    payload: Dict[str, object] = {
        "type": "highlights_record_status_update",
        "record_id": str(record_id),
        "highlights_status": str(highlights_status or ""),
        "timestamp": _now_iso(),
    }
    if has_highlights_analysis is not None:
        payload["has_highlights_analysis"] = bool(has_highlights_analysis)
    await broadcast_message(_RECORD_STATUS_WS_CHANNEL, payload)


def _broadcast_record_status_threadsafe(
    loop: asyncio.AbstractEventLoop,
    *,
    record_id: str,
    highlights_status: str,
    has_highlights_analysis: Optional[bool] = None,
) -> None:
    if not loop or not loop.is_running():
        return
    try:
        asyncio.run_coroutine_threadsafe(
            _broadcast_record_status(
                record_id=record_id,
                highlights_status=highlights_status,
                has_highlights_analysis=has_highlights_analysis,
            ),
            loop,
        )
    except Exception:
        pass


def _broadcast_task_threadsafe(loop: asyncio.AbstractEventLoop, task: Dict, event_type: str) -> None:
    if not loop or not loop.is_running():
        return
    try:
        asyncio.run_coroutine_threadsafe(_broadcast_task(task, event_type), loop)
    except Exception:
        pass


def _task_to_status_response(task: Dict) -> AnalyzeTaskStatusResponse:
    return AnalyzeTaskStatusResponse(
        success=True,
        task_id=str(task.get("task_id") or ""),
        record_id=str(task.get("record_id") or ""),
        status=normalize_task_status(str(task.get("status") or TASK_STATUS_FAILED)),
        stream_type=str(task.get("stream_type") or ""),
        story_enabled=bool(task.get("story_enabled") or False),
        progress=int(task.get("progress") or 0),
        message=task.get("message") or "",
        segment_count=int(task.get("segment_count") or 0),
        analyzed_at=task.get("analyzed_at") or "",
        error=task.get("error"),
        created_at=task.get("created_at") or "",
        updated_at=task.get("updated_at") or "",
    )


def _run_cancel_checker(cancel_checker: Optional[Callable[[], None]]) -> None:
    if cancel_checker:
        cancel_checker()


# 规则预过滤阈值：低于此分数的候选在 ASR/LLM 之前直接淘汰
_RULE_PREFILTER_MIN_SCORE = 0.15


def _prefilter_rule_segments(
    segments: List[Dict[str, Any]],
    min_score: float = _RULE_PREFILTER_MIN_SCORE,
) -> List[Dict[str, Any]]:
    """在 ASR/LLM 之前过滤掉规则得分过低的候选，减少不必要的 ASR 转写。

    对于 llm_required 模式，预过滤更激进（min_score * 1.5），因为 LLM 会进一步筛选。
    """
    if not segments:
        return segments

    original_count = len(segments)
    # 过滤：保留 score >= min_score 的候选
    filtered = [seg for seg in segments if float(seg.get("score", 0)) >= min_score]

    dropped = original_count - len(filtered)
    if dropped > 0:
        logger.info(
            "highlights.rule_prefilter dropped=%s/%s min_score=%.2f",
            dropped,
            original_count,
            min_score,
        )

    # 如果过滤后为空，返回原始列表（避免完全没结果）
    if not filtered:
        logger.warning("highlights.rule_prefilter.empty_after_filter count=%s", original_count)
        return segments

    return filtered


def _build_rule_candidates(
    *,
    record_id: str,
    request: AnalyzeRequest,
    danmu_path: str,
    timeline_base_ts: Optional[float],
    progress_callback: Optional[Callable[[int, int, str], None]] = None,
    cancel_checker: Optional[Callable[[], None]] = None,
) -> Tuple[List[Dict[str, Any]], int, int]:
    strategy = str(request.analysis_strategy or "hybrid").strip().lower()
    ai_decision_mode = strategy == "llm_required"
    rule_max_candidates = int(request.max_candidates or 1)
    if ai_decision_mode:
        # 在严格 LLM 模式下扩大召回池，把“取舍”交给 L1/L2。
        rule_max_candidates = min(120, max(rule_max_candidates * 6, rule_max_candidates + 8))

    segment_build_result = build_segments_from_danmu_file(
        danmu_path,
        timeline_base_ts=timeline_base_ts,
        highlight_type=request.highlight_type,
        window_seconds=request.window_seconds,
        max_candidates=rule_max_candidates,
        danmu_delay_compensation_seconds=request.danmu_delay_compensation_seconds,
        pre_padding_seconds=request.pre_padding_seconds,
        post_padding_seconds=request.post_padding_seconds,
        seed=request.seed,
        randomness=request.randomness,
        ai_decision_mode=ai_decision_mode,
    )
    raw_event_count = int(segment_build_result.get("raw_events") or 0)
    cleaned_event_count = int(segment_build_result.get("cleaned_events") or 0)
    if raw_event_count <= 0:
        logger.warning("highlights.analyze.empty_danmu record_id=%s danmu_path=%s", record_id, danmu_path)
        raise HTTPException(status_code=400, detail="弹幕文件为空，暂时无法分析")

    _run_cancel_checker(cancel_checker)
    logger.info(
        "highlights.analyze.events record_id=%s raw=%s cleaned=%s",
        record_id,
        raw_event_count,
        cleaned_event_count,
    )

    segments = list(segment_build_result.get("segments") or [])
    logger.info(
        "highlights.analyze.rule_segments record_id=%s count=%s ai_decision_mode=%s rule_max_candidates=%s",
        record_id,
        len(segments),
        ai_decision_mode,
        rule_max_candidates,
    )
    if progress_callback and segments:
        progress_callback(0, len(segments), "候选已生成")
    return segments, raw_event_count, cleaned_event_count


def _run_llm_enhancement_pipeline(
    *,
    db: Session,
    request: AnalyzeRequest,
    danmu_path: str,
    timeline_base_ts: Optional[float],
    segments: List[Dict[str, Any]],
    progress_callback: Optional[Callable[[int, int, str], None]] = None,
    cancel_checker: Optional[Callable[[], None]] = None,
) -> List[Dict[str, Any]]:
    strategy = str(request.analysis_strategy or "hybrid").strip().lower()
    if strategy == "llm_required":
        config_error = ""
        if request.l2_editor_config and request.l2_editor_config.provider != "none":
            l2_runtime_cfg = resolve_chat_config_from_model_config(
                request.l2_editor_config,
                db,
                context="l2",
            )
            config_error = _validate_chat_config(l2_runtime_cfg)
        else:
            _source, _config, config_error = resolve_chat_config_for_source(
                db=db,
                model_source=request.model_source,
            )
        if config_error:
            raise HTTPException(status_code=400, detail=config_error)

    if strategy == "rule_only":
        if progress_callback and segments:
            for i in range(len(segments)):
                _run_cancel_checker(cancel_checker)
                progress_callback(i + 1, len(segments), "规则分析")
        return segments

    _run_cancel_checker(cancel_checker)

    segment_comments_map = collect_segment_comments_from_danmu_file(
        danmu_path,
        segments=segments,
        timeline_base_ts=timeline_base_ts,
        danmu_delay_compensation_seconds=request.danmu_delay_compensation_seconds,
        progress_hook=progress_callback,
    )
    for seg in segments:
        seg["sample_texts"] = segment_comments_map.get(seg.get("id"), [])

    try:
        if request.l1_scout_config and request.l1_scout_config.provider != "none":
            segments = maybe_scout_segments_with_l1(
                db=db,
                segments=segments,
                model_cfg=request.l1_scout_config,
                highlight_type=request.highlight_type,
                stream_type=request.stream_type,
                cancel_checker=cancel_checker,
                progress_hook=progress_callback,
            )

        segments = maybe_enrich_segments_with_llm(
            db=db,
            model_source=request.model_source,
            highlight_type=request.highlight_type,
            stream_type=request.stream_type,
            story_enabled=request.story_enabled,
            segments=segments,
            events=None,
            timeline_base_ts=timeline_base_ts,
            danmu_delay_compensation_seconds=request.danmu_delay_compensation_seconds,
            segment_comments_map=segment_comments_map,
            progress_hook=progress_callback,
            cancel_checker=cancel_checker,
            strict_required=(strategy == "llm_required"),
            l2_config=request.l2_editor_config,
        )
        _run_cancel_checker(cancel_checker)
        return segments
    except RuntimeError as exc:
        if strategy == "llm_required":
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        raise


def _run_asr_enrichment_pipeline(
    *,
    request: AnalyzeRequest,
    source_video_path: str,
    segments: List[Dict[str, Any]],
    progress_callback: Optional[Callable[[int, int, str], None]] = None,
    cancel_checker: Optional[Callable[[], None]] = None,
) -> List[Dict[str, Any]]:
    strategy = str(request.analysis_strategy or "hybrid").strip().lower()
    if strategy == "rule_only" or not bool(getattr(request, "asr_enabled", True)) or not segments:
        return segments

    config = build_asr_config(
        enabled=True,
        model=getattr(request, "asr_model", "small"),
        device=getattr(request, "asr_device", "cpu"),
        compute_type=getattr(request, "asr_compute_type", "int8"),
        language="zh",
    )
    try:
        asr_map = transcribe_segments(
            source_video_path=source_video_path,
            segments=segments,
            config=config,
            progress_hook=progress_callback,
            cancel_checker=cancel_checker,
        )
    except RuntimeError as exc:
        logger.warning("highlights.asr.skip reason=runtime_error error=%s", exc)
        return segments
    except Exception as exc:
        logger.warning("highlights.asr.skip reason=unexpected error=%s", exc)
        return segments

    enriched: List[Dict[str, Any]] = []
    for seg in segments:
        item = dict(seg)
        asr_item = asr_map.get(str(item.get("id") or "")) or {}
        speech_text = str(asr_item.get("text") or "").strip()
        if speech_text:
            item["speech_text"] = speech_text[:900]
            item["speech_text_truncated"] = len(speech_text) > 900
            item["speech_text_path"] = asr_item.get("speech_text_path")
            item["speech_language"] = asr_item.get("language")
            item["speech_language_probability"] = asr_item.get("language_probability")
        enriched.append(item)

    logger.info(
        "highlights.asr.done segments=%s with_text=%s model=%s",
        len(enriched),
        sum(1 for seg in enriched if str(seg.get("speech_text") or "").strip()),
        config.model,
    )
    return enriched


def _boolish(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return bool(default)
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "on"}:
        return True
    if text in {"0", "false", "no", "off"}:
        return False
    return bool(default)


def _floatish(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except Exception:
        return float(default)


def _strict_global_rank_score(seg: Dict[str, Any]) -> float:
    decision = _floatish(seg.get("llm_decision_score"), _floatish(seg.get("llm_confidence"), 0.0))
    base_score = _floatish(seg.get("score"), 0.0)
    semantic = _floatish(seg.get("semantic_score"), 0.0)
    heat = min(1.0, _floatish(seg.get("heat_score"), 0.0) / 24.0)
    chat_count = max(0.0, _floatish(seg.get("chat_count"), 0.0))
    unique_users = max(0.0, _floatish(seg.get("unique_users"), 0.0))
    user_ratio = unique_users / max(1.0, chat_count)
    l1_score = _floatish(seg.get("l1_ai_score"), decision)

    reason = str(seg.get("llm_negative_reason") or "none").strip().lower()
    reason_penalty = 0.0
    if reason in _STRICT_HARD_NEGATIVE_REASONS:
        reason_penalty = 0.32
    elif reason == "low_signal":
        reason_penalty = 0.16

    rank_score = (
        decision * 0.42
        + base_score * 0.22
        + semantic * 0.12
        + heat * 0.10
        + min(1.0, user_ratio) * 0.08
        + l1_score * 0.06
        - reason_penalty
    )
    return round(max(0.0, min(1.0, rank_score)), 4)


def _filter_strict_llm_segments(segments: List[Dict[str, Any]], max_candidates: int) -> List[Dict[str, Any]]:
    """Drop common false positives and rerank remaining LLM-reviewed candidates globally."""
    if not segments:
        return segments

    filtered: List[Dict[str, Any]] = []
    diagnosed = 0
    for seg in segments:
        item = dict(seg)
        raw_decision = seg.get("llm_decision_score")
        raw_is_highlight = seg.get("llm_is_highlight")
        if raw_decision is None and raw_is_highlight is None:
            continue

        diagnosed += 1
        decision_score = _floatish(raw_decision if raw_decision is not None else seg.get("llm_confidence"), 0.0)
        is_highlight = _boolish(raw_is_highlight, default=False)
        negative_reason = str(seg.get("llm_negative_reason") or "none").strip().lower()
        hard_negative = negative_reason in _STRICT_HARD_NEGATIVE_REASONS

        keep = (is_highlight and decision_score >= _STRICT_LLM_MIN_DECISION_SCORE) or decision_score >= _STRICT_LLM_STRONG_DECISION_SCORE
        if hard_negative and decision_score < 0.78:
            keep = False

        item["global_rank_score"] = _strict_global_rank_score(item)
        if keep:
            filtered.append(item)

    if filtered:
        filtered.sort(
            key=lambda x: (
                _floatish(x.get("global_rank_score"), 0.0),
                _floatish(x.get("llm_decision_score"), 0.0),
                _floatish(x.get("score"), 0.0),
                _floatish(x.get("heat_score"), 0.0),
            ),
            reverse=True,
        )
        dropped = max(0, diagnosed - len(filtered))
        logger.info(
            "highlights.llm.strict_filter kept=%s dropped=%s diagnosed=%s total=%s min_score=%.2f strong_score=%.2f hard_reasons=%s",
            len(filtered),
            dropped,
            diagnosed,
            len(segments),
            _STRICT_LLM_MIN_DECISION_SCORE,
            _STRICT_LLM_STRONG_DECISION_SCORE,
            ",".join(sorted(_STRICT_HARD_NEGATIVE_REASONS)),
        )
        return filtered

    if diagnosed > 0:
        logger.warning(
            "highlights.llm.strict_filter.empty diagnosed=%s total=%s fallback=top_ranked",
            diagnosed,
            len(segments),
        )

    fallback = [dict(seg) for seg in segments[:max(1, int(max_candidates or 1))]]
    for item in fallback:
        item["global_rank_score"] = _strict_global_rank_score(item)
    return fallback


# 类型偏好权重：用户选择的类型匹配时加分
_TYPE_PREFERENCE_BOOST = 0.15
_TYPE_MISMATCH_PENALTY = 0.08
_VALID_HIGHLIGHT_TYPES = {"high_energy", "funny", "controversy", "teaching", "emotion"}


def _apply_highlight_type_preference(
    segments: List[Dict[str, Any]],
    highlight_type: str,
    max_candidates: int,
) -> List[Dict[str, Any]]:
    """根据用户选择的高光类型，对候选片段进行偏好加成和过滤。

    - 如果片段的 scene_type 匹配用户选择，global_rank_score 加成
    - 如果不匹配，降低排名
    - 如果有足够多匹配片段（>= max_candidates），优先保留匹配片段
    """
    if not segments:
        return segments

    # 标准化用户选择的类型
    user_type = str(highlight_type or "").strip().lower()
    if user_type not in _VALID_HIGHLIGHT_TYPES:
        # 无效类型，不做偏好处理
        return segments

    matching_segments: List[Dict[str, Any]] = []
    other_segments: List[Dict[str, Any]] = []

    for seg in segments:
        item = dict(seg)
        scene_type = str(item.get("scene_type") or "").strip().lower()

        if scene_type == user_type:
            # 类型匹配，加成
            original_score = float(item.get("global_rank_score", item.get("score", 0)))
            item["global_rank_score"] = round(min(1.0, original_score + _TYPE_PREFERENCE_BOOST), 4)
            item["type_matched"] = True
            matching_segments.append(item)
        else:
            # 类型不匹配，降低排名
            if scene_type in _VALID_HIGHLIGHT_TYPES:
                original_score = float(item.get("global_rank_score", item.get("score", 0)))
                item["global_rank_score"] = round(max(0.0, original_score - _TYPE_MISMATCH_PENALTY), 4)
            item["type_matched"] = False
            other_segments.append(item)

    # 如果匹配片段足够，直接返回匹配的
    if len(matching_segments) >= max_candidates:
        logger.info(
            "highlights.type_preference matched=%s/%s user_type=%s returning_matched_only=True",
            len(matching_segments),
            len(segments),
            user_type,
        )
        matching_segments.sort(
            key=lambda x: (
                float(x.get("global_rank_score", 0)),
                float(x.get("llm_decision_score", 0)),
                float(x.get("score", 0)),
            ),
            reverse=True,
        )
        return matching_segments[:max_candidates]

    # 合并：匹配的优先，但保留一些非匹配的作为补充
    result = matching_segments + other_segments
    result.sort(
        key=lambda x: (
            float(x.get("global_rank_score", 0)),
            float(x.get("llm_decision_score", 0)),
            float(x.get("score", 0)),
        ),
        reverse=True,
    )

    kept_matching = len(matching_segments)
    kept_others = max(0, max_candidates - kept_matching)
    logger.info(
        "highlights.type_preference matched=%s others=%s user_type=%s kept_matching=%s kept_others=%s",
        len(matching_segments),
        len(other_segments),
        user_type,
        kept_matching,
        kept_others,
    )

    return result[:max_candidates]


def _save_analysis_outputs(
    *,
    record_id: str,
    request: AnalyzeRequest,
    source_video_path: str,
    danmu_path: str,
    analysis_base_path: str,
    timeline_base_ts: Optional[float],
    raw_event_count: int,
    cleaned_event_count: int,
    segments: List[Dict[str, Any]],
    cancel_checker: Optional[Callable[[], None]] = None,
) -> Dict[str, Any]:
    analyzed_at = _now_iso()

    _run_cancel_checker(cancel_checker)
    segment_danmu_payload = _build_segment_danmu_snapshot_from_file(
        record_id=record_id,
        source_video_path=source_video_path,
        danmu_path=danmu_path,
        analyzed_at=analyzed_at,
        segments=segments,
        timeline_base_ts=timeline_base_ts,
        danmu_delay_compensation_seconds=request.danmu_delay_compensation_seconds,
    )
    _run_cancel_checker(cancel_checker)

    segment_danmu_path = save_segment_danmu(analysis_base_path, segment_danmu_payload)
    segment_danmu_map = {
        str(item.get("segment_id") or ""): item
        for item in (segment_danmu_payload.get("segments") or [])
    }

    total_segment_danmu_events = 0
    for seg in segments:
        seg_id = str(seg.get("id") or "")
        item = segment_danmu_map.get(seg_id) or {}
        seg["danmu_count"] = int(item.get("total_events") or 0)
        seg["danmu_truncated"] = bool(item.get("truncated") or False)
        seg["danmu_snapshot_path"] = segment_danmu_path
        total_segment_danmu_events += int(item.get("total_events") or 0)

    payload = {
        "record_id": record_id,
        "video_path": source_video_path,
        "danmu_path": danmu_path,
        "segment_danmu_path": segment_danmu_path,
        "stream_type": request.stream_type or "",
        "story_enabled": bool(request.story_enabled),
        "analyzed_at": analyzed_at,
        "analysis_request": request.model_dump(),
        "stats": {
            "raw_events": raw_event_count,
            "cleaned_events": cleaned_event_count,
            "segment_count": len(segments),
            "segment_danmu_events": total_segment_danmu_events,
        },
        "segments": segments,
    }
    _run_cancel_checker(cancel_checker)
    save_analysis(analysis_base_path, payload)
    logger.info("highlights.analyze.saved record_id=%s", record_id)

    return {
        "record_id": record_id,
        "danmu_path": danmu_path,
        "segment_count": len(segments),
        "analyzed_at": analyzed_at,
        "segments": segments,
    }


def _analyze_and_save(
    *,
    db: Session,
    record_id: str,
    request: AnalyzeRequest,
    progress_callback: Optional[Callable[[int, int, str], None]] = None,
    cancel_checker: Optional[Callable[[], None]] = None,
) -> Dict:
    started_at = time.perf_counter()
    rule_done_at = started_at
    llm_done_at = started_at
    _run_cancel_checker(cancel_checker)
    record = _must_get_record(record_id, db)
    source_video_path = _resolve_source_video_path(record)
    logger.info(
        "highlights.analyze.request record_id=%s strategy=%s model_source=%s highlight_type=%s stream_type=%s max_candidates=%s seed=%s randomness=%s danmu_delay_compensation=%s",
        record_id,
        request.analysis_strategy,
        request.model_source,
        request.highlight_type,
        (request.stream_type or "")[:32],
        request.max_candidates,
        request.seed,
        request.randomness,
        request.danmu_delay_compensation_seconds,
    )

    danmu_path = resolve_danmu_path(source_video_path)
    if not os.path.exists(danmu_path):
        raise HTTPException(status_code=400, detail="未找到对应弹幕文件，请先开启弹幕录制")
    _run_cancel_checker(cancel_checker)

    timeline_base_ts = _resolve_timeline_base_ts(record, danmu_path)

    segments, raw_event_count, cleaned_event_count = _build_rule_candidates(
        record_id=record_id,
        request=request,
        danmu_path=danmu_path,
        timeline_base_ts=timeline_base_ts,
        progress_callback=progress_callback,
        cancel_checker=cancel_checker,
    )
    rule_done_at = time.perf_counter()

    # 规则预过滤：淘汰低分候选，减少 ASR 开销
    strategy = str(request.analysis_strategy or "").strip().lower()
    prefilter_threshold = _RULE_PREFILTER_MIN_SCORE
    if strategy == "llm_required":
        # LLM 会进一步筛选，预过滤可以更激进
        prefilter_threshold = _RULE_PREFILTER_MIN_SCORE * 1.5
    segments = _prefilter_rule_segments(segments, min_score=prefilter_threshold)

    segments = _run_asr_enrichment_pipeline(
        request=request,
        source_video_path=source_video_path,
        segments=segments,
        progress_callback=progress_callback,
        cancel_checker=cancel_checker,
    )

    segments = _run_llm_enhancement_pipeline(
        db=db,
        request=request,
        danmu_path=danmu_path,
        timeline_base_ts=timeline_base_ts,
        segments=segments,
        progress_callback=progress_callback,
        cancel_checker=cancel_checker,
    )
    llm_done_at = time.perf_counter()

    _run_cancel_checker(cancel_checker)
    if str(request.analysis_strategy or "").strip().lower() == "llm_required":
        segments = _filter_strict_llm_segments(segments, request.max_candidates)

    # 应用用户选择的高光类型偏好
    segments = _apply_highlight_type_preference(
        segments,
        highlight_type=request.highlight_type,
        max_candidates=request.max_candidates,
    )

    segments = apply_story_fallback(segments, story_enabled=request.story_enabled)
    if len(segments) > request.max_candidates:
        segments.sort(key=lambda x: (float(x.get("global_rank_score", x.get("score", 0))), float(x.get("heat_score", 0))), reverse=True)
        segments = segments[: request.max_candidates]
    logger.info("highlights.analyze.final_segments record_id=%s count=%s", record_id, len(segments))

    analysis_base_path = _analysis_base_path(record, source_video_path)
    result = _save_analysis_outputs(
        record_id=record_id,
        request=request,
        source_video_path=source_video_path,
        danmu_path=danmu_path,
        analysis_base_path=analysis_base_path,
        timeline_base_ts=timeline_base_ts,
        raw_event_count=raw_event_count,
        cleaned_event_count=cleaned_event_count,
        segments=segments,
        cancel_checker=cancel_checker,
    )
    saved_at = time.perf_counter()
    logger.info(
        "highlights.analyze.timing record_id=%s strategy=%s segments=%s duration_total=%.3fs duration_rule=%.3fs duration_llm=%.3fs duration_save=%.3fs",
        record_id,
        request.analysis_strategy,
        len(segments),
        saved_at - started_at,
        rule_done_at - started_at,
        llm_done_at - rule_done_at,
        saved_at - llm_done_at,
    )
    return result


def _run_analyze_task_sync(
    *,
    task_id: str,
    record_id: str,
    request_data: Dict,
    loop: asyncio.AbstractEventLoop,
) -> None:
    db = None
    try:
        db = get_session()
        request = AnalyzeRequest.model_validate(request_data)
        request = normalize_analyze_request(request)
        _raise_if_task_cancelled(task_id)

        task = _task_update(task_id, status=TASK_STATUS_RUNNING, progress=3, message="开始分析")
        if task:
            _broadcast_task_threadsafe(loop, task, "highlights_analyze_progress")
            _broadcast_record_status_threadsafe(
                loop,
                record_id=record_id,
                highlights_status=TASK_STATUS_RUNNING,
            )

        task = _task_update(task_id, progress=12, message="加载弹幕数据")
        if task:
            _broadcast_task_threadsafe(loop, task, "highlights_analyze_progress")

        def _on_candidate_progress(done: int, total: int, stage: str) -> None:
            _raise_if_task_cancelled(task_id)
            stage_text = str(stage or "").strip()
            safe_total = max(1, int(total or 0))
            safe_done = max(0, min(int(done or 0), safe_total))
            ratio = max(0.0, min(1.0, float(safe_done) / float(safe_total)))

            # 分阶段进度映射，消除“候选生成 -> LLM增强”中间真空。
            if stage_text == "候选已生成":
                progress = 28
                message = "候选已生成"
            elif stage_text == "弹幕采样":
                progress = 30 + int(round(ratio * 10))  # 30~40
                message = f"{stage_text} {safe_done}/{safe_total}"
            elif stage_text in {"ASR转写", "ASR缓存"}:
                progress = 41 + int(round(ratio * 14))  # 41~55
                message = f"{stage_text} {safe_done}/{safe_total}"
            elif stage_text == "L1语义初筛":
                progress = 56 + int(round(ratio * 9))  # 56~65
                message = f"{stage_text} {safe_done}/{safe_total}"
            elif stage_text == "LLM增强":
                progress = 66 + int(round(ratio * 26))  # 66~92
                message = f"{stage_text} {safe_done}/{safe_total}"
            elif stage_text in {"规则分析", "降级规则"}:
                progress = 43 + int(round(ratio * 49))  # 43~92
                message = f"{stage_text} {safe_done}/{safe_total}"
            else:
                # 兜底映射，避免新阶段名没有进度反馈。
                progress = 30 + int(round(ratio * 62))  # 30~92
                message = f"{stage_text or '分析中'} {safe_done}/{safe_total}"

            task_inner = _task_update(task_id, progress=progress, message=message)
            if task_inner:
                _broadcast_task_threadsafe(loop, task_inner, "highlights_analyze_progress")

        result = _analyze_and_save(
            db=db,
            record_id=record_id,
            request=request,
            progress_callback=_on_candidate_progress,
            cancel_checker=lambda: _raise_if_task_cancelled(task_id),
        )
        _raise_if_task_cancelled(task_id)

        task = _task_update(
            task_id,
            status=TASK_STATUS_SUCCESS,
            progress=100,
            message="分析完成",
            segment_count=int(result.get("segment_count") or 0),
            analyzed_at=result.get("analyzed_at") or "",
            error=None,
        )
        if task:
            _broadcast_task_threadsafe(loop, task, "highlights_analyze_done")
            _broadcast_record_status_threadsafe(
                loop,
                record_id=record_id,
                highlights_status=TASK_STATUS_SUCCESS,
                has_highlights_analysis=True,
            )
    except AnalysisCancelled:
        logger.info("highlights.analyze.cancelled task_id=%s record_id=%s", task_id, record_id)
        if db:
            try:
                record = _must_get_record(record_id, db)
                _cleanup_record_artifacts(record)
            except Exception as cleanup_exc:
                logger.warning(
                    "highlights.analyze.cancel_cleanup_late_failed task_id=%s record_id=%s error=%s",
                    task_id,
                    record_id,
                    cleanup_exc,
                )
        task = _task_update(
            task_id,
            status=TASK_STATUS_CANCELLED,
            progress=100,
            message="分析已终止",
            error="cancelled",
            cancel_requested=True,
        )
        if task:
            _broadcast_task_threadsafe(loop, task, "highlights_analyze_cancelled")
            _broadcast_record_status_threadsafe(
                loop,
                record_id=record_id,
                highlights_status="",
                has_highlights_analysis=False,
            )
    except HTTPException as exc:
        if _is_task_cancel_requested(task_id):
            task = _task_update(
                task_id,
                status=TASK_STATUS_CANCELLED,
                progress=100,
                message="分析已终止",
                error="cancelled",
                cancel_requested=True,
            )
            if task:
                _broadcast_task_threadsafe(loop, task, "highlights_analyze_cancelled")
            return
        detail = str(exc.detail)
        logger.warning("highlights.analyze.async_failed task_id=%s record_id=%s detail=%s", task_id, record_id, detail)
        task = _task_update(task_id, status=TASK_STATUS_FAILED, progress=100, message="分析失败", error=detail)
        if task:
            _broadcast_task_threadsafe(loop, task, "highlights_analyze_error")
            _broadcast_record_status_threadsafe(
                loop,
                record_id=record_id,
                highlights_status=TASK_STATUS_FAILED,
            )
    except Exception as exc:
        if _is_task_cancel_requested(task_id):
            task = _task_update(
                task_id,
                status=TASK_STATUS_CANCELLED,
                progress=100,
                message="分析已终止",
                error="cancelled",
                cancel_requested=True,
            )
            if task:
                _broadcast_task_threadsafe(loop, task, "highlights_analyze_cancelled")
                _broadcast_record_status_threadsafe(
                    loop,
                    record_id=record_id,
                    highlights_status="",
                    has_highlights_analysis=False,
                )
            return
        logger.exception("highlights.analyze.async_crash task_id=%s record_id=%s", task_id, record_id)
        task = _task_update(task_id, status=TASK_STATUS_FAILED, progress=100, message="分析失败", error=str(exc))
        if task:
            _broadcast_task_threadsafe(loop, task, "highlights_analyze_error")
            _broadcast_record_status_threadsafe(
                loop,
                record_id=record_id,
                highlights_status=TASK_STATUS_FAILED,
            )
    finally:
        if db:
            try:
                db.close()
            except Exception:
                pass


async def _run_analyze_task_async(task_id: str, record_id: str, request_data: Dict, loop: asyncio.AbstractEventLoop) -> None:
    await asyncio.to_thread(
        _run_analyze_task_sync,
        task_id=task_id,
        record_id=record_id,
        request_data=request_data,
        loop=loop,
    )


@router.post("/analyze-async/{record_id}", response_model=AnalyzeTaskSubmitResponse)
@require_lifetime_license_api
async def analyze_record_highlights_async(
    record_id: str,
    request_body: dict = Body(...),
    current_user: User = Depends(get_current_user_or_token),
    db: Session = Depends(get_session),
):
    """异步提交分析任务，结果通过 WS 推送。"""
    logger.info("highlights.analyze.async_submit record_id=%s", record_id)
    try:
        request = AnalyzeRequest.model_validate(request_body)
        request = normalize_analyze_request(request)
    except ValidationError as exc:
        logger.warning("highlights.analyze.invalid_request record_id=%s errors=%s", record_id, str(exc)[:300])
        raise HTTPException(status_code=422, detail=exc.errors()) from exc

    record = _must_get_record(record_id, db)
    source_video_path = _resolve_source_video_path(record)
    analysis_base_path = _analysis_base_path(record, source_video_path)

    running = _find_running_task(record_id)
    if running:
        return AnalyzeTaskSubmitResponse(
            success=True,
            task_id=str(running.get("task_id") or ""),
            record_id=record_id,
            status=normalize_task_status(str(running.get("status") or TASK_STATUS_RUNNING)),
            ws_channel=_ws_channel(record_id),
            created_at=running.get("created_at") or _now_iso(),
        )

    persisted = _reconcile_persisted_task(analysis_base_path, load_task_status(analysis_base_path))
    if persisted:
        _task_store(persisted, persist=False)
    if persisted and persisted.get("status") in TASK_ACTIVE_STATUSES:
        return AnalyzeTaskSubmitResponse(
            success=True,
            task_id=str(persisted.get("task_id") or ""),
            record_id=record_id,
            status=normalize_task_status(str(persisted.get("status") or TASK_STATUS_RUNNING)),
            ws_channel=_ws_channel(record_id),
            created_at=persisted.get("created_at") or _now_iso(),
        )

    # 生成请求指纹，用于判断是否已有相同参数的正在运行或已完成的任务
    # 特殊处理：如果 seed 为 -1，说明用户想要“完全随机”，我们通过加入时间戳让指纹每次都刷新
    fingerprint_data = request.model_dump()
    if request.seed == -1:
        import time
        fingerprint_data["_force_random_salt"] = time.time()
        
    request_fingerprint = hashlib.sha1(
        json.dumps(fingerprint_data, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()
    if (
        persisted
        and persisted.get("request_fingerprint") == request_fingerprint
        and persisted.get("status") in {TASK_STATUS_SUCCESS}
    ):
        _task_store(persisted, persist=False)
        return AnalyzeTaskSubmitResponse(
            success=True,
            task_id=str(persisted.get("task_id") or ""),
            record_id=record_id,
            status=normalize_task_status(str(persisted.get("status") or TASK_STATUS_SUCCESS)),
            ws_channel=_ws_channel(record_id),
            created_at=persisted.get("created_at") or _now_iso(),
        )

    now = _now_iso()
    task_id = str(uuid.uuid4())
    task = {
        "task_id": task_id,
        "record_id": record_id,
        "analysis_base_path": analysis_base_path,
        "stream_type": request.stream_type or "",
        "story_enabled": bool(request.story_enabled),
        "request_fingerprint": request_fingerprint,
        "status": TASK_STATUS_QUEUED,
        "progress": 0,
        "message": "任务已提交",
        "segment_count": 0,
        "analyzed_at": "",
        "error": None,
        "created_at": now,
        "updated_at": now,
    }
    _task_store(task, persist=True)
    await _broadcast_record_status(
        record_id=record_id,
        highlights_status=TASK_STATUS_QUEUED,
    )

    loop = asyncio.get_running_loop()
    asyncio.create_task(_run_analyze_task_async(task_id, record_id, request.model_dump(), loop))

    return AnalyzeTaskSubmitResponse(
        success=True,
        task_id=task_id,
        record_id=record_id,
        status=TASK_STATUS_QUEUED,
        ws_channel=_ws_channel(record_id),
        created_at=now,
    )


@router.get("/analyze-task/{task_id}", response_model=AnalyzeTaskStatusResponse)
@require_lifetime_license_api
async def get_analyze_task_status(
    task_id: str,
    current_user: User = Depends(get_current_user_or_token),
):
    task = _task_snapshot(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="分析任务不存在")
    return _task_to_status_response(task)


@router.get("/analyze-task/latest/{record_id}", response_model=AnalyzeTaskStatusResponse)
@require_lifetime_license_api
async def get_latest_analyze_task_status(
    record_id: str,
    current_user: User = Depends(get_current_user_or_token),
    db: Session = Depends(get_session),
):
    record = _must_get_record(record_id, db)
    analysis_base_path = _pick_existing_artifact_base_path(record)
    if not analysis_base_path:
        raise HTTPException(status_code=404, detail="暂无分析任务")
    task = _reconcile_persisted_task(analysis_base_path, load_task_status(analysis_base_path))
    if not task:
        raise HTTPException(status_code=404, detail="暂无分析任务")
    _task_store(task, persist=False)
    return _task_to_status_response(task)


@router.post("/analyze-task/cancel/{record_id}", response_model=CleanupResponse)
@require_lifetime_license_api
async def cancel_analyze_task_for_record(
    record_id: str,
    current_user: User = Depends(get_current_user_or_token),
    db: Session = Depends(get_session),
):
    """终止某条录制记录的当前分析任务，并清理本场高光分析产物。"""
    record = _must_get_record(record_id, db)
    running = _find_running_task(record_id)
    removed_tasks = 0

    if running:
        task_id = str(running.get("task_id") or "")
        task = _task_update(
            task_id,
            persist=False,
            status=TASK_STATUS_CANCELLED,
            progress=100,
            message="分析已终止，已清理本场产物",
            error="cancelled",
            cancel_requested=True,
        )
        if task:
            await _broadcast_task(task, "highlights_analyze_cancelled")

    stats = _cleanup_record_artifacts(record)

    if not running:
        removed_tasks = _drop_record_tasks(record_id)

    await _broadcast_record_status(
        record_id=record_id,
        highlights_status="",
        has_highlights_analysis=False,
    )
    logger.info(
        "highlights.analyze.cancel_cleanup record_id=%s task_id=%s removed_files=%s removed_dirs=%s freed_bytes=%s",
        record_id,
        str(running.get("task_id") or "") if running else "",
        stats["removed_files"],
        stats["removed_dirs"],
        stats["freed_bytes"],
    )

    return CleanupResponse(
        success=True,
        record_id=record_id,
        removed_files=stats["removed_files"],
        removed_dirs=stats["removed_dirs"],
        freed_bytes=stats["freed_bytes"],
        removed_tasks=removed_tasks,
    )


@router.post("/analyze/{record_id}", response_model=AnalyzeResponse)
@require_lifetime_license_api
async def analyze_record_highlights(
    record_id: str,
    request_body: dict = Body(...),
    current_user: User = Depends(get_current_user_or_token),
    db: Session = Depends(get_session),
):
    """同步分析接口（兼容旧调用）。"""
    logger.info("highlights.analyze.start record_id=%s", record_id)
    try:
        request = AnalyzeRequest.model_validate(request_body)
        request = normalize_analyze_request(request)
    except ValidationError as exc:
        logger.warning("highlights.analyze.invalid_request record_id=%s errors=%s", record_id, str(exc)[:300])
        raise HTTPException(status_code=422, detail=exc.errors()) from exc

    result = _analyze_and_save(db=db, record_id=record_id, request=request)
    await _broadcast_record_status(
        record_id=record_id,
        highlights_status=TASK_STATUS_SUCCESS,
        has_highlights_analysis=True,
    )
    return AnalyzeResponse(
        success=True,
        record_id=result["record_id"],
        danmu_path=result["danmu_path"],
        stream_type=(request.stream_type or ""),
        analysis_request=request.model_dump(),
        segment_count=result["segment_count"],
        analyzed_at=result["analyzed_at"],
        data=[HighlightSegment(**s) for s in result["segments"]],
    )

# --- 聚合优化接口 ---

_ELIGIBLE_CACHE = {}
_CACHE_TTL = 300  # 5分钟缓存


def _check_danmu_exists(file_path: Optional[str], converted_path: Optional[str] = None) -> bool:
    """并行调用的文件检查函数。优先检查原文件路径，不存在时回退转码路径。"""
    for path in (file_path, converted_path):
        if not path:
            continue
        danmu_path = resolve_danmu_path(str(path))
        if os.path.exists(danmu_path):
            return True
    return False


def _resolve_highlights_state(file_path: Optional[str], converted_path: Optional[str] = None) -> Dict:
    """复用已有的逻辑判断高光状态"""
    for base_path in [str(file_path or "").strip(), str(converted_path or "").strip()]:
        if not base_path:
            continue
        status_path = resolve_task_status_path(base_path)
        if os.path.exists(status_path):
            try:
                with open(status_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    status = str(data.get("status") or "").strip().lower()
                    if status:
                        return {
                            "has_highlights_analysis": status == TASK_STATUS_SUCCESS,
                            "highlights_status": status
                        }
            except Exception:
                pass
        if os.path.exists(resolve_analysis_path(base_path)):
            return {"has_highlights_analysis": True, "highlights_status": TASK_STATUS_SUCCESS}
    return {"has_highlights_analysis": False, "highlights_status": "none"}


@router.get("/eligible-streamers")
@require_lifetime_license_api
async def get_eligible_streamers(
    db: Session = Depends(get_session),
    current_user: User = Depends(get_current_user_or_token)
):
    """获取拥有可分析记录的博主列表（高性能聚合版）"""
    # 尝试内存缓存
    cache_key = "eligible_streamers_all"
    now = time.time()
    if cache_key in _ELIGIBLE_CACHE:
        entry = _ELIGIBLE_CACHE[cache_key]
        if now - entry["ts"] < _CACHE_TTL:
            return {"success": True, "data": entry["data"]}

    # 1. 基础 SQL 过滤：只选有 file_path 的记录
    records = db.query(
        LiveRecord.id,
        LiveRecord.subscription_id,
        LiveRecord.file_path,
        LiveRecord.converted_path,
        LiveRecord.start_time,
        LiveRecord.anchor_name
    ).filter(
        (LiveRecord.file_path.isnot(None) | LiveRecord.converted_path.isnot(None)),
        LiveRecord.subscription_id.isnot(None)
    ).all()

    if not records:
        return {"success": True, "data": []}

    # 2. 并行检查磁盘文件是否存在
    results = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=15) as executor:
        future_to_rec = {
            executor.submit(_check_danmu_exists, r.file_path, r.converted_path): r
            for r in records
        }
        for future in concurrent.futures.as_completed(future_to_rec):
            rec = future_to_rec[future]
            try:
                if future.result():
                    results.append(rec)
            except:
                continue

    # 3. 按博主聚合
    eligible_platforms = {'douyin', 'bilibili', 'douyu', 'huya', 'twitch'}
    streamer_map = {}
    for r in results:
        sid = str(r.subscription_id)
        if sid not in streamer_map:
            sub = db.query(LiveSubscription).filter(LiveSubscription.id == sid).first()
            if not sub or sub.platform not in eligible_platforms:
                continue
            
            streamer_map[sid] = {
                "id": sid,
                "anchor_name": sub.anchor_name or r.anchor_name or "未知博主",
                "avatar_url": sub.avatar_url or "",
                "platform": sub.platform,
                "record_count": 0,
                "latest_start_time": r.start_time
            }
        
        node = streamer_map[sid]
        node["record_count"] += 1
        if r.start_time and (not node["latest_start_time"] or r.start_time > node["latest_start_time"]):
            node["latest_start_time"] = r.start_time

    data = sorted(
        streamer_map.values(), 
        key=lambda x: x["latest_start_time"].isoformat() if x["latest_start_time"] else "", 
        reverse=True
    )
    
    # 写入缓存
    _ELIGIBLE_CACHE[cache_key] = {"ts": now, "data": data}
    return {"success": True, "data": data}


@router.get("/eligible-records/{subscription_id}")
@require_lifetime_license_api
async def get_streamer_eligible_records(
    subscription_id: str,
    db: Session = Depends(get_session),
    current_user: User = Depends(get_current_user_or_token)
):
    """拉取指定博主下所有符合高光条件的记录列表"""
    records = db.query(LiveRecord).filter(
        LiveRecord.subscription_id == subscription_id,
        (LiveRecord.file_path.isnot(None) | LiveRecord.converted_path.isnot(None))
    ).order_by(LiveRecord.start_time.desc()).all()

    results = []
    for r in records:
        if _check_danmu_exists(r.file_path, r.converted_path):
            # 优先返回实际存在的文件路径（MP4 > TS），避免转码后 file_path 仍指向已删除 TS
            preferred_path = r.file_path or r.converted_path
            for path in (r.converted_path, r.file_path):
                if path and os.path.exists(path):
                    preferred_path = path
                    break
            state = _resolve_highlights_state(r.file_path, r.converted_path)
            results.append({
                "id": str(r.id),
                "start_time": r.start_time.isoformat() if r.start_time else None,
                "file_path": preferred_path,
                "duration": r.duration,
                "status": r.status,
                "has_danmu_file": True,
                "has_highlights_analysis": state.get("has_highlights_analysis"),
                "highlights_status": state.get("highlights_status"),
            })
    
    return {"success": True, "data": results}



@router.get("/{record_id}", response_model=AnalyzeResponse)
@require_lifetime_license_api
async def get_record_highlights(
    record_id: str,
    current_user: User = Depends(get_current_user_or_token),
    db: Session = Depends(get_session),
):
    """获取指定录制记录最近一次分析结果。"""
    logger.info("highlights.get.start record_id=%s", record_id)
    record = _must_get_record(record_id, db)
    analysis_base_path = _pick_existing_artifact_base_path(record)
    data = load_analysis(analysis_base_path) if analysis_base_path else None
    if not data:
        logger.info("highlights.get.empty record_id=%s", record_id)
        return AnalyzeResponse(
            success=True,
            record_id=record_id,
            danmu_path=resolve_danmu_path(analysis_base_path) if analysis_base_path else "",
            stream_type="",
            analysis_request=None,
            segment_count=0,
            analyzed_at="",
            data=[],
        )

    segments = data.get("segments") or []
    logger.info("highlights.get.ok record_id=%s segment_count=%s", record_id, len(segments))
    return AnalyzeResponse(
        success=True,
        record_id=record_id,
        danmu_path=data.get("danmu_path") or (resolve_danmu_path(analysis_base_path) if analysis_base_path else ""),
        stream_type=(
            (data.get("analysis_request") or {}).get("stream_type")
            or data.get("stream_type")
            or ""
        ),
        analysis_request=data.get("analysis_request") or None,
        segment_count=len(segments),
        analyzed_at=data.get("analyzed_at") or "",
        data=[HighlightSegment(**s) for s in segments],
    )


@router.get("/{record_id}/segment-danmu/{segment_id}", response_model=SegmentDanmuResponse)
@require_lifetime_license_api
async def get_record_segment_danmu(
    record_id: str,
    segment_id: str,
    current_user: User = Depends(get_current_user_or_token),
    db: Session = Depends(get_session),
):
    """获取指定候选片段对应的弹幕抽样（用于预览/调试）。"""
    record = _must_get_record(record_id, db)
    analysis_base_path = _pick_existing_artifact_base_path(record)
    payload = load_analysis(analysis_base_path) if analysis_base_path else None
    if not payload:
        raise HTTPException(status_code=404, detail="暂无分析结果")

    segments: List[dict] = payload.get("segments") or []
    has_segment = any(str(seg.get("id") or "") == segment_id for seg in segments)
    if not has_segment:
        raise HTTPException(status_code=404, detail="未找到对应候选片段")

    snapshot_path = payload.get("segment_danmu_path") or (
        resolve_segment_danmu_path(analysis_base_path) if analysis_base_path else ""
    )

    snapshot = load_segment_danmu(analysis_base_path) if analysis_base_path else None
    if not snapshot:
        raise HTTPException(status_code=404, detail="当前记录缺少片段弹幕快照，请重新分析")

    item = None
    for row in snapshot.get("segments") or []:
        if str(row.get("segment_id") or "") == segment_id:
            item = row
            break
    if item is None:
        raise HTTPException(status_code=404, detail="当前片段未找到弹幕快照，请重新分析")

    return SegmentDanmuResponse(
        success=True,
        record_id=record_id,
        segment_id=segment_id,
        total_events=int(item.get("total_events") or 0),
        included_events=int(item.get("included_events") or 0),
        truncated=bool(item.get("truncated") or False),
        snapshot_path=str(snapshot_path or ""),
        data=[SegmentDanmuItem(**row) for row in (item.get("events") or [])],
    )


@router.get("/{record_id}/danmu-range")
@require_lifetime_license_api
async def get_record_danmu_range(
    record_id: str,
    start_sec: float = Query(..., description="起始秒数"),
    end_sec: float = Query(..., description="结束秒数"),
    max_events: int = Query(200, description="最大返回条数"),
    current_user: User = Depends(get_current_user_or_token),
    db: Session = Depends(get_session),
):
    """按任意时间范围获取弹幕（用于调整切片起点/终点后刷新预览弹幕）。"""
    record = _must_get_record(record_id, db)
    _video_path, danmu_path = _resolve_danmu_range_paths(record)

    if end_sec < start_sec:
        start_sec, end_sec = end_sec, start_sec

    events: List[Dict] = []
    delay = 0.0
    try:
        # 从弹幕 JSONL 文件中读取第一条时间戳作为 base_ts
        base_ts: Optional[float] = None
        with open(danmu_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except Exception:
                    continue
                ts = obj.get("ts")
                if ts is None:
                    continue
                try:
                    ts_val = float(ts)
                except Exception:
                    continue
                base_ts = ts_val
                break

        if base_ts is None:
            return {"success": True, "data": [], "total_events": 0, "included_events": 0}

        abs_start = base_ts + start_sec
        abs_end = base_ts + end_sec

        with open(danmu_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except Exception:
                    continue
                ts = obj.get("ts")
                if ts is None:
                    continue
                try:
                    ts_val = float(ts)
                except Exception:
                    continue
                effective_ts = ts_val - delay
                if effective_ts < abs_start:
                    continue
                if effective_ts > abs_end:
                    continue
                text = _extract_text_direct(obj)
                uid = _extract_uid_direct(obj)
                event_type = str(obj.get("event_type") or obj.get("type") or "chat")
                events.append({
                    "event_type": event_type,
                    "sec": round(effective_ts - base_ts, 3),
                    "offset_sec": round(effective_ts - abs_start, 3),
                    "uid": uid,
                    "text": text,
                })

        total = len(events)
        sampled = events[:max_events] if max_events > 0 else events
        return {
            "success": True,
            "data": sampled,
            "total_events": total,
            "included_events": len(sampled),
            "truncated": total > len(sampled),
        }
    except HTTPException:
        raise
    except Exception as exc:
        logger.error(f"获取弹幕范围失败: {exc}")
        raise HTTPException(status_code=500, detail=f"获取弹幕失败: {exc}")


@router.post("/export/{record_id}", response_model=ExportResponse)
@require_lifetime_license_api
async def export_record_highlights(
    record_id: str,
    request_body: dict = Body(...),
    current_user: User = Depends(get_current_user_or_token),
    db: Session = Depends(get_session),
):
    """导出高光切片（按 segment_ids 或全部候选）。"""
    logger.info("highlights.export.start record_id=%s", record_id)
    try:
        request = ExportRequest.model_validate(request_body)
    except ValidationError as exc:
        logger.warning("highlights.export.invalid_request record_id=%s errors=%s", record_id, str(exc)[:300])
        raise HTTPException(status_code=422, detail=exc.errors()) from exc

    record = _must_get_record(record_id, db)
    source_video_path = _resolve_source_video_path(record)

    analysis_base_path = _pick_existing_artifact_base_path(record, source_video_path)
    payload = load_analysis(analysis_base_path)
    if not payload:
        raise HTTPException(status_code=400, detail="尚未分析，请先执行分析")

    segments: List[dict] = payload.get("segments") or []
    if not segments:
        logger.warning("highlights.export.no_segments record_id=%s", record_id)
        raise HTTPException(status_code=400, detail="没有可导出的候选片段")

    selected_ids = set(request.segment_ids or [])
    if selected_ids:
        selected_segments = [s for s in segments if str(s.get("id")) in selected_ids]
        if not selected_segments:
            raise HTTPException(status_code=400, detail="未匹配到要导出的片段")
    else:
        selected_segments = segments

    # 应用自定义时间范围（用户拖拽调整后的起止时间）
    custom_ranges = request.custom_ranges or []
    range_map = {cr.segment_id: cr for cr in custom_ranges}
    for seg in selected_segments:
        cr = range_map.get(str(seg.get("id", "")))
        if cr:
            seg["start_sec"] = cr.start_sec
            seg["end_sec"] = cr.end_sec
            logger.info(
                "highlights.export.custom_range segment_id=%s adjusted to %.1f-%.1f",
                cr.segment_id, cr.start_sec, cr.end_sec,
            )

    exported: List[dict] = []
    if not request.only_story_assets:
        exported = await asyncio.to_thread(
            export_segments,
            source_video_path=source_video_path,
            segments=selected_segments,
            overwrite=request.overwrite,
        )
    logger.info(
        "highlights.export.done record_id=%s selected=%s exported=%s",
        record_id,
        len(selected_segments),
        len(exported),
    )

    exported_map = {str(s.get("id")): s.get("clip_path") for s in exported}
    for s in segments:
        sid = str(s.get("id"))
        if sid in exported_map and exported_map[sid]:
            s["clip_path"] = exported_map[sid]

    payload["segments"] = segments
    payload["last_exported_at"] = _now_iso()
    save_analysis(analysis_base_path, payload)
    logger.info("highlights.export.saved record_id=%s", record_id)

    storyline_json_path = None
    subtitles_srt_path = None
    if request.include_story_assets or request.only_story_assets:
        assets = await asyncio.to_thread(
            export_story_assets,
            source_video_path=source_video_path,
            segments=selected_segments,
            stream_type=(payload.get("stream_type") or (payload.get("analysis_request") or {}).get("stream_type") or ""),
            overwrite=request.overwrite,
        )
        storyline_json_path = assets.get("storyline_json_path")
        subtitles_srt_path = assets.get("subtitles_srt_path")

    return ExportResponse(
        success=True,
        record_id=record_id,
        exported_count=len(exported),
        storyline_json_path=storyline_json_path,
        subtitles_srt_path=subtitles_srt_path,
        data=[HighlightSegment(**s) for s in exported],
    )


@router.post("/manual-export", response_model=ManualExportResponse)
@require_lifetime_license_api
async def manual_export_video(
    request_body: dict = Body(...),
    current_user: User = Depends(get_current_user_or_token),
):
    """手动切片：直接按视频文件和时间范围导出，无需 AI 分析。"""
    return await _manual_export_video_impl(request_body)


@router.post("/manual-export-by-path", response_model=ManualExportResponse)
async def manual_export_video_by_path(
    request_body: dict = Body(...),
    current_user: User = Depends(get_current_user_or_token),
):
    """下载中心手动切片：按下载文件路径导出，供普通授权用户使用。"""
    return await _manual_export_video_impl(request_body)


async def _manual_export_video_impl(request_body: dict) -> ManualExportResponse:
    """手动切片实现。调用方通过不同路由控制权限边界。"""
    logger.info("highlights.manual_export.start")
    try:
        request = ManualExportRequest.model_validate(request_body)
    except ValidationError as exc:
        logger.warning("highlights.manual_export.invalid_request errors=%s", str(exc)[:300])
        raise HTTPException(status_code=422, detail=exc.errors())

    # 解析视频文件路径
    source_video_path = os.path.normpath(request.file_path_)
    if not os.path.exists(source_video_path):
        # 尝试在 /app/downloads 下解析
        alt = os.path.normpath(os.path.join("/app/downloads", request.file_path_.lstrip("/")))
        if os.path.exists(alt):
            source_video_path = alt
        else:
            logger.warning("highlights.manual_export.file_not_found path=%s", request.file_path_)
            raise HTTPException(status_code=400, detail=f"视频文件不存在: {request.file_path_}")

    # 校验文件是否在 /app/downloads 范围内（安全约束）
    dl_real = os.path.realpath("/app/downloads")
    file_real = os.path.realpath(source_video_path)
    if not file_real.startswith(dl_real + os.sep) and not file_real == dl_real:
        logger.warning("highlights.manual_export.path_escape path=%s", file_real)
        raise HTTPException(status_code=400, detail="只支持 /app/downloads 目录下的文件")

    if not os.path.isfile(file_real):
        raise HTTPException(status_code=400, detail="路径不是有效文件")

    duration = request.end_sec - request.start_sec
    if duration <= 0:
        raise HTTPException(status_code=400, detail="结束时间必须大于开始时间")

    # 限制最大切片时长（例如 1 小时）
    max_duration = 3600
    if duration > max_duration:
        raise HTTPException(status_code=400, detail=f"切片时长不能超过 {max_duration} 秒")

    # 构造合成 segment
    seg_id = f"manual_{int(request.start_sec)}_{int(request.end_sec)}_{uuid.uuid4().hex[:8]}"
    from datetime import timedelta
    title_start = str(timedelta(seconds=int(request.start_sec)))
    title_end = str(timedelta(seconds=int(request.end_sec)))
    segment = {
        "id": seg_id,
        "start_sec": request.start_sec,
        "end_sec": request.end_sec,
        "highlight_type": "manual",
        "title": f"手动切片 {title_start} ~ {title_end}",
    }

    # 写入 _manual_clips/ 目录，与 AI 高光完全隔离
    manual_clip_dir = Path(resolve_manual_clip_dir(file_real))
    manual_clip_dir.mkdir(parents=True, exist_ok=True)

    out_name = f"manual_{int(request.start_sec)}_{int(request.end_sec)}_{seg_id[:8]}.mp4"
    out_path = manual_clip_dir / out_name

    if out_path.exists() and not request.overwrite:
        return ManualExportResponse(success=True, clip_path=str(out_path), segment=None)

    ffmpeg_cmd = [
        "ffmpeg", "-y",
        "-ss", str(request.start_sec),
        "-to", str(request.end_sec),
        "-i", file_real,
        "-c:v", "copy",
        "-c:a", "copy",
        str(out_path),
    ]

    proc = await asyncio.to_thread(
        lambda: subprocess.run(ffmpeg_cmd, capture_output=True, text=True, timeout=3600)
    )

    if proc.returncode != 0 or not out_path.exists():
        fallback_cmd = [
            "ffmpeg", "-y",
            "-ss", str(request.start_sec),
            "-to", str(request.end_sec),
            "-i", file_real,
            "-c:v", "libx264",
            "-preset", "fast",
            "-c:a", "aac",
            str(out_path),
        ]
        proc2 = await asyncio.to_thread(
            lambda: subprocess.run(fallback_cmd, capture_output=True, text=True, timeout=7200)
        )
        if proc2.returncode != 0 or not out_path.exists():
            err_msg = (proc2.stderr or proc2.stdout or "ffmpeg failed")[:300]
            logger.warning("highlights.manual_export.ffmpeg_error error=%s", err_msg)
            return ManualExportResponse(success=False, clip_path="", clip_error=err_msg)

    logger.info("highlights.manual_export.done path=%s clip=%s", file_real, str(out_path))
    return ManualExportResponse(success=True, clip_path=str(out_path), segment=None)



@router.get("/manual-clips/{record_id}", response_model=ManualClipListResponse)
@require_lifetime_license_api
async def list_manual_clips(
    record_id: str,
    current_user: User = Depends(get_current_user_or_token),
    db: Session = Depends(get_session),
):
    """列出某条录制的手动切片。"""
    record = _must_get_record(record_id, db)
    base_paths = []
    if record.file_path: base_paths.append(record.file_path)
    if record.converted_path and record.converted_path not in base_paths: base_paths.append(record.converted_path)
    
    clips = []
    seen = set()
    for bp in base_paths:
        clip_dir = Path(resolve_manual_clip_dir(bp))
        if not clip_dir.exists() or not clip_dir.is_dir():
            continue
        real_dir = str(clip_dir.resolve())
        if real_dir in seen:
            continue
        seen.add(real_dir)
        for f in sorted(clip_dir.iterdir()):
            if f.suffix.lower() not in ('.mp4', '.mkv', '.mov'):
                continue
            m = re.search(r'manual_(\d+)_(\d+)_', f.stem)
            start_sec = float(m.group(1)) if m else 0.0
            end_sec = float(m.group(2)) if m else 0.0
            mtime = datetime.fromtimestamp(f.stat().st_mtime).isoformat()
            clips.append(ManualClipItem(
                name=f.name, path=str(f), size_bytes=f.stat().st_size,
                start_sec=start_sec, end_sec=end_sec, created_at=mtime,
            ))
    return ManualClipListResponse(success=True, record_id=record_id, clips=clips)


@router.delete("/manual-clips/{record_id}/file/{clip_name}", response_model=ManualClipCleanupResponse)
@require_lifetime_license_api
async def delete_record_manual_clip(
    record_id: str,
    clip_name: str,
    current_user: User = Depends(get_current_user_or_token),
    db: Session = Depends(get_session),
):
    """删除某条录制下的单个手动切片。"""
    record = _must_get_record(record_id, db)
    safe_name = Path(str(clip_name or "")).name
    if not safe_name or safe_name != clip_name:
        raise HTTPException(status_code=400, detail="切片文件名无效")

    base_paths = []
    if record.file_path:
        base_paths.append(record.file_path)
    if record.converted_path and record.converted_path not in base_paths:
        base_paths.append(record.converted_path)

    seen = set()
    for bp in base_paths:
        clip_dir = Path(resolve_manual_clip_dir(bp))
        if not clip_dir.exists() or not clip_dir.is_dir():
            continue
        try:
            real_dir = clip_dir.resolve()
        except Exception:
            continue
        if str(real_dir) in seen:
            continue
        seen.add(str(real_dir))

        target = clip_dir / safe_name
        try:
            real_target = target.resolve()
        except Exception:
            continue
        if real_target.parent != real_dir:
            continue
        if not target.exists() or not target.is_file():
            continue
        if target.suffix.lower() not in ('.mp4', '.mkv', '.mov'):
            raise HTTPException(status_code=400, detail="仅支持删除视频切片文件")

        freed_bytes = target.stat().st_size
        target.unlink()
        removed_dirs = 0
        try:
            if not any(clip_dir.iterdir()):
                clip_dir.rmdir()
                removed_dirs = 1
        except Exception:
            removed_dirs = 0
        logger.info("highlights.manual_clip.delete record_id=%s clip=%s freed_bytes=%s", record_id, safe_name, freed_bytes)
        return ManualClipCleanupResponse(
            success=True,
            record_id=record_id,
            removed_files=1,
            removed_dirs=removed_dirs,
            freed_bytes=freed_bytes,
        )

    raise HTTPException(status_code=404, detail="未找到该手动切片文件")


def _find_manual_clip_path(record: LiveRecord, clip_name: str) -> Path:
    safe_name = Path(str(clip_name or "")).name
    if not safe_name or safe_name != clip_name:
        raise HTTPException(status_code=400, detail="切片文件名无效")

    base_paths = []
    if record.file_path:
        base_paths.append(record.file_path)
    if record.converted_path and record.converted_path not in base_paths:
        base_paths.append(record.converted_path)

    seen = set()
    for bp in base_paths:
        clip_dir = Path(resolve_manual_clip_dir(bp))
        if not clip_dir.exists() or not clip_dir.is_dir():
            continue
        try:
            real_dir = clip_dir.resolve()
        except Exception:
            continue
        if str(real_dir) in seen:
            continue
        seen.add(str(real_dir))

        target = clip_dir / safe_name
        try:
            real_target = target.resolve()
        except Exception:
            continue
        if real_target.parent != real_dir:
            continue
        if not target.exists() or not target.is_file():
            continue
        if target.suffix.lower() not in ('.mp4', '.mkv', '.mov'):
            raise HTTPException(status_code=400, detail="仅支持下载视频切片文件")
        return target

    raise HTTPException(status_code=404, detail="未找到该手动切片文件")


def _resolve_download_file_path(file_path: str) -> str:
    source_path = os.path.normpath(str(file_path or ""))
    if not os.path.exists(source_path):
        alt = os.path.normpath(os.path.join("/app/downloads", source_path.lstrip("/")))
        if os.path.exists(alt):
            source_path = alt
    dl_real = os.path.realpath("/app/downloads")
    file_real = os.path.realpath(source_path)
    if not file_real.startswith(dl_real + os.sep) and file_real != dl_real:
        raise HTTPException(status_code=400, detail="只支持 /app/downloads 目录下的文件")
    if not os.path.isfile(file_real):
        raise HTTPException(status_code=400, detail="视频文件不存在")
    return file_real


def _list_manual_clips_for_path(file_path: str) -> ManualClipListResponse:
    file_real = _resolve_download_file_path(file_path)
    clip_dir = Path(resolve_manual_clip_dir(file_real))
    clips = []
    if clip_dir.exists() and clip_dir.is_dir():
        for f in sorted(clip_dir.iterdir()):
            if f.suffix.lower() not in ('.mp4', '.mkv', '.mov'):
                continue
            m = re.search(r'manual_(\d+)_(\d+)_', f.stem)
            start_sec = float(m.group(1)) if m else 0.0
            end_sec = float(m.group(2)) if m else 0.0
            mtime = datetime.fromtimestamp(f.stat().st_mtime).isoformat()
            clips.append(ManualClipItem(
                name=f.name,
                path=str(f),
                size_bytes=f.stat().st_size,
                start_sec=start_sec,
                end_sec=end_sec,
                created_at=mtime,
            ))
    return ManualClipListResponse(success=True, record_id=resolve_record_id(file_real), clips=clips)


def _find_manual_clip_path_for_file(file_path: str, clip_name: str) -> Path:
    safe_name = Path(str(clip_name or "")).name
    if not safe_name or safe_name != clip_name:
        raise HTTPException(status_code=400, detail="切片文件名无效")
    file_real = _resolve_download_file_path(file_path)
    clip_dir = Path(resolve_manual_clip_dir(file_real))
    try:
        real_dir = clip_dir.resolve()
        target = clip_dir / safe_name
        real_target = target.resolve()
    except Exception:
        raise HTTPException(status_code=404, detail="未找到该手动切片文件")
    if real_target.parent != real_dir:
        raise HTTPException(status_code=400, detail="切片文件名无效")
    if not target.exists() or not target.is_file():
        raise HTTPException(status_code=404, detail="未找到该手动切片文件")
    if target.suffix.lower() not in ('.mp4', '.mkv', '.mov'):
        raise HTTPException(status_code=400, detail="仅支持视频切片文件")
    return target


@router.post("/manual-clips-by-path", response_model=ManualClipListResponse)
async def list_manual_clips_by_path(
    request_body: dict = Body(...),
    current_user: User = Depends(get_current_user_or_token),
):
    """按下载文件路径列出手动切片，用于下载中心入口。"""
    file_path = str((request_body or {}).get("file_path") or "")
    return await asyncio.to_thread(_list_manual_clips_for_path, file_path)


@router.post("/manual-clips-by-path/file/{clip_name}/download")
async def download_manual_clip_by_path(
    clip_name: str,
    request_body: dict = Body(...),
    current_user: User = Depends(get_current_user_or_token),
):
    """按下载文件路径下载单个手动切片。"""
    clip_path = _find_manual_clip_path_for_file(str((request_body or {}).get("file_path") or ""), clip_name)
    return FileResponse(path=str(clip_path), media_type="video/mp4", filename=clip_path.name)


@router.delete("/manual-clips-by-path/file/{clip_name}", response_model=ManualClipCleanupResponse)
async def delete_manual_clip_by_path(
    clip_name: str,
    request_body: dict = Body(...),
    current_user: User = Depends(get_current_user_or_token),
):
    """按下载文件路径删除单个手动切片。"""
    clip_path = _find_manual_clip_path_for_file(str((request_body or {}).get("file_path") or ""), clip_name)
    freed_bytes = clip_path.stat().st_size
    parent = clip_path.parent
    clip_path.unlink()
    removed_dirs = 0
    try:
        if not any(parent.iterdir()):
            parent.rmdir()
            removed_dirs = 1
    except Exception:
        removed_dirs = 0
    return ManualClipCleanupResponse(success=True, record_id=parent.name, removed_files=1, removed_dirs=removed_dirs, freed_bytes=freed_bytes)


@router.delete("/manual-clips-by-path", response_model=ManualClipCleanupResponse)
async def cleanup_manual_clips_by_path(
    request_body: dict = Body(...),
    current_user: User = Depends(get_current_user_or_token),
):
    """按下载文件路径清空该视频的全部手动切片。"""
    file_real = _resolve_download_file_path(str((request_body or {}).get("file_path") or ""))
    clip_dir = Path(resolve_manual_clip_dir(file_real))
    if not clip_dir.exists() or not clip_dir.is_dir():
        return ManualClipCleanupResponse(success=True, record_id=resolve_record_id(file_real), removed_files=0, removed_dirs=0, freed_bytes=0)

    removed_files = removed_dirs = freed_bytes = 0
    for item in clip_dir.rglob("*"):
        if item.is_file():
            removed_files += 1
            try:
                freed_bytes += item.stat().st_size
            except OSError:
                pass
        elif item.is_dir():
            removed_dirs += 1

    import shutil
    shutil.rmtree(clip_dir, ignore_errors=True)
    removed_dirs += 1
    return ManualClipCleanupResponse(
        success=True,
        record_id=resolve_record_id(file_real),
        removed_files=removed_files,
        removed_dirs=removed_dirs,
        freed_bytes=freed_bytes,
    )


@router.post("/manual-clips-by-path/bundle")
async def download_manual_clips_bundle_by_path(
    request_body: dict = Body(...),
    current_user: User = Depends(get_current_user_or_token),
):
    """按下载文件路径打包手动切片。"""
    file_path = str((request_body or {}).get("file_path") or "")
    requested_names = (request_body or {}).get("clip_names")
    if isinstance(requested_names, list) and requested_names:
        clip_names = []
        for name in requested_names:
            safe_name = Path(str(name or "")).name
            if safe_name and safe_name == str(name):
                clip_names.append(safe_name)
    else:
        clips_resp = await asyncio.to_thread(_list_manual_clips_for_path, file_path)
        clip_names = [clip.name for clip in clips_resp.clips]

    if not clip_names:
        raise HTTPException(status_code=400, detail="暂无可导出的手动切片")

    clip_paths = []
    seen = set()
    for name in clip_names:
        if name in seen:
            continue
        seen.add(name)
        clip_paths.append(_find_manual_clip_path_for_file(file_path, name))

    first_clip = clip_paths[0]
    bundle_dir = first_clip.parent / "_bundles"
    bundle_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    zip_name = f"manual_clips_download_{timestamp}.zip"
    zip_path = bundle_dir / zip_name

    def _write_bundle() -> int:
        manifest = {
            "bundle_layout": "manual_clips_by_path_v1",
            "source_file": os.path.basename(_resolve_download_file_path(file_path)),
            "generated_at": _now_iso(),
            "clip_count": len(clip_paths),
            "clips": [p.name for p in clip_paths],
        }
        added = 0
        with zipfile.ZipFile(str(zip_path), "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
            for idx, path in enumerate(clip_paths, start=1):
                zf.write(str(path), f"clip_{idx:02d}_{path.name}")
                added += 1
            zf.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
            added += 1
        return added

    await asyncio.to_thread(_write_bundle)
    if not zip_path.exists():
        raise HTTPException(status_code=500, detail="手动切片资源包生成失败")
    return FileResponse(path=str(zip_path), media_type="application/zip", filename=zip_name)


@router.get("/manual-clips/{record_id}/file/{clip_name}/download")
@require_lifetime_license_api
async def download_record_manual_clip(
    record_id: str,
    clip_name: str,
    current_user: User = Depends(get_current_user_or_token),
    db: Session = Depends(get_session),
):
    """下载某条录制下的单个手动切片。"""
    record = _must_get_record(record_id, db)
    clip_path = _find_manual_clip_path(record, clip_name)
    return FileResponse(
        path=str(clip_path),
        media_type="video/mp4",
        filename=clip_path.name,
    )


@router.post("/manual-clips/{record_id}/bundle")
@require_lifetime_license_api
async def download_record_manual_clips_bundle(
    record_id: str,
    request_body: dict = Body(default_factory=dict),
    current_user: User = Depends(get_current_user_or_token),
    db: Session = Depends(get_session),
):
    """打包下载某条录制下的手动切片。未传 clip_names 时导出全部。"""
    record = _must_get_record(record_id, db)
    requested_names = request_body.get("clip_names") if isinstance(request_body, dict) else None
    clip_names = []
    if isinstance(requested_names, list):
        for name in requested_names:
            safe_name = Path(str(name or "")).name
            if safe_name and safe_name == str(name):
                clip_names.append(safe_name)

    if not clip_names:
        clips_resp = await list_manual_clips(record_id=record_id, current_user=current_user, db=db)
        clip_names = [clip.name for clip in clips_resp.clips]

    if not clip_names:
        raise HTTPException(status_code=400, detail="暂无可导出的手动切片")

    clip_paths = []
    seen_names = set()
    for name in clip_names:
        if name in seen_names:
            continue
        seen_names.add(name)
        clip_paths.append(_find_manual_clip_path(record, name))

    first_clip = clip_paths[0]
    bundle_dir = first_clip.parent / "_bundles"
    bundle_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    anchor_name = _sanitize_filename_component(getattr(record, "anchor_name", "") or "主播")
    zip_name = f"manual_clips_{anchor_name}_{timestamp}.zip"
    zip_path = bundle_dir / zip_name

    def _write_manual_bundle() -> int:
        added = 0
        manifest = {
            "bundle_layout": "manual_clips_v1",
            "record_id": record_id,
            "anchor_name": getattr(record, "anchor_name", "") or "",
            "live_title": getattr(record, "live_title", "") or "",
            "generated_at": _now_iso(),
            "clip_count": len(clip_paths),
            "clips": [p.name for p in clip_paths],
        }
        with zipfile.ZipFile(str(zip_path), "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
            for idx, path in enumerate(clip_paths, start=1):
                arcname = f"clip_{idx:02d}_{path.name}"
                zf.write(str(path), arcname=arcname)
                added += 1
            zf.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
            added += 1
        return added

    added_count = await asyncio.to_thread(_write_manual_bundle)
    if not zip_path.exists():
        raise HTTPException(status_code=500, detail="手动切片资源包生成失败")

    logger.info("highlights.manual_clips.bundle record_id=%s clips=%s files=%s zip=%s", record_id, len(clip_paths), added_count, str(zip_path))
    return FileResponse(
        path=str(zip_path),
        media_type="application/zip",
        filename=zip_name,
    )


@router.delete("/manual-clips/{record_id}", response_model=ManualClipCleanupResponse)
@require_lifetime_license_api
async def cleanup_record_manual_clips(
    record_id: str,
    current_user: User = Depends(get_current_user_or_token),
    db: Session = Depends(get_session),
):
    """清理某条录制的所有手动切片。"""
    record = _must_get_record(record_id, db)
    base_paths = []
    if record.file_path: base_paths.append(record.file_path)
    if record.converted_path and record.converted_path not in base_paths: base_paths.append(record.converted_path)
    
    removed_files = removed_dirs = freed_bytes = 0
    for bp in base_paths:
        clip_dir = Path(resolve_manual_clip_dir(bp))
        if not clip_dir.exists():
            continue
        for f in clip_dir.rglob('*'):
            if f.is_file():
                freed_bytes += f.stat().st_size
                removed_files += 1
            elif f.is_dir():
                removed_dirs += 1
        import shutil
        shutil.rmtree(clip_dir, ignore_errors=True)
        removed_dirs += 1

    logger.info("highlights.manual_clips.cleanup record_id=%s removed_files=%s freed_bytes=%s", record_id, removed_files, freed_bytes)
    return ManualClipCleanupResponse(success=True, record_id=record_id, removed_files=removed_files, removed_dirs=removed_dirs, freed_bytes=freed_bytes)


@router.delete("/manual-clips-streamer/{subscription_id}", response_model=ManualClipCleanupResponse)
@require_lifetime_license_api
async def cleanup_streamer_manual_clips(
    subscription_id: str,
    current_user: User = Depends(get_current_user_or_token),
    db: Session = Depends(get_session),
):
    """清理某位博主下所有录制的手动切片。"""
    records = db.query(LiveRecord).filter(LiveRecord.subscription_id == subscription_id).all()
    if not records:
        raise HTTPException(status_code=404, detail="未找到该博主的录制记录")
    
    total_removed_files = total_removed_dirs = total_freed_bytes = 0
    import shutil
    for record in records:
        base_paths = []
        if record.file_path: base_paths.append(record.file_path)
        if record.converted_path and record.converted_path not in base_paths: base_paths.append(record.converted_path)
        seen = set()
        for bp in base_paths:
            clip_dir = Path(resolve_manual_clip_dir(bp))
            if not clip_dir.exists():
                continue
            real_dir = str(clip_dir.resolve())
            if real_dir in seen:
                continue
            seen.add(real_dir)
            for f in clip_dir.rglob('*'):
                if f.is_file():
                    total_freed_bytes += f.stat().st_size
                    total_removed_files += 1
                elif f.is_dir():
                    total_removed_dirs += 1
            shutil.rmtree(clip_dir, ignore_errors=True)
            total_removed_dirs += 1

    logger.info("highlights.manual_clips.cleanup_streamer sub=%s files=%s", subscription_id, total_removed_files)
    return ManualClipCleanupResponse(success=True, subscription_id=subscription_id,
        removed_files=total_removed_files, removed_dirs=total_removed_dirs, freed_bytes=total_freed_bytes)
@router.post("/bundle/{record_id}")
@require_lifetime_license_api
async def download_record_bundle(
    record_id: str,
    request_body: dict = Body(...),
    current_user: User = Depends(get_current_user_or_token),
    db: Session = Depends(get_session),
):
    """导出资源包（zip）：扁平根目录，面向交付。"""
    logger.info("highlights.bundle.start record_id=%s", record_id)
    try:
        request = BundleRequest.model_validate(request_body)
    except ValidationError as exc:
        logger.warning("highlights.bundle.invalid_request record_id=%s errors=%s", record_id, str(exc)[:300])
        raise HTTPException(status_code=422, detail=exc.errors()) from exc

    record = _must_get_record(record_id, db)
    source_video_path = _resolve_source_video_path(record)
    analysis_base_path = _pick_existing_artifact_base_path(record, source_video_path)

    payload = load_analysis(analysis_base_path)
    if not payload:
        raise HTTPException(status_code=400, detail="尚未分析，请先执行分析")

    segments: List[dict] = payload.get("segments") or []
    if not segments:
        raise HTTPException(status_code=400, detail="没有可导出的候选片段")

    selected_ids = {str(sid) for sid in (request.segment_ids or []) if str(sid).strip()}
    if selected_ids:
        selected_segments = [s for s in segments if str(s.get("id")) in selected_ids]
        if not selected_segments:
            raise HTTPException(status_code=400, detail="未匹配到要导出的片段")
    else:
        selected_segments = list(segments)

    exported_segments = await asyncio.to_thread(
        export_segments,
        source_video_path=source_video_path,
        segments=selected_segments,
        overwrite=request.overwrite,
    )
    exported_map = {str(s.get("id")): s.get("clip_path") for s in exported_segments if s.get("clip_path")}
    for s in segments:
        sid = str(s.get("id") or "")
        if sid in exported_map:
            s["clip_path"] = exported_map[sid]
    payload["segments"] = segments
    payload["last_exported_at"] = _now_iso()
    save_analysis(analysis_base_path, payload)

    storyline_json_path = None
    if request.include_story_assets:
        assets = await asyncio.to_thread(
            export_story_assets,
            source_video_path=source_video_path,
            segments=selected_segments,
            stream_type=(payload.get("stream_type") or (payload.get("analysis_request") or {}).get("stream_type") or ""),
            overwrite=request.overwrite,
        )
        storyline_json_path = assets.get("storyline_json_path")

    artifact_dir = Path(resolve_artifact_dir(analysis_base_path))
    bundle_dir = artifact_dir / "bundles"
    bundle_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    anchor_name = _sanitize_filename_component(getattr(record, "anchor_name", "") or "主播")
    zip_name = f"highlights_bundle_{anchor_name}_{timestamp}.zip"
    zip_path = bundle_dir / zip_name

    selected_segment_ids = {str(s.get("id") or "") for s in selected_segments}
    selected_with_clip = [s for s in segments if str(s.get("id") or "") in selected_segment_ids and s.get("clip_path")]
    selected_without_clip = [s for s in segments if str(s.get("id") or "") in selected_segment_ids and not s.get("clip_path")]

    manifest = {
        "bundle_layout": "per_clip_v3",
        "record_id": record_id,
        "anchor_name": getattr(record, "anchor_name", "") or "",
        "live_title": getattr(record, "live_title", "") or "",
        "generated_at": _now_iso(),
        "segment_count": len(selected_segments),
        "clip_count": len(selected_with_clip),
        "segments_without_clip": [str(s.get("id") or "") for s in selected_without_clip],
    }
    segment_danmu_path = payload.get("segment_danmu_path") or resolve_segment_danmu_path(analysis_base_path)
    if request.include_story_assets and storyline_json_path is None:
        storyline_json_path = resolve_storyline_json_path(analysis_base_path)

    added_count = await asyncio.to_thread(
        _build_bundle_zip,
        zip_path=str(zip_path),
        selected_with_clip=selected_with_clip,
        segment_danmu_path=str(segment_danmu_path),
        storyline_json_path=str(storyline_json_path or ""),
        manifest=manifest,
    )

    if not zip_path.exists():
        raise HTTPException(status_code=500, detail="资源包生成失败")

    logger.info(
        "highlights.bundle.done record_id=%s selected=%s clips=%s files=%s zip=%s",
        record_id,
        len(selected_segments),
        len(selected_with_clip),
        added_count,
        str(zip_path),
    )
    return FileResponse(
        path=str(zip_path),
        media_type="application/zip",
        filename=zip_name,
    )


@router.delete("/cleanup/{record_id}", response_model=CleanupResponse)
@require_lifetime_license_api
async def cleanup_record_highlights(
    record_id: str,
    current_user: User = Depends(get_current_user_or_token),
    db: Session = Depends(get_session),
):
    """清理某条录制记录对应的高光分析与导出产物。"""
    record = _must_get_record(record_id, db)

    running = _find_running_task(record_id)
    if running:
        raise HTTPException(status_code=409, detail="当前记录仍在分析中，请稍后再清理")

    stats = _cleanup_record_artifacts(record)
    removed_tasks = _drop_record_tasks(record_id)
    logger.info(
        "highlights.cleanup.done record_id=%s removed_files=%s removed_dirs=%s freed_bytes=%s removed_tasks=%s",
        record_id,
        stats["removed_files"],
        stats["removed_dirs"],
        stats["freed_bytes"],
        removed_tasks,
    )
    await _broadcast_record_status(
        record_id=record_id,
        highlights_status="",
        has_highlights_analysis=False,
    )

    return CleanupResponse(
        success=True,
        record_id=record_id,
        removed_files=stats["removed_files"],
        removed_dirs=stats["removed_dirs"],
        freed_bytes=stats["freed_bytes"],
        removed_tasks=removed_tasks,
    )


@router.delete("/cleanup-streamer/{subscription_id}", response_model=StreamerCleanupResponse)
@require_lifetime_license_api
async def cleanup_streamer_highlights(
    subscription_id: str,
    current_user: User = Depends(get_current_user_or_token),
    db: Session = Depends(get_session),
):
    """清理某位博主（subscription）下全部录制记录的高光分析与导出产物。"""
    records = db.query(LiveRecord).filter(LiveRecord.subscription_id == subscription_id).all()
    if not records:
        raise HTTPException(status_code=404, detail="未找到该博主的录制记录")

    running_records = [str(r.id) for r in records if _find_running_task(str(r.id))]
    if running_records:
        raise HTTPException(
            status_code=409,
            detail=f"该博主仍有 {len(running_records)} 条记录正在分析中，请稍后再试",
        )

    removed_files = 0
    removed_dirs = 0
    freed_bytes = 0
    removed_tasks = 0
    cleaned_records = 0
    cleaned_record_ids: List[str] = []
    cleanup_errors: List[str] = []

    for record in records:
        base_paths: List[str] = []
        if record.file_path:
            base_paths.append(record.file_path)
        if record.converted_path and record.converted_path not in base_paths:
            base_paths.append(record.converted_path)
        record_has_error = False

        for base_path in base_paths:
            try:
                stats = clear_record_artifacts(base_path)
                removed_files += int(stats.get("removed_files") or 0)
                removed_dirs += int(stats.get("removed_dirs") or 0)
                freed_bytes += int(stats.get("freed_bytes") or 0)
            except Exception as exc:
                cleanup_errors.append(f"{record.id}: {exc}")
                record_has_error = True

        if not record_has_error:
            removed_tasks += _drop_record_tasks(str(record.id))
            cleaned_records += 1
            cleaned_record_ids.append(str(record.id))

    if cleanup_errors:
        logger.warning(
            "highlights.cleanup_streamer.failed subscription_id=%s errors=%s",
            subscription_id,
            cleanup_errors[:2],
        )
        raise HTTPException(status_code=500, detail="批量清理失败，请检查目录权限后重试")

    for record_id in cleaned_record_ids:
        await _broadcast_record_status(
            record_id=record_id,
            highlights_status="",
            has_highlights_analysis=False,
        )

    logger.info(
        "highlights.cleanup_streamer.done subscription_id=%s cleaned_records=%s removed_files=%s removed_dirs=%s freed_bytes=%s removed_tasks=%s",
        subscription_id,
        cleaned_records,
        removed_files,
        removed_dirs,
        freed_bytes,
        removed_tasks,
    )
    return StreamerCleanupResponse(
        success=True,
        subscription_id=subscription_id,
        cleaned_records=cleaned_records,
        removed_files=removed_files,
        removed_dirs=removed_dirs,
        freed_bytes=freed_bytes,
        removed_tasks=removed_tasks,
    )
