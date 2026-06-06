from sqlalchemy import Column, String, Float, DateTime, Enum as SQLAlchemyEnum, Integer, CheckConstraint, Text, BigInteger
from sqlalchemy.sql import func
import enum
from .database_postgresql import Base
from pydantic import BaseModel, Field, validator
from datetime import datetime, timezone, timedelta
from typing import Optional
import json

class TaskStatus(str, enum.Enum):
    PENDING = "PENDING"
    DOWNLOADING = "DOWNLOADING"
    PROCESSING = "PROCESSING"
    COMPLETED = "COMPLETED"
    ERROR = "ERROR"
    CANCELLED = "CANCELLED"

    @classmethod
    def from_str(cls, value: str) -> 'TaskStatus':
        """安全地从字符串转换为枚举值"""
        try:
            return cls(value.upper())
        except (ValueError, AttributeError):
            return cls.ERROR

class SubscriptionStatus(str, enum.Enum):
    ACTIVE = "active"      # 正常运行
    PAUSED = "paused"      # 暂停更新
    ERROR = "error"        # 出错状态
    INVALID = "invalid"    # 资源失效（连续资源类失败）
    EXPIRED = "expired"    # 登录过期

    @classmethod
    def from_str(cls, value: str) -> 'SubscriptionStatus':
        """安全地从字符串转换为枚举值"""
        try:
            return cls(value.lower())
        except (ValueError, AttributeError):
            return cls.ERROR

class Platform(str, enum.Enum):
    DOUYIN = "douyin"
    DOUYIN_COLLECTION = "douyin_collection"  # 抖音合集
    INSTAGRAM = "instagram"
    YOUTUBE = "youtube"
    YOUTUBE_PLAYLIST = "youtube_playlist"  # YouTube播放列表
    BILIBILI = "bilibili"
    BILIBILI_COLLECTION = "bilibili_collection"  # B站合集
    TIKTOK = "tiktok"  # TikTok
    XIAOHONGSHU = "xiaohongshu"
    NETEASE = "netease"  # 网易云歌单
    X = "x"  # X(Twitter)
    UNKNOWN = "unknown"

    @classmethod
    def from_str(cls, value: str) -> 'Platform':
        """安全地从字符串转换为枚举值"""
        try:
            return cls(value.lower())
        except (ValueError, AttributeError):
            return cls.UNKNOWN

class Subscription(Base):
    """订阅表"""
    __tablename__ = "subscriptions"

    id = Column(String, primary_key=True)  # UUID
    platform = Column(String, nullable=False)  # 平台
    user_id = Column(String, nullable=False, index=True)  # 博主ID或合集ID
    nickname = Column(String)  # 博主昵称或合集标题
    storage_name = Column(String, nullable=True)  # 固化存储目录名（用于下载路径）
    nickname_locked = Column(String, default="false")  # 是否锁定自定义昵称，锁定后同步不覆盖
    # 订阅类型字段（user=用户视频, collection=合集, favorite=点赞列表）
    subscription_type = Column(String, default="user")  # 订阅类型：user/collection/favorite
    # 合集相关字段
    collection_id = Column(String, nullable=True)  # 合集ID
    collection_title = Column(String, nullable=True)  # 合集标题
    author_id = Column(String, nullable=True)  # 合集作者ID
    author_name = Column(String, nullable=True)  # 合集作者名称
    # 博主信息字段
    avatar_url = Column(Text, nullable=True)  # 头像
    profile_url = Column(String(500), nullable=True)  # 创作者主页链接（小红书等需带 xsec_token）
    signature = Column(String, nullable=True)   # 签名/简介
    follower_count = Column(BigInteger, nullable=True)  # 粉丝数
    following_count = Column(Integer, nullable=True)  # 关注数
    video_count = Column(Integer, nullable=True)     # 视频总数
    like_count = Column(BigInteger, nullable=True)      # 获赞总数
    last_sync_info = Column(DateTime(timezone=True), nullable=True)  # 最后同步信息时间
    # 最新视频信息
    latest_video_time = Column(DateTime(timezone=True), nullable=True, index=True)  # 最新视频发布时间
    latest_video_id = Column(String, nullable=True)  # 最新视频ID
    latest_video_title = Column(String, nullable=True)  # 最新视频标题
    latest_video_cover = Column(Text, nullable=True)  # 最新视频封面
    # 配置字段
    update_interval = Column(Float, default=3600)  # 更新间隔（秒）
    auto_download = Column(String, default="true")  # 是否自动下载
    quality = Column(String, default="best")  # 画质设置（仅对YouTube有效）
    youtube_tab_type = Column(String, nullable=True)  # YouTube标签类型：videos/shorts/playlists（仅对platform=youtube有效）
    skip_bilibili_upower = Column(String, default="false")  # 跳过B站充电专属视频
    # 状态字段
    last_check = Column(DateTime(timezone=True), nullable=True)  # 最后检查时间
    last_update = Column(DateTime(timezone=True), nullable=True)  # 最后更新时间
    status = Column(String, default=SubscriptionStatus.ACTIVE.value)  # 订阅状态
    created_at = Column(DateTime(timezone=True), nullable=False)  # 创建时间
    updated_at = Column(DateTime(timezone=True), nullable=False)  # 更新时间
    error_message = Column(String, nullable=True)  # 错误信息
    extra_data = Column(String, nullable=True)  # 额外数据（JSON格式）
    # 同步状态字段
    sync_status = Column(String, nullable=True)  # 同步状态：syncing, completed, error
    sync_progress = Column(Integer, default=0)  # 已同步的视频数量
    # 批量下载状态字段
    batch_download_status = Column(String, nullable=True)  # 批量下载状态：downloading, completed, error
    batch_download_progress = Column(Integer, default=0)  # 已下载数量
    batch_download_total = Column(Integer, default=0)  # 总下载数量
    batch_download_completed = Column(Integer, default=0)  # 成功下载数量
    batch_download_failed = Column(Integer, default=0)  # 失败下载数量
    batch_download_start_time = Column(DateTime(timezone=True), nullable=True)  # 批量下载开始时间

