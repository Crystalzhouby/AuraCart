"""
模型包
------
AuraCart 应用中所有 SQLAlchemy ORM 模型的统一注册中心。

本包对外暴露所有数据库实体，调用方可从单一命名空间（``app.models``）
引用。Alembic 的 ``env.py`` 及应用启动代码依赖本模块来发现模型元数据。

核心模型
--------
- ``Product``         – 产品目录主记录
- ``Sku``             – 产品的库存单位变体
- ``ProductMarketing`` – 长文营销描述
- ``ProductFaq``       – 产品的问答对
- ``UserReview``       – 用户提交的评价/评分
- ``ProductReview``    – 含向量嵌入的聚合评价语料
- ``CategoryLookup``   – 合法 (category, sub_category) 值对查找表

用法::

    from app.models import Product, Sku
"""

# ---------------------------------------------------------------------------
# 导入各模型，使 SQLAlchemy 的 Base.metadata 注册表能发现它们。
# ---------------------------------------------------------------------------
from app.models.product import Product  # noqa: E402, F401
from app.models.sku import Sku  # noqa: E402, F401
from app.models.product_marketing import ProductMarketing  # noqa: E402, F401
from app.models.product_faq import ProductFaq  # noqa: E402, F401
from app.models.user_review import UserReview  # noqa: E402, F401
from app.models.product_review import ProductReview  # noqa: E402, F401
from app.models.category_lookup import CategoryLookup  # noqa: E402, F401
from app.models.conversation import Conversation  # noqa: E402, F401
from app.models.chat_message import ChatMessage  # noqa: E402, F401

# ---------------------------------------------------------------------------
# 显式控制 ``from app.models import *`` 时暴露的内容。
# ---------------------------------------------------------------------------
__all__ = [
    "Product",
    "Sku",
    "ProductMarketing",
    "ProductFaq",
    "UserReview",
    "ProductReview",
    "CategoryLookup",
    "Conversation",
    "ChatMessage",
]
