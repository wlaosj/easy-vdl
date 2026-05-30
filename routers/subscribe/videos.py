"""
视频列表和统计相关路由
"""
import json
import os
from typing import Optional, List
from fastapi import APIRouter, HTTPException, Depends, Query
from sqlalchemy.orm import Session
from sqlalchemy import and_, or_, func, case
from pydantic import BaseModel
from sql.database_postgresql import get_db
from sql.models import Subscription, SubscriptionVideo, Task, TaskStatus, SubscriptionVideoResponse
from routers.auth import require_license_api
from .common import logger
from .models import SubscriptionVideosResponse

router = APIRouter()
DOWNLOAD_ROOT = "/app/downloads"


class NfoUpdateRequest(BaseModel):
    content: str


def _build_local_thumbnail_url(task_filename: Optional[str]) -> Optional[str]:
    """从任务文件路径推断本地缩略图 URL。"""
    if not task_filename:
        return None

    rel_path = str(task_filename).strip().replace("\\", "/").lstrip("/")
    if not rel_path:
        return None

    full_path = os.path.normpath(os.path.join(DOWNLOAD_ROOT, rel_path))
    root_path = os.path.normpath(DOWNLOAD_ROOT)
    if not (full_path == root_path or full_path.startswith(root_path + os.sep)):
        return None

    if os.path.isdir(full_path):
        target_dir = full_path
        video_base = None
    else:
        target_dir = os.path.dirname(full_path)
        video_base = os.path.splitext(os.path.basename(full_path))[0]

    if not os.path.isdir(target_dir):
        return None

    image_exts = (".jpg", ".jpeg", ".png", ".webp")
    specific_poster = []
    poster_files = []
    normal_images = []

    for name in sorted(os.listdir(target_dir)):
        candidate = os.path.join(target_dir, name)
        if not os.path.isfile(candidate):
            continue
        low_name = name.lower()
        if not low_name.endswith(image_exts):
            continue
        if "poster" in low_name:
            if video_base and video_base in name:
                specific_poster.append(name)
            else:
                poster_files.append(name)
        else:
            normal_images.append(name)

    picked = None
    if specific_poster:
        picked = specific_poster[0]
    elif poster_files:
        picked = poster_files[0]
    elif normal_images:
        picked = normal_images[0]

    if not picked:
        return None

    rel_dir = os.path.relpath(target_dir, DOWNLOAD_ROOT).replace("\\", "/")
    if rel_dir == ".":
        rel_dir = ""
    if rel_dir:
        return f"/downloads/{rel_dir}/{picked}"
    return f"/downloads/{picked}"


def _resolve_task_abs_path(task_filename: Optional[str]) -> Optional[str]:
    """将 task.filename 解析为 downloads 根目录下的绝对路径，并做越界保护。"""
    if not task_filename:
        return None

    rel_path = str(task_filename).strip().replace("\\", "/").lstrip("/")
    if not rel_path:
        return None

    root_path = os.path.realpath(DOWNLOAD_ROOT)
    abs_path = os.path.realpath(os.path.join(root_path, rel_path))
    if abs_path != root_path and not abs_path.startswith(root_path + os.sep):
        return None
    return abs_path


def _resolve_nfo_abs_path(task_filename: Optional[str]) -> Optional[str]:
    """根据 task.filename 推导对应 nfo 绝对路径。"""
    abs_path = _resolve_task_abs_path(task_filename)
    if not abs_path:
        return None

    # 常规视频：同目录同名 nfo
    if os.path.isfile(abs_path):
        stem, _ = os.path.splitext(abs_path)
        nfo_path = f"{stem}.nfo"
        return nfo_path if os.path.isfile(nfo_path) else None

    # 目录型任务（如图集/特殊平台）：优先目录同名 nfo，其次目录下唯一 nfo
    if os.path.isdir(abs_path):
        dir_name = os.path.basename(os.path.normpath(abs_path))
        named_nfo = os.path.join(abs_path, f"{dir_name}.nfo")
        if os.path.isfile(named_nfo):
            return named_nfo

        nfo_files = [
            os.path.join(abs_path, name)
            for name in sorted(os.listdir(abs_path))
            if name.lower().endswith(".nfo") and os.path.isfile(os.path.join(abs_path, name))
        ]
        if len(nfo_files) == 1:
            return nfo_files[0]

    return None


