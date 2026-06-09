# alembic/env.py
"""
Alembic 运行时环境配置。

本模块是每个 Alembic 命令（``upgrade``、``downgrade``、``revision`` 等）
的入口。其职责包括：

* 从应用程序的 ``config.yaml``（通过 ``app.config.settings``）加载数据库 URL。
* 在执行迁移前确保目标数据库已存在（自动创建）。
* 支持 **离线** 模式（无需实时数据库即可生成 SQL 脚本）和 **在线**
  模式（直接对运行中的异步数据库执行迁移）。
* 绑定 SQLAlchemy 模型元数据，以便 Alembic 通过 ``--autogenerate``
  自动生成迁移脚本。

架构说明:
    离线迁移以同步方式运行并生成原始 SQL。在线迁移使用从 ``alembic.ini``
    的 ``[alembic]`` 节创建的异步引擎，底层 URL 则被应用程序配置覆盖。
"""

import asyncio
from logging.config import fileConfig
from typing import Optional

import sqlalchemy as sa
from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.engine.url import make_url
from sqlalchemy.ext.asyncio import async_engine_from_config

from app.config import settings
from app.database import Base

# ---------------------------------------------------------------------------
# 导入所有 ORM 模型，使 ``Base.metadata`` 包含全部表定义。
# 这是 ``--autogenerate`` 检测 schema 变更的必要条件。
# ---------------------------------------------------------------------------
# noinspection PyUnresolvedReferences
from app.models import (  # noqa: F401  -- 为其对 metadata 的副作用而导入
    Product,
    ProductFaq,
    ProductMarketing,
    ProductReview,
    Sku,
    UserReview,
    CategoryLookup,
    Conversation,
    ChatHistory,
)

# Alembic Config 对象 – 提供对 alembic.ini 中配置值的访问。
config = context.config

# 从 alembic.ini 的 [loggers] 节设置 Python 日志（如果存在）。
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# ---------------------------------------------------------------------------
# 目标元数据 – Alembic 管理的 ORM 表集合。
# ---------------------------------------------------------------------------
target_metadata = Base.metadata

# 用应用程序配置中定义的 URL 覆盖 alembic.ini 中的 ``sqlalchemy.url``，
# 确保两者永不偏离。
config.set_main_option("sqlalchemy.url", settings.database.url)


def _quote_ident(identifier: str) -> str:
    """对 PostgreSQL 标识符进行双引号包裹，并转义内嵌引号。

    参数:
        identifier: Schema 对象名称（例如数据库名、表名）。

    返回值:
        被双引号包裹的标识符，可安全用于原始 SQL 中。
    """
    return '"' + identifier.replace('"', '""') + '"'


def _ensure_database_exists(sync_url: str) -> None:
    """如果目标数据库不存在则自动创建。

    连接到 ``postgres`` 维护数据库，检查目标数据库是否存在，必要时执行
    ``CREATE DATABASE``。这是一个便利功能，使开发者无需在首次运行迁移前
    手动创建数据库。

    参数:
        sync_url: 同步的 PostgreSQL 连接 URL，其 ``/dbname`` 部分标识
            目标数据库。
    """

    url = make_url(sync_url)
    dbname: Optional[str] = url.database
    if not dbname:
        return  # 没有需要创建的数据库名。

    # 连接到默认的 'postgres' 数据库以执行管理操作。
    admin_url = url.set(database="postgres")
    engine = sa.create_engine(admin_url, isolation_level="AUTOCOMMIT")
    try:
        with engine.connect() as conn:
            # 在系统目录中检查目标数据库是否存在。
            exists = conn.execute(
                sa.text("SELECT 1 FROM pg_database WHERE datname = :dbname"),
                {"dbname": dbname},
            ).scalar()
            if not exists:
                conn.execute(sa.text(f"CREATE DATABASE {_quote_ident(dbname)}"))
    finally:
        engine.dispose()


def run_migrations_offline() -> None:
    """以"离线"模式运行迁移 -- 将 SQL 输出到 stdout。

    离线模式不需要实时数据库连接。通常用于生成 SQL 脚本以供审查，或在
    迁移工具无法直接连接数据库的环境（例如受限的 CI 流水线）中应用迁移。
    """

    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    """在同步连接上下文中执行迁移。

    此回调被异步在线运行器传递给 ``connection.run_sync()``，以便在异步
    连接之上使用 Alembic 的同步迁移 API。

    参数:
        connection: 同步的 SQLAlchemy ``Connection`` 代理。
    """

    context.configure(connection=connection, target_metadata=target_metadata)

    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    """创建异步引擎并在线执行所有待处理的迁移。

    使用 ``alembic.ini`` 的 ``[alembic]`` 节（继承被覆盖的 ``sqlalchemy.url``），
    通过包装在 ``run_sync`` 中的异步连接来应用迁移。
    """

    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


def run_migrations_online() -> None:
    """以"在线"模式对实时数据库运行迁移。

    确保目标数据库在已配置的 PostgreSQL 服务器上存在，然后委托给异步
    迁移运行器。
    """

    _ensure_database_exists(settings.database.sync_url)
    asyncio.run(run_async_migrations())


# ---------------------------------------------------------------------------
# 主守卫：根据 Alembic 调用上下文（例如 ``--sql`` 标志触发离线模式）分发
# 到离线或在线模式。
# ---------------------------------------------------------------------------
if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
