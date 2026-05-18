"""
平台适配器抽象基类

定义所有平台适配器必须实现的接口，确保统一的调用方式。
"""
from abc import ABC, abstractmethod
from typing import List, Dict, Optional, Any, Callable
from datetime import datetime


class PlatformAdapter(ABC):
    """平台适配器抽象基类
    
    所有平台适配器必须继承此类并实现所有抽象方法。
    """
    
    @property
    @abstractmethod
    def platform_name(self) -> str:
        """平台名称（如 'douyin', 'youtube', 'bilibili', 'tiktok'）"""
        pass
    
    @property
    @abstractmethod
    def supported_subscription_types(self) -> List[str]:
        """支持的订阅类型列表
        
        例如：['user', 'favorite', 'collection']
        """
        pass
    
    @abstractmethod
    async def get_user_info(
        self,
        user_id: str,
        subscription_type: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        """获取用户/频道信息
        
        Args:
            user_id: 用户ID或频道ID
            subscription_type: 订阅类型（如 'favorite', 'collection'）
            
        Returns:
            用户信息字典，包含：
            - nickname: 昵称
            - avatar_url: 头像URL
            - follower_count: 粉丝数
            - video_count: 视频数
            - signature: 签名/简介
            - 其他平台特定字段
        """
        pass
    
    @abstractmethod
    async def get_latest_videos(
        self,
        user_id: str,
        subscription_type: Optional[str] = None,
        max_count: int = 30,
        latest_video_time: Optional[datetime] = None,
        latest_video_id: Optional[str] = None,
        **kwargs
    ) -> Dict[str, Any]:
        """获取最新视频列表（用于检查更新）
        
        Args:
            user_id: 用户ID或频道ID
            subscription_type: 订阅类型
            max_count: 最大获取数量
            latest_video_time: 上次最新视频时间（用于增量获取）
            latest_video_id: 上次最新视频ID（用于基于ID的检测）
            **kwargs: 平台特定参数（如 youtube_tab_type, latest_page 等）
            
        Returns:
            视频列表字典，格式：
            {
                'videos': List[Dict],  # 视频列表
                'has_more': bool,      # 是否还有更多
                'next_cursor': str,    # 下一页游标（可选）
                'real_channel_id': str # 真实频道ID（YouTube，可选）
            }
        """
        pass
    
    @abstractmethod
    async def get_all_videos(
        self,
        user_id: str,
        subscription_type: Optional[str] = None,
        progress_callback: Optional[Callable] = None,
        **kwargs
    ) -> List[Dict[str, Any]]:
        """获取所有视频列表（用于同步）
        
        Args:
            user_id: 用户ID或频道ID
            subscription_type: 订阅类型
            progress_callback: 进度回调函数（可选）
            **kwargs: 平台特定参数
            
        Returns:
            视频列表
        """
        pass
    
    @abstractmethod
    def normalize_video_data(
        self,
        video: Dict[str, Any],
        subscription_type: Optional[str] = None
    ) -> Dict[str, Any]:
        """标准化视频数据格式
        
        将平台特定的视频数据格式转换为统一格式。
        
        Args:
            video: 平台原始视频数据
            subscription_type: 订阅类型
            
        Returns:
            标准化后的视频数据，包含：
            - video_id: 视频ID
            - title: 标题
            - url: 视频URL
            - cover_url: 封面URL
            - publish_time: 发布时间（datetime对象）
            - stats: 统计数据（字典）
            - is_charging_arc: 是否充电专属（B站，可选）
        """
        pass
    
    def check_update_logic(
        self,
        latest_video: Dict[str, Any],
        subscription_latest_video_time: Optional[datetime],
        subscription_latest_video_id: Optional[str],
        subscription_type: Optional[str] = None
    ) -> bool:
        """检查是否有更新的逻辑
        
        默认实现：基于视频ID或发布时间判断
        
        Args:
            latest_video: 最新视频数据
            subscription_latest_video_time: 订阅记录的最新视频时间
            subscription_latest_video_id: 订阅记录的最新视频ID
            
        Returns:
            是否有更新
        """
        # 默认实现：优先使用ID检测，其次使用时间检测
        video_id = latest_video.get('video_id') or latest_video.get('id', {}).get('videoId')
        if video_id and subscription_latest_video_id:
            return video_id != subscription_latest_video_id
        
        video_time = latest_video.get('publish_time')
        if video_time and subscription_latest_video_time:
            if isinstance(video_time, str):
                video_time = datetime.fromisoformat(video_time.replace('Z', '+00:00'))
            return video_time > subscription_latest_video_time
        
        # 如果都没有，认为有更新（首次检查）
        return True
    
    async def update_subscription_info(
        self,
        subscription: Any,
        user_id: str,
        subscription_type: Optional[str] = None
    ) -> None:
        """更新订阅信息（可选实现）
        
        默认实现：调用 get_user_info 并更新订阅对象
        
        Args:
            subscription: 订阅对象（SQLAlchemy模型）
            user_id: 用户ID
            subscription_type: 订阅类型
        """
        user_info = await self.get_user_info(user_id, subscription_type)
        if not user_info:
            return
        
        # 更新订阅信息
        nickname_locked = str(getattr(subscription, 'nickname_locked', 'false')).lower() == 'true'
        if user_info.get('nickname') and subscription_type != 'favorite':
            if not nickname_locked:
                subscription.nickname = user_info.get('nickname')
        if user_info.get('avatar_url'):
            subscription.avatar_url = user_info.get('avatar_url')
        if user_info.get('follower_count') is not None:
            subscription.follower_count = user_info.get('follower_count')
        if user_info.get('video_count') is not None:
            subscription.video_count = user_info.get('video_count')
        if user_info.get('signature') is not None:
            subscription.signature = user_info.get('signature')
        if user_info.get('like_count') is not None:
            subscription.like_count = user_info.get('like_count')
        if user_info.get('following_count') is not None:
            subscription.following_count = user_info.get('following_count')
    
    def get_browser_page_key(self, user_id: str) -> str:
        """获取浏览器页面键名（用于标签页管理）
        
        Args:
            user_id: 用户ID
            
        Returns:
            页面键名
        """
        return f"{self.platform_name}:{user_id}"
    
    def should_skip_video(
        self,
        video: Dict[str, Any],
        skip_bilibili_upower: bool = False
    ) -> bool:
        """判断是否跳过视频（可选实现）
        
        Args:
            video: 视频数据
            skip_bilibili_upower: 是否跳过B站充电专属视频
            
        Returns:
            是否跳过
        """
        # 默认实现：B站充电专属视频过滤
        if self.platform_name.startswith('bilibili') and skip_bilibili_upower:
            return video.get('is_charging_arc', False)
        return False
    
    def get_anti_crawl_config(self) -> Dict[str, Any]:
        """获取反爬虫配置（可选实现）
        
        Returns:
            反爬虫配置字典
        """
        return {}
    
    def get_concurrent_limit(self) -> int:
        """获取并发限制数（可选实现）
        
        Returns:
            并发限制数，默认1（串行）
        """
        return 1
