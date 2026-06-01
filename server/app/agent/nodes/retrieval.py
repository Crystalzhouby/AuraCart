"""
Product Retrieval 节点 — 最复杂节点。

5 步流水线：
1. LLM 需求筛选（2000 token 窗口）
2. 按 sub_category 分组（三级回退）
3. 并行检索（asyncio.Semaphore，独立 session）
4. 渐进式 SSE（products + reasoning 事件）
5. 聚合 products_summary + failed_categories
"""
import asyncio
import json
import structlog

from app.config import settings
from app.services.retriever import Retriever, SubQuery
from app.services.sku_utils import _get_skus
from app.rag.merger import Merger
from app.rag.generator import Generator
from app.agent.prompts.relevance_filter_prompt import RELEVANCE_FILTER_SYSTEM

logger = structlog.get_logger("agent.retrieval")


def _group_sub_queries(sub_queries: list[dict]) -> dict[str, list[dict]]:
    """按 sub_category 分组，三级回退：sub_category → category → default。

    参数:
        sub_queries: 字典形式的 SubQuery 列表。

    返回值:
        分组后的字典，key 为品类路由键。
    """
    groups: dict[str, list[dict]] = {}
    for sq in sub_queries:
        key = sq.get("sub_category") or sq.get("category") or "default"
        if key not in groups:
            groups[key] = []
        groups[key].append(sq)
    return groups


def _aggregate_results(results: list[dict]) -> tuple[list[dict], list[dict]]:
    """串行聚合各品类任务的返回结果。

    参数:
        results: 品类任务返回的结构化结果列表，每项格式:
            {category, sub_category, products_summary, error}

    返回值:
        (products_summary, failed_categories)
    """
    products_summary = []
    failed_categories = []
    for r in results:
        if r["error"]:
            failed_categories.append({
                "category": r["category"],
                "sub_category": r["sub_category"],
                "error": r["error"],
            })
        else:
            products_summary.extend(r.get("products_summary", []))
    return products_summary, failed_categories


async def _filter_sub_queries(
    sub_queries: list[dict],
    user_query: str,
    llm,
) -> list[dict]:
    """LLM 需求筛选：从历史需求中筛选与当前查询相关的子集。

    输入窗口 2000 token（与 Memory 截断阈值一致）。
    失败时返回全部 sub_queries。
    """
    if len(sub_queries) <= 1:
        return sub_queries  # 单轮无需筛选

    history_text = json.dumps(sub_queries, ensure_ascii=False)
    prompt = (
        RELEVANCE_FILTER_SYSTEM
        .replace("{user_query}", user_query)
        .replace("{history_sub_queries}", history_text)
    )
    messages = [
        {"role": "system", "content": prompt},
        {"role": "user", "content": user_query},
    ]

    try:
        raw = await llm.chat(messages, temperature=0.1)
        start = raw.find("{")
        end = raw.rfind("}") + 1
        if start >= 0 and end > start:
            data = json.loads(raw[start:end])
            indices = data.get("relevant_indices", [])
            if indices:
                return [sub_queries[i] for i in indices if i < len(sub_queries)]
    except Exception as e:
        logger.warning("LLM 筛选失败，使用全部历史需求", error=str(e))

    return sub_queries


async def _category_task(
    group_key: str,
    sub_queries: list[dict],
    user_query: str,
    async_session_factory,
    emb_service,
    llm,
    queue,
) -> dict:
    """单个品类的检索任务（在独立 session 中执行）。

    返回结构化结果: {category, sub_category, products_summary, error}
    """
    category = sub_queries[0].get("category", "") if sub_queries else ""
    sub_category = group_key if group_key != "default" else ""

    try:
        async with async_session_factory() as db:
            # 1. 构建 SubQuery 对象
            subs = [
                SubQuery(
                    text=sq.get("text", ""),
                    strategy=sq.get("strategy", "semantic"),
                    field=sq.get("field"),
                    operator=sq.get("operator"),
                    value=sq.get("value"),
                    expanded_values=sq.get("expanded_values"),
                    category=sq.get("category"),
                    sub_category=sq.get("sub_category"),
                )
                for sq in sub_queries
            ]

            # 2. 检索
            retriever = Retriever(db=db, emb=emb_service)
            retrieve_result = await retriever.retrieve(
                subs, top_k=settings.search.top_k_per_query
            )

            # 3. RRF 融合
            merger = Merger(
                rrf_k=settings.search.rrf_k,
                final_limit=settings.search.final_sku_limit,
            )
            ranked = merger.merge(
                keyword_ranked=retrieve_result["keyword"],
                semantic_ranked=retrieve_result["semantic"],
            )

            if not ranked:
                return {
                    "category": category,
                    "sub_category": sub_category,
                    "products_summary": [],
                    "error": None,
                }

            # 4. 获取 SKU 详情
            skus = await _get_skus(db, ranked)

            # 5. 发送 products SSE 事件
            product_ids = [
                {"product_id": s["product_id"], "sku_id": s["sku_id"],
                 "category": category, "sub_category": sub_category}
                for s in skus
            ]
            if queue:
                await queue.put({"event": "products", "data": product_ids})

            # 6. 提取 products_summary
            summary = [
                {"product_id": s["product_id"], "sku_id": s["sku_id"],
                 "title": s["title"], "price": s["price"],
                 "category": category, "sub_category": sub_category}
                for s in skus
            ]

            # 7. Generator 流式生成推荐理由（缓冲后统一发送——品类顺序式 Q1 方案B）
            generator = Generator(llm=llm)
            tokens: list[str] = []
            agen = generator.generate(skus, user_query, sub_queries=subs)
            deadline = asyncio.get_event_loop().time() + settings.timeout.generation
            try:
                while True:
                    remaining = deadline - asyncio.get_event_loop().time()
                    if remaining <= 0:
                        logger.warning(f"Generator 超时: {category}/{sub_category}", token_count=len(tokens))
                        break
                    try:
                        token = await asyncio.wait_for(agen.__anext__(), timeout=remaining)
                        tokens.append(token)
                    except StopAsyncIteration:
                        break
                    except asyncio.TimeoutError:
                        logger.warning(f"Generator token 超时: {category}/{sub_category}", token_count=len(tokens))
                        break
            except Exception as gen_err:
                logger.warning(f"Generator 异常: {category}/{sub_category}", error=str(gen_err))

            # 缓冲 token，由主流程统一按品类顺序发送
            return {
                "category": category,
                "sub_category": sub_category,
                "products_summary": summary,
                "error": None,
                "reasoning_tokens": tokens,
            }

    except Exception as e:
        logger.error(f"品类检索失败: {category}/{sub_category}", error=str(e))
        return {
            "category": category,
            "sub_category": sub_category,
            "products_summary": [],
            "error": str(e),
            "reasoning_tokens": [],
        }