def _read_nfo_content(nfo_path: str) -> str:
    """兼容常见编码读取 nfo。"""
    encodings = ("utf-8-sig", "utf-8", "gb18030")
    for encoding in encodings:
        try:
            with open(nfo_path, "r", encoding=encoding) as f:
                return f.read()
        except UnicodeDecodeError:
            continue
    raise UnicodeDecodeError("nfo", b"", 0, 1, "无法识别的NFO编码")


def _is_file_missing_orphan(task: Optional[Task]) -> bool:
    """复刻下载中心口径：task.filename 存在但本地文件不存在。"""
    if not task or not getattr(task, "filename", None):
        return False
    abs_path = _resolve_task_abs_path(task.filename)
    if not abs_path:
        return False
    return not os.path.exists(abs_path)


def _delete_orphan_residuals(task_filename: Optional[str]) -> List[str]:
    """清理孤儿残留：删除同名主文件/同名副产物，若目标是目录则递归删除。"""
    deleted_paths: List[str] = []
    abs_path = _resolve_task_abs_path(task_filename)
    if not abs_path:
        return deleted_paths

    if os.path.isdir(abs_path):
        for root, dirs, files in os.walk(abs_path, topdown=False):
            for name in files:
                fp = os.path.join(root, name)
                try:
                    os.remove(fp)
                    deleted_paths.append(fp)
                except Exception:
                    pass
            for name in dirs:
                dp = os.path.join(root, name)
                try:
                    os.rmdir(dp)
                    deleted_paths.append(dp)
                except Exception:
                    pass
        try:
            os.rmdir(abs_path)
            deleted_paths.append(abs_path)
        except Exception:
            pass
        return deleted_paths

    parent_dir = os.path.dirname(abs_path)
    base_name = os.path.basename(abs_path)
    stem, _ = os.path.splitext(base_name)
    if not os.path.isdir(parent_dir) or not stem:
        return deleted_paths

    # 删除同 stem 的常见副产物（nfo/封面/字幕等），避免残留
    # 兼容常见命名：
    # 1) 与主文件同 stem: {stem}.nfo / {stem}.webp
    # 2) poster 后缀: {stem}-poster.jpg / {stem}_poster.jpg
    # 3) 多语言字幕: {stem}.zh-Hans.srt / {stem}.en.vtt
    sidecar_prefixes = (
        f"{stem}-",
        f"{stem}_",
        f"{stem}.",
    )
    for name in os.listdir(parent_dir):
        cand = os.path.join(parent_dir, name)
        if not os.path.isfile(cand):
            continue
        cand_stem, _ = os.path.splitext(name)
        if cand_stem != stem and not any(cand_stem.startswith(p) for p in sidecar_prefixes):
            continue
        try:
            os.remove(cand)
            deleted_paths.append(cand)
        except Exception:
            pass

    # 仅删除“视频专属目录”的空目录：
    # 当父目录名与主文件 stem 一致时，说明大概率是单视频目录（如 xxx/xxx.mp4）
    # 抖音合集等扁平结构通常不满足该条件，不会误删作者根目录
    try:
        parent_name = os.path.basename(parent_dir)
        if parent_name == stem and os.path.isdir(parent_dir) and not os.listdir(parent_dir):
            os.rmdir(parent_dir)
            deleted_paths.append(parent_dir)
    except Exception:
        pass

    return deleted_paths


