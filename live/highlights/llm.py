# -*- coding: utf-8 -*-
"""LLM 增强：用于高光标题/摘要的语义优化。"""

import json
import logging
import re
import threading
import time
import concurrent.futures
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

import httpx
from sqlalchemy.orm import Session

from .llm_presets import get_preset
from .prompts import (
    build_highlight_system_prompt,
    build_highlight_user_prompt,
    build_l1_scout_system_prompt,
)
from sql.models import GlobalConfig

# 重试机制配置
_RETRY_MAX_ATTEMPTS = 3
_RETRY_BASE_DELAY = 1.0  # 秒
_RETRY_STATUS_CODES = {429, 500, 502, 503, 504}


logger = logging.getLogger(__name__)
_SCENE_TYPES = {"high_energy", "funny", "controversy", "teaching", "emotion"}
_NEGATIVE_REASONS = {"none", "tech_issue", "shopping_query", "greeting", "spam", "off_topic", "low_signal"}
_COMMENT_SAMPLE_MIN = 24
_COMMENT_SAMPLE_DEFAULT = 36
_COMMENT_SAMPLE_MID = 48
_COMMENT_SAMPLE_MAX = 64
_COMMENT_SAMPLE_RETRY_MAX = 128


def _looks_like_openai_family_model(model_name: str) -> bool:
    name = str(model_name or "").strip().lower()
    if not name:
        return False
    if name.startswith(("gpt-", "o1", "o3", "o4")):
        return True
    return False


def _looks_like_local_model_name(model_name: str) -> bool:
    name = str(model_name or "").strip().lower()
    if not name:
        return False
    if ":" in name:
        return True
    local_prefixes = (
        "qwen",
        "llama",
        "mistral",
        "gemma",
        "yi-",
        "phi",
        "deepseek-r1",
    )
    return name.startswith(local_prefixes)


def _deepseek_default_model_name(db: Session) -> str:
    row = db.query(GlobalConfig).filter(GlobalConfig.key == "llm_deepseek_model").first()
    value = (row.value or "").strip() if row else ""
    return value or "deepseek-chat"


@dataclass
class ChatConfig:
    provider: str
    enabled: bool
    api_key: str
    base_url: str
    model: str
    timeout_seconds: int = 20
    max_concurrency: int = 1
    mode: str = "openai_compat"
    disable_thinking: bool = False
    extra_params: Dict[str, object] = field(default_factory=dict)


_SEMAPHORES_LOCK = threading.Lock()
_SEMAPHORES: Dict[str, threading.BoundedSemaphore] = {}
_PROVIDER_SOURCE_MAP = {
    "ollama": "ollama",
    "local": "ollama",
    "minimax": "cloud",
    "cloud": "cloud",
    "deepseek": "deepseek",
    "compat": "compat",
}


def _read_global_config(db: Session, key: str) -> str:
    row = db.query(GlobalConfig).filter(GlobalConfig.key == key).first()
    return (row.value or "").strip() if row else ""


def _provider_to_source(provider: str) -> str:
    key = str(provider or "").strip().lower()
    return _PROVIDER_SOURCE_MAP.get(key, "cloud")


def _to_bool(value: Optional[str], default: bool = False) -> bool:
    if value is None:
        return default
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _normalize_ollama_base_url(base_url: str, mode: str) -> str:
    normalized = str(base_url or "").strip().rstrip("/")
    if mode == "native":
        if normalized.lower().endswith("/v1"):
            normalized = normalized[:-3].rstrip("/")
    elif mode == "openai_compat":
        # 如果是典型的 Ollama 端口且没有 /v1，自动补上
        if ":11434" in normalized and not normalized.lower().endswith("/v1"):
            normalized += "/v1"
    return normalized


def _load_minimax_config(db: Session) -> ChatConfig:
    minimax_preset = get_preset("MiniMax")
    default_base_url = (
        minimax_preset.base_url if minimax_preset else "https://api.minimaxi.com/v1"
    )
    default_model = minimax_preset.default_model if minimax_preset else "MiniMax-Text-01"

    keys = [
        "llm_minimax_enabled",
        "llm_minimax_api_key",
        "llm_minimax_base_url",
        "llm_minimax_model",
        "llm_minimax_timeout_seconds",
    ]
    rows = db.query(GlobalConfig).filter(GlobalConfig.key.in_(keys)).all()
    kv = {row.key: (row.value or "") for row in rows}

    timeout_val = 90
    try:
        timeout_val = max(5, min(120, int(kv.get("llm_minimax_timeout_seconds") or "90")))
    except Exception:
        timeout_val = 90

    return ChatConfig(
        provider="minimax",
        enabled=_to_bool(kv.get("llm_minimax_enabled"), default=False),
        api_key=(kv.get("llm_minimax_api_key") or "").strip(),
        base_url=(kv.get("llm_minimax_base_url") or default_base_url).strip(),
        model=(kv.get("llm_minimax_model") or default_model).strip(),
        timeout_seconds=timeout_val,
        max_concurrency=4,
    )


def _load_deepseek_config(db: Session) -> ChatConfig:
    deepseek_preset = get_preset("DeepSeek")
    default_base_url = (
        deepseek_preset.base_url if deepseek_preset else "https://api.deepseek.com"
    )
    default_model = deepseek_preset.default_model if deepseek_preset else "deepseek-chat"

    keys = [
        "llm_deepseek_enabled",
        "llm_deepseek_api_key",
        "llm_deepseek_base_url",
        "llm_deepseek_model",
        "llm_deepseek_timeout_seconds",
    ]
    rows = db.query(GlobalConfig).filter(GlobalConfig.key.in_(keys)).all()
    kv = {row.key: (row.value or "") for row in rows}

    timeout_val = 90
    try:
        timeout_val = max(5, min(120, int(kv.get("llm_deepseek_timeout_seconds") or "90")))
    except Exception:
        timeout_val = 90

    return ChatConfig(
        provider="deepseek",
        enabled=_to_bool(kv.get("llm_deepseek_enabled"), default=False),
        api_key=(kv.get("llm_deepseek_api_key") or "").strip(),
        base_url=(kv.get("llm_deepseek_base_url") or default_base_url).strip(),
        model=(kv.get("llm_deepseek_model") or default_model).strip(),
        timeout_seconds=timeout_val,
        max_concurrency=4,
    )


def _load_compat_config(db: Session) -> ChatConfig:
    compat_preset = get_preset("OpenAI")
    default_base_url = compat_preset.base_url if compat_preset else "https://api.openai.com/v1"
    default_model = compat_preset.default_model if compat_preset else "gpt-4o-mini"

    keys = [
        "llm_compat_enabled",
        "llm_compat_provider",
        "llm_compat_api_key",
        "llm_compat_base_url",
        "llm_compat_model",
        "llm_compat_timeout_seconds",
        "llm_compat_extra_params",
    ]
    rows = db.query(GlobalConfig).filter(GlobalConfig.key.in_(keys)).all()
    kv = {row.key: (row.value or "") for row in rows}

    timeout_val = 90
    try:
        timeout_val = max(5, min(120, int(kv.get("llm_compat_timeout_seconds") or "90")))
    except Exception:
        timeout_val = 90

    extra_params: Dict[str, object] = {}
    extra_params_raw = str(kv.get("llm_compat_extra_params") or "").strip()
    if extra_params_raw:
        try:
            parsed = json.loads(extra_params_raw)
            if isinstance(parsed, dict):
                extra_params = parsed
            else:
                logger.warning("llm_compat_extra_params 不是对象，已忽略: type=%s", type(parsed).__name__)
        except Exception as exc:
            logger.warning("解析 llm_compat_extra_params 失败，已忽略: %s", exc)

    provider_label = (kv.get("llm_compat_provider") or "openai_compat").strip().lower()
    return ChatConfig(
        provider=f"compat:{provider_label}",
        enabled=_to_bool(kv.get("llm_compat_enabled"), default=False),
        api_key=(kv.get("llm_compat_api_key") or "").strip(),
        base_url=(kv.get("llm_compat_base_url") or default_base_url).strip(),
        model=(kv.get("llm_compat_model") or default_model).strip(),
        timeout_seconds=timeout_val,
        max_concurrency=4,
        mode="openai_compat",
        extra_params=extra_params,
    )


