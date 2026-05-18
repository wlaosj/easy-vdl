"""
批量操作相关路由
"""
import uuid
from datetime import datetime
from fastapi import APIRouter, HTTPException, Depends
from sqlalchemy.orm import Session
from sql.database_postgresql import get_db
from sql.models import Subscription, Platform
from routers.auth import require_license_api
from .common import logger
from .models import ImportSubscriptionRequest, ImportSubscriptionResponse

router = APIRouter()


@router.post("/batch_import", response_model=ImportSubscriptionResponse)
@require_license_api
async def batch_import_subscriptions(
    request: ImportSubscriptionRequest,
    db: Session = Depends(get_db)
):
    """批量导入订阅配置"""
    
    try:
        total = len(request.subscriptions)
        success_count = 0
        failed_count = 0
        errors = []
        
        for i, sub_data in enumerate(request.subscriptions):
            try:
                # 验证必要字段
                if not sub_data.get('platform') or not sub_data.get('user_id') or not sub_data.get('nickname'):
                    errors.append(f"订阅 {i+1}: 缺少必要字段 (platform, user_id, nickname)")
                    failed_count += 1
                    continue
                
                # 检查是否已存在相同的订阅
                existing = db.query(Subscription).filter(
                    Subscription.platform == sub_data['platform'],
                    Subscription.user_id == sub_data['user_id']
                ).first()
                
                if existing:
                    if sub_data['platform'] == Platform.DOUYIN.value:
                        platform_name = "抖音博主"
                    elif sub_data['platform'] == Platform.YOUTUBE.value:
                        platform_name = "YouTube频道"
                    elif sub_data['platform'] == Platform.BILIBILI.value:
                        platform_name = "B站UP主"
                    elif sub_data['platform'] == Platform.BILIBILI_COLLECTION.value:
                        platform_name = "B站合集"
                    else:
                        platform_name = "频道"
                    errors.append(f"订阅 {i+1} ({sub_data['nickname']}): 该{platform_name}已经订阅过了，无需重复添加")
                    failed_count += 1
                    continue
                
                # 创建新订阅
                now = datetime.now()
                subscription_id = str(uuid.uuid4())
                new_subscription = Subscription(
                    id=subscription_id,
                    platform=sub_data['platform'],
                    user_id=sub_data['user_id'],
                    nickname=sub_data['nickname'],
                    update_interval=sub_data.get('update_interval', 3600),
                    auto_download=str(sub_data.get('auto_download', False)).lower(),
                    status=sub_data.get('status', 'active'),
                    created_at=now,
                    updated_at=now,
                    last_check=now,
                    last_update=now,
                    # 如果有额外的博主信息，也保存
                    avatar_url=sub_data.get('avatar_url'),
                    signature=sub_data.get('signature'),
                    follower_count=sub_data.get('follower_count'),
                    like_count=sub_data.get('like_count'),
                    video_count=sub_data.get('video_count'),
                    # 添加画质设置支持，根据平台设置不同的默认值
                    quality=sub_data.get('quality', 'best' if sub_data['platform'] == 'youtube' else ('bestvideo+bestaudio' if sub_data['platform'] == 'bilibili' else 'best'))
                )
                
                db.add(new_subscription)
                success_count += 1
                
            except Exception as e:
                error_msg = f"订阅 {i+1} ({sub_data.get('nickname', '未知')}): {str(e)}"
                errors.append(error_msg)
                failed_count += 1
                logger.error(f"导入订阅失败: {error_msg}")
        
        # 提交所有成功的订阅
        if success_count > 0:
            db.commit()
        
        return ImportSubscriptionResponse(
            total=total,
            success=success_count,
            failed=failed_count,
            errors=errors
        )
        
    except Exception as e:
        logger.error(f"批量导入订阅失败: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))
