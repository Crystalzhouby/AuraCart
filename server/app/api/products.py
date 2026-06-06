"""
产品与 SKU 查询 API 路由

模块: app.api.products

提供产品基本信息、产品图片以及 SKU 详情的查询接口。
使用 SQLAlchemy 异步会话实现非阻塞数据库访问。
"""
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_db
from app.models.product import Product
from app.models.sku import Sku
from app.schemas.product import ProductInfo, SkuOut

router = APIRouter(prefix="/api", tags=["products"])

# 项目根目录（server/ 的上一级），用于解析 image_path 相对路径
_PROJECT_ROOT = Path(__file__).resolve().parents[3]
# 商品图片目录 = 项目根目录 + 数据集路径 + images/
_IMAGES_DIR = _PROJECT_ROOT / settings.dataset.dir / "images"


# ---------------------------------------------------------------------------
# Batch API 端点
# 注意：这些静态路径必须注册在参数路径（如 /products/{product_id}）之前，
# 否则会被动态路由吞掉，导致前端拿不到商品卡片数据。
# ---------------------------------------------------------------------------


def _normalize_ids(ids: str) -> list[str]:
    """解析、去空格、去重、去空的 ID 列表。

    参数:
        ids: 逗号分隔的 ID 字符串，可能包含空格和重复项。

    返回值:
        list[str]: 去重（保持首次出现顺序）的 ID 列表。
    """
    result: list[str] = []
    seen: set[str] = set()
    for raw in ids.split(","):
        item = raw.strip()
        if item and item not in seen:
            seen.add(item)
            result.append(item)
    return result


@router.get("/products/batch")
async def get_products_batch(
    ids: str = Query(..., min_length=1, description="逗号分隔的 product_id 列表（最多 20 个）"),
    db: AsyncSession = Depends(get_db),
):
    """
    批量获取产品基本信息。

    接口: GET /api/products/batch?ids=p1,p2,p3,...

    参数:
        ids: 逗号分隔的产品 ID 字符串。
        db: 异步 SQLAlchemy 会话。

    返回值:
        list[dict]: 包含 product_id/title/brand/category/sub_category/base_price 的列表。
        不存在的 ID 被忽略（不报错），已下架的被过滤。
    """
    id_list = _normalize_ids(ids)
    max_ids = settings.search.max_batch_ids
    if len(id_list) > max_ids:
        raise HTTPException(status_code=422, detail=f"最多支持 {max_ids} 个 ID")
    if not id_list:
        return []

    rows = await db.execute(
        select(Product).where(
            Product.product_id.in_(id_list),
            Product.is_active == True,
        )
    )
    products = rows.scalars().all()
    return [
        {
            "product_id": p.product_id,
            "title": p.title,
            "brand": p.brand,
            "category": p.category,
            "sub_category": p.sub_category,
            "base_price": float(p.base_price) if p.base_price else None,
        }
        for p in products
    ]


@router.get("/products/image/batch")
async def get_product_images_batch(
    ids: str = Query(..., min_length=1, description="逗号分隔的 product_id 列表（最多 20 个）"),
    db: AsyncSession = Depends(get_db),
):
    """
    批量获取产品图片路径。

    接口: GET /api/products/image/batch?ids=p1,p2,p3,...

    参数:
        ids: 逗号分隔的产品 ID 字符串。
        db: 异步 SQLAlchemy 会话。

    返回值:
        list[dict]: [{product_id, image_url}, ...]。
    """
    id_list = _normalize_ids(ids)
    max_ids = settings.search.max_batch_ids
    if len(id_list) > max_ids:
        raise HTTPException(status_code=422, detail=f"最多支持 {max_ids} 个 ID")
    if not id_list:
        return []

    rows = await db.execute(
        select(Product.product_id, Product.image_path).where(
            Product.product_id.in_(id_list),
            Product.is_active == True,
        )
    )
    return [
        {"product_id": row.product_id, "image_url": row.image_path}
        for row in rows
    ]


