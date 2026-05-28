# tests/test_models.py
"""测试 ORM 模型定义：验证表名与关键列。

确保应用中每个 SQLAlchemy 模型均映射到预期的数据库表，
并暴露必需的列集合与约束。
"""

import pytest


def test_product_model_exists():
    """验证 Product ORM 模型映射到 "product" 表，且包含正确的列。

    检查表名、所有预期列（product_id、title、brand、category、
    sub_category、base_price、image_path、is_active、created_at、
    updated_at）以及 product_id 唯一性约束是否齐全。
    """
    from app.models.product import Product

    assert Product.__tablename__ == "product"

    cols = {c.name: c for c in Product.__table__.columns}
    assert "product_id" in cols
    assert "title" in cols
    assert "brand" in cols
    assert "category" in cols
    assert "sub_category" in cols
    assert "base_price" in cols
    assert "image_path" in cols
    assert "is_active" in cols
    assert "created_at" in cols
    assert "updated_at" in cols

    # product_id 必须为主键，因此是唯一的
    assert cols["product_id"].unique is True


def test_sku_model_exists():
    """验证 Sku ORM 模型映射到 "sku" 表，且包含正确的列。

    确认 sku_id、product_id、properties（JSON）、price、stock 和
    is_active 列均已定义，且 sku_id 为唯一键。
    """
    from app.models.sku import Sku

    assert Sku.__tablename__ == "sku"

    cols = {c.name: c for c in Sku.__table__.columns}
    assert "sku_id" in cols
    assert "product_id" in cols
    assert "properties" in cols
    assert "price" in cols
    assert "stock" in cols
    assert "is_active" in cols
    assert cols["sku_id"].unique is True


def test_product_marketing_model_exists():
    """验证 ProductMarketing ORM 模型映射到 "product_marketing" 表。

    确保 product_id、description 和 is_active 列定义正确。
    """
    from app.models.product_marketing import ProductMarketing

    assert ProductMarketing.__tablename__ == "product_marketing"

    cols = {c.name: c for c in ProductMarketing.__table__.columns}
    assert "product_id" in cols
    assert "description" in cols
    assert "is_active" in cols


def test_product_faq_model_exists():
    """验证 ProductFaq ORM 模型映射到 "product_faq" 表。

    确保 product_id、question、answer 和 is_active 列定义正确。
    """
    from app.models.product_faq import ProductFaq

    assert ProductFaq.__tablename__ == "product_faq"

    cols = {c.name: c for c in ProductFaq.__table__.columns}
    assert "product_id" in cols
    assert "question" in cols
    assert "answer" in cols
    assert "is_active" in cols


def test_user_review_model_exists():
    """验证 UserReview ORM 模型映射到 "user_review" 表。

    确保 product_id、nickname、rating、content 和 is_active 列定义正确。
    """
    from app.models.user_review import UserReview

    assert UserReview.__tablename__ == "user_review"

    cols = {c.name: c for c in UserReview.__table__.columns}
    assert "product_id" in cols
    assert "nickname" in cols
    assert "rating" in cols
    assert "content" in cols
    assert "is_active" in cols


def test_product_review_model_exists():
    """验证 ProductReview ORM 模型映射到 "product_review" 表。

    此模型存储用于向量搜索的嵌入式评论内容。
    确认 product_id、source、content、embedding 和 metadata 列均已定义。
    """
    from app.models.product_review import ProductReview

    assert ProductReview.__tablename__ == "product_review"

    cols = {c.name: c for c in ProductReview.__table__.columns}
    assert "product_id" in cols
    assert "source" in cols
    assert "content" in cols
    assert "embedding" in cols
    assert "metadata" in cols


def test_all_models_importable():
    """验证所有顶层模型均可从 app.models 导入。

    一个简单的冒烟测试，用于捕获模型包中的导入错误、缺失符号
    或循环引用问题。
    """
    from app.models import Product, Sku, ProductMarketing, ProductFaq, UserReview, ProductReview

    assert Product is not None
    assert Sku is not None
    assert ProductMarketing is not None
    assert ProductFaq is not None
    assert UserReview is not None
    assert ProductReview is not None
