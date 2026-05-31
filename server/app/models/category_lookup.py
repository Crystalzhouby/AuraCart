"""Category 查找表 ORM 模型。

提供 (category, sub_category) 合法值对查询，供 Scenario Gen 注入品类列表、
Product Retrieval 分组校验使用。表通过 server/scripts/setup_category_lookup.py 手动维护。
"""
from sqlalchemy import String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class CategoryLookup(Base):
    """品类查找表 — 记录数据库中存在的 (category, sub_category) 组合。

    UNIQUE(category, sub_category) 保证值对唯一。
    """

    __tablename__ = "category_lookup"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    category: Mapped[str] = mapped_column(String, nullable=False)
    sub_category: Mapped[str] = mapped_column(String, nullable=False)

    __table_args__ = (
        UniqueConstraint("category", "sub_category", name="uq_category_lookup_pair"),
    )

    def __repr__(self) -> str:
        return f"<CategoryLookup(id={self.id}, category={self.category!r}, sub_category={self.sub_category!r})>"
