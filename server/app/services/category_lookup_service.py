"""
品类查找服务 — 为查询解析提供合法的 (category, sub_category) 值对。

功能:
- fetch_category_context(): 从 category_lookup 表查询并格式化为提示词片段
- validate_categories(): 后校验，将不在合法集合中的 category/sub_category 置 null
"""
import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.category_lookup import CategoryLookup

logger = structlog.get_logger("category_lookup_service")

__all__ = ["fetch_category_context", "validate_categories"]


async def fetch_category_context(db: AsyncSession) -> tuple[str, set[tuple[str, str]]]:
    """从 category_lookup 表加载合法品类数据。

    查询所有 (category, sub_category) 对，按 category 分组聚合为紧凑字符串，
    同时返回用于 O(1) 校验的合法值对集合。

    参数:
        db: 异步 SQLAlchemy 会话。

    返回值:
        (formatted_str, valid_pairs_set):
        - formatted_str: 按 category 分组的品类清单，每行一个 category。
          例: "- 面部护肤：防晒霜、洗面奶、面霜"
          异常或空表返回 ""。
        - valid_pairs_set: set[tuple[str, str]]，后校验用。
    """
    try:
        result = await db.execute(
            select(CategoryLookup.category, CategoryLookup.sub_category)
            .order_by(CategoryLookup.category, CategoryLookup.sub_category)
        )
        rows = result.all()
    except Exception as e:
        logger.warning("品类列表查询失败，回退为空", error=str(e))
        return "", set()

    if not rows:
        logger.warning("category_lookup 表为空，品类约束失效")
        return "", set()

    # 按 category 分组
    grouped: dict[str, list[str]] = {}
    for cat, sub in rows:
        grouped.setdefault(cat, []).append(sub)

    lines = [f"- {cat}：{'、'.join(subs)}" for cat, subs in grouped.items()]
    formatted = "\n".join(lines)
    valid_set = {(cat, sub) for cat, sub in rows}

    logger.debug("品类列表已加载", categories=len(grouped), pairs=len(valid_set))
    return formatted, valid_set


def validate_categories(
    sub_queries: list,
    valid_pairs: set[tuple[str, str]],
) -> list:
    """后校验：将不在合法集合中的 category/sub_category 置 None。

    确保 LLM 生成的品类值严格匹配 category_lookup 表中的数据。
    仅修正不合法的值，不影响 null 和合法值。

    参数:
        sub_queries: SubQuery 列表（含 category/sub_category 属性）。
        valid_pairs: 合法的 (category, sub_category) 值对集合。

    返回值:
        原地修正后的 sub_queries 列表（与输入同一引用）。
    """
    if not valid_pairs:
        return sub_queries

    valid_categories: set[str] = {c for c, _ in valid_pairs}

    for sq in sub_queries:
        if sq.category and sq.sub_category:
            # 完整值对校验
            if (sq.category, sq.sub_category) not in valid_pairs:
                logger.debug(
                    "品类值对不合法，已置 null",
                    input=(sq.category, sq.sub_category),
                )
                sq.category = None
                sq.sub_category = None
        elif sq.category and not sq.sub_category:
            # 仅 category 不为 null：检查 category 是否属于已知大类
            if sq.category not in valid_categories:
                logger.debug(
                    "category 不合法，已置 null",
                    input=sq.category,
                )
                sq.category = None

    return sub_queries
