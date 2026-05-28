"""
产品与 SKU 查询 API 路由

模块: app.api.products

提供产品基本信息、产品图片以及 SKU 详情的查询接口。
使用 SQLAlchemy 异步会话实现非阻塞数据库访问。
"""
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

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
