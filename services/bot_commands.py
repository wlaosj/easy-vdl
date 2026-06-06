"""
共享业务逻辑层 - Telegram Bot 和企业微信 Bot 共用
所有业务逻辑返回纯数据，由各平台适配层负责格式化消息
"""
import asyncio
import logging
import os
import re
import uuid
from datetime import datetime, date
from typing import Optional, Dict, Any, List

logger = logging.getLogger(__name__)


# ==================== 短链解析 ====================

async def resolve_url(url: str) -> str:
    """解析短链接，返回真实 URL"""
    if not url:
        return url

    try:
        import aiohttp

        # 抖音短链
        if "v.douyin.com" in url and "/note/" not in url and "/video/" not in url:
            try:
                import httpx
                async with httpx.AsyncClient(follow_redirects=True, timeout=10.0) as client:
                    response = await client.head(url)
                    resolved = str(response.url)
                    logger.debug(f"抖音短链解析: {url} -> {resolved}")
                    return resolved
            except Exception as e:
                logger.warning(f"解析抖音短链失败: {e}")

        # 小红书短链
        elif "xhslink.com" in url:
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.get(url, allow_redirects=True, timeout=aiohttp.ClientTimeout(total=8)) as resp:
                        resolved = str(resp.url)
                        logger.debug(f"小红书短链解析: {url} -> {resolved}")
                        return resolved
            except Exception as e:
                logger.warning(f"解析小红书短链失败: {e}")

        # 快手短链
        elif "v.kuaishou.com" in url:
            try:
                headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
                async with aiohttp.ClientSession() as session:
                    async with session.get(url, headers=headers, allow_redirects=True, timeout=aiohttp.ClientTimeout(total=8)) as resp:
                        resolved = str(resp.url)
                        logger.debug(f"快手短链解析: {url} -> {resolved}")
                        return resolved
            except Exception as e:
                logger.warning(f"解析快手短链失败: {e}")

        # B站短链
        elif "b23.tv" in url:
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.get(url, allow_redirects=True, timeout=aiohttp.ClientTimeout(total=8)) as resp:
                        resolved = str(resp.url)
                        logger.debug(f"B站短链解析: {url} -> {resolved}")
                        return resolved
            except Exception as e:
                logger.warning(f"解析B站短链失败: {e}")

    except ImportError:
        pass

    return url


# ==================== URL 清洗 ====================

def clean_url(url: str) -> str:
    """清洗 URL，去除追踪参数"""
    if not url:
        return url
    # 小红书保留原始 URL（需要 auth 参数）
    if "xiaohongshu.com" in url or "xhslink.com" in url:
        return url
    from urllib.parse import urlparse, parse_qsl, urlencode, urlunparse
    parsed = urlparse(url)
    params = parse_qsl(parsed.query, keep_blank_values=True)
    # 基础保留参数
    keep_params = {"v", "id", "room_id", "p", "list", "type"}
    # Bilibili 特有参数
    if "bilibili.com" in url or "b23.tv" in url:
        keep_params.update({"bvid", "aid", "cid", "sid", "ep_id", "season_id"})
    # 抖音保留 room_id
    if "douyin.com" in url or "amemv.com" in url:
        keep_params.add("room_id")
    filtered = [(k, v) for k, v in params if k in keep_params]
    new_query = urlencode(filtered)
    return urlunparse((parsed.scheme, parsed.netloc, parsed.path, "", new_query, ""))


# ==================== 订阅类型检测 ====================