@router.get("/{subscription_id}/videos", response_model=SubscriptionVideosResponse)
@require_license_api
async def get_subscription_videos(
    subscription_id: str,
    page: int = Query(1, gt=0),
    page_size: int = Query(20, gt=0, le=100),
    status: Optional[str] = Query(
        None,
        description="筛选状态: downloaded, not_downloaded, downloading, failed, "
                    "cancelled, orphaned, removed"
    ),
    simple: bool = Query(
        False,
        description="是否仅加载轻量级列表数据（推荐在高并发下载时使用）"
    ),
    db: Session = Depends(get_db)
):
    """获取订阅博主的视频列表

    - 默认行为保持兼容：返回当前页视频 + 各种统计字段。
    - 当 simple=true 时，仅做分页查询与任务状态映射，跳过大部分统计与写操作，
      用于在下载任务很多时减轻接口压力（前端可配合 /videos/stats 使用）。
    """
    try:
        subscription = db.query(Subscription).filter(
            Subscription.id == subscription_id
        ).first()
        if not subscription:
            raise HTTPException(status_code=404, detail="未找到该订阅")

        # 基础查询：当前订阅下的视频
        base_query = db.query(SubscriptionVideo).filter(
            SubscriptionVideo.subscription_id == subscription_id
        )

        orphan_filter = False

        # 状态筛选
        if status:
            if status == "downloaded":
                base_query = base_query.filter(SubscriptionVideo.downloaded == "true")
            elif status == "not_downloaded":
                base_query = base_query.filter(
                    SubscriptionVideo.downloaded == "false",
                    SubscriptionVideo.download_task_id.is_(None)
                )
            elif status == "downloading":
                base_query = base_query.join(
                    Task, SubscriptionVideo.download_task_id == Task.id
                ).filter(
                    Task.status.in_([
                        TaskStatus.PENDING.value,
                        TaskStatus.DOWNLOADING.value,
                        TaskStatus.PROCESSING.value
                    ])
                )
            elif status == "failed":
                base_query = base_query.outerjoin(
                    Task, SubscriptionVideo.download_task_id == Task.id
                ).filter(
                    or_(
                        SubscriptionVideo.error_message.isnot(None),
                        Task.status == TaskStatus.ERROR.value
                    )
                )
            elif status == "cancelled":
                base_query = base_query.join(
                    Task, SubscriptionVideo.download_task_id == Task.id
                ).filter(Task.status == TaskStatus.CANCELLED.value)
            elif status == "orphaned":
                # 孤儿按“文件缺失”口径计算，分页需要先做文件存在性检查
                orphan_filter = True
            elif status == "removed":
                base_query = base_query.filter(
                    SubscriptionVideo.extra_data.like('%"removed_from_source": true%')
                )
            elif status == "charging":
                base_query = base_query.filter(
                    SubscriptionVideo.extra_data.like('%"is_charging_arc": true%')
                )

        tasks_dict: dict = {}
        if orphan_filter:
            # 先按发布时间获取候选，再按文件缺失筛选，最后分页
            candidates = base_query.filter(
                SubscriptionVideo.download_task_id.isnot(None)
            ).order_by(
                SubscriptionVideo.publish_time.desc()
            ).all()

            candidate_task_ids = [v.download_task_id for v in candidates if v.download_task_id]
            if candidate_task_ids:
                tasks = db.query(Task).filter(Task.id.in_(candidate_task_ids)).all()
                tasks_dict = {task.id: task for task in tasks}

            orphan_videos = [
                v for v in candidates
                if _is_file_missing_orphan(tasks_dict.get(v.download_task_id))
            ]

            total_count = len(orphan_videos)
            start = (page - 1) * page_size
            end = start + page_size
            videos = orphan_videos[start:end]
        else:
            # 获取筛选后的总数（用于前端翻页）
            total_count = base_query.with_entities(
                SubscriptionVideo.id
            ).distinct().count()

            # 分页查询当前页
            videos = base_query.order_by(
                SubscriptionVideo.publish_time.desc()
            ).offset(
                (page - 1) * page_size
            ).limit(page_size).all()

            # 批量查询本页涉及的任务状态，避免 N+1
            video_task_ids = [v.download_task_id for v in videos if v.download_task_id]
            if video_task_ids:
                tasks = db.query(Task).filter(Task.id.in_(video_task_ids)).all()
                tasks_dict = {task.id: task for task in tasks}

        # 仅在必要范围内进行状态映射，避免在展示接口里大规模写库
        status_updated = False
        if not simple:
            # 兼容旧行为：必要时修正本页视频的 downloaded / error_message
            for video in videos:
                if not video.download_task_id:
                    continue

                task = tasks_dict.get(video.download_task_id)
                if task:
                    if task.status == TaskStatus.ERROR.value:
                        if video.downloaded != "false":
                            video.downloaded = "false"
                            status_updated = True
                        if video.error_message != task.error_message:
                            video.error_message = task.error_message
                            status_updated = True
                    elif task.status == TaskStatus.COMPLETED.value:
                        if video.downloaded != "true":
                            video.downloaded = "true"
                            status_updated = True
                        if video.error_message is not None:
                            video.error_message = None
                            status_updated = True
                    elif task.status in [
                        TaskStatus.PENDING.value,
                        TaskStatus.DOWNLOADING.value,
                        TaskStatus.PROCESSING.value
                    ]:
                        if video.downloaded != "false":
                            video.downloaded = "false"
                            status_updated = True
                else:
                    # 任务不存在，按原逻辑清理引用
                    if video.download_task_id is not None:
                        video.download_task_id = None
                        status_updated = True
                    if video.error_message is not None:
                        video.error_message = None
                        status_updated = True
                    if video.downloaded != "false":
                        video.downloaded = "false"
                        status_updated = True
                    logger.warning(
                        f"视频 {video.title} 的下载任务 {video.download_task_id} 不存在，已清理引用"
                    )

            if status_updated:
                db.commit()

        # 不论 simple 与否，都需要为前端计算每条视频的展示状态
        for video in videos:
            task = tasks_dict.get(video.download_task_id) if video.download_task_id else None
            if _is_file_missing_orphan(task):
                video.status = "orphaned"
            elif video.downloaded == "true":
                video.status = "downloaded"
            elif video.error_message:
                video.status = "failed"
            elif video.download_task_id:
                if task:
                    if task.status == TaskStatus.CANCELLED.value:
                        video.status = "cancelled"
                    elif task.status in [
                        TaskStatus.PENDING.value,
                        TaskStatus.DOWNLOADING.value,
                        TaskStatus.PROCESSING.value
                    ]:
                        video.status = "downloading"
                    elif task.status == TaskStatus.ERROR.value:
                        video.status = "failed"
                    else:
                        video.status = "unknown"
                else:
                    # 修复：task_id 存在但 task 不存在的情况（通常发生在取消下载）
                    # 直接清理无效引用，确保视频能出现在"未下载"分类中
                    video.download_task_id = None
                    video.downloaded = "false"
                    status_updated = True
                    logger.info(
                        f"视频 {video.title} 的任务已被清理，自动重置为未下载状态"
                    )
                    video.status = "not_downloaded"
            else:
                video.status = "not_downloaded"

            # 检查是否已从源平台移除
            video.removed_from_source = False
            if video.extra_data:
                try:
                    extra = json.loads(video.extra_data)
                    video.removed_from_source = extra.get('removed_from_source', False)
                except Exception:
                    pass

        # 如果在状态判断过程中有清理操作，提交事务
        if status_updated:
            db.commit()

        # simple=true：仅返回当前页 + total，其余统计交给独立接口
        if simple:
            return {
                "total": total_count,
                "downloaded_count": 0,
                "not_downloaded_count": 0,
                "downloading_count": 0,
                "failed_count": 0,
                "cancelled_count": 0,
                "orphaned_count": 0,
                "removed_count": 0,
                "charging_count": 0,
                "video_count": total_count,
                "note_count": 0,
                "videos": videos,
            }

        # 兼容旧行为：在非 simple 模式下继续返回完整统计信息
        all_videos_query = db.query(SubscriptionVideo).filter(
            SubscriptionVideo.subscription_id == subscription_id
        )

        stats_query = db.query(
            func.count(case(
                (SubscriptionVideo.downloaded == "true", 1)
            )).label('downloaded'),
            func.count(case(
                (and_(
                    SubscriptionVideo.downloaded == "false",
                    SubscriptionVideo.download_task_id.is_(None)
                ), 1)
            )).label('not_downloaded'),
            func.count(case(
                (and_(
                    SubscriptionVideo.download_task_id.isnot(None),
                    Task.status.in_([
                        TaskStatus.PENDING.value,
                        TaskStatus.DOWNLOADING.value,
                        TaskStatus.PROCESSING.value
                    ])
                ), 1)
            )).label('downloading'),
            func.count(case(
                (or_(
                    SubscriptionVideo.error_message.isnot(None),
                    and_(
                        SubscriptionVideo.download_task_id.isnot(None),
                        Task.status == TaskStatus.ERROR.value
                    )
                ), 1)
            )).label('failed'),
            func.count(case(
                (and_(
                    SubscriptionVideo.download_task_id.isnot(None),
                    Task.status == TaskStatus.CANCELLED.value
                ), 1)
            )).label('cancelled'),
            func.count(case(
                (and_(
                    SubscriptionVideo.download_task_id.isnot(None),
                    Task.id.is_(None)
                ), 1)
            )).label('orphaned'),
            func.count(case(
                (SubscriptionVideo.extra_data.like('%"removed_from_source": true%'), 1)
            )).label('removed')
        ).outerjoin(
            Task, SubscriptionVideo.download_task_id == Task.id
        ).filter(
            SubscriptionVideo.subscription_id == subscription_id
        ).first()

        downloaded_count = stats_query.downloaded or 0
        not_downloaded_count = stats_query.not_downloaded or 0
        downloading_count = stats_query.downloading or 0
        failed_count = stats_query.failed or 0
        cancelled_count = stats_query.cancelled or 0
        orphaned_count = 0
        removed_count = stats_query.removed or 0

        # 孤儿口径改为“文件缺失”：task.filename 对应本地目标不存在
        task_rows = all_videos_query.with_entities(
            SubscriptionVideo.downloaded,
            SubscriptionVideo.download_task_id
        ).filter(
            SubscriptionVideo.download_task_id.isnot(None)
        ).all()

        task_ids = list({row[1] for row in task_rows if row[1]})
        orphan_task_map = {}
        if task_ids:
            task_list = db.query(Task).filter(Task.id.in_(task_ids)).all()
            orphan_task_map = {t.id: t for t in task_list}

        downloaded_orphan_count = 0
        for downloaded_flag, task_id in task_rows:
            task = orphan_task_map.get(task_id)
            if _is_file_missing_orphan(task):
                orphaned_count += 1
                if str(downloaded_flag).lower() == "true":
                    downloaded_orphan_count += 1

        if downloaded_orphan_count > 0:
            downloaded_count = max(0, downloaded_count - downloaded_orphan_count)

        # 统计视频 / 图集数量
        if subscription.platform == 'douyin':
            video_count = all_videos_query.filter(
                SubscriptionVideo.url.like('%/video/%')
            ).count()
            note_count = all_videos_query.filter(
                SubscriptionVideo.url.like('%/note/%')
            ).count()
        elif subscription.platform == 'instagram':
            video_count = all_videos_query.filter(
                or_(
                    SubscriptionVideo.extra_data.like('%"platform_media_type": "video"%'),
                    SubscriptionVideo.extra_data.like('%"platform_media_type":"video"%')
                )
            ).count()
            note_count = all_videos_query.filter(
                or_(
                    SubscriptionVideo.extra_data.like('%"platform_media_type": "image"%'),
                    SubscriptionVideo.extra_data.like('%"platform_media_type":"image"%')
                )
            ).count()
        elif subscription.platform == 'xiaohongshu':
            video_count = all_videos_query.filter(
                or_(
                    SubscriptionVideo.extra_data.like('%"type": "video"%'),
                    SubscriptionVideo.extra_data.like('%"type":"video"%')
                )
            ).count()
            note_count = all_videos_query.filter(
                or_(
                    SubscriptionVideo.extra_data.like('%"type": "normal"%'),
                    SubscriptionVideo.extra_data.like('%"type":"normal"%')
                )
            ).count()
        else:
            video_count = total_count
            note_count = 0

        # B 站充电专属统计
        charging_count = 0
        if subscription.platform.startswith('bilibili'):
            charging_count = all_videos_query.filter(
                or_(
                    SubscriptionVideo.extra_data.like('%"is_charging_arc": true%'),
                    SubscriptionVideo.extra_data.like('%"is_charging_arc":true%')
                )
            ).count()

        return {
            "total": total_count,
            "downloaded_count": downloaded_count,
            "not_downloaded_count": not_downloaded_count,
            "downloading_count": downloading_count,
            "failed_count": failed_count,
            "cancelled_count": cancelled_count,
            "orphaned_count": max(0, orphaned_count),
            "removed_count": removed_count,
            "charging_count": charging_count,
            "video_count": video_count,
            "note_count": note_count,
            "videos": videos,
        }

    except Exception as e:
        logger.error(f"获取视频列表失败: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{subscription_id}/video/{video_id}/local-thumbnail")
