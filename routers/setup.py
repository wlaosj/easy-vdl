from fastapi import APIRouter, HTTPException
from sqlalchemy.orm import Session
from sql.database_postgresql import get_db
from sql.models import User, SystemConfig

router = APIRouter(prefix="/api/setup", tags=["系统设置"])

@router.get("/status")
async def get_system_status():
    """获取系统状态"""
    db = next(get_db())
    try:
        user_count = db.query(User).count()
        
        return {
            "is_first_install": user_count == 0,
            "user_count": user_count,
            "system_ready": user_count > 0
        }
    finally:
        db.close()

@router.get("/check")
async def check_system_ready():
    """检查系统是否已准备就绪"""
    db = next(get_db())
    try:
        user_count = db.query(User).count()
        
        if user_count == 0:
            raise HTTPException(status_code=404, detail="系统未初始化")
        
        return {"message": "系统已准备就绪", "user_count": user_count}
    finally:
        db.close()