async def _send_reasoning_sequential(
    safe_results: list[dict],
    group_keys: list[str],
    queue,
) -> None:
    """按品类顺序串行发送 reasoning token（品类顺序式 — Q1 方案B）。

    各品类任务将 token 缓存在 reasoning_tokens 中，
    此函数按 group_keys 顺序将它们整体发送到 SSE 队列。

    参数:
        safe_results: 品类任务返回的结构化结果列表。
        group_keys: groups 字典的键列表（决定发送顺序）。
        queue: SSE 事件队列。
    """
    if not queue:
        return

    # 建立 sub_category → result 的映射，便于按 group_keys 顺序访问
    result_map = {}
    for r in safe_results:
        sc = r.get("sub_category", "")
        result_map[sc] = r

    for key in group_keys:
        r = result_map.get(key, {})
        if r.get("error"):
            continue  # 失败品类跳过
        tokens: list[str] = r.get("reasoning_tokens", [])
        if not tokens:
            continue

        category = r.get("category", "")
        sub_category = r.get("sub_category", "")
        full_text = "".join(tokens)
        await queue.put({
            "event": "reasoning",
            "data": {
                "token": full_text,
                "category": category,
                "sub_category": sub_category,
            }
        })


async def retrieval_node(
    state: dict,
    llm,
    emb_service,
    async_session_factory,
    _sse_queue=None,
) -> dict:
    """Product Retrieval 节点函数。

    参数:
        state: AgentState 字典。
        llm: LLMService 实例。
        emb_service: EmbeddingService 实例。
        async_session_factory: async_session 工厂函数。
        _sse_queue: SSE 事件队列（可选）。

    返回值:
        dict: {"products_summary": [...], "failed_categories": [...]}
    """
    user_query = state.get("user_query", "")
    sub_queries = state.get("requirements", {}).get("sub_queries", [])
    queue = _sse_queue or state.get("_sse_queue")

    if not sub_queries:
        return {"products_summary": [], "failed_categories": []}

    # Step 1: LLM 需求筛选
    filtered_subs = await _filter_sub_queries(sub_queries, user_query, llm)

    # Step 2: 按 sub_category 分组
    groups = _group_sub_queries(filtered_subs)

    # Step 3: 并行检索（asyncio.Semaphore 限流）
    semaphore = asyncio.Semaphore(settings.search.max_category_concurrency)

    async def _bounded_task(key, subs):
        async with semaphore:
            return await _category_task(
                key, subs, user_query, async_session_factory, emb_service, llm, queue
            )

    tasks = [_bounded_task(key, subs) for key, subs in groups.items()]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    # 将 asyncio.gather 返回的异常转换为结构化错误
    safe_results = []
    group_key_list = list(groups.keys())
    for i, r in enumerate(results):
        if isinstance(r, Exception):
            key = group_key_list[i] if i < len(group_key_list) else "unknown"
            safe_results.append({
                "category": "", "sub_category": key,
                "products_summary": [], "error": str(r),
                "reasoning_tokens": [],
            })
        else:
            safe_results.append(r)

    # Step 4: 品类顺序式发送 reasoning（Q1 方案B）
    await _send_reasoning_sequential(safe_results, group_key_list, queue)

    # Step 5: 聚合 products_summary
    products_summary, failed_categories = _aggregate_results(safe_results)

    return {
        "products_summary": products_summary,
        "failed_categories": [f["sub_category"] for f in failed_categories],
    }
