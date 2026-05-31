import os
import asyncio
import logging
from pathlib import Path
from typing import Optional, Dict, Any
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session
from datetime import datetime, timezone, timedelta
import json

from sql import models
from sql.database_postgresql import get_db
from routers.youtube import youtube_api
from routers.bilibili import bilibili_api
from routers.xhsapi import xhs_api
from routers.auth import get_current_user, require_license_api
from routers.instagram import _clear_risk_failure, _encrypt_password
from sql.models import User

# 配置日志
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# 创建APIRouter实例
router = APIRouter(prefix="/api/cookie", tags=["cookie"])

# Cookie文件路径配置
COOKIE_PATHS = {
    "youtube": "/app/database/cookie/youtube_cookie.txt",
    "bilibili": "/app/database/cookie/bilibili_cookie.txt",
    "tiktok": "/app/database/cookie/tiktok_cookie.txt",
    "netease": "/app/database/cookie/netease_cookie.txt",
    "xiaohongshu": "/app/database/cookie/xiaohongshu_cookie.txt",
    "x": "/app/database/cookie/x.txt",
    "kuaishou": "/app/database/cookie/kuaishou_cookie.txt"
}

CREDENTIALS_FILE = "/app/database/instagram/credentials.json"
INSTAGRAM_SESSION_CACHE_PATH = "/app/database/instagram/session.json"

# 请求体模型
class CookieSaveRequest(BaseModel):
    cookie_content: str

class InstagramCredentialsRequest(BaseModel):
    username: str
    password: str

class AutoUpdateRequest(BaseModel):
    enabled: bool
    interval_minutes: int = 10

# 全局任务引用，用于管理自动更新任务
_auto_update_task = None

# 缓存配置，避免频繁查询数据库
_cached_config = {}

def _get_cached_config(platform: str) -> Dict[str, Any]:
    """获取缓存的配置，如果缓存中没有则从数据库加载"""
    if platform not in _cached_config:
        _cached_config[platform] = {
            "enabled": False,
            "interval_minutes": 10,
            "last_update": None,
            "next_update": None
        }
    return _cached_config[platform]

def _load_config_from_db(db: Session, platform: str) -> Dict[str, Any]:
    """从数据库加载配置（只读取，不保存）"""
    try:
        config = db.query(models.CookieConfig).filter(
            models.CookieConfig.platform == platform
        ).first()
        
        if config:
            # 只更新缓存，不触发保存
            _cached_config[platform] = {
                "enabled": config.enabled.lower() == "true",
                "interval_minutes": config.interval_minutes,
                "last_update": config.last_update.isoformat() if config.last_update else None,
                "next_update": config.next_update.isoformat() if config.next_update else None
            }
        else:
            # 如果数据库中没有配置，静默创建默认配置（不记录日志）
            default_config = models.CookieConfig(
                platform=platform,
                enabled="false",
                interval_minutes=10,
                last_update=None,
                next_update=None
            )
            db.add(default_config)
            db.commit()
            
            _cached_config[platform] = {
                "enabled": False,
                "interval_minutes": 10,
                "last_update": None,
                "next_update": None
            }
        
        return _cached_config[platform]
    except Exception as e:
        logger.error(f"从数据库加载{platform}配置失败: {str(e)}")
        # 返回默认配置
        return {
            "enabled": False,
            "interval_minutes": 10,
            "last_update": None,
            "next_update": None
        }

def _save_config_to_db(db: Session, platform: str, config: Dict[str, Any]):
    """保存配置到数据库"""
    try:
        db_config = db.query(models.CookieConfig).filter(
            models.CookieConfig.platform == platform
        ).first()
        
        if db_config:
            # 更新现有配置，只更新提供的字段
            if "enabled" in config:
                db_config.enabled = str(config["enabled"]).lower()
            if "interval_minutes" in config:
                db_config.interval_minutes = config["interval_minutes"]
            if "last_update" in config:
                db_config.last_update = datetime.fromisoformat(config["last_update"]) if config["last_update"] else None
            if "next_update" in config:
                db_config.next_update = datetime.fromisoformat(config["next_update"]) if config["next_update"] else None
            db_config.updated_at = datetime.now(tz=timezone.utc)
        else:
            # 创建新配置，使用默认值填充缺失的字段
            db_config = models.CookieConfig(
                platform=platform,
                enabled=str(config.get("enabled", False)).lower(),
                interval_minutes=config.get("interval_minutes", 10),
                last_update=datetime.fromisoformat(config["last_update"]) if config.get("last_update") else None,
                next_update=datetime.fromisoformat(config["next_update"]) if config.get("next_update") else None
            )
            db.add(db_config)
        
        db.commit()
        logger.debug(f"{platform}配置已保存到数据库")
    except Exception as e:
        logger.error(f"保存{platform}配置到数据库失败: {str(e)}")
        db.rollback()

def _update_config_cache(platform: str, config: Dict[str, Any]):
    """更新配置缓存"""
    _cached_config[platform] = config.copy()


def _clear_instagram_session_cache():
    """清除 Instagram 会话缓存，确保后续重新登录"""
    try:
        if os.path.exists(INSTAGRAM_SESSION_CACHE_PATH):
            os.remove(INSTAGRAM_SESSION_CACHE_PATH)
            logger.info(f"Instagram session缓存已删除: {INSTAGRAM_SESSION_CACHE_PATH}")
    except Exception as e:
        logger.warning(f"清除Instagram session缓存失败: {str(e)}")
    # 同时也清空 client 缓存，下次请求强制重新登录
    try:
        from routers.instagram import _clear_client_cache
        _clear_client_cache()
    except Exception:
        pass

def _get_auto_update_task_status():
    """获取自动更新任务状态"""
    global _auto_update_task
    if _auto_update_task is None:
        return "not_started"
    elif _auto_update_task.done():
        if _auto_update_task.cancelled():
            return "cancelled"
        else:
            return "completed"
    else:
        return "running"

def _cleanup_auto_update_task():
    """清理自动更新任务引用"""
    global _auto_update_task
    if _auto_update_task and _auto_update_task.done():
        _auto_update_task = None

