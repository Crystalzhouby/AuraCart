"""
Conversation ORM 模型
-------------------
定义 ``Conversation`` 实体 — 多会话支持的核心表，持久化每个会话的对话记忆。

每条记录以 UUID 作为主键（应用层生成），``memory`` 列存储
``conversation_history``（list[dict] 格式的 JSONB）。
"""

from sqlalchemy import String, DateTime, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func
from app.database import Base


class Conversation(Base):
    """
    会话实例，存储多轮对话的记忆。

    属性
    ----------
    conversation_id : str (PK)
        UUID v4 主键，应用层生成。最大长度 36。
    memory : list[dict] | None
        持久化的 conversation_history，JSONB 格式。
        默认值为空列表 ``[]``。每条记录为一个 requirements dict。
    created_at : datetime
        行创建时间戳，由数据库服务器自动设置。
    updated_at : datetime
        最后更新时间戳，每次 ``UPDATE`` 时自动刷新。
    """

    __tablename__ = "conversation"

    conversation_id: Mapped[str] = mapped_column(
        String(36), primary_key=True
    )

    memory: Mapped[list | None] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )

    created_at: Mapped[DateTime] = mapped_column(
        DateTime, server_default=func.now()
    )
    updated_at: Mapped[DateTime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )
