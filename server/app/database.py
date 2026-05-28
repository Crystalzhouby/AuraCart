"""
数据库连接与会话管理模块。

配置 SQLAlchemy 异步引擎、会话工厂以及所有 ORM 模型共享的
声明式基类。同时暴露一个 FastAPI 依赖生成器，用于在路由处理
函数中获取数据库会话。

核心功能：
- 根据应用配置创建异步 SQLAlchemy 引擎
- 具有一致配置的异步会话工厂
- 供 ORM 模型继承的声明式 Base 类
- 用于 FastAPI 路由的 ``get_db`` 异步生成器依赖
"""

from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.orm import DeclarativeBase
from app.config import settings

# 绑定到应用数据库的异步引擎
# echo=False 在生产环境中抑制 SQL 查询日志
engine = create_async_engine(settings.database.url, echo=False)

# 异步会话工厂 —— 每次调用产生一个新的 AsyncSession
async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


class Base(DeclarativeBase):
    """
    所有 ORM 模型的声明式基类。

    继承此类来定义 SQLAlchemy 模型，这些模型会参与元数据跟踪
    和迁移（Alembic）的自动生成。

    用法::

        class Product(Base):
            __tablename__ = "products"
            ...
    """

    pass


async def get_db() -> AsyncSession:
    """
    FastAPI 依赖，用于生成一个异步数据库会话。

    会话会在请求完成后（包括发生错误时）自动关闭，
    确保连接归还到连接池。

    路由中的用法::

        @router.get("/items")
        async def list_items(db: AsyncSession = Depends(get_db)):
            ...

    返回值（生成器）:
        AsyncSession: 一个活跃的异步 SQLAlchemy 会话。
    """
    async with async_session() as session:
        try:
            yield session
        finally:
            await session.close()