def detect_subscription_type(url: str) -> Optional[str]:
    """检测是否为订阅类链接，返回描述名称"""
    if not url:
        return None

    # 抖音合集
    if "douyin.com/collection/" in url or "/collection/" in url:
        return "抖音合集"
    # 抖音短链（排除 note/video，可能是博主主页或直播）
    if "v.douyin.com" in url and "/note/" not in url and "/video/" not in url:
        return "抖音博主主页"
    # 抖音博主主页
    if "douyin.com/user/" in url or "/user/" in url or "/share/user/" in url:
        return "抖音博主主页"
    # YouTube 播放列表
    if ("youtube.com" in url or "youtu.be" in url) and "list=" in url:
        return "YouTube播放列表"
    # YouTube 频道
    if ("youtube.com/@" in url or "youtube.com/c/" in url or "youtube.com/channel/" in url) and "list=" not in url and "/watch" not in url:
        return "YouTube频道主页"
    # B站收藏夹
    if "bilibili.com" in url and ("favlist" in url or "fid=" in url):
        return "B站收藏夹"
    # B站UP主主页
    if "space.bilibili.com" in url or "/space/" in url:
        return "B站UP主主页"
    # TikTok
    if "tiktok.com/@" in url and "/video/" not in url:
        return "TikTok博主主页"
    # 小红书
    if "xiaohongshu.com/user/profile/" in url or "xhslink.com" in url:
        if "/explore/" not in url and "/livestream" not in url:
            return "小红书博主主页"
    # Instagram
    if "instagram.com" in url and "/p/" not in url and "/reel/" not in url and "/stories/" not in url:
        return "Instagram博主主页"
    # 网易云歌单
    if "music.163.com" in url and ("playlist" in url or "id=" in url):
        return "网易云歌单"

    return None


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
                "success": True, "total": total, "downloading": downloading,
                "pending": pending, "completed": completed, "failed": failed,
            }
        finally:
            db.close()
    except Exception as e:
        return {"success": False, "error": str(e)}


def _get_dir_size(path: str) -> float:
    """获取目录大小 (GB)"""
    try:
        total = 0
        for dirpath, dirnames, filenames in os.walk(path):
            for f in filenames:
                fp = os.path.join(dirpath, f)
                if os.path.exists(fp):
                    total += os.path.getsize(fp)
        return total / (1024 ** 3)
    except Exception:
        return 0.0


