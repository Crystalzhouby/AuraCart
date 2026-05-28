"""
Admin API 路由

模块: app.api.admin

提供系统维护操作的管理端接口，包括触发产品数据与嵌入向量存储的完整同步。
使用 FastAPI 依赖注入获取数据库会话和嵌入服务实例。
"""
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from app.database import get_db
from app.services.sync import SyncService
from app.services.embedding import EmbeddingService
from app.config import settings

router = APIRouter(prefix="/api/admin", tags=["admin"])


def get_embedding_service() -> EmbeddingService:
    """
    EmbeddingService 的依赖工厂函数。

    根据应用配置创建一个新的 EmbeddingService 实例，包括嵌入模型的
    base_url、api_key 和 model 名称。

    返回值:
        EmbeddingService: 可直接使用的嵌入服务实例。
    """
    return EmbeddingService(
        base_url=settings.embedding.base_url,
        api_key=settings.embedding.api_key,
        model=settings.embedding.model,
    )


@router.post("/sync")
async def trigger_sync(
    db: AsyncSession = Depends(get_db),
    emb: EmbeddingService = Depends(get_embedding_service),
):
    """
    触发一次完整的数据同步运行。

    执行 SyncService.run_once()，从数据库中取出所有活跃产品，
    通过嵌入服务生成向量，并将结果存储到向量库中。

    接口: POST /api/admin/sync

    参数:
        db (AsyncSession): 通过依赖注入获取的异步 SQLAlchemy 会话。
        emb (EmbeddingService): 通过依赖注入获取的嵌入服务。

    返回值:
        dict: 包含 status "ok" 和确认消息的 JSON 对象。
    """
    # 将会话封装为可调用工厂，使 SyncService 能获取会话引用而不持有过期连接。
    svc = SyncService(db_session_factory=lambda: db, emb=emb)
    await svc.run_once()
    return {"status": "ok", "message": "Sync completed"}
