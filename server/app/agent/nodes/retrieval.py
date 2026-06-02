"""
Product Retrieval 节点 — 最复杂节点。

5 步流水线：
1. LLM 需求筛选（2000 token 窗口）
2. 按 sub_category 分组（三级回退）
3. 并行检索 + Generator 流式生成（asyncio.Semaphore，独立 session）
4. 品类顺序式 SSE 发送（products + reasoning 事件，由 retrieval_node 统一发送）
5. 聚合 retrieval_results + failed_categories
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

    structured_filter 子查询（如价格过滤）会被合并到所有非 default 分组中，
    确保过滤条件与关键词/语义搜索同时生效。

    参数:
        sub_queries: 字典形式的 SubQuery 列表。

    返回值:
        分组后的字典，key 为品类路由键。
    """
    # 分离 structured_filter 和普通子查询
    filter_subs = [sq for sq in sub_queries if sq.get("strategy") == "structured_filter"]
    normal_subs = [sq for sq in sub_queries if sq.get("strategy") != "structured_filter"]

    groups: dict[str, list[dict]] = {}
    for sq in normal_subs:
        key = sq.get("sub_category") or sq.get("category") or "default"
        if key not in groups:
            groups[key] = []
        groups[key].append(sq)

    # 将 structured_filter 合并到所有非 default 分组中
    if filter_subs and groups:
        for key in list(groups.keys()):
            if key != "default":
                groups[key].extend(filter_subs)

    return groups


def _aggregate_results(results: list[dict]) -> tuple[list[dict], list[dict]]:
    """串行聚合各品类任务的返回结果。

    参数:
        results: 品类任务返回的结构化结果列表，每项格式:
            {category, sub_category, skus, error}

    返回值:
        (retrieval_results, failed_categories)
    """
    retrieval_results = []
    failed_categories = []
    for r in results:
        if r["error"]:
            failed_categories.append({
                "category": r["category"],
                "sub_category": r["sub_category"],
                "error": r["error"],
            })
        else:
            retrieval_results.extend(r.get("skus", []))
    return retrieval_results, failed_categories


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
) -> dict:
    """单个品类的检索任务（在独立 session 中执行）。

    返回结构化结果: {category, sub_category, skus, product_ids, reasoning_text, error}
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
            logger.info(f"品类 [{category}/{sub_category}] 开始检索",
                        sub_queries=[s.text for s in subs], count=len(subs))
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

            logger.info(f"品类 [{category}/{sub_category}] 检索完成",
                        sku_count=len(ranked))

            if not ranked:
                return {
                    "category": category,
                    "sub_category": sub_category,
                    "skus": [],
                    "product_ids": [],
                    "reasoning_text": "",
                    "error": None,
                }

            # 4. 获取 SKU 详情
            skus = await _get_skus(db, ranked)

            # 5. 构建 product_ids（供 retrieval_node 统一发送 SSE）
            product_ids = [
                {"product_id": s["product_id"], "sku_id": s["sku_id"],
                 "category": category, "sub_category": sub_category}
                for s in skus
            ]

            # 6. Generator 流式生成推荐理由（缓冲后统一发送——品类顺序式 Q1 方案B）
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

            # 缓冲 token，拼接为完整文本后由 retrieval_node 统一按品类顺序发送 SSE
            reasoning_text = "".join(tokens)
            logger.info(f"品类 [{category}/{sub_category}] 推荐理由",
                        reasoning_preview=reasoning_text[:200])
            return {
                "category": category,
                "sub_category": sub_category,
                "skus": skus,
                "product_ids": product_ids,
                "reasoning_text": reasoning_text,
                "error": None,
            }

    except Exception as e:
        logger.error(f"品类检索失败: {category}/{sub_category}", error=str(e))
        return {
            "category": category,
            "sub_category": sub_category,
            "skus": [],
            "product_ids": [],
            "reasoning_text": "",
            "error": str(e),
        }


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
        dict: {"retrieval_results": [...], "failed_categories": [...]}
    """
    user_query = state.get("user_query", "")
    sub_queries = state.get("requirements", {}).get("sub_queries", [])
    queue = _sse_queue or state.get("_sse_queue")

    if not sub_queries:
        return {"retrieval_results": [], "failed_categories": []}

    # Step 1: LLM 需求筛选
    filtered_subs = await _filter_sub_queries(sub_queries, user_query, llm)

    # Step 2: 按 sub_category 分组
    groups = _group_sub_queries(filtered_subs)

    # Step 3: 并行检索（asyncio.Semaphore 限流）
    semaphore = asyncio.Semaphore(settings.search.max_category_concurrency)

    async def _bounded_task(key, subs):
        async with semaphore:
            return await _category_task(
                key, subs, user_query, async_session_factory, emb_service, llm
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
                "skus": [], "product_ids": [],
                "reasoning_text": "", "error": str(r),
            })
        else:
            safe_results.append(r)

    # Step 4: 品类顺序式发送 products + reasoning（Q1 方案B）
    if queue:
        for r in safe_results:
            if r.get("error"):
                continue
            # 发送 products 事件
            product_ids = r.get("product_ids", [])
            if product_ids:
                await queue.put({"event": "products", "data": product_ids})
            # 发送 reasoning 事件
            reason = r.get("reasoning_text", "")
            if reason:
                await queue.put({
                    "event": "reasoning",
                    "data": {
                        "token": reason,
                        "category": r.get("category", ""),
                        "sub_category": r.get("sub_category", ""),
                    }
                })

    # Step 5: 聚合 retrieval_results
    retrieval_results, failed_categories = _aggregate_results(safe_results)

    return {
        "retrieval_results": retrieval_results,
        "failed_categories": [f["sub_category"] for f in failed_categories],
    }
