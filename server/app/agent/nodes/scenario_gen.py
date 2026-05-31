"""
Scenario Gen 节点 — 场景化需求路径。

从 category_lookup 表获取可用品类列表，与 user_query 一起注入提示词，
单次 LLM 调用端到端输出带品类标签的 SubQuery 列表。
"""
import json
import structlog
from app.config import settings
from app.agent.prompts.scenario_gen_prompt import SCENARIO_GEN_SYSTEM
from app.services.llm import LLMService

logger = structlog.get_logger("agent.scenario_gen")


async def scenario_gen_node(state: dict, llm: LLMService, category_list: str = "") -> dict:
    """Scenario Gen 节点函数。

    参数:
        state: AgentState 字典。
        llm: LLMService 实例。
        category_list: 从 category_lookup 表查询的可用品类列表字符串。

    返回值:
        dict: {"scenario_description": str, "requirements": {"sub_queries": [...]}}
    """
    user_query = state.get("user_query", "")
    conversation_history = state.get("conversation_history", [])

    prompt = SCENARIO_GEN_SYSTEM.replace("{category_list}", category_list).replace("{user_query}", user_query)
    messages = [
        {"role": "system", "content": prompt},
        {"role": "user", "content": user_query},
    ]

    try:
        raw_response = await llm.chat(messages, temperature=0.3)

        # 解析 LLM JSON 响应
        start = raw_response.find("{")
        end = raw_response.rfind("}") + 1
        if start >= 0 and end > start:
            data = json.loads(raw_response[start:end])
        else:
            raise ValueError("无法从 LLM 响应中提取 JSON")

        scenario_description = data.get("scenario_description", user_query)
        sub_queries = data.get("requirements", {}).get("sub_queries", [])

    except Exception as e:
        logger.warning("Scenario Gen LLM 调用失败，返回空结果", error=str(e))
        return {
            "scenario_description": user_query,
            "requirements": {"sub_queries": []},
        }

    # 标准化 SubQuery 字典格式
    subs_dicts = []
    for sq in sub_queries:
        subs_dicts.append({
            "text": sq.get("text", ""),
            "strategy": sq.get("strategy", "semantic"),
            "field": sq.get("field"),
            "operator": sq.get("operator"),
            "value": sq.get("value"),
            "expanded_values": sq.get("expanded_values"),
            "category": sq.get("category"),
            "sub_category": sq.get("sub_category"),
        })

    # 追加到 conversation_history + 截断
    new_entry = {"sub_queries": subs_dicts}
    new_history = conversation_history + [new_entry]
    from app.agent.memory import truncate_by_tokens
    new_history = truncate_by_tokens(new_history, max_tokens=settings.search.memory_max_tokens, logger=logger)

    return {
        "scenario_description": scenario_description,
        "requirements": {"sub_queries": subs_dicts},
        "conversation_history": new_history,
    }
