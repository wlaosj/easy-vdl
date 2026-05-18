"""
平台登录相关路由
"""
import asyncio
import os
from typing import Optional
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from routers.auth import require_license_api, get_current_user
from routers.douyin import douyin_api
from routers.youtube import youtube_api
from routers.unified_browser_manager import unified_browser
from sql.models import User
from .common import logger
from .utils import _force_delete_directory

router = APIRouter()

SUPPORTED_HEARTBEAT_PLATFORMS = {"douyin", "youtube", "bilibili", "xiaohongshu"}


class BrowserHeartbeatRequest(BaseModel):
    platform: Optional[str] = None
    source: Optional[str] = "vnc_login_modal"


@router.post("/douyin/login")
@require_license_api
async def init_douyin_login():
    """初始化抖音登录"""
    try:
        return await douyin_api.login()
    except Exception as e:
        logger.error(f"初始化登录失败: {str(e)}")
        raise HTTPException(status_code=500, detail="初始化登录失败") 


@router.post("/youtube/login")
@require_license_api
async def init_youtube_login():
    """初始化YouTube登录"""
    try:
        # 调用youtube_api的login方法，它会处理浏览器的初始化和页面创建
        result = await youtube_api.login()
        
        return {"message": "已打开YouTube登录页面"}
            
    except Exception as e:
        logger.error(f"初始化YouTube登录失败: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/youtube/close")
@require_license_api
async def close_youtube_browser():
    """关闭YouTube浏览器"""
    try:
        await youtube_api.close_browser()
        return {"message": "YouTube浏览器已关闭"}
    except Exception as e:
        logger.error(f"关闭YouTube浏览器失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"关闭YouTube浏览器失败: {str(e)}")


@router.post("/browser/heartbeat")
@require_license_api
async def browser_heartbeat(payload: BrowserHeartbeatRequest):
    """VNC登录期间心跳保活浏览器"""
    try:
        if payload.platform and payload.platform not in SUPPORTED_HEARTBEAT_PLATFORMS:
            raise HTTPException(status_code=400, detail="不支持的平台")

        source = payload.source or "vnc_login_modal"
        if payload.platform:
            source = f"{source}:{payload.platform}"

        kept_alive = await unified_browser.touch_activity(source=source)
        if not kept_alive:
            return {"ok": True, "kept_alive": False, "message": "browser_not_running"}
        return {"ok": True, "kept_alive": True}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"浏览器心跳失败: {str(e)}")
        raise HTTPException(status_code=500, detail="浏览器心跳失败")


@router.post("/reset-browser")
@require_license_api
async def reset_browser(current_user: User = Depends(get_current_user)):
    """重置所有浏览器文件"""
    try:
        
        # 关闭所有浏览器实例
        try:
            await douyin_api.close_browser()
        except Exception as e:
            logger.warning(f"关闭抖音浏览器失败: {str(e)}")
            
        try:
            await youtube_api.close_browser()
        except Exception as e:
            logger.warning(f"关闭YouTube浏览器失败: {str(e)}")
        
        try:
            from routers.bilibili import bilibili_api
            await bilibili_api.close_browser()
        except Exception as e:
            logger.warning(f"关闭B站浏览器失败: {str(e)}")
        
        # 等待一段时间确保浏览器完全关闭
        await asyncio.sleep(2)
        
        # 删除整个chrome目录，使用改进的删除逻辑
        chrome_dir = "/app/database/chrome"
        if os.path.exists(chrome_dir):
            try:
                # 使用改进的删除函数
                await _force_delete_directory(chrome_dir)
                logger.info(f"已删除整个浏览器目录: {chrome_dir}")
            except Exception as e:
                logger.error(f"删除浏览器目录失败: {str(e)}")
                raise Exception(f"删除浏览器目录失败: {str(e)}")
        
        # 重新创建chrome目录结构（使用统一浏览器目录）
        try:
            os.makedirs("/app/database/chrome/unified", exist_ok=True)
            os.makedirs("/app/database/chrome/tmp", exist_ok=True)
            logger.info("已重新创建浏览器目录结构（unified，DYD使用headless模式无需持久化）")
        except Exception as e:
            logger.error(f"创建浏览器目录结构失败: {str(e)}")
            raise Exception(f"创建浏览器目录结构失败: {str(e)}")
        
        return {"message": "浏览器已重置"}
        
    except Exception as e:
        logger.error(f"重置浏览器失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"重置浏览器失败: {str(e)}")
