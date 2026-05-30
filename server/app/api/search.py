"""
搜索 API 路由

模块: app.api.search

提供 RAG 检索接口 /api/search：
- stream=True（默认） — SSE 流式：查询解析 → 多策略检索 → RRF 融合 → LLM 推荐生成
- stream=False         — JSON 非流式：一次返回完整的管线结果

需要嵌入服务、异步数据库会话和 LLM 服务实例。
"""
import json
import asyncio
from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sse_starlette.sse import EventSourceResponse
import structlog
from app.database import get_db
from app.config import settings
from app.models.product import Product
from app.models.sku import Sku
from app.schemas.product import SearchResponse
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


@router.get("/search")
async def search(
    request: Request,
    q: str = Query(..., min_length=1, description="搜索查询字符串"),
    stream: bool = Query(True, description="是否开启 SSE 流式回答，默认 True"),
    db: AsyncSession = Depends(get_db),
    emb: EmbeddingService = Depends(get_embedding_service),
    llm: LLMService = Depends(get_llm_service),
):
    """
    基于 RAG 的 AI 推理搜索，支持流式 (SSE) 与非流式 (JSON) 两种模式。

    管线各阶段：
      1. LLM 将用户查询解析为结构化的子查询（语义、关键词、过滤）。
      2. Retriever 对向量库并行执行语义检索和关键词检索。
      3. Merger 通过 RRF 融合排序，补充 SKU 与产品详情。
      4. Generator 通过 LLM 生成推荐文案。

    接口: GET /api/search?q=...&stream=true|false

    参数:
        request (Request):       FastAPI Request 对象，用于连接管理。
        q (str):                 用户提供的搜索查询字符串。
        stream (bool):           是否以 SSE 流式返回；默认 True。
        db (AsyncSession):       通过依赖注入获取的异步 SQLAlchemy 会话。
        emb (EmbeddingService):  通过依赖注入获取的嵌入服务。
        llm (LLMService):        通过依赖注入获取的 LLM 服务。

    返回值:
        stream=True  → EventSourceResponse（SSE 事件流）。
        stream=False → SearchResponse（JSON）。
    """
    # 初始化 RAG 管线组件。
    retriever = Retriever(db=db, emb=emb)
    parser = QueryParser(llm=llm)
    merger = Merger(
        rrf_k=60,
        final_limit=settings.search.final_sku_limit,
    )
    generator = Generator(llm=llm)

    async def _run_pipeline(q: str) -> dict:
        """执行 RAG 管线阶段 1-3，流式/非流式共用。"""
        pipeline_log = structlog.get_logger("search")
        result: dict = {}

        # ---- 阶段 1: 查询解析 (LLM) ----
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
                "field": s.field, "operator": s.operator, "value": s.value,
            }
            for s in sub_queries
        ]
        pipeline_log.info("阶段1: 查询解析完成", sub_queries=subs_detail)
        result["sub_queries"] = subs_detail

        # ---- 阶段 2: 多策略检索 ----
        retrieve_result = await retriever.retrieve(
            sub_queries, top_k=settings.search.top_k_per_query
        )
        pipeline_log.info("阶段2: 检索完成",
                          keyword_count=len(retrieve_result["keyword"]),
                          semantic_count=len(retrieve_result["semantic"]))

        # ---- 阶段 3: RRF 融合与排序 ----
        ranked_skuhits = merger.merge(
            keyword_ranked=retrieve_result["keyword"],
            semantic_ranked=retrieve_result["semantic"],
        )
        skus = await _get_skus(db, ranked_skuhits)
        pipeline_log.info("阶段3: 合并排序结果", sku_count=len(skus))
        result["products"] = skus

        return result

    # ---- 非流式模式 ----
    if not stream:
        pipeline_log = structlog.get_logger("search")
        try:
            result = await _run_pipeline(q)
            products = result["products"]
            subs = result["sub_queries"]

            reasoning = None
            if products:
                pipeline_log.info("阶段4: LLM生成开始", sku_count=len(products))
                tokens: list[str] = []
                try:
                    agen = generator.generate(products, q)
                    deadline = asyncio.get_event_loop().time() + settings.timeout.generation
                    while True:
                        remaining = deadline - asyncio.get_event_loop().time()
                        if remaining <= 0:
                            break
                        try:
                            token = await asyncio.wait_for(
                                agen.__anext__(), timeout=remaining
                            )
                            tokens.append(token)
                        except StopAsyncIteration:
                            break
                except asyncio.TimeoutError:
                    pipeline_log.info("阶段4: LLM生成超时", token_count=len(tokens))
                reasoning = "".join(tokens)
                pipeline_log.info("阶段4: LLM生成完成", token_count=len(tokens))
            else:
                pipeline_log.info("阶段4: 无候选商品，跳过生成")

            return SearchResponse(
                query=q, sub_queries=subs, products=products, reasoning=reasoning,
            )
        except Exception as e:
            pipeline_log.info("搜索异常", error=str(e))
            try:
                await db.rollback()
            except Exception:
                pass
            return SearchResponse(
                query=q, sub_queries=[], products=[], reasoning=None,
            )

    # ---- 流式模式 (SSE) ----
    async def event_stream():
        """SSE 事件生成器，逐阶段产出事件。"""
        pipeline_log = structlog.get_logger("search_stream")
        try:
            result = await _run_pipeline(q)
            products = result["products"]
            subs = result["sub_queries"]

            yield {"event": "sub_queries", "data": json.dumps(subs, ensure_ascii=False)}
            yield {"event": "products", "data": json.dumps(products, ensure_ascii=False)}

            if products:
                pipeline_log.info("阶段4: LLM生成开始", sku_count=len(products))
                agen = generator.generate(products, q)
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

            pipeline_log.info("阶段5: 流结束")
            yield {"event": "done", "data": "{}"}

        except Exception as e:
            pipeline_log.info("管道异常", error=str(e))
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