class SubscriptionVideo(Base):
    """订阅视频表"""
    __tablename__ = "subscription_videos"

    id = Column(String, primary_key=True)  # UUID
    subscription_id = Column(String, nullable=False, index=True)  # 关联的订阅ID
    video_id = Column(String, nullable=False, index=True)  # 视频ID
    title = Column(Text, nullable=True)  # 视频标题（改为TEXT类型支持长标题）
    description = Column(String, nullable=True)  # 视频描述
    url = Column(Text)  # 视频链接
    cover_url = Column(String, nullable=True)  # 封面图链接
    duration = Column(Float, nullable=True)  # 视频时长（秒）
    created_at = Column(DateTime(timezone=True), nullable=False)  # 创建时间
    publish_time = Column(DateTime(timezone=True), nullable=True)  # 发布时间
    downloaded = Column(String, default="false")  # 是否已下载
    download_task_id = Column(String, nullable=True)  # 关联的下载任务ID
    error_message = Column(String, nullable=True)  # 下载错误信息
    extra_data = Column(String, nullable=True)  # 额外数据（JSON格式）

class Task(Base):
    __tablename__ = "tasks"

    id = Column(String(36), primary_key=True)
    url = Column(Text, nullable=False)
    original_url = Column(Text, nullable=True)
    title = Column(String(256), nullable=True)
    author = Column(String(256), nullable=True)
    source = Column(String(50))  # 来源：douyin, others等
    status = Column(String(20))
    progress = Column(Float, default=0.0)
    error_message = Column(Text, nullable=True)
    created_at = Column(DateTime)
    updated_at = Column(DateTime)
    filename = Column(String(512), nullable=True)
    proxy = Column(String(256), nullable=True)
    cookie = Column(Text, nullable=True)
    format_id = Column(String(50), nullable=True)  # 视频格式ID
    headers = Column(Text, nullable=True)  # 请求头信息，JSON格式
    subscription_id = Column(String(36), nullable=True, index=True)  # 关联的订阅ID

class GlobalConfig(Base):
    __tablename__ = "global_config"
    key = Column(String, primary_key=True)
    value = Column(String, nullable=True)

class PlaybackRecord(Base):
    """播放记录表"""
    __tablename__ = "playback_records"
    
    subscription_id = Column(String, primary_key=True)  # 订阅ID，主键
    current_index = Column(Integer, default=0)  # 当前播放索引
    playback_mode = Column(String, default="asc")  # 播放模式：random/asc/desc
    video_progress = Column(Text, nullable=True)  # JSON格式，存储每个视频的播放进度 {"video_id": seconds}
    last_updated = Column(DateTime(timezone=True), nullable=False)  # 最后更新时间

# Pydantic models for API
class TaskBase(BaseModel):
    id: str = Field(..., description="任务ID")
    source: str = Field(..., description="来源（youtube 或 douyin）")
    url: str = Field(..., description="下载URL")
    original_url: Optional[str] = Field(default=None, description="原始源地址")
    proxy: Optional[str] = Field(default=None, description="下载代理")
    cookie: Optional[str] = Field(default=None, description="下载Cookie")
    status: str = Field(default=TaskStatus.PENDING.value, description="任务状态")  # 改为 str 类型
    progress: float = Field(default=0.0, ge=0.0, le=100.0, description="下载进度")
    filename: Optional[str] = Field(default=None, description="文件名")
    error_message: Optional[str] = Field(default=None, description="错误信息")
    created_at: datetime = Field(..., description="创建时间")
    updated_at: datetime = Field(..., description="更新时间")
    format_id: Optional[str] = Field(default=None, description="下载格式ID")
    subscription_id: Optional[str] = Field(default=None, description="关联的订阅ID")
    author_info: Optional[dict] = Field(default=None, description="博主信息")
    task_type_display: Optional[str] = Field(default=None, description="任务类型显示文本")

    @validator('subscription_id')
    def validate_subscription_id(cls, v):
        """确保subscription_id不会被忽略"""
        return v if v else None

    @validator('source')
    def validate_source(cls, v):
        if v not in ['youtube', 'bilibili', 'douyin', 'instagram', 'xiaohongshu', 'tiktok', 'netease', 'x', 'others', 'unknown']:
            return 'unknown'
        return v

    @validator('status')
    def validate_status(cls, v):
        """验证并规范化状态字段"""
        if not v:
            return TaskStatus.ERROR.value
        try:
            # 尝试转换为大写并验证是否为有效状态
            status = TaskStatus.from_str(str(v))
            return status.value
        except (ValueError, AttributeError):
            return TaskStatus.ERROR.value

    @validator('progress')
    def validate_progress(cls, v):
        if v is None or not isinstance(v, (int, float)):
            return 0.0
        return float(max(0.0, min(100.0, v)))

    @validator('created_at', 'updated_at', pre=True)
    def validate_datetime(cls, v):
        if v is None:
            return datetime.now()
        if isinstance(v, str):
            try:
                # 处理带 Z 后缀的 UTC 时间格式
                if v.endswith('Z'):
                    v = v[:-1] + '+00:00'
                return datetime.fromisoformat(v)
            except ValueError:
                return datetime.now()
        return v

    class Config:
        from_attributes = True
        json_encoders = {
            datetime: lambda v: v.astimezone(timezone(timedelta(hours=8))).isoformat() if v else None
        }

