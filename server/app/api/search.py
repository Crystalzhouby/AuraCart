"""
搜索 API 路由

模块: app.api.search

通过两种策略提供产品搜索功能：
1. /api/search         — 直接向量相似度搜索，返回排序结果。
2. /api/search/stream  — Server-Sent Events (SSE) 管道：通过 LLM 进行查询解析，
   多策略检索、结果合并以及 LLM 生成的推理 token。

两个接口均需要嵌入服务和异步数据库会话。
流式接口额外需要一个 LLM 服务实例。
"""
import json
import asyncio
from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text, select
from sse_starlette.sse import EventSourceResponse
import structlog
from app.database import get_db
from app.config import settings
from app.models.product import Product
from app.models.sku import Sku
from app.schemas.product import ProductOut, SkuOut, SearchResponse
from app.services.embedding import EmbeddingService
from app.services.llm import LLMService
from app.services.query_parser import QueryParser
from app.services.retriever import Retriever, SubQuery, SKUHit
from app.rag.merger import Merger
from app.rag.generator import Generator

router = APIRouter(prefix="/api", tags=["search"])


# ---------------------------------------------------------------------------
# 依赖注入工厂函数
# ---------------------------------------------------------------------------

def get_embedding_service() -> EmbeddingService:
    """
    EmbeddingService 的依赖工厂函数。

    根据应用配置创建一个新实例，包括嵌入模型的 base_url、api_key、model 名称
    和 batch_size。

    返回值:
        EmbeddingService: 可直接使用的嵌入服务实例。
    """
    return EmbeddingService(
        base_url=settings.embedding.base_url,
        api_key=settings.embedding.api_key,
        model=settings.embedding.model,
        batch_size=settings.embedding.batch_size,
    )


def get_llm_service() -> LLMService:
    """
    LLMService 的依赖工厂函数。

    根据应用配置创建一个新实例，包括 LLM 的 base_url、api_key、model 名称
    和 temperature。

    返回值:
        LLMService: 可直接使用的 LLM 服务实例。
    """
    return LLMService(
        base_url=settings.llm.base_url,
        api_key=settings.llm.api_key,
        model=settings.llm.model,
        temperature=settings.llm.temperature,
    )


# ---------------------------------------------------------------------------
# 路由
# ---------------------------------------------------------------------------


@router.get("/search", response_model=SearchResponse)
async def search(
    q: str = Query(..., min_length=1, description="搜索查询字符串"),
    top_k: int = Query(10, ge=1, le=50, description="最大返回结果数 (1-50)"),
    db: AsyncSession = Depends(get_db),
    emb: EmbeddingService = Depends(get_embedding_service),
):
    """
    在产品评论上执行向量相似度搜索。

    将用户查询编码为嵌入向量，然后使用 pgvector 余弦相似度 (<=>)
    查找最相关的产品评论。结果按产品去重，并按最高相似度排序。
    每个返回的产品包含所有活跃的 SKU 变体。

    接口: GET /api/search?q=...&top_k=...

    参数:
        q (str):              用户提供的搜索查询字符串。
        top_k (int):          返回的顶层结果最大数量（限定范围 1-50）。
        db (AsyncSession):    通过依赖注入获取的异步 SQLAlchemy 会话。
        emb (EmbeddingService):通过依赖注入获取的嵌入服务。

    返回值:
        SearchResponse: Pydantic 模型，包含原始查询、匹配的 ProductOut 对象列表
                        和结果总数。
    """
    # 步骤 1: 将原始查询字符串转换为向量嵌入。
    query_vector = await emb.embed(q)

    # 步骤 2: 在活跃产品评论上执行余弦相似度搜索。
    # <=> 运算符计算余弦距离；1 - 距离 = 相似度。
    sql = text("""
        SELECT pr.product_id, 1 - (pr.embedding <=> :vec) AS similarity
        FROM product_review pr
        JOIN product p ON p.product_id = pr.product_id AND p.is_active = TRUE
        ORDER BY pr.embedding <=> :vec
        LIMIT :limit
    """)
    result = await db.execute(sql, {"vec": str(query_vector), "limit": top_k})
    rows = result.fetchall()

    # 若无匹配评论，提前返回空结果。
    if not rows:
        return SearchResponse(query=q, products=[], total=0)

    # 步骤 3: 按 product_id 去重，每个产品保留最高分数。
    product_scores: dict[str, float] = {}
    for row in rows:
        pid = row.product_id
        score = row.similarity
        if pid not in product_scores or score > product_scores[pid]:
            product_scores[pid] = score

    # 步骤 4: 按相似度降序排列产品。
    ranked_pids = sorted(product_scores, key=product_scores.get, reverse=True)

    # 步骤 5: 为每个排序后的产品填充完整详情和活跃 SKU。
    products = []
    for pid in ranked_pids:
        prod = await db.execute(
            select(Product)
            .where(Product.product_id == pid, Product.is_active == True)
        )
        prod = prod.scalar_one_or_none()
        if prod is None:
            continue

        skus_result = await db.execute(
            select(Sku)
            .where(Sku.product_id == pid, Sku.is_active == True)
        )
        skus = [
            SkuOut(
                sku_id=s.sku_id,
                properties=s.properties,
                price=float(s.price),
                stock=s.stock,
            )
            for s in skus_result.scalars().all()
        ]

        products.append(ProductOut(
            product_id=prod.product_id,
            title=prod.title,
            brand=prod.brand,
            category=prod.category,
            base_price=float(prod.base_price) if prod.base_price else None,
            image_path=prod.image_path,
            skus=skus,
        ))

    return SearchResponse(query=q, products=products, total=len(products))


