"""
Option Gen 节点 — 推荐选项生成。

从 AgentState 读取 retrieval_results（含商品基础信息 + matched_texts），
    纯 LLM 调用生成 2-4 条下一步推荐选项。
零 DB 访问。
"""
import json
import structlog
from app.agent.prompts.option_gen_prompt import OPTION_GEN_SYSTEM
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


async def option_gen_node(state: dict, llm: LLMService) -> dict:
    """Option Gen 节点函数。

    参数:
        state: AgentState 字典。
        llm: LLMService 实例。

    返回值:
        dict: {"next_options": [...]}
    """
    options: list[str] = []

    try:
        requirements = json.dumps(state.get("requirements", {}), ensure_ascii=False)
        retrieval_results = _build_retrieval_summary(
            state.get("retrieval_results", [])
        )
        scenario_description = state.get("scenario_description") or "无"
        failed_categories = state.get("failed_categories", [])
        failed_categories_str = (
            json.dumps(failed_categories, ensure_ascii=False) if failed_categories else "无"
        )

        prompt = (
            OPTION_GEN_SYSTEM
            .replace("{requirements}", requirements)
            .replace("{retrieval_results}", retrieval_results)
            .replace("{scenario_description}", scenario_description)
            .replace("{failed_categories}", failed_categories_str)
        )
        messages = [
            {"role": "system", "content": prompt},
            {"role": "user", "content": "请生成下一步推荐选项"},
        ]

        logger.debug("option_gen prompt", prompt_len=len(prompt),
                     product_count=len(state.get("retrieval_results", [])))

        raw_response = await llm.chat(messages, temperature=0.3)

        start = raw_response.find("{")
        end = raw_response.rfind("}") + 1
        if start >= 0 and end > start:
            data = json.loads(raw_response[start:end])
            options = data.get("next_options", [])
        else:
            logger.warning("Option Gen 响应不含 JSON", raw=raw_response[:200])
    except Exception as e:
        logger.warning("Option Gen 调用失败", error=str(e))

    # 截断到最多 3 条
    if len(options) > 3:
        options = options[:3]

    # next_options 由 _agent_event_stream 的 finally 块统一从 final_state 读取并发送，
    # 避免队列排空和 finally 块双重发送。
    return {"next_options": options}
