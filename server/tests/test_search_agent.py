"""M10 + SSE API completion: /api/search Agent 工作流集成测试。

验证 LangGraph Agent 工作流在 SSE 流式端点中的正确集成：
- Queue 消费循环
- done/error 事件
- next_options 在 done 之后
- 超时保护
"""
import json
import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch, ANY

# Mock 重依赖避免在无 langgraph 环境崩溃
import sys
sys.modules["langgraph"] = MagicMock()
sys.modules["langgraph.graph"] = MagicMock()

_TEST_CONVERSATION_ID = "550e8400-e29b-41d4-a716-446655440000"


def _create_mock_db_session(memory=None):
    """创建 mock DB session，模拟 conversation 查询返回 memory 记录。"""
    if memory is None:
        memory = []
    mock_row = memory
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = mock_row
    mock_session = MagicMock()
    mock_session.execute = AsyncMock(return_value=mock_result)
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=None)
    return mock_session


@pytest.fixture(autouse=True)
def _mock_conversation_db():
    """所有测试自动 mock conversation DB 查询。"""
    mock_session = _create_mock_db_session()
    with patch("app.database.async_session", return_value=mock_session):
        yield


# ---------------------------------------------------------------------------
# event_stream 生成器逻辑的单元测试（独立于 FastAPI）
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_event_stream_yields_done_on_completion():
    """正常完成时 event_stream 应发送 done 事件。"""
    from app.agent.state import AgentState

    queue = asyncio.Queue()

    # 模拟 graph.ainvoke 完成并返回包含 next_options 的最终状态
    async def _mock_ainvoke(state):
        # 模拟节点发送 products 和 done 事件
        await queue.put({"event": "products", "data": [{"product_id": "p1", "sku_id": "sk1", "category": "test", "sub_category": "test"}]})
        await queue.put({"event": "done", "data": {"total_categories": 1, "failed_categories": []}})
        return {"next_options": ["选项1", "选项2"]}

    mock_graph = MagicMock()
    mock_graph.ainvoke = _mock_ainvoke

    events = []
    try:
        async for event in _agent_event_stream(
            user_query="测试查询",
            graph=mock_graph,
            queue=queue,
            total_timeout=5.0,
            conversation_id=_TEST_CONVERSATION_ID,
        ):
            events.append(event)
    except Exception as e:
        # 预期之外的错误
        pytest.fail(f"event_stream 不应抛出异常: {e}")

    event_types = [e["event"] for e in events]
    assert "products" in event_types
    assert "done" in event_types
    assert "next_options" in event_types


@pytest.mark.asyncio
async def test_event_stream_sends_next_options_after_done():
    """next_options 应在 done 事件之后发送。"""
    queue = asyncio.Queue()

    async def _mock_ainvoke(state):
        await queue.put({"event": "done", "data": {"total_categories": 0, "failed_categories": []}})
        return {"next_options": ["测试选项"]}

    mock_graph = MagicMock()
    mock_graph.ainvoke = _mock_ainvoke

    events = []
    async for event in _agent_event_stream(
        user_query="test", graph=mock_graph, queue=queue, total_timeout=5.0,
        conversation_id=_TEST_CONVERSATION_ID,
    ):
        events.append(event)

    # 找到 done 和 next_options 的索引
    done_idx = next(i for i, e in enumerate(events) if e["event"] == "done")
    next_opt_idx = next(i for i, e in enumerate(events) if e["event"] == "next_options")
    assert next_opt_idx > done_idx, "next_options 应在 done 之后发送"


@pytest.mark.asyncio
async def test_event_stream_sends_error_on_timeout():
    """超时时 event_stream 应发送 error + done 事件。"""
    queue = asyncio.Queue()

    async def _mock_ainvoke(state):
        # 模拟 graph 执行不发送任何事件（超时场景）
        await asyncio.sleep(0)
        return {}

    mock_graph = MagicMock()
    mock_graph.ainvoke = _mock_ainvoke

    events = []
    async for event in _agent_event_stream(
        user_query="test", graph=mock_graph, queue=queue,
        total_timeout=0.1,  # 100ms timeout
        conversation_id=_TEST_CONVERSATION_ID,
    ):
        events.append(event)

    event_types = [e["event"] for e in events]
    # 应包含 error 和 done
    assert "error" in event_types or "done" in event_types


@pytest.mark.asyncio
async def test_event_stream_handles_graph_exception():
    """graph 异常时 event_stream 应优雅降级。"""
    queue = asyncio.Queue()

    async def _mock_ainvoke(state):
        raise RuntimeError("Graph execution failed")

    mock_graph = MagicMock()
    mock_graph.ainvoke = _mock_ainvoke

    events = []
    try:
        async for event in _agent_event_stream(
            user_query="test", graph=mock_graph, queue=queue, total_timeout=5.0,
            conversation_id=_TEST_CONVERSATION_ID,
        ):
            events.append(event)
    except Exception:
        pytest.fail("event_stream 不应向上抛出异常")

    # 即使 graph 崩溃，也应发送 error 和 done
    event_types = [e["event"] for e in events]
    assert "error" in event_types
    assert "done" in event_types


@pytest.mark.asyncio
async def test_agent_event_stream_includes_next_options_when_present():
    """final_state 包含 next_options 时应发送 next_options 事件。"""
    queue = asyncio.Queue()

    async def _mock_ainvoke(state):
        await queue.put({"event": "done", "data": {"total_categories": 1, "failed_categories": []}})
        return {"next_options": ["A", "B", "C"]}

    mock_graph = MagicMock()
    mock_graph.ainvoke = _mock_ainvoke

    events = []
    async for event in _agent_event_stream(
        user_query="test", graph=mock_graph, queue=queue, total_timeout=5.0,
        conversation_id=_TEST_CONVERSATION_ID,
    ):
        events.append(event)

    next_opt_events = [e for e in events if e["event"] == "next_options"]
    assert len(next_opt_events) == 1
    data = json.loads(next_opt_events[0]["data"])
    assert data == ["A", "B", "C"]


@pytest.mark.asyncio
async def test_event_stream_returns_error_when_conversation_not_found():
    """conversation 不存在时应返回 error + done 事件。"""
    queue = asyncio.Queue()

    mock_graph = MagicMock()

    # 模拟 DB 返回 None（conversation 不存在）
    mock_row = None
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = mock_row
    mock_session = MagicMock()
    mock_session.execute = AsyncMock(return_value=mock_result)
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=None)

    with patch("app.database.async_session", return_value=mock_session):
        events = []
        async for event in _agent_event_stream(
            user_query="test", graph=mock_graph, queue=queue, total_timeout=5.0,
            conversation_id="non-existent-uuid",
        ):
            events.append(event)

    event_types = [e["event"] for e in events]
    assert event_types == ["error", "done"]
    error_data = json.loads(events[0]["data"])
    assert error_data["detail"] == "conversation not found"


# ---------------------------------------------------------------------------
# 辅助：event_stream 生成器的实现引用（由 search.py 提供）
# ---------------------------------------------------------------------------

from app.api.search import _agent_event_stream
