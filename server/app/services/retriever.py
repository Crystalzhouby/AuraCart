# app/services/retriever.py
"""
检索器模块
==========
将结构化的 SubQuery 对象分发到对应的搜索策略。

核心功能：
- 语义搜索：通过 pgvector Embedding 进行余弦相似度检索
- 关键词搜索：使用中文分词进行 PostgreSQL 全文搜索
- 结构化过滤：对产品和 SKU 字段进行精确/模糊匹配
- 回退机制：全文搜索无结果时进行基本的 ILIKE 匹配

本模块与 QueryParser 生成的 SubQuery 数据类配合使用。
"""

from dataclasses import dataclass, field
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text
from sqlalchemy.exc import ProgrammingError
import structlog
from app.services.embedding import EmbeddingService
from app.config import settings

logger = structlog.get_logger("agent.retrieval")


__all__ = ["Retriever", "SubQuery", "SKUHit", "Filters", "FilterClause"]


@dataclass
class SKUHit:
    """单条 SKU 级检索命中结果。

    属性:
        sku_id: SKU 唯一标识符。
        product_id: 所属产品 ID。
        score: 相关度分数（语义相似度、全文排名或 RRF 得分）。
    """
    sku_id: str
    product_id: str
    score: float


@dataclass
class FilterClause:
    """单条硬约束 SQL 片段，由 structured_filter SubQuery 生成。

    属性:
        table: 目标表名 ("product" 或 "sku")。
        sql: 参数化 SQL WHERE 片段（如 "p.brand NOT IN (:v0, :v1)"）。
        params: 参数名到值的映射字典。
    """
    table: str
    sql: str
    params: dict


@dataclass
class Filters:
    """从 structured_filter 子查询提取的硬约束集合。

    属性:
        conditions: FilterClause 列表，每条对应一个 WHERE 条件。
    """
    conditions: list[FilterClause]

    def _all_params(self) -> dict:
        """合并所有 FilterClause 的参数为单个字典。

        返回值:
            dict: 所有条件参数的合并映射。
        """
        merged: dict = {}
        for fc in self.conditions:
            merged.update(fc.params)
        return merged


@dataclass
class SubQuery:
    """
    表示从用户输入中解析出的单个子查询。

    属性：
        text (str)：要搜索的子查询文本。
        strategy (str)：应用的搜索策略，可选值：
            "semantic" - 向量相似度搜索，
            "keyword" - 全文搜索，
            "structured_filter" - 精确/模糊字段匹配。
        field (str | None)：structured_filter 策略的目标字段
                           （如 "brand"、"category"、"price"）。
        operator (str | None)：structured_filter 的比较操作符。
            可选值："eq"、"lt"、"gt"、"in"、"not_in"、"contains"、"not_contains"。
        value (str | float | None)：单个比较值。
        expanded_values (list[str] | None)：经 LLM 值扩展后，
            用于 "in"/"not_in" 操作符的多个值。
        category (str | None)：品类大类（如"面部护肤"），默认 None。
        sub_category (str | None)：品类细类（如"防晒霜"），默认 None。
    """
    text: str
    strategy: str  # "semantic" | "keyword" | "structured_filter"
    field: str | None = None
    operator: str | None = None  # "eq" | "lt" | "gt" | "in" | "not_in" | "contains" | "not_contains"
    value: str | float | None = None
    expanded_values: list[str] | None = None
    category: str | None = None       # 品类大类（如"面部护肤"）
    sub_category: str | None = None   # 品类细类（如"防晒霜"）


