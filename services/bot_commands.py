"""
共享业务逻辑层 - Telegram Bot 和企业微信 Bot 共用
所有业务逻辑返回纯数据，由各平台适配层负责格式化消息
"""
import asyncio
import logging
import re
import uuid
from datetime import datetime
from typing import Optional, Dict, Any, List

logger = logging.getLogger(__name__)


# ==================== 查询类命令 ====================

async def check_license() -> Dict[str, Any]:
    """查授权"""
    try:
        from routers.license import license_manager, LicenseStatus
        status = license_manager.status
        remaining = license_manager.remaining_days
        is_lifetime = license_manager.is_lifetime

        if status == LicenseStatus.VALID:
            if is_lifetime:
                return {"success": True, "type": "lifetime", "status": "valid"}
            elif remaining > 0:
                return {"success": True, "type": "normal", "status": "valid", "remaining_days": remaining}
            else:
                return {"success": True, "type": "normal", "status": "valid"}
        elif status == LicenseStatus.EXPIRED:
            return {"success": True, "status": "expired"}
        else:
            return {"success": True, "status": "invalid"}
    except Exception as e:
        return {"success": False, "error": str(e)}


async def check_tasks() -> Dict[str, Any]:
    """查任务"""
    try:
        from sql.database_postgresql import get_session
        from sql.models import Task, TaskStatus
        db = get_session()
        try:
            total = db.query(Task).count()
            downloading = db.query(Task).filter(Task.status == TaskStatus.DOWNLOADING.value).count()
            pending = db.query(Task).filter(Task.status == TaskStatus.PENDING.value).count()
            completed = db.query(Task).filter(Task.status == TaskStatus.COMPLETED.value).count()
            failed = db.query(Task).filter(Task.status == TaskStatus.ERROR.value).count()
            return {
                "success": True,
                "total": total,
                "downloading": downloading,
                "pending": pending,
                "completed": completed,
                "failed": failed,
            }
        finally:
            db.close()
    except Exception as e:
        return {"success": False, "error": str(e)}


