"""
ProductMarketing ORM 模型
-------------------------
定义 ``ProductMarketing`` 实体 —— 与产品关联的长文本描述（知识文章/
营销文案）。

这些行是 RAG（检索增强生成）内容的主要来源：每条 ``description`` 在
数据导入管道中会被切块、嵌入并索引到向量存储中。
"""

from sqlalchemy import String, Boolean, DateTime, Text
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func
from app.database import Base


class ProductMarketing(Base):
    """
    产品的长文营销/知识库内容。

    每行表示一段文本（描述），可用作 LLM 驱动的搜索和聊天的检索上下文。

    属性
    ----------
    id : int (PK)
        自增代理主键。
    product_id : str
        指向 ``product.product_id`` 的外键引用。已建索引以支持
        按产品范围的高效查询。最大长度 50。
    description : str
        完整营销文案或知识文章正文。以 ``TEXT``（无界）存储。必填。
    is_active : bool
        软删除/可见性标记。默认 ``True``。
    created_at : datetime
        行创建时间戳，由数据库服务器自动设置。
    updated_at : datetime
        最后更新时间戳，每次 ``UPDATE`` 时自动刷新。
    """

    __tablename__ = "product_marketing"

    # -- 主键 ----------------------------------------------------------------
    id: Mapped[int] = mapped_column(primary_key=True)

    # -- 外键引用 ------------------------------------------------------------
    product_id: Mapped[str] = mapped_column(
        String(50), nullable=False, index=True
    )

    # -- 内容 ----------------------------------------------------------------
    description: Mapped[str] = mapped_column(Text, nullable=False)

    # -- 状态与生命周期 ------------------------------------------------------
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    created_at: Mapped[DateTime] = mapped_column(
        DateTime, server_default=func.now()
    )
    updated_at: Mapped[DateTime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )
