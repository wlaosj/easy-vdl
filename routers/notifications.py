import uuid
import json
import logging
import asyncio
import aiohttp
import os
from urllib.parse import unquote
import time as _time
from contextlib import contextmanager
from datetime import datetime, time
from typing import List, Optional
from fastapi import APIRouter, HTTPException, Depends, BackgroundTasks
from sqlalchemy.orm import Session
from sqlalchemy import and_, or_, desc
from urllib.parse import quote

from sql.database_postgresql import get_db, get_session
from sql.models import (
    Notification, NotificationSetting, NotificationType, NotificationStatus,
    NotificationChannel, User, NotificationCreate, NotificationUpdate,
    NotificationSettingCreate, NotificationSettingUpdate, WechatBotTestRequest,
    ServerChan3TestRequest, TelegramBotTestRequest, BarkTestRequest, NotificationResponse, NotificationSettingResponse,
    Task, WecomBotTestRequest
)
from routers.auth import get_current_user

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/notifications", tags=["notifications"])

# 媒体库刷新节流：避免频繁下载完成导致 Jellyfin/Emby 反复全库扫描，引发 IO/数据库瓶颈
# 默认 90 秒冷却；可通过环境变量覆盖（单位：秒）
_MEDIA_REFRESH_COOLDOWN_SECONDS = int(os.getenv("MEDIA_SERVER_REFRESH_COOLDOWN_SECONDS", "90") or "90")
# key: normalized server_url -> last trigger monotonic timestamp
_media_refresh_last_ts: dict[str, float] = {}
_media_refresh_lock = asyncio.Lock()


@contextmanager
def _db_session_scope():
    """统一数据库会话作用域，确保异常回滚与连接关闭。"""
    db = get_session()
    try:
        yield db
    except Exception:
        try:
            db.rollback()
        except Exception:
            pass
        raise
    finally:
        try:
            if db.in_transaction():
                db.rollback()
        except Exception:
            pass
        try:
            db.close()
        except Exception:
            pass

def _normalize_server_url(url: str) -> str:
    return (url or "").strip().rstrip("/")

def _normalize_download_local_path(path_or_url: Optional[str]) -> Optional[str]:
    """将 /downloads 相对URL映射为容器内本地路径。"""
    if not path_or_url:
        return None
    p = str(path_or_url).strip()
    if not p:
        return None
    # 去除 query/hash 并反解 URL 编码，避免 %23 等导致本地路径匹配失败
    p = p.split("?", 1)[0].split("#", 1)[0]
    p = unquote(p)

    if p.startswith("/downloads/"):
        return os.path.join("/app/downloads", p[len("/downloads/"):].lstrip("/"))
    if p.startswith("/app/downloads/"):
        return p
    if p.startswith("/"):
        return p
    return os.path.join("/app/downloads", p)

def _format_file_size(size_bytes: int) -> str:
    size = float(max(0, int(size_bytes)))
    units = ["B", "KB", "MB", "GB", "TB"]
    idx = 0
    while size >= 1024.0 and idx < len(units) - 1:
        size /= 1024.0
        idx += 1
    if idx == 0:
        return f"{int(size)} {units[idx]}"
    return f"{size:.2f} {units[idx]}"

def _compute_directory_total_size(folder: str) -> int:
    total = 0
    for root, _, files in os.walk(folder):
        for name in files:
            fp = os.path.join(root, name)
            try:
                total += os.path.getsize(fp)
            except Exception:
                continue
    return total

def _pick_media_from_directory(folder: str) -> Optional[str]:
    if not folder or not os.path.isdir(folder):
        return None
    media_exts = (
        ".mp4", ".mov", ".m4v", ".webm", ".mkv", ".flv", ".ts",
        ".mp3", ".m4a", ".aac", ".flac", ".wav", ".ogg", ".opus"
    )
    candidates = []
    try:
        for name in os.listdir(folder):
            path = os.path.join(folder, name)
            if os.path.isfile(path) and name.lower().endswith(media_exts):
                candidates.append(path)
    except Exception:
        return None
    if not candidates:
        return None
    candidates.sort(key=lambda p: os.path.getsize(p), reverse=True)
    return candidates[0]

def _guess_media_from_cover(cover_path: str) -> Optional[str]:
    if not cover_path:
        return None
    base, _ = os.path.splitext(cover_path)
    for ext in (".mp4", ".mkv", ".webm", ".mov", ".m4v", ".flv", ".ts", ".mp3", ".m4a", ".flac", ".wav", ".aac", ".ogg", ".opus"):
        candidate = f"{base}{ext}"
        if os.path.exists(candidate) and os.path.isfile(candidate):
            return candidate
    return _pick_media_from_directory(os.path.dirname(cover_path))

def _enrich_download_completed_with_file_size(content: str, extra_data: Optional[dict]) -> tuple[str, Optional[dict]]:
    """为下载完成通知自动补充文件大小信息（bytes + 文本）。"""
    if not isinstance(extra_data, dict):
        extra_data = {}

    # 已有文件大小则直接复用
    if extra_data.get("file_size_text"):
        if "文件大小" not in (content or ""):
            content = (content or "").rstrip() + f"\n📦 文件大小: {extra_data.get('file_size_text')}"
        return content, extra_data

    size_bytes = None
    candidate_path = None

    # 1) 直接路径字段优先
    for key in ("video_path", "file_path", "path", "local_path", "download_path"):
        p = _normalize_download_local_path(extra_data.get(key))
        if p and os.path.exists(p):
            candidate_path = p
            break

    # 2) 图集目录路径
    if not candidate_path:
        gp = _normalize_download_local_path(extra_data.get("gallery_path"))
        if gp and os.path.exists(gp):
            candidate_path = gp

    # 3) 从封面路径推导媒体
    if not candidate_path:
        for key in ("cover", "cover_url", "poster"):
            cp = _normalize_download_local_path(extra_data.get(key))
            if cp and os.path.exists(cp):
                guessed = _guess_media_from_cover(cp)
                if guessed and os.path.exists(guessed):
                    candidate_path = guessed
                    break

    # 4) 计算大小
    try:
        if candidate_path and os.path.exists(candidate_path):
            if os.path.isfile(candidate_path):
                size_bytes = os.path.getsize(candidate_path)
            elif os.path.isdir(candidate_path):
                size_bytes = _compute_directory_total_size(candidate_path)
    except Exception:
        size_bytes = None

    if size_bytes is not None and size_bytes > 0:
        size_text = _format_file_size(size_bytes)
        extra_data["file_size_bytes"] = int(size_bytes)
        extra_data["file_size_text"] = size_text
        if "文件大小" not in (content or ""):
            content = (content or "").rstrip() + f"\n📦 文件大小: {size_text}"

    return content, extra_data

async def _should_trigger_media_refresh(server_url: str) -> bool:
    """同一 server_url 在冷却窗口内只触发一次刷新（去抖/合并）。"""
    if _MEDIA_REFRESH_COOLDOWN_SECONDS <= 0:
        return True

    key = _normalize_server_url(server_url)
    if not key:
        return False

    now = _time.monotonic()
    async with _media_refresh_lock:
        last = _media_refresh_last_ts.get(key)
        if last is not None and (now - last) < _MEDIA_REFRESH_COOLDOWN_SECONDS:
            return False
        _media_refresh_last_ts[key] = now
        return True

