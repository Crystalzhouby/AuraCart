"""MCL-I3: CategoryLookup ORM 模型测试。

验证：
1. 模型字段定义正确
2. 表名正确
3. UNIQUE(category, sub_category) 约束
"""
import pytest
from sqlalchemy import inspect, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.category_lookup import CategoryLookup


def test_category_lookup_table_name():
    """表名应为 category_lookup。"""
    assert CategoryLookup.__tablename__ == "category_lookup"


def test_category_lookup_columns():
    """应包含 id, category, sub_category 三个字段。"""
    columns = {c.name: c for c in CategoryLookup.__table__.columns}
    assert "id" in columns
    assert "category" in columns
    assert "sub_category" in columns
    # id 是主键
    assert columns["id"].primary_key
    # category 和 sub_category 不可为空
    assert not columns["category"].nullable
    assert not columns["sub_category"].nullable


def test_category_lookup_unique_constraint():
    """category + sub_category 应有唯一约束。"""
    # 获取表的唯一约束
    constraints = [
        c for c in CategoryLookup.__table__.constraints
        if hasattr(c, "columns")
    ]
    unique_constraints = []
    for c in constraints:
        cols = [col.name for col in getattr(c, "columns", [])]
        if len(cols) == 2 and "category" in cols and "sub_category" in cols:
            unique_constraints.append(c)
    assert len(unique_constraints) >= 1, "Missing UNIQUE(category, sub_category) constraint"


def test_category_lookup_creation():
    """验证 CategoryLookup 实例可创建。"""
    cl = CategoryLookup(category="美妆护肤", sub_category="防晒")
    assert cl.category == "美妆护肤"
    assert cl.sub_category == "防晒"


def test_category_lookup_repr():
    """验证 __repr__ 包含关键信息。"""
    cl = CategoryLookup(category="数码电子", sub_category="蓝牙耳机")
    r = repr(cl)
    assert "数码电子" in r
    assert "蓝牙耳机" in r
