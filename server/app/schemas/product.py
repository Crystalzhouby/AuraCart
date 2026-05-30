# app/schemas/product.py
"""
产品、SKU 及搜索响应序列化的 Pydantic schema 定义。

本模块定义了产品 API 层所使用的请求/响应结构，包括嵌套的 SKU 子 schema，
以及用于实时查询反馈的 SSE 流式负载。所有 ORM 模式的 schema
均设置 ``from_attributes=True``，以便直接从 SQLAlchemy 模型实例进行填充。
"""

from pydantic import BaseModel


class SkuOut(BaseModel):
    """单个库存单位（SKU）的序列化表示。

    属性:
        sku_id: 该 SKU 的唯一标识符（例如 "SKU-ROG-STRIX-BLACK"）。
        properties: 描述变体属性（颜色、尺寸、容量等）的任意键值对。
            对于基础 SKU 可能为 ``None``。
        price: 该 SKU 的当前单价。
        stock: 该 SKU 的可用库存数量。
    """

    sku_id: str
    properties: dict | None
    price: float
    stock: int

    # 允许 Pydantic 从 SQLAlchemy 模型属性填充字段。
    model_config = {"from_attributes": True}


class ProductInfo(BaseModel):
    """精简的产品信息，仅含基本元数据，不含 SKU 列表与图片路径。

    属性:
        product_id: 业务级产品标识符。
        title: 产品展示名称。
        brand: 制造商或品牌名称（可选）。
        category: 顶层产品分类。
        sub_category: 细粒度子分类。
        base_price: 默认标价。
    """

    product_id: str
    title: str
    brand: str | None
    category: str | None
    sub_category: str | None
    base_price: float | None

    model_config = {"from_attributes": True}


class SSESubQueryEvent(BaseModel):
    """多策略搜索过程中通过 SSE 流发出的单个子查询事件。
    每个事件代表从用户自然语言查询中提取的一个分解条件。

    属性:
        text: 该子查询来源的自然语言片段。
        strategy: 所应用的检索策略（例如 'semantic'、'keyword'、'filter'）。
        field: 该条件所针对的结构化字段（例如 'brand'、'category'）。
        operator: 使用的比较运算符（例如 'eq'、'gte'、'contains'）。
        value: 用于比较的标量值。
        expanded_values: 语义扩展产生的备选值（同义词、相关术语）。
    """

    text: str
    strategy: str
    field: str | None = None
    operator: str | None = None
    value: str | float | None = None
    expanded_values: list[str] | None = None


class SSEProduct(BaseModel):
    """渐进式搜索结果下发过程中通过 SSE 流传输的轻量产品快照。

    本 schema 省略了 ``base_price``，改为通过嵌套的 SKU 列表传递变体级别
    的价格，以保持单个 SSE 帧的紧凑性。

    属性:
        product_id: 业务级产品标识符。
        title: 产品展示名称。
        brand: 制造商或品牌名称（可选）。
        category: 顶层产品分类。
        base_price: 默认标价（可选）。
        image_path: 产品主图的 URL（可选）。
        skus: 该产品可用的 SKU 变体。
    """

    product_id: str
    title: str
    brand: str | None
    category: str | None
    base_price: float | None
    image_path: str | None
    skus: list[SkuOut]