class NotificationService:
    """通知服务类"""
    
    @staticmethod
    def safe_get_object_attr(obj, attr_name, default_value=None):
        """安全获取数据库对象属性，避免Session绑定问题"""
        try:
            if hasattr(obj, attr_name):
                return getattr(obj, attr_name)
            return default_value
        except Exception as e:
            logger.warning(f"获取对象属性 {attr_name} 失败: {str(e)}")
            return default_value
    
    @staticmethod
    def safe_get_video_info(video_id, db_session):
        """安全获取视频信息，避免Session绑定问题"""
        try:
            from sql.models import SubscriptionVideo, Subscription
            # 重新查询视频对象
            video = db_session.query(SubscriptionVideo).filter(
                SubscriptionVideo.id == video_id
            ).first()
            
            if video:
                # 获取订阅信息
                subscription = db_session.query(Subscription).filter(
                    Subscription.id == video.subscription_id
                ).first()
                
                return {
                    'title': video.title,
                    'subscription_nickname': subscription.nickname if subscription else "未知",
                    'extra_data': video.extra_data
                }
            return None
        except Exception as e:
            logger.warning(f"获取视频信息失败: {str(e)}")
            return None
    
    @staticmethod
    async def send_wechat_bot_message(webhook_url: str, message: str, msg_type: str = "text") -> bool:
        """发送微信机器人消息"""
        try:
            # 统一添加系统来源标签，便于在消息顶部区分来源
            tagged_message = f"[easy-vdl]\n{message}" if not message.startswith("[easy-vdl]") else message
            
            # 根据消息类型选择发送格式
            if msg_type == "markdown":
                # 使用Markdown格式发送
                payload = {
                    "msgtype": "markdown",
                    "markdown": {"content": tagged_message}
                }
            else:
                # 默认使用文本格式
                payload = {
                    "msgtype": "text",
                    "text": {"content": tagged_message}
                }
            
            async with aiohttp.ClientSession() as session:
                async with session.post(webhook_url, json=payload, timeout=10) as response:
                    if response.status == 200:
                        result = await response.json()
                        if result.get("errcode") == 0:
                            logger.debug(f"微信机器人消息发送成功: {message[:50]}...")
                            return True
                        else:
                            logger.error(f"微信机器人消息发送失败: {result}")
                            return False
                    else:
                        logger.error(f"微信机器人HTTP请求失败: {response.status}")
                        return False
        except Exception as e:
            logger.error(f"微信机器人消息发送异常: {str(e)}")
            return False
    
    @staticmethod
    async def send_wecom_bot_message(corp_id: str, agent_id: str, secret: str, user_id: str, message: str, msg_type: str = "text") -> bool:
        """发送企业微信应用消息"""
        try:
            from services.wecom_api import WecomApiClient
            client = WecomApiClient(corp_id=corp_id, agent_id=agent_id, secret=secret)
            tagged_message = f"[easy-vdl]\n{message}" if not message.startswith("[easy-vdl]") else message
            result = await client.send_message(user_id, tagged_message, msg_type)
            if result.get("errcode") == 0:
                logger.debug(f"企业微信应用消息发送成功: {message[:50]}...")
                return True
            else:
                logger.error(f"企业微信应用消息发送失败: {result}")
                return False
        except Exception as e:
            logger.error(f"企业微信应用消息发送异常: {str(e)}")
            return False

    @staticmethod
    async def send_serverchan3_message(uid: str, sendkey: str, title: str, content: str = "", avatar_url: str = None) -> bool:
        """发送Server酱³消息（使用Markdown格式，支持图片和头像）"""
        try:
            # Server酱³不使用顶部标签，直接使用原始title
            # 微信机器人保持原有的标签逻辑不变
            
            # 构建Markdown格式的消息，确保内容能够一行一个信息显示
            # 将内容按行分割，每行用Markdown格式包装，保持简洁
            content_lines = content.strip().split('\n')
            formatted_lines = []
            
            for line in content_lines:
                if line.strip():  # 跳过空行
                    # 所有内容都按普通文本处理，不再检测图片链接
                    formatted_lines.append(f"**{line.strip()}**")
            
            # 组合成Markdown格式的消息
            # 直接添加内容，不添加标题（因为顶部已有标题）
            markdown_content = ""
            
            # 添加内容
            for line in formatted_lines:
                markdown_content += line + "\n\n"
            
            # 如果有头像URL，在底部显示头像
            # if avatar_url and avatar_url.strip():
            #     # 改回图片形式进行测试
            #     markdown_content += f"![博主头像]({avatar_url.strip()})\n\n"
            
            markdown_content = markdown_content.rstrip("\n")  # 移除最后的换行符
            
            # 构造Server酱³ API URL
            api_url = f"https://{uid}.push.ft07.com/send/{sendkey}.send"
            
            # 准备请求参数 - Server酱³使用Markdown格式
            # 使用POST请求避免URL编码问题
            data = {
                "title": title,  # 直接使用原始title，不添加标签
                "desp": markdown_content,  # 使用Markdown格式内容
                "short": "订阅检测完成",  # 指定消息卡片显示的文字
                "tags": "easy-vdl"  # 添加标签
            }
            
            async with aiohttp.ClientSession() as session:
                async with session.post(api_url, data=data, timeout=10) as response:
                    if response.status == 200:
                        result = await response.json()
                        if result.get("code") == 0:
                            logger.debug(f"Server酱³消息发送成功: {title[:50]}...")
                            return True
                        else:
                            logger.error(f"Server酱³消息发送失败: {result}")
                            return False
                    else:
                        logger.error(f"Server酱³ HTTP请求失败: {response.status}")
                        return False
        except Exception as e:
            logger.error(f"Server酱³消息发送异常: {str(e)}")
            return False

    @staticmethod
    async def send_bark_message(
        server_url: Optional[str],
        device_key: str,
        title: str,
        content: str,
        sound: Optional[str] = None,
        group: Optional[str] = None,
        icon: Optional[str] = None,
        url: Optional[str] = None,
        automatically_copy: Optional[str] = None
    ) -> bool:
        """发送 Bark 消息"""
        try:
            key = (device_key or "").strip()
            if not key:
                return False

            base_url = (server_url or "https://api.day.app").strip().rstrip("/")
            safe_title = quote(title or "", safe="")
            safe_content = quote(content or "", safe="")
            api_url = f"{base_url}/{key}/{safe_title}/{safe_content}"

            params = {}
            if sound:
                params["sound"] = sound
            if group:
                params["group"] = group
            if icon:
                params["icon"] = icon
            if url:
                params["url"] = url

            auto_val = None
            if automatically_copy is not None:
                if isinstance(automatically_copy, bool):
                    auto_val = "1" if automatically_copy else "0"
                else:
                    raw = str(automatically_copy).strip().lower()
                    if raw in ("1", "true", "yes", "y", "on"):
                        auto_val = "1"
                    elif raw in ("0", "false", "no", "n", "off"):
                        auto_val = "0"
            if auto_val is not None:
                params["automaticallyCopy"] = auto_val

            async with aiohttp.ClientSession() as session:
                async with session.get(api_url, params=params, timeout=10) as response:
                    if response.status in (200, 201, 202):
                        try:
                            data = await response.json()
                            if isinstance(data, dict):
                                code = data.get("code")
                                if code not in (0, 200, None):
                                    logger.error(f"Bark 消息发送失败: {data}")
                                    return False
                        except Exception:
                            pass
                        return True
                    logger.error(f"Bark HTTP请求失败: {response.status}")
                    return False
        except Exception as e:
            logger.error(f"Bark 消息发送异常: {str(e)}")
            return False

    @staticmethod
    async def refresh_media_library(server_url: str, api_key: str, server_type: str = "jellyfin") -> bool:
        """刷新媒体服务器（Jellyfin/Emby）媒体库，默认刷新全部库"""
        try:
            if not server_url or not api_key:
                return False

            url = f"{server_url.rstrip('/')}/Library/Refresh"

            async with aiohttp.ClientSession() as session:
                # 选择认证头
                server_type_lower = (server_type or "jellyfin").lower()

                async def post_with_headers(headers: dict) -> bool:
                    async with session.post(url, headers=headers, timeout=30) as response:
                        if response.status in (200, 204):
                            return True
                        # 有些反代会返回JSON错误，记录一下
                        try:
                            body = await response.text()
                            logger.warning(f"媒体库刷新HTTP状态: {response.status}, 响应: {body[:200]}")
                        except Exception:
                            logger.warning(f"媒体库刷新HTTP状态: {response.status}")
                        return False

                if server_type_lower == "emby":
                    headers = {"X-Emby-Token": api_key}
                    ok = await post_with_headers(headers)
                    return ok
                elif server_type_lower == "auto":
                    # 先尝试Jellyfin
                    jf_headers = {"Authorization": f'MediaBrowser Token="{api_key}"'}
                    if await post_with_headers(jf_headers):
                        return True
                    # 再尝试Emby
                    emby_headers = {"X-Emby-Token": api_key}
                    return await post_with_headers(emby_headers)
                else:
                    # 默认Jellyfin
                    headers = {"Authorization": f'MediaBrowser Token="{api_key}"'}
                    ok = await post_with_headers(headers)
                    return ok
        except Exception as e:
            logger.error(f"媒体库刷新异常: {str(e)}")
            return False

    @staticmethod
    async def test_media_server_connection(server_url: str, api_key: str, server_type: str = "jellyfin") -> dict:
        """测试媒体服务器连接和API密钥有效性"""
        try:
            if not server_url or not api_key:
                return {
                    "success": False,
                    "message": "服务器地址或API密钥不能为空",
                    "detected_type": None
                }

            # 清理URL
            base_url = server_url.rstrip('/')
            
            async with aiohttp.ClientSession() as session:
                server_type_lower = (server_type or "jellyfin").lower()
                
                async def test_with_headers(headers: dict, test_type: str) -> tuple[bool, str]:
                    """使用指定头部测试连接"""
                    try:
                        # 尝试访问系统信息端点，这是最轻量级的测试
                        url = f"{base_url}/System/Info"
                        async with session.get(url, headers=headers, timeout=10) as response:
                            if response.status == 200:
                                try:
                                    data = await response.json()
                                    server_name = data.get('ServerName', 'Unknown')
                                    version = data.get('Version', 'Unknown')
                                    return True, f"{test_type}连接成功 - 服务器: {server_name}, 版本: {version}"
                                except Exception:
                                    return True, f"{test_type}连接成功 - 状态码: {response.status}"
                            else:
                                return False, f"{test_type}连接失败 - 状态码: {response.status}"
                    except Exception as e:
                        return False, f"{test_type}连接异常: {str(e)}"

                if server_type_lower == "jellyfin":
                    headers = {"Authorization": f'MediaBrowser Token="{api_key}"'}
                    success, message = await test_with_headers(headers, "Jellyfin")
                    return {
                        "success": success,
                        "message": message,
                        "detected_type": "jellyfin" if success else None
                    }
                elif server_type_lower == "emby":
                    headers = {"X-Emby-Token": api_key}
                    success, message = await test_with_headers(headers, "Emby")
                    return {
                        "success": success,
                        "message": message,
                        "detected_type": "emby" if success else None
                    }
                elif server_type_lower == "auto":
                    # 自动检测：先尝试Jellyfin
                    jf_headers = {"Authorization": f'MediaBrowser Token="{api_key}"'}
                    jf_success, jf_message = await test_with_headers(jf_headers, "Jellyfin")
                    if jf_success:
                        return {
                            "success": True,
                            "message": jf_message,
                            "detected_type": "jellyfin"
                        }
                    
                    # 再尝试Emby
                    emby_headers = {"X-Emby-Token": api_key}
                    emby_success, emby_message = await test_with_headers(emby_headers, "Emby")
                    if emby_success:
                        return {
                            "success": True,
                            "message": emby_message,
                            "detected_type": "emby"
                        }
                    
                    # 都失败了，返回详细错误信息
                    return {
                        "success": False,
                        "message": f"自动检测失败 - Jellyfin: {jf_message}, Emby: {emby_message}",
                        "detected_type": None
                    }
                else:
                    return {
                        "success": False,
                        "message": f"未知的服务器类型: {server_type}",
                        "detected_type": None
                    }
                    
        except Exception as e:
            logger.error(f"测试媒体服务器连接异常: {str(e)}")
            return {
                "success": False,
                "message": f"测试连接时发生异常: {str(e)}",
                "detected_type": None
            }
    
    @staticmethod
    def is_quiet_hours(quiet_start: str, quiet_end: str) -> bool:
        """检查是否在静音时间内"""
        try:
            current_time = datetime.now().time()
            start_time = datetime.strptime(quiet_start, "%H:%M").time()
            end_time = datetime.strptime(quiet_end, "%H:%M").time()
            
            if start_time <= end_time:
                # 同一天内的时间段
                return start_time <= current_time <= end_time
            else:
                # 跨天的时间段（如22:00-08:00）
                return current_time >= start_time or current_time <= end_time
        except Exception as e:
            logger.error(f"静音时间检查异常: {str(e)}")
            return False
    
    @staticmethod
    async def create_notification(
        db: Session,
        notification_type: str,
        title: str,
        content: str,
        user_id: Optional[str] = None,
        channel: str = NotificationChannel.WECHAT_BOT.value,
        priority: int = 1,
        extra_data: Optional[dict] = None
    ) -> Notification:
        """创建通知"""
        try:
            notification = Notification(
                id=str(uuid.uuid4()),
                user_id=user_id,
                type=notification_type,
                title=title,
                content=content,
                channel=channel,
                priority=priority,
                extra_data=json.dumps(extra_data) if extra_data else None
            )
            
            db.add(notification)
            db.commit()
            db.refresh(notification)
            
            logger.debug(f"通知创建成功: {notification.id} - {title}")
            return notification
            
        except Exception as e:
            db.rollback()
            logger.error(f"创建通知失败: {str(e)}")
            raise HTTPException(status_code=500, detail=f"创建通知失败: {str(e)}")
    
    @staticmethod
    async def send_notification(
        db: Session,
        notification: Notification,
        background_tasks: BackgroundTasks
    ) -> bool:
        """发送通知"""
        try:
            # 检查用户通知设置
            if notification.user_id:
                setting = db.query(NotificationSetting).filter(
                    NotificationSetting.user_id == notification.user_id
                ).first()
                
                if not setting:
                    # 创建默认设置
                    setting = NotificationSetting(
                        id=str(uuid.uuid4()),
                        user_id=notification.user_id
                    )
                    db.add(setting)
                    db.commit()
                
                # 检查静音时间
                if setting.quiet_hours_enabled == "true" and NotificationService.is_quiet_hours(setting.quiet_hours_start, setting.quiet_hours_end):
                    logger.info(f"用户 {notification.user_id} 在静音时间内，跳过通知")
                    return False
                
                # 多渠道同步推送逻辑
                channels_sent = []
                
                # 1. 发送到微信机器人（如果启用）
                if setting.wechat_bot_enabled == "true" and setting.wechat_webhook_url:
                    # 构建普通文本格式的消息（普通微信不支持Markdown）
                    current_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                    text_message = f"""🔔 {notification.title}

{notification.content}"""
                    
                    background_tasks.add_task(
                        NotificationService.send_wechat_bot_message,
                        setting.wechat_webhook_url,
                        text_message,
                        "text"  # 使用普通文本格式
                    )
                    channels_sent.append("wechat")
                    logger.debug(f"用户 {notification.user_id} 微信机器人通知已加入发送队列")

                # 1.5 发送到企业微信应用Bot（如果启用）
                if getattr(setting, 'wecom_bot_enabled', "false") == "true" and getattr(setting, 'wecom_corp_id', None) and getattr(setting, 'wecom_secret', None) and getattr(setting, 'wecom_agent_id', None):
                    wecom_message = f"🔔 {notification.title}\n\n{notification.content}"
                    background_tasks.add_task(
                        NotificationService.send_wecom_bot_message,
                        setting.wecom_corp_id,
                        setting.wecom_agent_id,
                        setting.wecom_secret,
                        "@all",
                        wecom_message,
                        "text"
                    )
                    channels_sent.append("wecom")
                    logger.debug(f"用户 {notification.user_id} 企业微信应用通知已加入发送队列")

                # 2. 发送到Server酱³（如果启用）
                if setting.serverchan3_enabled == "true" and setting.serverchan3_uid and setting.serverchan3_sendkey:
                    # 获取头像URL
                    avatar_url = None
                    
                    # 从订阅数据库中获取头像URL
                    if notification.extra_data:
                        try:
                            extra_data = json.loads(notification.extra_data) if isinstance(notification.extra_data, str) else notification.extra_data
                            # 尝试多种方式获取博主ID
                            blogger_id = extra_data.get('user_id') or extra_data.get('blogger_id') or extra_data.get('subscription_id')
                            
                            if blogger_id:
                                from sql.models import Subscription
                                subscription = db.query(Subscription).filter(
                                    Subscription.user_id == blogger_id  # 博主ID
                                ).first()
                                if subscription and subscription.avatar_url:
                                    avatar_url = subscription.avatar_url
                                    logger.info(f"从订阅数据库获取到头像: {avatar_url}")
                        except Exception as e:
                            logger.warning(f"获取订阅头像失败: {str(e)}")
                            pass
                    
                    # 直接传入原始内容，让 send_serverchan3_message 方法内部进行格式化
                    background_tasks.add_task(
                        NotificationService.send_serverchan3_message,
                        setting.serverchan3_uid,
                        setting.serverchan3_sendkey,
                        f"🔔 {notification.title}",
                        notification.content,  # 传入原始内容
                        avatar_url  # 传入头像URL
                    )
                    channels_sent.append("server")
                    logger.debug(f"用户 {notification.user_id} Server酱³通知已加入发送队列")
                
                # 3. 发送到邮件（如果启用）
                if setting.email_enabled == "true" and setting.email_address:
                    # TODO: 实现邮件发送逻辑
                    channels_sent.append("email")
                    logger.debug(f"用户 {notification.user_id} 邮件通知已加入发送队列")
                
                # 4. 发送到网页推送（如果启用）
                if setting.web_push_enabled == "true":
                    # TODO: 实现网页推送逻辑
                    channels_sent.append("web")
                    logger.debug(f"用户 {notification.user_id} 网页推送通知已加入发送队列")
                
                # 5. 发送到WebSocket（如果启用）
                if setting.websocket_enabled == "true":
                    # TODO: 实现WebSocket推送逻辑
                    channels_sent.append("ws")
                    # WebSocket通知已加入发送队列
                
                # 6. 发送到 Telegram 机器人（如果启用）
                if getattr(setting, 'telegram_bot_enabled', 'false') == "true":
                    from routers.telegram_bot import telegram_bot
                    
                    # 确定要发送给谁：如果有白名单（通常是单用户），发给所有白名单用户；或者发给 setting 里配置的
                    # 目前 telegram_bot.chat_id_whitelist 来自配置
                    targets = []
                    if setting.telegram_chat_id:
                        targets = [cid.strip() for cid in setting.telegram_chat_id.split(',') if cid.strip()]
                    
                    if targets:
                        # 构造消息
                        safe_title = telegram_bot.escape_markdown(notification.title)
                        safe_content = telegram_bot.escape_markdown(notification.content)
                        tg_msg = f"*{safe_title}*\n\n{safe_content}"
                        reply_markup = None

                        # 尝试获取封面图 / 图集列表
                        photo_path = None
                        gallery_items = []
                        extra = {}
                        notification_subscription_id = None
                        notification_task_id = None
                        if notification.extra_data:
                            try:
                                extra = json.loads(notification.extra_data) if isinstance(notification.extra_data, str) else notification.extra_data
                                if not isinstance(extra, dict):
                                    extra = {}
                                photo_path = extra.get('cover') or extra.get('cover_url') or extra.get('poster')
                                for key in ('image_urls', 'images', 'image_list', 'photos', 'gallery', 'gallery_urls', 'media_urls'):
                                    val = extra.get(key)
                                    if isinstance(val, list):
                                        for item in val:
                                            if isinstance(item, str) and item:
                                                gallery_items.append(item)
                                            elif isinstance(item, dict):
                                                for k in ('url', 'src', 'path', 'file', 'local_path', 'origin_url', 'download_url'):
                                                    if item.get(k):
                                                        gallery_items.append(item.get(k))
                                                        break
                                
                                if photo_path:
                                    logger.debug(f"Telegram 封面图路径: {photo_path}")
                            except Exception as e:
                                logger.warning(f"解析封面图路径失败: {e}")
                                extra = {}

                        for key in ("subscription_id", "sub_id"):
                            v = extra.get(key)
                            if v:
                                notification_subscription_id = str(v).strip()
                                break

                        for key in ("task_id", "download_task_id"):
                            v = extra.get(key)
                            if v:
                                notification_task_id = str(v).strip()
                                break

                        if notification_task_id and not notification_subscription_id:
                            try:
                                task = db.query(Task).filter(Task.id == notification_task_id).first()
                                if task and getattr(task, "subscription_id", None):
                                    notification_subscription_id = str(task.subscription_id).strip()
                            except Exception:
                                pass

                        if notification.type == NotificationType.DOWNLOAD_COMPLETED.value:
                            row_buttons = [{"text": "📤 发送媒体到Bot", "callback_data": f"tsv:{notification.id}"}]
                            if notification_subscription_id:
                                row_buttons.append({"text": "🔧 订阅管理", "callback_data": f"si:{notification_subscription_id}:n"})
                            reply_markup = {"inline_keyboard": [row_buttons]}

                        if notification.type == NotificationType.DOWNLOAD_ERROR.value:
                            inline_keyboard = [[
                                {"text": "🔁 重试下载", "callback_data": f"trn:{notification.id}"},
                                {"text": "🗑 删除任务", "callback_data": f"tdn:{notification.id}"}
                            ]]
                            if notification_subscription_id:
                                inline_keyboard.append([
                                    {"text": "🔧 订阅管理", "callback_data": f"si:{notification_subscription_id}:n"}
                                ])
                            reply_markup = {"inline_keyboard": inline_keyboard}
                        
                        for tid in targets:
                            # 仅对「Bot 发起的批量下载」静默单条下载完成通知，避免刷屏淹没汇总进度
                            if (
                                notification.type == NotificationType.DOWNLOAD_COMPLETED.value
                                and notification_subscription_id
                                and telegram_bot.should_suppress_completed_notification_for_bot_batch(notification_subscription_id)
                            ):
                                logger.debug(
                                    f"静默单条下载完成TG通知（Bot批量场景）: notification={notification.id}, sub={notification_subscription_id}"
                                )
                                continue

                            # 下载完成通知：仅发送通知文本/封面 + 按钮，媒体由按钮回调 tsv:* 触发发送
                            if notification.type == NotificationType.DOWNLOAD_COMPLETED.value:
                                if photo_path:
                                    background_tasks.add_task(telegram_bot.send_photo, tid, photo_path, tg_msg, reply_markup)
                                else:
                                    background_tasks.add_task(telegram_bot.send_message, tid, tg_msg, "Markdown", reply_markup)
                                continue

                            # 其他通知保持原行为（不自动发送图集媒体）
                            if photo_path:
                                background_tasks.add_task(telegram_bot.send_photo, tid, photo_path, tg_msg, reply_markup)
                            else:
                                background_tasks.add_task(telegram_bot.send_message, tid, tg_msg, "Markdown", reply_markup)
                        
                        channels_sent.append("telegram")
                        logger.debug(f"用户 {notification.user_id} Telegram 通知已加入发送队列")
                    else:
                        logger.warning(f"Telegram Bot 已启用但未配置 Chat ID")

                # 7. 发送到 Bark（如果启用）
                if getattr(setting, 'bark_enabled', 'false') == "true" and getattr(setting, 'bark_device_key', None):
                    background_tasks.add_task(
                        NotificationService.send_bark_message,
                        getattr(setting, 'bark_server_url', None),
                        getattr(setting, 'bark_device_key', None),
                        notification.title,
                        notification.content,
                        getattr(setting, 'bark_sound', None),
                        getattr(setting, 'bark_group', None),
                        getattr(setting, 'bark_icon', None),
                        getattr(setting, 'bark_url', None),
                        getattr(setting, 'bark_automatically_copy', None)
                    )
                    channels_sent.append("bark")
                    logger.debug(f"用户 {notification.user_id} Bark 通知已加入发送队列")

                # 检查是否有渠道被发送
                if channels_sent:
                    # 更新通知状态
                    notification.status = NotificationStatus.SENT.value
                    notification.sent_at = datetime.now()
                    # 截断 channel 字符串，确保不超过 20 个字符（数据库限制）
                    channel_str = ",".join(channels_sent)
                    notification.channel = channel_str[:20] if len(channel_str) > 20 else channel_str
                    db.commit()
                    
                    logger.debug(f"用户 {notification.user_id} 通知已发送到 {len(channels_sent)} 个渠道: {', '.join(channels_sent)}")
                    return True
                else:
                    logger.debug(f"用户 {notification.user_id} 未启用任何通知渠道")
                    return False
            
            return False
            
        except Exception as e:
            logger.error(f"发送通知失败: {str(e)}")
            try:
                db.rollback()
            except Exception:
                pass
            try:
                notification.status = NotificationStatus.FAILED.value
                notification.error_message = str(e)
                db.commit()
            except Exception as commit_error:
                logger.error(f"写入通知失败状态异常: {str(commit_error)}")
            return False

# 通知管理接口
@router.post("/", response_model=NotificationResponse)
async def create_notification(
    notification: NotificationCreate,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """创建通知"""
    try:
        # 创建通知记录
        db_notification = await NotificationService.create_notification(
            db=db,
            notification_type=notification.type,
            title=notification.title,
            content=notification.content,
            user_id=notification.user_id or current_user.id,
            channel=notification.channel,
            priority=notification.priority,
            extra_data=notification.extra_data
        )
        
        # 异步发送通知
        await NotificationService.send_notification(db, db_notification, background_tasks)
        
        return NotificationResponse(
            id=db_notification.id,
            type=db_notification.type,
            title=db_notification.title,
            content=db_notification.content,
            status=db_notification.status,
            channel=db_notification.channel,
            priority=db_notification.priority,
            created_at=db_notification.created_at,
            sent_at=db_notification.sent_at,
            read_at=db_notification.read_at
        )
        
    except Exception as e:
        logger.error(f"创建通知异常: {str(e)}")
        raise HTTPException(status_code=500, detail=f"创建通知失败: {str(e)}")

@router.get("/", response_model=List[NotificationResponse])
async def get_notifications(
    skip: int = 0,
    limit: int = 50,
    status: Optional[str] = None,
    notification_type: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """获取用户通知列表"""
    try:
        query = db.query(Notification).filter(Notification.user_id == current_user.id)
        
        if status:
            query = query.filter(Notification.status == status)
        
        if notification_type:
            query = query.filter(Notification.type == notification_type)
        
        notifications = query.order_by(desc(Notification.created_at)).offset(skip).limit(limit).all()
        
        return [
            NotificationResponse(
                id=n.id,
                type=n.type,
                title=n.title,
                content=n.content,
                status=n.status,
                channel=n.channel,
                priority=n.priority,
                created_at=n.created_at,
                sent_at=n.sent_at,
                read_at=n.read_at
            )
            for n in notifications
        ]
        
    except Exception as e:
        logger.error(f"获取通知列表异常: {str(e)}")
        raise HTTPException(status_code=500, detail=f"获取通知列表失败: {str(e)}")

@router.put("/{notification_id}/read")
async def mark_notification_read(
    notification_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """标记通知为已读"""
    try:
        notification = db.query(Notification).filter(
            and_(
                Notification.id == notification_id,
                Notification.user_id == current_user.id
            )
        ).first()
        
        if not notification:
            raise HTTPException(status_code=404, detail="通知不存在")
        
        notification.status = NotificationStatus.READ.value
        notification.read_at = datetime.now()
        db.commit()
        
        return {"success": True, "message": "通知已标记为已读"}
        
    except Exception as e:
        logger.error(f"标记通知已读异常: {str(e)}")
        raise HTTPException(status_code=500, detail=f"标记通知已读失败: {str(e)}")

@router.delete("/{notification_id}")
async def delete_notification(
    notification_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """删除通知"""
    try:
        notification = db.query(Notification).filter(
            and_(
                Notification.id == notification_id,
                Notification.user_id == current_user.id
            )
        ).first()
        
        if not notification:
            raise HTTPException(status_code=404, detail="通知不存在")
        
        db.delete(notification)
        db.commit()
        
        return {"success": True, "message": "通知已删除"}
        
    except Exception as e:
        logger.error(f"删除通知异常: {str(e)}")
        raise HTTPException(status_code=500, detail=f"删除通知失败: {str(e)}")

# 通知设置接口
@router.get("/settings", response_model=NotificationSettingResponse)
async def get_notification_settings(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """获取用户通知设置"""
    try:
        setting = db.query(NotificationSetting).filter(
            NotificationSetting.user_id == current_user.id
        ).first()
        
        if not setting:
            # 创建默认设置
            setting = NotificationSetting(
                id=str(uuid.uuid4()),
                user_id=current_user.id
            )
            db.add(setting)
            db.commit()
            db.refresh(setting)
        
        return NotificationSettingResponse(
            id=setting.id,
            user_id=setting.user_id,
            wechat_bot_enabled=setting.wechat_bot_enabled,
            wechat_webhook_url=setting.wechat_webhook_url,
            media_server_enabled=getattr(setting, 'media_server_enabled', "false"),
            media_server_type=getattr(setting, 'media_server_type', "jellyfin"),
            media_server_url=getattr(setting, 'media_server_url', None),
            media_server_api_key=getattr(setting, 'media_server_api_key', None),
            serverchan3_enabled=getattr(setting, 'serverchan3_enabled', "false"),
            serverchan3_uid=getattr(setting, 'serverchan3_uid', None),
            serverchan3_sendkey=getattr(setting, 'serverchan3_sendkey', None),
            email_enabled=setting.email_enabled,
            email_address=setting.email_address,
            web_push_enabled=setting.web_push_enabled,
            websocket_enabled=setting.websocket_enabled,
            download_completed_enabled=setting.download_completed_enabled,
            download_error_enabled=setting.download_error_enabled,

            subscription_check_failed_enabled=getattr(setting, 'subscription_check_failed_enabled', "true"),
            subscription_check_new_videos_enabled=getattr(setting, 'subscription_check_new_videos_enabled', "true"),
            subscription_check_no_new_videos_enabled=getattr(setting, 'subscription_check_no_new_videos_enabled', "false"),
            system_status_enabled=getattr(setting, 'system_status_enabled', "true"),
            quiet_hours_enabled=setting.quiet_hours_enabled,
            quiet_hours_start=setting.quiet_hours_start,
            quiet_hours_end=setting.quiet_hours_end,
            
            # Telegram 机器人配置
            telegram_bot_enabled=getattr(setting, 'telegram_bot_enabled', "false"),
            telegram_bot_token=getattr(setting, 'telegram_bot_token', None),
            telegram_chat_id=getattr(setting, 'telegram_chat_id', None),
            telegram_proxy=getattr(setting, 'telegram_proxy', None),
            telegram_media_max_concurrent=getattr(setting, 'telegram_media_max_concurrent', 5) or 5,
            telegram_media_use_date_subdir=getattr(setting, 'telegram_media_use_date_subdir', "true"),

            # 企业微信应用Bot
            wecom_bot_enabled=getattr(setting, 'wecom_bot_enabled', "false"),
            wecom_corp_id=getattr(setting, 'wecom_corp_id', None),
            wecom_agent_id=getattr(setting, 'wecom_agent_id', None),
            wecom_secret=getattr(setting, 'wecom_secret', None),
            wecom_callback_token=getattr(setting, 'wecom_callback_token', None),
            wecom_callback_aes_key=getattr(setting, 'wecom_callback_aes_key', None),
            wecom_callback_url=getattr(setting, 'wecom_callback_url', None),
            wecom_api_proxy=getattr(setting, 'wecom_api_proxy', None),

            # Bark
            bark_enabled=getattr(setting, 'bark_enabled', "false"),
            bark_server_url=getattr(setting, 'bark_server_url', None),
            bark_device_key=getattr(setting, 'bark_device_key', None),
            bark_sound=getattr(setting, 'bark_sound', None),
            bark_group=getattr(setting, 'bark_group', None),
            bark_icon=getattr(setting, 'bark_icon', None),
            bark_url=getattr(setting, 'bark_url', None),
            bark_automatically_copy=getattr(setting, 'bark_automatically_copy', "false"),

            created_at=setting.created_at,
            updated_at=setting.updated_at
        )

    except Exception as e:
        logger.error(f"获取通知设置异常: {str(e)}")
        raise HTTPException(status_code=500, detail=f"获取通知设置失败: {str(e)}")

@router.put("/settings", response_model=NotificationSettingResponse)
async def update_notification_settings(
    settings: NotificationSettingUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """更新用户通知设置"""
    try:
        setting = db.query(NotificationSetting).filter(
            NotificationSetting.user_id == current_user.id
        ).first()
        
        if not setting:
            # 创建新设置
            setting = NotificationSetting(
                id=str(uuid.uuid4()),
                user_id=current_user.id
            )
            db.add(setting)
        
        # 更新设置字段
        update_data = settings.dict(exclude_unset=True)

        # 安全加固：启用 Telegram Bot 时，必须同时配置 Token 与 Chat ID 白名单
        desired_telegram_enabled = str(
            update_data.get('telegram_bot_enabled', getattr(setting, 'telegram_bot_enabled', "false"))
        ).lower() == "true"
        desired_telegram_token = str(
            update_data.get('telegram_bot_token', getattr(setting, 'telegram_bot_token', '') or '')
        ).strip()
        desired_telegram_chat_id = str(
            update_data.get('telegram_chat_id', getattr(setting, 'telegram_chat_id', '') or '')
        ).strip()

        if desired_telegram_enabled:
            if not desired_telegram_token:
                raise HTTPException(status_code=400, detail="启用 Telegram Bot 失败：请先配置 Bot Token")
            if not desired_telegram_chat_id:
                raise HTTPException(status_code=400, detail="启用 Telegram Bot 失败：请先配置 Chat ID 白名单")

        desired_bark_enabled = str(
            update_data.get('bark_enabled', getattr(setting, 'bark_enabled', "false"))
        ).lower() == "true"
        desired_bark_key = str(
            update_data.get('bark_device_key', getattr(setting, 'bark_device_key', '') or '')
        ).strip()
        if desired_bark_enabled and not desired_bark_key:
            raise HTTPException(status_code=400, detail="启用 Bark 失败：请先配置设备 Key")

        for field, value in update_data.items():
            setattr(setting, field, value)
        
        setting.updated_at = datetime.now()
        db.commit()
        db.refresh(setting)
        
        # 如果更新了相关配置，重载 Telegram Bot
        if any(k in update_data for k in ['telegram_bot_enabled', 'telegram_bot_token', 'telegram_chat_id', 'telegram_proxy']):
            try:
                from routers.telegram_bot import telegram_bot
                # 使用 create_task 避免阻塞 API 响应
                asyncio.create_task(telegram_bot.reload())
                logger.info("已触发 Telegram Bot 配置重载")
            except Exception as e:
                logger.error(f"重载 Telegram Bot 失败: {e}")

        # 如果更新了相关配置，重载企业微信Bot
        if any(k in update_data for k in ['wecom_bot_enabled', 'wecom_corp_id', 'wecom_agent_id', 'wecom_secret', 'wecom_callback_token', 'wecom_callback_aes_key']):
            try:
                from routers.wecom_bot import wecom_bot
                asyncio.create_task(wecom_bot.reload())
                logger.info("已触发企业微信Bot配置重载")
            except Exception as e:
                logger.error(f"重载企业微信Bot 失败: {e}")
        
        return NotificationSettingResponse(
            id=setting.id,
            user_id=setting.user_id,
            wechat_bot_enabled=setting.wechat_bot_enabled,
            wechat_webhook_url=setting.wechat_webhook_url,
            media_server_enabled=getattr(setting, 'media_server_enabled', "false"),
            media_server_type=getattr(setting, 'media_server_type', "jellyfin"),
            media_server_url=getattr(setting, 'media_server_url', None),
            media_server_api_key=getattr(setting, 'media_server_api_key', None),
            serverchan3_enabled=getattr(setting, 'serverchan3_enabled', "false"),
            serverchan3_uid=getattr(setting, 'serverchan3_uid', None),
            serverchan3_sendkey=getattr(setting, 'serverchan3_sendkey', None),
            email_enabled=setting.email_enabled,
            email_address=setting.email_address,
            web_push_enabled=setting.web_push_enabled,
            websocket_enabled=setting.websocket_enabled,
            download_completed_enabled=setting.download_completed_enabled,
            download_error_enabled=setting.download_error_enabled,

            subscription_check_failed_enabled=getattr(setting, 'subscription_check_failed_enabled', "true"),
            subscription_check_new_videos_enabled=getattr(setting, 'subscription_check_new_videos_enabled', "true"),
            subscription_check_no_new_videos_enabled=getattr(setting, 'subscription_check_no_new_videos_enabled', "false"),
            system_status_enabled=getattr(setting, 'system_status_enabled', "true"),
            quiet_hours_enabled=setting.quiet_hours_enabled,
            quiet_hours_start=setting.quiet_hours_start,
            quiet_hours_end=setting.quiet_hours_end,

            # Telegram 机器人配置
            telegram_bot_enabled=getattr(setting, 'telegram_bot_enabled', "false"),
            telegram_bot_token=getattr(setting, 'telegram_bot_token', None),
            telegram_chat_id=getattr(setting, 'telegram_chat_id', None),
            telegram_proxy=getattr(setting, 'telegram_proxy', None),
            telegram_media_max_concurrent=getattr(setting, 'telegram_media_max_concurrent', 5) or 5,
            telegram_media_use_date_subdir=getattr(setting, 'telegram_media_use_date_subdir', "true"),

            # 企业微信应用Bot
            wecom_bot_enabled=getattr(setting, 'wecom_bot_enabled', "false"),
            wecom_corp_id=getattr(setting, 'wecom_corp_id', None),
            wecom_agent_id=getattr(setting, 'wecom_agent_id', None),
            wecom_secret=getattr(setting, 'wecom_secret', None),
            wecom_callback_token=getattr(setting, 'wecom_callback_token', None),
            wecom_callback_aes_key=getattr(setting, 'wecom_callback_aes_key', None),
            wecom_callback_url=getattr(setting, 'wecom_callback_url', None),
            wecom_api_proxy=getattr(setting, 'wecom_api_proxy', None),

            # Bark
            bark_enabled=getattr(setting, 'bark_enabled', "false"),
            bark_server_url=getattr(setting, 'bark_server_url', None),
            bark_device_key=getattr(setting, 'bark_device_key', None),
            bark_sound=getattr(setting, 'bark_sound', None),
            bark_group=getattr(setting, 'bark_group', None),
            bark_icon=getattr(setting, 'bark_icon', None),
            bark_url=getattr(setting, 'bark_url', None),
            bark_automatically_copy=getattr(setting, 'bark_automatically_copy', "false"),

            created_at=setting.created_at,
            updated_at=setting.updated_at
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"更新通知设置异常: {str(e)}")
        raise HTTPException(status_code=500, detail=f"更新通知设置失败: {str(e)}")

# 微信机器人测试接口
@router.post("/test/wechat-bot")
async def test_wechat_bot(
    test_request: WechatBotTestRequest,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user)
):
    """测试微信机器人配置"""
    try:
        # 构建普通文本格式的测试消息（普通微信不支持Markdown）
        current_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        text_message = f"""🧪 测试消息

{test_request.message}"""
        
        # 异步发送测试消息
        background_tasks.add_task(
            NotificationService.send_wechat_bot_message,
            test_request.webhook_url,
            text_message,
            "text"  # 使用普通文本格式
        )
        
        return {
            "success": True,
            "message": "测试消息已发送，请检查微信机器人是否收到消息"
        }
        
    except Exception as e:
        logger.error(f"测试微信机器人异常: {str(e)}")
        raise HTTPException(status_code=500, detail=f"测试微信机器人失败: {str(e)}")

# 企业微信应用Bot测试接口
@router.post("/test/wecom-bot")
async def test_wecom_bot(
    test_request: WecomBotTestRequest,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user)
):
    """测试企业微信应用Bot配置"""
    try:
        background_tasks.add_task(
            NotificationService.send_wecom_bot_message,
            test_request.corp_id,
            test_request.agent_id,
            test_request.secret,
            "@all",
            test_request.message,
            "text"
        )
        return {
            "success": True,
            "message": "测试消息已发送，请检查企业微信是否收到消息"
        }
    except Exception as e:
        logger.error(f"测试企业微信Bot异常: {str(e)}")
        raise HTTPException(status_code=500, detail=f"测试企业微信Bot失败: {str(e)}")

# Server酱³测试接口
@router.post("/test/serverchan3")
async def test_serverchan3(
    test_request: ServerChan3TestRequest,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user)
):
    """测试Server酱³配置"""
    try:
        # 直接传入原始消息内容，让 send_serverchan3_message 方法内部进行格式化
        background_tasks.add_task(
            NotificationService.send_serverchan3_message,
            test_request.uid,
            test_request.sendkey,
            f"🧪 测试消息",
            test_request.message,  # 传入原始消息内容
            None  # 测试时不使用头像
        )
        
        return {
            "success": True,
            "message": "测试消息已发送，请检查Server酱³ APP是否收到消息"
        }
        
    except Exception as e:
        logger.error(f"测试Server酱³异常: {str(e)}")
        raise HTTPException(status_code=500, detail=f"测试Server酱³失败: {str(e)}")

# Telegram Bot 测试接口
@router.post("/test/telegram-bot")
async def test_telegram_bot(
    test_request: TelegramBotTestRequest,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user)
):
    """测试 Telegram Bot 配置"""
    try:
        from routers.telegram_bot import telegram_bot
        
        # 暂时覆盖配置进行测试
        original_token = telegram_bot.token
        original_proxy = telegram_bot.proxy
        
        telegram_bot.token = test_request.token
        telegram_bot.proxy = test_request.proxy
        
        # 如果chat_id包含逗号，分割并发送给所有人
        targets = [cid.strip() for cid in test_request.chat_id.split(',') if cid.strip()]
        
        async def _send_test():
            try:
                msg = f"🧪 *Telegram Bot 测试*\n\n{test_request.message}"
                for tid in targets:
                    await telegram_bot.send_message(tid, msg)
            finally:
                # 恢复原来的配置（非线程安全，但在简单测试场景下可接受，更严谨的做法是实例化一个新的临时service）
                telegram_bot.token = original_token
                telegram_bot.proxy = original_proxy

        background_tasks.add_task(_send_test)
        
        return {
            "success": True,
            "message": "测试消息已发送到 Telegram"
        }
        
    except Exception as e:
        logger.error(f"测试 Telegram Bot 异常: {str(e)}")
        raise HTTPException(status_code=500, detail=f"测试 Telegram Bot 失败: {str(e)}")

# Bark 测试接口
@router.post("/test/bark")
async def test_bark(
    test_request: BarkTestRequest,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user)
):
    """测试 Bark 配置"""
    try:
        background_tasks.add_task(
            NotificationService.send_bark_message,
            test_request.server_url,
            test_request.device_key,
            test_request.title,
            test_request.message,
            test_request.sound,
            test_request.group,
            test_request.icon,
            test_request.url,
            test_request.automatically_copy
        )
        return {
            "success": True,
            "message": "测试消息已发送，请在 Bark App 中确认"
        }
    except Exception as e:
        logger.error(f"测试 Bark 异常: {str(e)}")
        raise HTTPException(status_code=500, detail=f"测试 Bark 失败: {str(e)}")

# 媒体服务器连接测试接口
@router.post("/test/media-server")
async def test_media_server_connection(
    request: dict,
    current_user: User = Depends(get_current_user)
):
    """测试媒体服务器连接和API密钥有效性"""
    try:
        server_url = request.get("server_url")
        api_key = request.get("api_key")
        server_type = request.get("server_type", "jellyfin")
        
        if not server_url or not api_key:
            raise HTTPException(status_code=400, detail="服务器地址和API密钥不能为空")
        
        # 调用测试方法
        result = await NotificationService.test_media_server_connection(
            server_url=server_url,
            api_key=api_key,
            server_type=server_type
        )
        
        return result
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"测试媒体服务器连接异常: {str(e)}")
        raise HTTPException(status_code=500, detail=f"测试媒体服务器连接失败: {str(e)}")

# 便捷通知接口
@router.post("/download-completed")
async def notify_download_completed(
    request: dict,
    background_tasks: BackgroundTasks
):
    """下载完成通知"""
    title = request.get("title")
    content = request.get("content")
    user_id = request.get("user_id")
    extra_data = request.get("extra_data")  # 获取额外数据（包含封面图路径）

    # 统一补充文件大小（若可解析到本地文件/目录）
    try:
        content, extra_data = _enrich_download_completed_with_file_size(content, extra_data)
    except Exception as e:
        logger.warning(f"补充下载文件大小信息失败（不影响主流程）: {e}")
    
    if not all([title, content, user_id]):
        return {"success": False, "message": "缺少必要参数: title, content, user_id"}
    """下载完成通知"""
    try:
        with _db_session_scope() as db:
            # 检查用户是否启用了下载完成通知
            setting = db.query(NotificationSetting).filter(
                and_(
                    NotificationSetting.user_id == user_id,
                    NotificationSetting.download_completed_enabled == "true"
                )
            ).first()
            
            # 如果找不到用户设置，尝试使用系统默认设置
            if not setting:
                # 查找第一个启用了通知的用户设置作为默认值（支持多渠道）
                default_setting = db.query(NotificationSetting).filter(
                    and_(
                        NotificationSetting.download_completed_enabled == "true",
                        or_(
                            and_(
                                NotificationSetting.wechat_bot_enabled == "true",
                                NotificationSetting.wechat_webhook_url.isnot(None)
                            ),
                            and_(
                                NotificationSetting.serverchan3_enabled == "true",
                                NotificationSetting.serverchan3_uid.isnot(None),
                                NotificationSetting.serverchan3_sendkey.isnot(None)
                            ),
                            and_(
                                NotificationSetting.email_enabled == "true",
                                NotificationSetting.email_address.isnot(None)
                            ),
                            and_(
                                NotificationSetting.bark_enabled == "true",
                                NotificationSetting.bark_device_key.isnot(None)
                            ),
                            NotificationSetting.web_push_enabled == "true",
                            NotificationSetting.websocket_enabled == "true"
                        )
                    )
                ).first()
                
                if default_setting:
                    setting = default_setting
                    user_id = default_setting.user_id  # 使用默认用户的ID
                    logger.info(f"使用默认用户 {user_id} 的通知设置发送下载完成通知")
                else:
                    return {"success": False, "message": "未找到可用的通知设置"}
            
            # 检查是否有可用的通知渠道
            has_available_channel = (
                (setting.wechat_bot_enabled == "true" and setting.wechat_webhook_url) or
                (setting.serverchan3_enabled == "true" and setting.serverchan3_uid and setting.serverchan3_sendkey) or
                (setting.email_enabled == "true" and setting.email_address) or
                (getattr(setting, 'bark_enabled', "false") == "true" and getattr(setting, 'bark_device_key', None)) or
                setting.web_push_enabled == "true" or
                setting.websocket_enabled == "true"
            )
            
            if not has_available_channel:
                return {"success": False, "message": "用户未启用任何通知渠道"}
            
            # 创建通知（使用默认渠道，实际发送时会多渠道推送）
            notification = await NotificationService.create_notification(
                db=db,
                notification_type=NotificationType.DOWNLOAD_COMPLETED.value,
                title=title,
                content=content,
                user_id=user_id,
                channel=NotificationChannel.WECHAT_BOT.value,  # 默认渠道，实际发送时会多渠道推送
                priority=2,
                extra_data=extra_data  # 传递额外数据（包含封面图路径）
            )
            
            # 发送通知（多渠道同步推送）
            await NotificationService.send_notification(db, notification, background_tasks)

            # 下载成功后触发媒体库刷新（可选，依据用户设置）
            try:
                if getattr(setting, 'media_server_enabled', "false") == "true" and getattr(setting, 'media_server_url', None) and getattr(setting, 'media_server_api_key', None):
                    server_url = getattr(setting, 'media_server_url')
                    api_key = getattr(setting, 'media_server_api_key')
                    server_type = getattr(setting, 'media_server_type', 'jellyfin')

                    # 节流：冷却窗口内合并刷新，避免 IO 峰值
                    if await _should_trigger_media_refresh(server_url):
                        background_tasks.add_task(
                            NotificationService.refresh_media_library,
                            server_url,
                            api_key,
                            server_type
                        )
                        logger.debug(f"媒体库刷新任务已加入后台队列: {_normalize_server_url(server_url)} ({server_type})")
                    else:
                        logger.debug(f"媒体库刷新已节流（冷却{_MEDIA_REFRESH_COOLDOWN_SECONDS}s内合并）: {_normalize_server_url(server_url)}")
            except Exception as e:
                logger.warning(f"加入媒体库刷新任务失败: {str(e)}")

            return {"success": True, "message": "下载完成通知已发送"}
        
    except Exception as e:
        logger.error(f"发送下载完成通知异常: {str(e)}")
        return {"success": False, "message": f"发送通知失败: {str(e)}"}

