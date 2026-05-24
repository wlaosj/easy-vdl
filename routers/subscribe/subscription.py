"""
订阅 CRUD 操作路由
"""
import asyncio
import uuid
import json
import re
import random
import httpx
from datetime import datetime
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, or_, and_
from sqlalchemy.orm import Session
from sql.database_postgresql import get_db, get_session
from sql.models import Subscription, SubscriptionVideo, Platform, SubscriptionStatus, SubscriptionCreate, SubscriptionUpdate, SubscriptionResponse
from routers.auth import require_license_api
from .common import logger
from .platforms import registry
from .utils import _is_douyin_collection_url, get_correct_douyin_url, generate_profile_url
from .models import QualityUpdateRequest, DouyinBatchAddRequest, DouyinBatchAddResponse
from .rename import SubscriptionRenameRequest, rename_bilibili_collection_subscription

# 导入平台API（保留用于特殊场景）
from routers.douyin import douyin_api, parse_collection_url, get_collection_videos
from routers.youtube import youtube_api
from routers.tiktok import tiktok_api
from routers.bilibili import bilibili_api
from routers.dyd import sanitize_filename

router = APIRouter()
MAX_VIDEO_TITLE_LENGTH = 500


def _truncate_video_title(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    return value[:MAX_VIDEO_TITLE_LENGTH]


def _get_storage_platform_candidates(platform: str) -> List[str]:
    """返回共享同一下载目录层级的平台集合（用于 storage_name 冲突检测）"""
    if platform in [Platform.DOUYIN.value, Platform.DOUYIN_COLLECTION.value]:
        return [Platform.DOUYIN.value, Platform.DOUYIN_COLLECTION.value]
    if platform in [Platform.YOUTUBE.value, Platform.YOUTUBE_PLAYLIST.value]:
        return [Platform.YOUTUBE.value, Platform.YOUTUBE_PLAYLIST.value]
    if platform in [Platform.BILIBILI.value, Platform.BILIBILI_COLLECTION.value]:
        return [Platform.BILIBILI.value, Platform.BILIBILI_COLLECTION.value]
    return [platform]


_PROXY_BASE = "/api/system/avatar-proxy"
_INSTAGRAM_CDN_DOMAINS = ("scontent-nrt", "scontent-", "cdninstagram.com")


def _proxy_avatar_url(platform: str, url: Optional[str]) -> Optional[str]:
    """将 Instagram 等有跨域限制的 CDN 头像 URL 转为后端代理 URL"""
    if not url:
        return url
    if platform == Platform.INSTAGRAM.value and any(domain in url for domain in _INSTAGRAM_CDN_DOMAINS):
        from urllib.parse import quote
        return f"{_PROXY_BASE}?url={quote(url)}"
    return url


@router.put("/{subscription_id}/rename")
@require_license_api
async def rename_subscription(
    subscription_id: str,
    request: SubscriptionRenameRequest,
    db: Session = Depends(get_db),
):
    """重命名订阅并迁移对应文件夹（当前仅 B站合集试点）"""
    try:
        result = rename_bilibili_collection_subscription(db, subscription_id, request.nickname)
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"重命名订阅失败: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/list", response_model=List[SubscriptionResponse])
@require_license_api
async def list_subscriptions(
    platform: Optional[str] = None,
    status: Optional[str] = None,
    db: Session = Depends(get_db)
):
    """获取订阅列表"""
    try:
        query = db.query(Subscription)
        
        # 应用过滤条件
        if platform:
            platform = Platform.from_str(platform).value
            query = query.filter(Subscription.platform == platform)
        if status:
            status = SubscriptionStatus.from_str(status).value
            query = query.filter(Subscription.status == status)
            
        # 按创建时间倒序排序
        subscriptions = query.order_by(Subscription.created_at.desc()).all()
        
        # 为每个订阅生成profile_url并更新视频数量
        for sub in subscriptions:
            # B站收藏夹订阅已经在创建时设置了profile_url，不需要重新生成
            if not (sub.platform == Platform.BILIBILI.value and sub.subscription_type == "favorite"):
                sub.profile_url = generate_profile_url(sub.platform, sub.user_id)

            
            # 对于YouTube、抖音、Instagram、TikTok、B站收藏夹、网易云、X，使用数据库实际视频数量
            if sub.platform in [Platform.YOUTUBE.value, Platform.YOUTUBE_PLAYLIST.value, Platform.TIKTOK.value, Platform.DOUYIN.value, Platform.NETEASE.value, Platform.X.value, Platform.INSTAGRAM.value] or \
               (sub.platform == Platform.BILIBILI.value and sub.subscription_type == 'favorite'):
                actual_count = db.query(SubscriptionVideo).filter(
                    SubscriptionVideo.subscription_id == sub.id
                ).count()
                sub.video_count = actual_count

        # 代理需要跨域代理的头像URL
        for sub in subscriptions:
            sub.avatar_url = _proxy_avatar_url(sub.platform, sub.avatar_url)

        return subscriptions

    except Exception as e:
        logger.error(f"获取订阅列表失败: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/stats")
@require_license_api
async def get_subscription_stats(db: Session = Depends(get_db)):
    """获取订阅统计信息（轻量级，供仪表盘使用）"""
    try:
        # 1) 平台分布 + 状态分布 + total (3合1聚合查询)
        agg_rows = db.query(
            Subscription.platform,
            Subscription.status,
            func.count(Subscription.id).label('count')
        ).group_by(Subscription.platform, Subscription.status).all()

        total = 0
        by_platform: dict = {}
        by_status: dict = {}
        for row in agg_rows:
            c = row.count
            total += c
            by_platform[row.platform] = by_platform.get(row.platform, 0) + c
            by_status[row.status] = by_status.get(row.status, 0) + c

        # 2) 自动下载 + 活跃订阅 (1 条组合查询)
        auto_dl_filter = or_(Subscription.auto_download == True, Subscription.auto_download == 'true')
        active_filter = and_(
            Subscription.status == SubscriptionStatus.ACTIVE.value,
            Subscription.update_interval > 0,
            auto_dl_filter,
        )
        combined = db.query(
            func.count(Subscription.id).filter(auto_dl_filter).label('auto_download_enabled'),
            func.count(Subscription.id).filter(active_filter).label('active_count'),
        ).first()
        auto_download_enabled = combined.auto_download_enabled or 0
        active_count = combined.active_count or 0

        return {
            "total": total,
            "by_platform": by_platform,
            "by_status": by_status,
            "auto_download_enabled": auto_download_enabled,
            "active_count": active_count
        }

    except Exception as e:
        logger.error(f"获取订阅统计失败: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{subscription_id}", response_model=SubscriptionResponse)
@require_license_api
async def get_subscription(
    subscription_id: str,
    db: Session = Depends(get_db)
):
    """获取单个订阅信息"""
    try:
        subscription = db.query(Subscription).filter(Subscription.id == subscription_id).first()
        if not subscription:
            raise HTTPException(status_code=404, detail="未找到该订阅")
        
        # 生成profile_url
        subscription.profile_url = generate_profile_url(subscription.platform, subscription.user_id)

        
        # 对于YouTube、Instagram、网易云、X、抖音点赞，使用数据库实际视频数量
        if subscription.platform in [Platform.YOUTUBE.value, Platform.YOUTUBE_PLAYLIST.value, Platform.NETEASE.value, Platform.X.value, Platform.INSTAGRAM.value] or \
           (subscription.platform == Platform.DOUYIN.value and subscription.subscription_type == 'favorite'):
            actual_count = db.query(SubscriptionVideo).filter(
                SubscriptionVideo.subscription_id == subscription.id
            ).count()
            subscription.video_count = actual_count

        # 代理需要跨域代理的头像URL
        subscription.avatar_url = _proxy_avatar_url(subscription.platform, subscription.avatar_url)

        return subscription
        
    except Exception as e:
        logger.error(f"获取订阅信息失败: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/{subscription_id}")
@require_license_api
async def delete_subscription(
    subscription_id: str,
    db: Session = Depends(get_db)
):
    """删除订阅"""
    try:
        subscription = db.query(Subscription).filter(Subscription.id == subscription_id).first()
        if not subscription:
            raise HTTPException(status_code=404, detail="未找到该订阅")
        
        # 记录删除前的信息用于日志
        platform = subscription.platform
        user_id = subscription.user_id
        nickname = subscription.nickname
        
        logger.info(f"开始删除订阅: {nickname} (平台: {platform}, 用户ID: {user_id})")
        
        # 1. 删除相关的视频记录
        deleted_videos = db.query(SubscriptionVideo).filter(
            SubscriptionVideo.subscription_id == subscription_id
        ).delete()
        logger.info(f"删除了 {deleted_videos} 个视频记录")
        
        # 2. 删除相关的下载任务记录（只删除该订阅对应的任务）
        from sql.models import Task
        deleted_tasks = db.query(Task).filter(
            Task.subscription_id == subscription_id
        ).delete()
        logger.info(f"删除了 {deleted_tasks} 个下载任务记录")
        
        # 3. 删除订阅记录
        db.delete(subscription)
        db.commit()
        
        logger.info(f"成功删除订阅: {nickname} (平台: {platform}, 用户ID: {user_id})")
        logger.info(f"总计删除: {deleted_videos} 个视频记录, {deleted_tasks} 个任务记录")
        
        return {
            "message": "删除成功", 
            "deleted_videos": deleted_videos,
            "deleted_tasks": deleted_tasks
        }
        
    except Exception as e:
        logger.error(f"删除订阅失败: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/{subscription_id}", response_model=SubscriptionResponse)
@require_license_api
async def update_subscription(
    subscription_id: str,
    update_data: SubscriptionUpdate,
    db: Session = Depends(get_db)
):
    """更新订阅设置"""
    try:
        subscription = db.query(Subscription).filter(Subscription.id == subscription_id).first()
        if not subscription:
            raise HTTPException(status_code=404, detail="未找到该订阅")
            
        # 更新字段
        update_dict = update_data.dict(exclude_unset=True)
        for key, value in update_dict.items():
            if key == 'auto_download':
                value = str(value).lower()
            setattr(subscription, key, value)
            
        subscription.updated_at = datetime.now()
        db.commit()
        db.refresh(subscription)
        
        # 生成profile_url
        subscription.profile_url = generate_profile_url(subscription.platform, subscription.user_id)

        # 代理需要跨域代理的头像URL
        subscription.avatar_url = _proxy_avatar_url(subscription.platform, subscription.avatar_url)

        return subscription

    except Exception as e:
        logger.error(f"更新订阅失败: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/{subscription_id}/quality", response_model=SubscriptionResponse)
@require_license_api
async def update_subscription_quality(
    subscription_id: str,
    request: QualityUpdateRequest,
    db: Session = Depends(get_db)
):
    """更新订阅的画质设置"""
    try:
        subscription = db.query(Subscription).filter(Subscription.id == subscription_id).first()
        if not subscription:
            raise HTTPException(status_code=404, detail="未找到该订阅")
            
        # 验证画质设置（对YouTube和B站有效）
        if subscription.platform in ["youtube", "bilibili", "bilibili_collection"]:
            valid_qualities = [
                # 新的兼容格式（支持8K）
                "best",
                "best[height<=4320]",  # 8K
                "best[height<=2160]",  # 4K
                "best[height<=1440]",  # 2K
                "best[height<=1080]",  # 1080p
                "best[height<=720]",   # 720p
                "best[height<=480]",   # 480p
                # 兼容旧格式
                "bestvideo+bestaudio",
                "bestvideo[height<=4320]+bestaudio",  # 8K
                "bestvideo[height<=2160]+bestaudio",  # 4K
                "bestvideo[height<=1440]+bestaudio",  # 2K
                "bestvideo[height<=1080]+bestaudio",  # 1080p
                "bestvideo[height<=720]+bestaudio",   # 720p
                "bestvideo[height<=480]+bestaudio"    # 480p
            ]
            if request.quality not in valid_qualities:
                raise HTTPException(status_code=400, detail="无效的画质设置")
        
        # 更新画质设置
        subscription.quality = request.quality
        subscription.updated_at = datetime.now()
        db.commit()
        db.refresh(subscription)
        
        # 生成profile_url
        subscription.profile_url = generate_profile_url(subscription.platform, subscription.user_id)

        # 代理需要跨域代理的头像URL
        subscription.avatar_url = _proxy_avatar_url(subscription.platform, subscription.avatar_url)

        return subscription

    except Exception as e:
        logger.error(f"更新订阅画质失败: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/douyin/add_favorite_subscription", response_model=SubscriptionResponse)
@require_license_api
async def add_favorite_subscription(
    db: Session = Depends(get_db)
):
    """添加当前登录抖音账号的点赞列表订阅"""
    try:
        # 1. 获取当前登录用户信息
        user_info = await douyin_api.get_current_user_info()
        if not user_info or not user_info.get("user_id"):
            raise HTTPException(status_code=400, detail="未登录抖音账号，请先登录")
        
        user_id = user_info["user_id"]
        nickname = user_info.get("nickname", "我的点赞")
        
        # 2. 检查是否已存在点赞列表订阅
        existing = db.query(Subscription).filter(
            Subscription.platform == Platform.DOUYIN.value,
            Subscription.subscription_type == "favorite",
            Subscription.user_id == user_id
        ).first()
        
        if existing:
            raise HTTPException(
                status_code=400,
                detail="已经订阅过该账号的点赞列表，无需重复添加"
            )
        
        # 3. 获取点赞列表的第一页视频
        favorite_videos = await douyin_api.get_favorite_videos(max_count=20, max_cursor=0)
        
        if not favorite_videos or not favorite_videos.get("aweme_list"):
            raise HTTPException(status_code=400, detail="获取点赞列表失败或点赞列表为空")
        
        # 4. 获取最新点赞视频信息
        # 点赞列表已经按点赞时间排序（最新的在前），直接取第一个
        videos_list = favorite_videos.get("aweme_list", [])
        latest_video = videos_list[0]
        # 使用当前时间作为最新视频时间（因为DOM提取无法获取真实的点赞时间）
        latest_publish_time = datetime.now()
        
        # 4.5 可选：尝试获取并缓存 sec_user_id，存入 extra_data 方便后续兜底使用
        extra_data: dict = {}
        try:
            sec_user_id = await douyin_api.get_my_sec_user_id()
            if sec_user_id:
                extra_data["sec_user_id"] = sec_user_id
        except Exception as e:
            # 获取失败不影响订阅创建，只做调试日志
            logger.warning(f"获取 sec_user_id 失败，将跳过缓存: {str(e)}")
        
        # 5. 创建订阅记录
        now = datetime.now()
        subscription_id = str(uuid.uuid4())
        
        new_subscription = Subscription(
            id=subscription_id,
            platform=Platform.DOUYIN.value,
            subscription_type="favorite",  # 标记为点赞列表订阅
            user_id=user_id,
            nickname=f"{nickname} - 点赞列表",
            avatar_url=user_info.get("avatar_url"),
            signature=user_info.get("signature"),
            follower_count=user_info.get("follower_count"),
            following_count=user_info.get("following_count"),
            video_count=user_info.get("video_count"),
            like_count=user_info.get("like_count"),
            latest_video_time=latest_publish_time,
            latest_video_title=_truncate_video_title(latest_video.get("desc", "")),
            latest_video_cover=latest_video.get("video", {}).get("cover", {}).get("url_list", [None])[0],
            extra_data=json.dumps(extra_data) if extra_data else None,
            update_interval=3600,
            auto_download="false",
            status=SubscriptionStatus.ACTIVE.value,
            created_at=now,
            updated_at=now,
            last_sync_info=now
        )
        
        db.add(new_subscription)
        db.commit()
        db.refresh(new_subscription)
        
        # 6. 保存视频到数据库
        logger.info(f"开始保存点赞视频到数据库...")
        saved_count = 0
        for video in videos_list:
            try:
                video_id = video.get("aweme_id")
                if not video_id:
                    continue
                
                # 检查视频是否已存在
                existing_video = db.query(SubscriptionVideo).filter(
                    SubscriptionVideo.subscription_id == subscription_id,
                    SubscriptionVideo.video_id == video_id
                ).first()
                
                if existing_video:
                    continue
                
                # 创建视频记录
                video_url = get_correct_douyin_url(video_id, video)  # 使用正确的URL格式
                cover_url = video.get("video", {}).get("cover", {}).get("url_list", [None])[0]
                publish_time = datetime.fromtimestamp(int(video.get("create_time", 0))) if video.get("create_time") else datetime.now()
                
                new_video = SubscriptionVideo(
                    id=str(uuid.uuid4()),
                    subscription_id=subscription_id,
                    video_id=video_id,
                    title=_truncate_video_title(video.get("desc", "")),
                    url=video_url,
                    cover_url=cover_url,
                    publish_time=publish_time,
                    created_at=now,
                    downloaded="false"
                )
                
                db.add(new_video)
                saved_count += 1
                
            except Exception as e:
                logger.error(f"保存视频 {video.get('aweme_id')} 失败: {str(e)}")
                continue
        
        db.commit()
        logger.info(f"成功添加点赞列表订阅: {nickname}，已保存 {saved_count} 个视频")
        
        return new_subscription
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"添加点赞列表订阅失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"添加订阅失败: {str(e)}")


async def _create_douyin_creator_subscription(
    profile_url: str,
    update_interval: float,
    auto_download: str,
    db: Session
) -> Subscription:
    """创建单个抖音博主订阅（批量添加使用）。"""
    normalized_url = (profile_url or "").strip()
    if not normalized_url:
        raise HTTPException(status_code=400, detail="主页链接不能为空")

    # 还原短链接，统一后续解析路径
    if 'v.douyin.com' in normalized_url and '/note/' not in normalized_url and '/video/' not in normalized_url:
        try:
            async with httpx.AsyncClient(follow_redirects=True, timeout=10.0) as client:
                response = await client.head(normalized_url)
                if response.status_code < 400 and str(response.url).startswith('http'):
                    normalized_url = str(response.url)
        except Exception as e:
            logger.warning(f"批量添加：短链接还原失败，将使用原链接: {normalized_url}, error={e}")

    # 批量入口仅支持博主，不支持合集链接
    if await _is_douyin_collection_url(normalized_url):
        raise HTTPException(
            status_code=400,
            detail="链接识别为抖音合集，请使用抖音合集添加入口"
        )

    douyin_adapter = registry.get_adapter("douyin")
    if not douyin_adapter:
        raise HTTPException(status_code=400, detail="抖音平台适配器未找到")

    user_info = await douyin_adapter.get_user_info(normalized_url)
    if not user_info:
        raise HTTPException(
            status_code=400,
            detail="无法获取抖音用户信息，请检查链接是否正确或稍后重试，或该账号为私密账号"
        )

    # 提取 user_id（与单条创建逻辑保持一致的兜底）
    extracted_user_id = user_info.get("user_id")
    if not extracted_user_id:
        user_id_match = re.search(r"/user/([^/?]+)", normalized_url)
        if user_id_match:
            extracted_user_id = user_id_match.group(1)
        elif normalized_url and not normalized_url.startswith("http") and len(normalized_url) <= 100:
            extracted_user_id = normalized_url
        else:
            extracted_user_id = normalized_url[:100] if len(normalized_url) > 100 else normalized_url

    if not extracted_user_id:
        raise HTTPException(status_code=400, detail="无法从链接中提取抖音用户ID")

    if len(extracted_user_id) > 100:
        extracted_user_id = extracted_user_id[:100]

    # 查重
    existing = db.query(Subscription).filter(
        Subscription.platform == Platform.DOUYIN.value,
        Subscription.user_id == extracted_user_id
    ).first()
    if existing:
        raise HTTPException(status_code=400, detail="该抖音博主已经订阅过了，无需重复添加")

    # 拉取首批视频，确保后续“检测更新”可直接工作
    videos_result = await douyin_adapter.get_latest_videos(
        extracted_user_id,
        subscription_type="user",
        max_count=30
    )
    videos_list = videos_result.get("videos", []) if videos_result else []
    if not videos_list:
        raise HTTPException(
            status_code=400,
            detail="无法获取最新视频信息，请稍后重试或检查网络连接，或该账号为私密账号"
        )

    latest_video_data = douyin_adapter.normalize_video_data(videos_list[0], "user")

    now = datetime.now()
    subscription_id = str(uuid.uuid4())
    nickname = user_info.get("nickname") or extracted_user_id
    new_subscription = Subscription(
        id=subscription_id,
        platform=Platform.DOUYIN.value,
        user_id=extracted_user_id,
        nickname=nickname,
        update_interval=update_interval,
        auto_download=str(auto_download).lower(),
        status=SubscriptionStatus.ACTIVE.value,
        created_at=now,
        updated_at=now,
        last_check=now,
        last_update=now,
        latest_video_time=latest_video_data.get("publish_time", now),
        latest_video_title=_truncate_video_title(latest_video_data.get("title", "")),
        latest_video_cover=latest_video_data.get("cover_url", ""),
        quality="best",
        subscription_type="user",
        follower_count=user_info.get("follower_count"),
        following_count=user_info.get("following_count"),
        video_count=user_info.get("video_count"),
        like_count=user_info.get("like_count"),
        signature=user_info.get("signature"),
        avatar_url=user_info.get("avatar_url"),
        last_sync_info=now,
        profile_url=generate_profile_url(Platform.DOUYIN.value, extracted_user_id)
    )
    db.add(new_subscription)

    for video in videos_list:
        aweme_id = video.get("aweme_id")
        if not aweme_id:
            continue

        create_time = video.get("create_time")
        if create_time:
            try:
                publish_time = datetime.fromtimestamp(int(create_time))
            except Exception:
                publish_time = now
        else:
            publish_time = now

        new_video = SubscriptionVideo(
            id=str(uuid.uuid4()),
            subscription_id=subscription_id,
            video_id=aweme_id,
            title=_truncate_video_title(video.get("desc", "")),
            url=get_correct_douyin_url(aweme_id, video),
            cover_url=video.get("video", {}).get("cover", {}).get("url_list", [None])[0],
            publish_time=publish_time,
            downloaded="false",
            created_at=now,
            extra_data=json.dumps({
                "publish_time_text": publish_time.strftime("%Y-%m-%d %H:%M:%S")
            })
        )
        db.add(new_video)

    db.commit()
    db.refresh(new_subscription)
    return new_subscription


@router.post("/douyin/batch_add", response_model=DouyinBatchAddResponse)
@require_license_api
async def batch_add_douyin_subscriptions(request: DouyinBatchAddRequest):
    """批量添加抖音博主订阅（后台异步执行）。"""
    max_batch_urls = 15
    raw_urls = request.profile_urls or []
    normalized_urls = []
    seen = set()
    for item in raw_urls:
        url = (item or "").strip()
        if not url or url in seen:
            continue
        seen.add(url)
        normalized_urls.append(url)

    if not normalized_urls:
        raise HTTPException(status_code=400, detail="请至少提供一个有效的抖音主页链接")
    if len(normalized_urls) > max_batch_urls:
        raise HTTPException(status_code=400, detail=f"单次最多支持批量添加 {max_batch_urls} 个抖音博主")

    task_id = str(uuid.uuid4())

    async def _run_batch_add():
        from routers.websocket import manager

        total = len(normalized_urls)
        success = 0
        failed = 0
        skipped = 0
        errors = []

        await manager.broadcast_message("batch_tasks", {
            "type": "batch_add_progress",
            "task_id": task_id,
            "status": "started",
            "total": total,
            "processed": 0,
            "success": 0,
            "failed": 0,
            "skipped": 0,
            "message": f"开始批量添加 {total} 个抖音博主订阅"
        })

        for idx, url in enumerate(normalized_urls, start=1):
            item_db = get_session()
            try:
                created = await _create_douyin_creator_subscription(
                    profile_url=url,
                    update_interval=request.update_interval,
                    auto_download=request.auto_download,
                    db=item_db
                )
                success += 1
                logger.info(f"批量添加抖音订阅成功 [{idx}/{total}] -> {created.nickname} ({created.user_id})")
            except HTTPException as he:
                detail = he.detail if isinstance(he.detail, str) else str(he.detail)
                # 已存在不算硬失败，归类为 skipped
                if "已经订阅过了" in detail:
                    skipped += 1
                else:
                    failed += 1
                    errors.append(f"[{idx}] {url} -> {detail}")
                try:
                    item_db.rollback()
                except Exception:
                    pass
                logger.warning(f"批量添加抖音订阅失败 [{idx}/{total}] -> {url}, reason={detail}")
            except Exception as e:
                failed += 1
                errors.append(f"[{idx}] {url} -> {str(e)}")
                try:
                    item_db.rollback()
                except Exception:
                    pass
                logger.error(f"批量添加抖音订阅异常 [{idx}/{total}] -> {url}, error={str(e)}")
            finally:
                try:
                    item_db.close()
                except Exception:
                    pass

            processed = success + failed + skipped
            await manager.broadcast_message("batch_tasks", {
                "type": "batch_add_progress",
                "task_id": task_id,
                "status": "running",
                "total": total,
                "processed": processed,
                "success": success,
                "failed": failed,
                "skipped": skipped,
                "current_index": idx,
                "current_url": url,
                "message": f"已处理 {processed}/{total}"
            })

            # 抖音风控较严格，批量场景主动降速
            await asyncio.sleep(random.uniform(0.4, 0.8))

        await manager.broadcast_message("batch_tasks", {
            "type": "batch_add_progress",
            "task_id": task_id,
            "status": "completed",
            "total": total,
            "processed": total,
            "success": success,
            "failed": failed,
            "skipped": skipped,
            "errors": errors[:20],
            "message": f"批量添加完成：成功 {success}，跳过 {skipped}，失败 {failed}"
        })

    asyncio.create_task(_run_batch_add())
    return DouyinBatchAddResponse(
        message="已发起批量添加任务",
        task_id=task_id,
        total=len(normalized_urls),
        queued=len(normalized_urls)
    )