def _load_ollama_config(db: Session) -> ChatConfig:
    ollama_preset = get_preset("Ollama")
    default_base_url = (
        ollama_preset.base_url if ollama_preset else "http://127.0.0.1:11434/v1"
    )
    default_model = ollama_preset.default_model if ollama_preset else "qwen2.5:7b"

    keys = [
        "llm_ollama_enabled",
        "llm_ollama_api_key",
        "llm_ollama_base_url",
        "llm_ollama_model",
        "llm_ollama_timeout_seconds",
        "llm_ollama_mode",
        "llm_ollama_disable_thinking",
        "llm_ollama_extra_params",
        "llm_ollama_max_concurrency",
    ]
    rows = db.query(GlobalConfig).filter(GlobalConfig.key.in_(keys)).all()
    kv = {row.key: (row.value or "") for row in rows}

    # 本地模型推理可能明显更慢，默认 180 秒；允许在 10~600 秒内调整。
    timeout_val = 180
    try:
        timeout_val = max(10, min(600, int(kv.get("llm_ollama_timeout_seconds") or "180")))
    except Exception:
        timeout_val = 180

    max_concurrency = 1
    try:
        max_concurrency = max(1, min(8, int(kv.get("llm_ollama_max_concurrency") or "1")))
    except Exception:
        max_concurrency = 1

    mode_raw = str(kv.get("llm_ollama_mode") or "native").strip().lower()
    if mode_raw not in {"native", "openai_compat"}:
        mode_raw = "native"

    disable_thinking = _to_bool(kv.get("llm_ollama_disable_thinking"), default=True)

    extra_params: Dict[str, object] = {}
    extra_params_raw = str(kv.get("llm_ollama_extra_params") or "").strip()
    if extra_params_raw:
        try:
            parsed = json.loads(extra_params_raw)
            if isinstance(parsed, dict):
                extra_params = parsed
            else:
                logger.warning("llm_ollama_extra_params 不是对象，已忽略: type=%s", type(parsed).__name__)
        except Exception as exc:
            logger.warning("解析 llm_ollama_extra_params 失败，已忽略: %s", exc)

    return ChatConfig(
        provider="ollama",
        enabled=_to_bool(kv.get("llm_ollama_enabled"), default=False),
        api_key=(kv.get("llm_ollama_api_key") or "").strip(),
        base_url=_normalize_ollama_base_url((kv.get("llm_ollama_base_url") or default_base_url).strip(), mode_raw),
        model=(kv.get("llm_ollama_model") or default_model).strip(),
        timeout_seconds=timeout_val,
        max_concurrency=max_concurrency,
        mode=mode_raw,
        disable_thinking=disable_thinking,
        extra_params=extra_params,
    )



def resolve_chat_config_from_model_config(model_cfg, db: Session, context: str = "legacy") -> ChatConfig:
    """根据用户传入的 AIModelConfig 动态解析 ChatConfig，支持彻底的全局自动跟随。"""
    if not model_cfg or model_cfg.provider == "none":
        return ChatConfig(provider="none", enabled=False, api_key="", base_url="", model="")

    provider = str(model_cfg.provider).lower()
    api_key = model_cfg.api_key or ""
    base_url = model_cfg.base_url or ""
    model_name = model_cfg.model or ""
    mode = "openai_compat"
    disable_thinking = False
    max_concurrency = 1

    # 处理完全自动跟随 (由前端 LiveHighlights.vue 传入 auto)。
    if provider == "auto":
        if context == "l1":
            provider = _read_global_config(db, "llm_l1_scout_provider") or "none"
            if not model_name:
                model_name = _read_global_config(db, "llm_l1_scout_model")
        elif context == "l2":
            provider = _read_global_config(db, "llm_l2_editor_provider") or "none"
            if not model_name:
                model_name = _read_global_config(db, "llm_l2_editor_model")

        if provider == "auto" or not provider:
            provider = _read_global_config(db, "llm_highlights_model_source") or "cloud"
    if provider == "none":
        return ChatConfig(provider="none", enabled=False, api_key="", base_url="", model="")

    source = _provider_to_source(provider)

    ollama_global_model = ""
    if source == "ollama":
        ollama_global_model = _read_global_config(db, "llm_ollama_model") or "qwen2.5:7b"
        # 优先使用请求体中的模型，缺失时回退全局设置。
        model_name = (model_name or ollama_global_model or "").strip()
        if _looks_like_openai_family_model(model_name):
            fallback_model = ollama_global_model
            logger.warning(
                "ollama.model_auto_correct from=%s to=%s base_url=%s",
                model_name,
                fallback_model,
                base_url,
            )
            model_name = fallback_model

        if not base_url:
            base_url = _read_global_config(db, "llm_ollama_base_url") or "http://localhost:11434/v1"
        if not model_name:
            model_name = ollama_global_model
        if not api_key:
            api_key = _read_global_config(db, "llm_ollama_api_key")

        mode = _read_global_config(db, "llm_ollama_mode") or "native"
        disable_thinking = _to_bool(_read_global_config(db, "llm_ollama_disable_thinking"), default=True)
        base_url = _normalize_ollama_base_url(base_url, mode)
        try:
            max_concurrency = max(1, min(8, int(_read_global_config(db, "llm_ollama_max_concurrency") or "1")))
        except Exception:
            max_concurrency = 1
    elif source == "cloud":
        if not base_url:
            base_url = _read_global_config(db, "llm_minimax_base_url") or "https://api.minimaxi.com/v1"
        global_model = (_read_global_config(db, "llm_minimax_model") or "").strip()
        model_name = model_name or global_model or "MiniMax-Text-01"
        if not api_key:
            api_key = _read_global_config(db, "llm_minimax_api_key")
        max_concurrency = 4
    elif source == "deepseek":
        if not base_url:
            base_url = _read_global_config(db, "llm_deepseek_base_url") or "https://api.deepseek.com"
        global_model = (_read_global_config(db, "llm_deepseek_model") or "").strip()
        model_name = model_name or global_model or "deepseek-chat"
        if not api_key:
            api_key = _read_global_config(db, "llm_deepseek_api_key")
        max_concurrency = 4
    elif source == "compat":
        if not base_url:
            base_url = _read_global_config(db, "llm_compat_base_url")
        global_model = (_read_global_config(db, "llm_compat_model") or "").strip()
        model_name = model_name or global_model
        if not api_key:
            api_key = _read_global_config(db, "llm_compat_api_key")
        max_concurrency = 4

    # 兜底：当 DeepSeek 官方地址搭配 OpenAI 家族模型名时，容易触发 400。
    # 这里自动回落到 DeepSeek 默认模型，避免前端历史默认值污染。
    if source == "deepseek":
        normalized_base = str(base_url or "").strip().lower()
        if "api.deepseek.com" in normalized_base and (
            _looks_like_openai_family_model(model_name) or _looks_like_local_model_name(model_name)
        ):
            fallback_model = _deepseek_default_model_name(db)
            logger.warning(
                "deepseek.model_auto_correct from=%s to=%s base_url=%s",
                model_name,
                fallback_model,
                base_url,
            )
            model_name = fallback_model

    override_concurrency = getattr(model_cfg, "max_concurrency", None)
    if override_concurrency is not None:
        try:
            max_concurrency = max(1, min(8, int(override_concurrency)))
        except Exception:
            pass

    extra_params_payload = {"temperature": model_cfg.temperature}
    if source == "ollama" and ollama_global_model:
        extra_params_payload["__fallback_model"] = ollama_global_model

    enabled_flag = bool(str(base_url or "").strip() and str(model_name or "").strip())
    if source != "ollama":
        enabled_flag = enabled_flag and bool(str(api_key or "").strip())

    return ChatConfig(
        provider=source,
        enabled=enabled_flag,
        api_key=api_key,
        base_url=base_url,
        model=model_name,
        max_concurrency=max_concurrency,
        mode=mode,
        disable_thinking=disable_thinking,
        extra_params=extra_params_payload,
    )


def resolve_chat_config_for_source(*, db: Session, model_source: str) -> tuple[str, Optional[ChatConfig], str]:
    """根据模型来源解析配置，并返回可读的配置错误信息（空串表示无错误）。"""
    source = str(model_source or "cloud").strip().lower()
    if source == "auto":
        source = "cloud"
    if source not in {"cloud", "deepseek", "compat", "local"}:
        return source, None, "模型来源无效，仅支持 cloud / deepseek / compat / local"

    if source == "local":
        config = _load_ollama_config(db)
        provider_name = "Ollama"
    elif source == "compat":
        config = _load_compat_config(db)
        provider_name = "兼容平台"
    elif source == "deepseek":
        config = _load_deepseek_config(db)
        provider_name = "DeepSeek"
    else:
        config = _load_minimax_config(db)
        provider_name = "MiniMax"

    if not config.enabled:
        return source, config, f"{provider_name} 未启用，请前往设置页完成配置并保存"
    if not str(config.base_url or "").strip():
        return source, config, f"{provider_name} Base URL 为空，请前往设置页配置"
    if not str(config.model or "").strip():
        return source, config, f"{provider_name} 模型名为空，请前往设置页配置"
    if source != "local" and not str(config.api_key or "").strip():
        return source, config, f"{provider_name} API Key 为空，请前往设置页配置"

    return source, config, ""


def _validate_chat_config(config: Optional[ChatConfig]) -> str:
    if not config:
        return "模型配置缺失"

    provider = str(getattr(config, "provider", "") or "").strip().lower()
    if provider in {"", "none"}:
        return "模型提供商未配置"

    base_url = str(getattr(config, "base_url", "") or "").strip()
    model_name = str(getattr(config, "model", "") or "").strip()
    api_key = str(getattr(config, "api_key", "") or "").strip()

    if not base_url:
        return "模型 Base URL 为空，请前往设置页配置"
    if not model_name:
        return "模型名为空，请前往设置页配置"
    if provider != "ollama" and not api_key:
        return "模型 API Key 为空，请前往设置页配置"
    return ""


def _strip_think_blocks(text: str) -> str:
    """剥离 <think>...</think> 推理链块，避免其内容干扰 JSON 提取。"""
    cleaned = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL | re.IGNORECASE)
    # 兼容未闭合的 <think>，直接截断到末尾，避免污染 JSON 抽取。
    cleaned = re.sub(r"<think>.*$", "", cleaned, flags=re.DOTALL | re.IGNORECASE)
    return cleaned.strip()


