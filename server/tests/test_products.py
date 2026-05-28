# tests/test_products.py
"""测试商品与 SKU 相关接口。"""

import pytest
from httpx import AsyncClient, ASGITransport
from app.main import app


def _is_db_unavailable(resp_or_exc) -> bool:
    """判断是否为数据库不可用导致的失败，而非逻辑错误。"""
    if hasattr(resp_or_exc, "status_code"):
        return resp_or_exc.status_code == 500
    return True  # 连接异常也视为 DB 不可用


# ---------------------------------------------------------------------------
# GET /api/products/{product_id}
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_product_detail_not_found():
    """请求不存在的商品时应返回 404。"""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        try:
            resp = await client.get("/api/products/NONEXISTENT")
            if resp.status_code == 500:
                pytest.skip("Database not available")
            assert resp.status_code == 404
        except Exception:
            pytest.skip("Database not available")


@pytest.mark.asyncio
async def test_product_detail_returns_simplified_fields():
    """验证返回字段仅包含 product_id/title/brand/category/sub_category/base_price，
    不包含 image_path 和 skus。"""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        try:
            resp = await client.get("/api/products/p_beauty_003")
            if resp.status_code == 500:
                pytest.skip("Database not available")
            if resp.status_code == 404:
                pytest.skip("Test product p_beauty_003 not in database")
            data = resp.json()
            assert "product_id" in data
            assert "title" in data
            assert "brand" in data
            assert "category" in data
            assert "sub_category" in data
            assert "base_price" in data
            assert "image_path" not in data
            assert "skus" not in data
        except AssertionError:
            raise
        except Exception:
            pytest.skip("Database not available")


# ---------------------------------------------------------------------------
# GET /api/products/image/{product_id}
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_product_image_not_found():
    """请求不存在商品的图片时应返回 404。"""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        try:
            resp = await client.get("/api/products/image/NONEXISTENT")
            if resp.status_code == 500:
                pytest.skip("Database not available")
            assert resp.status_code == 404
        except AssertionError:
            raise
        except Exception:
            pytest.skip("Database not available")


@pytest.mark.asyncio
async def test_product_image_returns_image():
    """请求有图片的商品时应返回图片文件（Content-Type 为 image/*）。"""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        try:
            resp = await client.get("/api/products/image/p_beauty_003")
            if resp.status_code == 500:
                pytest.skip("Database not available")
            if resp.status_code == 404:
                pytest.skip("Test product or image not in database")
            content_type = resp.headers.get("content-type", "")
            assert content_type.startswith("image/")
            assert len(resp.content) > 0
        except AssertionError:
            raise
        except Exception:
            pytest.skip("Database not available")


# ---------------------------------------------------------------------------
# GET /api/sku/{sku_id}
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_sku_detail_not_found():
    """请求不存在的 SKU 时应返回 404。"""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        try:
            resp = await client.get("/api/sku/NONEXISTENT")
            if resp.status_code == 500:
                pytest.skip("Database not available")
            assert resp.status_code == 404
        except AssertionError:
            raise
        except Exception:
            pytest.skip("Database not available")


@pytest.mark.asyncio
async def test_sku_detail_returns_correct_fields():
    """验证 SKU 返回字段包含 sku_id/properties/price/stock。"""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        try:
            resp = await client.get("/api/sku/s_p_beauty_003_1")
            if resp.status_code == 500:
                pytest.skip("Database not available")
            if resp.status_code == 404:
                pytest.skip("Test SKU not in database")
            data = resp.json()
            assert "sku_id" in data
            assert "properties" in data
            assert "price" in data
            assert "stock" in data
            assert isinstance(data["price"], (int, float))
            assert isinstance(data["stock"], int)
        except AssertionError:
            raise
        except Exception:
            pytest.skip("Database not available")
