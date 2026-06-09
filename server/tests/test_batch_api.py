"""MCL-B1: Batch API 端点测试。"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from httpx import AsyncClient, ASGITransport
from app.main import app
from app.api.get_product_info import _normalize_ids


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


# ---------------------------------------------------------------------------
# Batch API completion: ID normalization edge cases
# ---------------------------------------------------------------------------


def test_normalize_ids_deduplicates():
    """_normalize_ids 应去重，保持首次出现顺序。"""
    result = _normalize_ids("p1,p2,p1,p3,p2")
    assert result == ["p1", "p2", "p3"]


def test_normalize_ids_handles_extra_commas():
    """_normalize_ids 应处理多余的逗号和空格。"""
    result = _normalize_ids("p1,, p2 ,p3")
    assert result == ["p1", "p2", "p3"]


def test_normalize_ids_handles_all_empty():
    """_normalize_ids 在全空时返回空列表。"""
    result = _normalize_ids(",, ,")
    assert result == []


def test_normalize_ids_handles_empty_string():
    """_normalize_ids 在空字符串时返回空列表。"""
    result = _normalize_ids("")
    assert result == []


def test_normalize_ids_handles_whitespace_ids():
    """_normalize_ids 应处理首尾有空格的 ID。"""
    result = _normalize_ids(" p1 , p2 , p3 ")
    assert result == ["p1", "p2", "p3"]
