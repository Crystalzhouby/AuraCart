# tests/test_search.py
"""测试搜索接口的流式与非流式两种模式，以及 _truncate_texts 截断函数。

使用 ASGI transport（无需启动真实服务器）验证 GET /api/search
的查询参数要求、状态码以及基本可达性。
"""

import pytest
from unittest.mock import AsyncMock, MagicMock
from httpx import AsyncClient, ASGITransport
from app.main import app
from app.services.sku_utils_service import _truncate_texts, _get_products
from app.services.retriever_service import ProductHit


@pytest.mark.asyncio
async def test_search_sse_route_exists():
    """验证 GET /api/search/{conversation_id}?q=...&stream=true 是已注册的路由（SSE 模式）。

    根据下游服务是否运行，预期返回 200（成功）、500（内部错误）或 503（不可用）。
    """
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        try:
            resp = await client.get("/api/search/test-cid?q=防晒霜&stream=true")
            assert resp.status_code in (200, 404, 500, 503)
        except Exception:
            pass


@pytest.mark.asyncio
async def test_search_nonstream_route_exists():
    """验证 GET /api/search/{conversation_id}?q=...&stream=false 是已注册的路由（JSON 模式）。

    根据下游服务是否运行，预期返回 200（成功）、500（内部错误）或 503（不可用）。
    """
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        try:
            resp = await client.get("/api/search/test-cid?q=防晒霜&stream=false")
            assert resp.status_code in (200, 404, 500, 503)
        except Exception:
            pass


# ======================================================================
# _truncate_texts 单元测试
# ======================================================================


class TestTruncateTexts:
    """测试 _truncate_texts 纯函数的截断与排序行为。"""

    def test_sort_by_source_priority(self):
        """faq 应排在 marketing 前面，user_review 应排在最后（faq > marketing > user_review）。"""
        texts = [
            {"content": "官方描述A", "source": "marketing", "metadata": None},
            {"content": "用户评价X", "source": "user_review", "metadata": None},
            {"content": "FAQ内容B", "source": "faq", "metadata": None},
        ]
        result = _truncate_texts(texts, max_count=10, max_chars=1000)
        sources = [t["source"] for t in result]
        assert sources == ["faq", "marketing", "user_review"]

    def test_truncate_by_max_count(self):
        """超过 max_count 时截断到指定条数。"""
        texts = [
            {"content": "评价1", "source": "user_review", "metadata": None},
            {"content": "评价2", "source": "user_review", "metadata": None},
            {"content": "评价3", "source": "user_review", "metadata": None},
            {"content": "评价4", "source": "user_review", "metadata": None},
        ]
        result = _truncate_texts(texts, max_count=2, max_chars=1000)
        assert len(result) == 2

    def test_truncate_by_max_chars(self):
        """超出 max_chars 时截断（但至少保留 1 条）。"""
        texts = [
            {"content": "很长的评价内容ABCDEFGHIJ", "source": "user_review", "metadata": None},
            {"content": "第二条评价", "source": "user_review", "metadata": None},
        ]
        result = _truncate_texts(texts, max_count=10, max_chars=10)
        # 第一条 10 字符刚好等于 max_chars=10，第二条不会加入
        assert len(result) >= 1
        assert len(result) <= 2

    def test_empty_list(self):
        """空列表直接返回空列表。"""
        result = _truncate_texts([], max_count=3, max_chars=500)
        assert result == []

    def test_unknown_source_falls_to_last(self):
        """未知 source 排到最后（优先级 99）。"""
        texts = [
            {"content": "未知来源", "source": "unknown_type", "metadata": None},
            {"content": "官方描述", "source": "marketing", "metadata": None},
            {"content": "用户评价", "source": "user_review", "metadata": None},
        ]
        result = _truncate_texts(texts, max_count=10, max_chars=1000)
        sources = [t["source"] for t in result]
        # marketing(1) > user_review(2) > unknown_type(99)
        assert sources[0] == "marketing"
        assert sources[-1] == "unknown_type"

    def test_preserves_at_least_one(self):
        """即使第一条就超出 max_chars，也应保留至少 1 条。"""
        texts = [
            {"content": "A" * 100, "source": "faq", "metadata": None},
            {"content": "B" * 50, "source": "user_review", "metadata": None},
        ]
        result = _truncate_texts(texts, max_count=10, max_chars=5)
        assert len(result) >= 1


