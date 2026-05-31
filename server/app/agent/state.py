"""
AgentState 定义 — LangGraph 工作流共享状态的类型结构。

使用 Python TypedDict 定义，通过 Annotated[list, add] 实现
conversation_history 的自动累加。_sse_queue 作为隐藏字段，
不参与 LangGraph State 序列化，仅用于 SSE 事件通道。
"""
from typing import TypedDict, Annotated
from operator import add


class AgentState(TypedDict):
    """LangGraph 多 Agent 工作流的共享状态。

    字段:
        user_query: 当前轮用户原始输入。
        conversation_history: 对话历史，LangGraph add reducer 自动累加。
        intent: "recommend" | "chat"。
        is_scenario: True=场景化需求, False=明确商品需求。
        requirements: {"sub_queries": [...]}，SubQuery 列表的容器。
        scenario_description: 场景原文，仅 Scenario 路径填写。
        products_summary: 各品类检索结果的轻量摘要聚合。
        chat_reply: Chit-Chat 输出文本。
        next_options: Option Gen 输出的下一步选项列表。
        failed_categories: 检索失败的品类列表。

    注意:
        _sse_queue 不在 TypedDict 声明中，通过 state["_sse_queue"] = queue
        在 graph 执行前动态注入。节点通过 state.get("_sse_queue") 获取。
    """

    user_query: str
    conversation_history: Annotated[list[dict], add]
    intent: str
    is_scenario: bool
    requirements: dict
    scenario_description: str | None
    products_summary: list[dict]
    chat_reply: str
    next_options: list[str]
    failed_categories: list[str]