@router.post("/download-error")
async def notify_download_error(
    request: dict,
    background_tasks: BackgroundTasks
):
    """下载错误通知"""
    title = request.get("title")
    content = request.get("content")
    user_id = request.get("user_id")
    extra_data = request.get("extra_data")
    
    if not all([title, content, user_id]):
        return {"success": False, "message": "缺少必要参数: title, content, user_id"}
    """下载错误通知"""
    try:
        with _db_session_scope() as db:
            # 检查用户是否启用了下载错误通知
            setting = db.query(NotificationSetting).filter(
                and_(
                    NotificationSetting.user_id == user_id,
                    NotificationSetting.download_error_enabled == "true"
                )
            ).first()
            
            # 如果找不到用户设置，尝试使用系统默认设置
            if not setting:
                # 查找第一个启用了通知的用户设置作为默认值（支持多渠道）
                default_setting = db.query(NotificationSetting).filter(
                    and_(
                        NotificationSetting.download_error_enabled == "true",
                        or_(
                            and_(
                                NotificationSetting.wechat_bot_enabled == "true",
                                NotificationSetting.wechat_webhook_url.isnot(None)
                            ),
                            and_(
                                NotificationSetting.serverchan3_enabled == "true",
                                NotificationSetting.serverchan3_uid.isnot(None),
                                NotificationSetting.serverchan3_sendkey.isnot(None)
                            ),
                            and_(
                                NotificationSetting.email_enabled == "true",
                                NotificationSetting.email_address.isnot(None)
                            ),
                            and_(
                                NotificationSetting.bark_enabled == "true",
                                NotificationSetting.bark_device_key.isnot(None)
                            ),
                            NotificationSetting.web_push_enabled == "true",
                            NotificationSetting.websocket_enabled == "true"
                        )
                    )
                ).first()
                
                if default_setting:
                    setting = default_setting
                    user_id = default_setting.user_id  # 使用默认用户的ID
                    logger.info(f"使用默认用户 {user_id} 的通知设置发送下载错误通知")
                else:
                    return {"success": False, "message": "未找到可用的通知设置"}
            
            # 检查是否有可用的通知渠道
            has_available_channel = (
                (setting.wechat_bot_enabled == "true" and setting.wechat_webhook_url) or
                (setting.serverchan3_enabled == "true" and setting.serverchan3_uid and setting.serverchan3_sendkey) or
                (setting.email_enabled == "true" and setting.email_address) or
                (getattr(setting, 'bark_enabled', "false") == "true" and getattr(setting, 'bark_device_key', None)) or
                setting.web_push_enabled == "true" or
                setting.websocket_enabled == "true"
            )
            
            if not has_available_channel:
                return {"success": False, "message": "用户未启用任何通知渠道"}
            
            # 创建通知（使用默认渠道，实际发送时会多渠道推送）
            notification = await NotificationService.create_notification(
                db=db,
                notification_type=NotificationType.DOWNLOAD_ERROR.value,
                title=title,
                content=content,
                user_id=user_id,
                channel=NotificationChannel.WECHAT_BOT.value,  # 默认渠道，实际发送时会多渠道推送
                priority=4,  # 错误通知优先级较高
                extra_data=extra_data
            )
            
            # 发送通知（多渠道同步推送）
            await NotificationService.send_notification(db, notification, background_tasks)
            
            return {"success": True, "message": "下载错误通知已发送"}
        
    except Exception as e:
        logger.error(f"发送下载错误通知异常: {str(e)}")
        return {"success": False, "message": f"发送通知失败: {str(e)}"}

