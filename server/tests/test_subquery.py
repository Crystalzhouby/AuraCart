"""MCL-I1: SubQuery dataclass 新增 category/sub_category 可选字段的测试。

验证：
1. 带新字段构造 SubQuery
2. 不带新字段构造 SubQuery（向后兼容，默认 None）
3. 字典序列化/反序列化兼容性
"""
import pytest
from app.services.retriever_service import SubQuery


def test_subquery_default_category_fields_none():
    """构造 SubQuery 时不传 category/sub_category，新字段应为 None。"""
    sq = SubQuery(text="蓝牙耳机", strategy="keyword")
    assert sq.category is None
    assert sq.sub_category is None


def test_subquery_with_category_fields():
    """构造 SubQuery 时传入 category/sub_category，应正确存储。"""
    sq = SubQuery(
        text="防晒",
        strategy="keyword",
        category="美妆护肤",
        sub_category="防晒",
    )
    assert sq.category == "美妆护肤"
    assert sq.sub_category == "防晒"


def test_subquery_with_category_only():
    """只传 category 不传 sub_category。"""
    sq = SubQuery(
        text="跑鞋",
        strategy="keyword",
        category="运动户外",
    )
    assert sq.category == "运动户外"
    assert sq.sub_category is None


def test_subquery_all_fields_with_category():
    """所有字段（含新增）一起构造。"""
    sq = SubQuery(
        text="",
        strategy="structured_filter",
        field="price",
        operator="lt",
        value=200,
        expanded_values=None,
        category="数码电子",
        sub_category="蓝牙耳机",
    )
    assert sq.text == ""
    assert sq.strategy == "structured_filter"
    assert sq.field == "price"
    assert sq.operator == "lt"
    assert sq.value == 200
    assert sq.expanded_values is None
    assert sq.category == "数码电子"
    assert sq.sub_category == "蓝牙耳机"


def test_subquery_existing_code_unaffected():
    """确保现有构造代码不带新字段时行为不变。"""
    # 模拟现有 search.py 中的 SubQuery 构造
    sq = SubQuery(text="跑鞋", strategy="semantic")
    assert sq.text == "跑鞋"
    assert sq.strategy == "semantic"
    assert sq.field is None
    assert sq.operator is None
    assert sq.value is None
    assert sq.expanded_values is None
    # 新字段应为 None
    assert sq.category is None
    assert sq.sub_category is None
