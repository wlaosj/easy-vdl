"""
订阅模块路由聚合
"""
from fastapi import APIRouter
from .subscription import router as subscription_router
from .videos import router as videos_router
from .sync import router as sync_router
from .download import router as download_router
from .auth import router as auth_router
from .proxy import router as proxy_router
from .batch import router as batch_router
# 导出常用函数，供其他模块使用
from .utils import get_subscription_download_dir

router = APIRouter(
    prefix="/api/subscribe",
    tags=["subscribe"],
    responses={404: {"description": "Not found"}}
)

router.include_router(subscription_router)
router.include_router(videos_router)
router.include_router(sync_router)
router.include_router(download_router)
router.include_router(auth_router)
router.include_router(proxy_router)
router.include_router(batch_router)

__all__ = ["router", "get_subscription_download_dir"]
