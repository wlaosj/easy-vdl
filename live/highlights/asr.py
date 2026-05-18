# -*- coding: utf-8 -*-
"""Candidate-level ASR enrichment for live highlights."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import subprocess
import tempfile
import threading
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable, Dict, List, Optional

from .storage import resolve_artifact_dir

logger = logging.getLogger(__name__)
os.environ.setdefault("HF_HOME", "/app/database/huggingface")

_MODEL_LOCK = threading.Lock()
_MODEL_CACHE: Dict[tuple[str, str, str], object] = {}


@dataclass
class AsrConfig:
    enabled: bool = True
    model: str = "small"
    device: str = "cpu"
    compute_type: str = "int8"
    language: str = "zh"
    max_segment_seconds: int = 90
    padding_seconds: int = 6
    beam_size: int = 1
    vad_filter: bool = True


def resolve_asr_path(file_path: str) -> str:
    return str(Path(resolve_artifact_dir(file_path)) / "analysis" / "asr_segments.v1.json")


def _load_asr_cache(file_path: str) -> Dict[str, dict]:
    path = resolve_asr_path(file_path)
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as fh:
            payload = json.load(fh)
        entries = payload.get("segments") if isinstance(payload, dict) else {}
        return entries if isinstance(entries, dict) else {}
    except Exception as exc:
        logger.warning("highlights.asr.cache_load_failed path=%s error=%s", path, exc)
        return {}


def _save_asr_cache(file_path: str, entries: Dict[str, dict]) -> str:
    path = resolve_asr_path(file_path)
    parent = Path(path).parent
    parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "video_path": file_path,
        "updated_at": datetime.now().isoformat(),
        "segments": entries,
    }
    fd, tmp_path = tempfile.mkstemp(prefix=".tmp_asr_", suffix=".json", dir=str(parent))
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
    return path


def _as_bool(value: object, default: bool = True) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return bool(default)
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def build_asr_config(
    *,
    enabled: bool = True,
    model: str = "small",
    device: str = "cpu",
    compute_type: str = "int8",
    language: str = "zh",
) -> AsrConfig:
    return AsrConfig(
        enabled=bool(enabled),
        model=str(model or "small").strip() or "small",
        device=str(device or "cpu").strip() or "cpu",
        compute_type=str(compute_type or "int8").strip() or "int8",
        language=str(language or "zh").strip() or "zh",
    )


def build_asr_config_from_env(enabled: bool = True) -> AsrConfig:
    return build_asr_config(
        enabled=_as_bool(os.getenv("EASY_VDL_HIGHLIGHTS_ASR_ENABLED"), default=enabled),
        model=os.getenv("EASY_VDL_HIGHLIGHTS_ASR_MODEL", "small"),
        device=os.getenv("EASY_VDL_HIGHLIGHTS_ASR_DEVICE", "cpu"),
        compute_type=os.getenv("EASY_VDL_HIGHLIGHTS_ASR_COMPUTE_TYPE", "int8"),
        language=os.getenv("EASY_VDL_HIGHLIGHTS_ASR_LANGUAGE", "zh"),
    )


def _cache_key(seg: Dict, config: AsrConfig) -> str:
    start_sec = round(float(seg.get("start_sec") or 0.0), 1)
    end_sec = round(float(seg.get("end_sec") or 0.0), 1)
    raw = f"{start_sec}|{end_sec}|{config.model}|{config.language}|{config.padding_seconds}|{config.max_segment_seconds}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:20]


def _get_model(config: AsrConfig):
    key = (config.model, config.device, config.compute_type)
    with _MODEL_LOCK:
        model = _MODEL_CACHE.get(key)
        if model is not None:
            return model
        try:
            from faster_whisper import WhisperModel
        except Exception as exc:
            raise RuntimeError("ASR 依赖未安装，请安装 faster-whisper") from exc

        started = time.perf_counter()
        model = WhisperModel(config.model, device=config.device, compute_type=config.compute_type)
        _MODEL_CACHE[key] = model
        logger.info(
            "highlights.asr.model_loaded model=%s device=%s compute_type=%s duration=%.3fs",
            config.model,
            config.device,
            config.compute_type,
            time.perf_counter() - started,
        )
        return model


def _extract_audio_clip(source_video_path: str, start_sec: float, duration_sec: float) -> str:
    fd, wav_path = tempfile.mkstemp(prefix="easy_vdl_asr_", suffix=".wav")
    os.close(fd)
    cmd = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-ss",
        f"{max(0.0, start_sec):.3f}",
        "-t",
        f"{max(0.1, duration_sec):.3f}",
        "-i",
        source_video_path,
        "-vn",
        "-ac",
        "1",
        "-ar",
        "16000",
        wav_path,
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        try:
            os.unlink(wav_path)
        except OSError:
            pass
        raise RuntimeError((proc.stderr or proc.stdout or "ffmpeg audio extract failed")[:300])
    return wav_path


def _clean_speech_text(text: str, max_chars: int = 900) -> str:
    cleaned = " ".join(str(text or "").split())
    return cleaned[:max_chars]


def transcribe_segments(
    *,
    source_video_path: str,
    segments: List[Dict],
    config: Optional[AsrConfig] = None,
    progress_hook: Optional[Callable[[int, int, str], None]] = None,
    cancel_checker: Optional[Callable[[], None]] = None,
) -> Dict[str, dict]:
    config = config or build_asr_config_from_env(enabled=True)
    if not config.enabled or not segments:
        return {}
    if not os.path.exists(source_video_path):
        logger.warning("highlights.asr.skip reason=video_missing path=%s", source_video_path)
        return {}

    entries = _load_asr_cache(source_video_path)
    model = None
    results: Dict[str, dict] = {}
    total = len(segments)

    for index, seg in enumerate(segments):
        if cancel_checker:
            cancel_checker()

        seg_id = str(seg.get("id") or "")
        if not seg_id:
            continue

        key = _cache_key(seg, config)
        cached = entries.get(key)
        if isinstance(cached, dict) and str(cached.get("text") or "").strip():
            results[seg_id] = dict(cached)
            if progress_hook:
                progress_hook(index + 1, total, "ASR缓存")
            continue

        start_sec = float(seg.get("start_sec") or 0.0)
        end_sec = float(seg.get("end_sec") or start_sec)
        padded_start = max(0.0, start_sec - config.padding_seconds)
        padded_end = max(padded_start + 0.1, end_sec + config.padding_seconds)
        duration = min(float(config.max_segment_seconds), padded_end - padded_start)

        wav_path = ""
        started = time.perf_counter()
        try:
            if model is None:
                model = _get_model(config)
            wav_path = _extract_audio_clip(source_video_path, padded_start, duration)
            asr_segments, info = model.transcribe(
                wav_path,
                language=config.language or None,
                beam_size=max(1, int(config.beam_size or 1)),
                vad_filter=bool(config.vad_filter),
            )
            rows = list(asr_segments)
            text = _clean_speech_text("".join(row.text for row in rows))
            item = {
                "segment_id": seg_id,
                "cache_key": key,
                "start_sec": round(padded_start, 3),
                "end_sec": round(padded_start + duration, 3),
                "duration_sec": round(duration, 3),
                "text": text,
                "language": str(getattr(info, "language", config.language) or ""),
                "language_probability": round(float(getattr(info, "language_probability", 0.0) or 0.0), 4),
                "model": config.model,
                "device": config.device,
                "compute_type": config.compute_type,
                "transcribed_at": datetime.now().isoformat(),
                "elapsed_sec": round(time.perf_counter() - started, 3),
            }
            entries[key] = item
            results[seg_id] = item
            logger.info(
                "highlights.asr.segment_done index=%s text_len=%s elapsed=%.3fs",
                index,
                len(text),
                time.perf_counter() - started,
            )
        except Exception as exc:
            logger.warning("highlights.asr.segment_failed index=%s error=%s", index, exc)
            results[seg_id] = {
                "segment_id": seg_id,
                "cache_key": key,
                "text": "",
                "error": str(exc)[:300],
                "model": config.model,
            }
        finally:
            if wav_path:
                try:
                    os.unlink(wav_path)
                except OSError:
                    pass
            if progress_hook:
                progress_hook(index + 1, total, "ASR转写")

    if entries:
        try:
            cache_path = _save_asr_cache(source_video_path, entries)
            for item in results.values():
                item["speech_text_path"] = cache_path
        except Exception as exc:
            logger.warning("highlights.asr.cache_save_failed error=%s", exc)

    return results
