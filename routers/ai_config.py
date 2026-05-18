import logging
import os
import shutil
import time
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException, Body
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from sql import models
from sql.database_postgresql import get_db
from routers.auth import get_current_user
from sql.models import User
from live.highlights.llm_presets import get_preset_dict

logger = logging.getLogger(__name__)
router = APIRouter()

# ASR 模型下载状态记录（内存）
# key: 模型名称如 "tiny", "base", "small", "medium"
# value: {"started_at": timestamp, "started_by": username}
_asr_downloading: dict = {}
_asr_downloading_lock = __import__("threading").Lock()

def _set_asr_downloading(model_name: str, username: str):
    """设置模型正在下载"""
    with _asr_downloading_lock:
        _asr_downloading[model_name] = {
            "started_at": time.time(),
            "started_by": username,
        }

def _clear_asr_downloading(model_name: str):
    """清除模型下载状态"""
    with _asr_downloading_lock:
        _asr_downloading.pop(model_name, None)

def _get_asr_downloading_status() -> dict:
    """获取当前正在下载的模型状态"""
    with _asr_downloading_lock:
        return dict(_asr_downloading)

def _is_asr_model_downloading(model_name: str) -> bool:
    """检查指定模型是否正在下载"""
    with _asr_downloading_lock:
        return model_name in _asr_downloading

ASR_MODEL_SPECS = {
    "tiny": {
        "label": "快速 tiny",
        "repo_id": "Systran/faster-whisper-tiny",
        "description": "最快，适合连通性测试或低配机器，准确率较低。",
    },
    "base": {
        "label": "基础 base",
        "repo_id": "Systran/faster-whisper-base",
        "description": "速度快，资源占用低，适合轻量使用。",
    },
    "small": {
        "label": "均衡 small",
        "repo_id": "Systran/faster-whisper-small",
        "description": "推荐默认版本，CPU 可用，准确率和速度比较均衡。",
    },
    "medium": {
        "label": "高质量 medium",
        "repo_id": "Systran/faster-whisper-medium",
        "description": "准确率更高，CPU 首次加载和转写会明显更慢。",
    },
}

# AI 配置键集合（用于读取/清空）
AI_CONFIG_KEYS = [
    "llm_minimax_enabled",
    "llm_minimax_base_url",
    "llm_minimax_model",
    "llm_minimax_api_key",
    "llm_minimax_timeout_seconds",
    "llm_deepseek_enabled",
    "llm_deepseek_base_url",
    "llm_deepseek_model",
    "llm_deepseek_api_key",
    "llm_deepseek_timeout_seconds",
    "llm_compat_enabled",
    "llm_compat_provider",
    "llm_compat_base_url",
    "llm_compat_model",
    "llm_compat_api_key",
    "llm_compat_timeout_seconds",
    "llm_compat_extra_params",
    "llm_ollama_enabled",
    "llm_ollama_base_url",
    "llm_ollama_model",
    "llm_ollama_api_key",
    "llm_ollama_timeout_seconds",
    "llm_ollama_mode",
    "llm_ollama_disable_thinking",
    "llm_ollama_extra_params",
    "llm_ollama_vision_capability",
    "llm_ollama_vision_checked_at",
    "llm_ollama_vision_detail",
    "llm_highlights_model_source",
    "llm_l1_scout_provider",
    "llm_l1_scout_model",
    "llm_l2_editor_provider",
    "llm_l2_editor_model",
]


def _upsert_global_config(db: Session, key: str, value: str) -> None:
    row = db.query(models.GlobalConfig).filter_by(key=key).first()
    if row:
        row.value = value
    else:
        db.add(models.GlobalConfig(key=key, value=value))


def _asr_hf_home() -> Path:
    return Path(os.environ.get("HF_HOME") or "/app/database/huggingface").expanduser()


def _asr_cache_dir() -> Path:
    return _asr_hf_home() / "hub"


def _asr_model_cache_path(model_name: str) -> Path:
    spec = ASR_MODEL_SPECS[model_name]
    namespace, repo = spec["repo_id"].split("/", 1)
    return _asr_cache_dir() / f"models--{namespace}--{repo}"


def _dir_size_bytes(path: Path) -> int:
    total = 0
    if not path.exists():
        return total
    for item in path.rglob("*"):
        try:
            if item.is_file():
                total += item.stat().st_size
        except OSError:
            continue
    return total


def _asr_model_info(model_name: str) -> dict[str, Any]:
    spec = ASR_MODEL_SPECS[model_name]
    path = _asr_model_cache_path(model_name)
    snapshots = path / "snapshots"
    installed = snapshots.exists() and any(snapshots.iterdir())
    size_bytes = _dir_size_bytes(path) if path.exists() else 0
    return {
        "name": model_name,
        "label": spec["label"],
        "repo_id": spec["repo_id"],
        "description": spec["description"],
        "installed": installed,
        "size_bytes": size_bytes,
        "cache_path": str(path),
    }


def _validate_asr_model_name(model_name: str) -> str:
    normalized = str(model_name or "").strip().lower()
    if normalized not in ASR_MODEL_SPECS:
        raise HTTPException(status_code=404, detail=f"不支持的 ASR 模型版本: {model_name}")
    return normalized


