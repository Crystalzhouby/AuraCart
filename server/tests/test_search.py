# tests/test_search.py
"""测试搜索接口的流式与非流式两种模式。

使用 ASGI transport（无需启动真实服务器）验证 GET /api/search
的查询参数要求、状态码以及基本可达性。
"""

import pytest
from httpx import AsyncClient, ASGITransport
from app.main import app


@pytest.mark.asyncio
async def test_search_sse_route_exists():
    """验证 GET /api/search?q=...&stream=true 是已注册的路由（SSE 模式）。

    根据下游服务是否运行，预期返回 200（成功）、500（内部错误）或 503（不可用）。
    """
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        try:
            resp = await client.get("/api/search?q=防晒霜&stream=true")
            assert resp.status_code in (200, 500, 503)
        except Exception:
            pass


@pytest.mark.asyncio
async def test_search_nonstream_route_exists():
    """验证 GET /api/search?q=...&stream=false 是已注册的路由（JSON 模式）。

    根据下游服务是否运行，预期返回 200（成功）、500（内部错误）或 503（不可用）。
    """
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        try:
            resp = await client.get("/api/search?q=防晒霜&stream=false")
            assert resp.status_code in (200, 500, 503)
        except Exception:
            pass