@router.post("/add", response_model=SubscriptionResponse)
@require_license_api
async def add_subscription(
    subscription: SubscriptionCreate,
    db: Session = Depends(get_db)
):
    """添加订阅，记录最新视频时间和创建视频记录"""
    # [新增] 统一处理抖音短链接重定向 (Bot/网页端通用)
    if hasattr(subscription, 'profile_url') and subscription.profile_url:
        s_url = subscription.profile_url
        if 'v.douyin.com' in s_url and '/note/' not in s_url and '/video/' not in s_url:
            try:
                logger.info(f"正在还原抖音短链接: {s_url}")
                async with httpx.AsyncClient(follow_redirects=True, timeout=10.0) as client:
                    response = await client.head(s_url)
                    # 只有成功获取且域名正确时才替换
                    if response.status_code < 400 and str(response.url).startswith('http'):
                        real_url = str(response.url)
                        subscription.profile_url = real_url
                        logger.info(f"短链接已还原: {real_url}")
            except Exception as e:
                logger.warning(f"短链接还原失败，将尝试使用原链接: {e}")
    
    try:
        # 小红书：在解析阶段会覆盖 user_id，先保存带 xsec_token 的完整链接供入库使用
        xiaohongshu_profile_url_to_save = None
        # 记录用户输入昵称（若有），用于自定义昵称锁定（仅抖音博主）
        input_nickname = (subscription.nickname or "").strip()
        allow_custom_nickname = subscription.platform == Platform.DOUYIN.value
        has_custom_nickname = allow_custom_nickname and bool(input_nickname)
        # 0. 基于前端选择与链接进行抖音类型校验（不符合则直接提示并拒绝添加）
        if hasattr(subscription, 'platform') and hasattr(subscription, 'profile_url') \
            and subscription.profile_url and subscription.platform in [Platform.DOUYIN.value, Platform.DOUYIN_COLLECTION.value]:
            is_collection_link = await _is_douyin_collection_url(subscription.profile_url)
            # 前端选"抖音博主"，但识别为合集
            if subscription.platform == Platform.DOUYIN.value and is_collection_link:
                raise HTTPException(
                    status_code=400,
                    detail="您选择了\"抖音博主\"，但链接识别为合集链接，请切换为\"抖音合集\"后再添加"
                )
            # 前端选"抖音合集"，但识别为博主
            if subscription.platform == Platform.DOUYIN_COLLECTION.value and not is_collection_link:
                raise HTTPException(
                    status_code=400,
                    detail="您选择了\"抖音合集\"，但链接识别为博主主页，请切换为\"抖音博主\"后再添加"
                )

        # 1. 如果提供了profile_url，先解析获取user_id和nickname
        # 初始化变量，用于存储已获取的用户信息，避免重复调用
        bilibili_user_info = None
        instagram_user_info = None
        
        if hasattr(subscription, 'profile_url') and subscription.profile_url:
            try:
                if subscription.platform == Platform.DOUYIN.value:
                    # 使用适配器解析抖音用户信息
                    douyin_adapter = registry.get_adapter("douyin")
                    if not douyin_adapter:
                        raise HTTPException(status_code=400, detail="抖音平台适配器未找到")
                    
                    user_url = subscription.profile_url if subscription.profile_url else subscription.user_id
                    if not user_url:
                        raise HTTPException(status_code=400, detail="请提供抖音用户主页链接或用户ID")
                    
                    # 适配器的 get_user_info 可以处理URL或用户ID（参考旧版实现，会自动解析URL并提取user_id）
                    user_info = await douyin_adapter.get_user_info(user_url)
                    if not user_info:
                        raise HTTPException(status_code=400, detail="无法获取抖音用户信息")
                    
                    # 从 user_info 获取 user_id（适配器已通过 parse_user_profile 解析并提取）
                    extracted_user_id = user_info.get("user_id")
                    if not extracted_user_id:
                        # 兜底：如果适配器没有返回 user_id，从 URL 中提取
                        user_id_match = re.search(r"/user/([^/?]+)", user_url)
                        if user_id_match:
                            extracted_user_id = user_id_match.group(1)
                        else:
                            # 如果既不是标准URL格式，也不是短链接，且长度合理，可能是直接输入的用户ID
                            if user_url and not user_url.startswith("http") and len(user_url) <= 100:
                                extracted_user_id = user_url
                            else:
                                # 如果无法提取，截断URL到100字符（作为最后手段）
                                extracted_user_id = user_url[:100] if len(user_url) > 100 else user_url
                                logger.warning(f"无法从URL中提取用户ID，使用截断后的URL: {extracted_user_id[:50]}...")
                    
                    # 确保 user_id 不超过数据库字段长度限制（100字符）
                    if len(extracted_user_id) > 100:
                        logger.warning(f"提取的用户ID长度超过100字符，将被截断: {extracted_user_id[:50]}...")
                        extracted_user_id = extracted_user_id[:100]
                    
                    subscription.user_id = extracted_user_id
                    # 用户手动填写了昵称时，优先保留用户输入
                    if has_custom_nickname:
                        subscription.nickname = input_nickname
                    else:
                        subscription.nickname = user_info.get("nickname", "")
                elif subscription.platform == Platform.DOUYIN_COLLECTION.value:
                    # 抖音合集订阅：在后续合集逻辑中解析
                    pass
                elif subscription.platform == Platform.INSTAGRAM.value:
                    instagram_adapter = registry.get_adapter("instagram")
                    if not instagram_adapter:
                        raise HTTPException(status_code=400, detail="Instagram平台适配器未找到")

                    user_info = await instagram_adapter.get_user_info(subscription.profile_url or subscription.user_id)
                    if not user_info or user_info.get("__error__"):
                        raise HTTPException(
                            status_code=400,
                            detail=(user_info or {}).get("__error__") or "无法获取Instagram用户信息，请检查登录态或主页链接"
                        )

                    instagram_user_info = user_info
                    subscription.user_id = user_info.get("user_id") or user_info.get("username")
                    subscription.nickname = user_info.get("nickname") or subscription.user_id
                    subscription.profile_url = user_info.get("profile_url") or generate_profile_url(Platform.INSTAGRAM.value, subscription.user_id)
                elif subscription.platform == Platform.YOUTUBE.value:
                    # 使用适配器解析YouTube频道信息
                    youtube_adapter = registry.get_adapter("youtube")
                    if not youtube_adapter:
                        raise HTTPException(status_code=400, detail="YouTube平台适配器未找到")
                    
                    user_info = await youtube_adapter.get_user_info(subscription.profile_url)
                    if not user_info:
                        raise HTTPException(status_code=400, detail="无法获取YouTube频道信息")
                    
                    subscription.user_id = user_info.get("channel_id") or user_info.get("user_id", "")
                    subscription.nickname = user_info.get("name") or user_info.get("nickname", "")
                elif subscription.platform == Platform.YOUTUBE_PLAYLIST.value:
                    # 解析YouTube播放列表信息
                    profile_url = subscription.profile_url or ""
                    playlist_id = None
                    
                    # 尝试从URL中提取播放列表ID
                    playlist_match = re.search(r'[?&]list=([^&]+)', profile_url)
                    if playlist_match:
                        playlist_id = playlist_match.group(1)
                    else:
                        # 如果输入不是URL，可能是直接输入的播放列表ID
                        if profile_url and not profile_url.startswith("http"):
                            if profile_url.startswith("PL") and len(profile_url) >= 10:
                                playlist_id = profile_url
                                logger.info(f"检测到直接输入的播放列表ID: {playlist_id}")
                            else:
                                id_match = re.search(r'(PL[a-zA-Z0-9_-]+)', profile_url)
                                if id_match:
                                    playlist_id = id_match.group(1)
                                    logger.info(f"从输入中提取到播放列表ID: {playlist_id}")
                    
                    if not playlist_id:
                        raise HTTPException(
                            status_code=400, 
                            detail="无法从输入中提取播放列表ID，请使用：1) 播放列表链接（如：https://www.youtube.com/playlist?list=PLxxxxx）2) 播放列表ID（如：PLxxxxx）"
                        )
                    
                    subscription.user_id = playlist_id
                    subscription.nickname = subscription.nickname or f"播放列表 {playlist_id}"
                elif subscription.platform == Platform.NETEASE.value:
                    # 解析网易云歌单链接，提取歌单ID
                    profile_or_id = (subscription.profile_url or subscription.user_id or "").strip()
                    playlist_id = None

                    # 支持直接输入歌单ID
                    if profile_or_id.isdigit():
                        playlist_id = profile_or_id
                    else:
                        # 链接模式只支持 music.163.com
                        if "music.163.com" not in profile_or_id:
                            raise HTTPException(
                                status_code=400,
                                detail="目前仅支持网易云歌单链接或纯歌单ID，请使用 https://music.163.com/playlist?id=xxxx 或直接输入数字ID",
                            )
                        # 常见歌单链接格式：/playlist?id=123456 或 /#/my/m/music/playlist?id=123456
                        id_match = re.search(r"[?&]id=(\d+)", profile_or_id)
                        if id_match:
                            playlist_id = id_match.group(1)

                    if not playlist_id:
                        raise HTTPException(
                            status_code=400,
                            detail="无法从输入中提取网易云歌单ID，请使用：1) 歌单链接（如：https://music.163.com/playlist?id=123456）2) 歌单ID（如：123456）",
                        )

                    subscription.user_id = playlist_id
                    subscription.nickname = subscription.nickname or f"网易云歌单 {playlist_id}"
                    # 标记为歌单订阅，便于后续扩展
                    subscription.subscription_type = "playlist"
                elif subscription.platform == Platform.X.value:
                    # X 点赞订阅：支持用户名/主页链接/@handle
                    from services import x_graphql
                    screen_name = x_graphql.parse_screen_name(subscription.profile_url or subscription.user_id)
                    if not screen_name:
                        raise HTTPException(status_code=400, detail="请输入有效的 X 用户名或主页链接")
                    subscription.user_id = screen_name
                    subscription.subscription_type = "favorite"
                    try:
                        info = x_graphql.fetch_user_info(screen_name)
                        if info:
                            subscription.nickname = info.nickname or subscription.nickname
                            if info.avatar_url and hasattr(subscription, "avatar_url"):
                                subscription.avatar_url = info.avatar_url
                            if info.follower_count is not None and hasattr(subscription, "follower_count"):
                                subscription.follower_count = info.follower_count
                            if info.following_count is not None and hasattr(subscription, "following_count"):
                                subscription.following_count = info.following_count
                            if info.video_count is not None and hasattr(subscription, "video_count"):
                                subscription.video_count = info.video_count
                            if info.signature is not None and hasattr(subscription, "signature"):
                                subscription.signature = info.signature
                    except Exception as e:
                        logger.warning(f"获取X用户信息失败，将继续创建订阅: {str(e)}")
                elif subscription.platform == Platform.BILIBILI.value:
                    # 判断是UP主订阅还是收藏夹订阅
                    if subscription.subscription_type == "favorite":
                        # B站收藏夹订阅
                        from routers.bilibili import parse_bilibili_favorite_url, get_bilibili_favorite_info, get_bilibili_favorite_videos
                        
                        fav_url_or_id = subscription.profile_url or subscription.user_id
                        if not fav_url_or_id:
                            raise HTTPException(status_code=400, detail="B站收藏夹订阅需要提供收藏夹URL或ID")
                        
                        try:
                            fav_info = parse_bilibili_favorite_url(fav_url_or_id)
                            fav_id = fav_info["fav_id"]
                            
                            cookies_path = "/app/database/cookie/bilibili_cookie.txt"
                            fav_data = await get_bilibili_favorite_info(fav_id, cookies_path)
                            
                            subscription.user_id = fav_id
                            subscription.nickname = fav_data["title"]
                            subscription.profile_url = fav_data["fav_url"]
                            
                            bilibili_user_info = {
                                "user_id": fav_id,
                                "nickname": fav_data["title"],
                                "video_count": fav_data["video_count"],
                                "fav_url": fav_data["fav_url"]
                            }
                            
                            logger.info(f"B站收藏夹订阅创建: {fav_data['title']} (ID: {fav_id}, 视频数: {fav_data['video_count']})")
                            
                            target_count = 30
                            avatar_url = fav_data.get("avatar_url", "") or ""
                            
                            try:
                                latest_videos = await get_bilibili_favorite_videos(
                                    fav_id,
                                    cookies_path,
                                    extract_flat=False,
                                    max_count=target_count
                                )
                                
                                if latest_videos and len(latest_videos) > 0:
                                    videos_list = latest_videos
                                    latest_video = videos_list[0]
                                    latest_video_title = latest_video.get("title", "")
                                    latest_video_cover = latest_video.get("cover_url", "")
                                    
                                    if not avatar_url and latest_video_cover:
                                        avatar_url = latest_video_cover
                                        logger.info(f"使用第一个视频封面作为收藏夹头像: {avatar_url}")
                                    
                                    publish_time_str = latest_video.get("publish_time", "")
                                    if publish_time_str:
                                        try:
                                            if publish_time_str.endswith("Z"):
                                                publish_time_str = publish_time_str.replace("Z", "+00:00")
                                            latest_video_time = datetime.fromisoformat(publish_time_str)
                                        except Exception as e:
                                            logger.warning(f"B站收藏夹视频时间解析失败: {publish_time_str}, 错误: {str(e)}, 使用当前时间")
                                            latest_video_time = datetime.now()
                                    else:
                                        latest_video_time = datetime.now()
                                    
                                    logger.info(f"获取到 {len(videos_list)} 个收藏夹视频（首次订阅）")
                                else:
                                    videos_list = []
                                    latest_video_time = datetime.now()
                                    latest_video_title = ""
                                    latest_video_cover = ""
                                    logger.info("收藏夹中没有视频或无法获取视频列表")
                            except Exception as e:
                                logger.warning(f"获取B站收藏夹视频失败（不影响订阅创建）: {str(e)}")
                                videos_list = []
                                latest_video_time = datetime.now()
                                latest_video_title = ""
                                latest_video_cover = ""
                            
                            if not avatar_url and videos_list and len(videos_list) > 0:
                                first_video_cover = videos_list[0].get("cover_url", "")
                                if first_video_cover:
                                    avatar_url = first_video_cover
                                    logger.info(f"使用第一个视频封面作为收藏夹头像（备用方案）: {avatar_url}")
                            
                            user_stats = {
                                'follower_count': 0,
                                'video_count': fav_data["video_count"],
                                'like_count': 0,
                                'signature': f"收藏夹：{fav_data['title']}",
                                'avatar_url': avatar_url
                            }
                            logger.info(f"B站收藏夹订阅 user_stats: avatar_url={avatar_url}, video_count={fav_data['video_count']}")
                        except ValueError as e:
                            raise HTTPException(status_code=400, detail=f"无法解析收藏夹信息: {str(e)}")
                        except Exception as e:
                            logger.error(f"获取B站收藏夹信息失败: {str(e)}")
                            raise HTTPException(status_code=400, detail=f"获取收藏夹信息失败: {str(e)}")
                    else:
                        # 使用适配器解析B站UP主信息
                        bilibili_adapter = registry.get_adapter("bilibili")
                        if not bilibili_adapter:
                            raise HTTPException(status_code=400, detail="B站平台适配器未找到")
                        
                        up_id = None
                        profile_url = subscription.profile_url or ""
                        
                        if profile_url:
                            match = re.search(r'space\.bilibili\.com/(\d+)', profile_url)
                            if match:
                                up_id = match.group(1)
                                logger.info(f"从URL中提取到UP主ID: {up_id}")
                            else:
                                if profile_url and not profile_url.startswith("http") and profile_url.isdigit():
                                    up_id = profile_url
                                    logger.info(f"检测到直接输入的UP主ID: {up_id}")
                                else:
                                    id_match = re.search(r'(\d+)', profile_url)
                                    if id_match:
                                        up_id = id_match.group(1)
                                        logger.info(f"从输入中提取到UP主ID: {up_id}")
                        
                        if not up_id and subscription.user_id:
                            if subscription.user_id.isdigit():
                                up_id = subscription.user_id
                                logger.info(f"使用提供的user_id作为UP主ID: {up_id}")
                        
                        if not up_id:
                            raise HTTPException(
                                status_code=400, 
                                detail="无法从输入中提取UP主ID，请使用：1) B站个人空间链接（如：https://space.bilibili.com/123456）2) UP主ID（如：123456）"
                            )
                        
                        user_info = await bilibili_adapter.get_user_info(up_id, "user")
                        if not user_info:
                            raise HTTPException(status_code=400, detail="无法获取B站UP主信息")
                        
                        subscription.user_id = user_info.get("user_id", up_id)
                        subscription.nickname = user_info.get("nickname", "")
                        bilibili_user_info = user_info
                elif subscription.platform == Platform.BILIBILI_COLLECTION.value:
                    # 使用适配器解析B站合集信息
                    bilibili_adapter = registry.get_adapter("bilibili")
                    if not bilibili_adapter:
                        raise HTTPException(status_code=400, detail="B站平台适配器未找到")
                    
                    bvid = None
                    profile_url = subscription.profile_url or ""
                    
                    if profile_url:
                        bv_match = re.search(r'bilibili\.com/video/(BV[\w]+)', profile_url, re.IGNORECASE)
                        if bv_match:
                            bvid = bv_match.group(1)
                            logger.info(f"从URL中提取到BV号: {bvid}")
                        else:
                            if profile_url and not profile_url.startswith("http"):
                                if re.match(r'^BV[a-zA-Z0-9]+$', profile_url, re.IGNORECASE):
                                    bvid = profile_url
                                    logger.info(f"检测到直接输入的BV号: {bvid}")
                                else:
                                    bv_match = re.search(r'(BV[a-zA-Z0-9]+)', profile_url, re.IGNORECASE)
                                    if bv_match:
                                        bvid = bv_match.group(1)
                                        logger.info(f"从输入中提取到BV号: {bvid}")
                    
                    if not bvid and subscription.user_id:
                        if re.match(r'^BV[a-zA-Z0-9]+$', subscription.user_id, re.IGNORECASE):
                            bvid = subscription.user_id
                            logger.info(f"使用提供的user_id作为BV号: {bvid}")
                    
                    if not bvid:
                        raise HTTPException(
                            status_code=400, 
                            detail="无法从输入中提取BV号，请使用：1) B站视频链接（如：https://www.bilibili.com/video/BVxxxxx）2) BV号（如：BVxxxxx）"
                        )
                    
                    collection_info = await bilibili_adapter.get_user_info(bvid, "collection")
                    if not collection_info:
                        raise HTTPException(status_code=400, detail="无法获取合集信息，请检查BV号是否正确或视频是否存在")
                    if not collection_info.get('is_collection', False):
                        raise HTTPException(status_code=400, detail="该视频不是合集，请使用多P视频合集链接")
                    
                    subscription.user_id = bvid
                    subscription.nickname = collection_info.get("collection_title") or collection_info.get("title") or f"合集 {bvid}"
                    bilibili_user_info = collection_info
                elif subscription.platform == Platform.TIKTOK.value:
                    # 使用适配器获取TikTok用户信息
                    tiktok_adapter = registry.get_adapter("tiktok")
                    if not tiktok_adapter:
                        raise HTTPException(status_code=400, detail="TikTok平台适配器未找到")
                    
                    user_url = subscription.profile_url if subscription.profile_url else subscription.user_id
                    if not user_url:
                        raise HTTPException(status_code=400, detail="请提供TikTok用户主页链接或用户名")
                    
                    # 从URL中提取用户名（如果提供的是完整URL）
                    if user_url.startswith("http"):
                        user_id_from_url = user_url.split("@")[-1].split("/")[0] if "@" in user_url else None
                        if user_id_from_url:
                            user_url = user_id_from_url
                    
                    user_info = await tiktok_adapter.get_user_info(user_url)
                    if not user_info:
                        raise HTTPException(status_code=400, detail="无法获取TikTok用户信息")
                    
                    subscription.user_id = user_url  # TikTok使用用户名作为ID
                    subscription.nickname = user_info.get("nickname", user_url)
                elif subscription.platform == Platform.XIAOHONGSHU.value:
                    # 使用适配器获取小红书用户信息
                    xiaohongshu_adapter = registry.get_adapter("xiaohongshu")
                    if not xiaohongshu_adapter:
                        raise HTTPException(status_code=400, detail="小红书平台适配器未找到")
                    
                    user_url = subscription.profile_url if subscription.profile_url else subscription.user_id
                    if not user_url:
                        raise HTTPException(status_code=400, detail="请提供小红书用户主页链接或用户ID")
                    
                    user_info = await xiaohongshu_adapter.get_user_info(user_url)
                    if isinstance(user_info, dict) and user_info.get("__error__"):
                        raise HTTPException(status_code=400, detail=user_info.get("__error__"))
                    if not user_info:
                        raise HTTPException(
                            status_code=400,
                            detail="无法获取小红书用户信息。请使用创作者主页链接（含 xsec_token），不要使用笔记链接。"
                        )
                    if "xsec_token" in (user_url or ""):
                        xiaohongshu_profile_url_to_save = user_url
                    subscription.user_id = user_info.get("user_id", user_url)
                    subscription.nickname = user_info.get("nickname", "")
                else:
                    raise HTTPException(status_code=400, detail="暂不支持该平台")
            except HTTPException:
                raise
            except Exception as e:
                logger.error(f"解析频道信息失败: {str(e)}")
                raise HTTPException(status_code=400, detail=f"无法解析频道信息: {str(e)}")
        
        # 2. 检查是否已存在相同的订阅
        if subscription.platform == Platform.YOUTUBE.value and subscription.youtube_tab_type:
            existing = db.query(Subscription).filter(
                Subscription.platform == subscription.platform,
                Subscription.user_id == subscription.user_id,
                Subscription.youtube_tab_type == subscription.youtube_tab_type
            ).first()
        elif subscription.platform == Platform.BILIBILI.value and subscription.subscription_type:
            existing = db.query(Subscription).filter(
                Subscription.platform == subscription.platform,
                Subscription.user_id == subscription.user_id,
                Subscription.subscription_type == subscription.subscription_type
            ).first()
        else:
            existing = db.query(Subscription).filter(
                Subscription.platform == subscription.platform,
                Subscription.user_id == subscription.user_id
            ).first()
        
        if existing:
            if subscription.platform == Platform.DOUYIN.value:
                platform_name = "抖音博主"
            elif subscription.platform == Platform.YOUTUBE.value:
                tab_type_names = {
                    "videos": "视频",
                    "shorts": "Shorts",
                    "playlists": "播放列表"
                }
                tab_name = tab_type_names.get(subscription.youtube_tab_type, "")
                platform_name = f"YouTube频道（{tab_name}）" if tab_name else "YouTube频道"
            elif subscription.platform == Platform.YOUTUBE_PLAYLIST.value:
                platform_name = "YouTube播放列表"
            elif subscription.platform == Platform.BILIBILI.value:
                if subscription.subscription_type == "favorite":
                    platform_name = "B站收藏夹"
                elif subscription.subscription_type == "collection":
                    platform_name = "B站合集"
                else:
                    platform_name = "B站UP主"
            elif subscription.platform == Platform.BILIBILI_COLLECTION.value:
                platform_name = "B站合集"
            elif subscription.platform == Platform.TIKTOK.value:
                platform_name = "TikTok用户"
            elif subscription.platform == Platform.INSTAGRAM.value:
                platform_name = "Instagram博主"
            elif subscription.platform == Platform.XIAOHONGSHU.value:
                platform_name = "小红书博主"
            elif subscription.platform == Platform.NETEASE.value:
                platform_name = "网易云歌单"
            elif subscription.platform == Platform.X.value:
                platform_name = "X点赞"
            else:
                platform_name = "频道"
            raise HTTPException(
                status_code=400, 
                detail=f"该{platform_name}已经订阅过了，无需重复添加"
            )
        
        # 3. 如果是抖音平台，先获取用户信息和最新视频
        # 注意：B站收藏夹订阅已经在上面设置了user_stats和latest_video_time等变量，不要重置
        is_bilibili_favorite = (subscription.platform == Platform.BILIBILI.value and 
                                hasattr(subscription, 'subscription_type') and 
                                subscription.subscription_type == "favorite")
        
        if not is_bilibili_favorite:
            # 非B站收藏夹订阅，正常初始化变量
            user_stats = None
            latest_video_time = None
            latest_video_title = None
            latest_video_cover = None
            latest_video = None
            videos_list = []
        
        # 检查是否为合集订阅
        is_collection_subscription = False
        collection_info = None
        
        if subscription.platform == Platform.INSTAGRAM.value:
            try:
                instagram_adapter = registry.get_adapter("instagram")
                if not instagram_adapter:
                    raise HTTPException(status_code=400, detail="Instagram平台适配器未找到")

                user_stats = instagram_user_info or await instagram_adapter.get_user_info(subscription.user_id or subscription.profile_url)
                if not user_stats or user_stats.get("__error__"):
                    raise HTTPException(
                        status_code=400,
                        detail=(user_stats or {}).get("__error__") or "无法获取Instagram用户信息，请检查登录态"
                    )

                initial_post_count = 15
                initial_media_limit = 30
                videos_result = await instagram_adapter.get_latest_videos(
                    subscription.user_id,
                    subscription_type="user",
                    max_count=initial_post_count
                )
                videos_list = videos_result.get("videos", []) if videos_result else []
                if len(videos_list) > initial_media_limit:
                    videos_list = videos_list[:initial_media_limit]
                if not videos_list:
                    raise HTTPException(status_code=400, detail="无法获取Instagram媒体列表，请检查账号权限或稍后重试")

                latest_video_data = instagram_adapter.normalize_video_data(videos_list[0], "user")
                latest_video_time = latest_video_data.get("publish_time") or datetime.now()
                latest_video_title = latest_video_data.get("title", "")
                latest_video_cover = latest_video_data.get("cover_url", "")
                latest_video_id = latest_video_data.get("video_id", "")

                subscription.user_id = user_stats.get("user_id") or subscription.user_id
                subscription.nickname = user_stats.get("nickname") or subscription.nickname or subscription.user_id
                logger.info(f"首次订阅获取到 {len(videos_list)} 个Instagram媒体（最近{initial_post_count}个帖子，最多{initial_media_limit}个子媒体）")
            except HTTPException:
                raise
            except Exception as e:
                logger.error(f"获取Instagram用户信息失败: {str(e)}")
                raise HTTPException(status_code=400, detail=f"获取Instagram用户信息失败: {str(e)}")

        elif subscription.platform == Platform.DOUYIN_COLLECTION.value:
            try:
                # 合集订阅：解析合集 URL 并获取合集视频
                url_to_parse = subscription.profile_url or subscription.user_id
                collection_info = await parse_collection_url(url_to_parse)
                is_collection_subscription = True

                subscription.user_id = collection_info["collection_id"]
                subscription.nickname = collection_info.get("collection_title") or f"合集 {collection_info['collection_id']}"

                collection_videos = await get_collection_videos(collection_info["collection_id"], count=30)

                if not collection_videos or not collection_videos.get("videos"):
                    raise HTTPException(
                        status_code=400,
                        detail="无法获取合集视频信息，请检查链接是否正确或稍后重试"
                    )

                videos_list = collection_videos.get("videos", [])
                accurate_total = int(collection_videos.get("total_count", 0) or 0)
                try:
                    if (accurate_total <= len(videos_list)) and collection_videos.get("has_more"):
                        cursor_count = int(collection_videos.get("next_cursor", 0) or 0)
                        has_more_count = bool(collection_videos.get("has_more"))
                        page_total = len(videos_list)
                        while has_more_count:
                            page = await get_collection_videos(collection_info["collection_id"], cursor=cursor_count, count=50, with_meta=False)
                            items = page.get("videos", []) or []
                            page_total += len(items)
                            has_more_count = bool(page.get("has_more"))
                            cursor_count = int(page.get("next_cursor", 0) or 0)
                            await asyncio.sleep(random.uniform(0.2, 0.5))
                        accurate_total = page_total
                except Exception as _e:
                    logger.warning(f"统计合集总数失败，使用接口返回的数量: {str(_e)}")

                user_stats = {
                    'follower_count': 0,
                    'video_count': accurate_total or collection_videos.get("total_count", 0),
                    'like_count': 0,
                    'signature': f"合集：{collection_videos.get('collection_title', '')}",
                    'avatar_url': None
                }

                if collection_videos.get("collection_title"):
                    subscription.nickname = collection_videos["collection_title"].strip()
                collection_cover = collection_videos.get("collection_cover")
                if collection_cover:
                    user_stats['avatar_url'] = collection_cover

                if videos_list:
                    latest_video = videos_list[-1]
                    publish_time = latest_video.get("publish_time")
                    if publish_time and publish_time > 0:
                        latest_video_time = datetime.fromtimestamp(publish_time)
                    else:
                        latest_video_time = datetime.now()
                    latest_video_title = latest_video.get("title", "")
                    latest_video_cover = latest_video.get("cover_url", "")

                if not subscription.nickname:
                    subscription.nickname = f"合集 {subscription.user_id}"

                logger.info(f"抖音合集信息: {json.dumps(collection_info)}")
                logger.info(f"获取到 {len(videos_list)} 个合集视频")

            except Exception as e:
                logger.error(f"获取抖音合集信息失败: {str(e)}")
                raise HTTPException(
                    status_code=400,
                    detail="获取合集信息或视频失败，请检查链接是否正确或稍后重试"
                )

        elif subscription.platform == Platform.DOUYIN.value:
            try:
                # 使用适配器获取用户信息和视频
                douyin_adapter = registry.get_adapter("douyin")
                if not douyin_adapter:
                    raise HTTPException(status_code=400, detail="抖音平台适配器未找到")
                
                # 获取用户信息
                user_info = await douyin_adapter.get_user_info(subscription.user_id)
                if not user_info:
                    raise HTTPException(
                        status_code=400,
                        detail="无法获取用户信息，请检查链接是否正确或稍后重试，或该账号为私密账号"
                    )
                
                user_stats = {
                    'follower_count': user_info.get('follower_count', 0),
                    'video_count': user_info.get('video_count', 0),
                    'like_count': user_info.get('like_count', 0),
                    'signature': user_info.get('signature', ''),
                    'avatar_url': user_info.get('avatar_url', '')
                }

                if not is_collection_subscription:
                    # 使用适配器获取最新视频
                    videos_result = await douyin_adapter.get_latest_videos(
                        subscription.user_id,
                        subscription_type="user",
                        max_count=30
                    )
                    
                    videos_list = videos_result.get("videos", []) if videos_result else []
                    
                    if not videos_list:
                        raise HTTPException(
                            status_code=400, 
                            detail="无法获取最新视频信息，请稍后重试或检查网络连接，或该账号为私密账号"
                        )
                    
                    # 使用适配器标准化第一个视频
                    if videos_list:
                        latest_video_data = douyin_adapter.normalize_video_data(videos_list[0], "user")
                        latest_video_time = latest_video_data.get("publish_time", datetime.now())
                        latest_video_title = latest_video_data.get("title", "")
                        latest_video_cover = latest_video_data.get("cover_url", "")
                
            except HTTPException:
                raise
            except Exception as e:
                logger.error(f"获取用户信息或最新视频失败: {str(e)}")
                raise HTTPException(
                    status_code=400, 
                    detail="获取用户信息或最新视频失败，请检查链接是否正确或稍后重试，或该账号为私密账号"
                )
                
        elif subscription.platform == Platform.YOUTUBE.value:
            try:
                # 使用适配器获取YouTube频道信息和视频
                youtube_adapter = registry.get_adapter("youtube")
                if not youtube_adapter:
                    raise HTTPException(status_code=400, detail="YouTube平台适配器未找到")
                
                # 构建频道URL（适配器内部会处理）
                if subscription.user_id.startswith('UC') and len(subscription.user_id) == 24:
                    channel_url = f"https://www.youtube.com/channel/{subscription.user_id}"
                else:
                    if not subscription.user_id.startswith('@'):
                        channel_url = f"https://www.youtube.com/@{subscription.user_id}"
                    else:
                        channel_url = f"https://www.youtube.com/{subscription.user_id}"
                
                channel_info = await youtube_adapter.get_user_info(channel_url)
                
                if not channel_info:
                    raise HTTPException(
                        status_code=400, 
                        detail="无法获取频道信息，请检查链接是否正确或稍后重试"
                    )
                
                if channel_info.get("channel_id"):
                    subscription.user_id = channel_info["channel_id"]
                if channel_info.get("name"):
                    subscription.nickname = channel_info["name"]
                    
                user_stats = {
                    'follower_count': channel_info.get('follower_count', 0),
                    'video_count': channel_info.get('video_count', 0),
                    'like_count': channel_info.get('like_count', 0),
                    'signature': channel_info.get('signature', ''),
                    'avatar_url': channel_info.get('avatar_url', '')
                }
                
                tab_type = subscription.youtube_tab_type or "videos"
                target_count = 30
                
                # 使用适配器获取最新视频
                videos_result = await youtube_adapter.get_latest_videos(
                    subscription.user_id,
                    subscription_type="channel",
                    max_count=target_count,
                    tab_type=tab_type
                )
                
                videos_list = videos_result.get("videos", []) if videos_result else []
                
                if not videos_list:
                    raise HTTPException(
                        status_code=400, 
                        detail=f"无法获取最新{tab_type}信息，请稍后重试或检查网络连接"
                    )
                
                # 使用适配器标准化第一个视频
                if videos_list:
                    latest_video_data = youtube_adapter.normalize_video_data(videos_list[0], "channel")
                    latest_video_time = latest_video_data.get("publish_time", datetime.now())
                    latest_video_title = latest_video_data.get("title", "")
                    latest_video_cover = latest_video_data.get("cover_url", "")
                
                logger.info(f"YouTube频道信息: {json.dumps(user_stats)}")
                logger.info(f"获取到 {len(videos_list)} 个YouTube内容（标签类型: {tab_type}）")
                
            except HTTPException:
                raise
            except Exception as e:
                logger.error(f"获取YouTube频道信息失败: {str(e)}")
                raise HTTPException(status_code=400, detail=f"获取YouTube频道信息失败: {str(e)}")
        
        elif subscription.platform == Platform.YOUTUBE_PLAYLIST.value:
            try:
                playlist_id = subscription.user_id
                from routers.youtube import get_playlist_videos
                playlist_videos = await get_playlist_videos(playlist_id, max_count=30, page_token="")
                
                if not playlist_videos or not playlist_videos.get("items"):
                    raise HTTPException(
                        status_code=400,
                        detail="无法获取播放列表视频信息，请检查播放列表链接是否正确或稍后重试"
                    )
                
                videos_list = playlist_videos["items"]
                
                playlist_meta = playlist_videos.get("playlist") or {}
                playlist_title = (playlist_meta.get("title") or "").strip()
                if playlist_title:
                    subscription.nickname = playlist_title
                elif not subscription.nickname:
                    subscription.nickname = f"播放列表 {playlist_id}"
                
                playlist_video_count = playlist_meta.get("videoCount") or len(videos_list)
                
                if playlist_meta:
                    user_stats = {
                        'follower_count': 0,
                        'video_count': playlist_video_count,
                        'like_count': 0,
                        'signature': playlist_meta.get("description") or "",
                        'avatar_url': playlist_meta.get("thumbnail")
                    }
                
                if videos_list:
                    latest_video = videos_list[0]
                    snippet = latest_video.get("snippet", {})
                    published_at = snippet.get("publishedAt", "")
                    if published_at:
                        if published_at.endswith("Z"):
                            published_at = published_at.replace("Z", "+00:00")
                        latest_video_time = datetime.fromisoformat(published_at)
                    latest_video_title = snippet.get("title", "")
                    latest_video_cover = snippet.get("thumbnails", {}).get("high", {}).get("url", "")
                
                if not user_stats:
                    user_stats = {
                        'follower_count': 0,
                        'video_count': len(videos_list),
                        'like_count': 0,
                        'signature': f"YouTube播放列表: {subscription.nickname}",
                        'avatar_url': latest_video_cover if videos_list else ""
                    }
                else:
                    user_stats['video_count'] = playlist_video_count or len(videos_list)
                    if not user_stats.get('signature'):
                        user_stats['signature'] = f"YouTube播放列表: {subscription.nickname}"
                    if not user_stats.get('avatar_url'):
                        user_stats['avatar_url'] = latest_video_cover if videos_list else ""
                
                logger.info(f"YouTube播放列表信息: {json.dumps(user_stats)}")
                logger.info(f"获取到 {len(videos_list)} 个播放列表视频")
                
            except Exception as e:
                logger.error(f"获取YouTube播放列表信息失败: {str(e)}")
                raise HTTPException(status_code=400, detail=f"获取YouTube播放列表信息失败: {str(e)}")
        
        elif subscription.platform == Platform.BILIBILI.value:
            if hasattr(subscription, 'subscription_type') and subscription.subscription_type == "favorite":
                logger.info("B站收藏夹订阅信息已在上方处理完成，跳过UP主视频获取")
            else:
                try:
                    # 使用适配器获取B站UP主信息和视频
                    bilibili_adapter = registry.get_adapter("bilibili")
                    if not bilibili_adapter:
                        raise HTTPException(status_code=400, detail="B站平台适配器未找到")
                    
                    if bilibili_user_info:
                        up_info = bilibili_user_info
                        logger.info("使用已获取的B站UP主信息，避免重复调用")
                    else:
                        up_info = await bilibili_adapter.get_user_info(subscription.user_id, "user")
                        logger.info("重新获取B站UP主信息")
                    
                    if not up_info:
                        raise HTTPException(status_code=400, detail="无法获取B站UP主信息")
                    
                    subscription.user_id = up_info.get("user_id", subscription.user_id)
                    subscription.nickname = up_info.get("nickname", "")
                    
                    user_stats = {
                        'follower_count': up_info.get('follower_count', 0),
                        'video_count': up_info.get('video_count', 0),
                        'like_count': up_info.get('like_count', 0),
                        'signature': up_info.get('signature', ''),
                        'avatar_url': up_info.get('avatar_url', ''),
                        'following_count': up_info.get('following_count', 0),
                        'play_count': up_info.get('play_count', 0)
                    }
                    
                    target_count = 30
                    # 使用适配器获取最新视频
                    videos_result = await bilibili_adapter.get_latest_videos(
                        subscription.user_id,
                        subscription_type="user",
                        max_count=target_count
                    )
                    
                    videos_list = videos_result.get("videos", []) if videos_result else []
                    
                    if not videos_list:
                        raise HTTPException(
                            status_code=400, 
                            detail="无法获取最新视频信息，请稍后重试或检查网络连接"
                        )
                    
                    # 使用适配器标准化第一个视频
                    if videos_list:
                        latest_video_data = bilibili_adapter.normalize_video_data(videos_list[0], "user")
                        latest_video_time = latest_video_data.get("publish_time", datetime.now())
                        latest_video_title = latest_video_data.get("title", "")
                        latest_video_cover = latest_video_data.get("cover_url", "")
                    
                    logger.info(f"B站UP主信息: {json.dumps(user_stats)}")
                    logger.info(f"获取到 {len(videos_list)} 个B站视频")
                    
                except HTTPException:
                    raise
                except Exception as e:
                    logger.error(f"获取B站UP主信息失败: {str(e)}")
                    raise HTTPException(status_code=400, detail=f"获取B站UP主信息失败: {str(e)}")
        
        elif subscription.platform == Platform.BILIBILI_COLLECTION.value:
            try:
                # 使用适配器获取B站合集信息和视频
                bilibili_adapter = registry.get_adapter("bilibili")
                if not bilibili_adapter:
                    raise HTTPException(status_code=400, detail="B站平台适配器未找到")
                
                if bilibili_user_info:
                    collection_info = bilibili_user_info
                    logger.info("使用已获取的B站合集信息，避免重复调用")
                else:
                    collection_info = await bilibili_adapter.get_user_info(subscription.user_id, "collection")
                    logger.info("重新获取B站合集信息")
                
                if not collection_info:
                    raise HTTPException(status_code=400, detail="无法获取B站合集信息")
                
                subscription.user_id = collection_info.get("bvid", subscription.user_id)
                collection_title = collection_info.get("collection_title") or collection_info.get("nickname") or collection_info.get("title", "")
                subscription.nickname = collection_title
                
                # 优先使用适配器返回的avatar_url，如果没有则使用cover_url
                avatar_url = collection_info.get('avatar_url') or collection_info.get('cover_url', '')
                user_stats = {
                    'follower_count': 0,
                    'video_count': collection_info.get('videos_count', 0),
                    'like_count': 0,
                    'signature': f"B站合集: {collection_title}",
                    'avatar_url': avatar_url,
                    'following_count': 0,
                    'play_count': 0
                }
                
                target_count = 30
                # 使用适配器获取最新视频
                videos_result = await bilibili_adapter.get_latest_videos(
                    subscription.user_id,
                    subscription_type="collection",
                    max_count=target_count
                )
                
                videos_list = videos_result.get("videos", []) if videos_result else []
                
                if not videos_list:
                    raise HTTPException(
                        status_code=400, 
                        detail="无法获取合集视频信息，请稍后重试或检查网络连接"
                    )
                
                # 使用适配器标准化第一个视频
                if videos_list:
                    latest_video_data = bilibili_adapter.normalize_video_data(videos_list[0], "collection")
                    latest_video_id = latest_video_data.get("video_id", "")
                    latest_video_time = latest_video_data.get("publish_time", datetime.now())
                    latest_video_title = latest_video_data.get("title", "")
                    latest_video_cover = latest_video_data.get("cover_url", "")
                    
                    # 如果合集封面为空，使用第一个视频的封面作为头像（参考B站收藏夹订阅的逻辑）
                    if not user_stats.get('avatar_url') and latest_video_cover:
                        user_stats['avatar_url'] = latest_video_cover
                        logger.info(f"使用第一个视频封面作为B站合集头像: {latest_video_cover}")
                
                logger.info(f"B站合集信息: {json.dumps(user_stats)}")
                logger.info(f"获取到 {len(videos_list)} 个合集视频")
                
            except Exception as e:
                logger.error(f"获取B站合集信息失败: {str(e)}")
                raise HTTPException(status_code=400, detail=f"获取B站合集信息失败: {str(e)}")
        
        elif subscription.platform == Platform.TIKTOK.value:
            try:
                user_url = subscription.profile_url if hasattr(subscription, 'profile_url') and subscription.profile_url else subscription.user_id
                if not user_url:
                    raise HTTPException(status_code=400, detail="请提供TikTok用户主页链接或用户名")
                
                user_info = await tiktok_api.get_user_info(user_url)
                
                subscription.user_id = user_info["user_id"]
                subscription.nickname = user_info["nickname"]
                
                user_stats = {
                    'follower_count': user_info.get('follower_count'),
                    'video_count': user_info.get('video_count', 0),
                    'like_count': 0,
                    'signature': user_info.get('signature', ''),
                    'avatar_url': user_info.get('avatar_url', '')
                }
                
                target_count = 30
                videos_result = await tiktok_api.get_user_videos(
                    user_url,
                    max_count=target_count
                )
                
                if not videos_result or not videos_result.get("videos"):
                    raise HTTPException(
                        status_code=400,
                        detail="无法获取TikTok视频信息，请检查链接是否正确或稍后重试"
                    )
                
                videos_list = videos_result["videos"]
                
                if videos_list:
                    latest_video = videos_list[0]
                    create_time = latest_video.get("create_time", 0)
                    if create_time > 0:
                        latest_video_time = datetime.fromtimestamp(create_time)
                    else:
                        latest_video_time = datetime.now()
                    latest_video_title = latest_video.get("title", "")
                    latest_video_cover = latest_video.get("cover_url", "")
                
                logger.info(f"TikTok用户信息: {json.dumps(user_stats)}")
                logger.info(f"获取到 {len(videos_list)} 个TikTok视频")
                
            except Exception as e:
                logger.error(f"获取TikTok用户信息失败: {str(e)}")
                raise HTTPException(status_code=400, detail=f"获取TikTok用户信息失败: {str(e)}")
        
        elif subscription.platform == Platform.NETEASE.value:
            try:
                # 网易云：把歌单当作“订阅源”，首次添加时默认入库 30 首歌曲（对齐 TikTok 行为）
                netease_adapter = registry.get_adapter("netease")
                if not netease_adapter:
                    raise HTTPException(status_code=400, detail="网易云平台适配器未找到")

                playlist_id = subscription.user_id
                if not playlist_id:
                    raise HTTPException(status_code=400, detail="请提供网易云歌单ID或歌单链接")

                target_count = 30
                videos_result = await netease_adapter.get_latest_videos(
                    playlist_id,
                    subscription_type="playlist",
                    max_count=target_count
                )
                videos_list = videos_result.get("videos", []) if videos_result else []
                if not videos_list:
                    raise HTTPException(
                        status_code=400,
                        detail="无法获取网易云歌单歌曲列表，请检查歌单链接/ID是否正确或稍后重试"
                    )

                # 兜底获取歌单标题/封面（yt-dlp flat 模式可能缺失 thumbnail）
                playlist_user_info = await netease_adapter.get_user_info(playlist_id, "playlist")
                if playlist_user_info:
                    if playlist_user_info.get("nickname"):
                        subscription.nickname = playlist_user_info["nickname"]
                    if playlist_user_info.get("avatar_url"):
                        # 先用歌单封面做订阅头像
                        if "user_stats" not in locals() or not user_stats:
                            user_stats = {}
                        user_stats["avatar_url"] = playlist_user_info["avatar_url"]

                # 使用适配器标准化第一个条目，作为订阅的“最新内容”
                latest_video_data = netease_adapter.normalize_video_data(videos_list[0], "playlist")
                latest_video_time = latest_video_data.get("publish_time", datetime.now())
                latest_video_title = latest_video_data.get("title", "")
                latest_video_cover = latest_video_data.get("cover_url", "")
                latest_video_id = latest_video_data.get("video_id", "")

                user_stats = {
                    "follower_count": 0,
                    "video_count": len(videos_list),
                    "like_count": 0,
                    "signature": generate_profile_url(Platform.NETEASE.value, playlist_id) or "",
                    "avatar_url": (user_stats.get("avatar_url") if isinstance(user_stats, dict) else "") or latest_video_cover or ""
                }

                logger.info(f"获取到 {len(videos_list)} 首网易云歌单歌曲（首次订阅默认入库）")
            except HTTPException:
                raise
            except Exception as e:
                logger.error(f"获取网易云歌单信息失败: {str(e)}")
                raise HTTPException(status_code=400, detail=f"获取网易云歌单信息失败: {str(e)}")
        
        elif subscription.platform == Platform.X.value:
            try:
                from services import x_graphql
                screen_name = x_graphql.parse_screen_name(subscription.user_id or subscription.profile_url)
                if not screen_name:
                    raise HTTPException(status_code=400, detail="请输入有效的 X 用户名或主页链接")
                subscription.user_id = screen_name
                subscription.subscription_type = "favorite"

                user_info = x_graphql.fetch_user_info(screen_name)
                if user_info:
                    subscription.nickname = user_info.nickname or subscription.nickname
                    user_stats = {
                        "follower_count": user_info.follower_count,
                        "video_count": user_info.video_count or 0,
                        "like_count": 0,
                        "signature": user_info.signature or "",
                        "avatar_url": user_info.avatar_url or ""
                    }

                target_count = 30
                videos_list = x_graphql.fetch_liked_items(screen_name, max_items=target_count)
                if not videos_list:
                    raise HTTPException(
                        status_code=400,
                        detail="无法获取X点赞视频，请检查 cookie 是否有效或稍后重试"
                    )

                if videos_list:
                    latest_video = videos_list[0]
                    latest_video_time = latest_video.get("publish_time") or datetime.now()
                    latest_video_title = latest_video.get("title", "")
                    latest_video_cover = latest_video.get("cover_url", "")
                    latest_video_id = latest_video.get("video_id", "")
                    # 写入头像到 user_stats（最终入库）
                    if user_stats is None:
                        user_stats = {}
                    if not user_stats.get("avatar_url"):
                        if latest_video_cover:
                            user_stats["avatar_url"] = latest_video_cover
                        else:
                            # 兜底：从列表中找第一个有封面的条目
                            for item in videos_list:
                                cover = item.get("cover_url")
                                if cover:
                                    user_stats["avatar_url"] = cover
                                    break

                logger.info(f"获取到 {len(videos_list)} 条X点赞视频（首次订阅默认入库）")
            except HTTPException:
                raise
            except Exception as e:
                logger.error(f"获取X点赞信息失败: {str(e)}")
                raise HTTPException(status_code=400, detail=f"获取X点赞信息失败: {str(e)}")

        elif subscription.platform == Platform.XIAOHONGSHU.value:
            try:
                # 使用适配器获取小红书用户信息和视频
                xiaohongshu_adapter = registry.get_adapter("xiaohongshu")
                if not xiaohongshu_adapter:
                    raise HTTPException(status_code=400, detail="小红书平台适配器未找到")
                # 链接可能在 profile_url 或 user_id（未进前面解析分支时），在覆盖前保存带 token 的 URL
                url_for_xhs = getattr(subscription, "profile_url", None) or subscription.user_id
                if url_for_xhs and "xsec_token" in (url_for_xhs or ""):
                    xiaohongshu_profile_url_to_save = url_for_xhs
                # 获取用户信息（可能已在前面获取过；url_for_xhs 为完整链接或 user_id）
                user_info = await xiaohongshu_adapter.get_user_info(url_for_xhs)
                if isinstance(user_info, dict) and user_info.get("__error__"):
                    raise HTTPException(status_code=400, detail=user_info.get("__error__"))
                if not user_info:
                    raise HTTPException(
                        status_code=400,
                        detail="无法获取小红书用户信息，请检查链接是否正确或稍后重试"
                    )
                # get_user_info 可接受 URL 或 user_id，上面用 subscription.user_id 可能已是 URL
                subscription.user_id = user_info.get("user_id", subscription.user_id)
                subscription.nickname = user_info.get("nickname", "")
                
                user_stats = {
                    'follower_count': user_info.get('follower_count', 0),
                    'video_count': user_info.get('video_count', 0),
                    'like_count': user_info.get('like_count', 0),
                    'signature': user_info.get('signature', ''),
                    'avatar_url': user_info.get('avatar_url', ''),
                    'following_count': user_info.get('following_count', 0)
                }
                
                # 获取最新笔记（必须传入带 xsec_token 的 profile_url，即创作者主页完整链接）
                target_count = 30
                profile_url_for_api = xiaohongshu_profile_url_to_save or getattr(subscription, "profile_url", None)
                videos_result = await xiaohongshu_adapter.get_latest_videos(
                    subscription.user_id,
                    subscription_type="user",
                    max_count=target_count,
                    profile_url=profile_url_for_api
                )
                videos_list = videos_result.get("videos", []) if videos_result else []
                if not videos_list:
                    err_msg = (videos_result or {}).get("error") or "无法获取最新笔记信息，请稍后重试或检查网络连接"
                    if "xsec_token" in str(err_msg):
                        err_msg = "请使用带 xsec_token 的创作者链接添加订阅（从浏览器地址栏复制完整链接）"
                    raise HTTPException(status_code=400, detail=err_msg)
                
                # 使用适配器标准化第一个视频
                if videos_list:
                    latest_video_data = xiaohongshu_adapter.normalize_video_data(videos_list[0], "user")
                    latest_video_time = latest_video_data.get("publish_time", datetime.now())
                    latest_video_title = latest_video_data.get("title", "")
                    latest_video_cover = latest_video_data.get("cover_url", "")
                
                logger.info(f"小红书用户信息: {json.dumps(user_stats)}")
                logger.info(f"获取到 {len(videos_list)} 个小红书笔记")
                
            except HTTPException:
                raise
            except Exception as e:
                logger.error(f"获取小红书用户信息失败: {str(e)}")
                raise HTTPException(status_code=400, detail=f"获取小红书用户信息失败: {str(e)}")
        
        # 4. 创建新订阅
        if has_custom_nickname:
            subscription.nickname = input_nickname

        latest_video_title = _truncate_video_title(latest_video_title)
        now = datetime.now()
        subscription_id = str(uuid.uuid4())
        nickname_locked = "true" if has_custom_nickname else "false"
        resolved_storage_name = sanitize_filename(subscription.nickname or "")
        if not resolved_storage_name or resolved_storage_name.strip('._ ') == '' or resolved_storage_name == "untitled":
            resolved_storage_name = f"author_{subscription_id[:8]}"
            logger.warning(
                f"订阅目录名清洗后为空，使用兜底目录名: subscription_id={subscription_id}, "
                f"nickname={subscription.nickname}, storage_name={resolved_storage_name}"
            )
        # 自定义昵称场景下做冲突检测：避免多订阅写入同一目录
        if has_custom_nickname:
            storage_name_conflict = db.query(Subscription.id).filter(
                Subscription.platform.in_(_get_storage_platform_candidates(subscription.platform)),
                Subscription.storage_name == resolved_storage_name
            ).first()
            if storage_name_conflict:
                raise HTTPException(
                    status_code=400,
                    detail=(
                        f"目录名称“{resolved_storage_name}”已存在，请更换自定义博主名称后重试"
                    )
                )

        new_subscription = Subscription(
            id=subscription_id,
            platform=subscription.platform,
            user_id=subscription.user_id,
            nickname=subscription.nickname,
            storage_name=resolved_storage_name,
            nickname_locked=nickname_locked,
            update_interval=subscription.update_interval,
            auto_download=str(subscription.auto_download).lower(),
            status=subscription.status,
            created_at=now,
            updated_at=now,
            last_check=now,
            last_update=now,
            latest_video_time=latest_video_time,
            latest_video_title=latest_video_title,
            latest_video_cover=latest_video_cover,
            quality='bestvideo+bestaudio' if subscription.platform in [Platform.YOUTUBE.value, Platform.YOUTUBE_PLAYLIST.value, Platform.BILIBILI.value, Platform.BILIBILI_COLLECTION.value] else 'best',
            youtube_tab_type=subscription.youtube_tab_type if hasattr(subscription, 'youtube_tab_type') else None,
            subscription_type=subscription.subscription_type if hasattr(subscription, 'subscription_type') and subscription.subscription_type else (
                "collection" if subscription.platform == Platform.BILIBILI_COLLECTION.value else "user"
            ),
            collection_id=bilibili_user_info.get("bvid") if bilibili_user_info and subscription.platform == Platform.BILIBILI_COLLECTION.value else None,
            collection_title=bilibili_user_info.get("collection_title") if bilibili_user_info and subscription.platform == Platform.BILIBILI_COLLECTION.value else None,
            author_id=str(bilibili_user_info["owner"]["mid"]) if bilibili_user_info and subscription.platform == Platform.BILIBILI_COLLECTION.value else None,
            author_name=bilibili_user_info["owner"]["name"] if bilibili_user_info and subscription.platform == Platform.BILIBILI_COLLECTION.value else None,
            skip_bilibili_upower=getattr(subscription, 'skip_bilibili_upower', 'false')
        )
        
        # 5. 如果有用户统计信息，添加到订阅中
        if user_stats:
            new_subscription.follower_count = user_stats.get('follower_count')
            new_subscription.following_count = user_stats.get('following_count')
            new_subscription.video_count = user_stats.get('video_count')
            new_subscription.like_count = user_stats.get('like_count')
            new_subscription.signature = user_stats.get('signature')
            avatar_url_value = user_stats.get('avatar_url')
            new_subscription.avatar_url = avatar_url_value
            new_subscription.last_sync_info = now
            logger.info(f"设置订阅头像: platform={subscription.platform}, subscription_type={getattr(subscription, 'subscription_type', None)}, avatar_url={avatar_url_value}")
        
        # 5.1 profile_url 必须在 commit 前设置才会写入数据库（小红书需保留带 xsec_token 的完整链接）
        if new_subscription.subscription_type != "favorite" or new_subscription.platform != Platform.BILIBILI.value:
            if new_subscription.platform == Platform.XIAOHONGSHU.value and xiaohongshu_profile_url_to_save:
                new_subscription.profile_url = xiaohongshu_profile_url_to_save
            else:
                new_subscription.profile_url = generate_profile_url(new_subscription.platform, new_subscription.user_id)
        
        # 6. 设置最新视频时间（如果已获取）
        if latest_video_time:
            new_subscription.latest_video_time = latest_video_time
        # 6.1 设置最新视频ID（如已获取）
        if 'latest_video_id' in locals() and latest_video_id:
            try:
                new_subscription.latest_video_id = str(latest_video_id)
            except Exception:
                pass
        
        # 7. 保存订阅信息
        db.add(new_subscription)
        
        # 8. 保存所有获取到的视频记录
        if videos_list:
            if subscription.platform == Platform.DOUYIN.value or subscription.platform == Platform.DOUYIN_COLLECTION.value:
                for video in videos_list:
                    if subscription.platform == Platform.DOUYIN_COLLECTION.value:
                        publish_ts = video.get("publish_time")
                        if isinstance(publish_ts, (int, float)) and publish_ts > 0:
                            video_time = datetime.fromtimestamp(int(publish_ts))
                        else:
                            video_time = now
                        new_video = SubscriptionVideo(
                            subscription_id=subscription_id,
                            video_id=video["video_id"],
                            title=_truncate_video_title(video["title"]),
                            url=video["url"],
                            cover_url=video.get("cover_url"),
                            publish_time=video_time,
                            downloaded="false",
                            created_at=now,
                            extra_data=json.dumps({
                                "publish_time_text": video_time.strftime("%Y-%m-%d %H:%M:%S"),
                                "duration_text": video.get("duration_text"),
                                "play_count": video.get("play_count"),
                                "collection_video": True
                            })
                        )
                    else:
                        video_time = datetime.fromtimestamp(int(video.get("create_time", 0)))
                        aweme_id = video["aweme_id"]
                        new_video = SubscriptionVideo(
                            subscription_id=subscription_id,
                            video_id=aweme_id,
                            title=_truncate_video_title(video["desc"]),
                            url=get_correct_douyin_url(aweme_id, video),
                            cover_url=video.get("video", {}).get("cover", {}).get("url_list", [None])[0],
                            publish_time=video_time,
                            downloaded="false",
                            created_at=now,
                            extra_data=json.dumps({
                                "publish_time_text": video_time.strftime("%Y-%m-%d %H:%M:%S")
                            })
                        )
                    new_video.id = str(uuid.uuid4())
                    db.add(new_video)
            elif subscription.platform == Platform.YOUTUBE.value:
                for video in videos_list:
                    snippet = video.get("snippet", {})
                    video_id = video.get("id", {}).get("videoId", "")
                    published_at = (snippet.get("publishedAt") or "").replace("Z", "+00:00")
                    try:
                        video_time = datetime.fromisoformat(published_at) if published_at else now
                    except Exception:
                        video_time = now
                    
                    new_video = SubscriptionVideo(
                        subscription_id=subscription_id,
                        video_id=video_id,
                        title=_truncate_video_title(snippet.get("title", "")),
                        url=f"https://www.youtube.com/watch?v={video_id}",
                        cover_url=snippet.get("thumbnails", {}).get("high", {}).get("url", ""),
                        publish_time=video_time,
                        downloaded="false",
                        created_at=now,
                        extra_data=json.dumps({
                            "publish_time_text": video_time.strftime("%Y-%m-%d %H:%M:%S"),
                            "description": snippet.get("description", ""),
                            "view_count": video.get("statistics", {}).get("viewCount", "0")
                        })
                    )
                    new_video.id = str(uuid.uuid4())
                    db.add(new_video)
            elif subscription.platform == Platform.YOUTUBE_PLAYLIST.value:
                for video in videos_list:
                    snippet = video.get("snippet", {})
                    video_id = video.get("id", {}).get("videoId", "")
                    published_at = (snippet.get("publishedAt") or "").replace("Z", "+00:00")
                    try:
                        video_time = datetime.fromisoformat(published_at) if published_at else now
                    except Exception:
                        video_time = now

                    new_video = SubscriptionVideo(
                        subscription_id=subscription_id,
                        video_id=video_id,
                        title=_truncate_video_title(snippet.get("title", "")),
                        url=f"https://www.youtube.com/watch?v={video_id}",
                        cover_url=snippet.get("thumbnails", {}).get("high", {}).get("url", ""),
                        publish_time=video_time,
                        downloaded="false",
                        created_at=now,
                        extra_data=json.dumps({
                            "publish_time_text": video_time.strftime("%Y-%m-%d %H:%M:%S"),
                            "description": snippet.get("description", ""),
                            "view_count": video.get("statistics", {}).get("viewCount", "0")
                        })
                    )
                    new_video.id = str(uuid.uuid4())
                    db.add(new_video)
            elif subscription.platform == Platform.INSTAGRAM.value:
                instagram_adapter = registry.get_adapter("instagram")
                if not instagram_adapter:
                    raise HTTPException(status_code=400, detail="Instagram平台适配器未找到")
                for raw_media in videos_list:
                    media = instagram_adapter.normalize_video_data(raw_media, "user")
                    video_id = media.get("video_id") or ""
                    if not video_id:
                        logger.warning(f"跳过无效Instagram媒体: {raw_media}")
                        continue
                    media_time = media.get("publish_time") or now
                    if isinstance(media_time, str):
                        try:
                            media_time = datetime.fromisoformat(media_time.replace("Z", "+00:00"))
                        except Exception:
                            media_time = now
                    extra_data = {
                        "publish_time_text": media_time.strftime("%Y-%m-%d %H:%M:%S"),
                    }
                    if isinstance(media.get("extra_data"), dict):
                        extra_data.update(media["extra_data"])
                    new_video = SubscriptionVideo(
                        subscription_id=subscription_id,
                        video_id=str(video_id),
                        title=_truncate_video_title(media.get("title", "")),
                        description=media.get("description", ""),
                        url=media.get("url", ""),
                        cover_url=media.get("cover_url", ""),
                        duration=media.get("duration"),
                        publish_time=media_time,
                        downloaded="false",
                        created_at=now,
                        extra_data=json.dumps(extra_data)
                    )
                    new_video.id = str(uuid.uuid4())
                    db.add(new_video)
            elif subscription.platform == Platform.BILIBILI.value:
                if hasattr(subscription, 'subscription_type') and subscription.subscription_type == "favorite":
                    for video in videos_list:
                        if getattr(subscription, 'skip_bilibili_upower', 'false') == 'true' and video.get('is_charging_arc', False):
                            logger.info(f"添加订阅：跳过 B 站充电专属视频: {video.get('title')}")
                            continue

                        video_id = video.get("video_id", "")
                        publish_time_str = video.get("publish_time", "")
                        
                        if publish_time_str:
                            try:
                                if publish_time_str.endswith("Z"):
                                    publish_time_str = publish_time_str.replace("Z", "+00:00")
                                video_time = datetime.fromisoformat(publish_time_str)
                            except Exception as e:
                                logger.warning(f"B站收藏夹视频时间解析失败: {publish_time_str}, 错误: {str(e)}, 使用当前时间")
                                video_time = now
                        else:
                            video_time = now
                        
                        new_video = SubscriptionVideo(
                            subscription_id=subscription_id,
                            video_id=video_id,
                            title=_truncate_video_title(video.get("title", "")),
                            url=video.get("url", ""),
                            cover_url=video.get("cover_url", ""),
                            publish_time=video_time,
                            downloaded="false",
                            created_at=now,
                            extra_data=json.dumps({
                                "publish_time_text": video_time.strftime("%Y-%m-%d %H:%M:%S"),
                                "duration": video.get("duration", 0),
                                "uploader": video.get("uploader", ""),
                                "uploader_id": video.get("uploader_id", ""),
                                "favorite_video": True,
                                "is_charging_arc": video.get("is_charging_arc", False)
                            })
                        )
                        new_video.id = str(uuid.uuid4())
                        db.add(new_video)
                else:
                    for video in videos_list:
                        if getattr(subscription, 'skip_bilibili_upower', 'false') == 'true' and video.get('is_charging_arc', False):
                            logger.info(f"添加订阅：跳过 B 站充电专属视频: {video.get('title')}")
                            continue

                        video_id = video.get("url", "").split("/")[-1] if video.get("url") else ""
                        video_time = datetime.fromisoformat(video.get("publish_time_parsed", ""))
                        
                        new_video = SubscriptionVideo(
                            subscription_id=subscription_id,
                            video_id=video_id,
                            title=_truncate_video_title(video.get("title", "")),
                            url=video.get("url", ""),
                            cover_url=video.get("cover_url", ""),
                            publish_time=video_time,
                            downloaded="false",
                            created_at=now,
                            extra_data=json.dumps({
                                "publish_time_text": video_time.strftime("%Y-%m-%d %H:%M:%S"),
                                "play_count": video.get("play_count", "0"),
                                "is_charging_arc": video.get("is_charging_arc", False)
                            })
                        )
                        new_video.id = str(uuid.uuid4())
                        db.add(new_video)
            elif subscription.platform == Platform.BILIBILI_COLLECTION.value:
                for video in videos_list:
                    if getattr(subscription, 'skip_bilibili_upower', 'false') == 'true' and video.get('is_charging_arc', False):
                        logger.info(f"添加订阅：跳过 B 站充电专属视频: {video.get('title')}")
                        continue

                    video_id = video.get("video_id", "")
                    video_time = datetime.fromisoformat(video.get("publish_time", ""))
                    
                    new_video = SubscriptionVideo(
                        subscription_id=subscription_id,
                        video_id=video_id,
                        title=_truncate_video_title(video.get("title", "")),
                        url=video.get("url", ""),
                        cover_url=video.get("cover_url", ""),
                        publish_time=video_time,
                        downloaded="false",
                        created_at=now,
                        extra_data=json.dumps({
                            "publish_time_text": video_time.strftime("%Y-%m-%d %H:%M:%S"),
                            "page": video.get("page", 1),
                            "cid": video.get("cid", ""),
                            "duration": video.get("duration", ""),
                            "author": video.get("author", ""),
                            "author_id": video.get("author_id", ""),
                            "is_charging_arc": video.get("is_charging_arc", False),
                            "section_title": video.get("section_title", ""),
                            "episode_title": video.get("episode_title", ""),
                            "root_bvid": video.get("root_bvid", ""),
                            "root_bvid_title": video.get("root_bvid_title", ""),
                            "stats": {
                                "page": video.get("page", 1),
                                "cid": video.get("cid", ""),
                                "duration": video.get("duration", ""),
                                "author": video.get("author", ""),
                                "author_id": video.get("author_id", ""),
                                "section_title": video.get("section_title", ""),
                                "episode_title": video.get("episode_title", ""),
                                "root_bvid": video.get("root_bvid", ""),
                                "root_bvid_title": video.get("root_bvid_title", "")
                            }
                        })
                    )
                    new_video.id = str(uuid.uuid4())
                    db.add(new_video)
            elif subscription.platform == Platform.TIKTOK.value:
                for video in videos_list:
                    video_id = video.get("video_id", "")
                    create_time = video.get("create_time", 0)
                    if create_time > 0:
                        video_time = datetime.fromtimestamp(create_time)
                    else:
                        video_time = now
                    
                    new_video = SubscriptionVideo(
                        subscription_id=subscription_id,
                        video_id=video_id,
                        title=_truncate_video_title(video.get("title", "")),
                        url=video.get("video_url", ""),
                        cover_url=video.get("cover_url", ""),
                        publish_time=video_time,
                        downloaded="false",
                        created_at=now,
                        extra_data=json.dumps({
                            "publish_time_text": video_time.strftime("%Y-%m-%d %H:%M:%S"),
                            "view_count": video.get("view_count", 0),
                            "like_count": video.get("like_count", 0),
                            "comment_count": video.get("comment_count", 0),
                            "share_count": video.get("share_count", 0),
                            "duration": video.get("duration", 0)
                        })
                    )
                    new_video.id = str(uuid.uuid4())
                    db.add(new_video)
            elif subscription.platform == Platform.X.value:
                for video in videos_list:
                    video_id = video.get("video_id", "")
                    video_time = video.get("publish_time") or now
                    if isinstance(video_time, str):
                        try:
                            video_time = datetime.fromisoformat(video_time.replace("Z", "+00:00"))
                        except Exception:
                            video_time = now
                    new_video = SubscriptionVideo(
                        subscription_id=subscription_id,
                        video_id=video_id,
                        title=_truncate_video_title(video.get("title", "")),
                        url=video.get("url", ""),
                        cover_url=video.get("cover_url", ""),
                        publish_time=video_time,
                        downloaded="false",
                        created_at=now,
                        extra_data=json.dumps({
                            "publish_time_text": video_time.strftime("%Y-%m-%d %H:%M:%S"),
                        })
                    )
                    new_video.id = str(uuid.uuid4())
                    db.add(new_video)
            elif subscription.platform == Platform.NETEASE.value:
                # 网易云：先标准化歌曲数据再保存（对齐小红书写法）
                netease_adapter = registry.get_adapter("netease")
                if not netease_adapter:
                    raise HTTPException(status_code=400, detail="网易云平台适配器未找到")

                for raw_song in videos_list:
                    song = netease_adapter.normalize_video_data(raw_song, "playlist")
                    video_id = song.get("video_id") or ""
                    if not video_id:
                        logger.warning(f"跳过无效网易云歌曲条目: {raw_song}")
                        continue
                    video_time = song.get("publish_time") or now

                    extra_data = {
                        "publish_time_text": video_time.strftime("%Y-%m-%d %H:%M:%S"),
                    }

                    new_video = SubscriptionVideo(
                        subscription_id=subscription_id,
                        video_id=str(video_id),
                        title=_truncate_video_title(song.get("title", "")),
                        url=song.get("url", ""),
                        cover_url=song.get("cover_url", ""),
                        publish_time=video_time,
                        downloaded="false",
                        created_at=now,
                        extra_data=json.dumps(extra_data)
                    )
                    new_video.id = str(uuid.uuid4())
                    db.add(new_video)
            elif subscription.platform == Platform.XIAOHONGSHU.value:
                # 小红书：先标准化笔记数据再保存
                for raw_video in videos_list:
                    video = xiaohongshu_adapter.normalize_video_data(raw_video, "user")
                    video_id = video.get("video_id") or ""
                    if not video_id:
                        logger.warning(f"跳过无效小红书笔记: {raw_video}")
                        continue
                    video_time = video.get("publish_time") or now
                    # 合并 extra_data，确保 type 和 xsec_token 等字段都被保存
                    extra_data = {
                        "publish_time_text": video_time.strftime("%Y-%m-%d %H:%M:%S"),
                        "digg_count": video.get("stats", {}).get("digg_count", 0)
                    }
                    # 合并 normalize_video_data 返回的 extra_data（包含 type 和 xsec_token）
                    if "extra_data" in video and isinstance(video.get("extra_data"), dict):
                        extra_data.update(video["extra_data"])
                    new_video = SubscriptionVideo(
                        subscription_id=subscription_id,
                        video_id=video_id,
                        title=_truncate_video_title(video.get("title", "")),
                        url=video.get("url", ""),
                        cover_url=video.get("cover_url", ""),
                        publish_time=video_time,
                        downloaded="false",
                        created_at=now,
                        extra_data=json.dumps(extra_data)
                    )
                    new_video.id = str(uuid.uuid4())
                    db.add(new_video)
        
        db.commit()
        db.refresh(new_subscription)
        
        logger.info(f"订阅创建完成: id={new_subscription.id}, nickname={new_subscription.nickname}, avatar_url={new_subscription.avatar_url}")
        
        return new_subscription
        
    except HTTPException as he:
        raise he
    except Exception as e:
        db.rollback()
        logger.error(f"添加订阅失败: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))