class SubscriptionBase(BaseModel):
    """订阅基础模型"""
    platform: str
    user_id: Optional[str] = None  # 改为可选，可通过profile_url解析
    nickname: Optional[str] = None  # 改为可选，可通过profile_url解析
    update_interval: float = 3600
    auto_download: str = "false"  # 默认不自动下载
    quality: str = "best"  # 默认画质设置
    youtube_tab_type: Optional[str] = None  # YouTube标签类型：videos/shorts/playlists（仅对platform=youtube有效）
    subscription_type: Optional[str] = "user"  # 订阅类型：user/collection/favorite
    skip_bilibili_upower: Optional[str] = "false"  # 跳过B站充电专属视频
    status: str = SubscriptionStatus.ACTIVE.value

    @validator('platform')
    def validate_platform(cls, v):
        return Platform.from_str(v).value

    @validator('status')
    def validate_status(cls, v):
        return SubscriptionStatus.from_str(v).value

    @validator('update_interval')
    def validate_interval(cls, v):
        return max(1800, min(86400, float(v)))  # 限制在30分钟到24小时之间

    @validator('auto_download')
    def validate_auto_download(cls, v):
        return str(v).lower()  # 确保是小写字符串
    
class SubscriptionCreate(SubscriptionBase):
    """创建订阅的请求模型"""
    profile_url: Optional[str] = None  # 添加profile_url字段，支持直接传入频道链接

    @validator('user_id', 'nickname')
    def validate_user_info(cls, v, values):
        """验证用户信息：要么直接提供user_id和nickname，要么提供profile_url"""
        profile_url = values.get('profile_url')
        if not v and not profile_url:
            raise ValueError('必须提供user_id和nickname，或者提供profile_url')
        return v

class SubscriptionUpdate(BaseModel):
    """更新订阅的请求模型"""
    nickname: Optional[str] = None
    nickname_locked: Optional[str] = None
    update_interval: Optional[float] = None
    auto_download: Optional[str] = None  # 改为字符串类型
    quality: Optional[str] = None  # 画质设置
    skip_bilibili_upower: Optional[str] = None  # 跳过B站充电专属视频
    status: Optional[str] = None

    @validator('status')
    def validate_status(cls, v):
        if v is not None:
            return SubscriptionStatus.from_str(v).value
        return v

    @validator('update_interval')
    def validate_interval(cls, v):
        if v is not None:
            return max(1800, min(86400, float(v)))  # 限制在30分钟到24小时之间
        return v

    @validator('auto_download')
    def validate_auto_download(cls, v):
        if v is not None:
            return str(v).lower()
        return v

    @validator('nickname_locked')
    def validate_nickname_locked(cls, v):
        if v is not None:
            return str(v).lower()
        return v

class SubscriptionResponse(SubscriptionBase):
    """订阅响应模型"""
    id: str
    last_check: Optional[datetime] = None  # 添加最后检查时间字段
    last_update: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime
    error_message: Optional[str] = None
    quality: Optional[str] = None  # 画质设置
    youtube_tab_type: Optional[str] = None  # YouTube标签类型
    skip_bilibili_upower: Optional[str] = "false"  # 跳过B站充电专属视频
    # 博主信息字段
    avatar_url: Optional[str] = None
    signature: Optional[str] = None
    follower_count: Optional[int] = None
    following_count: Optional[int] = None
    video_count: Optional[int] = None
    like_count: Optional[int] = None
    last_sync_info: Optional[datetime] = None
    # 最新视频信息
    latest_video_time: Optional[datetime] = None
    latest_video_id: Optional[str] = None
    latest_video_title: Optional[str] = None
    latest_video_cover: Optional[str] = None
    # 同步状态字段
    sync_status: Optional[str] = None
    sync_progress: Optional[int] = None
    # 批量下载状态字段
    batch_download_status: Optional[str] = None
    batch_download_progress: Optional[int] = None
    batch_download_total: Optional[int] = None
    batch_download_completed: Optional[int] = None
    batch_download_failed: Optional[int] = None
    batch_download_start_time: Optional[datetime] = None
    # 博主主页URL
    profile_url: Optional[str] = None
    storage_name: Optional[str] = None
    nickname_locked: Optional[str] = "false"

    class Config:
        from_attributes = True
        json_encoders = {
            datetime: lambda v: v.astimezone(timezone(timedelta(hours=8))).isoformat() if v else None
        }

class SubscriptionVideoBase(BaseModel):
    """视频基础模型"""
    subscription_id: str
    video_id: str
    title: str
    url: str
    cover_url: Optional[str] = None
    duration: Optional[float] = None
    publish_time: Optional[datetime] = None
    downloaded: str = "false"  # 改为字符串类型，与数据库一致
    download_task_id: Optional[str] = None
    error_message: Optional[str] = None  # 下载错误信息

    @validator('downloaded')
    def validate_downloaded(cls, v):
        if isinstance(v, bool):
            return str(v).lower()
        return str(v).lower()  # 确保是小写的字符串

class SubscriptionVideoCreate(SubscriptionVideoBase):
    """创建视频记录的请求模型"""
    pass

