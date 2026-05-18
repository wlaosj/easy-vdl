"""
订阅重命名与文件迁移服务
当前仅支持 B站合集试点。
"""
import os
import shutil
from typing import Dict, List, Optional, Tuple

from fastapi import HTTPException
from pydantic import BaseModel, Field, validator
from sqlalchemy.orm import Session

from routers.dyd import sanitize_filename
from .common import logger
from sql.models import Subscription, SubscriptionVideo, Task, TaskStatus, Platform


DOWNLOADS_ROOT = "/app/downloads"
SUBSCRIPTIONS_ROOT = os.path.join(DOWNLOADS_ROOT, "subscriptions")


class SubscriptionRenameRequest(BaseModel):
    nickname: str = Field(..., min_length=1, max_length=200)

    @validator("nickname")
    def validate_nickname(cls, value):
        value = (value or "").strip()
        if not value:
            raise ValueError("新名称不能为空")
        return value


def is_bilibili_collection_subscription(subscription: Subscription) -> bool:
    return (
        subscription.platform == Platform.BILIBILI_COLLECTION.value
        or (
            subscription.platform == Platform.BILIBILI.value
            and getattr(subscription, "subscription_type", None) == "collection"
        )
    )


def _storage_platform(platform: str) -> str:
    if platform == Platform.BILIBILI_COLLECTION.value:
        return Platform.BILIBILI.value
    return (platform or "").lower()


def _subscription_dir(platform: str, storage_name: str) -> str:
    platform_dir = _storage_platform(platform)
    root_real = os.path.realpath(SUBSCRIPTIONS_ROOT)
    path_real = os.path.realpath(os.path.join(root_real, platform_dir, storage_name))
    if path_real != root_real and not path_real.startswith(root_real + os.sep):
        raise HTTPException(status_code=400, detail="订阅目录路径非法")
    return path_real


def _resolve_new_storage_name(nickname: str, subscription_id: str) -> str:
    storage_name = sanitize_filename(nickname or "")
    if not storage_name or storage_name.strip("._ ") == "" or storage_name == "untitled":
        storage_name = f"author_{str(subscription_id)[:8]}"
    return storage_name


def _task_filename_matches(prefix: str, filename: Optional[str]) -> bool:
    if not filename:
        return False
    normalized = str(filename).replace("\\", "/")
    return normalized.startswith(prefix)


def rename_bilibili_collection_subscription(
    db: Session,
    subscription_id: str,
    new_nickname: str,
) -> Dict[str, object]:
    subscription = db.query(Subscription).filter(Subscription.id == subscription_id).first()
    if not subscription:
        raise HTTPException(status_code=404, detail="未找到该订阅")
    if not is_bilibili_collection_subscription(subscription):
        raise HTTPException(status_code=400, detail="当前仅支持 B站合集重命名试点")

    running_tasks = db.query(Task).filter(
        Task.subscription_id == subscription_id,
        Task.status.in_([
            TaskStatus.PENDING.value,
            TaskStatus.DOWNLOADING.value,
            TaskStatus.PROCESSING.value,
        ]),
    ).count()
    if running_tasks > 0:
        raise HTTPException(status_code=400, detail="当前订阅存在进行中的下载任务，请先等待任务完成后再重命名")

    old_storage_name = (subscription.storage_name or "").strip()
    if not old_storage_name:
        old_storage_name = _resolve_new_storage_name(subscription.nickname or "", subscription.id)

    new_storage_name = _resolve_new_storage_name(new_nickname, subscription.id)
    if new_storage_name == old_storage_name and (subscription.nickname or "").strip() == new_nickname.strip():
        return {
            "success": True,
            "message": "名称未变化",
            "nickname": subscription.nickname,
            "storage_name": subscription.storage_name,
            "migrated": False,
            "updated_tasks": 0,
            "renamed_paths": [],
        }

    old_dir = _subscription_dir(subscription.platform, old_storage_name)
    new_dir = _subscription_dir(subscription.platform, new_storage_name)

    if os.path.exists(new_dir) and os.path.realpath(old_dir) != os.path.realpath(new_dir):
        raise HTTPException(status_code=400, detail=f"目标目录已存在: {new_storage_name}")

    old_prefix = f"subscriptions/{_storage_platform(subscription.platform)}/{old_storage_name}/"
    new_prefix = f"subscriptions/{_storage_platform(subscription.platform)}/{new_storage_name}/"

    if not os.path.exists(old_dir):
        old_dir_exists = False
    else:
        old_dir_exists = True

    updated_task_ids: List[str] = []
    renamed_paths: List[Tuple[str, str]] = []

    try:
        if old_dir_exists and os.path.realpath(old_dir) != os.path.realpath(new_dir):
            os.makedirs(os.path.dirname(new_dir), exist_ok=True)
            shutil.move(old_dir, new_dir)

        tasks = db.query(Task).filter(Task.subscription_id == subscription_id).all()
        for task in tasks:
            if not _task_filename_matches(old_prefix, task.filename):
                continue
            new_filename = str(task.filename).replace(old_prefix, new_prefix, 1)
            if new_filename != task.filename:
                renamed_paths.append((task.filename, new_filename))
                task.filename = new_filename
                updated_task_ids.append(task.id)

        subscription.nickname = new_nickname.strip()
        subscription.storage_name = new_storage_name
        subscription.nickname_locked = "true"
        subscription.subscription_type = "collection"
        subscription.updated_at = subscription.updated_at or subscription.created_at

        db.commit()
        db.refresh(subscription)

        return {
            "success": True,
            "message": "重命名迁移完成",
            "nickname": subscription.nickname,
            "storage_name": subscription.storage_name,
            "migrated": old_dir_exists,
            "updated_tasks": len(updated_task_ids),
            "renamed_paths": renamed_paths,
            "old_dir": old_dir if old_dir_exists else None,
            "new_dir": new_dir,
        }
    except Exception:
        db.rollback()
        raise
