"""
同步和检查更新相关路由
"""
import asyncio
import json
import random
import uuid
import os
import re
from datetime import datetime, timezone
from typing import Optional, List
from fastapi import APIRouter, HTTPException, Depends, Request, Body, Query
from sqlalchemy.orm import Session
from sql.database_postgresql import get_db
from sql.models import Subscription, SubscriptionVideo, SubscriptionStatus, Platform
from routers.auth import require_license_api
from routers.scheduler import scheduler
from routers.douyin import douyin_api, get_collection_videos
from routers.youtube import youtube_api
from routers.bilibili import bilibili_api, get_bilibili_favorite_info, get_bilibili_favorite_videos
from routers.tiktok import tiktok_api
from routers import instagram as instagram_api
from routers.unified_browser_manager import unified_browser
from routers.websocket import send_progress_update
from .common import logger, PLATFORM_CONCURRENT_LIMITS
from .models import CheckUpdateResponse
from .platforms import registry
from .utils import (
    get_correct_douyin_url,
    _cleanup_subscription_pages,
    _cleanup_platform_pages,
    send_subscription_check_notification,
    _expected_dev_secret,
    _async_add_download,
    generate_profile_url
)

router = APIRouter()
MAX_VIDEO_TITLE_LENGTH = 500
RESOURCE_FAILURE_THRESHOLD = 3
RESOURCE_FAILURE_KEYWORDS = (
    "not found",
    "does not exist",
    "doesn't exist",
    "no such",
    "unavailable",
    "video unavailable",
    "playlist does not exist",
    "channel does not exist",
    "account has been terminated",
    "deleted",
    "removed",
    "suspended",
    "private",
    "resource not found",
    "404",
    "不存在",
    "已删除",
    "已失效",
    "资源失效",
    "资源不存在",
    "账号不存在",
    "用户不存在",
    "内容不存在",
    "视频不存在",
    "歌单不存在",
    "页面不存在",
    "已被封禁",
    "已注销",
)


def _douyin_request_delay_seconds(page_count: int, mode: str = "check") -> float:
    """抖音分页请求延时策略（仅节奏优化，不改变业务逻辑）。

    Args:
        page_count: 当前分页次数（从1开始）
        mode: check 或 sync
    """
    if mode == "sync":
        base_min, base_max = 1.8, 3.6
    else:
        base_min, base_max = 1.4, 2.8

    delay = random.uniform(base_min, base_max)
    # 阶梯式停顿：随着分页增多，模拟真人操作的间歇停留
    if page_count > 0 and page_count % 20 == 0:
        delay += random.uniform(3.0, 6.0)
    elif page_count > 0 and page_count % 8 == 0:
        delay += random.uniform(1.0, 2.0)
    return delay


def _bilibili_detail_delay_seconds(fetch_index: int) -> float:
    """B站详情补全请求延时策略（用于收藏夹检测时逐条补全）。"""
    delay = random.uniform(0.6, 1.2)
    if fetch_index > 0 and fetch_index % 10 == 0:
        delay += random.uniform(1.0, 2.0)
    return delay