@router.get("/search/stream")
async def search_stream(
    request: Request,
    q: str = Query(..., min_length=1, description="搜索查询字符串"),
    db: AsyncSession = Depends(get_db),
    emb: EmbeddingService = Depends(get_embedding_service),
    llm: LLMService = Depends(get_llm_service),
):
    """
    基于 RAG 的 AI 推理 SSE 流式搜索。

    管道各阶段以 SSE 事件的形式发送：
      1. "sub_queries" — LLM 将用户查询解析为结构化的子查询
         （语义、关键词、过滤），支持可选的否定检测。
      2. "products"    — Retriever 对向量库执行每个子查询；
         Merger 合并排序结果，排除被否定的产品集合。
      3. "reasoning"   — Generator 流式输出 AI token，分析产品
         为何匹配用户的搜索意图。
      4. "done"        — 表示流结束。
      5. "error"       — 任何失败时发送，随后发送 "done"。

    接口: GET /api/search/stream?q=...

    参数:
        request (Request):       FastAPI Request 对象，用于连接管理。
        q (str):                 用户提供的搜索查询字符串。
        db (AsyncSession):       通过依赖注入获取的异步 SQLAlchemy 会话。
        emb (EmbeddingService):  通过依赖注入获取的嵌入服务。
        llm (LLMService):        通过依赖注入获取的 LLM 服务。

    返回值:
        EventSourceResponse: 向客户端发送事件的 SSE 流。
    """
    # 使用配置驱动的参数初始化 RAG 管道组件。
    retriever = Retriever(db=db, emb=emb)
    parser = QueryParser(llm=llm)
    merger = Merger(
        rrf_k=60,
        final_limit=settings.search.final_sku_limit,
    )
    generator = Generator(llm=llm)

    async def event_stream():
        """
        内部异步生成器，为流式管道产出 SSE 事件。

        产出:
            dict: 包含 "event" 和 "data" 键的 SSE 事件对象。
        """
        try:
            # ---- 阶段 1: 查询解析 (LLM) ----
            pipeline_log = structlog.get_logger("search_stream")
            pipeline_log.info("阶段1: 查询解析开始", raw_query=q)
            try:
                sub_queries = await asyncio.wait_for(
                    parser.parse(q), timeout=settings.timeout.query_parse
                )
            except asyncio.TimeoutError:
                pipeline_log.info("阶段1: 查询解析超时，回退为语义检索")
                sub_queries = [SubQuery(text=q, strategy="semantic")]

            subs_detail = [
                {
                    "text": s.text, "strategy": s.strategy,
                    "field": s.field,
                    "operator": s.operator, "value": s.value,
                }
                for s in sub_queries
            ]
            pipeline_log.info("阶段1: 查询解析完成", sub_queries=subs_detail)

            # ---- 阶段 2: 多策略检索 ----
            result = await retriever.retrieve(sub_queries, top_k=settings.search.top_k_per_query)
            keyword_hits = result["keyword"]
            semantic_hits = result["semantic"]

            pipeline_log.info("阶段2: 检索完成",
                              keyword_count=len(keyword_hits),
                              semantic_count=len(semantic_hits))

            # ---- 阶段 3: RRF 融合与排序 ----
            ranked_skuhits = merger.merge(
                keyword_ranked=keyword_hits,
                semantic_ranked=semantic_hits,
            )
            skus = await _get_skus(db, ranked_skuhits)

            skus_summary = [
                {"sku_id": s["sku_id"], "product_id": s["product_id"],
                 "title": s["title"], "brand": s["brand"],
                 "price": s["price"]}
                for s in skus
            ]
            pipeline_log.info("阶段3: 合并排序结果",
                              sku_count=len(skus),
                              skus=skus_summary)

            yield {"event": "products", "data": json.dumps(skus, ensure_ascii=False)}

            # ---- 阶段 4: LLM 生成 (token 流式输出) ----
            if skus:
                pipeline_log.info("阶段4: LLM生成开始", sku_count=len(skus))
                agen = generator.generate(skus, q)
                deadline = asyncio.get_event_loop().time() + settings.timeout.generation
                token_count = 0
                try:
                    while True:
                        remaining = deadline - asyncio.get_event_loop().time()
                        if remaining <= 0:
                            break
                        try:
                            token = await asyncio.wait_for(
                                agen.__anext__(), timeout=remaining
                            )
                            yield {"event": "reasoning", "data": token}
                            token_count += 1
                        except StopAsyncIteration:
                            break
                except asyncio.TimeoutError:
                    pipeline_log.info("阶段4: LLM生成超时", token_count=token_count)
                else:
                    pipeline_log.info("阶段4: LLM生成完成", token_count=token_count)
            else:
                pipeline_log.info("阶段4: 无候选商品，跳过生成")

            # ---- 阶段 5: 完成 ----
            pipeline_log.info("阶段5: 流结束")
            yield {"event": "done", "data": "{}"}

        except Exception as e:
            pipeline_log.info("管道异常", error=str(e))
            # 重置可能的失败事务，避免毒化数据库会话
            try:
                await db.rollback()
            except Exception:
                pass
            yield {"event": "error", "data": json.dumps({"message": str(e)})}
            yield {"event": "done", "data": "{}"}

    return EventSourceResponse(event_stream())


