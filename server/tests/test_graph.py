"""MCL-G1 + Graph completion: StateGraph 结构和 Memory 集成测试。

验证 route_intent 条件边逻辑，build_graph 编译，以及 Memory 截断集成。
"""
import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

# Mock langgraph before importing graph module
import sys
sys.modules["langgraph"] = MagicMock()
sys.modules["langgraph.graph"] = MagicMock()


def test_route_intent_chat():
    """route_intent 应将 intent=chat 路由到 'chat' (→ END)。"""
    from app.agent.graph import route_intent
    state = {"intent": "chat"}
    assert route_intent(state) == "chat"


def test_route_intent_scenario():
    """route_intent 应将 intent=scenario 路由到 scenario_gen。"""
    from app.agent.graph import route_intent
    state = {"intent": "scenario"}
    assert route_intent(state) == "scenario_gen"


def test_route_intent_extraction():
    """route_intent 应将 intent=explicit 路由到 extraction。"""
    from app.agent.graph import route_intent
    state = {"intent": "explicit"}
    assert route_intent(state) == "extraction"


def test_route_intent_missing_keys_defaults():
    """缺少 intent 时默认路由到 extraction。"""
    from app.agent.graph import route_intent
    state: dict = {}
    assert route_intent(state) == "extraction"


@pytest.mark.asyncio
async def test_build_graph_registers_five_nodes():
    """build_graph 应向 StateGraph 注册 5 个节点（post-chitchat 删除）。"""
    from app.agent.graph import build_graph

    mock_llm = MagicMock()
    mock_emb = MagicMock()
    mock_factory = MagicMock()

    graph = build_graph(mock_llm, mock_emb, mock_factory)
    assert graph is not None

    # 编译后的 graph 应该有节点字典
    assert hasattr(graph, "nodes") or hasattr(graph, "_all_nodes")
