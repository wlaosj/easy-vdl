"""
下载相关路由
"""
import asyncio
import uuid
from datetime import datetime, timedelta
from fastapi import APIRouter, HTTPException, Depends
from sqlalchemy.orm import Session
from sql.database_postgresql import get_db
from sql.models import Subscription, SubscriptionVideo, Task, TaskStatus
from routers.auth import require_license_api
from routers.downloader import download_manager
from .common import logger, cancelled_batch_downloads, get_platform_anti_crawl_config
from .videos import _get_video_media_type
from .models import RetryFailedDownloadsRequest, BatchDownloadRequest, VideoDownloadRequest
from .utils import (
    process_download_queue,
    update_batch_download_progress,
    get_subscription_download_dir,
    _force_delete_directory,
    _force_delete_files,
    _fix_file_permissions,
    _async_add_download
)

router = APIRouter()

# 这些平台缺少稳定的真实发布时间，不支持按发布时间筛选批量下载
TIME_FILTER_UNSUPPORTED_PLATFORMS = {"xiaohongshu", "netease"}


def _supports_time_filter(subscription: Subscription) -> bool:
    platform = (subscription.platform or "").lower()
    if platform in TIME_FILTER_UNSUPPORTED_PLATFORMS:
        return False
    if platform == "youtube" and (subscription.youtube_tab_type or "").lower() == "shorts":
        return False
    if platform == "youtube_shorts":
        return False
    return True


@router.post("/video/{video_id}/download")
@require_license_api
async def download_video(
    video_id: str,
    request: VideoDownloadRequest = None,
    db: Session = Depends(get_db)
):
    """手动下载指定视频"""
    try:
        # 1. 获取视频信息
        video = db.query(SubscriptionVideo).filter(
            SubscriptionVideo.id == video_id
        ).first()
        
        if not video:
            raise HTTPException(status_code=404, detail="未找到该视频")
            
        # 2. 如果视频已经下载，返回提示
        if video.downloaded.lower() == "true":
            return {"message": "视频已下载"}
            
        # 3. 获取订阅信息
        subscription = db.query(Subscription).filter(
            Subscription.id == video.subscription_id
        ).first()
        
        if not subscription:
            raise HTTPException(status_code=404, detail="未找到相关订阅信息")
            
        # 4. 确定画质设置
        # 如果请求中有画质设置，使用请求中的；否则使用订阅中的默认画质设置
        quality = request.quality if request else subscription.quality
        
        # 5. 添加到下载队列
        task_id = await download_manager.add_subscription_download(video, quality, db)
        
        # 返回成功响应
        return {"message": "已添加到下载队列", "task_id": task_id}
    except Exception as e:
        logger.error(f"添加下载任务失败: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/video/{video_id}")
@require_license_api
async def delete_subscription_video(
    video_id: str,
    db: Session = Depends(get_db)
):
    """删除指定的订阅视频记录"""
    try:
        video = db.query(SubscriptionVideo).filter(
            SubscriptionVideo.id == video_id
        ).first()
        
        if not video:
            raise HTTPException(status_code=404, detail="未找到该视频")
            
        db.delete(video)
        db.commit()
        
        return {"message": "视频记录已删除"}
        
    except Exception as e:
        logger.error(f"删除视频失败: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/video/{video_id}/redownload")
@require_license_api
async def redownload_video(
    video_id: str,
    db: Session = Depends(get_db)
):
    """重新下载指定视频"""
    try:
        from routers.file_manager import cleanup_task_before_retry

        # 1. 获取视频信息
        video = db.query(SubscriptionVideo).filter(
            SubscriptionVideo.id == video_id
        ).first()
        
        if not video:
            raise HTTPException(status_code=404, detail="未找到该视频")
            
        # 2. 重置下载状态（先清理旧任务残留）
        if video.download_task_id:
            old_task = db.query(Task).filter(Task.id == video.download_task_id).first()
            if old_task:
                cleanup_task_before_retry(old_task, mode="full_output")

        video.downloaded = "false"
        video.download_task_id = None
        video.error_message = None  # 清除之前的错误信息
        db.commit()
        
        # 3. 获取订阅信息
        subscription = db.query(Subscription).filter(
            Subscription.id == video.subscription_id
        ).first()
        
        # 4. 创建新的下载任务记录
        now = datetime.now()
        task_id = str(uuid.uuid4())
        # 优先根据订阅平台确定 source，避免小红书等被误标为抖音
        if subscription:
            platform = (subscription.platform or "").lower()
            # 兼容 *_collection / *_playlist 这类平台标识
            if platform in ["douyin_collection"]:
                source = "douyin"
            elif platform in ["youtube_playlist"]:
                source = "youtube"
            elif platform in ["douyin", "youtube", "bilibili", "xiaohongshu", "tiktok", "netease", "x"]:
                source = platform
            else:
                source = "unknown"
        else:
            # 没有关联订阅时，退回到按 URL 判断
            if video.url.startswith("https://www.youtube.com") or video.url.startswith("https://youtu.be"):
                source = "youtube"
            elif video.url.startswith("https://www.tiktok.com") or video.url.startswith("https://vt.tiktok.com"):
                source = "tiktok"
            elif video.url.startswith("https://www.bilibili.com") or video.url.startswith("https://b23.tv"):
                source = "bilibili"
            elif video.url.startswith("https://www.douyin.com") or video.url.startswith("https://v.douyin.com"):
                source = "douyin"
            elif video.url.startswith("https://www.xiaohongshu.com") or video.url.startswith("https://xhslink.com"):
                source = "xiaohongshu"
            elif video.url.startswith("https://x.com") or video.url.startswith("https://twitter.com"):
                source = "x"
            else:
                source = "unknown"

        task = Task(
            id=task_id,
            source=source,
            url=video.url,
            title=video.title,
            status=TaskStatus.PENDING.value,
            progress=0.0,
            created_at=now,
            updated_at=now,
            subscription_id=video.subscription_id
        )
        db.add(task)
        db.commit()
        
        # 5. 更新视频的下载任务ID
        video.download_task_id = task_id
        db.commit()
        
        # 统一走下载管理器队列，避免平台分支遗漏导致错误路由（例如 B站误走 dyd）
        queue_subscription_id = video.subscription_id if video.subscription_id else None
        asyncio.create_task(download_manager._add_to_queue(task_id, queue_subscription_id, video.title))
        
        return {"message": "已重新添加到下载队列", "task_id": task_id}
        
    except Exception as e:
        logger.error(f"重新下载视频失败: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/{subscription_id}/retry_failed")
@require_license_api
async def retry_failed_downloads(
    subscription_id: str,
    request: RetryFailedDownloadsRequest = None,
    db: Session = Depends(get_db)
):
    """重试失败的下载任务"""
    try:
        from routers.file_manager import cleanup_task_before_retry

        # 获取订阅信息
        subscription = db.query(Subscription).filter(
            Subscription.id == subscription_id
        ).first()
        
        if not subscription:
            raise HTTPException(status_code=404, detail="未找到该订阅")
        
        # 如果没有传递参数,使用默认值
        if request is None:
            request = RetryFailedDownloadsRequest()
            
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
            if video.download_task_id:
                task = db.query(Task).filter(Task.id == video.download_task_id).first()
                if not task:
                    video.error_message = "下载任务已丢失"
                    failed_videos.append(video)
        
        # 去重
        failed_videos = list({video.id: video for video in failed_videos}.values())
        
        if not failed_videos:
            return {"message": "没有失败的任务需要重试"}
        
        # 采用和批量重试一样的逻辑：删除旧任务，走 process_download_queue 统一调度
        retry_count = 0
        
        for video in failed_videos:
            try:
                if video.download_task_id:
                    old_task = db.query(Task).filter(Task.id == video.download_task_id).first()
                    if old_task:
                        cleanup_task_before_retry(old_task, mode="temp_only")
                        db.delete(old_task)
                        logger.info(f"删除旧任务 {video.download_task_id} for video: {video.title}")
                
                video.error_message = None
                video.download_task_id = None
                video.downloaded = "false"
                retry_count += 1
                    
            except Exception as e:
                logger.error(f"重置任务状态时出错: {str(e)}")
                continue
        
        # 提交所有状态重置操作
        db.commit()
        
        if retry_count > 0:
            subscription.batch_download_status = "downloading"
            subscription.batch_download_progress = 0
            subscription.batch_download_total = retry_count
            subscription.batch_download_completed = 0
            subscription.batch_download_failed = 0
            subscription.batch_download_start_time = datetime.now()
            db.commit()
            
            asyncio.create_task(process_download_queue(
                subscription_id,
                failed_videos,
                request.quality,
                request.batch_size or 1
            ))
            
            return {
                "message": f"已重新添加 {retry_count} 个失败任务到下载队列",
                "task_count": retry_count
            }
        else:
            return {"message": "没有任务被重新添加到下载队列"}
            
    except Exception as e:
        logger.error(f"重试失败任务失败: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/{subscription_id}/dismiss_failed")
@require_license_api
async def dismiss_failed_status(
    subscription_id: str,
    db: Session = Depends(get_db)
):
    """关闭失败状态提示"""
    try:
        subscription = db.query(Subscription).filter(
            Subscription.id == subscription_id
        ).first()
        
        if not subscription:
            raise HTTPException(status_code=404, detail="未找到该订阅")
            
        # 清除批量下载状态
        subscription.batch_download_status = None
        subscription.batch_download_progress = None
        subscription.batch_download_total = None
        subscription.batch_download_completed = None
        subscription.batch_download_failed = None
        subscription.batch_download_start_time = None
        
        db.commit()
        
        return {"message": "已关闭失败状态提示"}
        
    except Exception as e:
        logger.error(f"关闭失败状态提示失败: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/{subscription_id}/batch_download")
@require_license_api
async def batch_download(
    subscription_id: str,
    request: BatchDownloadRequest,
    db: Session = Depends(get_db),
    progress_callback = None
):
    """批量下载视频"""
    try:
        subscription = db.query(Subscription).filter(
            Subscription.id == subscription_id
        ).first()
        
        if not subscription:
            raise HTTPException(status_code=404, detail="未找到该订阅")

        if subscription.sync_status == "syncing":
            raise HTTPException(status_code=400, detail="正在同步视频，请等待同步完成后再开始下载")

        if subscription.batch_download_status == "downloading":
            raise HTTPException(status_code=400, detail="已有正在进行的下载任务")

        if request.type == "time" and not _supports_time_filter(subscription):
            raise HTTPException(
                status_code=400,
                detail="当前平台缺少稳定发布时间，不支持按日期批量下载，请改用按数量下载"
            )

        query = db.query(SubscriptionVideo).filter(
            SubscriptionVideo.subscription_id == subscription_id,
            SubscriptionVideo.downloaded == "false"
        )

        if request.type == "count" and request.count and request.count > 0:
            query = query.order_by(SubscriptionVideo.publish_time.desc())
            if request.count != -1:
                query = query.limit(request.count)
        elif request.type == "time" and request.days:
            cutoff_date = datetime.now() - timedelta(days=request.days)
            query = query.filter(SubscriptionVideo.publish_time >= cutoff_date)

        videos = query.all()
        if request.media_type:
            videos = [v for v in videos if _get_video_media_type(v) == request.media_type]
        if not videos:
            return {"message": "没有需要下载的视频", "count": 0}

        subscription.batch_download_status = "downloading"
        subscription.batch_download_progress = 0
        subscription.batch_download_total = len(videos)
        subscription.batch_download_completed = 0
        subscription.batch_download_failed = 0
        subscription.batch_download_start_time = datetime.now()
        db.commit()

        asyncio.create_task(process_download_queue(subscription_id, videos, request.quality, request.batch_size, progress_callback=progress_callback))

        return {
            "message": "批量下载任务已创建",
            "count": len(videos)
        }

    except Exception as e:
        logger.error(f"创建批量下载任务失败: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/{subscription_id}/batch_download/retry")
