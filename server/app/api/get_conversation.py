"""
会话 API 路由

模块: app.api.get_conversation

提供多会话支持接口：
- GET /api/conversation/ — 创建新会话，返回 conversation_id (UUID)
"""
import uuid
from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession
from app.database import get_db
from app.models.conversation import Conversation

router = APIRouter(prefix="/api", tags=["conversation"])


@router.get("/conversation")
async def create_conversation(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """
    创建新会话并返回唯一的 conversation_id。

    生成 UUID v4 作为会话标识，在 conversation 表中插入一行空记忆，
    返回 ``{"conversation_id": "<UUID>"}``。

    参数:
        request (Request): FastAPI Request 对象。
        db (AsyncSession): 通过依赖注入获取的异步 SQLAlchemy 会话。

    返回值:
        dict: ``{"conversation_id": str}``
    """
    conversation_id = str(uuid.uuid4())
    db.add(Conversation(conversation_id=conversation_id, memory=[]))
    await db.commit()
    return {"conversation_id": conversation_id}