@router.post("/subscription-check")
async def notify_subscription_check(
    request: dict,
    background_tasks: BackgroundTasks
):
    """订阅检测通知"""
    title = request.get("title")
    content = request.get("content")
    user_id = request.get("user_id")
    notification_type = request.get("type", "subscription_check_success")
    extra_data = request.get("extra_data", {})  # 获取额外数据，包含博主信息
    
    if not all([title, content, user_id]):
        return {"success": False, "message": "缺少必要参数: title, content, user_id"}
    
    try:
        with _db_session_scope() as db:
            # 根据通知类型检查对应的用户设置
            if notification_type == "subscription_check_success":
                setting_filter = NotificationSetting.subscription_check_success_enabled == "true"
            elif notification_type == "subscription_check_failed":
                setting_filter = NotificationSetting.subscription_check_failed_enabled == "true"
            elif notification_type == "subscription_check_new_videos":
                setting_filter = NotificationSetting.subscription_check_new_videos_enabled == "true"
            elif notification_type == "subscription_check_no_new_videos":
                setting_filter = NotificationSetting.subscription_check_no_new_videos_enabled == "true"
            else:
                # 默认使用成功通知设置
                setting_filter = NotificationSetting.subscription_check_success_enabled == "true"
            
            setting = db.query(NotificationSetting).filter(
                and_(
                    NotificationSetting.user_id == user_id,
                    setting_filter
                )
            ).first()
            
            # 如果找不到用户设置，尝试使用系统默认设置
            if not setting:
                # 查找第一个启用了通知的用户设置作为默认值（支持多渠道）
                default_setting = db.query(NotificationSetting).filter(
                    and_(
                        setting_filter,
                        or_(
                            and_(
                                NotificationSetting.wechat_bot_enabled == "true",
                                NotificationSetting.wechat_webhook_url.isnot(None)
                            ),
                            and_(
                                NotificationSetting.serverchan3_enabled == "true",
                                NotificationSetting.serverchan3_uid.isnot(None),
                                NotificationSetting.serverchan3_sendkey.isnot(None)
                            ),
                            and_(
                                NotificationSetting.email_enabled == "true",
                                NotificationSetting.email_address.isnot(None)
                            ),
                            and_(
                                NotificationSetting.bark_enabled == "true",
                                NotificationSetting.bark_device_key.isnot(None)
                            ),
                            NotificationSetting.web_push_enabled == "true",
                            NotificationSetting.websocket_enabled == "true"
                        )
                    )
                ).first()
                
                if default_setting:
                    setting = default_setting
                    user_id = default_setting.user_id  # 使用默认用户的ID
                    logger.info(f"使用默认用户 {user_id} 的通知设置发送订阅检测通知")
                else:
                    return {"success": False, "message": "未找到可用的通知设置"}
            
            # 检查是否有可用的通知渠道
            has_available_channel = (
                (setting.wechat_bot_enabled == "true" and setting.wechat_webhook_url) or
                (setting.serverchan3_enabled == "true" and setting.serverchan3_uid and setting.serverchan3_sendkey) or
                (setting.email_enabled == "true" and setting.email_address) or
                (getattr(setting, 'bark_enabled', "false") == "true" and getattr(setting, 'bark_device_key', None)) or
                setting.web_push_enabled == "true" or
                setting.websocket_enabled == "true"
            )
            
            if not has_available_channel:
                return {"success": False, "message": "用户未启用任何通知渠道"}
            
            # 根据通知类型设置优先级
            if notification_type == "subscription_check_new_videos":
                priority = 3  # 发现新视频通知优先级较高
            elif notification_type == "subscription_check_no_new_videos":
                priority = 1  # 未发现新视频通知优先级较低
            elif notification_type == "subscription_check_failed":
                priority = 4  # 失败通知优先级最高
            else:
                priority = 2  # 默认优先级
            
            # 创建通知（使用默认渠道，实际发送时会多渠道推送）
            notification = await NotificationService.create_notification(
                db=db,
                notification_type=notification_type,
                title=title,
                content=content,
                user_id=user_id,
                channel=NotificationChannel.WECHAT_BOT.value,  # 默认渠道，实际发送时会多渠道推送
                priority=priority,
                extra_data=extra_data  # 传递额外数据，包含博主信息
            )
            
            # 发送通知（多渠道同步推送）
            await NotificationService.send_notification(db, notification, background_tasks)
            
            return {"success": True, "message": "订阅检测通知已发送"}
        
    except Exception as e:
        logger.error(f"发送订阅检测通知异常: {str(e)}")
        return {"success": False, "message": f"发送通知失败: {str(e)}"}
