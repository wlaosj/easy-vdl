# -*- coding: utf-8 -*-
"""AI 高光切片 V1：分析结果存储与切片导出。"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional


def resolve_danmu_path(file_path: str) -> str:
    base, _ext = os.path.splitext(file_path)
    return f"{base}.danmu.jsonl"


def resolve_record_id(file_path: str) -> str:
    stem = Path(file_path).stem
    parts = stem.rsplit("_", 1)
    if len(parts) == 2 and parts[1]:
        return parts[1]
    return stem


def resolve_artifact_dir(file_path: str) -> str:
    video_path = Path(file_path)
    record_id = resolve_record_id(file_path)
    return str(video_path.parent / "_highlights" / record_id)


def resolve_manual_clip_dir(file_path: str) -> str:
    """手动切片产物目录，与 AI 切片完全隔离。"""
    video_path = Path(file_path)
    record_id = resolve_record_id(file_path)
    return str(video_path.parent / "_manual_clips" / record_id)


def resolve_analysis_path(file_path: str) -> str:
    artifact_dir = resolve_artifact_dir(file_path)
    return str(Path(artifact_dir) / "highlights.v1.json")


def resolve_task_status_path(file_path: str) -> str:
    artifact_dir = resolve_artifact_dir(file_path)
    return str(Path(artifact_dir) / "task_status.v1.json")


def resolve_clip_dir(file_path: str) -> str:
    artifact_dir = resolve_artifact_dir(file_path)
    return str(Path(artifact_dir) / "clips")


def resolve_storyline_json_path(file_path: str) -> str:
    artifact_dir = resolve_artifact_dir(file_path)
    return str(Path(artifact_dir) / "analysis" / "storyline.v1.json")


def resolve_storyline_srt_path(file_path: str) -> str:
    artifact_dir = resolve_artifact_dir(file_path)
    return str(Path(artifact_dir) / "subtitles" / "storyline.v1.srt")


def resolve_segment_danmu_path(file_path: str) -> str:
    artifact_dir = resolve_artifact_dir(file_path)
    return str(Path(artifact_dir) / "analysis" / "segment_danmu.v1.json")


def clear_record_artifacts(file_path: str) -> Dict[str, int]:
    """清理某条录制记录对应的高光产物目录。"""
    artifact_dir = Path(resolve_artifact_dir(file_path))
    if not artifact_dir.exists():
        return {
            "removed_files": 0,
            "removed_dirs": 0,
            "freed_bytes": 0,
        }

    removed_files = 0
    removed_dirs = 0
    freed_bytes = 0

    for _root, dirs, files in os.walk(artifact_dir):
        removed_dirs += len(dirs)
        removed_files += len(files)
        for name in files:
            path = Path(_root) / name
            try:
                freed_bytes += path.stat().st_size
            except OSError:
                pass

    shutil.rmtree(artifact_dir, ignore_errors=False)
    removed_dirs += 1  # artifact_dir 自身

    return {
        "removed_files": removed_files,
        "removed_dirs": removed_dirs,
        "freed_bytes": freed_bytes,
    }


def _to_srt_time(seconds: float) -> str:
    sec = max(0.0, float(seconds or 0.0))
    total_ms = int(round(sec * 1000))
    h = total_ms // 3600000
    m = (total_ms % 3600000) // 60000
    s = (total_ms % 60000) // 1000
    ms = total_ms % 1000
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def load_analysis(file_path: str) -> Optional[dict]:
    path = resolve_analysis_path(file_path)
    if not os.path.exists(path):
        return None
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def _atomic_write_json(path: str, payload: Dict[str, Any]) -> None:
    parent = Path(path).parent
    parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(prefix=".tmp_", suffix=".json", dir=str(parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, ensure_ascii=False, indent=2)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp_path, path)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def save_analysis(file_path: str, payload: dict) -> str:
    path = resolve_analysis_path(file_path)
    payload = dict(payload)
    payload["updated_at"] = datetime.now().isoformat()
    _atomic_write_json(path, payload)
    return path


def load_task_status(file_path: str) -> Optional[dict]:
    path = resolve_task_status_path(file_path)
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as fh:
            raw = fh.read()
        if not raw.strip():
            return None
        return json.loads(raw)
    except (json.JSONDecodeError, OSError, ValueError):
        return None


def save_task_status(file_path: str, payload: dict) -> str:
    path = resolve_task_status_path(file_path)
    data = dict(payload)
    data["updated_at"] = datetime.now().isoformat()
    _atomic_write_json(path, data)
    return path


def load_segment_danmu(file_path: str) -> Optional[Dict[str, Any]]:
    path = resolve_segment_danmu_path(file_path)
    if not os.path.exists(path):
        return None
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def save_segment_danmu(file_path: str, payload: Dict[str, Any]) -> str:
    path = resolve_segment_danmu_path(file_path)
    data = dict(payload)
    data["updated_at"] = datetime.now().isoformat()
    _atomic_write_json(path, data)
    return path


def export_story_assets(
    *,
    source_video_path: str,
    segments: List[Dict],
    stream_type: str,
    overwrite: bool,
) -> Dict[str, str]:
    json_path = Path(resolve_storyline_json_path(source_video_path))
    srt_path = Path(resolve_storyline_srt_path(source_video_path))
    json_path.parent.mkdir(parents=True, exist_ok=True)
    srt_path.parent.mkdir(parents=True, exist_ok=True)

    ordered = sorted(
        [dict(s) for s in segments],
        key=lambda x: float(x.get("start_sec") or 0),
    )
    storyline_payload = {
        "video_path": source_video_path,
        "stream_type": stream_type or "",
        "generated_at": datetime.now().isoformat(),
        "segment_count": len(ordered),
        "segments": [
            {
                "id": str(seg.get("id") or ""),
                "start_sec": float(seg.get("start_sec") or 0),
                "end_sec": float(seg.get("end_sec") or 0),
                "title": str(seg.get("title") or ""),
                "summary": str(seg.get("summary") or ""),
                "story_text": str(seg.get("story_text") or seg.get("summary") or ""),
                "keywords": seg.get("keywords") or [],
                "clip_path": seg.get("clip_path"),
            }
            for seg in ordered
        ],
    }

    if overwrite or not json_path.exists():
        with open(json_path, "w", encoding="utf-8") as fh:
            json.dump(storyline_payload, fh, ensure_ascii=False, indent=2)

    if overwrite or not srt_path.exists():
        lines: List[str] = []
        for idx, seg in enumerate(ordered, start=1):
            start_sec = float(seg.get("start_sec") or 0)
            end_sec = float(seg.get("end_sec") or 0)
            if end_sec <= start_sec:
                continue
            text = str(seg.get("story_text") or seg.get("summary") or "").strip()
            if not text:
                continue
            lines.append(str(idx))
            lines.append(f"{_to_srt_time(start_sec)} --> {_to_srt_time(end_sec)}")
            lines.append(text)
            lines.append("")
        with open(srt_path, "w", encoding="utf-8") as fh:
            fh.write("\n".join(lines).strip() + ("\n" if lines else ""))

    return {
        "storyline_json_path": str(json_path),
        "subtitles_srt_path": str(srt_path),
    }


def export_segments(
    *,
    source_video_path: str,
    segments: List[Dict],
    overwrite: bool,
) -> List[Dict]:
    clip_dir = Path(resolve_clip_dir(source_video_path))
    clip_dir.mkdir(parents=True, exist_ok=True)

    exported = []
    for idx, seg in enumerate(segments, start=1):
        start_sec = float(seg.get("start_sec") or 0)
        end_sec = float(seg.get("end_sec") or 0)
        duration = max(0.0, end_sec - start_sec)
        if duration <= 0:
            continue

        segment_id = str(seg.get("id") or f"seg_{idx}")
        safe_type = str(seg.get("highlight_type") or "highlight")
        out_name = f"{idx:02d}_{safe_type}_{int(start_sec)}_{segment_id[:8]}.mp4"
        out_path = clip_dir / out_name

        if out_path.exists() and not overwrite:
            seg["clip_path"] = str(out_path)
            exported.append(seg)
            continue

        cmd = [
            "ffmpeg",
            "-y",
            "-ss",
            str(start_sec),
            "-to",
            str(end_sec),
            "-i",
            source_video_path,
            "-c:v",
            "copy",
            "-c:a",
            "copy",
            str(out_path),
        ]

        proc = subprocess.run(cmd, capture_output=True, text=True)
        if proc.returncode != 0:
            # 容错：copy 失败时回退重编码
            cmd_fallback = [
                "ffmpeg",
                "-y",
                "-ss",
                str(start_sec),
                "-to",
                str(end_sec),
                "-i",
                source_video_path,
                "-c:v",
                "libx264",
                "-preset",
                "veryfast",
                "-crf",
                "23",
                "-c:a",
                "aac",
                "-b:a",
                "128k",
                str(out_path),
            ]
            proc2 = subprocess.run(cmd_fallback, capture_output=True, text=True)
            if proc2.returncode != 0:
                seg["clip_error"] = (proc2.stderr or proc2.stdout or "ffmpeg failed")[:300]
                continue

        seg["clip_path"] = str(out_path)
        exported.append(seg)

    return exported
