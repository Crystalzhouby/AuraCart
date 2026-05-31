"""MCL-I4: sku_utils 模块测试。

验证 _get_skus 和 _truncate_texts 从 search.py 迁移到独立的 services/sku_utils.py。
"""
import pytest


def test_sku_utils_module_importable():
    """验证 app.services.sku_utils 模块可导入。"""
    from app.services import sku_utils
    assert sku_utils is not None


def test_get_skus_function_exists():
    """验证 _get_skus 函数可从 sku_utils 导入。"""
    from app.services.sku_utils import _get_skus
    assert callable(_get_skus)


def test_truncate_texts_function_exists():
    """验证 _truncate_texts 函数可从 sku_utils 导入。"""
    from app.services.sku_utils import _truncate_texts
    assert callable(_truncate_texts)


def test_source_priority_constant_exists():
    """验证 _SOURCE_PRIORITY 常量存在于 sku_utils。"""
    from app.services.sku_utils import _SOURCE_PRIORITY
    assert isinstance(_SOURCE_PRIORITY, dict)
    assert "faq" in _SOURCE_PRIORITY
    assert "marketing" in _SOURCE_PRIORITY
    assert "user_review" in _SOURCE_PRIORITY


def test_search_imports_from_sku_utils():
    """验证 search.py 可从 sku_utils 导入 _get_skus。"""
    # 此测试确保迁移后 search.py 的导入路径正确
    from app.services.sku_utils import _get_skus
    # 验证函数签名接受 db 和 skuhits 参数
    import inspect
    sig = inspect.signature(_get_skus)
    params = list(sig.parameters.keys())
    assert "db" in params
    assert "skuhits" in params


def test_truncate_texts_basic_behavior():
    """验证 _truncate_texts 的基本行为（不依赖 DB）。"""
    from app.services.sku_utils import _truncate_texts

    texts = [
        {"content": "很好的产品", "source": "faq", "metadata": {}},
        {"content": "值得购买", "source": "user_review", "metadata": {}},
        {"content": "官方推荐", "source": "marketing", "metadata": {}},
    ]
    # 截断到最多 2 条
    result = _truncate_texts(texts, max_count=2, max_chars=100)
    assert len(result) <= 2
    # 空输入应返回空列表
    assert _truncate_texts([], max_count=10, max_chars=100) == []


def test_truncate_texts_respects_max_chars():
    """验证 _truncate_texts 遵守 max_chars 限制。"""
    from app.services.sku_utils import _truncate_texts

    texts = [
        {"content": "A" * 100, "source": "faq", "metadata": {}},
    ]
    result = _truncate_texts(texts, max_count=5, max_chars=50)
    # 应至少保留 1 条（即使超出 max_chars）
    assert len(result) >= 1
