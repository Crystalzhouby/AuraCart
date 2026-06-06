"""
SKU ORM 模型
------------
定义 ``Sku`` 实体 —— 表示 ``Product`` 的一个具体可购买变体的库存单位
（例如 "iPhone 25 – 128 GB – Black"）。

每个 SKU 通过 ``product_id`` 业务键关联到其父产品，在 JSONB 列中持有
变体特定的属性，并跟踪各自的价格、库存数量和激活标记。
"""

from sqlalchemy import String, Integer, Numeric, Boolean, DateTime
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func
from app.database import Base


class Sku(Base):
    """
    库存单位 —— 产品的可购买变体。

    一个 ``Product`` 可以有零个或多个 ``Sku`` 行，每行表示变体属性
    （如尺寸、颜色、容量）的唯一组合。``properties`` JSONB 列以
    无模式形式存储这些属性。

    属性
    ----------
    id : int (PK)
        自增代理主键。
    sku_id : str
        此 SKU 的唯一业务标识符（例如 "SKU-12345"）。最大长度 50。
    product_id : str
        指向 ``product.product_id`` 的外键引用。已建索引以支持高效查询。
        数据库层不强制约束（无 FK 约束）；引用完整性在应用层维护。
    properties : dict | None
        定义变体的属性，以 JSONB 文档存储，例如
        ``{"color": "Black", "size": "128GB"}``。可为空。
    price : float
        SKU 特定价格，以 ``NUMERIC(10, 2)`` 存储。必填。
    stock : int
        当前库存数量。默认 0。
    is_active : bool
        软删除/可见性标记。默认 ``True``。
    created_at : datetime
        行创建时间戳，由数据库服务器自动设置。
    updated_at : datetime
        最后更新时间戳，每次 ``UPDATE`` 时自动刷新。
    """

    __tablename__ = "sku"

    # -- 主键 ----------------------------------------------------------------
    id: Mapped[int] = mapped_column(primary_key=True)

    # -- 业务键 --------------------------------------------------------------
    sku_id: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)

    # 指向 ``product.product_id`` 的带索引外键引用。
    product_id: Mapped[str] = mapped_column(
        String(50), nullable=False, index=True
    )

    # -- 变体数据 ------------------------------------------------------------
    # JSONB 列存储描述变体的任意键值对（如颜色、尺寸、材质）。
    # 无模式设计可灵活适应多样的产品类别。
    properties: Mapped[dict | None] = mapped_column(JSONB)

    # -- 定价与库存 ----------------------------------------------------------
    price: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False)
    stock: Mapped[int] = mapped_column(Integer, default=0)

    # -- 状态与生命周期 ------------------------------------------------------
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    created_at: Mapped[DateTime] = mapped_column(
        DateTime, server_default=func.now()
    )
    updated_at: Mapped[DateTime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )
