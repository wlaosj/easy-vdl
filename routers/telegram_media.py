from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from routers.auth import get_current_user
from services.telegram_media_service import telegram_media_service
from sql.database_postgresql import get_db
from sql.models import User

router = APIRouter(prefix="/api/telegram/media", tags=["telegram-media"])


class TelegramUpdateIngestRequest(BaseModel):
    update: Dict[str, Any]


@router.post("/ingest-update")
async def ingest_telegram_update(
    payload: TelegramUpdateIngestRequest,
    _: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    接收 Telegram update（包含 message/video/photo/document）并下载保存到本地。
    说明：
    - 不修改现有 telegram_bot.py 逻辑。
    - 仅复用现有 Telegram Bot 配置（token/chat_id/proxy）。
    """
    try:
        result = await telegram_media_service.ingest_update(payload.update, db)
        return {"success": True, "message": "媒体已保存", "data": result}
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"ingest failed: {str(e)}")