@require_license_api
async def get_subscription_video_local_thumbnail(
    subscription_id: str,
    video_id: str,
    db: Session = Depends(get_db)
):
    """返回订阅视频对应的本地缩略图地址（用于网络封面失败时兜底）。"""
    try:
        video = db.query(SubscriptionVideo).filter(
            SubscriptionVideo.id == video_id,
            SubscriptionVideo.subscription_id == subscription_id
        ).first()
        if not video:
            raise HTTPException(status_code=404, detail="未找到视频记录")

        if not video.download_task_id:
            raise HTTPException(status_code=404, detail="视频暂无下载任务记录")

        task = db.query(Task).filter(Task.id == video.download_task_id).first()
        if not task or not task.filename:
            raise HTTPException(status_code=404, detail="未找到下载文件路径")

        thumbnail_url = _build_local_thumbnail_url(task.filename)
        if not thumbnail_url:
            raise HTTPException(status_code=404, detail="未找到本地缩略图")

        return {
            "success": True,
            "thumbnail_url": thumbnail_url
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取本地缩略图失败: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{subscription_id}/video/{video_id}/nfo")
@require_license_api
async def get_subscription_video_nfo(
    subscription_id: str,
    video_id: str,
    db: Session = Depends(get_db)
):
    """读取订阅视频对应的 NFO 内容。"""
    try:
        video = db.query(SubscriptionVideo).filter(
            SubscriptionVideo.id == video_id,
            SubscriptionVideo.subscription_id == subscription_id
        ).first()
        if not video:
            raise HTTPException(status_code=404, detail="未找到视频记录")

        if not video.download_task_id:
            raise HTTPException(status_code=404, detail="视频暂无下载任务记录")

        task = db.query(Task).filter(Task.id == video.download_task_id).first()
        if not task or not task.filename:
            raise HTTPException(status_code=404, detail="未找到下载文件路径")

        nfo_path = _resolve_nfo_abs_path(task.filename)
        if not nfo_path:
            raise HTTPException(status_code=404, detail="未找到NFO文件")

        content = _read_nfo_content(nfo_path)
        rel_nfo_path = os.path.relpath(nfo_path, DOWNLOAD_ROOT).replace("\\", "/")

        return {
            "success": True,
            "content": content,
            "nfo_path": f"/downloads/{rel_nfo_path}"
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"读取NFO失败: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{subscription_id}/video/{video_id}/nfo/exists")
@require_license_api
async def check_subscription_video_nfo_exists(
    subscription_id: str,
    video_id: str,
    db: Session = Depends(get_db)
):
    """检查订阅视频是否存在可编辑的 NFO 文件。"""
    try:
        video = db.query(SubscriptionVideo).filter(
            SubscriptionVideo.id == video_id,
            SubscriptionVideo.subscription_id == subscription_id
        ).first()
        if not video:
            raise HTTPException(status_code=404, detail="未找到视频记录")

        if not video.download_task_id:
            return {"success": True, "has_nfo": False}

        task = db.query(Task).filter(Task.id == video.download_task_id).first()
        if not task or not task.filename:
            return {"success": True, "has_nfo": False}

        nfo_path = _resolve_nfo_abs_path(task.filename)
        return {"success": True, "has_nfo": bool(nfo_path)}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"检查NFO存在性失败: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/{subscription_id}/video/{video_id}/nfo")
