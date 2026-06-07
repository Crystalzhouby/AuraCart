"""MCL-A1: AgentState TypedDict 测试。

验证:
1. AgentState 各字段的默认值
2. _sse_queue 注入机制
"""
import asyncio
import pytest
from app.agent.state import AgentState


def test_agent_state_default_values():
    """验证 AgentState 各字段的默认值。"""
    state = AgentState(
        user_query="测试查询",

session_memory=[],
        intent="",
        requirements=[],
        retrieval_results=[],
        chat_reply="",
        next_options=[],
        failed_categories=[],
        scenario_description=None,
    )
    assert state["user_query"] == "测试查询"
    assert state["session_memory"] == []
    assert state["intent"] == ""
    assert state["requirements"] == []
    assert state["retrieval_results"] == []
    assert state["chat_reply"] == ""
    assert state["next_options"] == []
    assert state["failed_categories"] == []
    assert state["scenario_description"] is None


def test_agent_state_sse_queue_injection():
    """验证 _sse_queue 可通过属性注入到 AgentState 实例中。"""
    state = AgentState(
        user_query="test",

session_memory=[],
        intent="",
        requirements=[],
        retrieval_results=[],
        chat_reply="",
        next_options=[],
        failed_categories=[],
        scenario_description=None,
    )
    queue = asyncio.Queue()
    state["_sse_queue"] = queue
    assert state["_sse_queue"] is queue


def test_agent_state_sse_queue_in_annotations():
    """_sse_queue 必须在 AgentState 的 __annotations__ 中，确保 LangGraph 节点间传递时保留该字段。"""
    state = AgentState(
        user_query="test",

session_memory=[],
        intent="",
        requirements=[],
        retrieval_results=[],
        chat_reply="",
        next_options=[],
        failed_categories=[],
        scenario_description=None,
    )
    # _sse_queue 必须在 AgentState TypedDict 中，否则 LangGraph 在节点间传递时
    # 会将其丢弃，导致 SSE 事件无法发送到客户端。
    assert "_sse_queue" in AgentState.__annotations__


@pytest.mark.asyncio
async def test_sse_queue_put_get():
    """验证通过 _sse_queue 可进行异步读写。"""
    state = AgentState(
        user_query="test",

session_memory=[],
        intent="",
        requirements=[],
        retrieval_results=[],
        chat_reply="",
        next_options=[],
        failed_categories=[],
        scenario_description=None,
    )
    queue = asyncio.Queue()
    state["_sse_queue"] = queue

    # 写入事件
    await state["_sse_queue"].put({"event": "products", "data": []})
    await state["_sse_queue"].put({"event": "done", "data": {}})

    # 读取事件
    event1 = await state["_sse_queue"].get()
    assert event1["event"] == "products"
    event2 = await state["_sse_queue"].get()
    assert event2["event"] == "done"
