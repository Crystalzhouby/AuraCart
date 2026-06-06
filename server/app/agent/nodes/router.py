"""
Intent Router 节点 — 工作流第一个节点。

单次三分类 + 查询改写：
1. 意图分类: chat（闲聊）/ explicit（明确商品需求）/ scenario（场景化推荐）
2. 若为 explicit 或 scenario，利用 session_memory 中最近 N 轮历史改写当前查询，
   补充商品主体。完整查询不做改写（透传）。
"""
import json
import re
import structlog
from app.config import settings
from app.agent.prompts.router_prompt import ROUTER_SYSTEM
from app.agent.prompts.rewrite_prompt import REWRITE_SYSTEM
from app.agent.memory import get_recent_queries
from app.services.llm_service import LLMService

logger = structlog.get_logger("agent.router")


def _parse_router_response(raw: str) -> dict:
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


async def _rewrite_query(
    user_query: str,
    recent_queries: list[dict],
    llm: LLMService,
) -> str:
    """利用历史对话改写当前查询，补充商品主体。

    若当前查询已完整，LLM 根据提示词指示直接返回原查询（透传）。

    参数:
        user_query: 当前用户原始查询。
        recent_queries: 最近 N 轮历史原始查询。
        llm: LLMService 实例。

    返回值:
        str: 改写后的查询（或原查询）。
    """
    history_text = _format_recent_queries(recent_queries)
    prompt = (REWRITE_SYSTEM
              .replace("{recent_queries}", history_text)
              .replace("{user_query}", user_query))

    messages = [
        {"role": "system", "content": prompt},
        {"role": "user", "content": user_query},
    ]

    try:
        raw_response = await llm.chat(messages, temperature=0.1)
        rewritten = raw_response.strip()
        # 去除可能的 markdown 代码围栏或引号
        if rewritten.startswith("```"):
            lines = rewritten.split("\n")
            rewritten = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])
        rewritten = rewritten.strip().strip('"').strip("'")
        logger.info("Router 查询改写完成",
                    original=user_query[:80],
                    rewritten=rewritten[:80])
        return rewritten if rewritten else user_query
    except Exception as e:
        logger.warning("Router 查询改写失败，透传原查询", error=str(e))
        return user_query


async def router_node(state: dict, llm: LLMService) -> dict:
    """Intent Router + 查询改写节点函数。

    流程:
    1. LLM 三分类: chat / explicit / scenario
    2. 若为 explicit 或 scenario: 从 session_memory 取最近 N 轮 → LLM 改写查询

    参数:
        state: AgentState 字典。
        llm: LLMService 实例。

    返回值:
        dict: {"intent", "rewritten_query"}，写入 AgentState。
    """
    user_query = state.get("user_query", "")
    session_memory = state.get("session_memory", [])

    # ---- Step 1: 三分类 ----
    prompt = (ROUTER_SYSTEM
              .replace("{user_query}", user_query))
    messages = [
        {"role": "system", "content": prompt},
        {"role": "user", "content": user_query},
    ]

    try:
        raw_response = await llm.chat(messages, temperature=0.1)
        parsed = _parse_router_response(raw_response)
    except Exception as e:
        logger.warning("Router LLM 调用失败，使用 fallback", error=str(e))
        parsed = {"intent": "explicit"}

    intent = parsed.get("intent", "explicit")

    # ---- Step 2: 查询改写（explicit / scenario 路径） ----
    if intent in ("explicit", "scenario"):
        n_rounds = settings.search.memory_recent_rounds
        recent_queries = get_recent_queries(session_memory, n_rounds)
        rewritten_query = await _rewrite_query(user_query, recent_queries, llm)
    else:
        rewritten_query = user_query

    return {
        "intent": intent,
        "rewritten_query": rewritten_query,
    }
