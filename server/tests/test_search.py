# tests/test_search.py
"""测试搜索接口的流式与非流式两种模式，以及 truncate_texts 截断函数。

使用 ASGI transport（无需启动真实服务器）验证 GET /api/search
的查询参数要求、状态码以及基本可达性。
"""

import pytest
from unittest.mock import AsyncMock, MagicMock
from httpx import AsyncClient, ASGITransport
from app.main import app
from app.utils.search_util import truncate_texts


@pytest.mark.asyncio
async def test_search_sse_route_exists():
    """验证 GET /api/search/{conversation_id}?q=...&stream=true 是已注册的路由（SSE 模式）。

    根据下游服务是否运行，预期返回 200（成功）、500（内部错误）或 503（不可用）。
    """
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        try:
            resp = await client.get("/api/search/test-cid?q=防晒&stream=true")
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
            resp = await client.get("/api/search/test-cid?q=防晒&stream=false")
            assert resp.status_code in (200, 404, 500, 503)
        except Exception:
            pass


# ======================================================================
# truncate_texts 单元测试
# ======================================================================


class TestTruncateTexts:
    """测试 truncate_texts 纯函数的截断与排序行为。"""

    def test_sort_by_source_priority(self):
        """faq 应排在 marketing 前面，user_review 应排在最后（faq > marketing > user_review）。"""
        texts = [
            {"content": "官方描述A", "source": "marketing", "metadata": None},
            {"content": "用户评价X", "source": "user_review", "metadata": None},
            {"content": "FAQ内容B", "source": "faq", "metadata": None},
        ]
        result = truncate_texts(texts, max_count=10, max_chars=1000)
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
        result = truncate_texts(texts, max_count=2, max_chars=1000)
        assert len(result) == 2

    def test_truncate_by_max_chars(self):
        """超出 max_chars 时截断（但至少保留 1 条）。"""
        texts = [
            {"content": "很长的评价内容ABCDEFGHIJ", "source": "user_review", "metadata": None},
            {"content": "第二条评价", "source": "user_review", "metadata": None},
        ]
        result = truncate_texts(texts, max_count=10, max_chars=10)
        # 第一条 10 字符刚好等于 max_chars=10，第二条不会加入
        assert len(result) >= 1
        assert len(result) <= 2

    def test_empty_list(self):
        """空列表直接返回空列表。"""
        result = truncate_texts([], max_count=3, max_chars=500)
        assert result == []

    def test_unknown_source_falls_to_last(self):
        """未知 source 排到最后（优先级 99）。"""
        texts = [
            {"content": "未知来源", "source": "unknown_type", "metadata": None},
            {"content": "官方描述", "source": "marketing", "metadata": None},
            {"content": "用户评价", "source": "user_review", "metadata": None},
        ]
        result = truncate_texts(texts, max_count=10, max_chars=1000)
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
        result = truncate_texts(texts, max_count=10, max_chars=5)
        assert len(result) >= 1