class Retriever:
    """
    将 SubQuery 对象分发到相应的搜索实现。

    需要数据库会话和 Embedding 服务以支持语义（向量）搜索。
    """

    def __init__(self, db: AsyncSession, emb: EmbeddingService):
        """
        初始化检索器。

        参数：
            db (AsyncSession)：SQLAlchemy 异步数据库会话。
            emb (EmbeddingService)：用于在语义搜索时即时生成
                                   查询 Embedding 的服务。
        """
        self.db = db
        self.emb = emb

    def _extract_filters(self, subs: list[SubQuery]) -> Filters:
        """从 structured_filter 子查询中提取硬约束条件集合。

        遍历所有 strategy="structured_filter" 的 SubQuery，
        为每条生成一个 FilterClause。非 filter 子查询被忽略。

        参数:
            subs: 所有子查询列表。

        返回值:
            Filters: 包含所有结构化过滤条件的集合。
        """
        field_table = {
            "brand": "product", "category": "product",
            "sub_category": "product", "title": "product",
            "price": "sku", "stock": "sku",
        }

        clauses: list[FilterClause] = []
        for sub in subs:
            if sub.strategy != "structured_filter":
                continue

            table = field_table.get(sub.field or "")
            if table is None:
                continue

            values = sub.expanded_values if sub.expanded_values else (
                [sub.value] if sub.value is not None else []
            )
            col = "p" if table == "product" else "s"

            if sub.operator in ("in", "not_in") and values:
                placeholders = ", ".join([f":v{i}" for i in range(len(values))])
                col_ref = f"{col}.{sub.field}"
                if sub.operator == "in":
                    sql = f"{col_ref} IN ({placeholders})"
                else:
                    sql = f"{col_ref} NOT IN ({placeholders})"
                params = {f"v{i}": v for i, v in enumerate(values)}
            elif sub.operator == "lt" and sub.value is not None:
                sql = f"{col}.{sub.field} < :val"
                params = {"val": sub.value}
            elif sub.operator == "gt" and sub.value is not None:
                sql = f"{col}.{sub.field} > :val"
                params = {"val": sub.value}
            elif sub.operator == "eq" and sub.value is not None:
                sql = f"{col}.{sub.field} = :val"
                params = {"val": sub.value}
            elif sub.operator in ("contains", "not_contains") and sub.value:
                pattern = f"%{sub.value}%"
                col_ref = f"{col}.{sub.field}"
                if sub.operator == "contains":
                    sql = f"{col_ref} ILIKE :pat"
                else:
                    sql = f"{col_ref} NOT ILIKE :pat"
                params = {"pat": pattern}
            else:
                continue

            clauses.append(FilterClause(table=table, sql=sql, params=params))

        return Filters(conditions=clauses)

    def _build_base_query(self, filters: Filters, score_expr: str) -> str:
        """构建三表 JOIN 骨架 SQL，注入 score_expr 和硬约束条件。

        三表结构：product_review pr → product p → sku s
        product_review 与 sku 通过 product 间接关联。

        参数:
            filters: 硬约束条件集合。
            score_expr: 得分表达式（注入到 SELECT 子句）。

        返回值:
            完整的参数化 SQL 查询字符串。
        """
        select_clause = f"SELECT s.sku_id, p.product_id, {score_expr}"
        from_clause = (
            "FROM product_review pr "
            "JOIN product p ON p.product_id = pr.product_id AND p.is_active = TRUE "
            "JOIN sku s ON s.product_id = p.product_id AND s.is_active = TRUE"
        )

        if filters.conditions:
            where_parts = [fc.sql for fc in filters.conditions]
            where_clause = "WHERE " + " AND ".join(where_parts)
            return f"{select_clause} {from_clause} {where_clause}"
        else:
            return f"{select_clause} {from_clause}"

    @staticmethod
    def _build_weight_expr(weights: dict[str, float]) -> tuple[str, dict]:
        """根据权重配置生成 CASE WHEN 片段和参数绑定。

        对每个已知 source 生成 WHEN 分支，权重值从 weights dict 读取，
        未配置的 source 默认 1.0。ELSE 1.0 兜底所有未知 source。

        参数:
            weights: source → weight 映射，如 {"marketing": 1.0, "faq": 1.0, "user_review": 0.7}。

        返回值:
            (sql_fragment, params)
            sql_fragment:  "CASE pr.source WHEN 'marketing' THEN :wv_mkt ... ELSE 1.0 END"
            params:        参数绑定字典。
        """
        known_sources = ["marketing", "faq", "user_review"]
        when_parts: list[str] = []
        params: dict = {}

        for src in known_sources:
            w = weights.get(src, 1.0)
            param_name = f"wv_{src}"
            when_parts.append(f"WHEN '{src}' THEN :{param_name}")
            params[param_name] = w

        sql = "CASE pr.source " + " ".join(when_parts) + " ELSE 1.0 END"
        return sql, params

    async def retrieve(
        self, subs: list[SubQuery], top_k: int = 20
    ) -> dict[str, list[SKUHit]]:
        """对 SubQuery 列表进行分组检索，返回按策略分组的 SKUHit 结果。

        内部：
        1. 提取 structured_filter 子查询为硬约束 Filters。
        2. 分组 keyword 和 semantic 子查询。
        3. 并行执行 keyword 和 semantic 检索（asyncio.gather）。

        参数：
            subs: 所有子查询列表。
            top_k: 每条路径返回的最大结果数。

        返回值:
            dict: {"keyword": list[SKUHit], "semantic": list[SKUHit]}
        """
        filters = self._extract_filters(subs)

        kw_subs = [s for s in subs if s.strategy == "keyword"]
        sem_subs = [s for s in subs if s.strategy == "semantic"]

        # 并行执行两路检索
        import asyncio
        kw_task = self._keyword_search(kw_subs, filters, top_k) if kw_subs else None
        sem_task = self._semantic_search(sem_subs, filters, top_k) if sem_subs else None

        if kw_task and sem_task:
            kw_results, sem_results = await asyncio.gather(kw_task, sem_task)
        elif kw_task:
            kw_results = await kw_task
            sem_results = []
        elif sem_task:
            kw_results = []
            sem_results = await sem_task
        else:
            kw_results = []
            sem_results = []

        return {"keyword": kw_results, "semantic": sem_results}

    async def _semantic_search(
        self, sem_subs: list[SubQuery], filters: Filters, top_k: int
    ) -> list[SKUHit]:
        """对多条 semantic 子查询执行向量相似度搜索，独立打分后加和为综合得分。

        每条 semantic 子查询独立计算与 product_review.embedding 的余弦相似度
        （1 - <=>），综合得分为各子查询得分的 SUM。结果按 sku_id 分组。

        参数：
            sem_subs: semantic 策略的子查询列表。
            filters: 硬约束条件集合。
            top_k: 返回的最大结果数。

        返回值：
            按综合得分降序排列的 SKUHit 列表。
        """
        if not sem_subs:
            return []

        # 为每条 semantic 子查询生成 embedding
        vectors = []
        for sub in sem_subs:
            vec = await self.emb.embed(sub.text)
            vectors.append(str(vec))

        # 构建 source 加权 + sum 得分表达式
        weight_expr, w_params = self._build_weight_expr(settings.search.source_weights)
        score_parts = [f"(1 - (pr.embedding <=> :vec_{i}))" for i in range(len(vectors))]
        score_expr = " + ".join(score_parts)
        score_expr_full = f"SUM({weight_expr} * ({score_expr})) AS score"

        sql_str = self._build_base_query(filters, score_expr_full)

        # 添加 GROUP BY 以按 sku 聚合 sum 得分
        if "WHERE" in sql_str:
            parts = sql_str.split("WHERE", 1)
            sql_str = f"{parts[0]}WHERE {parts[1]} GROUP BY s.sku_id, p.product_id"
        else:
            sql_str = f"{sql_str} GROUP BY s.sku_id, p.product_id"

        sql_str += " ORDER BY score DESC LIMIT :limit"

        params = {f"vec_{i}": v for i, v in enumerate(vectors)}
        params["limit"] = top_k
        params.update(filters._all_params())
        params.update(w_params)  # 合并 source 权重参数

        sql = text(sql_str)
        logger.info("semantic_search SQL", sql=sql_str, params={k: str(v)[:80] for k, v in params.items()})
        result = await self.db.execute(sql, params)
        rows = result.fetchall()

        return [
                SKUHit(sku_id=r.sku_id, product_id=r.product_id, score=float(r.score))
            for r in rows
        ]

    async def _keyword_search(
        self, kw_subs: list[SubQuery], filters: Filters, top_k: int
    ) -> list[SKUHit]:
        """对每个 keyword 子查询执行全文搜索，合并结果并去重。

        每个 keyword SubQuery 尝试 tsvector 全文搜索（优先 chinese 配置，
        其次 simple），无结果时降级为 ILIKE。所有 keyword 子查询的结果
        按 sku_id 去重（保留最高分）。

        参数：
            kw_subs: keyword 策略的子查询列表。
            filters: 硬约束条件集合。
            top_k: 返回的最大结果数。

        返回值：
            按 score 降序排列的 SKUHit 列表。
        """
        all_rows: list[dict] = []

        # 构建 source 权重表达式（semantic 和 keyword 共用）
        weight_expr, w_params = self._build_weight_expr(settings.search.source_weights)

        for sub in kw_subs:
            rows = []
            # 尝试 tsvector 全文搜索
            for tsv_config in ("chinese", "simple"):
                try:
                    base_sql = self._build_base_query(
                        filters,
                        f"{weight_expr} * ts_rank(pr.content_tsv, plainto_tsquery(:tsv_config, :kw)) AS score",
                    )
                    where_extra = "pr.content_tsv @@ plainto_tsquery(:tsv_config, :kw)"
                    if "WHERE" in base_sql:
                        sql_with_where = base_sql + " AND " + where_extra
                    else:
                        sql_with_where = base_sql + " WHERE " + where_extra

                    sql = text(
                        sql_with_where
                        + " ORDER BY score DESC LIMIT :limit"
                    )
                    kw_params = {"tsv_config": tsv_config, "kw": sub.text.strip(), "limit": top_k, **filters._all_params(), **w_params}
                    logger.info("keyword_search SQL (tsvector)", config=tsv_config, sql=sql_with_where, params={k: str(v)[:80] for k, v in kw_params.items()})
                    result = await self.db.execute(sql, kw_params)
                    rows = result.fetchall()
                    if rows:
                        break
                except ProgrammingError:
                    await self.db.rollback()
                    continue

            # 降级：ILIKE（同时搜索产品字段和评价内容）
            if not rows:
                base_sql = self._build_base_query(
                    filters, f"{weight_expr} * 0.3 AS score"
                )
                where_extra = (
                    "pr.content ILIKE :pat OR p.brand ILIKE :pat "
                    "OR p.category ILIKE :pat OR p.title ILIKE :pat"
                )
                if "WHERE" in base_sql:
                    sql_str = base_sql + " AND (" + where_extra + ") LIMIT :limit"
                else:
                    sql_str = base_sql + " WHERE " + where_extra + " LIMIT :limit"

                sql = text(sql_str)
                ilike_params = {"pat": f"%{sub.text}%", "limit": top_k, **filters._all_params(), **w_params}
                logger.info("keyword_search SQL (ILIKE fallback)", sql=sql_str, params={k: str(v)[:80] for k, v in ilike_params.items()})
                result = await self.db.execute(sql, ilike_params)
                rows = result.fetchall()

            for r in rows:
                all_rows.append({
                    "sku_id": r.sku_id,
                    "product_id": r.product_id,
                    "score": float(r.score),
                })

        # 按 sku_id 去重，保留最高分
        deduped: dict[str, SKUHit] = {}
        for row in all_rows:
            sid = row["sku_id"]
            if sid not in deduped or row["score"] > deduped[sid].score:
                deduped[sid] = SKUHit(
                    sku_id=sid,
                    product_id=row["product_id"],
                    score=row["score"],
                )

        ranked = sorted(deduped.values(), key=lambda h: h.score, reverse=True)
        return ranked[:top_k]

    async def _structured_filter(self, sub: SubQuery, top_k: int) -> list[dict]:
        """
        对产品或 SKU 字段执行结构化（精确/模糊）过滤。

        支持的操作符：in、not_in、lt、gt、contains、not_contains。
        对 brand/category/sub_category 字段路由到 'product' 表，
        对 price/stock 字段路由到 'sku' 表。仅返回活跃产品。

        参数：
            sub (SubQuery)：包含字段、操作符、值和可选的
                            expanded_values 的子查询。
            top_k (int)：最大结果数。

        返回值：
            list[dict]：包含 product_id、source（"basic_info" 或 "sku"）
                        和固定分数 1.0 的结果。
        """
        # 根据字段名确定目标表
        if sub.field in ("brand", "category", "sub_category"):
            table = "product"
        elif sub.field in ("price", "stock"):
            table = "sku"
        else:
            return []

        # 解析值：优先使用 expanded_values，其次使用单个值
        values = sub.expanded_values if sub.expanded_values else (
            [sub.value] if sub.value is not None else []
        )

        # 根据操作符构建 WHERE 子句和参数
        if sub.operator in ("in", "not_in") and values:
            placeholders = ", ".join([f":v{i}" for i in range(len(values))])
            col = f"p.{sub.field}" if table == "product" else f"s.{sub.field}"
            if sub.operator == "in":
                where_clause = f"{col} IN ({placeholders})"
            else:
                where_clause = f"{col} NOT IN ({placeholders})"
            params = {f"v{i}": v for i, v in enumerate(values)}
        elif sub.operator == "lt" and sub.value is not None:
            col = f"p.{sub.field}" if table == "product" else f"s.{sub.field}"
            where_clause = f"{col} < :val"
            params = {"val": sub.value}
        elif sub.operator == "gt" and sub.value is not None:
            col = f"p.{sub.field}" if table == "product" else f"s.{sub.field}"
            where_clause = f"{col} > :val"
            params = {"val": sub.value}
        elif sub.operator in ("contains", "not_contains") and sub.value:
            col = f"p.{sub.field}" if table == "product" else f"s.{sub.field}"
            pattern = f"%{sub.value}%"
            if sub.operator == "contains":
                where_clause = f"{col} ILIKE :pat"
            else:
                where_clause = f"{col} NOT ILIKE :pat"
            params = {"pat": pattern}
        else:
            return []

        # 按表构建并执行相应的查询
        if table == "product":
            sql = text(f"""
                SELECT DISTINCT p.product_id, 'basic_info' AS source, 1.0 AS score
                FROM product p
                WHERE p.is_active = TRUE AND {where_clause}
                LIMIT :limit
            """)
        else:
            sql = text(f"""
                SELECT DISTINCT s.product_id, 'sku' AS source, 1.0 AS score
                FROM sku s
                JOIN product p ON p.product_id = s.product_id AND p.is_active = TRUE
                WHERE {where_clause}
                LIMIT :limit
            """)

        params["limit"] = top_k
        result = await self.db.execute(sql, params)
        return [
            {"product_id": r.product_id, "source": r.source, "score": float(r.score)}
            for r in result.fetchall()
        ]
