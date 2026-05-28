"""
UserReview ORM 模型
-------------------
定义 ``UserReview`` 实体 —— 用户提交的产品评价，包含可选的昵称、
可选的数值评分和必填的自由文本内容。

这些评价可能从外部来源（如电商平台导出）加载，或由终端用户直接提交。
``product_id`` 列将每条评价关联到其父 ``Product``。
"""

from sqlalchemy import String, Integer, Boolean, DateTime, Text
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func
from app.database import Base


class UserReview(Base):
    """
    用户提交的产品评价。

    每行记录一条评价事件：撰写者（昵称）、给出的评分以及评价的自由文本正文。

    属性
    ----------
    id : int (PK)
        自增代理主键。
    product_id : str
        指向 ``product.product_id`` 的外键引用。已建索引以支持
        按产品范围的高效查询。最大长度 50。
    nickname : str | None
        评价者的显示名称。可选；最大 100 字符。
    rating : int | None
        数值评分（例如 1-5 星）。可选。
    content : str
        评价的自由文本正文。以 ``TEXT``（无界）存储。必填。
    is_active : bool
        软删除/可见性标记。默认 ``True``。
    created_at : datetime
        行创建时间戳，由数据库服务器自动设置。
    updated_at : datetime
        最后更新时间戳，每次 ``UPDATE`` 时自动刷新。
    """

    __tablename__ = "user_review"

    # -- 主键 ----------------------------------------------------------------
    id: Mapped[int] = mapped_column(primary_key=True)

    # -- 外键引用 ------------------------------------------------------------
    product_id: Mapped[str] = mapped_column(
        String(50), nullable=False, index=True
    )

    # -- 评价者元数据 --------------------------------------------------------
    nickname: Mapped[str | None] = mapped_column(String(100))
    rating: Mapped[int | None] = mapped_column(Integer)

    # -- 评价内容 ------------------------------------------------------------
    content: Mapped[str] = mapped_column(Text, nullable=False)

    # -- 状态与生命周期 ------------------------------------------------------
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    created_at: Mapped[DateTime] = mapped_column(
        DateTime, server_default=func.now()
    )
    updated_at: Mapped[DateTime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )
