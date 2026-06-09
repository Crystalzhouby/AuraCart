"""
ChatHistory ORM 模型
--------------------
定义 ``ChatHistory`` 实体 —— 按时间顺序存储每轮对话的用户查询与助手回复。
"""

from sqlalchemy import String, DateTime, Text, Integer
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func
from app.database import Base


class ChatHistory(Base):
    """单条对话消息，按 created_at 排序即为对话时间线。

    属性
    ----------
    id : int (PK)
        自增代理主键。
    conversation_id : str
        关联会话 ID。已建索引。最大长度 36。
    role : str
        消息角色：``"user"`` 或 ``"assistant"``。最大长度 10。
    content : str
        消息文本内容。以 ``TEXT`` 存储。
    created_at : datetime
        行创建时间戳，由数据库服务器自动设置。
    """

    __tablename__ = "chat_history"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    conversation_id: Mapped[str] = mapped_column(
        String(36), nullable=False, index=True
    )

    role: Mapped[str] = mapped_column(String(10), nullable=False)

    content: Mapped[str] = mapped_column(Text, nullable=False)

    created_at: Mapped[DateTime] = mapped_column(
        DateTime, server_default=func.now()
    )