@router.get("/sku/batch")
async def get_sku_batch(
    ids: str = Query(..., min_length=1, description="逗号分隔的 sku_id 列表（最多 20 个）"),
    db: AsyncSession = Depends(get_db),
):
    """
    批量获取 SKU 详情。

    接口: GET /api/sku/batch?ids=sk1,sk2,sk3,...

    参数:
        ids: 逗号分隔的 SKU ID 字符串。
        db: 异步 SQLAlchemy 会话。

    返回值:
        list[dict]: [{sku_id, product_id, properties, price, stock}, ...]。
    """
    id_list = _normalize_ids(ids)
    max_ids = settings.search.max_batch_ids
    if len(id_list) > max_ids:
        raise HTTPException(status_code=422, detail=f"最多支持 {max_ids} 个 ID")
    if not id_list:
        return []

    rows = await db.execute(
        select(Sku).where(
            Sku.sku_id.in_(id_list),
            Sku.is_active == True,
        )
    )
    skus = rows.scalars().all()
    return [
        {
            "sku_id": s.sku_id,
            "product_id": s.product_id,
            "properties": s.properties,
            "price": float(s.price),
            "stock": s.stock,
        }
        for s in skus
    ]


# ---------------------------------------------------------------------------
# 单条查询端点
# ---------------------------------------------------------------------------


@router.get("/products/{product_id}", response_model=ProductInfo)
async def get_product(
    product_id: str,
    db: AsyncSession = Depends(get_db),
):
    """
    根据产品 ID 获取产品基本信息。

    接口: GET /api/products/{product_id}

    参数:
        product_id: 产品唯一标识符。
        db: 异步 SQLAlchemy 会话。

    返回值:
        ProductInfo: 包含 product_id/title/brand/category/sub_category/base_price。

    异常:
        HTTPException: 产品未找到或已停用返回 404。
    """
    prod = await db.execute(
        select(Product).where(
            Product.product_id == product_id,
            Product.is_active == True,
        )
    )
    prod = prod.scalar_one_or_none()
    if prod is None:
        raise HTTPException(status_code=404, detail="Product not found")

    return prod


@router.get("/products/image/{product_id}")
async def get_product_image(
    product_id: str,
    db: AsyncSession = Depends(get_db),
):
    """
    根据产品 ID 返回产品图片文件。

    接口: GET /api/products/image/{product_id}

    参数:
        product_id: 产品唯一标识符。
        db: 异步 SQLAlchemy 会话。

    返回值:
        FileResponse: 图片文件二进制流。

    异常:
        HTTPException: 产品未找到、已停用或无图片时返回 404。
    """
    prod = await db.execute(
        select(Product.image_path).where(
            Product.product_id == product_id,
            Product.is_active == True,
        )
    )
    image_path = prod.scalar_one_or_none()
    if image_path is None:
        raise HTTPException(status_code=404, detail="Product not found")

    file_path = _IMAGES_DIR / Path(image_path).name
    if not file_path.is_file():
        raise HTTPException(status_code=404, detail="Image not found")

    return FileResponse(str(file_path))


@router.get("/sku/{sku_id}", response_model=SkuOut)
async def get_sku(
    sku_id: str,
    db: AsyncSession = Depends(get_db),
):
    """
    根据 SKU ID 获取单个 SKU 的详细信息。

    接口: GET /api/sku/{sku_id}

    参数:
        sku_id: SKU 唯一标识符。
        db: 异步 SQLAlchemy 会话。

    返回值:
        SkuOut: 包含 sku_id/properties/price/stock。

    异常:
        HTTPException: SKU 未找到或已停用返回 404。
    """
    sku = await db.execute(
        select(Sku).where(
            Sku.sku_id == sku_id,
            Sku.is_active == True,
        )
    )
    sku = sku.scalar_one_or_none()
    if sku is None:
        raise HTTPException(status_code=404, detail="SKU not found")

    return sku
