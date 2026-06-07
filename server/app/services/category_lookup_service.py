"""
品类查找服务 — 从 category_lookup 表查询并格式化为提示词片段。
"""
import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.category_lookup import CategoryLookup

logger = structlog.get_logger("category_lookup_service")


async def fetch_category_context(db: AsyncSession) -> tuple[str, set[tuple[str, str]]]:
    """从 category_lookup 表加载合法品类数据。

    查询所有 (category, sub_category) 对，按 category 分组聚合为紧凑字符串，
    同时返回用于 O(1) 校验的合法值对集合。

    参数:
        db: 异步 SQLAlchemy 会话。

    返回值:
        (formatted_str, valid_pairs_set):
        - formatted_str: 按 category 分组的品类清单，每行一个 category。
          例: "- 美妆护肤：防晒、洗面奶、面霜"
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
