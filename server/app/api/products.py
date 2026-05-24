"""
商品数据 API
从 data/ecommerce_agent_dataset 读取 JSON 文件，
提供商品列表和商品详情接口（含 rag_knowledge）
"""
import json
from pathlib import Path
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import JSONResponse

router = APIRouter()

# data/ecommerce_agent_dataset 相对于项目根目录
_DATASET_DIR = Path(__file__).resolve().parents[3] / "data" / "ecommerce_agent_dataset"


def _load_all() -> dict[str, dict]:
    """加载全部商品，缓存在内存里（进程级缓存）"""
    if hasattr(_load_all, "_cache"):
        return _load_all._cache  # type: ignore

    products: dict[str, dict] = {}
    for json_file in _DATASET_DIR.rglob("data/*.json"):
        try:
            with json_file.open("r", encoding="utf-8") as f:
                p = json.load(f)
            pid = p.get("product_id")
            if pid:
                # 把 image_path 转成 API 可访问的 URL
                img_path = p.get("image_path", "")
                p["image_url"] = f"/images/{img_path}" if img_path else None
                products[pid] = p
        except Exception:
            pass

    _load_all._cache = products  # type: ignore
    return products


@router.get("/products")
async def list_products(
    category: Optional[str] = Query(None),
    q:        Optional[str] = Query(None),
    limit:    int            = Query(20, ge=1, le=100),
    offset:   int            = Query(0, ge=0),
) -> JSONResponse:
    all_p = list(_load_all().values())

    if category:
        all_p = [p for p in all_p if category in (p.get("category") or "")]
    if q:
        kw = q.lower()
        all_p = [
            p for p in all_p
            if kw in (p.get("title") or "").lower()
            or kw in (p.get("brand") or "").lower()
            or kw in (p.get("category") or "").lower()
        ]

    total = len(all_p)
    page = all_p[offset : offset + limit]

    # 列表只返回轻量字段，不含 rag_knowledge（节省流量）
    slim: list[dict[str, Any]] = []
    for p in page:
        slim.append({
            "product_id":   p.get("product_id"),
            "title":        p.get("title"),
            "brand":        p.get("brand"),
            "category":     p.get("category"),
            "sub_category": p.get("sub_category"),
            "base_price":   p.get("base_price"),
            "image_url":    p.get("image_url"),
            "skus":         p.get("skus", []),
        })

    return JSONResponse({"total": total, "offset": offset, "limit": limit, "products": slim})


@router.get("/products/{product_id}")
async def get_product(product_id: str) -> JSONResponse:
    """返回商品完整数据，含 rag_knowledge（FAQ + 用户评价）"""
    products = _load_all()
    p = products.get(product_id)
    if not p:
        raise HTTPException(status_code=404, detail=f"Product {product_id} not found")
    return JSONResponse(p)
