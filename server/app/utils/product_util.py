"""商品查询工具 — 将 ProductHit 列表填充为扁平 product 字典。"""
import structlog
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.models.product import Product
from app.models.sku import Sku
from app.models.product_review import ProductReview
from app.services.retriever_service import ProductHit
from app.config import settings
from app.utils.search_util import truncate_texts

logger = structlog.get_logger("agent.retrieval")


async def get_products(
    db: AsyncSession,
    hits: list[ProductHit],
) -> list[dict]:
    """将 ProductHit 列表填充为扁平 product 字典。

    按 product_id 查询 Product 表并 JOIN sku 表补全 SKU 字段，
    LEFT JOIN product_review 表附带评论文本，经聚合和截断后注入 matched_texts。

    参数:
        db: 异步 SQLAlchemy 会话。
        hits: 按 RRF 排名排序的 ProductHit 列表。

    返回值:
        list[dict]: 扁平 product 字典列表，包含 product 字段、
                    skus（list）和 matched_texts（list[dict]）。
    """
    if not hits:
        return []

    product_ids = [h.product_id for h in hits]

    stmt = (
        select(
            Product.product_id, Product.title, Product.brand,
            Product.category, Product.sub_category, Product.base_price,
            Sku.sku_id, Sku.properties, Sku.price, Sku.stock,
            ProductReview.content, ProductReview.source, ProductReview.extra_data,
        )
        .outerjoin(Sku, Sku.product_id == Product.product_id)
        .outerjoin(ProductReview, ProductReview.product_id == Product.product_id)
        .where(
            Product.product_id.in_(product_ids),
            Product.is_active == True,
        )
    )
    logger.info("get_products SQL",
                sql=str(stmt.compile(compile_kwargs={"literal_binds": True})),
                product_ids=product_ids[:20])
    rows = await db.execute(stmt)

    # 按 product_id 聚合
    row_by_pid: dict[str, dict] = {}
    texts_by_pid: dict[str, list[dict]] = {}
    for row in rows:
        pid = row.product_id
        if pid not in row_by_pid:
            row_by_pid[pid] = {
                "product_id": row.product_id,
                "title": row.title,
                "brand": row.brand,
                "category": row.category,
                "sub_category": row.sub_category,
                "base_price": float(row.base_price) if row.base_price else None,
                "skus": [],
            }
            texts_by_pid[pid] = []

        # 收集 SKU（去重）
        if row.sku_id:
            existing_sku_ids = {s["sku_id"] for s in row_by_pid[pid]["skus"]}
            if row.sku_id not in existing_sku_ids:
                row_by_pid[pid]["skus"].append({
                    "sku_id": row.sku_id,
                    "properties": row.properties,
                    "price": float(row.price),
                    "stock": row.stock,
                })

        if row.content:
            texts_by_pid[pid].append({
                "content": row.content,
                "source": row.source,
                "metadata": row.extra_data,
            })

    max_count = settings.search.max_match_texts_per_product
    max_chars = settings.search.max_match_chars_per_product
    result = []
    for h in hits:
        item = row_by_pid.get(h.product_id)
        if item is not None:
            raw_texts = texts_by_pid.get(h.product_id, [])
            item["matched_texts"] = truncate_texts(raw_texts, max_count, max_chars)
            result.append(item)

    return result