class SubscriptionVideoResponse(SubscriptionVideoBase):
    """视频响应模型"""
    id: str
    created_at: datetime
    description: Optional[str] = None
    error_message: Optional[str] = None  # 下载错误信息
    status: Optional[str] = None  # 计算的状态字段：downloaded, failed, cancelled, downloading, orphaned, not_downloaded
    removed_from_source: Optional[bool] = False  # 是否已从源平台移除
    extra_data: Optional[str] = None  # 额外数据（JSON字符串格式，前端需要解析）

    class Config:
        from_attributes = True
        json_encoders = {
            datetime: lambda v: v.astimezone(timezone(timedelta(hours=8))).isoformat() if v else None
        }

class SystemConfig(Base):
    """系统配置表"""
    __tablename__ = "system_config"

    key = Column(String, primary_key=True)
    value = Column(String, nullable=True)
    updated_at = Column(DateTime(timezone=True), nullable=False)

class User(Base):
    """用户表"""
    __tablename__ = "users"

    id = Column(String, primary_key=True)  # UUID
    username = Column(String, unique=True, nullable=False, index=True)
    password_hash = Column(String, nullable=False)  # bcrypt加密
    email = Column(String, nullable=True)  # 可选，用于密码重置
    is_admin = Column(String, default="true")  # 首次注册的用户默认为管理员
    is_active = Column(String, default="true")
    created_at = Column(DateTime(timezone=True), nullable=False)
    last_login = Column(DateTime(timezone=True), nullable=True)

class ApiToken(Base):
    """API Token 表 - 用于外部应用（如电报机器人、微信机器人）调用 API"""
    __tablename__ = "api_tokens"
    
    id = Column(String, primary_key=True)  # UUID
    token = Column(String, unique=True, nullable=False, index=True)  # Token 字符串
    name = Column(String, nullable=False)  # Token 名称/描述
    user_id = Column(String, nullable=True, index=True)  # 关联的用户 ID（创建者）
    created_at = Column(DateTime(timezone=True), nullable=False)  # 创建时间
    expires_at = Column(DateTime(timezone=True), nullable=True)  # 过期时间（None 表示永不过期）
    last_used_at = Column(DateTime(timezone=True), nullable=True)  # 最后使用时间
    is_active = Column(String, default="true")  # 是否激活

# Pydantic models for User API
class UserBase(BaseModel):
    """用户基础模型"""
    username: str = Field(..., min_length=3, max_length=50, description="用户名")
    email: Optional[str] = Field(None, description="邮箱地址")

class UserCreate(UserBase):
    """创建用户的请求模型"""
    password: str = Field(..., min_length=6, description="密码")

class UserLogin(BaseModel):
    """用户登录模型"""
    username: str = Field(..., description="用户名")
    password: str = Field(..., description="密码")

class UserResponse(UserBase):
    """用户响应模型"""
    id: str
    is_admin: str
    is_active: str
    created_at: datetime
    last_login: Optional[datetime] = None

    class Config:
        from_attributes = True
        json_encoders = {
            datetime: lambda v: v.astimezone(timezone(timedelta(hours=8))).isoformat() if v else None
        }

class TokenResponse(BaseModel):
    """Token响应模型"""
    access_token: str
    token_type: str = "bearer"
    username: str
    is_admin: str 

# API Token Pydantic models
class ApiTokenCreate(BaseModel):
    """创建 API Token 请求模型"""
    name: str = Field(..., description="Token 名称/描述")
    expires_in_days: Optional[int] = Field(None, ge=1, description="过期天数，None 表示永不过期")

class ApiTokenUpdate(BaseModel):
    """更新 API Token 请求模型"""
    name: Optional[str] = Field(None, description="Token 名称/描述")
    expires_in_days: Optional[int] = Field(None, ge=1, description="过期天数，None 表示永不过期")
    is_active: Optional[bool] = Field(None, description="是否激活")

class ApiTokenResponse(BaseModel):
    """API Token 响应模型"""
    id: str
    token: str  # 仅在创建时返回完整 token
    name: str
    user_id: Optional[str]
    created_at: datetime
    expires_at: Optional[datetime]
    last_used_at: Optional[datetime]
    is_active: str
    
    class Config:
        from_attributes = True

class CookieConfig(Base):
    """Cookie自动更新配置表"""
    __tablename__ = "cookie_config"

    platform = Column(String, primary_key=True)  # 平台名称（如youtube）
    enabled = Column(String, default="false")  # 是否启用自动更新
    interval_minutes = Column(Integer, default=10)  # 更新间隔（分钟）
    last_update = Column(DateTime(timezone=True), nullable=True)  # 最后更新时间
    next_update = Column(DateTime(timezone=True), nullable=True)  # 下次更新时间
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())

# Pydantic models for CookieConfig API
class CookieConfigBase(BaseModel):
    """Cookie配置基础模型"""
    platform: str
    enabled: str = "false"
    interval_minutes: int = 10
    last_update: Optional[datetime] = None
    next_update: Optional[datetime] = None

class CookieConfigCreate(CookieConfigBase):
    """创建Cookie配置的请求模型"""
    pass

class CookieConfigUpdate(BaseModel):
    """更新Cookie配置的请求模型"""
    enabled: Optional[str] = None
    interval_minutes: Optional[int] = None
    last_update: Optional[datetime] = None
    next_update: Optional[datetime] = None

