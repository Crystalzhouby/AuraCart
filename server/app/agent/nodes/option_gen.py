"""
Option Gen 节点 — 合并生成结束语 + 下一步推荐选项。

从 AgentState 读取 retrieval_results（含商品基础信息 + matched_texts），
纯 LLM 单次调用输出 ending + next_options，ending 通过 _sse_queue 发送。
零 DB 访问。
"""
import json
import structlog
from app.agent.prompts.option_gen_prompt import ENDING_OPTION_SYSTEM
from app.services.llm_service import LLMService

logger = structlog.get_logger("agent.option_gen")

# option_gen 提示词最多使用的商品数——避免 prompt 过大导致 LLM 截断
_MAX_PRODUCTS_FOR_OPTIONS = 5
# 单个商品摘要最大字符数
_MAX_CHARS_PER_PRODUCT = 300


def _summarize_product(p: dict) -> str:
    """将 product 字典压缩为一行短摘要，供 option_gen LLM 使用。"""
    title = p.get("title", "未知商品")
    brand = p.get("brand", "")
    price = p.get("base_price", "")
    cat = p.get("category", "")
    sub = p.get("sub_category", "")

    parts = [title]
    if brand:
        parts.append(f"品牌:{brand}")
    if price is not None and price != "":
        parts.append(f"¥{price}")
    if cat and sub:
        parts.append(f"{cat}/{sub}")

    return " / ".join(str(x) for x in parts)


def _build_retrieval_summary(retrieval_results: list[dict]) -> str:
    """将 retrieval_results 压缩为 LLM 友好的精简摘要。

    只保留 title/brand/price/category，每条不超过 _MAX_CHARS_PER_PRODUCT，
    最多 _MAX_PRODUCTS_FOR_OPTIONS 条。
    """
    if not retrieval_results:
        return "（暂无推荐商品）"

    lines = []
    for i, p in enumerate(retrieval_results[:_MAX_PRODUCTS_FOR_OPTIONS], 1):
        summary = _summarize_product(p)
        if len(summary) > _MAX_CHARS_PER_PRODUCT:
            summary = summary[:_MAX_CHARS_PER_PRODUCT] + "..."
        lines.append(f"{i}. {summary}")

    total = len(retrieval_results)
    if total > _MAX_PRODUCTS_FOR_OPTIONS:
        lines.append(f"... 共 {total} 件商品，仅展示前 {_MAX_PRODUCTS_FOR_OPTIONS} 件")

    return "\n".join(lines)


def _build_ending_context(state: dict) -> dict:
    """从 state 构建结束语所需的上下文字段。"""
    retrieval_results = state.get("retrieval_results", [])
    categories = set()
    for p in retrieval_results:
        cat = p.get("category", "")
        sub = p.get("sub_category", "")
        if cat and sub:
            categories.add(f"{cat}/{sub}")
    return {
        "categories_summary": "、".join(sorted(categories)) if categories else "无",
        "product_count": len(retrieval_results),
    }


def _build_recent_queries_text(state: dict) -> str:
    """从 session_memory 构建最近查询文本。"""
    from app.agent.memory import get_recent_queries
    from app.config import settings
    memory = state.get("session_memory", [])
    if not memory:
        return "(无历史记录)"
    recent = get_recent_queries(memory, settings.search.memory_recent_rounds)
    if not recent:
        return "(无历史记录)"
    sorted_q = sorted(recent, key=lambda x: x["timestamp"])
    return "\n".join(f"- {q['query']}" for q in sorted_q)


async def option_gen_node(state: dict, llm: LLMService) -> dict:
    """Option Gen 节点函数 — 合并生成结束语 + 下一步推荐选项。

    参数:
        state: AgentState 字典。
        llm: LLMService 实例。

    返回值:
        dict: {"next_options": [...]}
    """
    options: list[str] = []
    ending: str = ""
    queue = state.get("_sse_queue")
    stream = state.get("stream", True)

    try:
        # 1. 构建结束语上下文
        ending_ctx = _build_ending_context(state)
        categories_summary = ending_ctx["categories_summary"]
        product_count = ending_ctx["product_count"]

        # 2. 构建最近查询
        recent_queries = _build_recent_queries_text(state)

        # 3. 构建选项上下文
        user_query = state.get("user_query", "")
        requirements = json.dumps(state.get("requirements", {}), ensure_ascii=False)
        retrieval_results = _build_retrieval_summary(
            state.get("retrieval_results", [])
        )
        scenario_description = state.get("scenario_description") or "无"
        failed_categories = state.get("failed_categories", [])
        failed_categories_str = (
            json.dumps(failed_categories, ensure_ascii=False) if failed_categories else "无"
        )

        # 4. LLM 调用合并 prompt
        prompt = (
            ENDING_OPTION_SYSTEM
            .replace("{user_query}", user_query)
            .replace("{categories_summary}", categories_summary)
            .replace("{product_count}", str(product_count))
            .replace("{scenario_description}", scenario_description)
            .replace("{recent_queries}", recent_queries)
            .replace("{requirements}", requirements)
            .replace("{retrieval_results}", retrieval_results)
            .replace("{failed_categories}", failed_categories_str)
        )
        messages = [
            {"role": "system", "content": prompt},
            {"role": "user", "content": "请生成结束语和推荐选项"},
        ]

        logger.debug("option_gen prompt", prompt_len=len(prompt),
                     product_count=product_count)

        if stream and queue:
            # 流式路径: chat_stream() + stream_json_field() 实时推送 ending 并解析 options
            from app.agent.utils.stream_json import stream_json_field

            await queue.put({"event": "ending_stream", "data": {"type": "start"}})

            async def _on_delta(ch: str):
                await queue.put({"event": "ending_stream", "data": {"type": "delta", "text": ch}})

            token_stream = llm.chat_stream(messages, temperature=0.3)
            _stream_events, parsed = await stream_json_field(token_stream, "ending", on_delta=_on_delta)

            await queue.put({"event": "ending_stream", "data": {"type": "end"}})

            if parsed:
                ending = parsed.get("ending", "")
                options = parsed.get("next_options", [])
            else:
                logger.warning("Option Gen 流式 JSON 解析失败，options 为空")
        else:
            # 非流式路径: 保持现有逻辑
            raw_response = await llm.chat(messages, temperature=0.3)

            start = raw_response.find("{")
            end = raw_response.rfind("}") + 1
            if start >= 0 and end > start:
                data = json.loads(raw_response[start:end])
                ending = data.get("ending", "")
                options = data.get("next_options", [])
            else:
                logger.warning("Option Gen 响应不含 JSON", raw=raw_response[:200])

            # 5. 通过 queue 发送 ending 事件
            if queue and ending:
                await queue.put({"event": "ending", "data": ending})

    except Exception as e:
        logger.warning("Option Gen 调用失败", error=str(e))

    # 截断到最多 3 条
    if len(options) > 3:
        options = options[:3]

    return {"next_options": options}