def _find_balanced_json_candidates(text: str) -> List[str]:
    candidates: List[str] = []
    start = -1
    depth = 0
    in_string = False
    escaped = False

    for idx, ch in enumerate(text):
        if in_string:
            if escaped:
                escaped = False
                continue
            if ch == "\\":
                escaped = True
                continue
            if ch == '"':
                in_string = False
            continue

        if ch == '"':
            in_string = True
            continue
        if ch == "{":
            if depth == 0:
                start = idx
            depth += 1
            continue
        if ch == "}":
            if depth <= 0:
                continue
            depth -= 1
            if depth == 0 and start >= 0:
                candidates.append(text[start : idx + 1])
                start = -1
    return candidates


def _decode_json_escaped_string(raw: str) -> str:
    s = str(raw or "")
    try:
        return str(json.loads(f'"{s}"'))
    except Exception:
        return s.replace("\\n", " ").replace("\\t", " ").strip()


def _extract_string_field_relaxed(text: str, key: str) -> str:
    if not text:
        return ""
    pattern_double = rf'"{re.escape(key)}"\s*:\s*"((?:\\.|[^"\\])*)"'
    m = re.search(pattern_double, text, flags=re.IGNORECASE | re.DOTALL)
    if m:
        return _decode_json_escaped_string(m.group(1)).strip()

    # 兼容少数非标准 JSON（单引号）输出。
    pattern_single = rf"'{re.escape(key)}'\s*:\s*'((?:\\.|[^'\\])*)'"
    m = re.search(pattern_single, text, flags=re.IGNORECASE | re.DOTALL)
    if m:
        return str(m.group(1)).strip()
    return ""


def _extract_last_object_fragment(text: str) -> str:
    if not text:
        return ""
    idx = text.rfind("{")
    fragment = text[idx:] if idx >= 0 else text
    # 去掉可能跟在后面的 markdown 围栏。
    fence_idx = fragment.find("```")
    if fence_idx >= 0:
        fragment = fragment[:fence_idx]
    return fragment.strip()


def _extract_keywords_relaxed(text: str) -> List[str]:
    if not text:
        return []
    m = re.search(r'"keywords"\s*:\s*\[([^\]]*)', text, flags=re.IGNORECASE | re.DOTALL)
    if not m:
        m = re.search(r"'keywords'\s*:\s*\[([^\]]*)", text, flags=re.IGNORECASE | re.DOTALL)
    if not m:
        return []

    body = m.group(1)
    values: List[str] = []
    for token in re.findall(r'"((?:\\.|[^"\\])*)"', body, flags=re.DOTALL):
        s = _decode_json_escaped_string(token).strip()
        if s:
            values.append(s)
    for token in re.findall(r"'((?:\\.|[^'\\])*)'", body, flags=re.DOTALL):
        s = str(token).strip()
        if s:
            values.append(s)

    deduped: List[str] = []
    seen = set()
    for kw in values:
        if kw in seen:
            continue
        seen.add(kw)
        deduped.append(kw)
        if len(deduped) >= 8:
            break
    return deduped


def _extract_relaxed_json_object(text: str) -> Optional[dict]:
    if not text:
        return None

    fragment = _extract_last_object_fragment(text)
    if not fragment:
        return None

    title = _extract_string_field_relaxed(fragment, "title")
    summary = _extract_string_field_relaxed(fragment, "summary")
    story_text = _extract_string_field_relaxed(fragment, "story_text")
    scene_type = _extract_string_field_relaxed(fragment, "scene_type").lower()
    negative_reason = _extract_string_field_relaxed(fragment, "negative_reason").lower()
    keywords = _extract_keywords_relaxed(fragment)

    if not title and not summary:
        return None

    if not title and summary:
        title = summary[:32]
    if not summary and title:
        summary = title
    if not story_text:
        story_text = summary or title

    # 宽松解析场景下，字段缺失时走保守默认，避免误把不确定结果当高光。
    is_highlight = False
    bool_match = re.search(
        r'"is_highlight"\s*:\s*(true|false|1|0)',
        fragment,
        flags=re.IGNORECASE,
    )
    if not bool_match:
        bool_match = re.search(
            r"'is_highlight'\s*:\s*(true|false|1|0)",
            fragment,
            flags=re.IGNORECASE,
        )
    if bool_match:
        bool_token = str(bool_match.group(1)).strip().lower()
        is_highlight = bool_token in {"true", "1"}

    confidence = 0.5
    confidence_match = re.search(
        r'"confidence"\s*:\s*(-?\d+(?:\.\d*)?)',
        fragment,
        flags=re.IGNORECASE,
    )
    if not confidence_match:
        confidence_match = re.search(
            r"'confidence'\s*:\s*(-?\d+(?:\.\d*)?)",
            fragment,
            flags=re.IGNORECASE,
        )
    if confidence_match:
        try:
            confidence = float(confidence_match.group(1))
        except Exception:
            confidence = 0.5

    def _extract_int_field(key: str, default_val: int = 0) -> int:
        m = re.search(rf'"{re.escape(key)}"\s*:\s*(-?\d+)', fragment, flags=re.IGNORECASE)
        if not m:
            m = re.search(rf"'{re.escape(key)}'\s*:\s*(-?\d+)", fragment, flags=re.IGNORECASE)
        if not m:
            return int(default_val)
        try:
            return int(m.group(1))
        except Exception:
            return int(default_val)

    return {
        "title": title[:64],
        "summary": summary[:220],
        "keywords": keywords,
        "story_text": story_text[:220],
        "scene_type": scene_type,
        "is_highlight": bool(is_highlight),
        "confidence": confidence,
        "negative_reason": negative_reason if negative_reason in _NEGATIVE_REASONS else "none",
        "start_shift_sec": _extract_int_field("start_shift_sec", 0),
        "end_shift_sec": _extract_int_field("end_shift_sec", 0),
    }


def _is_placeholder_text(value: str) -> bool:
    text = str(value or "").strip().lower()
    if not text:
        return True
    placeholders = {
        "title",
        "summary",
        "story_text",
        "关键词",
        "标题",
        "摘要",
        "剧情",
    }
    return text in placeholders


def _score_llm_json_candidate(candidate: dict) -> int:
    if not isinstance(candidate, dict):
        return -1

    score = 0
    for key in ("title", "summary", "story_text", "scene_type", "confidence", "negative_reason"):
        if key in candidate:
            score += 1

    title = str(candidate.get("title") or "").strip()
    summary = str(candidate.get("summary") or "").strip()
    story_text = str(candidate.get("story_text") or "").strip()
    scene_type = str(candidate.get("scene_type") or "").strip().lower()
    confidence = candidate.get("confidence")
    negative_reason = str(candidate.get("negative_reason") or "").strip().lower()
    keywords = candidate.get("keywords")

    if title and not _is_placeholder_text(title):
        score += 3
    if summary and not _is_placeholder_text(summary):
        score += 3
    if story_text and not _is_placeholder_text(story_text):
        score += 2
    if scene_type in _SCENE_TYPES:
        score += 2
    if isinstance(keywords, list) and any(str(k).strip() for k in keywords):
        score += 2
    if negative_reason in _NEGATIVE_REASONS:
        score += 1
    try:
        conf_val = float(confidence)
        if 0.0 <= conf_val <= 1.0:
            score += 2
    except Exception:
        pass

    return score


def _score_l1_json_candidate(candidate: dict) -> int:
    if not isinstance(candidate, dict):
        return -1

    score = 0
    for key in ("score", "reason", "is_high_energy"):
        if key in candidate:
            score += 1

    try:
        score_val = float(candidate.get("score"))
        if 0.0 <= score_val <= 1.0:
            score += 4
    except Exception:
        pass

    reason_val = str(candidate.get("reason") or "").strip()
    if reason_val and not _is_placeholder_text(reason_val):
        score += 2

    bool_like = {"1", "true", "yes", "on", "0", "false", "no", "off"}
    high_energy_val = candidate.get("is_high_energy")
    if isinstance(high_energy_val, bool) or str(high_energy_val).strip().lower() in bool_like:
        score += 2

    return score


def _is_valid_llm_result(parsed: Optional[dict]) -> bool:
    if not isinstance(parsed, dict):
        return False
    title = str(parsed.get("title") or "").strip()
    summary = str(parsed.get("summary") or "").strip()
    scene_type = str(parsed.get("scene_type") or "").strip().lower()
    # 至少要有可用标题或可用摘要，避免“有内容但被整体丢弃”。
    title_ok = bool(title and not _is_placeholder_text(title))
    summary_ok = bool(summary and not _is_placeholder_text(summary))
    if not (title_ok or summary_ok):
        return False
    # 兼容弱模型：scene_type 缺失或非法都允许通过，后续按原值兜底。
    if scene_type and scene_type not in _SCENE_TYPES:
        logger.debug("llm_result.scene_type_invalid ignored: %s", scene_type)
    return True


def _is_valid_l1_result(parsed: Optional[dict]) -> bool:
    if not isinstance(parsed, dict):
        return False
    score_val = parsed.get("score")
    score_ok = False
    try:
        score_num = float(score_val)
        score_ok = 0.0 <= score_num <= 1.0
    except Exception:
        score_ok = False

    # 兼容部分模型只返回布尔判定，不返回分数。
    bool_like = {"1", "true", "yes", "on", "0", "false", "no", "off"}
    high_energy_val = parsed.get("is_high_energy")
    high_energy_ok = isinstance(high_energy_val, bool) or str(high_energy_val).strip().lower() in bool_like
    return bool(score_ok or high_energy_ok)


def _extract_relaxed_l1_object(text: str) -> Optional[dict]:
    if not text:
        return None

    fragment = _extract_last_object_fragment(text)
    if not fragment:
        return None

    reason = _extract_string_field_relaxed(fragment, "reason")

    score_val = None
    score_match = re.search(r'"score"\s*:\s*(-?\d+(?:\.\d*)?)', fragment, flags=re.IGNORECASE)
    if not score_match:
        score_match = re.search(r"'score'\s*:\s*(-?\d+(?:\.\d*)?)", fragment, flags=re.IGNORECASE)
    if score_match:
        try:
            score_val = float(score_match.group(1))
        except Exception:
            score_val = None

    high_energy_val = None
    bool_match = re.search(r'"is_high_energy"\s*:\s*(true|false|1|0)', fragment, flags=re.IGNORECASE)
    if not bool_match:
        bool_match = re.search(r"'is_high_energy'\s*:\s*(true|false|1|0)", fragment, flags=re.IGNORECASE)
    if bool_match:
        token = str(bool_match.group(1)).strip().lower()
        high_energy_val = token in {"true", "1"}

    if score_val is None and high_energy_val is None:
        return None

    return {
        "score": round(max(0.0, min(1.0, float(score_val if score_val is not None else 0.5))), 4),
        "reason": reason[:120],
        "is_high_energy": bool(high_energy_val) if high_energy_val is not None else False,
    }


def _extract_json_from_text(text: str, schema: str = "l2") -> Optional[dict]:
    if not text:
        return None

    use_l1_schema = str(schema or "l2").strip().lower() == "l1"

    # 先剥离 CoT 推理块，防止 <think> 内部的示例 JSON 误导提取
    raw = _strip_think_blocks(text).strip()

    if raw.startswith("```"):
        lines = raw.splitlines()
        if len(lines) >= 3:
            raw = "\n".join(lines[1:-1]).strip()

    best_parsed: Optional[dict] = None
    best_score = -1
    for candidate in _find_balanced_json_candidates(raw):
        try:
            parsed = json.loads(candidate)
            if isinstance(parsed, dict):
                score = _score_l1_json_candidate(parsed) if use_l1_schema else _score_llm_json_candidate(parsed)
                if score > best_score:
                    best_score = score
                    best_parsed = parsed
        except Exception:
            continue
    if best_parsed:
        return best_parsed

    # 宽松兜底：用于处理“有字段但 JSON 尾部截断/夹杂解释文本”的弱模型输出。
    relaxed = _extract_relaxed_l1_object(raw) if use_l1_schema else _extract_relaxed_json_object(raw)
    if relaxed:
        logger.debug("llm.json_extractor fallback=relaxed_raw")
        return relaxed

    if raw != text:
        relaxed_orig = _extract_relaxed_l1_object(text) if use_l1_schema else _extract_relaxed_json_object(text)
        if relaxed_orig:
            logger.debug("llm.json_extractor fallback=relaxed_original")
            return relaxed_orig

    return None


def _extract_text_payload(value) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        parts: List[str] = []
        for item in value:
            if isinstance(item, str):
                if item.strip():
                    parts.append(item)
                continue
            if not isinstance(item, dict):
                continue
            text_val = item.get("text")
            if isinstance(text_val, str) and text_val.strip():
                parts.append(text_val)
        return "\n".join(parts).strip()
    if isinstance(value, dict):
        text_val = value.get("text")
        if isinstance(text_val, str):
            return text_val
    return ""


def _resolve_comment_sample_limit(chat_count: int) -> int:
    count = max(0, int(chat_count or 0))
    if count >= 90:
        return _COMMENT_SAMPLE_MAX
    if count >= 60:
        return _COMMENT_SAMPLE_MID
    if count >= 30:
        return _COMMENT_SAMPLE_DEFAULT
    return _COMMENT_SAMPLE_MIN


