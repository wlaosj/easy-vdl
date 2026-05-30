"""
订阅模块的所有 Pydantic 数据模型
"""
from pydantic import BaseModel, Field
from typing import List, Optional, Literal
from sql.models import SubscriptionVideoResponse

class RetryFailedDownloadsRequest(BaseModel):
    quality: str = Field(default="best", description="下载画质")
    batch_size: int = Field(default=1, ge=1, le=5, description="每批次同时处理的视频数量，1-5之间")

class BatchDownloadRequest(BaseModel):
    """批量下载请求模型"""
    type: Literal["count", "time"]
    count: Optional[int] = None
    days: Optional[int] = None
    quality: str = "best"  # 默认最高画质（包括8K）
    batch_size: int = Field(default=1, ge=1, le=5, description="每批次同时处理的视频数量，1-5之间")
    media_type: Optional[str] = Field(default=None, description="媒体类型过滤：video 仅视频，image 仅图片，不传则全部下载")

class CheckUpdateResponse(BaseModel):
    """检查更新响应模型"""
    message: str
    has_update: bool
    new_videos_count: int
    requires_sync: Optional[bool] = False
    status: Optional[str] = None
    error_message: Optional[str] = None

class SubscriptionVideosResponse(BaseModel):
    """订阅视频列表响应模型"""
    total: int
    downloaded_count: int
    not_downloaded_count: int
    downloading_count: int
    failed_count: int
    cancelled_count: int
    orphaned_count: int
    removed_count: int  # 已从源平台移除的视频数量
    charging_count: int = 0  # 充电专属视频数量
    video_count: int  # 视频数量
    note_count: int   # 图集数量
    videos: List[SubscriptionVideoResponse]

class QualityUpdateRequest(BaseModel):
    """画质设置更新请求模型"""
    quality: str

class VideoDownloadRequest(BaseModel):
    """视频下载请求模型"""
    quality: str = "best"  # 默认最高画质

class ImportSubscriptionRequest(BaseModel):
    """批量导入订阅请求模型"""
    subscriptions: List[dict]  # 订阅列表

class ImportSubscriptionResponse(BaseModel):
    """批量导入订阅响应模型"""
    total: int
    success: int
    failed: int
    errors: List[str]


class DouyinBatchAddRequest(BaseModel):
    """抖音博主批量添加请求"""
    profile_urls: List[str] = Field(..., max_items=15, description="抖音主页链接列表（支持短链，单次最多15个）")
    update_interval: float = Field(default=3600, description="自动检测周期（秒）")
    auto_download: str = Field(default="true", description="是否自动下载（true/false）")


class DouyinBatchAddResponse(BaseModel):
    """抖音博主批量添加响应"""
    message: str
    task_id: str
    total: int
    queued: int
