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


async def option_gen_node(state: dict, llm: LLMService) -> dict:
    """Option Gen 节点函数。

    参数:
        state: AgentState 字典。
        llm: LLMService 实例。

    返回值:
        dict: {"next_options": [...]}
    """
    requirements = json.dumps(state.get("requirements", {}), ensure_ascii=False)
    retrieval_results = json.dumps(state.get("retrieval_results", []), ensure_ascii=False)
    conversation_history = json.dumps(state.get("conversation_history", []), ensure_ascii=False)
    scenario_description = state.get("scenario_description") or "无"
    failed_categories = state.get("failed_categories", [])
    failed_categories_str = json.dumps(failed_categories, ensure_ascii=False) if failed_categories else "无"

    prompt = (
        OPTION_GEN_SYSTEM
        .replace("{requirements}", requirements)
        .replace("{retrieval_results}", retrieval_results)
        .replace("{conversation_history}", conversation_history)
        .replace("{scenario_description}", scenario_description)
        .replace("{failed_categories}", failed_categories_str)
    )
    messages = [
        {"role": "system", "content": prompt},
        {"role": "user", "content": "请生成下一步推荐选项"},
    ]

    try:
        raw_response = await llm.chat(messages, temperature=0.3)

        start = raw_response.find("{")
        end = raw_response.rfind("}") + 1
        if start >= 0 and end > start:
            data = json.loads(raw_response[start:end])
            options = data.get("next_options", [])
        else:
            options = []
    except Exception as e:
        logger.warning("Option Gen LLM 调用失败", error=str(e))
        options = []

    # 截断到最多 4 条
    if len(options) > 4:
        options = options[:4]

    # 通过 SSE 队列发送 done 事件（推荐路径的终端节点）
    queue = state.get("_sse_queue")
    if queue:
        await queue.put({"event": "done", "data": {"next_options_count": len(options)}})

    return {"next_options": options}
