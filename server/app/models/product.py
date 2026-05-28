"""
Product ORM 模型
----------------
定义 ``Product`` 实体 —— AuraCart 目录中每个产品的主记录。每个产品拥有
唯一的 ``product_id``（业务键）、层级分类元数据、基础价格和生命周期时间戳。

关联子表将 ``product.product_id`` 作为外键引用：
- ``Sku``              – 变体级别的定价/库存
- ``ProductMarketing`` – 富文本营销文案
- ``ProductFaq``       – 问答条目
- ``UserReview``       – 用户评分
- ``ProductReview``    – 含向量嵌入的评价语料

本表通过 SQLAlchemy 2.0 声明式风格映射到 PostgreSQL，使用
``mapped_column`` 和 PEP-484 ``Mapped`` 类型注解。
"""

from sqlalchemy import String, Numeric, Boolean, DateTime, Text
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func
from app.database import Base


class Product(Base):
    """
    产品目录主记录。

    表示目录中的单个可售商品。变体（颜色、尺寸等）在 ``Sku`` 表中建模；
    本表持有共享/不变的属性，如品牌、分类和基础价格。

    属性
    ----------
    id : int (PK)
        自增代理主键。
    product_id : str
        业务/外部产品标识符。必须在整个目录中唯一。最大长度 50。
    title : str
        可读的产品名称/标题。必填。
    brand : str | None
        品牌名称。可选；最大 100 字符。
    category : str | None
        粗粒度分类（例如 "Electronics"）。可选；最大 50 字符。
    sub_category : str | None
        细粒度子分类（例如 "Laptops"）。可选；最大 50 字符。
    base_price : float | None
        默认/参考价格，以 ``NUMERIC(10, 2)`` 存储。
    image_path : str | None
        主产品图片的文件系统或 URL 路径。
    is_active : bool
        软删除/可见性标记。默认 ``True``。
    created_at : datetime
        行创建时间戳，由数据库服务器自动设置。
    updated_at : datetime
        最后更新时间戳，每次 ``UPDATE`` 时自动刷新。
    """

    # PostgreSQL 架构中的表名。
    __tablename__ = "product"

    # -- 主键 ----------------------------------------------------------------
    id: Mapped[int] = mapped_column(primary_key=True)

    # -- 业务键 --------------------------------------------------------------
    # 所有子表作为 FK 目标引用的唯一外部标识符。
    product_id: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)

    # -- 描述属性 ------------------------------------------------------------
    title: Mapped[str] = mapped_column(Text, nullable=False)
    brand: Mapped[str | None] = mapped_column(String(100))
    category: Mapped[str | None] = mapped_column(String(50))
    sub_category: Mapped[str | None] = mapped_column(String(50))

    # -- 定价与媒体 ----------------------------------------------------------
    base_price: Mapped[float | None] = mapped_column(Numeric(10, 2))
    image_path: Mapped[str | None] = mapped_column(String(500))

    # -- 状态与生命周期 ------------------------------------------------------
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    # ``server_default`` 将值的生成委托给数据库，使批量插入也能获得正确的时间戳。
    created_at: Mapped[DateTime] = mapped_column(
        DateTime, server_default=func.now()
    )
    # ``onupdate`` 确保每次行 UPDATE 时刷新该列。
    updated_at: Mapped[DateTime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )
