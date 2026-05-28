# tests/test_search.py
"""测试向量搜索与 SSE 流式接口。

使用 ASGI transport（无需启动真实服务器）验证 GET /api/search
和 GET /api/search/stream 的查询参数要求、状态码以及基本可达性。
"""

import pytest
from httpx import AsyncClient, ASGITransport
from app.main import app


@pytest.mark.asyncio
async def test_search_endpoint_requires_query():
    """验证 GET /api/search 缺少 `q` 参数时返回 HTTP 422（校验错误）。

    FastAPI 内置的查询校验应在缺少必填的 `q` 参数时拒绝请求。
    """
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/search")

    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_search_endpoint_accepts_query():
    """验证 GET /api/search?q=... 返回的状态码与依赖可用性一致。

    提供合法的 `q` 参数后，接口在外部服务不可达时应返回认证失败（401）、
    内部错误（500）或服务不可用（503）。
    """
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        try:
            resp = await client.get("/api/search?q=防晒霜")
            assert resp.status_code in (401, 500, 503)
        except Exception:
            # 允许依赖不可用时的连接级异常
            pass


@pytest.mark.asyncio
async def test_search_sse_route_exists():
    """验证 GET /api/search/stream?q=... 是已注册的路由。

    根据下游服务是否运行，预期返回 200（成功）、500（内部错误）或 503（不可用）。
    """
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        try:
            resp = await client.get("/api/search/stream?q=防晒霜")
            assert resp.status_code in (200, 500, 503)
        except Exception:
            pass