@require_license_api
async def retry_failed_downloads_batch(
    subscription_id: str,
    request: RetryFailedDownloadsRequest,
    db: Session = Depends(get_db)
):
    """重试失败的下载任务（批量下载专用）"""
    try:
        from routers.file_manager import cleanup_task_before_retry

        subscription = db.query(Subscription).filter(
            Subscription.id == subscription_id
        ).first()
        
        if not subscription:
            raise HTTPException(status_code=404, detail="未找到该订阅")

        failed_videos = []
        
        error_videos = db.query(SubscriptionVideo).filter(
            SubscriptionVideo.subscription_id == subscription_id,
            SubscriptionVideo.downloaded == "false",
            SubscriptionVideo.error_message != None
        ).all()
        failed_videos.extend(error_videos)
        
        failed_status_videos = db.query(SubscriptionVideo).filter(
            SubscriptionVideo.subscription_id == subscription_id,
            SubscriptionVideo.downloaded == "false",
            SubscriptionVideo.error_message == None
        ).all()
        
        for video in failed_status_videos:
            if video.download_task_id:
                task = db.query(Task).filter(Task.id == video.download_task_id).first()
                if task and task.status == TaskStatus.ERROR.value:
                    failed_videos.append(video)
                    video.error_message = task.error_message or "下载任务失败"
        
        error_tasks = db.query(Task).filter(
            Task.subscription_id == subscription_id,
            Task.status == TaskStatus.ERROR.value
        ).all()
        
        for task in error_tasks:
            video = db.query(SubscriptionVideo).filter(
                SubscriptionVideo.download_task_id == task.id
            ).first()
            if video and video not in failed_videos:
                failed_videos.append(video)
                if not video.error_message:
                    video.error_message = task.error_message or "下载任务失败"

        failed_videos = list({video.id: video for video in failed_videos}.values())

        if not failed_videos:
            return {"message": "没有需要重试的失败视频", "count": 0}

        for video in failed_videos:
            if video.download_task_id:
                old_task = db.query(Task).filter(Task.id == video.download_task_id).first()
                if old_task:
                    cleanup_task_before_retry(old_task, mode="temp_only")
                    db.delete(old_task)
                    logger.info(f"删除旧的失败任务: {video.download_task_id} for video: {video.title}")
            
            video.error_message = None
            video.download_task_id = None
            video.downloaded = "false"
        
        db.commit()

        subscription.batch_download_status = "downloading"
        subscription.batch_download_progress = 0
        subscription.batch_download_total = len(failed_videos)
        subscription.batch_download_completed = 0
        subscription.batch_download_failed = 0
        subscription.batch_download_start_time = datetime.now()
        db.commit()

        asyncio.create_task(process_download_queue(
            subscription_id, 
            failed_videos, 
            request.quality, 
            request.batch_size
        ))

        return {
            "message": f"重试任务已创建，将使用画质 {request.quality} 和并发数 {request.batch_size}",
            "count": len(failed_videos)
        }

    except Exception as e:
        logger.error(f"重试失败的下载任务失败: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/{subscription_id}/batch_download/cancel")
@require_license_api
async def cancel_batch_download(
    subscription_id: str,
    db: Session = Depends(get_db)
):
    """取消批量下载任务 - 立即生效，不等待"""
    try:
        subscription = db.query(Subscription).filter(
            Subscription.id == subscription_id
        ).first()
        
        if not subscription:
            raise HTTPException(status_code=404, detail="未找到该订阅")

        if subscription.batch_download_status != "downloading":
            return {"message": "没有正在进行的下载任务"}

        cancelled_batch_downloads.add(subscription_id)
        logger.info(f"已添加到取消集合: {subscription_id}")

        removed_from_queue = 0
        queue_items_to_remove = []
        for item in download_manager.download_queue:
            task_id, sub_id = item
            if sub_id == subscription_id:
                queue_items_to_remove.append(item)
        
        for item in queue_items_to_remove:
            try:
                download_manager.download_queue.remove(item)
                removed_from_queue += 1
            except ValueError:
                pass
        
        if removed_from_queue > 0:
            logger.info(f"已从队列移除 {removed_from_queue} 个未开始的任务")

        cancelled_tasks_count = 0
        pending_tasks = db.query(Task).filter(
            Task.subscription_id == subscription_id,
            Task.status == TaskStatus.PENDING.value
        ).all()
        
        for task in pending_tasks:
            task.status = TaskStatus.CANCELLED.value
            task.updated_at = datetime.now()
            cancelled_tasks_count += 1
        
        subscription.batch_download_status = "cancelled"
        subscription.batch_download_progress = None
        subscription.batch_download_total = None
        subscription.batch_download_completed = None
        subscription.batch_download_failed = None
        subscription.batch_download_start_time = None
        db.commit()
        
        logger.info(f"已取消批量下载任务: {subscription_id}, 取消了 {cancelled_tasks_count} 个待处理任务")
        
        return {
            "message": "批量下载任务已取消",
            "cancelled_tasks": cancelled_tasks_count,
            "removed_from_queue": removed_from_queue
        }
        
    except Exception as e:
        logger.error(f"取消批量下载任务失败: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))
