"""
Conversation ORM 模型
-------------------
定义 ``Conversation`` 实体 — 会话存在性记录。

每条记录以 UUID 作为主键（应用层生成），用于校验 conversation_id 合法性。
对话历史存储在 ``chat_history`` 表中。
"""

from sqlalchemy import String, DateTime
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func
from app.database import Base


class Conversation(Base):
    """
    会话实例，证明会话存在。

    属性
    ----------
    conversation_id : str (PK)
        UUID v4 主键，应用层生成。最大长度 36。
    created_at : datetime
        行创建时间戳，由数据库服务器自动设置。
    updated_at : datetime
        最后更新时间戳，每次 ``UPDATE`` 时自动刷新。
    """

    __tablename__ = "conversation"

    conversation_id: Mapped[str] = mapped_column(
        String(36), primary_key=True
    )

    created_at: Mapped[DateTime] = mapped_column(
        DateTime, server_default=func.now()
    )
    updated_at: Mapped[DateTime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )
