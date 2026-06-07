# -*- coding: utf-8 -*-
"""
前端 AI 对话端点
供 ChatView.vue 调用，复用 services/llm_assistant.py 共享层
"""
import logging
from typing import Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from sql.database_postgresql import get_db
from routers.auth import get_current_user
from services.llm_assistant import llm_assistant, get_llm_config
from sql.models import User

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/chat", tags=["chat"])


class ChatRequest(BaseModel):
    message: str
    session_id: Optional[str] = None


class ChatClearRequest(BaseModel):
    session_id: Optional[str] = None


@router.get("/model")
async def chat_model(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """获取当前 AI 对话使用的模型信息"""
    config = get_llm_config(db)
    return {
        "provider": config.get("provider", "none"),
        "model": config.get("model", ""),
        "base_url": config.get("base_url", ""),
    }


@router.post("/send")
async def chat_send(
    body: ChatRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """发送消息给 AI 助手，返回回复 + 执行的操作"""
    # 前端传了 client_uuid 则组合为 web:{user.id}:{uuid}，区分多设备
    if body.session_id:
        session_id = f"web:{user.id}:{body.session_id}"
    else:
        session_id = f"web:{user.id}"
    try:
        result = await llm_assistant.chat(session_id, body.message, db)
        return result
    except Exception as e:
        logger.error(f"Chat 处理失败: {e}", exc_info=True)
        return {
            "success": False,
            "reply": "抱歉，处理消息时出现错误，请稍后重试。",
            "actions": [],
            "session_id": session_id,
        }


@router.post("/clear")
async def chat_clear(
    body: ChatClearRequest = ChatClearRequest(),
    user: User = Depends(get_current_user),
):
    """清除对话历史"""
    if body.session_id:
        session_id = f"web:{user.id}:{body.session_id}"
    else:
        session_id = f"web:{user.id}"
    llm_assistant.clear_session(session_id)
    return {"success": True}
