import logging
from datetime import datetime
from typing import List, Dict, Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from sql.database_postgresql import get_db
from sql.models import Subscription, LiveSubscription
from routers.auth import require_license_api
from routers.subscribe.batch import batch_import_subscriptions
from routers.subscribe.models import ImportSubscriptionRequest, ImportSubscriptionResponse
from routers.subscribe.utils import generate_profile_url

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/backup", tags=["backup"])


class SubscriptionBackup(BaseModel):
    """订阅配置备份数据（仅订阅列表）"""

    export_time: str
    total_subscriptions: int
    subscriptions: List[Dict[str, Any]]


class LiveSubscriptionBackup(BaseModel):
    """直播订阅配置备份数据（仅订阅列表）"""

    export_time: str
    total_subscriptions: int
    subscriptions: List[Dict[str, Any]]


async def _export_subscriptions(db: Session) -> Dict[str, Any]:
    """导出所有订阅配置（供 API 与内部调用复用）"""
    subscriptions = db.query(Subscription).all()

    export_data: Dict[str, Any] = {
        "export_time": datetime.now().isoformat(),
        "total_subscriptions": len(subscriptions),
        "subscriptions": [],
    }

    for sub in subscriptions:
        profile_url = generate_profile_url(sub.platform, sub.user_id)
        subscription_type = sub.subscription_type
        if sub.platform == "bilibili_collection":
            subscription_type = "collection"

        subscription_data = {
            "platform": sub.platform,
            "user_id": sub.user_id,
            "nickname": sub.nickname,
            "storage_name": sub.storage_name,
            "nickname_locked": sub.nickname_locked,
            "subscription_type": subscription_type,
            "collection_id": sub.collection_id,
            "collection_title": sub.collection_title,
            "author_id": sub.author_id,
            "author_name": sub.author_name,
            "profile_url": profile_url,
            "update_interval": sub.update_interval,
            "auto_download": sub.auto_download,
            "status": sub.status,
            "created_at": sub.created_at.isoformat() if sub.created_at else None,
            "signature": sub.signature,
            "avatar_url": sub.avatar_url,
            "follower_count": sub.follower_count,
            "like_count": sub.like_count,
            "video_count": sub.video_count,
            "quality": sub.quality,
        }
        export_data["subscriptions"].append(subscription_data)

    return export_data


async def _export_live_subscriptions(db: Session) -> Dict[str, Any]:
    """导出所有直播订阅配置"""
    live_subs = db.query(LiveSubscription).all()

    export_data: Dict[str, Any] = {
        "export_time": datetime.now().isoformat(),
        "total_subscriptions": len(live_subs),
        "subscriptions": [],
    }

    for sub in live_subs:
        sub_data = {
            "platform": sub.platform,
            "room_url": sub.room_url,
            "room_id": sub.room_id,
            "anchor_name": sub.anchor_name,
            "avatar_url": sub.avatar_url,
            "signature": sub.signature,
            "quality": sub.quality,
            "auto_record": sub.auto_record,
            "check_interval": sub.check_interval,
            "notification_enabled": sub.notification_enabled,
            "output_format": sub.output_format,
            "split_enabled": sub.split_enabled,
            "split_duration": sub.split_duration,
            "max_duration": sub.max_duration,
            "proxy": sub.proxy,
            "cookies": sub.cookies,
            "remark": sub.remark,
            "extra_data": sub.extra_data,
            "created_at": sub.created_at.isoformat() if sub.created_at else None,
        }
        export_data["subscriptions"].append(sub_data)

    return export_data


@router.get("/subscriptions", response_model=SubscriptionBackup)
@require_license_api
async def export_subscriptions_backup(db: Session = Depends(get_db)):
    """
    导出订阅配置（备份订阅列表）

    与 /api/subscribe/export_config 使用同一份导出逻辑，
    只是挂在专用 backup 路由下，方便未来扩展更多备份类型。
    """
    try:
        export_data = await _export_subscriptions(db)
        return export_data
    except Exception as e:
        logger.error(f"导出订阅备份失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post(
    "/subscriptions/import",
    response_model=ImportSubscriptionResponse,
)
@require_license_api
async def import_subscriptions_backup(
    payload: SubscriptionBackup, db: Session = Depends(get_db)
):
    """
    导入订阅配置备份（仅订阅列表）

    接受由 /api/backup/subscriptions 或 /api/subscribe/export_config 导出的数据，
    仅处理 subscriptions 列表，复用 batch_import_subscriptions 的去重与写入逻辑。
    """
    try:
        subscriptions_data = payload.subscriptions or []
        if not subscriptions_data:
            raise HTTPException(status_code=400, detail="备份中不包含任何订阅数据")

        request = ImportSubscriptionRequest(subscriptions=subscriptions_data)
        # 直接复用订阅模块的批量导入实现，保持行为一致
        result = await batch_import_subscriptions(request, db)
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"导入订阅备份失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


