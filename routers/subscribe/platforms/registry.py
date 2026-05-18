"""
平台适配器注册表

管理所有平台适配器的注册和获取。
"""
from typing import Dict, Optional, List
from .base import PlatformAdapter


class PlatformRegistry:
    """平台适配器注册表
    
    单例模式，管理所有平台适配器的注册和获取。
    """
    _instance: Optional['PlatformRegistry'] = None
    _adapters: Dict[str, PlatformAdapter] = {}
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
    
    def register(self, adapter: PlatformAdapter) -> None:
        """注册平台适配器
        
        Args:
            adapter: 平台适配器实例
        """
        platform_name = adapter.platform_name
        if platform_name in self._adapters:
            raise ValueError(f"平台适配器 '{platform_name}' 已注册")
        self._adapters[platform_name] = adapter
    
    def get_adapter(self, platform_name: str) -> Optional[PlatformAdapter]:
        """获取平台适配器
        
        Args:
            platform_name: 平台名称
            
        Returns:
            平台适配器实例，如果不存在返回 None
        """
        return self._adapters.get(platform_name)
    
    def has_adapter(self, platform_name: str) -> bool:
        """检查是否已注册平台适配器
        
        Args:
            platform_name: 平台名称
            
        Returns:
            是否已注册
        """
        return platform_name in self._adapters
    
    def list_platforms(self) -> List[str]:
        """列出所有已注册的平台
        
        Returns:
            平台名称列表
        """
        return list(self._adapters.keys())
    
    def unregister(self, platform_name: str) -> None:
        """注销平台适配器
        
        Args:
            platform_name: 平台名称
        """
        if platform_name in self._adapters:
            del self._adapters[platform_name]


# 全局注册表实例
registry = PlatformRegistry()
