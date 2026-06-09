"""
Intent Router 节点 — 工作流第一个节点，统一入口。

单次 LLM 完成意图分类 + 回复生成：
- chat: 生成闲聊回复 + SSE 推送 + done 事件 → 直接结束
- explicit/scenario: 生成欢迎语 + SSE 推送 → 继续后续链
"""
import json
import re
from datetime import datetime
import structlog
from app.config import settings
from app.agent.prompts.intent_router_prompt import INTENT_ROUTER_SYSTEM
from app.agent.memory import get_recent_queries, append_query
from app.services.llm_service import LLMService

logger = structlog.get_logger("agent.router")


def _parse_route_response(raw: str) -> dict:
    """从 LLM 原始响应中提取 JSON，失败返回 fallback 默认值。

    增强容错：
    - markdown 代码围栏 (```json ... ```)
    - 尾随逗号（常见 LLM 错误）
    - JSON 前后的说明文字
    """
    if not raw:
        return {"intent": "explicit"}

    # 尝试提取第一个 { ... } JSON 对象
    start = raw.find("{")
    end = raw.rfind("}") + 1
    if start < 0 or end <= start:
        return {"intent": "explicit"}

    json_str = raw[start:end]

    # 1. 直接解析
    try:
        return json.loads(json_str)
    except json.JSONDecodeError:
        pass

    # 2. 移除尾随逗号后重试（常见 LLM 输出错误）
    cleaned = re.sub(r",\s*([}\]])", r"\1", json_str)
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass

    return {"intent": "explicit"}


def _format_recent_queries(recent_queries: list[dict]) -> str:
    """将最近 N 轮原始查询格式化为提示词可用的平铺文本。

    格式: #1 [2026-06-04T10:00:00] 帮我推荐跑鞋
          #2 [2026-06-04T10:01:00] 要轻量的

    参数:
        recent_queries: get_recent_queries() 的返回结果（已按时间降序）。

    返回值:
        str: 格式化后的多行文本。空列表返回 "(无历史记录)"。
    """
    if not recent_queries:
        return "(无历史记录)"

    # 按时间升序展示（最早→最新），便于理解对话发展
    sorted_queries = sorted(recent_queries, key=lambda q: q["timestamp"])
    lines = []
    for i, q in enumerate(sorted_queries, 1):
        lines.append(f"#{i} [{q['timestamp']}] {q['query']}")
    return "\n".join(lines)


async def intent_route_node(state: dict, llm: LLMService, _sse_queue=None) -> dict:
    """Intent Router 节点函数 — 统一入口。

    单次 LLM 调用完成分类 + 回复生成：
    1. 构建 INTENT_ROUTER_SYSTEM prompt（含对话历史）
    2. 流式: stream_json_field 提取 welcome_chat 逐 token 推送
    3. 非流式: 同步 LLM → 解析 JSON → 发送对应事件
    - chat 路径: 发送 done → 直接结束
    - explicit/scenario 路径: 继续后续链

    参数:
        state: AgentState 字典。
        llm: LLMService 实例。
        _sse_queue: 可选，asyncio.Queue，用于 SSE 推送。

    返回值:
        dict: {"intent", "welcome_text"}
    """
    user_query = state.get("user_query", "")
    session_memory = state.get("session_memory", [])
    stream = state.get("stream", True)
    queue = _sse_queue or state.get("_sse_queue")

    # ---- 构建统一 prompt ----
    n_rounds = settings.search.memory_recent_rounds
    recent_queries = get_recent_queries(session_memory, n_rounds)
    history_text = _format_recent_queries(recent_queries)
    prompt = (INTENT_ROUTER_SYSTEM
              .replace("{user_query}", user_query)
              .replace("{recent_queries}", history_text))
    messages = [
        {"role": "system", "content": prompt},
        {"role": "user", "content": user_query},
    ]

    # ---- LLM 调用 + 流式推送 ----
    if stream and queue:
        from app.agent.utils.stream_json import stream_json_field

        try:
            await queue.put({"event": "welcome_chat_stream", "data": {"type": "start"}})

            async def _on_delta(ch: str):
                await queue.put({"event": "welcome_chat_stream", "data": {"type": "delta", "text": ch}})

            token_stream = llm.chat_stream(messages, temperature=0.1)
            _stream_events, parsed = await stream_json_field(token_stream, "welcome_chat", on_delta=_on_delta)

            await queue.put({"event": "welcome_chat_stream", "data": {"type": "end"}})

            intent = parsed.get("intent", "explicit") if parsed else "explicit"
            welcome_chat = parsed.get("welcome_chat", "") if parsed else ""
        except Exception as e:
            logger.warning("Unified Router 流式调用失败", error=str(e))
            intent = "explicit"
            welcome_chat = ""

        if intent == "chat":
            await queue.put({"event": "done", "data": {}})
            new_memory = append_query(
                session_memory, user_query, [],
                timestamp=datetime.now().isoformat(),
            )
            return {"intent": "chat", "welcome_text": "", "chat_reply": welcome_chat, "session_memory": new_memory}

        return {"intent": intent, "welcome_text": welcome_chat}

    else:
        # 非流式路径: 同步 LLM → 解析 JSON
        try:
            raw = await llm.chat(messages, temperature=0.1)
            parsed = _parse_route_response(raw)
            intent = parsed.get("intent", "explicit")
            welcome_chat = parsed.get("welcome_chat", "")
        except Exception as e:
            logger.warning("Unified Router LLM 调用失败", error=str(e))
            intent = "explicit"
            welcome_chat = ""

        if intent == "chat":
            if queue:
                await queue.put({
                    "event": "chat_reply",
                    "data": welcome_chat or "我主要可以帮助您推荐和比较商品，有需要的话随时告诉我！",
                })
                await queue.put({"event": "done", "data": {}})
            new_memory = append_query(
                session_memory, user_query, [],
                timestamp=datetime.now().isoformat(),
            )
            return {"intent": "chat", "welcome_text": "", "chat_reply": welcome_chat, "session_memory": new_memory}

        if queue and welcome_chat:
            await queue.put({"event": "welcome", "data": welcome_chat})

        return {"intent": intent, "welcome_text": welcome_chat}