class CookieConfigResponse(CookieConfigBase):
    """Cookie配置响应模型"""
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True
        json_encoders = {
            datetime: lambda v: v.astimezone(timezone(timedelta(hours=8))).isoformat() if v else None
        } 

class NotificationType(str, enum.Enum):
    """通知类型枚举"""
    DOWNLOAD_COMPLETED = "download_completed"      # 下载完成
    DOWNLOAD_ERROR = "download_error"              # 下载错误
    USER_ACTION = "user_action"                    # 用户操作
    BATCH_OPERATION = "batch_operation"            # 批量操作

    SUBSCRIPTION_CHECK_FAILED = "subscription_check_failed"    # 订阅检测失败
    SUBSCRIPTION_CHECK_NEW_VIDEOS = "subscription_check_new_videos"  # 订阅检测发现新视频
    SUBSCRIPTION_CHECK_NO_NEW_VIDEOS = "subscription_check_no_new_videos"  # 订阅检测未发现新视频

class NotificationStatus(str, enum.Enum):
    """通知状态枚举"""
    PENDING = "pending"        # 待发送
    SENT = "sent"              # 已发送
    FAILED = "failed"          # 发送失败
    READ = "read"              # 已读

class NotificationChannel(str, enum.Enum):
    """通知渠道枚举"""
    WECHAT_BOT = "wechat_bot"     # 微信机器人
    SERVERCHAN3 = "serverchan3"   # Server酱³
    EMAIL = "email"                # 邮件
    WEB_PUSH = "web_push"          # 网页推送
    WEBSOCKET = "websocket"        # WebSocket实时推送
    TELEGRAM_BOT = "telegram_bot"  # Telegram机器人
    BARK = "bark"                  # Bark (iOS)
    WECOM_BOT = "wecom_bot"        # 企业微信应用机器人

class Notification(Base):
    """通知表"""
    __tablename__ = "notifications"

    id = Column(String, primary_key=True)  # UUID
    user_id = Column(String, nullable=True, index=True)  # 用户ID（可为空，表示系统通知）
    type = Column(String, nullable=False)  # 通知类型
    title = Column(String, nullable=False)  # 通知标题
    content = Column(Text, nullable=False)  # 通知内容
    status = Column(String, default=NotificationStatus.PENDING.value)  # 通知状态
    channel = Column(String, default=NotificationChannel.WECHAT_BOT.value)  # 通知渠道
    priority = Column(Integer, default=1)  # 优先级（1-5，5最高）
    extra_data = Column(Text, nullable=True)  # 元数据（JSON格式）
    sent_at = Column(DateTime(timezone=True), nullable=True)  # 发送时间
    read_at = Column(DateTime(timezone=True), nullable=True)  # 阅读时间
    error_message = Column(String, nullable=True)  # 错误信息
    retry_count = Column(Integer, default=0)  # 重试次数
    created_at = Column(DateTime(timezone=True), nullable=False, default=func.now())  # 创建时间
    updated_at = Column(DateTime(timezone=True), nullable=False, default=func.now(), onupdate=func.now())  # 更新时间

class NotificationSetting(Base):
    """通知设置表"""
    __tablename__ = "notification_settings"

    id = Column(String, primary_key=True)  # UUID
    user_id = Column(String, nullable=False, unique=True, index=True)  # 用户ID
    wechat_bot_enabled = Column(String, default="true")  # 微信机器人开关
    wechat_webhook_url = Column(String, nullable=True)  # 微信机器人Webhook URL
    serverchan3_enabled = Column(String, default="false")  # Server酱³开关
    serverchan3_uid = Column(String, nullable=True)  # Server酱³ UID
    serverchan3_sendkey = Column(String, nullable=True)  # Server酱³ SendKey
    email_enabled = Column(String, default="false")  # 邮件通知开关
    email_address = Column(String, nullable=True)  # 邮箱地址
    web_push_enabled = Column(String, default="true")  # 网页推送开关
    websocket_enabled = Column(String, default="true")  # WebSocket实时推送开关
    # 媒体服务器集成（Jellyfin/Emby）
    media_server_enabled = Column(String, default="false")  # 是否启用媒体服务器刷新
    media_server_type = Column(String, default="jellyfin")  # 媒体服务器类型：jellyfin/emby/auto
    media_server_url = Column(String, nullable=True)  # 媒体服务器地址
    media_server_api_key = Column(String, nullable=True)  # 媒体服务器API密钥
    # 通知类型开关
    download_completed_enabled = Column(String, default="true")  # 下载完成通知
    download_error_enabled = Column(String, default="true")  # 下载错误通知

    subscription_check_failed_enabled = Column(String, default="true")  # 订阅检测失败通知
    subscription_check_new_videos_enabled = Column(String, default="true")  # 订阅检测发现新视频通知
    subscription_check_no_new_videos_enabled = Column(String, default="false")  # 订阅检测未发现新视频通知
    system_status_enabled = Column(String, default="true")  # 系统状态/公告通知开关
    # 通知频率设置

    quiet_hours_enabled = Column(String, default="true")  # 静音时间开关
    quiet_hours_start = Column(String, default="22:00")  # 静音时间开始
    quiet_hours_end = Column(String, default="08:00")  # 静音时间结束
    
    # Telegram 机器人配置
    telegram_bot_enabled = Column(String, default="false")
    telegram_bot_token = Column(String, nullable=True)
    telegram_chat_id = Column(String, nullable=True)
    telegram_proxy = Column(String, nullable=True)
    telegram_media_max_concurrent = Column(Integer, default=5)
    telegram_media_use_date_subdir = Column(String, default="true")
    # 企业微信应用Bot配置
    wecom_bot_enabled = Column(String, default="false")
    wecom_corp_id = Column(String, nullable=True)
    wecom_agent_id = Column(String, nullable=True)
    wecom_secret = Column(String, nullable=True)
    wecom_callback_token = Column(String, nullable=True)
    wecom_callback_aes_key = Column(String, nullable=True)
    wecom_callback_url = Column(String, nullable=True)
    wecom_api_proxy = Column(String, nullable=True)  # API代理地址
    # Bark (iOS 推送) 配置
    bark_enabled = Column(String, default="false")
    bark_server_url = Column(String, nullable=True)
    bark_device_key = Column(String, nullable=True)
    bark_sound = Column(String, nullable=True)
    bark_group = Column(String, nullable=True)
    bark_icon = Column(String, nullable=True)
    bark_url = Column(String, nullable=True)
    bark_automatically_copy = Column(String, default="false")
    created_at = Column(DateTime(timezone=True), nullable=False, default=func.now())  # 创建时间
    updated_at = Column(DateTime(timezone=True), nullable=False, default=func.now(), onupdate=func.now())  # 更新时间