@router.get("/api/ai-config/")
def get_ai_config(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """获取 AI 相关配置。"""
    minimax_enabled = False
    minimax_base_url = "https://api.minimaxi.com/v1"
    minimax_model = "MiniMax-Text-01"
    minimax_api_key = ""
    minimax_timeout_seconds = 90

    deepseek_enabled = False
    deepseek_base_url = "https://api.deepseek.com"
    deepseek_model = "deepseek-chat"
    deepseek_api_key = ""
    deepseek_timeout_seconds = 90

    compat_enabled = False
    compat_provider = "OpenAI"
    compat_base_url = "https://api.openai.com/v1"
    compat_model = "gpt-4o-mini"
    compat_api_key = ""
    compat_timeout_seconds = 90
    compat_extra_params = "{}"

    ollama_enabled = False
    ollama_base_url = "http://127.0.0.1:11434"
    ollama_model = "qwen2.5:7b"
    ollama_api_key = ""
    ollama_timeout_seconds = 180
    ollama_mode = "native"
    ollama_disable_thinking = True
    ollama_extra_params = "{}"
    ollama_vision_capability = "unknown"
    ollama_vision_checked_at = ""
    ollama_vision_detail = ""

    highlights_model_source = "cloud"
    l1_scout_provider = "none"
    l1_scout_model = ""
    l2_editor_provider = "none"
    l2_editor_model = ""

    try:
        rows = db.query(models.GlobalConfig).filter(models.GlobalConfig.key.in_(AI_CONFIG_KEYS)).all()
        kv = {row.key: (row.value or "") for row in rows}

        minimax_enabled = str(kv.get("llm_minimax_enabled") or "false").strip().lower() == "true"
        if kv.get("llm_minimax_base_url"):
            minimax_base_url = str(kv.get("llm_minimax_base_url")).strip()
        if kv.get("llm_minimax_model"):
            minimax_model = str(kv.get("llm_minimax_model")).strip()
        if kv.get("llm_minimax_api_key"):
            minimax_api_key = str(kv.get("llm_minimax_api_key")).strip()
        if kv.get("llm_minimax_timeout_seconds"):
            minimax_timeout_seconds = max(5, min(120, int(kv.get("llm_minimax_timeout_seconds") or 90)))

        deepseek_enabled = str(kv.get("llm_deepseek_enabled") or "false").strip().lower() == "true"
        if kv.get("llm_deepseek_base_url"):
            deepseek_base_url = str(kv.get("llm_deepseek_base_url")).strip()
        if kv.get("llm_deepseek_model"):
            deepseek_model = str(kv.get("llm_deepseek_model")).strip()
        if kv.get("llm_deepseek_api_key"):
            deepseek_api_key = str(kv.get("llm_deepseek_api_key")).strip()
        if kv.get("llm_deepseek_timeout_seconds"):
            deepseek_timeout_seconds = max(5, min(120, int(kv.get("llm_deepseek_timeout_seconds") or 90)))

        compat_enabled = str(kv.get("llm_compat_enabled") or "false").strip().lower() == "true"
        if kv.get("llm_compat_provider"):
            compat_provider = str(kv.get("llm_compat_provider")).strip()
        if kv.get("llm_compat_base_url"):
            compat_base_url = str(kv.get("llm_compat_base_url")).strip()
        if kv.get("llm_compat_model"):
            compat_model = str(kv.get("llm_compat_model")).strip()
        if kv.get("llm_compat_api_key"):
            compat_api_key = str(kv.get("llm_compat_api_key")).strip()
        if kv.get("llm_compat_timeout_seconds"):
            compat_timeout_seconds = max(5, min(120, int(kv.get("llm_compat_timeout_seconds") or 90)))
        if kv.get("llm_compat_extra_params"):
            try:
                extra_obj = json.loads(str(kv.get("llm_compat_extra_params")))
                if isinstance(extra_obj, dict):
                    compat_extra_params = json.dumps(extra_obj, ensure_ascii=False, separators=(",", ":"))
            except Exception:
                pass

        ollama_enabled = str(kv.get("llm_ollama_enabled") or "false").strip().lower() == "true"
        if kv.get("llm_ollama_base_url"):
            ollama_base_url = str(kv.get("llm_ollama_base_url")).strip()
        if kv.get("llm_ollama_model"):
            ollama_model = str(kv.get("llm_ollama_model")).strip()
        if kv.get("llm_ollama_api_key"):
            ollama_api_key = str(kv.get("llm_ollama_api_key")).strip()
        if kv.get("llm_ollama_timeout_seconds"):
            ollama_timeout_seconds = max(10, min(600, int(kv.get("llm_ollama_timeout_seconds") or 180)))

        mode_value = str(kv.get("llm_ollama_mode") or "native").strip().lower()
        if mode_value in {"native", "openai_compat"}:
            ollama_mode = mode_value

        ollama_disable_thinking = str(kv.get("llm_ollama_disable_thinking") or "true").strip().lower() == "true"

        if kv.get("llm_ollama_extra_params"):
            try:
                extra_obj = json.loads(str(kv.get("llm_ollama_extra_params")))
                if isinstance(extra_obj, dict):
                    ollama_extra_params = json.dumps(extra_obj, ensure_ascii=False, separators=(",", ":"))
            except Exception:
                pass

        capability_val = str(kv.get("llm_ollama_vision_capability") or "unknown").strip().lower()
        if capability_val in {"supported", "unsupported", "unknown"}:
            ollama_vision_capability = capability_val
        if kv.get("llm_ollama_vision_checked_at"):
            ollama_vision_checked_at = str(kv.get("llm_ollama_vision_checked_at")).strip()
        if kv.get("llm_ollama_vision_detail"):
            ollama_vision_detail = str(kv.get("llm_ollama_vision_detail")).strip()[:500]

        source_value = str(kv.get("llm_highlights_model_source") or "cloud").strip().lower()
        if source_value in {"cloud", "deepseek", "compat", "local"}:
            highlights_model_source = source_value
        
        if kv.get("llm_l1_scout_provider"):
            l1_scout_provider = str(kv.get("llm_l1_scout_provider")).strip()
        if kv.get("llm_l1_scout_model"):
            l1_scout_model = str(kv.get("llm_l1_scout_model")).strip()
        if kv.get("llm_l2_editor_provider"):
            l2_editor_provider = str(kv.get("llm_l2_editor_provider")).strip()
        if kv.get("llm_l2_editor_model"):
            l2_editor_model = str(kv.get("llm_l2_editor_model")).strip()
    except Exception as e:
        logger.warning(f"读取 AI 配置失败，将使用默认值: {e}")

    return {
        "llm_minimax_enabled": minimax_enabled,
        "llm_minimax_base_url": minimax_base_url,
        "llm_minimax_model": minimax_model,
        "llm_minimax_api_key": minimax_api_key,
        "llm_minimax_timeout_seconds": minimax_timeout_seconds,
        "llm_deepseek_enabled": deepseek_enabled,
        "llm_deepseek_base_url": deepseek_base_url,
        "llm_deepseek_model": deepseek_model,
        "llm_deepseek_api_key": deepseek_api_key,
        "llm_deepseek_timeout_seconds": deepseek_timeout_seconds,
        "llm_compat_enabled": compat_enabled,
        "llm_compat_provider": compat_provider,
        "llm_compat_base_url": compat_base_url,
        "llm_compat_model": compat_model,
        "llm_compat_api_key": compat_api_key,
        "llm_compat_timeout_seconds": compat_timeout_seconds,
        "llm_compat_extra_params": compat_extra_params,
        "llm_ollama_enabled": ollama_enabled,
        "llm_ollama_base_url": ollama_base_url,
        "llm_ollama_model": ollama_model,
        "llm_ollama_api_key": ollama_api_key,
        "llm_ollama_timeout_seconds": ollama_timeout_seconds,
        "llm_ollama_mode": ollama_mode,
        "llm_ollama_disable_thinking": ollama_disable_thinking,
        "llm_ollama_extra_params": ollama_extra_params,
        "llm_ollama_vision_capability": ollama_vision_capability,
        "llm_ollama_vision_checked_at": ollama_vision_checked_at,
        "llm_ollama_vision_detail": ollama_vision_detail,
        "llm_highlights_model_source": highlights_model_source,
        "llm_l1_scout_provider": l1_scout_provider,
        "llm_l1_scout_model": l1_scout_model,
        "llm_l2_editor_provider": l2_editor_provider,
        "llm_l2_editor_model": l2_editor_model,
    }


@router.post("/api/ai-config/")
def set_ai_config(
    current_user: User = Depends(get_current_user),
    llm_minimax_enabled: bool = Body(None),
    llm_minimax_base_url: str = Body(None),
    llm_minimax_model: str = Body(None),
    llm_minimax_api_key: str = Body(None),
    llm_minimax_timeout_seconds: int = Body(None),
    llm_deepseek_enabled: bool = Body(None),
    llm_deepseek_base_url: str = Body(None),
    llm_deepseek_model: str = Body(None),
    llm_deepseek_api_key: str = Body(None),
    llm_deepseek_timeout_seconds: int = Body(None),
    llm_compat_enabled: bool = Body(None),
    llm_compat_provider: str = Body(None),
    llm_compat_base_url: str = Body(None),
    llm_compat_model: str = Body(None),
    llm_compat_api_key: str = Body(None),
    llm_compat_timeout_seconds: int = Body(None),
    llm_compat_extra_params: str = Body(None),
    llm_ollama_enabled: bool = Body(None),
    llm_ollama_base_url: str = Body(None),
    llm_ollama_model: str = Body(None),
    llm_ollama_api_key: str = Body(None),
    llm_ollama_timeout_seconds: int = Body(None),
    llm_ollama_mode: str = Body(None),
    llm_ollama_disable_thinking: bool = Body(None),
    llm_ollama_extra_params: str = Body(None),
    llm_highlights_model_source: str = Body(None),
    llm_l1_scout_provider: str = Body(None),
    llm_l1_scout_model: str = Body(None),
    llm_l2_editor_provider: str = Body(None),
    llm_l2_editor_model: str = Body(None),
    db: Session = Depends(get_db),
):
    """保存 AI 相关配置。"""
    minimax_updates = {
        "llm_minimax_enabled": str(bool(llm_minimax_enabled)).lower() if llm_minimax_enabled is not None else None,
        "llm_minimax_base_url": (llm_minimax_base_url or "").strip() if llm_minimax_base_url is not None else None,
        "llm_minimax_model": (llm_minimax_model or "").strip() if llm_minimax_model is not None else None,
        "llm_minimax_api_key": (llm_minimax_api_key or "").strip() if llm_minimax_api_key is not None else None,
        "llm_minimax_timeout_seconds": str(max(5, min(120, int(llm_minimax_timeout_seconds)))) if llm_minimax_timeout_seconds is not None else None,
    }
    minimax_updates = {k: v for k, v in minimax_updates.items() if v is not None}

    deepseek_updates = {
        "llm_deepseek_enabled": str(bool(llm_deepseek_enabled)).lower() if llm_deepseek_enabled is not None else None,
        "llm_deepseek_base_url": (llm_deepseek_base_url or "").strip() if llm_deepseek_base_url is not None else None,
        "llm_deepseek_model": (llm_deepseek_model or "").strip() if llm_deepseek_model is not None else None,
        "llm_deepseek_api_key": (llm_deepseek_api_key or "").strip() if llm_deepseek_api_key is not None else None,
        "llm_deepseek_timeout_seconds": str(max(5, min(120, int(llm_deepseek_timeout_seconds)))) if llm_deepseek_timeout_seconds is not None else None,
    }
    deepseek_updates = {k: v for k, v in deepseek_updates.items() if v is not None}

    normalized_compat_extra_params = None
    if llm_compat_extra_params is not None:
        raw_extra = str(llm_compat_extra_params or "").strip()
        if not raw_extra:
            normalized_compat_extra_params = "{}"
        else:
            try:
                extra_obj = json.loads(raw_extra)
            except Exception as e:
                raise HTTPException(status_code=400, detail=f"兼容平台额外参数 JSON 无效: {str(e)}")
            if not isinstance(extra_obj, dict):
                raise HTTPException(status_code=400, detail="兼容平台额外参数必须是 JSON 对象")
            normalized_compat_extra_params = json.dumps(extra_obj, ensure_ascii=False, separators=(",", ":"))

    compat_updates = {
        "llm_compat_enabled": str(bool(llm_compat_enabled)).lower() if llm_compat_enabled is not None else None,
        "llm_compat_provider": (llm_compat_provider or "").strip() if llm_compat_provider is not None else None,
        "llm_compat_base_url": (llm_compat_base_url or "").strip() if llm_compat_base_url is not None else None,
        "llm_compat_model": (llm_compat_model or "").strip() if llm_compat_model is not None else None,
        "llm_compat_api_key": (llm_compat_api_key or "").strip() if llm_compat_api_key is not None else None,
        "llm_compat_timeout_seconds": str(max(5, min(120, int(llm_compat_timeout_seconds)))) if llm_compat_timeout_seconds is not None else None,
        "llm_compat_extra_params": normalized_compat_extra_params,
    }
    compat_updates = {k: v for k, v in compat_updates.items() if v is not None}

    normalized_ollama_mode = None
    if llm_ollama_mode is not None:
        normalized_ollama_mode = str(llm_ollama_mode or "").strip().lower()
        if normalized_ollama_mode not in {"native", "openai_compat"}:
            raise HTTPException(status_code=400, detail="Ollama 模式仅支持 native/openai_compat")

    normalized_ollama_extra_params = None
    if llm_ollama_extra_params is not None:
        raw_extra = str(llm_ollama_extra_params or "").strip()
        if not raw_extra:
            normalized_ollama_extra_params = "{}"
        else:
            try:
                extra_obj = json.loads(raw_extra)
            except Exception as e:
                raise HTTPException(status_code=400, detail=f"Ollama 额外参数 JSON 无效: {str(e)}")
            if not isinstance(extra_obj, dict):
                raise HTTPException(status_code=400, detail="Ollama 额外参数必须是 JSON 对象")
            normalized_ollama_extra_params = json.dumps(extra_obj, ensure_ascii=False, separators=(",", ":"))

    ollama_updates = {
        "llm_ollama_enabled": str(bool(llm_ollama_enabled)).lower() if llm_ollama_enabled is not None else None,
        "llm_ollama_base_url": (llm_ollama_base_url or "").strip() if llm_ollama_base_url is not None else None,
        "llm_ollama_model": (llm_ollama_model or "").strip() if llm_ollama_model is not None else None,
        "llm_ollama_api_key": (llm_ollama_api_key or "").strip() if llm_ollama_api_key is not None else None,
        "llm_ollama_timeout_seconds": str(max(10, min(600, int(llm_ollama_timeout_seconds)))) if llm_ollama_timeout_seconds is not None else None,
        "llm_ollama_mode": normalized_ollama_mode,
        "llm_ollama_disable_thinking": str(bool(llm_ollama_disable_thinking)).lower() if llm_ollama_disable_thinking is not None else None,
        "llm_ollama_extra_params": normalized_ollama_extra_params,
    }
    ollama_updates = {k: v for k, v in ollama_updates.items() if v is not None}
    if ollama_updates:
        ollama_updates["llm_ollama_vision_capability"] = "unknown"
        ollama_updates["llm_ollama_vision_checked_at"] = ""
        ollama_updates["llm_ollama_vision_detail"] = ""

    source_update = None
    if llm_highlights_model_source is not None:
        source_value = str(llm_highlights_model_source).strip().lower()
        if source_value == "auto":
            source_value = "cloud"
        if source_value not in {"cloud", "deepseek", "compat", "local"}:
            raise HTTPException(status_code=400, detail="默认增强引擎仅支持 cloud/deepseek/compat/local")
        source_update = source_value

    l1_scout_provider_update = (llm_l1_scout_provider or "").strip() if llm_l1_scout_provider is not None else None
    l1_scout_model_update = (llm_l1_scout_model or "").strip() if llm_l1_scout_model is not None else None
    l2_editor_provider_update = (llm_l2_editor_provider or "").strip() if llm_l2_editor_provider is not None else None
    l2_editor_model_update = (llm_l2_editor_model or "").strip() if llm_l2_editor_model is not None else None

    try:
        for key, value in minimax_updates.items():
            _upsert_global_config(db, key, value)
        for key, value in deepseek_updates.items():
            _upsert_global_config(db, key, value)
        for key, value in compat_updates.items():
            _upsert_global_config(db, key, value)
        for key, value in ollama_updates.items():
            _upsert_global_config(db, key, value)
        if source_update is not None:
            _upsert_global_config(db, "llm_highlights_model_source", source_update)
        if l1_scout_provider_update is not None:
            _upsert_global_config(db, "llm_l1_scout_provider", l1_scout_provider_update)
        if l1_scout_model_update is not None:
            _upsert_global_config(db, "llm_l1_scout_model", l1_scout_model_update)
        if l2_editor_provider_update is not None:
            _upsert_global_config(db, "llm_l2_editor_provider", l2_editor_provider_update)
        if l2_editor_model_update is not None:
            _upsert_global_config(db, "llm_l2_editor_model", l2_editor_model_update)
        db.commit()
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"保存 AI 配置失败: {str(e)}")

    return {"message": "AI 配置已保存"}


@router.post("/api/ai-config/clear")
def clear_ai_config(
    clear_keys: list = Body(..., embed=True),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """清除指定 AI 配置项。"""
    if not clear_keys:
        raise HTTPException(status_code=400, detail="必须指定要清除的配置项")
    invalid_keys = [key for key in clear_keys if key not in AI_CONFIG_KEYS]
    if invalid_keys:
        raise HTTPException(status_code=400, detail=f"无效的配置项: {', '.join(invalid_keys)}")

    deleted_count = 0
    for clear_key in clear_keys:
        try:
            result = db.query(models.GlobalConfig).filter_by(key=clear_key).delete(synchronize_session=False)
            if result > 0:
                deleted_count += 1
        except Exception as e:
            logger.warning(f"删除 AI 配置 {clear_key} 失败: {e}")

    if deleted_count > 0:
        db.commit()
        return {"message": f"已清除 {deleted_count} 个 AI 配置项", "deleted_count": deleted_count}
    return {"message": "指定的 AI 配置项不存在或已被清除", "deleted_count": 0}


@router.get("/api/ai-config/asr-models")
def list_asr_models(current_user: User = Depends(get_current_user)):
    """列出可管理的 faster-whisper ASR 模型缓存状态。"""
    hf_home = _asr_hf_home()
    models = [_asr_model_info(name) for name in ASR_MODEL_SPECS]
    downloading = _get_asr_downloading_status()
    return {
        "hf_home": str(hf_home),
        "cache_dir": str(_asr_cache_dir()),
        "models": models,
        "total_size_bytes": sum(int(item.get("size_bytes") or 0) for item in models),
        "downloading": downloading,
    }


@router.post("/api/ai-config/asr-models/{model_name}/download")
def download_asr_model(model_name: str, current_user: User = Depends(get_current_user)):
    """下载指定 faster-whisper 模型到 /app/database/huggingface 缓存。"""
    normalized = _validate_asr_model_name(model_name)
    spec = ASR_MODEL_SPECS[normalized]
    hf_home = _asr_hf_home()
    hf_home.mkdir(parents=True, exist_ok=True)
    os.environ["HF_HOME"] = str(hf_home)

    username = current_user.username if current_user else "unknown"

    # 检查是否正在下载
    if _is_asr_model_downloading(normalized):
        logger.warning(f"[ASR] 模型下载冲突: {normalized} 正在下载中，拒绝重复请求（用户: {username}）")
        raise HTTPException(
            status_code=409,
            detail=f"ASR 模型 {normalized} 正在下载中，请等待完成后再试"
        )

    logger.info(f"[ASR] 开始下载模型: {normalized}（{spec['label']}），用户: {username}")

    # 广播下载开始
    def _broadcast_start():
        try:
            import asyncio
            from routers.websocket import broadcast_message
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                loop.run_until_complete(broadcast_message("asr_model", {
                    "type": "asr_download_start",
                    "model_name": normalized,
                    "started_by": username,
                    "timestamp": datetime.now().isoformat()
                }))
            finally:
                loop.close()
        except Exception:
            pass

    # 设置下载状态
    _set_asr_downloading(normalized, username)
    _broadcast_start()

    try:
        from huggingface_hub import snapshot_download
    except Exception as e:
        _clear_asr_downloading(normalized)
        logger.error(f"[ASR] huggingface_hub 导入失败: {normalized}，错误: {str(e)}")
        raise HTTPException(status_code=500, detail=f"huggingface_hub 未安装或不可用: {str(e)}")

    begin = time.time()
    try:
        logger.info(f"[ASR] 正在从 HuggingFace 下载: {spec['repo_id']}")
        local_path = snapshot_download(repo_id=spec["repo_id"], cache_dir=str(_asr_cache_dir()))
        elapsed = round(time.time() - begin, 2)
        logger.info(f"[ASR] ✅ 模型下载完成: {normalized}，耗时: {elapsed}秒")
    except Exception as e:
        elapsed = round(time.time() - begin, 2)
        error_msg = str(e)
        logger.error(f"[ASR] ❌ 模型下载失败: {normalized}，耗时: {elapsed}秒，错误: {error_msg[:200]}")

        # 简化错误信息给前端
        if "SSL" in error_msg or "ConnectError" in error_msg:
            user_msg = f"网络连接失败，请检查网络或设置 HF_TOKEN（当前为未认证，限速较低）"
        elif "LocalEntryNotFound" in error_msg:
            user_msg = f"模型文件未找到，可能网络不稳定，请重试"
        else:
            user_msg = f"下载失败: {error_msg[:100]}"

        _clear_asr_downloading(normalized)
        # 广播下载失败
        def _broadcast_error():
            try:
                import asyncio
                from routers.websocket import broadcast_message
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                try:
                    loop.run_until_complete(broadcast_message("asr_model", {
                        "type": "asr_download_error",
                        "model_name": normalized,
                        "error": user_msg,
                        "timestamp": datetime.now().isoformat()
                    }))
                finally:
                    loop.close()
            except Exception:
                pass
        _broadcast_error()
        raise HTTPException(status_code=500, detail=f"下载 ASR 模型失败: {user_msg}")

    info = _asr_model_info(normalized)
    _clear_asr_downloading(normalized)

    # 广播下载完成
    def _broadcast_complete():
        try:
            import asyncio
            from routers.websocket import broadcast_message
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                loop.run_until_complete(broadcast_message("asr_model", {
                    "type": "asr_download_complete",
                    "model_name": normalized,
                    "model": info,
                    "elapsed_seconds": round(time.time() - begin, 2),
                    "timestamp": datetime.now().isoformat()
                }))
            finally:
                loop.close()
        except Exception:
            pass
    _broadcast_complete()

    return {
        "message": f"ASR 模型 {normalized} 下载完成",
        "model": info,
        "snapshot_path": local_path,
        "elapsed_seconds": round(time.time() - begin, 2),
    }


@router.delete("/api/ai-config/asr-models/{model_name}")
def delete_asr_model(model_name: str, current_user: User = Depends(get_current_user)):
    """删除指定 faster-whisper 模型缓存。"""
    normalized = _validate_asr_model_name(model_name)
    path = _asr_model_cache_path(normalized).resolve()
    cache_dir = _asr_cache_dir().resolve()

    if cache_dir not in path.parents:
        raise HTTPException(status_code=400, detail="ASR 模型缓存路径异常，已拒绝删除")
    if not path.exists():
        return {
            "message": f"ASR 模型 {normalized} 未安装或已删除",
            "deleted": False,
            "model": _asr_model_info(normalized),
        }

    size_bytes = _dir_size_bytes(path)
    try:
        shutil.rmtree(path)
    except Exception as e:
        logger.exception("删除 ASR 模型失败: %s", path)
        raise HTTPException(status_code=500, detail=f"删除 ASR 模型失败: {str(e)}")

    return {
        "message": f"ASR 模型 {normalized} 已删除",
        "deleted": True,
        "freed_size_bytes": size_bytes,
        "model": _asr_model_info(normalized),
    }

# 64x64 PNG（纯色）用于快速探测模型图像输入能力。
# 说明：部分模型在 1x1 极小图上会出现 runner 异常（并非真实不支持视觉），
# 因此使用更稳健的中等尺寸测试图。
_VISION_TEST_PNG_BASE64 = (
    "iVBORw0KGgoAAAANSUhEUgAAAEAAAABACAIAAAAlC+aJAAAAS0lEQVR42u3PQQkAAAgAsetfWiP4FgYrsKZeS0BAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEDgsqnc8OJg6Ln3AAAAAElFTkSuQmCC"
)

@router.post("/api/global-config/test-minimax")
def test_minimax_config(
    current_user: User = Depends(get_current_user),
    llm_minimax_base_url: str = Body(None),
    llm_minimax_model: str = Body(None),
    llm_minimax_api_key: str = Body(None),
    llm_minimax_timeout_seconds: int = Body(None),
    db: Session = Depends(get_db),
):
    """测试 MiniMax 配置可用性（不落库）。"""
    try:
        base_url = (llm_minimax_base_url or "").strip()
        model = (llm_minimax_model or "").strip()
        api_key = (llm_minimax_api_key or "").strip()
        timeout_seconds = llm_minimax_timeout_seconds

        # 允许前端只传部分字段，未传字段回退到已保存配置
        keys = [
            "llm_minimax_base_url",
            "llm_minimax_model",
            "llm_minimax_api_key",
            "llm_minimax_timeout_seconds",
        ]
        rows = db.query(models.GlobalConfig).filter(models.GlobalConfig.key.in_(keys)).all()
        kv = {row.key: (row.value or "") for row in rows}

        if not base_url:
            base_url = (kv.get("llm_minimax_base_url") or "https://api.minimaxi.com/v1").strip()
        if not model:
            model = (kv.get("llm_minimax_model") or "MiniMax-Text-01").strip()
        if not api_key:
            api_key = (kv.get("llm_minimax_api_key") or "").strip()
        if timeout_seconds is None:
            try:
                timeout_seconds = int(kv.get("llm_minimax_timeout_seconds") or 90)
            except Exception:
                timeout_seconds = 90
        timeout_seconds = max(10, min(600, int(timeout_seconds)))

        if not api_key:
            raise HTTPException(status_code=400, detail="请先填写 MiniMax API Key")

        endpoint = base_url.rstrip("/") + "/chat/completions"
        payload = {
            "model": model,
            "temperature": 0,
            "max_tokens": 20,
            "messages": [
                {"role": "system", "content": "你是一个API连通性测试助手。"},
                {"role": "user", "content": "请回复OK"},
            ],
        }
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

        begin = time.time()
        with httpx.Client(timeout=timeout_seconds) as client:
            resp = client.post(endpoint, headers=headers, json=payload)
        cost_ms = int((time.time() - begin) * 1000)

        if resp.status_code >= 400:
            detail = ""
            try:
                detail = str((resp.json() or {}).get("error") or (resp.json() or {}).get("message") or "")
            except Exception:
                detail = (resp.text or "")[:300]
            return JSONResponse(
                status_code=400,
                content={
                    "success": False,
                    "provider": "minimax",
                    "message": f"连通失败: HTTP {resp.status_code}",
                    "detail": detail,
                    "latency_ms": cost_ms,
                },
            )

        data = {}
        try:
            data = resp.json() or {}
        except Exception:
            data = {}

        content_preview = ""
        try:
            content_preview = str(data.get("choices", [{}])[0].get("message", {}).get("content", "")).strip()
        except Exception:
            content_preview = ""

        return {
            "success": True,
            "provider": "minimax",
            "message": "MiniMax 配置可用",
            "model": model,
            "latency_ms": cost_ms,
            "preview": (content_preview[:80] if content_preview else ""),
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("测试 MiniMax 配置失败")
        raise HTTPException(status_code=500, detail=f"测试 MiniMax 配置失败: {str(e)}")


@router.post("/api/global-config/test-openai-compatible")
def test_openai_compatible_config(
    current_user: User = Depends(get_current_user),
    llm_compat_provider: str = Body(None),
    llm_compat_base_url: str = Body(None),
    llm_compat_model: str = Body(None),
    llm_compat_api_key: str = Body(None),
    llm_compat_timeout_seconds: int = Body(None),
    llm_compat_extra_params: str = Body(None),
    db: Session = Depends(get_db),
):
    """测试 OpenAI 兼容平台配置可用性（不落库）。"""
    try:
        provider = (llm_compat_provider or "").strip() or "OpenAI"
        preset = get_preset_dict(provider)
        default_base_url = preset.get("base_url") or "https://api.openai.com/v1"
        default_model = preset.get("default_model") or "gpt-4o-mini"

        base_url = (llm_compat_base_url or "").strip()
        model = (llm_compat_model or "").strip()
        api_key = (llm_compat_api_key or "").strip()
        timeout_seconds = llm_compat_timeout_seconds
        extra_params_raw = llm_compat_extra_params

        keys = [
            "llm_compat_provider",
            "llm_compat_base_url",
            "llm_compat_model",
            "llm_compat_api_key",
            "llm_compat_timeout_seconds",
            "llm_compat_extra_params",
        ]
        rows = db.query(models.GlobalConfig).filter(models.GlobalConfig.key.in_(keys)).all()
        kv = {row.key: (row.value or "") for row in rows}

        if not base_url:
            base_url = (kv.get("llm_compat_base_url") or default_base_url).strip()
        if not model:
            model = (kv.get("llm_compat_model") or default_model).strip()
        if not api_key:
            api_key = (kv.get("llm_compat_api_key") or "").strip()
        if timeout_seconds is None:
            try:
                timeout_seconds = int(kv.get("llm_compat_timeout_seconds") or 90)
            except Exception:
                timeout_seconds = 90
        timeout_seconds = max(5, min(120, int(timeout_seconds)))
        if extra_params_raw is None:
            extra_params_raw = str(kv.get("llm_compat_extra_params") or "{}")
        extra_params_raw = str(extra_params_raw or "").strip()
        if not extra_params_raw:
            extra_params_raw = "{}"
        try:
            extra_params = json.loads(extra_params_raw)
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"兼容平台额外参数 JSON 无效: {str(e)}")
        if not isinstance(extra_params, dict):
            raise HTTPException(status_code=400, detail="兼容平台额外参数必须是 JSON 对象")

        if not api_key:
            raise HTTPException(status_code=400, detail="请先填写 API Key")

        endpoint = base_url.rstrip("/") + "/chat/completions"
        payload = {
            "model": model,
            "temperature": 0,
            "max_tokens": 20,
            "messages": [
                {"role": "system", "content": "你是一个API连通性测试助手。"},
                {"role": "user", "content": "请回复OK"},
            ],
        }
        for key, value in extra_params.items():
            if key in {"model", "messages"}:
                continue
            payload[key] = value
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

        begin = time.time()
        with httpx.Client(timeout=timeout_seconds) as client:
            resp = client.post(endpoint, headers=headers, json=payload)
        cost_ms = int((time.time() - begin) * 1000)

        if resp.status_code >= 400:
            detail = ""
            try:
                detail = str((resp.json() or {}).get("error") or (resp.json() or {}).get("message") or "")
            except Exception:
                detail = (resp.text or "")[:300]
            return JSONResponse(
                status_code=400,
                content={
                    "success": False,
                    "provider": "openai_compatible",
                    "message": f"连通失败: HTTP {resp.status_code}",
                    "detail": detail,
                    "latency_ms": cost_ms,
                },
            )

        data = {}
        try:
            data = resp.json() or {}
        except Exception:
            data = {}

        content_preview = ""
        try:
            content_preview = str(data.get("choices", [{}])[0].get("message", {}).get("content", "")).strip()
        except Exception:
            content_preview = ""

        return {
            "success": True,
            "provider": "openai_compatible",
            "message": f"{provider} 配置可用",
            "model": model,
            "latency_ms": cost_ms,
            "preview": (content_preview[:80] if content_preview else ""),
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("测试兼容平台配置失败")
        raise HTTPException(status_code=500, detail=f"测试兼容平台配置失败: {str(e)}")


@router.post("/api/global-config/test-ollama")
def test_ollama_config(
    current_user: User = Depends(get_current_user),
    llm_ollama_base_url: str = Body(None),
    llm_ollama_model: str = Body(None),
    llm_ollama_api_key: str = Body(None),
    llm_ollama_timeout_seconds: int = Body(None),
    llm_ollama_mode: str = Body(None),
    llm_ollama_disable_thinking: bool = Body(None),
    llm_ollama_extra_params: str = Body(None),
    db: Session = Depends(get_db),
):
    """测试 Ollama 配置可用性（不落库，支持 native/openai_compat）。"""
    try:
        base_url = (llm_ollama_base_url or "").strip()
        model = (llm_ollama_model or "").strip()
        api_key = (llm_ollama_api_key or "").strip()
        timeout_seconds = llm_ollama_timeout_seconds
        mode = (llm_ollama_mode or "").strip().lower()
        disable_thinking = llm_ollama_disable_thinking
        extra_params_raw = llm_ollama_extra_params

        keys = [
            "llm_ollama_base_url",
            "llm_ollama_model",
            "llm_ollama_api_key",
            "llm_ollama_timeout_seconds",
            "llm_ollama_mode",
            "llm_ollama_disable_thinking",
            "llm_ollama_extra_params",
        ]
        rows = db.query(models.GlobalConfig).filter(models.GlobalConfig.key.in_(keys)).all()
        kv = {row.key: (row.value or "") for row in rows}

        if not base_url:
            base_url = (kv.get("llm_ollama_base_url") or "http://127.0.0.1:11434").strip()
        if not model:
            model = (kv.get("llm_ollama_model") or "qwen2.5:7b").strip()
        if not api_key:
            api_key = (kv.get("llm_ollama_api_key") or "").strip()
        if timeout_seconds is None:
            try:
                timeout_seconds = int(kv.get("llm_ollama_timeout_seconds") or 180)
            except Exception:
                timeout_seconds = 180
        timeout_seconds = max(10, min(600, int(timeout_seconds)))
        if not mode:
            mode = str(kv.get("llm_ollama_mode") or "native").strip().lower()
        if mode not in {"native", "openai_compat"}:
            raise HTTPException(status_code=400, detail="Ollama 模式仅支持 native/openai_compat")
        if disable_thinking is None:
            disable_thinking = str(kv.get("llm_ollama_disable_thinking") or "true").strip().lower() == "true"
        if extra_params_raw is None:
            extra_params_raw = str(kv.get("llm_ollama_extra_params") or "{}")
        extra_params_raw = str(extra_params_raw or "").strip()
        if not extra_params_raw:
            extra_params_raw = "{}"
        try:
            extra_params = json.loads(extra_params_raw)
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Ollama 额外参数 JSON 无效: {str(e)}")
        if not isinstance(extra_params, dict):
            raise HTTPException(status_code=400, detail="Ollama 额外参数必须是 JSON 对象")

        if mode == "native":
            normalized_base = base_url.rstrip("/")
            if normalized_base.lower().endswith("/v1"):
                normalized_base = normalized_base[:-3].rstrip("/")
            endpoint = normalized_base + "/api/chat"
            payload = {
                "model": model,
                "stream": False,
                "messages": [
                    {"role": "system", "content": "你是一个API连通性测试助手。"},
                    {"role": "user", "content": "请回复OK"},
                ],
                "options": {
                    "temperature": 0,
                    "num_predict": 20,
                },
            }
            if disable_thinking:
                payload["think"] = False
            options = payload["options"]
            extra_options = extra_params.get("options")
            if isinstance(extra_options, dict):
                options.update(extra_options)
            for k, v in extra_params.items():
                if k == "options":
                    continue
                if k in {"model", "messages", "stream"}:
                    continue
                if k in {"think", "format", "keep_alive", "template", "raw", "tools"}:
                    payload[k] = v
                else:
                    options[k] = v
        else:
            endpoint = base_url.rstrip("/") + "/chat/completions"
            payload = {
                "model": model,
                "temperature": 0,
                "max_tokens": 20,
                "messages": [
                    {"role": "system", "content": "你是一个API连通性测试助手。"},
                    {"role": "user", "content": "请回复OK"},
                ],
            }
            payload.update(extra_params)
        headers = {"Content-Type": "application/json"}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"

        begin = time.time()
        with httpx.Client(timeout=timeout_seconds) as client:
            resp = client.post(endpoint, headers=headers, json=payload)
        cost_ms = int((time.time() - begin) * 1000)

        if resp.status_code >= 400:
            detail = ""
            try:
                detail = str((resp.json() or {}).get("error") or (resp.json() or {}).get("message") or "")
            except Exception:
                detail = (resp.text or "")[:300]
            return JSONResponse(
                status_code=400,
                content={
                    "success": False,
                    "provider": "ollama",
                    "message": f"连通失败: HTTP {resp.status_code}",
                    "detail": detail,
                    "latency_ms": cost_ms,
                },
            )

        data = {}
        try:
            data = resp.json() or {}
        except Exception:
            data = {}

        content_preview = ""
        try:
            if mode == "native":
                msg = data.get("message", {}) if isinstance(data, dict) else {}
                content_preview = str(msg.get("content", "") or msg.get("thinking", "")).strip()
            else:
                content_preview = str(data.get("choices", [{}])[0].get("message", {}).get("content", "")).strip()
        except Exception:
            content_preview = ""

        return {
            "success": True,
            "provider": "ollama",
            "mode": mode,
            "message": "Ollama 配置可用",
            "model": model,
            "latency_ms": cost_ms,
            "preview": (content_preview[:80] if content_preview else ""),
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("测试 Ollama 配置失败")
        raise HTTPException(status_code=500, detail=f"测试 Ollama 配置失败: {str(e)}")


@router.post("/api/global-config/test-ollama-vision")
def test_ollama_vision_config(
    current_user: User = Depends(get_current_user),
    llm_ollama_base_url: str = Body(None),
    llm_ollama_model: str = Body(None),
    llm_ollama_api_key: str = Body(None),
    llm_ollama_timeout_seconds: int = Body(None),
    llm_ollama_mode: str = Body(None),
    llm_ollama_disable_thinking: bool = Body(None),
    llm_ollama_extra_params: str = Body(None),
    db: Session = Depends(get_db),
):
    """检测 Ollama 当前模型是否支持图像输入能力（支持 native/openai_compat）。"""
    try:
        base_url = (llm_ollama_base_url or "").strip()
        model = (llm_ollama_model or "").strip()
        api_key = (llm_ollama_api_key or "").strip()
        timeout_seconds = llm_ollama_timeout_seconds
        mode = (llm_ollama_mode or "").strip().lower()
        disable_thinking = llm_ollama_disable_thinking
        extra_params_raw = llm_ollama_extra_params

        keys = [
            "llm_ollama_base_url",
            "llm_ollama_model",
            "llm_ollama_api_key",
            "llm_ollama_timeout_seconds",
            "llm_ollama_mode",
            "llm_ollama_disable_thinking",
            "llm_ollama_extra_params",
        ]
        rows = db.query(models.GlobalConfig).filter(models.GlobalConfig.key.in_(keys)).all()
        kv = {row.key: (row.value or "") for row in rows}

        if not base_url:
            base_url = (kv.get("llm_ollama_base_url") or "http://127.0.0.1:11434").strip()
        if not model:
            model = (kv.get("llm_ollama_model") or "qwen2.5:7b").strip()
        if not api_key:
            api_key = (kv.get("llm_ollama_api_key") or "").strip()
        if timeout_seconds is None:
            try:
                timeout_seconds = int(kv.get("llm_ollama_timeout_seconds") or 180)
            except Exception:
                timeout_seconds = 180
        timeout_seconds = max(10, min(600, int(timeout_seconds)))
        if not mode:
            mode = str(kv.get("llm_ollama_mode") or "native").strip().lower()
        if mode not in {"native", "openai_compat"}:
            raise HTTPException(status_code=400, detail="Ollama 模式仅支持 native/openai_compat")
        if disable_thinking is None:
            disable_thinking = str(kv.get("llm_ollama_disable_thinking") or "true").strip().lower() == "true"
        if extra_params_raw is None:
            extra_params_raw = str(kv.get("llm_ollama_extra_params") or "{}")
        extra_params_raw = str(extra_params_raw or "").strip()
        if not extra_params_raw:
            extra_params_raw = "{}"
        try:
            extra_params = json.loads(extra_params_raw)
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Ollama 额外参数 JSON 无效: {str(e)}")
        if not isinstance(extra_params, dict):
            raise HTTPException(status_code=400, detail="Ollama 额外参数必须是 JSON 对象")

        if mode == "native":
            normalized_base = base_url.rstrip("/")
            if normalized_base.lower().endswith("/v1"):
                normalized_base = normalized_base[:-3].rstrip("/")
            endpoint = normalized_base + "/api/chat"
            payload = {
                "model": model,
                "stream": False,
                "messages": [
                    {
                        "role": "user",
                        "content": "请简短描述这张图片（10个字以内）。",
                        "images": [_VISION_TEST_PNG_BASE64],
                    }
                ],
                "options": {
                    "temperature": 0,
                    "num_predict": 20,
                },
            }
            if disable_thinking:
                payload["think"] = False
            options = payload["options"]
            extra_options = extra_params.get("options")
            if isinstance(extra_options, dict):
                options.update(extra_options)
            for k, v in extra_params.items():
                if k == "options":
                    continue
                if k in {"model", "messages", "stream"}:
                    continue
                if k in {"think", "format", "keep_alive", "template", "raw", "tools"}:
                    payload[k] = v
                else:
                    options[k] = v
        else:
            endpoint = base_url.rstrip("/") + "/chat/completions"
            payload = {
                "model": model,
                "temperature": 0,
                "max_tokens": 60,
                "messages": [
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": "请简短描述这张图片（10个字以内）。"},
                            {"type": "image_url", "image_url": {"url": "data:image/png;base64," + _VISION_TEST_PNG_BASE64}},
                        ],
                    }
                ],
            }
            payload.update(extra_params)

        headers = {"Content-Type": "application/json"}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"

        begin = time.time()
        with httpx.Client(timeout=timeout_seconds) as client:
            resp = client.post(endpoint, headers=headers, json=payload)
        cost_ms = int((time.time() - begin) * 1000)

        vision_supported = False
        detail = ""
        preview = ""

        if resp.status_code < 400:
            data = {}
            try:
                data = resp.json() or {}
            except Exception:
                data = {}
            try:
                if mode == "native":
                    msg = data.get("message", {}) if isinstance(data, dict) else {}
                    preview = str(msg.get("content", "") or "").strip()
                else:
                    preview = str(data.get("choices", [{}])[0].get("message", {}).get("content", "")).strip()
            except Exception:
                preview = ""
            vision_supported = bool(preview)
            if not vision_supported:
                detail = "模型返回成功但未产出可解析文本，可能不支持图像输入。"
        else:
            try:
                resp_json = resp.json() or {}
                detail = str(resp_json.get("error") or resp_json.get("message") or "")
            except Exception:
                detail = (resp.text or "")[:300]
            detail = f"HTTP {resp.status_code}: {detail}".strip()

        capability = "supported" if vision_supported else "unsupported"
        if not vision_supported and resp.status_code >= 400:
            detail_lower = (detail or "").lower()
            ambiguous_markers = [
                "invalid checksum",
                "invalid format",
                "failed to process inputs",
                "decode",
                "connection",
                "timeout",
                "internal server error",
            ]
            if resp.status_code >= 500 or any(marker in detail_lower for marker in ambiguous_markers):
                capability = "unknown"

        checked_at = datetime.now(timezone.utc).isoformat()
        detail_to_store = (detail or preview or "").strip()[:500]
        for k, v in {
            "llm_ollama_vision_capability": capability,
            "llm_ollama_vision_checked_at": checked_at,
            "llm_ollama_vision_detail": detail_to_store,
        }.items():
            obj = db.query(models.GlobalConfig).filter_by(key=k).first()
            if obj:
                obj.value = v
            else:
                db.add(models.GlobalConfig(key=k, value=v))
        db.commit()

        return {
            "success": True,
            "provider": "ollama",
            "mode": mode,
            "model": model,
            "vision_supported": vision_supported,
            "capability": capability,
            "message": (
                "检测到支持图像分析"
                if capability == "supported"
                else ("检测到不支持图像分析" if capability == "unsupported" else "暂时无法确定图像能力")
            ),
            "detail": detail,
            "preview": (preview[:120] if preview else ""),
            "latency_ms": cost_ms,
            "checked_at": checked_at,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("检测 Ollama 图像能力失败")
        raise HTTPException(status_code=500, detail=f"检测 Ollama 图像能力失败: {str(e)}")


@router.post("/api/global-config/ollama-capabilities")
def get_ollama_capabilities(
    current_user: User = Depends(get_current_user),
    llm_ollama_base_url: str = Body(None),
    llm_ollama_model: str = Body(None),
    llm_ollama_api_key: str = Body(None),
    llm_ollama_timeout_seconds: int = Body(None),
    llm_ollama_mode: str = Body(None),
    db: Session = Depends(get_db),
):
    """读取 Ollama 模型元数据能力（/api/show），用于页面实时能力展示。"""
    try:
        base_url = (llm_ollama_base_url or "").strip()
        model = (llm_ollama_model or "").strip()
        api_key = (llm_ollama_api_key or "").strip()
        timeout_seconds = llm_ollama_timeout_seconds
        mode = (llm_ollama_mode or "").strip().lower()

        keys = [
            "llm_ollama_base_url",
            "llm_ollama_model",
            "llm_ollama_api_key",
            "llm_ollama_timeout_seconds",
            "llm_ollama_mode",
        ]
        rows = db.query(models.GlobalConfig).filter(models.GlobalConfig.key.in_(keys)).all()
        kv = {row.key: (row.value or "") for row in rows}

        if not base_url:
            base_url = (kv.get("llm_ollama_base_url") or "http://127.0.0.1:11434").strip()
        if not model:
            model = (kv.get("llm_ollama_model") or "qwen2.5:7b").strip()
        if not api_key:
            api_key = (kv.get("llm_ollama_api_key") or "").strip()
        if timeout_seconds is None:
            try:
                timeout_seconds = int(kv.get("llm_ollama_timeout_seconds") or 30)
            except Exception:
                timeout_seconds = 30
        timeout_seconds = max(5, min(120, int(timeout_seconds)))
        if not mode:
            mode = str(kv.get("llm_ollama_mode") or "native").strip().lower()
        if mode not in {"native", "openai_compat"}:
            raise HTTPException(status_code=400, detail="Ollama 模式仅支持 native/openai_compat")
        if not base_url:
            raise HTTPException(status_code=400, detail="请先配置 Ollama Base URL")
        if not model:
            raise HTTPException(status_code=400, detail="请先配置 Ollama 模型名")

        normalized_base = base_url.rstrip("/")
        if normalized_base.lower().endswith("/v1"):
            normalized_base = normalized_base[:-3].rstrip("/")
        endpoint = normalized_base + "/api/show"

        headers = {"Content-Type": "application/json"}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"

        payload = {"model": model}
        begin = time.time()
        with httpx.Client(timeout=timeout_seconds) as client:
            resp = client.post(endpoint, headers=headers, json=payload)
        latency_ms = int((time.time() - begin) * 1000)

        if resp.status_code >= 400:
            detail = ""
            try:
                err_data = resp.json() or {}
                detail = str(err_data.get("error") or err_data.get("message") or "")
            except Exception:
                detail = (resp.text or "")[:300]
            detail = f"HTTP {resp.status_code}: {detail}".strip()
            return {
                "success": True,
                "provider": "ollama",
                "mode": mode,
                "model": model,
                "capability": "unknown",
                "vision_supported": None,
                "capabilities": [],
                "detail": detail,
                "supports_completion": None,
                "supports_vision": None,
                "supports_audio": None,
                "supports_tools": None,
                "supports_thinking": None,
                "meta": {
                    "family": "",
                    "parameter_size": "",
                    "quantization_level": "",
                    "format": "",
                    "architecture": "",
                    "context_length": None,
                    "requires": "",
                    "modified_at": "",
                },
                "checked_at": datetime.now(timezone.utc).isoformat(),
                "latency_ms": latency_ms,
            }

        try:
            data = resp.json() or {}
        except Exception:
            data = {}

        raw_caps = data.get("capabilities", [])
        capabilities = []
        if isinstance(raw_caps, list):
            for item in raw_caps:
                txt = str(item or "").strip().lower()
                if txt:
                    capabilities.append(txt)
        capabilities = sorted(list(set(capabilities)))

        details_obj = data.get("details", {}) if isinstance(data, dict) else {}
        if not isinstance(details_obj, dict):
            details_obj = {}
        model_info = data.get("model_info", {}) if isinstance(data, dict) else {}
        if not isinstance(model_info, dict):
            model_info = {}

        def _to_text(value: Any) -> str:
            if value is None:
                return ""
            return str(value).strip()

        def _to_int(value: Any) -> Optional[int]:
            try:
                if value is None or value == "":
                    return None
                return int(value)
            except Exception:
                return None

        context_length = None
        for key, val in model_info.items():
            key_str = str(key or "").lower()
            if key_str.endswith(".context_length") or "context_length" in key_str:
                context_length = _to_int(val)
                if context_length:
                    break

        supports_completion = "completion" in capabilities
        supports_vision = "vision" in capabilities
        supports_audio = "audio" in capabilities
        supports_tools = "tools" in capabilities
        supports_thinking = "thinking" in capabilities

        meta_summary = []
        if supports_vision:
            meta_summary.append("图像")
        if supports_audio:
            meta_summary.append("音频")
        if supports_tools:
            meta_summary.append("工具调用")
        if supports_thinking:
            meta_summary.append("思考模式")

        vision_supported = "vision" in capabilities if capabilities else None
        capability = "supported" if vision_supported else ("unsupported" if capabilities else "unknown")
        detail = (
            f"能力：{', '.join(meta_summary)}"
            if meta_summary
            else ("capabilities: " + ", ".join(capabilities) if capabilities else "模型未返回 capabilities 字段。")
        )

        return {
            "success": True,
            "provider": "ollama",
            "mode": mode,
            "model": model,
            "capability": capability,
            "vision_supported": vision_supported,
            "capabilities": capabilities,
            "detail": detail,
            "supports_completion": supports_completion,
            "supports_vision": supports_vision,
            "supports_audio": supports_audio,
            "supports_tools": supports_tools,
            "supports_thinking": supports_thinking,
            "meta": {
                "family": _to_text(details_obj.get("family")),
                "parameter_size": _to_text(details_obj.get("parameter_size")),
                "quantization_level": _to_text(details_obj.get("quantization_level")),
                "format": _to_text(details_obj.get("format")),
                "architecture": _to_text(model_info.get("general.architecture")),
                "context_length": context_length,
                "requires": _to_text(data.get("requires")),
                "modified_at": _to_text(data.get("modified_at")),
            },
            "checked_at": datetime.now(timezone.utc).isoformat(),
            "latency_ms": latency_ms,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("获取 Ollama 能力信息失败")
        raise HTTPException(status_code=500, detail=f"获取 Ollama 能力信息失败: {str(e)}")


@router.post("/api/global-config/test-deepseek")
def test_deepseek_config(
    current_user: User = Depends(get_current_user),
    llm_deepseek_base_url: str = Body(None),
    llm_deepseek_model: str = Body(None),
    llm_deepseek_api_key: str = Body(None),
    llm_deepseek_timeout_seconds: int = Body(None),
    db: Session = Depends(get_db),
):
    """测试 DeepSeek(OpenAI兼容) 配置可用性（不落库）。"""
    try:
        base_url = (llm_deepseek_base_url or "").strip()
        model = (llm_deepseek_model or "").strip()
        api_key = (llm_deepseek_api_key or "").strip()
        timeout_seconds = llm_deepseek_timeout_seconds

        keys = [
            "llm_deepseek_base_url",
            "llm_deepseek_model",
            "llm_deepseek_api_key",
            "llm_deepseek_timeout_seconds",
        ]
        rows = db.query(models.GlobalConfig).filter(models.GlobalConfig.key.in_(keys)).all()
        kv = {row.key: (row.value or "") for row in rows}

        if not base_url:
            base_url = (kv.get("llm_deepseek_base_url") or "https://api.deepseek.com").strip()
        if not model:
            model = (kv.get("llm_deepseek_model") or "deepseek-chat").strip()
        if not api_key:
            api_key = (kv.get("llm_deepseek_api_key") or "").strip()
        if timeout_seconds is None:
            try:
                timeout_seconds = int(kv.get("llm_deepseek_timeout_seconds") or 90)
            except Exception:
                timeout_seconds = 90
        timeout_seconds = max(5, min(120, int(timeout_seconds)))

        if not api_key:
            raise HTTPException(status_code=400, detail="请先填写 DeepSeek API Key")

        endpoint = base_url.rstrip("/") + "/chat/completions"
        payload = {
            "model": model,
            "temperature": 0,
            "max_tokens": 20,
            "messages": [
                {"role": "system", "content": "你是一个API连通性测试助手。"},
                {"role": "user", "content": "请回复OK"},
            ],
        }
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

        begin = time.time()
        with httpx.Client(timeout=timeout_seconds) as client:
            resp = client.post(endpoint, headers=headers, json=payload)
        cost_ms = int((time.time() - begin) * 1000)

        if resp.status_code >= 400:
            detail = ""
            try:
                detail = str((resp.json() or {}).get("error") or (resp.json() or {}).get("message") or "")
            except Exception:
                detail = (resp.text or "")[:300]
            return JSONResponse(
                status_code=400,
                content={
                    "success": False,
                    "provider": "deepseek",
                    "message": f"连通失败: HTTP {resp.status_code}",
                    "detail": detail,
                    "latency_ms": cost_ms,
                },
            )

        data = {}
        try:
            data = resp.json() or {}
        except Exception:
            data = {}

        content_preview = ""
        try:
            content_preview = str(data.get("choices", [{}])[0].get("message", {}).get("content", "")).strip()
        except Exception:
            content_preview = ""

        return {
            "success": True,
            "provider": "deepseek",
            "message": "DeepSeek 配置可用",
            "model": model,
            "latency_ms": cost_ms,
            "preview": (content_preview[:80] if content_preview else ""),
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("测试 DeepSeek 配置失败")
        raise HTTPException(status_code=500, detail=f"测试 DeepSeek 配置失败: {str(e)}")