@require_license_api
async def update_subscription_video_nfo(
    subscription_id: str,
    video_id: str,
    payload: NfoUpdateRequest,
    db: Session = Depends(get_db)
):
    """覆盖写入订阅视频对应的 NFO 内容。"""
    try:
        video = db.query(SubscriptionVideo).filter(
            SubscriptionVideo.id == video_id,
            SubscriptionVideo.subscription_id == subscription_id
        ).first()
        if not video:
            raise HTTPException(status_code=404, detail="未找到视频记录")

        if not video.download_task_id:
            raise HTTPException(status_code=404, detail="视频暂无下载任务记录")

        task = db.query(Task).filter(Task.id == video.download_task_id).first()
        if not task or not task.filename:
            raise HTTPException(status_code=404, detail="未找到下载文件路径")

        nfo_path = _resolve_nfo_abs_path(task.filename)
        if not nfo_path:
            raise HTTPException(status_code=404, detail="未找到NFO文件")

        with open(nfo_path, "w", encoding="utf-8-sig") as f:
            f.write(payload.content or "")

        return {
            "success": True,
            "message": "NFO更新成功"
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"更新NFO失败: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{subscription_id}/videos/stats")
@require_license_api
async def get_subscription_videos_stats(
    subscription_id: str,
    db: Session = Depends(get_db)
):
    """获取订阅博主的视频下载状态统计（不返回具体视频列表）

    供前端在需要精确统计时单独调用，以避免在列表接口中重复做重型统计。
    """
    try:
        subscription = db.query(Subscription).filter(
            Subscription.id == subscription_id
        ).first()
        if not subscription:
            raise HTTPException(status_code=404, detail="未找到该订阅")

        all_videos_query = db.query(SubscriptionVideo).filter(
            SubscriptionVideo.subscription_id == subscription_id
        )

        total_count = all_videos_query.with_entities(
            SubscriptionVideo.id
        ).distinct().count()

        stats_query = db.query(
            func.count(case(
                (SubscriptionVideo.downloaded == "true", 1)
            )).label('downloaded'),
            func.count(case(
                (and_(
                    SubscriptionVideo.downloaded == "false",
                    SubscriptionVideo.download_task_id.is_(None)
                ), 1)
            )).label('not_downloaded'),
            func.count(case(
                (and_(
                    SubscriptionVideo.download_task_id.isnot(None),
                    Task.status.in_([
                        TaskStatus.PENDING.value,
                        TaskStatus.DOWNLOADING.value,
                        TaskStatus.PROCESSING.value
                    ])
                ), 1)
            )).label('downloading'),
            func.count(case(
                (or_(
                    SubscriptionVideo.error_message.isnot(None),
                    and_(
                        SubscriptionVideo.download_task_id.isnot(None),
                        Task.status == TaskStatus.ERROR.value
                    )
                ), 1)
            )).label('failed'),
            func.count(case(
                (and_(
                    SubscriptionVideo.download_task_id.isnot(None),
                    Task.status == TaskStatus.CANCELLED.value
                ), 1)
            )).label('cancelled'),
            func.count(case(
                (and_(
                    SubscriptionVideo.download_task_id.isnot(None),
                    Task.id.is_(None)
                ), 1)
            )).label('orphaned'),
            func.count(case(
                (SubscriptionVideo.extra_data.like('%"removed_from_source": true%'), 1)
            )).label('removed')
        ).outerjoin(
            Task, SubscriptionVideo.download_task_id == Task.id
        ).filter(
            SubscriptionVideo.subscription_id == subscription_id
        ).first()

        downloaded_count = stats_query.downloaded or 0
        not_downloaded_count = stats_query.not_downloaded or 0
        downloading_count = stats_query.downloading or 0
        failed_count = stats_query.failed or 0
        cancelled_count = stats_query.cancelled or 0
        orphaned_count = 0
        removed_count = stats_query.removed or 0

        task_rows = all_videos_query.with_entities(
            SubscriptionVideo.downloaded,
            SubscriptionVideo.download_task_id
        ).filter(
            SubscriptionVideo.download_task_id.isnot(None)
        ).all()

        task_ids = list({row[1] for row in task_rows if row[1]})
        orphan_task_map = {}
        if task_ids:
            task_list = db.query(Task).filter(Task.id.in_(task_ids)).all()
            orphan_task_map = {t.id: t for t in task_list}

        downloaded_orphan_count = 0
        for downloaded_flag, task_id in task_rows:
            task = orphan_task_map.get(task_id)
            if _is_file_missing_orphan(task):
                orphaned_count += 1
                if str(downloaded_flag).lower() == "true":
                    downloaded_orphan_count += 1

        if downloaded_orphan_count > 0:
            downloaded_count = max(0, downloaded_count - downloaded_orphan_count)

        if subscription.platform == 'douyin':
            video_count = all_videos_query.filter(
                SubscriptionVideo.url.like('%/video/%')
            ).count()
            note_count = all_videos_query.filter(
                SubscriptionVideo.url.like('%/note/%')
            ).count()
        elif subscription.platform == 'instagram':
            video_count = all_videos_query.filter(
                or_(
                    SubscriptionVideo.extra_data.like('%"platform_media_type": "video"%'),
                    SubscriptionVideo.extra_data.like('%"platform_media_type":"video"%')
                )
            ).count()
            note_count = all_videos_query.filter(
                or_(
                    SubscriptionVideo.extra_data.like('%"platform_media_type": "image"%'),
                    SubscriptionVideo.extra_data.like('%"platform_media_type":"image"%')
                )
            ).count()
        elif subscription.platform == 'xiaohongshu':
            video_count = all_videos_query.filter(
                or_(
                    SubscriptionVideo.extra_data.like('%"type": "video"%'),
                    SubscriptionVideo.extra_data.like('%"type":"video"%')
                )
            ).count()
            note_count = all_videos_query.filter(
                or_(
                    SubscriptionVideo.extra_data.like('%"type": "normal"%'),
                    SubscriptionVideo.extra_data.like('%"type":"normal"%')
                )
            ).count()
        else:
            video_count = total_count
            note_count = 0

        charging_count = 0
        if subscription.platform.startswith('bilibili'):
            charging_count = all_videos_query.filter(
                or_(
                    SubscriptionVideo.extra_data.like('%"is_charging_arc": true%'),
                    SubscriptionVideo.extra_data.like('%"is_charging_arc":true%')
                )
            ).count()

        return {
            "total": total_count,
            "downloaded_count": downloaded_count,
            "not_downloaded_count": not_downloaded_count,
            "downloading_count": downloading_count,
            "failed_count": failed_count,
            "cancelled_count": cancelled_count,
            "orphaned_count": max(0, orphaned_count),
            "removed_count": removed_count,
            "charging_count": charging_count,
            "video_count": video_count,
            "note_count": note_count,
        }

    except Exception as e:
        logger.error(f"获取订阅统计失败: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/{subscription_id}/videos/orphan/cleanup")
