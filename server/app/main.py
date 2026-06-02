"""
FastAPI 应用入口。

创建并配置 FastAPI 应用实例，注册 API 路由，
挂载静态文件服务，并管理后台数据同步服务的生命周期。

核心功能：
- 用于启动/停止同步循环的 lifespan 上下文管理器
- 搜索、商品和管理后台路由的注册
- 为电商 Agent 数据集提供静态文件服务
- 用于就绪探测的健康检查端点
"""

import asyncio
from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from app.api import search, products, admin, conversation
from app.config import settings
from app.database import async_session
from app.services.embedding import EmbeddingService
from app.services.sync import SyncService
from app.core.logging import setup_logging

# 尽早初始化结构化日志，以便所有后续 logger 均被正确配置
setup_logging(level=settings.log.level, log_dir=settings.log.dir)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    应用生命周期管理器。

    在启动时启动后台同步循环，在关闭时优雅地取消它。
    如果配置中禁用了同步，则上下文为空操作。

    参数:
        app: FastAPI 应用实例。
    """
    if settings.sync.enabled:
        # 将同步服务与数据库会话和 Embedding 服务组装
        sync_service = SyncService(
            db_session_factory=lambda: async_session(),
            emb=EmbeddingService(
                base_url=settings.embedding.base_url,
                api_key=settings.embedding.api_key,
                model=settings.embedding.model,
            ),
        )
        # 将同步循环作为后台任务运行
        task = asyncio.create_task(sync_service.run_loop())
        yield
        # 关闭：取消循环并吞入预期的取消异常
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
    else:
        yield


# FastAPI 应用实例
app = FastAPI(title="AuraCart", version="0.1.0", lifespan=lifespan)

# 注册各领域路由
app.include_router(search.router)
app.include_router(products.router)
app.include_router(admin.router)
app.include_router(conversation.router)

# 托管静态数据集目录（图片等）
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
app.mount("/static", StaticFiles(directory=str(_PROJECT_ROOT / settings.dataset.dir)), name="static")


@app.get("/health")
async def health():
    """
    健康检查端点。

    返回一个简单的 JSON 响应，表明服务可达。
    适用于 Kubernetes 的存活/就绪探测。

    返回值:
        dict: 始终返回 ``{"status": "ok"}``。
    """
    return {"status": "ok"}