@router.get("/status")
def get_cookie_status(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """获取所有cookie的状态信息"""
    try:
        status = {}
        
        for platform, file_path in COOKIE_PATHS.items():
            cookie_info = {
                "exists": os.path.exists(file_path),
                "size": 0,
                "last_modified": None,
                "auto_update_enabled": False,
                "last_update": None,
                "next_update": None
            }
            
            if cookie_info["exists"]:
                # 获取文件大小
                try:
                    cookie_info["size"] = os.path.getsize(file_path)
                except:
                    cookie_info["size"] = 0
                
                # 获取最后修改时间
                try:
                    mtime = os.path.getmtime(file_path)
                    cookie_info["last_modified"] = datetime.fromtimestamp(mtime, tz=timezone.utc).isoformat()
                except:
                    cookie_info["last_modified"] = None
            
            # 从数据库加载配置
            db_config = _load_config_from_db(db, platform)
            cookie_info["auto_update_enabled"] = db_config["enabled"]
            cookie_info["interval_minutes"] = db_config["interval_minutes"]
            cookie_info["last_update"] = db_config["last_update"]
            cookie_info["next_update"] = db_config["next_update"]
            
            # 添加任务状态信息
            if platform == "youtube":
                cookie_info["task_status"] = _get_auto_update_task_status()
            elif platform == "bilibili" or platform == "xiaohongshu":
                # 任务状态通过配置来判断
                cookie_info["task_status"] = "running" if db_config["enabled"] else "not_started"
            elif platform == "tiktok" or platform == "instagram" or platform == "netease" or platform == "x" or platform == "kuaishou":
                # These platforms do not support automatic update, task status is always not_started
                cookie_info["task_status"] = "not_started"
            
            status[platform] = cookie_info

        # Instagram 改用账号密码方式，从 credentials.json 读取状态
        instagram_configured = False
        instagram_username = ""
        if os.path.exists(CREDENTIALS_FILE):
            try:
                creds = json.loads(Path(CREDENTIALS_FILE).read_text(encoding="utf-8"))
                instagram_username = (creds.get("username") or "").strip()
                instagram_configured = bool(instagram_username and creds.get("password"))
            except Exception:
                pass
        status["instagram"] = {
            "exists": instagram_configured,
            "configured": instagram_configured,
            "username": instagram_username,
            "size": 0,
            "last_modified": None
        }

        return status
    except Exception as e:
        logger.error(f"获取cookie状态失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"获取cookie状态失败: {str(e)}")

@router.get("/content/youtube")
def get_youtube_cookie_content(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """获取YouTube cookie内容"""
    file_path = COOKIE_PATHS["youtube"]
    
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="YouTube cookie文件不存在")
    
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        return {
            "platform": "youtube",
            "content": content,
            "size": len(content),
            "last_modified": datetime.fromtimestamp(
                os.path.getmtime(file_path), 
                tz=timezone.utc
            ).isoformat()
        }
    except Exception as e:
        logger.error(f"读取YouTube cookie内容失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"读取cookie内容失败: {str(e)}")

@router.get("/content/bilibili")
def get_bilibili_cookie_content(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """获取B站 cookie内容"""
    file_path = COOKIE_PATHS["bilibili"]
    
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="B站 cookie文件不存在")
    
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        return {
            "platform": "bilibili",
            "content": content,
            "size": len(content),
            "last_modified": datetime.fromtimestamp(
                os.path.getmtime(file_path), 
                tz=timezone.utc
            ).isoformat()
        }
    except Exception as e:
        logger.error(f"读取B站 cookie内容失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"读取cookie内容失败: {str(e)}")

@router.get("/content/tiktok")
def get_tiktok_cookie_content(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """获取TikTok cookie内容"""
    file_path = COOKIE_PATHS["tiktok"]
    
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="TikTok cookie文件不存在")
    
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        return {
            "platform": "tiktok",
            "content": content,
            "size": len(content),
            "last_modified": datetime.fromtimestamp(
                os.path.getmtime(file_path), 
                tz=timezone.utc
            ).isoformat()
        }
    except Exception as e:
        logger.error(f"读取TikTok cookie内容失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"读取cookie内容失败: {str(e)}")

@router.get("/content/instagram")
def get_instagram_cookie_content(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """获取Instagram账号配置状态（不返回密码）"""
    configured = False
    username = ""
    if os.path.exists(CREDENTIALS_FILE):
        try:
            creds = json.loads(Path(CREDENTIALS_FILE).read_text(encoding="utf-8"))
            username = (creds.get("username") or "").strip()
            configured = bool(username and creds.get("password"))
        except Exception:
            pass

    return {
        "platform": "instagram",
        "configured": configured,
        "username": username,
        "note": "Instagram 已改用账号密码登录，无需设置 cookie"
    }

@router.get("/content/netease")
def get_netease_cookie_content(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """获取网易云音乐 cookie内容"""
    file_path = COOKIE_PATHS["netease"]
    
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="网易云音乐 cookie文件不存在")
    
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        return {
            "platform": "netease",
            "content": content,
            "size": len(content),
            "last_modified": datetime.fromtimestamp(
                os.path.getmtime(file_path), 
                tz=timezone.utc
            ).isoformat()
        }
    except Exception as e:
        logger.error(f"读取网易云音乐 cookie内容失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"读取cookie内容失败: {str(e)}")

@router.get("/content/xiaohongshu")
def get_xiaohongshu_cookie_content(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """获取小红书 cookie内容"""
    file_path = COOKIE_PATHS["xiaohongshu"]
    
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="小红书 cookie文件不存在")
    
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        return {
            "platform": "xiaohongshu",
            "content": content,
            "size": len(content),
            "last_modified": datetime.fromtimestamp(
                os.path.getmtime(file_path), 
                tz=timezone.utc
            ).isoformat()
        }
    except Exception as e:
        logger.error(f"读取小红书 cookie内容失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"读取cookie内容失败: {str(e)}")

@router.post("/update/youtube")
@require_license_api
async def update_youtube_cookie(background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    """手动更新YouTube cookie"""
    try:
        # 在后台任务中更新cookie
        background_tasks.add_task(_update_youtube_cookie_task)
        
        return {
            "message": "YouTube cookie更新任务已启动",
            "status": "updating"
        }
    except Exception as e:
        logger.error(f"启动YouTube cookie更新任务失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"启动更新任务失败: {str(e)}")

@router.post("/update/bilibili")
@require_license_api
async def update_bilibili_cookie(background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    """手动更新B站 cookie"""
    try:
        # 在后台任务中更新cookie
        background_tasks.add_task(_update_bilibili_cookie_task)
        
        return {
            "message": "B站 cookie更新任务已启动",
            "status": "updating"
        }
    except Exception as e:
        logger.error(f"启动B站 cookie更新任务失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"启动更新任务失败: {str(e)}")

@router.post("/update/xiaohongshu")
@require_license_api
async def update_xiaohongshu_cookie(background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    """手动更新小红书 cookie"""
    try:
        # 在后台任务中更新cookie
        background_tasks.add_task(_update_xiaohongshu_cookie_task)
        
        return {
            "message": "小红书 cookie更新任务已启动",
            "status": "updating"
        }
    except Exception as e:
        logger.error(f"启动小红书 cookie更新任务失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"启动更新任务失败: {str(e)}")

async def _update_youtube_cookie_task():
    """后台更新YouTube cookie的任务"""
    try:
        # 直接导出 Netscape 格式（保留真实 domain/path/secure/expires），供 yt-dlp 认证使用
        netscape_cookie_content = await youtube_api.export_cookies_netscape(force_refresh=True)
        
        # 保存到文件
        file_path = COOKIE_PATHS["youtube"]
        os.makedirs(os.path.dirname(file_path), exist_ok=True)

        if not netscape_cookie_content:
            logger.debug("YouTube cookie导出为空，跳过更新")
            return

        # 原子写入，避免并发读到半截导致 “Netscape format cookies file” 错误
        tmp_path = f"{file_path}.tmp"
        with open(tmp_path, 'w', encoding='utf-8') as f:
            f.write(netscape_cookie_content)
        os.replace(tmp_path, file_path)
        
        # 更新配置缓存
        now = datetime.now(tz=timezone.utc)
        _cached_config["youtube"]["last_update"] = now.isoformat()
        
        if _cached_config["youtube"]["enabled"]:
            interval = timedelta(minutes=_cached_config["youtube"]["interval_minutes"])
            _cached_config["youtube"]["next_update"] = (now + interval).isoformat()
        
        # 异步保存到数据库
        asyncio.create_task(_save_config_async("youtube", {
            "last_update": _cached_config["youtube"]["last_update"],
            "next_update": _cached_config["youtube"]["next_update"]
        }))
        
        logger.debug("YouTube cookie已更新")
        
    except Exception as e:
        logger.error(f"YouTube cookie更新失败: {str(e)}")

async def _update_bilibili_cookie_task():
    """后台更新B站 cookie的任务"""
    try:
        # 直接导出 Netscape 格式（保留真实 domain/path/secure/expires），供 yt-dlp 认证使用
        netscape_cookie_content = await bilibili_api.export_cookies_netscape(force_refresh=True)
        
        # 保存到文件
        file_path = COOKIE_PATHS["bilibili"]
        os.makedirs(os.path.dirname(file_path), exist_ok=True)

        if not netscape_cookie_content:
            logger.debug("B站 cookie导出为空，跳过更新")
            return

        # 原子写入，避免并发读到半截导致 “Netscape format cookies file” 错误
        tmp_path = f"{file_path}.tmp"
        with open(tmp_path, 'w', encoding='utf-8') as f:
            f.write(netscape_cookie_content)
        os.replace(tmp_path, file_path)
        
        # 更新配置缓存
        now = datetime.now(tz=timezone.utc)
        _cached_config["bilibili"]["last_update"] = now.isoformat()
        
        if _cached_config["bilibili"]["enabled"]:
            interval = timedelta(minutes=_cached_config["bilibili"]["interval_minutes"])
            _cached_config["bilibili"]["next_update"] = (now + interval).isoformat()
        
        # 异步保存到数据库
        asyncio.create_task(_save_config_async("bilibili", {
            "last_update": _cached_config["bilibili"]["last_update"],
            "next_update": _cached_config["bilibili"]["next_update"]
        }))
        
        logger.debug("B站 cookie已更新")
        
    except Exception as e:
        logger.error(f"B站 cookie更新失败: {str(e)}")

async def _update_xiaohongshu_cookie_task():
    """后台更新小红书 cookie的任务"""
    try:
        # 导出 Netscape 格式
        netscape_cookie_content = await xhs_api.export_cookies_netscape(force_refresh=True)
        
        # 保存到文件
        file_path = COOKIE_PATHS["xiaohongshu"]
        os.makedirs(os.path.dirname(file_path), exist_ok=True)

        if not netscape_cookie_content:
            logger.debug("小红书 cookie导出为空，跳过更新")
            return

        # 原子写入
        tmp_path = f"{file_path}.tmp"
        with open(tmp_path, 'w', encoding='utf-8') as f:
            f.write(netscape_cookie_content)
        os.replace(tmp_path, file_path)
        
        # 更新配置缓存
        now = datetime.now(tz=timezone.utc)
        _cached_config["xiaohongshu"]["last_update"] = now.isoformat()
        
        if _cached_config["xiaohongshu"]["enabled"]:
            interval = timedelta(minutes=_cached_config["xiaohongshu"]["interval_minutes"])
            _cached_config["xiaohongshu"]["next_update"] = (now + interval).isoformat()
        
        # 异步保存到数据库
        asyncio.create_task(_save_config_async("xiaohongshu", {
            "last_update": _cached_config["xiaohongshu"]["last_update"],
            "next_update": _cached_config["xiaohongshu"]["next_update"]
        }))
        
        logger.debug("小红书 cookie已更新")
        
    except Exception as e:
        logger.error(f"小红书 cookie更新失败: {str(e)}")

async def _save_config_async(platform: str, config_updates: Dict[str, Any]):
    """异步保存配置到数据库"""
    try:
        from sql.database_postgresql import SessionLocal
        
        db = SessionLocal()
        try:
            _save_config_to_db(db, platform, config_updates)
        finally:
            try:
                db.rollback()
            except Exception:
                pass
            db.close()
    except Exception as e:
        logger.error(f"异步保存{platform}配置失败: {str(e)}")

def _convert_to_netscape_format(http_cookies: str) -> str:
    """将HTTP cookie格式转换为Netscape格式
    
    HTTP格式: name1=value1; name2=value2; name3=value3
    Netscape格式: domain\tFLAG\tpath\tsecure\texpiry\tname\tvalue
    """
    try:
        # 解析HTTP cookie字符串
        cookies = []
        for cookie in http_cookies.split(';'):
            cookie = cookie.strip()
            if '=' in cookie:
                name, value = cookie.split('=', 1)
                name = name.strip()
                value = value.strip()
                
                # 跳过空值
                if not name or not value:
                    continue
                
                # 构建Netscape格式的cookie行
                # 格式: .youtube.com\tTRUE\t/\tTRUE\t1735689600\tname\tvalue
                
                # 检查是否是安全cookie
                is_secure = name.startswith('__Secure-') or name.startswith('__Host-')
                
                # 对于某些特殊的cookie，设置为会话cookie（过期时间为0）
                # 这些cookie通常不需要过期时间，浏览器关闭后自动失效
                if name in ['YSC', 'wide', 'PREF']:
                    expiry = 0
                elif name in ['VISITOR_INFO1_LIVE', 'VISITOR_PRIVACY_METADATA']:
                    # 访客信息相关的cookie，设置较短的过期时间（7天）
                    expiry = int((datetime.now() + timedelta(days=7)).timestamp())
                elif name.startswith('__Secure-'):
                    # 安全cookie设置较长的过期时间（1年）
                    expiry = int((datetime.now() + timedelta(days=365)).timestamp())
                else:
                    # 其他cookie设置中等过期时间（6个月）
                    expiry = int((datetime.now() + timedelta(days=180)).timestamp())
                
                # 使用.youtube.com作为域名（更通用的格式）
                # FLAG设置为TRUE（表示所有子域名都可以访问）
                # 路径设置为/（根路径）
                cookie_line = f".youtube.com\tTRUE\t/\t{str(is_secure).upper()}\t{expiry}\t{name}\t{value}"
                cookies.append(cookie_line)
        
        if not cookies:
            logger.warning("没有有效的cookie需要转换")
            return ""
        
        # 添加Netscape cookie文件头 - 使用与yt-dlp生成的格式相同的格式
        header = "# Netscape HTTP Cookie File\n# This file is generated by yt-dlp.  Do not edit.\n\n"
        
        return header + '\n'.join(cookies)
        
    except Exception as e:
        logger.error(f"转换cookie格式失败: {str(e)}")
        # 如果转换失败，返回原始格式（虽然可能不兼容）
        return http_cookies

def _convert_bilibili_to_netscape_format(http_cookies: str) -> str:
    """将B站HTTP cookie格式转换为Netscape格式
    
    HTTP格式: name1=value1; name2=value2; name3=value3
    Netscape格式: domain\tFLAG\tpath\tsecure\texpiry\tname\tvalue
    """
    try:
        # 解析HTTP cookie字符串
        cookies = []
        for cookie in http_cookies.split(';'):
            cookie = cookie.strip()
            if '=' in cookie:
                name, value = cookie.split('=', 1)
                name = name.strip()
                value = value.strip()
                
                # 跳过空值
                if not name or not value:
                    continue
                
                # 构建Netscape格式的cookie行
                # 格式: .bilibili.com\tTRUE\t/\tTRUE\t1735689600\tname\tvalue
                
                # 检查是否是安全cookie
                is_secure = name.startswith('__Secure-') or name.startswith('__Host-')
                
                # 对于某些特殊的cookie，设置为会话cookie（过期时间为0）
                # 这些cookie通常不需要过期时间，浏览器关闭后自动失效
                if name in ['buvid3', 'b_nut', 'i-wanna-go-back']:
                    expiry = 0
                elif name in ['SESSDATA', 'bili_jct', 'DedeUserID']:
                    # 登录相关的cookie，设置较长的过期时间（1年）
                    expiry = int((datetime.now() + timedelta(days=365)).timestamp())
                elif name.startswith('__Secure-'):
                    # 安全cookie设置较长的过期时间（1年）
                    expiry = int((datetime.now() + timedelta(days=365)).timestamp())
                else:
                    # 其他cookie设置中等过期时间（6个月）
                    expiry = int((datetime.now() + timedelta(days=180)).timestamp())
                
                # 使用.bilibili.com作为域名（更通用的格式）
                # FLAG设置为TRUE（表示所有子域名都可以访问）
                # 路径设置为/（根路径）
                cookie_line = f".bilibili.com\tTRUE\t/\t{str(is_secure).upper()}\t{expiry}\t{name}\t{value}"
                cookies.append(cookie_line)
        
        if not cookies:
            logger.warning("没有有效的B站cookie需要转换")
            return ""
        
        # 添加Netscape cookie文件头 - 使用与yt-dlp生成的格式相同的格式
        header = "# Netscape HTTP Cookie File\n# This file is generated by yt-dlp.  Do not edit.\n\n"
        
        return header + '\n'.join(cookies)
        
    except Exception as e:
        logger.error(f"转换B站cookie格式失败: {str(e)}")
        # 如果转换失败，返回原始格式（虽然可能不兼容）
        return http_cookies

@router.post("/save/youtube")
def save_youtube_cookie(
    request: CookieSaveRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """手动保存YouTube cookie（用户输入的Netscape格式）"""
    try:
        cookie_content = request.cookie_content
        if not cookie_content.strip():
            raise HTTPException(status_code=400, detail="Cookie内容不能为空")
        
        # 直接保存用户输入的cookie内容（假设已经是正确的Netscape格式）
        file_path = COOKIE_PATHS["youtube"]
        os.makedirs(os.path.dirname(file_path), exist_ok=True)
        
        tmp_path = file_path + ".tmp"
        with open(tmp_path, 'w', encoding='utf-8') as f:
            f.write(cookie_content)
        os.replace(tmp_path, file_path)
        
        # 更新配置缓存
        now = datetime.now(tz=timezone.utc)
        _cached_config["youtube"]["last_update"] = now.isoformat()
        
        # 保存配置到数据库
        _save_config_to_db(db, "youtube", {
            "last_update": now.isoformat()
        })
        
        logger.info(f"YouTube cookie已手动保存，文件大小: {len(cookie_content)} 字符")
        
        return {
            "message": "YouTube cookie已保存",
            "size": len(cookie_content),
            "last_update": now.isoformat()
        }
        
    except Exception as e:
        logger.error(f"保存YouTube cookie失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"保存cookie失败: {str(e)}")

@router.post("/save/bilibili")
def save_bilibili_cookie(
    request: CookieSaveRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """手动保存B站 cookie（用户输入的Netscape格式）"""
    try:
        cookie_content = request.cookie_content
        if not cookie_content.strip():
            raise HTTPException(status_code=400, detail="Cookie内容不能为空")
        
        # 直接保存用户输入的cookie内容（假设已经是正确的Netscape格式）
        file_path = COOKIE_PATHS["bilibili"]
        os.makedirs(os.path.dirname(file_path), exist_ok=True)
        
        tmp_path = file_path + ".tmp"
        with open(tmp_path, 'w', encoding='utf-8') as f:
            f.write(cookie_content)
        os.replace(tmp_path, file_path)
        
        # 更新配置缓存
        now = datetime.now(tz=timezone.utc)
        _cached_config["bilibili"]["last_update"] = now.isoformat()
        
        # 保存配置到数据库
        _save_config_to_db(db, "bilibili", {
            "last_update": now.isoformat()
        })
        
        logger.info(f"B站 cookie已手动保存，文件大小: {len(cookie_content)} 字符")
        
        return {
            "message": "B站 cookie已保存",
            "size": len(cookie_content),
            "last_update": now.isoformat()
        }
        
    except Exception as e:
        logger.error(f"保存B站 cookie失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"保存cookie失败: {str(e)}")

@router.post("/save/tiktok")
def save_tiktok_cookie(
    request: CookieSaveRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """手动保存TikTok cookie（用户输入的Netscape格式）"""
    try:
        cookie_content = request.cookie_content
        if not cookie_content.strip():
            raise HTTPException(status_code=400, detail="Cookie内容不能为空")
        
        # 直接保存用户输入的cookie内容（假设已经是正确的Netscape格式）
        file_path = COOKIE_PATHS["tiktok"]
        os.makedirs(os.path.dirname(file_path), exist_ok=True)
        
        tmp_path = file_path + ".tmp"
        with open(tmp_path, 'w', encoding='utf-8') as f:
            f.write(cookie_content)
        os.replace(tmp_path, file_path)
        
        # 更新配置缓存
        now = datetime.now(tz=timezone.utc)
        if "tiktok" not in _cached_config:
            _cached_config["tiktok"] = {
                "enabled": False,
                "interval_minutes": 10,
                "last_update": None,
                "next_update": None
            }
        _cached_config["tiktok"]["last_update"] = now.isoformat()
        
        # 保存配置到数据库
        _save_config_to_db(db, "tiktok", {
            "last_update": now.isoformat()
        })
        
        logger.info(f"TikTok cookie已手动保存，文件大小: {len(cookie_content)} 字符")
        
        return {
            "message": "TikTok cookie已保存",
            "size": len(cookie_content),
            "last_update": now.isoformat()
        }
        
    except Exception as e:
        logger.error(f"保存TikTok cookie失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"保存cookie失败: {str(e)}")

@router.post("/save/instagram")
def save_instagram_cookie(
    request: InstagramCredentialsRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """保存Instagram账号密码（替代旧的cookie方式，更稳定）"""
    try:
        username = (request.username or "").strip()
        password = request.password or ""
        if not username or not password:
            raise HTTPException(status_code=400, detail="用户名和密码不能为空")

        os.makedirs(os.path.dirname(CREDENTIALS_FILE), exist_ok=True)

        # 加密密码后保存，避免明文泄露
        encrypted = _encrypt_password(password)
        json.dump({"username": username, "password": encrypted},
                  open(CREDENTIALS_FILE, 'w', encoding='utf-8'),
                  ensure_ascii=False)

        _clear_instagram_session_cache()
        _clear_risk_failure()

        now = datetime.now(tz=timezone.utc)
        if "instagram" not in _cached_config:
            _cached_config["instagram"] = {
                "enabled": False,
                "interval_minutes": 10,
                "last_update": None,
                "next_update": None
            }
        _cached_config["instagram"]["last_update"] = now.isoformat()

        _save_config_to_db(db, "instagram", {
            "last_update": now.isoformat()
        })

        logger.info(f"Instagram 账号已保存: {username}")

        return {
            "message": "Instagram 账号密码已保存",
            "username": username,
            "last_update": now.isoformat()
        }

    except Exception as e:
        logger.error(f"保存Instagram账号失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"保存账号失败: {str(e)}")

@router.post("/save/netease")
def save_netease_cookie(
    request: CookieSaveRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """手动保存网易云音乐 cookie（用户输入的Netscape格式）"""
    try:
        cookie_content = request.cookie_content
        if not cookie_content.strip():
            raise HTTPException(status_code=400, detail="Cookie内容不能为空")
        
        # 直接保存用户输入的cookie内容（假设已经是正确的Netscape格式）
        file_path = COOKIE_PATHS["netease"]
        os.makedirs(os.path.dirname(file_path), exist_ok=True)
        
        tmp_path = file_path + ".tmp"
        with open(tmp_path, 'w', encoding='utf-8') as f:
            f.write(cookie_content)
        os.replace(tmp_path, file_path)
        
        # 更新配置缓存
        now = datetime.now(tz=timezone.utc)
        if "netease" not in _cached_config:
            _cached_config["netease"] = {
                "enabled": False,
                "interval_minutes": 10,
                "last_update": None,
                "next_update": None
            }
        _cached_config["netease"]["last_update"] = now.isoformat()
        
        # 保存配置到数据库
        _save_config_to_db(db, "netease", {
            "last_update": now.isoformat()
        })
        
        logger.info(f"网易云音乐 cookie已手动保存，文件大小: {len(cookie_content)} 字符")
        
        return {
            "message": "网易云音乐 cookie已保存",
            "size": len(cookie_content),
            "last_update": now.isoformat()
        }
        
    except Exception as e:
        logger.error(f"保存网易云音乐 cookie失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"保存cookie失败: {str(e)}")

@router.post("/save/x")
def save_x_cookie(
    request: CookieSaveRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """手动保存X cookie（用户输入的Netscape格式）"""
    try:
        cookie_content = request.cookie_content
        if not cookie_content.strip():
            raise HTTPException(status_code=400, detail="Cookie内容不能为空")

        file_path = COOKIE_PATHS["x"]
        os.makedirs(os.path.dirname(file_path), exist_ok=True)

        tmp_path = file_path + ".tmp"
        with open(tmp_path, 'w', encoding='utf-8') as f:
            f.write(cookie_content)
        os.replace(tmp_path, file_path)

        now = datetime.now(tz=timezone.utc)
        if "x" not in _cached_config:
            _cached_config["x"] = {
                "enabled": False,
                "interval_minutes": 10,
                "last_update": None,
                "next_update": None
            }
        _cached_config["x"]["last_update"] = now.isoformat()

        _save_config_to_db(db, "x", {
            "last_update": now.isoformat()
        })

        logger.info(f"X cookie已手动保存，文件大小: {len(cookie_content)} 字符")

        return {
            "message": "X cookie已保存",
            "size": len(cookie_content),
            "last_update": now.isoformat()
        }
    except Exception as e:
        logger.error(f"保存X cookie失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"保存cookie失败: {str(e)}")

@router.post("/save/xiaohongshu")
def save_xiaohongshu_cookie(
    request: CookieSaveRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """手动保存小红书 cookie（用户输入的Netscape格式）"""
    try:
        cookie_content = request.cookie_content
        if not cookie_content.strip():
            raise HTTPException(status_code=400, detail="Cookie内容不能为空")
        
        file_path = COOKIE_PATHS["xiaohongshu"]
        os.makedirs(os.path.dirname(file_path), exist_ok=True)
        
        tmp_path = file_path + ".tmp"
        with open(tmp_path, 'w', encoding='utf-8') as f:
            f.write(cookie_content)
        os.replace(tmp_path, file_path)
        
        # 更新配置缓存
        now = datetime.now(tz=timezone.utc)
        if "xiaohongshu" not in _cached_config:
            _cached_config["xiaohongshu"] = {
                "enabled": False,
                "interval_minutes": 10,
                "last_update": None,
                "next_update": None
            }
        _cached_config["xiaohongshu"]["last_update"] = now.isoformat()
        
        # 保存配置到数据库
        _save_config_to_db(db, "xiaohongshu", {
            "last_update": now.isoformat()
        })
        
        logger.info(f"小红书 cookie已手动保存，文件大小: {len(cookie_content)} 字符")
        
        return {
            "message": "小红书 cookie已保存",
            "size": len(cookie_content),
            "last_update": now.isoformat()
        }
        
    except Exception as e:
        logger.error(f"保存小红书 cookie失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"保存cookie失败: {str(e)}")

@router.get("/content/kuaishou")
def get_kuaishou_cookie_content(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """获取快手 cookie内容"""
    file_path = COOKIE_PATHS["kuaishou"]
    
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="快手 cookie文件不存在")
    
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        return {
            "platform": "kuaishou",
            "content": content,
            "size": len(content),
            "last_modified": datetime.fromtimestamp(
                os.path.getmtime(file_path), 
                tz=timezone.utc
            ).isoformat()
        }
    except Exception as e:
        logger.error(f"读取快手 cookie内容失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"读取cookie内容失败: {str(e)}")

@router.post("/save/kuaishou")
def save_kuaishou_cookie(
    request: CookieSaveRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """手动保存快手 cookie（用户输入的Netscape格式）"""
    try:
        cookie_content = request.cookie_content
        if not cookie_content.strip():
            raise HTTPException(status_code=400, detail="Cookie内容不能为空")
        
        file_path = COOKIE_PATHS["kuaishou"]
        os.makedirs(os.path.dirname(file_path), exist_ok=True)
        
        tmp_path = file_path + ".tmp"
        with open(tmp_path, 'w', encoding='utf-8') as f:
            f.write(cookie_content)
        os.replace(tmp_path, file_path)
        
        # 更新配置缓存
        now = datetime.now(tz=timezone.utc)
        if "kuaishou" not in _cached_config:
            _cached_config["kuaishou"] = {
                "enabled": False,
                "interval_minutes": 10,
                "last_update": None,
                "next_update": None
            }
        _cached_config["kuaishou"]["last_update"] = now.isoformat()
        
        # 保存配置到数据库
        _save_config_to_db(db, "kuaishou", {
            "last_update": now.isoformat()
        })
        
        logger.info(f"快手 cookie已手动保存，文件大小: {len(cookie_content)} 字符")
        
        return {
            "message": "快手 cookie已保存",
            "size": len(cookie_content),
            "last_update": now.isoformat()
        }
        
    except Exception as e:
        logger.error(f"保存快手 cookie失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"保存cookie失败: {str(e)}")

@router.post("/auto-update/youtube")
@require_license_api
async def set_youtube_auto_update(
    request: AutoUpdateRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db)
):
    """设置YouTube cookie自动更新"""
    global _auto_update_task
    
    try:
        enabled = request.enabled
        interval_minutes = request.interval_minutes
        
        if interval_minutes < 1 or interval_minutes > 1440:  # 1分钟到24小时
            raise HTTPException(status_code=400, detail="更新间隔必须在1-1440分钟之间")
        
        # 更新配置缓存
        _cached_config["youtube"]["enabled"] = enabled
        _cached_config["youtube"]["interval_minutes"] = interval_minutes
        
        now = datetime.now(tz=timezone.utc)
        if enabled:
            # 如果启用自动更新，设置下次更新时间
            interval = timedelta(minutes=interval_minutes)
            _cached_config["youtube"]["next_update"] = (now + interval).isoformat()
            
            # 使用BackgroundTasks启动自动更新任务
            if _auto_update_task is None or _auto_update_task.done():
                try:
                    # 使用BackgroundTasks来启动异步任务
                    background_tasks.add_task(_start_youtube_auto_update_safe)
                    logger.info(f"YouTube cookie自动更新任务已启动，间隔: {interval_minutes}分钟")
                except Exception as e:
                    logger.error(f"启动自动更新任务失败: {str(e)}")
        else:
            _cached_config["youtube"]["next_update"] = None
            # 如果禁用自动更新，取消现有任务
            if _auto_update_task and not _auto_update_task.done():
                _auto_update_task.cancel()
                _auto_update_task = None
                logger.info("YouTube cookie自动更新任务已取消")
        
        # 保存配置到数据库
        _save_config_to_db(db, "youtube", {
            "enabled": enabled,
            "interval_minutes": interval_minutes,
            "next_update": _cached_config["youtube"]["next_update"]
        })
        
        return {
            "message": f"YouTube cookie自动更新已{'启用' if enabled else '禁用'}",
            "enabled": enabled,
            "interval_minutes": interval_minutes,
            "next_update": _cached_config["youtube"]["next_update"]
        }
        
    except Exception as e:
        logger.error(f"设置YouTube cookie自动更新失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"设置自动更新失败: {str(e)}")

@router.post("/auto-update/bilibili")
@require_license_api
async def set_bilibili_auto_update(
    request: AutoUpdateRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db)
):
    """设置B站 cookie自动更新"""
    try:
        enabled = request.enabled
        interval_minutes = request.interval_minutes
        
        if interval_minutes < 1 or interval_minutes > 1440:  # 1分钟到24小时
            raise HTTPException(status_code=400, detail="更新间隔必须在1-1440分钟之间")
        
        # 更新配置缓存
        _cached_config["bilibili"]["enabled"] = enabled
        _cached_config["bilibili"]["interval_minutes"] = interval_minutes
        
        now = datetime.now(tz=timezone.utc)
        if enabled:
            # 如果启用自动更新，设置下次更新时间
            interval = timedelta(minutes=interval_minutes)
            _cached_config["bilibili"]["next_update"] = (now + interval).isoformat()
            
            # 使用BackgroundTasks启动自动更新任务
            try:
                # 使用BackgroundTasks来启动异步任务
                background_tasks.add_task(_start_bilibili_auto_update_safe)
                logger.info(f"B站 cookie自动更新任务已启动，间隔: {interval_minutes}分钟")
            except Exception as e:
                logger.error(f"启动B站自动更新任务失败: {str(e)}")
        else:
            _cached_config["bilibili"]["next_update"] = None
            # 如果禁用自动更新，取消现有任务（如果有的话）
            # 注意：B站目前没有全局任务引用，所以这里只是设置配置
        
        # 保存配置到数据库
        _save_config_to_db(db, "bilibili", {
            "enabled": enabled,
            "interval_minutes": interval_minutes,
            "next_update": _cached_config["bilibili"]["next_update"]
        })
        
        return {
            "message": f"B站 cookie自动更新已{'启用' if enabled else '禁用'}",
            "enabled": enabled,
            "interval_minutes": interval_minutes,
            "next_update": _cached_config["bilibili"]["next_update"]
        }
        
    except Exception as e:
        logger.error(f"设置B站 cookie自动更新失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"设置自动更新失败: {str(e)}")

@router.post("/auto-update/xiaohongshu")
@require_license_api
async def set_xiaohongshu_auto_update(
    request: AutoUpdateRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db)
):
    """设置小红书 cookie自动更新"""
    try:
        enabled = request.enabled
        interval_minutes = request.interval_minutes
        
        if interval_minutes < 1 or interval_minutes > 1440:  # 1分钟到24小时
            raise HTTPException(status_code=400, detail="更新间隔必须在1-1440分钟之间")
        
        # 更新配置缓存
        _cached_config["xiaohongshu"]["enabled"] = enabled
        _cached_config["xiaohongshu"]["interval_minutes"] = interval_minutes
        
        now = datetime.now(tz=timezone.utc)
        if enabled:
            # 如果启用自动更新，设置下次更新时间
            interval = timedelta(minutes=interval_minutes)
            _cached_config["xiaohongshu"]["next_update"] = (now + interval).isoformat()
            
            # 使用BackgroundTasks启动自动更新任务
            try:
                # 使用BackgroundTasks来启动异步任务
                background_tasks.add_task(_start_xiaohongshu_auto_update_safe)
                logger.info(f"小红书 cookie自动更新任务已启动，间隔: {interval_minutes}分钟")
            except Exception as e:
                logger.error(f"启动自动更新任务失败: {str(e)}")
        else:
            _cached_config["xiaohongshu"]["next_update"] = None
            # 注意：小红书目前没有全局任务引用，所以这里只是设置配置
        
        # 保存配置到数据库
        _save_config_to_db(db, "xiaohongshu", {
            "enabled": enabled,
            "interval_minutes": interval_minutes,
            "next_update": _cached_config["xiaohongshu"]["next_update"]
        })
        
        return {
            "message": f"小红书 cookie自动更新已{'启用' if enabled else '禁用'}",
            "enabled": enabled,
            "interval_minutes": interval_minutes,
            "next_update": _cached_config["xiaohongshu"]["next_update"]
        }
        
    except Exception as e:
        logger.error(f"设置小红书 cookie自动更新失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"设置自动更新失败: {str(e)}")

async def _start_youtube_auto_update_safe():
    """安全启动YouTube cookie自动更新循环的包装函数"""
    global _auto_update_task
    
    try:
        # 确保在正确的事件循环上下文中运行
        await _start_youtube_auto_update()
    except Exception as e:
        logger.error(f"YouTube cookie自动更新任务异常: {str(e)}")
        # 重置任务引用
        _auto_update_task = None

async def _start_youtube_auto_update():
    """启动YouTube cookie自动更新循环"""
    global _auto_update_task
    
    while _cached_config["youtube"]["enabled"]:
        try:
            # 等待到下次更新时间
            if _cached_config["youtube"]["next_update"]:
                next_update = datetime.fromisoformat(_cached_config["youtube"]["next_update"])
                now = datetime.now(tz=timezone.utc)
                
                if next_update > now:
                    wait_seconds = (next_update - now).total_seconds()
                    await asyncio.sleep(wait_seconds)
            
            # 执行更新
            from routers.license import license_manager
            if not await license_manager.is_active_for("cookie.youtube_auto_update"):
                logger.warning("授权已失效，跳过YouTube Cookie自动更新")
            else:
                await _update_youtube_cookie_task()
            
            # 设置下次更新时间
            if _cached_config["youtube"]["enabled"]:
                now = datetime.now(tz=timezone.utc)
                interval = timedelta(minutes=_cached_config["youtube"]["interval_minutes"])
                _cached_config["youtube"]["next_update"] = (now + interval).isoformat()
                
                # 异步保存到数据库
                asyncio.create_task(_save_config_async("youtube", {
                    "next_update": _cached_config["youtube"]["next_update"]
                }))
                
        except asyncio.CancelledError:
            logger.info("YouTube cookie自动更新任务被取消")
            break
        except Exception as e:
            logger.error(f"YouTube cookie自动更新循环出错: {str(e)}")
            # 出错后等待1分钟再重试
            await asyncio.sleep(60)
    
    # 任务结束，重置引用
    _auto_update_task = None
    logger.info("YouTube cookie自动更新任务已结束")

async def _start_bilibili_auto_update_safe():
    """安全启动B站 cookie自动更新循环的包装函数"""
    try:
        # 确保在正确的事件循环上下文中运行
        await _start_bilibili_auto_update()
    except Exception as e:
        logger.error(f"B站 cookie自动更新任务异常: {str(e)}")

async def _start_bilibili_auto_update():
    """启动B站 cookie自动更新循环"""
    while _cached_config["bilibili"]["enabled"]:
        try:
            # 等待到下次更新时间
            if _cached_config["bilibili"]["next_update"]:
                next_update = datetime.fromisoformat(_cached_config["bilibili"]["next_update"])
                now = datetime.now(tz=timezone.utc)
                
                if next_update > now:
                    wait_seconds = (next_update - now).total_seconds()
                    await asyncio.sleep(wait_seconds)
            
            # 执行更新
            from routers.license import license_manager
            if not await license_manager.is_active_for("cookie.bilibili_auto_update"):
                logger.warning("授权已失效，跳过B站 Cookie自动更新")
            else:
                await _update_bilibili_cookie_task()
            
            # 设置下次更新时间
            if _cached_config["bilibili"]["enabled"]:
                now = datetime.now(tz=timezone.utc)
                interval = timedelta(minutes=_cached_config["bilibili"]["interval_minutes"])
                _cached_config["bilibili"]["next_update"] = (now + interval).isoformat()
                
                # 异步保存到数据库
                asyncio.create_task(_save_config_async("bilibili", {
                    "next_update": _cached_config["bilibili"]["next_update"]
                }))
                
        except asyncio.CancelledError:
            logger.info("B站 cookie自动更新任务被取消")
            break
        except Exception as e:
            logger.error(f"B站 cookie自动更新循环出错: {str(e)}")
            # 出错后等待1分钟再重试
            await asyncio.sleep(60)
    
    logger.info("B站 cookie自动更新任务已结束")

async def _start_xiaohongshu_auto_update_safe():
    """安全启动小红书 cookie自动更新循环的包装函数"""
    try:
        # 确保在正确的事件循环上下文中运行
        await _start_xiaohongshu_auto_update()
    except Exception as e:
        logger.error(f"小红书 cookie自动更新任务异常: {str(e)}")

async def _start_xiaohongshu_auto_update():
    """启动小红书 cookie自动更新循环"""
    while _cached_config["xiaohongshu"]["enabled"]:
        try:
            # 等待到下次更新时间
            if _cached_config["xiaohongshu"]["next_update"]:
                next_update = datetime.fromisoformat(_cached_config["xiaohongshu"]["next_update"])
                now = datetime.now(tz=timezone.utc)
                
                if next_update > now:
                    wait_seconds = (next_update - now).total_seconds()
                    await asyncio.sleep(wait_seconds)
            
            # 执行更新
            from routers.license import license_manager
            if not await license_manager.is_active_for("cookie.xiaohongshu_auto_update"):
                logger.warning("授权已失效，跳过小红书 Cookie自动更新")
            else:
                await _update_xiaohongshu_cookie_task()
            
            # 设置下次更新时间
            if _cached_config["xiaohongshu"]["enabled"]:
                now = datetime.now(tz=timezone.utc)
                interval = timedelta(minutes=_cached_config["xiaohongshu"]["interval_minutes"])
                _cached_config["xiaohongshu"]["next_update"] = (now + interval).isoformat()
                
                # 异步保存到数据库
                asyncio.create_task(_save_config_async("xiaohongshu", {
                    "next_update": _cached_config["xiaohongshu"]["next_update"]
                }))
                
        except asyncio.CancelledError:
            logger.info("小红书 cookie自动更新任务被取消")
            break
        except Exception as e:
            logger.error(f"小红书 cookie自动更新循环出错: {str(e)}")
            # 出错后等待1分钟再重试
            await asyncio.sleep(60)
    
    logger.info("小红书 cookie自动更新任务已结束")

@router.delete("/clear/youtube")
def clear_youtube_cookie(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """清除YouTube cookie"""
    file_path = COOKIE_PATHS["youtube"]
    
    try:
        if os.path.exists(file_path):
            os.remove(file_path)
            logger.info(f"YouTube cookie文件已删除: {file_path}")
        
        # 重置自动更新配置缓存
        _cached_config["youtube"]["last_update"] = None
        _cached_config["youtube"]["next_update"] = None
        
        # 保存配置到数据库
        _save_config_to_db(db, "youtube", {
            "last_update": None,
            "next_update": None
        })
        
        return {
            "message": "YouTube cookie已清除",
            "platform": "youtube"
        }
        
    except Exception as e:
        logger.error(f"清除YouTube cookie失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"清除cookie失败: {str(e)}")

@router.delete("/clear/bilibili")
def clear_bilibili_cookie(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """清除B站 cookie"""
    file_path = COOKIE_PATHS["bilibili"]
    
    try:
        if os.path.exists(file_path):
            os.remove(file_path)
            logger.info(f"B站 cookie文件已删除: {file_path}")
        
        # 重置自动更新配置缓存
        _cached_config["bilibili"]["last_update"] = None
        _cached_config["bilibili"]["next_update"] = None
        
        # 保存配置到数据库
        _save_config_to_db(db, "bilibili", {
            "last_update": None,
            "next_update": None
        })
        
        return {
            "message": "B站 cookie已清除",
            "platform": "bilibili"
        }
        
    except Exception as e:
        logger.error(f"清除B站 cookie失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"清除cookie失败: {str(e)}")

@router.delete("/clear/tiktok")
def clear_tiktok_cookie(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """清除TikTok cookie"""
    file_path = COOKIE_PATHS["tiktok"]
    
    try:
        if os.path.exists(file_path):
            os.remove(file_path)
            logger.info(f"TikTok cookie文件已删除: {file_path}")
        
        # 重置配置缓存
        if "tiktok" not in _cached_config:
            _cached_config["tiktok"] = {
                "enabled": False,
                "interval_minutes": 10,
                "last_update": None,
                "next_update": None
            }
        _cached_config["tiktok"]["last_update"] = None
        _cached_config["tiktok"]["next_update"] = None
        
        # 保存配置到数据库
        _save_config_to_db(db, "tiktok", {
            "last_update": None,
            "next_update": None
        })
        
        return {
            "message": "TikTok cookie已清除",
            "platform": "tiktok"
        }
        
    except Exception as e:
        logger.error(f"清除TikTok cookie失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"清除cookie失败: {str(e)}")

@router.delete("/clear/instagram")
def clear_instagram_cookie(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """清除Instagram账号密码和登录态"""
    try:
        # 清除 credentials.json
        if os.path.exists(CREDENTIALS_FILE):
            os.remove(CREDENTIALS_FILE)
            logger.info(f"Instagram credentials已删除: {CREDENTIALS_FILE}")

        _clear_instagram_session_cache()

        if "instagram" not in _cached_config:
            _cached_config["instagram"] = {
                "enabled": False,
                "interval_minutes": 10,
                "last_update": None,
                "next_update": None
            }
        _cached_config["instagram"]["last_update"] = None
        _cached_config["instagram"]["next_update"] = None
        _cached_config["instagram"]["enabled"] = False

        _save_config_to_db(db, "instagram", {
            "enabled": False,
            "last_update": None,
            "next_update": None
        })

        return {
            "message": "Instagram 账号密码已清除",
            "platform": "instagram"
        }

    except Exception as e:
        logger.error(f"清除Instagram cookie失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"清除cookie失败: {str(e)}")

@router.post("/clear-risk/instagram")
def clear_instagram_risk(current_user: User = Depends(get_current_user)):
    """清除Instagram风控冷却状态（用户在APP完成验证后调用，无需重新保存账号）"""
    try:
        _clear_risk_failure()
        _clear_instagram_session_cache()
        logger.info("Instagram 风控冷却状态已清除")
        return {"message": "Instagram 风控冷却状态已清除"}
    except Exception as e:
        logger.error(f"清除Instagram风控状态失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"清除风控状态失败: {str(e)}")

@router.delete("/clear/netease")
def clear_netease_cookie(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """清除网易云音乐 cookie"""
    file_path = COOKIE_PATHS["netease"]
    
    try:
        if os.path.exists(file_path):
            os.remove(file_path)
            logger.info(f"网易云音乐 cookie文件已删除: {file_path}")
        
        # 重置配置缓存
        if "netease" not in _cached_config:
            _cached_config["netease"] = {
                "enabled": False,
                "interval_minutes": 10,
                "last_update": None,
                "next_update": None
            }
        _cached_config["netease"]["last_update"] = None
        _cached_config["netease"]["next_update"] = None
        
        # 保存配置到数据库
        _save_config_to_db(db, "netease", {
            "last_update": None,
            "next_update": None
        })
        
        return {
            "message": "网易云音乐 cookie已清除",
            "platform": "netease"
        }
        
    except Exception as e:
        logger.error(f"清除网易云音乐 cookie失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"清除cookie失败: {str(e)}")

@router.delete("/clear/x")
def clear_x_cookie(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """清除X cookie"""
    file_path = COOKIE_PATHS["x"]

    try:
        if os.path.exists(file_path):
            os.remove(file_path)
            logger.info(f"X cookie文件已删除: {file_path}")

        if "x" not in _cached_config:
            _cached_config["x"] = {
                "enabled": False,
                "interval_minutes": 10,
                "last_update": None,
                "next_update": None
            }
        _cached_config["x"]["last_update"] = None
        _cached_config["x"]["next_update"] = None

        _save_config_to_db(db, "x", {
            "last_update": None,
            "next_update": None
        })

        return {
            "message": "X cookie已清除",
            "platform": "x"
        }
    except Exception as e:
        logger.error(f"清除X cookie失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"清除cookie失败: {str(e)}")

@router.delete("/clear/xiaohongshu")
def clear_xiaohongshu_cookie(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """清除小红书 cookie"""
    file_path = COOKIE_PATHS["xiaohongshu"]
    
    try:
        if os.path.exists(file_path):
            os.remove(file_path)
            logger.info(f"小红书 cookie文件已删除: {file_path}")
        
        # 重置配置缓存
        if "xiaohongshu" not in _cached_config:
            _cached_config["xiaohongshu"] = {
                "enabled": False,
                "interval_minutes": 10,
                "last_update": None,
                "next_update": None
            }
        _cached_config["xiaohongshu"]["last_update"] = None
        _cached_config["xiaohongshu"]["next_update"] = None
        
        # 保存配置到数据库
        _save_config_to_db(db, "xiaohongshu", {
            "last_update": None,
            "next_update": None
        })
        
        return {
            "message": "小红书 cookie已清除",
            "platform": "xiaohongshu"
        }
        
    except Exception as e:
        logger.error(f"清除小红书 cookie失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"清除cookie失败: {str(e)}")

@router.delete("/clear/kuaishou")
def clear_kuaishou_cookie(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """清除快手 cookie"""
    file_path = COOKIE_PATHS["kuaishou"]
    
    try:
        if os.path.exists(file_path):
            os.remove(file_path)
            logger.info(f"快手 cookie文件已删除: {file_path}")
        
        # 重置配置缓存
        if "kuaishou" not in _cached_config:
            _cached_config["kuaishou"] = {
                "enabled": False,
                "interval_minutes": 10,
                "last_update": None,
                "next_update": None
            }
        _cached_config["kuaishou"]["last_update"] = None
        _cached_config["kuaishou"]["next_update"] = None
        
        # 保存配置到数据库
        _save_config_to_db(db, "kuaishou", {
            "last_update": None,
            "next_update": None
        })
        
        return {
            "message": "快手 cookie已清除",
            "platform": "kuaishou"
        }
        
    except Exception as e:
        logger.error(f"清除快手 cookie失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"清除cookie失败: {str(e)}")

@router.delete("/clear/all")
def clear_all_cookies(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """清除所有cookie（YouTube、B站、TikTok和网易云音乐）"""
    try:
        cleared_count = 0
        
        for platform, file_path in COOKIE_PATHS.items():
            if os.path.exists(file_path):
                os.remove(file_path)
                cleared_count += 1
                logger.info(f"{platform} cookie文件已删除: {file_path}")
        
        # 重置所有自动更新配置缓存
        for platform in _cached_config:
            _cached_config[platform]["last_update"] = None
            _cached_config[platform]["next_update"] = None
            
            # 保存配置到数据库
            _save_config_to_db(db, platform, {
                "last_update": None,
                "next_update": None
            })
        
        return {
            "message": f"已清除 {cleared_count} 个cookie文件",
            "cleared_count": cleared_count
        }
        
    except Exception as e:
        logger.error(f"清除所有cookie失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"清除所有cookie失败: {str(e)}")

@router.get("/config")
@require_license_api
async def get_cookie_config(db: Session = Depends(get_db)):
    """获取cookie配置信息"""
    config_info = {}
    for platform, file_path in COOKIE_PATHS.items():
        config_info[platform] = {
            "file_path": file_path,
            "exists": os.path.exists(file_path),
            "last_update": None,
            "next_update": None,
            "auto_update_enabled": False,
            "interval_minutes": 10
        }
        if os.path.exists(file_path):
            try:
                config_info[platform]["last_update"] = datetime.fromtimestamp(
                    os.path.getmtime(file_path),
                    tz=timezone.utc
                ).isoformat()
            except:
                pass
        
        # 从数据库加载配置
        db_config = _load_config_from_db(db, platform)
        config_info[platform]["auto_update_enabled"] = db_config["enabled"]
        config_info[platform]["interval_minutes"] = db_config["interval_minutes"]
        config_info[platform]["last_update"] = db_config["last_update"]
        config_info[platform]["next_update"] = db_config["next_update"]
        
        # 添加任务状态信息
        if platform == "youtube":
            config_info[platform]["task_status"] = _get_auto_update_task_status()
        elif platform == "bilibili" or platform == "xiaohongshu":
            # B站、小红书任务状态通过配置来判断
            config_info[platform]["task_status"] = "running" if db_config["enabled"] else "not_started"
    
    return {
        "auto_update": config_info,
        "file_paths": COOKIE_PATHS,
        "note": "支持YouTube、B站、TikTok、网易云音乐和小红书 cookie管理"
    }

@router.get("/auto-update/status")
@require_license_api
async def get_auto_update_status(db: Session = Depends(get_db)):
    """获取自动更新任务的详细状态"""
    try:
        youtube_task_status = _get_auto_update_task_status()
        
        # 从数据库加载YouTube配置
        db_config = _load_config_from_db(db, "youtube")
        
        # 从数据库加载B站配置
        bilibili_config = _load_config_from_db(db, "bilibili")
        
        # 检查B站任务状态（由于B站没有全局任务引用，我们通过配置来判断）
        bilibili_task_status = "running" if bilibili_config["enabled"] else "not_started"
        
        # 从数据库加载小红书配置
        xiaohongshu_config = _load_config_from_db(db, "xiaohongshu")
        xiaohongshu_task_status = "running" if xiaohongshu_config["enabled"] else "not_started"
        
        return {
            "youtube": {
                "enabled": db_config["enabled"],
                "interval_minutes": db_config["interval_minutes"],
                "last_update": db_config["last_update"],
                "next_update": db_config["next_update"],
                "task_status": youtube_task_status,
                "task_running": youtube_task_status == "running"
            },
            "bilibili": {
                "enabled": bilibili_config["enabled"],
                "interval_minutes": bilibili_config["interval_minutes"],
                "last_update": bilibili_config["last_update"],
                "next_update": bilibili_config["next_update"],
                "task_status": bilibili_task_status,
                "task_running": bilibili_config["enabled"]
            },
            "xiaohongshu": {
                "enabled": xiaohongshu_config["enabled"],
                "interval_minutes": xiaohongshu_config["interval_minutes"],
                "last_update": xiaohongshu_config["last_update"],
                "next_update": xiaohongshu_config["next_update"],
                "task_status": xiaohongshu_task_status,
                "task_running": xiaohongshu_config["enabled"]
            }
        }
    except Exception as e:
        logger.error(f"获取自动更新状态失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"获取自动更新状态失败: {str(e)}")

@router.on_event("startup")
async def startup_event():
    """应用启动时的初始化事件"""
    global _auto_update_task
    try:
        # 在启动时，我们需要手动获取数据库会话来加载配置
        # 由于startup_event不能直接使用Depends，我们需要手动创建数据库会话
        from sql.database_postgresql import SessionLocal
        
        db = SessionLocal()
        try:
            # 初始化缓存
            _cached_config.clear()
            
            # 加载YouTube配置
            _load_config_from_db(db, "youtube")
            
            # 检查是否有启用的自动更新配置
            if _cached_config["youtube"]["enabled"]:
                # 在启动事件中，我们已经在事件循环上下文中，可以直接创建任务
                _auto_update_task = asyncio.create_task(_start_youtube_auto_update())
            
            # 加载B站配置
            _load_config_from_db(db, "bilibili")
            
            # 检查是否有启用的B站自动更新配置
            if _cached_config["bilibili"]["enabled"]:
                # 在启动事件中，我们已经在事件循环上下文中，可以直接创建任务
                asyncio.create_task(_start_bilibili_auto_update())
            
            # 加载TikTok配置（TikTok不支持自动更新，只加载基础配置）
            _load_config_from_db(db, "tiktok")
            
            # 加载小红书配置
            _load_config_from_db(db, "xiaohongshu")
            
            # 检查是否有启用的小红书自动更新配置
            if _cached_config["xiaohongshu"]["enabled"]:
                asyncio.create_task(_start_xiaohongshu_auto_update())
                
            # 加载快手配置
            _load_config_from_db(db, "kuaishou")
        finally:
            try:
                db.rollback()
            except Exception:
                pass
            db.close()
            
    except Exception as e:
        logger.error(f"启动cookie自动更新系统失败: {str(e)}")
        _auto_update_task = None

@router.on_event("shutdown")
async def shutdown_event():
    """应用关闭时的清理事件"""
    global _auto_update_task
    try:
        if _auto_update_task and not _auto_update_task.done():
            _auto_update_task.cancel()
            logger.info("YouTube cookie自动更新任务已取消")
    except Exception as e:
        logger.error(f"关闭YouTube cookie自动更新系统失败: {str(e)}")
