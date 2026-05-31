"""MCL-A3: Router 节点测试。

验证 Intent Router 节点的输入输出，使用 mock LLM。
"""
import json
import pytest
from unittest.mock import AsyncMock
from app.agent.nodes.router import router_node


@pytest.mark.asyncio
async def test_router_recommend_explicit():
    """Router 应将明确的商品需求路由为 recommend+explicit。"""
    mock_llm = AsyncMock()
    mock_llm.chat.return_value = json.dumps({
        "intent": "recommend",
        "is_scenario": False,
    })

    state = {
        "user_query": "200元以下的蓝牙耳机",
        "conversation_history": [],
    }
    result = await router_node(state, llm=mock_llm)

    assert result["intent"] == "recommend"
    assert result["is_scenario"] is False


@pytest.mark.asyncio
async def test_router_recommend_scenario():
    """Router 应将场景化需求路由为 recommend+scenario。"""
    mock_llm = AsyncMock()
    mock_llm.chat.return_value = json.dumps({
        "intent": "recommend",
        "is_scenario": True,
    })

    state = {
        "user_query": "去三亚度假需要准备什么",
        "conversation_history": [],
    }
    result = await router_node(state, llm=mock_llm)

    assert result["intent"] == "recommend"
    assert result["is_scenario"] is True


@pytest.mark.asyncio
async def test_router_chat():
    """Router 应将非导购提问路由为 chat。"""
    mock_llm = AsyncMock()
    mock_llm.chat.return_value = json.dumps({
        "intent": "chat",
        "is_scenario": False,
    })

    state = {
        "user_query": "讲个笑话",
        "conversation_history": [],
    }
    result = await router_node(state, llm=mock_llm)

    assert result["intent"] == "chat"


@pytest.mark.asyncio
async def test_router_fallback_on_llm_error():
    """LLM 调用失败时 fallback 为 recommend+explicit。"""
    mock_llm = AsyncMock()
    mock_llm.chat.side_effect = Exception("LLM connection error")

    state = {
        "user_query": "蓝牙耳机",
        "conversation_history": [],
    }
    result = await router_node(state, llm=mock_llm)

    assert result["intent"] == "recommend"
    assert result["is_scenario"] is False


@pytest.mark.asyncio
async def test_router_fallback_on_bad_json():
    """LLM 返回无效 JSON 时 fallback 为 recommend+explicit。"""
    mock_llm = AsyncMock()
    mock_llm.chat.return_value = "这不是有效的 JSON"

    state = {
        "user_query": "蓝牙耳机",
        "conversation_history": [],
    }
    result = await router_node(state, llm=mock_llm)

    assert result["intent"] == "recommend"
    assert result["is_scenario"] is False
