"""MCL-I2: 配置扩展测试。

验证 config.yaml → config.py 新增的 4 个配置字段：
- search.max_category_concurrency (默认 5)
- search.max_batch_ids (默认 20)
- database.pool_size (默认 8)
- database.max_overflow (默认 5)
"""
import pytest
from app.config import Settings


def test_database_pool_size_default():
    """DatabaseSettings 应有 pool_size 字段，默认 8。"""
    s = Settings.from_yaml()
    assert hasattr(s.database, "pool_size")
    assert s.database.pool_size == 8


def test_database_max_overflow_default():
    """DatabaseSettings 应有 max_overflow 字段，默认 5。"""
    s = Settings.from_yaml()
    assert hasattr(s.database, "max_overflow")
    assert s.database.max_overflow == 5


def test_search_max_category_concurrency_default():
    """SearchSettings 应有 max_category_concurrency 字段，默认 5。"""
    s = Settings.from_yaml()
    assert hasattr(s.search, "max_category_concurrency")
    assert s.search.max_category_concurrency == 5


def test_search_max_batch_ids_default():
    """SearchSettings 应有 max_batch_ids 字段，默认 20。"""
    s = Settings.from_yaml()
    assert hasattr(s.search, "max_batch_ids")
    assert s.search.max_batch_ids == 20


def test_settings_from_yaml_loads_all_fields():
    """完整加载 config.yaml，所有新字段均有值。"""
    s = Settings.from_yaml()
    # 验证新字段存在且类型正确
    assert isinstance(s.database.pool_size, int)
    assert isinstance(s.database.max_overflow, int)
    assert isinstance(s.search.max_category_concurrency, int)
    assert isinstance(s.search.max_batch_ids, int)
    # 验证默认值合理
    assert s.database.pool_size >= 5
    assert s.database.max_overflow >= 0
    assert s.search.max_category_concurrency >= 1
    assert s.search.max_batch_ids >= 1
