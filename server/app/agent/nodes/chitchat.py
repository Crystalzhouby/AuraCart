"""
Chit-Chat 节点 — 处理非导购相关的闲聊提问。

简短友好回复 + 服务边界声明。不走 Memory 和检索管线。
"""
import structlog
from app.agent.prompts.chitchat_prompt import CHITCHAT_SYSTEM
from app.services.llm import LLMService

logger = structlog.get_logger("agent.chitchat")

FALLBACK_REPLY = "我主要可以帮助您推荐和比较商品，有需要的话随时告诉我！"


async def chitchat_node(state: dict, llm: LLMService) -> dict:
    """Chit-Chat 节点函数。

    参数:
        state: AgentState 字典，读取 user_query。
        llm: LLMService 实例。

    返回值:
        dict: {"chat_reply": str}，写入 AgentState。
    """
    user_query = state.get("user_query", "")

    prompt = CHITCHAT_SYSTEM.format(user_query=user_query)
    messages = [
        {"role": "system", "content": prompt},
        {"role": "user", "content": user_query},
    ]

    try:
        reply = await llm.chat(messages, temperature=0.3)
        if not reply or not reply.strip():
            reply = FALLBACK_REPLY
    except Exception as e:
        logger.warning("ChitChat LLM 调用失败，使用 fallback", error=str(e))
        reply = FALLBACK_REPLY

    return {"chat_reply": reply}
