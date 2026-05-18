from abc import ABC, abstractmethod
from typing import Dict, Optional, Any

class BaseAdapter(ABC):
    """
    直播平台适配器基类
    定义所有平台必须实现的标准接口
    """
    
    @property
    @abstractmethod
    def platform_name(self) -> str:
        """平台标识 (如 douyin)"""
        pass
        
    @abstractmethod
    def is_match(self, url: str) -> bool:
        """检查此URL是否属于当前平台"""
        pass

    @abstractmethod
    async def get_room_info(self, url: str, **kwargs) -> Dict[str, Any]:
        """
        获取标准化的直播间信息
        
        Args:
            url: 直播间地址
            **kwargs: 其他可选参数 (如 cookies, proxy 等)
        
        Returns:
            {
                "anchor_name": str,      # 主播名称
                "room_id": str,          # 房间ID
                "avatar_url": str|None,  # 头像URL
                "is_live": bool,         # 是否开播
                "raw_data": dict         # 原始数据(用于由后续流程透传)
            }
        
        Raises:
            Exception: 获取失败或解析错误
        """
        pass

    @abstractmethod
    async def get_stream_url(self, url: str, quality: str, **kwargs) -> Dict[str, Any]:
        """
        获取录制流地址
        
        Args:
            url: 直播间地址
            quality: 画质名称 (原画/蓝光/超清/高清)
            **kwargs: 其他可选参数 (如 cookies, proxy 等)
            
        Returns:
            {
                "url": str,           # 真实的流地址
                "format": str,        # 格式 (flv/m3u8)
                "is_live": bool,      # 是否开播
                "anchor_name": str    # (可选) 再次确认的主播名
            }
        """
        pass