# Pydantic模型
class NotificationCreate(BaseModel):
    """创建通知请求模型"""
    user_id: Optional[str] = None
    type: str
    title: str
    content: str
    channel: str = NotificationChannel.WECHAT_BOT.value
    priority: int = 1
    extra_data: Optional[dict] = None

class NotificationUpdate(BaseModel):
    """更新通知请求模型"""
    status: Optional[str] = None
    read_at: Optional[datetime] = None
    error_message: Optional[str] = None
    retry_count: Optional[int] = None

class NotificationSettingCreate(BaseModel):
    """创建通知设置请求模型"""
    wechat_bot_enabled: str = "true"
    wechat_webhook_url: Optional[str] = None
    serverchan3_enabled: str = "false"
    serverchan3_uid: Optional[str] = None
    serverchan3_sendkey: Optional[str] = None
    email_enabled: str = "false"
    email_address: Optional[str] = None
    web_push_enabled: str = "true"
    websocket_enabled: str = "true"
    # 媒体服务器集成（Jellyfin/Emby）
    media_server_enabled: str = "false"
    media_server_type: str = "jellyfin"
    media_server_url: Optional[str] = None
    media_server_api_key: Optional[str] = None
    download_completed_enabled: str = "true"
    download_error_enabled: str = "true"

    subscription_check_failed_enabled: str = "true"
    subscription_check_new_videos_enabled: str = "true"
    subscription_check_no_new_videos_enabled: str = "false"
    system_status_enabled: str = "true"

    quiet_hours_enabled: str = "true"
    quiet_hours_start: str = "22:00"
    quiet_hours_end: str = "08:00"

    # Telegram 机器人配置
    telegram_bot_enabled: str = "false"
    telegram_bot_token: Optional[str] = None
    telegram_chat_id: Optional[str] = None
    telegram_proxy: Optional[str] = None
    telegram_media_max_concurrent: int = Field(default=5, ge=1, le=10)
    telegram_media_use_date_subdir: str = "true"
    # 企业微信应用Bot
    wecom_bot_enabled: str = "false"
    wecom_corp_id: Optional[str] = None
    wecom_agent_id: Optional[str] = None
    wecom_secret: Optional[str] = None
    wecom_callback_token: Optional[str] = None
    wecom_callback_aes_key: Optional[str] = None
    wecom_callback_url: Optional[str] = None
    wecom_api_proxy: Optional[str] = None
    # Bark
    bark_enabled: str = "false"
    bark_server_url: Optional[str] = None
    bark_device_key: Optional[str] = None
    bark_sound: Optional[str] = None
    bark_group: Optional[str] = None
    bark_icon: Optional[str] = None
    bark_url: Optional[str] = None
    bark_automatically_copy: str = "false"

class NotificationSettingUpdate(BaseModel):
    """更新通知设置请求模型"""
    wechat_bot_enabled: Optional[str] = None
    wechat_webhook_url: Optional[str] = None
    serverchan3_enabled: Optional[str] = None
    serverchan3_uid: Optional[str] = None
    serverchan3_sendkey: Optional[str] = None
    email_enabled: Optional[str] = None
    email_address: Optional[str] = None
    web_push_enabled: Optional[str] = None
    websocket_enabled: Optional[str] = None
    # 媒体服务器集成（Jellyfin/Emby）
    media_server_enabled: Optional[str] = None
    media_server_type: Optional[str] = None
    media_server_url: Optional[str] = None
    media_server_api_key: Optional[str] = None
    download_completed_enabled: Optional[str] = None
    download_error_enabled: Optional[str] = None

    subscription_check_failed_enabled: Optional[str] = None
    subscription_check_new_videos_enabled: Optional[str] = None
    subscription_check_no_new_videos_enabled: Optional[str] = None
    system_status_enabled: Optional[str] = None

    quiet_hours_enabled: Optional[str] = None
    quiet_hours_start: Optional[str] = None
    quiet_hours_end: Optional[str] = None

    # Telegram 机器人配置
    telegram_bot_enabled: Optional[str] = None
    telegram_bot_token: Optional[str] = None
    telegram_chat_id: Optional[str] = None
    telegram_proxy: Optional[str] = None
    telegram_media_max_concurrent: Optional[int] = Field(default=None, ge=1, le=10)
    telegram_media_use_date_subdir: Optional[str] = None
    # 企业微信应用Bot
    wecom_bot_enabled: Optional[str] = None
    wecom_corp_id: Optional[str] = None
    wecom_agent_id: Optional[str] = None
    wecom_secret: Optional[str] = None
    wecom_callback_token: Optional[str] = None
    wecom_callback_aes_key: Optional[str] = None
    wecom_callback_url: Optional[str] = None
    wecom_api_proxy: Optional[str] = None
    # Bark
    bark_enabled: Optional[str] = None
    bark_server_url: Optional[str] = None
    bark_device_key: Optional[str] = None
    bark_sound: Optional[str] = None
    bark_group: Optional[str] = None
    bark_icon: Optional[str] = None
    bark_url: Optional[str] = None
    bark_automatically_copy: Optional[str] = None

