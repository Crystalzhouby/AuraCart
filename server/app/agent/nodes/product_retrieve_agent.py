"""
Product Retrieval 节点 —— 商品级多路检索与精排管线。

完整 RAG 检索管线（每个品类独立执行，多品类并行）：
1. SubQuery 转换 — intent → keyword/semantic/structured_filter SubQuery 对象
2. SQL 条件转换 — category/sub_category/price/brand → SQL WHERE clause
3. 双路并行检索:
   a. 语义检索: pgvector cosine_distance + SQL 条件 → top-25 (semantic_top_k)
   b. 关键词检索: plainto_tsquery + ts_rank + SQL 条件 → top-25 (keyword_top_k)
   c. 按 product_id 去重: ROW_NUMBER() OVER (PARTITION BY product_id)
4. 加权 RRF 融合 — semantic 0.7 / keyword 0.3, k=60 → top-25 (rrf_top_k), 按 product_id 聚合
5. bge-reranker 精排 — SiliconFlow API (BAAI/bge-reranker-v2-m3) → top-5 (rerank_top_k)
   失败 fallback: RRF 前 5
6. 品类介绍语 — LLM 生成（仅多品类时），逐 token 推送 category_intro_stream
7. 推荐理由 — 每个商品一条 LLM 生成理由，逐条推送 product_reason
8. 商品 SSE — 逐商品发送 products 事件（product_id + category + sub_category）

并行策略: asyncio.Semaphore(max_category_concurrency) 限流，每品类独立 AsyncSession
Review 截断: max_match_texts_per_product 条/商品, max_match_chars_per_product 字/条
"""
import asyncio
import traceback
import structlog

from app.config import settings
from app.services.retriever_service import Retriever, SubQuery, Merger
from app.utils.search_util import truncate_texts
from app.agent.history import get_chat_history_window
from app.agent.prompts.category_introduct_prompt import CATEGORY_INTRODUCT_SYSTEM
from app.agent.prompts.product_recommendation_prompt import PRODUCT_RECOMMENDATION_SYSTEM

logger = structlog.get_logger("agent.retrieval")

SOURCE_LABEL = {"user_review": "[用户评价]", "marketing": "[官方描述]", "faq": "[FAQ]"}


def _intent_to_sub_queries(intent: dict) -> list[SubQuery]:
    """将新格式意图转换为 SubQuery 对象列表，兼容现有 Retriever 接口。"""
    subs = []
    cat = intent.get("category")
    sub = intent.get("sub_category")
    text = intent.get("text", "")
    min_p = intent.get("min_price", 0)
    max_p = intent.get("max_price", 4294967295)
    order_n = intent.get("order_num", 1)
    brands = intent.get("brand")

    if text:
        subs.append(SubQuery(text=text, strategy="keyword",
                             category=cat, sub_category=sub))
    if text:
        subs.append(SubQuery(text=text, strategy="semantic",
                             category=cat, sub_category=sub))

    if cat:
        subs.append(SubQuery(text="", strategy="structured_filter",
                             field="category", operator="eq",
                             value=cat, category=cat, sub_category=sub))
    if sub:
        subs.append(SubQuery(text="", strategy="structured_filter",
                             field="sub_category", operator="eq",
                             value=sub, category=cat, sub_category=sub))
    if min_p and min_p > 0:
        subs.append(SubQuery(text="", strategy="structured_filter",
                             field="price", operator="gt", value=float(min_p),
                             category=cat, sub_category=sub))
    if max_p and max_p < 4294967295:
        subs.append(SubQuery(text="", strategy="structured_filter",
                             field="price", operator="lt", value=float(max_p),
                             category=cat, sub_category=sub))
    if order_n and order_n > 1:
        subs.append(SubQuery(text="", strategy="structured_filter",
                             field="stock", operator="gt", value=float(order_n),
                             category=cat, sub_category=sub))
    if brands and isinstance(brands, list) and len(brands) > 0:
        subs.append(SubQuery(text="", strategy="structured_filter",
                             field="brand", operator="in",
                             expanded_values=brands,
                             category=cat, sub_category=sub))

    return subs


def _build_product_context(products: list[dict]) -> str:
    """按 product 列表构建商品上下文字符串，用于 LLM 生成推荐理由。

    每个 product 字典已包含 skus 列表和 matched_texts，直接遍历构建。
    """
    if not products:
        return ""

    lines = []
    for i, p in enumerate(products, 1):
        lines.append(f"{i}. {p['title']}")
        if p.get("brand"):
            lines.append(f"   品牌: {p['brand']}")
        if p.get("category"):
            lines.append(f"   品类: {p['category']}")
        if p.get("base_price"):
            lines.append(f"   基础价格: ¥{p['base_price']}")

        for sku in p.get("skus", []):
            props_parts = []
            if sku.get("properties"):
                props_parts = [
                    f"{k}: {v}" for k, v in sku["properties"].items()
                ]
            props = " / ".join(props_parts)
            sku_desc = f"   - SKU {sku['sku_id']}: ¥{sku['price']}"
            if props:
                sku_desc += f" ({props})"
            lines.append(sku_desc)

        lines.append("")

    matched_lines: list[str] = []
    for p in products:
        for mt in p.get("matched_texts", []):
            label = SOURCE_LABEL.get(mt.get("source", ""), "[其他]")
            matched_lines.append(f"{label} {mt.get('content', '')}")

    if matched_lines:
        lines.append("【用户评价与描述】")
        lines.extend(matched_lines)
        lines.append("")

    return "\n".join(lines)


async def _category_task(
    intent: dict,
    async_session_factory,
    emb_service,
    reranker=None,
) -> dict:
    """单个品类的检索任务：SQL 条件 → 双路检索 → RRF → reranker。"""
    category = intent.get("category") or ""
    sub_category = intent.get("sub_category") or ""
    text = intent.get("text", "")

    try:
        subs = _intent_to_sub_queries(intent)

        async with async_session_factory() as db:
            logger.info(f"品类 [{category}/{sub_category}] 开始检索", text=text[:80])

            retriever = Retriever(db=db, emb=emb_service)
            retrieve_result = await retriever.retrieve(
                subs, top_k=max(settings.search.semantic_top_k,
                                settings.search.keyword_top_k)
            )
            kw_results = retrieve_result["keyword"]
            sem_results = retrieve_result["semantic"]
            merged_meta = retrieve_result.get("hit_metadata", {})

            merger = Merger(
                rrf_k=settings.search.rrf_k,
                semantic_weight=settings.search.rrf_semantic_weight,
                keyword_weight=settings.search.rrf_keyword_weight,
                final_limit=settings.search.rrf_top_k,
            )
            rrf_ranked = merger.merge(
                keyword_ranked=kw_results,
                semantic_ranked=sem_results,
            )

            logger.info(f"品类 [{category}/{sub_category}] RRF 融合完成",
                        product_count=len(rrf_ranked))

            if not rrf_ranked:
                return {
                    "category": category, "sub_category": sub_category,
                    "products": [], "product_ids": [],
                    "error": None,
                }

            if reranker and len(rrf_ranked) > settings.search.rerank_top_k:
                documents = []
                for hit in rrf_ranked:
                    meta = merged_meta.get(hit.product_id, {})
                    title = meta.get("title", "")
                    matched = meta.get("matched_texts", [])
                    first_text = matched[0].get("content", "") if matched else ""
                    documents.append(f"title: {title} | {first_text}"[:500])

                rerank_results = await reranker.rerank(
                    query=text, documents=documents,
                    top_n=settings.search.rerank_top_k,
                )

                if rerank_results:
                    final_hits = []
                    for rr in rerank_results:
                        idx = rr.get("index", 0)
                        if idx < len(rrf_ranked):
                            hit = rrf_ranked[idx]
                            hit.score = rr.get("relevance_score", hit.score)
                            final_hits.append(hit)
                    rrf_ranked = final_hits
                    logger.info(f"品类 [{category}/{sub_category}] reranker 完成",
                                result_count=len(rrf_ranked))
                else:
                    rrf_ranked = rrf_ranked[:settings.search.rerank_top_k]
            else:
                rrf_ranked = rrf_ranked[:settings.search.rerank_top_k]

            products = []
            for hit in rrf_ranked:
                data = merged_meta.get(hit.product_id)
                if data is None:
                    continue
                raw_texts = data.get("matched_texts", [])
                truncated = truncate_texts(
                    raw_texts,
                    settings.search.max_match_texts_per_product,
                    settings.search.max_match_chars_per_product,
                )
                data["matched_texts"] = truncated
                products.append(data)

            logger.info(f"品类 [{category}/{sub_category}] 检索完成",
                        final_product_count=len(products))

            return {
                "category": category,
                "sub_category": sub_category,
                "products": products,
                "product_ids": [
                    {"product_id": p["product_id"],
                     "category": category, "sub_category": sub_category}
                    for p in products
                ],
                "error": None,
            }

    except Exception as e:
        logger.error(f"品类检索失败: {category}/{sub_category}",
                     error=str(e), traceback=traceback.format_exc())
        return {
            "category": category, "sub_category": sub_category,
            "products": [], "product_ids": [],
            "error": str(e),
        }


