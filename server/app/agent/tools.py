"""
Agent 内部数据库查询 Tool 模块。

提供 3 个纯 Python 函数，供 Extraction / Scenario Gen 节点
在执行意图提取前查询数据库元信息和字段取值。所有函数仅依赖
AsyncSession，不依赖 LLM / Embedding 服务。

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
    "product",
    "sku",
    "product_review",
    "product_marketing",
    "product_faq",
    "user_review",
    "category_lookup",
    "conversation",
}

# 每张表允许 DISTINCT 查询的字段（从 information_schema 可查的列都允许，
# 此处仅校验表级白名单，字段名通过参数化查询防注入）
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

# ---------------------------------------------------------------------------
# 中文描述映射（硬编码，维护成本低 — 共 8 张表 / ~60 个字段）
# ---------------------------------------------------------------------------
TABLE_DESCRIPTIONS: dict[str, str] = {
    "product": "产品目录主表，存储每个商品的基本信息（标题、品牌、品类、基础价格等）",
    "sku": "库存单位表，存储产品的具体可购买变体（规格、价格、库存数量），通过 product_id 关联产品",
    "product_review": "商品评价语料表，存储评价文本及其向量嵌入（pgvector），支持语义相似度检索和全文搜索（tsvector）",
    "product_marketing": "商品营销文案表，存储产品的长文营销描述，供 RAG 检索使用",
    "product_faq": "商品问答表，存储产品相关的 FAQ 问答对",
    "user_review": "用户评价表，存储用户提交的商品评价（含昵称、评分、内容）",
    "category_lookup": "品类查找表，存储系统中合法的 (category, sub_category) 值对，供意图提取时校验",
    "conversation": "会话表，持久化多轮对话的记忆数据（JSONB 格式）",
}

COLUMN_DESCRIPTIONS: dict[str, dict[str, str]] = {
    "product": {
        "product_id": "商品唯一业务标识",
        "title": "商品名称/标题",
        "brand": "品牌名称",
        "category": "品类大类（如「面部护肤」「服饰运动」）",
        "sub_category": "品类细类（如「防晒霜」「跑步鞋」）",
        "base_price": "商品基础参考价格",
        "image_path": "商品主图片路径",
        "is_active": "是否上架（TRUE=在售）",
    },
    "sku": {
        "sku_id": "SKU 唯一标识",
        "product_id": "所属商品 ID，关联 product 表",
        "price": "SKU 实际售价",
        "stock": "库存数量",
        "properties": "SKU 规格属性（JSONB，如颜色/尺寸/容量）",
        "is_active": "是否有效",
    },
    "product_review": {
        "product_id": "所属商品 ID",
        "source": "评价来源（marketing/faq/user_review）",
        "content": "评价文本内容",
    },
    "product_marketing": {
        "product_id": "所属商品 ID",
        "description": "营销文案长文本",
    },
    "product_faq": {
        "product_id": "所属商品 ID",
        "question": "常见问题",
        "answer": "问题答案",
    },
    "user_review": {
        "product_id": "所属商品 ID",
        "nickname": "用户昵称",
        "rating": "评分（1-5）",
        "content": "评价内容",
    },
    "category_lookup": {
        "category": "品类大类",
        "sub_category": "品类细类",
    },
    "conversation": {
        "conversation_id": "会话 UUID 主键",
    },
}


async def list_tables(db: AsyncSession) -> list[dict]:
    """查询 ecommerce 数据库下所有业务表，返回表名及中文描述。

    参数:
        db: 异步 SQLAlchemy 会话。

    返回值:
        [{"table_name": "product", "description": "产品目录主表，..."}, ...]
    """
    try:
        sql = text(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema = 'public' AND table_type = 'BASE TABLE' "
            "ORDER BY table_name"
        )
        result = await db.execute(sql)
        rows = result.fetchall()
    except Exception as e:
        logger.warning("list_tables 查询失败", error=str(e))
        return []

    tables = []
    for row in rows:
        name = row.table_name
        if name in _ALLOWED_TABLES:
            tables.append({
                "table_name": name,
                "description": TABLE_DESCRIPTIONS.get(name, ""),
            })
    return tables


async def list_fields(db: AsyncSession, table_name: str) -> list[dict]:
    """查询指定表的所有字段名、类型及中文含义描述。

    参数:
        db: 异步 SQLAlchemy 会话。
        table_name: 表名（必须在白名单内）。

    返回值:
        [{"column_name": "sku_id", "data_type": "character varying",
          "description": "SKU 唯一标识"}, ...]
    """
    if table_name not in _ALLOWED_TABLES:
        logger.warning("list_fields 表名不在白名单", table_name=table_name)
        return []

    col_descs = COLUMN_DESCRIPTIONS.get(table_name, {})

    try:
        sql = text(
            "SELECT column_name, data_type FROM information_schema.columns "
            "WHERE table_schema = 'public' AND table_name = :tbl "
            "ORDER BY ordinal_position"
        )
        result = await db.execute(sql, {"tbl": table_name})
        rows = result.fetchall()
    except Exception as e:
        logger.warning("list_fields 查询失败", table_name=table_name, error=str(e))
        return []

    fields = []
    for row in rows:
        fields.append({
            "column_name": row.column_name,
            "data_type": row.data_type,
            "description": col_descs.get(row.column_name, ""),
        })
    return fields


async def query_field_values(
    db: AsyncSession,
    table: str,
    field: str,
    filters: dict | None = None,
) -> list:
    """查询指定表某个字段的去重取值列表，支持多字段联合过滤。

    例: query_field_values(db, "product", "brand",
          {"category": "面部护肤", "sub_category": "防晒霜"})
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


async def get_brands_by_category(
    db: AsyncSession,
    category: str | None,
    sub_category: str | None,
) -> list[str]:
    """查询指定品类下的品牌列表（单品类便捷封装）。

    参数:
        db: 异步 SQLAlchemy 会话。
        category: 品类大类。为 None 时不加过滤。
        sub_category: 品类细类。为 None 时不加过滤。

    返回值:
        品牌名列表（去重）。全部为 None 时返回全部品牌。
    """
    filters = {}
    if category:
        filters["category"] = category
    if sub_category:
        filters["sub_category"] = sub_category
    return await query_field_values(db, "product", "brand", filters)


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
