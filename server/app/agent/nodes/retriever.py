"""
Product Retrieval 节点。

流水线：
1. 欢迎语（由 router 节点生成，从 state 读取）
2. 按品类分组检索（requirements 已按品类分组）
3. SQL 条件转换 + 双路检索（语义 top-25 + 关键词 top-25）并行
4. 加权 RRF 融合（semantic 0.7 / keyword 0.3）→ top-25
5. bge-reranker 精排（top-5）+ fallback
6. 品类介绍语（LLM，仅多品类）→ 逐商品 SSE 发送（products 单对象 + product_reason 推荐理由）
7. Memory 更新（原始查询按品类追加到 session_memory）
"""
import asyncio
import traceback
from datetime import datetime
import structlog

from app.config import settings
from app.services.retriever_service import Retriever, SubQuery, Merger
from app.services.sku_utils_service import _truncate_texts
from app.agent.memory import append_query
from app.agent.prompts.show_prompt import (
    CATEGORY_INTRO_SYSTEM,
    PRODUCT_REASON_SYSTEM,
)

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
                truncated = _truncate_texts(
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
        prompt = CATEGORY_INTRO_SYSTEM.format(
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
    session_memory: list[dict] | None = None,
) -> str:
    """为单个商品生成推荐理由。"""
    if not llm:
        return ""
    try:
        user_history = ""
        if session_memory:
            from app.agent.memory import get_queries_by_category
            cat = product.get("category", "")
            sub = product.get("sub_category", "")
            queries = get_queries_by_category(session_memory, cat, sub)
            if queries:
                user_history = (
                    "用户此前对该品类的关注：\n"
                    + "\n".join(f"- {q['query']}" for q in queries)
                )

        product_detail = _build_product_context([product])
        category_overview = (
            _build_product_context(category_products)
            if len(category_products) > 1
            else product_detail
        )
        prompt = PRODUCT_REASON_SYSTEM.format(
            user_intent=user_intent or "推荐合适的商品",
            total_in_category=len(category_products),
            category_overview=category_overview,
            product_detail=product_detail,
            max_chars=settings.search.reasoning_max_chars,
            user_history=user_history or "无",
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


async def retrieval_node(
    state: dict,
    llm=None,
    emb_service=None,
    async_session_factory=None,
    reranker=None,
    _sse_queue=None,
) -> dict:
    """Product Retrieval 节点函数。

    流水线：欢迎语 → 并行检索 → 品类介绍(多品类) → 逐商品推荐 → Memory 更新。
    """
    user_query = state.get("user_query", "")
    requirements = state.get("requirements", [])
    scenario_description = state.get("scenario_description", "")
    queue = _sse_queue or state.get("_sse_queue")
    stream = state.get("stream", True)

    if not requirements:
        return {"retrieval_results": [], "failed_categories": [],
                "session_memory": state.get("session_memory", [])}

    logger.info("Retrieval 节点开始", user_query=user_query,
                requirement_count=len(requirements))

    # 1. 欢迎语（仅非流式模式: Router 已写入 state，此处读取并发送）
    if not stream:
        welcome_text = state.get("welcome_text", "")
        if queue and welcome_text:
            await queue.put({"event": "welcome", "data": welcome_text})

    # 2. 并行检索
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

    # 3. SSE 逐品类 → 逐商品发送
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

        # 3a. 品类介绍语
        if total_valid > 1:
            if stream and queue:
                # 流式路径: 逐 token 推送 category_intro_stream
                try:
                    prompt = CATEGORY_INTRO_SYSTEM.format(
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

        # 3b. 逐商品推荐
        if products:
            reason_tasks = [
                _generate_product_reason(p, user_query, products, llm, session_memory=state.get("session_memory"))
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

    # 4. Memory 更新
    new_memory = state.get("session_memory", [])
    if requirements and user_query:
        categories_list = [
            {"category": req.get("category"), "sub_category": req.get("sub_category")}
            for req in requirements
        ]
        new_memory = append_query(
            new_memory,
            query=user_query,
            categories=categories_list,
            timestamp=datetime.now().isoformat(),
        )

    logger.info("Retrieval 节点完成",
                total_products=len(retrieval_results),
                failed_categories=len(failed_categories))

    return {
        "retrieval_results": retrieval_results,
        "failed_categories": [f["sub_category"] for f in failed_categories],
        "session_memory": new_memory,
    }
