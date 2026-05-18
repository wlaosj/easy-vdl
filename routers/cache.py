"""
缓存管理路由
提供API参数缓存的清理等管理功能
"""

import logging
from fastapi import APIRouter, HTTPException, Depends
from typing import Dict, Any

from routers.api_params_cache import api_params_cache
from routers.auth import get_current_user
from sql.models import User

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/cache", tags=["cache"])


@router.post("/clear")
async def clear_cache(current_user: User = Depends(get_current_user)) -> Dict[str, Any]:
    """清理所有平台的API参数缓存
    
    Returns:
        包含清理结果的字典
    """
    try:
        platforms = ["douyin", "youtube", "bilibili"]
        cleared_platforms = []
        failed_platforms = []
        
        for platform in platforms:
            try:
                success = api_params_cache.invalidate(platform)
                if success:
                    cleared_platforms.append(platform)
                    logger.info(f"已清理 {platform} 平台的API参数缓存")
                else:
                    failed_platforms.append(platform)
                    logger.warning(f"清理 {platform} 平台的API参数缓存失败")
            except Exception as e:
                failed_platforms.append(platform)
                logger.error(f"清理 {platform} 平台的API参数缓存时发生异常: {e}")
        
        if failed_platforms:
            message = f"已清理 {len(cleared_platforms)} 个平台的缓存，{len(failed_platforms)} 个平台清理失败"
            logger.warning(message)
        else:
            message = f"已成功清理所有 {len(cleared_platforms)} 个平台的API参数缓存"
            logger.info(message)
        
        return {
            "success": len(failed_platforms) == 0,
            "message": message,
            "cleared_platforms": cleared_platforms,
            "failed_platforms": failed_platforms
        }
        
    except Exception as e:
        logger.error(f"清理缓存失败: {e}")
        raise HTTPException(status_code=500, detail=f"清理缓存失败: {str(e)}")


@router.get("/status")
async def get_cache_status(current_user: User = Depends(get_current_user)) -> Dict[str, Any]:
    """获取所有平台的缓存状态
    
    Returns:
        包含各平台缓存状态的字典
    """
    try:
        platforms = ["douyin", "youtube", "bilibili"]
        cache_status = {}
        
        for platform in platforms:
            cache_status[platform] = api_params_cache.get_cache_info(platform)
        
        return {
            "success": True,
            "platforms": cache_status
        }
        
    except Exception as e:
        logger.error(f"获取缓存状态失败: {e}")
        raise HTTPException(status_code=500, detail=f"获取缓存状态失败: {str(e)}")
