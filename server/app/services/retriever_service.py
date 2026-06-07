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

本模块与 SubQuery 数据类配合使用。
"""

from dataclasses import dataclass, field
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text
from sqlalchemy.exc import ProgrammingError
import structlog
from app.services.embedding_service import EmbeddingService
from app.config import settings

logger = structlog.get_logger("agent.retrieval")


__all__ = ["Retriever", "SubQuery", "ProductHit", "Filters", "FilterClause", "Merger"]


@dataclass
class ProductHit:
    """单条 product 级检索命中结果。

    属性:
        product_id: 所属产品 ID。
        score: 相关度分数（语义相似度、全文排名或 RRF 得分）。
    """
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
    operator: str | None = None
    value: str | float | None = None
    expanded_values: list[str] | None = None
    category: str | None = None
    sub_category: str | None = None


def _merge_metadata(meta1: dict[str, dict], meta2: dict[str, dict]) -> dict[str, dict]:
    """合并两个 hit_metadata dict，对同 product 的 matched_texts 按 content 去重。

    参数:
        meta1: keyword 或 semantic 路径的 hit_metadata。
        meta2: 另一路径的 hit_metadata。

    返回值:
        合并后的 hit_metadata dict，key 为 product_id。
    """
    merged: dict[str, dict] = {}
    for pid, data in meta1.items():
        merged[pid] = {
            **data,
            "matched_texts": list(data.get("matched_texts", [])),
        }
    for pid, data in meta2.items():
        if pid not in merged:
            merged[pid] = {
                **data,
                "matched_texts": list(data.get("matched_texts", [])),
            }
        else:
            existing_contents = {t["content"] for t in merged[pid].get("matched_texts", [])}
            for text in data.get("matched_texts", []):
                if text.get("content") and text["content"] not in existing_contents:
                    merged[pid]["matched_texts"].append(text)
                    existing_contents.add(text["content"])
    return merged


class Retriever:
    """
    将 SubQuery 对象分发到相应的搜索实现。

    需要数据库会话和 Embedding 服务以支持语义（向量）搜索。
    """

    def __init__(self, db: AsyncSession, emb: EmbeddingService):
        """初始化检索器。"""
        self.db = db
        self.emb = emb

    def _extract_filters(self, subs: list[SubQuery]) -> Filters:
        """从 structured_filter 子查询中提取硬约束条件集合。"""
        field_table = {
            "brand": "product", "category": "product",
            "sub_category": "product", "title": "product",
            "price": "sku", "stock": "sku",
        }

        clauses: list[FilterClause] = []
        counter = 0
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
                placeholders = ", ".join(
                    [f":fv{counter}_{i}" for i in range(len(values))]
                )
                col_ref = f"{col}.{sub.field}"
                if sub.operator == "in":
                    sql = f"{col_ref} IN ({placeholders})"
                else:
                    sql = f"{col_ref} NOT IN ({placeholders})"
                params = {f"fv{counter}_{i}": v for i, v in enumerate(values)}
            elif sub.operator == "lt" and sub.value is not None:
                sql = f"{col}.{sub.field} < :fv{counter}"
                params = {f"fv{counter}": sub.value}
            elif sub.operator == "gt" and sub.value is not None:
                sql = f"{col}.{sub.field} > :fv{counter}"
                params = {f"fv{counter}": sub.value}
            elif sub.operator == "eq" and sub.value is not None:
                sql = f"{col}.{sub.field} = :fv{counter}"
                params = {f"fv{counter}": sub.value}
            elif sub.operator in ("contains", "not_contains") and sub.value:
                pattern = f"%{sub.value}%"
                col_ref = f"{col}.{sub.field}"
                if sub.operator == "contains":
                    sql = f"{col_ref} ILIKE :fv{counter}"
                else:
                    sql = f"{col_ref} NOT ILIKE :fv{counter}"
                params = {f"fv{counter}": pattern}
            else:
                continue

            clauses.append(FilterClause(table=table, sql=sql, params=params))
            counter += 1

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
        select_clause = (
            "SELECT p.product_id, p.title, p.brand, p.category, p.sub_category, p.base_price, "
            "pr.content, pr.source, pr.metadata, "
            f"{score_expr} AS raw_score, "
            "jsonb_build_object('sku_id', s.sku_id, 'properties', s.properties, 'price', s.price, 'stock', s.stock) AS sku_json"
        )
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
        """根据权重配置生成 CASE WHEN 片段和参数绑定。"""
        known_sources = ["marketing", "faq", "user_review", "property"]
        when_parts: list[str] = []
        params: dict = {}

        for src in known_sources:
            w = weights.get(src, 1.0)
            param_name = f"wv_{src}"
            when_parts.append(f"WHEN '{src}' THEN :{param_name}")
            params[param_name] = w

        sql = "CASE pr.source " + " ".join(when_parts) + " ELSE 1.0 END"
        return sql, params

    def _build_grouped_query(self, inner_sql: str) -> str:
        """将子查询包装为 product 级别 GROUP BY 聚合外层查询。

        子查询负责计算原始得分和 ROW_NUMBER，外层负责：
        - 按 product 聚合 SUM 得分
        - jsonb_agg 收集 SKU 列表和 matched_texts
        - 限制每个 product 最多 max_chunks_per_product 行

        参数:
            inner_sql: 已包含 WHERE 条件的基础查询（来自 _build_base_query）。

        返回值:
            完整的外层 GROUP BY SQL。
        """
        max_chunks = settings.search.max_chunks_per_product
        wrapped = (
            "SELECT "
            "sub.product_id, sub.title, sub.brand, sub.category, sub.sub_category, sub.base_price, "
            "SUM(sub.raw_score) AS score, "
            "jsonb_agg(DISTINCT sub.sku_json) AS skus_json, "
            "jsonb_agg(jsonb_build_object('content', sub.content, 'source', sub.source, 'metadata', sub.metadata)) AS matched_texts_json "
            f"FROM (SELECT *, ROW_NUMBER() OVER (PARTITION BY pr.product_id ORDER BY raw_score DESC) AS rn FROM ({inner_sql}) pr) sub "
            f"WHERE sub.rn <= {max_chunks} "
            "GROUP BY sub.product_id, sub.title, sub.brand, sub.category, sub.sub_category, sub.base_price "
            "ORDER BY score DESC LIMIT :limit"
        )
        return wrapped

    async def retrieve(
        self, subs: list[SubQuery], top_k: int = 20
    ) -> dict:
        """对 SubQuery 列表进行分组检索，返回按策略分组的 ProductHit 结果。"""
        filters = self._extract_filters(subs)

        kw_subs = [s for s in subs if s.strategy == "keyword"]
        sem_subs = [s for s in subs if s.strategy == "semantic"]

        import asyncio
        kw_task = self._keyword_search(kw_subs, filters, top_k) if kw_subs else None
        sem_task = self._semantic_search(sem_subs, filters, top_k) if sem_subs else None

        if kw_task and sem_task:
            (kw_results, kw_meta), (sem_results, sem_meta) = await asyncio.gather(kw_task, sem_task)
        elif kw_task:
            kw_results, kw_meta = await kw_task
            sem_results, sem_meta = [], {}
        elif sem_task:
            kw_results, kw_meta = [], {}
            sem_results, sem_meta = await sem_task
        else:
            kw_results, kw_meta = [], {}
            sem_results, sem_meta = [], {}

        merged_meta = _merge_metadata(kw_meta, sem_meta)
        return {"keyword": kw_results, "semantic": sem_results, "hit_metadata": merged_meta}

    async def _semantic_search(
        self, sem_subs: list[SubQuery], filters: Filters, top_k: int
    ) -> tuple[list[ProductHit], dict[str, dict]]:
        """对多条 semantic 子查询执行向量相似度搜索，product 级别聚合。

        使用子查询 + ROW_NUMBER 限制每个 product 最多 max_chunks_per_product 行，
        外层按 product_id GROUP BY 并聚合 SKU 列表和 matched_texts。

        参数：
            sem_subs: semantic 策略的子查询列表。
            filters: 硬约束条件集合。
            top_k: 返回的最大结果数。

        返回值：
            (按综合得分降序排列的 ProductHit 列表, hit_metadata dict)
        """
        if not sem_subs:
            return [], {}

        vectors = []
        for sub in sem_subs:
            vec = await self.emb.embed(sub.text)
            vectors.append(str(vec))

        weight_expr, w_params = self._build_weight_expr(settings.search.source_weights)
        score_parts = [f"(1 - (pr.embedding <=> :vec_{i}))" for i in range(len(vectors))]
        score_expr = f"{weight_expr} * ({' + '.join(score_parts)})"

        inner_sql = self._build_base_query(filters, score_expr)
        sql_str = self._build_grouped_query(inner_sql)

        params = {f"vec_{i}": v for i, v in enumerate(vectors)}
        params["limit"] = top_k
        params.update(filters._all_params())
        params.update(w_params)

        sql = text(sql_str)
        logger.debug("semantic_search SQL", sql=sql_str, params={k: str(v)[:80] for k, v in params.items()})
        result = await self.db.execute(sql, params)
        rows = result.fetchall()

        logger.debug("semantic_search 结果",
                     row_count=len(rows),
                     top_rows=[{"product_id": r.product_id,
                                "score": round(float(r.score), 4),
                                "content": (r.matched_texts_json or [{}])[0].get("content", "")[:100]}
                               for r in rows[:3]])

        hits: list[ProductHit] = []
        hit_metadata: dict[str, dict] = {}
        for r in rows:
            pid = r.product_id
            hits.append(ProductHit(product_id=pid, score=float(r.score)))
            hit_metadata[pid] = {
                "product_id": pid,
                "title": r.title,
                "brand": r.brand,
                "category": r.category,
                "sub_category": r.sub_category,
                "base_price": float(r.base_price) if r.base_price else None,
                "skus": r.skus_json or [],
                "matched_texts": r.matched_texts_json or [],
            }

        return hits, hit_metadata

    async def _keyword_search(
        self, kw_subs: list[SubQuery], filters: Filters, top_k: int
    ) -> tuple[list[ProductHit], dict[str, dict]]:
        """对每个 keyword 子查询执行全文搜索，product 级别聚合。

        使用子查询 + ROW_NUMBER 限制每个 product 最多 max_chunks_per_product 行，
        外层按 product_id GROUP BY。各子查询结果按 product_id 去重（保留最高分）。

        参数：
            kw_subs: keyword 策略的子查询列表。
            filters: 硬约束条件集合。
            top_k: 返回的最大结果数。

        返回值：
            (按 score 降序排列的 ProductHit 列表, hit_metadata dict)
        """
        all_rows: list[dict] = []

        weight_expr, w_params = self._build_weight_expr(settings.search.source_weights)

        for sub in kw_subs:
            rows = []
            for tsv_config in ("chinese", "simple"):
                try:
                    score_expr = f"{weight_expr} * ts_rank(pr.content_tsv, plainto_tsquery(:tsv_config, :kw))"
                    inner_sql = self._build_base_query(filters, score_expr)
                    sql_str = self._build_grouped_query(inner_sql)
                    sql = text(sql_str)
                    kw_params = {"tsv_config": tsv_config, "kw": sub.text.strip(), "limit": top_k, **filters._all_params(), **w_params}
                    logger.debug("keyword_search SQL (tsvector)", config=tsv_config, sql=sql_str, params={k: str(v)[:80] for k, v in kw_params.items()})
                    result = await self.db.execute(sql, kw_params)
                    rows = result.fetchall()
                    if rows:
                        break
                except ProgrammingError:
                    await self.db.rollback()
                    continue

            if not rows:
                score_expr = f"{weight_expr} * 0.3"
                inner_sql = self._build_base_query(filters, score_expr)
                where_extra = (
                    "pr.content ILIKE :pat OR p.brand ILIKE :pat "
                    "OR p.category ILIKE :pat OR p.title ILIKE :pat"
                )
                if "WHERE" in inner_sql:
                    inner_sql = inner_sql + " AND (" + where_extra + ")"
                else:
                    inner_sql = inner_sql + " WHERE " + where_extra

                sql_str = self._build_grouped_query(inner_sql)
                sql = text(sql_str)
                ilike_params = {"pat": f"%{sub.text}%", "limit": top_k, **filters._all_params(), **w_params}
                logger.debug("keyword_search SQL (ILIKE fallback)", sql=sql_str, params={k: str(v)[:80] for k, v in ilike_params.items()})
                result = await self.db.execute(sql, ilike_params)
                rows = result.fetchall()

            if rows:
                logger.debug("keyword_search 结果",
                             sub_text=sub.text[:80],
                             row_count=len(rows),
                             top_rows=[{"product_id": r.product_id, "score": round(float(r.score), 4)}
                                        for r in rows[:3]])

            for r in rows:
                all_rows.append({
                    "product_id": r.product_id,
                    "score": float(r.score),
                    "title": r.title,
                    "brand": r.brand,
                    "category": r.category,
                    "sub_category": r.sub_category,
                    "base_price": float(r.base_price) if r.base_price else None,
                    "skus": r.skus_json or [],
                    "matched_texts": r.matched_texts_json or [],
                })

        # 按 product_id 去重（保留最高分）
        deduped: dict[str, ProductHit] = {}
        hit_metadata: dict[str, dict] = {}
        for row in all_rows:
            pid = row["product_id"]
            if pid not in deduped or row["score"] > deduped[pid].score:
                deduped[pid] = ProductHit(product_id=pid, score=row["score"])
            if pid not in hit_metadata:
                hit_metadata[pid] = {
                    "product_id": pid,
                    "title": row["title"],
                    "brand": row["brand"],
                    "category": row["category"],
                    "sub_category": row["sub_category"],
                    "base_price": row["base_price"],
                    "skus": list(row["skus"]),
                    "matched_texts": [],
                }
            # 追加 matched_texts（按 content 去重）
            existing_contents = {t["content"] for t in hit_metadata[pid]["matched_texts"]}
            for mt in row.get("matched_texts", []):
                if mt.get("content") and mt["content"] not in existing_contents:
                    hit_metadata[pid]["matched_texts"].append(mt)
                    existing_contents.add(mt["content"])

        ranked = sorted(deduped.values(), key=lambda h: h.score, reverse=True)
        return ranked[:top_k], hit_metadata

    async def _structured_filter(self, sub: SubQuery, top_k: int) -> list[dict]:
        """对产品或 SKU 字段执行结构化过滤。"""
        if sub.field in ("brand", "category", "sub_category"):
            table = "product"
        elif sub.field in ("price", "stock"):
            table = "sku"
        else:
            return []

        values = sub.expanded_values if sub.expanded_values else (
            [sub.value] if sub.value is not None else []
        )

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


# ---------------------------------------------------------------------------
# 加权 RRF (Reciprocal Rank Fusion) 合并器
# --------------------------------------------------------------------------


class Merger:
    """将 keyword/semantic 两路排名结果通过加权 RRF 融合。

    属性:
        rrf_k: RRF 平滑参数（默认 60）。
        semantic_weight: 语义检索权重（默认 0.7）。
        keyword_weight: 关键词检索权重（默认 0.3）。
        final_limit: 融合后返回的最大 product 数量（默认 25）。
    """

    def __init__(
        self,
        rrf_k: int = 60,
        semantic_weight: float = 0.7,
        keyword_weight: float = 0.3,
        final_limit: int = 25,
    ):
        self.rrf_k = rrf_k
        self.semantic_weight = semantic_weight
        self.keyword_weight = keyword_weight
        self.final_limit = final_limit

    def merge(
        self,
        keyword_ranked: list[ProductHit],
        semantic_ranked: list[ProductHit],
    ) -> list[ProductHit]:
        """通过加权 RRF 融合两路排名结果。

        参数:
            keyword_ranked: 关键词检索的排名结果（按分数降序）。
            semantic_ranked: 语义检索的排名结果（按分数降序）。

        返回值:
            按加权 RRF 得分降序排列的 ProductHit 列表，最多 final_limit 条。
        """
        rrf_scores: dict[str, float] = {}
        product_map: dict[str, ProductHit] = {}

        for rank, hit in enumerate(keyword_ranked, start=1):
            rrf = self.keyword_weight / (self.rrf_k + rank)
            rrf_scores[hit.product_id] = rrf_scores.get(hit.product_id, 0.0) + rrf
            if hit.product_id not in product_map:
                product_map[hit.product_id] = hit

        for rank, hit in enumerate(semantic_ranked, start=1):
            rrf = self.semantic_weight / (self.rrf_k + rank)
            rrf_scores[hit.product_id] = rrf_scores.get(hit.product_id, 0.0) + rrf
            if hit.product_id not in product_map:
                product_map[hit.product_id] = hit

        ranked_ids = sorted(rrf_scores, key=rrf_scores.get, reverse=True)

        return [
            ProductHit(
                product_id=product_map[pid].product_id,
                score=rrf_scores[pid],
            )
            for pid in ranked_ids[:self.final_limit]
        ]
