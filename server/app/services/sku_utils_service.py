"""
SKU 工具函数模块。

从 app.api.search.py 迁移至此，供 Agent 节点（retrieval.py）和 API 层（search.py）
共同调用。函数签名和实现逻辑与迁移前完全一致。

核心函数：
- _truncate_texts: 按 source 优先级排序后截断匹配文本列表
- _get_skus: 将 SKUHit 列表填充为扁平 SKU 字典
"""
import structlog
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.models.product import Product
from app.models.sku import Sku
from app.models.product_review import ProductReview
from app.services.retriever_service import SKUHit
from app.config import settings

logger = structlog.get_logger("agent.retrieval")

# source → 优先级（数值越小优先级越高），供 _truncate_texts 排序
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

    # 按 source 优先级排序
    sorted_texts = sorted(
        matched_texts,
        key=lambda t: _SOURCE_PRIORITY.get(t.get("source", ""), 99),
    )

    # 按字符数截断 + 条数截断
    result: list[dict] = []
    char_total = 0
    for item in sorted_texts:
        if len(result) >= max_count:
            break
        content = item.get("content", "")
        char_total += len(content)
        if char_total > max_chars and result:
            # 至少保留一条，超出预算时停止追加
            break
        result.append(item)

    return result


async def _get_skus(
    db: AsyncSession,
    skuhits: list[SKUHit],
) -> list[dict]:
    """
    将 SKUHit 列表填充为扁平 SKU 字典，每个包含所属 product 信息和匹配文本。

    按 sku_id 查询 SKU 表并 JOIN product 表补全产品字段，
    LEFT JOIN product_review 表附带评论文本，经聚合和截断后注入 matched_texts。

    参数:
        db (AsyncSession): 异步 SQLAlchemy 会话。
        skuhits (list[SKUHit]): 按 RRF 排名排序的 SKU 命中列表。

    返回值:
        list[dict]: 扁平 SKU 字典列表，包含 product 字段
                    （product_id/title/brand/category/sub_category/base_price）、
                    SKU 字段（sku_id/properties/price/stock）
                    以及 matched_texts（list[dict]）。
    """
    if not skuhits:
        return []

    sku_ids = [h.sku_id for h in skuhits]

    # 批量查询 SKU + JOIN product + LEFT JOIN product_review，一次 SQL 完成
    stmt = (
        select(
            Product.product_id, Product.title, Product.brand,
            Product.category, Product.sub_category, Product.base_price,
            Sku.sku_id, Sku.properties, Sku.price, Sku.stock,
            ProductReview.content, ProductReview.source, ProductReview.extra_data,
        )
        .join(Sku, Sku.product_id == Product.product_id)
        .outerjoin(ProductReview, ProductReview.product_id == Product.product_id)
        .where(
            Sku.sku_id.in_(sku_ids),
            Sku.is_active == True,
            Product.is_active == True,
        )
    )
    logger.info("_get_skus SQL",
                sql=str(stmt.compile(compile_kwargs={"literal_binds": True})),
                sku_ids=sku_ids[:20])
    rows = await db.execute(stmt)

    # 按 sku_id 聚合：LEFT JOIN 会导致同一 SKU 出现多行（每个 product_review 一行）
    row_by_sku: dict[str, dict] = {}
    texts_by_sku: dict[str, list[dict]] = {}
    for row in rows:
        sid = row.sku_id
        if sid not in row_by_sku:
            row_by_sku[sid] = {
                "product_id": row.product_id,
                "title": row.title,
                "brand": row.brand,
                "category": row.category,
                "sub_category": row.sub_category,
                "base_price": float(row.base_price) if row.base_price else None,
                "sku_id": row.sku_id,
                "properties": row.properties,
                "price": float(row.price),
                "stock": row.stock,
            }
            texts_by_sku[sid] = []

        # 收集 product_review 文本（content 非空时才追加）
        if row.content:
            texts_by_sku[sid].append({
                "content": row.content,
                "source": row.source,
                "metadata": row.extra_data,
            })

    # 截断 + 保持 RRF 排名顺序
    max_count = settings.search.max_match_texts_per_sku
    max_chars = settings.search.max_match_chars_per_sku
    result = []
    for h in skuhits:
        item = row_by_sku.get(h.sku_id)
        if item is not None:
            raw_texts = texts_by_sku.get(h.sku_id, [])
            item["matched_texts"] = _truncate_texts(raw_texts, max_count, max_chars)
            result.append(item)

    return result
