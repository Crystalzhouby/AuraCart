"""
Intent Extraction 节点 — 明确商品需求路径。

从 user_query 中提取结构化 SubQuery 列表，复用扩展后的 QUERY_PARSE_SYSTEM。
具备品类标记能力（category/sub_category），与 Scenario Gen 保持数据契约一致。
"""
import json
import structlog
from app.config import settings
from app.rag.prompt import QUERY_PARSE_SYSTEM
from app.services.llm import LLMService

logger = structlog.get_logger("agent.extraction")


def _format_history_context(conversation_history: list[dict]) -> str:
    """从 conversation_history 中提取子查询，格式化为 LLM 可消费的历史需求文本。

    每轮对话只取 sub_queries 中的 text/strategy/category/sub_category 关键字段，
    省略内部细节（field/operator/value 等），控制注入量。

    参数:
        conversation_history: 对话历史列表。

    返回值:
        str: 格式化的历史需求文本（在提示词中注入）。空历史返回 ""。
    """
    if not conversation_history:
        return ""

    lines = []
    for i, entry in enumerate(conversation_history, 1):
        subs = entry.get("sub_queries", [])
        for sq in subs:
            parts = [f"text={sq.get('text', '')}"]
            if sq.get("category"):
                parts.append(f"category={sq['category']}")
            if sq.get("sub_category"):
                parts.append(f"sub_category={sq['sub_category']}")
            lines.append(", ".join(parts))
    if not lines:
        return ""

    header = "## 用户历史需求"
    body = "\n".join(f"- {line}" for line in lines)
    return f"{header}\n{body}"


async def extraction_node(state: dict, llm: LLMService) -> dict:
    """Intent Extraction 节点函数。

    参数:
        state: AgentState 字典。
        llm: LLMService 实例。

    返回值:
        dict: {"requirements": {"sub_queries": [...]}, "conversation_history": [...]}
    """
    user_query = state.get("user_query", "")
    conversation_history = state.get("conversation_history", [])

    # 组装提示词：QUERY_PARSE_SYSTEM + 历史需求上下文 + 用户查询
    history_context = _format_history_context(conversation_history)
    system_prompt = QUERY_PARSE_SYSTEM
    if history_context:
        system_prompt = QUERY_PARSE_SYSTEM + "\n\n" + history_context

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_query},
    ]

    try:
        # 使用流式调用收集完整响应
        parts = []
        async for token in llm.chat_stream(messages, temperature=0.1):
            parts.append(token)
        raw_response = "".join(parts)

        # 复用 QueryParser 的解析逻辑
        from app.services.query_parser import QueryParser
        parser = QueryParser(llm=llm)
        sub_queries = parser._parse_response(raw_response)
    except Exception as e:
        logger.warning("Extraction LLM 调用失败，使用 fallback", error=str(e))
        from app.services.retriever import SubQuery
        sub_queries = [SubQuery(text=user_query, strategy="semantic")]

    # 转为可序列化字典列表
    subs_dicts = [
        {
            "text": sq.text, "strategy": sq.strategy,
            "field": sq.field, "operator": sq.operator,
            "value": sq.value, "expanded_values": sq.expanded_values,
            "category": sq.category, "sub_category": sq.sub_category,
        }
        for sq in sub_queries
    ]

    # 追加到 conversation_history
    new_entry = {"sub_queries": subs_dicts}
    new_history = conversation_history + [new_entry]

    # 写时截断（使用配置驱动的 token 上限）
    from app.agent.memory import truncate_by_tokens
    new_history = truncate_by_tokens(new_history, max_tokens=settings.search.memory_max_tokens, logger=logger)

    return {
        "requirements": {"sub_queries": subs_dicts},
        "conversation_history": new_history,
    }
