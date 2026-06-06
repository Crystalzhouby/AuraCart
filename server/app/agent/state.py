"""
AgentState 定义 — LangGraph 工作流共享状态的类型结构。

_sse_queue 作为 SSE 事件通道，必须在 TypedDict 中声明，
否则 LangGraph 节点间传递时会将其丢弃。
"""
from typing import TypedDict, Any


class AgentState(TypedDict):
    """LangGraph 多 Agent 工作流的共享状态。

    字段:
        user_query: 当前轮用户原始输入。
        rewritten_query: Router 改写后的用户查询。
        session_memory: 会话记忆 — 按 (category,sub_category) 分组的原始查询列表。
            格式: [{category, sub_category, queries: [{query, timestamp}]}]
        intent: "chat" | "explicit" | "scenario"。
        requirements: 提取后的意图列表。
            格式: [{category, sub_category, text, min_price, max_price, order_num, brand}]。
        scenario_description: 场景原文，仅 Scenario 路径填写。
        retrieval_results: 各品类检索结果（完整 SKU 含 matched_texts）。
        chat_reply: Chit-Chat 输出文本。
        next_options: Option Gen 输出的下一步选项列表。
        failed_categories: 检索失败的品类列表。
        _sse_queue: asyncio.Queue，SSE 事件通道。不参与序列化/持久化。
    """

    user_query: str
    rewritten_query: str
    session_memory: list[dict]
    intent: str
    requirements: list[dict]
    scenario_description: str | None
    retrieval_results: list[dict]
    chat_reply: str
    next_options: list[str]
    failed_categories: list[str]
    _sse_queue: Any