@require_license_api
async def cleanup_subscription_orphan_videos(
    subscription_id: str,
    db: Session = Depends(get_db)
):
    """清理订阅视频中的“文件缺失孤儿”：
    1) 删除残留文件/目录（默认）
    2) 重置 SubscriptionVideo 下载状态
    3) 删除关联 Task 记录
    """
    try:
        subscription = db.query(Subscription).filter(
            Subscription.id == subscription_id
        ).first()
        if not subscription:
            raise HTTPException(status_code=404, detail="未找到该订阅")

        videos = db.query(SubscriptionVideo).filter(
            SubscriptionVideo.subscription_id == subscription_id,
            SubscriptionVideo.download_task_id.isnot(None)
        ).all()

        task_ids = list({v.download_task_id for v in videos if v.download_task_id})
        task_map = {}
        if task_ids:
            task_list = db.query(Task).filter(Task.id.in_(task_ids)).all()
            task_map = {t.id: t for t in task_list}

        matched = 0
        reset_videos = 0
        deleted_tasks = 0
        deleted_paths: List[str] = []
        errors: List[str] = []
        task_ids_to_delete = set()

        for video in videos:
            task = task_map.get(video.download_task_id)
            if not _is_file_missing_orphan(task):
                continue

            matched += 1

            try:
                if task and task.id:
                    task_ids_to_delete.add(task.id)
                deleted_paths.extend(_delete_orphan_residuals(task.filename if task else None))

                if video.downloaded != "false":
                    video.downloaded = "false"
                if video.download_task_id is not None:
                    video.download_task_id = None
                if video.error_message is not None:
                    video.error_message = None
                reset_videos += 1
            except Exception as item_exc:
                errors.append(f"video_id={video.id}: {str(item_exc)}")

        if task_ids_to_delete:
            deleted_tasks = db.query(Task).filter(
                Task.id.in_(list(task_ids_to_delete)),
                Task.subscription_id == subscription_id
            ).delete(synchronize_session=False)

        db.commit()

        # 去重输出路径
        dedup_paths = []
        seen = set()
        for p in deleted_paths:
            if p in seen:
                continue
            seen.add(p)
            dedup_paths.append(p)

        return {
            "success": True,
            "subscription_id": subscription_id,
            "matched": matched,
            "reset_videos": reset_videos,
            "deleted_tasks": deleted_tasks,
            "deleted_paths_count": len(dedup_paths),
            "deleted_paths": dedup_paths,
            "errors": errors,
        }
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"清理订阅孤儿失败: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{subscription_id}/failed_videos", response_model=List[SubscriptionVideoResponse])
@require_license_api
async def get_failed_videos(
    subscription_id: str,
    db: Session = Depends(get_db)
):
    """获取下载失败的视频列表"""
    try:
        # 获取订阅信息
        subscription = db.query(Subscription).filter(
            Subscription.id == subscription_id
        ).first()
        
        if not subscription:
            raise HTTPException(status_code=404, detail="未找到该订阅")
            
        # 获取失败的视频列表 - 改进逻辑以识别所有失败的视频
        failed_videos = []
        
        # 方法1：通过JOIN查询查找任务状态为ERROR的视频
        error_task_videos = db.query(SubscriptionVideo).join(
            Task, SubscriptionVideo.download_task_id == Task.id
        ).filter(
            SubscriptionVideo.subscription_id == subscription_id,
            Task.status == TaskStatus.ERROR.value
        ).all()
        failed_videos.extend(error_task_videos)
        
        # 方法2：查找有错误信息但没有关联任务的视频
        error_message_videos = db.query(SubscriptionVideo).filter(
            SubscriptionVideo.subscription_id == subscription_id,
            SubscriptionVideo.downloaded == "false",
            SubscriptionVideo.error_message != None,
            SubscriptionVideo.download_task_id == None
        ).all()
        failed_videos.extend(error_message_videos)
        
        # 方法3：查找状态为failed但没有错误信息的视频
        failed_status_videos = db.query(SubscriptionVideo).filter(
            SubscriptionVideo.subscription_id == subscription_id,
            SubscriptionVideo.downloaded == "false",
            SubscriptionVideo.error_message == None,
            SubscriptionVideo.download_task_id == None
        ).all()
        
        # 检查这些视频是否应该被标记为失败
        for video in failed_status_videos:
            # 如果视频有下载任务ID但任务不存在，说明任务被删除了
            if video.download_task_id:
                task = db.query(Task).filter(Task.id == video.download_task_id).first()
                if not task:
                    # 任务不存在，标记为失败
                    video.error_message = "下载任务已丢失"
                    failed_videos.append(video)
        
        # 去重
        failed_videos = list({video.id: video for video in failed_videos}.values())
        
        return failed_videos
        
    except Exception as e:
        logger.error(f"获取失败视频列表失败: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))
