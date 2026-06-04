"""
Product Retrieval 节点 — 重构后。

流水线：
1. 按品类分组检索（requirements 已按品类分组）
2. SQL 条件转换 + 双路检索（语义 top-25 + 关键词 top-25）并行
3. 加权 RRF 融合（semantic 0.7 / keyword 0.3）→ top-25
4. bge-reranker 精排（top-5）+ fallback
5. 按品类生成推荐理由（LLM，复用 GENERATOR_SYSTEM 提示词）
6. 品类顺序式 SSE 发送（products → chat_reply）+ 聚合
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
from app.agent.prompts.generator_prompt import GENERATOR_SYSTEM

logger = structlog.get_logger("agent.retrieval")

# source → 中文标签映射，用于构建推荐理由上下文的匹配文本
SOURCE_LABEL = {"user_review": "[用户评价]", "marketing": "[官方描述]", "faq": "[FAQ]"}


def _intent_to_sub_queries(intent: dict) -> list[SubQuery]:
    """将新格式意图转换为 SubQuery 对象列表，兼容现有 Retriever 接口。

    参数:
        intent: {category, sub_category, text, min_price, max_price, order_num, brand}

    返回值:
        [SubQuery(text=..., strategy="semantic"), SubQuery(strategy="structured_filter"), ...]
    """
    subs = []
    cat = intent.get("category")
    sub = intent.get("sub_category")
    text = intent.get("text", "")
    min_p = intent.get("min_price", 0)
    max_p = intent.get("max_price", 4294967295)
    order_n = intent.get("order_num", 1)
    brands = intent.get("brand")

    # 关键词查询（精确商品/品类名匹配）
    if text:
        subs.append(SubQuery(text=text, strategy="keyword",
                             category=cat, sub_category=sub))
    # 语义查询（主观评价/体验意图）
    if text:
        subs.append(SubQuery(text=text, strategy="semantic",
                             category=cat, sub_category=sub))

    # 结构化条件
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


def _build_product_context(skus: list[dict]) -> str:
    """按 product_id 分组构建商品上下文字符串，用于 LLM 生成推荐理由。

    将扁平 SKU 列表按 product_id 归组，每组渲染为一个商品条目：
    商品概要行（标题/品牌/品类/基础价格），后跟组内每条 SKU 的详情行，
    最后追加匹配文本（FAQ / 用户评价 / 官方描述）。组间以空行分隔。

    参数:
        skus: 扁平 SKU 字典列表，与 retrieval_results 格式一致。

    返回值:
        适合注入 LLM 提示词的多行字符串，作为商品上下文。
    """
    if not skus:
        return ""

    # 按 product_id 分组，保持首次出现顺序
    grouped: dict[str, dict] = {}
    order: list[str] = []
    for item in skus:
        pid = item["product_id"]
        if pid not in grouped:
            grouped[pid] = {
                "title": item["title"],
                "brand": item.get("brand"),
                "category": item.get("category"),
                "base_price": item.get("base_price"),
                "skus": [],
            }
            order.append(pid)
        grouped[pid]["skus"].append({
            "sku_id": item["sku_id"],
            "properties": item.get("properties"),
            "price": item["price"],
        })

    lines = []
    for i, pid in enumerate(order, 1):
        p = grouped[pid]
        lines.append(f"{i}. {p['title']}")
        if p.get("brand"):
            lines.append(f"   品牌: {p['brand']}")
        if p.get("category"):
            lines.append(f"   品类: {p['category']}")
        if p.get("base_price"):
            lines.append(f"   基础价格: ¥{p['base_price']}")

        for sku in p["skus"]:
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

    # ---- 追加匹配文本（用户评价/官方描述/FAQ） ----
    matched_lines: list[str] = []
    for item in skus:
        for mt in item.get("matched_texts", []):
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
    llm=None,
) -> dict:
    """单个品类的检索任务：SQL 条件 → 双路检索 → RRF → reranker → 推荐理由生成。

    参数:
        intent: 单品类意图 {category, sub_category, text, min_price, max_price, order_num, brand}
        async_session_factory: async_session 工厂函数。
        emb_service: EmbeddingService 实例。
        reranker: RerankerService 实例（可选）。
        llm: LLMService 实例（可选），用于生成推荐理由。

    返回值:
        {category, sub_category, skus, product_ids, reasoning_text, error}
    """
    category = intent.get("category") or ""
    sub_category = intent.get("sub_category") or ""
    text = intent.get("text", "")

    try:
        # 将意图转换为 SubQuery 列表（兼容现有 Retriever 接口）
        subs = _intent_to_sub_queries(intent)

        async with async_session_factory() as db:
            logger.info(f"品类 [{category}/{sub_category}] 开始检索", text=text[:80])

            # 双路检索（Retriever 内部并行执行 semantic + keyword）
            retriever = Retriever(db=db, emb=emb_service)
            retrieve_result = await retriever.retrieve(
                subs, top_k=max(settings.search.semantic_top_k,
                                settings.search.keyword_top_k)
            )
            kw_results = retrieve_result["keyword"]
            sem_results = retrieve_result["semantic"]
            merged_meta = retrieve_result.get("hit_metadata", {})

            # 3. 加权 RRF 融合
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
                        sku_count=len(rrf_ranked))

            if not rrf_ranked:
                return {
                    "category": category, "sub_category": sub_category,
                    "skus": [], "product_ids": [],
                    "reasoning_text": "", "error": None,
                }

            # 4. bge-reranker 精排
            if reranker and len(rrf_ranked) > settings.search.rerank_top_k:
                # 构建 documents 文本列表
                documents = []
                for hit in rrf_ranked:
                    meta = merged_meta.get(hit.sku_id, {})
                    title = meta.get("title", "")
                    matched = meta.get("matched_texts", [])
                    first_text = matched[0].get("content", "") if matched else ""
                    documents.append(f"title: {title} | {first_text}"[:500])

                rerank_results = await reranker.rerank(
                    query=text, documents=documents,
                    top_n=settings.search.rerank_top_k,
                )

                if rerank_results:
                    # 用 rerank index 映射回 SKU
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
                    # fallback: RRF top-5
                    rrf_ranked = rrf_ranked[:settings.search.rerank_top_k]
            else:
                rrf_ranked = rrf_ranked[:settings.search.rerank_top_k]

            # 5. Review 截断 + 组装 SKU 数据
            skus = []
            for hit in rrf_ranked:
                data = merged_meta.get(hit.sku_id)
                if data is None:
                    continue
                raw_texts = data.get("matched_texts", [])
                # Review 截断
                truncated = _truncate_texts(
                    raw_texts,
                    settings.search.max_reviews_per_product,
                    settings.search.max_match_chars_per_sku,
                )
                data["matched_texts"] = truncated
                skus.append(data)

            logger.info(f"品类 [{category}/{sub_category}] 检索完成",
                        final_sku_count=len(skus))

            # 6. 生成推荐理由：检索结束后立刻按品类独立生成
            reasoning_text = ""
            if skus and llm:
                try:
                    context = _build_product_context(skus)
                    user_intent = text or ""
                    cat_label = f"{category}/{sub_category}".strip("/")
                    requirements_summary = f"品类: {cat_label}"
                    if user_intent:
                        requirements_summary += f"\n用户关注: {user_intent}"

                    system_prompt = GENERATOR_SYSTEM.format(
                        product_context=context,
                        requirements_summary=requirements_summary,
                        reasoning_max_chars=settings.search.reasoning_max_chars,
                    )
                    user_msg = f"请根据以上商品信息，为用户推荐：{user_intent or cat_label + '推荐'}"

                    messages = [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_msg},
                    ]
                    reasoning_text = await llm.chat(messages, temperature=0.3)
                    logger.info(f"品类 [{category}/{sub_category}] 推荐理由生成完成",
                                chars=len(reasoning_text))
                except Exception as e:
                    logger.warning(f"品类 [{category}/{sub_category}] 推荐理由生成失败",
                                   error=str(e))
                    reasoning_text = ""

            return {
                "category": category,
                "sub_category": sub_category,
                "skus": skus,
                "product_ids": [
                    {"product_id": s["product_id"], "sku_id": s["sku_id"],
                     "category": category, "sub_category": sub_category}
                    for s in skus
                ],
                "reasoning_text": reasoning_text,
                "error": None,
            }

    except Exception as e:
        logger.error(f"品类检索失败: {category}/{sub_category}",
                     error=str(e), traceback=traceback.format_exc())
        return {
            "category": category, "sub_category": sub_category,
            "skus": [], "product_ids": [],
            "reasoning_text": "", "error": str(e),
        }


async def retrieval_node(
    state: dict,
    llm=None,
    emb_service=None,
    async_session_factory=None,
    reranker=None,
    _sse_queue=None,
) -> dict:
    """Product Retrieval 节点函数 — 重构版。

    参数:
        state: AgentState 字典。
        llm: LLMService 实例，传递给 _category_task 用于生成推荐理由。
        emb_service: EmbeddingService 实例。
        async_session_factory: async_session 工厂函数。
        reranker: RerankerService 实例（可选）。
        _sse_queue: SSE 事件队列（可选）。

    返回值:
        dict: {"retrieval_results", "failed_categories", "session_memory"}
    """
    user_query = state.get("user_query", "")
    requirements = state.get("requirements", [])
    queue = _sse_queue or state.get("_sse_queue")

    if not requirements:
        return {"retrieval_results": [], "failed_categories": [], "session_memory": state.get("session_memory", [])}

    logger.info("Retrieval 节点开始", user_query=user_query,
                requirement_count=len(requirements))

    # 并行检索（多品类 + asyncio.Semaphore 限流）
    semaphore = asyncio.Semaphore(settings.search.max_category_concurrency)

    async def _bounded_task(intent):
        async with semaphore:
            return await _category_task(
                intent, async_session_factory, emb_service, reranker, llm
            )

    tasks = [_bounded_task(req) for req in requirements]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    # 异常处理
    safe_results = []
    for i, r in enumerate(results):
        if isinstance(r, Exception):
            req = requirements[i] if i < len(requirements) else {}
            safe_results.append({
                "category": req.get("category", ""),
                "sub_category": req.get("sub_category", ""),
                "skus": [], "product_ids": [],
                "reasoning_text": "", "error": str(r),
            })
        else:
            safe_results.append(r)

    # SSE 发送 + 聚合
    retrieval_results = []
    failed_categories = []
    for r in safe_results:
        if r.get("error"):
            failed_categories.append({
                "category": r.get("category", ""),
                "sub_category": r.get("sub_category", ""),
                "error": r["error"],
            })
        else:
            retrieval_results.extend(r.get("skus", []))

            # SSE: products（商品 ID 列表）
            if queue:
                product_ids = r.get("product_ids", [])
                if product_ids:
                    await queue.put({"event": "products", "data": product_ids})

                # SSE: chat_reply（该品类的推荐理由文案）
                reasoning = r.get("reasoning_text", "")
                if reasoning:
                    await queue.put({"event": "chat_reply", "data": reasoning})

    # Memory 更新：原始查询按品类追加到 session_memory
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
                total_skus=len(retrieval_results),
                failed_categories=len(failed_categories))

    return {
        "retrieval_results": retrieval_results,
        "failed_categories": [f["sub_category"] for f in failed_categories],
        "session_memory": new_memory,
    }