def _truncate_video_title(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    return value[:MAX_VIDEO_TITLE_LENGTH]


def _safe_douyin_cover_url(item: dict) -> Optional[str]:
    """安全提取抖音封面URL，避免空 url_list 导致索引异常。"""
    try:
        url_list = item.get("video", {}).get("cover", {}).get("url_list") or []
        if isinstance(url_list, list) and url_list:
            return url_list[0]
    except Exception:
        pass
    return None


def _load_subscription_extra_data(subscription: Subscription) -> dict:
    try:
        data = json.loads(subscription.extra_data or "{}")
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _save_subscription_extra_data(subscription: Subscription, data: dict) -> None:
    subscription.extra_data = json.dumps(data, ensure_ascii=False) if data else None


def _is_resource_failure(error_message: Optional[str]) -> bool:
    message = (error_message or "").lower()
    return any(keyword in message for keyword in RESOURCE_FAILURE_KEYWORDS)


def _mark_subscription_check_success(subscription: Subscription) -> None:
    extra = _load_subscription_extra_data(subscription)
    health = extra.get("health") if isinstance(extra.get("health"), dict) else {}
    previous_count = int(health.get("resource_failure_count", 0) or 0)

    if previous_count > 0:
        logger.info(f"订阅[{subscription.nickname}]检测成功，清理资源失败计数（原计数: {previous_count}）")

    health.pop("resource_failure_count", None)
    health.pop("last_resource_failure_at", None)
    health.pop("last_resource_failure_message", None)
    if health:
        extra["health"] = health
    else:
        extra.pop("health", None)
    _save_subscription_extra_data(subscription, extra)

    if subscription.status in {SubscriptionStatus.ERROR.value, SubscriptionStatus.INVALID.value}:
        subscription.status = SubscriptionStatus.ACTIVE.value
    subscription.error_message = None


def _mark_subscription_check_failure(subscription: Subscription, error_message: str) -> None:
    extra = _load_subscription_extra_data(subscription)
    health = extra.get("health") if isinstance(extra.get("health"), dict) else {}

    if _is_resource_failure(error_message):
        fail_count = int(health.get("resource_failure_count", 0) or 0) + 1
        health["resource_failure_count"] = fail_count
        health["last_resource_failure_at"] = datetime.now().isoformat(timespec="seconds")
        health["last_resource_failure_message"] = (error_message or "")[:500]
        logger.warning(f"订阅[{subscription.nickname}]资源类失败，第 {fail_count}/{RESOURCE_FAILURE_THRESHOLD} 次: {error_message}")

        if fail_count >= RESOURCE_FAILURE_THRESHOLD:
            subscription.status = SubscriptionStatus.INVALID.value
        elif subscription.status not in {SubscriptionStatus.PAUSED.value, SubscriptionStatus.INVALID.value}:
            subscription.status = SubscriptionStatus.ERROR.value
    elif subscription.status not in {SubscriptionStatus.PAUSED.value, SubscriptionStatus.INVALID.value}:
        subscription.status = SubscriptionStatus.ERROR.value

    extra["health"] = health
    _save_subscription_extra_data(subscription, extra)
    subscription.error_message = error_message

# 注意：由于 check_subscription_update 和 sync_videos 函数非常长（约1500行和1800行），
# 需要从原文件中完整复制这些函数的实现。
# 这里先创建框架，后续需要分批添加完整实现。

@router.post("/{subscription_id}/check", response_model=CheckUpdateResponse)
@require_license_api
async def check_subscription_update(
    subscription_id: str,
    db: Session = Depends(get_db),
    cleanup_page: bool = True,
    manual_refresh: bool = False
):
    """检查订阅更新，增量添加新发现的视频
    
    Args:
        subscription_id: 订阅ID
        db: 数据库会话
        cleanup_page: 是否清理页面
        manual_refresh: 是否为手动刷新，手动刷新时会同时更新博主信息（包括头像）
    """
    subscription = None
    try:
        # 1. 获取订阅信息
        subscription = db.query(Subscription).filter(
            Subscription.id == subscription_id
        ).first()
        
        if not subscription:
            return {
                "message": "未找到该订阅",
                "has_update": False,
                "new_videos_count": 0,
                "requires_sync": False
            }
        
        # 1.5. 检查是否正在同步视频，如果是则跳过检查更新（避免数据库连接冲突）
        if subscription.sync_status == "syncing":
            logger.info(f"订阅[{subscription.nickname}]正在同步视频，跳过自动检查更新")
            return {
                "message": "正在同步视频，跳过检查更新",
                "has_update": False,
                "new_videos_count": 0,
                "requires_sync": False
            }
        
        # 2. 检查数据库中是否有视频记录
        existing_videos_count = db.query(SubscriptionVideo).filter(
            SubscriptionVideo.subscription_id == subscription_id
        ).count()
        
        if existing_videos_count == 0:
            return {
                "message": "数据库中没有任何视频记录，请先点击'同步视频'获取视频列表，避免下载全部视频",
                "has_update": False,
                "new_videos_count": 0,
                "requires_sync": True
            }
            
        # 3. 更新检查时间和用户统计信息
        now = datetime.now()
        subscription.last_check = now
        
        # 手动刷新时更新博主信息（包括头像）
        # 自动定期检查时，对于 TikTok 平台也更新头像（相对轻量，不影响性能）
        if manual_refresh:  # 手动刷新时启用博主信息更新
            logger.info(f"手动刷新模式：将更新订阅[{subscription.nickname}]的博主信息（包括头像）")
            try:
                # 使用适配器更新用户信息
                adapter = registry.get_adapter(subscription.platform)
                if not adapter:
                    # 处理特殊平台名称
                    if subscription.platform == "douyin_collection":
                        adapter = registry.get_adapter("douyin")
                    elif subscription.platform == "youtube_playlist":
                        adapter = registry.get_adapter("youtube")
                    elif subscription.platform == "bilibili_collection":
                        adapter = registry.get_adapter("bilibili")
                
                if adapter:
                    # 使用适配器更新订阅信息
                    subscription_type_for_update = subscription.subscription_type
                    if subscription.platform == "douyin_collection" or subscription.platform == "bilibili_collection":
                        subscription_type_for_update = "collection"
                    elif subscription.platform == "youtube_playlist":
                        subscription_type_for_update = "playlist"
                    
                    # 对于抖音点赞列表，需要特殊处理
                    if subscription.platform == "douyin" and subscription.subscription_type == "favorite":
                        # 点赞列表订阅：获取当前登录用户信息
                        try:
                            async with unified_browser.task_context("douyin", "get_current_user_info"):
                                stats = await douyin_api.get_current_user_info()
                            # 检查返回的数据是否有效（返回 None 或没有 nickname 表示失败）
                            if stats and stats.get('nickname'):
                                nickname_locked = str(getattr(subscription, 'nickname_locked', 'false')).lower() == 'true'
                                if not nickname_locked:
                                    subscription.nickname = stats.get('nickname')
                                subscription.follower_count = stats.get('follower_count', 0)
                                subscription.following_count = stats.get('following_count', 0)
                                subscription.video_count = stats.get('video_count', 0)
                                subscription.like_count = stats.get('like_count', 0)
                                subscription.signature = stats.get('signature', '')
                                if stats.get('avatar_url'):
                                    subscription.avatar_url = stats.get('avatar_url')
                                subscription.last_sync_info = now
                                logger.debug(f"已更新点赞订阅[{subscription.nickname}]的用户信息")
                            else:
                                # 获取失败但不影响后续流程，仅记录调试信息（已由 get_current_user_info 记录警告）
                                logger.debug(f"获取点赞订阅用户信息失败，将使用已有缓存信息（不影响视频检查）")
                        except Exception as user_info_error:
                            # 获取用户信息失败不影响后续的视频检查流程
                            logger.warning(f"更新点赞订阅用户信息时出错: {str(user_info_error)}，将使用已有缓存信息")
                    elif subscription.platform == "youtube_playlist":
                        # 播放列表订阅：不需要更新统计信息
                        pass
                    else:
                        # 使用适配器更新信息
                        await adapter.update_subscription_info(
                            subscription,
                            subscription.user_id,
                            subscription_type_for_update
                        )
                        # 只要没抛出异常，就认为更新成功，设置同步时间
                        subscription.last_sync_info = now

                    # X 平台：强制刷新头像（避免适配器遗漏头像字段）
                    if subscription.platform == "x":
                        try:
                            from services import x_graphql
                            info = x_graphql.fetch_user_info(subscription.user_id)
                            if info:
                                nickname_locked = str(getattr(subscription, 'nickname_locked', 'false')).lower() == 'true'
                                if info.nickname and not nickname_locked:
                                    subscription.nickname = info.nickname
                                if info.avatar_url:
                                    subscription.avatar_url = info.avatar_url
                                if info.follower_count is not None:
                                    subscription.follower_count = info.follower_count
                                if info.following_count is not None:
                                    subscription.following_count = info.following_count
                                if info.video_count is not None:
                                    subscription.video_count = info.video_count
                                if info.signature is not None:
                                    subscription.signature = info.signature
                                subscription.last_sync_info = now
                                logger.info(f"X手动刷新：已更新头像={bool(info.avatar_url)} 昵称={info.nickname}")
                            else:
                                logger.warning("X手动刷新：未获取到用户信息")
                        except Exception as e:
                            logger.warning(f"X手动刷新获取用户信息失败: {e}")
                else:
                    logger.warning(f"未找到平台适配器: {subscription.platform}")
            except Exception as e:
                logger.warning(f"更新用户统计信息失败: {str(e)}")
        
        # 自动定期检查时，对于 TikTok 平台也更新头像（相对轻量，不影响性能）
        if not manual_refresh and subscription.platform == "tiktok":
            try:
                tiktok_adapter = registry.get_adapter("tiktok")
                if tiktok_adapter:
                    # 关键修复：get_user_info 期望的是 user_id，而不是生成的 profile_url
                    user_info = await tiktok_adapter.get_user_info(subscription.user_id)
                    if user_info and user_info.get('avatar_url'):
                        subscription.avatar_url = user_info.get('avatar_url')
                        subscription.last_sync_info = now
                        logger.debug(f"自动更新TikTok订阅[{subscription.nickname}]的头像")
            except Exception as _e:
                logger.warning(f"自动更新TikTok用户头像失败: {str(_e)}")
                
        db.commit()  # 立即提交更新
        
        # 【重要】在进行耗时的浏览器操作前，先提取所有需要的数据
        # 避免浏览器操作期间数据库连接处于 idle-in-transaction 状态
        platform = subscription.platform
        user_id = subscription.user_id
        subscription_type = subscription.subscription_type
        nickname = subscription.nickname
        youtube_tab_type = subscription.youtube_tab_type
        quality = subscription.quality
        auto_download = subscription.auto_download
        skip_bilibili_upower = getattr(subscription, 'skip_bilibili_upower', 'false') == 'true'
        
        # 3. 获取基准时间（上次记录的最新视频时间）
        last_video_time = subscription.latest_video_time or datetime.min
        # 确保基准时间是naive datetime
        if last_video_time.tzinfo is not None:
            last_video_time = last_video_time.replace(tzinfo=None)
        
        # 4. 获取新视频
        has_update = False
        
        # 初始化各平台的最新视频信息变量（函数级作用域，避免locals()检查失败）
        douyin_latest_video = None
        douyin_latest_publish_time = None
        douyin_collection_latest_video = None
        douyin_collection_latest_publish_time = None
        # 抖音点赞订阅可能会用到的 sec_user_id 缓存（必须函数级定义，避免 NameError）
        cached_sec_user_id = None
        current_latest_video = None
        current_latest_publish_time = None
        current_latest_video_id = None
        xhs_latest_video_data = None
        xhs_latest_publish_time = None
        netease_latest_video_data = None
        latest_video = None
        all_videos = []  # 初始化视频列表，确保所有代码路径都能使用
        
        # 使用平台适配器获取最新视频
        # 先处理特殊平台名称映射，再获取适配器
        platform_name = subscription.platform
        base_platform = platform_name
        
        if platform_name == "douyin_collection":
            # 抖音合集使用 douyin 适配器，但 subscription_type 为 collection
            base_platform = "douyin"
            subscription_type = "collection"
        elif platform_name == "youtube_playlist":
            # YouTube播放列表使用 youtube 适配器，但 subscription_type 为 playlist
            base_platform = "youtube"
            subscription_type = "playlist"
        elif platform_name == "bilibili_collection":
            # B站合集使用 bilibili 适配器，但 subscription_type 为 collection
            base_platform = "bilibili"
            subscription_type = "collection"
        
        # 使用映射后的基础平台名称获取适配器
        adapter = registry.get_adapter(base_platform)
        if not adapter:
            logger.error(f"未找到平台适配器: {base_platform} (原始平台: {subscription.platform})")
            return {
                "message": f"不支持的平台: {subscription.platform}",
                "has_update": False,
                "new_videos_count": 0,
                "requires_sync": False
            }
        else:
            subscription_type = subscription.subscription_type
        
        if subscription.platform == "douyin" or subscription.platform == "douyin_collection":
            # 抖音平台（包括合集）
            # 抖音点赞订阅：优先使用数据库缓存的 sec_user_id（存于 extra_data），减少对 /user/self 解析的依赖
            cached_sec_user_id = None
            if subscription.platform == "douyin" and subscription.subscription_type == "favorite":
                try:
                    extra = json.loads(subscription.extra_data or "{}")
                    cached_sec_user_id = extra.get("sec_user_id")
                except Exception:
                    cached_sec_user_id = None
            latest_videos_result = await adapter.get_latest_videos(
                subscription.user_id,
                subscription_type=subscription_type,
                max_count=20,
                latest_video_time=subscription.latest_video_time,
                latest_video_id=subscription.latest_video_id,
                sec_user_id=cached_sec_user_id
            )
            
            if not latest_videos_result or not latest_videos_result.get("videos"):
                adapter_error = latest_videos_result.get("error", "") if latest_videos_result else ""
                if adapter_error:
                    logger.error(f"抖音检测失败: {adapter_error}")
                    _mark_subscription_check_failure(subscription, f"抖音检测失败: {adapter_error}")
                    db.commit()
                    asyncio.create_task(send_subscription_check_notification(
                        subscription_id=subscription_id,
                        user_id=subscription.user_id,
                        nickname=subscription.nickname,
                        platform=subscription.platform,
                        success=False,
                        error_message=f"抖音检测失败: {adapter_error}"
                    ))
                    return {
                        "message": f"抖音检测失败: {adapter_error}",
                        "has_update": False,
                        "new_videos_count": 0,
                        "requires_sync": False,
                        "status": subscription.status,
                        "error_message": subscription.error_message
                    }
                logger.info("没有发现新视频")
                _mark_subscription_check_success(subscription)
                db.commit()
                return {
                    "message": "检查完成",
                    "has_update": False,
                    "new_videos_count": 0,
                    "requires_sync": False
                }
            
            videos_list = latest_videos_result.get("videos", [])
            
            if subscription.subscription_type == "favorite":
                # 点赞列表：基于视频ID检测
                latest_video = videos_list[0]
                latest_video_id = latest_video.get("aweme_id", "")
                has_update = not subscription.latest_video_id or latest_video_id != subscription.latest_video_id
                subscription.latest_video_id = latest_video_id
                subscription.latest_video_title = _truncate_video_title(latest_video.get("desc", ""))
                subscription.latest_video_cover = _safe_douyin_cover_url(latest_video)
                subscription.latest_video_time = datetime.fromtimestamp(int(latest_video.get("create_time", 0)))
                subscription.last_update = now
                
                # 补充：如果订阅的 extra_data 中还没有 sec_user_id，且本次检测成功，
                # 尝试从浏览器获取一次并缓存到数据库，后续可作为兜底使用
                try:
                    extra = json.loads(subscription.extra_data or "{}")
                except Exception:
                    extra = {}
                if not extra.get("sec_user_id"):
                    try:
                        sec_uid = await douyin_api.get_my_sec_user_id()
                        if sec_uid:
                            extra["sec_user_id"] = sec_uid
                            subscription.extra_data = json.dumps(extra)
                            logger.info(f"已为订阅[{subscription.nickname}]缓存 sec_user_id")
                    except Exception as e:
                        # 获取失败不影响本次检测，仅记录调试日志
                        logger.debug(f"检测更新时缓存 sec_user_id 失败: {str(e)}")
            elif subscription.platform == "douyin_collection":
                # 合集：基于发布时间检测
                latest_video = videos_list[0]
                latest_publish_time = datetime.fromtimestamp(int(latest_video.get("publish_time", 0)))
                has_update = (not subscription.latest_video_time) or (latest_publish_time > subscription.latest_video_time)
                douyin_collection_latest_video = latest_video
                douyin_collection_latest_publish_time = latest_publish_time
                
                # 若有更新，拉取增量视频
                if has_update:
                    all_videos = []
                    cursor = 0
                    has_more = True
                    page_count = 0
                    total_sleep_seconds = 0.0
                    while has_more:
                        page_count += 1
                        from routers.douyin import get_collection_videos
                        page = await get_collection_videos(subscription.user_id, cursor=cursor, count=50, with_meta=False)
                        items = page.get("videos", []) or []
                        items.sort(key=lambda x: int(x.get("publish_time", 0)), reverse=True)
                        for item in items:
                            ts = int(item.get("publish_time", 0) or 0)
                            item_dt = datetime.fromtimestamp(ts) if ts else datetime.min
                            if item_dt <= last_video_time:
                                has_more = False
                                break
                            all_videos.append(item)
                        has_more = has_more and bool(page.get("has_more"))
                        cursor = int(page.get("next_cursor", 0)) if has_more else cursor
                        if not has_more:
                            break
                        delay_seconds = _douyin_request_delay_seconds(page_count, mode="check")
                        total_sleep_seconds += delay_seconds
                        await asyncio.sleep(delay_seconds)
                    logger.info(
                        "[DouyinAntiRisk] 抖音合集检测分页完成: pages=%d induced_sleep=%.2fs",
                        page_count,
                        total_sleep_seconds,
                    )
            else:
                # 用户视频：基于发布时间检测
                videos_list.sort(key=lambda x: int(x.get("create_time", 0)), reverse=True)
                latest_video = videos_list[0]
                latest_publish_time = datetime.fromtimestamp(int(latest_video.get("create_time", 0)))
                has_update = not subscription.latest_video_time or latest_publish_time > subscription.latest_video_time
                douyin_latest_video = latest_video
                douyin_latest_publish_time = latest_publish_time
                
        elif subscription.platform == "douyin_collection":
            # 获取合集第一页（用于判定最新视频及是否有更新）
            from routers.douyin import get_collection_videos
            all_videos = []  # 初始化新视频列表
            page = await get_collection_videos(subscription.user_id, cursor=0, count=50, with_meta=False)
            videos_list = page.get("videos", [])
            # 将无发布时间的视频过滤掉
            videos_list = [v for v in videos_list if v.get("publish_time")]
            # 按发布时间降序
            videos_list.sort(key=lambda x: int(x.get("publish_time", 0)), reverse=True)
            if not videos_list:
                logger.info("没有发现新视频")
                _mark_subscription_check_success(subscription)
                db.commit()
                return {
                    "message": "检查完成",
                    "has_update": False,
                    "new_videos_count": 0,
                    "requires_sync": False
                }

            latest_video = videos_list[0]
            latest_publish_time = datetime.fromtimestamp(int(latest_video.get("publish_time", 0)))
            has_update = (not subscription.latest_video_time) or (latest_publish_time > subscription.latest_video_time)

            # 暂存最新信息，等视频入库成功后再更新
            douyin_collection_latest_video = latest_video
            douyin_collection_latest_publish_time = latest_publish_time

            # 若有更新，拉取增量视频（分页，直到遇到不大于 last_video_time 的视频）
            if has_update:
                cursor = 0
                has_more = True
                page_count = 0
                total_sleep_seconds = 0.0
                while has_more:
                    page_count += 1
                    page = await get_collection_videos(subscription.user_id, cursor=cursor, count=50, with_meta=False)
                    items = page.get("videos", []) or []
                    # 降序保证从新到旧
                    items.sort(key=lambda x: int(x.get("publish_time", 0)), reverse=True)
                    for item in items:
                        ts = int(item.get("publish_time", 0) or 0)
                        item_dt = datetime.fromtimestamp(ts) if ts else datetime.min
                        if item_dt <= last_video_time:
                            has_more = False
                            break
                        all_videos.append(item)
                    has_more = has_more and bool(page.get("has_more"))
                    cursor = int(page.get("next_cursor", 0)) if has_more else cursor
                    if not has_more:
                        break
                    delay_seconds = _douyin_request_delay_seconds(page_count, mode="check")
                    total_sleep_seconds += delay_seconds
                    await asyncio.sleep(delay_seconds)
                logger.info(
                    "[DouyinAntiRisk] 抖音合集检测分页完成: pages=%d induced_sleep=%.2fs",
                    page_count,
                    total_sleep_seconds,
                )

        elif subscription.platform == "youtube" or subscription.platform == "youtube_playlist":
            # YouTube平台（包括播放列表）
            youtube_adapter = registry.get_adapter("youtube")
            if not youtube_adapter:
                logger.error("未找到YouTube适配器")
                return {
                    "message": "不支持的平台",
                    "has_update": False,
                    "new_videos_count": 0,
                    "requires_sync": False
                }
            
            tab_type = subscription.youtube_tab_type or "videos" if subscription.platform == "youtube" else None
            latest_videos_result = await youtube_adapter.get_latest_videos(
                subscription.user_id,
                subscription_type="playlist" if subscription.platform == "youtube_playlist" else None,
                max_count=30,
                latest_video_id=subscription.latest_video_id,
                youtube_tab_type=tab_type
            )
            
            if not latest_videos_result or not latest_videos_result.get("videos"):
                adapter_error = latest_videos_result.get("error", "") if latest_videos_result else ""
                if adapter_error:
                    logger.error(f"YouTube检测失败: {adapter_error}")
                    _mark_subscription_check_failure(subscription, f"YouTube检测失败: {adapter_error}")
                    db.commit()
                    asyncio.create_task(send_subscription_check_notification(
                        subscription_id=subscription_id,
                        user_id=subscription.user_id,
                        nickname=subscription.nickname,
                        platform=subscription.platform,
                        success=False,
                        error_message=f"YouTube检测失败: {adapter_error}"
                    ))
                    return {
                        "message": f"YouTube检测失败: {adapter_error}",
                        "has_update": False,
                        "new_videos_count": 0,
                        "requires_sync": False,
                        "status": subscription.status,
                        "error_message": subscription.error_message
                    }
                tab_type_name = tab_type or "播放列表"
                logger.info(f"无法获取YouTube{tab_type_name}列表")
                return {
                    "message": f"无法获取{tab_type_name}列表",
                    "has_update": False,
                    "new_videos_count": 0,
                    "requires_sync": False
                }
            
            # 检查是否需要更新真实的频道ID（仅YouTube频道）
            if subscription.platform == "youtube":
                real_channel_id = latest_videos_result.get("real_channel_id")
                if real_channel_id and real_channel_id != subscription.user_id:
                    try:
                        old_user_id = subscription.user_id
                        subscription.user_id = real_channel_id
                        db.commit()
                        logger.info(f"✅ 已更新订阅 '{subscription.nickname}' 的频道ID: {old_user_id} → {real_channel_id}")
                    except Exception as e:
                        logger.error(f"❌ 更新订阅频道ID失败: {str(e)}")
                        db.rollback()
            
            # 获取最新内容信息
            videos_list = latest_videos_result.get("videos", [])
            latest_video = videos_list[0] if videos_list else None
            if not latest_video:
                return {
                    "message": "无法获取视频列表",
                    "has_update": False,
                    "new_videos_count": 0,
                    "requires_sync": False
                }
            
            latest_video_id = latest_video.get("id", {}).get("videoId", "")
            has_update = not subscription.latest_video_id or latest_video_id != subscription.latest_video_id
        
        elif subscription.platform == "tiktok":
            # TikTok平台
            tiktok_adapter = registry.get_adapter("tiktok")
            if not tiktok_adapter:
                logger.error("未找到TikTok适配器")
                return {
                    "message": "不支持的平台",
                    "has_update": False,
                    "new_videos_count": 0,
                    "requires_sync": False
                }
            
            try:
                # 1. 获取最新视频列表（增加数量以提高容错）
                latest_videos_result = await tiktok_adapter.get_latest_videos(
                    subscription.user_id,
                    max_count=30,
                    latest_video_id=subscription.latest_video_id
                )
                
                videos_list = latest_videos_result.get("videos", []) if latest_videos_result else []

                adapter_error = latest_videos_result.get("error", "") if latest_videos_result else ""
                if adapter_error:
                    logger.error(f"TikTok检测失败: {adapter_error}")
                    _mark_subscription_check_failure(subscription, f"TikTok检测失败: {adapter_error}")
                    db.commit()
                    asyncio.create_task(send_subscription_check_notification(
                        subscription_id=subscription_id,
                        user_id=subscription.user_id,
                        nickname=subscription.nickname,
                        platform=subscription.platform,
                        success=False,
                        error_message=f"TikTok检测失败: {adapter_error}"
                    ))
                    return {
                        "message": f"TikTok检测失败: {adapter_error}",
                        "has_update": False,
                        "new_videos_count": 0,
                        "requires_sync": False,
                        "status": subscription.status,
                        "error_message": subscription.error_message
                    }

                if not videos_list:
                    logger.info("无法获取TikTok视频列表或列表为空")
                    # 无更新
                    _mark_subscription_check_success(subscription)
                    db.commit()
                    return {
                        "message": "检查完成",
                        "has_update": False,
                        "new_videos_count": 0,
                        "requires_sync": False
                    }
                
                # 2. 获取数据库中已存在的视频ID集合
                existing_video_ids = set()
                existing_videos = db.query(SubscriptionVideo).filter(
                    SubscriptionVideo.subscription_id == subscription_id
                ).all()
                existing_video_ids = {v.video_id for v in existing_videos}
                logger.info(f"TikTok检测更新：数据库中已存在 {len(existing_video_ids)} 个视频")

                # 3. 收集所有新视频（ID不在数据库中的）
                all_videos = []
                for video in videos_list:
                    vid = video.get("video_id")
                    if vid and vid not in existing_video_ids:
                        all_videos.append(video)
                
                # 4. 判定是否有更新
                has_update = len(all_videos) > 0
                
                # 用于后续更新基准信息（取列表第一条作为最新状态）
                latest_video = videos_list[0]
                
                if has_update:
                     logger.info(f"TikTok检测到更新: 发现 {len(all_videos)} 个新视频")
                
            except Exception as e:
                logger.error(f"获取TikTok视频失败: {str(e)}")
                _mark_subscription_check_failure(subscription, str(e))
                db.commit()
                asyncio.create_task(send_subscription_check_notification(
                    subscription_id=subscription_id,
                    user_id=subscription.user_id,
                    nickname=subscription.nickname,
                    platform=subscription.platform,
                    success=False,
                    error_message=str(e)
                ))
                return {
                    "message": f"获取TikTok视频失败: {str(e)}",
                    "has_update": False,
                    "new_videos_count": 0,
                    "requires_sync": False
                }

        elif subscription.platform == "instagram":
            instagram_adapter = registry.get_adapter("instagram")
            if not instagram_adapter:
                logger.error("未找到Instagram适配器")
                return {
                    "message": "不支持的平台",
                    "has_update": False,
                    "new_videos_count": 0,
                    "requires_sync": False
                }

            try:
                # 获取已存在的视频ID集合，用于分页检测的停止条件
                existing_videos = db.query(SubscriptionVideo).filter(
                    SubscriptionVideo.subscription_id == subscription_id
                ).all()
                existing_video_ids = {v.video_id for v in existing_videos}
                logger.info(f"Instagram检测更新：数据库中已存在 {len(existing_video_ids)} 个媒体")

                # 分页拉取博主媒体，每页逐条比对，遇到已存在的 video_id 就停止
                resolved_user_id = await instagram_api.get_user_id(subscription.user_id)
                end_cursor = ""
                all_videos = []
                first_item = None
                page_count = 0

                while True:
                    page_count += 1
                    page = await instagram_api.get_user_medias_page(
                        resolved_user_id, count=50, end_cursor=end_cursor
                    )
                    items = page.get("items", []) or []
                    end_cursor = page.get("next_cursor") or ""

                    if not items:
                        break

                    found_existing = False
                    for item in items:
                        normalized = instagram_adapter.normalize_video_data(item, "user")
                        media_id = str(normalized.get("video_id") or "")

                        if first_item is None:
                            first_item = item

                        # 碰到已入库的 ID，说明已经追上新帖边界，停止翻页
                        if media_id and media_id in existing_video_ids:
                            found_existing = True
                            break

                        if media_id and media_id not in existing_video_ids:
                            all_videos.append(item)

                    if found_existing:
                        logger.info(f"Instagram分页检测: 第{page_count}页遇到已存在的视频，停止翻页")
                        break
                    if not end_cursor:
                        logger.info(f"Instagram分页检测: 第{page_count}页已翻完所有帖子")
                        break

                    await asyncio.sleep(1)

                if not first_item:
                    # 博主没有任何帖子
                    logger.info("Instagram媒体列表为空")
                    _mark_subscription_check_success(subscription)
                    db.commit()
                    return {
                        "message": "检查完成",
                        "has_update": False,
                        "new_videos_count": 0,
                        "requires_sync": False,
                        "status": subscription.status,
                        "error_message": subscription.error_message
                    }

                has_update = len(all_videos) > 0
                latest_video = first_item
                videos_list = [first_item]

                if has_update:
                    logger.info(f"Instagram检测到更新: 共翻{page_count}页, 发现 {len(all_videos)} 个新媒体")

            except Exception as e:
                logger.error(f"获取Instagram媒体失败: {str(e)}")
                _mark_subscription_check_failure(subscription, str(e))
                db.commit()
                asyncio.create_task(send_subscription_check_notification(
                    subscription_id=subscription_id,
                    user_id=subscription.user_id,
                    nickname=subscription.nickname,
                    platform=subscription.platform,
                    success=False,
                    error_message=str(e)
                ))
                return {
                    "message": f"获取Instagram媒体失败: {str(e)}",
                    "has_update": False,
                    "new_videos_count": 0,
                    "requires_sync": False,
                    "status": subscription.status,
                    "error_message": subscription.error_message
                }

        elif subscription.platform == "x":
            x_adapter = registry.get_adapter("x")
            if not x_adapter:
                logger.error("未找到X适配器")
                return {
                    "message": "不支持的平台",
                    "has_update": False,
                    "new_videos_count": 0,
                    "requires_sync": False
                }

            try:
                # X 点赞列表顺序不稳定：扩大抓取范围，并限制页数，直到命中 latest_video_id
                max_count = 800 if subscription.latest_video_id else 200
                max_pages = 8 if subscription.latest_video_id else 3
                latest_videos_result = await x_adapter.get_latest_videos(
                    subscription.user_id,
                    subscription_type="favorite",
                    max_count=max_count,
                    latest_video_id=subscription.latest_video_id,
                    max_pages=max_pages
                )
                videos_list = latest_videos_result.get("videos", []) if latest_videos_result else []

                adapter_error = latest_videos_result.get("error", "") if latest_videos_result else ""
                if adapter_error:
                    logger.error(f"X检测失败: {adapter_error}")
                    _mark_subscription_check_failure(subscription, f"X检测失败: {adapter_error}")
                    db.commit()
                    asyncio.create_task(send_subscription_check_notification(
                        subscription_id=subscription_id,
                        user_id=subscription.user_id,
                        nickname=subscription.nickname,
                        platform=subscription.platform,
                        success=False,
                        error_message=f"X检测失败: {adapter_error}"
                    ))
                    return {
                        "message": f"X检测失败: {adapter_error}",
                        "has_update": False,
                        "new_videos_count": 0,
                        "requires_sync": False,
                        "status": subscription.status,
                        "error_message": subscription.error_message
                    }

                if not videos_list:
                    # stop_at_id 命中时可能返回空列表，这种情况应视为“无新增”，而不是失败
                    if subscription.latest_video_id:
                        logger.info("X点赞检查：未发现新增（可能已命中最新ID）")
                    else:
                        logger.info("无法获取X点赞列表或列表为空")

                    # 头像兜底：优先用已记录的 latest_video_cover，否则用数据库中最新视频封面
                    if not subscription.avatar_url:
                        if subscription.latest_video_cover:
                            subscription.avatar_url = subscription.latest_video_cover
                        else:
                            latest_video_db = db.query(SubscriptionVideo).filter(
                                SubscriptionVideo.subscription_id == subscription_id
                            ).order_by(
                                SubscriptionVideo.publish_time.desc(),
                                SubscriptionVideo.created_at.desc()
                            ).first()
                            if latest_video_db and latest_video_db.cover_url:
                                subscription.avatar_url = latest_video_db.cover_url

                    _mark_subscription_check_success(subscription)
                    db.commit()
                    return {
                        "message": "检查完成",
                        "has_update": False,
                        "new_videos_count": 0,
                        "requires_sync": False
                    }

                # 如果设置了 latest_video_id，但在拉取范围内未命中，提示可能仍有漏抓风险
                if subscription.latest_video_id:
                    found_latest = any(
                        v.get("video_id") == subscription.latest_video_id for v in videos_list
                    )
                    if not found_latest and len(videos_list) >= max_count:
                        logger.warning(
                            "X点赞检查：未在 %s 条内命中 latest_video_id，可能存在漏抓风险 (latest_video_id=%s)",
                            max_count,
                            subscription.latest_video_id
                        )

                existing_video_ids = set()
                existing_videos = db.query(SubscriptionVideo).filter(
                    SubscriptionVideo.subscription_id == subscription_id
                ).all()
                existing_video_ids = {v.video_id for v in existing_videos}
                logger.info(f"X点赞检测更新：数据库中已存在 {len(existing_video_ids)} 个视频")

                all_videos = []
                for video in videos_list:
                    vid = video.get("video_id")
                    if vid and vid not in existing_video_ids:
                        all_videos.append(video)

                has_update = len(all_videos) > 0
                latest_video = videos_list[0]
                if latest_video:
                    cover = latest_video.get("cover_url")
                    if cover:
                        subscription.avatar_url = cover
                        logger.info(f"X检测更新：已更新头像 cover_url={cover}")
                if has_update:
                    logger.info(f"X点赞检测到更新: 发现 {len(all_videos)} 个新视频")
            except Exception as e:
                logger.error(f"获取X点赞失败: {str(e)}")
                _mark_subscription_check_failure(subscription, str(e))
                db.commit()
                asyncio.create_task(send_subscription_check_notification(
                    subscription_id=subscription_id,
                    user_id=subscription.user_id,
                    nickname=subscription.nickname,
                    platform=subscription.platform,
                    success=False,
                    error_message=str(e)
                ))
                return {
                    "message": f"获取X点赞失败: {str(e)}",
                    "has_update": False,
                    "new_videos_count": 0,
                    "requires_sync": False
                }
        
        elif subscription.platform == "netease":
            # 网易云歌单：基于歌曲ID做增量检测
            netease_adapter = registry.get_adapter("netease")
            if not netease_adapter:
                logger.error("未找到网易云适配器")
                return {
                    "message": "不支持的平台",
                    "has_update": False,
                    "new_videos_count": 0,
                    "requires_sync": False
                }

            try:
                latest_videos_result = await netease_adapter.get_latest_videos(
                    subscription.user_id,
                    subscription_type="playlist",
                    max_count=100,
                    latest_video_id=subscription.latest_video_id
                )
                videos_list = latest_videos_result.get("videos", []) if latest_videos_result else []

                adapter_error = latest_videos_result.get("error", "") if latest_videos_result else ""
                if adapter_error:
                    logger.error(f"网易云检测失败: {adapter_error}")
                    _mark_subscription_check_failure(subscription, f"网易云检测失败: {adapter_error}")
                    db.commit()
                    asyncio.create_task(send_subscription_check_notification(
                        subscription_id=subscription_id,
                        user_id=subscription.user_id,
                        nickname=subscription.nickname,
                        platform=subscription.platform,
                        success=False,
                        error_message=f"网易云检测失败: {adapter_error}"
                    ))
                    return {
                        "message": f"网易云检测失败: {adapter_error}",
                        "has_update": False,
                        "new_videos_count": 0,
                        "requires_sync": False,
                        "status": subscription.status,
                        "error_message": subscription.error_message
                    }

                if not videos_list:
                    logger.info("无法获取网易云歌单歌曲列表或列表为空")
                    _mark_subscription_check_success(subscription)
                    db.commit()
                    return {
                        "message": "检查完成",
                        "has_update": False,
                        "new_videos_count": 0,
                        "requires_sync": False
                    }

                # 记录当前最新歌曲（用于更新基准）
                netease_latest_video_data = netease_adapter.normalize_video_data(videos_list[0], "playlist")
                latest_video = videos_list[0]

                # 读取数据库已存在歌曲ID
                existing_videos = db.query(SubscriptionVideo).filter(
                    SubscriptionVideo.subscription_id == subscription_id
                ).all()
                existing_video_ids = {v.video_id for v in existing_videos}
                logger.info(f"网易云检测更新：数据库中已存在 {len(existing_video_ids)} 首歌曲")

                # 过滤新增歌曲（ID不在库中）
                all_videos = []
                for song in videos_list:
                    normalized_song = netease_adapter.normalize_video_data(song, "playlist")
                    song_id = str(normalized_song.get("video_id") or "")
                    if song_id and song_id not in existing_video_ids:
                        all_videos.append(song)

                latest_song_id = str(netease_latest_video_data.get("video_id") or "")
                has_update = (
                    (latest_song_id and latest_song_id != str(subscription.latest_video_id or ""))
                    or len(all_videos) > 0
                )

                if has_update:
                    logger.info(f"网易云检测到更新: 发现 {len(all_videos)} 首新歌曲")

            except Exception as e:
                logger.error(f"获取网易云歌单歌曲失败: {str(e)}")
                _mark_subscription_check_failure(subscription, str(e))
                db.commit()
                asyncio.create_task(send_subscription_check_notification(
                    subscription_id=subscription_id,
                    user_id=subscription.user_id,
                    nickname=subscription.nickname,
                    platform=subscription.platform,
                    success=False,
                    error_message=str(e)
                ))
                return {
                    "message": f"获取网易云歌单歌曲失败: {str(e)}",
                    "has_update": False,
                    "new_videos_count": 0,
                    "requires_sync": False
                }

        elif subscription.platform == "xiaohongshu":
            # 小红书订阅：通过适配器 + 带 xsec_token 的主页链接获取最新笔记
            xhs_adapter = registry.get_adapter("xiaohongshu")
            if not xhs_adapter:
                logger.error("未找到小红书适配器")
                return {
                    "message": "不支持的平台",
                    "has_update": False,
                    "new_videos_count": 0,
                    "requires_sync": False
                }

            profile_url_for_api = subscription.profile_url
            if not profile_url_for_api or "xsec_token" not in (profile_url_for_api or ""):
                # 旧订阅可能没有保存完整链接，提示用户删除后用带 xsec_token 的主页链接重新添加
                error_msg = "小红书订阅缺少带 xsec_token 的创作者主页链接，请删除该订阅后，从浏览器地址栏复制完整链接重新添加。"
                logger.warning(f"{error_msg} subscription_id={subscription_id}, user_id={subscription.user_id}")
                _mark_subscription_check_failure(subscription, error_msg)
                subscription.last_check = now
                db.commit()
                asyncio.create_task(send_subscription_check_notification(
                    subscription_id=subscription_id,
                    user_id=subscription.user_id,
                    nickname=subscription.nickname,
                    platform=subscription.platform,
                    success=False,
                    error_message=error_msg
                ))
                return {
                    "message": error_msg,
                    "has_update": False,
                    "new_videos_count": 0,
                    "requires_sync": False
                }

            try:
                async with unified_browser.task_context("xiaohongshu", "check_update"):
                    latest_videos_result = await xhs_adapter.get_latest_videos(
                        subscription.user_id,
                        subscription_type="user",
                        max_count=30,
                        profile_url=profile_url_for_api,
                    )

                notes = latest_videos_result.get("videos", []) if latest_videos_result else []

                adapter_error = latest_videos_result.get("error", "") if latest_videos_result else ""
                if adapter_error:
                    logger.error(f"小红书检测失败: {adapter_error}")
                    _mark_subscription_check_failure(subscription, f"小红书检测失败: {adapter_error}")
                    db.commit()
                    asyncio.create_task(send_subscription_check_notification(
                        subscription_id=subscription_id,
                        user_id=subscription.user_id,
                        nickname=subscription.nickname,
                        platform=subscription.platform,
                        success=False,
                        error_message=f"小红书检测失败: {adapter_error}"
                    ))
                    return {
                        "message": f"小红书检测失败: {adapter_error}",
                        "has_update": False,
                        "new_videos_count": 0,
                        "requires_sync": False,
                        "status": subscription.status,
                        "error_message": subscription.error_message
                    }

                logger.info(
                    "[XhsAntiRisk] 小红书检测拉取完成: notes=%d max_count=%d",
                    len(notes),
                    30,
                )
                if not notes:
                    logger.info(f"小红书订阅 {subscription.nickname} 无法获取笔记列表或无新笔记")
                    latest_video = None
                    has_update = False
                else:
                    # 🚀 优化逻辑：参考抖音，先按时间排序排除置顶干扰
                    # 1. 解析所有笔记的时间
                    parsed_notes = []
                    normalized_notes = []
                    for note in notes:
                        # 归一化以获取标准时间和标准ID
                        normalized = xhs_adapter.normalize_video_data(note, "user")
                        normalized_notes.append((note, normalized))
                        pt = normalized.get("publish_time")
                        if isinstance(pt, datetime):
                            parsed_notes.append((note, normalized, pt))
                    
                    # 获取数据库中已存在的视频ID集合（无论是否有时间，都要先算出来）
                    existing_videos = db.query(SubscriptionVideo).filter(
                        SubscriptionVideo.subscription_id == subscription_id
                    ).all()
                    existing_video_ids = {v.video_id for v in existing_videos}
                    logger.info(f"小红书检测更新：数据库中已存在 {len(existing_video_ids)} 个视频")

                    if parsed_notes:
                        # 2a. 有有效时间：按发布时间降序排序 (用于确定最新视频信息)，同时做 ID 比较
                        parsed_notes.sort(key=lambda x: x[2], reverse=True)
                        
                        # 取出真正最新的笔记（第一条）
                        latest_note_tuple = parsed_notes[0]
                        latest_note = latest_note_tuple[0]
                        xhs_latest_video_data = latest_note_tuple[1]
                        xhs_latest_publish_time = latest_note_tuple[2]
                        
                        # 收集所有新视频（ID不在数据库中的）
                        all_videos = []
                        for note, normalized, pt in parsed_notes:
                            vid = normalized.get("video_id")
                            if vid and vid not in existing_video_ids:
                                all_videos.append(note)
                    else:
                        # 2b. 没有任何时间信息（当前小红书接口常态）：退化为纯 ID 检测，按接口原始顺序处理
                        all_videos = []
                        latest_note = None
                        xhs_latest_video_data = None
                        xhs_latest_publish_time = None

                        for idx, (note, normalized) in enumerate(normalized_notes):
                            vid = normalized.get("video_id")
                            if not vid:
                                continue
                            if latest_note is None:
                                # 将列表中的第一条视为“最新”，并记录其标准化数据
                                latest_note = note
                                xhs_latest_video_data = normalized
                                # 没有真实发布时间，用当前时间作为展示用的近似时间
                                xhs_latest_publish_time = datetime.now()
                            if vid not in existing_video_ids:
                                all_videos.append(note)
                        
                        # 用于显示
                        latest_video = latest_note
                        
                    # 只要有不在库中的视频，就视为有更新
                    has_update = len(all_videos) > 0

                    if has_update:
                        logger.info(f"小红书检测到更新: 发现 {len(all_videos)} 个新视频")

            except Exception as e:
                logger.error(f"获取小红书笔记失败: {str(e)}")
                _mark_subscription_check_failure(subscription, str(e))
                subscription.last_check = now
                db.commit()
                asyncio.create_task(send_subscription_check_notification(
                    subscription_id=subscription_id,
                    user_id=subscription.user_id,
                    nickname=subscription.nickname,
                    platform=subscription.platform,
                    success=False,
                    error_message=str(e)
                ))
                return {
                    "message": f"获取小红书笔记失败: {str(e)}",
                    "has_update": False,
                    "new_videos_count": 0,
                    "requires_sync": False
                }
        
        elif subscription.platform == "bilibili" and subscription.subscription_type == "favorite":
            # B站收藏夹增量检查逻辑（基于ID比较，更准确）
            # 注意：收藏夹有特殊处理逻辑（需要获取详细信息），保持原有实现但使用适配器基础功能
            bilibili_adapter = registry.get_adapter("bilibili")
            if not bilibili_adapter:
                logger.error("未找到B站适配器")
                return {
                    "message": "不支持的平台",
                    "has_update": False,
                    "new_videos_count": 0,
                    "requires_sync": False
                }
            
            try:
                # 使用适配器获取收藏夹信息
                fav_info = await bilibili_adapter.get_user_info(subscription.user_id, "favorite")
                if fav_info:
                    subscription.video_count = fav_info.get("video_count", 0)
                
                # 获取数据库中已存在的视频ID集合
                existing_video_ids = set()
                existing_videos = db.query(SubscriptionVideo).filter(
                    SubscriptionVideo.subscription_id == subscription_id
                ).all()
                existing_video_ids = {v.video_id for v in existing_videos}
                logger.info(f"B站收藏夹检测更新：数据库中已存在 {len(existing_video_ids)} 个视频")
                
                # 使用适配器获取最新视频
                latest_videos_result = await bilibili_adapter.get_latest_videos(
                    subscription.user_id,
                    subscription_type="favorite",
                    max_count=50,
                    latest_video_id=subscription.latest_video_id
                )
                
                all_fav_videos = latest_videos_result.get("videos", []) if latest_videos_result else []
                
                # 通过ID比较找出新视频
                new_videos = []
                for video in all_fav_videos:
                    video_id = video.get("video_id", "")
                    if video_id and video_id not in existing_video_ids:
                        new_videos.append(video)
                
                # 转换为统一格式，如果cover_url为空，尝试获取详细信息
                latest_videos = []
                detail_fetch_count = 0
                detail_fetch_sleep_total = 0.0
                for video in new_videos:
                    cover_url = video.get("cover_url", "")
                    publish_time = video.get("publish_time", "")
                    
                    # 如果缩略图为空，尝试获取详细信息
                    if not cover_url:
                        try:
                            import yt_dlp
                            import os
                            video_url = video.get("url", "")
                            cookies_path = "/app/database/cookie/bilibili_cookie.txt"
                            if video_url:
                                detail_fetch_count += 1
                                if detail_fetch_count > 1:
                                    delay_seconds = _bilibili_detail_delay_seconds(detail_fetch_count)
                                    detail_fetch_sleep_total += delay_seconds
                                    await asyncio.sleep(delay_seconds)
                                ydl_opts = {
                                    "quiet": True,
                                    "no_warnings": True,
                                    "extract_flat": False,
                                    "socket_timeout": 30,
                                    "retries": 2,
                                }
                                if cookies_path and os.path.exists(cookies_path):
                                    ydl_opts["cookiefile"] = cookies_path
                                
                                def _extract_video_info():
                                    try:
                                        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                                            return ydl.extract_info(video_url, download=False)
                                    except Exception as e:
                                        raise ValueError(f"yt-dlp提取失败: {str(e)}")
                                
                                loop = asyncio.get_event_loop()
                                video_info = await loop.run_in_executor(None, _extract_video_info)
                                
                                if video_info:
                                    cover_url = video_info.get("thumbnail", "")
                                    if not cover_url and isinstance(video_info.get("thumbnails"), list) and video_info.get("thumbnails"):
                                        cover_url = video_info.get("thumbnails", [{}])[0].get("url", "")
                                    
                                    if not publish_time:
                                        upload_date = video_info.get("upload_date", "")
                                        if upload_date and len(upload_date) == 8:
                                            try:
                                                formatted_date = f"{upload_date[:4]}-{upload_date[4:6]}-{upload_date[6:8]}"
                                                publish_time = datetime.strptime(formatted_date, "%Y-%m-%d").isoformat() + "+00:00"
                                            except:
                                                pass
                        except Exception as e:
                            logger.debug(f"获取视频详细信息失败（视频ID: {video.get('video_id', '')}）: {str(e)}")
                    
                    latest_videos.append({
                        "video_id": video.get("video_id", ""),
                        "title": video.get("title", ""),
                        "url": video.get("url", ""),
                        "cover_url": cover_url,
                        "publish_time": publish_time,
                    })
                if detail_fetch_count > 1:
                    logger.info(
                        "[BilibiliAntiRisk] 收藏夹详情补全节流: fetch_count=%d induced_sleep=%.2fs",
                        detail_fetch_count,
                        detail_fetch_sleep_total,
                    )
                
                if latest_videos:
                    new_count = len(latest_videos)
                    current_video_count = subscription.video_count
                    logger.info(f"B站收藏夹 {subscription.nickname} 发现 {new_count} 个新视频 (当前收藏夹: {current_video_count}, 已存: {len(existing_video_ids)})")
                    has_update = True
                else:
                    logger.info(f"B站收藏夹 {subscription.nickname} 无新视频 (当前收藏夹: {subscription.video_count}, 已存: {len(existing_video_ids)})")
                    has_update = False
                    latest_videos = []
                    
                    _mark_subscription_check_success(subscription)
                    subscription.last_check = now
                    subscription.last_update = now
                    db.commit()
                    
                    try:
                        asyncio.create_task(send_subscription_check_notification(
                            subscription_id=subscription_id,
                            user_id=subscription.user_id,
                            nickname=subscription.nickname,
                            platform=subscription.platform,
                            success=True,
                            new_videos_count=0
                        ))
                    except Exception as _notify_err:
                        logger.warning(f"触发B站收藏夹无新视频通知失败: {str(_notify_err)}")
                    
                    return {
                        "message": "检查完成",
                        "has_update": False,
                        "new_videos_count": 0,
                        "requires_sync": False
                    }
                    
            except Exception as e:
                logger.error(f"B站收藏夹检查更新失败: {str(e)}")
                _mark_subscription_check_failure(subscription, str(e))
                subscription.last_check = now
                db.commit()
                raise HTTPException(status_code=500, detail=f"检查收藏夹更新失败: {str(e)}")
        
        elif subscription.platform == "bilibili" or subscription.platform == "bilibili_collection":
            # B站平台（UP主、收藏夹、合集）
            bilibili_adapter = registry.get_adapter("bilibili")
            if not bilibili_adapter:
                logger.error("未找到B站适配器")
                return {
                    "message": "不支持的平台",
                    "has_update": False,
                    "new_videos_count": 0,
                    "requires_sync": False
                }
            
            # 定义进度回调函数
            async def bilibili_check_progress_callback(progress_data):
                """B站检查更新进度回调"""
                try:
                    if progress_data.get("type") == "check_progress":
                        message = progress_data.get("message", "")
                        current = progress_data.get("current", 0)
                        total = progress_data.get("total", 0)
                        await send_progress_update(subscription_id, {
                            "type": "check_progress",
                            "status": "checking",
                            "message": message,
                            "current": current,
                            "total": total
                        })
                except Exception as e:
                    logger.warning(f"发送B站检查进度更新失败: {str(e)}")
            
            # 处理合集特殊逻辑：提取页码
            latest_page = None
            if subscription.platform == "bilibili_collection" and subscription.latest_video_id:
                page_match = re.search(r'_p(\d+)$', subscription.latest_video_id)
                if page_match:
                    latest_page = int(page_match.group(1))
            
            # 使用适配器获取最新视频
            latest_videos_result = await bilibili_adapter.get_latest_videos(
                subscription.user_id,
                subscription_type=subscription.subscription_type if subscription.platform == "bilibili" else "collection",
                max_count=50,
                latest_video_time=subscription.latest_video_time,
                latest_video_id=subscription.latest_video_id,
                latest_page=latest_page
            )
            
            latest_videos = latest_videos_result.get("videos", []) if latest_videos_result else []

            # 检测B站API是否返回错误（如登录失效、风控拦截）
            adapter_error = latest_videos_result.get("error", "") if latest_videos_result else ""
            if adapter_error:
                logger.error(f"B站检测失败: {adapter_error}")
                _mark_subscription_check_failure(subscription, f"B站检测失败: {adapter_error}")
                db.commit()
                asyncio.create_task(send_subscription_check_notification(
                    subscription_id=subscription_id,
                    user_id=subscription.user_id,
                    nickname=subscription.nickname,
                    platform=subscription.platform,
                    success=False,
                    error_message=f"B站检测失败: {adapter_error}"
                ))
                return {
                    "message": f"B站检测失败: {adapter_error}",
                    "has_update": False,
                    "new_videos_count": 0,
                    "requires_sync": False,
                    "status": subscription.status,
                    "error_message": subscription.error_message
                }

            # 获取最新视频信息（用于后续更新基准时间）
            current_latest_video = None
            current_latest_publish_time = None
            current_latest_video_id = None
            
            if subscription.platform == "bilibili" and subscription.subscription_type != "favorite":
                # UP主：获取最新视频信息
                try:
                    from routers.bilibili import bilibili_api
                    current_latest_videos = await bilibili_api.get_up_videos_queued(
                        subscription.user_id,
                        max_count=5,
                        progress_callback=None
                    )
                    if current_latest_videos:
                        current_latest_video = current_latest_videos[0]
                        current_latest_publish_time = datetime.fromisoformat(current_latest_video.get("publish_time_parsed", ""))
                        current_latest_video_id = current_latest_video.get("video_id", "")
                        logger.info(f"B站最新视频: {current_latest_video.get('title', '')} (发布时间: {current_latest_publish_time})")
                except Exception as e:
                    logger.warning(f"获取B站UP主最新视频信息失败: {str(e)}")
            elif subscription.platform == "bilibili_collection":
                # 合集：获取最新视频信息
                try:
                    from routers.bilibili import bilibili_api
                    current_latest_videos = await bilibili_api.get_collection_videos_queued(
                        subscription.user_id,
                        max_count=5,
                        progress_callback=None
                    )
                    if current_latest_videos:
                        current_latest_video = current_latest_videos[0]
                        current_latest_publish_time = datetime.fromisoformat(current_latest_video.get("publish_time", ""))
                        current_latest_video_id = current_latest_video.get("video_id", "")
                        logger.info(f"B站合集最新视频: {current_latest_video.get('title', '')} (页码: {current_latest_video.get('page', 1)})")
                except Exception as e:
                    logger.warning(f"获取B站合集最新视频信息失败: {str(e)}")
            
            if not latest_videos:
                logger.info("没有发现新视频")
                _mark_subscription_check_success(subscription)
                subscription.last_update = now
                db.commit()
                
                try:
                    asyncio.create_task(send_subscription_check_notification(
                        subscription_id=subscription_id,
                        user_id=subscription.user_id,
                        nickname=subscription.nickname,
                        platform=subscription.platform,
                        success=True,
                        new_videos_count=0
                    ))
                except Exception as _notify_err:
                    logger.warning(f"触发B站无新视频通知失败: {str(_notify_err)}")
                
                if cleanup_page:
                    try:
                        await _cleanup_subscription_pages(subscription.platform, subscription.user_id)
                    except Exception as e:
                        logger.debug(f"清理标签页失败: {str(e)}")
                
                return {
                    "message": "检查完成",
                    "has_update": False,
                    "new_videos_count": 0,
                    "requires_sync": False
                }
            
            # 有新视频，设置更新标志
            has_update = True
        
        # 获取所有新视频
        # 注意：抖音合集订阅在检测阶段已经获取了新视频到all_videos，这里需要保留
        if subscription.platform != "douyin_collection" and subscription.platform != "xiaohongshu" and subscription.platform != "tiktok" and subscription.platform != "netease" and subscription.platform != "x" and subscription.platform != "instagram":
            all_videos = []
        
        if subscription.platform == "douyin":
            # 只有在有更新时才获取新视频
            if has_update:
                if subscription.subscription_type == "favorite":
                    # 点赞订阅：获取数据库中已存在的视频ID集合
                    existing_video_ids = set()
                    existing_videos = db.query(SubscriptionVideo).filter(
                        SubscriptionVideo.subscription_id == subscription_id
                    ).all()
                    existing_video_ids = {v.video_id for v in existing_videos}
                    logger.info(f"抖音点赞检测更新：数据库中已存在 {len(existing_video_ids)} 个视频")

                    # 优化：使用增量分页逻辑，直到遇到已存在的视频
                    all_videos = []
                    
                    # 使用task_context防止浏览器被空闲超时关闭
                    async with unified_browser.task_context("douyin", "check_favorite_update"):
                        max_cursor = 0
                        empty_page_count = 0
                        max_empty_pages = 5
                        should_continue = True
                        page_count = 0
                        total_sleep_seconds = 0.0
                        
                        while should_continue:
                            page_count += 1
                            # 获取一页视频
                            page_result = await douyin_api.get_favorite_videos(
                                max_count=20,  # 单页数量，多次请求以覆盖更多
                                max_cursor=max_cursor,
                                sec_user_id=cached_sec_user_id
                            )
                            
                            if not page_result:
                                break
                                
                            videos = page_result.get("aweme_list", [])
                            has_more = page_result.get("has_more", False)
                            max_cursor = page_result.get("max_cursor", 0)
                            
                            if not videos:
                                empty_page_count += 1
                                if empty_page_count >= max_empty_pages:
                                    logger.info(f"连续 {max_empty_pages} 次获取空页面，停止分页")
                                    break
                            else:
                                empty_page_count = 0
                                # 检查是否有与数据库重复的视频
                                page_new_videos = []
                                for video in videos:
                                    video_id = video.get("aweme_id", "")
                                    if video_id in existing_video_ids:
                                        # 遇到已存在的视频，说明后续的都是旧的，停止分页
                                        should_continue = False
                                        logger.info(f"遇到已存在的视频 {video_id}，停止点赞列表分页") 
                                        break
                                    page_new_videos.append(video)
                                
                                all_videos.extend(page_new_videos)
                                logger.debug(f"当前页新增 {len(page_new_videos)} 个潜在新视频 (累计: {len(all_videos)})")
                                
                            if not has_more or not should_continue:
                                break
                                
                            # 避免请求过快
                            delay_seconds = _douyin_request_delay_seconds(page_count, mode="check")
                            total_sleep_seconds += delay_seconds
                            await asyncio.sleep(delay_seconds)

                    logger.info(
                        "[DouyinAntiRisk] 抖音点赞检测分页完成: pages=%d induced_sleep=%.2fs new_candidates=%d",
                        page_count,
                        total_sleep_seconds,
                        len(all_videos),
                    )

                    total_items = len(all_videos) + len(existing_video_ids) # 近似总数
                    new_items = len(all_videos)
                    existing_items = len(existing_video_ids)
                    logger.info(f"抖音点赞检查更新-分页处理结束: 发现新视频 {new_items} 个")
                else:
                    # 普通用户视频订阅（使用task_context防止浏览器被空闲超时关闭）
                    async with unified_browser.task_context("douyin", "check_user_update"):
                        max_cursor = 0
                        empty_page_count = 0
                        max_empty_pages = 5
                        page_count = 0
                        total_sleep_seconds = 0.0
                        
                        should_continue = True
                        while should_continue:
                            page_count += 1
                            page_videos = await douyin_api.get_user_videos(
                                subscription.user_id,
                                max_cursor=max_cursor
                            )
                            
                            if not page_videos:
                                break
                            
                            # 获取分页信息
                            has_more = page_videos.get("has_more", False)
                            max_cursor = page_videos.get("max_cursor", 0)
                            videos = page_videos.get("aweme_list", [])
                            
                            if videos:
                                empty_page_count = 0
                                # 按发布时间排序当前页的视频
                                videos.sort(key=lambda x: int(x.get("create_time", 0)), reverse=True)
                                
                                # 检查是否已经获取到所有新视频
                                page_new_count = 0
                                for video in videos:
                                    video_time = datetime.fromtimestamp(int(video.get("create_time", 0)))
                                    if video_time <= last_video_time:
                                        # 遇到旧视频，停止整个分页循环
                                        logger.info(f"遇到基准时间之前的视频，停止分页: {video_time} <= {last_video_time}")
                                        should_continue = False
                                        break
                                    all_videos.append(video)
                                    page_new_count += 1
                                
                                if page_new_count > 0:
                                    logger.info(f"当前页获取到 {page_new_count} 个新视频，总计 {len(all_videos)} 个")
                            else:
                                empty_page_count += 1
                                if empty_page_count >= max_empty_pages:
                                    break
                            
                            # 检查是否还有更多数据
                            if not has_more or not max_cursor:
                                break
                                
                            # 添加延时避免请求过快
                            delay_seconds = _douyin_request_delay_seconds(page_count, mode="check")
                            total_sleep_seconds += delay_seconds
                            await asyncio.sleep(delay_seconds)
                    logger.info(
                        "[DouyinAntiRisk] 抖音博主检测分页完成: pages=%d induced_sleep=%.2fs new_candidates=%d",
                        page_count,
                        total_sleep_seconds,
                        len(all_videos),
                    )
        
        # 处理已获取的视频列表（去重）
        # B站和抖音合集已经在检测阶段获取了新视频，直接使用
        if subscription.platform == "bilibili" or subscription.platform == "bilibili_collection":
            if has_update:
                all_videos = latest_videos if isinstance(latest_videos, list) else []
        elif subscription.platform == "xiaohongshu" or subscription.platform == "tiktok" or subscription.platform == "netease" or subscription.platform == "x":
            # 小红书/TikTok/网易云：在检测阶段已经收集了 all_videos (通过差集比对)，直接使用，不需要再次清空或重新拉取
            pass
        elif subscription.platform == "youtube" or subscription.platform == "youtube_playlist":
            # YouTube平台：需要去重
            if has_update:
                # 获取数据库中已存在的视频ID集合
                existing_video_ids = set()
                existing_videos = db.query(SubscriptionVideo).filter(
                    SubscriptionVideo.subscription_id == subscription_id
                ).all()
                existing_video_ids = {v.video_id for v in existing_videos}
                platform_name = "YouTube播放列表" if subscription.platform == "youtube_playlist" else "YouTube"
                logger.info(f"{platform_name}检测更新：数据库中已存在 {len(existing_video_ids)} 个视频")

                # 从已获取的视频列表中过滤
                videos_list = latest_videos_result.get("videos", []) if isinstance(latest_videos_result, dict) else []
                page_new_videos = []
                youtube_adapter = registry.get_adapter("youtube")
                for video in videos_list:
                    if youtube_adapter:
                        normalized = youtube_adapter.normalize_video_data(video)
                        video_id = normalized.get("video_id", "")
                    else:
                        video_id = video.get("id", {}).get("videoId", "")
                    if video_id and video_id not in existing_video_ids:
                        page_new_videos.append(video)
                all_videos = page_new_videos
                total_items = len(videos_list)
                new_items = len(page_new_videos)
                existing_items = total_items - new_items
                logger.info(f"检查更新-当前页面处理: 总视频{total_items}个, 新视频{new_items}个, 已存在{existing_items}个")
        
        # 处理新视频
        potential_new_videos_count = len(all_videos)  # 发现的潜在新视频数
        actual_new_videos_count = 0  # 实际入库的视频数（初始化计数器）
        
        # 关键修复：只要检测到has_update=True，就需要处理（无论是否有新视频入库）
        # 这样确保即使最新视频已在库中，也会更新基准时间，避免重复检测
        if has_update:
            # 记录所有新视频的ID，便于调试
            # 获取适配器用于提取视频ID
            temp_adapter = registry.get_adapter(subscription.platform)
            if not temp_adapter:
                if subscription.platform == "douyin_collection":
                    temp_adapter = registry.get_adapter("douyin")
                elif subscription.platform == "youtube_playlist":
                    temp_adapter = registry.get_adapter("youtube")
                elif subscription.platform == "bilibili_collection":
                    temp_adapter = registry.get_adapter("bilibili")
            
            video_ids = []
            for video in all_videos:
                if temp_adapter:
                    # 使用适配器标准化后提取ID
                    subscription_type_for_id = subscription.subscription_type
                    if subscription.platform == "douyin_collection" or subscription.platform == "bilibili_collection":
                        subscription_type_for_id = "collection"
                    elif subscription.platform == "youtube_playlist":
                        subscription_type_for_id = "playlist"
                    normalized = temp_adapter.normalize_video_data(video, subscription_type_for_id)
                    video_id = normalized.get("video_id", "unknown")
                else:
                    video_id = "unknown"
                video_ids.append(video_id)
            
            logger.info(f"发现 {potential_new_videos_count} 个潜在新视频，视频ID列表: {video_ids}，开始处理...")
            
            # 处理每个新视频
            # 获取平台适配器（如果还没有获取）
            if 'adapter' not in locals():
                adapter = registry.get_adapter(subscription.platform)
                if not adapter:
                    # 处理特殊平台名称
                    if subscription.platform == "douyin_collection":
                        adapter = registry.get_adapter("douyin")
                        subscription_type_for_normalize = "collection"
                    elif subscription.platform == "youtube_playlist":
                        adapter = registry.get_adapter("youtube")
                        subscription_type_for_normalize = "playlist"
                    elif subscription.platform == "bilibili_collection":
                        adapter = registry.get_adapter("bilibili")
                        subscription_type_for_normalize = "collection"
                    else:
                        adapter = registry.get_adapter(subscription.platform)
                        subscription_type_for_normalize = subscription.subscription_type
                else:
                    subscription_type_for_normalize = subscription.subscription_type
            else:
                # adapter 已经在 locals 中，但需要确保 subscription_type_for_normalize 也被定义
                if subscription.platform == "douyin_collection" or subscription.platform == "bilibili_collection":
                    subscription_type_for_normalize = "collection"
                elif subscription.platform == "youtube_playlist":
                    subscription_type_for_normalize = "playlist"
                else:
                    subscription_type_for_normalize = subscription.subscription_type
            
            for video in all_videos:
                # 使用适配器标准化视频数据
                if adapter:
                    video_data = adapter.normalize_video_data(video, subscription_type_for_normalize)
                else:
                    # 回退到原始逻辑（不应该到达这里）
                    logger.error(f"无法标准化视频数据，平台: {subscription.platform}")
                    continue

                # --- 核心：过滤 B 站充电专属视频 ---
                if adapter and adapter.should_skip_video(video_data, skip_bilibili_upower):
                    logger.info(f"检查更新：跳过 B 站充电专属视频: {video_data['title']}")
                    continue
                
                # 检查视频是否已存在（更严格的检查）
                existing_video = db.query(SubscriptionVideo).filter(
                    SubscriptionVideo.subscription_id == subscription_id,
                    SubscriptionVideo.video_id == video_data["video_id"]
                ).first()
                
                if not existing_video:
                    # 额外检查：确保没有并发插入相同视频
                    try:
                        # 刷新数据库会话，确保获取最新状态
                        db.flush()
                        
                        # 再次检查是否已存在
                        existing_video_again = db.query(SubscriptionVideo).filter(
                            SubscriptionVideo.subscription_id == subscription_id,
                            SubscriptionVideo.video_id == video_data["video_id"]
                        ).first()
                        
                        if existing_video_again:
                            logger.warning(f"视频 {video_data['video_id']} 在检查过程中已被其他进程添加，跳过")
                            continue
                    except Exception as check_error:
                        logger.warning(f"重复检查视频时出错: {str(check_error)}")
                        # 继续处理，让数据库约束来处理重复
                    # 将stats数据存储到extra_data字段中
                    extra_data = {}
                    if "stats" in video_data:
                        extra_data["stats"] = video_data["stats"]
                    if "is_charging_arc" in video_data:
                        extra_data["is_charging_arc"] = video_data["is_charging_arc"]
                    # 与全量同步保持一致：发布时间为空时使用当前时间兜底
                    publish_time_for_db = video_data.get("publish_time") or datetime.now()
                    fallback_now = not bool(video_data.get("publish_time"))
                    logger.debug(
                        f"[DB_PUBLISH_TIME] mode=check_update video_id={video_data.get('video_id')} "
                        f"raw_publish_time={video_data.get('publish_time')} "
                        f"publish_time_for_db={publish_time_for_db.isoformat() if isinstance(publish_time_for_db, datetime) else publish_time_for_db} "
                        f"fallback={fallback_now}"
                    )
                    if fallback_now:
                        logger.warning(
                            f"[DB_PUBLISH_TIME][FALLBACK_NOW] mode=check_update video_id={video_data.get('video_id')} "
                            f"raw_publish_time={video_data.get('publish_time')} reason=empty_publish_time"
                        )
                    # 保存 publish_time_text 到 extra_data（与其他场景保持一致）
                    if isinstance(publish_time_for_db, datetime):
                        extra_data["publish_time_text"] = publish_time_for_db.strftime("%Y-%m-%d %H:%M:%S")
                    elif isinstance(publish_time_for_db, str):
                        extra_data["publish_time_text"] = publish_time_for_db
                    # 合并 normalize_video_data 返回的 extra_data（包含 type 和 xsec_token 等字段）
                    # 这对于小红书等平台正确区分视频和图集至关重要
                    if "extra_data" in video_data and isinstance(video_data.get("extra_data"), dict):
                        extra_data.update(video_data["extra_data"])
                    
                    # 创建新视频记录 - 在添加到数据库前生成UUID
                    new_video = SubscriptionVideo(
                        subscription_id=subscription_id,
                        video_id=video_data["video_id"],
                        title=_truncate_video_title(video_data["title"]),
                        url=video_data["url"],
                        cover_url=video_data["cover_url"],
                        publish_time=publish_time_for_db,
                        downloaded="false",
                        created_at=datetime.now(),
                        extra_data=json.dumps(extra_data) if extra_data else None
                    )
                    # 在添加到数据库前设置UUID
                    new_video.id = str(uuid.uuid4())
                    
                    try:
                        db.add(new_video)
                        # 立即刷新，检查是否有约束冲突
                        db.flush()
                        # 视频成功添加，计数器+1
                        actual_new_videos_count += 1
                    except Exception as add_error:
                        if "UNIQUE constraint failed" in str(add_error):
                            logger.warning(f"视频 {video_data['video_id']} 已存在，跳过添加")
                            continue
                        else:
                            raise add_error
                    
                    # 如果设置了自动下载，添加到下载队列
                    if subscription.auto_download.lower() == "true":
                        # 根据平台显示对应的日志
                        platform_name_map = {
                            "douyin": "抖音",
                            "douyin_collection": "抖音合集",
                            "youtube": "YouTube",
                            "youtube_playlist": "YouTube播放列表",
                            "tiktok": "TikTok",
                            "instagram": "Instagram",
                            "bilibili": "B站",
                            "bilibili_collection": "B站合集"
                        }
                        platform_display_name = platform_name_map.get(subscription.platform, subscription.platform)
                        logger.info(f"开始自动下载{platform_display_name}视频: {new_video.title}，画质设置: {subscription.quality}")
                        
                        # 异步处理下载，避免阻塞当前事务
                        asyncio.create_task(_async_add_download(new_video.id, subscription.quality))
                    
            # 提交所有新视频
            try:
                db.commit()
                
                # 更新订阅状态
                _mark_subscription_check_success(subscription)
                db.commit()
            except Exception as commit_error:
                logger.error(f"提交数据库事务失败: {str(commit_error)}")
                db.rollback()
                
                # 如果是唯一约束冲突，尝试重新检查并跳过已存在的视频
                if "UNIQUE constraint failed" in str(commit_error) and "subscription_videos.id" in str(commit_error):
                    logger.warning("检测到重复视频记录，尝试重新处理...")
                    # 重新查询数据库，获取已存在的视频ID
                    existing_video_ids = set()
                    existing_videos = db.query(SubscriptionVideo).filter(
                        SubscriptionVideo.subscription_id == subscription_id
                    ).all()
                    existing_video_ids = {v.video_id for v in existing_videos}
                    
                    # 重新处理新视频，跳过已存在的
                    actual_new_count = 0
                    for video in all_videos:
                        if subscription.platform == "douyin":
                            video_id = video.get("aweme_id")
                        elif subscription.platform == "douyin_collection":
                            video_id = video.get("video_id")
                        elif subscription.platform == "youtube" or subscription.platform == "youtube_playlist":
                            video_id = video.get("id", {}).get("videoId")
                        elif subscription.platform == "bilibili":
                            if subscription.subscription_type == "favorite":
                                # B站收藏夹订阅：使用video_id字段（BV号）
                                video_id = video.get("video_id", "")
                            elif subscription.subscription_type == "collection":
                                # B站合集订阅：使用video_id字段
                                video_id = video.get("video_id", "")
                            else:
                                # B站UP主订阅：从URL中提取
                                video_id = video.get("url", "").split("/")[-1] if video.get("url") else ""
                        elif subscription.platform == "bilibili_collection":
                            video_id = video.get("video_id", "")
                        elif subscription.platform == "tiktok":
                            video_id = video.get("video_id")
                        elif subscription.platform == "instagram":
                            instagram_adapter = registry.get_adapter("instagram")
                            if instagram_adapter:
                                normalized_media = instagram_adapter.normalize_video_data(video, "user")
                                video_id = normalized_media.get("video_id")
                            else:
                                video_id = video.get("video_id")
                        elif subscription.platform == "x":
                            video_id = video.get("video_id") or video.get("url", "").split("/")[-1]
                        elif subscription.platform == "netease":
                            netease_adapter = registry.get_adapter("netease")
                            if netease_adapter:
                                normalized_song = netease_adapter.normalize_video_data(video, "playlist")
                                video_id = normalized_song.get("video_id")
                            else:
                                video_id = video.get("id") or video.get("track_id")
                        else:
                            video_id = None
                        
                        if video_id and video_id not in existing_video_ids:
                            actual_new_count += 1
                    
                    logger.info(f"重新处理后，实际新增视频数: {actual_new_count}")
                    
                    # 重要：无论是否有新增视频，都要更新基准时间（因为检测到了has_update=True）
                    # 这样确保下次检测不会重复提示相同的"更新"
                    if subscription.platform == "bilibili" and current_latest_video is not None:
                        subscription.latest_video_time = current_latest_publish_time
                        subscription.latest_video_id = current_latest_video_id
                        subscription.latest_video_title = _truncate_video_title(current_latest_video.get("title", ""))
                        subscription.latest_video_cover = current_latest_video.get("cover_url", "")
                        subscription.last_update = now
                        logger.info(f"B站更新基准时间（异常恢复）: {current_latest_publish_time} (入库视频数: {actual_new_count})")
                    elif subscription.platform == "bilibili_collection" and current_latest_video is not None:
                        subscription.latest_video_time = current_latest_publish_time
                        subscription.latest_video_id = current_latest_video_id
                        subscription.latest_video_title = _truncate_video_title(current_latest_video.get("title", ""))
                        subscription.latest_video_cover = current_latest_video.get("cover_url", "")
                        subscription.last_update = now
                        logger.info(
                            f"B站合集更新基准时间（异常恢复）: {current_latest_publish_time} "
                            f"(入库视频数: {actual_new_count})"
                        )
                    elif subscription.platform == "douyin" and subscription.subscription_type != "favorite" and douyin_latest_video is not None:
                        subscription.latest_video_time = douyin_latest_publish_time
                        subscription.latest_video_title = _truncate_video_title(douyin_latest_video.get("desc", ""))
                        subscription.latest_video_cover = _safe_douyin_cover_url(douyin_latest_video)
                        subscription.last_update = now
                        logger.info(f"抖音博主更新基准时间（异常恢复）: {douyin_latest_publish_time} (入库视频数: {actual_new_count})")
                    elif subscription.platform == "douyin_collection" and douyin_collection_latest_video is not None:
                        subscription.latest_video_time = douyin_collection_latest_publish_time
                        subscription.latest_video_title = _truncate_video_title(douyin_collection_latest_video.get("title", ""))
                        subscription.latest_video_cover = douyin_collection_latest_video.get("cover_url", "")
                        subscription.last_update = now
                        logger.info(f"抖音合集更新基准时间（异常恢复）: {douyin_collection_latest_publish_time} (入库视频数: {actual_new_count})")
                    elif subscription.platform == "x" and latest_video is not None:
                        subscription.latest_video_id = latest_video.get("video_id", subscription.latest_video_id or "")
                        subscription.latest_video_title = _truncate_video_title(latest_video.get("title", subscription.latest_video_title or ""))
                        subscription.latest_video_cover = latest_video.get("cover_url", subscription.latest_video_cover or "")
                        subscription.latest_video_time = latest_video.get("publish_time") or datetime.now()
                        subscription.last_update = now
                        logger.info(f"X更新基准信息（异常恢复）: ID={subscription.latest_video_id} (入库视频数: {actual_new_count})")
                    elif subscription.platform == "netease" and netease_latest_video_data is not None:
                        subscription.latest_video_id = str(netease_latest_video_data.get("video_id") or subscription.latest_video_id or "")
                        subscription.latest_video_title = _truncate_video_title(netease_latest_video_data.get("title", subscription.latest_video_title or ""))
                        subscription.latest_video_cover = netease_latest_video_data.get("cover_url", subscription.latest_video_cover or "")
                        subscription.latest_video_time = netease_latest_video_data.get("publish_time") or datetime.now()
                        subscription.last_update = now
                        logger.info(f"网易云更新基准信息（异常恢复）: ID={subscription.latest_video_id} (入库歌曲数: {actual_new_count})")
                    
                    # 更新订阅状态
                    _mark_subscription_check_success(subscription)
                    db.commit()
                    
                    return {
                        "message": "检查完成（部分视频已存在）",
                        "has_update": actual_new_count > 0,
                        "new_videos_count": actual_new_count,
                        "requires_sync": False
                    }
                else:
                    raise commit_error
            
            # 重要：无论是否有新视频入库，只要检测到has_update=True，都要更新基准时间
            # 这样确保下次检测不会重复提示相同的"更新"
            try:
                if subscription.platform == "bilibili" and current_latest_video:
                    # B站：更新基准时间（避免重复检测）
                    subscription.latest_video_time = current_latest_publish_time
                    subscription.latest_video_id = current_latest_video_id
                    subscription.latest_video_title = _truncate_video_title(current_latest_video.get("title", ""))
                    subscription.latest_video_cover = current_latest_video.get("cover_url", "")
                    subscription.last_update = now
                    logger.info(f"B站更新基准时间: {current_latest_publish_time} (实际入库: {actual_new_videos_count}/{potential_new_videos_count})")
                elif subscription.platform == "bilibili_collection" and current_latest_video:
                    # B站合集：更新基准时间（避免重复检测）
                    subscription.latest_video_time = current_latest_publish_time
                    subscription.latest_video_id = current_latest_video_id
                    subscription.latest_video_title = _truncate_video_title(current_latest_video.get("title", ""))
                    subscription.latest_video_cover = current_latest_video.get("cover_url", "")
                    subscription.last_update = now
                    logger.info(
                        f"B站合集更新基准时间: {current_latest_publish_time} "
                        f"(实际入库: {actual_new_videos_count}/{potential_new_videos_count})"
                    )
                elif subscription.platform == "douyin" and subscription.subscription_type != "favorite" and douyin_latest_video is not None:
                    # 抖音博主：更新基准时间（避免重复检测）
                    subscription.latest_video_time = douyin_latest_publish_time
                    subscription.latest_video_title = _truncate_video_title(douyin_latest_video.get("desc", ""))
                    subscription.latest_video_cover = _safe_douyin_cover_url(douyin_latest_video)
                    subscription.last_update = now
                    logger.info(f"抖音博主更新基准时间: {douyin_latest_publish_time} (实际入库: {actual_new_videos_count}/{potential_new_videos_count})")
                elif subscription.platform == "douyin_collection" and douyin_collection_latest_video is not None:
                    # 抖音合集：更新基准时间（避免重复检测）
                    subscription.latest_video_time = douyin_collection_latest_publish_time
                    subscription.latest_video_title = _truncate_video_title(douyin_collection_latest_video.get("title", ""))
                    subscription.latest_video_cover = douyin_collection_latest_video.get("cover_url", "")
                    subscription.last_update = now
                    logger.info(f"抖音合集更新基准时间: {douyin_collection_latest_publish_time} (实际入库: {actual_new_videos_count}/{potential_new_videos_count})")
                elif subscription.platform == "netease" and netease_latest_video_data is not None:
                    # 网易云：基于歌曲ID更新基准信息
                    subscription.latest_video_id = str(netease_latest_video_data.get("video_id") or subscription.latest_video_id or "")
                    subscription.latest_video_title = _truncate_video_title(netease_latest_video_data.get("title", subscription.latest_video_title or ""))
                    subscription.latest_video_cover = netease_latest_video_data.get("cover_url", subscription.latest_video_cover or "")
                    subscription.latest_video_time = netease_latest_video_data.get("publish_time") or datetime.now()
                    subscription.last_update = now
                    logger.info(f"网易云更新基准信息: ID={subscription.latest_video_id} (实际入库: {actual_new_videos_count}/{potential_new_videos_count})")
                elif subscription.platform == "xiaohongshu" and has_update and xhs_latest_video_data is not None:
                    # 小红书：适配器已返回 datetime，直接更新基准时间
                    subscription.latest_video_time = xhs_latest_publish_time or subscription.latest_video_time
                    subscription.latest_video_title = _truncate_video_title(xhs_latest_video_data.get("title", subscription.latest_video_title or ""))
                    subscription.latest_video_cover = xhs_latest_video_data.get("cover_url", subscription.latest_video_cover or "")
                    subscription.last_update = now
                    logger.info(f"小红书更新基准时间: {xhs_latest_publish_time} (实际入库: {actual_new_videos_count}/{potential_new_videos_count})")
                elif (subscription.platform == "youtube" or subscription.platform == "youtube_playlist") and has_update:
                    # YouTube：保持原有逻辑
                    snippet = latest_video.get("snippet", {}) if latest_video is not None else {}
                    published_at = snippet.get("publishedAt")
                    if published_at:
                        try:
                            subscription.latest_video_time = datetime.fromisoformat(published_at.replace('Z', '+00:00'))
                        except Exception:
                            subscription.latest_video_time = datetime.utcnow()
                    subscription.latest_video_id = latest_video.get("id", {}).get("videoId", subscription.latest_video_id)
                    subscription.latest_video_title = _truncate_video_title(snippet.get("title", subscription.latest_video_title or ""))
                    subscription.latest_video_cover = snippet.get("thumbnails", {}).get("high", {}).get("url", subscription.latest_video_cover or "")
                    subscription.last_update = now
                elif subscription.platform == "tiktok" and has_update and latest_video is not None:
                    # TikTok：更新基准视频信息（基于 ID 检测，与 YouTube 保持一致）
                    subscription.latest_video_id = latest_video.get("video_id", subscription.latest_video_id or "")
                    subscription.latest_video_title = _truncate_video_title(latest_video.get("title", subscription.latest_video_title or ""))
                    subscription.latest_video_cover = latest_video.get("cover_url", subscription.latest_video_cover or "")
                    
                    # 时间仅用于显示（检测逻辑基于 ID）
                    create_time = latest_video.get("create_time", 0)
                    if create_time and create_time > 0:
                        subscription.latest_video_time = datetime.fromtimestamp(create_time)
                    else:
                        subscription.latest_video_time = datetime.now()
                    
                    subscription.last_update = now
                    logger.info(f"TikTok更新基准视频: ID={latest_video.get('video_id', 'N/A')} (实际入库: {actual_new_videos_count}/{potential_new_videos_count})")
                elif subscription.platform == "instagram" and has_update and latest_video is not None:
                    normalized_latest = adapter.normalize_video_data(latest_video, "user")
                    subscription.latest_video_id = str(normalized_latest.get("video_id") or subscription.latest_video_id or "")
                    subscription.latest_video_title = _truncate_video_title(normalized_latest.get("title", subscription.latest_video_title or ""))
                    subscription.latest_video_cover = normalized_latest.get("cover_url", subscription.latest_video_cover or "")
                    subscription.latest_video_time = normalized_latest.get("publish_time") or datetime.now()
                    subscription.last_update = now
                    logger.info(f"Instagram更新基准媒体: ID={subscription.latest_video_id} (实际入库: {actual_new_videos_count}/{potential_new_videos_count})")
                elif subscription.platform == "x" and has_update and latest_video is not None:
                    subscription.latest_video_id = latest_video.get("video_id", subscription.latest_video_id or "")
                    subscription.latest_video_title = _truncate_video_title(latest_video.get("title", subscription.latest_video_title or ""))
                    subscription.latest_video_cover = latest_video.get("cover_url", subscription.latest_video_cover or "")
                    subscription.latest_video_time = latest_video.get("publish_time") or datetime.now()
                    subscription.last_update = now
                    logger.info(f"X更新基准视频: ID={subscription.latest_video_id} (实际入库: {actual_new_videos_count}/{potential_new_videos_count})")
                
                db.commit()
            except Exception as e:
                logger.warning(f"更新订阅最新视频信息失败: {str(e)}")

            # 发送成功通知
            asyncio.create_task(send_subscription_check_notification(
                subscription_id=subscription_id,
                user_id=subscription.user_id,
                nickname=subscription.nickname,
                platform=subscription.platform,
                success=True,
                new_videos_count=actual_new_videos_count
            ))
            
            # 🚀 优化：检测更新完成后主动清理对应的标签页
            if cleanup_page:
                try:
                    await _cleanup_subscription_pages(subscription.platform, subscription.user_id)
                except Exception as e:
                    logger.warning(f"清理检测更新标签页失败: {str(e)}")
            
            # 根据实际入库情况返回消息
            if actual_new_videos_count > 0:
                message = f"检查完成，新增 {actual_new_videos_count} 个视频"
            else:
                message = "检查完成，最新视频已在库中，已更新基准时间"
            
            return {
                "message": message,
                "has_update": actual_new_videos_count > 0,  # 只有真正入库新视频才算有更新
                "new_videos_count": actual_new_videos_count,
                "requires_sync": False,
                "status": subscription.status,
                "error_message": subscription.error_message
            }
        else:
            logger.info("没有发现新视频")
            
            # 即使没有新视频，也更新YouTube/播放列表/TikTok的最新视频信息（用于显示）
            if (subscription.platform == "youtube" or subscription.platform == "youtube_playlist") and latest_video is not None:
                try:
                    snippet = latest_video.get("snippet", {})
                    published_at = snippet.get("publishedAt")
                    if published_at:
                        try:
                            subscription.latest_video_time = datetime.fromisoformat(published_at.replace('Z', '+00:00'))
                        except Exception:
                            subscription.latest_video_time = datetime.utcnow()
                    subscription.latest_video_id = latest_video.get("id", {}).get("videoId", subscription.latest_video_id)
                    subscription.latest_video_title = _truncate_video_title(snippet.get("title", subscription.latest_video_title or ""))
                    subscription.latest_video_cover = snippet.get("thumbnails", {}).get("high", {}).get("url", subscription.latest_video_cover or "")
                    subscription.last_update = now
                except Exception as e:
                    logger.warning(f"更新订阅最新视频信息失败: {str(e)}")
            elif subscription.platform == "tiktok" and latest_video is not None:
                try:
                    # TikTok：即使无更新也要更新显示信息
                    subscription.latest_video_id = latest_video.get("video_id", subscription.latest_video_id or "")
                    subscription.latest_video_title = _truncate_video_title(latest_video.get("title", subscription.latest_video_title or ""))
                    subscription.latest_video_cover = latest_video.get("cover_url", subscription.latest_video_cover or "")
                    
                    # 时间仅用于显示
                    create_time = latest_video.get("create_time", 0)
                    if create_time and create_time > 0:
                        subscription.latest_video_time = datetime.fromtimestamp(create_time)
                    
                    subscription.last_update = now
                    logger.info(f"TikTok更新显示信息: ID={latest_video.get('video_id', 'N/A')}")
                except Exception as e:
                    logger.warning(f"更新TikTok订阅最新视频信息失败: {str(e)}")
            elif subscription.platform == "instagram" and latest_video is not None:
                try:
                    normalized_latest = adapter.normalize_video_data(latest_video, "user")
                    subscription.latest_video_id = str(normalized_latest.get("video_id") or subscription.latest_video_id or "")
                    subscription.latest_video_title = _truncate_video_title(normalized_latest.get("title", subscription.latest_video_title or ""))
                    subscription.latest_video_cover = normalized_latest.get("cover_url", subscription.latest_video_cover or "")
                    if normalized_latest.get("publish_time"):
                        subscription.latest_video_time = normalized_latest.get("publish_time")
                    subscription.last_update = now
                    logger.info(f"Instagram更新显示信息: ID={subscription.latest_video_id}")
                except Exception as e:
                    logger.warning(f"更新Instagram订阅最新媒体信息失败: {str(e)}")
            elif subscription.platform == "xiaohongshu" and xhs_latest_video_data is not None:
                try:
                    # 小红书：即使无新增也更新展示用的最新笔记信息
                    if xhs_latest_publish_time:
                        subscription.latest_video_time = xhs_latest_publish_time
                    subscription.latest_video_title = _truncate_video_title(xhs_latest_video_data.get("title", subscription.latest_video_title or ""))
                    subscription.latest_video_cover = xhs_latest_video_data.get("cover_url", subscription.latest_video_cover or "")
                    subscription.last_update = now
                    logger.info("小红书更新显示信息（无新增笔记）")
                except Exception as e:
                    logger.warning(f"更新小红书订阅最新笔记信息失败: {str(e)}")
            elif subscription.platform == "netease" and netease_latest_video_data is not None:
                try:
                    subscription.latest_video_id = str(netease_latest_video_data.get("video_id") or subscription.latest_video_id or "")
                    subscription.latest_video_title = _truncate_video_title(netease_latest_video_data.get("title", subscription.latest_video_title or ""))
                    subscription.latest_video_cover = netease_latest_video_data.get("cover_url", subscription.latest_video_cover or "")
                    subscription.latest_video_time = netease_latest_video_data.get("publish_time") or subscription.latest_video_time or datetime.now()
                    subscription.last_update = now
                    logger.info(f"网易云更新显示信息: ID={subscription.latest_video_id}")
                except Exception as e:
                    logger.warning(f"更新网易云订阅最新歌曲信息失败: {str(e)}")
            
            # 更新订阅状态
            # 仅当原来是ERROR状态或ACTIVE状态时才更新为ACTIVE
            # 如果是PAUSED状态，说明用户手动暂停了，不应因手动检查更新而自动恢复
            _mark_subscription_check_success(subscription)
            db.commit()
            
            # 发送成功通知（无新视频）
            asyncio.create_task(send_subscription_check_notification(
                subscription_id=subscription_id,
                user_id=subscription.user_id,
                nickname=subscription.nickname,
                platform=subscription.platform,
                success=True,
                new_videos_count=0
            ))
            
            # 🚀 优化：检测更新完成后主动清理对应的标签页
            if cleanup_page:
                try:
                    await _cleanup_subscription_pages(subscription.platform, subscription.user_id)
                except Exception as e:
                    logger.warning(f"清理检测更新标签页失败: {str(e)}")
            
            return {
                "message": "检查完成",
                "has_update": False,
                "new_videos_count": 0,
                "requires_sync": False,
                "status": subscription.status,
                "error_message": subscription.error_message
            }
        
    except Exception as e:
        logger.error(f"检查订阅更新失败: {str(e)}")
        
        # 首先尝试回滚任何可能无效的事务
        try:
            db.rollback()
        except Exception:
            pass
        
        # 使用已提取的局部变量（如果可用）发送通知，避免访问可能已失效的 session 对象
        notification_user_id = locals().get('user_id', subscription.user_id if subscription else None)
        notification_nickname = locals().get('nickname', subscription.nickname if subscription else None)
        notification_platform = locals().get('platform', subscription.platform if subscription else None)
        
        try:
            if subscription:
                # 重新从数据库获取 subscription 以确保事务有效
                try:
                    subscription = db.query(Subscription).filter(
                        Subscription.id == subscription_id
                    ).first()
                    if subscription:
                        _mark_subscription_check_failure(subscription, str(e))
                        db.commit()
                except Exception:
                    db.rollback()
                
                # 发送失败通知 - 使用已提取的局部变量
                if notification_user_id and notification_platform:
                    asyncio.create_task(send_subscription_check_notification(
                        subscription_id=subscription_id,
                        user_id=notification_user_id,
                        nickname=notification_nickname,
                        platform=notification_platform,
                        success=False,
                        error_message=str(e)
                    ))
        except Exception as commit_error:
            logger.error(f"更新订阅错误状态失败: {str(commit_error)}")
            try:
                db.rollback()
            except Exception:
                pass
        
        raise HTTPException(status_code=500, detail=f"检查订阅更新失败: {str(e)}")


@router.post("/{subscription_id}/sync_videos")
@require_license_api
async def sync_videos(
    subscription_id: str,
    db: Session = Depends(get_db),
    progress_callback = None
):
    """同步博主的所有视频信息到数据库，确保数据库中的视频与博主当前视频完全匹配
    
    注意：此函数使用短连接模式，避免长时间同步任务导致连接超时
    """
    from routers.unified_browser_manager import unified_browser
    
    try:
        # 🔧 优化：使用独立短连接，避免长连接超时
        from sql.database_postgresql import get_session
        
        # 1. 获取订阅信息
        query_db = get_session()
        try:
            subscription = query_db.query(Subscription).filter(
                Subscription.id == subscription_id
            ).first()
            
            if not subscription:
                query_db.close()
                raise HTTPException(status_code=404, detail="未找到该订阅")

            # 🔧 修复：在关闭连接前，先读取所有需要的属性值，避免对象分离后无法访问
            platform = subscription.platform
            user_id = subscription.user_id
            nickname = subscription.nickname
            subscription_type = subscription.subscription_type
            youtube_tab_type = getattr(subscription, 'youtube_tab_type', None)
            collection_id = getattr(subscription, 'collection_id', None)
            skip_bilibili_upower = getattr(subscription, 'skip_bilibili_upower', 'false') == 'true'
            profile_url = getattr(subscription, 'profile_url', None) or ""

            # 2. 如果开启了跳过B站充电视频，先清理数据库中已有的充电视频
            if platform.startswith('bilibili') and skip_bilibili_upower:
                try:
                    # 查找 extra_data 中包含 is_charging_arc 为 true 的视频并删除
                    # 即使是以前同步的视频，如果这次同步中发现是充电视频，也会被过滤
                    from sqlalchemy import or_
                    deleted = query_db.query(SubscriptionVideo).filter(
                        SubscriptionVideo.subscription_id == subscription_id,
                        SubscriptionVideo.downloaded != "true",  # ⚡️ 保护：已下载的视频不删除
                        or_(
                            SubscriptionVideo.extra_data.like('%"is_charging_arc": true%'),
                            SubscriptionVideo.extra_data.like('%"is_charging_arc":true%')
                        )
                    ).delete(synchronize_session=False)
                    query_db.commit()
                    if deleted > 0:
                        logger.info(f"订阅[{nickname}]清理了 {deleted} 个已存在的 B 站充电专属视频")
                except Exception as e:
                    logger.warning(f"清理已存在充电视频失败: {e}")
                    query_db.rollback()

            # 3. 更新同步状态为开始同步
            subscription.sync_status = "syncing"
            subscription.sync_progress = 0
            query_db.commit()
        finally:
            query_db.close()

        logger.info(f"开始同步订阅: {nickname} (平台: {platform}, 用户ID: {user_id})")

        # 发送开始同步状态
        await send_progress_update(subscription_id, {
            "type": "sync_progress",
            "status": "syncing",
            "count": 0
        })

        # 3. 获取所有视频
        all_videos = []

        # [补全] 初始化流式处理状态变量
        processed_video_ids = set()
        total_fetched_count = 0
        new_videos_count = 0
        deleted_count = 0
        kept_count = 0
        latest_video_timestamp = 0.0
        latest_video_data = None

        # [新增] 内部批量处理函数 (用于流式同步)
        # 允许在获取视频的过程中实时写入数据库，防止任务中断导致数据丢失
        # ⚡️ 优化：使用短生命周期的独立 Session，避免长连接超时
        async def process_video_batch(videos_batch: List[dict]):
            nonlocal total_fetched_count, new_videos_count
            
            if not videos_batch:
                return

            total_fetched_count += len(videos_batch)
            
            if progress_callback:
                asyncio.create_task(progress_callback(total_fetched_count))
            
            # --- 核心业务逻辑包装在独立 Session 中 ---
            # 随用随开，用完即弃，不依赖外部的长 Session
            from sql.database_postgresql import get_session
            from sqlalchemy.exc import OperationalError, DisconnectionError, InvalidRequestError
            import time

            # 先统一解析发布时间，避免逐条 WARNING 刷屏，并确保重试时解析结果一致
            prepared_videos = []
            fallback_count = 0
            fallback_samples = []
            for video in videos_batch:
                video_id = video.get("video_id")
                publish_time = datetime.now()
                fallback_to_now = True
                fallback_reason = "empty_or_unparsed"
                p_time_raw = video.get("publish_time")
                try:
                    if isinstance(p_time_raw, datetime):
                        publish_time = p_time_raw
                        fallback_to_now = False
                        fallback_reason = ""
                    elif isinstance(p_time_raw, str):
                        normalized_time_str = p_time_raw.strip()
                        if normalized_time_str:
                            if normalized_time_str.endswith('Z'):
                                normalized_time_str = normalized_time_str.replace('Z', '+00:00')
                            publish_time = datetime.fromisoformat(normalized_time_str)
                            fallback_to_now = False
                            fallback_reason = ""
                    elif isinstance(p_time_raw, (int, float)):
                        ts_val = int(p_time_raw)
                        if ts_val > 10000000000:
                            ts_val /= 1000.0
                        publish_time = datetime.fromtimestamp(ts_val)
                        fallback_to_now = False
                        fallback_reason = ""
                except Exception as parse_error:
                    fallback_to_now = True
                    fallback_reason = f"parse_error:{str(parse_error)}"

                if fallback_to_now:
                    fallback_count += 1
                    if len(fallback_samples) < 5 and video_id:
                        fallback_samples.append(f"{video_id}:{fallback_reason}")

                logger.debug(
                    f"[DB_PUBLISH_TIME] video_id={video_id} raw_publish_time={p_time_raw} "
                    f"parsed_publish_time={publish_time.isoformat()} fallback={fallback_to_now}"
                )
                prepared_videos.append((video, publish_time))
            
            # 添加重试机制，最多重试3次
            max_retries = 3
            retry_delay = 1.0  # 初始重试延迟1秒
            
            for attempt in range(max_retries):
                local_db = None
                try:
                    # 使用 get_session() 直接获取会话，避免生成器问题
                    local_db = get_session()
                    
                    # 批量处理视频入库
                    for video, publish_time in prepared_videos:
                        # --- 跳过 B 站充电专属视频逻辑 ---
                        is_charging = video.get("is_charging_arc", False)
                        if platform.startswith('bilibili') and skip_bilibili_upower and is_charging:
                            logger.debug(f"跳过 B 站充电专属视频: {video.get('title')}")
                            # 如果开启了跳过，且视频已存在于数据库中（可能是以前同步的旧数据），则将其删除
                            try:
                                v_id = video.get("video_id")
                                if v_id:
                                    existing_to_del = local_db.query(SubscriptionVideo).filter(
                                        SubscriptionVideo.subscription_id == subscription_id,
                                        SubscriptionVideo.video_id == v_id
                                    ).first()
                                    if existing_to_del:
                                        local_db.delete(existing_to_del)
                                        logger.info(f"同步过程中清理了已存在的充电专属视频: {video.get('title')}")
                            except Exception as del_err:
                                logger.warning(f"同步中清理充电视频失败: {del_err}")
                            continue

                        video_id = video["video_id"]

                        # --- 数据库 Upsert ---
                        # 检查视频是否已存在
                        existing_video = local_db.query(SubscriptionVideo).filter(
                            SubscriptionVideo.subscription_id == subscription_id,
                            SubscriptionVideo.video_id == video_id
                        ).first()
                    
                        if existing_video:
                            # 更新
                            existing_video.title = video["title"]
                            if video.get("cover_url"):
                                existing_video.cover_url = video["cover_url"]
                            existing_video.publish_time = publish_time
                            
                            # 更新 extra_data（含 xsec_token 等，便于小红书 feed 直链下载）
                            try:
                                extra = json.loads(existing_video.extra_data or '{}')
                                if extra.get('removed_from_source'):
                                    extra.pop('removed_from_source', None)
                                    extra.pop('removed_at', None)
                                extra['publish_time_text'] = publish_time.strftime("%Y-%m-%d %H:%M:%S")
                                extra['stats'] = video["stats"]
                                extra['is_charging_arc'] = is_charging
                                extra_update = video.get("extra_data") or {}
                                for k, v in extra_update.items():
                                    if v is not None:
                                        extra[k] = v
                                existing_video.extra_data = json.dumps(extra)
                            except:
                                pass
                        else:
                            # 新增
                            new_videos_count += 1
                            new_video = SubscriptionVideo(
                                id=str(uuid.uuid4()),
                                subscription_id=subscription_id,
                                video_id=video_id,
                                title=_truncate_video_title(video["title"]),
                                url=video["url"],
                                cover_url=video["cover_url"],
                                publish_time=publish_time,
                                downloaded="false",
                                created_at=datetime.now(),
                                extra_data=json.dumps({
                                    "publish_time_text": publish_time.strftime("%Y-%m-%d %H:%M:%S"),
                                    "stats": video["stats"],
                                    "is_charging_arc": is_charging,
                                    **(video.get("extra_data") or {}),
                                })
                            )
                            local_db.add(new_video)
                
                    # --- 提交 ---
                    local_db.commit() 
                    logger.info(f"流式同步: 本批次已保存 {len(videos_batch)} 个视频 (累计: {total_fetched_count})")
                    if fallback_count > 0:
                        fallback_msg = (
                            f"[DB_PUBLISH_TIME][FALLBACK_NOW] platform={platform} "
                            f"batch_count={len(videos_batch)} fallback_count={fallback_count} "
                            f"samples={fallback_samples}"
                        )
                        if str(platform).startswith("xiaohongshu"):
                            logger.info(fallback_msg)
                        else:
                            logger.warning(fallback_msg)
                    
                    # 成功提交后，确保关闭连接
                    if local_db:
                        try:
                            local_db.close()
                        except:
                            pass
                    return  # 成功，退出重试循环
                    
                except (OperationalError, DisconnectionError, InvalidRequestError) as db_error:
                    # 数据库连接相关错误：记录详细错误信息并重试
                    error_msg = str(db_error).lower()
                    if local_db:
                        try:
                            local_db.rollback()
                        except:
                            pass
                        try:
                            local_db.close()
                        except:
                            pass
                        local_db = None
                    
                    if attempt < max_retries - 1:
                        if 'rollback' in error_msg or 'invalid transaction' in error_msg:
                            logger.warning(f"数据库事务状态无效，尝试重试 ({attempt + 1}/{max_retries}): {db_error}")
                        elif 'connection' in error_msg or 'closed' in error_msg:
                            logger.warning(f"数据库连接已断开，尝试重试 ({attempt + 1}/{max_retries}): {db_error}")
                        else:
                            logger.warning(f"数据库操作失败，尝试重试 ({attempt + 1}/{max_retries}): {db_error}")
                        
                        # 指数退避重试
                        await asyncio.sleep(retry_delay * (2 ** attempt))
                        continue
                    else:
                        # 重试次数用尽，记录错误但不抛出异常，允许继续处理后续批次
                        logger.error(f"批量入库失败，已重试{max_retries}次，跳过本批次: {db_error}")
                        # 不抛出异常，允许继续处理后续批次
                        return
                        
                except Exception as e:
                    # 其他异常：记录错误并关闭连接
                    if local_db:
                        try:
                            local_db.rollback()
                        except:
                            pass
                        try:
                            local_db.close()
                        except:
                            pass
                    
                    if attempt < max_retries - 1:
                        logger.warning(f"批量入库提交失败，尝试重试 ({attempt + 1}/{max_retries}): {e}")
                        await asyncio.sleep(retry_delay * (2 ** attempt))
                        continue
                    else:
                        logger.error(f"批量入库提交失败，已重试{max_retries}次，跳过本批次: {e}")
                        # 不抛出异常，允许继续处理后续批次
                        return
        
        if platform == "douyin":
            logger.info("使用抖音API获取视频列表")
            # 抖音视频获取逻辑
            
            if subscription_type == "favorite":
                # 点赞列表订阅：一次性加载所有视频
                logger.info("点赞列表订阅，一次性加载所有视频...")

                # 点赞列表 API 可能需要 sec_user_id（优先从订阅 extra_data 缓存读取）
                cached_sec_user_id = None
                try:
                    from sql.database_postgresql import get_session
                    sec_db = get_session()
                    try:
                        sub_row = sec_db.query(Subscription).filter(
                            Subscription.id == subscription_id
                        ).first()
                        if sub_row:
                            try:
                                extra = json.loads(sub_row.extra_data or "{}")
                                cached_sec_user_id = extra.get("sec_user_id")
                            except Exception:
                                cached_sec_user_id = None
                    finally:
                        sec_db.close()
                except Exception:
                    cached_sec_user_id = None
                
                # 定义进度回调函数
                async def on_scroll_progress(count: int):
                    """滚动进度回调"""
                    # [优化] 不再需要手动数据库保活，因为使用了短连接
                    # 此时 simply return
                    await send_progress_update(subscription_id, {
                        "type": "sync_progress",
                        "status": "syncing",
                        "count": count
                    })
                
                # 使用task_context防止浏览器被空闲超时关闭
                async with unified_browser.task_context("douyin", "sync_favorite_videos"):
                    
                    # [新增] 批次处理回调适配器
                    async def on_batch_received(batch_items: List[dict]):
                        """接收 API 返回的原始数据批次，转换并入库"""
                        batch_videos_processed = []
                        skipped_items = 0
                        for index, item in enumerate(batch_items):
                            try:
                                if not isinstance(item, dict):
                                    skipped_items += 1
                                    logger.warning(
                                        f"点赞批次第{index + 1}条数据结构异常，已跳过: "
                                        f"type={type(item).__name__}"
                                    )
                                    continue

                                aweme_id = item.get("aweme_id")
                                if not aweme_id:
                                    skipped_items += 1
                                    logger.warning(f"点赞批次第{index + 1}条缺少 aweme_id，已跳过")
                                    continue

                                stats = item.get("statistics") or {}
                                if not isinstance(stats, dict):
                                    stats = {}

                                video = {
                                    "video_id": aweme_id,
                                    "title": item.get("desc", ""),
                                    "url": get_correct_douyin_url(aweme_id, item),
                                    "cover_url": _safe_douyin_cover_url(item),
                                    "publish_time": item.get("create_time"),
                                    "stats": {
                                        "digg_count": stats.get("digg_count", 0),
                                        "comment_count": stats.get("comment_count", 0),
                                        "share_count": stats.get("share_count", 0)
                                    }
                                }
                                batch_videos_processed.append(video)
                            except Exception as item_error:
                                skipped_items += 1
                                logger.warning(
                                    f"点赞批次第{index + 1}条数据处理失败，已跳过: {item_error}"
                                )

                        if skipped_items > 0:
                            logger.warning(
                                f"点赞批次存在异常数据，已跳过 {skipped_items} 条，"
                                f"本批有效 {len(batch_videos_processed)} 条"
                            )

                        if not batch_videos_processed:
                            return

                        # 调用通用批处理
                        await process_video_batch(batch_videos_processed)

                    response = await douyin_api.get_favorite_videos(
                        max_count=999,  # 不限制数量
                        max_cursor=1,   # 1表示加载所有
                        progress_callback=on_scroll_progress,  # 传入进度回调
                        batch_callback=on_batch_received,      # [新增] 传入批处理回调
                        sec_user_id=cached_sec_user_id
                    )
                
                if response and response.get("aweme_list"):
                    # 处理所有视频
                    for item in response.get("aweme_list", []):
                        aweme_id = item.get("aweme_id")
                        video = {
                            "video_id": aweme_id,
                            "title": item.get("desc", ""),
                            "url": get_correct_douyin_url(aweme_id, item),  # 使用正确的URL格式
                            "cover_url": _safe_douyin_cover_url(item),
                            "publish_time": item.get("create_time"),
                            "stats": {
                                "digg_count": item.get("statistics", {}).get("digg_count", 0),
                                "comment_count": item.get("statistics", {}).get("comment_count", 0),
                                "share_count": item.get("statistics", {}).get("share_count", 0)
                            }
                        }
                        all_videos.append(video)
                    
                    logger.info(f"点赞列表同步完成，共获取 {len(all_videos)} 个视频")
            else:
                # 用户视频订阅：分页加载
                # 使用task_context防止浏览器被空闲超时关闭
                async with unified_browser.task_context("douyin", "sync_user_videos"):
                    max_cursor = 0
                    empty_page_count = 0  # 连续空页面计数
                    max_empty_pages = 5   # 最多允许5个连续空页面
                    page_count = 0
                    total_sleep_seconds = 0.0
                    
                    while True:
                        page_count += 1
                        response = await douyin_api.get_user_videos(
                            user_id,
                            max_count=30,
                            max_cursor=max_cursor
                        )
                        
                        # 检查API响应
                        if not response:
                            logger.warning("API返回空响应，终止分页")
                            break
                        
                        # 获取分页信息
                        has_more = response.get("has_more", False)
                        max_cursor_raw = response.get("max_cursor", 0)
                        # 确保 max_cursor 是整数类型
                        try:
                            max_cursor = int(max_cursor_raw) if max_cursor_raw else 0
                        except (ValueError, TypeError):
                            max_cursor = 0
                        aweme_list = response.get("aweme_list", [])
                        
                        # 处理视频数据
                        if aweme_list:
                            empty_page_count = 0  # 重置空页面计数
                            logger.debug(f"当前页获取到 {len(aweme_list)} 个视频, 累计 {len(all_videos)+len(aweme_list)} 个")
                            videos = []
                            for item in aweme_list:
                                aweme_id = item.get("aweme_id")
                                video = {
                                    "video_id": aweme_id,
                                    "title": item.get("desc", ""),
                                    "url": get_correct_douyin_url(aweme_id, item),  # 使用正确的URL格式
                                    "cover_url": _safe_douyin_cover_url(item),
                                    "publish_time": item.get("create_time"),
                                    "stats": {
                                        "digg_count": item.get("statistics", {}).get("digg_count", 0),
                                        "comment_count": item.get("statistics", {}).get("comment_count", 0),
                                        "share_count": item.get("statistics", {}).get("share_count", 0)
                                    }
                                }
                                videos.append(video)
                            
                            # ⚡️ 优化：使用 process_video_batch 进行流式入库，不依赖外部db
                            await process_video_batch(videos)
                            
                            all_videos.extend(videos)
                            
                            # 更新同步进度
                            subscription.sync_progress = len(all_videos)

                            # 发送进度更新
                            await send_progress_update(subscription_id, {
                                "type": "sync_progress",
                                "status": "syncing",
                                "count": len(all_videos)
                            })
                            
                            # 如果当前页有数据，即使 has_more=0，只要 max_cursor 有值就继续
                            # 因为有些情况下 API 可能返回 has_more=0 但仍有更多数据
                            if max_cursor > 0:
                                logger.debug(f"当前页有数据且 max_cursor={max_cursor}，继续请求下一页")
                        else:
                            # 当前页为空
                            empty_page_count += 1
                            logger.debug(f"当前页为空 (连续{empty_page_count}次), has_more={has_more}, max_cursor={max_cursor}")
                            
                            # 如果连续多个空页面，可能是API问题，提前退出
                            if empty_page_count >= max_empty_pages:
                                logger.warning(f"连续{empty_page_count}个空页面，终止分页")
                                break
                        
                        # 检查是否还有更多数据
                        # 停止条件：has_more=0 且 (max_cursor=0 或当前页为空且连续空页面达到上限)
                        # 如果当前页有数据且 max_cursor>0，即使 has_more=0 也继续
                        should_stop = False
                        if not has_more:
                            if max_cursor == 0:
                                should_stop = True
                                logger.info(f"分页结束: has_more={has_more}, max_cursor={max_cursor}, 已获取{len(all_videos)}个视频")
                            elif not aweme_list and empty_page_count >= max_empty_pages:
                                should_stop = True
                                logger.warning(f"分页结束: 连续{empty_page_count}个空页面且 has_more={has_more}, max_cursor={max_cursor}, 已获取{len(all_videos)}个视频")
                            else:
                                logger.debug(f"has_more=0 但 max_cursor={max_cursor} 且当前页有数据，继续分页")
                        
                        if should_stop:
                            break
                        
                        # 添加延时避免请求过快
                        delay_seconds = _douyin_request_delay_seconds(page_count, mode="sync")
                        total_sleep_seconds += delay_seconds
                        await asyncio.sleep(delay_seconds)
                    logger.info(
                        "[DouyinAntiRisk] 抖音博主同步分页完成: pages=%d induced_sleep=%.2fs fetched=%d",
                        page_count,
                        total_sleep_seconds,
                        len(all_videos),
                    )

        elif platform == "douyin_collection":
            logger.info("使用抖音合集API获取视频列表")
            # 抖音合集视频获取逻辑（分页）
            cursor = 0
            has_more = True
            page_count = 0
            total_sleep_seconds = 0.0
            while has_more:
                page_count += 1
                try:
                    response = await get_collection_videos(collection_id or user_id, cursor=cursor, count=50)
                except Exception as e:
                    raise HTTPException(status_code=500, detail=f"获取合集视频失败: {str(e)}")

                videos = []
                for item in (response.get("videos") or []):
                    video = {
                        "video_id": item.get("video_id"),
                        "title": item.get("title", ""),
                        "url": item.get("url"),
                        "cover_url": item.get("cover_url"),
                        "publish_time": item.get("publish_time"),  # 秒级时间戳
                        "stats": {
                            "play_count": (item.get("play_count") or 0)
                        }
                    }
                    videos.append(video)

                # ⚡️ 优化：使用 process_video_batch 进行流式入库
                await process_video_batch(videos)
                
                all_videos.extend(videos)

                # 🔧 修复：不再直接修改 subscription 对象，因为连接已关闭
                # 同步进度通过 send_progress_update 发送，不需要更新数据库

                # 发送进度更新
                await send_progress_update(subscription_id, {
                    "type": "sync_progress",
                    "status": "syncing",
                    "count": len(all_videos)
                })

                has_more = bool(response.get("has_more"))
                cursor = int(response.get("next_cursor", 0)) if has_more else cursor
                if not has_more:
                    break
                delay_seconds = _douyin_request_delay_seconds(page_count, mode="sync")
                total_sleep_seconds += delay_seconds
                await asyncio.sleep(delay_seconds)
            logger.info(
                "[DouyinAntiRisk] 抖音合集同步分页完成: pages=%d induced_sleep=%.2fs fetched=%d",
                page_count,
                total_sleep_seconds,
                len(all_videos),
            )
                
        elif platform == "youtube":
            logger.info("使用YouTube API获取内容列表")
            # YouTube内容获取逻辑（全量同步，类似抖音）
            tab_type = youtube_tab_type or "videos"  # 默认videos
            
            page_token = ""
            retry_count = 0
            max_retries = 3
            
            # 为Shorts生成全局基准时间戳，确保多页获取时排序正确
            base_timestamp = None
            if tab_type == "shorts":
                base_timestamp = int(datetime.now().timestamp())
            
            # 使用task_context防止浏览器被空闲超时关闭
            async with unified_browser.task_context("youtube", "sync_channel_videos"):
                while True:
                    try:
                        response = await youtube_api.get_channel_videos(
                            user_id,
                            max_count=30,  # 每页30个内容
                            page_token=page_token,
                            tab_type=tab_type,
                            base_timestamp=base_timestamp,  # 传递基准时间戳
                            start_index=len(all_videos)  # 传递当前已获取的视频数
                        )
                    
                        if not response:
                            # 检查是否是首次请求就失败，如果是则可能是配置问题
                            if not all_videos and not page_token:
                                logger.warning(f"YouTube API首次请求就返回空响应，可能是配置问题")
                                # 直接跳出循环，让后续的空视频处理逻辑来处理
                                break
                            else:
                                logger.warning(f"YouTube API返回空响应，可能已获取完所有视频")
                                break
                        
                        # 处理视频数据（全量获取，不过滤已存在的视频）
                        videos = []
                        for item in response.get("items", []):
                            video_id = item.get("id", {}).get("videoId", "")
                            snippet = item.get("snippet", {})
                            raw_published_at = snippet.get("publishedAt")
                            logger.debug(
                                f"[YT_RAW_TIME] mode=channel tab_type={tab_type} video_id={video_id} "
                                f"raw_published_at={raw_published_at}"
                            )
                            video = {
                                "video_id": video_id,
                                "title": snippet.get("title", ""),
                                "url": f"https://www.youtube.com/watch?v={video_id}",
                                "cover_url": snippet.get("thumbnails", {}).get("high", {}).get("url"),
                                "publish_time": raw_published_at,
                                "stats": {
                                    "view_count": item.get("statistics", {}).get("viewCount", 0),
                                    "like_count": item.get("statistics", {}).get("likeCount", 0),
                                    "comment_count": item.get("statistics", {}).get("commentCount", 0)
                                }
                            }
                            videos.append(video)
                        
                        # ⚡️ 优化：使用 process_video_batch 进行流式入库
                        await process_video_batch(videos)
                        
                        # 添加所有视频到列表
                        all_videos.extend(videos)
                        
                        # 记录当前页面的处理情况
                        total_items = len(response.get("items", []))
                        logger.info(f"当前页面处理: 总视频{total_items}个，累计获取{len(all_videos)}个")
                        retry_count = 0  # 重置重试计数
                        
                        # 🔧 优化：使用独立短连接更新同步进度，避免访问已分离的对象
                        progress_db = get_session()
                        try:
                            progress_subscription = progress_db.query(Subscription).filter(
                                Subscription.id == subscription_id
                            ).first()
                            if progress_subscription:
                                progress_subscription.sync_progress = len(all_videos)
                                progress_db.commit()
                        except Exception as e:
                            logger.debug(f"更新同步进度失败: {str(e)}")
                            progress_db.rollback()
                        finally:
                            progress_db.close()

                        # 发送进度更新
                        await send_progress_update(subscription_id, {
                            "type": "sync_progress",
                            "status": "syncing",
                            "count": len(all_videos)
                        })
                        
                        # 获取下一页的令牌
                        page_token = response.get("nextPageToken")
                        if not page_token:
                            logger.info(f"没有更多页面，同步完成，共获取 {len(all_videos)} 个视频")
                            break
                        
                        # 添加延时避免请求过快
                        await asyncio.sleep(random.uniform(0.5, 1.0))
                        
                    except Exception as e:
                        retry_count += 1
                        error_msg = f"获取YouTube视频失败 (第{retry_count}次): {str(e)}"
                        logger.error(error_msg)
                        
                        # 检查是否是YouTube API配置相关错误
                        is_config_error = any([
                            "400" in str(e),
                            "Request contains an invalid argument" in str(e),
                            "badRequest" in str(e),
                            "INVALID_ARGUMENT" in str(e)
                        ])
                        
                        # 发送错误进度更新
                        progress_update = {
                            "type": "sync_error",
                            "status": "error", 
                            "message": error_msg,
                            "retry_count": retry_count
                        }
                        
                        # 如果是配置错误，添加智能提示
                        if is_config_error:
                            progress_update["suggestion"] = {
                                "action": "check_update_first",
                                "text": "💡 建议：先点击\"检查更新\"按钮刷新YouTube配置后再重试同步",
                                "reason": "检测到API配置问题，检查更新功能可以重新初始化YouTube配置"
                            }
                        
                        await send_progress_update(subscription_id, progress_update)
                        
                        if retry_count >= max_retries:
                            logger.error(f"重试{max_retries}次后仍然失败，停止同步")
                            
                            # 对于配置错误，提供更友好的错误信息
                            if is_config_error:
                                raise HTTPException(
                                    status_code=500,
                                    detail=f"YouTube同步失败，建议先点击\"检查更新\"刷新配置后重试。错误详情: {str(e)}"
                                )
                            else:
                                raise HTTPException(
                                    status_code=500, 
                                    detail=f"YouTube同步失败: {str(e)}"
                                )
                        
                        # 等待后重试
                        wait_time = min(2 ** retry_count, 30)  # 指数退避，最大30秒
                        logger.info(f"等待{wait_time}秒后重试...")
                        await asyncio.sleep(wait_time)
                    
        elif platform == "youtube_playlist":
            logger.info("使用YouTube播放列表API获取视频列表")
            # YouTube播放列表视频获取逻辑（全量同步）
            playlist_id = user_id  # 播放列表ID存储在user_id中
            
            # 发送开始获取视频的进度更新
            await send_progress_update(subscription_id, {
                "type": "sync_progress",
                "status": "syncing",
                "message": "正在获取YouTube播放列表视频...",
                "count": 0
            })
            
            page_token = ""
            retry_count = 0
            max_retries = 3
            # 添加循环保护机制
            empty_response_count = 0  # 连续空响应计数
            max_empty_responses = 3   # 最大连续空响应次数
            max_loop_iterations = 1000  # 最大循环次数，支持更大播放列表 (1000 * 50 = 50000 视频)
            loop_count = 0
            
            while True:
                # 检查循环次数限制
                loop_count += 1
                if loop_count > max_loop_iterations:
                    logger.warning(f"播放列表同步达到最大循环次数限制 ({max_loop_iterations})，强制退出")
                    break
                
                try:
                    # 使用内部API调用获取播放列表视频
                    from routers.youtube import get_playlist_videos
                    response = await get_playlist_videos(
                        playlist_id,
                        max_count=30,  # 每页30个视频
                        page_token=page_token
                    )
                    
                    if not response:
                        # 检查是否是首次请求就失败
                        if not all_videos and not page_token:
                            logger.warning(f"YouTube播放列表API首次请求就返回空响应，可能是配置问题")
                            break
                        else:
                            logger.warning(f"YouTube播放列表API返回空响应，可能已获取完所有视频")
                            break
                    
                    # 处理视频数据（全量获取，不过滤已存在的视频）
                    videos = []
                    for item in response.get("items", []):
                        video_id = item.get("id", {}).get("videoId", "")
                        snippet = item.get("snippet", {})
                        raw_published_at = snippet.get("publishedAt")
                        logger.debug(
                            f"[YT_RAW_TIME] mode=playlist video_id={video_id} raw_published_at={raw_published_at}"
                        )
                        video = {
                            "video_id": video_id,
                            "title": snippet.get("title", ""),
                            "url": f"https://www.youtube.com/watch?v={video_id}",
                            "cover_url": snippet.get("thumbnails", {}).get("high", {}).get("url"),
                            "publish_time": raw_published_at,
                            "stats": {
                                "view_count": item.get("statistics", {}).get("viewCount", 0),
                                "like_count": item.get("statistics", {}).get("likeCount", 0),
                                "comment_count": item.get("statistics", {}).get("commentCount", 0)
                            }
                        }
                        videos.append(video)
                    
                    # ⚡️ 优化：使用 process_video_batch 进行流式入库
                    await process_video_batch(videos)
                    
                    # 添加所有视频到列表
                    all_videos.extend(videos)
                    
                    # 记录当前页面的处理情况
                    total_items = len(response.get("items", []))
                    logger.info(f"播放列表当前页面处理: 总视频{total_items}个，累计获取{len(all_videos)}个")
                    
                    # 检查连续空响应
                    if total_items == 0:
                        empty_response_count += 1
                        logger.warning(f"获取到空响应，连续空响应次数: {empty_response_count}/{max_empty_responses}")
                        if empty_response_count >= max_empty_responses:
                            logger.warning(f"连续 {max_empty_responses} 次空响应，可能遇到API问题，强制退出同步")
                            break
                    else:
                        empty_response_count = 0  # 重置空响应计数
                    
                    retry_count = 0  # 重置重试计数
                    
                    # 🔧 优化：使用独立短连接更新同步进度，避免访问已分离的对象
                    progress_db = get_session()
                    try:
                        progress_subscription = progress_db.query(Subscription).filter(
                            Subscription.id == subscription_id
                        ).first()
                        if progress_subscription:
                            progress_subscription.sync_progress = len(all_videos)
                            progress_db.commit()
                    except Exception as e:
                        logger.debug(f"更新同步进度失败: {str(e)}")
                        progress_db.rollback()
                    finally:
                        progress_db.close()
                    
                    # 发送进度更新（每次获取到视频后立即更新）
                    await send_progress_update(subscription_id, {
                        "type": "sync_progress",
                        "status": "syncing",
                        "message": f"正在同步播放列表视频... 已获取 {len(all_videos)} 个视频",
                        "count": len(all_videos)
                    })
                    
                    # 获取下一页的令牌
                    page_token = response.get("nextPageToken")
                    if not page_token:
                        logger.info(f"播放列表没有更多页面，同步完成，共获取 {len(all_videos)} 个视频")
                        # 发送完成获取视频列表的进度更新
                        await send_progress_update(subscription_id, {
                            "type": "sync_progress",
                            "status": "syncing",
                            "message": f"视频列表获取完成，共 {len(all_videos)} 个视频，正在处理数据...",
                            "count": len(all_videos)
                        })
                        break
                    
                    # 额外的安全检查：如果有nextPageToken但连续获取空响应，也要退出
                    if page_token and empty_response_count > 0:
                        logger.warning(f"存在nextPageToken但获取到空响应，可能API异常，token: {page_token[:20]}...")
                        # 如果连续空响应已经在上面处理了，这里就不需要额外处理
                    
                    # 添加延时避免请求过快
                    await asyncio.sleep(random.uniform(0.5, 1.0))
                    
                except Exception as e:
                    retry_count += 1
                    error_msg = f"获取YouTube播放列表视频失败 (第{retry_count}次): {str(e)}"
                    logger.error(error_msg)
                    
                    # 检查是否是YouTube API配置相关错误
                    is_config_error = any([
                        "400" in str(e),
                        "Request contains an invalid argument" in str(e),
                        "badRequest" in str(e),
                        "INVALID_ARGUMENT" in str(e)
                    ])
                    
                    # 发送错误进度更新
                    progress_update = {
                        "type": "sync_error",
                        "status": "error", 
                        "message": error_msg,
                        "retry_count": retry_count
                    }
                    
                    # 如果是配置错误，添加智能提示
                    if is_config_error:
                        progress_update["suggestion"] = {
                            "action": "check_update_first",
                            "text": "💡 建议：先点击\"检查更新\"按钮刷新YouTube配置后再重试同步",
                            "reason": "检测到API配置问题，检查更新功能可以重新初始化YouTube配置"
                        }
                    
                    await send_progress_update(subscription_id, progress_update)
                    
                    if retry_count >= max_retries:
                        logger.error(f"重试{max_retries}次后仍然失败，停止同步")
                        
                        # 对于配置错误，提供更友好的错误信息
                        if is_config_error:
                            raise HTTPException(
                                status_code=500,
                                detail=f"YouTube播放列表同步失败，建议先点击\"检查更新\"刷新配置后重试。错误详情: {str(e)}"
                            )
                        else:
                            raise HTTPException(
                                status_code=500, 
                                detail=f"YouTube播放列表同步失败: {str(e)}"
                            )
                    
                    # 等待后重试
                    wait_time = min(2 ** retry_count, 30)  # 指数退避，最大30秒
                    logger.info(f"等待{wait_time}秒后重试...")
                    await asyncio.sleep(wait_time)
                    
        elif platform == "bilibili":
            # 判断是UP主订阅还是收藏夹订阅
            if subscription_type == "favorite":
                # B站收藏夹同步逻辑
                logger.info("使用yt-dlp获取B站收藏夹所有视频")
                try:
                    from routers.bilibili import get_bilibili_favorite_videos
                    import os
                    
                    fav_id = user_id
                    cookies_path = "/app/database/cookie/bilibili_cookie.txt"
                    
                    # 发送开始获取视频的进度更新
                    await send_progress_update(subscription_id, {
                        "type": "sync_progress",
                        "status": "syncing",
                        "message": "正在获取B站收藏夹视频列表...",
                        "count": 0
                    })

                    async def _bilibili_favorite_progress_callback(payload: dict):
                        try:
                            await send_progress_update(subscription_id, payload)
                        except Exception as e:
                            logger.debug(f"B站收藏夹分页进度推送失败: {str(e)}")
                    
                    # 获取收藏夹所有视频（获取详细信息）
                    videos_list = await get_bilibili_favorite_videos(
                        fav_id,
                        cookies_path,
                        extract_flat=False,  # 获取详细信息，包括标题、UP主、时长等
                        max_count=None,  # 获取全部视频
                        progress_callback=_bilibili_favorite_progress_callback
                    )
                    
                    if not videos_list:
                        logger.warning("收藏夹中没有视频或无法获取视频列表")
                        all_videos = []
                    else:
                        # 处理视频数据
                        videos = []
                        for i, item in enumerate(videos_list):
                            video = {
                                "video_id": item.get("video_id", ""),
                                "title": item.get("title", ""),
                                "url": item.get("url", ""),
                                "cover_url": item.get("cover_url", ""),
                                "publish_time": item.get("publish_time", ""),
                                "stats": {
                                    "duration": item.get("duration", 0),
                                    "uploader": item.get("uploader", ""),
                                    "uploader_id": item.get("uploader_id", "")
                                },
                                "is_charging_arc": item.get("is_charging_arc", False)
                            }
                            videos.append(video)
                            
                            # 每处理10个视频发送一次进度更新
                            if (i + 1) % 10 == 0:
                                await send_progress_update(subscription_id, {
                                    "type": "sync_progress",
                                    "status": "syncing",
                                    "message": f"正在处理视频数据... ({i + 1}/{len(videos_list)})",
                                    "count": i + 1
                                })
                        
                        # ⚡️ 优化：使用 process_video_batch 进行流式入库
                        await process_video_batch(videos)
                        
                        all_videos = videos
                        
                        # 发送视频获取完成的进度更新
                        await send_progress_update(subscription_id, {
                            "type": "sync_progress",
                            "status": "syncing",
                            "message": f"收藏夹视频列表获取完成，共 {len(all_videos)} 个视频",
                            "count": len(all_videos)
                        })
                        
                        # 🔧 优化：使用独立短连接更新同步进度和视频数量，避免访问已分离的对象
                        progress_db = get_session()
                        try:
                            progress_subscription = progress_db.query(Subscription).filter(
                                Subscription.id == subscription_id
                            ).first()
                            if progress_subscription:
                                progress_subscription.sync_progress = len(all_videos)
                                progress_subscription.video_count = len(all_videos)
                                progress_db.commit()
                        except Exception as e:
                            logger.debug(f"更新同步进度失败: {str(e)}")
                            progress_db.rollback()
                        finally:
                            progress_db.close()
                        
                        logger.info(f"B站收藏夹同步完成，共获取 {len(all_videos)} 个视频")
                    
                except Exception as e:
                    error_msg = f"获取B站收藏夹视频失败: {str(e)}"
                    logger.error(error_msg)
                    
                    # 发送错误进度更新
                    await send_progress_update(subscription_id, {
                        "type": "sync_error",
                        "status": "error",
                        "message": error_msg
                    })
                    
                    raise HTTPException(
                        status_code=500, 
                        detail=f"B站收藏夹同步失败: {str(e)}"
                    )
            else:
                # B站UP主同步逻辑（原有逻辑）
                logger.info("使用B站API分页获取所有视频")
                try:
                    from routers.bilibili import bilibili_api
                        
                    # 发送开始获取视频的进度更新
                    await send_progress_update(subscription_id, {
                        "type": "sync_progress",
                        "status": "syncing",
                        "message": "正在获取B站视频列表...",
                        "count": 0
                    })
                    
                    # 定义进度回调函数
                    async def bilibili_progress_callback(progress_data):
                        """B站同步进度回调"""
                        try:
                            # 根据进度类型发送不同的更新
                            if progress_data.get("type") == "page_progress":
                                # 分页进度
                                message = progress_data.get("message", "")
                                current_page = progress_data.get("current_page", 0)
                                total_pages = progress_data.get("total_pages", 0)
                                count = progress_data.get("count", 0)
                                
                                await send_progress_update(subscription_id, {
                                    "type": "sync_progress",
                                    "status": "syncing",
                                    # 移除message，让前端统一显示"已同步 N 个视频"
                                    "count": count
                                })
                            elif progress_data.get("type") == "time_progress":
                                # 获取发布时间进度
                                message = progress_data.get("message", "")
                                current = progress_data.get("current", 0)
                                total = progress_data.get("total", 0)
                                
                                await send_progress_update(subscription_id, {
                                    "type": "sync_progress",
                                    "status": "syncing",
                                    "message": f"{message} ({current}/{total})",
                                    "count": current
                                })
                        except Exception as e:
                            logger.warning(f"发送B站进度更新失败: {str(e)}")
                    
                    # 获取所有分页视频（max_count=-1表示获取所有分页视频）
                    # 使用task_context防止浏览器被空闲超时关闭
                    async with unified_browser.task_context("bilibili", "sync_up_videos"):
                        response = await bilibili_api.get_up_videos_queued(
                            user_id,
                            max_count=-1,  # 同步时获取所有分页视频
                            progress_callback=bilibili_progress_callback
                        )
                    
                    if not response:
                        logger.warning(f"B站API返回空响应")
                        all_videos = []
                    else:
                        # 处理视频数据
                        videos = []
                        for i, item in enumerate(response):
                            # 修复：从URL中正确提取BV号，而不是spm_id_from参数
                            url = item.get("url", "")
                            video_id = ""
                            if url:
                                # 使用正则表达式提取BV号
                                import re
                                bv_match = re.search(r'/video/(BV[\w]+)', url)
                                if bv_match:
                                    video_id = bv_match.group(1)
                                else:
                                    # 如果无法提取BV号，使用原始URL
                                    video_id = url
                            
                            video = {
                                "video_id": video_id,
                                "title": item.get("title", ""),
                                "url": item.get("url", ""),
                                "cover_url": item.get("cover_url", ""),
                                "publish_time": item.get("publish_time_parsed", ""),
                                "stats": {
                                    "play_count": item.get("play_count", 0),
                                    "like_count": 0,  # B站API不提供点赞数
                                    "duration": item.get("duration", "")
                                },
                                "is_charging_arc": item.get("is_charging_arc", False)
                            }
                            videos.append(video)
                            
                            # 每处理10个视频发送一次进度更新
                            if (i + 1) % 10 == 0:
                                await send_progress_update(subscription_id, {
                                    "type": "sync_progress",
                                    "status": "syncing",
                                    "message": f"正在处理视频数据... ({i + 1}/{len(response)})",
                                    "count": i + 1
                                })
                        
                        # ⚡️ 优化：使用 process_video_batch 进行流式入库
                        
                        # 如果开启了跳过充电专属视频，过滤掉它们
                        if response and skip_bilibili_upower:
                            original_count = len(videos)
                            videos = [v for v in videos if not v.get("is_charging_arc")]
                            filtered_count = original_count - len(videos)
                            if filtered_count > 0:
                                logger.info(f"已根据设置过滤掉 {filtered_count} 个充电专属视频")

                        await process_video_batch(videos)
                        
                        all_videos = videos
                        
                        # 发送视频获取完成的进度更新
                        await send_progress_update(subscription_id, {
                            "type": "sync_progress",
                            "status": "syncing",
                            "message": f"视频列表获取完成，共 {len(all_videos)} 个视频",
                            "count": len(all_videos)
                        })
                        
                        # 🔧 优化：使用独立短连接更新同步进度，避免访问已分离的对象
                        progress_db = get_session()
                        try:
                            progress_subscription = progress_db.query(Subscription).filter(
                                Subscription.id == subscription_id
                            ).first()
                            if progress_subscription:
                                progress_subscription.sync_progress = len(all_videos)
                                progress_db.commit()
                        except Exception as e:
                            logger.debug(f"更新同步进度失败: {str(e)}")
                            progress_db.rollback()
                        finally:
                            progress_db.close()

                        # 发送最终进度更新
                        await send_progress_update(subscription_id, {
                            "type": "sync_progress",
                            "status": "syncing",
                            "count": len(all_videos)
                        })
                        
                        logger.info(f"B站同步完成，共获取 {len(all_videos)} 个视频（分页获取）")
                        
                except Exception as e:
                    error_msg = f"获取B站视频失败: {str(e)}"
                    logger.error(error_msg)
                    
                    # 发送错误进度更新
                    await send_progress_update(subscription_id, {
                        "type": "sync_error",
                        "status": "error",
                        "message": error_msg
                    })
                    
                    raise HTTPException(
                        status_code=500, 
                        detail=f"B站同步失败: {str(e)}"
                    )
        
        elif platform == "bilibili_collection":
            logger.info("使用B站API获取合集所有视频")
            # B站合集视频获取逻辑
            try:
                # 发送开始获取视频的进度更新
                await send_progress_update(subscription_id, {
                    "type": "sync_progress",
                    "status": "syncing",
                    "message": "正在获取B站合集视频列表...",
                    "count": 0
                })
                
                # 定义进度回调函数
                async def bilibili_collection_progress_callback(progress_data):
                    """B站合集同步进度回调"""
                    try:
                        if progress_data.get("type") == "page_progress":
                            message = progress_data.get("message", "")
                            current_page = progress_data.get("current_page", 0)
                            total_pages = progress_data.get("total_pages", 0)
                            count = progress_data.get("count", 0)
                            
                            await send_progress_update(subscription_id, {
                                "type": "sync_progress",
                                "status": "syncing",
                                # 移除message，让前端统一显示"已同步 N 个视频"
                                "count": count
                            })
                    except Exception as e:
                        logger.warning(f"发送B站合集同步进度更新失败: {str(e)}")
                
                # 获取合集的所有视频
                from routers.bilibili import bilibili_api
                response = await bilibili_api.get_collection_videos_queued(
                    user_id,  # BV号
                    progress_callback=bilibili_collection_progress_callback
                )
                
                if not response:
                    raise Exception("无法获取合集视频列表")
                
                # 处理视频数据
                videos = []
                for i, item in enumerate(response):
                    video_id = item.get("video_id", "")
                    
                    video = {
                        "video_id": video_id,
                        "title": item.get("title", ""),
                        "url": item.get("url", ""),
                        "cover_url": item.get("cover_url", ""),
                        "publish_time": item.get("publish_time", ""),
                        "extra_data": {
                            "section_title": item.get("section_title", ""),
                            "episode_title": item.get("episode_title", ""),
                            "root_bvid": item.get("root_bvid", ""),
                            "root_bvid_title": item.get("root_bvid_title", ""),
                        },
                        "stats": {
                            "page": item.get("page", 1),
                            "cid": item.get("cid", ""),
                            "duration": item.get("duration", ""),
                            "author": item.get("author", ""),
                            "author_id": item.get("author_id", ""),
                            "section_title": item.get("section_title", ""),
                            "episode_title": item.get("episode_title", ""),
                            "root_bvid": item.get("root_bvid", ""),
                            "root_bvid_title": item.get("root_bvid_title", "")
                        }
                    }
                    videos.append(video)
                    
                    # 每处理10个视频发送一次进度更新
                    if (i + 1) % 10 == 0:
                        await send_progress_update(subscription_id, {
                            "type": "sync_progress",
                            "status": "syncing",
                            "message": f"正在处理合集视频数据... ({i + 1}/{len(response)})",
                            "count": i + 1
                        })
                
                # ⚡️ 优化：使用 process_video_batch 进行流式入库
                
                # 如果开启了跳过充电专属视频，过滤掉它们
                if skip_bilibili_upower:
                    original_count = len(videos)
                    videos = [v for v in videos if not v.get("is_charging_arc")]
                    filtered_count = original_count - len(videos)
                    if filtered_count > 0:
                        logger.info(f"已根据设置过滤掉 {filtered_count} 个充电专属视频")

                await process_video_batch(videos)
                
                all_videos = videos
                
                # 发送视频获取完成的进度更新
                await send_progress_update(subscription_id, {
                    "type": "sync_progress",
                    "status": "syncing",
                    "message": f"合集视频列表获取完成，共 {len(all_videos)} 个视频",
                    "count": len(all_videos)
                })
                
                # 🔧 优化：使用独立短连接更新同步进度，避免访问已分离的对象
                progress_db = get_session()
                try:
                    progress_subscription = progress_db.query(Subscription).filter(
                        Subscription.id == subscription_id
                    ).first()
                    if progress_subscription:
                        progress_subscription.sync_progress = len(all_videos)
                        progress_db.commit()
                except Exception as e:
                    logger.debug(f"更新同步进度失败: {str(e)}")
                    progress_db.rollback()
                finally:
                    progress_db.close()
                
                logger.info(f"B站合集同步完成，共获取 {len(all_videos)} 个视频")
                
            except Exception as e:
                error_msg = f"获取B站合集视频失败: {str(e)}"
                logger.error(error_msg)
                
                # 发送错误进度更新
                await send_progress_update(subscription_id, {
                    "type": "sync_error",
                    "status": "error",
                    "message": error_msg
                })
                
                raise HTTPException(
                    status_code=500, 
                    detail=f"B站合集同步失败: {str(e)}"
                )
        
        elif platform == "tiktok":
            logger.info("使用TikTok API获取所有视频")
            # TikTok视频获取逻辑 - 全量同步
            from routers.tiktok import tiktok_api
            try:
                # 发送开始同步的进度更新
                await send_progress_update(subscription_id, {
                    "type": "sync_progress",
                    "status": "syncing",
                    "message": "正在全量同步TikTok视频，请稍候...",
                    "count": 0
                })
                
                # 构建用户主页URL
                user_url = f"https://www.tiktok.com/@{user_id}"
                
                # === TikTok 全量同步策略 ===
                # 手动同步时，全量获取所有视频，与抖音等平台保持一致
                logger.info("开始全量同步TikTok视频...")

                async def _tiktok_sync_progress_callback(payload: dict):
                    try:
                        await send_progress_update(subscription_id, payload)
                    except Exception as e:
                        logger.debug(f"TikTok分页进度推送失败: {str(e)}")
                
                # 执行全量拉取 API（max_count 设置为很大的值以获取所有视频）
                videos_result = await tiktok_api.get_user_videos(
                    user_url,
                    max_count=None,  # 全量同步走分页抓取，避免单次拉取过大
                    progress_callback=_tiktok_sync_progress_callback
                )
                
                if not videos_result or not videos_result.get("videos"):
                    logger.warning(f"TikTok API返回空响应")
                    all_videos = []
                else:
                    # 处理视频数据
                    videos = []
                    videos_list = videos_result["videos"]
                    
                    for i, item in enumerate(videos_list):
                        video_id = item.get("video_id", "")
                        
                        # 构建完整的视频URL
                        video_url = item.get("video_url", "")
                        if not video_url and video_id:
                            # 如果没有完整URL，根据video_id构建
                            video_url = f"https://www.tiktok.com/@{user_id}/video/{video_id}"
                        
                        video = {
                            "video_id": video_id,
                            "title": item.get("title", ""),
                            "url": video_url,
                            "cover_url": item.get("cover_url", ""),
                            "publish_time": item.get("create_time", 0),  # TikTok返回时间戳
                            "stats": {
                                "view_count": item.get("view_count", 0),
                                "like_count": item.get("like_count", 0),
                                "comment_count": item.get("comment_count", 0),
                                "share_count": item.get("share_count", 0),
                                "duration": item.get("duration", 0)
                            }
                        }
                        videos.append(video)
                        
                        # 每处理10个视频发送一次进度更新
                        if (i + 1) % 10 == 0:
                            await send_progress_update(subscription_id, {
                                "type": "sync_progress",
                                "status": "syncing",
                                "message": f"正在处理视频数据... ({i + 1}/{len(videos_list)})",
                                "count": i + 1
                            })
                    
                    # ⚡️ 优化：使用 process_video_batch 进行流式入库
                    await process_video_batch(videos)
                    
                    all_videos = videos
                    
                    # 发送视频获取完成的进度更新
                    await send_progress_update(subscription_id, {
                        "type": "sync_progress",
                        "status": "syncing",
                        "message": f"视频列表获取完成，共 {len(all_videos)} 个视频",
                        "count": len(all_videos)
                    })
                    
                    # 更新同步进度
                    subscription.sync_progress = len(all_videos)
                    
                    logger.info(f"TikTok同步完成，共获取 {len(all_videos)} 个视频")
                    
            except Exception as e:
                error_msg = f"获取TikTok视频失败: {str(e)}"
                logger.error(error_msg)
                
                # 发送错误进度更新
                await send_progress_update(subscription_id, {
                    "type": "sync_error",
                    "status": "error",
                    "message": error_msg
                })
                
                raise HTTPException(
                    status_code=500, 
                    detail=f"TikTok同步失败: {str(e)}"
                )

        elif platform == "instagram":
            logger.info("使用Instagram适配器全量同步媒体")
            instagram_adapter = registry.get_adapter("instagram")
            if not instagram_adapter:
                raise HTTPException(status_code=400, detail="Instagram平台适配器未找到")
            try:
                await send_progress_update(subscription_id, {
                    "type": "sync_progress",
                    "status": "syncing",
                    "message": "正在获取Instagram媒体列表...",
                    "count": 0
                })

                all_videos = []

                async def instagram_progress_callback(progress_data):
                    await send_progress_update(subscription_id, {
                        "type": "sync_progress",
                        "status": "syncing",
                        "message": progress_data.get("message") or f"已获取Instagram媒体 {progress_data.get('current', 0)} 条",
                        "count": progress_data.get("current", 0)
                    })

                async def instagram_batch_callback(batch_items):
                    normalized_batch = []
                    start_index = len(all_videos)
                    for item in batch_items:
                        try:
                            normalized_batch.append(instagram_adapter.normalize_video_data(item, "user"))
                        except Exception as normalize_error:
                            logger.warning(f"跳过无效Instagram媒体: {normalize_error}")

                    if not normalized_batch:
                        return

                    await process_video_batch(normalized_batch)
                    all_videos.extend(normalized_batch)
                    await send_progress_update(subscription_id, {
                        "type": "sync_progress",
                        "status": "syncing",
                        "message": f"已保存Instagram媒体 {len(all_videos)} 条（本批 {len(normalized_batch)} 条）",
                        "count": len(all_videos)
                    })

                if hasattr(instagram_adapter, "iter_all_videos"):
                    await instagram_adapter.iter_all_videos(
                        user_id,
                        subscription_type="user",
                        page_size=50,
                        max_count=None,
                        progress_callback=instagram_progress_callback,
                        batch_callback=instagram_batch_callback
                    )
                else:
                    all_items = await instagram_adapter.get_all_videos(
                        user_id,
                        subscription_type="user"
                    )
                    for i, item in enumerate(all_items):
                        video = instagram_adapter.normalize_video_data(item, "user")
                        all_videos.append(video)
                        if (i + 1) % 20 == 0:
                            await send_progress_update(subscription_id, {
                                "type": "sync_progress",
                                "status": "syncing",
                                "message": f"正在处理Instagram媒体... ({i + 1}/{len(all_items)})",
                                "count": i + 1
                            })
                    await process_video_batch(all_videos)

                await send_progress_update(subscription_id, {
                    "type": "sync_progress",
                    "status": "syncing",
                    "message": f"Instagram媒体列表获取完成，共 {len(all_videos)} 条",
                    "count": len(all_videos)
                })

                progress_db = get_session()
                try:
                    progress_subscription = progress_db.query(Subscription).filter(
                        Subscription.id == subscription_id
                    ).first()
                    if progress_subscription:
                        progress_subscription.sync_progress = len(all_videos)
                        if videos:
                            cover = videos[0].get("cover_url")
                            if cover:
                                progress_subscription.avatar_url = cover
                        progress_db.commit()
                except Exception as e:
                    logger.debug(f"更新同步进度失败: {str(e)}")
                    progress_db.rollback()
                finally:
                    progress_db.close()

                logger.info(f"Instagram同步完成，共获取 {len(all_videos)} 条媒体")
            except HTTPException:
                raise
            except Exception as e:
                error_msg = f"获取Instagram媒体失败: {str(e)}"
                logger.error(error_msg)
                await send_progress_update(subscription_id, {
                    "type": "sync_error",
                    "status": "error",
                    "message": error_msg
                })
                from routers import instagram as instagram_api
                if instagram_api.is_instagram_risk_error(str(e)):
                    raise HTTPException(status_code=429, detail=f"Instagram同步触发风控，已停止本次同步: {str(e)}")
                raise HTTPException(status_code=500, detail=f"Instagram同步失败: {str(e)}")

        elif platform == "xiaohongshu":
            logger.info("使用小红书适配器全量同步笔记")
            xiaohongshu_adapter = registry.get_adapter("xiaohongshu")
            if not xiaohongshu_adapter:
                raise HTTPException(status_code=400, detail="小红书平台适配器未找到")
            if not profile_url or "xsec_token" not in profile_url:
                raise HTTPException(
                    status_code=400,
                    detail="同步小红书笔记需要带 xsec_token 的创作者主页链接。请删除该订阅后，从浏览器地址栏复制完整链接重新添加。"
                )
            try:
                await send_progress_update(subscription_id, {
                    "type": "sync_progress",
                    "status": "syncing",
                    "message": "正在获取小红书笔记列表...",
                    "count": 0
                })

                async def xhs_progress_callback(progress_data):
                    try:
                        current = progress_data.get("current", 0)
                        await send_progress_update(subscription_id, {
                            "type": "sync_progress",
                            "status": "syncing",
                            "message": progress_data.get("message", f"已获取 {current} 条笔记"),
                            "count": current
                        })
                    except Exception as e:
                        logger.warning(f"发送小红书同步进度失败: {str(e)}")

                async with unified_browser.task_context("xiaohongshu", "sync_notes"):
                    all_notes = await xiaohongshu_adapter.get_all_videos(
                        user_id,
                        subscription_type="user",
                        progress_callback=xhs_progress_callback,
                        profile_url=profile_url
                    )
                logger.info("[XhsAntiRisk] 小红书全量同步拉取完成: notes=%d", len(all_notes))

                videos = []
                for i, note in enumerate(all_notes):
                    video = xiaohongshu_adapter.normalize_video_data(note, "user")
                    videos.append(video)
                    if (i + 1) % 10 == 0:
                        await send_progress_update(subscription_id, {
                            "type": "sync_progress",
                            "status": "syncing",
                            "message": f"正在处理笔记数据... ({i + 1}/{len(all_notes)})",
                            "count": i + 1
                        })

                await process_video_batch(videos)
                all_videos = videos

                await send_progress_update(subscription_id, {
                    "type": "sync_progress",
                    "status": "syncing",
                    "message": f"笔记列表获取完成，共 {len(all_videos)} 条",
                    "count": len(all_videos)
                })
                progress_db = get_session()
                try:
                    progress_subscription = progress_db.query(Subscription).filter(
                        Subscription.id == subscription_id
                    ).first()
                    if progress_subscription:
                        progress_subscription.sync_progress = len(all_videos)
                        progress_db.commit()
                except Exception as e:
                    logger.debug(f"更新同步进度失败: {str(e)}")
                    progress_db.rollback()
                finally:
                    progress_db.close()
                logger.info(f"小红书同步完成，共获取 {len(all_videos)} 条笔记")
            except HTTPException:
                raise
            except Exception as e:
                error_msg = f"获取小红书笔记失败: {str(e)}"
                logger.error(error_msg)
                await send_progress_update(subscription_id, {
                    "type": "sync_error",
                    "status": "error",
                    "message": error_msg
                })
                raise HTTPException(status_code=500, detail=f"小红书同步失败: {str(e)}")
        
        elif platform == "netease":
            logger.info("使用网易云适配器全量同步歌单歌曲")
            netease_adapter = registry.get_adapter("netease")
            if not netease_adapter:
                raise HTTPException(status_code=400, detail="网易云平台适配器未找到")

            try:
                await send_progress_update(subscription_id, {
                    "type": "sync_progress",
                    "status": "syncing",
                    "message": "正在获取网易云歌单歌曲列表...",
                    "count": 0
                })

                async def netease_progress_callback(progress_data):
                    try:
                        current = progress_data.get("current", 0)
                        await send_progress_update(subscription_id, {
                            "type": "sync_progress",
                            "status": "syncing",
                            "message": progress_data.get("message", f"已获取 {current} 首歌曲"),
                            "count": current
                        })
                    except Exception as e:
                        logger.warning(f"发送网易云同步进度失败: {str(e)}")

                all_songs = await netease_adapter.get_all_videos(
                    user_id,
                    subscription_type="playlist",
                    progress_callback=netease_progress_callback
                )

                videos = []
                for i, song in enumerate(all_songs):
                    video = netease_adapter.normalize_video_data(song, "playlist")
                    videos.append(video)
                    if (i + 1) % 20 == 0:
                        await send_progress_update(subscription_id, {
                            "type": "sync_progress",
                            "status": "syncing",
                            "message": f"正在处理歌曲数据... ({i + 1}/{len(all_songs)})",
                            "count": i + 1
                        })

                await process_video_batch(videos)
                all_videos = videos

                await send_progress_update(subscription_id, {
                    "type": "sync_progress",
                    "status": "syncing",
                    "message": f"歌曲列表获取完成，共 {len(all_videos)} 首",
                    "count": len(all_videos)
                })

                progress_db = get_session()
                try:
                    progress_subscription = progress_db.query(Subscription).filter(
                        Subscription.id == subscription_id
                    ).first()
                    if progress_subscription:
                        progress_subscription.sync_progress = len(all_videos)
                        progress_db.commit()
                except Exception as e:
                    logger.debug(f"更新同步进度失败: {str(e)}")
                    progress_db.rollback()
                finally:
                    progress_db.close()

                logger.info(f"网易云歌单同步完成，共获取 {len(all_videos)} 首歌曲")
            except HTTPException:
                raise
            except Exception as e:
                error_msg = f"获取网易云歌单歌曲失败: {str(e)}"
                logger.error(error_msg)
                await send_progress_update(subscription_id, {
                    "type": "sync_error",
                    "status": "error",
                    "message": error_msg
                })
                raise HTTPException(status_code=500, detail=f"网易云同步失败: {str(e)}")
        
        elif platform == "x":
            logger.info("使用X适配器全量同步点赞视频")
            x_adapter = registry.get_adapter("x")
            if not x_adapter:
                raise HTTPException(status_code=400, detail="X平台适配器未找到")
            try:
                await send_progress_update(subscription_id, {
                    "type": "sync_progress",
                    "status": "syncing",
                    "message": "正在获取X点赞视频列表...",
                    "count": 0
                })

                items = await x_adapter.get_all_videos(
                    user_id,
                    subscription_type="favorite",
                    max_count=None
                )
                videos = []
                for i, item in enumerate(items):
                    video = x_adapter.normalize_video_data(item, "favorite")
                    videos.append(video)
                    if (i + 1) % 20 == 0:
                        await send_progress_update(subscription_id, {
                            "type": "sync_progress",
                            "status": "syncing",
                            "message": f"正在处理点赞数据... ({i + 1}/{len(items)})",
                            "count": i + 1
                        })

                await process_video_batch(videos)
                all_videos = videos

                await send_progress_update(subscription_id, {
                    "type": "sync_progress",
                    "status": "syncing",
                    "message": f"点赞列表获取完成，共 {len(all_videos)} 条",
                    "count": len(all_videos)
                })
                progress_db = get_session()
                try:
                    progress_subscription = progress_db.query(Subscription).filter(
                        Subscription.id == subscription_id
                    ).first()
                    if progress_subscription:
                        progress_subscription.sync_progress = len(all_videos)
                        # 使用最新一条视频封面作为头像
                        if videos:
                            cover = videos[0].get("cover_url")
                            if cover:
                                progress_subscription.avatar_url = cover
                        progress_db.commit()
                except Exception as e:
                    logger.debug(f"更新同步进度失败: {str(e)}")
                    progress_db.rollback()
                finally:
                    progress_db.close()

                logger.info(f"X点赞同步完成，共获取 {len(all_videos)} 条")
            except HTTPException:
                raise
            except Exception as e:
                error_msg = f"获取X点赞失败: {str(e)}"
                logger.error(error_msg)
                await send_progress_update(subscription_id, {
                    "type": "sync_error",
                    "status": "error",
                    "message": error_msg
                })
                raise HTTPException(status_code=500, detail=f"X同步失败: {str(e)}")
        
        else:
            raise HTTPException(status_code=400, detail=f"不支持的平台类型: {platform}")

        # 4. 保护性判断：若未获取到任何视频，跳过清理，避免误删（如私密账号/受限）
        if len(all_videos) == 0:
            logger.warning(
                f"同步结果为空，已跳过清理以保护历史记录：{nickname} (平台: {platform}, 用户ID: {user_id})"
            )
            # 🔧 优化：使用独立短连接更新状态
            update_db = get_session()
            try:
                # 重新查询并更新，因为 subscription 对象可能已过期
                update_subscription = update_db.query(Subscription).filter(
                    Subscription.id == subscription_id
                ).first()
                if update_subscription:
                    update_subscription.sync_status = "skipped"
                    update_subscription.sync_progress = 0
                    update_db.commit()
            finally:
                update_db.close()

            # 根据平台类型提供不同的提示
            if platform == "youtube":
                # 发送YouTube特定的跳过状态和建议
                await send_progress_update(subscription_id, {
                    "type": "sync_progress",
                    "status": "skipped",
                    "message": "未获取到任何YouTube视频，可能是配置问题",
                    "count": 0,
                    "suggestion": {
                        "action": "check_update_first",
                        "text": "💡 建议：先点击\"检查更新\"按钮刷新YouTube配置后再重试同步",
                        "reason": "未获取到视频可能是API配置或认证问题，检查更新可以重新初始化配置"
                    }
                })
                
                # 🚀 优化：即使跳过也清理标签页
                try:
                    await _cleanup_subscription_pages(platform, user_id)
                except Exception as cleanup_error:
                    logger.debug(f"清理标签页失败: {str(cleanup_error)}")
                
                return {
                    "message": "未获取到任何YouTube视频，建议先点击\"检查更新\"刷新配置后重试同步",
                    "total_videos": 0,
                    "new_videos": 0,
                    "deleted_videos": 0,
                    "suggestion": "请先使用检查更新功能刷新YouTube配置"
                }
            else:
                # 其他平台的默认处理
                await send_progress_update(subscription_id, {
                    "type": "sync_progress",
                    "status": "skipped", 
                    "message": "未获取到任何视频，可能为私密账号或网络受限，已跳过清理",
                    "count": 0
                })
                
                # 🚀 优化：即使跳过也清理标签页
                try:
                    await _cleanup_subscription_pages(platform, user_id)
                except Exception as cleanup_error:
                    logger.debug(f"清理标签页失败: {str(cleanup_error)}")
                
                return {
                    "message": "未获取到任何视频，可能为私密账号或网络受限，已跳过清理以保护历史记录",
                    "total_videos": 0,
                    "new_videos": 0,
                    "deleted_videos": 0
                }

        # 5. 获取数据库中的所有视频
        # 🔧 优化：使用独立短连接，避免长连接超时
        from sqlalchemy.exc import OperationalError, DisconnectionError, InvalidRequestError, PendingRollbackError
        
        existing_videos = []
        query_db = get_session()
        try:
            existing_videos = query_db.query(SubscriptionVideo).filter(
                SubscriptionVideo.subscription_id == subscription_id
            ).all()
        finally:
            query_db.close()

        # 创建当前视频ID集合（包含新获取的视频）
        current_video_ids = {video["video_id"] for video in all_videos}
        
        # 记录删除和新增的数量
        deleted_count = 0
        new_videos_count = 0

        # 6. 删除已不存在的视频（但保留已下载的）
        # 🔧 优化：使用独立短连接批量处理删除和更新
        kept_count = 0
        if existing_videos:
            delete_db = get_session()
            try:
                # 批量查询需要删除和更新的视频
                videos_to_delete = []
                videos_to_update = []
                
                for video in existing_videos:
                    if video.video_id not in current_video_ids:
                        # 检查视频是否已下载
                        if video.downloaded == "true":
                            logger.debug(f"视频已从源平台移除但本地已下载，保留记录: {video.title} (平台: {platform})")
                            videos_to_update.append((video.id, video.extra_data))
                            kept_count += 1
                        else:
                            logger.debug(f"视频已从源平台移除且未下载，从数据库中删除: {video.title} (平台: {platform})")
                            videos_to_delete.append(video.id)
                            deleted_count += 1
                
                # 批量删除
                if videos_to_delete:
                    delete_db.query(SubscriptionVideo).filter(
                        SubscriptionVideo.id.in_(videos_to_delete)
                    ).delete(synchronize_session=False)
                
                # 批量更新标记
                if videos_to_update:
                    for video_id, extra_data in videos_to_update:
                        try:
                            video_obj = delete_db.query(SubscriptionVideo).filter(
                                SubscriptionVideo.id == video_id
                            ).first()
                            if video_obj:
                                extra = json.loads(extra_data or '{}')
                                extra['removed_from_source'] = True
                                extra['removed_at'] = datetime.now().isoformat()
                                video_obj.extra_data = json.dumps(extra)
                        except Exception as e:
                            logger.warning(f"更新视频标记失败: {str(e)}")
                
                delete_db.commit()
                logger.info(f"已处理不存在的视频: 删除{deleted_count}个, 保留已下载{kept_count}个")
            except Exception as e:
                delete_db.rollback()
                logger.error(f"删除视频失败: {str(e)}")
                raise
            finally:
                delete_db.close()

        # 7. 添加或更新视频
        # 🔧 优化：process_video 使用独立短连接，避免并发冲突和长连接超时
        async def process_video(video):
            # 使用独立短连接处理每个视频
            local_db = get_session()
            try:
                # 检查视频是否已存在
                existing_video = local_db.query(SubscriptionVideo).filter(
                    SubscriptionVideo.subscription_id == subscription_id,
                    SubscriptionVideo.video_id == video["video_id"]
                ).first()
                
                if existing_video:
                    # 🔧 检查并更新URL格式（针对抖音平台）
                    if platform == "douyin" and existing_video.url != video["url"]:
                        logger.info(f"更新视频URL格式: {video['video_id']} {existing_video.url} -> {video['url']}")
                        existing_video.url = video["url"]
                    
                    # 🔄 更新已存在视频的信息（包括缩略图，因为缩略图URL可能会失效）
                    existing_video.title = video["title"]
                    if video.get("cover_url"):
                        existing_video.cover_url = video["cover_url"]
                    
                    # 处理时间格式
                    if platform == "youtube" or platform == "youtube_playlist":
                        try:
                            publish_time_str = video.get("publish_time", "")
                            if publish_time_str:
                                publish_time = datetime.fromisoformat(publish_time_str.replace('Z', '+00:00'))
                            else:
                                publish_time = datetime.now()
                        except:
                            publish_time = datetime.now()
                    elif platform == "bilibili":
                        try:
                            if ":" in video["publish_time"]:
                                publish_time = datetime.fromisoformat(video["publish_time"])
                            else:
                                current_year = datetime.now().year
                                date_str = f"{current_year}-{video['publish_time']} 00:00:00"
                                publish_time = datetime.fromisoformat(date_str)
                        except Exception as e:
                            logger.warning(f"B站时间解析失败: {video['publish_time']}, 错误: {str(e)}, 使用当前时间")
                            publish_time = datetime.now()
                    elif platform == "bilibili_collection":
                        try:
                            publish_time = datetime.fromisoformat(video["publish_time"])
                        except Exception as e:
                            logger.warning(f"B站合集时间解析失败: {video['publish_time']}, 错误: {str(e)}, 使用当前时间")
                            publish_time = datetime.now()
                    elif platform == "tiktok":
                        try:
                            publish_time = datetime.fromtimestamp(int(video["publish_time"]))
                        except Exception as e:
                            logger.warning(f"TikTok时间解析失败: {video['publish_time']}, 错误: {str(e)}, 使用当前时间")
                            publish_time = datetime.now()
                    elif isinstance(video.get("publish_time"), datetime):
                        # 小红书等适配器已返回 datetime
                        publish_time = video["publish_time"]
                    else:
                        try:
                            publish_time = datetime.fromtimestamp(int(video["publish_time"]))
                        except Exception:
                            publish_time = datetime.now()
                    
                    # 对于没有真实发布时间的内容类型，需要更新publish_time以保持正确的顺序
                    if (platform == Platform.DOUYIN.value and subscription_type == 'favorite') or \
                       (platform == Platform.YOUTUBE.value and youtube_tab_type == 'shorts'):
                        existing_video.publish_time = publish_time
                    
                    # 更新extra_data，如果视频重新出现在源平台，清除removed_from_source标记
                    try:
                        extra = json.loads(existing_video.extra_data or '{}')
                        if extra.get('removed_from_source'):
                            logger.info(f"视频重新出现在源平台，清除移除标记: {existing_video.title}")
                            extra.pop('removed_from_source', None)
                            extra.pop('removed_at', None)
                        extra['publish_time_text'] = publish_time.strftime("%Y-%m-%d %H:%M:%S")
                        extra['stats'] = video["stats"]
                        # 合并规范化后的 extra_data，支持历史数据回填（如 B站合集 root_bvid/section_title）
                        extra_update = video.get("extra_data") or {}
                        for k, v in extra_update.items():
                            if v is not None:
                                extra[k] = v
                        existing_video.extra_data = json.dumps(extra)
                    except Exception as e:
                        logger.warning(f"更新extra_data失败: {str(e)}")
                        existing_video.extra_data = json.dumps({
                            "publish_time_text": publish_time.strftime("%Y-%m-%d %H:%M:%S"),
                            "stats": video["stats"],
                            **(video.get("extra_data") or {}),
                        })
                    
                    local_db.commit()
                    return  # 已存在的视频，更新完成
                
                if not existing_video:
                    # 添加新视频
                    # 处理不同平台的时间格式
                    if platform == "youtube" or platform == "youtube_playlist":
                        try:
                            # YouTube和播放列表返回的是ISO 8601格式，如 "2024-01-01T12:00:00Z"
                            publish_time_str = video.get("publish_time", "")
                            if publish_time_str:
                                publish_time = datetime.fromisoformat(publish_time_str.replace('Z', '+00:00'))
                            else:
                                publish_time = datetime.now()
                        except:
                            # 如果解析失败，使用当前时间
                            publish_time = datetime.now()
                    elif platform == "bilibili":
                        try:
                            # B站现在返回的是从详情页获取的准确时间，如 "2025-08-20 20:00:00"
                            # 或者原始的粗略时间，如 "08-20"
                            # 或者ISO格式时间，如 "2020-05-09T00:00:00Z" 或 "2020-05-09T00:00:00+00:00"
                            publish_time_str = video["publish_time"]
                            if ":" in publish_time_str:
                                # 包含时分秒的完整时间
                                # 处理Z后缀（Python 3.11之前不支持）
                                if publish_time_str.endswith("Z"):
                                    publish_time_str = publish_time_str.replace("Z", "+00:00")
                                publish_time = datetime.fromisoformat(publish_time_str)
                            else:
                                # 只有日期的粗略时间，需要补充年份和时分秒
                                current_year = datetime.now().year
                                date_str = f"{current_year}-{video['publish_time']} 00:00:00"
                                publish_time = datetime.fromisoformat(date_str)
                        except Exception as e:
                            logger.warning(f"B站时间解析失败: {video['publish_time']}, 错误: {str(e)}, 使用当前时间")
                            publish_time = datetime.now()
                    elif platform == "bilibili_collection":
                        try:
                            # B站合集使用ISO格式时间，处理Z后缀（Python 3.11之前不支持）
                            publish_time_str = video["publish_time"]
                            if publish_time_str.endswith("Z"):
                                publish_time_str = publish_time_str.replace("Z", "+00:00")
                            publish_time = datetime.fromisoformat(publish_time_str)
                        except Exception as e:
                            logger.warning(f"B站合集时间解析失败: {video['publish_time']}, 错误: {str(e)}, 使用当前时间")
                            publish_time = datetime.now()
                    elif platform == "tiktok":
                        try:
                            # TikTok使用时间戳（秒）
                            publish_time = datetime.fromtimestamp(int(video["publish_time"]))
                        except Exception as e:
                            logger.warning(f"TikTok时间解析失败: {video['publish_time']}, 错误: {str(e)}, 使用当前时间")
                            publish_time = datetime.now()
                    elif isinstance(video.get("publish_time"), datetime):
                        # 小红书等适配器已返回 datetime
                        publish_time = video["publish_time"]
                    else:
                        # 抖音等平台使用时间戳
                        try:
                            publish_time = datetime.fromtimestamp(int(video["publish_time"]))
                        except Exception:
                            publish_time = datetime.now()
                    
                    new_video = SubscriptionVideo(
                        subscription_id=subscription_id,
                        video_id=video["video_id"],
                        title=_truncate_video_title(video["title"]),
                        url=video["url"],
                        cover_url=video["cover_url"],
                        publish_time=publish_time,
                        downloaded="false",
                        created_at=datetime.now(),
                        extra_data=json.dumps({
                            "publish_time_text": publish_time.strftime("%Y-%m-%d %H:%M:%S"),
                            "stats": video["stats"],
                            **(video.get("extra_data") or {}),
                        })
                    )
                    # 在添加到数据库前设置UUID
                    new_video.id = str(uuid.uuid4())
                    local_db.add(new_video)
                    local_db.commit()
                    return True
            except Exception as e:
                local_db.rollback()
                logger.error(f"处理视频失败 {video.get('video_id', 'unknown')}: {str(e)}")
                return False
            finally:
                local_db.close()

        # 并行处理所有视频
        tasks = [process_video(video) for video in all_videos]
        results = await asyncio.gather(*tasks)
        new_videos_count = sum(1 for r in results if r)

        logger.info(f"同步完成统计: 总视频数={len(all_videos)}, 新增视频数={new_videos_count}, 删除视频数={deleted_count}, 保留已下载视频数={kept_count}")

        # 7. 更新同步状态为完成并更新订阅信息
        # 🔧 优化：使用独立短连接更新状态
        update_db = get_session()
        try:
            # 重新查询并更新，因为 subscription 对象可能已过期
            update_subscription = update_db.query(Subscription).filter(
                Subscription.id == subscription_id
            ).first()
            if update_subscription:
                update_subscription.sync_status = "completed"
                update_subscription.last_check = datetime.now()
                
                # 更新最新视频信息
                if all_videos:
                    # 按发布时间排序所有视频（避免置顶视频的影响）
                    def get_publish_timestamp(video):
                        if platform == "youtube" or platform == "youtube_playlist":
                            try:
                                publish_time_str = video.get("publish_time", "")
                                if publish_time_str:
                                    return datetime.fromisoformat(publish_time_str.replace('Z', '+00:00')).timestamp()
                                else:
                                    return datetime.now().timestamp()
                            except:
                                return datetime.now().timestamp()
                        elif platform == "bilibili":
                            try:
                                if ":" in video["publish_time"]:
                                    return datetime.fromisoformat(video["publish_time"]).timestamp()
                                else:
                                    current_year = datetime.now().year
                                    date_str = f"{current_year}-{video['publish_time']} 00:00:00"
                                    return datetime.fromisoformat(date_str).timestamp()
                            except:
                                return datetime.now().timestamp()
                        elif platform == "bilibili_collection":
                            try:
                                return datetime.fromisoformat(video["publish_time"]).timestamp()
                            except:
                                return datetime.now().timestamp()
                        elif platform == "tiktok":
                            try:
                                return datetime.fromtimestamp(int(video["publish_time"])).timestamp()
                            except:
                                return datetime.now().timestamp()
                        elif isinstance(video.get("publish_time"), datetime):
                            return video["publish_time"].timestamp()
                        else:
                            try:
                                return datetime.fromtimestamp(int(video["publish_time"])).timestamp()
                            except:
                                return datetime.now().timestamp()
                    
                    sorted_videos = sorted(all_videos, key=get_publish_timestamp, reverse=True)
                    latest_video = sorted_videos[0]
                    
                    # 根据平台类型解析最新视频时间
                    if platform == "youtube" or platform == "youtube_playlist":
                        try:
                            publish_time_str = latest_video.get("publish_time", "")
                            if publish_time_str:
                                update_subscription.latest_video_time = datetime.fromisoformat(publish_time_str.replace('Z', '+00:00'))
                            else:
                                update_subscription.latest_video_time = datetime.now()
                        except:
                            update_subscription.latest_video_time = datetime.now()
                    elif platform == "bilibili":
                        try:
                            if ":" in latest_video["publish_time"]:
                                update_subscription.latest_video_time = datetime.fromisoformat(latest_video["publish_time"])
                            else:
                                current_year = datetime.now().year
                                date_str = f"{current_year}-{latest_video['publish_time']} 00:00:00"
                                update_subscription.latest_video_time = datetime.fromisoformat(date_str)
                        except Exception as e:
                            logger.warning(f"B站最新视频时间解析失败: {latest_video['publish_time']}, 错误: {str(e)}, 使用当前时间")
                            update_subscription.latest_video_time = datetime.now()
                    elif platform == "bilibili_collection":
                        try:
                            update_subscription.latest_video_time = datetime.fromisoformat(latest_video["publish_time"])
                        except Exception as e:
                            logger.warning(f"B站合集最新视频时间解析失败: {latest_video['publish_time']}, 错误: {str(e)}, 使用当前时间")
                            update_subscription.latest_video_time = datetime.now()
                    elif isinstance(latest_video.get("publish_time"), datetime):
                        update_subscription.latest_video_time = latest_video["publish_time"]
                    else:
                        try:
                            update_subscription.latest_video_time = datetime.fromtimestamp(int(latest_video["publish_time"]))
                        except Exception:
                            update_subscription.latest_video_time = datetime.now()
                    update_subscription.latest_video_title = _truncate_video_title(latest_video["title"])
                    update_subscription.latest_video_cover = latest_video["cover_url"]
                    
                    logger.info(f"最新视频: {latest_video['title']} (发布时间: {latest_video['publish_time']})")
                
                update_db.commit()
        finally:
            update_db.close()

        logger.info(f"订阅同步完成: {nickname}")

        # 🚀 优化：任务完成后主动清理对应的标签页
        try:
            await _cleanup_subscription_pages(platform, user_id)
        except Exception as e:
            logger.warning(f"清理订阅标签页失败: {str(e)}")

        # 发送 Telegram 通知
        try:
            from routers.telegram_bot import telegram_bot
            if telegram_bot.is_running:
                await telegram_bot.send_sync_complete_notification(
                    subscription_nickname=nickname,
                    total_videos=len(all_videos),
                    new_videos=new_videos_count,
                    deleted_videos=deleted_count
                )
        except Exception as e:
            logger.warning(f"发送 Telegram 同步完成通知失败: {str(e)}")

        # 发送完成状态
        await send_progress_update(subscription_id, {
            "type": "sync_progress",
            "status": "completed",
            "count": len(all_videos)
        })

        if progress_callback:
            res_data = {
                "message": "同步完成",
                "total_videos": len(all_videos),
                "new_videos": new_videos_count,
                "deleted_videos": deleted_count,
                "kept_downloaded_videos": kept_count
            }
            asyncio.create_task(progress_callback(len(all_videos), finished=True, result=res_data))

        return {
            "message": "同步完成",
            "total_videos": len(all_videos),
            "new_videos": new_videos_count,
            "deleted_videos": deleted_count,
            "kept_downloaded_videos": kept_count
        }

    except Exception as e:
        logger.error(f"同步视频失败: {str(e)}")
        
        if progress_callback:
            asyncio.create_task(progress_callback(total_fetched_count if 'total_fetched_count' in locals() else 0, finished=True, error=e))
            
        # 🔧 优化：使用独立短连接更新错误状态
        if subscription_id:
            error_db = get_session()
            try:
                error_subscription = error_db.query(Subscription).filter(
                    Subscription.id == subscription_id
                ).first()
                if error_subscription:
                    error_subscription.sync_status = "error"
                    error_subscription.error_message = str(e)
                    error_db.commit()
            except Exception as update_error:
                logger.error(f"更新错误状态失败: {str(update_error)}")
                error_db.rollback()
            finally:
                error_db.close()
            # 发送错误状态
            sync_progress = 0
            platform = None
            user_id = None
            if subscription_id:
                # 获取订阅信息用于清理标签页
                try:
                    info_db = get_session()
                    try:
                        info_subscription = info_db.query(Subscription).filter(
                            Subscription.id == subscription_id
                        ).first()
                        if info_subscription:
                            sync_progress = info_subscription.sync_progress or 0
                            platform = info_subscription.platform
                            user_id = info_subscription.user_id
                    finally:
                        info_db.close()
                except Exception:
                    pass



@router.post("/check_all")
@require_license_api
async def check_all_subscriptions(request: Request, db: Session = Depends(get_db)):
    """批量检测订阅更新"""
    try:
        # 服务端校验口令（当天日期）
        secret = request.headers.get('X-Admin-Secret', '')
        if secret != _expected_dev_secret():
            raise HTTPException(status_code=403, detail="Forbidden")

        # 获取非暂停的订阅
        subscriptions = db.query(Subscription).filter(
            Subscription.status != SubscriptionStatus.PAUSED.value
        ).all()

        enqueued = 0
        for sub in subscriptions:
            sub_id = sub.id
            # 交由全局调度器的并发限流执行
            asyncio.create_task(scheduler._limited_check(sub_id))
            enqueued += 1

        return {"message": "已批量发起订阅检测", "enqueued": enqueued}
    except Exception as e:
        logger.error(f"批量检测订阅更新失败: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/sync_all")
@require_license_api
async def sync_all_subscriptions(request: Request, db: Session = Depends(get_db)):
    """批量同步订阅视频（注意：受并发限流保护）"""
    try:
        # 服务端校验口令（当天日期）
        secret = request.headers.get('X-Admin-Secret', '')
        if secret != _expected_dev_secret():
            raise HTTPException(status_code=403, detail="Forbidden")

        subscriptions = db.query(Subscription).filter(
            Subscription.status != SubscriptionStatus.PAUSED.value
        ).all()

        async def _limited_sync(sub_id: str):
            # 复用调度器的全局信号量，避免占满连接池
            async with scheduler._semaphore:  # noqa: SLF001 访问受控属性用于限流
                await sync_videos(sub_id)

        enqueued = 0
        for sub in subscriptions:
            asyncio.create_task(_limited_sync(sub.id))
            enqueued += 1

        return {"message": "已批量发起视频同步", "enqueued": enqueued}
    except Exception as e:
        logger.error(f"批量同步订阅视频失败: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/batch_check_filtered")
@require_license_api
async def batch_check_filtered(
    request: Request,
    subscription_ids: List[str] = Body(...),
    db: Session = Depends(get_db)
):
    """批量检测指定的订阅更新（后台异步执行）"""
    try:
        # 服务端校验口令（当天日期）
        secret = request.headers.get('X-Admin-Secret', '')
        if secret != _expected_dev_secret():
            raise HTTPException(status_code=403, detail="Forbidden")
        # 验证订阅ID是否存在
        valid_ids = []
        for sub_id in subscription_ids:
            sub = db.query(Subscription).filter(Subscription.id == sub_id).first()
            if sub:
                valid_ids.append(sub_id)
        
        if not valid_ids:
            raise HTTPException(status_code=400, detail="没有有效的订阅ID")
        
        # 按平台分组，每个平台创建一个后台任务
        platform_groups = {}
        for sub_id in valid_ids:
            sub = db.query(Subscription).filter(Subscription.id == sub_id).first()
            if sub:
                platform = sub.platform
                if platform not in platform_groups:
                    platform_groups[platform] = []
                platform_groups[platform].append(sub_id)
        
        async def _check_platform_group(platform: str, sub_ids: List[str], task_id: str):
            """检测单个平台的所有订阅（YouTube并发，其他串行）"""
            # 获取平台并发数，默认为1（串行）
            concurrent_limit = PLATFORM_CONCURRENT_LIMITS.get(platform, 1)
            concurrency_desc = f"{concurrent_limit}个并发" if concurrent_limit > 1 else "串行"
            logger.info(f"开始批量检测 {platform} 平台的 {len(sub_ids)} 个订阅（{concurrency_desc}）")
            
            from routers.websocket import manager
            try:
                # 推送任务开始消息
                await manager.broadcast_message("batch_tasks", {
                    "type": "batch_check_progress",
                    "task_id": task_id,
                    "platform": platform,
                    "status": "started",
                    "total": len(sub_ids),
                    "checked": 0,
                    "message": f"开始检测 {platform} 平台（{concurrency_desc}）"
                })
                
                checked_count = 0
                
                if concurrent_limit > 1:
                    # 并发处理（仅YouTube）
                    platform_semaphore = asyncio.Semaphore(concurrent_limit)
                    progress_lock = asyncio.Lock()
                    
                    async def _check_single_subscription(sub_id: str):
                        nonlocal checked_count
                        try:
                            async with platform_semaphore:  # 平台内并发限制
                                # 注意：scheduler._limited_check 内部已经有信号量，这里不需要再获取
                                logger.info(f"开始并发检测订阅: {sub_id} (平台: {platform})")
                                await scheduler._limited_check(sub_id, cleanup_page=False)
                                logger.info(f"完成并发检测订阅: {sub_id}")
                            
                            # 线程安全地更新计数和进度
                            async with progress_lock:
                                checked_count += 1
                                current_count = checked_count
                            
                            # 推送进度更新
                            await manager.broadcast_message("batch_tasks", {
                                "type": "batch_check_progress",
                                "task_id": task_id,
                                "platform": platform,
                                "status": "running",
                                "total": len(sub_ids),
                                "checked": current_count,
                                "message": f"{platform} 平台: 已完成 {current_count}/{len(sub_ids)}"
                            })
                        except Exception as e:
                            logger.error(f"检测订阅 {sub_id} 失败: {str(e)}", exc_info=True)
                            # 线程安全地更新计数
                            async with progress_lock:
                                checked_count += 1
                                current_count = checked_count
                            
                            # 即使失败也推送进度
                            await manager.broadcast_message("batch_tasks", {
                                "type": "batch_check_progress",
                                "task_id": task_id,
                                "platform": platform,
                                "status": "running",
                                "total": len(sub_ids),
                                "checked": current_count,
                                "message": f"{platform} 平台: 已完成 {current_count}/{len(sub_ids)} (有失败)"
                            })
                    
                    # 创建所有检测任务并等待完成
                    tasks = [_check_single_subscription(sub_id) for sub_id in sub_ids]
                    await asyncio.gather(*tasks, return_exceptions=True)
                else:
                    # 串行处理（抖音、B站等）
                    for idx, sub_id in enumerate(sub_ids, 1):
                        try:
                            logger.info(f"开始检测订阅 {idx}/{len(sub_ids)}: {sub_id} (平台: {platform})")
                            # 注意：scheduler._limited_check 内部已经有信号量，这里不需要再获取
                            await scheduler._limited_check(sub_id, cleanup_page=False)
                            checked_count += 1
                            logger.info(f"完成检测订阅 {idx}/{len(sub_ids)}: {sub_id}")
                            
                            # 推送进度更新
                            await manager.broadcast_message("batch_tasks", {
                                "type": "batch_check_progress",
                                "task_id": task_id,
                                "platform": platform,
                                "status": "running",
                                "total": len(sub_ids),
                                "checked": checked_count,
                                "message": f"{platform} 平台: 已完成 {checked_count}/{len(sub_ids)}"
                            })
                        except Exception as e:
                            logger.error(f"检测订阅 {sub_id} 失败: {str(e)}", exc_info=True)
                            checked_count += 1
                            # 即使失败也推送进度
                            await manager.broadcast_message("batch_tasks", {
                                "type": "batch_check_progress",
                                "task_id": task_id,
                                "platform": platform,
                                "status": "running",
                                "total": len(sub_ids),
                                "checked": checked_count,
                                "message": f"{platform} 平台: 已完成 {checked_count}/{len(sub_ids)} (有失败)"
                            })
                
                # 推送任务完成消息
                await manager.broadcast_message("batch_tasks", {
                    "type": "batch_check_progress",
                    "task_id": task_id,
                    "platform": platform,
                    "status": "completed",
                    "total": len(sub_ids),
                    "checked": checked_count,
                    "message": f"{platform} 平台检测完成"
                })
            except Exception as e:
                logger.error(f"批量检测 {platform} 平台时出错: {str(e)}")
                checked_count = checked_count if 'checked_count' in locals() else 0
                await manager.broadcast_message("batch_tasks", {
                    "type": "batch_check_progress",
                    "task_id": task_id,
                    "platform": platform,
                    "status": "error",
                    "total": len(sub_ids),
                    "checked": checked_count,
                    "message": f"{platform} 平台检测出错: {str(e)}"
                })
            logger.info(f"完成批量检测 {platform} 平台")
            
            # 🚀 优化：批量检测完成后清理平台相关标签页
            try:
                await _cleanup_platform_pages(platform)
            except Exception as e:
                logger.warning(f"清理平台 {platform} 标签页失败: {str(e)}")
        
        # 生成任务ID
        task_id = str(uuid.uuid4())
        
        # 为每个平台创建并发任务
        for platform, sub_ids in platform_groups.items():
            asyncio.create_task(_check_platform_group(platform, sub_ids, task_id))
        
        return {
            "message": "已批量发起订阅检测",
            "total": len(valid_ids),
            "platforms": {k: len(v) for k, v in platform_groups.items()},
            "task_id": task_id
        }
    except Exception as e:
        logger.error(f"批量检测指定订阅失败: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/batch_sync_filtered")
@require_license_api
async def batch_sync_filtered(
    request: Request,
    subscription_ids: List[str] = Body(...),
    db: Session = Depends(get_db)
):
    """批量同步指定的订阅视频（后台异步执行）"""
    try:
        # 服务端校验口令（当天日期）
        secret = request.headers.get('X-Admin-Secret', '')
        if secret != _expected_dev_secret():
            raise HTTPException(status_code=403, detail="Forbidden")
        # 验证订阅ID是否存在
        valid_ids = []
        for sub_id in subscription_ids:
            sub = db.query(Subscription).filter(Subscription.id == sub_id).first()
            if sub:
                valid_ids.append(sub_id)
        
        if not valid_ids:
            raise HTTPException(status_code=400, detail="没有有效的订阅ID")
        
        # 按平台分组，每个平台创建一个后台任务
        platform_groups = {}
        for sub_id in valid_ids:
            sub = db.query(Subscription).filter(Subscription.id == sub_id).first()
            if sub:
                platform = sub.platform
                if platform not in platform_groups:
                    platform_groups[platform] = []
                platform_groups[platform].append(sub_id)
        
        async def _sync_platform_group(platform: str, sub_ids: List[str], task_id: str):
            """同步单个平台的所有订阅（YouTube并发，其他串行）"""
            # 获取平台并发数，默认为1（串行）
            concurrent_limit = PLATFORM_CONCURRENT_LIMITS.get(platform, 1)
            concurrency_desc = f"{concurrent_limit}个并发" if concurrent_limit > 1 else "串行"
            logger.info(f"开始批量同步 {platform} 平台的 {len(sub_ids)} 个订阅（{concurrency_desc}）")
            
            from routers.websocket import manager
            try:
                # 推送任务开始消息
                await manager.broadcast_message("batch_tasks", {
                    "type": "batch_sync_progress",
                    "task_id": task_id,
                    "platform": platform,
                    "status": "started",
                    "total": len(sub_ids),
                    "synced": 0,
                    "message": f"开始同步 {platform} 平台（{concurrency_desc}）"
                })
                
                synced_count = 0
                
                if concurrent_limit > 1:
                    # 并发处理（仅YouTube）
                    platform_semaphore = asyncio.Semaphore(concurrent_limit)
                    progress_lock = asyncio.Lock()
                    
                    async def _sync_single_subscription(sub_id: str):
                        nonlocal synced_count
                        try:
                            async with platform_semaphore:  # 平台内并发限制
                                async with scheduler._semaphore:  # 全局并发限制
                                    await sync_videos(sub_id)
                            
                            # 线程安全地更新计数和进度
                            async with progress_lock:
                                synced_count += 1
                                current_count = synced_count
                            
                            # 推送进度更新
                            await manager.broadcast_message("batch_tasks", {
                                "type": "batch_sync_progress",
                                "task_id": task_id,
                                "platform": platform,
                                "status": "running",
                                "total": len(sub_ids),
                                "synced": current_count,
                                "message": f"{platform} 平台: 已完成 {current_count}/{len(sub_ids)}"
                            })
                        except Exception as e:
                            logger.error(f"同步订阅 {sub_id} 失败: {str(e)}")
                            # 线程安全地更新计数
                            async with progress_lock:
                                synced_count += 1
                                current_count = synced_count
                            
                            # 即使失败也推送进度
                            await manager.broadcast_message("batch_tasks", {
                                "type": "batch_sync_progress",
                                "task_id": task_id,
                                "platform": platform,
                                "status": "running",
                                "total": len(sub_ids),
                                "synced": current_count,
                                "message": f"{platform} 平台: 已完成 {current_count}/{len(sub_ids)} (有失败)"
                            })
                    
                    # 创建所有同步任务并等待完成
                    tasks = [_sync_single_subscription(sub_id) for sub_id in sub_ids]
                    await asyncio.gather(*tasks, return_exceptions=True)
                else:
                    # 串行处理（抖音、B站等）
                    for sub_id in sub_ids:
                        try:
                            async with scheduler._semaphore:
                                await sync_videos(sub_id)
                                synced_count += 1
                                
                                # 推送进度更新
                                await manager.broadcast_message("batch_tasks", {
                                    "type": "batch_sync_progress",
                                    "task_id": task_id,
                                    "platform": platform,
                                    "status": "running",
                                    "total": len(sub_ids),
                                    "synced": synced_count,
                                    "message": f"{platform} 平台: 已完成 {synced_count}/{len(sub_ids)}"
                                })
                        except Exception as e:
                            logger.error(f"同步订阅 {sub_id} 失败: {str(e)}")
                            synced_count += 1
                            # 即使失败也推送进度
                            await manager.broadcast_message("batch_tasks", {
                                "type": "batch_sync_progress",
                                "task_id": task_id,
                                "platform": platform,
                                "status": "running",
                                "total": len(sub_ids),
                                "synced": synced_count,
                                "message": f"{platform} 平台: 已完成 {synced_count}/{len(sub_ids)} (有失败)"
                            })
                
                # 推送任务完成消息
                await manager.broadcast_message("batch_tasks", {
                    "type": "batch_sync_progress",
                    "task_id": task_id,
                    "platform": platform,
                    "status": "completed",
                    "total": len(sub_ids),
                    "synced": synced_count,
                    "message": f"{platform} 平台同步完成"
                })
            except Exception as e:
                logger.error(f"批量同步 {platform} 平台时出错: {str(e)}")
                synced_count = synced_count if 'synced_count' in locals() else 0
                await manager.broadcast_message("batch_tasks", {
                    "type": "batch_sync_progress",
                    "task_id": task_id,
                    "platform": platform,
                    "status": "error",
                    "total": len(sub_ids),
                    "synced": synced_count,
                    "message": f"{platform} 平台同步出错: {str(e)}"
                })
            logger.info(f"完成批量同步 {platform} 平台")
            
            # 🚀 优化：批量同步完成后清理平台相关标签页
            try:
                await _cleanup_platform_pages(platform)
            except Exception as e:
                logger.warning(f"清理平台 {platform} 标签页失败: {str(e)}")
        
        # 生成任务ID
        task_id = str(uuid.uuid4())
        
        # 为每个平台创建并发任务
        for platform, sub_ids in platform_groups.items():
            asyncio.create_task(_sync_platform_group(platform, sub_ids, task_id))
        
        return {
            "message": "已批量发起视频同步",
            "total": len(valid_ids),
            "platforms": {k: len(v) for k, v in platform_groups.items()},
            "task_id": task_id
        }
    except Exception as e:
        logger.error(f"批量同步指定订阅失败: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/batch_task_status")
@require_license_api
async def get_batch_task_status(
    request: Request,
    subscription_ids: List[str] = Body(...),
    task_type: str = Body(..., description="任务类型: check 或 sync"),
    baseline_time: Optional[str] = Body(None, description="基准时间（ISO格式），用于判断任务是否完成"),
    db: Session = Depends(get_db)
):
    """检查批量任务的状态"""
    try:
        if task_type not in ['check', 'sync']:
            raise HTTPException(status_code=400, detail="任务类型必须是 'check' 或 'sync'")
        
        # 获取所有订阅的当前状态
        subscriptions = db.query(Subscription).filter(
            Subscription.id.in_(subscription_ids)
        ).all()
        
        if not subscriptions:
            return {
                "completed": False,
                "total": 0,
                "checked": 0,
                "message": "未找到订阅"
            }
        
        total = len(subscriptions)
        checked_count = 0
        baseline_dt = None
        
        # 解析基准时间
        if baseline_time:
            try:
                baseline_dt = datetime.fromisoformat(baseline_time.replace('Z', '+00:00'))
            except Exception:
                pass
        
        # 检查每个订阅的状态
        for sub in subscriptions:
            if task_type == 'check':
                # 检查last_check是否在基准时间之后更新
                if sub.last_check:
                    if baseline_dt:
                        # 如果有基准时间，检查是否在基准时间之后
                        if sub.last_check > baseline_dt:
                            checked_count += 1
                    else:
                        # 没有基准时间，检查是否在最近5分钟内更新
                        now = datetime.now()
                        time_diff = (now - sub.last_check).total_seconds()
                        if time_diff < 300:  # 5分钟内
                            checked_count += 1
            else:  # sync
                # 检查last_update是否在基准时间之后更新
                if sub.last_update:
                    if baseline_dt:
                        # 如果有基准时间，检查是否在基准时间之后
                        if sub.last_update > baseline_dt:
                            checked_count += 1
                    else:
                        # 没有基准时间，检查是否在最近5分钟内更新
                        now = datetime.now()
                        time_diff = (now - sub.last_update).total_seconds()
                        if time_diff < 300:  # 5分钟内
                            checked_count += 1
        
        # 如果所有订阅都已检查/同步，认为任务完成
        completed = checked_count == total
        
        return {
            "completed": completed,
            "total": total,
            "checked": checked_count,
            "message": f"任务{'已完成' if completed else '进行中'} ({checked_count}/{total})"
        }
        
    except Exception as e:
        logger.error(f"检查批量任务状态失败: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))
