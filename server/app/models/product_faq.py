"""
ProductFaq ORM 模型
-------------------
定义 ``ProductFaq`` 实体 —— 与产品关联的问答对。这些行提供结构化的
FAQ 内容，可在 UI 中展示或被 RAG 管道用作检索上下文。
"""

from sqlalchemy import String, Boolean, DateTime, Text
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func
from app.database import Base


class ProductFaq(Base):
    """
    产品的常见问题条目。

    每行将一个问题与对应答案配对，并通过 ``product_id`` 关联到所属产品。

    属性
    ----------
    id : int (PK)
        自增代理主键。
    product_id : str
        指向 ``product.product_id`` 的外键引用。已建索引以支持
        按产品范围的高效查询。最大长度 50。
    question : str
        问题文本。以 ``TEXT``（无界）存储。必填。
    answer : str
        答案文本。以 ``TEXT``（无界）存储。必填。
    is_active : bool
        软删除/可见性标记。默认 ``True``。
    created_at : datetime
        行创建时间戳，由数据库服务器自动设置。
    updated_at : datetime
        最后更新时间戳，每次 ``UPDATE`` 时自动刷新。
    """

    __tablename__ = "product_faq"

    # -- 主键 ----------------------------------------------------------------
    id: Mapped[int] = mapped_column(primary_key=True)

    # -- 外键引用 ------------------------------------------------------------
    product_id: Mapped[str] = mapped_column(
        String(50), nullable=False, index=True
    )

    # -- 问答内容 ------------------------------------------------------------
    question: Mapped[str] = mapped_column(Text, nullable=False)
    answer: Mapped[str] = mapped_column(Text, nullable=False)

    # -- 状态与生命周期 ------------------------------------------------------
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    created_at: Mapped[DateTime] = mapped_column(
        DateTime, server_default=func.now()
    )
    updated_at: Mapped[DateTime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )
