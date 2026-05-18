# -*- coding: utf-8 -*-
"""Highlights request normalization and lightweight fallback helpers."""

import re
from typing import Dict, List, Optional

from .schemas import AnalyzeRequest


def sanitize_stream_type(raw: Optional[str]) -> str:
    text = str(raw or "").strip()
    if not text:
        return ""
    text = re.sub(r"\s+", " ", text)
    return text[:64]


def normalize_analyze_request(request: AnalyzeRequest) -> AnalyzeRequest:
    stream_type = sanitize_stream_type(request.stream_type)
    normalized_source = str(request.model_source or "cloud").strip().lower()
    if normalized_source == "auto":
        normalized_source = "cloud"
    if normalized_source not in {"cloud", "deepseek", "compat", "local"}:
        normalized_source = "cloud"
    normalized_strategy = str(request.analysis_strategy or "hybrid").strip().lower()
    if normalized_strategy not in {"hybrid", "rule_only", "llm_required"}:
        normalized_strategy = "hybrid"
    return request.model_copy(
        update={
            "stream_type": (stream_type or None),
            "mode": "offline",
            "story_enabled": bool(request.story_enabled),
            "asr_enabled": bool(request.asr_enabled),
            "model_source": normalized_source,
            "analysis_strategy": normalized_strategy,
            "danmu_delay_compensation_seconds": max(
                0,
                min(30, int(request.danmu_delay_compensation_seconds or 0)),
            ),
        }
    )


def apply_story_fallback(segments: List[Dict], story_enabled: bool) -> List[Dict]:
    if not story_enabled:
        return segments
    out: List[Dict] = []
    for seg in segments:
        item = dict(seg)
        story_text = str(item.get("story_text") or "").strip()
        if not story_text:
            story_text = str(item.get("summary") or "").strip()
        if story_text:
            item["story_text"] = story_text[:220]
        out.append(item)
    return out