class WecomBotTestRequest(BaseModel):
    """企业微信应用Bot测试请求模型"""
    corp_id: str
    agent_id: str
    secret: str
    proxy: Optional[str] = ""
    message: str = "这是一条测试消息，用于验证企业微信应用Bot配置是否正确。"

class WechatBotTestRequest(BaseModel):
    """微信机器人测试请求模型"""
    webhook_url: str
    message: str = "这是一条测试消息，用于验证微信机器人配置是否正确。"

class ServerChan3TestRequest(BaseModel):
    """Server酱³测试请求模型"""
    uid: str
    sendkey: str
    message: str = "这是一条测试消息，用于验证Server酱³配置是否正确。"

class TelegramBotTestRequest(BaseModel):
    """Telegram Bot测试请求模型"""
    token: str
    chat_id: str
    proxy: Optional[str] = None
    message: str = "这是一条测试消息，用于验证 Telegram Bot 配置是否正确。"

class BarkTestRequest(BaseModel):
    """Bark 测试请求模型"""
    device_key: str
    server_url: Optional[str] = None
    sound: Optional[str] = None
    group: Optional[str] = None
    icon: Optional[str] = None
    url: Optional[str] = None
    automatically_copy: Optional[str] = "false"
    title: str = "🧪 Bark 测试消息"
    message: str = "这是一条测试消息，用于验证 Bark 配置是否正确。"

class NotificationResponse(BaseModel):
    """通知响应模型"""
    id: str
    type: str
    title: str
    content: str
    status: str
    channel: str
    priority: int
    created_at: datetime
    sent_at: Optional[datetime] = None
    read_at: Optional[datetime] = None

class NotificationSettingResponse(BaseModel):
    """通知设置响应模型"""
    id: str
    user_id: str
    wechat_bot_enabled: str
    wechat_webhook_url: Optional[str] = None
    serverchan3_enabled: str
    serverchan3_uid: Optional[str] = None
    serverchan3_sendkey: Optional[str] = None
    email_enabled: str
    email_address: Optional[str] = None
    web_push_enabled: str
    websocket_enabled: str
    # 媒体服务器集成（Jellyfin/Emby）
    media_server_enabled: str
    media_server_type: str
    media_server_url: Optional[str] = None
    media_server_api_key: Optional[str] = None
    download_completed_enabled: str
    download_error_enabled: str

    subscription_check_failed_enabled: str
    subscription_check_new_videos_enabled: str
    subscription_check_no_new_videos_enabled: str
    system_status_enabled: str = "true"

    quiet_hours_enabled: str
    quiet_hours_start: str
    quiet_hours_end: str
    created_at: datetime
    updated_at: datetime

    # Telegram 机器人配置
    telegram_bot_enabled: str
    telegram_bot_token: Optional[str] = None
    telegram_chat_id: Optional[str] = None
    telegram_proxy: Optional[str] = None
    telegram_media_max_concurrent: int = 5
    telegram_media_use_date_subdir: str = "true"
    # 企业微信应用Bot
    wecom_bot_enabled: str = "false"
    wecom_corp_id: Optional[str] = None
    wecom_agent_id: Optional[str] = None
    wecom_secret: Optional[str] = None
    wecom_callback_token: Optional[str] = None
    wecom_callback_aes_key: Optional[str] = None
    wecom_callback_url: Optional[str] = None
    wecom_api_proxy: Optional[str] = None
    # Bark
    bark_enabled: str = "false"
    bark_server_url: Optional[str] = None
    bark_device_key: Optional[str] = None
    bark_sound: Optional[str] = None
    bark_group: Optional[str] = None
    bark_icon: Optional[str] = None
    bark_url: Optional[str] = None
    bark_automatically_copy: str = "false"

# 播放记录相关模型
class PlaybackRecordBase(BaseModel):
    """播放记录基础模型"""
    subscription_id: str = Field(..., description="订阅ID")
    current_index: int = Field(default=0, ge=0, description="当前播放索引")
    playback_mode: str = Field(default="asc", description="播放模式：random/asc/desc")
    video_progress: Optional[dict] = Field(default=None, description="视频播放进度，格式：{\"video_id\": seconds}")

class PlaybackRecordCreate(PlaybackRecordBase):
    """创建播放记录请求模型"""
    pass

class PlaybackRecordUpdate(BaseModel):
    """更新播放记录请求模型"""
    current_index: Optional[int] = Field(None, ge=0, description="当前播放索引")
    playback_mode: Optional[str] = Field(None, description="播放模式：random/asc/desc")
    video_progress: Optional[dict] = Field(None, description="视频播放进度")

class PlaybackRecordResponse(PlaybackRecordBase):
    """播放记录响应模型"""
    last_updated: datetime = Field(..., description="最后更新时间")
    
    class Config:
        from_attributes = True 

