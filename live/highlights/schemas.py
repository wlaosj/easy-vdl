# -*- coding: utf-8 -*-
"""AI 高光切片 V1 数据模型。"""

from typing import Any, Dict, List, Optional, Literal
from pydantic import BaseModel, Field, field_validator


HighlightType = Literal[
    "high_energy",
    "funny",
    "controversy",
    "teaching",
    "emotion",
]


class AIModelConfig(BaseModel):
    provider: Literal["auto", "cloud", "ollama", "none", "deepseek", "compat"] = Field("none", description="模型提供商")
    model: str = Field("", description="具体模型名称")
    api_key: Optional[str] = Field(None, description="API Key (如果需要)")
    base_url: Optional[str] = Field(None, description="API Base URL (可选)")
    temperature: float = Field(0.0, ge=0.0, le=2.0, description="采样温度")
    max_concurrency: Optional[int] = Field(None, ge=1, le=8, description="并发上限（高级）")

    @field_validator("provider", mode="before")
    @classmethod
    def _normalize_provider_alias(cls, value):
        text = str(value or "").strip().lower()
        alias_map = {
            "minimax": "cloud",
            "local": "ollama",
        }
        return alias_map.get(text, text or "none")


class AnalyzeRequest(BaseModel):
    model_config = {"protected_namespaces": ()}

    highlight_type: HighlightType = Field("high_energy", description="高光类型")
    mode: Literal["offline"] = Field("offline", description="分析模式")
    model_source: Literal["auto", "cloud", "deepseek", "compat", "local"] = Field("cloud", description="模型来源")
    analysis_strategy: Literal["hybrid", "rule_only", "llm_required"] = Field(
        "hybrid",
        description="分析策略",
    )

    # --- 新架构：L1 Scout & L2 Editor ---
    l1_scout_config: AIModelConfig = Field(
        default_factory=lambda: AIModelConfig(provider="none"),
        description="L1 语义侦察兵配置：负责初筛、打分、剔除噪音"
    )
    l2_editor_config: AIModelConfig = Field(
        default_factory=lambda: AIModelConfig(provider="none"),
        description="L2 内容剪辑师配置：负责标题、摘要、故事线生成"
    )
    # ----------------------------------

    stream_type: Optional[str] = Field(None, max_length=64, description="直播类型上下文")
    story_enabled: bool = Field(True, description="是否启用剧情文案增强")
    asr_enabled: bool = Field(True, description="是否启用候选片段主播语音转写")
    asr_model: str = Field("small", max_length=64, description="ASR 模型名称")
    asr_device: Literal["cpu", "cuda"] = Field("cpu", description="ASR 推理设备")
    asr_compute_type: str = Field("int8", max_length=32, description="ASR 计算精度")
    window_seconds: int = Field(10, ge=5, le=60, description="聚合窗口（秒）")
    max_candidates: int = Field(5, ge=1, le=100, description="最大候选数量")
    seed: int = Field(-1, description="随机种子")
    randomness: int = Field(50, ge=0, le=100, description="随机性强度")
    danmu_delay_compensation_seconds: int = Field(5, ge=0, le=30, description="弹幕天然延迟补偿（秒）")
    pre_padding_seconds: int = Field(20, ge=0, le=120, description="切片前扩展秒数")
    post_padding_seconds: int = Field(15, ge=0, le=120, description="切片后扩展秒数")

    @field_validator("model_source", mode="before")
    @classmethod
    def _normalize_model_source_alias(cls, value):
        text = str(value or "").strip().lower()
        alias_map = {
            "minimax": "cloud",
            "ollama": "local",
        }
        return alias_map.get(text, text or "cloud")


class CustomRangeEntry(BaseModel):
    segment_id: str
    start_sec: float
    end_sec: float


class ExportRequest(BaseModel):
    segment_ids: Optional[List[str]] = Field(None, description="指定导出的高光片段 ID 列表")
    overwrite: bool = Field(False, description="已存在时是否覆盖")
    include_story_assets: bool = Field(False, description="导出剧情素材（storyline/srt）")
    only_story_assets: bool = Field(False, description="仅导出剧情素材，不导出切片")
    custom_ranges: Optional[List[CustomRangeEntry]] = Field(None, description="自定义切片时间范围覆盖")


class BundleRequest(BaseModel):
    segment_ids: Optional[List[str]] = Field(None, description="指定导出资源包的高光片段 ID 列表")
    overwrite: bool = Field(False, description="已存在切片时是否覆盖重导")
    include_story_assets: bool = Field(True, description="是否附带剧情素材（storyline/srt）")