async def check_status() -> Dict[str, Any]:
    """查系统状态（对标 TG Bot 详细版）"""
    try:
        import psutil
        from sql.database_postgresql import get_session
        from sql.models import Task, TaskStatus, Subscription, LiveSubscription, SubscriptionVideo, LiveRecord

        cpu = psutil.cpu_percent(interval=1)
        mem = psutil.virtual_memory()
        disk = psutil.disk_usage("/app/downloads")

        db = get_session()
        try:
            # 任务统计
            downloading = db.query(Task).filter(Task.status == TaskStatus.DOWNLOADING.value).count()
            pending = db.query(Task).filter(Task.status == TaskStatus.PENDING.value).count()
            completed = db.query(Task).filter(Task.status == TaskStatus.COMPLETED.value).count()
            failed = db.query(Task).filter(Task.status == TaskStatus.ERROR.value).count()

            # 订阅统计
            all_subs = db.query(Subscription).all()
            total_subs = len(all_subs)
            active_subs = 0
            paused_subs = 0
            error_subs = 0
            for sub in all_subs:
                s = str(getattr(sub, "status", "") or "").lower()
                if s == "error":
                    error_subs += 1
                    continue
                interval = getattr(sub, "check_interval", None) or getattr(sub, "update_interval", 0)
                try:
                    interval_ok = float(interval or 0) > 0
                except Exception:
                    interval_ok = False
                auto_dl = getattr(sub, "auto_download", False)
                auto_ok = auto_dl is True or str(auto_dl).lower() == "true"
                if s == "active" and interval_ok and auto_ok:
                    active_subs += 1
                else:
                    paused_subs += 1

            sub_videos = db.query(SubscriptionVideo).count()

            # 直播统计
            total_lives = db.query(LiveSubscription).count()
            auto_record = db.query(LiveSubscription).filter(LiveSubscription.auto_record == "true").count()
            live_count = db.query(LiveSubscription).filter(LiveSubscription.is_live == "true").count()
            recording = db.query(LiveSubscription).filter(LiveSubscription.is_recording == "true").count()
            today_start = datetime.combine(date.today(), datetime.min.time())
            today_records = db.query(LiveRecord).filter(LiveRecord.start_time >= today_start).count()

            # 正在下载任务详情（从运行时 download_manager 获取）
            active_downloads = []
            try:
                from routers.downloader import download_manager
                for tid, task in download_manager.tasks.items():
                    active_downloads.append({
                        "id": tid[:8],
                        "title": (task.get("title") or "")[:30],
                        "progress": task.get("progress", 0) or 0,
                        "speed": task.get("speed", ""),
                    })
            except Exception:
                pass
        finally:
            db.close()

        # 用运行时的 live_recorder 覆盖 recording 计数，比 DB 状态更准确
        try:
            from live.recorder import live_recorder
            runtime_recording = len(live_recorder.get_all_recording_ids())
            if runtime_recording > 0:
                recording = runtime_recording
        except Exception:
            pass

        # 存储大小
        sub_storage = _get_dir_size("/app/downloads/subscriptions")

        # 版本信息
        app_version = ""
        core_version = ""
        try:
            from routers.version import get_build_version
            bv = await get_build_version()
            if bv and isinstance(bv, dict):
                app_version = bv.get("version", "")
        except Exception:
            pass
        try:
            from routers.system import _get_core_version_with_cache
            cv = _get_core_version_with_cache()
            if cv and isinstance(cv, dict):
                core_version = cv.get("current_version", "")
        except Exception:
            pass

        # 直播录制存储
        live_storage_gb = 0.0
        try:
            from live.routers import _stats_data
            if _stats_data and _stats_data.get('total_size', 0) > 0:
                live_storage_gb = round(_stats_data['total_size'] / (1000 ** 3), 2)
        except Exception:
            pass

        from routers.license import license_manager, LicenseStatus
        lic_valid = license_manager.status == LicenseStatus.VALID
        lic_lifetime = license_manager.is_lifetime
        lic_remaining = license_manager.remaining_days

        return {
            "success": True,
            "cpu": cpu,
            "mem_percent": mem.percent,
            "mem_used_gb": round(mem.used / (1024 ** 3), 1),
            "mem_total_gb": round(mem.total / (1024 ** 3), 1),
            "disk_percent": disk.percent,
            "disk_used_gb": round(disk.used / (1024 ** 3), 1),
            "disk_total_gb": round(disk.total / (1024 ** 3), 1),
            "downloading": downloading,
            "pending": pending,
            "completed": completed,
            "failed": failed,
            "total_subs": total_subs,
            "active_subs": active_subs,
            "paused_subs": paused_subs,
            "error_subs": error_subs,
            "sub_videos": sub_videos,
            "total_lives": total_lives,
            "auto_record": auto_record,
            "live_count": live_count,
            "recording": recording,
            "today_records": today_records,
            "sub_storage_gb": round(sub_storage, 2),
            "live_storage_gb": live_storage_gb,
            "license_valid": lic_valid,
            "license_lifetime": lic_lifetime,
            "license_remaining": lic_remaining,
            "app_version": app_version,
            "core_version": core_version,
            "active_downloads": active_downloads,
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


async def check_subscriptions(page: int = 1, page_size: int = 10) -> Dict[str, Any]:
    """查订阅（支持翻页，默认每页 10 条）"""
    try:
        from sql.database_postgresql import get_session
        from sql.models import Subscription
        db = get_session()
        try:
            total = db.query(Subscription).count()
            offset = (page - 1) * page_size
            subs = db.query(Subscription).order_by(Subscription.created_at.desc()).offset(offset).limit(page_size).all()
            items = []
            for sub in subs:
                items.append({
                    "id": sub.id[:8],
                    "full_id": sub.id,
                    "status": sub.status,
                    "name": sub.nickname or (sub.profile_url or "")[:30],
                    "url": sub.profile_url or "",
                    "platform": sub.platform,
                })
            total_pages = max(1, (total + page_size - 1) // page_size)
            return {"success": True, "total": total, "items": items, "page": page, "total_pages": total_pages}
        finally:
            db.close()
    except Exception as e:
        return {"success": False, "error": str(e)}


async def check_live_subscriptions(page: int = 1, page_size: int = 10) -> Dict[str, Any]:
    """查直播订阅（支持翻页，默认每页 10 条）"""
    try:
        from sql.database_postgresql import get_session
        from sql.models import LiveSubscription
        db = get_session()
        try:
            total = db.query(LiveSubscription).count()
            offset = (page - 1) * page_size
            lives = db.query(LiveSubscription).order_by(
                LiveSubscription.is_live.desc(),
                LiveSubscription.is_recording.desc(),
                LiveSubscription.created_at.desc(),
            ).offset(offset).limit(page_size).all()
            items = []
            for live in lives:
                items.append({
                    "id": live.id[:8],
                    "full_id": live.id,
                    "is_recording": live.is_recording == "true",
                    "is_live": live.is_live == "true",
                    "auto_record": live.auto_record == "true",
                    "anchor_name": live.anchor_name or live.room_url[:30],
                    "platform": live.platform,
                    "room_url": live.room_url,
                })
            total_pages = max(1, (total + page_size - 1) // page_size)
            return {"success": True, "total": total, "items": items, "page": page, "total_pages": total_pages}
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
            ).order_by(Task.updated_at.desc(), Task.created_at.desc()).limit(10).all()
            items = []
            for t in failed_tasks:
                items.append({
                    "id": t.id[:8],
                    "full_id": t.id,
                    "title": t.title or t.url[:30] if hasattr(t, 'title') and t.title else (t.url[:30] if t.url else "未知"),
                    "error": t.error_message[:50] if t.error_message else "未知错误",
                    "source": t.source or "未知",
                    "url": t.url,
                })
            return {"success": True, "total": len(failed_tasks), "items": items}
        finally:
            db.close()
    except Exception as e:
        return {"success": False, "error": str(e)}


# ==================== 操作类命令 ====================

async def download_url(url: str) -> Dict[str, Any]:
    """下载单个视频（含短链解析）"""
    try:
        from sql.database_postgresql import get_session
        from sql.models import Task, TaskStatus
        from routers.downloader import download_manager

        # 短链解析
        url = await resolve_url(url)
        # 清洗 URL
        url = clean_url(url)

        # 识别来源
        source = _detect_source(url)

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
    """添加订阅（含短链解析+精确平台检测+输入校验）"""
    try:
        from routers.license import license_manager
        if not await license_manager.is_active_for("bot.subscribe"):
            return {"success": False, "error": "订阅功能是高级功能，授权无效或已过期。"}

        # 短链解析
        url = await resolve_url(url)

        # 直播链接检测：如果是直播链接，转给直播订阅
        url_lower = url.lower()
        if any(x in url_lower for x in [
            "live.douyin.com", "live.bilibili.com", "youtube.com/live/",
            "webcast.amemv.com", "amemv.com",
        ]):
            return await add_live_subscription(url)

        # 输入校验：拒绝无效链接
        if "instagram.com" in url:
            if "/p/" in url or "/reel/" in url or "/stories/" in url:
                return {"success": False, "error": "Instagram 单帖/Reel/Stories 不支持订阅，请发送博主主页链接"}
        if "xiaohongshu.com" in url:
            if "/explore/" in url or "/livestream" in url:
                return {"success": False, "error": "小红书笔记/直播不支持订阅，请发送博主主页链接"}
        if "music.163.com" in url and "playlist" not in url and "id=" not in url:
            return {"success": False, "error": "网易云只支持歌单订阅，请发送歌单链接"}

        from routers.subscribe.subscription import add_subscription as _add_sub
        from sql.models import SubscriptionCreate, Platform

        platform = _detect_platform(url)
        subscription_type = "user"
        youtube_tab_type = None

        # 精确平台检测
        if "douyin.com" in url:
            if "/collection/" in url:
                platform = Platform.douyin_collection if hasattr(Platform, 'douyin_collection') else Platform.douyin
                subscription_type = "collection"
        elif "youtube.com" in url or "youtu.be" in url:
            if "list=" in url:
                subscription_type = "playlist"
            elif "/@" in url or "/c/" in url or "/channel/" in url:
                subscription_type = "channel"
            # YouTube 标签页类型
            if "/shorts" in url:
                youtube_tab_type = "shorts"
            elif "/videos" in url:
                youtube_tab_type = "videos"
        elif "bilibili.com" in url:
            if "favlist" in url or "fid=" in url:
                subscription_type = "favorite"
            elif "/video/BV" in url:
                subscription_type = "collection"

        sub_create = SubscriptionCreate(
            profile_url=url,
            platform=platform,
            auto_download="true",
            quality="best",
            update_interval=3600,
            subscription_type=subscription_type,
            youtube_tab_type=youtube_tab_type,
        )
        try:
            from sql.database_postgresql import get_session
            db_session = get_session()
            try:
                result = await _add_sub(sub_create, db_session)
            finally:
                db_session.close()
        except Exception as e:
            logger.error(f"添加订阅失败 (url={url[:50]}): {e}", exc_info=True)
            return {"success": False, "error": str(e)}
        if result:
            name = getattr(result, 'nickname', None) or getattr(result, 'profile_url', url[:40])
            sub_type = detect_subscription_type(url) or subscription_type
            return {"success": True, "name": name, "platform": str(platform) if platform else "自动识别", "type": sub_type}
        return {"success": False, "error": "添加失败"}
    except Exception as e:
        logger.error(f"添加订阅异常 (url={url[:50]}): {e}", exc_info=True)
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
            if "douyin.com" in url or "iesdouyin.com" in url or "amemv.com" in url:
                adapter = adapters.get_adapter_by_platform("douyin")
            elif "bilibili.com" in url or "b23.tv" in url:
                adapter = adapters.get_adapter_by_platform("bilibili")
            elif "xiaohongshu.com" in url or "xhslink.com" in url:
                adapter = adapters.get_adapter_by_platform("xhs")
            elif "huya.com" in url:
                adapter = adapters.get_adapter_by_platform("huya")
            elif "kuaishou.com" in url or "gifshow.com" in url or "chenzhongtech.com" in url:
                adapter = adapters.get_adapter_by_platform("kuaishou")
            elif "douyu.com" in url:
                adapter = adapters.get_adapter_by_platform("douyu")
            elif "cc.163.com" in url:
                adapter = adapters.get_adapter_by_platform("cc")
            elif "twitch.tv" in url:
                adapter = adapters.get_adapter_by_platform("twitch")

        if not adapter:
            return {"success": False, "error": "无法识别的直播链接，目前支持：抖音、B站、快手、虎牙、小红书、油管、咪咕、斗鱼、网易CC、Twitch"}

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
            if not existing and room_id:
                existing = db.query(LiveSubscription).filter(
                    LiveSubscription.platform == platform_name,
                    LiveSubscription.room_id == str(room_id)
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
            try:
                await live_scheduler.add_monitor(
                    subscription_id=new_sub.id,
                    room_url=new_sub.room_url,
                    platform=new_sub.platform,
                    check_interval=new_sub.check_interval or 60,
                )
            except Exception as scheduler_err:
                logger.warning(f"触发监控失败（系统重启后将自动接管）: {scheduler_err}")
            return {"success": True, "anchor_name": anchor_name, "platform": platform_name}
        finally:
            db.close()
    except Exception as e:
        return {"success": False, "error": str(e)}


async def retry_task(task_id: str) -> Dict[str, Any]:
    """重试失败任务（对标 TG Bot 使用 retry_task_internal）"""
    try:
        from sql.database_postgresql import get_session
        from sql.models import Task
        from routers.file_manager import retry_task_internal

        def _enqueue(func, *args):
            result = func(*args)
            if asyncio.iscoroutine(result):
                asyncio.create_task(result)

        db = get_session()
        try:
            # 先找到完整任务 ID
            task = db.query(Task).filter(Task.id.startswith(task_id)).first()
            if not task:
                return {"success": False, "error": f"未找到任务: {task_id}"}
            res = retry_task_internal(task.id, db, _enqueue)
            return {"success": True, "task_id": task.id[:8], "message": res.get("message", "任务已开始重试")}
        finally:
            db.close()
    except Exception as e:
        return {"success": False, "error": str(e)}


async def delete_task(task_id: str) -> Dict[str, Any]:
    """删除任务（含文件清理+关联视频重置）"""
    try:
        from sql.database_postgresql import get_session
        from sql.models import Task, SubscriptionVideo
        db = get_session()
        try:
            task = db.query(Task).filter(Task.id.startswith(task_id)).first()
            if not task:
                return {"success": False, "error": f"未找到任务: {task_id}"}

            # 文件清理
            cleaned = 0
            try:
                from routers.file_manager import cleanup_task_before_delete
                cleanup_res = cleanup_task_before_delete(task, delete_output=True, delete_temp=True)
                cleaned = len(cleanup_res.get("output", [])) + len(cleanup_res.get("temp", []))
            except Exception as e:
                logger.warning(f"文件清理失败: {e}")

            # 重置关联的 SubscriptionVideo
            related_videos = db.query(SubscriptionVideo).filter(
                SubscriptionVideo.download_task_id == task.id
            ).all()
            for video in related_videos:
                video.downloaded = "false"
                video.download_task_id = None
                video.error_message = None

            db.delete(task)
            db.commit()
            msg = f"任务已删除"
            if cleaned > 0:
                msg += f"，清理 {cleaned} 个文件"
            return {"success": True, "task_id": task.id[:8], "message": msg}
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
            return {"success": True, "name": sub.nickname or (sub.profile_url or "")[:30]}
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
            return {"success": True, "name": sub.nickname or (sub.profile_url or "")[:30]}
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
            return {"success": True, "name": sub.nickname or (sub.profile_url or "")[:30]}
        finally:
            db.close()
    except Exception as e:
        return {"success": False, "error": str(e)}


# ==================== 直播订阅管理 ====================


async def pause_live_subscription(sub_id: str) -> Dict[str, Any]:
    """暂停直播订阅：停止当前录制 + 关闭自动录制"""
    try:
        from sql.database_postgresql import get_session
        from sql.models import LiveSubscription
        from live.scheduler import live_scheduler
        from live.recorder import live_recorder
        db = get_session()
        try:
            sub = db.query(LiveSubscription).filter(LiveSubscription.id.startswith(sub_id)).first()
            if not sub:
                return {"success": False, "error": f"未找到直播订阅: {sub_id}"}

            # 先停正在录制的流
            stop_result = await live_recorder.stop_recording(
                sub.id, convert_to_mp4=True
            )
            if stop_result.get('success'):
                sub.is_recording = "false"
                # 更新录制记录结束时间
                from sql.models import LiveRecord
                record = db.query(LiveRecord).filter(
                    LiveRecord.subscription_id == sub.id,
                    LiveRecord.status == "recording"
                ).order_by(LiveRecord.start_time.desc()).first()
                if record:
                    record.end_time = datetime.now()
                    record.duration = stop_result.get('duration', 0)
                    record.file_size = stop_result.get('file_size', 0)
                    record.status = "completed"

            sub.auto_record = "false"
            db.commit()
            live_scheduler.invalidate_config_cache(sub.id)
            return {"success": True, "name": sub.anchor_name or sub.room_url[:30]}
        finally:
            db.close()
    except Exception as e:
        return {"success": False, "error": str(e)}


async def resume_live_subscription(sub_id: str) -> Dict[str, Any]:
    """恢复直播订阅（开启自动录制）"""
    try:
        from sql.database_postgresql import get_session
        from sql.models import LiveSubscription
        from live.scheduler import live_scheduler
        db = get_session()
        try:
            sub = db.query(LiveSubscription).filter(LiveSubscription.id.startswith(sub_id)).first()
            if not sub:
                return {"success": False, "error": f"未找到直播订阅: {sub_id}"}
            sub.auto_record = "true"
            db.commit()
            live_scheduler.invalidate_config_cache(sub.id)
            # 立即触发一次检测，不等下一个轮询周期
            try:
                await live_scheduler.trigger_immediate_check(sub.id)
            except Exception:
                pass
            return {"success": True, "name": sub.anchor_name or sub.room_url[:30]}
        finally:
            db.close()
    except Exception as e:
        return {"success": False, "error": str(e)}


async def delete_live_subscription(sub_id: str) -> Dict[str, Any]:
    """删除直播订阅"""
    try:
        from sql.database_postgresql import get_session
        from sql.models import LiveSubscription
        from live.scheduler import live_scheduler
        db = get_session()
        try:
            sub = db.query(LiveSubscription).filter(LiveSubscription.id.startswith(sub_id)).first()
            if not sub:
                return {"success": False, "error": f"未找到直播订阅: {sub_id}"}
            await live_scheduler.remove_monitor(sub.id, stop_recording=False)
            db.delete(sub)
            db.commit()
            return {"success": True, "name": sub.anchor_name or sub.room_url[:30]}
        finally:
            db.close()
    except Exception as e:
        return {"success": False, "error": str(e)}


# ==================== URL 识别 ====================

# 直播上下文提示词（用于短链未解析时兜底检测）
LIVE_TEXT_KEYWORDS = [
    "正在直播", "直播中", "来和我一起", "直播间的", "直播间",
    "live.douyin", "live.bilibili",
]


def contains_live_context(text: str) -> bool:
    """检测文本是否包含直播上下文提示"""
    if not text:
        return False
    text_lower = text.lower()
    return any(kw in text_lower for kw in LIVE_TEXT_KEYWORDS)


def extract_url(text: str) -> Optional[str]:
    """从文本中提取第一个 URL"""
    urls = re.findall(r'https?://[^\s<>"\']+', text)
    return urls[0].rstrip("/") if urls else None


def classify_url(url: str, context_text: str = "") -> str:
    """识别 URL 类型: live / subscription / download

    支持传入 context_text 辅助判断（短链未解析时，原文含"正在直播"等提示词直接命中直播）
    """
    url_lower = url.lower()
    if any(x in url_lower for x in [
        "live.douyin", "live.bilibili", "huya.com", "kuaishou.com/live",
        "douyu.com", "twitch.tv",
        "webcast.amemv.com", "amemv.com",  # 抖音直播 webcast 域名
    ]):
        return "live"
    # 抖音短链 v.douyin.com — 可能指向直播间（配合文本上下文判断）
    if "v.douyin.com" in url and "/note/" not in url and "/video/" not in url:
        if contains_live_context(context_text):
            return "live"
    # 上下文明确含直播提示词，且 URL 来自直播平台，判为直播
    if contains_live_context(context_text) and any(
        d in url_lower for d in ["douyin.com", "iesdouyin.com", "amemv.com"]
    ):
        return "live"
    if detect_subscription_type(url):
        return "subscription"
    return "download"


async def handle_url(url: str, context_text: str = "") -> Dict[str, Any]:
    """智能处理 URL（含短链解析 + 文本上下文辅助判断）"""
    # 先解析短链（仅用于分类判断，传给业务函数时用原始 URL 避免丢失参）
    resolved = await resolve_url(url)
    url_type = classify_url(resolved, context_text)
    logger.debug(f"handle_url: url={url[:60]}, resolved={resolved[:60]}, type={url_type}")
    if url_type == "live":
        result = await add_live_subscription(url)
        result["action"] = "直播录制"
        return result
    elif url_type == "subscription":
        result = await add_subscription(url)
        result["action"] = "订阅"
        return result
    else:
        result = await download_url(url)
        result["action"] = "下载"
        return result


# ==================== 内部工具 ====================

def _detect_source(url: str) -> str:
    """识别 URL 来源平台"""
    if "douyin.com" in url or "iesdouyin.com" in url:
        return "douyin"
    elif "tiktok.com" in url or "vt.tiktok.com" in url:
        return "tiktok"
    elif "bilibili.com" in url or "b23.tv" in url:
        return "bilibili"
    elif "youtube.com" in url or "youtu.be" in url:
        return "youtube"
    elif "xiaohongshu.com" in url or "xhslink.com" in url:
        return "xiaohongshu"
    elif "kuaishou.com" in url or "gifshow.com" in url:
        return "kuaishou"
    elif "x.com" in url or "twitter.com" in url:
        return "x"
    elif "music.163.com" in url:
        return "netease"
    return "others"


def _detect_platform(url: str):
    """检测订阅平台类型"""
    from sql.models import Platform
    if "douyin.com" in url or "v.douyin.com" in url:
        return Platform.DOUYIN
    elif "bilibili.com" in url or "b23.tv" in url:
        return Platform.BILIBILI
    elif "youtube.com" in url or "youtu.be" in url:
        return Platform.YOUTUBE
    elif "xiaohongshu.com" in url or "xhslink.com" in url:
        return Platform.XIAOHONGSHU
    elif "tiktok.com" in url or "vt.tiktok.com" in url:
        return Platform.TIKTOK
    elif "instagram.com" in url:
        return Platform.INSTAGRAM
    elif "music.163.com" in url:
        return Platform.NETEASE
    return None