# ==================== API参数缓存表 ====================

class ApiParamsCache(Base):
    """API参数缓存表 - 抖音/YouTube/B站共用
    
    用于持久化存储各平台API请求所需的参数，避免每次重启后重新获取。
    支持按平台设置不同的过期时间。
    """
    __tablename__ = "api_params_cache"
    
    platform = Column(String, primary_key=True)  # 平台标识: douyin/youtube/bilibili
    params_json = Column(Text, nullable=False)   # JSON格式存储的参数
    expire_seconds = Column(Integer, default=1800)  # 过期时间（秒），默认30分钟
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())  # 更新时间
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())  # 创建时间


# ==================== 直播录制相关表 ====================

class LiveSubscription(Base):
    """直播间订阅表"""
    __tablename__ = "live_subscriptions"
    
    id = Column(String, primary_key=True)  # UUID
    platform = Column(String, nullable=False, index=True)  # 平台: douyin/bilibili/kuaishou/huya/douyu等
    room_url = Column(String, nullable=False)  # 直播间URL
    room_id = Column(String, nullable=True, index=True)  # 直播间ID (未开播时可能为空)
    anchor_name = Column(String, nullable=True)  # 主播名称 (未开播时可能为空)
    avatar_url = Column(String, nullable=True)  # 主播头像
    signature = Column(Text, nullable=True)  # 主播签名/简介
    
    # 录制配置
    quality = Column(String, default="原画")  # 录制画质: 原画/蓝光/超清/高清
    auto_record = Column(String, default="true")  # 是否自动录制
    monitor_enabled = Column(String, default="true")  # 是否启用周期检测
    check_interval = Column(Integer, default=60)  # 检测间隔(秒)
    output_format = Column(String, default="ts")  # 输出格式: ts/mp4/flv
    
    # 分段录制
    split_enabled = Column(String, default="false")  # 是否开启分段录制
    split_duration = Column(Integer, default=3600)  # 分段时长(秒), 默认1小时
    
    # 时长限制
    max_duration = Column(Integer, nullable=True)  # 最大录制时长(秒), NULL=不限制
    
    # 状态字段
    is_live = Column(String, default="false")  # 是否正在直播
    is_recording = Column(String, default="false")  # 是否正在录制
    last_check_time = Column(DateTime(timezone=True), nullable=True)  # 最后检查时间
    last_live_time = Column(DateTime(timezone=True), nullable=True)  # 最后开播时间
    
    # 通知设置
    notification_enabled = Column(String, default="true")  # 是否启用开播通知
    notification_end_enabled = Column(String, default="false")  # 是否启用下播通知
    
    # 网络配置
    proxy = Column(String, nullable=True)  # 代理设置 (如 http://127.0.0.1:7890)
    cookies = Column(Text, nullable=True)  # 自定义Cookie
    
    # 统计信息
    total_record_count = Column(Integer, default=0)  # 累计录制次数
    total_record_duration = Column(Integer, default=0)  # 累计录制时长(秒)
    total_record_size = Column(BigInteger, default=0)  # 累计录制大小(字节)
    
    # 备注
    remark = Column(Text, nullable=True)  # 用户备注
    
    # 扩展字段 (预留)
    extra_data = Column(Text, nullable=True)  # 额外数据(JSON格式)
    
    # 时间戳
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())


class LiveRecord(Base):
    """直播录制记录表"""
    __tablename__ = "live_records"
    
    id = Column(String, primary_key=True)  # UUID
    subscription_id = Column(String, nullable=False, index=True)  # 关联的订阅ID
    
    # 主播信息快照 (录制时的信息,避免关联查询)
    platform = Column(String, nullable=True)  # 平台
    anchor_name = Column(String, nullable=True)  # 主播名称
    room_id = Column(String, nullable=True)  # 直播间ID
    
    # 直播信息
    live_title = Column(String, nullable=True)  # 直播标题
    
    # 录制信息
    stream_url = Column(Text, nullable=True)  # 直播流URL
    quality = Column(String, nullable=True)  # 录制画质
    start_time = Column(DateTime(timezone=True), nullable=False)  # 开始时间
    end_time = Column(DateTime(timezone=True), nullable=True)  # 结束时间
    duration = Column(Integer, nullable=True)  # 录制时长(秒)
    
    # 文件信息
    file_path = Column(String, nullable=True)  # 文件路径
    file_name = Column(String, nullable=True)  # 文件名
    file_size = Column(BigInteger, nullable=True)  # 文件大小(字节)
    format = Column(String, default="ts")  # 文件格式: ts/mp4/flv
    
    # 分段信息
    segment_index = Column(Integer, default=0)  # 分段索引, 0=未分段或第一段
    parent_record_id = Column(String, nullable=True)  # 父记录ID (如果是分段录制)
    
    # 状态
    status = Column(String, default="recording")  # 状态: recording/completed/failed/stopped/converting
    error_message = Column(Text, nullable=True)  # 错误信息
    remark = Column(Text, nullable=True)  # 用户备注
    
    # 触发方式
    trigger_type = Column(String, default="auto")  # 触发方式: auto(自动)/manual(手动)
    
    # 转码信息
    converted = Column(String, default="false")  # 是否已转码
    converted_path = Column(String, nullable=True)  # 转码后文件路径
    converted_format = Column(String, nullable=True)  # 转码后格式
    
    # 扩展字段 (预留)
    extra_data = Column(Text, nullable=True)  # 额外数据(JSON格式)
    
    # 时间戳
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())