class LiveSubscriptionImportResponse(BaseModel):
    """直播订阅批量导入响应模型"""

    total: int
    success: int
    failed: int
    errors: List[str]


@router.get("/live_subscriptions", response_model=LiveSubscriptionBackup)
@require_license_api
async def export_live_subscriptions_backup(db: Session = Depends(get_db)):
    """
    导出直播订阅配置（备份直播订阅列表）

    仅导出 live_subscriptions 表的配置，不包含录制历史。
    """
    try:
        export_data = await _export_live_subscriptions(db)
        return export_data
    except Exception as e:
        logger.error(f"导出直播订阅备份失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post(
    "/live_subscriptions/import",
    response_model=LiveSubscriptionImportResponse,
)
@require_license_api
async def import_live_subscriptions_backup(
    payload: LiveSubscriptionBackup, db: Session = Depends(get_db)
):
    """
    导入直播订阅配置备份（仅直播订阅列表）

    去重规则：按 (platform, room_url) 判断是否已存在，已存在则跳过。
    新增订阅时，会自动为其创建监控任务。
    """
    from live.scheduler import live_scheduler  # 延迟导入避免循环引用
    from live.danmu import is_danmu_supported
    import uuid

    subs_data = payload.subscriptions or []
    if not subs_data:
        raise HTTPException(status_code=400, detail="备份中不包含任何直播订阅数据")

    total = len(subs_data)
    success_count = 0
    failed_count = 0
    errors: List[str] = []

    for idx, item in enumerate(subs_data, start=1):
        try:
            platform = (item.get("platform") or "").strip()
            room_url = (item.get("room_url") or "").strip()

            if not platform or not room_url:
                failed_count += 1
                errors.append(f"第{idx}条缺少 platform 或 room_url，已跳过")
                continue

            # 查重：按 (platform, room_url)
            existing = (
                db.query(LiveSubscription)
                .filter(
                    LiveSubscription.platform == platform,
                    LiveSubscription.room_url == room_url,
                )
                .first()
            )
            if existing:
                failed_count += 1
                errors.append(f"已存在相同直播订阅（{platform} - {room_url}），已跳过")
                continue

            # 处理 extra_data（弹幕设置等）
            extra_data_raw = item.get("extra_data")
            if extra_data_raw:
                # 保留备份中的 extra_data（如弹幕设置）
                extra_data = extra_data_raw
            else:
                # 旧备份无 extra_data，按平台自动开启弹幕
                extra_data = json.dumps({
                    "danmu_enabled": is_danmu_supported(platform),
                })

            sub = LiveSubscription(
                id=str(uuid.uuid4()),
                platform=platform,
                room_url=room_url,
                room_id=item.get("room_id"),
                anchor_name=item.get("anchor_name"),
                avatar_url=item.get("avatar_url"),
                signature=item.get("signature"),
                quality=item.get("quality") or "原画",
                auto_record=str(item.get("auto_record") or "true").lower(),
                check_interval=int(item.get("check_interval") or 60),
                output_format=item.get("output_format") or "ts",
                split_enabled=str(item.get("split_enabled") or "false").lower(),
                split_duration=int(item.get("split_duration") or 3600),
                max_duration=item.get("max_duration"),
                notification_enabled=str(
                    item.get("notification_enabled") or "true"
                ).lower(),
                notification_end_enabled="false",
                proxy=item.get("proxy"),
                cookies=item.get("cookies"),
                remark=item.get("remark"),
                extra_data=extra_data,
                created_at=datetime.now(),
                updated_at=datetime.now(),
            )

            db.add(sub)
            db.commit()
            db.refresh(sub)

            # 为新订阅添加监控任务
            try:
                await live_scheduler.add_monitor(
                    sub.id, sub.room_url, sub.platform, sub.check_interval or 60
                )
            except Exception as e:
                logger.warning(f"为直播订阅添加监控失败 ({sub.id}): {e}")

            success_count += 1
        except Exception as e:
            db.rollback()
            failed_count += 1
            errors.append(f"第{idx}条导入失败: {e}")
            logger.error(f"导入直播订阅失败（第{idx}条）: {e}", exc_info=True)
    
    return LiveSubscriptionImportResponse(
        total=total,
        success=success_count,
        failed=failed_count,
        errors=errors,
    )