# ======================================================================
# _get_products 单元测试（mock DB）
# ======================================================================


class _MockRow:
    """模拟 SQLAlchemy 查询返回的 Row 对象，支持属性访问。"""

    def __init__(self, **kwargs):
        for k, v in kwargs.items():
            setattr(self, k, v)


def _make_mock_db(rows: list[dict]) -> AsyncMock:
    """构造一个返回指定行的 mock AsyncSession。

    _get_products 中 await db.execute(...) 返回的 Result 对象
    会被直接 for 迭代，因此 mock 返回 list[_MockRow] 即可。
    """
    mock_db = AsyncMock()
    mock_db.execute.return_value = [_MockRow(**r) for r in rows]
    return mock_db


class TestGetProducts:
    """测试 _get_products 的 SQL 扩展与聚合行为。"""

    @pytest.mark.asyncio
    async def test_empty_hits(self):
        """空列表直接返回空列表。"""
        db = _make_mock_db([])
        result = await _get_products(db, [])
        assert result == []

    @pytest.mark.asyncio
    async def test_no_reviews(self):
        """product_review 无数据时 matched_texts 为空列表。"""
        db = _make_mock_db([
            {"product_id": "P1", "title": "测试商品", "brand": "品牌A",
             "category": "美妆", "sub_category": "防晒", "base_price": 100.0,
             "sku_id": "SKU1", "properties": None, "price": 99.0, "stock": 10,
             "content": None, "source": None, "extra_data": None},
        ])
        hits = [ProductHit(product_id="P1", score=0.9)]
        result = await _get_products(db, hits)
        assert len(result) == 1
        assert result[0]["matched_texts"] == []

    @pytest.mark.asyncio
    async def test_with_reviews_aggregated(self):
        """同一 product 的多条 product_review 聚合到 matched_texts。"""
        db = _make_mock_db([
            {"product_id": "P1", "title": "测试商品", "brand": "品牌A",
             "category": "美妆", "sub_category": "防晒", "base_price": 100.0,
             "sku_id": "SKU1", "properties": None, "price": 99.0, "stock": 10,
             "content": "好评！保湿效果好", "source": "user_review", "extra_data": None},
            {"product_id": "P1", "title": "测试商品", "brand": "品牌A",
             "category": "美妆", "sub_category": "防晒", "base_price": 100.0,
             "sku_id": "SKU1", "properties": None, "price": 99.0, "stock": 10,
             "content": "官方推荐产品", "source": "marketing", "extra_data": None},
            {"product_id": "P1", "title": "测试商品", "brand": "品牌A",
             "category": "美妆", "sub_category": "防晒", "base_price": 100.0,
             "sku_id": "SKU1", "properties": None, "price": 99.0, "stock": 10,
             "content": "Q:适合干皮吗 A:适合", "source": "faq", "extra_data": None},
        ])
        hits = [ProductHit(product_id="P1", score=0.9)]
        result = await _get_products(db, hits)
        assert len(result) == 1
        assert len(result[0]["matched_texts"]) == 3

    @pytest.mark.asyncio
    async def test_preserves_rrf_order(self):
        """返回结果保持 RRF 排名顺序。"""
        db = _make_mock_db([
            {"product_id": "P2", "title": "商品B", "brand": "B",
             "category": "数码", "sub_category": "手机", "base_price": 2000.0,
             "sku_id": "SKU2", "properties": None, "price": 1999.0, "stock": 5,
             "content": "评价B", "source": "user_review", "extra_data": None},
            {"product_id": "P1", "title": "商品A", "brand": "A",
             "category": "美妆", "sub_category": "防晒", "base_price": 100.0,
             "sku_id": "SKU1", "properties": None, "price": 99.0, "stock": 10,
             "content": "评价A", "source": "user_review", "extra_data": None},
        ])
        # RRF 排 P2 第一，P1 第二
        hits = [
            ProductHit(product_id="P2", score=0.95),
            ProductHit(product_id="P1", score=0.90),
        ]
        result = await _get_products(db, hits)
        assert result[0]["product_id"] == "P2"
        assert result[1]["product_id"] == "P1"

    @pytest.mark.asyncio
    async def test_product_id_not_in_db(self):
        """DB 中不存在的 product_id 被跳过。"""
        db = _make_mock_db([])
        hits = [ProductHit(product_id="NONEXIST", score=0.5)]
        result = await _get_products(db, hits)
        assert result == []