def _resolve_llm_budget(
    *,
    segments: List[Dict],
    strict_required: bool,
    segment_comments_map: Optional[Dict[str, List[str]]],
) -> int:
    total = len(segments)
    if total <= 0:
        return 0
    if strict_required:
        return total

    if total <= 24:
        return total

    if total <= 80:
        coverage_ratio = 0.8
    elif total <= 120:
        coverage_ratio = 0.65
    else:
        coverage_ratio = 0.55
    budget = int(round(total * coverage_ratio))
    budget = max(24, budget)

    if segment_comments_map:
        rich_segments = 0
        for seg in segments:
            seg_id = str(seg.get("id") or "")
            if len(segment_comments_map.get(seg_id) or []) >= _COMMENT_SAMPLE_DEFAULT:
                rich_segments += 1
        if rich_segments >= max(1, total // 2):
            budget += 8

    return min(total, max(8, min(96, budget)))


def _should_retry_uncertain_result(
    *,
    llm_decision_score: float,
    confidence: float,
    comments_count: int,
) -> bool:
    if comments_count < _COMMENT_SAMPLE_MIN:
        return False
    if confidence < 0.72:
        return True
    if 0.66 <= llm_decision_score <= 0.80:
        return True
    return False


def _uniform_sample_comments(comments: List[str], limit: int) -> List[str]:
    """均匀采样：适用于已按时间排序的评论列表。"""
    if limit <= 0 or not comments:
        return []
    if len(comments) <= limit:
        return comments
    if limit == 1:
        return [comments[len(comments) // 2]]

    n = len(comments)
    picked = []
    seen_idx = set()
    for i in range(limit):
        idx = int(round(i * (n - 1) / (limit - 1)))
        idx = max(0, min(n - 1, idx))
        if idx in seen_idx:
            continue
        seen_idx.add(idx)
        picked.append(comments[idx])

    if len(picked) < limit:
        for idx in range(n):
            if idx in seen_idx:
                continue
            seen_idx.add(idx)
            picked.append(comments[idx])
            if len(picked) >= limit:
                break
    return picked[:limit]


def _density_weighted_sample_comments(
    comments_with_ts: List[tuple[float, str]], limit: int
) -> List[str]:
    """密度加权采样：高密度时段的弹幕获得更多采样权重。

    1. 将时间窗口分成若干桶
    2. 每个桶根据弹幕数量分配采样配额
    3. 每桶内均匀采样
    """
    if limit <= 0 or not comments_with_ts:
        return []
    if len(comments_with_ts) <= limit:
        return [text for _, text in comments_with_ts]

    # 收集所有弹幕时间戳用于计算分布
    timestamps = [ts for ts, _ in comments_with_ts]
    if len(set(timestamps)) == 1:
        # 所有弹幕在同一时刻，用均匀采样
        return _uniform_sample_comments([text for _, text in comments_with_ts], limit)

    # 分桶：最少4桶，最多8桶，每桶至少3条弹幕
    num_buckets = min(8, max(4, len(comments_with_ts) // 6))
    bucket_size = len(comments_with_ts) / num_buckets

    buckets: List[List[tuple[float, str]]] = [[] for _ in range(num_buckets)]
    bucket_counts = [0] * num_buckets

    for i, (ts, text) in enumerate(comments_with_ts):
        bucket_idx = min(int(i / bucket_size), num_buckets - 1)
        buckets[bucket_idx].append((ts, text))
        bucket_counts[bucket_idx] += 1

    # 计算每桶的配额（按密度加权，但有最小/最大配额）
    total = len(comments_with_ts)
    quota = [max(2, min(limit // 2, int(c * limit / total) + 1)) for c in bucket_counts]

    # 调整配额确保总数不超过 limit
    while sum(quota) > limit:
        # 从配额最大的桶减1
        max_idx = quota.index(max(quota))
        if quota[max_idx] > 1:
            quota[max_idx] -= 1

    picked: List[tuple[float, str]] = []
    for bucket_idx, (bucket, q) in enumerate(zip(buckets, quota)):
        if not bucket or q <= 0:
            continue
        # 每桶内均匀采样
        bucket_texts = [text for _, text in bucket]
        bucket_samples = _uniform_sample_comments(bucket_texts, q)
        picked.extend(bucket_samples)

    # 如果还不够，随机补充
    all_picked_texts = set(picked)
    for _, text in comments_with_ts:
        if len(picked) >= limit:
            break
        if text not in all_picked_texts:
            picked.append(text)
            all_picked_texts.add(text)

    return picked[:limit]


def _collect_segment_comments(
    events: List,
    timeline_base_ts: Optional[float],
    start_sec: float,
    end_sec: float,
    danmu_delay_compensation_seconds: int = 0,
    limit: int = _COMMENT_SAMPLE_DEFAULT,
) -> List[str]:
    """收集片段内的弹幕，使用密度加权采样。"""
    if not events:
        return []

    base_ts = float(timeline_base_ts) if timeline_base_ts is not None else float(events[0].ts)
    abs_start = base_ts + max(0.0, float(start_sec))
    abs_end = base_ts + max(0.0, float(end_sec))
    delay = float(max(0, int(danmu_delay_compensation_seconds or 0)))

    comments_with_ts: List[tuple[float, str]] = []
    seen = set()

    for ev in events:
        if getattr(ev, "event_type", "") != "chat":
            continue
        ts = float(getattr(ev, "ts", 0.0))
        effective_ts = ts - delay
        if effective_ts < abs_start or effective_ts > abs_end:
            if effective_ts > abs_end:
                break
            continue
        text = str(getattr(ev, "text", "") or "").strip()
        text = re.sub(r"\s+", " ", text)
        text = text[:56].strip()
        if not text:
            continue
        if text in seen:
            continue
        seen.add(text)
        # 保存 (相对时间戳, 文本)
        rel_ts = effective_ts - abs_start
        comments_with_ts.append((rel_ts, text))

    effective_limit = max(_COMMENT_SAMPLE_MIN, min(_COMMENT_SAMPLE_MAX, int(limit or 0)))

    # 弹幕数量少时用均匀采样，多时用密度加权
    if len(comments_with_ts) <= effective_limit * 1.5:
        return _uniform_sample_comments([text for _, text in comments_with_ts], effective_limit)
    else:
        return _density_weighted_sample_comments(comments_with_ts, effective_limit)


def _call_chat_with_retry(
    config: ChatConfig,
    endpoint: str,
    headers: Dict[str, str],
    payload: Dict[str, object],
    is_ollama_native: bool,
    fallback_model: str = "",
) -> Optional[str]:
    """带有指数退避重试的 HTTP 请求。"""
    last_exception = None
    for attempt in range(_RETRY_MAX_ATTEMPTS):
        try:
            with httpx.Client(timeout=config.timeout_seconds) as client:
                logger.debug(
                    "%s 请求LLM(attempt=%s): endpoint=%s model=%s",
                    config.provider,
                    attempt + 1,
                    endpoint,
                    config.model,
                )
                resp = client.post(endpoint, headers=headers, json=payload)

                # 检查是否需要重试
                if resp.status_code in _RETRY_STATUS_CODES:
                    wait_time = _RETRY_BASE_DELAY * (2 ** attempt)
                    logger.warning(
                        "%s 请求被拒(attempt=%s status=%s)，等待 %.1f 秒后重试",
                        config.provider,
                        attempt + 1,
                        resp.status_code,
                        wait_time,
                    )
                    time.sleep(wait_time)
                    continue

                # 404/405 时尝试切换 Ollama 端点模式
                if is_ollama_native and resp.status_code in {404, 405}:
                    logger.info("ollama native 接口不可用，自动切换 openai_compat 端点重试")
                    endpoint = _normalize_ollama_base_url(config.base_url, "openai_compat") + "/chat/completions"
                    payload = _build_openai_compat_payload(config, endpoint, headers)
                    resp = client.post(endpoint, headers=headers, json=payload)
                    is_ollama_native = False

                # 400 错误时尝试移除 response_format
                if not is_ollama_native and resp.status_code >= 400 and resp.status_code in {400, 404, 415, 422}:
                    logger.info("%s 不支持 response_format，执行降级重试", config.provider)
                    fallback_payload = dict(payload)
                    fallback_payload.pop("response_format", None)
                    resp = client.post(endpoint, headers=headers, json=fallback_payload)

                # Ollama 404 时尝试回退模型
                if (
                    config.provider == "ollama"
                    and resp.status_code == 404
                    and fallback_model
                    and fallback_model != str(config.model or "").strip()
                ):
                    logger.info(
                        "ollama 当前模型不可用，自动回退重试 model=%s -> %s",
                        config.model,
                        fallback_model,
                    )
                    payload_retry = dict(payload)
                    payload_retry["model"] = fallback_model
                    resp = client.post(endpoint, headers=headers, json=payload_retry)

                resp.raise_for_status()

                try:
                    data = resp.json()
                except Exception as json_exc:
                    logger.warning(
                        "%s 响应JSON解码失败: err=%s body_preview=%s",
                        config.provider,
                        json_exc,
                        (resp.text or "")[:500],
                    )
                    return None

                # 提取 content
                content = _extract_response_content(data, is_ollama_native)
                if content is not None:
                    return content

                return None

        except httpx.TimeoutException as exc:
            last_exception = exc
            wait_time = _RETRY_BASE_DELAY * (2 ** attempt)
            logger.warning(
                "%s 请求超时(attempt=%s)，等待 %.1f 秒后重试: %s",
                config.provider,
                attempt + 1,
                wait_time,
                exc,
            )
            if attempt < _RETRY_MAX_ATTEMPTS - 1:
                time.sleep(wait_time)
                continue
        except httpx.HTTPStatusError as exc:
            last_exception = exc
            if exc.response.status_code in _RETRY_STATUS_CODES:
                wait_time = _RETRY_BASE_DELAY * (2 ** attempt)
                logger.warning(
                    "%s HTTP错误(attempt=%s status=%s)，等待 %.1f 秒后重试: %s",
                    config.provider,
                    attempt + 1,
                    exc.response.status_code,
                    wait_time,
                    exc,
                )
                if attempt < _RETRY_MAX_ATTEMPTS - 1:
                    time.sleep(wait_time)
                    continue
            logger.warning("%s 调用失败: %s", config.provider, exc)
            return None
        except Exception as exc:
            last_exception = exc
            wait_time = _RETRY_BASE_DELAY * (2 ** attempt)
            logger.warning(
                "%s 调用异常(attempt=%s)，等待 %.1f 秒后重试: %s",
                config.provider,
                attempt + 1,
                wait_time,
                exc,
            )
            if attempt < _RETRY_MAX_ATTEMPTS - 1:
                time.sleep(wait_time)
                continue

    logger.warning("%s 重试 %s 次后仍然失败: %s", config.provider, _RETRY_MAX_ATTEMPTS, last_exception)
    return None


def _build_openai_compat_payload(config: ChatConfig, endpoint: str, headers: Dict) -> Dict[str, object]:
    """构建 OpenAI 兼容格式的请求 payload。"""
    system_prompt = ""

    def _build_openai_compat_payload_inner() -> Dict[str, object]:
        req_payload: Dict[str, object] = {
            "model": config.model,
            "temperature": 0.0,
            "max_tokens": 520,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": ""},
            ],
            "response_format": {"type": "json_object"},
        }
        extra_params = getattr(config, "extra_params", {}) or {}
        if isinstance(extra_params, dict):
            for key, value in extra_params.items():
                if str(key).startswith("__"):
                    continue
                if key in {"model", "messages"}:
                    continue
                req_payload[key] = value
        return req_payload

    return _build_openai_compat_payload_inner()


def _extract_response_content(data: dict, is_ollama_native: bool) -> Optional[str]:
    """从响应数据中提取 content。"""
    message_obj = {}
    first_choice = {}
    choices = []
    if is_ollama_native:
        message_obj = data.get("message") if isinstance(data, dict) else {}
        if not isinstance(message_obj, dict):
            return None
    else:
        choices = data.get("choices") if isinstance(data, dict) else None
        if not isinstance(choices, list) or not choices:
            return None
        first_choice = choices[0] if isinstance(choices[0], dict) else {}
        message_obj = first_choice.get("message") if isinstance(first_choice, dict) else {}

    content = ""
    content_source = "content"
    if isinstance(message_obj, dict):
        content = _extract_text_payload(message_obj.get("content"))
        if not content.strip():
            for key in ("output_text", "reasoning", "thinking", "analysis"):
                alt_content = _extract_text_payload(message_obj.get(key))
                if alt_content.strip():
                    content = alt_content
                    content_source = key
                    break
        if not content.strip() and isinstance(first_choice, dict):
            alt_content = _extract_text_payload(first_choice.get("text"))
            if alt_content.strip():
                content = alt_content
                content_source = "choice.text"

    if not content.strip():
        logger.warning("%s 提取到空content", "ollama" if is_ollama_native else "openai")
        return None

    return content


def _call_chat_once(
    *,
    config: ChatConfig,
    user_prompt: str,
    temperature: float,
    max_tokens: int,
    response_schema: str = "l2",
) -> Optional[str]:
    system_prompt = (
        build_l1_scout_system_prompt()
        if str(response_schema or "l2").strip().lower() == "l1"
        else build_highlight_system_prompt()
    )

    def _build_openai_compat_payload() -> Dict[str, object]:
        req_payload: Dict[str, object] = {
            "model": config.model,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "messages": [
                {
                    "role": "system",
                    "content": system_prompt,
                },
                {"role": "user", "content": user_prompt},
            ],
            "response_format": {"type": "json_object"},
        }
        extra_params = getattr(config, "extra_params", {}) or {}
        if isinstance(extra_params, dict):
            for key, value in extra_params.items():
                if str(key).startswith("__"):
                    continue
                if key in {"model", "messages"}:
                    continue
                req_payload[key] = value
        return req_payload

    is_ollama_native = config.provider == "ollama" and getattr(config, "mode", "openai_compat") == "native"
    if is_ollama_native:
        endpoint = _normalize_ollama_base_url(config.base_url, "native") + "/api/chat"
        payload = {
            "model": config.model,
            "stream": False,
            "messages": [
                {
                    "role": "system",
                    "content": system_prompt,
                },
                {"role": "user", "content": user_prompt},
            ],
            "options": {
                "temperature": temperature,
                "num_predict": max_tokens,
            },
        }
        if getattr(config, "disable_thinking", False):
            payload["think"] = False
        extra_params = getattr(config, "extra_params", {}) or {}
        if isinstance(extra_params, dict):
            extra_options = extra_params.get("options")
            if isinstance(extra_options, dict):
                payload["options"].update(extra_options)
            for key, value in extra_params.items():
                if str(key).startswith("__"):
                    continue
                if key == "options":
                    continue
                if key in {"model", "messages", "stream"}:
                    continue
                if key in {"think", "format", "keep_alive", "template", "raw", "tools"}:
                    payload[key] = value
                else:
                    payload["options"][key] = value
    else:
        endpoint = config.base_url.rstrip("/") + "/chat/completions"
        payload = _build_openai_compat_payload()

    headers = {"Content-Type": "application/json"}
    if config.api_key:
        headers["Authorization"] = f"Bearer {config.api_key}"

    # 获取 fallback_model
    fallback_model = ""
    extra_params = getattr(config, "extra_params", {}) or {}
    if isinstance(extra_params, dict):
        fallback_model = str(extra_params.get("__fallback_model") or "").strip()

    # 使用带重试的调用
    content = _call_chat_with_retry(
        config=config,
        endpoint=endpoint,
        headers=headers,
        payload=payload,
        is_ollama_native=is_ollama_native,
        fallback_model=fallback_model,
    )

    if content is not None:
        logger.debug(
            "%s 结构化响应: content_len=%s",
            config.provider,
            len(content),
        )

    return content


@contextmanager
def _provider_concurrency_slot(config: ChatConfig):
    limit = max(1, int(getattr(config, "max_concurrency", 1) or 1))
    # 本地模型容易因并发导致格式抖动，按 provider/base_url/model 共享并发闸门。
    mode = getattr(config, "mode", "openai_compat")
    key = f"{config.provider}|{mode}|{config.base_url.rstrip('/')}|{config.model}|{limit}"
    with _SEMAPHORES_LOCK:
        sem = _SEMAPHORES.get(key)
        if sem is None:
            sem = threading.BoundedSemaphore(value=limit)
            _SEMAPHORES[key] = sem

    sem.acquire()
    try:
        yield
    finally:
        sem.release()


def _call_chat(config: ChatConfig, user_prompt: str, response_schema: str = "l2") -> Optional[dict]:
    schema = str(response_schema or "l2").strip().lower()
    if schema == "l1":
        attempts = [
            {
                "prompt": (
                    user_prompt
                    + "\n\n【输出要求】必须只输出一个 JSON 对象。"
                    + "必须包含: score,reason,is_high_energy。"
                    + "禁止任何前后缀文字、禁止 Markdown、禁止 <think>。"
                ),
                "temperature": 0.0,
                "max_tokens": 220,
            },
            {
                "prompt": (
                    user_prompt
                    + "\n\n【最后重试】只返回最小合法 JSON："
                    + '{"score":0.0,"reason":"", "is_high_energy":false}'
                    + " 禁止任何解释和前后缀。"
                ),
                "temperature": 0.0,
                "max_tokens": 180,
            },
        ]
    else:
        # 优先使用强约束提示词，减少“首轮输出思考过程”的无效调用。
        attempts = [
            {
                "prompt": (
                    user_prompt
                    + "\n\n【输出要求】必须只输出一个 JSON 对象，所有 key/value 使用双引号，禁止换行截断。"
                    + "禁止任何前后缀文字、禁止 Markdown、禁止 <think>。"
                ),
                "temperature": 0.0,
                "max_tokens": 520,
            },
            {
                "prompt": (
                    user_prompt
                    + "\n\n【最后重试】忽略所有分析过程，仅返回最小合法 JSON。"
                    + "必须包含: title,summary,keywords,story_text,scene_type,is_highlight,confidence,negative_reason,start_shift_sec,end_shift_sec。"
                    + "禁止任何解释和前后缀。"
                ),
                "temperature": 0.0,
                "max_tokens": 360,
            },
        ]

    last_content = ""
    for idx, attempt in enumerate(attempts, start=1):
        content = _call_chat_once(
            config=config,
            user_prompt=attempt["prompt"],
            temperature=attempt["temperature"],
            max_tokens=attempt["max_tokens"],
            response_schema=schema,
        )
        if content is None:
            continue
        last_content = content
        logger.debug("%s 原始响应长度(第%s次): %s", config.provider, idx, len(content))
        logger.debug("%s 原始响应内容(第%s次): %s", config.provider, idx, content)
        parsed = _extract_json_from_text(content, schema=schema)
        is_valid = _is_valid_l1_result(parsed) if schema == "l1" else _is_valid_llm_result(parsed)
        if parsed and is_valid:
            if idx > 1:
                logger.info("%s JSON 解析在重试后成功", config.provider)
            logger.debug(
                "%s 解析成功JSON(第%s次): %s",
                config.provider,
                idx,
                json.dumps(parsed, ensure_ascii=False)[:1200],
            )
            return parsed
        if parsed:
            if schema == "l1":
                logger.warning(
                    "%s 命中疑似模板/无效JSON(第%s次)，继续重试: keys=%s score=%s reason=%s is_high_energy=%s",
                    config.provider,
                    idx,
                    list(parsed.keys())[:12],
                    str(parsed.get("score") or "")[:20],
                    str(parsed.get("reason") or "")[:60],
                    str(parsed.get("is_high_energy") or "")[:12],
                )
            else:
                logger.warning(
                    "%s 命中疑似模板/无效JSON(第%s次)，继续重试: keys=%s title=%s summary=%s scene_type=%s",
                    config.provider,
                    idx,
                    list(parsed.keys())[:12],
                    str(parsed.get("title") or "")[:40],
                    str(parsed.get("summary") or "")[:60],
                    str(parsed.get("scene_type") or "")[:20],
                )
        else:
            logger.warning(
                "%s 未提取到JSON对象(第%s次)，内容预览=%s",
                config.provider,
                idx,
                content[:280],
            )

    if last_content:
        logger.warning("%s 返回内容解析 JSON 失败(重试后): %s", config.provider, last_content)
    return None


def _clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


def _scene_alignment_bias(expected_scene: str, llm_scene: str) -> float:
    expected = str(expected_scene or "").strip().lower()
    predicted = str(llm_scene or "").strip().lower()
    if predicted not in _SCENE_TYPES:
        return 0.0
    if expected and predicted == expected:
        return 0.08
    if expected and predicted != expected:
        return -0.05
    return 0.0


def _fuse_llm_scores(
    *,
    base_score: float,
    base_semantic: float,
    confidence: float,
    is_highlight: bool,
    expected_scene_type: str,
    llm_scene_type: str,
) -> Dict[str, float]:
    scene_bias = _scene_alignment_bias(expected_scene_type, llm_scene_type)
    highlight_bias = 0.08 if is_highlight else -0.22
    llm_decision_score = _clamp(confidence + scene_bias + highlight_bias, 0.0, 1.0)

    fused_sem = _clamp(base_semantic * 0.62 + llm_decision_score * 0.38, 0.0, 1.0)
    fused_score = _clamp(base_score * 0.50 + fused_sem * 0.15 + llm_decision_score * 0.35, 0.0, 1.0)

    if not is_highlight:
        fused_score = _clamp(fused_score * 0.72, 0.0, 1.0)
    elif llm_decision_score >= 0.86:
        fused_score = _clamp(fused_score + 0.03, 0.0, 1.0)

    return {
        "semantic_score": round(fused_sem, 4),
        "score": round(fused_score, 4),
        "llm_decision_score": round(llm_decision_score, 4),
        "llm_scene_bias": round(scene_bias, 4),
    }


def _as_bool(value, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return bool(default)
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _as_float(value, default: float) -> float:
    try:
        return float(value)
    except Exception:
        return float(default)


def _as_int(value, default: int) -> int:
    try:
        return int(round(float(value)))
    except Exception:
        return int(default)


def _apply_time_shift(item: Dict, start_shift: int, end_shift: int) -> None:
    old_start = _as_float(item.get("start_sec"), 0.0)
    old_end = _as_float(item.get("end_sec"), old_start + 12.0)

    safe_start_shift = int(_clamp(start_shift, -8, 8))
    safe_end_shift = int(_clamp(end_shift, -12, 8))
    new_start = max(0.0, old_start + safe_start_shift)
    new_end = max(new_start + 12.0, old_end + safe_end_shift)
    if (new_end - new_start) > 150.0:
        new_end = new_start + 150.0

    item["start_sec"] = round(new_start, 3)
    item["end_sec"] = round(new_end, 3)
    item["duration_sec"] = round(new_end - new_start, 3)
    item["llm_start_shift_sec"] = safe_start_shift
    item["llm_end_shift_sec"] = safe_end_shift


def maybe_enrich_segments_with_llm(
    *,
    db: Session,
    model_source: str,
    highlight_type: str,
    stream_type: Optional[str],
    story_enabled: bool,
    segments: List[Dict],
    events: Optional[List],
    timeline_base_ts: Optional[float],
    danmu_delay_compensation_seconds: int = 0,
    segment_comments_map: Optional[Dict[str, List[str]]] = None,
    progress_hook: Optional[Callable[[int, int, str], None]] = None,
    cancel_checker: Optional[Callable[[], None]] = None,
    strict_required: bool = False,
    l2_config: Optional[Any] = None,
) -> List[Dict]:
    if not segments:
        logger.info("highlights.llm.skip reason=no_segments")
        return segments

    if l2_config and l2_config.provider != "none":
        config = resolve_chat_config_from_model_config(l2_config, db, context="l2")
        source = f"custom:{config.provider}"
        config_error = None if config.enabled else "自定义 L2 模型配置不完整"
    else:
        source, config, config_error = resolve_chat_config_for_source(db=db, model_source=model_source)

    if not config_error:
        config_error = _validate_chat_config(config) or None
    
    if config_error:
        logger.info(
            "highlights.llm.skip reason=config_invalid model_source=%s strict=%s error=%s",
            source,
            bool(strict_required),
            config_error,
        )
        if strict_required:
            raise RuntimeError(config_error)
        if progress_hook and segments:
            total = len(segments)
            for i in range(total):
                progress_hook(i + 1, total, "降级规则")
        return segments

    logger.info(
        "highlights.llm.start provider=%s model=%s source=%s segments=%s stream_type=%s story_enabled=%s",
        config.provider,
        config.model,
        source,
        len(segments),
        (stream_type or "").strip()[:32],
        bool(story_enabled),
    )
    logger.info(
        "highlights.llm.concurrency provider=%s model=%s limit=%s",
        config.provider,
        config.model,
        config.max_concurrency,
    )
    enriched_slots: List[Optional[Dict]] = [None] * len(segments)
    # 动态预算：优先提高 AI 覆盖率；仅在超长列表时按比例限流。
    llm_budget = _resolve_llm_budget(
        segments=segments,
        strict_required=bool(strict_required),
        segment_comments_map=segment_comments_map,
    )
    enriched_count = 0
    llm_call_attempted_count = 0
    scene_changed_count = 0
    timing_adjusted_count = 0
    llm_negative_count = 0
    uncertain_retry_count = 0
    done_count = 0
    done_lock = threading.Lock()

    def _mark_progress() -> None:
        nonlocal done_count
        if progress_hook is None:
            return
        with done_lock:
            done_count += 1
            current = done_count
        progress_hook(current, len(segments), "LLM增强")

    def _process_l2_segment(index: int, seg: Dict[str, Any]) -> tuple[int, Dict[str, Any], Dict[str, int]]:
        if cancel_checker:
            cancel_checker()
        item = dict(seg)
        seg_id = str(item.get("id") or "")
        original_scene_type = str(item.get("highlight_type") or "")
        original_start_sec = _as_float(item.get("start_sec"), 0.0)
        original_end_sec = _as_float(item.get("end_sec"), original_start_sec + 12.0)
        metrics = {
            "attempted": 0,
            "enriched": 0,
            "scene_changed": 0,
            "timing_adjusted": 0,
            "llm_negative": 0,
            "uncertain_retry": 0,
        }

        comment_limit = _resolve_comment_sample_limit(int(item.get("chat_count") or 0))
        if segment_comments_map is not None:
            pre_comments = list(segment_comments_map.get(seg_id) or [])
            comments = _uniform_sample_comments(pre_comments, comment_limit)
        else:
            comments = _collect_segment_comments(
                events=events or [],
                timeline_base_ts=timeline_base_ts,
                start_sec=float(item.get("start_sec") or 0),
                end_sec=float(item.get("end_sec") or 0),
                danmu_delay_compensation_seconds=danmu_delay_compensation_seconds,
                limit=comment_limit,
            )
        logger.info(
            "Segment %s comments sampled=%s limit=%s chat_count=%s",
            index,
            len(comments),
            comment_limit,
            int(item.get("chat_count") or 0),
        )
        if len(comments) < 2:
            logger.info("Segment %s skipped: too few comments (%s)", index, len(comments))
            return index, item, metrics

        prompt = build_highlight_user_prompt(
            highlight_type=highlight_type,
            stream_type=stream_type,
            title=str(item.get("title") or ""),
            summary=str(item.get("summary") or ""),
            comments=comments,
            story_enabled=story_enabled,
            speech_text=str(item.get("speech_text") or ""),
        )
        metrics["attempted"] += 1
        with _provider_concurrency_slot(config):
            parsed = _call_chat(config, prompt, response_schema="l2")
        if not parsed:
            logger.info("Segment %s LLM call returned None", index)
            return index, item, metrics

        base_sem = _clamp(_as_float(item.get("semantic_score"), 0.45), 0.0, 1.0)
        base_score = _clamp(_as_float(item.get("score"), 0.45), 0.0, 1.0)

        def _parse_l2_output(parsed_obj: Dict[str, Any]) -> Dict[str, Any]:
            parsed_title = str(parsed_obj.get("title") or "").strip()
            parsed_summary = str(parsed_obj.get("summary") or "").strip()
            parsed_story_text = str(parsed_obj.get("story_text") or "").strip()
            parsed_scene_type = str(parsed_obj.get("scene_type") or "").strip().lower()
            parsed_is_highlight = _as_bool(parsed_obj.get("is_highlight"), default=False)
            parsed_confidence = _clamp(_as_float(parsed_obj.get("confidence"), 0.55), 0.0, 1.0)
            parsed_negative_reason = str(parsed_obj.get("negative_reason") or "none").strip().lower()
            if parsed_negative_reason not in _NEGATIVE_REASONS:
                parsed_negative_reason = "none"
            if parsed_is_highlight:
                parsed_negative_reason = "none"
            parsed_start_shift_sec = _as_int(parsed_obj.get("start_shift_sec"), 0)
            parsed_end_shift_sec = _as_int(parsed_obj.get("end_shift_sec"), 0)
            parsed_keywords = parsed_obj.get("keywords") or []
            if isinstance(parsed_keywords, list):
                parsed_keywords = [str(k).strip() for k in parsed_keywords if str(k).strip()]
            else:
                parsed_keywords = []
            parsed_score_pack = _fuse_llm_scores(
                base_score=base_score,
                base_semantic=base_sem,
                confidence=parsed_confidence,
                is_highlight=bool(parsed_is_highlight),
                expected_scene_type=highlight_type,
                llm_scene_type=parsed_scene_type,
            )
            return {
                "title": parsed_title,
                "summary": parsed_summary,
                "story_text": parsed_story_text,
                "scene_type": parsed_scene_type,
                "is_highlight": parsed_is_highlight,
                "confidence": parsed_confidence,
                "negative_reason": parsed_negative_reason,
                "start_shift_sec": parsed_start_shift_sec,
                "end_shift_sec": parsed_end_shift_sec,
                "keywords": parsed_keywords,
                "score_pack": parsed_score_pack,
            }

        parsed_fields = _parse_l2_output(parsed)

        logger.info(
            "Segment %s LLM parsed: title=%s summary=%s scene_type=%s confidence=%s negative_reason=%s shift=(%s,%s) keywords=%s story=%s",
            index,
            parsed_fields["title"][:60],
            parsed_fields["summary"][:120],
            parsed_fields["scene_type"][:24],
            str(parsed_fields["confidence"]),
            str(parsed_fields["negative_reason"]),
            str(parsed_fields["start_shift_sec"]),
            str(parsed_fields["end_shift_sec"]),
            parsed_fields["keywords"][:6],
            parsed_fields["story_text"][:120],
        )

        if _should_retry_uncertain_result(
            llm_decision_score=float(parsed_fields["score_pack"]["llm_decision_score"]),
            confidence=float(parsed_fields["confidence"]),
            comments_count=len(comments),
        ):
            expanded_limit = min(_COMMENT_SAMPLE_RETRY_MAX, max(comment_limit * 2, comment_limit + 24))
            if segment_comments_map is not None:
                pre_comments = list(segment_comments_map.get(seg_id) or [])
                retry_comments = _uniform_sample_comments(pre_comments, expanded_limit)
            else:
                retry_comments = _collect_segment_comments(
                    events=events or [],
                    timeline_base_ts=timeline_base_ts,
                    start_sec=float(item.get("start_sec") or 0),
                    end_sec=float(item.get("end_sec") or 0),
                    danmu_delay_compensation_seconds=danmu_delay_compensation_seconds,
                    limit=expanded_limit,
                )

            if len(retry_comments) >= len(comments) + 8:
                retry_prompt = build_highlight_user_prompt(
                    highlight_type=highlight_type,
                    stream_type=stream_type,
                    title=str(item.get("title") or ""),
                    summary=str(item.get("summary") or ""),
                    comments=retry_comments,
                    story_enabled=story_enabled,
                    speech_text=str(item.get("speech_text") or ""),
                )
                metrics["attempted"] += 1
                with _provider_concurrency_slot(config):
                    parsed_retry = _call_chat(config, retry_prompt, response_schema="l2")
                if parsed_retry:
                    retry_fields = _parse_l2_output(parsed_retry)
                    old_decision = float(parsed_fields["score_pack"]["llm_decision_score"])
                    old_score = float(parsed_fields["score_pack"]["score"])
                    new_decision = float(retry_fields["score_pack"]["llm_decision_score"])
                    new_score = float(retry_fields["score_pack"]["score"])
                    if (
                        new_decision >= old_decision + 0.05
                        or new_score >= old_score + 0.03
                    ):
                        parsed_fields = retry_fields
                        metrics["uncertain_retry"] += 1
                        logger.info(
                            "Segment %s uncertain_retry.accepted old_decision=%.4f new_decision=%.4f old_score=%.4f new_score=%.4f comments=%s->%s",
                            index,
                            old_decision,
                            new_decision,
                            old_score,
                            new_score,
                            len(comments),
                            len(retry_comments),
                        )

        title = str(parsed_fields["title"] or "").strip()
        summary = str(parsed_fields["summary"] or "").strip()
        story_text = str(parsed_fields["story_text"] or "").strip()
        scene_type = str(parsed_fields["scene_type"] or "").strip().lower()
        is_highlight = _as_bool(parsed_fields["is_highlight"], default=False)
        confidence = _clamp(_as_float(parsed_fields["confidence"], 0.55), 0.0, 1.0)
        negative_reason = str(parsed_fields["negative_reason"] or "none").strip().lower()
        if negative_reason not in _NEGATIVE_REASONS:
            negative_reason = "none"
        start_shift_sec = _as_int(parsed_fields["start_shift_sec"], 0)
        end_shift_sec = _as_int(parsed_fields["end_shift_sec"], 0)
        keywords = parsed_fields["keywords"] if isinstance(parsed_fields["keywords"], list) else []

        if title:
            item["title"] = title[:64]
        if summary:
            item["summary"] = summary[:220]
        if scene_type in _SCENE_TYPES:
            item["highlight_type"] = scene_type
            item["llm_scene_type"] = scene_type
            if scene_type != original_scene_type:
                metrics["scene_changed"] += 1
        if keywords:
            item["keywords"] = keywords[:8]

        score_pack = _fuse_llm_scores(
            base_score=base_score,
            base_semantic=base_sem,
            confidence=confidence,
            is_highlight=bool(is_highlight),
            expected_scene_type=highlight_type,
            llm_scene_type=scene_type,
        )
        item["semantic_score"] = score_pack["semantic_score"]
        item["score"] = score_pack["score"]
        item["llm_confidence"] = round(confidence, 4)
        item["llm_is_highlight"] = bool(is_highlight)
        item["llm_decision_score"] = score_pack["llm_decision_score"]
        item["llm_scene_bias"] = score_pack["llm_scene_bias"]
        item["llm_negative_reason"] = "none" if is_highlight else negative_reason
        if not is_highlight:
            metrics["llm_negative"] += 1

        _apply_time_shift(item, start_shift_sec, end_shift_sec)
        if (
            abs(_as_float(item.get("start_sec"), original_start_sec) - original_start_sec) > 1e-6
            or abs(_as_float(item.get("end_sec"), original_end_sec) - original_end_sec) > 1e-6
        ):
            metrics["timing_adjusted"] += 1

        if story_enabled:
            item["story_text"] = (story_text or summary or str(item.get("summary") or "")).strip()[:220]

        metrics["enriched"] += 1
        return index, item, metrics

    to_process: List[tuple[int, Dict[str, Any]]] = []
    for index, seg in enumerate(segments):
        if index >= llm_budget:
            enriched_slots[index] = dict(seg)
            _mark_progress()
            continue
        to_process.append((index, seg))

    if to_process:
        max_workers = max(1, min(int(config.max_concurrency or 1), len(to_process)))
        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_map = {
                executor.submit(_process_l2_segment, idx, seg): idx
                for idx, seg in to_process
            }
            for future in concurrent.futures.as_completed(future_map):
                index, item, metrics = future.result()
                enriched_slots[index] = item
                llm_call_attempted_count += int(metrics["attempted"])
                enriched_count += int(metrics["enriched"])
                scene_changed_count += int(metrics["scene_changed"])
                timing_adjusted_count += int(metrics["timing_adjusted"])
                llm_negative_count += int(metrics["llm_negative"])
                uncertain_retry_count += int(metrics["uncertain_retry"])
                _mark_progress()

    enriched: List[Dict] = []
    for index, seg in enumerate(segments):
        slot_item = enriched_slots[index]
        if slot_item is None:
            slot_item = dict(seg)
        enriched.append(slot_item)

    if strict_required and llm_call_attempted_count <= 0:
        raise RuntimeError("大模型严格模式下无可用弹幕样本，无法完成语义分析，请稍后重试或切换规则模式")
    if strict_required and llm_call_attempted_count > 0 and enriched_count <= 0:
        raise RuntimeError("大模型服务当前不可用或响应异常，请检查模型配置与服务状态后重试")

    enriched.sort(key=lambda x: (x.get("score", 0), x.get("heat_score", 0)), reverse=True)
    logger.info(
        "highlights.llm.done provider=%s total=%s budget=%s enriched=%s scene_changed=%s timing_adjusted=%s llm_negative=%s uncertain_retry=%s",
        config.provider,
        len(segments),
        llm_budget,
        enriched_count,
        scene_changed_count,
        timing_adjusted_count,
        llm_negative_count,
        uncertain_retry_count,
    )
    return enriched

def maybe_scout_segments_with_l1(
    db: Session,
    segments: List[Dict],
    model_cfg,
    highlight_type: str = "high_energy",
    stream_type: Optional[str] = None,
    cancel_checker: Optional[Callable[[], None]] = None,
    progress_hook: Optional[Callable[[int, int, str], None]] = None,
) -> List[Dict]:
    """L1 阶段：语义侦察兵。快速判定片段的能量等级。"""
    if not segments or not model_cfg or model_cfg.provider == "none":
        return segments

    config = resolve_chat_config_from_model_config(model_cfg, db, context="l1")
    if not config.enabled:
        return segments
    config_error = _validate_chat_config(config)
    if config_error:
        logger.warning("highlights.l1_scout.skip reason=config_invalid error=%s", config_error)
        return segments

    logger.info("highlights.l1_scout.start provider=%s model=%s segments=%s", config.provider, config.model, len(segments))
    
    scouted_slots: List[Optional[Dict]] = [None] * len(segments)
    done_count = 0
    done_lock = threading.Lock()

    def _mark_progress() -> None:
        nonlocal done_count
        if progress_hook is None:
            return
        with done_lock:
            done_count += 1
            current = done_count
        progress_hook(current, len(segments), "L1语义初筛")

    def _process_l1_segment(index: int, seg: Dict[str, Any]) -> tuple[int, Dict[str, Any]]:
        if cancel_checker:
            cancel_checker()
        item = dict(seg)
        comments = item.get("sample_texts", [])
        speech_text = str(item.get("speech_text") or "").strip()
        if not comments and not speech_text:
            return index, item

        # 构建上下文：优先语音转写，其次弹幕
        context_parts = []
        if speech_text:
            context_parts.append(f"主播语音：{speech_text[:200]}")
        if comments:
            texts_block = "\n".join(comments[:30])  # L1 限制采样数
            context_parts.append(f"弹幕样本：\n{texts_block}")

        context_block = "\n\n".join(context_parts)
        prompt = f"""作为高光判定员，请结合主播语音和弹幕判断该片段是否高光，并打分。
{context_block}

请仅输出以下格式的 JSON：
{{"score": 0.0-1.0, "reason": "简述原因", "is_high_energy": true/false}}
"""
        with _provider_concurrency_slot(config):
            parsed = _call_chat(config, prompt, response_schema="l1")

        if parsed:
            score_raw = parsed.get("score")
            score_present = score_raw is not None and str(score_raw).strip() != ""
            is_high_energy = _as_bool(parsed.get("is_high_energy"), default=False)
            if score_present:
                ai_score = _clamp(_as_float(score_raw, 0.5), 0.0, 1.0)
                # 同时返回布尔判定时，追加轻微偏置，避免布尔信号被忽略。
                ai_score = _clamp(ai_score + (0.08 if is_high_energy else -0.08), 0.0, 1.0)
            else:
                # 仅有布尔判定时也映射成可融合分数，避免退回中性分。
                ai_score = 0.78 if is_high_energy else 0.22
            item["l1_ai_score"] = ai_score
            item["l1_is_high_energy"] = bool(is_high_energy)
            item["l1_reason"] = parsed.get("reason")
            # 融合得分：L1 权重占 0.4
            base_score = _clamp(_as_float(item.get("score"), 0.0), 0.0, 1.0)
            item["score"] = round(_clamp(base_score * 0.6 + ai_score * 0.4, 0.0, 1.0), 4)
            logger.info("Segment %s L1 scout: score=%.2f reason=%s", index, ai_score, item["l1_reason"])
        if cancel_checker:
            cancel_checker()
        return index, item

    if progress_hook:
        progress_hook(0, len(segments), "L1语义初筛")
    max_workers = max(1, min(int(config.max_concurrency or 1), len(segments)))
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_map = {
            executor.submit(_process_l1_segment, index, seg): index
            for index, seg in enumerate(segments)
        }
        for future in concurrent.futures.as_completed(future_map):
            index, item = future.result()
            scouted_slots[index] = item
            _mark_progress()

    scouted: List[Dict] = []
    for index, seg in enumerate(segments):
        slot_item = scouted_slots[index]
        if slot_item is None:
            slot_item = dict(seg)
        scouted.append(slot_item)
    return scouted