# ---------------------------------------------------------------------------
# 辅助函数
# ---------------------------------------------------------------------------


async def _get_skus(
    db: AsyncSession,
    skuhits: list[SKUHit],
) -> list[dict]:
    """
    将 SKUHit 列表填充为扁平 SKU 字典，每个包含所属 product 信息。

    按 sku_id 查询 SKU 表并 JOIN product 表补全产品字段，
    返回的扁平列表中每条记录对应一个匹配的 SKU。

    参数:
        db (AsyncSession): 异步 SQLAlchemy 会话。
        skuhits (list[SKUHit]): 按 RRF 排名排序的 SKU 命中列表。

    返回值:
        list[dict]: 扁平 SKU 字典列表，包含 product 字段
                    （product_id/title/brand/category/sub_category/base_price）
                    和 SKU 字段（sku_id/properties/price/stock）。
    """
    if not skuhits:
        return []

    sku_ids = [h.sku_id for h in skuhits]

    # 批量查询 SKU + JOIN product，一次 SQL 完成
    rows = await db.execute(
        select(
            Product.product_id, Product.title, Product.brand,
            Product.category, Product.sub_category, Product.base_price,
            Sku.sku_id, Sku.properties, Sku.price, Sku.stock,
        )
        .join(Sku, Sku.product_id == Product.product_id)
        .where(
            Sku.sku_id.in_(sku_ids),
            Sku.is_active == True,
            Product.is_active == True,
        )
    )
    # 按 sku_id 索引，用于保持顺序
    row_by_sku: dict[str, dict] = {}
    for row in rows:
        row_by_sku[row.sku_id] = {
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

    # 保持 RRF 排名顺序
    result = []
    for h in skuhits:
        item = row_by_sku.get(h.sku_id)
        if item is not None:
            result.append(item)

    return result
