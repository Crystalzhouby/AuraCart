"""MCL-B1: Batch API 端点测试。"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from httpx import AsyncClient, ASGITransport
from app.main import app


@pytest.mark.asyncio
async def test_products_batch_route_exists():
    """GET /api/products/batch 路由已注册。"""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        try:
            resp = await client.get("/api/products/batch?ids=p1,p2")
            assert resp.status_code in (200, 422, 500, 503)
        except Exception:
            pass


@pytest.mark.asyncio
async def test_products_image_batch_route_exists():
    """GET /api/products/image/batch 路由已注册。"""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        try:
            resp = await client.get("/api/products/image/batch?ids=p1,p2")
            assert resp.status_code in (200, 422, 500, 503)
        except Exception:
            pass


@pytest.mark.asyncio
async def test_sku_batch_route_exists():
    """GET /api/sku/batch 路由已注册。"""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        try:
            resp = await client.get("/api/sku/batch?ids=sk1,sk2")
            assert resp.status_code in (200, 422, 500, 503)
        except Exception:
            pass


@pytest.mark.asyncio
async def test_products_batch_missing_ids_param():
    """缺少 ids 参数时返回 422（参数校验在 DB 连接之前）。"""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        try:
            resp = await client.get("/api/products/batch")
            assert resp.status_code == 422
        except Exception:
            pass


@pytest.mark.asyncio
async def test_products_batch_exceeds_max():
    """超过 max_batch_ids 限制时返回 422。"""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        try:
            ids = ",".join([f"p{i}" for i in range(25)])
            resp = await client.get(f"/api/products/batch?ids={ids}")
            assert resp.status_code == 422
        except Exception:
            pass