async def _generate_category_intro(
    category: str,
    sub_category: str,
    index: int,
    total: int,
    scenario_description: str,
    llm,
) -> str:
    """生成品类介绍过渡语。"""
    if not llm:
        return ""
    try:
        prompt = CATEGORY_INTRODUCT_SYSTEM.format(
            category=category or "",
            sub_category=sub_category or "",
            index=index,
            total=total,
            scenario_description=scenario_description or "无",
        )
        messages = [
            {"role": "system", "content": prompt},
            {"role": "user", "content": "请生成品类介绍"},
        ]
        text = await llm.chat(messages, temperature=0.3)
        return text.strip() if text else ""
    except Exception as e:
        logger.warning("品类介绍生成失败", category=category, error=str(e))
        return ""


async def _generate_product_reason(
    product: dict,
    user_intent: str,
    category_products: list[dict],
    llm,
    db_session_factory=None,
    conversation_id: str = "",
) -> str:
    """为单个商品生成推荐理由。2b 阶段注入品类相关的对话历史。"""
    if not llm:
        return ""
    try:
        user_history = "无"
        if db_session_factory and conversation_id:
            try:
                cat = product.get("category", "")
                sub = product.get("sub_category", "")
                filter_cats = [f"{cat}/{sub}"] if cat and sub else None
                async with db_session_factory() as session:
                    user_history = await get_chat_history_window(
                        session, conversation_id,
                        settings.search.memory_recent_rounds,
                        category_filter=filter_cats,
                    )
            except Exception as e:
                logger.warning("推荐理由历史加载失败", error=str(e))

        product_detail = _build_product_context([product])
        category_overview = (
            _build_product_context(category_products)
            if len(category_products) > 1
            else product_detail
        )
        prompt = PRODUCT_RECOMMENDATION_SYSTEM.format(
            user_intent=user_intent or "推荐合适的商品",
            total_in_category=len(category_products),
            category_overview=category_overview,
            product_detail=product_detail,
            max_chars=settings.search.reasoning_max_chars,
            user_history=user_history,
        )
        messages = [
            {"role": "system", "content": prompt},
            {"role": "user", "content": "请推荐这件商品"},
        ]
        text = await llm.chat(messages, temperature=0.3)
        return text.strip() if text else ""
    except Exception as e:
        logger.warning("商品推荐理由生成失败", product=product.get("product_id"), error=str(e))
        return ""


async def product_retrieve_node(
    state: dict,
    llm=None,
    emb_service=None,
    async_session_factory=None,
    reranker=None,
    _sse_queue=None,
) -> dict:
    """Product Retrieval 节点函数 —— 商品级多路检索与精排管线。

    从 AgentState.requirements 读取按品类分组的意图列表，各品类并行执行完整 RAG 管线：

    管线步骤（每品类）:
    1. SubQuery 转换: intent → keyword + semantic + structured_filter SubQuery
    2. SQL 条件转换: category/sub_category/price/stock/brand → FilterClause
    3. 双路并行检索: 语义 (pgvector cosine) + 关键词 (ts_query) → 各 top-25
    4. 加权 RRF 融合: semantic 0.7 / keyword 0.3, k=60 → top-25, 按 product_id 聚合
    5. bge-reranker 精排: SiliconFlow API → top-5; 失败 fallback 到 RRF top-5
    6. Review 截断: 每商品 max_match_texts_per_product 条 × max_match_chars_per_product 字
    7. 品类介绍语: LLM 生成（仅多品类）→ 逐 token 推送 category_intro_stream
    8. 推荐理由: 每商品一条 LLM 理由 → product_reason SSE
    9. 商品 SSE: 逐商品推送 products 事件 (product_id + category + sub_category)

    并行策略: asyncio.Semaphore(max_category_concurrency) 限流，每品类独立 AsyncSession

    参数:
        state: AgentState 字典，读取 requirements / conversation_id / _sse_queue
        llm: LLMService，用于推荐理由和品类介绍
        emb_service: EmbeddingService，用于语义检索
        async_session_factory: async_session 工厂，每品类独立 session
        reranker: 可选 RerankerService，用于精排
        _sse_queue: 可选，覆盖 state 中的 asyncio.Queue

    返回值:
        {"retrieval_results": [商品详情], "failed_categories": [失败的 sub_category]}
    """
    user_query = state.get("user_query", "")
    requirements = state.get("requirements", [])
    scenario_description = state.get("scenario_description", "")
    conversation_id = state.get("conversation_id", "")
    queue = _sse_queue or state.get("_sse_queue")
    stream = state.get("stream", True)

    if not requirements:
        return {"retrieval_results": [], "failed_categories": []}

    logger.info("Retrieval 节点开始", user_query=user_query,
                requirement_count=len(requirements))

    # 1. 并行检索
    semaphore = asyncio.Semaphore(settings.search.max_category_concurrency)

    async def _bounded_task(intent):
        async with semaphore:
            return await _category_task(
                intent, async_session_factory, emb_service, reranker
            )

    tasks = [_bounded_task(req) for req in requirements]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    safe_results = []
    for i, r in enumerate(results):
        if isinstance(r, Exception):
            req = requirements[i] if i < len(requirements) else {}
            safe_results.append({
                "category": req.get("category", ""),
                "sub_category": req.get("sub_category", ""),
                "products": [], "product_ids": [],
                "error": str(r),
            })
        else:
            safe_results.append(r)

    # 2. SSE 逐品类 → 逐商品发送
    retrieval_results = []
    failed_categories = []
    total_valid = len([r for r in safe_results if not r.get("error")])

    for idx, r in enumerate(safe_results):
        if r.get("error"):
            failed_categories.append({
                "category": r.get("category", ""),
                "sub_category": r.get("sub_category", ""),
                "error": r["error"],
            })
            continue

        products = r.get("products", [])
        retrieval_results.extend(products)
        category = r.get("category", "")
        sub_category = r.get("sub_category", "")

        # 2a. 品类介绍语
        if total_valid > 1:
            if stream and queue:
                # 流式路径: 逐 token 推送 category_intro_stream
                try:
                    prompt = CATEGORY_INTRODUCT_SYSTEM.format(
                        category=category or "",
                        sub_category=sub_category or "",
                        index=idx + 1,
                        total=total_valid,
                        scenario_description=scenario_description or "无",
                    )
                    messages = [
                        {"role": "system", "content": prompt},
                        {"role": "user", "content": "请生成品类介绍"},
                    ]
                    await queue.put({"event": "category_intro_stream", "data": {"type": "start"}})
                    async for token in llm.chat_stream(messages, temperature=0.3):
                        await queue.put({"event": "category_intro_stream", "data": {"type": "delta", "text": token}})
                    await queue.put({"event": "category_intro_stream", "data": {"type": "end"}})
                except Exception as e:
                    logger.warning("流式品类介绍生成失败", category=category, error=str(e))
            else:
                # 非流式路径
                intro = await _generate_category_intro(
                    category, sub_category, idx + 1, total_valid,
                    scenario_description, llm,
                )
                if queue and intro:
                    await queue.put({"event": "category_intro", "data": intro})

        # 2b. 逐商品推荐
        if products:
            reason_tasks = [
                _generate_product_reason(p, user_query, products, llm,
                                         db_session_factory=async_session_factory,
                                         conversation_id=conversation_id)
                for p in products
            ]
            reasons = await asyncio.gather(*reason_tasks, return_exceptions=True)

            for i, p in enumerate(products):
                if queue:
                    await queue.put({
                        "event": "products",
                        "data": {
                            "product_id": p["product_id"],
                            "category": p.get("category") or category,
                            "sub_category": p.get("sub_category") or sub_category,
                        },
                    })
                    reason = reasons[i] if (
                        i < len(reasons)
                        and isinstance(reasons[i], str)
                    ) else ""
                    if reason:
                        await queue.put({"event": "product_reason", "data": reason})

    logger.info("Retrieval 节点完成",
                total_products=len(retrieval_results),
                failed_categories=len(failed_categories))

    return {
        "retrieval_results": retrieval_results,
        "failed_categories": [f["sub_category"] for f in failed_categories],
    }
