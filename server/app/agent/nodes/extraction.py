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

    # 构建对话历史上下文
    history_text = ""
    if conversation_history:
        history_text = json.dumps(conversation_history, ensure_ascii=False)

    # 组装提示词：QUERY_PARSE_SYSTEM + 对话历史 + 用户查询
    system_prompt = QUERY_PARSE_SYSTEM
    if history_text:
        system_prompt = QUERY_PARSE_SYSTEM.replace(
            "现在请对以下用户查询进行拆解",
            f"## 对话历史\n{history_text}\n\n现在请对以下用户查询进行拆解"
        )

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
