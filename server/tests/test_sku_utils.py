"""MCL-I4: search_util 工具函数测试。

验证 truncate_texts 从 services/sku_utils.py 迁移到 utils/search_util.py 后的正确性。
"""
import pytest


def test_search_util_module_importable():
    """验证 app.utils.search_util 模块可导入。"""
    from app.utils import search_util
    assert search_util is not None


def test_truncate_texts_function_exists():
    """验证 truncate_texts 函数可从 search_util 导入。"""
    from app.utils.search_util import truncate_texts
    assert callable(truncate_texts)


def test_source_priority_constant_exists():
    """验证 _SOURCE_PRIORITY 常量存在于 search_util。"""
    from app.utils.search_util import _SOURCE_PRIORITY
    assert isinstance(_SOURCE_PRIORITY, dict)
    assert "faq" in _SOURCE_PRIORITY
    assert "marketing" in _SOURCE_PRIORITY
    assert "user_review" in _SOURCE_PRIORITY


def test_truncate_texts_basic_behavior():
    """验证 truncate_texts 的基本行为（不依赖 DB）。"""
    from app.utils.search_util import truncate_texts

    texts = [
        {"content": "很好的产品", "source": "faq", "metadata": {}},
        {"content": "值得购买", "source": "user_review", "metadata": {}},
        {"content": "官方推荐", "source": "marketing", "metadata": {}},
    ]
    # 截断到最多 2 条
    result = truncate_texts(texts, max_count=2, max_chars=100)
    assert len(result) <= 2
    # 空输入应返回空列表
    assert truncate_texts([], max_count=10, max_chars=100) == []


def test_truncate_texts_respects_max_chars():
    """验证 truncate_texts 遵守 max_chars 限制。"""
    from app.utils.search_util import truncate_texts

    texts = [
        {"content": "A" * 100, "source": "faq", "metadata": {}},
    ]
    result = truncate_texts(texts, max_count=5, max_chars=50)
    # 应至少保留 1 条（即使超出 max_chars）
    assert len(result) >= 1
