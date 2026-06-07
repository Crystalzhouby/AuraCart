"""
SKU 工具函数模块。

从 app.api.search.py 迁移至此，供 Agent 节点（retrieval.py）和 API 层（search.py）
共同调用。

核心函数：
- _truncate_texts: 按 source 优先级排序后截断匹配文本列表
- _get_products: 将 ProductHit 列表填充为扁平 product 字典
"""
import structlog
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.models.product import Product
from app.models.sku import Sku
from app.models.product_review import ProductReview
from app.services.retriever_service import ProductHit
from app.config import settings

logger = structlog.get_logger("agent.retrieval")

_SOURCE_PRIORITY = {"faq": 0, "marketing": 1, "user_review": 2}


def _truncate_texts(
    matched_texts: list[dict],
    max_count: int,
    max_chars: int,
) -> list[dict]:
    """按 source 优先级排序后截断匹配文本列表。

    优先级: faq > marketing > user_review。先按优先级排序，再依次累加
    字符数，超出 max_chars 时截断，最后截取前 max_count 条。

    参数:
        matched_texts: 待截断的文本列表，每条为 {"content","source","metadata"}。
        max_count: 最多保留条数。
        max_chars: content 字段累计字符数上限。

    返回值:
        截断后的文本列表。
    """
    if not matched_texts:
        return []

    sorted_texts = sorted(
        matched_texts,
        key=lambda t: _SOURCE_PRIORITY.get(t.get("source", ""), 99),
    )

    result: list[dict] = []
    char_total = 0
    for item in sorted_texts:
        if len(result) >= max_count:
            break
        content = item.get("content", "")
        char_total += len(content)
        if char_total > max_chars and result:
            break
        result.append(item)

    return result


async def _get_products(
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
    logger.info("_get_products SQL",
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
            item["matched_texts"] = _truncate_texts(raw_texts, max_count, max_chars)
            result.append(item)

    return result