async def check_status() -> Dict[str, Any]:
    """查系统状态"""
    try:
        import psutil
        from sql.database_postgresql import get_session
        from sql.models import Task, TaskStatus, Subscription, LiveSubscription

        cpu = psutil.cpu_percent(interval=1)
        mem = psutil.virtual_memory()
        disk = psutil.disk_usage("/")

        db = get_session()
        try:
            downloading = db.query(Task).filter(Task.status == TaskStatus.DOWNLOADING.value).count()
            pending = db.query(Task).filter(Task.status == TaskStatus.PENDING.value).count()
            total_tasks = db.query(Task).count()
            subs = db.query(Subscription).filter(Subscription.status == "active").count()
            lives = db.query(LiveSubscription).count()
            recording = db.query(LiveSubscription).filter(LiveSubscription.is_recording == "true").count()
        finally:
            db.close()

        from routers.license import license_manager, LicenseStatus
        lic_valid = license_manager.status == LicenseStatus.VALID
        lic_lifetime = license_manager.is_lifetime
        lic_remaining = license_manager.remaining_days

        return {
            "success": True,
            "cpu": cpu,
            "mem_percent": mem.percent,
            "mem_used_gb": mem.used // (1024 ** 3),
            "mem_total_gb": mem.total // (1024 ** 3),
            "disk_percent": disk.percent,
            "disk_used_gb": disk.used // (1024 ** 3),
            "disk_total_gb": disk.total // (1024 ** 3),
            "downloading": downloading,
            "pending": pending,
            "total_tasks": total_tasks,
            "subs": subs,
            "lives": lives,
            "recording": recording,
            "license_valid": lic_valid,
            "license_lifetime": lic_lifetime,
            "license_remaining": lic_remaining,
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


async def check_subscriptions() -> Dict[str, Any]:
    """查订阅"""
    try:
        from sql.database_postgresql import get_session
        from sql.models import Subscription
        db = get_session()
        try:
            subs = db.query(Subscription).all()
            items = []
            for sub in subs[:20]:
                items.append({
                    "id": sub.id[:8],
                    "status": sub.status,
                    "name": sub.nickname or sub.url[:30] if hasattr(sub, 'nickname') else sub.url[:30],
                    "url": sub.url,
                })
            return {"success": True, "total": len(subs), "items": items}
        finally:
            db.close()
    except Exception as e:
        return {"success": False, "error": str(e)}


async def check_live_subscriptions() -> Dict[str, Any]:
    """查直播订阅"""
    try:
        from sql.database_postgresql import get_session
        from sql.models import LiveSubscription
        db = get_session()
        try:
            lives = db.query(LiveSubscription).all()
            items = []
            for live in lives[:20]:
                items.append({
                    "id": live.id[:8],
                    "is_recording": live.is_recording == "true",
                    "anchor_name": live.anchor_name or live.room_url[:30],
                    "platform": live.platform,
                })
            return {"success": True, "total": len(lives), "items": items}
        finally:
            db.close()
    except Exception as e:
        return {"success": False, "error": str(e)}


async def check_failed_tasks() -> Dict[str, Any]:
    """查失败任务"""
    try:
        from sql.database_postgresql import get_session
        from sql.models import Task, TaskStatus
        db = get_session()
        try:
            failed_tasks = db.query(Task).filter(
                Task.status == TaskStatus.ERROR.value
            ).order_by(Task.created_at.desc()).limit(10).all()
            items = []
            for t in failed_tasks:
                items.append({
                    "id": t.id[:8],
                    "title": t.title or t.url[:30] if hasattr(t, 'title') and t.title else (t.url[:30] if t.url else "未知"),
                    "error": t.error_message[:50] if t.error_message else "未知错误",
                })
            return {"success": True, "total": len(failed_tasks), "items": items}
        finally:
            db.close()
    except Exception as e:
        return {"success": False, "error": str(e)}


# ==================== 操作类命令 ====================

async def download_url(url: str) -> Dict[str, Any]:
    """下载单个视频"""
    try:
        from sql.database_postgresql import get_session
        from sql.models import Task, TaskStatus
        from routers.downloader import download_manager

        # 清洗 URL
        url = url.split("?")[0] if "?" in url and len(url) > 200 else url

        # 识别来源
        source = "others"
        if "douyin.com" in url or "tiktok.com" in url:
            source = "douyin"
        elif "bilibili.com" in url or "b23.tv" in url:
            source = "bilibili"
        elif "youtube.com" in url or "youtu.be" in url:
            source = "youtube"
        elif "xiaohongshu.com" in url or "xhslink.com" in url:
            source = "xiaohongshu"
        elif "kuaishou.com" in url:
            source = "kuaishou"

        task_id = str(uuid.uuid4())
        db = get_session()
        try:
            new_task = Task(
                id=task_id,
                url=url,
                original_url=url,
                source=source,
                title=url,
                status=TaskStatus.PENDING.value,
                created_at=datetime.now(),
                updated_at=datetime.now(),
            )
            db.add(new_task)
            db.commit()
            await download_manager.add_download_task(task_id)
            return {"success": True, "task_id": task_id[:8], "source": source, "url": url[:50]}
        finally:
            db.close()
    except Exception as e:
        return {"success": False, "error": str(e)}


async def add_subscription(url: str) -> Dict[str, Any]:
    """添加订阅"""
    try:
        from routers.license import license_manager
        if not await license_manager.is_active_for("bot.subscribe"):
            return {"success": False, "error": "订阅功能是高级功能，授权无效或已过期。"}

        from routers.subscribe.subscription import add_subscription as _add_sub
        from sql.models import SubscriptionCreate, Platform

        platform = None
        if "douyin.com" in url or "v.douyin.com" in url:
            platform = Platform.douyin
        elif "bilibili.com" in url or "b23.tv" in url:
            platform = Platform.bilibili
        elif "youtube.com" in url or "youtu.be" in url:
            platform = Platform.youtube
        elif "xiaohongshu.com" in url or "xhslink.com" in url:
            platform = Platform.xiaohongshu
        elif "tiktok.com" in url:
            platform = Platform.tiktok
        elif "instagram.com" in url:
            platform = Platform.instagram
        elif "music.163.com" in url:
            platform = Platform.netease

        sub_create = SubscriptionCreate(url=url, platform=platform, auto_download=True)
        result = await _add_sub(sub_create)
        if result:
            name = getattr(result, 'nickname', None) or getattr(result, 'url', url[:40])
            return {"success": True, "name": name, "platform": str(platform) if platform else "自动识别"}
        return {"success": False, "error": "添加失败"}
    except Exception as e:
        return {"success": False, "error": str(e)}


async def add_live_subscription(url: str) -> Dict[str, Any]:
    """添加直播录制订阅"""
    try:
        from routers.license import license_manager
        if not await license_manager.is_active_for("bot.add_live_subscription"):
            return {"success": False, "error": "直播订阅功能是高级功能，授权无效或已过期。"}

        from live import adapters
        from sql.models import LiveSubscription
        from live.danmu import is_danmu_supported
        from sql.database_postgresql import get_session

        adapter = adapters.get_adapter(url)
        if not adapter:
            if "douyin.com" in url or "iesdouyin.com" in url:
                adapter = adapters.get_adapter_by_platform("douyin")
            elif "bilibili.com" in url or "b23.tv" in url:
                adapter = adapters.get_adapter_by_platform("bilibili")
            elif "xiaohongshu.com" in url or "xhslink.com" in url:
                adapter = adapters.get_adapter_by_platform("xhs")
            elif "huya.com" in url:
                adapter = adapters.get_adapter_by_platform("huya")
            elif "kuaishou.com" in url:
                adapter = adapters.get_adapter_by_platform("kuaishou")
            elif "douyu.com" in url:
                adapter = adapters.get_adapter_by_platform("douyu")
            elif "twitch.tv" in url:
                adapter = adapters.get_adapter_by_platform("twitch")

        if not adapter:
            return {"success": False, "error": "无法识别的直播链接，目前支持：抖音、B站、快手、虎牙、小红书、斗鱼、Twitch"}

        platform_name = adapter.platform_name
        info = await adapter.get_room_info(url)
        anchor_name = info.get("anchor_name", "未知主播")
        room_id = info.get("room_id")
        avatar_url = info.get("avatar_url")

        if not room_id and not anchor_name:
            return {"success": False, "error": "无法获取直播间信息"}

        db = get_session()
        try:
            existing = db.query(LiveSubscription).filter(
                LiveSubscription.platform == platform_name,
                LiveSubscription.room_url == url
            ).first()
            if existing:
                return {"success": False, "error": f"该直播间已存在: {existing.anchor_name}"}

            new_sub = LiveSubscription(
                id=str(uuid.uuid4()),
                platform=platform_name,
                room_url=url,
                room_id=str(room_id) if room_id else "",
                anchor_name=anchor_name,
                avatar_url=avatar_url,
                quality="原画",
                auto_record="true",
                check_interval=60,
                notification_enabled="true",
                extra_data=__import__('json').dumps({"danmu_enabled": is_danmu_supported(platform_name)}),
            )
            db.add(new_sub)
            db.commit()
            db.refresh(new_sub)

            from live.scheduler import live_scheduler
            await live_scheduler.add_monitor(
                subscription_id=new_sub.id,
                room_url=new_sub.room_url,
                platform=new_sub.platform,
                check_interval=new_sub.check_interval or 60,
            )
            return {"success": True, "anchor_name": anchor_name, "platform": platform_name}
        finally:
            db.close()
    except Exception as e:
        return {"success": False, "error": str(e)}


async def retry_task(task_id: str) -> Dict[str, Any]:
    """重试失败任务"""
    try:
        from sql.database_postgresql import get_session
        from sql.models import Task, TaskStatus
        from routers.downloader import download_manager
        db = get_session()
        try:
            task = db.query(Task).filter(Task.id.startswith(task_id)).first()
            if not task:
                return {"success": False, "error": f"未找到任务: {task_id}"}
            task.status = TaskStatus.PENDING.value
            task.error_message = None
            task.updated_at = datetime.now()
            db.commit()
            await download_manager.add_download_task(task.id)
            return {"success": True, "task_id": task.id[:8], "url": task.url[:50]}
        finally:
            db.close()
    except Exception as e:
        return {"success": False, "error": str(e)}


async def delete_task(task_id: str) -> Dict[str, Any]:
    """删除任务"""
    try:
        from sql.database_postgresql import get_session
        from sql.models import Task
        db = get_session()
        try:
            task = db.query(Task).filter(Task.id.startswith(task_id)).first()
            if not task:
                return {"success": False, "error": f"未找到任务: {task_id}"}
            db.delete(task)
            db.commit()
            return {"success": True, "task_id": task.id[:8]}
        finally:
            db.close()
    except Exception as e:
        return {"success": False, "error": str(e)}


async def pause_subscription(sub_id: str) -> Dict[str, Any]:
    """暂停订阅"""
    try:
        from sql.database_postgresql import get_session
        from sql.models import Subscription
        db = get_session()
        try:
            sub = db.query(Subscription).filter(Subscription.id.startswith(sub_id)).first()
            if not sub:
                return {"success": False, "error": f"未找到订阅: {sub_id}"}
            sub.status = "paused"
            db.commit()
            return {"success": True, "name": sub.nickname or sub.url[:30]}
        finally:
            db.close()
    except Exception as e:
        return {"success": False, "error": str(e)}


async def resume_subscription(sub_id: str) -> Dict[str, Any]:
    """恢复订阅"""
    try:
        from sql.database_postgresql import get_session
        from sql.models import Subscription
        db = get_session()
        try:
            sub = db.query(Subscription).filter(Subscription.id.startswith(sub_id)).first()
            if not sub:
                return {"success": False, "error": f"未找到订阅: {sub_id}"}
            sub.status = "active"
            db.commit()
            return {"success": True, "name": sub.nickname or sub.url[:30]}
        finally:
            db.close()
    except Exception as e:
        return {"success": False, "error": str(e)}


async def delete_subscription(sub_id: str) -> Dict[str, Any]:
    """删除订阅"""
    try:
        from sql.database_postgresql import get_session
        from sql.models import Subscription
        db = get_session()
        try:
            sub = db.query(Subscription).filter(Subscription.id.startswith(sub_id)).first()
            if not sub:
                return {"success": False, "error": f"未找到订阅: {sub_id}"}
            db.delete(sub)
            db.commit()
            return {"success": True, "name": sub.nickname or sub.url[:30]}
        finally:
            db.close()
    except Exception as e:
        return {"success": False, "error": str(e)}


# ==================== URL 识别 ====================

def extract_url(text: str) -> Optional[str]:
    """从文本中提取第一个 URL"""
    urls = re.findall(r'https?://[^\s<>"\']+', text)
    return urls[0].rstrip("/") if urls else None


def classify_url(url: str) -> str:
    """识别 URL 类型: live / subscription / download"""
    url_lower = url.lower()
    # 直播 URL
    if any(x in url_lower for x in ["live.douyin", "live.bilibili", "huya.com", "kuaishou.com/live", "douyu.com", "twitch.tv"]):
        return "live"
    # 订阅 URL
    if any(x in url_lower for x in ["/user/", "/collection/", "/playlist/", "channel/", "/space/", "/profile/"]):
        return "subscription"
    return "download"


async def handle_url(url: str) -> Dict[str, Any]:
    """智能处理 URL"""
    url_type = classify_url(url)
    if url_type == "live":
        return await add_live_subscription(url)
    elif url_type == "subscription":
        return await add_subscription(url)
    else:
        return await download_url(url)
