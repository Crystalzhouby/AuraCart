"""
Agent 内部数据库查询 Tool 模块。

提供 query_field_values / get_brands_by_categories 两个函数，
供 Extraction / Scenario Gen 节点在执行意图提取前查询字段取值和品牌。

安全设计：table / field / filter_key 均通过白名单校验后拼接为
参数化 SQL，防止 LLM 幻觉输出的非法值引发 SQL 注入。
"""

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text
import structlog

logger = structlog.get_logger("agent.tools")

# ---------------------------------------------------------------------------
# 白名单：允许查询的表和字段
# ---------------------------------------------------------------------------
_ALLOWED_TABLES = {
    "product", "sku", "product_review", "product_marketing",
    "product_faq", "user_review", "category_lookup", "conversation",
}

_ALLOWED_FIELDS_BY_TABLE: dict[str, set[str]] = {
    "product": {"product_id", "title", "brand", "category", "sub_category",
                "base_price", "image_path", "is_active"},
    "sku": {"sku_id", "product_id", "price", "stock", "properties", "is_active"},
    "product_review": {"product_id", "source", "content"},
    "product_marketing": {"product_id", "description"},
    "product_faq": {"product_id", "question", "answer"},
    "user_review": {"product_id", "nickname", "rating", "content"},
    "category_lookup": {"category", "sub_category"},
    "conversation": {"conversation_id"},
}

async def query_field_values(
    db: AsyncSession,
    table: str,
    field: str,
    filters: dict | None = None,
) -> list:
    """查询指定表某个字段的去重取值列表，支持多字段联合过滤。

    例: query_field_values(db, "product", "brand",
          {"category": "美妆护肤", "sub_category": "防晒"})
    返回: ["安热沙", "资生堂", ...]

    参数:
        db: 异步 SQLAlchemy 会话。
        table: 表名（必须在白名单内）。
        field: 字段名（必须在对应表的字段白名单内）。
        filters: 可选过滤条件 {column: value}，key 必须在字段白名单内。

    返回值:
        去重后的字段取值列表（按值升序排列）。非法参数或查询失败返回空列表。
    """
    # --- 白名单校验 ---
    if table not in _ALLOWED_TABLES:
        logger.warning("query_field_values 表名不在白名单", table=table)
        return []

    allowed_fields = _ALLOWED_FIELDS_BY_TABLE.get(table, set())
    if field not in allowed_fields:
        logger.warning("query_field_values 字段名不在白名单",
                       table=table, field=field)
        return []

    # --- 构建参数化 SQL ---
    # 基础查询
    sql_str = f'SELECT DISTINCT "{field}" FROM "{table}"'

    params: dict = {}
    if filters:
        where_parts = []
        for i, (fk, fv) in enumerate(filters.items()):
            if fk not in allowed_fields:
                logger.warning("query_field_values 过滤字段不在白名单",
                               table=table, field=fk)
                return []
            param_name = f"fv_{i}"
            where_parts.append(f'"{fk}" = :{param_name}')
            params[param_name] = fv
        if where_parts:
            sql_str += " WHERE " + " AND ".join(where_parts)

    sql_str += f' ORDER BY "{field}"'

    try:
        sql = text(sql_str)
        result = await db.execute(sql, params)
        rows = result.fetchall()
    except Exception as e:
        logger.warning("query_field_values 查询失败",
                       table=table, field=field, error=str(e))
        return []

    return [row[0] for row in rows]


async def get_brands_by_categories(
    db: AsyncSession,
    pairs: list[tuple[str, str]],
) -> dict[tuple[str, str], list[str]]:
    """批量查询多个品类的品牌列表。

    一次 SQL 查询全部品牌，按 (category, sub_category) 分组后
    每品类截断 top-20（按商品数量降序）。

    参数:
        db: 异步 SQLAlchemy 会话。
        pairs: (category, sub_category) 元组列表。

    返回值:
        {(category, sub_category): [brand1, brand2, ...]}。
        请求的 pair 即使无品牌也返回空列表。
    """
    if not pairs:
        return {}

    pair_set = set(pairs)
    placeholders = []
    params: dict[str, str] = {}
    for i, (cat, sub) in enumerate(pair_set):
        cp = f"c_{i}"
        sp = f"s_{i}"
        placeholders.append(f"(:{cp}, :{sp})")
        params[cp] = cat
        params[sp] = sub

    sql = text(f"""
        SELECT category, sub_category, brand, COUNT(*) AS cnt
        FROM product
        WHERE (category, sub_category) IN ({", ".join(placeholders)})
          AND brand IS NOT NULL AND brand != ''
          AND is_active = TRUE
        GROUP BY category, sub_category, brand
        ORDER BY category, sub_category, cnt DESC
    """)

    try:
        result = await db.execute(sql, params)
        rows = result.fetchall()
    except Exception as e:
        logger.warning("get_brands_by_categories 查询失败", error=str(e))
        return {}

    grouped: dict[tuple[str, str], list[str]] = {}
    for row in rows:
        key = (row.category, row.sub_category)
        if key not in grouped:
            grouped[key] = []
        if len(grouped[key]) < 20:
            grouped[key].append(row.brand)

    for pair in pair_set:
        if pair not in grouped:
            grouped[pair] = []

    return grouped
