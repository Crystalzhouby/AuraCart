"""
Intent Router 节点 — 工作流第一个节点。

根据 user_query + conversation_history 做两级分类：
1. 意图分流: recommend / chat
2. 查询类型: is_scenario (场景化需求) / explicit (明确商品需求)

一次 LLM 调用同时输出 intent + is_scenario，驱动条件边。
"""
import json
import structlog
from app.agent.prompts.router_prompt import ROUTER_SYSTEM
from app.services.llm import LLMService

logger = structlog.get_logger("agent.router")


def _parse_router_response(raw: str) -> dict:
    """从 LLM 原始响应中提取 JSON，失败返回 fallback 默认值。

    增强容错：
    - markdown 代码围栏 (```json ... ```)
    - 尾随逗号（常见 LLM 错误）
    - JSON 前后的说明文字
    """
    if not raw:
        return {"intent": "recommend", "is_scenario": False}

    # 尝试提取第一个 { ... } JSON 对象
    start = raw.find("{")
    end = raw.rfind("}") + 1
    if start < 0 or end <= start:
        return {"intent": "recommend", "is_scenario": False}

    json_str = raw[start:end]

    # 1. 直接解析
    try:
        return json.loads(json_str)
    except json.JSONDecodeError:
        pass

    # 2. 移除尾随逗号后重试（常见 LLM 输出错误）
    import re
    cleaned = re.sub(r",\s*([}\]])", r"\1", json_str)
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass

    return {"intent": "recommend", "is_scenario": False}


async def router_node(state: dict, llm: LLMService) -> dict:
    """Intent Router 节点函数。

    参数:
        state: AgentState 字典，读取 user_query 和 conversation_history。
        llm: LLMService 实例，通过闭包/参数注入。

    返回值:
        dict: {"intent": str, "is_scenario": bool}，写入 AgentState。
    """
    user_query = state.get("user_query", "")
    conversation_history = state.get("conversation_history", [])

    # 序列化对话历史
    history_str = ""
    if conversation_history:
        history_str = json.dumps(conversation_history, ensure_ascii=False)

    prompt = ROUTER_SYSTEM.replace("{conversation_history}", history_str).replace("{user_query}", user_query)
    messages = [
        {"role": "system", "content": prompt},
        {"role": "user", "content": user_query},
    ]

    try:
        raw_response = await llm.chat(messages, temperature=0.1)
        parsed = _parse_router_response(raw_response)
    except Exception as e:
        logger.warning("Router LLM 调用失败，使用 fallback", error=str(e))
        parsed = {"intent": "recommend", "is_scenario": False}

    return {"intent": parsed.get("intent", "recommend"), "is_scenario": parsed.get("is_scenario", False)}