class HighlightSegment(BaseModel):
    id: str
    start_sec: float
    end_sec: float
    duration_sec: float
    score: float
    heat_score: float
    semantic_score: float
    highlight_type: str
    title: str
    summary: str
    keywords: List[str] = Field(default_factory=list)
    chat_count: int = 0
    unique_users: int = 0
    gift_count: int = 0
    like_count: int = 0
    danmu_count: int = 0
    danmu_truncated: bool = False
    danmu_snapshot_path: Optional[str] = None
    clip_path: Optional[str] = None
    story_text: Optional[str] = None
    speech_text: Optional[str] = None
    speech_text_path: Optional[str] = None
    speech_text_truncated: bool = False
    speech_language: Optional[str] = None
    speech_language_probability: Optional[float] = None
    llm_confidence: Optional[float] = None
    llm_is_highlight: Optional[bool] = None
    llm_decision_score: Optional[float] = None
    llm_scene_type: Optional[str] = None
    llm_scene_bias: Optional[float] = None
    llm_negative_reason: Optional[str] = None
    global_rank_score: Optional[float] = None
    llm_start_shift_sec: Optional[int] = None
    llm_end_shift_sec: Optional[int] = None


class AnalyzeResponse(BaseModel):
    success: bool
    record_id: str
    danmu_path: str
    stream_type: str = ""
    analysis_request: Optional[Dict[str, Any]] = None
    segment_count: int
    analyzed_at: str
    data: List[HighlightSegment]


class ExportResponse(BaseModel):
    success: bool
    record_id: str
    exported_count: int
    storyline_json_path: Optional[str] = None
    subtitles_srt_path: Optional[str] = None
    data: List[HighlightSegment]


class AnalyzeTaskSubmitResponse(BaseModel):
    success: bool
    task_id: str
    record_id: str
    status: Literal["queued", "running", "success", "failed", "cancelled"]
    ws_channel: str
    created_at: str


class AnalyzeTaskStatusResponse(BaseModel):
    success: bool
    task_id: str
    record_id: str
    status: Literal["queued", "running", "success", "failed", "cancelled"]
    stream_type: str = ""
    story_enabled: bool = False
    progress: int = 0
    message: str = ""
    segment_count: int = 0
    analyzed_at: str = ""
    error: Optional[str] = None
    created_at: str
    updated_at: str


class CleanupResponse(BaseModel):
    success: bool
    record_id: str
    removed_files: int = 0
    removed_dirs: int = 0
    freed_bytes: int = 0
    removed_tasks: int = 0


class StreamerCleanupResponse(BaseModel):
    success: bool
    subscription_id: str
    cleaned_records: int = 0
    removed_files: int = 0
    removed_dirs: int = 0
    freed_bytes: int = 0
    removed_tasks: int = 0


class ManualExportRequest(BaseModel):
    file_path_: str = Field(..., alias="file_path", description="视频文件绝对路径（如 /app/downloads/live/xxx/xxx.mp4）")
    start_sec: float = Field(..., ge=0, description="切片起始秒数")
    end_sec: float = Field(..., ge=0, description="切片结束秒数")
    overwrite: bool = Field(False, description="已存在时是否覆盖")


class ManualExportResponse(BaseModel):
    success: bool
    clip_path: str
    clip_error: Optional[str] = None
    segment: Optional[Dict[str, Any]] = None


class ManualClipItem(BaseModel):
    name: str
    path: str
    size_bytes: int
    start_sec: float
    end_sec: float
    created_at: str


class ManualClipListResponse(BaseModel):
    success: bool
    record_id: str
    clips: List[ManualClipItem]


class ManualClipCleanupResponse(BaseModel):
    success: bool
    record_id: Optional[str] = None
    subscription_id: Optional[str] = None
    removed_files: int = 0
    removed_dirs: int = 0
    freed_bytes: int = 0


class SegmentDanmuItem(BaseModel):
    event_type: str = "chat"
    sec: float = 0.0
    offset_sec: float = 0.0
    uid: str = ""
    text: str = ""


class SegmentDanmuResponse(BaseModel):
    success: bool
    record_id: str
    segment_id: str
    total_events: int = 0
    included_events: int = 0
    truncated: bool = False
    snapshot_path: str = ""
    data: List[SegmentDanmuItem] = Field(default_factory=list)
