"""
API参数缓存管理器

提供统一的API参数缓存功能，支持抖音/YouTube/B站共用。
采用内存+数据库双层缓存策略：
1. 内存缓存：快速访问
2. 数据库缓存：持久化存储，重启后可恢复
"""

import json
import time
import logging
from datetime import datetime, timezone
from typing import Optional, Dict, Any

from sqlalchemy.orm import Session
from sql.database_postgresql import get_db
from sql.models import ApiParamsCache

logger = logging.getLogger(__name__)


class ApiParamsCacheManager:
    """API参数缓存管理器 - 抖音/YouTube/B站共用"""
    
    # 各平台默认过期时间 （秒）
    DEFAULT_EXPIRE_SECONDS = {
        "douyin": 43200,     # 12小时
        "youtube": 43200,    # 12小时
        "bilibili": 43200,   # 12小时
    }
    
    def __init__(self):
        # 内存缓存: {platform: {"params": dict, "timestamp": float, "expire_seconds": int}}
        self._memory_cache: Dict[str, Dict[str, Any]] = {}
    
    def _get_default_expire(self, platform: str) -> int:
        """获取平台默认过期时间"""
        return self.DEFAULT_EXPIRE_SECONDS.get(platform, 1800)
    
    def _is_cache_valid(self, timestamp: float, expire_seconds: int) -> bool:
        """检查缓存是否有效"""
        return (time.time() - timestamp) < expire_seconds
    
    def get(self, platform: str, db: Optional[Session] = None) -> Optional[Dict[str, Any]]:
        """获取缓存的参数
        
        优先级：内存缓存 > 数据库缓存
        
        Args:
            platform: 平台标识 (douyin/youtube/bilibili)
            db: 数据库会话（可选，如果不传则自动获取）
            
        Returns:
            缓存的参数字典，如果缓存不存在或已过期则返回 None
        """
        # 1. 先查内存缓存
        if platform in self._memory_cache:
            cache = self._memory_cache[platform]
            if self._is_cache_valid(cache["timestamp"], cache["expire_seconds"]):
                logger.debug(f"[{platform}] 命中内存缓存")
                return cache["params"]
            else:
                logger.debug(f"[{platform}] 内存缓存已过期")
        
        # 2. 内存没有或过期，查数据库
        try:
            should_close_db = False
            if db is None:
                db = next(get_db())
                should_close_db = True
            
            try:
                db_cache = db.query(ApiParamsCache).filter(
                    ApiParamsCache.platform == platform
                ).first()
                
                if db_cache:
                    # 检查数据库缓存是否过期
                    # 注意：数据库时间已带时区信息，直接用 astimezone 转换
                    now_utc = datetime.now(timezone.utc)
                    updated_utc = db_cache.updated_at.astimezone(timezone.utc) if db_cache.updated_at.tzinfo else db_cache.updated_at.replace(tzinfo=timezone.utc)
                    cache_age = (now_utc - updated_utc).total_seconds()
                    if cache_age < db_cache.expire_seconds:
                        # 数据库缓存有效，同步到内存
                        params = json.loads(db_cache.params_json)
                        self._memory_cache[platform] = {
                            "params": params,
                            "timestamp": time.time(),  # 使用当前时间作为内存缓存起点
                            "expire_seconds": db_cache.expire_seconds - cache_age  # 剩余有效期
                        }
                        logger.info(f"[{platform}] 从数据库恢复缓存（剩余 {int(db_cache.expire_seconds - cache_age)} 秒）")
                        return params
                    else:
                        logger.debug(f"[{platform}] 数据库缓存已过期（{int(cache_age)}秒 > {db_cache.expire_seconds}秒）")
            finally:
                if should_close_db:
                    db.close()
                    
        except Exception as e:
            logger.warning(f"[{platform}] 读取数据库缓存失败: {e}")
        
        return None
    
    def set(self, platform: str, params: Dict[str, Any], 
            expire_seconds: Optional[int] = None, db: Optional[Session] = None) -> bool:
        """保存参数到缓存
        
        同时更新内存缓存和数据库缓存
        
        Args:
            platform: 平台标识
            params: 要缓存的参数字典
            expire_seconds: 过期时间（秒），不传则使用平台默认值
            db: 数据库会话（可选）
            
        Returns:
            是否保存成功
        """
        if not params:
            return False
        
        if expire_seconds is None:
            expire_seconds = self._get_default_expire(platform)
        
        now = time.time()
        
        # 1. 更新内存缓存
        self._memory_cache[platform] = {
            "params": params,
            "timestamp": now,
            "expire_seconds": expire_seconds
        }
        
        # 2. 更新数据库缓存
        try:
            should_close_db = False
            if db is None:
                db = next(get_db())
                should_close_db = True
            
            try:
                params_json = json.dumps(params, ensure_ascii=False)
                now_dt = datetime.now(timezone.utc)
                
                db_cache = db.query(ApiParamsCache).filter(
                    ApiParamsCache.platform == platform
                ).first()
                
                if db_cache:
                    # 更新现有记录
                    db_cache.params_json = params_json
                    db_cache.expire_seconds = expire_seconds
                    db_cache.updated_at = now_dt
                else:
                    # 创建新记录
                    db_cache = ApiParamsCache(
                        platform=platform,
                        params_json=params_json,
                        expire_seconds=expire_seconds,
                        updated_at=now_dt,
                        created_at=now_dt
                    )
                    db.add(db_cache)
                
                db.commit()
                logger.info(f"[{platform}] 参数已缓存到数据库（有效期 {expire_seconds} 秒）")
                return True
                
            finally:
                if should_close_db:
                    db.close()
                    
        except Exception as e:
            logger.error(f"[{platform}] 保存数据库缓存失败: {e}")
            # 内存缓存已更新，数据库失败不影响使用
            return True
    
    def invalidate(self, platform: str, db: Optional[Session] = None) -> bool:
        """使缓存失效
        
        Args:
            platform: 平台标识
            db: 数据库会话（可选）
            
        Returns:
            是否成功
        """
        # 1. 清除内存缓存
        if platform in self._memory_cache:
            del self._memory_cache[platform]
        
        # 2. 删除数据库缓存
        try:
            should_close_db = False
            if db is None:
                db = next(get_db())
                should_close_db = True
            
            try:
                db.query(ApiParamsCache).filter(
                    ApiParamsCache.platform == platform
                ).delete()
                db.commit()
                logger.info(f"[{platform}] 缓存已清除")
                return True
            finally:
                if should_close_db:
                    db.close()
                    
        except Exception as e:
            logger.error(f"[{platform}] 清除数据库缓存失败: {e}")
            return False
    
    def get_cache_info(self, platform: str) -> Dict[str, Any]:
        """获取缓存信息（用于调试）"""
        info = {
            "platform": platform,
            "memory_cached": False,
            "db_cached": False,
            "valid": False,
            "remaining_seconds": 0
        }
        
        if platform in self._memory_cache:
            cache = self._memory_cache[platform]
            info["memory_cached"] = True
            remaining = cache["expire_seconds"] - (time.time() - cache["timestamp"])
            if remaining > 0:
                info["valid"] = True
                info["remaining_seconds"] = int(remaining)
        
        return info


# 全局单例
api_params_cache = ApiParamsCacheManager()
