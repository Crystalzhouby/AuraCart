"""MCL-A3: Router 节点测试。

验证 Intent Router 节点的输入输出，使用 mock LLM。
"""
import json
import pytest
from unittest.mock import AsyncMock
from app.agent.nodes.router import router_node, _parse_router_response


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


# ---------------------------------------------------------------------------
# Router completion: enhanced JSON parsing robustness
# ---------------------------------------------------------------------------


def test_parse_router_response_markdown_fence():
    """_parse_router_response 应能处理 markdown 代码围栏包裹的 JSON。"""
    raw = '```json\n{"intent": "recommend", "is_scenario": false}\n```'
    result = _parse_router_response(raw)
    assert result["intent"] == "recommend"
    assert result["is_scenario"] is False


def test_parse_router_response_trailing_comma():
    """_parse_router_response 应能处理 JSON 中的尾随逗号（常见 LLM 错误）。"""
    raw = '{"intent": "recommend", "is_scenario": true,}'
    result = _parse_router_response(raw)
    assert result["intent"] == "recommend"
    assert result["is_scenario"] is True


def test_parse_router_response_text_before_json():
    """_parse_router_response 应能从非 JSON 文本中提取 JSON 对象。"""
    raw = '分析结果如下：用户想要推荐商品。\n{"intent": "recommend", "is_scenario": false}'
    result = _parse_router_response(raw)
    assert result["intent"] == "recommend"
    assert result["is_scenario"] is False


def test_parse_router_response_empty_returns_fallback():
    """_parse_router_response 在空字符串时应返回 fallback。"""
    result = _parse_router_response("")
    assert result == {"intent": "recommend", "is_scenario": False}


def test_parse_router_response_pure_text_returns_fallback():
    """_parse_router_response 在纯文本无 JSON 时应返回 fallback。"""
    result = _parse_router_response("这是纯文本回复，不包含任何 JSON 对象")
    assert result == {"intent": "recommend", "is_scenario": False}


@pytest.mark.asyncio
async def test_router_handles_markdown_fence_response():
    """Router 节点应处理 LLM 返回 markdown 代码围栏包裹的 JSON。"""
    mock_llm = AsyncMock()
    mock_llm.chat.return_value = '```json\n{"intent": "chat", "is_scenario": false}\n```'

    state = {"user_query": "你好", "conversation_history": []}
    result = await router_node(state, llm=mock_llm)

    assert result["intent"] == "chat"
